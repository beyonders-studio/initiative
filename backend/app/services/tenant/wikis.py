"""Wiki pages: the spine, and the slugs that address it.

A wiki's pages form a tree. That tree is two columns — ``parent_page_id`` and
``position`` — and this module owns every operation that has to keep them
coherent: naming a page, filing it, moving it, and reading the tree back.

Two kinds of thing sit in that tree: the pages written in the wiki, and the
files borrowed into it. A borrowed file keeps its own address and its
own owner, so the wiki cannot write its place onto it — it records where it
put it instead, in ``Wiki.file_positions``: which page it is filed under,
and where among what else is filed there. Both are facts about this wiki, not
about the file, which may sit somewhere else entirely in another wiki. A
file is filed under a page but never holds anything itself.
:func:`load_list` is the one place pages and files are read as a single
order, and :func:`place_in_list` is the one place that order is rewritten.

A third structure, the headings inside a page, is content rather than filing
and lives in the body.

What is deliberately NOT here: anything a page connects to. A page ``part_of``
a task, a page ``related_to`` another wiki's page, and the ``references`` edges
read out of ``[[ ]]`` links in a body are all rows in ``relationships``,
handled by the services that already own that table. The order is navigation;
the edges are meaning, and they are kept apart on purpose.
"""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy.orm import defer, selectinload, undefer

from app.core.tools import KINDS
from app.core.messages import WikiMessages
from app.models.tenant.wiki import Wiki, WikiPage, WikiPageOrder
from app.services.permissions import with_tool
from app.services.tenant import comments as comments_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant.names import slugify, unique_slug


def list_loader_options() -> list:
    """Eager-load what a wiki *list* row needs: its sharing, the level the
    request holds on it, and the page it opens on."""
    return [
        selectinload(Wiki.grants),
        selectinload(Wiki.initiative),
        undefer(Wiki.actions),
        selectinload(Wiki.home_page),
    ]


async def get_wiki(
    session: AsyncSession,
    wiki_id: int,
    *,
    populate_existing: bool = False,
) -> Wiki | None:
    """Fetch a wiki as a list row carries it: what authorizing it and the
    grant flow read. RLS scopes the row to the request's guild."""
    statement = (
        select(Wiki)
        .where(Wiki.id == wiki_id)
        .options(*list_loader_options())
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(statement)).one_or_none()


async def get_wiki_hydrated(
    session: AsyncSession,
    wiki_id: int,
    *,
    populate_existing: bool = False,
) -> Wiki | None:
    """:func:`get_wiki` plus what a serialized ``WikiRead`` carries beyond its
    columns: its tags, properties and comment count."""
    wiki = await get_wiki(session, wiki_id, populate_existing=populate_existing)
    if wiki is not None:
        await tags_service.annotate_tags(session, [wiki])
        await metadata_service.annotate_properties(session, [wiki])
        await comments_service.annotate_comment_counts(
            session, [wiki], column="wiki_id"
        )
    return wiki


async def get_page(
    session: AsyncSession,
    page_id: int,
    *,
    wiki_id: int | None = None,
    populate_existing: bool = False,
) -> WikiPage | None:
    """One page, with its wiki as authorizing it reads it. ``wiki_id`` makes a
    page of another wiki read as missing rather than as somebody else's."""
    statement = (
        select(WikiPage)
        .where(WikiPage.id == page_id)
        .options(
            selectinload(WikiPage.author),
            with_tool(WikiPage.wiki),
        )
    )
    if wiki_id is not None:
        statement = statement.where(WikiPage.wiki_id == wiki_id)
    statement = statement.execution_options(populate_existing=populate_existing)
    return (await session.exec(statement)).one_or_none()


