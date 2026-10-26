"""Export endpoints + worker: inline/job delivery, own-row isolation, and the
job-gated download path.

The download gate matters most here: an export artifact is a per-user
snapshot that may contain initiative-isolated content, so another guild
member must get 404 on the job and its download even though they share the
guild schema.
"""

import hashlib
import io
import json
import struct
import zipfile
import zlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import docx
import pytest
from httpx import AsyncClient, Response
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import delete as sa_delete
from sqlmodel import select

from app.api import deps as api_deps
from app.core.config import settings
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.core.user_display import handle_of
from app.models.platform.guild import Guild, CommunityRole, CommunityStatus
from app.models.platform.guild_image import GuildImage, GuildImageVariant
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.file import FileType
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.tenant.property import PropertyType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.services import storage as storage_module
from app.services.export import worker as export_worker
from app.services.guild_sweeps import Scope, each_guild
from app.services.storage import get_guild_storage
from app.services.tenant import ical_service
from app.testing import create_resource_grant, route_session_to_guild, drain_notices
from app.testing.factories import (
    assign_tag,
    checklist_items,
    create_calendar,
    create_calendar_event,
    create_comment,
    create_counter,
    create_counter_group,
    create_dashboard,
    create_file,
    create_export_job,
    create_guild_plugin,
    create_initiative,
    create_post,
    create_project,
    create_property_definition,
    create_property_value,
    create_queue,
    create_queue_item,
    create_relationship,
    create_tag,
    create_task,
    create_tool_entity,
    create_upload,
    enable_all_tools,
)
from app.services.export import limits as export_limits


# ---------------------------------------------------------------------------
# Asking for an export
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def _export(
    client: AsyncClient,
    a,
    source: str,
    *,
    headers: dict[str, str] | None = None,
    **params: Any,
) -> Response:
    """``GET /exports/<source>`` in the actor's guild, selector as keywords.
    ``headers`` runs the same request as somebody else."""
    return await client.get(
        a.g(f"/exports/{source}"), headers=headers or a.headers, params=params
    )


async def _job(client: AsyncClient, a, job_id: int) -> dict:
    """The job row as its own creator reads it back."""
    resp = await client.get(a.g(f"/exports/jobs/{job_id}"), headers=a.headers)
    assert resp.status_code == 200
    return resp.json()


async def _run_worker() -> None:
    """Render the queued jobs the way the worker does. It re-queries as the
    creator on a read session from the community's cohort, which the standard
    harness points at the test database."""
    await export_worker.process_export_jobs()


async def _download(client: AsyncClient, a, job_id: int) -> Response:
    """The finished artifact — surfacing the job's own error if it never
    rendered."""
    dl = await client.get(a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers)
    assert dl.status_code == 200, (await _job(client, a, job_id)).get("error")
    return dl


async def _rendered_zip(client, a, monkeypatch, role_session, resp) -> zipfile.ZipFile:
    """202 -> worker render -> download; returns the opened zip."""
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    await _run_worker()
    body = await _job(client, a, job_id)
    assert body["status"] == ExportJobStatus.done.value, body.get("error")
    dl = await _download(client, a, job_id)
    assert dl.headers["content-type"] == "application/zip"
    return _zip(dl)


# ---------------------------------------------------------------------------
# Reading an export back: one shape check per format, one text view per format
# ---------------------------------------------------------------------------

# What a format looks like on the wire: the bytes a valid file starts with
# (empty where the format is text) and the substring its content type carries.
_FORMAT_SHAPE = {
    "pdf": (b"%PDF", "application/pdf"),
    "csv": (b"", "text/csv"),
    "xlsx": (b"PK", "spreadsheetml.sheet"),
    "docx": (b"PK", "wordprocessingml.document"),
    "md": (b"", "text/markdown"),
    "json": (b"", "application/json"),
    "ics": (b"BEGIN:VCALENDAR", "text/calendar"),
    "zip": (b"PK", "application/zip"),
}


def _pdf_has(text: str, *needles: str) -> bool:
    """Substring check tolerant of pypdf's naive extraction inserting spaces at
    kerned pairs (Outfit kerns e.g. ``To`` so ``Torches`` extracts as
    ``T orches``). The rendered PDF is correct; only the extraction splits, so
    compare space-insensitively."""
    packed = text.replace(" ", "")
    return all(needle.replace(" ", "") in packed for needle in needles)


def _has(text: str, needle: str, *, packed: bool) -> bool:
    """One needle: space-insensitive against text pulled out of a PDF or docx
    (see :func:`_pdf_has`), literal everywhere else."""
    return _pdf_has(text, needle) if packed else needle in text


def _sheet(resp: Response):
    """The first worksheet of a workbook response."""
    return load_workbook(io.BytesIO(resp.content)).active


def _pdf_pages(resp: Response) -> list[str]:
    """The extracted text of a PDF response, one entry per page."""
    return [page.extract_text() for page in PdfReader(io.BytesIO(resp.content)).pages]


def _as_text(resp: Response, fmt: str) -> str:
    """An export's content as searchable text: extracted pages for a PDF,
    paragraphs for a docx, comma-joined cells for a workbook, the decoded body
    for the text formats. A zip is a container, so it reads as empty — pass
    ``read`` to pull the text out of the entry that carries it."""
    if fmt == "pdf":
        return "\n".join(_pdf_pages(resp))
    if fmt == "docx":
        paragraphs = docx.Document(io.BytesIO(resp.content)).paragraphs
        return "\n".join(p.text for p in paragraphs)
    if fmt == "xlsx":
        return "\n".join(
            ",".join("" if cell.value is None else str(cell.value) for cell in row)
            for row in _sheet(resp).iter_rows()
        )
    return "" if fmt == "zip" else resp.content.decode("utf-8")


def _assert_export(
    resp: Response,
    fmt: str,
    *,
    shape: str | None = None,
    read: Callable[[Response], str] | None = None,
    disposition: tuple[str, ...] = (),
    disposition_absent: tuple[str, ...] = (),
    present: tuple[str, ...] = (),
    absent: tuple[str, ...] = (),
    extra: Callable[[Response, Any], None] | None = None,
    subject: Any = None,
) -> str:
    """One export response, checked the way every export is: it downloads as an
    attachment of its format's content type and magic bytes, its filename says
    what it is, and its text carries what that source renders.

    ``shape`` names the delivered format when it differs from the requested one
    (markdown with assets arrives as a zip), ``read`` pulls the text out of
    that container, and ``extra`` asserts what flat text cannot show — cell
    types, an embedded image, an exact envelope. Returns the text.
    """
    assert resp.status_code == 200, resp.text
    shape = shape or fmt
    magic, content_type = _FORMAT_SHAPE[shape]
    assert resp.content.startswith(magic), shape
    assert content_type in resp.headers["content-type"], resp.headers["content-type"]

    header = resp.headers["content-disposition"]
    assert "attachment" in header
    for needle in disposition:
        assert needle in header, (shape, needle)
    for needle in disposition_absent:
        assert needle not in header, (shape, needle)

    text = read(resp) if read is not None else _as_text(resp, shape)
    packed = shape in ("pdf", "docx")
    for needle in present:
        assert _has(text, needle, packed=packed), (shape, needle)
    for needle in absent:
        assert not _has(text, needle, packed=packed), (shape, needle)
    if extra is not None:
        extra(resp, subject)
    return text


def _zip(resp: Response) -> zipfile.ZipFile:
    """The archive a bundled download delivers."""
    return zipfile.ZipFile(io.BytesIO(resp.content))


def _zip_names(resp: Response) -> list[str]:
    """The entry names of a zip download, sorted."""
    return sorted(_zip(resp).namelist())


def _zip_json(resp: Response) -> list[dict]:
    """Every entry of a zip download parsed as JSON, in entry-name order."""
    archive = _zip(resp)
    return [json.loads(archive.read(name)) for name in sorted(archive.namelist())]


def _png() -> bytes:
    """A 1x1 PNG: a real image for the renderers to stage and embed."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


async def _actor_with_tasks(acting_user, session, count=2):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    for i in range(count):
        await create_task(session, a.project, title=f"Task {i}")
    return a


async def _uploaded_file(
    session,
    a,
    *,
    name: str,
    key: str,
    filename: str,
    payload: bytes | None = None,
    size: int | None = None,
    content_type: str | None = None,
):
    """An uploaded file over a stored blob. ``size`` without ``payload`` gives a
    row that claims bytes nothing has written."""
    content_type = content_type or "application/pdf"
    if payload is not None:
        get_guild_storage(a.guild.id).write(key, payload, content_type=content_type)
    return await create_file(
        session,
        a.initiative,
        a.user,
        name=name,
        file_type=FileType.file,
        file_url=f"/uploads/{a.guild.id}/{key}",
        original_filename=filename,
        file_content_type=content_type,
        file_size=len(payload) if payload is not None else size,
    )


async def _image_file(session, a, *, name: str, key: str):
    """A native file whose body embeds one stored image."""
    return await create_file(
        session,
        a.initiative,
        a.user,
        name=name,
        content={
            "root": {
                "type": "root",
                "children": [
                    {
                        "type": "image",
                        "src": f"/uploads/{a.guild.id}/{key}",
                        "altText": "pic",
                    }
                ],
            }
        },
    )


# ---------------------------------------------------------------------------
# Task exports
# ---------------------------------------------------------------------------

_TASK_COLUMNS = "Task,Assignees,Due,Priority,Status"

_TASK_REPORTS: dict[str, dict[str, Any]] = {
    "pdf": {},
    "csv": {"present": (_TASK_COLUMNS, "Task 0", "Task 1")},
    "xlsx": {"disposition": ('filename="tasks.xlsx"',)},
    "md": {
        "present": ("| Task | Assignees | Due | Priority | Status |",),
        "disposition": ('filename="tasks.md"',),
    },
}


@pytest.mark.parametrize("fmt", list(_TASK_REPORTS))
async def test_task_export_renders_the_task_table_in_every_format(
    client: AsyncClient, acting_user, session, fmt
):
    """The task list downloads as an attachment in each offered format, named
    for the source it came from."""
    a = await _actor_with_tasks(acting_user, session)
    _assert_export(
        await _export(client, a, "tasks", format=fmt), fmt, **_TASK_REPORTS[fmt]
    )


async def test_task_export_checklist_layout_lists_tasks_instead_of_tabling_them(
    client: AsyncClient, acting_user, session
):
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "tasks", format="md", layout="checklist")
    _assert_export(
        resp,
        "md",
        present=("- [ ] Task 0", "- [ ] Task 1"),
        absent=("| Task |",),  # a checklist, not a table
    )


async def test_export_stamp_names_the_exporter_as_the_community_does(
    client: AsyncClient, acting_user, session
):
    a = await _actor_with_tasks(acting_user, session)
    a.membership.display_name = "Ada Lovelace"
    session.add(a.membership)
    await session.commit()
    _assert_export(
        await _export(client, a, "tasks", format="md"),
        "md",
        present=("; by: Ada Lovelace -->",),
    )


async def test_task_export_rejects_a_format_it_does_not_offer(
    client: AsyncClient, acting_user, session
):
    """``docx`` is outside the task export's format Literal, so the HTTP layer
    turns it away before any render."""
    a = await _actor_with_tasks(acting_user, session)
    assert (await _export(client, a, "tasks", format="docx")).status_code == 422


async def test_inline_export_respects_task_filters(
    client: AsyncClient, acting_user, session
):
    """Malformed conditions fail exactly like the list endpoint (same parse
    pipeline), proving the export rides the list's filter engine."""
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "tasks", conditions="not json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUERY_INVALID_CONDITIONS"


async def test_task_export_of_a_selection_carries_only_those_tasks(
    client: AsyncClient, acting_user, session
):
    """Export Selected names its tasks by id, as the list's own filter does."""
    a = await _actor_with_tasks(acting_user, session, count=0)
    picked = await create_task(session, a.project, title="Picked")
    await create_task(session, a.project, title="Left out")
    resp = await _export(
        client,
        a,
        "tasks",
        format="md",
        conditions=json.dumps([{"field": "id", "op": "in_", "value": [picked.id]}]),
    )
    _assert_export(resp, "md", present=("Picked",), absent=("Left out",))


def _grouped_rows(resp: Response) -> list[tuple[str, ...]]:
    """A grouped markdown task table's (group, task) cells, in order."""
    assert resp.status_code == 200, resp.text
    return [
        tuple(cell.strip() for cell in line.strip("|").split("|")[:2])
        for line in resp.text.splitlines()
        if line.startswith("| ") and not line.startswith("| ---")
    ]


async def test_task_export_grouped_by_tag_lists_a_task_under_each_tag(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """Grouped by tag, as the table shows it: a task under every tag it has,
    the tags by name and the untagged last, each group in the list's order."""
    a = await _actor_with_tasks(acting_user, session, count=0)
    both = await create_task(session, a.project, title="Both")
    one = await create_task(session, a.project, title="One")
    await create_task(session, a.project, title="Neither")
    beta = await create_tag(session, a.guild, name="Beta")
    alpha = await create_tag(session, a.guild, name="alpha")
    for task, tag in ((both, beta), (both, alpha), (one, alpha)):
        await assign_tag(session, task, tag)
    await session.commit()

    resp = await _export(client, a, "tasks", format="md", group_by="tag_ids")
    assert _grouped_rows(resp) == [
        ("Tags", "Task"),
        ("alpha", "Both"),
        ("alpha", "One"),
        ("Beta", "Both"),
        ("Untagged", "Neither"),
    ]
    # The groups the view leaves out stay out of its export.
    resp = await _export(
        client,
        a,
        "tasks",
        format="md",
        group_by="tag_ids",
        hidden_groups=[str(alpha.id), ""],
    )
    assert _grouped_rows(resp)[1:] == [("Beta", "Both")]

    # Three tasks are four rows grouped, and the ceiling counts the rows.
    monkeypatch.setattr(export_limits, "EXPORT_MAX_ROWS", 3)
    resp = await _export(client, a, "tasks", format="md", group_by="tag_ids")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_TOO_LARGE"


async def test_task_export_groups_by_each_kind_of_field(
    client: AsyncClient, acting_user, session
):
    """An enum by its own order (priority most urgent first), people through
    the relation that reaches them, the date window by its buckets, and a
    property by its options."""
    a = await _actor_with_tasks(acting_user, session, count=0)
    b = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )
    a.membership.display_name = "Zed"
    b.membership.display_name = "Amy"
    session.add_all([a.membership, b.membership])
    region = await create_property_definition(
        session,
        a.initiative,
        name="Region",
        type=PropertyType.select,
        options=[
            {"value": "north", "label": "North"},
            {"value": "south", "label": "South"},
        ],
    )
    now = datetime.now(timezone.utc)
    late = await create_task(
        session,
        a.project,
        title="Late",
        priority=TaskPriority.low,
        due_date=now - timedelta(days=2),
        assignees=[a.user],
    )
    soon = await create_task(
        session,
        a.project,
        title="Soon",
        priority=TaskPriority.urgent,
        due_date=now + timedelta(days=3),
        assignees=[a.user, b.user],
    )
    await create_property_value(session, late, region, value_text="south")
    await create_property_value(session, soon, region, value_text="north")

    expected = {
        "priority": [("Urgent", "Soon"), ("Low", "Late")],
        "assignee_ids": [("Amy", "Soon"), ("Zed", "Late"), ("Zed", "Soon")],
        "date_group": [("Overdue", "Late"), ("This week", "Soon")],
        f"property:{region.id}": [("North", "Soon"), ("South", "Late")],
    }
    for field, rows in expected.items():
        resp = await _export(client, a, "tasks", format="md", group_by=field)
        assert _grouped_rows(resp)[1:] == rows, field

    # A date by a bucket of the calendar, named by its first day.
    resp = await _export(
        client, a, "tasks", format="md", group_by="due_date", bucket="year"
    )
    assert [group for group, _ in _grouped_rows(resp)[1:]] == [
        str((now - timedelta(days=2)).year),
        str((now + timedelta(days=3)).year),
    ]


