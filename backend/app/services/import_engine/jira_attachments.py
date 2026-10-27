"""A Jira issue's attachments, brought over (design §6.1).

An image attached to an issue becomes a blob in the bundle's ``assets/``,
restored by the ordinary backup apply under a storage key made here — so it
is quota-checked, deduplicated and registered like any other upload — and
the markdown shows it where the description or a comment embedded it.

Any other file — a PDF, a spreadsheet — becomes an uploaded file of its own,
attached to the task: a file has one home, the initiative's files, and
the task is linked to it. Images up to :data:`MAX_IMAGE_BYTES`, other files
up to :data:`MAX_FILE_BYTES`. SVG is left out on purpose: it is markup, and
these are files from somebody else's site.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.core.messages import ImportEngineMessages
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine import limits as import_limits

logger = logging.getLogger(__name__)

#: The design's per-image cap.
MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: The cap on one attached file that is not a picture.
MAX_FILE_BYTES = 50 * 1024 * 1024

#: Types never brought over, picture or not.
REFUSED_TYPES = frozenset({"image/svg+xml"})

#: The image types brought over, and the extension each is stored under.
IMAGE_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


#: Held back from the bundle's byte and member bounds for the manifest and
#: the envelopes, so attachments cannot crowd them out. Envelopes for a full
#: row budget run to about a gigabyte.
_BUNDLE_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
_BUNDLE_RESERVE_FILES = 1_000


@dataclass
class AssetBudget:
    """What the bundle can still hold, shared by everything one import reads.

    Kept under the bounds a fetched bundle is opened with — its uncompressed
    size and its member count — with room left for the manifest and the
    envelopes, so a bundle the fetch wrote is never one the apply refuses
    whole.
    """

    bytes_left: int
    files_left: int


def bundle_budget(storage_left: int | None = None) -> AssetBudget:
    """A whole fetched bundle's worth, before anything has been spent.

    ``storage_left`` is what the community's storage quota still allows, when
    it has one: attachments past it could never be restored, so they are not
    downloaded either.
    """
    bytes_left = max(
        0,
        import_limits.IMPORT_FETCH_MAX_BUNDLE_BYTES - _BUNDLE_RESERVE_BYTES,
    )
    if storage_left is not None:
        bytes_left = min(bytes_left, max(0, storage_left))
    return AssetBudget(
        bytes_left=bytes_left,
        files_left=max(
            0, import_limits.IMPORT_FETCH_MAX_ZIP_MEMBERS - _BUNDLE_RESERVE_FILES
        ),
    )


@dataclass(frozen=True)
class Attachment:
    id: str
    filename: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class StoredImage:
    """A file downloaded and given the key it will be restored under.

    Its bytes are not here: they went into the bundle the moment they
    arrived (see :data:`AssetSink`), and only what the manifest and the
    mapping need is kept.
    """

    filename: str
    storage_key: str
    content_type: str
    size_bytes: int


#: Where a downloaded file goes as soon as it has arrived: the bundle being
#: written, which keeps the bytes so the fetch does not have to.
AssetSink = Callable[[StoredImage, bytes], Awaitable[None]]


@dataclass
class ImageReport:
    images: int = 0
    image_bytes: int = 0
    #: Images over the per-image cap, or past the bundle's byte budget.
    oversize: int = 0
    #: Files that are not images, left behind: attachments were brought for
    #: their pictures only, the initiative cannot take files, or a
    #: file cannot hold its type.
    other_files: int = 0
    #: Attachments the site would not hand over.
    unreadable: int = 0
    #: What each issue's images became, by issue key.
    by_issue: dict[str, list[StoredImage]] = field(default_factory=dict)
    #: Every other file that came over, to become a file attached to its
    #: task, by issue key.
    files: int = 0
    file_bytes: int = 0
    files_by_issue: dict[str, list[StoredImage]] = field(default_factory=dict)

    def absorb(self, other: "ImageReport") -> None:
        """Add another page's report to this one."""
        self.images += other.images
        self.image_bytes += other.image_bytes
        self.oversize += other.oversize
        self.other_files += other.other_files
        self.unreadable += other.unreadable
        self.files += other.files
        self.file_bytes += other.file_bytes
        for key, stored in other.by_issue.items():
            self.by_issue.setdefault(key, []).extend(stored)
        for key, stored in other.files_by_issue.items():
            self.files_by_issue.setdefault(key, []).extend(stored)


