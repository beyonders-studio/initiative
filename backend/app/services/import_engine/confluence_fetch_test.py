"""Reading Confluence spaces into a bundle: the calls, the paging, and what a
site that is slow, partial or absent does to it."""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian, confluence_fetch
from app.services.import_engine.atlassian_bundle import BundleWriter, merge_people
from app.services.import_engine.atlassian_test import answered
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.jira_attachments import bundle_budget


CREDENTIAL = atlassian.AtlassianCredential(
    site_url="https://acme.atlassian.net",
    email="someone@example.com",
    api_token="shhh",
)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(atlassian, "_sleep", fake_sleep)


def _page(page_id, title, parent=None, parent_type="page", position=0, body=None):
    return {
        "id": str(page_id),
        "title": title,
        "parentId": str(parent) if parent else None,
        "parentType": parent_type if parent else None,
        "position": position,
        "authorId": "acc-1",
        "createdAt": "2024-03-04T09:00:00.000Z",
        "version": {"createdAt": "2024-05-01T10:00:00.000Z"},
        "body": {"storage": {"value": body or f"<p>{title} body</p>"}},
    }


def _site(
    monkeypatch,
    *,
    pages=None,
    batches=None,
    folders=None,
    labels=None,
    users=None,
    locked=(),
    throttled=False,
    attachments=None,
    files=None,
    comments=None,
):
    """A Confluence site. ``batches`` pages the listing: a list of page lists,
    each followed by a ``next`` link but the last."""
    calls: list[dict] = []
    folders = folders or {}
    labels = labels or {}
    names: dict[str, str] = users if users is not None else {"acc-1": "Robin Ade"}
    batches = batches if batches is not None else [pages or []]
    attachments = attachments or {}
    files = files or {}
    comments = comments or {}

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "json": json, "headers": headers})
        if throttled:
            return httpx.Response(429, json={})
        if "/wiki/api/v2/spaces?keys=" in url:
            key = url.split("keys=")[1].split("&")[0]
            if key in locked:
                return httpx.Response(200, json={"results": []})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": f"9{key}",
                            "key": key,
                            "name": f"{key} space",
                            "homepageId": "1",
                        }
                    ]
                },
            )
        if "/pages?" in url and "/spaces/" in url:
            index = int(url.split("cursor=")[1]) if "cursor=" in url else 0
            body = {"results": batches[index]}
            if index + 1 < len(batches):
                body["_links"] = {
                    "next": url.split("/wiki")[1].split("&cursor=")[0]
                    + f"&cursor={index + 1}"
                }
            return httpx.Response(200, json=body)
        if "-comments" in url:
            # ``/pages/{id}/footer-comments`` and ``/footer-comments/{id}/children``
            # both answer from one map, keyed by what the path names.
            path = url.split("/wiki/api/v2/")[1].split("?")[0]
            return httpx.Response(200, json={"results": comments.get(path, [])})
        if "/attachments?" in url:
            page_id = url.split("/pages/")[1].split("/")[0]
            return httpx.Response(200, json={"results": attachments.get(page_id, [])})
        if "/child/attachment/" in url:
            # The site hands a download on to the media host.
            att_id = url.split("/child/attachment/")[1].split("/")[0]
            return httpx.Response(
                302, headers={"location": f"https://media.example.com/{att_id}"}
            )
        if url.startswith("https://media.example.com/"):
            att_id = url.rsplit("/", 1)[1]
            if att_id in files:
                return await answered(
                    method, url, httpx.Response(200, content=files[att_id]), kw
                )
            return httpx.Response(404)
        if "/labels" in url:
            page_id = url.split("/pages/")[1].split("/")[0]
            return httpx.Response(
                200, json={"results": [{"name": n} for n in labels.get(page_id, [])]}
            )
        if "/wiki/api/v2/folders/" in url:
            folder_id = url.rsplit("/", 1)[1]
            if folder_id in folders:
                return httpx.Response(200, json=folders[folder_id])
            return httpx.Response(404, json={})
        if url.endswith("/wiki/api/v2/users-bulk"):
            wanted = (json or {}).get("accountIds") or []
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"accountId": a, "displayName": names[a]}
                        for a in wanted
                        if a in names
                    ]
                },
            )
        return httpx.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