async def unique_page_slug(
    session: AsyncSession,
    wiki_id: int,
    title: str,
    *,
    exclude_page_id: int | None = None,
) -> str:
    """A slug free among this wiki's live pages, suffixing ``-2``, ``-3``, ….

    ``exclude_page_id`` is the page being renamed, which must not collide with
    itself. Trashed pages hold no slug — the session filter hides them — so a
    page can take the name of one that was thrown away, and restoring that one
    is where the conflict surfaces.
    """
    statement = select(WikiPage.slug).where(WikiPage.wiki_id == wiki_id)
    if exclude_page_id is not None:
        statement = statement.where(WikiPage.id != exclude_page_id)
    taken = set((await session.exec(statement)).all())
    return unique_slug(slugify(title, fallback="page"), taken)


async def next_position(
    session: AsyncSession, wiki: Wiki, parent_page_id: int | None = None
) -> int:
    """Where a new page lands: after the last thing filed beside it.

    Positions are sparse and never renumbered on insert, so this is a read of
    the current maximum rather than a count. At the top level it reads the
    files' places too, because they are filed there and a new page goes
    after them.
    """
    statement = select(WikiPage.position).where(WikiPage.wiki_id == wiki.id)
    statement = (
        statement.where(WikiPage.parent_page_id.is_(None))
        if parent_page_id is None
        else statement.where(WikiPage.parent_page_id == parent_page_id)
    )
    positions = list((await session.exec(statement)).all())
    for spot in (wiki.file_positions or {}).values():
        position, parent = _read_placement(spot)
        if parent == parent_page_id and position != UNPLACED:
            positions.append(position)
    return (max(positions) + 1) if positions else 0


#: How each ordering sorts pages. ``manual`` reads the spine somebody
#: dragged; the others ignore it, which is the point — nobody hand-orders two
#: hundred entries, and a decisions log wants the newest at the top.
_ORDERINGS = {
    WikiPageOrder.manual: lambda: (WikiPage.position, WikiPage.id),
    WikiPageOrder.title: lambda: (func.lower(WikiPage.title), WikiPage.id),
    WikiPageOrder.recently_updated: lambda: (
        WikiPage.updated_at.desc(),
        WikiPage.id.desc(),
    ),
}


async def load_pages(
    session: AsyncSession,
    wiki_id: int,
    *,
    page_order: WikiPageOrder = WikiPageOrder.manual,
) -> list[WikiPage]:
    """Every live page of a wiki the reader can see, in the order the
    navigation draws them. A draft is part of the wiki for the people who write
    it and not for the people who read it (the ``wiki_pages`` read policy)."""
    statement = select(WikiPage).where(WikiPage.wiki_id == wiki_id)
    return list(
        (await session.exec(statement.order_by(*_ORDERINGS[page_order]()))).all()
    )


#: Where something nobody has placed sits: after everything that has been. Far
#: enough out that no real position reaches it, and the same for every one of
#: them, so unplaced files fall back to the tie-break below (their name).
UNPLACED = 1_000_000_000


def _read_placement(recorded: Any) -> tuple[int, int | None]:
    """A recorded place as ``(position, parent page id)``.

    Written as ``{"position": 3, "parent": 12}``; a bare number is a place
    recorded before files could be filed under a page, which is the top.
    """
    if isinstance(recorded, bool):
        return UNPLACED, None
    if isinstance(recorded, int):
        return recorded, None
    if isinstance(recorded, dict):
        position = recorded.get("position")
        parent = recorded.get("parent")
        return (
            position
            if isinstance(position, int) and not isinstance(position, bool)
            else UNPLACED,
            parent
            if isinstance(parent, int) and not isinstance(parent, bool)
            else None,
        )
    return UNPLACED, None


def _placement(wiki: Wiki, file_id: int) -> tuple[int, int | None]:
    return _read_placement((wiki.file_positions or {}).get(str(file_id)))


def file_parent(wiki: Wiki, file_id: int) -> int | None:
    """The page this wiki files the file under, or ``None`` for the top."""
    return _placement(wiki, file_id)[1]


def file_position(wiki: Wiki, file_id: int) -> int:
    """Where among its siblings this wiki puts the file, or the end if it
    has not said."""
    return _placement(wiki, file_id)[0]


