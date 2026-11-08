"""Wiki source adapter: the importable envelope (json), or the whole wiki as
one document (pdf, md, docx) — and, beside either, the files filed in it.

As a document, the pages are read in the order the tree gives them, each under
a heading with its title, nested as deep as the page sits; drafts are left
out, because a copy to read is not where an unfinished page gets shown. The
files filed in the wiki ride in the same download under ``files/``,
each in the format that fits its type — a text document in the format asked
for, a spreadsheet as a workbook, an upload as itself. The importable file
carries them inside the wiki's envelope instead, with where each is filed, so
an import files them again; an upload's bytes ride under ``assets/``. A wiki
exported on its own is always a zip, filed files or not, so its download
is one kind of file whatever it holds. Only the files the exporter could export on their own come
along: filing a file in a wiki is not a way to hand over a copy of it.

A wiki is its pages and the shape they sit in, so the envelope carries both:
each page's Lexical body whole, the way the post and file envelopes carry
theirs, and the tree as a ``parent`` slug on each page.

The tree crosses as **slugs, not ids**. Ids mean nothing in the guild a backup
is restored into, and a page's slug is the name its own siblings know it by —
so a restored wiki rebuilds the same shape without having to preserve a single
primary key. Pages are written out in the order the navigation draws them,
which is siblings by position rather than a walk down each branch, so a
child can be written before its parent; the importer resolves every parent
slug in a second pass once all the pages exist.

What the envelope deliberately drops is the sharing and the home page's id.
Sharing is a fact about who is in *this* community. The home page crosses as a
slug for the same reason the tree does.

Access rule: READ on the wiki (exporting is a formatted read), enforced by the
``ToolExportAdapter.fetch`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from dataclasses import replace

from fastapi import HTTPException

from app.core.errors import CodedError
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.core.file_types import FileType, is_stored
from app.models.tenant.file import File
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.tenant.tag import annotated_tags
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    asset_item,
    envelope_key,
    export_stem,
)
from app.services.export.adapters.file import FileAdapter
from app.services.export.contract import RenderItem
from app.services.export.property_values import exported_properties
from app.services.permissions import EXPORT_ACCESS

#: What one wiki contributes to a batch: its row, its pages, and the files
#: filed in it that come along.
Loaded = tuple[Wiki, list[WikiPage], list[File]]

#: Where the filed files sit in the download.
FILES_DIR = "files/"


class WikiAdapter(ToolExportAdapter):
    tool = Tool.wiki
    template_id = "document"  # the Lexical PDF template files use
    formats = ("json", "pdf", "md", "docx")
    #: Always a zip: the wiki and the files filed in it are one download.
    force_zip = True

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        wiki_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Loaded:
        from app.services.tenant.wikis import linked_files

        wiki, pages, _ = await self.fetch_pages(
            session, user, guild_id, wiki_id, access=access
        )
        file_adapter = FileAdapter()
        files: list[File] = []
        for linked in await linked_files(session, wiki.id):
            try:
                files.append(
                    await file_adapter.fetch(
                        session, user, guild_id, linked.id, access=access
                    )
                )
            except (HTTPException, CodedError):
                # Not theirs to export: it stays out of the download.
                continue
        return wiki, pages, files

    async def fetch_pages(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        wiki_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Loaded:
        """The wiki and its pages, with no filed files. An initiative or
        community backup writes those as entries of their own and places them
        in the wiki from there. The pages come in reading order."""
        from app.services.tenant import metadata as metadata_service
        from app.services.tenant import tags as tags_service
        from app.services.tenant.wikis import load_pages

        wiki = await super().fetch(session, user, guild_id, wiki_id, access=access)
        pages = await load_pages(session, wiki.id, page_order=wiki.page_order)
        await tags_service.annotate_tags(session, pages)
        await metadata_service.annotate_properties(session, pages)
        return wiki, pages, []

    async def reach(
        self, session: AsyncSession, params: dict, loaded: list[Loaded], /
    ) -> set[int]:
        # A file filed in the wiki can belong to another initiative.
        return {
            initiative_id
            for wiki, _pages, files in loaded
            for initiative_id in (
                wiki.initiative_id,
                *(d.initiative_id for d in files),
            )
        }

    def title(self, loaded: Loaded, /) -> str:
        wiki, _pages, _files = loaded
        return wiki.name

    def rows(self, loaded: Loaded, /) -> int:
        # One row per page and per filed file: a wiki's size is what is
        # written in it, not the single row naming it.
        _wiki, pages, files = loaded
        return (len(pages) + len(files)) or 1

    def item(self, loaded: Loaded, ctx: BuildContext, /) -> RenderItem:
        wiki, pages, _files = loaded
        if ctx.format == "json":
            return build_wiki_item(wiki, pages, ctx.now)
        return build_wiki_file_item(wiki, pages, ctx)

    def items(self, loaded: Loaded, ctx: BuildContext, /) -> tuple[RenderItem, ...]:
        """The wiki, then each file filed in it — beside it as a file of
        its own, or inside its envelope with an upload's bytes beside it."""
        wiki, pages, files = loaded
        if ctx.format == "json":
            filed, uploads = filed_file_records(wiki, pages, files, ctx)
            return (build_wiki_item(wiki, pages, ctx.now, files=filed), *uploads)
        return (
            self.item(loaded, ctx),
            *(filed_file_item(file, ctx) for file in files),
        )