async def _bundle(**kw):
    """:func:`fetch_spaces`, written into a bundle of its own and read back
    whole."""
    with BundleWriter() as writer:
        fetched = await confluence_fetch.fetch_spaces(
            CREDENTIAL,
            space_keys=kw.pop("space_keys", ["DOCS"]),
            guild_id=1,
            app_version="0.0.0-test",
            store=writer.put_asset,
            **kw,
        )
        bundle = writer.finish(
            images=fetched.images,
            wikis=fetched.envelopes,
            wiki_files=fetched.files,
            people=merge_people([], fetched.people),
            guild_id=1,
            guild_name="acme.atlassian.net",
            target_initiative_id=42,
            app_version="0.0.0-test",
            site_url=CREDENTIAL.site_url,
        ).read_bytes()
    return bundle, fetched.report


def _open(bundle: bytes) -> tuple[dict, dict[str, dict]]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        envelopes = {
            e["path"]: json.loads(archive.read(e["path"])) for e in manifest["entries"]
        }
    return manifest, envelopes


async def test_a_space_becomes_a_wiki_in_the_chosen_initiative(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            _page(1, "Home"),
            _page(
                2,
                "Guide",
                parent=1,
                body='<p>Ask <ac:link><ri:user ri:account-id="acc-2"/></ac:link></p>',
            ),
        ],
        labels={"2": ["howto"]},
        users={"acc-1": "Robin Ade", "acc-2": "Sam Bee"},
    )
    bundle, report = await _bundle()
    manifest, envelopes = _open(bundle)
    (initiative,) = manifest["initiatives"]
    assert initiative["target_initiative_id"] == 42
    assert initiative["tools"] == {"wiki": "included"}
    (entry,) = manifest["entries"]
    assert entry["tool"] == "wiki" and entry["type"] == "initiative-wiki"
    wiki = envelopes[entry["path"]]
    assert wiki["name"] == "DOCS space" and wiki["home_page"] == "home"
    guide = wiki["pages"][1]
    assert guide["parent"] == "home" and guide["tags"] == ["howto"]
    assert guide["author_handle"] == "Robin Ade"
    assert guide["mention_handles"] == ["Sam Bee"]
    assert [p["handle"] for p in manifest["people"]] == ["Robin Ade", "Sam Bee"]
    assert (report.spaces, report.pages, report.labels) == (1, 2, 1)


async def test_the_bundle_is_one_the_backup_importer_reads(monkeypatch):
    from app.services.import_engine import backup

    _site(monkeypatch, pages=[_page(1, "Home")])
    bundle, _report = await _bundle()
    plan = backup.plan_backup(
        bundle, existing_initiative_names=set(), member_ids_by_handle={}
    )
    assert plan.initiatives[0].target_initiative_id == 42


async def test_every_page_of_the_listing_is_read(monkeypatch):
    calls = _site(
        monkeypatch,
        batches=[[_page(1, "One")], [_page(2, "Two")], [_page(3, "Three")]],
    )
    _bundle_bytes, report = await _bundle()
    assert report.pages == 3
    assert report.spaces_over_limit == []
    listing = [c["url"] for c in calls if "/pages?" in c["url"]]
    assert len(listing) == 3
    # Current pages, with their bodies, in the one format the walker reads.
    assert "body-format=storage" in listing[0] and "status=current" in listing[0]


async def test_a_page_in_a_folder_is_filed_under_it(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            _page(1, "Home"),
            _page(2, "Login", parent=60, parent_type="folder"),
        ],
        folders={
            "60": {
                "id": "60",
                "title": "Designs",
                "parentId": "50",
                "parentType": "folder",
            },
            "50": {
                "id": "50",
                "title": "Product",
                "parentId": "1",
                "parentType": "page",
            },
        },
    )
    bundle, report = await _bundle()
    _manifest, envelopes = _open(bundle)
    (wiki,) = envelopes.values()
    parents = {p["title"]: p["parent"] for p in wiki["pages"]}
    assert parents == {
        "Home": None,
        "Product": "home",
        "Designs": "product",
        "Login": "designs",
    }
    assert report.containers == 2


