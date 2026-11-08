"""Reading a Jira project into a bundle.

The load-bearing test is `test_the_bundle_is_one_the_backup_importer_reads`:
the whole design rests on a Jira import being a restore of something this app
could have exported, so if the applier cannot open what the fetch writes, the
idea does not hold. The rest is the paging and the failure behaviour — a
foreign server is allowed to be slow, partial, hostile or absent, and none of
those may take the job down with it.
"""

import io
import json
import zipfile

import httpx2
import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian, jira_fetch
from app.services.import_engine import limits as import_limits
from app.services.import_engine.atlassian_bundle import BundleWriter
from app.services.import_engine.atlassian_test import answered
from app.services.import_engine.contract import ImportEngineError


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """A throttled call retries after a wait; the tests take the retry and
    skip the wait."""

    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(atlassian, "_sleep", fake_sleep)


CREDENTIAL = atlassian.AtlassianCredential(
    site_url="https://acme.atlassian.net",
    email="someone@example.com",
    api_token="shhh",
)


def _issue(key, summary, status="To Do", **fields):
    return {
        "key": key,
        "fields": {"summary": summary, "status": {"name": status}, **fields},
    }


STATUSES = [
    {
        "name": "Story",
        "statuses": [
            {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
            {"id": "2", "name": "Done", "statusCategory": {"key": "done"}},
        ],
    }
]


def _site(monkeypatch, *, issues=None, pages=None, project_status=200, boards=True):
    """A Jira site answering the calls a fetch makes.

    ``pages`` is a list of (issues, next_token) for testing the walk; ``issues``
    is the single-page shorthand.
    """
    calls: list[dict] = []
    state = {"page": 0}

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "json": json})
        if "/rest/api/3/project/" in url and url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            if project_status != 200:
                return httpx2.Response(project_status, json={})
            key = url.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"key": key, "name": f"{key} Board"})
        if "/rest/agile/1.0/board?" in url:
            if not boards:
                return httpx2.Response(404, json={})
            return httpx2.Response(200, json={"values": [{"id": 7}]})
        if "/configuration" in url:
            return httpx2.Response(
                200,
                json={
                    "columnConfig": {
                        "columns": [
                            {"name": "Doing", "statuses": [{"id": "2"}]},
                            {"name": "Queue", "statuses": [{"id": "1"}]},
                        ]
                    }
                },
            )
        if "/rest/api/3/search/jql" in url:
            if pages is not None:
                idx = state["page"]
                state["page"] += 1
                if idx >= len(pages):
                    return httpx2.Response(200, json={"issues": []})
                page_issues, next_token = pages[idx]
                body = {"issues": page_issues}
                if next_token:
                    body["nextPageToken"] = next_token
                return httpx2.Response(200, json=body)
            return httpx2.Response(200, json={"issues": issues or []})
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


async def _bundle(monkeypatch, **kw):
    """:func:`fetch_projects`, written into a bundle of its own and read back
    whole."""
    with BundleWriter() as writer:
        fetched = await jira_fetch.fetch_projects(
            CREDENTIAL,
            project_keys=kw.pop("project_keys", ["ACME"]),
            guild_id=1,
            app_version="0.0.0-test",
            store=writer.put_asset,
            **kw,
        )
        bundle = writer.finish(
            projects=fetched.envelopes,
            task_files=fetched.files,
            calendars=fetched.calendars,
            images=fetched.images,
            people=fetched.people,
            guild_id=1,
            guild_name="Acme",
            target_initiative_id=42,
            app_version="0.0.0-test",
            site_url=CREDENTIAL.site_url,
        ).read_bytes()
    return bundle, fetched.report


# --- the bundle ------------------------------------------------------------


