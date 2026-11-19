"""What can be referred to, and how a reference is resolved.

A `#` link, a `[[ ]]` link and a smart chip all name the same thing: one row,
in one guild schema. Resolving one asks two questions — *what is it called now* and
*may this request see it* — and neither answer is written down here.

The name is the ``title`` column the search registry
(:func:`~app.db.search_index.search_sources`) declares for every searchable
table. The tool whose sharing governs a row, which is often its parent's (a
task is shared as part of its project), is the one the path its row security
is rendered from names (``app.db.initiative_rls.governing_walk``). Both are
read in the community's tool set, so a tool plug-in's rows resolve as a built-in tool's do,
and a tool added to either registry becomes referenceable, resolvable and gated
without an edit here. What this module states is only the shape of the
derivation, and the two kinds that are deliberately not referenceable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from sqlalchemy import Select, Table, case, func, literal, null, select, text
from sqlalchemy.dialects.postgresql import array as pg_array

from app.core import usernames
from app.core.references import NOT_REFERENCEABLE
from app.core.relationships import PERSON
from app.core.search import SearchEntityType
from app.core.tool_set import KEPT_TOOL_SETS, ToolSet
from app.core.user_display import display_name
from app.db.authorization import standing_arg
from app.db.blocking import open_expr
from app.db.initiative_rls import governing_walk, paths_for
from app.db.search_index import SEARCH_SOURCES, search_sources
from app.db.session import routed_tools
from app.db.tool_rows import joined_up
from app.models.platform.user_profile_view import MemberProfile


@lru_cache(KEPT_TOOL_SETS)
def _tables_by_kind(tools: ToolSet) -> dict[str, str]:
    """Each kind's table, in a community with ``tools``."""
    return {
        source.entity_type: table for table, source in search_sources(tools).items()
    }


def _table_for(entity_type: str, tools: ToolSet) -> str:
    return _tables_by_kind(tools)[entity_type]


def referenceable_types() -> tuple[SearchEntityType, ...]:
    """Every kind a reference can name, sorted."""
    return tuple(
        sorted(
            (
                SearchEntityType(source.entity_type)
                for source in SEARCH_SOURCES.values()
                if source.entity_type not in NOT_REFERENCEABLE
            ),
            key=lambda t: t.value,
        )
    )


def title_column(entity_type: str, *, tools: ToolSet):
    """The column holding what a row of this kind is called."""
    table = _table_for(entity_type, tools)
    return tools.tables[table].c[search_sources(tools)[table].title]


def id_column(entity_type: str, *, tools: ToolSet):
    """The column addressing a row of this kind."""
    return tools.tables[_table_for(entity_type, tools)].c["id"]


@dataclass(frozen=True)
class Visual:
    """What a kind shows of itself besides its name.

    Three possibilities, in the order a mixed list tries them: a picture, an
    emoji, a colour. Most kinds declare none and draw as their kind's own icon,
    which is the honest answer for a thing with no look of its own rather than a
    blank where a picture would go.

    ``image`` names columns coalesced in preference order, so a fallback is
    decided here rather than by every surface that draws one.

    A column named ``pointer.column`` is read from the row the foreign key
    ``pointer`` names: a file's facts live on its current version.
    """

    image: tuple[str, ...] = ()
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
VISUALS: dict[str, Visual] = {
    "files": Visual(
        image=("featured_image_url",),
        file_type="file_type",
        mime="current_version_id.file_content_type",
        filename="current_version_id.original_filename",
        link_in_json=("content", "url"),
    ),
    "projects": Visual(icon="icon"),
    "calendars": Visual(color="color"),
    "counters": Visual(color="color"),
    "tags": Visual(color="color"),
}


def _live(table: Table):
    """Rows that still exist. Trash is browsed, not linked to."""
    return table.c["deleted_at"].is_(None) if "deleted_at" in table.c else None