async def test_task_export_shows_the_columns_its_view_shows(
    client: AsyncClient, acting_user, session
):
    """The layout fields the view's table shows, in its order, a property by
    its name and value; recurrence, which only the app writes in words, and a
    property the community no longer has are left out; the status comes last,
    as the table draws it."""
    a = await _actor_with_tasks(acting_user, session, count=0)
    effort = await create_property_definition(
        session,
        a.initiative,
        name="Effort",
        type=PropertyType.select,
        options=[{"value": "big", "label": "Big"}],
    )
    task = await create_task(
        session, a.project, title="Map", priority=TaskPriority.high
    )
    await create_property_value(session, task, effort, value_text="big")

    resp = await _export(
        client,
        a,
        "tasks",
        format="md",
        # The longest id a layout can name: an install's field it no longer
        # declares, which is left out rather than refused.
        columns=[
            "priority",
            f"property:{effort.id}",
            "recurrence",
            "property:999",
            f"plugin:9999999999:{'k' * 64}",
        ],
    )
    _assert_export(
        resp,
        "md",
        present=(
            "| Task | Priority | Effort | Status |",
            "| Map | High | Big | To Do |",
        ),
    )


async def test_detailed_task_export_follows_the_task_page(
    client: AsyncClient, acting_user, session
):
    """Each page draws the task page's parts in its order: a property placed
    on the page, then the description with its mentions named."""
    a = await _actor_with_tasks(acting_user, session, count=0)
    a.membership.display_name = "Ada"
    session.add(a.membership)
    effort = await create_property_definition(
        session, a.initiative, name="Effort", type=PropertyType.text
    )
    task = await create_task(
        session,
        a.project,
        title="Map",
        description=f"Pair with @[]({a.user.id})",
    )
    await create_property_value(session, task, effort, value_text="Large")

    resp = await _export(
        client,
        a,
        "tasks",
        format="pdf",
        layout="detailed",
        detail=[f"property:{effort.id}", "description", "status"],
    )
    assert resp.status_code == 200, resp.text
    page = " ".join(_pdf_pages(resp)[0].split())
    assert page.index("Effort: Large") < page.index("Description")
    assert page.index("Description") < page.index("Status:")
    assert "Pair with @Ada" in page and "](" not in page


async def test_project_report_shows_the_columns_its_view_shows(
    client: AsyncClient, acting_user, session
):
    a = await _actor_with_tasks(acting_user, session, count=1)
    resp = await _export(
        client,
        a,
        "project",
        ids=[a.project.id],
        format="csv",
        filters=json.dumps({"tasks": {"columns": ["priority"]}}),
    )
    _assert_export(resp, "csv", present=("Task,Priority,Status", "Task 0,Medium,To Do"))


async def test_detailed_task_export_names_each_task_page_by_its_group(
    client: AsyncClient, acting_user, session
):
    a = await _actor_with_tasks(acting_user, session, count=1)
    resp = await _export(
        client, a, "tasks", format="pdf", layout="detailed", group_by="priority"
    )
    assert resp.status_code == 200, resp.text
    assert "Priority: Medium" in _pdf_pages(resp)[0]


async def test_task_export_refuses_a_field_that_does_not_group(
    client: AsyncClient, acting_user, session
):
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "tasks", format="md", group_by="title")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_INVALID_PARAMS"