async def test_the_bundle_is_one_the_backup_importer_reads(monkeypatch):
    """The whole design rests on this: a Jira import is a restore of something
    this app could have exported, so the applier's own reader has to open what
    the fetch writes without knowing where it came from."""
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    _site(monkeypatch, issues=[_issue("ACME-1", "One"), _issue("ACME-2", "Two")])
    payload, report = await _bundle(monkeypatch)

    archive = open_zip(payload)
    manifest = read_manifest(archive)

    assert manifest.type == "initiative-backup"
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.tool == "project"
    assert entry.type == "initiative-project"

    # And the entry it names is really in there, and really an envelope.
    from app.schemas.tenant.project_export import ProjectExportEnvelope

    envelope = ProjectExportEnvelope.model_validate(
        json.loads(archive.read(entry.path))
    )
    assert [t.title for t in envelope.tasks] == ["One", "Two"]
    assert report.projects == 1 and report.tasks == 2


async def test_the_bundle_files_into_the_initiative_somebody_chose(monkeypatch):
    """A Jira project belongs in an initiative somebody already runs, not in a
    new one named after somebody else's site. That is what §8.2 was for."""
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)

    manifest = read_manifest(open_zip(payload))
    assert len(manifest.initiatives) == 1
    assert manifest.initiatives[0].target_initiative_id == 42


async def test_the_bundle_names_the_people_it_quotes(monkeypatch):
    """The wizard's people step is rendered from this."""
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    _site(
        monkeypatch,
        issues=[
            _issue("ACME-1", "One", assignee={"displayName": "Alice Chen"}),
            _issue("ACME-2", "Two", assignee={"displayName": "Alice Chen"}),
            _issue("ACME-3", "Three", assignee={"displayName": "Bob Ray"}),
        ],
    )
    payload, _ = await _bundle(monkeypatch)

    manifest = read_manifest(open_zip(payload))
    # Most-named first, so the row that matters most is at the top.
    assert [p.handle for p in manifest.people] == ["Alice Chen", "Bob Ray"]


async def test_the_bundle_holds_no_token(monkeypatch):
    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)
    assert b"shhh" not in payload


# --- the conversation ------------------------------------------------------


async def test_issues_are_asked_for_in_rank_order(monkeypatch):
    """Rank is what the team dragged them into, and the only ordering worth
    carrying across."""
    calls = _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    await _bundle(monkeypatch)

    search = [c for c in calls if "search/jql" in c["url"]]
    assert search and search[0]["method"] == "POST"
    assert search[0]["json"]["jql"] == 'project = "ACME" ORDER BY Rank ASC'


async def test_a_narrowing_narrows_rather_than_replaces(monkeypatch):
    """The selection is the project. A narrowing that could widen it would not
    be one."""
    calls = _site(monkeypatch, issues=[])
    await _bundle(monkeypatch, jql_extra="created >= -30d")

    jql = next(c for c in calls if "search/jql" in c["url"])["json"]["jql"]
    assert jql == 'project = "ACME" AND (created >= -30d) ORDER BY Rank ASC'


async def test_the_board_decides_the_column_order(monkeypatch):
    """The stub board puts Done before To Do; the workflow lists them the
    other way round. The board wins."""
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)
    archive = open_zip(payload)
    entry = read_manifest(archive).entries[0]
    envelope = json.loads(archive.read(entry.path))

    assert [s["name"] for s in envelope["task_statuses"]] == ["Done", "To Do"]


async def test_a_project_with_no_board_still_fetches(monkeypatch):
    """A project can have no board, and a board this token cannot read is the
    same thing. Neither is worth failing over."""
    _site(monkeypatch, issues=[_issue("ACME-1", "One")], boards=False)
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 1


async def test_paging_follows_the_cursor_to_the_end(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            ([_issue("ACME-1", "One")], "cursor-1"),
            ([_issue("ACME-2", "Two")], None),
        ],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 2