async def test_a_space_the_token_cannot_read_is_named_not_fatal(monkeypatch):
    _site(monkeypatch, pages=[_page(1, "Home")], locked=("SECRET",))
    bundle, report = await _bundle(space_keys=["SECRET", "DOCS"])
    manifest, _envelopes = _open(bundle)
    assert report.unreadable_spaces == ["SECRET"]
    assert report.spaces == 1 and len(manifest["entries"]) == 1


async def test_nothing_readable_fails_the_fetch(monkeypatch):
    _site(monkeypatch, locked=("SECRET",))
    with pytest.raises(ImportEngineError) as caught:
        await _bundle(space_keys=["SECRET"])
    assert caught.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_nothing_ticked_is_refused_before_a_call(monkeypatch):
    calls = _site(monkeypatch)
    with pytest.raises(ImportEngineError) as caught:
        await _bundle(space_keys=[])
    assert caught.value.code == ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED
    assert calls == []


async def test_being_throttled_stops_the_fetch(monkeypatch):
    _site(monkeypatch, throttled=True)
    with pytest.raises(ImportEngineError) as caught:
        await _bundle()
    assert caught.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED


async def test_progress_hears_each_space_and_can_stop_the_walk(monkeypatch):
    _site(monkeypatch, pages=[_page(1, "Home")])
    heard: list[int] = []

    class Stop(Exception):
        pass

    async def progress(report):
        heard.append(report.spaces)
        raise Stop

    with pytest.raises(Stop):
        await _bundle(space_keys=["DOCS", "MORE"], progress=progress)
    assert heard == [1]


async def test_a_pages_attachments_come_as_uploads_and_files_in_its_wiki(
    monkeypatch,
):
    calls = _site(
        monkeypatch,
        pages=[
            _page(
                1,
                "Home",
                body=(
                    '<p><ac:image><ri:attachment ri:filename="chart.png"/></ac:image>'
                    '<ac:link><ri:attachment ri:filename="spec.pdf"/></ac:link></p>'
                ),
            )
        ],
        attachments={
            "1": [
                {
                    "id": "att1",
                    "title": "chart.png",
                    "mediaType": "image/png",
                    "fileSize": 4,
                },
                {
                    "id": "att2",
                    "title": "spec.pdf",
                    "mediaType": "application/pdf",
                    "fileSize": 4,
                },
                {"id": "att3", "title": "gone.pdf", "mediaType": "application/pdf"},
            ]
        },
        files={"att1": b"\x89PNG", "att2": b"%PDF"},
    )
    bundle, report = await _bundle(asset_budget=bundle_budget())
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    wiki_entry, file_entry = manifest["entries"]
    pdf_key = file_entry["asset"].removeprefix("assets/")
    assert file_entry["type"] == "file" and file_entry["tool"] == "file"
    assert (
        file_entry["title"] == "spec.pdf" and file_entry["path"] == file_entry["asset"]
    )
    assert file_entry["attach_to"] == {
        "kind": "wiki",
        "ref": wiki_entry["path"],
        "page": "home",
    }
    assert manifest["initiatives"][0]["tools"] == {
        "wiki": "included",
        "file": "included",
    }
    assert {a["original_filename"] for a in manifest["assets"]} == {
        "chart.png",
        "spec.pdf",
    }

    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        wiki = json.loads(archive.read(wiki_entry["path"]))
        assert archive.read(file_entry["asset"]) == b"%PDF"
    (paragraph,) = wiki["pages"][0]["content"]["root"]["children"]
    image, mention = paragraph["children"]
    assert image["src"].startswith("/uploads/1/") and image["src"].endswith(".png")
    assert mention["importRef"] == f"entry:assets/{pdf_key}"

    assert (report.images, report.files, report.attachment_bytes) == (1, 1, 8)
    assert report.attachments_skipped == 1 and report.attachments == 0
    # The download went on to the media host without the site's token.
    hop = next(c for c in calls if c["url"].startswith("https://media.example.com/"))
    assert "Authorization" not in (hop["headers"] or {})


