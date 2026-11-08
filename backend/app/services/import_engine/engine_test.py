"""Staged payloads round-trip through either storage backend."""

import pytest

from app.services import storage as storage_module
from app.services.import_engine import engine as import_engine
from app.services.storage import LocalFilesystemStorage, S3Storage
from app.services.storage_test import FakeS3Client

_PAYLOAD = b"PK\x03\x04" + bytes(range(256)) * 600  # spans several read chunks


def test_staged_payload_reads_back_from_s3(monkeypatch):
    backend = S3Storage(bucket="bucket", client=FakeS3Client(), prefix="guild_7/")
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    ref = import_engine.stage_payload(7, _PAYLOAD, suffix="zip")

    assert import_engine.read_payload(7, ref) == _PAYLOAD


def test_staged_payload_reads_back_from_local_storage(monkeypatch, tmp_path):
    backend = LocalFilesystemStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    ref = import_engine.stage_payload(7, _PAYLOAD, suffix="zip")

    assert import_engine.read_payload(7, ref) == _PAYLOAD


def test_missing_payload_reads_as_none(monkeypatch):
    backend = S3Storage(bucket="bucket", client=FakeS3Client(), prefix="guild_7/")
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    assert import_engine.read_payload(7, "imports/gone.zip") is None


async def test_a_payload_opens_as_a_file_from_s3_and_the_copy_is_removed(
    monkeypatch, tmp_path
):
    backend = S3Storage(bucket="bucket", client=FakeS3Client(), prefix="guild_7/")
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)
    source = tmp_path / "bundle.zip"
    source.write_bytes(_PAYLOAD)
    ref = import_engine.stage_payload_file(7, source, suffix="zip")

    async with import_engine.open_payload(7, ref) as path:
        assert path is not None and path.read_bytes() == _PAYLOAD
    assert not path.exists()


async def test_a_payload_opens_in_place_from_local_storage(monkeypatch, tmp_path):
    backend = LocalFilesystemStorage(base_dir=str(tmp_path / "store"))
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)
    ref = import_engine.stage_payload(7, _PAYLOAD, suffix="zip")

    async with import_engine.open_payload(7, ref) as path:
        assert path is not None and path.read_bytes() == _PAYLOAD
    # The stored file is the payload itself, and it is left where it is.
    assert path.exists()


async def test_a_missing_payload_opens_as_none(monkeypatch):
    backend = S3Storage(bucket="bucket", client=FakeS3Client(), prefix="guild_7/")
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    async with import_engine.open_payload(7, "imports/gone.zip") as path:
        assert path is None


async def test_an_upload_spools_to_a_file_removed_after_the_block():
    import io

    async with import_engine.spooled_upload(
        io.BytesIO(_PAYLOAD), max_bytes=len(_PAYLOAD)
    ) as path:
        assert path.read_bytes() == _PAYLOAD
    assert not path.exists()


async def test_an_upload_past_its_cap_is_refused_and_leaves_no_file(
    monkeypatch, tmp_path
):
    import io
    import tempfile

    from app.services.import_engine.contract import ImportEngineError

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with pytest.raises(ImportEngineError) as caught:
        async with import_engine.spooled_upload(
            io.BytesIO(_PAYLOAD), max_bytes=len(_PAYLOAD) - 1
        ):
            pass
    assert caught.value.code == "IMPORT_TOO_LARGE"
    assert caught.value.status_code == 413
    assert list(tmp_path.iterdir()) == []