def place_file(
    wiki: Wiki,
    file_id: int,
    *,
    parent_page_id: int | None,
    position: int | None = None,
) -> None:
    """Place a file under a page (or at the top) — at ``position``, or at
    the end of what is already there. For an import, which places each file
    under the page it was attached to without a drag."""
    placements = dict(wiki.file_positions or {})
    placements[str(file_id)] = {
        "position": UNPLACED if position is None else position,
        "parent": parent_page_id,
    }
    wiki.file_positions = placements


def _sort_key(wiki: Wiki, item: Any, page_order: WikiPageOrder):
    """One key over both kinds of row, so a list can hold them together.

    A page and a file answer the same three questions in different words —
    a page has a ``title`` and a file a ``name`` — so the key asks each in
    its own terms and the comparison never sees the difference.
    """
    is_page = isinstance(item, WikiPage)
    title = (item.title if is_page else item.name) or ""
    if page_order is WikiPageOrder.title:
        return (title.lower(), item.id)
    if page_order is WikiPageOrder.recently_updated:
        # Negated rather than reversed: the whole list sorts one way, and
        # "recently updated" means the newest first.
        return (-item.updated_at.timestamp(), -item.id)
    position = item.position if is_page else file_position(wiki, item.id)
    # Ties are ordinary: positions are sparse and a page arrives at 0 before
    # anybody drags anything. Broken by arrival — pages first, then the
    # files borrowed in — rather than by name, so a list somebody has not
    # arranged still reads in the order it was written.
    return (position, 0 if is_page else 1, item.id)


def visible_file_parent(wiki: Wiki, file_id: int, known: set[int]) -> int | None:
    """The page a file is filed under, as far as this read can see: one
    under a page the reader cannot see — a draft, or a page in the trash — is
    drawn at the top rather than dropped."""
    parent = file_parent(wiki, file_id)
    return parent if parent in known else None


def _parent_of(item: Any, known: set[int]) -> int | None:
    """What a row is filed under, as far as THIS read can see.

    A page whose parent is not in the set — a draft hidden from a reader, a
    page the reader may not see — is drawn at the top rather than dropped, so a
    partial read still shows every row it was given.
    """
    parent = getattr(item, "parent_page_id", None)
    return parent if parent in known else None


async def load_list(
    session: AsyncSession,
    wiki: Wiki,
) -> list[tuple[Any, list]]:
    """A wiki's whole tree — its pages and its files — in reading order,
    each with the heading nodes of its body.

    Depth-first: each row, then everything filed under it. The navigation draws
    this, and the order it comes back in is the order it reads in. Assembled
    here rather than in SQL because it spans two tables and a wiki's list is
    the size of a table of contents, not of a table.

    No body is read: the navigation draws a row's headings and nothing else of
    it, so the database picks those out (:func:`heading_nodes`).
    """
    from app.models.tenant.file import File

    page_rows = (
        await session.exec(
            select(WikiPage, heading_nodes(WikiPage.content))
            .where(WikiPage.wiki_id == wiki.id)
            .options(defer(WikiPage.content), defer(WikiPage.yjs_state))
        )
    ).all()
    file_ids = await _linked_file_ids(session, wiki.id)
    file_rows = (
        (
            await session.exec(
                select(File, heading_nodes(File.content))
                .where(File.id.in_(file_ids))
                .options(undefer(File.smart_link_url))
            )
        ).all()
        if file_ids
        else []
    )
    nodes_of = {
        (type(item), item.id): nodes for item, nodes in (*page_rows, *file_rows)
    }
    pages = [page for page, _ in page_rows]
    files = [file for file, _ in file_rows]
    known = {page.id for page in pages}

    filed: dict[int | None, list[Any]] = {}
    for item in (*pages, *files):
        parent = (
            _parent_of(item, known)
            if isinstance(item, WikiPage)
            else visible_file_parent(wiki, item.id, known)
        )
        filed.setdefault(parent, []).append(item)
    for group in filed.values():
        group.sort(key=lambda item: _sort_key(wiki, item, wiki.page_order))

    ordered: list[Any] = []

    def walk(parent: int | None) -> None:
        for item in filed.get(parent, []):
            ordered.append(item)
            if isinstance(item, WikiPage):
                walk(item.id)

    walk(None)
    return [(item, nodes_of[(type(item), item.id)]) for item in ordered]