async def test_without_a_budget_no_attachment_is_asked_for(monkeypatch):
    calls = _site(
        monkeypatch,
        pages=[
            _page(
                1,
                "Home",
                body='<p><ac:link><ri:attachment ri:filename="spec.pdf"/></ac:link></p>',
            )
        ],
    )
    _bundle_bytes, report = await _bundle()
    assert not [c for c in calls if "attachment" in c["url"]]
    # The file the page links to is named as staying behind.
    assert report.attachments == 1


def _comment(comment_id, body, author="acc-1"):
    return {
        "id": str(comment_id),
        "version": {"authorId": author, "createdAt": "2024-05-01T10:00:00.000Z"},
        "body": {"storage": {"value": body}},
    }


async def test_a_pages_comments_come_with_it_replies_and_all(monkeypatch):
    calls = _site(
        monkeypatch,
        pages=[_page(1, "Home")],
        users={"acc-1": "Robin Ade", "acc-2": "Sam Bee"},
        comments={
            "pages/1/footer-comments": [_comment(10, "<p>First</p>")],
            "footer-comments/10/children": [_comment(11, "<p>Reply</p>", "acc-2")],
            "pages/1/inline-comments": [
                {
                    **_comment(20, "<p>Fix this</p>"),
                    "properties": {"inlineOriginalSelection": "teh"},
                },
                # Resolved: the discussion is over, so it and its replies stay.
                {**_comment(21, "<p>Done already</p>"), "resolutionStatus": "resolved"},
            ],
            "inline-comments/21/children": [_comment(22, "<p>Thanks</p>")],
        },
    )
    bundle, report = await _bundle(include_comments=True)
    _manifest, envelopes = _open(bundle)
    (wiki,) = envelopes.values()
    first, reply, inline = wiki["pages"][0]["comments"]
    assert reply["reply_to_ref"] == first["external_ref"]
    assert reply["author_handle"] == "Sam Bee"
    assert inline["content"]["root"]["children"][0]["type"] == "quote"
    assert report.comments == 3
    assert report.comments_resolved == 1
    assert not [c for c in calls if "inline-comments/21/children" in c["url"]]
    # Both kinds are asked for, with their bodies.
    asked = [c["url"] for c in calls if "-comments" in c["url"]]
    assert any("/pages/1/footer-comments?body-format=storage" in u for u in asked)
    assert any("/pages/1/inline-comments?body-format=storage" in u for u in asked)


async def test_comments_are_not_asked_for_unless_wanted(monkeypatch):
    calls = _site(monkeypatch, pages=[_page(1, "Home")])
    await _bundle()
    assert not [c for c in calls if "-comments" in c["url"]]


def test_a_next_link_that_is_not_the_listing_is_not_followed():
    assert confluence_fetch._next_path({"_links": {"next": "/api/v2/x?cursor=2"}}) == (
        "/wiki/api/v2/x?cursor=2"
    )
    assert (
        confluence_fetch._next_path({"_links": {"next": "https://evil.example/"}})
        is None
    )
    assert confluence_fetch._next_path({"_links": {"next": "/wiki/rest/api/x"}}) is None
    assert confluence_fetch._next_path({}) is None


async def test_spaces_the_row_budget_cut_are_named(monkeypatch):
    """A space whose listing was stopped by the budget, and every space after
    it, are named in the plan rather than quietly shortened."""
    _site(
        monkeypatch,
        batches=[[_page(1, "One"), _page(2, "Two")], [_page(3, "Three")]],
    )
    _bundle_bytes, report = await _bundle(space_keys=["DOCS", "MORE"], max_rows=3)
    assert report.pages == 2
    assert report.spaces_over_limit == ["DOCS", "MORE"]
