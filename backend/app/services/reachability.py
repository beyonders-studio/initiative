"""Why a row the request asked for was not there.

Gate 4 is a policy, so a resource a reader may not reach is simply absent by
the time a handler runs — and "not yours" and "not there" are different
answers. This asks the system engine that one question and takes back a yes or
no, never a row.

It is a *status-code* decision, not a gate: nothing here grants access, and
every caller has already been refused by the database before it asks.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import ColumnElement, Select, null as sa_null
from sqlmodel import select

from app.core.tools import Tool
from app.db import cohorts
from app.db.base import MODELS_BY_TABLE
from app.db.session import set_rls_context
from app.db.request_context import SystemGuild


def _comment_initiative() -> ColumnElement[Optional[int]]:
    """A comment's initiative, through whichever parent it names.

    A comment hangs off exactly one of them, so the parents are tried in the
    order they are declared for the policies and the first that answers wins.
    A parent that is not itself a tool entity takes the hop its registry entry
    names — a task belongs to a project, a wiki page to a wiki — because the
    initiative is the tool's.
    """
    from sqlalchemy import func as sa_func

    from app.db.initiative_rls import COMMENT_PARENTS
    from app.models.tenant.comment import Comment

    lookups = []
    for column, parent in COMMENT_PARENTS.items():
        tool = MODELS_BY_TABLE.get(
            parent.governed_by.plural if parent.governed_by else parent.table
        )
        if tool is None:  # pragma: no cover - a tool always has a table
            continue
        if parent.tool_fk is None:
            lookups.append(
                select(tool.initiative_id)
                .where(tool.id == getattr(Comment, column))
                .scalar_subquery()
            )
            continue
        mid = MODELS_BY_TABLE.get(parent.table)
        if mid is None:  # pragma: no cover - a declared parent always has one
            continue
        lookups.append(
            select(tool.initiative_id)
            .join(mid, getattr(mid, parent.tool_fk) == tool.id)
            .where(mid.id == getattr(Comment, column))
            .scalar_subquery()
        )
    return sa_func.coalesce(*lookups)


def _initiative_query(model: Any, row_id: int) -> Select[tuple[int, Optional[int]]]:
    """A select yielding ``row_id`` and its initiative, or no row at all.

    The id rides along so the two cases stay apart: a row that exists and
    belongs to no initiative (a guild calendar) answers ``None`` for the
    second column, which a single-column select could not tell from no row.

    Most tables carry ``initiative_id``. A row that does not — a task, a wiki
    page — reaches one through the thing it belongs to, and which hops those
    are is already declared for the policies (``INITIATIVE_PATHS``), so they
    are read from there rather than a second time here. A comment names one of
    several parents, so it is read through the same chain its own policies use.
    """
    from app.models.tenant.comment import Comment

    live = getattr(model, "deleted_at", None)
    if model is Comment:
        statement = select(Comment.id, _comment_initiative()).where(
            Comment.id == row_id
        )
    elif hasattr(model, "initiative_id"):
        statement = select(model.id, model.initiative_id).where(model.id == row_id)
    else:
        statement = _initiative_through_parents(model, row_id)
    if live is not None:
        statement = statement.where(live.is_(None))
    return statement.where(*_not_drafts(model))


def _initiative_through_parents(model: Any, row_id: int) -> Select[Any]:
    """``row_id`` and the initiative of whatever it belongs to.

    The hops come from the row's own initiative path — the same declaration the
    RLS policies are rendered from — so a child table added later is reached
    here without an edit.
    """
    from app.db.initiative_rls import INITIATIVE_PATHS

    table = getattr(model, "__tablename__", None)
    path = INITIATIVE_PATHS.get(table) if table else None
    hops = getattr(getattr(path, "dac", None), "via", ()) or ()

    joins: list[tuple[Any, Any]] = []
    current: Any = model
    for fk, parent_table in hops:
        parent = MODELS_BY_TABLE.get(parent_table)
        if parent is None:  # pragma: no cover - a declared hop has a table
            break
        joins.append((parent, getattr(current, fk) == parent.id))
        current = parent
    if not joins or not hasattr(current, "initiative_id"):
        # Nothing declares how this row reaches an initiative. Answering "no
        # initiative" is the fail-closed reading: it makes the status 404
        # rather than claiming the reader is inside something.
        return select(model.id, sa_null()).where(model.id == row_id)

    # Both columns from the start: a select built with one and widened after
    # still reads back as a scalar.
    statement = select(model.id, current.initiative_id)
    for parent, condition in joins:
        statement = statement.join(parent, condition)
    return statement.where(
        model.id == row_id, *_not_drafts(*(parent for parent, _ in joins))
    )


def _not_drafts(*models: Any) -> list[Any]:
    """A draft, or anything inside one, is not there to somebody the draft
    policy hides it from (``guild_ddl.DRAFTS``)."""
    from sqlalchemy import Boolean, literal_column, not_
    from sqlalchemy.sql.expression import Grouping

    from app.db.guild_ddl import DRAFTS

    return [
        not_(Grouping(literal_column(DRAFTS[m.__tablename__], Boolean)))
        for m in models
        if m.__tablename__ in DRAFTS
    ]


async def missing_or_denied(
    tool: Tool,
    row_id: int,
    user_id: int | None,
    guild_id: int,
) -> Exception:
    """The exception for a ``tool`` row the request could not see.

    No access where the reader is in the row's initiative, not found
    otherwise. Returns the exception rather than raising it, so a caller reads
    as ``raise await missing_or_denied(...)``. An installed plug-in (``user_id``
    ``None``) is answered not found: it is in no initiative as a member.
    """
    if user_id is not None and await reader_is_in_the_initiative(
        tool.plural, row_id, user_id, guild_id
    ):
        return tool.no_access()
    return tool.not_found()


async def reader_is_in_the_initiative(
    table: str, row_id: int, user_id: int, guild_id: int
) -> bool:
    """Whether ``row_id`` belongs to an initiative ``user_id`` is a member of.

    Routed as the guild's own admin, which is how every other system read
    reaches guild content. A row belonging to no initiative (a guild calendar)
    has no initiative gate to fail, so reaching this point means a later gate
    refused it.
    """
    from app.models.tenant.initiative import InitiativeMember

    model = MODELS_BY_TABLE.get(table)
    if model is None:
        return False

    async with cohorts.system_session(guild_id) as probe, probe.begin():
        # One transaction, explicitly: the routing is transaction-local, and the
        # probe runs on a session of its own rather than the request's.
        await set_rls_context(probe, SystemGuild(guild_id))
        found = (await probe.exec(_initiative_query(model, row_id))).first()
        if found is None:
            return False
        initiative_id = found[1]
        if initiative_id is None:
            return True
        member = (
            await probe.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative_id,
                    InitiativeMember.user_id == user_id,
                )
            )
        ).first()
    return member is not None
