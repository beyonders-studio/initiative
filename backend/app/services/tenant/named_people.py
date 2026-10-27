"""Who may be named on a piece of content.

A task's assignees, an event's attendees, a person-valued property and a queue
item's person all name somebody on a row that lives inside a tool. Whoever is
named must be able to open that tool's row: the rule is the same for all of
them, and it is asked here.

"Able to open" is the database's own answer for that person, restated for a
person other than the one asking. The policies read the requester's standing,
so they cannot answer about somebody else; this spells the same gates over the
tables the standing is computed from:

- the account is in the community and not absent (suspended, or leaving);
- a community admin opens everything;
- anyone else, for a row of an initiative: they are its member, the tool is
  switched on there, their role lets them view the tool, and the row's sharing
  reaches them (a grant naming them, their role, or every member) or their role
  sees past sharing;
- for a row of the community itself (a guild calendar): its sharing reaches
  them.

``named_people_test`` holds this to what the database answers when the person
opens the row themselves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, false, or_, true
from sqlalchemy import Select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy import select as sa_select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import CommonMessages
from app.core.tools import DEFAULT_ENABLED_TOOLS, Tool
from app.db import cohorts
from app.db.session import (
    guild_context,
    install_context,
    routed_guild_id,
    set_rls_context,
)
from app.models.platform.guild import GUILD_LADDER, GuildMembership, CommunityRole
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    InitiativeRolePermission,
)
from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
from app.models.tenant.property import PropertyValue
from app.models.tenant.queue import QueueItem
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import Task, TaskAssignee
from app.services.membership import live_membership_clause
from app.services.platform.users import visible_to_other_people
from app.db.request_context import SystemGuild

_ADMIN_RUNGS = [rung for rung in GUILD_LADDER if rung.reaches(CommunityRole.admin)]


@dataclass(frozen=True)
class Governing:
    """The tool row whose sharing decides who may be named on content inside
    it: a task's project, an event's calendar, a file itself.

    Content no sharing governs, a collection, is opened by whoever can open
    one of its files: ``resource_id`` is None and ``resource_ids`` selects
    those files."""

    tool: Tool
    resource_id: Optional[int]
    initiative_id: Optional[int]
    resource_ids: Any = None

    @classmethod
    def of(cls, tool: Tool, row: Any) -> "Governing":
        return cls(tool, row.id, row.initiative_id)

    @classmethod
    def of_collection(cls, row: Any) -> "Governing":
        from app.models.tenant.collection import CollectionFile

        files = select(CollectionFile.file_id).where(
            CollectionFile.collection_id == row.id
        )
        return cls(Tool.file, None, row.initiative_id, resource_ids=files)

    def governs(self, column: Any) -> ColumnElement[bool]:
        """Whether a resource id column names the governing row, or one of
        them."""
        if self.resource_ids is not None:
            return column.in_(self.resource_ids)
        return column == self.resource_id


async def governing_of(
    session: AsyncSession, ref: tuple[str, int]
) -> tuple[Tool, Any] | None:
    """The tool, and its row, that governs ``ref`` (a task's project, a page's
    wiki, a tool itself), read on ``session``, or ``None`` where the session
    cannot reach it. The hops come from ``governing_path``, so no caller names
    a tool."""
    from sqlalchemy import column as sa_column
    from sqlalchemy import table as sa_table

    from app.db.initiative_rls import entity_tables, governing_path
    from app.models.tenant._mixins import tool_models

    kind, entity_id = ref
    table = entity_tables()[kind]
    walk = governing_path(table)
    if walk is None:
        raise ValueError(f"no tool governs {kind!r}")
    tool, hops = walk
    row_id: int | None = entity_id
    for column, parent in hops:
        step = sa_table(table, sa_column("id"), sa_column(column))
        row_id = (
            await session.exec(select(step.c[column]).where(step.c.id == row_id))
        ).one_or_none()
        if row_id is None:
            return None
        table = parent
    model = tool_models()[tool.plural]
    row = (
        await session.exec(select(model).where(model.id == row_id))  # type: ignore[attr-defined]
    ).one_or_none()
    return None if row is None else (tool, row)


def _grant_reaches(
    governing: Governing, user_id: Any, guest: ColumnElement[bool], *outer: Any
) -> ColumnElement[bool]:
    """A grant on the row that reaches ``user_id``: naming them, on a role
    they hold, or shared with every member of an initiative they are in (or of
    the community, on a row that belongs to none, unless ``guest``)."""
    im = aliased(InitiativeMember)
    held = sa_select(im.role_id).where(im.user_id == user_id).correlate(*outer)
    joined = sa_select(im.initiative_id).where(im.user_id == user_id).correlate(*outer)
    return (
        exists()
        .where(
            ResourceGrant.resource_type == governing.tool.value,
            governing.governs(ResourceGrant.resource_id),
            or_(
                ResourceGrant.user_id == user_id,
                ResourceGrant.role_id.in_(held),
                and_(
                    ResourceGrant.all_initiative_members.is_(True),
                    or_(
                        and_(ResourceGrant.initiative_id.is_(None), ~guest),
                        ResourceGrant.initiative_id.in_(joined),
                    ),
                ),
            ),
        )
        .correlate(*outer)
    )


def readers_of(governing: Governing, guild_id: int) -> Select:
    """The ids of everyone who can open the governing row, as a subquery."""
    tool = governing.tool
    gm = aliased(GuildMembership)
    present = (
        exists()
        .where(
            MemberProfile.id == gm.user_id,
            visible_to_other_people(MemberProfile.status),
        )
        .correlate(gm)
    )
    guest = gm.role == CommunityRole.guest
    if governing.initiative_id is None:
        reached = _grant_reaches(governing, gm.user_id, guest, gm)
    else:
        im = aliased(InitiativeMember)
        role = aliased(InitiativeRoleModel)
        default = true() if tool in DEFAULT_ENABLED_TOOLS else false()

        def role_says(enabled: bool) -> ColumnElement[bool]:
            return (
                exists()
                .where(
                    InitiativeRolePermission.initiative_role_id == im.role_id,
                    InitiativeRolePermission.permission_key == tool.view_permission,
                    InitiativeRolePermission.enabled.is_(enabled),
                )
                .correlate(im)
            )

        reached = exists(
            sa_select(1)
            .select_from(im)
            .join(Initiative, Initiative.id == im.initiative_id)
            .outerjoin(role, role.id == im.role_id)
            .where(
                im.initiative_id == governing.initiative_id,
                im.user_id == gm.user_id,
                getattr(Initiative, f"{tool.plural}_enabled").is_(True),
                or_(
                    role.is_manager.is_(True),
                    role_says(True),
                    and_(default, ~role_says(False)),
                ),
                or_(
                    role.override_share_restrictions.is_(True),
                    _grant_reaches(governing, gm.user_id, guest, gm, im),
                ),
            )
            .correlate(gm)
        )
        # A guest given the row itself, in an initiative they are not in.
        given = (
            exists()
            .where(
                ResourceGrant.resource_type == tool.value,
                governing.governs(ResourceGrant.resource_id),
                ResourceGrant.user_id == gm.user_id,
            )
            .correlate(gm)
        )
        enabled = exists().where(
            Initiative.id == governing.initiative_id,
            getattr(Initiative, f"{tool.plural}_enabled").is_(True),
        )
        reached = or_(reached, and_(guest, given, enabled))
    return sa_select(gm.user_id).where(
        gm.guild_id == guild_id,
        live_membership_clause(gm),
        present,
        or_(gm.role.in_(_ADMIN_RUNGS), reached),
    )


@asynccontextmanager
async def roster_session(
    session: AsyncSession, *, whole: bool = False
) -> AsyncIterator[AsyncSession]:
    """Where the routed community's roster is read for ``session``'s request.

    The request's own session for a person, so a row it has just made is seen.
    An installed plug-in's role reads as much of the roster as its scopes allow,
    and who can open something is not its scopes' to say, so its requests are
    answered by the community's own read instead, as
    :mod:`app.services.reachability` does.

    A guest reads only their own place in the roster, which is what they may
    name. ``whole`` is for who a notice reaches, which is the community's to
    say whoever acted, so a guest's request reads that on the community's own
    read too.
    """
    context = guild_context(session)
    if install_context(session) is None and not (whole and context and context.guest):
        yield session
        return
    guild_id = routed_guild_id(session)
    async with cohorts.system_session(guild_id) as probe, probe.begin():
        await set_rls_context(probe, SystemGuild(guild_id))
        yield probe


async def readers(
    session: AsyncSession, governing: Governing, user_ids: Iterable[int]
) -> set[int]:
    """Those of ``user_ids`` who can open the governing row, read on
    :func:`roster_session`."""
    ids = sorted(set(user_ids))
    if not ids:
        return set()
    guild_id = routed_guild_id(session)
    if guild_id is None:
        raise RuntimeError("people are named on content inside a community")
    stmt = select(MemberProfile.id).where(
        MemberProfile.id.in_(ids),
        MemberProfile.id.in_(readers_of(governing, guild_id)),
    )
    async with roster_session(session) as reader:
        return set((await reader.exec(stmt)).all())


async def require_readers(
    session: AsyncSession, governing: Governing, user_ids: Iterable[int]
) -> None:
    """Refuse (422 ``PERSON_CANNOT_READ``) unless everyone in ``user_ids`` can
    open the governing row."""
    wanted = set(user_ids)
    if wanted - await readers(session, governing, wanted):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CommonMessages.PERSON_CANNOT_READ,
        )


# --- Where content names somebody --------------------------------------------


@dataclass(frozen=True)
class PersonRef:
    """A column naming a person on content inside a tool. ``within`` picks the
    rows inside one governing row; ``clears`` empties the column rather than
    deleting the row, where the row is more than the name (a property value,
    a queue item)."""

    column: Any
    within: Callable[[int], ColumnElement[bool]]
    clears: bool = False


#: Every person column, by the tool whose sharing decides who it may name —
#: beside a person-valued property, which :func:`person_refs` adds for every
#: tool from the properties seam.
PERSON_REFS: dict[Tool, tuple[PersonRef, ...]] = {
    Tool.project: (
        PersonRef(
            TaskAssignee.user_id,
            lambda pid: TaskAssignee.task_id.in_(
                sa_select(Task.id).where(Task.project_id == pid)
            ),
        ),
    ),
    Tool.calendar: (
        PersonRef(
            CalendarEventAttendee.user_id,
            lambda cid: CalendarEventAttendee.calendar_event_id.in_(
                sa_select(CalendarEvent.id).where(CalendarEvent.calendar_id == cid)
            ),
        ),
    ),
    Tool.queue: (
        PersonRef(
            QueueItem.user_id, lambda qid: QueueItem.queue_id == qid, clears=True
        ),
    ),
}


def _property_ref(tool: Tool) -> PersonRef | None:
    """A person-valued property on anything ``tool`` governs: the tool row
    itself and every sub-tool row inside it, read from the properties seam."""
    from app.services.tenant.properties import PROPERTY_LINKS

    specs = [spec for spec in PROPERTY_LINKS.values() if spec.tool is tool]
    if not specs:
        return None

    def within(gid: int) -> ColumnElement[bool]:
        return or_(
            *(
                and_(
                    PropertyValue.entity_type == spec.target,
                    PropertyValue.entity_id == gid
                    if spec.via is None
                    else PropertyValue.entity_id.in_(
                        sa_select(spec.model.id).where(
                            getattr(spec.model, spec.via) == gid
                        )
                    ),
                )
                for spec in specs
            )
        )

    return PersonRef(PropertyValue.value_user_id, within, clears=True)


def person_refs(tool: Tool) -> tuple[PersonRef, ...]:
    """Every person column on content inside ``tool``'s rows."""
    prop = _property_ref(tool)
    return (*PERSON_REFS.get(tool, ()), *((prop,) if prop is not None else ()))


async def named_on(session: AsyncSession, governing: Governing) -> set[int]:
    """Everyone the content inside the governing row names."""
    named: set[int] = set()
    for ref in person_refs(governing.tool):
        named.update(
            (
                await session.exec(
                    select(ref.column)
                    .where(ref.within(governing.resource_id), ref.column.is_not(None))
                    .distinct()
                )
            ).all()
        )
    return named


async def sweep(session: AsyncSession, governing: Governing) -> set[int]:
    """Take everyone who cannot open the governing row off the content inside
    it, and answer who that was."""
    named = await named_on(session, governing)
    gone = named - await readers(session, governing, named)
    if not gone:
        return gone
    for ref in person_refs(governing.tool):
        table = ref.column.class_
        where = (ref.within(governing.resource_id), ref.column.in_(gone))
        await session.exec(
            sa_update(table).where(*where).values({ref.column.key: None})
            if ref.clears
            else sa_delete(table).where(*where)
        )
    return gone
