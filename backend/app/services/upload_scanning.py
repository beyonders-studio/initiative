"""Scanning what is uploaded, before it is stored (opt-in).

With ``UPLOAD_SCANNER_URL`` set, every file a person or an import brings in is
streamed to the deployment's upload scanner before it is kept: an upload, a
file's new version, a pasted picture, evidence, and a large file once it has
finished arriving. The scanner is infra's (initiative_infra ``scanner/``,
ADR 0019 §4): a hash list, a look inside archives, YARA rules and ClamAV.

It fails closed. A file the scanner refuses is refused here
(:class:`ScanRefusedError`), and so is every upload while the scanner cannot
answer (:class:`ScannerUnavailableError`, a 503): nothing is stored unscanned
on a deployment that asked for scanning.

Unset (the default, and every FOSS install): nothing here runs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

import httpx

from app.core.config import settings
from app.core.errors import CodedError
from app.core.messages import FileMessages

logger = logging.getLogger(__name__)

#: How long a scan may take: a large file, read whole by every engine.
_TIMEOUT = httpx.Timeout(connect=5.0, read=900.0, write=900.0, pool=5.0)


class ScanRefusedError(CodedError):
    """The scanner refused the file."""

    status_code = 400

    def __init__(self, engine: str = "", reason: str = "") -> None:
        super().__init__(FileMessages.REFUSED_BY_SCAN)
        self.engine, self.reason = engine, reason


class ScannerUnavailableError(CodedError):
    """The scanner could not answer, so nothing is taken until it can."""

    status_code = 503

    def __init__(self) -> None:
        super().__init__(FileMessages.SCANNER_UNAVAILABLE)


def enabled() -> bool:
    return bool(settings.UPLOAD_SCANNER_URL)


def _post(content: bytes | Iterator[bytes], size: int) -> None:
    try:
        response = httpx.post(
            f"{settings.UPLOAD_SCANNER_URL.rstrip('/')}/v1/scan",
            content=content,
            headers={
                "Authorization": f"Bearer {settings.UPLOAD_SCANNER_TOKEN}",
                "Content-Length": str(size),
                "Content-Type": "application/octet-stream",
            },
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning("upload scanner unreachable: %s", type(exc).__name__)
        raise ScannerUnavailableError() from exc
    if response.status_code == 413:
        # Larger than the scanner takes: refused, as a file it cannot vouch for.
        raise ScanRefusedError("size", "larger than the scanner takes")
    if response.status_code != 200:
        logger.warning("upload scanner answered %s", response.status_code)
        raise ScannerUnavailableError()
    verdict = response.json()
    if verdict.get("verdict") == "clean":
        return
    if verdict.get("verdict") == "refused":
        logger.info(
            "upload refused by scan: engine=%s reason=%s",
            verdict.get("engine"),
            verdict.get("reason"),
        )
        raise ScanRefusedError(
            str(verdict.get("engine", "")), str(verdict.get("reason", ""))
        )
    raise ScannerUnavailableError()


def scan_bytes(data: bytes) -> None:
    """Have ``data`` scanned; raises unless it is clean. Blocks."""
    if enabled():
        _post(data, len(data))


def scan_stream(pieces: Iterable[bytes], size: int) -> None:
    """Have the ``size`` bytes of ``pieces`` scanned without holding them;
    raises unless they are clean. Blocks."""
    if enabled():
        _post(iter(pieces), size)
