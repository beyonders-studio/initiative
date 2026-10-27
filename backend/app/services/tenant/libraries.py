"""Library service — loaders, the annotations a list needs, and the picture
upload rules.

A library is a shareable DAC resource (``resource_type='library'``) holding
pictures as child rows. What is genuinely this tool's own is in two places:

* **What a picture is allowed to be.** Two gates, cheapest first.
  :func:`validate_image` reads the file's header — the format, the pixel size
  — which is a few bounds-checked slices rather than a decoder. Raster only,
  and no SVG: a picture here is drawn in an ``<img>``, and an SVG is a
  file rather than a picture. Then :func:`render_thumbnail` decodes it,
  and only a body the decoder reads is stored. A header says what a file
  claims; the decode is what confirms it.
* **The order.** Newest first, always. A library is a record of what arrived,
  and a design round is read in the order it happened; the timeline view
  groups the same order by day.

Thumbnails are made here, at upload, with Pillow — the one place in the
request path that decodes pixels, under a pixel ceiling. A picture small
enough not to need one is stored without it and the grid shows the picture
itself; a picture that cannot be decoded at all is not stored.
"""

from datetime import timezone
import io
import logging
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.image_headers import ImageHeader, read_image_header
from app.models.tenant.library import Library, LibraryItem, LibraryItemVersion
from app.schemas.tenant.library import LibraryCover, library_cover
from app.services.permissions import with_tool
from app.services.tenant import comments as comments_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service

#: How big a picture may be. Larger than a document item (10 MB): a library
#: is where exported canvases and store art go, and those are big.
MAX_IMAGE_BYTES = 25 * 1024 * 1024

#: The longest side of a thumbnail. Wide enough for a masonry column on a
#: large screen at 2x, small enough that a grid of forty is a few hundred KB.
THUMBNAIL_EDGE = 640

#: The most pixels a picture may hold before the decoder refuses it. Well
#: above any canvas or photo, well below what would exhaust a worker's memory
#: decompressing it — the default Pillow ceiling, stated here so it is a
#: decision rather than an inheritance.
MAX_IMAGE_PIXELS = 89_478_485

logger = logging.getLogger(__name__)

#: What a picture in a library may be. Exactly what ``read_image_header``
#: recognizes: the raster formats an ``<img>`` draws.
PICTURE_EXTENSIONS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class InvalidImageError(ValueError):
    """The bytes are not a raster item this library can show."""


class EmptyImageError(ValueError):
    """Nothing was uploaded."""


def validate_image(contents: bytes) -> tuple[ImageHeader, str]:
    """Identify an upload from its header, or refuse it.

    Returns the header (content type, pixel size) and the extension the
    stored file takes. The client's ``Content-Type`` and filename are not
    consulted: what the bytes are is the only fact that matters, and a
    mislabelled PNG is still a PNG.
    """
    if not contents:
        raise EmptyImageError()
    header = read_image_header(contents)
    if header is None or header.content_type not in PICTURE_EXTENSIONS:
        raise InvalidImageError()
    return header, PICTURE_EXTENSIONS[header.content_type]


@dataclass(frozen=True)
class Thumbnail:
    """A smaller rendition of a picture, and the size of the picture it was
    made from — read after EXIF orientation was applied, which the header
    check cannot see."""

    data: bytes
    content_type: str
    extension: str
    source_width: int
    source_height: int