async def test_a_cursor_that_is_not_a_string_ends_the_walk(monkeypatch):
    """The cursor is the site's to hand back, so it is checked rather than
    trusted — otherwise a junk value drives the loop."""
    _site(
        monkeypatch,
        pages=[([_issue("ACME-1", "One")], 12345), ([_issue("ACME-2", "Two")], None)],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 1


async def test_the_row_budget_is_shared_across_projects(monkeypatch):
    """One enormous project must not eat the whole import's ceiling and leave
    the others empty without saying so."""

    monkeypatch.setattr(import_limits, "IMPORT_FETCH_MAX_ROWS", 3)
    _site(monkeypatch, issues=[_issue(f"ACME-{i}", f"Task {i}") for i in range(10)])
    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])

    assert report.tasks == 3
    assert report.projects == 1
    # Said, not merely done: one project was cut short and one left out.
    assert report.projects_over_limit == ["ACME", "OTHER"]


async def test_a_project_stopped_with_more_to_read_is_named(monkeypatch):
    """The budget ran out exactly at a page boundary, with the site still
    offering more: that project was not read in full either."""
    monkeypatch.setattr(import_limits, "IMPORT_FETCH_MAX_ROWS", 2)
    _site(
        monkeypatch,
        pages=[
            ([_issue("ACME-1", "One"), _issue("ACME-2", "Two")], "cursor-1"),
            ([_issue("ACME-3", "Three")], None),
        ],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 2
    assert report.projects_over_limit == ["ACME"]


async def test_a_project_read_to_its_end_is_not_named(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            ([_issue("ACME-1", "One")], "cursor-1"),
            ([_issue("ACME-2", "Two")], None),
        ],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.projects_over_limit == []


# --- when the site misbehaves ----------------------------------------------


async def test_an_unreadable_project_is_counted_not_fatal(monkeypatch):
    """Somebody who ticked two projects and can reach one should get the one
    and be told about the other."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/api/3/project/LOCKED" in url and not url.endswith("/statuses"):
            return httpx2.Response(403, json={})
        if "/rest/api/3/project/" in url and url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"key": key, "name": key})
        if "/rest/agile/1.0/board?" in url:
            return httpx2.Response(404, json={})
        if "search/jql" in url:
            return httpx2.Response(200, json={"issues": [_issue("ACME-1", "One")]})
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "LOCKED"])

    assert report.projects == 1
    assert report.unreadable_projects == ["LOCKED"]


async def test_progress_hears_every_project_read_or_not(monkeypatch):
    """The job row climbs one project at a time, and a locked project is
    still a step taken — otherwise a fetch stuck behind it looks stalled."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/api/3/project/LOCKED" in url:
            return httpx2.Response(403, json={})
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"key": key, "name": key})
        if "search/jql" in url:
            return httpx2.Response(200, json={"issues": [_issue("ACME-1", "One")]})
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    heard: list[tuple[int, int, list[str]]] = []

    async def progress(report):
        heard.append((report.projects, report.tasks, list(report.unreadable_projects)))

    await _bundle(monkeypatch, project_keys=["ACME", "LOCKED"], progress=progress)

    assert heard == [(1, 1, []), (1, 1, ["LOCKED"])]


async def test_a_progress_listener_can_stop_the_walk(monkeypatch):
    """What a cancel looks like from in here: the listener raises, and no
    further project is asked for."""
    calls = _site(monkeypatch, issues=[_issue("ACME-1", "One")])

    class Stop(Exception):
        pass

    async def progress(report):
        raise Stop

    with pytest.raises(Stop):
        await _bundle(monkeypatch, project_keys=["ACME", "OTHER"], progress=progress)
    assert not any("/project/OTHER" in call["url"] for call in calls)


