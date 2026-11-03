"""A Jira issue's images, brought over as uploads."""

import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import jira_attachments as ja
from app.services.import_engine.contract import ImportEngineError


def _att(att_id, filename, mime="image/png", size=100):
    return {"id": att_id, "filename": filename, "mimeType": mime, "size": size}


def _issue(key, *attachments):
    return {"key": key, "fields": {"attachment": list(attachments)}}


def _downloader(payloads=None, errors=None):
    calls: list[tuple[str, int]] = []

    async def download(attachment_id, max_bytes):
        calls.append((attachment_id, max_bytes))
        if errors and attachment_id in errors:
            raise ImportEngineError(errors[attachment_id])
        return (payloads or {}).get(attachment_id, b"x" * 10)

    download.calls = calls  # type: ignore[attr-defined]
    return download


def _sink():
    kept: dict[str, bytes] = {}

    async def store(stored, data):
        kept[stored.storage_key] = data

    store.kept = kept  # type: ignore[attr-defined]
    return store


def test_attachments_are_read_and_malformed_ones_skipped():
    issue = _issue(
        "ACME-1",
        _att("10", "door.png"),
        {"id": "not-a-number", "filename": "x.png"},
        {"id": "11"},
        "nonsense",
    )
    found = ja.issue_attachments(issue)
    assert [(a.id, a.filename, a.mime_type) for a in found] == [
        ("10", "door.png", "image/png")
    ]


async def test_images_come_over_and_everything_else_is_counted():
    """Raster images download; a PDF is left behind when files were not
    asked for, and an SVG always is — both counted, neither fetched."""
    download = _downloader()
    report = await ja.download_images(
        [
            _issue(
                "ACME-1",
                _att("10", "door.png"),
                _att("11", "spec.pdf", mime="application/pdf"),
                _att("12", "logo.svg", mime="image/svg+xml"),
            )
        ],
        download=download,
        store=_sink(),
        budget_bytes=10_000,
        max_files=100,
    )
    assert [c[0] for c in download.calls] == ["10"]
    assert (report.images, report.other_files) == (1, 2)
    (stored,) = report.by_issue["ACME-1"]
    assert stored.filename == "door.png"
    assert stored.content_type == "image/png"


async def test_the_storage_key_is_ours_not_the_sites_filename():
    """A filename is somebody else's text: the key is fresh and flat."""
    report = await ja.download_images(
        [_issue("ACME-1", _att("10", "../../etc/passwd.png"))],
        download=_downloader(),
        store=_sink(),
        budget_bytes=10_000,
        max_files=100,
    )
    key = report.by_issue["ACME-1"][0].storage_key
    assert "/" not in key and key.endswith(".png") and "passwd" not in key


async def test_an_image_over_the_cap_is_never_downloaded():
    download = _downloader()
    report = await ja.download_images(
        [_issue("ACME-1", _att("10", "huge.png", size=ja.MAX_IMAGE_BYTES + 1))],
        download=download,
        store=_sink(),
        budget_bytes=10**12,
        max_files=100,
    )
    assert download.calls == []
    assert report.oversize == 1


async def test_the_bundle_budget_stops_downloads_by_bytes_and_by_count():
    download = _downloader()
    report = await ja.download_images(
        [
            _issue(
                "ACME-1",
                _att("10", "a.png", size=10),
                _att("11", "b.png", size=10),
                _att("12", "c.png", size=10),
            )
        ],
        download=download,
        store=_sink(),
        budget_bytes=10_000,
        max_files=2,
    )
    assert (report.images, report.oversize) == (2, 1)

    report = await ja.download_images(
        [_issue("ACME-1", _att("10", "a.png", size=10), _att("11", "b.png", size=10))],
        download=_downloader(),
        store=_sink(),
        budget_bytes=15,
        max_files=100,
    )
    assert (report.images, report.oversize) == (1, 1)


async def test_a_file_bigger_than_declared_is_counted_as_oversize():
    """The site's declared size is somebody else's to get wrong; the download
    enforces the cap on what arrives, and the image is dropped, not fatal."""
    report = await ja.download_images(
        [_issue("ACME-1", _att("10", "liar.png", size=10))],
        download=_downloader(errors={"10": ImportEngineMessages.IMPORT_TOO_LARGE}),
        store=_sink(),
        budget_bytes=10_000,
        max_files=100,
    )
    assert (report.images, report.oversize) == (0, 1)


async def test_an_image_the_site_withholds_is_counted_but_throttling_stops_it():
    report = await ja.download_images(
        [_issue("ACME-1", _att("10", "a.png"), _att("11", "b.png"))],
        download=_downloader(errors={"10": ImportEngineMessages.IMPORT_SOURCE_AUTH}),
        store=_sink(),
        budget_bytes=10_000,
        max_files=100,
    )
    assert (report.images, report.unreadable) == (1, 1)

    with pytest.raises(ImportEngineError) as exc:
        await ja.download_images(
            [_issue("ACME-1", _att("10", "a.png"))],
            download=_downloader(
                errors={"10": ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED}
            ),
            store=_sink(),
            budget_bytes=10_000,
            max_files=100,
        )
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED


def test_images_are_found_by_filename_and_the_rest_listed_at_the_foot():
    images = [
        ja.StoredImage("door.png", "k1.png", "image/png", 0),
        ja.StoredImage("hinge.png", "k2.png", "image/png", 0),
    ]
    assert ja.media_urls(images, guild_id=5) == {
        "door.png": "/uploads/5/k1.png",
        "hinge.png": "/uploads/5/k2.png",
    }
    section = ja.unreferenced_section(images, {"door.png"}, guild_id=5)
    assert section is not None
    assert "![hinge.png](/uploads/5/k2.png)" in section
    assert "door.png" not in section
    assert (
        ja.unreferenced_section(images, {"door.png", "hinge.png"}, guild_id=5) is None
    )


async def test_other_files_come_over_as_files_when_asked_for():
    """A file of a type an uploaded file can hold comes over, a table of text included (it
    becomes a spreadsheet); a program is left behind."""
    download = _downloader()
    store = _sink()
    report = await ja.download_images(
        [
            _issue(
                "ACME-1",
                _att("10", "door.png"),
                _att("11", "spec.pdf", mime="application/pdf"),
                _att("12", "logo.svg", mime="image/svg+xml"),
                _att("13", "counts.csv", mime="text/csv"),
                _att("14", "setup.exe", mime="application/x-msdownload"),
            )
        ],
        download=download,
        store=store,
        budget_bytes=10_000,
        max_files=100,
        files_allowed=True,
    )
    assert sorted(c[0] for c in download.calls) == ["10", "11", "13"]
    assert (report.images, report.files, report.other_files) == (1, 2, 2)
    pdf, table = report.files_by_issue["ACME-1"]
    assert pdf.filename == "spec.pdf" and pdf.storage_key.endswith(".pdf")
    assert table.storage_key.endswith(".csv")
    assert report.file_bytes == pdf.size_bytes + table.size_bytes
    assert pdf.size_bytes == len(store.kept[pdf.storage_key])


def test_a_fetched_bundle_is_bounded_by_the_communitys_storage_left():
    unbounded = ja.bundle_budget()
    assert unbounded.bytes_left > 10 * 1024 * 1024 * 1024
    assert ja.bundle_budget(5_000).bytes_left == 5_000
    assert ja.bundle_budget(-1).bytes_left == 0
    assert ja.bundle_budget(5_000).files_left == unbounded.files_left