async def test_export_max_rows_bound(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(export_limits, "EXPORT_MAX_ROWS", 1)
    a = await _actor_with_tasks(acting_user, session, count=2)
    resp = await _export(client, a, "tasks")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_TOO_LARGE"


async def test_large_export_becomes_job(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "tasks")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == ExportJobStatus.queued.value
    assert body["source"] == "tasks"
    assert body["created_by"] == a.user.id
    # The row persists the SELECTOR only — no artifact_ref field is exposed,
    # and params echo the caller's own filter input.
    assert "artifact_ref" not in body
    assert body["params"]["include_archived"] is False

    # Not rendered yet: download must refuse, not serve a partial artifact.
    dl = await client.get(
        a.g(f"/exports/jobs/{body['id']}/download"), headers=a.headers
    )
    assert dl.status_code == 409
    assert dl.json()["detail"] == "EXPORT_NOT_READY"


async def test_job_limit_per_user(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    monkeypatch.setattr(export_limits, "EXPORT_MAX_ACTIVE_JOBS_PER_USER", 1)
    a = await _actor_with_tasks(acting_user, session)
    assert (await _export(client, a, "tasks")).status_code == 202
    second = await _export(client, a, "tasks")
    assert second.status_code == 429
    assert second.json()["detail"] == "EXPORT_JOB_LIMIT_REACHED"


async def test_jobs_are_own_row_isolated(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """Another member of the SAME guild sees neither the job nor its download
    (RLS hides the row -> 404); a guild admin sees it via the admin leg."""
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "tasks")
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

    assert (await _job(client, a, job_id))["id"] == job_id
    for path in (f"/exports/jobs/{job_id}", f"/exports/jobs/{job_id}/download"):
        denied = await client.get(a.g(path), headers=other.headers)
        assert denied.status_code == 404, path
    assert (
        await client.get(a.g(f"/exports/jobs/{job_id}"), headers=admin.headers)
    ).status_code == 200

    # List views scope the same way.
    assert (await client.get(a.g("/exports/jobs"), headers=other.headers)).json() == []
    assert [
        j["id"]
        for j in (await client.get(a.g("/exports/jobs"), headers=a.headers)).json()
    ] == [job_id]


async def test_an_export_is_served_while_its_initiatives_are_reached(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """The job records the initiatives its artifact holds, and the download
    asks for each one that still exists: a member removed from one is refused,
    and one deleted since the render, purged or in the trash, is skipped."""
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    guild_id, initiative_id, user_id = a.guild.id, a.initiative.id, a.user.id
    job_id = (await _export(client, a, "tasks")).json()["id"]
    await _run_worker()

    await route_session_to_guild(session, guild_id)
    job = await session.get(ExportJob, job_id)
    assert job.initiative_ids == [initiative_id]
    job.initiative_ids = [initiative_id, initiative_id + 1000]
    session.add(job)
    await session.commit()
    await _download(client, a, job_id)

    # Once one of its initiatives keeps its content in, the file is not
    # served, and a new list export holding it is refused.
    initiative = await session.get(Initiative, initiative_id)
    initiative.keep_content_in = True
    session.add(initiative)
    await session.commit()
    dl = await client.get(a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers)
    assert dl.json()["detail"] == "INITIATIVE_CONTENT_KEPT_IN"
    refused_id = (await _export(client, a, "tasks")).json()["id"]
    await _run_worker()
    assert (await _job(client, a, refused_id))["error"] == "INITIATIVE_CONTENT_KEPT_IN"
    initiative.keep_content_in = False
    session.add(initiative)
    await session.commit()

    await session.exec(
        sa_delete(InitiativeMember).where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    await session.commit()
    dl = await client.get(a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers)
    assert dl.status_code == 403
    assert dl.json()["detail"] == "EXPORT_OUT_OF_REACH"

    initiative = await session.get(Initiative, initiative_id)
    initiative.deleted_at = datetime.now(timezone.utc)
    session.add(initiative)
    await session.commit()
    await _download(client, a, job_id)


async def test_worker_renders_job_and_download_succeeds(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """The queued job renders in the default format (pdf), downloads once it is
    ``done``, stays off the media route, and leaves the creator an inbox entry
    pointing at it — the recovery path when they navigated away mid-render."""
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "tasks")
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    await _run_worker()

    body = await _job(client, a, job_id)
    assert body["status"] == ExportJobStatus.done.value, body.get("error")
    assert body["expires_at"] is not None
    _assert_export(await _download(client, a, job_id), "pdf")

    # And the artifact never lands in the uploads table / media route.
    media = await client.get(
        f"/uploads/{a.guild.id}/exports/{job_id}.pdf", headers=a.headers
    )
    assert media.status_code == 404

    await drain_notices()
    rows = await session.exec(
        select(Notification).where(Notification.user_id == a.user.id)
    )
    export_notes = [n for n in rows if n.type == NotificationType.export_ready]
    assert len(export_notes) == 1
    assert export_notes[0].data["export_job_id"] == job_id
    assert export_notes[0].data["community_id"] == a.guild.id


# ---------------------------------------------------------------------------
# Project exports
# ---------------------------------------------------------------------------


async def test_inline_project_export_returns_envelope(
    client: AsyncClient, acting_user, session
):
    """The engine-delivered project backup: same envelope the import endpoint
    consumes, same filename convention as the retired route. An assignee is
    named as the community names them, beside the handle an import matches."""
    a = await _actor_with_tasks(acting_user, session)
    a.membership.display_name = "Ada Lovelace"
    session.add(a.membership)
    await create_task(session, a.project, title="Named", assignees=[a.user])
    resp = await _export(client, a, "project", ids=[a.project.id])
    envelope = json.loads(
        _assert_export(resp, "json", disposition=(".initiative-project.json",))
    )
    assert envelope["schema_version"] >= 1
    assert envelope["project"]["name"] == a.project.name
    tasks = {t["title"]: t for t in envelope["tasks"]}
    assert set(tasks) == {"Task 0", "Task 1", "Named"}
    assert tasks["Named"]["assignee_handles"] == [handle_of(a.user)]
    assert tasks["Named"]["assignee_names"] == ["Ada Lovelace"]


# What each report format carries beyond the task titles all of them render.
_PROJECT_REPORTS: dict[str, tuple[str, ...]] = {
    "pdf": (),
    "csv": ("Task,Assignees,Due,Priority,Status",),
    "xlsx": (),
}


@pytest.mark.parametrize("fmt", list(_PROJECT_REPORTS))
async def test_project_report_formats_render_the_live_tasks_only(
    client: AsyncClient, acting_user, session, fmt
):
    """pdf/csv/xlsx render the project report from the same adapter that
    produces the json backup: the unarchived tasks, under a report filename
    rather than the backup one."""
    a = await _actor_with_tasks(acting_user, session)
    await create_task(
        session, a.project, title="Old news", archived_at=datetime.now(timezone.utc)
    )
    resp = await _export(client, a, "project", ids=[a.project.id], format=fmt)
    _assert_export(
        resp,
        fmt,
        disposition_absent=(".initiative-project",),
        present=("Task 0", "Task 1", *_PROJECT_REPORTS[fmt]),
        absent=("Old news",),  # archived stays backup-only
    )


async def test_an_archived_projects_report_carries_the_tasks_archived_with_it(
    client: AsyncClient, acting_user, session
):
    """Archiving the project stamps its tasks with the project's own time; the
    report shows those, as the project's task list does, and still leaves out
    a task archived on its own beforehand."""
    a = await _actor_with_tasks(acting_user, session)
    await create_task(
        session, a.project, title="Old news", archived_at=datetime.now(timezone.utc)
    )
    archived = await client.post(
        a.g(f"/archive/project/{a.project.id}"), headers=a.headers
    )
    assert archived.status_code == 200

    resp = await _export(client, a, "project", ids=[a.project.id], format="csv")
    _assert_export(
        resp,
        "csv",
        disposition_absent=(".initiative-project",),
        present=("Task 0", "Task 1"),
        absent=("Old news",),
    )


async def test_project_export_job_path_renders_json(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await _export(client, a, "project", ids=[a.project.id])
    assert resp.status_code == 202
    assert resp.json()["source"] == "project"

    await _run_worker()

    dl = await _download(client, a, resp.json()["id"])
    envelope = json.loads(_assert_export(dl, "json"))
    assert envelope["project"]["name"] == a.project.name


# ---------------------------------------------------------------------------
# File exports
# ---------------------------------------------------------------------------

_SHEET_CONTENT = {
    "schema_version": 2,
    "dimensions": {"rows": 2, "cols": 2},
    # "=SUM(...)" is the author's own formula and first-class content;
    # "+not-a-formula" is a plain string that happens to open with a trigger
    # character, and the app exports it as the text it is.
    "cells": {"0:0": "Item", "0:1": "=SUM(B2:B9)", "1:0": "+not-a-formula", "1:1": 42},
    "cellStyles": {"0:0": {"style": {"bold": True, "fill": "#ff0000"}}},
    "columns": {"0": {"width": 140}},
    "rows": {},
    "frozen": {"rows": 1, "cols": 0},
}

# One file per type, holding the payload that type stores.
_FILE_KINDS: dict[str, dict[str, Any]] = {
    "native": {"name": "Notes", "content": {"root": {"children": [], "type": "root"}}},
    "whiteboard": {
        "name": "Board",
        "file_type": FileType.whiteboard,
        "content": {"elements": [{"type": "rectangle"}], "appState": {}, "files": {}},
    },
    "smart_link": {
        "name": "Design doc",
        "file_type": FileType.smart_link,
        "content": {"url": "https://example.com/spec"},
    },
    "spreadsheet": {
        "name": "Budget: Q3",
        "file_type": FileType.spreadsheet,
        "content": _SHEET_CONTENT,
    },
}


async def _file(session, a, kind: str):
    return await create_file(session, a.initiative, a.user, **_FILE_KINDS[kind])


def _file_envelope(resp: Response) -> dict:
    """The generic envelope every file type's json export is wrapped in."""
    envelope = json.loads(resp.content)
    assert envelope["type"] == "initiative-file"
    return envelope


def _native_envelope_carries_the_editor_state(resp: Response, subject: Any) -> None:
    """The raw editor state rides as ``content`` (the editor toolbar's import
    unwraps it)."""
    envelope = _file_envelope(resp)
    assert envelope["file_type"] == "native"
    assert envelope["content"]["root"]["type"] == "root"
    assert envelope["tags"] == [] and envelope["properties"] == []


def _whiteboard_envelope_wraps_a_scene(resp: Response, subject: Any) -> None:
    """Unwrapping ``content`` yields a file any Excalidraw opens."""
    envelope = _file_envelope(resp)
    assert envelope["file_type"] == "whiteboard"
    scene = envelope["content"]
    assert scene["type"] == "excalidraw"
    assert scene["elements"] == [{"type": "rectangle"}]


_TYPE_EXPORTS: dict[str, dict[str, Any]] = {
    "native": {
        "fmt": "json",
        "disposition": (".json",),
        "extra": _native_envelope_carries_the_editor_state,
    },
    "whiteboard": {"fmt": "json", "extra": _whiteboard_envelope_wraps_a_scene},
    "smart_link": {
        "fmt": "md",
        "present": ("# Design doc", "<https://example.com/spec>"),
    },
}


@pytest.mark.parametrize("kind", list(_TYPE_EXPORTS))
async def test_each_file_type_exports_its_own_payload(
    client: AsyncClient, acting_user, session, kind
):
    """Every file type exports in the format that carries its content: the
    generic envelope for editor state and whiteboard scenes, markdown for a
    smart link's URL."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await _file(session, a, kind)
    row = dict(_TYPE_EXPORTS[kind])
    fmt = row.pop("fmt")
    resp = await _export(client, a, "file", ids=[doc.id], format=fmt)
    _assert_export(resp, fmt, subject=doc, **row)


@pytest.mark.parametrize(
    "kind,fmt",
    [
        ("native", "csv"),
        ("whiteboard", "md"),
        ("smart_link", "xlsx"),
        ("smart_link", "pdf"),
    ],
)
async def test_file_export_refuses_a_format_its_type_cannot_render(
    client: AsyncClient, acting_user, session, kind, fmt
):
    """A format outside the type's own set is an immediate 400 — no job row, no
    partial render."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await _file(session, a, kind)
    resp = await _export(client, a, "file", ids=[doc.id], format=fmt)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_INVALID_FORMAT"


async def test_smart_link_exports_the_importable_file_envelope(
    client: AsyncClient, acting_user, session
):
    """Smart links export the generic file envelope (like spreadsheets), so
    an initiative/guild backup can carry them importably — md stays for the
    human-readable form."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    link = await _file(session, a, "smart_link")
    resp = await _export(client, a, "file", ids=[link.id], format="json")
    assert json.loads(_assert_export(resp, "json")) == {
        "type": "initiative-file",
        "schema_version": 1,
        "file_type": "smart_link",
        "name": "Design doc",
        "content": {"url": "https://example.com/spec"},
        "tags": [],
        "properties": [],
        # Where it was taken, so an import can tell whether an id in it still
        # names the same thing.
        "source_instance_url": settings.APP_URL,
        "source_guild_id": a.guild.id,
    }


def _rich_content(guild_id: int) -> dict:
    """A lexical tree with a heading, bold text and a same-guild image."""
    return {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "heading",
                    "tag": "h2",
                    "children": [{"type": "text", "text": "Section", "format": 0}],
                },
                {
                    "type": "paragraph",
                    "children": [{"type": "text", "text": "Hello world", "format": 1}],
                },
                {
                    "type": "image",
                    "src": f"/uploads/{guild_id}/att-1.png",
                    "altText": "pic",
                },
            ],
        }
    }


def _markdown_bundle(resp: Response) -> str:
    """A markdown export that references an image arrives as a zip: the
    markdown itself plus the image under ``assets/``."""
    archive = _zip(resp)
    assert "assets/att-1.png" in archive.namelist()
    md_name = next(n for n in archive.namelist() if n.endswith(".md"))
    return archive.read(md_name).decode("utf-8")


def _docx_embeds_the_image(resp: Response, subject: Any) -> None:
    assert len(docx.Document(io.BytesIO(resp.content)).inline_shapes) == 1


_LEXICAL_RENDERS: dict[str, dict[str, Any]] = {
    "md": {
        "shape": "zip",
        "read": _markdown_bundle,
        "disposition": (".zip",),
        "present": ("# Rich Notes", "**Hello world**", "![pic](assets/att-1.png)"),
    },
    "pdf": {},
    "docx": {"present": ("Hello world",), "extra": _docx_embeds_the_image},
}


@pytest.mark.parametrize("fmt", list(_LEXICAL_RENDERS))
async def test_lexical_file_renders_to_every_prose_format(
    client: AsyncClient, acting_user, session, fmt
):
    """One tree walk feeds md, pdf and docx, and a referenced same-guild image
    rides along — bundled beside the markdown, embedded in the others."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    get_guild_storage(a.guild.id).write("att-1.png", _png(), content_type="image/png")
    doc = await create_file(
        session,
        a.initiative,
        a.user,
        name="Rich Notes",
        content=_rich_content(a.guild.id),
    )
    resp = await _export(client, a, "file", ids=[doc.id], format=fmt)
    _assert_export(resp, fmt, **_LEXICAL_RENDERS[fmt])


async def test_file_export_lexical_md_plain_without_assets(
    client: AsyncClient, acting_user, session
):
    """Nothing to bundle, so the markdown downloads as itself rather than a
    zip."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(
        session,
        a.initiative,
        a.user,
        name="Plain",
        content={
            "root": {
                "type": "root",
                "children": [
                    {
                        "type": "paragraph",
                        "children": [{"type": "text", "text": "no images here"}],
                    }
                ],
            }
        },
    )
    resp = await _export(client, a, "file", ids=[doc.id], format="md")
    _assert_export(resp, "md", present=("no images here",))


def _workbook_keeps_the_grid_typed(resp: Response, subject: Any) -> None:
    """Sheet name, styling, formulas, literal strings, numbers and frozen panes
    each land as themselves."""
    sheet = _sheet(resp)
    assert sheet.title == "Budget Q3"  # forbidden ":" stripped
    assert sheet.cell(row=1, column=1).value == "Item"
    assert sheet.cell(row=1, column=1).font.bold is True
    assert sheet.cell(row=1, column=2).value == "=SUM(B2:B9)"
    assert sheet.cell(row=1, column=2).data_type == "f"  # a live formula
    assert sheet.cell(row=2, column=1).value == "+not-a-formula"
    assert sheet.cell(row=2, column=1).data_type == "s"  # a string, not inferred
    assert sheet.cell(row=2, column=2).value == 42
    assert sheet.cell(row=2, column=2).data_type == "n"  # numbers stay typed
    assert sheet.freeze_panes == "A2"


def _envelope_round_trips_the_snapshot(resp: Response, subject: Any) -> None:
    """json is the canonical snapshot: cells, styles, frozen panes and
    schema_version come back verbatim inside the importable envelope."""
    envelope = _file_envelope(resp)
    assert envelope["file_type"] == "spreadsheet"
    assert envelope["name"] == "Budget: Q3"
    assert envelope["content"] == subject.content


_SHEET_RENDERS: dict[str, dict[str, Any]] = {
    "csv": {
        "present": (
            "Item,=SUM(B2:B9)",  # own formulas survive
            "'+not-a-formula",  # a plain string stays a string
        )
    },
    "xlsx": {"extra": _workbook_keeps_the_grid_typed},
    "json": {"extra": _envelope_round_trips_the_snapshot},
}


@pytest.mark.parametrize("fmt", list(_SHEET_RENDERS))
async def test_spreadsheet_file_renders_to_every_grid_format(
    client: AsyncClient, acting_user, session, fmt
):
    """A spreadsheet exports as flat text, as a live workbook, and as the
    snapshot an import reads back."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await _file(session, a, "spreadsheet")
    resp = await _export(client, a, "file", ids=[doc.id], format=fmt)
    _assert_export(resp, fmt, subject=doc, **_SHEET_RENDERS[fmt])


async def test_file_export_spreadsheet_survives_corrupt_snapshot(
    client: AsyncClient, acting_user, session
):
    """One bad snapshot entry is skipped rather than failing the render:
    malformed cell keys are dropped, and 3-char / garbage hex colors are
    expanded / ignored."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(
        session,
        a.initiative,
        a.user,
        name="Odd",
        file_type=FileType.spreadsheet,
        content={
            "schema_version": 2,
            "dimensions": {"rows": 1, "cols": 1},
            "cells": {"0:0": "ok", "corrupt": "x", "1:2:3": "y", ":": "z"},
            "cellStyles": {"0:0": {"style": {"fill": "#fff", "color": "not-a-color"}}},
        },
    )
    resp = await _export(client, a, "file", ids=[doc.id], format="xlsx")
    _assert_export(resp, "xlsx")
    sheet = _sheet(resp)
    assert sheet.cell(row=1, column=1).value == "ok"
    # #fff shorthand expanded to a valid ARGB white fill.
    assert sheet.cell(row=1, column=1).fill.start_color.rgb == "FFFFFFFF"


async def test_file_export_file_passthrough(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Uploaded files export the stored blob unconverted under the original
    name — inline and through the job path (job-id-prefixed artifact key)."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    payload = b"%PDF-original-bytes"
    file_doc = await _uploaded_file(
        session,
        a,
        name="Uploaded report",
        key="stored-abc123.pdf",
        filename="Q3 Report Final.pdf",
        payload=payload,
        content_type="application/pdf",
    )

    resp = await _export(client, a, "file", ids=[file_doc.id], format="file")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"] == "application/pdf"
    # Spaces force the RFC 5987 form — the original name survives, escaped.
    assert "Q3%20Report%20Final.pdf" in resp.headers["content-disposition"]

    # Job path: the original filename survives via the job-id-prefixed key.
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", -1)
    queued = await _export(client, a, "file", ids=[file_doc.id], format="file")
    assert queued.status_code == 202
    job_id = queued.json()["id"]

    await _run_worker()

    dl = await _download(client, a, job_id)
    assert dl.content == payload
    assert "Q3%20Report%20Final.pdf" in dl.headers["content-disposition"]
    # The stored object carries the job id in its basename, so it can't
    # collide with another job exporting a same-named file (both backends
    # flatten a key to its basename, dropping any directory).
    job = await session.get(ExportJob, job_id)
    assert job.artifact_ref == f"exports/{job_id}-Q3 Report Final.pdf"


async def test_passthrough_exports_do_not_collide_by_filename(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Two members exporting a same-named file each get their own artifact: the
    job id is in the storage basename (the directory a nested key would add is
    stripped by both backends), so the refs stay distinct."""
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", -1)
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async def queue_export(blob_key, blob_bytes):
        doc = await _uploaded_file(
            session,
            a,
            name="report",
            key=blob_key,
            filename="report.pdf",  # SAME name for both
            payload=blob_bytes,
            content_type="application/pdf",
        )
        resp = await _export(client, a, "file", ids=[doc.id], format="file")
        assert resp.status_code == 202
        return resp.json()["id"]

    job_a = await queue_export("src-a.pdf", b"AAAA-first-member")
    job_b = await queue_export("src-b.pdf", b"BBBB-second-member")

    await _run_worker()

    row_a = await session.get(ExportJob, job_a)
    row_b = await session.get(ExportJob, job_b)
    assert row_a.artifact_ref != row_b.artifact_ref

    dl_a = await _download(client, a, job_a)
    dl_b = await _download(client, a, job_b)
    assert dl_a.content == b"AAAA-first-member"  # not overwritten by job_b
    assert dl_b.content == b"BBBB-second-member"


async def test_file_envelope_carries_tags_and_properties(
    client: AsyncClient, acting_user, session
):
    """Backups must not shed metadata: the file envelope includes tags by
    name and custom properties in the shared flat encoding."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await _file(session, a, "native")
    tag = await create_tag(session, a.guild, name="worldbuilding")
    await assign_tag(session, doc, tag)
    await session.commit()
    definition = await create_property_definition(session, a.initiative, name="Status")
    await create_property_value(session, doc, definition, value_text="Draft")

    resp = await _export(client, a, "file", ids=[doc.id], format="json")
    envelope = json.loads(_assert_export(resp, "json"))
    assert envelope["tags"] == ["worldbuilding"]
    assert envelope["properties"] == [
        {"property_name": "Status", "property_type": "text", "value_text": "Draft"}
    ]


# ---------------------------------------------------------------------------
# Artifact lifecycle (GC)
# ---------------------------------------------------------------------------


class _BrokenStorage:
    def delete(self, key: str) -> bool:
        raise RuntimeError("storage down")


@pytest.mark.parametrize("storage_fails", [False, True], ids=["deletes", "raises"])
async def test_gc_expires_the_job_row_and_releases_its_artifact(
    acting_user, session, monkeypatch, storage_fails
):
    """Past its expiry, GC drops the artifact and moves the row to ``expired``
    with no artifact_ref, in a community that is not active as in any other.
    A storage backend that raises on delete reaches the same row state, with
    the failure logged, so the pass still completes."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    storage = get_guild_storage(a.guild.id)
    key = "exports/424242.pdf"
    storage.write(key, b"%PDF-fake", content_type="application/pdf")
    job = await create_export_job(
        session,
        a.guild,
        a.user,
        status=ExportJobStatus.done,
        artifact_ref=key,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    guild = await session.get(Guild, a.guild.id)
    guild.status = CommunityStatus.suspended.value
    session.add(guild)
    await session.commit()

    if storage_fails:
        monkeypatch.setattr(
            storage_module, "get_guild_storage", lambda gid: _BrokenStorage()
        )

    await each_guild([(Scope.PROVISIONED, export_worker.expire_artifacts)], name="t")

    if not storage_fails:
        assert storage.open_readable(key) is None

    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    refreshed = await session.get(ExportJob, job.id)
    assert refreshed.status == ExportJobStatus.expired.value
    assert refreshed.artifact_ref is None


async def test_an_artifact_past_its_expiry_is_not_served(
    client: AsyncClient, acting_user, session
):
    """Past ``expires_at`` a finished export is refused with 410 and reads as
    ``expired`` — before GC has swept it as well as after. So is one rendered
    before the job recorded the initiatives it holds."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    storage = get_guild_storage(a.guild.id)
    key = "exports/515151.pdf"
    storage.write(key, b"%PDF-fake", content_type="application/pdf")
    now = datetime.now(timezone.utc)
    due = await create_export_job(
        session,
        a.guild,
        a.user,
        status=ExportJobStatus.done,
        artifact_ref=key,
        expires_at=now - timedelta(minutes=1),
    )
    swept = await create_export_job(
        session,
        a.guild,
        a.user,
        status=ExportJobStatus.expired,
        expires_at=now - timedelta(days=1),
    )
    unrecorded = await create_export_job(
        session,
        a.guild,
        a.user,
        status=ExportJobStatus.done,
        artifact_ref=key,
        expires_at=now + timedelta(days=1),
    )

    for job in (due, swept, unrecorded):
        dl = await client.get(
            a.g(f"/exports/jobs/{job.id}/download"), headers=a.headers
        )
        assert dl.status_code == 410, job.status
        assert dl.json()["detail"] == "EXPORT_EXPIRED"
    for job in (due, swept):
        assert (await _job(client, a, job.id))["status"] == (
            ExportJobStatus.expired.value
        )


# ---------------------------------------------------------------------------
# Queue exports
# ---------------------------------------------------------------------------


async def _queue_with_items(acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    queue = await create_queue(
        session,
        a.initiative,
        a.user,
        name="Battle Order",
        description="Round tracker",
        is_active=True,
        current_round=3,
    )
    # Rotation order is position DESCENDING: Alice acts first.
    current = await create_queue_item(session, queue, label="Alice", position=30)
    await create_queue_item(
        session, queue, label="Bob", position=20, held_at_round=2, notes="waiting"
    )
    lurker = await create_queue_item(
        session, queue, label="Lurker", position=10, is_visible=False
    )
    tag = await create_tag(session, a.guild, name="npc")
    await assign_tag(session, lurker, tag)
    doc = await create_file(session, a.initiative, a.user, name="Dungeon map")
    task = await create_task(session, a.project, title="Prep loot")
    for target in (
        (SearchEntityType.file, doc.id),
        (SearchEntityType.task, task.id),
    ):
        await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.queue_item, current.id),
            target=target,
        )
    queue.current_item_id = current.id
    session.add(queue)
    await session.commit()
    return a, queue


async def test_queue_export_json_envelope(client: AsyncClient, acting_user, session):
    a, queue = await _queue_with_items(acting_user, session)
    resp = await _export(client, a, "queue", ids=[queue.id], format="json")
    envelope = json.loads(
        _assert_export(resp, "json", disposition=(".initiative-queue.json",))
    )
    assert envelope["type"] == "initiative-queue"
    assert envelope["schema_version"] == 1
    assert envelope["name"] == "Battle Order"
    assert envelope["is_active"] is True
    assert envelope["current_round"] == 3

    items = envelope["items"]
    assert [i["label"] for i in items] == ["Alice", "Bob", "Lurker"]  # rotation order
    assert [i["is_current"] for i in items] == [True, False, False]
    assert items[1]["held_at_round"] == 2
    assert items[2]["is_visible"] is False
    assert items[2]["tags"] == ["npc"]
    # Guild-local references ride along as display text only (an import can't
    # rebind them): member name, linked file/task titles — never raw ids.
    assert "member" in items[0] and "user_id" not in items[0]
    assert items[0]["files"] == ["Dungeon map"]
    assert items[0]["tasks"] == ["Prep loot"]
    assert items[1]["files"] == [] and items[1]["tasks"] == []


async def test_a_queue_envelope_records_the_initiatives_of_its_attachments(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """A queue's envelope names what is attached to its items, so the job
    records the initiative of an attached file beside the queue's own. A
    report names only the queue's own fields, and records only its own."""
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a, queue = await _queue_with_items(acting_user, session)
    second = await create_initiative(session, a.guild, a.user, name="Second Front")
    doc = await create_file(session, second, a.user, name="Far map")
    await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.queue_item, queue.current_item_id),
        target=(SearchEntityType.file, doc.id),
    )
    guild_id, own, other = a.guild.id, a.initiative.id, second.id
    jobs = {}
    for fmt in ("json", "csv"):
        resp = await _export(client, a, "queue", ids=[queue.id], format=fmt)
        jobs[fmt] = resp.json()["id"]
        await _run_worker()

    await route_session_to_guild(session, guild_id)
    recorded = {
        fmt: (await session.get(ExportJob, job_id)).initiative_ids
        for fmt, job_id in jobs.items()
    }
    assert recorded == {"json": sorted([own, other]), "csv": [own]}


_QUEUE_REPORTS: dict[str, dict[str, Any]] = {
    "csv": {
        "present": (
            "#,Item,Member,Tags,Notes,Status",
            "1,Alice,,,,Current",
            "2,Bob,,,waiting,Held",
            "3,Lurker,,npc,,Hidden",
        )
    },
    "md": {
        "present": (
            "# Battle Order",
            "1. **Alice** (Current)",  # numbered turn order, current bolded
            "2. Bob (waiting · Held)",
            "3. Lurker (npc · Hidden)",
        ),
        "absent": ("| Item |",),  # a list, not a table
    },
    "pdf": {"present": ("Battle Order", "Alice", "Lurker", "Round tracker")},
}


@pytest.mark.parametrize("fmt", list(_QUEUE_REPORTS))
async def test_queue_report_formats_render_the_rotation(
    client: AsyncClient, acting_user, session, fmt
):
    """The queue report carries the whole rotation in turn order — held, hidden
    and current items, and the description block — in every format it offers."""
    a, queue = await _queue_with_items(acting_user, session)
    resp = await _export(client, a, "queue", ids=[queue.id], format=fmt)
    _assert_export(resp, fmt, **_QUEUE_REPORTS[fmt])


# ---------------------------------------------------------------------------
# Counter-group exports
# ---------------------------------------------------------------------------


async def _counter_group_with_counters(acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    group = await create_counter_group(
        session, a.initiative, a.user, name="Party Resources", description="Session 12"
    )
    await create_counter(
        session,
        group,
        name="Torches",
        count=Decimal("5.0000000000"),
        min=Decimal("0"),
        max=Decimal("10"),
        position=Decimal("1"),
    )
    await create_counter(
        session,
        group,
        name="Rations",
        count=Decimal("2.5"),
        step=Decimal("0.5"),
        position=Decimal("2"),
    )
    return a, group


async def test_counter_group_export_json_envelope(
    client: AsyncClient, acting_user, session
):
    a, group = await _counter_group_with_counters(acting_user, session)
    resp = await _export(client, a, "counter_group", ids=[group.id], format="json")
    envelope = json.loads(
        _assert_export(resp, "json", disposition=(".initiative-counter-group.json",))
    )
    assert envelope["type"] == "initiative-counter-group"
    assert envelope["schema_version"] == 1
    assert envelope["name"] == "Party Resources"

    by_name = {c["name"]: c for c in envelope["counters"]}
    # NUMERIC(20,10) scale must not leak: integral Decimals become plain ints.
    assert by_name["Torches"]["count"] == 5
    assert isinstance(by_name["Torches"]["count"], int)
    assert by_name["Torches"]["min"] == 0 and by_name["Torches"]["max"] == 10
    assert by_name["Rations"]["count"] == 2.5
    assert by_name["Rations"]["step"] == 0.5
    assert by_name["Rations"]["min"] is None
    assert by_name["Torches"]["view_mode"] == "number"


def _workbook_keeps_counts_numeric(resp: Response, subject: Any) -> None:
    sheet = _sheet(resp)
    assert [c.value for c in sheet[1]] == ["Counter", "Count", "Min", "Max", "Step"]
    assert sheet.cell(row=2, column=2).value == 5
    assert sheet.cell(row=2, column=2).data_type == "n"  # counts stay numeric
    assert sheet.cell(row=3, column=2).value == 2.5


_COUNTER_REPORTS: dict[str, dict[str, Any]] = {
    "csv": {
        "present": (
            "Counter,Count,Min,Max,Step",
            "Torches,5,0,10,1",
            "Rations,2.5,,,0.5",  # unbounded min/max stay empty
        )
    },
    "xlsx": {"extra": _workbook_keeps_counts_numeric},
    "pdf": {"present": ("Party Resources", "Torches", "Rations")},
}


@pytest.mark.parametrize("fmt", list(_COUNTER_REPORTS))
async def test_counter_group_report_formats_render_every_counter(
    client: AsyncClient, acting_user, session, fmt
):
    """The counter report lists every counter with its bounds in each format it
    offers."""
    a, group = await _counter_group_with_counters(acting_user, session)
    resp = await _export(client, a, "counter_group", ids=[group.id], format=fmt)
    _assert_export(resp, fmt, **_COUNTER_REPORTS[fmt])


# ---------------------------------------------------------------------------
# The initiative gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", list(Tool), ids=lambda tool: tool.value)
async def test_export_of_content_outside_the_callers_initiative_is_not_found(
    client: AsyncClient, acting_user, session, tool
):
    """The initiative gate, source by source: a member of the same guild who is
    not in the initiative gets 404 (RLS hides the row), exactly like the rest
    of the initiative boundary. Every tool, from the registry."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await enable_all_tools(session, a.initiative)
    entity = await create_tool_entity(session, tool, a.initiative, a.user)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    resp = await _export(
        client,
        a,
        tool.value,
        headers=outsider.headers,
        ids=[entity.id],
        format="json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Who may export a tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", list(Tool), ids=lambda tool: tool.value)
async def test_exporting_a_tool_takes_the_rung_that_may_delete_it(
    client: AsyncClient, acting_user, session, tool
):
    """An export hands the whole thing over, so it is for whoever may delete
    it: its owner, and anyone with full access to it — the community's admin,
    an initiative role that overrides sharing. Somebody it is shared with to
    edit may read and change it, and still may not take a copy away. Every
    tool, from the registry."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await enable_all_tools(session, a.initiative)
    entity = await create_tool_entity(session, tool, a.initiative, a.user)
    editor = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, entity, user=editor.user, level=ResourceAccessLevel.write
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    source = tool.value
    params = {"ids": [entity.id], "format": "json"}

    refused = await _export(client, a, source, headers=editor.headers, **params)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "EXPORT_OWNER_REQUIRED"
    for who in (a, admin):
        resp = await _export(client, a, source, headers=who.headers, **params)
        assert resp.status_code == 200, (who.user.id, resp.text)

    # An initiative that keeps its content in exports nothing on its own, for
    # anyone; its backup still takes it.
    kept = await client.patch(
        a.g(f"/initiatives/{a.initiative.id}"),
        headers=a.headers,
        json={"keep_content_in": True},
    )
    assert kept.json()["keep_content_in"] is True, kept.text
    read = await client.get(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )
    assert read.json()["can"]["export"] is False
    for who in (a, admin):
        resp = await _export(client, a, source, headers=who.headers, **params)
        assert resp.json()["detail"] == "INITIATIVE_CONTENT_KEPT_IN", resp.text
    backup = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    await _run_worker()
    done = await _job(client, a, backup.json()["id"])
    assert done["status"] == ExportJobStatus.done.value, done.get("error")


def _page_body(text: str) -> dict:
    return {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "paragraph",
                    "children": [{"type": "text", "text": text, "format": 0}],
                }
            ],
        }
    }


async def _wiki_with_filed_files(session, a, acting_user):
    """A wiki whose pages nest, one draft, and four files filed in it: a
    text document, a spreadsheet and an upload the exporter owns — the upload
    filed under the first page — and one they can only read."""
    from app.testing.factories import create_wiki, create_wiki_page

    await enable_all_tools(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user, name="Handbook")
    # Written child-first: the export must still put the parent above it.
    parent = await create_wiki_page(
        session, wiki, a.user, title="Rules", content=_page_body("Be kind"), position=0
    )
    await create_wiki_page(
        session,
        wiki,
        a.user,
        title="Combat",
        content=_page_body("Roll initiative"),
        parent_page_id=parent.id,
        position=0,
    )
    await create_wiki_page(
        session,
        wiki,
        a.user,
        title="Secret plans",
        content=_page_body("Not yet"),
        is_draft=True,
        position=1,
    )
    notes = await create_file(
        session, a.initiative, a.user, name="Session notes", content=_page_body("Hi")
    )
    sheet = await create_file(
        session,
        a.initiative,
        a.user,
        name="Loot",
        file_type=FileType.spreadsheet,
        content={},
    )
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    theirs = await create_file(
        session, a.initiative, other.user, name="Their map", content=_page_body("x")
    )
    await create_resource_grant(session, theirs, user=a.user)
    handout = await _uploaded_file(
        session,
        a,
        name="Handout",
        key="handout-key.pdf",
        filename="handout.pdf",
        payload=MINIMAL_PDF,
        content_type="application/pdf",
    )
    for file in (notes, sheet, theirs, handout):
        await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.file, file.id),
            target=(SearchEntityType.wiki, wiki.id),
            relationship_type=RelationshipType.part_of,
        )
    from app.models.tenant.wiki import Wiki
    from app.services.tenant.wikis import place_file

    await route_session_to_guild(session, a.guild.id)
    row = await session.get(Wiki, wiki.id)
    place_file(row, handout.id, parent_page_id=parent.id, position=3)
    session.add(row)
    await session.commit()
    return wiki