async def test_every_project_unreadable_is_a_failure(monkeypatch):
    """That is the selection being wrong, not one project being locked."""
    _site(monkeypatch, project_status=403)
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_being_throttled_stops_the_whole_fetch(monkeypatch):
    """Rate limiting is about the site, not one project — the next project
    would be throttled too, and hammering it is how a short block becomes a
    long one."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        return httpx2.Response(429, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED


async def test_nothing_selected_is_its_own_answer(monkeypatch):
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch, project_keys=[])
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED


async def test_what_the_description_lost_is_reported(monkeypatch):
    """The honest half of the degradation contract: the plan says what will be
    lost before anybody commits to the import."""
    _site(
        monkeypatch,
        issues=[
            _issue(
                "ACME-1",
                "One",
                description={
                    "type": "doc",
                    "content": [{"type": "somethingNew", "attrs": {"x": 1}}],
                },
            )
        ],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.dropped_nodes == 1


async def test_a_malformed_issue_is_counted_as_skipped(monkeypatch):
    _site(monkeypatch, issues=[_issue("ACME-1", "Good"), {"key": "ACME-2"}])
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 1
    assert report.skipped_issues == 1


async def test_the_zip_stays_inside_the_members_bound(monkeypatch):
    """open_zip refuses an archive with too many members, so the fetch
    must not build one it would then refuse."""
    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert len(archive.infolist()) == 2  # manifest + one envelope


async def test_a_throttled_board_lookup_is_not_mistaken_for_no_board(monkeypatch):
    """A board the token cannot read is fine to do without; a site that is
    throttling us is not the same thing, and importing without the column
    order would hide it."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/agile/1.0/board" in url:
            return httpx2.Response(429, json={})
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            return httpx2.Response(200, json={"key": "ACME", "name": "ACME"})
        return httpx2.Response(200, json={"issues": []})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED


# --- links -------------------------------------------------------------------


def _two_projects(monkeypatch, issues_by_project):
    """A site with a project per key, each answering its own issues."""
    calls: list[dict] = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"url": url, "json": json})
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"key": key, "name": key})
        if "search/jql" in url and json is not None:
            key = json["jql"].split('"')[1]
            return httpx2.Response(200, json={"issues": issues_by_project[key]})
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


def _blocked_by(key, blocker, link_id):
    return {
        "id": link_id,
        "type": {"name": "Blocks", "outward": "blocks"},
        "inwardIssue": {"key": blocker},
    }


def _blocks_link(key, blocked, link_id):
    return {
        "id": link_id,
        "type": {"name": "Blocks", "outward": "blocks"},
        "outwardIssue": {"key": blocked},
    }


async def test_links_are_asked_for(monkeypatch):
    calls = _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    await _bundle(monkeypatch)
    search = next(c for c in calls if "search/jql" in c["url"])
    # Every navigable field, which carries the links and the parent too: which
    # of a site's fields anybody filled in is only known by reading them.
    assert search["json"]["fields"][0] == "*navigable"


async def test_links_are_counted_once_and_split_by_whether_both_ends_came(
    monkeypatch,
):
    """Both sides of a Jira link report it, so it is counted by id. A link
    between two ticked projects will be drawn; one to an issue nobody ticked
    will not, and the plan says how many before anybody confirms."""
    _two_projects(
        monkeypatch,
        {
            "ACME": [
                _issue(
                    "ACME-1",
                    "Fit it",
                    issuelinks=[_blocks_link("ACME-1", "ACME-2", "10")],
                ),
                _issue(
                    "ACME-2",
                    "Hang it",
                    parent={"key": "ACME-1"},
                    issuelinks=[
                        _blocked_by("ACME-2", "ACME-1", "10"),
                        _blocked_by("ACME-2", "OPS-1", "11"),
                    ],
                ),
            ],
            "OPS": [
                _issue(
                    "OPS-1",
                    "Order hinges",
                    issuelinks=[
                        _blocks_link("OPS-1", "ACME-2", "11"),
                        _blocked_by("OPS-1", "HR-4", "12"),
                    ],
                )
            ],
        },
    )

    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "OPS"])

    # Drawn: 10 (ACME-1 blocks ACME-2), 11 (OPS-1 blocks ACME-2, across the
    # two projects), and ACME-2's parent. Not: 12, whose far end is in a
    # project nobody ticked.
    assert report.links == 3
    assert report.links_outside_selection == 1