def visible_ids(
    entity_type: str,
    user_id: int | None,
    *,
    tools: ToolSet,
    need_write: bool = False,
) -> Select:
    """Ids of this kind that ``user_id`` may open, or may edit.

    Joins the row to the resource that governs it — its own, or its parent's —
    and asks ``resource_access``, the same function the tables' own RLS
    policies call. A kind with no sharing of its own (the guild's tags, a
    collection) is read as its own policies read it, and changed as the edge
    policies ask: through ``entity_access``, which holds a collection to its
    file makers.

    ``need_write`` asks the same question at edit level. It is the caller's to
    say, because reaching a thing and changing it are different questions and
    only the caller knows which it is asking.
    """
    table_name = _table_for(entity_type, tools)
    table = tools.tables[table_name]

    statement = select(table.c["id"])
    live = _live(table)
    if live is not None:
        statement = statement.where(live)

    walk = governing_walk(table_name, paths_for(tools))
    if walk is None:
        if not need_write:
            return statement
        return statement.where(
            func.entity_access(entity_type, table.c["id"], True, True, standing_arg())
        )

    # The row is the shared resource (a project, a file), which answers for
    # itself, or is shared as part of the tool it is in: a task by its
    # project, an event by its calendar.
    tool, hops = walk
    joined, resource = joined_up(table, hops, tools)
    return statement.select_from(joined).where(
        func.resource_access(
            tool.kind,
            resource.c["id"],
            user_id,
            resource.c["initiative_id"],
            need_write,
            standing_arg(),
        )
    )


async def live_ids(session, entity_type: str, ids: Sequence[int]) -> set[int]:
    """Which of these ids still exist and this session may read.

    Asked as the session itself, which is what a caller mid-save wants: the
    question is what the person writing this content can point at, and their
    connection answers it the same way it answers every other statement.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    if not wanted:
        return set()
    tools = routed_tools(session)
    table = tools.tables[_table_for(entity_type, tools)]
    statement = select(table.c["id"]).where(table.c["id"].in_(wanted))
    live = _live(table)
    if live is not None:
        statement = statement.where(live)
    return {row[0] for row in (await session.exec(statement)).all()}


async def unfrozen_ids(session, entity_type: str, ids: Sequence[int]) -> set[int]:
    """Which of these are still taking writes — not archived or trashed, and
    not sitting under something that is.

    Asked through ``resource_frozen``, the same declaration the freeze
    policies are rendered from, so a caller checking before it writes and the
    database deciding afterwards are reading one answer.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    if not wanted:
        return set()
    tools = routed_tools(session)
    table_name = _table_for(entity_type, tools)
    table = tools.tables[table_name]
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


def _container(table_name: str, table: Table, tools: ToolSet):
    """What a row of this kind is addressed inside, as select pieces: the
    tool's kind, the join from the kind's table up to the tool's row, the
    tool's id, and the tool's name.

    The same pair a search hit carries, because a link to a thing with no page
    of its own needs its parent's id to be built at all. A name on its own
    identifies nothing in a list of mixed things either: six projects run
    from one template hold six tasks called "Do a thing", and the project is
    the only thing that tells them apart. A kind that governs itself — which
    every tool does — names no container, and a kind no one tool governs
    names no tool.

    Left joins: a container this reader cannot see leaves the name blank
    rather than dropping a row they were allowed to resolve.
    """
    walk = governing_walk(table_name, paths_for(tools))
    if walk is None:
        return None, table, null(), null()
    tool, hops = walk
    if not hops:
        return tool.kind, table, table.c["id"], null()
    joined, container = joined_up(table, hops, tools, isouter=True)
    # The row's own key names its tool where the tool is its parent.
    tool_id = table.c[hops[0][0]] if len(hops) == 1 else container.c["id"]
    title = container.c[search_sources(tools)[tool.table.name].title]
    return tool.kind, joined, tool_id, title