def render_thumbnail(contents: bytes) -> Thumbnail | None:
    """Render a thumbnail, or ``None`` where one is not needed.

    WebP, because it is the smallest thing every browser draws. A picture no
    larger than the thumbnail edge needs none: the grid would only be shown a
    copy of what it already has. Animation is dropped — a thumbnail is a
    still.

    Raises :class:`InvalidImageError` for a body the decoder will not read —
    truncated, corrupt, or more pixels than :data:`MAX_IMAGE_PIXELS`. The
    caller refuses the upload on that: a picture nothing can decode is a
    picture nothing can draw.

    Decoding is the one thing in the request path that touches pixels, so it
    is boxed — the decompression-bomb warning is raised as an error, and
    everything the decoder can object to leaves by the same door.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(io.BytesIO(contents)) as opened:
                item = ImageOps.exif_transpose(opened) or opened
                source_width, source_height = item.size
                if max(source_width, source_height) <= THUMBNAIL_EDGE:
                    return None
                item.thumbnail(
                    (THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS
                )
                # WebP takes RGB or RGBA; palette and greyscale-with-alpha
                # items are converted rather than refused.
                if item.mode not in ("RGB", "RGBA"):
                    item = item.convert("RGBA" if "A" in item.getbands() else "RGB")
                out = io.BytesIO()
                item.save(out, format="WEBP", quality=80, method=4)
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ) as exc:
        logger.info("Refused an upload the decoder would not read: %s", exc)
        raise InvalidImageError() from exc
    return Thumbnail(
        data=out.getvalue(),
        content_type="image/webp",
        extension=".webp",
        source_width=source_width,
        source_height=source_height,
    )


def list_loader_options() -> list:
    """Eager-load what a library *list* row needs: its sharing, the level the
    request holds on it, and the cover it chose."""
    return [
        selectinload(Library.grants),
        selectinload(Library.initiative),
        undefer(Library.actions),
        selectinload(Library.cover_item),
    ]


def item_loader_options() -> list:
    """Eager-load what a picture needs to be drawn: who uploaded it."""
    return [
        selectinload(LibraryItem.uploader),
    ]


#: What orders a library: each item's date, then when it was added, then its
#: id, so two added in the same instant still order stably. Matches
#: ``ix_library_items_library_order``.
_ITEM_ORDER = (LibraryItem.occurred_on, LibraryItem.created_at, LibraryItem.id)


def item_order(*, oldest_first: bool = False) -> list:
    """The order items are shown in: newest first by their date.
    ``oldest_first`` is the same order read the other way — a site diary, in
    sequence."""
    if oldest_first:
        return [column.asc() for column in _ITEM_ORDER]
    return [column.desc() for column in _ITEM_ORDER]


def anchored_clause(until, *, oldest_first: bool = False):
    """The WHERE leg for "start the list here", inclusive.

    Measured by the same day the list is ordered by, so the item the rail's
    anchor names is the first one the page returns — and pointed the same way
    the list is read. The anchor is that day's start in UTC, which is the
    shape a timeline bucket carries. Newest first, an anchor is a ceiling and the
    page walks back from it; oldest first, it is a floor and the page walks
    forward. One clause with a direction rather than two, because there is
    one question: where does this page start.
    """
    day = (until.astimezone(timezone.utc) if until.tzinfo else until).date()
    if oldest_first:
        return LibraryItem.occurred_on >= day
    return LibraryItem.occurred_on <= day


async def get_library(
    session: AsyncSession,
    library_id: int,
    *,
    populate_existing: bool = False,
) -> Library | None:
    """Fetch a library as a list row carries it: what authorizing it and the
    grant flow read. RLS scopes the row to the request's guild."""
    stmt = (
        select(Library)
        .where(Library.id == library_id)
        .options(*list_loader_options())
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(stmt)).one_or_none()


async def get_library_hydrated(
    session: AsyncSession,
    library_id: int,
    *,
    populate_existing: bool = False,
) -> Library | None:
    """:func:`get_library` plus what a serialized ``LibraryRead`` carries
    beyond its columns: its tags, properties and comment count."""
    library = await get_library(
        session, library_id, populate_existing=populate_existing
    )
    if library is not None:
        await tags_service.annotate_tags(session, [library])
        await properties_service.annotate_properties(session, [library])
        await comments_service.annotate_comment_counts(
            session, [library], column="library_id"
        )
    return library


async def get_item(
    session: AsyncSession,
    item_id: int,
    *,
    library_id: int | None = None,
    populate_existing: bool = False,
) -> LibraryItem | None:
    """One picture, with its library as authorizing it reads it. ``library_id``
    makes a picture of another library read as missing."""
    stmt = (
        select(LibraryItem)
        .where(LibraryItem.id == item_id)
        .options(
            *item_loader_options(),
            with_tool(LibraryItem.library),
        )
    )
    if library_id is not None:
        stmt = stmt.where(LibraryItem.library_id == library_id)
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    item = (await session.exec(stmt)).one_or_none()
    if item is not None:
        await tags_service.annotate_tags(session, [item])
        await properties_service.annotate_properties(session, [item])
    return item


#: How many pictures a library shows from outside when no cover was chosen.
PREVIEW_COUNT = 4


async def list_previews(
    session: AsyncSession, libraries: Sequence[Library]
) -> dict[int, list[LibraryCover]]:
    """The newest few pictures of every library on a list's page, which its
    card draws as a small grid where nobody chose a cover: a wall of forty
    says what it is better than any one of the forty would.

    One query for the page: a window over each library's pictures, newest
    first, cut at :data:`PREVIEW_COUNT`.
    """
    previews: dict[int, list[LibraryCover]] = {
        library.id: [] for library in libraries if library.id is not None
    }
    if not previews:
        return previews
    ranked = (
        select(
            LibraryItem,
            func.row_number()
            .over(
                partition_by=LibraryItem.library_id,
                order_by=(LibraryItem.created_at.desc(), LibraryItem.id.desc()),
            )
            .label("rank"),
        )
        .where(LibraryItem.library_id.in_(tuple(previews)))
        .subquery()
    )
    item_alias = aliased(LibraryItem, ranked)
    newest = (
        select(item_alias)
        .where(ranked.c.rank <= PREVIEW_COUNT)
        .order_by(ranked.c.library_id, ranked.c.rank)
    )
    for item in (await session.exec(newest)).all():
        cover = library_cover(item)
        if cover is not None:
            previews[item.library_id].append(cover)
    return previews


async def annotate_version_counts(
    session: AsyncSession, rows: Sequence[LibraryItem]
) -> None:
    """Set ``version_count`` on each picture from one grouped query."""
    ids = [i.id for i in rows if i.id is not None]
    if not ids:
        return
    result = await session.exec(
        select(LibraryItemVersion.library_item_id, func.count(LibraryItemVersion.id))
        .where(LibraryItemVersion.library_item_id.in_(tuple(ids)))
        .group_by(LibraryItemVersion.library_item_id)
    )
    counts = dict(result.all())
    for item in rows:
        object.__setattr__(item, "version_count", counts.get(item.id, 1))