async def test_the_links_land_in_the_bundle(monkeypatch):
    _site(
        monkeypatch,
        issues=[
            _issue("ACME-1", "Fit it"),
            _issue(
                "ACME-2",
                "Hang it",
                issuelinks=[_blocked_by("ACME-2", "ACME-1", "10")],
            ),
        ],
    )
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    payload, _report = await _bundle(monkeypatch)
    archive = open_zip(payload)
    manifest = read_manifest(archive)
    envelope = json.loads(archive.read(manifest.entries[0].path))
    assert envelope["tasks"][1]["links"] == [
        {"type": "depends_on", "target_external_ref": "jira:ACME-1"}
    ]


# --- fields ------------------------------------------------------------------


async def test_the_field_catalog_is_read_once_and_counts_sum_across_projects(
    monkeypatch,
):
    """The catalog is the site's, not a project's, so one read serves every
    project; and the same field on two boards is one property in the
    initiative they land in, carried by every task that filled it."""
    catalog_calls = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if url.endswith("/rest/api/3/field"):
            catalog_calls.append(url)
            return httpx2.Response(
                200,
                json=[
                    {
                        "id": "customfield_1",
                        "name": "Story points",
                        "custom": True,
                        "schema": {"type": "number"},
                    }
                ],
            )
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"key": key, "name": key})
        if "search/jql" in url and json is not None:
            key = json["jql"].split('"')[1]
            return httpx2.Response(
                200,
                json={"issues": [_issue(f"{key}-1", "One", customfield_1=3)]},
            )
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "OPS"])

    assert len(catalog_calls) == 1
    assert report.properties["Story points"] == ("number", 2)
    assert report.properties["Jira key"] == ("text", 2)


async def test_a_catalog_the_site_will_not_give_is_not_fatal(monkeypatch):
    """The built-ins still map by their own ids; only a site's own fields go
    untyped, and are left out."""
    _site(monkeypatch, issues=[_issue("ACME-1", "One", priority={"name": "High"})])
    _payload, report = await _bundle(monkeypatch)
    assert report.properties["Priority"] == ("select", 1)


# --- sprints -----------------------------------------------------------------


def _sprint_site(monkeypatch, issues):
    catalog = [
        {
            "id": "customfield_10020",
            "name": "Sprint",
            "custom": True,
            "schema": {
                "type": "array",
                "custom": "com.pyxis.greenhopper.jira:gh-sprint",
            },
        }
    ]

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if url.endswith("/rest/api/3/field"):
            return httpx2.Response(200, json=catalog)
        if "/rest/agile/1.0/board/3" in url:
            return httpx2.Response(200, json={"id": 3, "name": "Door team"})
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            return httpx2.Response(200, json={"key": "ACME", "name": "ACME"})
        if "search/jql" in url:
            return httpx2.Response(200, json={"issues": issues})
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)


def _sprinted(key, *sprint_ids):
    return _issue(
        key,
        key,
        customfield_10020=[
            {
                "id": sprint_id,
                "name": f"Sprint {sprint_id}",
                "boardId": 3,
                "startDate": "2024-03-04T09:00:00.000Z",
                "endDate": "2024-03-18T09:00:00.000Z",
            }
            for sprint_id in sprint_ids
        ],
    )


async def test_sprints_ride_in_the_bundle_as_a_calendar_its_tasks_point_at(
    monkeypatch,
):
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    _sprint_site(monkeypatch, [_sprinted("ACME-1", 7), _sprinted("ACME-2", 7, 8)])
    payload, report = await _bundle(monkeypatch)

    assert (report.sprints, report.sprint_calendars, report.sprints_undated) == (
        2,
        1,
        0,
    )
    archive = open_zip(payload)
    manifest = read_manifest(archive)
    calendar_entry = next(e for e in manifest.entries if e.tool == "calendar")
    assert manifest.initiatives[0].tools["calendar"] == "included"
    calendar = json.loads(archive.read(calendar_entry.path))
    assert calendar["name"] == "Door team"
    assert [e["external_ref"] for e in calendar["events"]] == [
        "jira-sprint:7",
        "jira-sprint:8",
    ]
    project = json.loads(
        archive.read(next(e for e in manifest.entries if e.tool == "project").path)
    )
    links = {t["external_ref"]: t["links"] for t in project["tasks"]}
    assert {"type": "related_to", "target_external_ref": "jira-sprint:8"} in links[
        "jira:ACME-2"
    ]