@dataclass(frozen=True)
class Resolved:
    """What a reference turned out to name."""

    entity_type: str
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
    tool: str | None = None
    tool_id: int | None = None
    #: What that tool is CALLED, for the surfaces that show a list of mixed
    #: things: "Do a thing" says nothing until it says which project. None for
    #: a row that is a tool itself.
    tool_title: str | None = None
    #: What the row shows of itself beside its name — see :class:`Visual`. At
    #: most one of the three is set, and most kinds set none.
    image_urls: list[str] = field(default_factory=list)
    icon: str | None = None
    color: str | None = None
    #: What sort of thing it is within its kind, for the kinds whose icon
    #: depends on that. Only files report these.
    file_type: str | None = None
    mime_type: str | None = None
    original_filename: str | None = None
    smart_link_url: str | None = None
    #: A person's handle as their profile is addressed by. Only a person
    #: reports one.
    handle: str | None = None
    #: Whether this row is still outstanding — still capable of holding
    #: something else up. None for a kind that never finishes, which is most of
    #: them; see :mod:`app.db.blocking`.
    is_open: bool | None = None
    #: When it starts, for a kind that happens at a time: an event. None for
    #: every other kind.
    starts_at: datetime | None = None


async def resolve_many(
    session, entity_type: str, ids: Sequence[int], *, user_id: int | None
) -> dict[int, Resolved]:
    """The rows of one kind this reader may open, keyed by id.

    One query for the lot. The initiative comes from the same
    ``paths_for`` entry that renders the kind's RLS, so a surface asking
    "are these two in one initiative" and the policy deciding who may read them
    are working from one declaration rather than two.

    A person is read as the community shows them, by name, avatar and handle,
    whoever they are to it now: a link outlives a membership, as a comment by
    them does. They belong to no initiative and are never archived.

    A kind this session's community does not have resolves nothing.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    tools = routed_tools(session)
    if not wanted or (
        entity_type != PERSON.value and entity_type not in _tables_by_kind(tools)
    ):
        return {}

    if entity_type == PERSON.value:
        people = await session.exec(
            select(MemberProfile).where(MemberProfile.id.in_(wanted))
        )
        return {
            person.id: Resolved(
                entity_type=entity_type,
                id=person.id,
                title=display_name(person),
                initiative_id=None,
                scoped_kind=False,
                archived=False,
                image_urls=[person.avatar_url] if person.avatar_url else [],
                # ``/u/jordan1234``: the name and its four digits run together.
                handle=f"{person.username}"
                f"{person.discriminator:0{usernames.DISCRIMINATOR_DIGITS}d}",
            )
            for person in people.scalars().all()
        }

    table_name = _table_for(entity_type, tools)
    table = tools.tables[table_name]
    path = paths_for(tools).get(table_name)
    initiative = text(path.initiative_expr(table_name)) if path is not None else null()
    archived = (
        table.c["archived_at"].isnot(None)
        if "archived_at" in table.c
        else literal(False)
    )
    updated = table.c["updated_at"] if "updated_at" in table.c else null()
    starts = table.c["start_at"] if "start_at" in table.c else null()
    images, icon, color, doc_type, mime, filename, link_url = _visual_exprs(
        table_name, table
    )
    tool, joined, tool_id, tool_title = _container(table_name, table, tools)
    is_open = open_expr(table)

    stmt = select(
        table.c["id"],
        title_column(entity_type, tools=tools),
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
        starts,
    ).select_from(joined)
    rows = await session.exec(
        stmt.where(
            table.c["id"].in_(wanted),
            table.c["id"].in_(visible_ids(entity_type, user_id, tools=tools)),
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
            starts_at=row[15],
        )
        for row in rows.all()
    }


async def resolve_one(
    session, entity_type: str, entity_id: int, *, user_id: int | None
) -> Resolved | None:
    """:func:`resolve_many` for one id."""
    found = await resolve_many(session, entity_type, [entity_id], user_id=user_id)
    return found.get(entity_id)
