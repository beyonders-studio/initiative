"""A zip is opened within its bounds and each member read up to its cap."""

import io
import json
import zipfile

import pytest

from app.services.import_engine import limits as import_limits
from app.services.import_engine import zip_bounds
from app.services.import_engine.contract import ImportEngineError


def _zip(**members: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class _UnderstatedArchive:
    """Declares ten bytes for a member that reads to far more."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.read_so_far = 0

    def getinfo(self, name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name)
        info.file_size = 10
        return info

    def open(self, info: zipfile.ZipInfo) -> io.BytesIO:
        archive = self

        class _Counting(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                chunk = super().read(size)
                archive.read_so_far += len(chunk)
                return chunk

        return _Counting(b"x" * self.size)


def test_a_member_is_read_whole_within_its_cap():
    archive = zipfile.ZipFile(io.BytesIO(_zip(**{"a.txt": b"hello"})))
    assert zip_bounds.read_member(archive, "a.txt", max_bytes=5) == b"hello"


def test_a_member_declaring_more_than_its_cap_is_refused():
    archive = zipfile.ZipFile(io.BytesIO(_zip(**{"a.txt": b"hello"})))
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.read_member(archive, "a.txt", max_bytes=4)
    assert caught.value.code == "IMPORT_TOO_LARGE"


def test_reading_stops_once_a_member_passes_its_cap():
    archive = _UnderstatedArchive(size=50 * 1024 * 1024)
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.read_member(
            archive,
            "big.bin",
            max_bytes=100,
            code="IMPORT_QUOTA_EXCEEDED",
        )
    assert caught.value.code == "IMPORT_QUOTA_EXCEEDED"
    # Read up to the cap and one byte past it, and no further.
    assert archive.read_so_far == 101


def test_a_json_member_parses_or_says_what_is_wrong():
    archive = zipfile.ZipFile(
        io.BytesIO(
            _zip(**{"ok.json": json.dumps({"type": "x"}).encode(), "bad.json": b"{"})
        )
    )
    assert zip_bounds.read_json_member(archive, "ok.json", max_bytes=100) == {
        "type": "x"
    }
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.read_json_member(
            archive, "bad.json", max_bytes=100, invalid="IMPORT_ZIP_INVALID"
        )
    assert caught.value.code == "IMPORT_ZIP_INVALID"
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.read_json_member(archive, "ok.json", max_bytes=3)
    assert caught.value.code == "IMPORT_TOO_LARGE"
    with pytest.raises(KeyError):
        zip_bounds.read_json_member(archive, "absent.json", max_bytes=100)


@pytest.mark.parametrize("name", ["../up.txt", "/root.txt", "a/../../b.txt"])
def test_a_name_outside_the_zip_is_refused(name):
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.open_zip(_zip(**{name: b"x"}))
    assert caught.value.code == "IMPORT_ZIP_INVALID"


def test_declared_sizes_past_the_bound_are_refused(monkeypatch):
    monkeypatch.setattr(import_limits, "IMPORT_MAX_ZIP_UNCOMPRESSED_BYTES", 8)
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.open_zip(_zip(**{"a.txt": b"12345", "b.txt": b"12345"}))
    assert caught.value.code == "IMPORT_TOO_LARGE"
    assert len(zip_bounds.open_zip(_zip(**{"a.txt": b"12345"})).infolist()) == 1


def test_bytes_that_are_not_a_zip_are_refused():
    with pytest.raises(ImportEngineError) as caught:
        zip_bounds.open_zip(b"not a zip")
    assert caught.value.code == "IMPORT_ZIP_INVALID"
