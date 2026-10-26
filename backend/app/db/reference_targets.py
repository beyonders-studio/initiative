"""What can be referred to, and how a reference is resolved.

A `#` link, a `[[ ]]` link and a smart chip all name the same thing: one row,
in one guild schema. Resolving one asks two questions — *what is it called now* and
*may this request see it* — and neither answer is written down here.

Both come from :data:`~app.db.search_index.SEARCH_SOURCES`, which every
searchable table already declares:

- ``title`` — the column holding the row's name (``name``, ``title``, ``label``).
- ``dac_tool`` / ``dac_id`` — the resource whose sharing governs the row, which
  is often its parent: a task is shared as part of its project.

So a tool added to that registry becomes referenceable, resolvable and gated
without an edit here. What this module states is only the shape of the
derivation, and the two kinds that are deliberately not referenceable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from sqlalchemy import Select, Table, case, func, literal, null, select, text
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlmodel import SQLModel

from app.core.references import NOT_REFERENCEABLE
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.blocking import open_expr
from app.db.initiative_rls import INITIATIVE_PATHS
from app.db.search_index import SEARCH_SOURCES
from app.db.authorization import standing_arg


def _table_for(entity_type: SearchEntityType) -> str:
    for table, source in SEARCH_SOURCES.items():
        if source.entity_type is entity_type:
            return table
    raise KeyError(entity_type)


def referenceable_types() -> tuple[SearchEntityType, ...]:
    """Every kind a reference can name, sorted."""
    return tuple(
        sorted(
            (
                source.entity_type
                for source in SEARCH_SOURCES.values()
                if source.entity_type not in NOT_REFERENCEABLE
            ),
            key=lambda t: t.value,
        )
    )


def title_column(entity_type: SearchEntityType):
    """The column holding what a row of this kind is called."""
    table = _table_for(entity_type)
    return SQLModel.metadata.tables[table].c[SEARCH_SOURCES[table].title]


def id_column(entity_type: SearchEntityType):
    """The column addressing a row of this kind."""
    return SQLModel.metadata.tables[_table_for(entity_type)].c["id"]


@dataclass(frozen=True)
class Preview:
    """Pictures that live on another table — a catalog's are its own images.

    The chosen one stands alone; with none chosen, the newest few stand in for
    it. That is what a catalog shows of itself everywhere else, and a catalog
    nobody has picked a cover for is the usual kind.
    """

    #: The table the pictures are on.
    table: str
    #: Column there pointing back at this row.
    parent_fk: str
    #: Column here naming the one picture somebody chose, if any.
    chosen_fk: str
    #: Columns on a picture, coalesced in preference order.
    columns: tuple[str, ...]
    #: Column deciding which are newest.
    newest_by: str
    #: How many stand in when none was chosen.
    limit: int = 4


@dataclass(frozen=True)
class Visual:
    """What a kind shows of itself besides its name.

    Three possibilities, in the order a mixed list tries them: a picture, an
    emoji, a colour. Most kinds declare none and draw as their kind's own icon,
    which is the honest answer for a thing with no look of its own rather than a
    blank where a picture would go.

    ``image`` names columns coalesced in preference order, because a catalog
    thumbnail is absent whenever the source was already small enough not to need
    one — so the full picture is the fallback, decided here rather than by every
    surface that draws one.

    A column named ``pointer.column`` is read from the row the foreign key
    ``pointer`` names: a file's facts live on its current version.
    """

    image: tuple[str, ...] = ()
    preview: Preview | None = None
    icon: str | None = None
    color: str | None = None
    #: Columns saying what SORT of thing this is within its kind, for a kind
    #: whose icon depends on that rather than being fixed: a spreadsheet, a
    #: whiteboard and a PDF are all files and none of them should draw as a
    #: scroll. These are the same three facts a recent item already carries, plus
    #: the link a smart link points at, so a client picks the icon with the
    #: helper it already has instead of fetching each row to find out.
    file_type: str | None = None
    mime: str | None = None
    filename: str | None = None
    #: A JSON column and the key inside it holding a link, for a kind that keeps
    #: one there rather than in a column of its own. Only that key is read, never
    #: the whole body — which for a file is the largest thing it has.
    link_in_json: tuple[str, str] | None = None


#: Keyed by table, the way :data:`~app.db.search_index.SEARCH_SOURCES` is. A
#: table with no entry has no look of its own, which is most of them.
#: A picture's file and its thumbnail, read from the version it shows.
_PICTURE = ("current_version_id.thumbnail_url", "current_version_id.file_url")

VISUALS: dict[str, Visual] = {
    "files": Visual(
        image=("featured_image_url",),
        file_type="file_type",
        mime="current_version_id.file_content_type",
        filename="current_version_id.original_filename",
        link_in_json=("content", "url"),
    ),
    "catalog_items": Visual(image=_PICTURE),
    "catalogs": Visual(
        preview=Preview(
            table="catalog_items",
            parent_fk="catalog_id",
            chosen_fk="cover_item_id",
            columns=_PICTURE,
            newest_by="created_at",
        )
    ),
    "projects": Visual(icon="icon"),
    "calendars": Visual(color="color"),
    "counters": Visual(color="color"),
    "queue_items": Visual(color="color"),
    "tags": Visual(color="color"),
}


def _live(table: Table):
    """Rows that still exist. Trash is browsed, not linked to."""
    return table.c["deleted_at"].is_(None) if "deleted_at" in table.c else None


def visible_ids(
    entity_type: SearchEntityType, user_id: int | None, *, need_write: bool = False
) -> Select:
    """Ids of this kind that ``user_id`` may open, or may edit.

    Joins the row to the resource that governs it — its own, or its parent's —
    and asks ``resource_access``, the same function the tables' own RLS
    policies call. A kind with no sharing of its own (the guild's tags) is
    reachable by anyone who reached the schema, which is the whole gate for it.

    ``need_write`` asks the same question at edit level. It is the caller's to
    say, because reaching a thing and changing it are different questions and
    only the caller knows which it is asking.
    """
    table_name = _table_for(entity_type)
    source = SEARCH_SOURCES[table_name]
    table = SQLModel.metadata.tables[table_name]

    statement = select(table.c["id"])
    live = _live(table)
    if live is not None:
        statement = statement.where(live)

    if source.dac_tool is None:
        return statement

    resource = SQLModel.metadata.tables[source.dac_tool.plural]
    if resource is table:
        # The row IS the shared resource — a project, a file. Nothing to
        # join to; it answers for itself.
        return statement.where(
            func.resource_access(
                source.dac_tool.value,
                table.c["id"],
                user_id,
                table.c["initiative_id"],
                need_write,
                standing_arg(),
            )
        )

    # The row is shared as part of its parent: a task by its project, an event
    # by its calendar. The pair naming that parent is the one the index stores.
    local = table.c[source.dac_id] if source.dac_id else table.c["id"]
    return statement.select_from(table.join(resource, resource.c["id"] == local)).where(
        func.resource_access(
            source.dac_tool.value,
            resource.c["id"],
            user_id,
            resource.c["initiative_id"],
            need_write,
            standing_arg(),
        )
    )


async def live_ids(
    session, entity_type: SearchEntityType, ids: Sequence[int]
) -> set[int]:
    """Which of these ids still exist and this session may read.

    Asked as the session itself, which is what a caller mid-save wants: the
    question is what the person writing this content can point at, and their
    connection answers it the same way it answers every other statement.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    if not wanted:
        return set()
    table = SQLModel.metadata.tables[_table_for(entity_type)]
    statement = select(table.c["id"]).where(table.c["id"].in_(wanted))
    live = _live(table)
    if live is not None:
        statement = statement.where(live)
    return {row[0] for row in (await session.exec(statement)).all()}


async def unfrozen_ids(
    session, entity_type: SearchEntityType, ids: Sequence[int]
) -> set[int]:
    """Which of these are still taking writes — not archived or trashed, and
    not sitting under something that is.

    Asked through ``resource_frozen``, the same declaration the freeze
    policies are rendered from, so a caller checking before it writes and the
    database deciding afterwards are reading one answer.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    if not wanted:
        return set()
    table_name = _table_for(entity_type)
    table = SQLModel.metadata.tables[table_name]
    rows = await session.exec(
        select(table.c["id"]).where(
            table.c["id"].in_(wanted),
            ~func.resource_frozen(table_name, table.c["id"], False),
        )
    )
    return {row[0] for row in rows.all()}


def _coalesced(columns):
    """One expression from columns tried in order."""
    return func.coalesce(*columns) if len(columns) > 1 else columns[0]


def _column(table: Table, name: str):
    """A column of ``table``, or for ``pointer.column`` the column of the row
    the foreign key ``pointer`` names."""
    pointer, _, column = name.rpartition(".")
    if not pointer:
        return table.c[column]
    (key,) = table.c[pointer].foreign_keys
    target = key.column.table
    return (
        select(target.c[column])
        .where(target.c["id"] == table.c[pointer])
        .scalar_subquery()
    )


def _urls_of(picked, column: str):
    """The URLs a subquery selected, as one array. NULL when it picked none."""
    rows = picked.subquery()
    return select(func.array_agg(rows.c[column])).scalar_subquery()


def _preview_expr(table: Table, preview: Preview):
    """The pictures a row shows of itself, as an array of URLs.

    One when somebody chose it, the newest few when nobody did. Ordering and
    limiting happen in the database rather than over a page of rows here,
    because this runs once per kind for a whole page of edges.
    """
    other = SQLModel.metadata.tables[preview.table]
    url = _coalesced([_column(other, name) for name in preview.columns]).label("url")
    live = _live(other)

    chosen = select(url).where(other.c["id"] == table.c[preview.chosen_fk])
    newest = (
        select(url)
        .where(other.c[preview.parent_fk] == table.c["id"])
        .order_by(other.c[preview.newest_by].desc())
        .limit(preview.limit)
    )
    if live is not None:
        # A picture in the trash is not one to draw.
        chosen = chosen.where(live)
        newest = newest.where(live)

    return case(
        (
            table.c[preview.chosen_fk].isnot(None),
            _urls_of(chosen, "url"),
        ),
        else_=_urls_of(newest, "url"),
    )


def _visual_exprs(table_name: str, table: Table):
    """How one kind draws, as select expressions: the picture, the emoji, the
    colour, and the four facts that pick an icon for a kind that has no fixed
    one.

    A kind declaring nothing selects NULLs rather than being special-cased by the
    caller, so the shape of the row is the same whatever is asked for.
    """
    visual = VISUALS.get(table_name, Visual())

    if visual.image:
        # A row with no picture reports no pictures, not one that is null.
        one = _coalesced([_column(table, name) for name in visual.image])
        images = case((one.isnot(None), pg_array([one])), else_=null())
    elif visual.preview is not None:
        images = _preview_expr(table, visual.preview)
    else:
        images = null()

    icon = table.c[visual.icon] if visual.icon else null()
    color = table.c[visual.color] if visual.color else null()
    facets = tuple(
        _column(table, name) if name else null()
        for name in (visual.file_type, visual.mime, visual.filename)
    )
    if visual.link_in_json is not None:
        # One key out of the JSON, never the body around it.
        column, key = visual.link_in_json
        link_url = table.c[column][key].astext
    else:
        link_url = null()
    return (images, icon, color, *facets, link_url)


def _governing_tool(table_name: str, table: Table):
    """``(tool, id-expression)`` naming what a row of this kind is addressed
    inside — its project for a task, its calendar for an event.

    The same pair a search hit carries, from the same declaration, because a
    link to a thing with no page of its own needs its parent's id to be built at
    all. A kind whose governing tool differs per row (only a comment, which is
    not referenceable) reports none rather than a guess.
    """
    source = SEARCH_SOURCES[table_name]
    if source.dac_tool is None or source.dac_sql is not None:
        return None, null()
    local = table.c[source.dac_id] if source.dac_id else table.c["id"]
    return source.dac_tool, local


def _container_title(table_name: str, table: Table, tool: Tool | None):
    """The table holding what a row is addressed inside, and its name column.

    A name on its own identifies nothing in a list of mixed things: six
    projects run from one template hold six tasks called "Do a thing", and the
    project is the only thing that tells them apart. A kind that governs itself
    — which every tool does — has no container to name and reports none.
    """
    source = SEARCH_SOURCES[table_name]
    if tool is None or source.dac_id is None:
        return None, null()
    container = SQLModel.metadata.tables[tool.plural]
    return container, container.c[SEARCH_SOURCES[tool.plural].title]


@dataclass(frozen=True)
class Resolved:
    """What a reference turned out to name."""

    entity_type: SearchEntityType
    id: int
    title: str | None
    #: The initiative the row belongs to. None means one of two different
    #: things, which :attr:`scoped_kind` tells apart.
    initiative_id: int | None
    #: Whether rows of this kind belong to an initiative at all. A tag does not
    #: — it is the guild's own vocabulary — so it pairs with anything in the
    #: guild. A calendar event does, and a NULL there means this particular one
    #: sits on a guild calendar, which is guild-level content rather than
    #: initiative content.
    scoped_kind: bool
    #: Whether the row is archived. Every tool can be, as can a task and an
    #: initiative; a kind that carries no archive lifecycle reports False, which
    #: is the honest answer for a kind with no such state rather than a default
    #: standing in for one.
    archived: bool
    #: When the row last changed, for the surfaces that order by recency. None
    #: for a kind that records no such moment.
    updated_at: datetime | None = None
    #: The tool this row is addressed inside, and which one of them. A task is
    #: addressed in its project and an event in its calendar, so a link to one
    #: cannot be built from its own id alone.
    tool: Tool | None = None
    tool_id: int | None = None
    #: What that tool is CALLED, for the surfaces that show a list of mixed
    #: things: "Do a thing" says nothing until it says which project. None for
    #: a row that is a tool itself.
    tool_title: str | None = None
    #: What the row shows of itself beside its name — see :class:`Visual`. At
    #: most one of the three is set, and most kinds set none. A picture is a
    #: list because a catalog shows several when nobody picked one.
    image_urls: list[str] = field(default_factory=list)
    icon: str | None = None
    color: str | None = None
    #: What sort of thing it is within its kind, for the kinds whose icon
    #: depends on that. Only files report these.
    file_type: str | None = None
    mime_type: str | None = None
    original_filename: str | None = None
    smart_link_url: str | None = None
    #: Whether this row is still outstanding — still capable of holding
    #: something else up. None for a kind that never finishes, which is most of
    #: them; see :mod:`app.db.blocking`.
    is_open: bool | None = None


async def resolve_many(
    session, entity_type: SearchEntityType, ids: Sequence[int], *, user_id: int | None
) -> dict[int, Resolved]:
    """The rows of one kind this reader may open, keyed by id.

    One query for the lot. The initiative comes from the same
    ``INITIATIVE_PATHS`` entry that renders the kind's RLS, so a surface asking
    "are these two in one initiative" and the policy deciding who may read them
    are working from one declaration rather than two.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    if not wanted:
        return {}

    table_name = _table_for(entity_type)
    table = SQLModel.metadata.tables[table_name]
    path = INITIATIVE_PATHS.get(table_name)
    initiative = text(path.initiative_expr(table_name)) if path is not None else null()
    archived = (
        table.c["archived_at"].isnot(None)
        if "archived_at" in table.c
        else literal(False)
    )
    updated = table.c["updated_at"] if "updated_at" in table.c else null()
    images, icon, color, doc_type, mime, filename, link_url = _visual_exprs(
        table_name, table
    )
    tool, tool_id = _governing_tool(table_name, table)
    container, tool_title = _container_title(table_name, table, tool)
    is_open = open_expr(table_name, table)

    stmt = select(
        table.c["id"],
        title_column(entity_type),
        initiative,
        archived,
        updated,
        tool_id,
        images,
        icon,
        color,
        doc_type,
        mime,
        filename,
        link_url,
        tool_title,
        is_open,
    ).select_from(table)
    if container is not None:
        # Left: a container this reader cannot see leaves the name blank rather
        # than dropping a row they were allowed to resolve.
        stmt = stmt.join(container, container.c["id"] == tool_id, isouter=True)
    rows = await session.exec(
        stmt.where(
            table.c["id"].in_(wanted),
            table.c["id"].in_(visible_ids(entity_type, user_id)),
        )
    )
    return {
        row[0]: Resolved(
            entity_type=entity_type,
            id=row[0],
            title=row[1],
            initiative_id=row[2],
            scoped_kind=path is not None,
            archived=bool(row[3]),
            updated_at=row[4],
            tool=tool,
            tool_id=row[5],
            image_urls=list(row[6] or ()),
            icon=row[7],
            color=row[8],
            file_type=row[9],
            mime_type=row[10],
            original_filename=row[11],
            smart_link_url=row[12],
            tool_title=row[13],
            is_open=None if row[14] is None else bool(row[14]),
        )
        for row in rows.all()
    }


async def resolve_one(
    session, entity_type: SearchEntityType, entity_id: int, *, user_id: int | None
) -> Resolved | None:
    """:func:`resolve_many` for one id."""
    found = await resolve_many(session, entity_type, [entity_id], user_id=user_id)
    return found.get(entity_id)
