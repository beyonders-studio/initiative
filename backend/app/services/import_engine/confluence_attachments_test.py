"""A Confluence page's attachments: which come, as what, and what is counted
instead."""

from __future__ import annotations

import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import confluence_attachments as ca
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.jira_attachments import AssetBudget


def attachment(att_id, filename, media_type, size=10):
    return ca.PageAttachment(
        id=att_id, filename=filename, media_type=media_type, size=size
    )


def test_a_listing_is_read_and_anything_malformed_skipped():
    found = ca.read_attachments(
        {
            "results": [
                {
                    "id": "att101",
                    "title": "chart.png",
                    "mediaType": "IMAGE/PNG",
                    "fileSize": 12,
                },
                {"id": "att102", "title": "  "},
                # The id goes into a path on the site.
                {"id": "../../x", "title": "sneaky.pdf"},
                {"id": "103", "title": "spec.pdf", "fileSize": True},
                "nonsense",
            ]
        }
    )
    assert found == [
        attachment("att101", "chart.png", "image/png", 12),
        attachment("103", "spec.pdf", "", 0),
    ]
    assert ca.read_attachments("nope") == []


async def _download(attachments, *, bytes_left=10_000, files_left=100, **kw):
    blobs = kw.pop("blobs", {})
    failures = kw.pop("failures", {})
    budget = AssetBudget(bytes_left=bytes_left, files_left=files_left)
    report = ca.AttachmentReport()

    async def download(item, max_bytes):
        if item.id in failures:
            raise ImportEngineError(failures[item.id])
        return blobs.get(item.id, b"x" * item.size)

    async def store(stored, data):
        pass

    media = await ca.download_page_attachments(
        attachments,
        guild_id=7,
        download=download,
        store=store,
        budget=budget,
        report=report,
        **kw,
    )
    return media, report, budget


async def test_pictures_render_from_their_upload_and_other_files_wait_to_be_files():
    media, report, budget = await _download(
        [
            attachment("1", "chart.png", "image/png"),
            attachment("2", "spec.pdf", "application/pdf"),
            attachment("3", "counts.csv", "text/csv"),
            attachment("4", "setup.exe", "application/x-msdownload"),
        ]
    )
    # A table of text comes over to become a spreadsheet; a program does not
    # come at all.
    assert set(media.files) == {"spec.pdf", "counts.csv"}
    assert report.refused == 1
    stored = media.stored_images["chart.png"]
    assert media.images == {"chart.png": f"/uploads/7/{stored.storage_key}"}
    assert stored.storage_key.endswith(".png")
    pdf = media.files["spec.pdf"]
    # A fresh key, never the site's filename; the extension is kept.
    assert pdf.storage_key.endswith(".pdf") and "spec" not in pdf.storage_key
    assert report.bytes == 30
    assert (budget.bytes_left, budget.files_left) == (9_970, 97)
    assert ca.file_ref(pdf) == f"entry:assets/{pdf.storage_key}"


async def test_what_does_not_fit_is_counted_not_fetched():
    media, report, _budget = await _download(
        [
            attachment("1", "huge.png", "image/png", ca.MAX_IMAGE_BYTES + 1),
            attachment("2", "huge.pdf", "application/pdf", ca.MAX_FILE_BYTES + 1),
            attachment("3", "logo.svg", "image/svg+xml"),
            attachment("4", "past-budget.pdf", "application/pdf", 600),
        ],
        bytes_left=500,
    )
    assert media.files == {} and media.stored_images == {}
    assert (report.oversize, report.refused) == (3, 1)


async def test_the_budget_counts_files_as_well_as_bytes():
    media, report, _budget = await _download(
        [
            attachment("1", "a.pdf", "application/pdf"),
            attachment("2", "b.pdf", "application/pdf"),
        ],
        files_left=1,
    )
    assert list(media.files) == ["a.pdf"]
    assert report.oversize == 1


async def test_a_file_that_will_not_come_is_counted_and_throttling_stops_the_fetch():
    media, report, _budget = await _download(
        [
            attachment("1", "gone.pdf", "application/pdf"),
            attachment("2", "lied.pdf", "application/pdf"),
            attachment("3", "fine.pdf", "application/pdf"),
        ],
        failures={
            "1": ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE,
            "2": ImportEngineMessages.IMPORT_TOO_LARGE,
        },
    )
    assert list(media.files) == ["fine.pdf"]
    assert (report.unreadable, report.oversize) == (1, 1)

    with pytest.raises(ImportEngineError):
        await _download(
            [attachment("1", "a.pdf", "application/pdf")],
            failures={"1": ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED},
        )


async def test_without_files_only_the_pictures_come():
    media, report, _budget = await _download(
        [
            attachment("1", "chart.png", "image/png"),
            attachment("2", "spec.pdf", "application/pdf"),
        ],
        files_allowed=False,
    )
    assert list(media.stored_images) == ["chart.png"]
    assert media.files == {}
    assert report.blocked == 1


async def test_a_picture_the_page_never_shows_becomes_a_file():
    media, _report, _budget = await _download(
        [
            attachment("1", "shown.png", "image/png"),
            attachment("2", "hidden.png", "image/png"),
            attachment("3", "spec.pdf", "application/pdf"),
        ]
    )
    assert [s.filename for s in media.uploads(["shown.png"])] == ["shown.png"]
    assert [s.filename for s in media.as_files(["shown.png"])] == [
        "spec.pdf",
        "hidden.png",
    ]