async def siblings_of(
    session: AsyncSession, wiki: Wiki, parent_page_id: int | None
) -> list[Any]:
    """Everything filed in one place, in order: the pages and the files
    filed there together, since one drag arranges them as one list.

    A file filed under a page that is gone counts at the top, where the
    tree draws it.
    """
    all_pages = await load_pages(session, wiki.id, page_order=wiki.page_order)
    known = {page.id for page in all_pages}
    group: list[Any] = [
        page for page in all_pages if page.parent_page_id == parent_page_id
    ]
    group.extend(
        file
        for file in await linked_files(session, wiki.id)
        if visible_file_parent(wiki, file.id, known) == parent_page_id
    )
    group.sort(key=lambda item: _sort_key(wiki, item, wiki.page_order))
    return group


async def place_in_list(
    session: AsyncSession,
    wiki: Wiki,
    moved: Any,
    position: int,
    parent_page_id: int | None = None,
) -> None:
    """File one row somewhere and put it in order there — what a drag is.

    Only the row's new neighbours are renumbered: positions mean something
    among the things filed together and nothing across the tree, so one pass
    over one group leaves no two of them sharing a number. Each is written
    where it can be — a page in its own columns, a file in the wiki's
    record of where it put things — so a file is filed and reordered
    without being touched.

    Drafts are counted even for a reader who cannot see them: the index comes
    from a list the person dragging was looking at, and they can write here.
    """
    if isinstance(moved, WikiPage):
        moved.parent_page_id = parent_page_id
        session.add(moved)
    else:
        # Recorded before the group is read, so the file counts among the
        # things filed where it is going rather than where it was.
        place_file(wiki, moved.id, parent_page_id=parent_page_id)

    others = [
        item
        for item in await siblings_of(session, wiki, parent_page_id)
        if not (type(item) is type(moved) and item.id == moved.id)
    ]
    index = min(position, len(others))
    ordered = [*others[:index], moved, *others[index:]]

    placements = dict(wiki.file_positions or {})
    for spot, item in enumerate(ordered):
        if isinstance(item, WikiPage):
            item.position = spot
            session.add(item)
        else:
            placements[str(item.id)] = {"position": spot, "parent": parent_page_id}
    # Replaced rather than mutated: SQLAlchemy tracks the attribute, not what
    # the dict does to itself.
    wiki.file_positions = placements
    session.add(wiki)


def descendant_ids(pages: Iterable[WikiPage], root_id: int) -> set[int]:
    """Every page beneath ``root_id``, the root excluded."""
    filed: dict[int | None, list[int]] = {}
    for page in pages:
        filed.setdefault(page.parent_page_id, []).append(page.id)

    found: set[int] = set()
    frontier = list(filed.get(root_id, []))
    while frontier:
        page_id = frontier.pop()
        if page_id in found:
            continue
        found.add(page_id)
        frontier.extend(filed.get(page_id, []))
    return found


async def validate_reparent(
    session: AsyncSession, page: WikiPage, new_parent_id: int | None
) -> None:
    """Refuse a move that would take a branch out of the tree.

    A page cannot be filed under itself, under one of its own descendants, or
    under a page belonging to another wiki.
    """
    if new_parent_id is None:
        return
    if new_parent_id == page.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WikiMessages.PAGE_PARENT_ITSELF,
        )

    parent = await get_page(session, new_parent_id, wiki_id=page.wiki_id)
    if parent is None:
        raise KINDS["wiki_page"].not_found()

    pages = await load_pages(session, page.wiki_id)
    if new_parent_id in descendant_ids(pages, page.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WikiMessages.PAGE_PARENT_DESCENDANT,
        )