def _reading_order(pages: list[WikiPage]) -> list[tuple[WikiPage, int]]:
    """Each page with its depth, parents before their children.

    ``pages`` come in navigation order — siblings by position — so a page can
    precede its parent; walking the tree from the top puts every page under
    the one it is filed in. A page whose parent is not in the list sits at the
    top.
    """
    ids = {page.id for page in pages}
    children: dict[int | None, list[WikiPage]] = {}
    for page in pages:
        parent = page.parent_page_id if page.parent_page_id in ids else None
        children.setdefault(parent, []).append(page)
    ordered: list[tuple[WikiPage, int]] = []
    seen: set[int | None] = set()

    def walk(parent: int | None, depth: int) -> None:
        for page in children.get(parent, []):
            if page.id in seen:
                continue
            seen.add(page.id)
            ordered.append((page, depth))
            walk(page.id, depth + 1)

    walk(None, 0)
    return ordered


def _heading(text: str, depth: int) -> dict[str, Any]:
    return {
        "type": "heading",
        "tag": f"h{min(depth + 1, 6)}",
        "version": 1,
        "direction": "ltr",
        "format": "",
        "indent": 0,
        "children": [
            {
                "type": "text",
                "version": 1,
                "text": text,
                "format": 0,
                "style": "",
                "mode": "normal",
                "detail": 0,
            }
        ],
    }


def _page_state(page: WikiPage, depth: int) -> dict[str, Any]:
    """One page as an editor state: its title as a heading at its depth, then
    its body."""
    children: list[Any] = [_heading(page.title, depth)]
    root = (page.content or {}).get("root")
    if isinstance(root, dict):
        children.extend(root.get("children") or [])
    return {"root": {"type": "root", "version": 1, "children": children}}


def build_wiki_file_item(
    wiki: Wiki, pages: list[WikiPage], ctx: BuildContext
) -> RenderItem:
    """The wiki as one file, in the format asked for."""
    from app.services.export.i18n import et, export_locale
    from app.services.export.lexical import blocks_from_editor_state

    loc = export_locale(ctx.user)
    stem = export_stem(wiki.name, ctx.date)
    # Each page starts a page of its own in a PDF or a Word file.
    blocks: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    for page, depth in _reading_order([page for page in pages if not page.is_draft]):
        page_blocks, page_assets = blocks_from_editor_state(
            _page_state(page, depth), guild_id=ctx.guild_id
        )
        if blocks:
            blocks.append({"type": "pagebreak"})
        blocks.extend(page_blocks)
        for asset in page_assets:
            assets.setdefault(asset["key"], asset)
    return RenderItem(
        key=stem,
        data={
            # Title and footer are the wiki's own name (user data).
            "title": wiki.name,
            "footer": wiki.name,
            "page_of": et("pageOf", loc),
            "stem": stem,
            "blocks": blocks,
            "assets": list(assets.values()),
        },
    )


def filed_format(file: File, format: str) -> str:
    """The format a filed file travels in beside a wiki exported as
    ``format``: its own type decides what it can be."""
    file_type = getattr(file.file_type, "value", file.file_type)
    if file_type == FileType.lexical.value:
        return format
    if file_type == FileType.sheet.value:
        return "json" if format == "json" else "xlsx"
    if is_stored(file_type):
        return "file"
    if file_type == FileType.url.value:
        return "json" if format == "json" else "md"
    # A whiteboard is only ever its scene.
    return "json"


