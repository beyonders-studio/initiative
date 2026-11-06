"""A Confluence page's attachments, brought over (design §6.2).

Two kinds of thing arrive. A picture the page shows becomes an upload,
rendered where the page embedded it — the same path a Jira issue's images
take. Every other file, and any picture the page never showed, becomes an uploaded file filed in the wiki: a file has one home, the initiative's files,
and being in the wiki is the relation that is a second view of it (D10).

Both are blobs under the bundle's ``assets/``, restored by the ordinary
backup apply — quota-checked, deduplicated and registered like any upload.
Only what fits: a picture up to :data:`MAX_IMAGE_BYTES`, and the bundle's
budget across all of them, which any other file may take as much of as is
left. Each is written to disk as it arrives, never held whole. What does not
fit, or will not download, is counted rather than guessed at.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, BinaryIO, Callable, Optional

from app.core.messages import ImportEngineMessages
from app.services.data_jobs import while_beating
from app.services.import_engine.atlassian import HEARTBEAT_SECONDS
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.jira_attachments import (
    IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    REFUSED_TYPES,
    AssetBudget,
    AssetSink,
    StoredImage,
    file_can_hold,
    file_extension,
)

_ATTACHMENT_ID = re.compile(r"(?:att)?\d{1,20}")


@dataclass(frozen=True)
class PageAttachment:
    id: str
    filename: str
    media_type: str
    size: int

    @property
    def is_image(self) -> bool:
        return self.media_type in IMAGE_TYPES


def read_attachments(payload: Any) -> list[PageAttachment]:
    """The attachments a ``/pages/{id}/attachments`` answer lists, skipping
    anything malformed."""
    results = payload.get("results") if isinstance(payload, dict) else None
    found: list[PageAttachment] = []
    for entry in results if isinstance(results, list) else []:
        if not isinstance(entry, dict):
            continue
        attachment_id = str(entry.get("id") or "").strip()
        filename = str(entry.get("title") or "").strip()
        size = entry.get("fileSize")
        # The id goes into a path on the site, so it has to look like one.
        if not _ATTACHMENT_ID.fullmatch(attachment_id) or not filename:
            continue
        found.append(
            PageAttachment(
                id=attachment_id,
                filename=filename,
                media_type=str(entry.get("mediaType") or "").strip().lower(),
                size=size
                if isinstance(size, int) and not isinstance(size, bool)
                else 0,
            )
        )
    return found


def storage_key(attachment: PageAttachment) -> str:
    """A fresh, flat storage key — never the site's filename, which is
    somebody else's text and not a path this server should write to."""
    if attachment.is_image:
        return f"{uuid.uuid4().hex}{IMAGE_TYPES[attachment.media_type]}"
    return f"{uuid.uuid4().hex}{file_extension(attachment.filename)}"


@dataclass
class PageMedia:
    """One page's attachments that came over, by the filename the page uses."""

    #: A picture's filename → the URL it renders from here.
    images: dict[str, str] = field(default_factory=dict)
    #: The stored blobs behind those pictures, by filename.
    stored_images: dict[str, StoredImage] = field(default_factory=dict)
    #: Every other file that came over, by filename.
    files: dict[str, StoredImage] = field(default_factory=dict)

    def as_files(self, shown: list[str]) -> list[StoredImage]:
        """What becomes an uploaded file: every file, and every picture the
        page has but never shows — so nothing attached is kept only in
        storage."""
        seen = set(shown)
        return [*self.files.values()] + [
            stored for name, stored in self.stored_images.items() if name not in seen
        ]

    def uploads(self, shown: list[str]) -> list[StoredImage]:
        """The pictures the page shows, which travel as uploads."""
        seen = set(shown)
        return [stored for name, stored in self.stored_images.items() if name in seen]


@dataclass(frozen=True)
class PageFile:
    """An uploaded file, and the page it was attached to — which it is filed
    under in the wiki — by that page's slug."""

    stored: StoredImage
    page_slug: Optional[str] = None


@dataclass
class AttachmentReport:
    """What downloading cost. What the files became is the mapping's to
    count, since a picture a page never shows turns out to be a file."""

    bytes: int = 0
    #: A picture over its cap, or a file past the bundle's budget.
    oversize: int = 0
    #: What the site would not hand over.
    unreadable: int = 0
    #: A type never brought over.
    refused: int = 0
    #: Attachments that could not become files in the chosen initiative.
    blocked: int = 0


#: ``download(attachment, max_bytes, target)`` writes the attachment to
#: ``target`` and answers its size.
Downloader = Callable[[PageAttachment, int, BinaryIO], Awaitable[int]]


async def download_page_attachments(
    attachments: list[PageAttachment],
    *,
    guild_id: int,
    download: Downloader,
    store: AssetSink,
    budget: AssetBudget,
    report: AttachmentReport,
    files_allowed: bool = True,
    tick: Optional[Callable[[], Awaitable[None]]] = None,
) -> PageMedia:
    """Fetch one page's attachments, within the caps and the shared budget.

    ``download`` is the site call, writing each file to a temporary one, and
    ``store`` takes it from there as soon as it has arrived. One file that will
    not come is counted and skipped — a broken attachment is not a reason to
    lose the space — but being throttled stops the fetch, as it does
    everywhere else.

    ``files_allowed`` false is an initiative that cannot take uploaded files:
    only the pictures come, to be shown where the page put them.
    """
    media = PageMedia()
    for attachment in attachments:
        if attachment.media_type in REFUSED_TYPES or (
            not attachment.is_image
            and not file_can_hold(attachment.filename, attachment.media_type)
        ):
            report.refused += 1
            continue
        if not files_allowed and not attachment.is_image:
            report.blocked += 1
            continue
        if (
            (attachment.is_image and attachment.size > MAX_IMAGE_BYTES)
            or attachment.size > budget.bytes_left
            or budget.files_left <= 0
        ):
            report.oversize += 1
            continue
        with tempfile.NamedTemporaryFile(prefix="import-attachment-") as spool:
            try:
                size = await while_beating(
                    download(
                        attachment,
                        min(MAX_IMAGE_BYTES, budget.bytes_left)
                        if attachment.is_image
                        else budget.bytes_left,
                        spool,
                    ),
                    tick,
                    every=HEARTBEAT_SECONDS,
                )
            except ImportEngineError as exc:
                if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                    raise
                if exc.code == ImportEngineMessages.IMPORT_TOO_LARGE:
                    report.oversize += 1
                else:
                    report.unreadable += 1
                continue
            finally:
                if tick is not None:
                    await tick()
            budget.bytes_left -= size
            budget.files_left -= 1
            report.bytes += size
            stored = StoredImage(
                filename=attachment.filename,
                storage_key=storage_key(attachment),
                content_type=attachment.media_type or "application/octet-stream",
                size_bytes=size,
            )
            spool.flush()
            await while_beating(
                store(stored, Path(spool.name)), tick, every=HEARTBEAT_SECONDS
            )
        if attachment.is_image:
            media.stored_images.setdefault(attachment.filename, stored)
            media.images.setdefault(
                attachment.filename, f"/uploads/{guild_id}/{stored.storage_key}"
            )
        else:
            media.files.setdefault(attachment.filename, stored)
    return media


def file_ref(stored: StoredImage) -> str:
    """The name an uploaded file answers to once the apply has written it:
    its manifest entry, which sits at its asset's path."""
    return f"entry:assets/{stored.storage_key}"
