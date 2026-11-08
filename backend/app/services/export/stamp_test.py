"""The export stamp lands in each format's metadata, never on the page."""

import io
import re
import zipfile

import pytest

from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.local_backend import LocalRenderBackend
from app.services.export.stamp import stamp_export

_TABLE = {
    "title": "Tasks",
    "columns": [{"key": "title", "label": "Task"}],
    "rows": [{"title": "A task"}],
}
_DOCUMENT = {
    "title": "Notes",
    "blocks": [{"type": "paragraph", "runs": [{"text": "Body"}]}],
}


def _stamped(format: str, template_id: str, data: dict) -> RenderRequest:
    request = RenderRequest(
        guild_id=1,
        template_id=template_id,
        format=format,
        batch=(RenderItem(key="item", data=data),),
    )
    return stamp_export(request, "Ada Lovelace")


async def _render(format: str, template_id: str, data: dict) -> bytes:
    artifacts = await LocalRenderBackend().render(_stamped(format, template_id, data))
    return artifacts[0].content


def test_json_items_are_not_stamped():
    request = _stamped("json", "task-table", {"version": 1})
    assert "exported" not in request.batch[0].data


@pytest.mark.parametrize(
    ("template_id", "data"),
    [
        ("task-table", _TABLE),
        ("data-table", _TABLE),
        ("project-report", _TABLE),
        ("task-detail", {"title": "Tasks", "tasks": []}),
        ("document", _DOCUMENT),
    ],
)
async def test_pdf_carries_author_and_date_in_its_metadata(template_id, data):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(await _render("pdf", template_id, data)))
    assert reader.metadata is not None
    assert reader.metadata.author == "Ada Lovelace"
    assert reader.metadata.creation_date is not None
    assert "Ada Lovelace" not in reader.pages[0].extract_text()


@pytest.mark.parametrize("data", [_TABLE, _DOCUMENT])
async def test_markdown_carries_the_stamp_as_a_comment(data):
    first = (await _render("md", "task-table", data)).decode().splitlines()[0]
    assert first.startswith("<!-- exported: ") and first.endswith(
        "; by: Ada Lovelace -->"
    )


def test_markdown_comment_survives_a_name_that_would_close_it():
    from app.services.export.stamp import markdown_stamp

    request = stamp_export(
        RenderRequest(
            guild_id=1,
            template_id="task-table",
            format="md",
            batch=(RenderItem(key="item", data={}),),
        ),
        "a--->b",
    )
    comment = markdown_stamp(request.batch[0].data)[0]
    assert comment.count("--") == 2


@pytest.mark.parametrize(
    ("data", "format"),
    [(_TABLE, "xlsx"), ({"title": "Sheet", "grid": {}}, "xlsx"), (_DOCUMENT, "docx")],
)
async def test_office_files_carry_the_stamp_in_core_properties(data, format):
    content = await _render(format, "task-table", data)
    core = zipfile.ZipFile(io.BytesIO(content)).read("docProps/core.xml").decode()
    assert re.search(r"<dc:creator[^>]*>Ada Lovelace</dc:creator>", core)
    assert "dcterms:created" in core