#: The smallest file a file upload is recognised as a PDF from.
MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


async def test_a_wiki_exports_as_one_document_with_its_filed_files(
    client: AsyncClient, acting_user, session
):
    """A wiki reads as one document — each published page under a heading at
    its depth, parents before children, drafts left out — and the files
    filed in it that the exporter could export on their own ride beside it
    under ``files/``, in the format their type allows."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    wiki = await _wiki_with_filed_files(session, a, acting_user)

    resp = await _export(client, a, "wiki", ids=[wiki.id], format="md")
    assert resp.status_code == 200, resp.text
    archive = _zip(resp)
    names = sorted(archive.namelist())
    [page_file] = [n for n in names if not n.startswith("files/")]
    text = archive.read(page_file).decode()
    assert text.index("# Rules") < text.index("Be kind") < text.index("## Combat")
    assert "Roll initiative" in text
    assert "Secret plans" not in text
    filed = [n for n in names if n.startswith("files/")]
    assert any(n.startswith("files/session_notes") and n.endswith(".md") for n in filed)
    assert any(n.startswith("files/loot") and n.endswith(".xlsx") for n in filed)
    assert "files/handout.pdf" in filed
    assert not any("their_map" in n for n in filed)

    # Each page starts a page of its own: two published pages, one break.
    docx_zip = _zip(await _export(client, a, "wiki", ids=[wiki.id], format="docx"))
    [wiki_docx] = [
        n for n in docx_zip.namelist() if n.endswith(".docx") and "/" not in n
    ]
    with zipfile.ZipFile(io.BytesIO(docx_zip.read(wiki_docx))) as package:
        body = package.read("word/document.xml").decode()
    assert body.count('w:type="page"') == 1

    pdf_zip = _zip(await _export(client, a, "wiki", ids=[wiki.id], format="pdf"))
    [wiki_pdf] = [n for n in pdf_zip.namelist() if n.endswith(".pdf") and "/" not in n]
    pages = PdfReader(io.BytesIO(pdf_zip.read(wiki_pdf))).pages
    assert len(pages) >= 2
    assert "Combat" not in pages[0].extract_text()


async def test_a_wikis_importable_file_carries_its_filed_files(
    client: AsyncClient, acting_user, session
):
    """The importable file carries the filed files inside the wiki's
    envelope, each with where it is filed, and an upload's bytes beside it
    under ``assets/``."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    wiki = await _wiki_with_filed_files(session, a, acting_user)

    resp = await _export(client, a, "wiki", ids=[wiki.id], format="json")
    assert resp.status_code == 200, resp.text
    archive = _zip(resp)
    assert "assets/handout-key.pdf" in archive.namelist()
    [envelope_name] = [n for n in archive.namelist() if n.endswith(".json")]
    envelope = json.loads(archive.read(envelope_name))
    by_name = {
        (entry.get("envelope") or entry.get("upload"))["name"]: entry
        for entry in envelope["files"]
    }
    assert set(by_name) == {"Session notes", "Loot", "Handout"}
    assert by_name["Handout"]["page"] == "rules"
    assert by_name["Handout"]["upload"]["storage_key"] == "handout-key.pdf"
    assert by_name["Session notes"]["envelope"]["type"] == "initiative-file"


async def test_a_gallery_exports_as_a_zip_of_its_envelope_and_pictures(
    client: AsyncClient, acting_user, session
):
    """A gallery's envelope names its pictures by storage key, so the download
    carries the pictures beside it under ``assets/``. One whose file is gone is
    still listed and left out of the zip, which is what an import expects."""
    from app.testing.factories import create_gallery, create_gallery_image
    from app.services.storage import get_guild_storage

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await enable_all_tools(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user, name="Barovia maps")
    kept = await create_gallery_image(session, gallery, a.user, title="Village")
    gone = await create_gallery_image(
        session, gallery, a.user, title="Castle", write_blob=False
    )
    kept_key = kept.current_version.file_url.rsplit("/", 1)[-1]
    gone_key = gone.current_version.file_url.rsplit("/", 1)[-1]

    resp = await _export(client, a, "gallery", ids=[gallery.id], format="json")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    archive = _zip(resp)
    [envelope_name] = [n for n in archive.namelist() if n.endswith(".json")]
    assert envelope_name.endswith(".initiative-gallery.json")
    envelope = json.loads(archive.read(envelope_name))
    assert {image["storage_key"] for image in envelope["images"]} == {
        kept_key,
        gone_key,
    }
    assert sorted(archive.namelist()) == sorted([envelope_name, f"assets/{kept_key}"])
    stored = get_guild_storage(a.guild.id).open_readable(kept_key)
    assert stored is not None and stored.path is not None
    assert archive.read(f"assets/{kept_key}") == stored.path.read_bytes()


# ---------------------------------------------------------------------------
# Report chrome: locale, branding, detailed layout
# ---------------------------------------------------------------------------


async def _set_locale(session, user, locale):
    """Persist a locale on the creator so the request (and the worker replay)
    re-load it — the export content localizes to the creator, not the
    request's Accept-Language."""
    db_user = await session.get(type(user), user.id)
    db_user.locale = locale
    session.add(db_user)
    await session.commit()


async def test_task_export_localizes_report_content(
    client: AsyncClient, acting_user, session
):
    """The generated report chrome (column headers, title, summary line)
    localizes to the creator's locale — not just the surrounding UI."""
    a = await _actor_with_tasks(acting_user, session, count=1)
    await _set_locale(session, a.user, "es")

    # Spanish headers, not "Task,Assignees,...".
    _assert_export(
        await _export(client, a, "tasks", format="csv"),
        "csv",
        present=("Tarea,Asignados,Vence,Prioridad,Estado",),
    )
    _assert_export(
        await _export(client, a, "tasks", format="md"),
        "md",
        present=(
            "# Tareas",  # localized title
            "\n1 tarea\n",  # localized, singular plural form
        ),
    )


async def test_queue_export_localizes_status_flags_and_headers(
    client: AsyncClient, acting_user, session
):
    """Queue report status flags (Current/Held/Hidden) and headers localize —
    the JSON envelope stays canonical (importable machine data)."""
    a, queue = await _queue_with_items(acting_user, session)
    await _set_locale(session, a.user, "fr")

    _assert_export(
        await _export(client, a, "queue", ids=[queue.id], format="csv"),
        "csv",
        present=(
            "N°,Élément,Membre,Étiquettes,Notes,Statut",  # French headers
            "Actuel",
            "En attente",
            "Masqué",  # status flags
        ),
    )

    # The importable envelope must NOT be localized — kind and field keys stay
    # canonical so a French user's backup still imports.
    json_resp = await _export(client, a, "queue", ids=[queue.id], format="json")
    envelope = json.loads(json_resp.content)
    assert envelope["type"] == "initiative-queue"
    assert "items" in envelope and "is_current" in envelope["items"][0]


