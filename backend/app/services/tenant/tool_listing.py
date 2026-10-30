"""The query behind every guild-wide tool list — search, scope, order, page.

The guild home shows one table for whichever tool is selected, so the nine list
endpoints behind it have to answer the same questions the same way: which rows
are in scope, what the search box narrows, how the three shared columns order,
and where the page boundary falls. Those answers live here once and each tool
supplies only what is genuinely its own — its model, what to eager-load, how a
row becomes a summary, and the order it falls back to.

Ordering belongs in SQL rather than in whichever page the caller happens to be
holding: a sort that only reaches the twenty rows in hand is not a sort of the
guild's work, it is a sort of the accident of pagination. Searching those lists
is ``search.tool_search_clause``, which reads the same index the search page
does.

**Two scope clauses, and they are not the same clause.** A *list* uses
``permissions.listing_scope_clause``: confined to one initiative it adds
nothing, because the table's own policy already asked the question, and
spanning initiatives it falls back to what has been granted. A *count* uses
``permissions.granted_scope_clause`` directly: a count is always guild-wide, so
it has no single initiative to ask about and the "granted to the reader" rule
is the only one that applies. Keeping them apart is what lets one initiative's
list show a guild admin everything while the sidebar badge beside it still
counts what actually reaches them.

Each tool keeps its own default order (a project's is the manual one its owner
dragged into place, a calendar's is by name), so a request that asks for none
of these is left exactly as it was.
"""

from typing import Any, Callable, Optional, Sequence

from sqlalchemy import ColumnElement, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.guild_standing import ActorContext
from app.db.query import apply_pagination, clamp_page
from app.models.tenant.initiative import Initiative
from app.services import permissions as permissions_service
from app.services.tenant import search as search_service
from app.services.tenant import tags as tags_service
from app.services.tenant.initiative_tools import tool_on_sql

#: What ``sort_by`` accepts on every guild-wide tool list.
TOOL_SORT_FIELDS = ("name", "initiative", "updated_at")


def apply_tool_order(
    statement,
    model,
    sort_by: Optional[str],
    sort_dir: Optional[str],
    *,
    default,
    initiative_joined: bool = False,
    extra_fields: Optional[dict[str, Any]] = None,
):
    """Order a tool list by one of :data:`TOOL_SORT_FIELDS`, else by ``default``.

    Ordering by initiative means ordering by its *name*, which is the column
    the table shows, so the statement is joined to ``Initiative`` for it —
    outer, because a tool may hold guild-level rows belonging to no initiative
    (calendars do). Pass ``initiative_joined`` where the caller already joined
    it. ``id`` is the tiebreak throughout, so a page boundary never splits two
    rows that compare equal.

    ``extra_fields`` names columns one tool sorts by beyond the shared three —
    a file's ``created_at``, which its own list has always offered.
    """
    if sort_by == "name":
        column = func.lower(model.name)
    elif sort_by == "initiative":
        column = func.lower(Initiative.name)
        if not initiative_joined:
            statement = statement.outerjoin(
                Initiative, model.initiative_id == Initiative.id
            )
    elif sort_by == "updated_at":
        column = model.updated_at
    elif extra_fields and sort_by in extra_fields:
        column = extra_fields[sort_by]
    else:
        return statement.order_by(*default)

    order = column.desc() if sort_dir == "desc" else column.asc()
    return statement.order_by(order.nulls_last(), model.id.desc())


def initiative_switch_clause(
    tool: Tool,
    model,
    *,
    guild_level_rows: bool = False,
) -> ColumnElement[bool]:
    """Rows whose initiative has this tool switched on.

    One spelling for every tool, from the initiative's switch column the tool
    names (``Tool.view_permission``).
    An initiative with the tool off has nothing to list, so the switch is a
    plain leg of the WHERE rather than a lookup the handler makes first: asking
    for that initiative by id and asking for the whole guild then answer the
    same way, and neither costs a round trip.

    ``guild_level_rows`` admits the rows that belong to the guild rather than
    to an initiative — calendars, where installing the plug-in is what turned the
    tool on and no initiative has anything to say about it.
    """
    enabled = model.initiative_id.in_(select(Initiative.id).where(tool_on_sql(tool)))
    if guild_level_rows:
        return or_(model.initiative_id.is_(None), enabled)
    return enabled


def base_conditions(
    tool: Tool,
    model,
    user_id: int | None,
    *,
    context: ActorContext,
    initiative_id: Optional[int] = None,
    search: Optional[str] = None,
    tag_ids: Optional[Sequence[int]] = None,
    guild_level_rows: bool = False,
) -> list:
    """The WHERE legs every tool list and every tool count share.

    The tool's switch, the initiative filter when one is named, sharing, the
    search box and the tag filter. The community is the schema the statement
    runs in, so it is not a leg. The archive leg is deliberately
    absent: a list answers ``archived`` and a count never does, so each caller
    appends the one it means (``archive.archive_filter_clause``).
    """
    conditions: list = [
        initiative_switch_clause(tool, model, guild_level_rows=guild_level_rows),
        permissions_service.listing_scope_clause(
            tool,
            model.id,
            user_id,
            context=context,
            initiative_id=initiative_id,
        ),
    ]
    if initiative_id is not None:
        conditions.append(model.initiative_id == initiative_id)

    name_match = search_service.tool_search_clause(tool, model.id, search, context)
    if name_match is not None:
        conditions.append(name_match)

    if tag_ids:
        conditions.append(
            model.id.in_(
                tags_service.tagged_entity_ids(
                    tags_service.TOOL_TAG_LINKS[tool],
                    tuple(tag_ids),
                    guild_id=context.guild_id,
                )
            )
        )

    return conditions


async def list_tool_rows(
    session: AsyncSession,
    model,
    *,
    conditions: Sequence[Any],
    loader_options: Sequence[Any],
    sort_by: Optional[str],
    sort_dir: Optional[str],
    default_order: Sequence[Any],
    page: int,
    page_size: int,
    extra_sort_fields: Optional[dict[str, Any]] = None,
    refine: Optional[Callable[[Any], Any]] = None,
    clamp: bool = False,
) -> tuple[list, int, int]:
    """One page of a tool, with the total the pager underneath it reads.

    Returns ``(rows, total_count, page)``. ``page`` comes back because a tool
    may ask to be moved to the first page when the one requested has fallen off
    the end (``clamp``) — the projects board does, since its filters change
    under a reader who is already deep in the list.

    ``refine`` adds whatever a tool's own order needs the statement to carry —
    the projects list joins each reader's manual positions — and runs before
    the ORDER BY that reads it.
    """
    count_subq = select(model.id).where(*conditions).subquery()
    total_count = int(
        (await session.exec(select(func.count()).select_from(count_subq))).one()
    )
    if clamp:
        page = clamp_page(page, page_size, total_count)

    statement = select(model).where(*conditions).options(*loader_options)
    if refine is not None:
        statement = refine(statement)
    statement = apply_tool_order(
        statement,
        model,
        sort_by,
        sort_dir,
        default=default_order,
        extra_fields=extra_sort_fields,
    )
    # One windowing rule for every page_size, the ``page_size<=0`` "fetch all"
    # protocol included: the response is bounded, ``page`` selects the window,
    # and ``has_next`` tells the caller to keep walking.
    statement = apply_pagination(statement, page, page_size)
    rows = list((await session.exec(statement)).unique().all())
    return rows, total_count, page
