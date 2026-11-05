"""The one bundle an Atlassian fetch writes."""

import zipfile
from collections import Counter

import pytest

from app.services.import_engine.atlassian_bundle import BundleWriter, merge_people
from app.services.import_engine.backup import read_manifest
from app.services.import_engine.zip_bounds import open_zip
from app.services.import_engine.jira_attachments import StoredImage


def test_somebody_in_both_products_is_asked_about_once():
    people = merge_people(
        [
            {"handle": "Robin Ade", "name": "Robin Ade", "comment_count": 3},
            {"handle": "Sam Bee", "name": "Sam Bee", "comment_count": 0},
        ],
        Counter({"robin ade": 2, "Kit Cole": 5}),
    )
    assert [p["handle"] for p in people] == ["Robin Ade", "Kit Cole", "Sam Bee"]
    # Jira's spelling, and its comment count, are the ones kept.
    assert people[0]["comment_count"] == 3


def _stored(key, content_type="image/png", size=4):
    return StoredImage(
        filename=f"{key}.bin",
        storage_key=key,
        content_type=content_type,
        size_bytes=size,
    )


def _finish(writer, **kwargs):
    return writer.finish(
        people=[],
        guild_id=1,
        guild_name="acme.atlassian.net",
        target_initiative_id=9,
        app_version="0.0.0-test",
        site_url="https://acme.atlassian.net",
        **kwargs,
    )


async def test_files_are_written_as_they_arrive_and_listed_when_named():
    picture, notes, unshown = (
        _stored("k1.png"),
        _stored("k2.txt", content_type="text/plain", size=5),
        _stored("k3.png"),
    )
    with BundleWriter() as writer:
        await writer.put_asset(picture, b"\x89PNG")
        await writer.put_asset(notes, b"notes")
        await writer.put_asset(unshown, b"\x89PNG")
        # The same file twice is written once.
        await writer.put_asset(picture, b"\x89PNG")
        path = _finish(writer, images=[picture], task_files=[notes])

        archive = open_zip(path)
        manifest = read_manifest(archive)
        assert [a.storage_key for a in manifest.assets] == ["k1.png", "k2.txt"]
        assert manifest.initiatives[0].target_initiative_id == 9
        assert archive.read("assets/k2.txt") == b"notes"
        # A picture is stored as it is; text is compressed.
        assert archive.getinfo("assets/k1.png").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("assets/k2.txt").compress_type == zipfile.ZIP_DEFLATED
        # Downloaded but named by nothing: in the zip, not in the manifest.
        assert "assets/k3.png" in archive.namelist()
        archive.close()
    assert not path.exists()


async def test_a_listed_file_that_never_arrived_is_refused():
    with BundleWriter() as writer:
        with pytest.raises(RuntimeError):
            _finish(writer, images=[_stored("missing.png")])


def test_an_unfinished_bundle_leaves_no_file_behind():
    with BundleWriter() as writer:
        path = writer.path
        assert path.exists()
    assert not path.exists()


def test_a_bundle_opens_past_the_upload_bounds(monkeypatch):
    """A backup, a Confluence export, or a bundle this app wrote from a fetch
    is held to the bundle bounds rather than another zip's."""
    import io

    from app.services.import_engine import limits as import_limits
    from app.services.import_engine.contract import ImportEngineError

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(3):
            archive.writestr(f"assets/{index}.txt", "x")
    payload = buffer.getvalue()
    monkeypatch.setattr(import_limits, "IMPORT_MAX_ZIP_MEMBERS", 2)

    with pytest.raises(ImportEngineError):
        open_zip(payload)
    assert len(open_zip(payload, bundle=True).infolist()) == 3

    monkeypatch.setattr(import_limits, "IMPORT_MAX_BUNDLE_MEMBERS", 2)
    with pytest.raises(ImportEngineError):
        open_zip(payload, bundle=True)