async def test_task_detailed_pdf_is_one_page_per_task_with_full_detail(
    client: AsyncClient, acting_user, session
):
    """layout=detailed renders a one-task-per-page PDF carrying each task's
    description, checklist and comments — not the tabular line-per-task list."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    t1 = await create_task(
        session,
        a.project,
        title="Boss fight",
        # Markdown, as the app treats descriptions: formatting must RENDER
        # (no literal ** in the PDF), paragraphs stay separate.
        description="Balance the **encounter**.\n\n- Check the second phase"
        "\n\n* [x] Scout the arena",
        checklist=[
            *checklist_items("Tune the HP", done=True),
            *checklist_items("Write the dialogue"),
        ],
    )
    root = await create_comment(
        session, a.user, task=t1, content="Started **already**."
    )
    # A reply must render nested under its parent, not appended chronologically
    # — even though it was created after the later root comment below.
    await create_task(session, a.project, title="Loot table")
    later_root = await create_comment(
        session, a.user, task=t1, content="Separate thread here."
    )
    await create_comment(
        session,
        a.user,
        task=t1,
        content="Replying to the first.",
        parent_comment_id=root.id,
    )
    # An empty-content comment must not abort the compile.
    await create_comment(session, a.user, task=t1, content="")
    assert later_root.id

    resp = await _export(client, a, "tasks", format="pdf", layout="detailed")
    text = _assert_export(
        resp,
        "pdf",
        present=(
            "Boss fight",
            "Loot table",
            "Balance the encounter",  # markdown RENDERS: words in, syntax out
            "Check the second phase",  # the list item
            "Scout the arena",  # a checklist in the description
            "Tune the HP",
            "Write the dialogue",  # checklist
            "Started already",  # comment body
            # Localized section labels (en locale).
            "Description",
            "Checklist",
            "Comments",
        ),
    )
    assert "**" not in text  # bold markers consumed, not printed
    assert "[x]" not in text  # the task box draws as a box
    assert len(_pdf_pages(resp)) == 2  # one page per task
    # Threaded order: a reply renders directly under its parent, before the
    # later root comment — not in flat creation order. (Compare on the
    # space-packed text so kerning splits don't shift indices.)
    packed = text.replace(" ", "")
    assert (
        packed.index("Startedalready")
        < packed.index("Replyingtothefirst")
        < packed.index("Separatethreadhere")
    )


async def test_detailed_layout_ignored_for_non_pdf_formats(
    client: AsyncClient, acting_user, session
):
    """layout=detailed only applies to PDF; csv falls through to the table."""
    a = await _actor_with_tasks(acting_user, session, count=1)
    resp = await _export(client, a, "tasks", format="csv", layout="detailed")
    _assert_export(resp, "csv", present=(_TASK_COLUMNS,))


async def test_pdf_export_carries_guild_brand_header(
    client: AsyncClient, acting_user, session
):
    """Every PDF report shows the guild's name (and icon when set) in a running
    header — read from the guild's stored icon and staged into the render."""
    a = await _actor_with_tasks(acting_user, session, count=1)
    guild = await session.get(Guild, a.guild.id)
    guild.name = "Ravenloft Chronicle"
    session.add(guild)
    icon = _png()
    session.add(
        GuildImage(
            guild_id=a.guild.id,
            variant=GuildImageVariant.icon.value,
            sha256=hashlib.sha256(icon).hexdigest(),
            content_type="image/png",
            byte_size=len(icon),
            data=icon,
        )
    )
    await session.commit()

    resp = await _export(client, a, "tasks", format="pdf")
    # The brand header, with the icon staged alongside it.
    _assert_export(resp, "pdf", present=("Ravenloft Chronicle",))


async def test_detailed_pdf_page_count_is_localized(
    client: AsyncClient, acting_user, session
):
    """A multi-page report's footer page count follows the creator's locale —
    "1 von 2" for a German user, not "1 of 2"."""
    a = await _actor_with_tasks(acting_user, session, count=2)
    await _set_locale(session, a.user, "de")

    resp = await _export(client, a, "tasks", format="pdf", layout="detailed")
    _assert_export(resp, "pdf", present=("1 von 2", "2 von 2"), absent=("1 of 2",))
    assert len(_pdf_pages(resp)) == 2


# ---------------------------------------------------------------------------
# Bulk selections
# ---------------------------------------------------------------------------


async def test_bulk_file_selection_exports_as_zip(
    client: AsyncClient, acting_user, session
):
    """Selecting N files exports one artifact per file in the requested
    format, packaged as a single zip download — each entry under its own name
    (colliding titles deduped, not overwritten)."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    native = await create_file(session, a.initiative, a.user, name="Session Notes")
    sheet = await create_file(
        session,
        a.initiative,
        a.user,
        name="Budget",
        file_type=FileType.spreadsheet,
        content={"schema_version": 2, "cells": {"0:0": "x"}},
    )
    twin = await create_file(session, a.initiative, a.user, name="Session Notes")

    resp = await _export(
        client,
        a,
        "file",
        ids=[native.id, sheet.id, twin.id],
        format="json",
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert 'filename="file-' in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].endswith('.zip"')

    names = _zip_names(resp)
    assert len(names) == 3
    assert all(n.endswith(".json") for n in names)
    assert len(set(names)) == 3  # the twin "Session Notes" title deduped
    envelopes = _zip_json(resp)
    assert all(e["type"] == "initiative-file" for e in envelopes)
    assert {e["file_type"] for e in envelopes} == {"native", "spreadsheet"}
    assert {e["name"] for e in envelopes} == {"Session Notes", "Budget"}


async def test_bulk_file_selection_rejects_format_not_shared_by_all(
    client: AsyncClient, acting_user, session
):
    """The requested format must be valid for EVERY selected file's type (a
    whiteboard can't render pdf), and per-item authorization still holds (an
    out-of-initiative file 404s the whole selection)."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    native = await _file(session, a, "native")
    board = await _file(session, a, "whiteboard")
    ids = [native.id, board.id]

    resp = await _export(client, a, "file", ids=ids, format="pdf")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_INVALID_FORMAT"

    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    denied = await _export(
        client, a, "file", headers=outsider.headers, ids=ids, format="json"
    )
    assert denied.status_code == 404