def filed_file_item(file: File, ctx: BuildContext) -> RenderItem:
    """One filed file, under ``files/`` in the wiki's download."""
    from app.services.export.adapters.file import build_file_item
    from app.services.export.i18n import export_locale

    format = filed_format(file, ctx.format)
    item = build_file_item(
        file,
        format,
        guild_id=ctx.guild_id,
        date=ctx.date,
        loc=export_locale(ctx.user),
    )
    if format == "file":
        name = str(item.data.get("filename") or item.key)
    elif format == "json":
        name = f"{envelope_key(Tool.file, file.name, ctx.date)}.json"
    else:
        name = f"{item.key}.{format}"
    return replace(item, format=format, filename=f"{FILES_DIR}{name}")


def build_wiki_item(
    wiki: Wiki,
    pages: list[WikiPage],
    now: datetime,
    *,
    files: list[dict[str, Any]] | None = None,
) -> RenderItem:
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    data = _envelope(wiki, pages)
    if files:
        data["files"] = files
    return RenderItem(
        key=envelope_key(Tool.wiki, wiki.name, now.strftime("%Y-%m-%d")),
        data=data,
    )


def filed_file_records(
    wiki: Wiki, pages: list[WikiPage], files: list[File], ctx: BuildContext
) -> tuple[list[dict[str, Any]], list[RenderItem]]:
    """Each filed file as the wiki's envelope carries it — whole, or for
    an upload the row and the key its bytes are zipped under — and the upload
    blobs to zip beside it. An upload whose file is gone is left out."""
    from app.services.export.adapters.file import build_file_item
    from app.services.export.i18n import export_locale
    from app.services.storage import get_guild_storage
    from app.services.tenant.wikis import file_parent, file_position

    slugs = {page.id: page.slug for page in pages}
    storage = get_guild_storage(ctx.guild_id)
    loc = export_locale(ctx.user)
    records: list[dict[str, Any]] = []
    uploads: list[RenderItem] = []
    for file in files:
        parent = file_parent(wiki, file.id)
        record: dict[str, Any] = {
            "page": slugs.get(parent) if parent is not None else None,
            "position": file_position(wiki, file.id),
            "external_ref": f"file:{file.id}",
        }
        file_type = getattr(file.file_type, "value", file.file_type)
        if is_stored(file_type):
            version = file.current_version
            asset = asset_item(storage, version)
            if version is None or asset is None:
                continue
            record["upload"] = {
                "name": file.name,
                "storage_key": asset.key,
                "original_filename": version.original_filename,
                "content_type": version.file_content_type,
                "tags": sorted(tag.name for tag in annotated_tags(file)),
                "properties": exported_properties(file),
            }
            uploads.append(asset)
        else:
            record["envelope"] = build_file_item(
                file, "json", guild_id=ctx.guild_id, date=ctx.date, loc=loc
            ).data
        records.append(record)
    return records, uploads


def _envelope(wiki: Wiki, pages: list[WikiPage]) -> dict[str, Any]:
    by_id = {page.id: page for page in pages}
    home = by_id.get(wiki.home_page_id) if wiki.home_page_id else None
    template = by_id.get(wiki.template_page_id) if wiki.template_page_id else None
    return {
        "type": tool_envelope_type(Tool.wiki),
        "schema_version": 1,
        "name": wiki.name,
        "description": wiki.description,
        "home_page": home.slug if home is not None else None,
        "template_page": template.slug if template is not None else None,
        "page_order": wiki.page_order,
        "contents_depth": wiki.contents_depth,
        "show_connections": wiki.show_connections,
        "show_updated_at": wiki.show_updated_at,
        "reading_width": wiki.reading_width,
        "accent_color": wiki.accent_color,
        "tags": sorted(tag.name for tag in annotated_tags(wiki)),
        "properties": exported_properties(wiki),
        "pages": [_page_envelope(page, by_id) for page in pages],
    }


def _page_envelope(page: WikiPage, by_id: dict[int, WikiPage]) -> dict[str, Any]:
    parent = by_id.get(page.parent_page_id) if page.parent_page_id else None
    return {
        "title": page.title,
        "slug": page.slug,
        # What this page is filed under, named the way its siblings name it.
        # None means it sits at the top of the wiki.
        "parent": parent.slug if parent is not None else None,
        "position": page.position,
        # A draft restores as a draft: it is a page somebody has not shown
        # anyone yet, and a restore is not the moment to publish it for them.
        "is_draft": page.is_draft,
        "content": page.content or {},
        "tags": sorted(tag.name for tag in annotated_tags(page)),
        "properties": exported_properties(page),
        # When it was written, and when it was last edited. A restore that
        # dated every page to the day it was restored lost the one thing a
        # wiki's reading order is usually checked against.
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        # The name this page answers to across one import, so a reference to
        # it elsewhere in the same restore points at the page it became.
        "external_ref": f"wiki_page:{page.id}",
    }
