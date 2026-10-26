"""Catalog service — loaders, the annotations a list needs, and the picture
upload rules.

A catalog is a shareable DAC resource (``resource_type='catalog'``) holding
pictures as child rows. What is genuinely this tool's own is in two places:

* **What a picture is allowed to be.** Two gates, cheapest first.
  :func:`validate_image` reads the file's header — the format, the pixel size
  — which is a few bounds-checked slices rather than a decoder. Raster only,
  and no SVG: a picture here is drawn in an ``<img>``, and an SVG is a
  file rather than a picture. Then :func:`render_thumbnail` decodes it,
  and only a body the decoder reads is stored. A header says what a file
  claims; the decode is what confirms it.
* **The order.** Newest first, always. A catalog is a record of what arrived,
  and a design round is read in the order it happened; the timeline view
  groups the same order by day.

Thumbnails are made here, at upload, with Pillow — the one place in the
request path that decodes pixels, under a pixel ceiling. A picture small
enough not to need one is stored without it and the grid shows the picture
itself; a picture that cannot be decoded at all is not stored.
"""

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
from app.models.tenant.catalog import Catalog, CatalogItem, CatalogItemVersion
from app.schemas.tenant.catalog import CatalogCover, catalog_cover
from app.services.permissions import with_tool
from app.services.tenant import comments as comments_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service

#: How big a picture may be. Larger than a document item (10 MB): a catalog
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

#: What a picture in a catalog may be. Exactly what ``read_image_header``
#: recognizes: the raster formats an ``<img>`` draws.
PICTURE_EXTENSIONS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class InvalidImageError(ValueError):
    """The bytes are not a raster item this catalog can show."""


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
    """Eager-load what a catalog *list* row needs: its sharing, the level the
    request holds on it, and the cover it chose."""
    return [
        selectinload(Catalog.grants),
        selectinload(Catalog.initiative),
        undefer(Catalog.actions),
        selectinload(Catalog.cover_item),
    ]


def item_loader_options() -> list:
    """Eager-load what a picture needs to be drawn: who uploaded it."""
    return [
        selectinload(CatalogItem.uploader),
    ]


def item_order(*, oldest_first: bool = False) -> list:
    """The order pictures are shown in: newest first, id as the tiebreak so
    two uploaded in the same instant still order stably. ``oldest_first``
    is the same order read the other way — a design round, in sequence."""
    if oldest_first:
        return [CatalogItem.created_at.asc(), CatalogItem.id.asc()]
    return [CatalogItem.created_at.desc(), CatalogItem.id.desc()]


def anchored_clause(until, *, oldest_first: bool = False):
    """The WHERE leg for "start the list here", inclusive.

    Measured by the same instant the list is ordered by, so the picture the
    rail's anchor names is the first one the page returns — and pointed the
    same way the list is read. Newest first, an anchor is a ceiling and the
    page walks back from it; oldest first, it is a floor and the page walks
    forward. One clause with a direction rather than two, because there is
    one question: where does this page start.
    """
    if oldest_first:
        return CatalogItem.created_at >= until
    return CatalogItem.created_at <= until


async def get_catalog(
    session: AsyncSession,
    catalog_id: int,
    *,
    populate_existing: bool = False,
) -> Catalog | None:
    """Fetch a catalog as a list row carries it: what authorizing it and the
    grant flow read. RLS scopes the row to the request's guild."""
    stmt = (
        select(Catalog)
        .where(Catalog.id == catalog_id)
        .options(*list_loader_options())
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(stmt)).one_or_none()


async def get_catalog_hydrated(
    session: AsyncSession,
    catalog_id: int,
    *,
    populate_existing: bool = False,
) -> Catalog | None:
    """:func:`get_catalog` plus what a serialized ``CatalogRead`` carries
    beyond its columns: its tags, properties and comment count."""
    catalog = await get_catalog(
        session, catalog_id, populate_existing=populate_existing
    )
    if catalog is not None:
        await tags_service.annotate_tags(session, [catalog])
        await properties_service.annotate_properties(session, [catalog])
        await comments_service.annotate_comment_counts(
            session, [catalog], column="catalog_id"
        )
    return catalog


async def get_item(
    session: AsyncSession,
    item_id: int,
    *,
    catalog_id: int | None = None,
    populate_existing: bool = False,
) -> CatalogItem | None:
    """One picture, with its catalog as authorizing it reads it. ``catalog_id``
    makes a picture of another catalog read as missing."""
    stmt = (
        select(CatalogItem)
        .where(CatalogItem.id == item_id)
        .options(
            *item_loader_options(),
            with_tool(CatalogItem.catalog),
        )
    )
    if catalog_id is not None:
        stmt = stmt.where(CatalogItem.catalog_id == catalog_id)
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    item = (await session.exec(stmt)).one_or_none()
    if item is not None:
        await tags_service.annotate_tags(session, [item])
        await properties_service.annotate_properties(session, [item])
    return item


#: How many pictures a catalog shows from outside when no cover was chosen.
PREVIEW_COUNT = 4


async def list_previews(
    session: AsyncSession, catalogs: Sequence[Catalog]
) -> dict[int, list[CatalogCover]]:
    """The newest few pictures of every catalog on a list's page, which its
    card draws as a small grid where nobody chose a cover: a wall of forty
    says what it is better than any one of the forty would.

    One query for the page: a window over each catalog's pictures, newest
    first, cut at :data:`PREVIEW_COUNT`.
    """
    previews: dict[int, list[CatalogCover]] = {
        catalog.id: [] for catalog in catalogs if catalog.id is not None
    }
    if not previews:
        return previews
    ranked = (
        select(
            CatalogItem,
            func.row_number()
            .over(
                partition_by=CatalogItem.catalog_id,
                order_by=(CatalogItem.created_at.desc(), CatalogItem.id.desc()),
            )
            .label("rank"),
        )
        .where(CatalogItem.catalog_id.in_(tuple(previews)))
        .subquery()
    )
    item_alias = aliased(CatalogItem, ranked)
    newest = (
        select(item_alias)
        .where(ranked.c.rank <= PREVIEW_COUNT)
        .order_by(ranked.c.catalog_id, ranked.c.rank)
    )
    for item in (await session.exec(newest)).all():
        cover = catalog_cover(item)
        if cover is not None:
            previews[item.catalog_id].append(cover)
    return previews


async def annotate_version_counts(
    session: AsyncSession, rows: Sequence[CatalogItem]
) -> None:
    """Set ``version_count`` on each picture from one grouped query."""
    ids = [i.id for i in rows if i.id is not None]
    if not ids:
        return
    result = await session.exec(
        select(CatalogItemVersion.catalog_item_id, func.count(CatalogItemVersion.id))
        .where(CatalogItemVersion.catalog_item_id.in_(tuple(ids)))
        .group_by(CatalogItemVersion.catalog_item_id)
    )
    counts = dict(result.all())
    for item in rows:
        object.__setattr__(item, "version_count", counts.get(item.id, 1))