async def test_bulk_queue_selection_exports_envelope_zip(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    q1 = await create_queue(session, a.initiative, a.user, name="Alpha Rotation")
    q2 = await create_queue(session, a.initiative, a.user, name="Beta Rotation")

    resp = await _export(client, a, "queue", ids=[q1.id, q2.id], format="json")
    assert resp.status_code == 200
    names = _zip_names(resp)
    assert len(names) == 2
    assert all(n.endswith(".initiative-queue.json") for n in names)
    assert {e["name"] for e in _zip_json(resp)} == {"Alpha Rotation", "Beta Rotation"}

    # Single-id selection stays a plain (unzipped) file.
    single = await _export(client, a, "queue", ids=[q1.id], format="json")
    assert single.status_code == 200
    assert single.headers["content-type"] == "application/json"


async def test_bulk_counter_group_pdf_zip_through_job_path(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A bulk selection over the inline threshold becomes a job; the worker
    renders and stores the ZIP, and the download carries the bundle name."""
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    g1 = await create_counter_group(session, a.initiative, a.user, name="Party")
    g2 = await create_counter_group(session, a.initiative, a.user, name="Villains")
    await create_counter(session, g1, name="HP")
    await create_counter(session, g2, name="Minions")

    queued = await _export(client, a, "counter_group", ids=[g1.id, g2.id], format="pdf")
    assert queued.status_code == 202

    await _run_worker()

    dl = await _download(client, a, queued.json()["id"])
    _assert_export(dl, "zip", disposition=("counter-group-",))
    archive = _zip(dl)
    assert len(archive.namelist()) == 2
    for name in archive.namelist():
        assert archive.read(name).startswith(b"%PDF")


async def test_bulk_selection_size_is_bounded(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await _export(client, a, "file", ids=list(range(1, 103)), format="json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_INVALID_PARAMS"


async def test_bulk_project_selection_exports_backup_zip(
    client: AsyncClient, acting_user, session
):
    """Selecting N projects exports one backup envelope per project in a zip —
    and the per-project WRITE rule holds: a read-only project anywhere in the
    selection fails the whole export instead of leaving a silent gap."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    second = await create_project(session, a.initiative, a.user, name="Second Arc")

    resp = await _export(
        client, a, "project", ids=[a.project.id, second.id], format="json"
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    names = _zip_names(resp)
    assert len(names) == 2
    assert all(n.endswith(".initiative-project.json") for n in names)
    assert {e["project"]["name"] for e in _zip_json(resp)} == {
        a.project.name,
        "Second Arc",
    }

    # A write-less project in the selection: the owner grant belongs to the
    # other member, so the whole selection is refused (403), not a partial zip.
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    theirs = await create_project(session, a.initiative, b.user, name="Not Yours")
    denied = await _export(
        client, a, "project", ids=[a.project.id, theirs.id], format="json"
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Calendar exports
# ---------------------------------------------------------------------------


async def _events_enabled(session, initiative):
    """Calendar events are a toggleable tool (off by default) — flip the
    initiative's master switch so the enumeration includes it."""
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()


async def test_calendar_export_ics_and_json(client: AsyncClient, acting_user, session):
    """A calendar exports as one multi-event iCalendar file (the stored rules as
    they are, a picked one's start written on its picked day, all read back
    unchanged by the ics import) or one importable envelope carrying the
    calendar plus every event."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _events_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Raid Nights")
    # Mondays and Wednesdays at 00:30, picked in Berlin: Sundays and Tuesdays
    # in UTC.
    session_start = datetime(2026, 10, 4, 22, 30, tzinfo=timezone.utc)
    weekly = "RRULE:FREQ=WEEKLY;BYDAY=MO,WE"
    recurring_event = await create_calendar_event(
        session,
        calendar,
        a.user,
        title="Session 13",
        start_at=session_start,
        end_at=session_start + timedelta(hours=3),
        description="Return to the castle",
        location="Roll20",
        recurrence=weekly,
        recurrence_shift=1440,
    )
    # All day on the second Monday until mid-December, November skipped.
    monthly = "RRULE:FREQ=MONTHLY;UNTIL=20261214;BYDAY=2MO\nEXDATE;VALUE=DATE:20261109"
    await create_calendar_event(
        session,
        calendar,
        a.user,
        title="Guild meeting",
        all_day=True,
        start_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
        end_at=datetime(2026, 10, 12, 23, 59, 59, tzinfo=timezone.utc),
        recurrence=monthly,
    )
    definition = await create_property_definition(session, a.initiative, name="Table")
    await create_property_value(
        session, recurring_event, definition, value_text="Table 3"
    )
    await create_calendar_event(session, calendar, a.user, title="One-shot night")
    # The first session, an hour late: its own row, in the series' UID.
    await create_calendar_event(
        session,
        calendar,
        a.user,
        title="Session 13 (late)",
        start_at=session_start + timedelta(hours=1),
        end_at=session_start + timedelta(hours=4),
        series_id=recurring_event.id,
        original_start=session_start,
    )

    body = _assert_export(
        await _export(client, a, "calendar", format="ics"),
        "ics",
        disposition=('filename="raid_nights-',),
        present=(
            "SUMMARY:Session 13",
            "DTSTART;TZID=Etc/GMT-2:20261005T003000",
            "RRULE:FREQ=WEEKLY;BYDAY=MO,WE",
            "DTSTART;VALUE=DATE:20261012",
            "DTEND;VALUE=DATE:20261013",
            "RRULE:FREQ=MONTHLY;UNTIL=20261214;BYDAY=2MO",
            "EXDATE;VALUE=DATE:20261109",
            "LOCATION:Roll20",
            "RECURRENCE-ID:20261004T223000Z",
        ),
    )
    assert body.count("BEGIN:VEVENT") == 4
    assert body.count(f"UID:event-{recurring_event.id}@initiative") == 2
    imported, errors, _ = ical_service.build_calendar_events(
        body, calendar.id, a.guild.id, a.user.id, tz="Europe/Berlin"
    )
    assert errors == []
    by_title = {event.title: event for event in imported}
    picked = by_title["Session 13"]
    assert (picked.start_at, picked.recurrence, picked.recurrence_shift) == (
        session_start,
        weekly,
        1440,
    )
    late = by_title["Session 13 (late)"]
    # It came without the series' description and place, so those are its own.
    assert (late.series, late.original_start, late.overridden_fields) == (
        picked,
        session_start,
        ["all_day", "description", "end_at", "location", "start_at", "title"],
    )
    meeting = by_title["Guild meeting"]
    assert (meeting.start_at, meeting.end_at, meeting.recurrence) == (
        datetime(2026, 10, 12, tzinfo=timezone.utc),
        datetime(2026, 10, 12, 23, 59, 59, tzinfo=timezone.utc),
        monthly,
    )
    # Another app's file: a rule in its own zone comes into UTC terms, a
    # floating time is read in the importer's zone, and a rule an event can't
    # repeat by leaves the event without its repeat.
    foreign, errors, _ = ical_service.build_calendar_events(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nSUMMARY:Standup\r\n"
        "DTSTART;TZID=Europe/Berlin:20261005T003000\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nSUMMARY:Month end\r\nDTSTART:20261031T090000\r\n"
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nSUMMARY:Ticker\r\nDTSTART:20261005T090000Z\r\n"
        "RRULE:FREQ=MINUTELY\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n",
        calendar.id,
        a.guild.id,
        a.user.id,
        tz="America/New_York",
    )
    assert errors == []
    assert {
        e.title: (e.start_at, e.recurrence, e.recurrence_shift) for e in foreign
    } == {
        "Standup": (session_start, "RRULE:FREQ=WEEKLY;BYDAY=MO", 1440),
        "Month end": (
            datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc),
            "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1",
            0,
        ),
        "Ticker": (datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc), None, 0),
    }

    js = await _export(client, a, "calendar", format="json")
    envelope = json.loads(_assert_export(js, "json"))
    assert envelope["type"] == "initiative-calendar"
    assert envelope["schema_version"] == 1
    assert envelope["name"] == "Raid Nights"
    titles = {e["title"] for e in envelope["events"]}
    assert titles == {
        "Session 13",
        "Session 13 (late)",
        "Guild meeting",
        "One-shot night",
    }
    recurring = next(e for e in envelope["events"] if e["title"] == "Session 13")
    late = next(e for e in envelope["events"] if e["title"] == "Session 13 (late)")
    # The late one names its series the way the series answers to.
    assert (late["series_ref"], late["original_start"]) == (
        recurring["external_ref"],
        session_start.isoformat(),
    )
    assert recurring["recurrence"] == weekly
    assert recurring["description"] == "Return to the castle"
    # Custom properties ride flat and by NAME (project-envelope encoding).
    assert recurring["properties"] == [
        {"property_name": "Table", "property_type": "text", "value_text": "Table 3"}
    ]


async def test_calendar_export_applies_calendar_sharing(
    client: AsyncClient, acting_user, session
):
    """Calendar sharing holds for exports: export-all carries the calendars the
    exporter may export — the ones they own — and leaves out one they can only
    read as well as one not shared with them at all. Asking for either by id
    is refused, while a guild admin still reaches them by explicit selection.
    The events export takes read access instead, so it carries the readable
    calendar too, and still nothing unshared."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _events_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    own_cal = await create_calendar(session, a.initiative, b.user, name="Theirs")
    read_cal = await create_calendar(session, a.initiative, a.user, name="Readable")
    secret_cal = await create_calendar(session, a.initiative, a.user, name="Secret")
    await create_calendar_event(session, own_cal, b.user, title="Their session")
    await create_calendar_event(session, read_cal, a.user, title="Read only")
    secret = await create_calendar_event(session, secret_cal, a.user, title="Hidden")
    # Strip every grant except the creator's own — b can no longer see it.
    # (is_distinct_from: role grants carry a NULL user_id, which a plain
    # ``!=`` would silently skip.)
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == "calendar",
            ResourceGrant.resource_id == secret_cal.id,
            ResourceGrant.user_id.is_distinct_from(a.user.id),
        )
    )
    await session.commit()
    assert secret.id

    resp = await _export(client, a, "calendar", headers=b.headers, format="json")
    envelope = json.loads(_assert_export(resp, "json"))
    assert envelope["name"] == "Theirs"
    assert {e["title"] for e in envelope["events"]} == {"Their session"}

    # Explicitly requesting one they may not export is refused outright.
    for calendar in (read_cal, secret_cal):
        denied = await _export(
            client,
            a,
            "calendar",
            headers=b.headers,
            format="ics",
            ids=[calendar.id],
        )
        assert denied.status_code == 403, calendar.name
    # A filter narrows a selection after it is authorized, never instead of it.
    filtered = await _export(
        client,
        a,
        "calendar",
        headers=b.headers,
        format="ics",
        ids=[own_cal.id, secret_cal.id],
        filters=json.dumps({"archived": False}),
    )
    assert filtered.status_code == 403

    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    admin_resp = await _export(
        client,
        a,
        "calendar",
        headers=admin.headers,
        format="json",
        ids=[secret_cal.id],
    )
    admin_env = json.loads(_assert_export(admin_resp, "json"))
    assert {e["title"] for e in admin_env["events"]} == {"Hidden"}

    # The events export is a formatted read: what b can see, and nothing more.
    body = _assert_export(
        await _export(client, a, "events", headers=b.headers, format="ics"),
        "ics",
        disposition=('filename="events.ics"',),
        present=("SUMMARY:Their session", "SUMMARY:Read only"),
        absent=("SUMMARY:Hidden",),
    )
    assert body.count("BEGIN:VEVENT") == 2
    named = await _export(
        client, a, "events", headers=b.headers, calendar_ids=[secret_cal.id]
    )
    assert _assert_export(named, "ics").count("BEGIN:VEVENT") == 0
    left_out = await _export(
        client, a, "events", headers=b.headers, exclude_calendar_ids=[read_cal.id]
    )
    assert "SUMMARY:Read only" not in _assert_export(left_out, "ics")


#: July to September 2026, as the wizard and the calendar page send a range.
_SUMMER = {
    "start_after": "2026-07-01T00:00:00+00:00",
    "start_before": "2026-09-30T23:59:59+00:00",
}


async def test_calendar_export_narrows_by_initiative_and_date_range(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """A calendar export narrows to one initiative, and to the events starting
    in a date range: a repeating one whole, with an occurrence moved out of the
    range, counted as what it carries. The calendar page's events export takes
    the same range."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _events_enabled(session, a.initiative)
    other = await create_initiative(
        session, a.guild, a.user, name="Side quests", calendars_enabled=True
    )
    main_cal = await create_calendar(session, a.initiative, a.user, name="Main Cal")
    side_cal = await create_calendar(session, other, a.user, name="Side Cal")
    await create_calendar_event(session, main_cal, a.user, title="Main event")
    await create_calendar_event(session, side_cal, a.user, title="Side event")

    resp = await _export(
        client, a, "calendar", format="json", initiative_id=a.initiative.id
    )
    envelope = json.loads(_assert_export(resp, "json"))
    assert envelope["name"] == "Main Cal"
    assert {e["title"] for e in envelope["events"]} == {"Main event"}

    def at(month: int, day: int = 10) -> dict:
        start = datetime(2026, month, day, 18, tzinfo=timezone.utc)
        return {"start_at": start, "end_at": start + timedelta(hours=2)}

    await create_calendar_event(session, side_cal, a.user, title="Spring", **at(3))
    await create_calendar_event(session, side_cal, a.user, title="Summer", **at(7))
    weekly = await create_calendar_event(
        session,
        side_cal,
        a.user,
        title="Weekly",
        recurrence="RRULE:FREQ=WEEKLY",
        **at(6, 1),
    )
    await create_calendar_event(
        session,
        side_cal,
        a.user,
        title="Weekly, moved",
        series_id=weekly.id,
        original_start=at(6, 8)["start_at"],
        **at(12),
    )
    in_range = {"Summer", "Weekly", "Weekly, moved"}
    # Counted as the range leaves it, it is small enough to hand back inline.
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", len(in_range))
    resp = await _export(
        client,
        a,
        "calendar",
        format="json",
        ids=[side_cal.id],
        filters=json.dumps({"events": _SUMMER}),
    )
    envelope = json.loads(_assert_export(resp, "json"))
    assert {e["title"] for e in envelope["events"]} == in_range
    events = _assert_export(
        await _export(client, a, "events", calendar_ids=[side_cal.id], **_SUMMER),
        "ics",
        absent=("SUMMARY:Spring",),
    )
    assert events.count("BEGIN:VEVENT") == len(in_range)


# ---------------------------------------------------------------------------
# Aggregate exports: initiative & guild backup/report (the wizard backend)
# ---------------------------------------------------------------------------


async def _all_tools_enabled(session, initiative):
    """Every non-core tool is off by default — flip each initiative master
    switch so the aggregate enumeration includes them.

    Derived from the enum rather than listed, so a new tool is switched on
    here the day it exists instead of quietly sitting out the backup tests."""
    for tool in Tool:
        setattr(initiative, tool.view_permission, True)
    session.add(initiative)
    await session.commit()


async def _populate_initiative(session, a, initiative):
    """One entity per tool inside the given initiative."""
    await _all_tools_enabled(session, initiative)
    project = await create_project(session, initiative, a.user, name="Main Arc")
    await create_task(session, project, title="Fell the tower")
    await create_file(session, initiative, a.user, name="Campaign Notes")
    await create_queue(session, initiative, a.user, name="Turn Order")
    await create_counter_group(session, initiative, a.user, name="Party Gold")
    calendar = await create_calendar(session, initiative, a.user, name="Raid Nights")
    await create_calendar_event(session, calendar, a.user, title="Session Zero")
    await create_post(session, initiative, a.user, name="Session moved")


async def test_initiative_backup_zip_layout_and_manifest(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A backup is one importable zip: per-tool JSON envelopes in per-tool
    folders under the initiative's own directory, indexed by a manifest whose
    entries match the archive exactly. Aggregate exports are always a job."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _populate_initiative(session, a, a.initiative)

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    names = set(archive.namelist())
    assert "manifest.json" in names

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["type"] == "initiative-backup"
    assert manifest["schema_version"] == 1
    assert manifest["guild"]["id"] == a.guild.id
    assert [i["id"] for i in manifest["initiatives"]] == [a.initiative.id]
    assert manifest["initiatives"][0]["tools"] == {
        "project": "included",
        "file": "included",
        "queue": "included",
        "counter_group": "included",
        "calendar": "included",
        "post": "included",
        # On, and holding nothing: a tool the initiative has is in the backup
        # whether or not anybody has written in it yet.
        "wiki": "included",
        "gallery": "included",
        "dashboard": "included",
    }

    # Every file in the archive is accounted for by the manifest, and vice
    # versa: tool envelopes and the initiative's own shape as entries, the
    # community's own files as guild_sections.
    entry_paths = {e["path"] for e in manifest["entries"]}
    section_paths = {s["path"] for s in manifest["guild_sections"]}
    assert entry_paths | section_paths == names - {"manifest.json"}
    assert manifest["assets"] == [] and manifest["skipped"] == []

    folder = next(n for n in names if n.startswith("initiatives/")).split("/")[1]
    assert folder.startswith(f"{a.initiative.id}-")
    by_type = {e["type"]: e for e in manifest["entries"]}
    assert set(by_type) == {
        "initiative-project",
        "initiative-file",
        "initiative-queue",
        "initiative-counter-group",
        "initiative-calendar",
        "initiative-post",
        # The initiative's own shape rides as an entry too: it is applied by
        # the same loop, ahead of the content that refers to it.
        "initiative-structure",
    }

    # Spot-check envelopes round-trip through the archive paths.
    project_env = json.loads(archive.read(by_type["initiative-project"]["path"]))
    assert project_env["type"] == "initiative-project"
    assert project_env["project"]["name"] == "Main Arc"
    assert [t["title"] for t in project_env["tasks"]] == ["Fell the tower"]
    doc_env = json.loads(archive.read(by_type["initiative-file"]["path"]))
    assert doc_env["type"] == "initiative-file"
    assert doc_env["name"] == "Campaign Notes"
    calendar_env = json.loads(archive.read(by_type["initiative-calendar"]["path"]))
    assert calendar_env["name"] == "Raid Nights"
    assert [e["title"] for e in calendar_env["events"]] == ["Session Zero"]
    assert by_type["initiative-calendar"]["path"].endswith(".initiative-calendar.json")
    assert "/calendars/" in by_type["initiative-calendar"]["path"]


async def test_initiative_backup_includes_read_only_projects(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """An initiative's export is for those who manage it, as its settings page
    is. Within it, the aggregate-export relaxation: a project the exporter can
    only READ is still in their backup (standalone per-project export would
    403)."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    exporter, member = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role=role,
        )
        for role in ("project_manager", "member")
    ]
    theirs = await create_project(session, owner.initiative, owner.user, name="Theirs")
    await create_resource_grant(session, theirs, user=exporter.user)

    refused = await _export(
        client, member, "initiative", initiative_id=owner.initiative.id
    )
    assert refused.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED", refused.text
    # Standalone export of the same project: still write-gated.
    denied = await _export(client, exporter, "project", ids=[theirs.id], format="json")
    assert denied.status_code == 403

    resp = await _export(
        client, exporter, "initiative", initiative_id=owner.initiative.id
    )
    archive = await _rendered_zip(client, exporter, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    project_entries = [e for e in manifest["entries"] if e["tool"] == "project"]
    assert {e["title"] for e in project_entries} == {"Theirs"}

    # No longer managing it, the exporter is not served the file either.
    roles = await client.get(
        owner.g(f"/initiatives/{owner.initiative.id}/roles"), headers=owner.headers
    )
    member_role = next(r["id"] for r in roles.json() if r["name"] == "member")
    demoted = await client.patch(
        owner.g(f"/initiatives/{owner.initiative.id}/members/{exporter.user.id}"),
        headers=owner.headers,
        json={"role_id": member_role},
    )
    assert demoted.status_code == 200, demoted.text
    dl = await client.get(
        exporter.g(f"/exports/jobs/{resp.json()['id']}/download"),
        headers=exporter.headers,
    )
    assert dl.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED", dl.text


async def test_a_backup_lists_its_assignees_among_its_people(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """The restore asks who everybody is before it writes anything, and an
    assignee is somebody it has to place — a task restored into a community
    where that handle means nobody would otherwise arrive unassigned, with
    nobody having been asked."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(session, a.project, title="Carry the torch", assignees=[a.user])

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))

    assert {
        "handle": handle_of(a.user),
        "name": None,
        "comment_count": 0,
    } in manifest["people"]


async def test_a_backup_lists_who_its_user_properties_name(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A restore places a user-type property value through the people step,
    so the manifest has to list whoever one names — or the step never asks,
    and the value lands only on an exact name match."""
    from app.core.user_display import handle_of
    from app.models.tenant.property import PropertyType

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project, title="Report it")
    reporter = await create_property_definition(
        session, a.initiative, name="Reporter", type=PropertyType.user_reference
    )
    await create_property_value(session, task, reporter, value_user_id=a.user.id)

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))

    assert handle_of(a.user) in [p["handle"] for p in manifest["people"]]


async def test_aggregate_export_hides_dac_invisible_rows(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Rows not shared with the exporter are simply ABSENT from the backup —
    not listed under ``skipped`` either."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _all_tools_enabled(session, a.initiative)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_file(session, a.initiative, other.user, name="Their Secret")
    await create_queue(session, a.initiative, other.user, name="Their Queue")
    await create_file(session, a.initiative, a.user, name="My Notes")

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    titles = {e["title"] for e in manifest["entries"]}
    assert "My Notes" in titles and a.project.name in titles
    assert "Their Secret" not in titles and "Their Queue" not in titles
    assert manifest["skipped"] == []  # invisible != skipped
    dumped = json.dumps(manifest)
    assert "Their Secret" not in dumped and "Their Queue" not in dumped


async def test_guild_export_belongs_to_the_seat(
    client: AsyncClient, acting_user, session
):
    """Running a community is an admin's job; taking every initiative it has
    in one file is the seat's. An ordinary admin is refused, as a member is."""
    seat = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)
    member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
    for caller in (admin, member):
        for source, params in (("community", {}), ("estimate", {"scope": "community"})):
            resp = await _export(
                client, caller, source, headers=caller.headers, **params
            )
            assert resp.status_code == 403, (caller.membership.role, source)
            assert resp.json()["detail"] == "EXPORT_SUPERADMIN_REQUIRED"


async def test_guild_backup_spans_initiatives_and_refreshes_access(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A guild backup is the initiative backup repeated per initiative, in one
    zip — and the builder re-validates the creator's access per chunk (the
    staleness rule for long builds)."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    await _populate_initiative(session, a, a.initiative)
    second = await create_initiative(session, a.guild, a.user, name="Second Front")
    await _populate_initiative(session, a, second)

    real_establish = api_deps.establish_guild_access
    calls = {"n": 0}

    async def counting_establish(*args, **kwargs):
        calls["n"] += 1
        return await real_establish(*args, **kwargs)

    monkeypatch.setattr(api_deps, "establish_guild_access", counting_establish)

    resp = await _export(client, a, "community")
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["type"] == "guild-backup"
    assert {i["name"] for i in manifest["initiatives"]} >= {
        a.initiative.name,
        "Second Front",
    }

    folders = {
        n.split("/")[1] for n in archive.namelist() if n.startswith("initiatives/")
    }
    assert any(f.startswith(f"{a.initiative.id}-") for f in folders)
    assert any(f.startswith(f"{second.id}-") for f in folders)

    # Worker routing (1) + one forced refresh per initiative in the build.
    assert calls["n"] >= 1 + len(manifest["initiatives"])