def forget_file_placement(wiki: Wiki, file_id: int) -> None:
    """Drop a file's place when it leaves the wiki, so it does not come
    back to a spot it was given last time."""
    placements = dict(wiki.file_positions or {})
    if placements.pop(str(file_id), None) is not None:
        wiki.file_positions = placements


#: Where a Lexical body keeps its headings: every node of type ``heading``, at
#: any depth, in the order they appear.
_HEADING_NODES = 'strict $.** ? (@.type == "heading")'


def heading_nodes(content: Any) -> Any:
    """The heading nodes of a body column, picked out by the database, so a
    list reads a page's headings without reading the page."""
    return func.jsonb_path_query_array(content, cast(_HEADING_NODES, JSONPATH))


#: What an anchor keeps. Mirrors ``slugify`` in the frontend, which is what
#: stamps the ``id`` on a rendered heading — the two have to agree or a link
#: from the navigation lands nowhere.
_ANCHOR_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")


def anchor_slug(text: str) -> str:
    """A heading's anchor, as the editor stamps it on the rendered element."""
    kept = "".join(
        ch if ch in _ANCHOR_CHARS else "-" if ch.isspace() else ""
        for ch in text.strip().lower()
    )
    while "--" in kept:
        kept = kept.replace("--", "-")
    return kept.strip("-")


def _node_text(node: Any) -> str:
    """Every bit of text under a node, in order."""
    if not isinstance(node, dict):
        return ""
    own = node.get("text")
    parts = [own] if isinstance(own, str) else []
    children = node.get("children")
    if isinstance(children, list):
        parts.extend(_node_text(child) for child in children)
    return "".join(parts)


def page_headings(content: Any) -> list[dict[str, Any]]:
    """The headings written on a page, in the order they appear.

    Read from the stored body rather than from an editor, because the
    navigation draws the headings of every page in a wiki and only one of them
    is ever open. ``content`` is the body, or the nodes :func:`heading_nodes`
    picked out of it. Level comes from the tag, and the anchor is what the
    editor stamps on the heading when it renders it.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "heading":
            text = _node_text(node).strip()
            tag = node.get("tag")
            level = int(tag[1:]) if isinstance(tag, str) and tag[1:].isdigit() else 2
            if text:
                found.append(
                    {"text": text, "level": level, "anchor": anchor_slug(text)}
                )
        for child in node.get("children") or []:
            walk(child)

    if isinstance(content, dict):
        walk(content.get("root"))
    elif isinstance(content, list):
        for node in content:
            walk(node)
    return found


async def linked_files(session: AsyncSession, wiki_id: int) -> list[Any]:
    """The files somebody has put in this wiki.

    A file joins a wiki by an edge, not by a column: ``file part_of
    wiki`` is exactly the fact being asserted, and ``relationships`` already
    holds facts of that shape. So a file can sit in a wiki without being
    moved, copied, or owned by it — it stays the file it was, in whatever
    else it also belongs to.
    """
    from app.models.tenant.file import File

    file_ids = await _linked_file_ids(session, wiki_id)
    if not file_ids:
        return []

    # RLS is the gate, as everywhere else: a file the reader may not see
    # simply does not come back, and the wiki is shorter by one row.
    rows = (await session.exec(select(File).where(File.id.in_(file_ids)))).all()
    return list(rows)


async def _linked_file_ids(session: AsyncSession, wiki_id: int) -> list[int]:
    """The ids of the files somebody has put in this wiki, by the
    ``file part_of wiki`` edges (:func:`linked_files`)."""
    from app.core.relationships import RelationshipType, decode_node_id, node_id
    from app.core.search import SearchEntityType
    from app.models.tenant.relationship import EntityRelationship

    edges = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.target_node
                == node_id(SearchEntityType.wiki, wiki_id),
                EntityRelationship.relationship_type == RelationshipType.part_of,
                EntityRelationship.removed_at.is_(None),
            )
        )
    ).all()

    return [
        entity_id
        for kind, entity_id in (decode_node_id(edge.source_node) for edge in edges)
        if kind is SearchEntityType.file
    ]