async def test_sprints_blocked_by_the_target_are_counted_and_left_out(monkeypatch):
    """Counted, so the plan can say what is being left behind; and no task is
    pointed at a sprint that will not exist."""
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    _sprint_site(monkeypatch, [_sprinted("ACME-1", 7)])
    payload, report = await _bundle(
        monkeypatch, sprints_blocked_by="IMPORT_TOOL_DISABLED"
    )

    assert report.sprints == 1
    assert report.sprint_calendars == 0
    assert report.sprints_skipped == "IMPORT_TOOL_DISABLED"
    manifest = read_manifest(open_zip(payload))
    assert [e.tool for e in manifest.entries] == ["project"]
    project = json.loads(open_zip(payload).read(manifest.entries[0].path))
    assert project["tasks"][0]["links"] == []


# --- comments ----------------------------------------------------------------


def _adf(text):
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _comment(author, text, created, **extra):
    return {
        "author": {"displayName": author},
        "body": _adf(text),
        "created": created,
        **extra,
    }


async def test_comments_come_with_their_issue_and_the_rest_are_paged_in(monkeypatch):
    """The search carries the first page and a total; only an issue with more
    than that costs a call of its own, and the whole thread arrives."""
    comment_calls = []

    first = [_comment("Robin", "One", "2024-03-04T09:00:00.000+0000")]
    rest = [
        _comment("Robin", "One", "2024-03-04T09:00:00.000+0000"),
        _comment("Sam", "Two", "2024-03-05T09:00:00.000+0000"),
    ]

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/comment?" in url:
            comment_calls.append(url)
            return httpx2.Response(200, json={"comments": rest, "total": 2})
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            return httpx2.Response(200, json={"key": "ACME", "name": "ACME"})
        if "search/jql" in url:
            assert json is not None and "comment" in json["fields"]
            return httpx2.Response(
                200,
                json={
                    "issues": [
                        _issue(
                            "ACME-1", "Long", comment={"comments": first, "total": 2}
                        ),
                        _issue(
                            "ACME-2",
                            "Short",
                            comment={
                                "comments": [
                                    _comment(
                                        "Ash", "Hi", "2024-03-06T09:00:00.000+0000"
                                    )
                                ],
                                "total": 1,
                            },
                        ),
                    ]
                },
            )
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    payload, report = await _bundle(monkeypatch)

    assert len(comment_calls) == 1 and "/issue/ACME-1/comment" in comment_calls[0]
    assert report.comments == 3
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    archive = open_zip(payload)
    manifest = read_manifest(archive)
    envelope = json.loads(archive.read(manifest.entries[0].path))
    assert [c["body"] for c in envelope["tasks"][0]["comments"]] == ["One", "Two"]
    people = {p.handle: p.comment_count for p in manifest.people}
    assert people == {"Robin": 1, "Sam": 1, "Ash": 1}


async def test_comments_can_be_left_behind(monkeypatch):
    calls = _site(
        monkeypatch,
        issues=[
            _issue(
                "ACME-1",
                "One",
                comment={
                    "comments": [
                        _comment("Robin", "Hi", "2024-03-04T09:00:00.000+0000")
                    ],
                    "total": 1,
                },
            )
        ],
    )
    payload, report = await _bundle(monkeypatch, include_comments=False)
    search = next(c for c in calls if "search/jql" in c["url"])
    assert "comment" not in search["json"]["fields"]
    assert report.comments == 0

    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    archive = open_zip(payload)
    envelope = json.loads(archive.read(read_manifest(archive).entries[0].path))
    assert envelope["tasks"][0]["comments"] == []