async def test_backup_uploads_toggle_and_asset_bundling(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """include_uploads=true bundles the uploaded file's blob AND native docs'
    embedded images under assets/ (embedded ones at their real stored size,
    from their uploads row); =false records the file doc under ``skipped``
    with reason uploads_excluded instead of silently dropping it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    payload = b"%PDF-handout-bytes"
    file_doc = await _uploaded_file(
        session,
        a,
        name="Player Handout",
        key="handout-xyz.pdf",
        filename="Player Handout.pdf",
        payload=payload,
        content_type="application/pdf",
    )
    image_bytes = b"embedded-image-bytes"
    get_guild_storage(a.guild.id).write(
        "inline-img.png", image_bytes, content_type="image/png"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="inline-img.png",
        size_bytes=len(image_bytes),
        content_type="image/png",
    )
    await _image_file(session, a, name="Illustrated Notes", key="inline-img.png")

    with_uploads = await _export(
        client, a, "initiative", initiative_id=a.initiative.id, include_uploads=True
    )
    archive = await _rendered_zip(client, a, monkeypatch, role_session, with_uploads)
    assert archive.read("assets/handout-xyz.pdf") == payload
    assert archive.read("assets/inline-img.png") == image_bytes
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["include_uploads"] is True
    assets = {rec["storage_key"]: rec for rec in manifest["assets"]}
    handout = assets["handout-xyz.pdf"]
    assert handout["path"] == "assets/handout-xyz.pdf"
    assert handout["original_filename"] == "Player Handout.pdf"
    assert handout["size_bytes"] == len(payload)
    inline = assets["inline-img.png"]
    assert inline["size_bytes"] == len(image_bytes)  # real size, not 0
    assert inline["content_type"] == "image/png"
    assert inline["referenced_by"] == [
        next(
            e["path"] for e in manifest["entries"] if e["title"] == "Illustrated Notes"
        )
    ]
    (entry,) = [e for e in manifest["entries"] if e["type"] == "file"]
    assert entry["entity_id"] == file_doc.id
    assert entry["asset"] == "assets/handout-xyz.pdf"

    without = await _export(
        client, a, "initiative", initiative_id=a.initiative.id, include_uploads=False
    )
    archive2 = await _rendered_zip(client, a, monkeypatch, role_session, without)
    names = set(archive2.namelist())
    assert not any(n.startswith("assets/") for n in names)
    manifest2 = json.loads(archive2.read("manifest.json"))
    assert manifest2["include_uploads"] is False
    assert manifest2["assets"] == []
    (skip,) = manifest2["skipped"]
    assert skip["entity_id"] == file_doc.id
    assert skip["reason"] == "uploads_excluded"
    assert not any(e["type"] == "file" for e in manifest2["entries"])


async def test_backup_upload_byte_cap(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """The uploads byte cap rejects an oversized backup at request time, before
    a job row exists."""
    monkeypatch.setattr(export_limits, "EXPORT_MAX_BACKUP_UPLOAD_BYTES", 4)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _uploaded_file(
        session,
        a,
        name="Big Map",
        key="big-map.png",
        filename="big-map.png",
        size=1_000_000,
    )
    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_TOO_LARGE"

    # Excluding uploads lifts the cap: the doc is skipped, not shipped.
    ok = await _export(
        client, a, "initiative", initiative_id=a.initiative.id, include_uploads=False
    )
    assert ok.status_code == 202


async def test_backup_embedded_image_bytes_hit_cap_at_build(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Embedded document images aren't visible to the pre-flight count (it only
    sizes uploaded files), so the cap catches them at build time: the job fails
    closed instead of assembling an over-cap archive."""
    monkeypatch.setattr(export_limits, "EXPORT_MAX_BACKUP_UPLOAD_BYTES", 4)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_upload(
        session, a.guild, a.user, filename="huge.png", size_bytes=1_000_000
    )
    await _image_file(session, a, name="Illustrated", key="huge.png")

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    assert resp.status_code == 202  # pre-flight can't see embedded bytes
    job_id = resp.json()["id"]

    await _run_worker()

    body = await _job(client, a, job_id)
    assert body["status"] == ExportJobStatus.failed.value
    assert body["error"] == "EXPORT_TOO_LARGE"


async def test_report_mode_mixed_formats_zip(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """À-la-carte report: one job, one zip, each tool in its chosen format — a
    PDF beside a CSV beside an ICS — and no manifest/assets."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _populate_initiative(session, a, a.initiative)

    resp = await _export(
        client,
        a,
        "initiative",
        initiative_id=a.initiative.id,
        mode="report",
        formats=json.dumps(
            {
                "project": "pdf",
                "queue": "csv",
                "counter_group": "xlsx",
                "calendar": "ics",
                "file": {"native": "md"},
            }
        ),
    )
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    names = archive.namelist()
    assert "manifest.json" not in names
    assert {n.rsplit(".", 1)[-1] for n in names} == {"pdf", "csv", "xlsx", "ics", "md"}
    pdf_name = next(n for n in names if n.endswith(".pdf"))
    assert archive.read(pdf_name).startswith(b"%PDF")
    ics_name = next(n for n in names if n.endswith(".ics"))
    assert archive.read(ics_name).startswith(b"BEGIN:VCALENDAR")
    md_name = next(n for n in names if n.endswith(".md"))
    assert "Campaign Notes" in archive.read(md_name).decode("utf-8")


# Selectors the aggregate export refuses to guess at, and the code each one
# comes back with. Truthy-but-not-boolean include values ("yes") are rejected
# rather than read as true.
_INVALID_SELECTORS: list[tuple[dict[str, Any], str]] = [
    ({"include": "not json"}, "EXPORT_INVALID_PARAMS"),
    ({"mode": "report", "formats": '{"queue": "wav"}'}, "EXPORT_INVALID_FORMAT"),
    (
        {"mode": "report", "formats": '{"file": {"native": "xlsx"}}'},
        "EXPORT_INVALID_FORMAT",
    ),
    ({"include": '{"wands": true}'}, "EXPORT_INVALID_PARAMS"),
    ({"include": '{"project": "yes"}'}, "EXPORT_INVALID_PARAMS"),
    ({"filters": '{"wands": {}}'}, "EXPORT_INVALID_PARAMS"),
    # Paging is the export's own business, not a filter.
    ({"filters": '{"queue": {"page": 2}}'}, "EXPORT_INVALID_PARAMS"),
    (
        {"filters": '{"calendar": {"events": {"start_after": "soon"}}}'},
        "EXPORT_INVALID_PARAMS",
    ),
    (
        {"filters": '{"project": {"tasks": {"conditions": "[{]"}}}'},
        "EXPORT_INVALID_PARAMS",
    ),
    # More property filters than the task list compiles.
    (
        {
            "filters": json.dumps(
                {
                    "project": {
                        "tasks": {
                            "conditions": json.dumps(
                                [
                                    {
                                        "field": "property_values",
                                        "op": "eq",
                                        "value": {"property_id": i, "value": "x"},
                                    }
                                    for i in range(6)
                                ]
                            )
                        }
                    }
                }
            )
        },
        "EXPORT_INVALID_PARAMS",
    ),
]


async def test_aggregate_export_rejects_invalid_selectors(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    for params, detail in _INVALID_SELECTORS:
        resp = await _export(
            client, a, "initiative", initiative_id=a.initiative.id, **params
        )
        assert resp.status_code == 400, params
        assert resp.json()["detail"] == detail, params

    # An initiative the caller can't reach is indistinguishable from absent.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    hidden = await _export(
        client, a, "initiative", headers=outsider.headers, initiative_id=a.initiative.id
    )
    assert hidden.status_code == 404


async def test_estimate_reports_counts_uploads_and_ceilings(
    client: AsyncClient, acting_user, session
):
    """The wizard's pre-flight numbers — and the route stays reachable (a
    parametric /{job_id} route declared first would 422 on 'estimate')."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _populate_initiative(session, a, a.initiative)
    payload = b"12345678"
    await _uploaded_file(
        session,
        a,
        name="Attached file",
        key="est-blob.bin",
        filename="est-blob.bin",
        payload=payload,
    )

    resp = await _export(
        client, a, "estimate", scope="initiative", initiative_id=a.initiative.id
    )
    assert resp.status_code == 200
    body = resp.json()
    counts = {tool: t["count"] for tool, t in body["tools"].items()}
    assert counts == {
        "project": 2,  # the actor fixture's project + Main Arc
        "file": 2,  # Campaign Notes + the file doc
        "queue": 1,
        "counter_group": 1,
        "calendar": 1,
        "post": 1,
        "wiki": 0,  # the tool is on; nobody has made one
        "gallery": 0,  # likewise
        "dashboard": 0,  # likewise
    }
    assert not any(t["disabled"] for t in body["tools"].values())
    assert body["uploads_count"] == 1
    assert body["uploads_bytes"] == len(payload)
    assert body["uploads_approximate"] is True
    # entities (8) + tasks (1) + uploads MiB (0)
    assert body["estimated_rows"] == 9
    assert body["max_rows"] == export_limits.EXPORT_MAX_BACKUP_ROWS
    assert body["max_upload_bytes"] == export_limits.EXPORT_MAX_BACKUP_UPLOAD_BYTES

    without_uploads = await _export(
        client,
        a,
        "estimate",
        scope="initiative",
        initiative_id=a.initiative.id,
        include_uploads=False,
    )
    assert without_uploads.json()["uploads_bytes"] == 0


async def test_backup_filters_narrow_each_tool_and_are_not_kept(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Each tool's filters are its list's: a tag keeps the queues carrying it,
    archived ones too unless the archive is asked about, templates too unless
    templates are asked about, a calendar keeps the events in its range, and a
    project the tasks its task list would show. The estimate counts what the
    filters leave, and the finished job keeps no filters."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await enable_all_tools(session, a.initiative)
    tag = await create_tag(session, a.guild, name="raid")
    tagged = await create_queue(session, a.initiative, a.user, name="Tagged")
    shelved = await create_queue(
        session,
        a.initiative,
        a.user,
        name="Shelved",
        archived_at=datetime.now(timezone.utc),
    )
    await create_queue(session, a.initiative, a.user, name="Plain")
    for queue in (tagged, shelved):
        await assign_tag(session, queue, tag)
    calendar = await create_calendar(session, a.initiative, a.user, name="Raids")
    for title, month in (("Spring", 3), ("Summer", 7)):
        start = datetime(2026, month, 10, 18, tzinfo=timezone.utc)
        await create_calendar_event(
            session, calendar, a.user, title=title, start_at=start, end_at=start
        )

    blueprint = await create_project(
        session, a.initiative, a.user, name="Blueprint", is_template=True
    )
    await create_task(session, blueprint, title="Template step")
    open_task = await create_task(session, a.project, title="Open")
    shipped = await create_task(
        session, a.project, title="Shipped", status_category=TaskStatusCategory.done
    )
    await create_task(
        session, a.project, title="Put away", archived_at=datetime.now(timezone.utc)
    )
    await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, open_task.id),
        target=(SearchEntityType.task, shipped.id),
        relationship_type=RelationshipType.depends_on,
    )
    open_tasks = {
        "tasks": {
            "conditions": json.dumps(
                [{"field": "status_category", "op": "in_", "value": ["todo"]}]
            )
        }
    }

    def filters(**queue: Any) -> str:
        return json.dumps(
            {
                "queue": {"tag_ids": [tag.id], **queue},
                "calendar": {"events": _SUMMER},
                "project": {"archived": False, **open_tasks},
            }
        )

    async def queues(**queue: Any) -> int:
        resp = await _export(
            client,
            a,
            "estimate",
            scope="initiative",
            initiative_id=a.initiative.id,
            filters=filters(**queue),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["tools"]["queue"]["count"]

    assert (await queues(), await queues(archived=False)) == (2, 1)

    resp = await _export(
        client, a, "initiative", initiative_id=a.initiative.id, filters=filters()
    )
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))

    def envelopes(kind: str) -> list[dict]:
        return [
            json.loads(archive.read(e["path"]))
            for e in manifest["entries"]
            if e["type"] == kind
        ]

    assert {q["name"] for q in envelopes("initiative-queue")} == {"Tagged", "Shelved"}
    [raids] = envelopes("initiative-calendar")
    assert [e["title"] for e in raids["events"]] == ["Summer"]
    projects = {p["project"]["name"]: p for p in envelopes("initiative-project")}
    assert set(projects) == {a.project.name, "Blueprint"}
    assert [t["title"] for t in projects[a.project.name]["tasks"]] == ["Open"]
    assert "filters" not in (await _job(client, a, resp.json()["id"]))["params"]

    # A project's own export takes the same task filter, read by the rule for
    # that project: a guild admin with no grant on it gets the same tasks. A
    # link to a task the filter left out has nothing to land on, so it goes.
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    # Counted as the filters leave it — the template set aside, one open task —
    # it is handed back inline.
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 1)
    own = await _export(
        client,
        a,
        "project",
        headers=admin.headers,
        ids=[a.project.id, blueprint.id],
        format="json",
        filters=json.dumps({"is_template": False, **open_tasks}),
    )
    [kept] = json.loads(_assert_export(own, "json"))["tasks"]
    assert (kept["title"], kept["links"]) == ("Open", [])
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 200)
    # A report shows what its filter asks for, archived tasks included, in
    # the order its sort asks for.
    report = _assert_export(
        await _export(
            client,
            a,
            "project",
            ids=[a.project.id],
            format="csv",
            filters=json.dumps(
                {
                    "tasks": {
                        "include_archived": True,
                        "sorting": json.dumps([{"field": "title", "dir": "desc"}]),
                    }
                }
            ),
        ),
        "csv",
        present=("Open", "Shipped", "Put away"),
    )
    assert report.index("Shipped") < report.index("Put away") < report.index("Open")


