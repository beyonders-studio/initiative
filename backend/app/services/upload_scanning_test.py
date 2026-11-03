"""Upload scanning: the client against a fake scanner, and the hooks that call
it. No database."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services import storage_config, upload_scanning
from app.services.platform import evidence
from app.services.storage import LocalFilesystemStorage
from app.services.tenant import attachments
from app.services.upload_scanning import ScannerUnavailableError, ScanRefusedError


class FakeScanner:
    """The scanner's ``POST /v1/scan``, answering what it is told to."""

    def __init__(self, answer: httpx.Response | Exception) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def post(
        self, url: str, *, content: Any, headers: dict[str, str], timeout: Any
    ) -> httpx.Response:
        body = content if isinstance(content, bytes) else b"".join(content)
        self.calls.append({"url": url, "body": body, "headers": headers})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def scanner(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeScanner]:
    fake = FakeScanner(httpx.Response(200, json={"verdict": "clean"}))
    monkeypatch.setattr(settings, "UPLOAD_SCANNER_URL", "http://scanner:8080")
    monkeypatch.setattr(settings, "UPLOAD_SCANNER_TOKEN", "token")
    monkeypatch.setattr(upload_scanning.httpx, "post", fake.post)
    yield fake


def test_unset_nothing_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_SCANNER_URL", "")
    sent: list[bytes] = []
    monkeypatch.setattr(upload_scanning.httpx, "post", lambda *a, **k: sent.append(b""))
    upload_scanning.scan_bytes(b"anything")
    assert sent == []


def test_a_clean_file_passes_with_the_token_and_its_length(
    scanner: FakeScanner,
) -> None:
    upload_scanning.scan_bytes(b"ordinary")
    (call,) = scanner.calls
    assert call["url"] == "http://scanner:8080/v1/scan"
    assert call["headers"]["Authorization"] == "Bearer token"
    assert call["headers"]["Content-Length"] == "8"
    assert call["body"] == b"ordinary"


def test_a_refused_file_is_refused(scanner: FakeScanner) -> None:
    scanner.answer = httpx.Response(
        200, json={"verdict": "refused", "engine": "clamav", "reason": "Eicar"}
    )
    with pytest.raises(ScanRefusedError) as refused:
        upload_scanning.scan_bytes(b"x")
    assert (refused.value.engine, refused.value.status_code) == ("clamav", 400)


def test_too_large_to_scan_is_refused(scanner: FakeScanner) -> None:
    scanner.answer = httpx.Response(413)
    with pytest.raises(ScanRefusedError):
        upload_scanning.scan_bytes(b"x")


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(503),
        httpx.Response(500),
        httpx.Response(200, json={"verdict": "something new"}),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
def test_no_answer_holds_every_upload_back(scanner: FakeScanner, answer: Any) -> None:
    scanner.answer = answer
    with pytest.raises(ScannerUnavailableError) as held:
        upload_scanning.scan_bytes(b"x")
    assert held.value.status_code == 503


def test_a_stream_is_sent_whole_with_its_length(scanner: FakeScanner) -> None:
    upload_scanning.scan_stream(iter([b"one ", b"two"]), 7)
    (call,) = scanner.calls
    assert call["body"] == b"one two"
    assert call["headers"]["Content-Length"] == "7"


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFilesystemStorage:
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    storage_config.reset_for_tests()
    store = LocalFilesystemStorage(prefix="guild_7/")
    store.write("resumable-done", b"%PDF-1.7\n" + b"x" * 200)
    return store


def test_a_finished_upload_is_scanned_whole_before_it_is_taken(
    scanner: FakeScanner, staged: LocalFilesystemStorage
) -> None:
    size = len(b"%PDF-1.7\n") + 200
    assert (
        attachments.validate_stored(7, "resumable-done", size, "a.pdf")
        == "application/pdf"
    )
    assert scanner.calls[0]["body"].startswith(b"%PDF-1.7")
    assert len(scanner.calls[0]["body"]) == size


def test_a_finished_upload_the_scanner_refuses_is_not_taken(
    scanner: FakeScanner, staged: LocalFilesystemStorage
) -> None:
    scanner.answer = httpx.Response(200, json={"verdict": "refused", "engine": "yara"})
    with pytest.raises(ScanRefusedError):
        attachments.validate_stored(7, "resumable-done", 209, "a.pdf")


def test_evidence_is_scanned_before_it_is_kept(scanner: FakeScanner) -> None:
    from app.core.intake import EvidencePolicy

    policy = EvidencePolicy(
        max_files=1, max_bytes=10_000, types=frozenset({"application/pdf"})
    )
    scanner.answer = httpx.Response(
        200, json={"verdict": "refused", "engine": "clamav"}
    )
    with pytest.raises(ScanRefusedError):
        evidence.prepare([evidence.IncomingFile("a.pdf", b"%PDF-1.7\nhello")], policy)
