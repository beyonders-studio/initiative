"""Library source adapter: the importable envelope, with its pictures.

A library is its pictures, so the envelope carries what the rows say about
them — title, description, date, dimensions, the order they arrived in — and names each
blob by its **storage key**. The bytes ride beside it under ``assets/``, named
by that key: in a backup the backup adapter registers them, and a library
exported on its own is always a zip of the envelope and its pictures, because
an envelope alone would be a list of descriptions for pictures that are not there.
A picture whose file is gone is left out of the zip and still listed, which is
what the importer already expects of a missing file.

Thumbnails are deliberately **not** carried. A thumbnail is a rendition the
app makes at upload and can make again, so shipping both doubles the bytes of
a picture-heavy backup to restore something derivable.

Access rule: READ on the library (exporting is a formatted read), enforced by
the ``ToolExportAdapter.fetch`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.library import Library, LibraryItem
from app.schemas.tenant.tag import annotated_tags
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    asset_item,
    envelope_key,
    storage_key_of,
)
from app.services.export.contract import RenderItem
from app.services.export.property_values import exported_properties
from app.services.permissions import EXPORT_ACCESS

#: What one library contributes to a batch: its row and its pictures.
Loaded = tuple[Library, list[LibraryItem]]


#: The size proxy divisor for the pictures: one "row" per MiB, as an uploaded file counts, so a library of large pictures is delivered as a job.
_IMAGE_ROW_BYTES = 1_048_576


class LibraryAdapter(ToolExportAdapter):
    tool = Tool.library
    #: Always a zip, even with no pictures: the envelope and its files are one
    #: download.
    force_zip = True

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        library_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Loaded:
        """The library and its pictures, oldest first: the order they were put
        in, so a restore reads the same way round."""
        from sqlmodel import select

        from app.services.tenant import properties as properties_service
        from app.services.tenant import tags as tags_service
        from app.services.tenant.libraries import item_loader_options, item_order

        library = await super().fetch(
            session, user, guild_id, library_id, access=access
        )
        items = list(
            await session.exec(
                select(LibraryItem)
                .where(LibraryItem.library_id == library.id)
                .options(*item_loader_options())
                .order_by(*item_order(oldest_first=True))
            )
        )
        await tags_service.annotate_tags(session, items)
        await properties_service.annotate_properties(session, items)
        return library, items

    async def reach(
        self, session: AsyncSession, params: dict, loaded: list[Loaded], /
    ) -> set[int]:
        return {library.initiative_id for library, _images in loaded}

    def title(self, loaded: Loaded, /) -> str:
        library, _images = loaded
        return library.name

    def rows(self, loaded: Loaded, /) -> int:
        # A library's size is what is in it, not the single row naming it:
        # each picture counts for its megabytes, and at least one.
        _library, items = loaded
        return 1 + sum(
            max(1, int(item.current_version.file_size or 0) // _IMAGE_ROW_BYTES)
            for item in items
        )

    def item(self, loaded: Loaded, ctx: BuildContext, /) -> RenderItem:
        library, items = loaded
        return build_library_item(library, items, ctx.now)

    def items(self, loaded: Loaded, ctx: BuildContext, /) -> tuple[RenderItem, ...]:
        """The envelope, then each picture whose file is still stored."""
        from app.services.storage import get_guild_storage

        _library, items = loaded
        storage = get_guild_storage(ctx.guild_id)
        pictures = (asset_item(storage, item.current_version) for item in items)
        return (self.item(loaded, ctx), *(p for p in pictures if p is not None))


def build_library_item(
    library: Library, items: list[LibraryItem], now: datetime
) -> RenderItem:
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    return RenderItem(
        key=envelope_key(Tool.library, library.name, now.strftime("%Y-%m-%d")),
        data=_envelope(library, items),
    )


def _envelope(library: Library, items: list[LibraryItem]) -> dict[str, Any]:
    cover = next(
        (img for img in items if img.id == library.cover_item_id),
        None,
    )
    return {
        "type": tool_envelope_type(Tool.library),
        "schema_version": 1,
        "name": library.name,
        "description": library.description,
        # The cover crosses as a storage key for the reason a wiki's home page
        # crosses as a slug: an id means nothing in the guild this restores
        # into, and the key is what both sides call the same picture.
        "cover": (
            storage_key_of(cover.current_version.file_url)
            if cover is not None
            else None
        ),
        "tags": sorted(tag.name for tag in annotated_tags(library)),
        "properties": exported_properties(library),
        "items": [_item_envelope(item) for item in items],
    }


def _item_envelope(item: LibraryItem) -> dict[str, Any]:
    version = item.current_version
    return {
        "title": item.title,
        "description": item.description,
        "occurred_on": item.occurred_on.isoformat(),
        "storage_key": storage_key_of(version.file_url),
        "content_type": version.file_content_type,
        "size_bytes": version.file_size,
        "original_filename": version.original_filename,
        "width": version.width,
        "height": version.height,
        "tags": sorted(tag.name for tag in annotated_tags(item)),
        "properties": exported_properties(item),
        # What a reference to this picture points at across one import.
        "external_ref": f"library_item:{item.id}",
    }