async def test_empty_initiative_backup_is_manifest_only_zip(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Zero CONTENT still yields an importable zip, with switched-off tools
    marked disabled in the inventory and their rows left out.

    "Empty" is the content, not the initiative: it has roles and a creator
    from the moment it exists, so its ``structure.json`` rides along. An
    archive that dropped it would restore a pile of nothing with nobody in
    it."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await create_project(session, a.initiative, a.user, name="Switched off")
    # The factory switches every tool on; turn some off so the inventory has
    # deliberately disabled ones to report, one of them holding a project.
    a.initiative.queues_enabled = False
    a.initiative.calendars_enabled = False
    a.initiative.projects_enabled = False
    session.add(a.initiative)
    await session.commit()

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    names = archive.namelist()
    assert "manifest.json" in names
    manifest = json.loads(archive.read("manifest.json"))
    # No CONTENT, so every entry is the initiative's own shape.
    assert {e["type"] for e in manifest["entries"]} == {"initiative-structure"}
    tools = manifest["initiatives"][0]["tools"]
    assert (tools["project"], tools["queue"], tools["calendar"]) == ("disabled",) * 3
    assert tools["file"] == "included"


async def test_guild_export_seat_vacated_fails_closed(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """The seat left between request and render: the worker's re-check fails
    the job instead of shipping a community dump to whoever used to hold it.
    Stepping down to ordinary admin is enough — the archive is the seat's."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    resp = await _export(client, a, "community")
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    a.membership.role = CommunityRole.admin
    session.add(a.membership)
    await session.commit()

    await _run_worker()

    body = await _job(client, a, job_id)
    assert body["status"] == ExportJobStatus.failed.value
    assert body["error"] == "EXPORT_SUPERADMIN_REQUIRED"
    dl = await client.get(a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers)
    assert dl.status_code == 409


# ---------------------------------------------------------------------------
# What a community owns outside its initiatives
# ---------------------------------------------------------------------------


async def test_guild_backup_carries_the_community_itself(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A community backup covers the community, not only the work done inside
    it: its configuration, its tag vocabulary and its roster."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    await create_tag(session, a.guild, name="worldbuilding", color="#ff0000")

    resp = await _export(client, a, "community")
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    names = set(archive.namelist())
    assert {"guild/settings.json", "guild/tags.json", "guild/members.json"} <= names

    settings_payload = json.loads(archive.read("guild/settings.json"))
    assert settings_payload["type"] == "guild-settings"
    assert settings_payload["name"] == a.guild.name

    tags = json.loads(archive.read("guild/tags.json"))["tags"]
    # The colour is the point: envelopes reference tags by name alone, so the
    # definition is what a round trip would otherwise lose.
    assert {"worldbuilding"} <= {t["name"] for t in tags}
    assert [t for t in tags if t["name"] == "worldbuilding"][0]["color"] == "#ff0000"

    members = json.loads(archive.read("guild/members.json"))["members"]
    assert a.user.id in {m["user_id"] for m in members}
    # Named the way the rest of the app names people: handles and display
    # names, the same shape a byline or a mention renders.
    assert all(m.get("handle") for m in members)
    assert not any("@" in json.dumps(m) for m in members)
    # A name is exported only where one was set, never the handle in its place.
    assert [m["name"] for m in members if m["user_id"] == a.user.id] == [None]
    # Whose personal API keys reach the community travels with each member.
    assert {m["api_keys_allowed"] for m in members} == {True}

    manifest = json.loads(archive.read("manifest.json"))
    assert {s["key"] for s in manifest["guild_sections"]} >= {
        "settings",
        "tags",
        "members",
    }


async def test_initiative_backup_omits_community_wide_sections(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """An initiative export carries the initiative. The community's roster,
    configuration and installed plug-ins belong to the community-scoped export.
    The tag vocabulary does ride along, because it is part of the content the
    archive carries."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_tag(session, a.guild, name="npc")

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    names = set(archive.namelist())
    assert "guild/tags.json" in names
    assert "guild/members.json" not in names
    assert "guild/settings.json" not in names
    assert "guild/plugins.json" not in names


async def test_backup_carries_initiative_roles_and_members(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Tool envelopes carry content; none of them carries the access structure
    the content sat inside. Without it a restored initiative is a pile of work
    with nobody in it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    path = next(
        e["path"] for e in manifest["entries"] if e["type"] == "initiative-structure"
    )
    structure = json.loads(archive.read(path))

    assert structure["type"] == "initiative-structure"
    assert structure["initiative_id"] == a.initiative.id
    assert a.user.id in {m["user_id"] for m in structure["members"]}
    assert [m["name"] for m in structure["members"] if m["user_id"] == a.user.id] == [
        None
    ]
    # Roles and memberships travel by NAME: an id means nothing in whatever
    # instance the archive is opened in.
    role_names = {r["name"] for r in structure["roles"]}
    assert role_names
    assert {m["role"] for m in structure["members"]} <= role_names | {None}


async def test_guild_backup_bundles_blobs_nothing_points_at(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Assets otherwise ride with the entity referencing them, so a file
    nobody currently points at is the one thing a full backup would drop
    without saying so."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    orphan_key = "orphan-upload-xyz.bin"
    get_guild_storage(a.guild.id).write(orphan_key, b"orphan-bytes")
    await create_upload(
        session,
        a.guild,
        a.user,
        filename=orphan_key,
        size_bytes=len(b"orphan-bytes"),
        content_type="application/octet-stream",
    )

    resp = await _export(client, a, "community", include_uploads=True)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    assert f"assets/{orphan_key}" in archive.namelist()
    assert archive.read(f"assets/{orphan_key}") == b"orphan-bytes"


# ---------------------------------------------------------------------------
# Dashboards: exportable, minus what belongs to somebody else's plug-in
# ---------------------------------------------------------------------------


async def test_hand_built_dashboard_exports(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A dashboard somebody built here is ordinary content."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    dashboard = await create_dashboard(
        session, a.initiative, a.user, name="Campaign Health"
    )

    resp = await _export(client, a, "dashboard", ids=[dashboard.id])
    assert resp.status_code == 200, resp.text
    envelope = json.loads(resp.content)
    assert envelope["type"] == "initiative-dashboard"
    assert envelope["name"] == "Campaign Health"
    assert envelope["listing_uid"] is None
    assert "definition" in envelope


async def test_dashboard_from_a_third_party_plugin_is_refused(
    client: AsyncClient, acting_user, session
):
    """Its definition belongs to its publisher; the way to have it elsewhere
    is to install that plug-in there."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    dashboard = await create_dashboard(
        session, a.initiative, a.user, name="GitHub Overview"
    )
    dashboard.listing_uid = "notbuiltin123"
    dashboard.listing_version = "1.0.0"
    session.add(dashboard)
    await session.commit()

    resp = await _export(client, a, "dashboard", ids=[dashboard.id])
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_THIRD_PARTY_PLUGIN"


async def test_backup_skips_third_party_dashboards_and_says_so(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """One plugin-derived dashboard must not fail a whole community's backup —
    and the archive states that it existed rather than quietly omitting it."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    mine = await create_dashboard(session, a.initiative, a.user, name="Mine")
    theirs = await create_dashboard(session, a.initiative, a.user, name="Theirs")
    theirs.listing_uid = "notbuiltin123"
    theirs.listing_version = "1.0.0"
    session.add(theirs)
    await session.commit()

    resp = await _export(client, a, "community")
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))

    exported = {e["entity_id"] for e in manifest["entries"] if e["tool"] == "dashboard"}
    assert mine.id in exported
    assert theirs.id not in exported

    skipped = {
        s["entity_id"]: s["reason"]
        for s in manifest["skipped"]
        if s["tool"] == "dashboard"
    }
    assert skipped.get(theirs.id) == "third_party_plugin"


async def test_guild_backup_records_plugins_it_does_not_carry(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """A plug-in published by somebody else is restored by installing it in the
    destination, not by unpacking a copy — so the archive names it in
    ``skipped`` rather than passing over it in silence."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    plugin = await create_guild_plugin(
        session,
        a.guild,
        a.user,
        definition={"kind": "widget", "widgets": []},
        listing_uid="NOTBUILTIN0001",
        name="GitHub",
    )

    resp = await _export(client, a, "community")
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))

    assert "guild/plugins.json" not in archive.namelist()
    skipped = {
        s["entity_id"]: s["reason"]
        for s in manifest["skipped"]
        if s["tool"] == "plugin"
    }
    assert skipped.get(plugin.id) == "third_party_plugin"


async def test_backup_carries_property_definitions(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Envelopes carry property VALUES by name and type. Without the
    definitions an import rebuilds one from the first value it sees, so a
    select arrives holding only the options somebody happened to use."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_property_definition(
        session,
        a.initiative,
        name="Region",
        type=PropertyType.select,
        options=[
            {"id": "n", "label": "North", "color": "#112233"},
            {"id": "s", "label": "South", "color": "#445566"},
        ],
    )

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    path = next(
        e["path"] for e in manifest["entries"] if e["type"] == "initiative-properties"
    )
    payload = json.loads(archive.read(path))

    region = next(p for p in payload["properties"] if p["name"] == "Region")
    assert region["type"] == PropertyType.select.value
    # The whole option list, not just what happens to be in use.
    assert [o["label"] for o in region["options"]] == ["North", "South"]


# ---------------------------------------------------------------------------
# Large exports: delivered to the operator's destination, not downloaded
# ---------------------------------------------------------------------------


async def test_whole_community_export_has_a_cooldown(
    client: AsyncClient, acting_user, session
):
    """A community's entire content is not a thing to re-read on a loop, and
    the cooldown is counted across the community rather than per person."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    first = await _export(client, a, "community")
    assert first.status_code == 202, first.text

    again = await _export(client, a, "community")
    assert again.status_code == 429
    assert again.json()["detail"] == "EXPORT_COOLDOWN_ACTIVE"

    # A second holder of the seat does not get a fresh allowance.
    b = await acting_user(guild_role=CommunityRole.superadmin, guild=a.guild)
    theirs = await _export(client, b, "community", headers=b.headers)
    assert theirs.status_code == 429


async def test_cooldown_can_be_switched_off(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(settings, "EXPORT_GUILD_COOLDOWN_HOURS", 0)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    assert (await _export(client, a, "community")).status_code == 202
    assert (await _export(client, a, "community")).status_code == 202


async def test_guild_export_status_says_who_took_the_last_one_and_when(
    client: AsyncClient, acting_user, session
):
    """What the community settings page asks before anybody opens the wizard.

    Nobody should learn that a colleague already exported the community by
    being refused when they try it themselves.
    """
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    quiet = await client.get(a.g("/exports/community/status"), headers=a.headers)
    assert quiet.status_code == 200, quiet.text
    body = quiet.json()
    assert body["latest"] is None
    assert body["latest_started_by"] is None
    assert body["next_available_at"] is None
    assert body["cooldown_hours"] == settings.EXPORT_GUILD_COOLDOWN_HOURS

    started = await _export(client, a, "community")
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]

    body = (
        await client.get(a.g("/exports/community/status"), headers=a.headers)
    ).json()
    assert body["latest"]["id"] == job_id
    assert body["latest"]["status"] == ExportJobStatus.queued.value
    assert body["latest_started_by"] == f"{a.user.username}#{a.user.discriminator:04d}"

    # The countdown the page shows and the door the create route shuts are the
    # same number, read from the same job.
    created_at = datetime.fromisoformat(body["latest"]["created_at"])
    available_at = datetime.fromisoformat(body["next_available_at"])
    assert available_at == created_at + timedelta(
        hours=settings.EXPORT_GUILD_COOLDOWN_HOURS
    )

    refused = await _export(client, a, "community")
    assert refused.status_code == 429
    left = (available_at - datetime.now(timezone.utc)).total_seconds()
    assert abs(int(refused.headers["Retry-After"]) - left) <= 5


async def test_guild_export_status_is_the_seats(
    client: AsyncClient, acting_user, session
):
    """It reports the seat's own actions to the seat."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)

    resp = await client.get(admin.g("/exports/community/status"), headers=admin.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "EXPORT_SUPERADMIN_REQUIRED"


async def test_a_failed_export_is_reported_but_holds_no_door(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Only work that was really done counts against the wait — and a failure
    is still the thing the page has to report, or the next person tries the
    same export and it fails the same way."""
    monkeypatch.setattr(settings, "EXPORT_MAX_DOWNLOAD_BYTES", 1)
    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", None)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    job_id = (await _export(client, a, "community")).json()["id"]
    await _run_worker()

    body = (
        await client.get(a.g("/exports/community/status"), headers=a.headers)
    ).json()
    assert body["latest"]["id"] == job_id
    assert body["latest"]["status"] == ExportJobStatus.failed.value
    assert body["next_available_at"] is None
    assert (await _export(client, a, "community")).status_code == 202


async def test_an_archive_over_the_download_bound_is_delivered(
    client: AsyncClient, acting_user, session, monkeypatch, role_session, tmp_path
):
    """Past the bound the app neither holds the archive nor serves it: it goes
    to the operator's destination and the job says so."""
    monkeypatch.setattr(settings, "EXPORT_MAX_DOWNLOAD_BYTES", 1)
    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", str(tmp_path))
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    resp = await _export(client, a, "community")
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    await _run_worker()

    body = await _job(client, a, job_id)
    assert body["status"] == ExportJobStatus.done.value, body.get("error")
    assert body["delivered"] is True
    # The path stays server-side; the client is told that it was delivered.
    assert "destination_ref" not in body

    delivered = list((tmp_path / f"guild_{a.guild.id}").iterdir())
    assert len(delivered) == 1 and delivered[0].suffix == ".zip"

    # Nothing to download, and the job says why rather than reading as unready.
    dl = await client.get(a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers)
    assert dl.status_code == 409
    assert dl.json()["detail"] == "EXPORT_DELIVERED"


async def test_a_delivered_archive_is_not_swept_up_by_artifact_gc(
    client: AsyncClient, acting_user, session, monkeypatch, role_session, tmp_path
):
    """It lives in the operator's destination under their retention, so it
    carries no GC deadline of ours."""
    monkeypatch.setattr(settings, "EXPORT_MAX_DOWNLOAD_BYTES", 1)
    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", str(tmp_path))
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    resp = await _export(client, a, "community")
    job_id = resp.json()["id"]
    await _run_worker()

    body = await _job(client, a, job_id)
    assert body["expires_at"] is None


async def test_over_the_bound_with_no_destination_fails_the_job_clearly(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Refused rather than produced with nowhere to go, and the code names the
    thing the operator can actually do about it."""
    monkeypatch.setattr(settings, "EXPORT_MAX_DOWNLOAD_BYTES", 1)
    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", None)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    resp = await _export(client, a, "community")
    job_id = resp.json()["id"]
    await _run_worker()

    body = await _job(client, a, job_id)
    assert body["status"] == ExportJobStatus.failed.value
    assert body["error"] == "EXPORT_DESTINATION_REQUIRED"


async def test_estimate_reports_the_download_bound_and_whether_delivery_exists(
    client: AsyncClient, acting_user, session, monkeypatch, tmp_path
):
    """So the wizard can say which of the two is going to happen before
    anybody submits."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    resp = await _export(client, a, "estimate", scope="community")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["max_download_bytes"] == settings.EXPORT_MAX_DOWNLOAD_BYTES
    assert body["delivery_available"] is False

    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", str(tmp_path))
    again = await _export(client, a, "estimate", scope="community")
    assert again.json()["delivery_available"] is True


async def test_download_redirects_when_storage_can_sign_a_url(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Where the operator has turned it on and the object store can sign a
    URL, the bytes travel from it to the client rather than through this
    process for the whole download. The RLS-gated job lookup is still what
    decided it — the URL is minted only after that passed."""
    monkeypatch.setattr(settings, "EXPORT_PRESIGNED_DOWNLOADS", True)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # An aggregate export is always a job, so this needs no inline coaxing.
    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    await _run_worker()
    assert (await _job(client, a, job_id))["status"] == ExportJobStatus.done.value

    import app.api.v1.tenant_endpoints.exports as exports_module

    real_storage = exports_module.get_guild_storage

    class Signing:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def presign_get(self, key, *, ttl, filename=None):
            return f"https://objects.example/{key}?sig=x"

    monkeypatch.setattr(
        exports_module, "get_guild_storage", lambda gid: Signing(real_storage(gid))
    )
    dl = await client.get(
        a.g(f"/exports/jobs/{job_id}/download"),
        headers=a.headers,
        follow_redirects=False,
    )
    assert dl.status_code == 307
    assert dl.headers["location"].startswith("https://objects.example/")


async def test_download_stays_proxied_unless_the_operator_turns_it_on(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """Opt-in: a deployment that has not allowed this app's origin on its
    bucket keeps the proxied response rather than finding out on a redirect."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    job_id = resp.json()["id"]
    await _run_worker()

    import app.api.v1.tenant_endpoints.exports as exports_module

    real_storage = exports_module.get_guild_storage

    class Signing:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def presign_get(self, key, *, ttl, filename=None):
            return f"https://objects.example/{key}?sig=x"

    monkeypatch.setattr(
        exports_module, "get_guild_storage", lambda gid: Signing(real_storage(gid))
    )
    monkeypatch.setattr(settings, "EXPORT_PRESIGNED_DOWNLOADS", False)
    dl = await client.get(
        a.g(f"/exports/jobs/{job_id}/download"),
        headers=a.headers,
        follow_redirects=False,
    )
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"


async def test_a_backup_says_which_wiki_page_a_file_is_filed_under(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    """An uploaded file in a wiki crosses as ``attach_to`` naming the wiki's
    entry — and, when it sits under one of the wiki's pages, that page's slug,
    so a restore files it there again."""
    from app.core.search import SearchEntityType
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.wikis import place_file
    from app.testing.factories import create_wiki, create_wiki_page

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    a.initiative.wikis_enabled = True
    session.add(a.initiative)
    await session.commit()
    file_doc = await _uploaded_file(
        session,
        a,
        name="Rulebook",
        key="rulebook-abc.pdf",
        filename="Rulebook.pdf",
        payload=b"%PDF-rules",
        content_type="application/pdf",
    )
    wiki = await create_wiki(session, a.initiative, a.user, name="Handbook")
    page = await create_wiki_page(session, wiki, a.user, title="Rules")
    await relationships_service.create(
        session,
        source=relationships_service.Endpoint(SearchEntityType.file, file_doc.id),
        relationship_type=RelationshipType.part_of,
        target=relationships_service.Endpoint(SearchEntityType.wiki, wiki.id),
        created_by=a.user.id,
    )
    place_file(wiki, file_doc.id, parent_page_id=page.id)
    session.add(wiki)
    await session.commit()

    resp = await _export(
        client, a, "initiative", initiative_id=a.initiative.id, include_uploads=True
    )
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    wiki_entry = next(e for e in manifest["entries"] if e["type"] == "initiative-wiki")
    (entry,) = [e for e in manifest["entries"] if e["type"] == "file"]
    assert entry["attach_to"] == {
        "kind": "wiki",
        "ref": wiki_entry["path"],
        "page": page.slug,
    }