def issue_attachments(issue: Any) -> list[Attachment]:
    """The attachments an issue lists, skipping anything malformed."""
    fields = issue.get("fields") if isinstance(issue, dict) else None
    raw = fields.get("attachment") if isinstance(fields, dict) else None
    if not isinstance(raw, list):
        return []
    found = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        attachment_id = str(entry.get("id") or "").strip()
        filename = str(entry.get("filename") or "").strip()
        size = entry.get("size")
        if not attachment_id.isdigit() or not filename:
            continue
        found.append(
            Attachment(
                id=attachment_id,
                filename=filename,
                mime_type=str(entry.get("mimeType") or "").strip().lower(),
                size=size
                if isinstance(size, int) and not isinstance(size, bool)
                else 0,
            )
        )
    return found


def file_extension(filename: str) -> str:
    """A filename's extension, kept only when it looks like one."""
    dot = filename.rfind(".")
    extension = filename[dot:].lower() if dot > 0 else ""
    return extension if 1 < len(extension) <= 10 and extension[1:].isalnum() else ""


def file_can_hold(filename: str, media_type: str) -> bool:
    """Whether a file that is not a picture can become a file here: anything
    but a program."""
    from app.core.file_types import is_refused

    return not is_refused(media_type, filename)


def storage_key(attachment: Attachment) -> str:
    """A fresh, flat storage key — never the site's filename, which is
    somebody else's text and not a path this server should write to."""
    if attachment.mime_type in IMAGE_TYPES:
        return f"{uuid.uuid4().hex}{IMAGE_TYPES[attachment.mime_type]}"
    return f"{uuid.uuid4().hex}{file_extension(attachment.filename)}"


Downloader = Callable[[str, int], Awaitable[bytes]]


async def download_images(
    issues: list[Any],
    *,
    download: Downloader,
    store: AssetSink,
    budget_bytes: int,
    max_files: int,
    files_allowed: bool = False,
    tick: Optional[Callable[[], Awaitable[None]]] = None,
) -> ImageReport:
    """Fetch every issue's images, within the per-image cap and a total budget.

    ``download(attachment_id, max_bytes)`` is the site call, and ``store``
    takes each file as it arrives. An image the site
    will not hand over is counted and skipped — one broken attachment is not
    a reason to lose the project — but being throttled stops the fetch, as it
    does everywhere else. What would take the bundle past ``budget_bytes`` or
    ``max_files`` is skipped and counted as oversize. ``files_allowed`` brings the
    files that are not pictures too; without it they are counted.
    """
    report = ImageReport()
    spent = 0
    for issue in issues:
        key = str(issue.get("key") or "").strip() if isinstance(issue, dict) else ""
        for attachment in issue_attachments(issue):
            is_image = attachment.mime_type in IMAGE_TYPES
            if attachment.mime_type in REFUSED_TYPES or (
                not is_image
                and not (
                    files_allowed
                    and file_can_hold(attachment.filename, attachment.mime_type)
                )
            ):
                report.other_files += 1
                continue
            cap = MAX_IMAGE_BYTES if is_image else MAX_FILE_BYTES
            if (
                attachment.size > cap
                or spent + attachment.size > budget_bytes
                or report.images + report.files >= max_files
            ):
                report.oversize += 1
                continue
            try:
                data = await download(attachment.id, min(cap, budget_bytes - spent))
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
            spent += len(data)
            stored = StoredImage(
                filename=attachment.filename,
                storage_key=storage_key(attachment),
                content_type=attachment.mime_type or "application/octet-stream",
                size_bytes=len(data),
            )
            await store(stored, data)
            del data
            if is_image:
                report.images += 1
                report.image_bytes += stored.size_bytes
                report.by_issue.setdefault(key, []).append(stored)
            else:
                report.files += 1
                report.file_bytes += stored.size_bytes
                report.files_by_issue.setdefault(key, []).append(stored)
    return report


def media_urls(images: list[StoredImage], *, guild_id: int) -> dict[str, str]:
    """Filename → the URL an embedded image renders from here.

    Keyed by filename because that is what Jira puts on a media node's
    ``alt``; the node's own id is a Media Services id with no way back to the
    attachment (JRACLOUD-96384). Two attachments with one name keep the first.
    """
    urls: dict[str, str] = {}
    for image in images:
        urls.setdefault(image.filename, f"/uploads/{guild_id}/{image.storage_key}")
    return urls


def unreferenced_section(
    images: list[StoredImage], referenced: set[str], *, guild_id: int
) -> Optional[str]:
    """Markdown for the images attached but never embedded, or ``None``.

    Ends the description, under a rule, so an image somebody attached without
    placing it is still on the task rather than silently in storage.
    """
    rest = [image for image in images if image.filename not in referenced]
    if not rest:
        return None
    lines = ["---", "", "**Attachments**", ""]
    for image in rest:
        alt = image.filename.replace("]", "")
        lines.append(f"![{alt}](/uploads/{guild_id}/{image.storage_key})")
    return "\n".join(lines)