async def test_comments_spend_the_row_budget(monkeypatch):
    """A comment is a row. Two issues with two comments each fill a budget of
    four, so the next project is not started."""

    thread = {
        "comments": [
            _comment("Robin", "a", "2024-03-04T09:00:00.000+0000"),
            _comment("Robin", "b", "2024-03-05T09:00:00.000+0000"),
        ],
        "total": 2,
    }
    _site(monkeypatch, issues=[_issue("ACME-1", "One", comment=thread)])
    monkeypatch.setattr(import_limits, "IMPORT_FETCH_MAX_ROWS", 3)
    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])
    assert report.projects == 1
    assert report.projects_over_limit == ["OTHER"]


# --- images --------------------------------------------------------------------


def _image_site(monkeypatch, issues, content=b"\x89PNG-bytes"):
    calls: list[dict] = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"url": url, "json": json})
        if "/attachment/content/" in url:
            return await answered(
                method, url, httpx2.Response(200, content=content), kw
            )
        if url.endswith("/statuses"):
            return httpx2.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            return httpx2.Response(200, json={"key": "ACME", "name": "ACME"})
        if "search/jql" in url:
            return httpx2.Response(200, json={"issues": issues})
        return httpx2.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


def _with_image(key, filename="door.png", att_id="10"):
    return _issue(
        key,
        key,
        attachment=[
            {"id": att_id, "filename": filename, "mimeType": "image/png", "size": 11}
        ],
    )


async def test_images_ride_in_the_bundle_as_assets_the_task_points_at(monkeypatch):
    """Restored by the ordinary backup apply under a key made here: the
    manifest lists it, the zip holds it, and the task shows it."""
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    calls = _image_site(monkeypatch, [_with_image("ACME-1")])
    payload, report = await _bundle(monkeypatch)

    search = next(c for c in calls if "search/jql" in c["url"])
    assert "attachment" in search["json"]["fields"]
    download = next(c for c in calls if "/attachment/content/" in c["url"])
    assert download["url"].endswith("/attachment/content/10?redirect=false")
    assert (report.images, report.image_bytes) == (1, len(b"\x89PNG-bytes"))

    archive = open_zip(payload)
    manifest = read_manifest(archive)
    (asset,) = manifest.assets
    assert asset.original_filename == "door.png"
    assert archive.read(asset.path) == b"\x89PNG-bytes"
    envelope = json.loads(archive.read(manifest.entries[0].path))
    assert f"/uploads/1/{asset.storage_key}" in envelope["tasks"][0]["description"]


async def test_images_can_be_left_behind(monkeypatch):
    from app.services.import_engine.backup import read_manifest
    from app.services.import_engine.zip_bounds import open_zip

    calls = _image_site(monkeypatch, [_with_image("ACME-1")])
    payload, report = await _bundle(monkeypatch, include_attachments=False)
    assert not [c for c in calls if "/attachment/content/" in c["url"]]
    assert report.images == 0
    assert read_manifest(open_zip(payload)).assets == []


async def test_a_cancel_reaches_a_fetch_inside_one_project(monkeypatch):
    """Progress is heard between pages too, not only between projects, so a
    cancel stops a large project part way through."""
    monkeypatch.setattr(atlassian, "HEARTBEAT_SECONDS", 0)
    calls = _site(
        monkeypatch,
        pages=[
            ([_issue("ACME-1", "One")], "cursor-1"),
            ([_issue("ACME-2", "Two")], None),
        ],
    )

    class Stop(Exception):
        pass

    async def progress(report):
        raise Stop

    with pytest.raises(Stop):
        await _bundle(monkeypatch, progress=progress)
    assert sum("search/jql" in call["url"] for call in calls) == 1
