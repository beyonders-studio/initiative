"""The DAC engine, asked the way a request asks it.

The rung a request holds on a row is the database's answer — the schema's
``resource_level``, mapped on every shareable model as ``access_level`` — so
every case here loads the row on the request login, routed through the seam
as the reader, through the loader the endpoints use. ``resource_level_test``
holds that function to the sharing gate, standing by standing. What this
file holds is what the app layer still decides on top of the level: the
named refusal, the frozen caps, the clauses a list spanning initiatives
adds, and the audience a notice reaches.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import ColumnElement, delete
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.errors import CodedError
from app.api import resource_access
from app.core.tools import Tool
from app.db import session as db_session
from app.db.guild_standing import GuildContext
from app.db.request_context import Member
from app.db.session import _RLS_CONTEXT_INFO_KEY
from app.models.platform.guild import Guild, CommunityRole, CommunityStatus
from app.models.platform.user import UserRole
from app.models.tenant.calendar_event import CalendarEventAttendee
from app.models.tenant.file import File
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.metadata import MetadataType, MetadataValue
from app.models.tenant.queue import QueueItem
from app.models.tenant.personal_item import PersonalItem
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.task import TaskAssignee
from app.services.permissions import (
    DAC_RESOURCES,
    audience,
    TOOL_CAN,
    Action,
    actions_of,
    client_access,
    granted_scope_clause,
    listing_scope_clause,
    require_access,
    writable_scope_clause,
)
from app.services.tenant import named_people
from app.services.tenant.archive import archive_entity
from app.services.tenant.initiatives import remove_user_from_guild_initiatives
from app.testing import (
    create_access_grant,
    create_calendar,
    create_calendar_event,
    create_file,
    create_project,
    create_property_definition,
    create_property_value,
    create_queue,
    create_queue_item,
    create_resource_grant,
    create_task,
    create_user,
    route_as,
)
from app.testing.factories import TOOL_FACTORIES

ALL_TOOLS = list(DAC_RESOURCES)

# The canonical per-tool factory registry rather than a copy of it: that one
# is checked against the Tool enum at import time, so a new tool cannot reach
# these parametrized cases without a factory behind it.
_TOOL_FACTORIES = TOOL_FACTORIES


# ── Building a real world ────────────────────────────────────────────────────


class World:
    """One guild, one initiative, one resource of ``tool``, and three actors."""

    def __init__(
        self,
        session,
        role_session,
        tool,
        guild,
        initiative,
        row,
        owner,
        co_member,
        admin,
    ):
        self.session = session
        self.role_session = role_session
        self.tool = tool
        self.resource = DAC_RESOURCES[tool]
        self.guild = guild
        self.initiative = initiative
        self.model = type(row)
        self.row = row
        self.row_id = row.id
        self.owner = owner
        self.co_member = co_member
        self.admin = admin

    async def as_reader(self, user):
        """The resource as ``user`` reads it, and the standing it was read
        under: on the request login, routed through the seam, through the
        loader the endpoints use. ``None`` where the policy admits nothing."""
        s = await self.role_session("app_user")
        context = await route_as(s, user_id=user.id, guild_id=self.guild.id)
        loader = resource_access.RESOURCE_ACCESS[self.tool].loader
        assert loader is not None, f"{self.tool.value} has no loader"
        return await loader(s, self.row_id), context

    async def grant(self, level, *, user=None, role_id=None, everyone=False) -> None:
        """Replace the resource's grants with exactly the ones named."""
        await self.session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.resource_type == self.tool.value,
                ResourceGrant.resource_id == self.row_id,
            )
        )
        if level is not None:
            await create_resource_grant(
                self.session,
                self.row,
                user=user,
                role_id=role_id,
                all_initiative_members=everyone,
                level=ResourceAccessLevel(level),
                commit=False,
            )
        await self.session.commit()


async def build_world(session, role_session, acting_user, tool: Tool) -> World:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    initiative, guild = owner.initiative, owner.guild
    for t in Tool:
        if hasattr(initiative, t.view_permission):
            setattr(initiative, t.view_permission, True)
    session.add(initiative)
    await session.commit()

    co_member = await acting_user(
        guild_role=CommunityRole.member,
        guild=guild,
        initiative=initiative,
        initiative_role="member",
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)

    factory = _TOOL_FACTORIES[tool]
    row = await factory(session, initiative, owner.user)
    return World(
        session, role_session, tool, guild, initiative, row, owner, co_member, admin
    )


def standing(
    guild=None,
    *,
    admin: bool = False,
    grant: str | None = None,
    read_only: bool = False,
    overrides: tuple[int, ...] = (),
) -> GuildContext | None:
    """A reader's standing in one community, shaped as the seam computes it,
    for the clause builders — which read the standing and no row.

    ``None`` is a request with no standing anywhere.
    """
    if guild is None:
        return None
    guild_id = guild if isinstance(guild, int) else guild.id
    return GuildContext(
        guild=guild if not isinstance(guild, int) else Guild(id=guild_id, name="g"),
        user_id=0,
        guild_id=guild_id,
        guild_role=CommunityRole.admin.value if admin else CommunityRole.member.value,
        standing_guild_id=guild_id,
        guild_admin=admin,
        pam_read=grant is not None,
        pam_write=grant == "read_write",
        content_read_only=read_only,
        override_initiatives=overrides,
    )


def refused(resource, row, **kwargs) -> HTTPException | CodedError:
    with pytest.raises((HTTPException, CodedError)) as exc:
        require_access(resource, row, **kwargs)
    assert exc.value.status_code == 403
    return exc.value


async def _role_id_of(session, initiative, user) -> int:
    row = (
        await session.exec(
            select(InitiativeMember.role_id).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == user.id,
            )
        )
    ).one()
    role_id = row[0] if isinstance(row, tuple) else row
    assert role_id is not None
    return role_id


async def _remove_from_initiative(session, initiative, user) -> None:
    await session.exec(
        delete(InitiativeMember).where(
            InitiativeMember.initiative_id == initiative.id,
            InitiativeMember.user_id == user.id,
        )
    )
    await session.commit()


async def _freeze(session, guild) -> None:
    guild.status = CommunityStatus.read_only.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.commit()


# ── Every tool resolves sharing through the same engine ──────────────────────


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_every_tool_resolves_sharing_through_one_engine(
    session, role_session, acting_user, tool: Tool
):
    """Each tool answers the same questions the same way, with the refusal
    messages its registry entry names.

    A tool reaches the engine through its ``DAC_RESOURCES`` entry and its
    ``RESOURCE_ACCESS`` loader, so a tool added later inherits this behaviour by
    registering rather than by re-implementing it.
    """
    w = await build_world(session, role_session, acting_user, tool)
    resource = w.resource

    # The holder of the owner grant.
    await w.grant("owner", user=w.owner.user)
    row, context = await w.as_reader(w.owner.user)
    require_access(resource, row, context=context, access="write")
    assert client_access(row, context.user_id, context=context) == {
        **{action.value: True for action in TOOL_CAN},
        "unarchive": False,
    }

    # An initiative co-member with no grant on this resource: the table's own
    # policy admits nothing, so there is no row to refuse.
    row, _ = await w.as_reader(w.co_member.user)
    assert row is None

    # A guild admin needs no grant at all.
    row, context = await w.as_reader(w.admin.user)
    require_access(resource, row, context=context, access="write")
    require_access(resource, row, context=context, action=Action.delete)
    assert client_access(row, context.user_id, context=context) == {
        **{action.value: True for action in TOOL_CAN},
        "unarchive": False,
    }

    # A PAM read grant opens the guild for reading only. The grantee holds the
    # rung the grant lends, so the write stops at the level check and names
    # the tool's own write message.
    grantee = await create_user(session, role=UserRole.support)
    await create_access_grant(session, user=grantee, guild=w.guild)
    row, context = await w.as_reader(grantee)
    require_access(resource, row, context=context, access="read")
    assert (
        refused(resource, row, context=context, access="write").body
        == resource.name.write_required().body
    )

    # Holding a read grant of their own is where the level check answers.
    await w.grant("read", user=w.co_member.user)
    row, context = await w.as_reader(w.co_member.user)
    require_access(resource, row, context=context, access="read")
    assert (
        refused(resource, row, context=context, access="write").body
        == resource.name.write_required().body
    )
    assert (
        refused(resource, row, context=context, action=Action.delete).body
        == resource.name.owner_required().body
    )

    # A writer edits it; deleting it and changing who it is shared with are
    # the owner's.
    await w.grant("write", user=w.co_member.user)
    row, context = await w.as_reader(w.co_member.user)
    assert client_access(row, context.user_id, context=context) == {
        "contribute": True,
        "edit": True,
        "delete": False,
        "share": False,
        "export": False,
        "unarchive": False,
    }


# ── How a grant resolves ─────────────────────────────────────────────────────


async def test_a_role_grant_elevates_over_a_users_own(
    session, role_session, acting_user
):
    """A grant to an initiative role the user holds outranks their own lower
    grant — the two combine by taking the higher."""
    w = await build_world(session, role_session, acting_user, Tool.project)

    role_id = await _role_id_of(session, w.initiative, w.co_member.user)
    await w.grant("read", user=w.co_member.user)
    row, context = await w.as_reader(w.co_member.user)
    assert actions_of(row) == frozenset()

    await create_resource_grant(
        session, w.row, role_id=role_id, level=ResourceAccessLevel.write
    )
    row, _ = await w.as_reader(w.co_member.user)
    assert actions_of(row) == {"contribute", "edit"}


async def test_general_access_covers_the_initiatives_members_only(
    session, role_session, acting_user
):
    """An all-initiative-members grant reaches every member without naming them,
    and stops at the initiative boundary."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=w.guild)

    await w.grant("write", everyone=True)
    row, context = await w.as_reader(w.co_member.user)
    assert actions_of(row) == {"contribute", "edit"}
    require_access(w.resource, row, context=context, access="write")

    row, _ = await w.as_reader(outsider.user)
    assert row is None


async def test_membership_alone_grants_nothing(session, role_session, acting_user):
    """The gate is an AND-layer: being in the initiative is not access to its
    resources."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant(None)
    row, _ = await w.as_reader(w.co_member.user)
    assert row is None


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_a_grant_left_behind_after_removal_reaches_nothing(
    session, role_session, acting_user, reading_as, tool: Tool
):
    """A grant row outliving the user's initiative membership carries no access.

    Leaving an initiative does not sweep the grants written for you, so the row
    is still there naming you at owner. What answers it is the table's own
    policy: every content table ANDs ``initiative_access`` onto its
    sharing leg, so the resource stops being visible the moment the membership
    goes — asserted against the database on the request login, because that is
    where the answer comes from.
    """
    w = await build_world(session, role_session, acting_user, tool)
    await w.grant("owner", user=w.co_member.user)

    async def visible() -> bool:
        reader = await reading_as(w.co_member.user.id, w.guild.id)
        rows = (
            await reader.exec(select(w.model.id).where(w.model.id == w.row_id))
        ).all()
        await reader.rollback()
        return bool(rows)

    assert await visible(), "the grant should reach it while the membership stands"

    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    assert not await visible(), (
        "a grant that outlived the membership must reach nothing"
    )


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_who_may_be_named_is_who_can_open_it(
    session, role_session, acting_user, reading_as, tool: Tool
):
    """``named_people`` answers for a person what the database answers when
    that person opens the row themselves, grant by grant."""
    w = await build_world(session, role_session, acting_user, tool)
    asker = await role_session("app_user")
    await route_as(asker, user_id=w.owner.user.id, guild_id=w.guild.id)
    governing = named_people.Governing(tool, w.row_id, w.initiative.id)
    people = [w.co_member.user, w.admin.user]

    async def agree() -> None:
        named = await named_people.readers(asker, governing, [u.id for u in people])
        await asker.rollback()
        for user in people:
            reader = await reading_as(user.id, w.guild.id)
            opens = bool(
                (
                    await reader.exec(select(w.model.id).where(w.model.id == w.row_id))
                ).all()
            )
            await reader.rollback()
            assert (user.id in named) == opens, (user.username, opens)

    role_id = await _role_id_of(session, w.initiative, w.co_member.user)
    for grant in (
        {"level": None},
        {"level": "read", "user": w.owner.user},
        {"level": "read", "user": w.co_member.user},
        {"level": "read", "role_id": role_id},
        {"level": "read", "everyone": True},
    ):
        await w.grant(**grant)
        await agree()
    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    await agree()


# ── The overrides that sit above sharing ─────────────────────────────────────


async def test_a_guild_admin_bypasses_the_scope_gate(
    session, role_session, acting_user
):
    """Guild admin is full authority over the guild, membership of the
    initiative or not."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant(None)
    row, context = await w.as_reader(w.admin.user)
    require_access(w.resource, row, context=context, access="write")
    require_access(w.resource, row, context=context, action=Action.delete)


def test_a_standing_for_another_community_is_never_read_back():
    """A standing means nothing outside the community it was computed in.

    The binding is where the context is read off the session: one routed into
    guild B is handed no standing computed for guild A, so an admin of A
    reaches nothing here by carrying theirs along.
    """

    class _Session:
        def __init__(self, guild_id):
            self.info = {
                _RLS_CONTEXT_INFO_KEY: Member(
                    guild_id=guild_id, user_id=0, standing=held
                )
            }

    held = standing(7, admin=True)
    assert db_session.guild_context(_Session(7)) is held
    assert db_session.guild_context(_Session(9)) is None


async def test_a_platform_owner_holds_no_standing_bypass(
    session, role_session, acting_user
):
    """``data.bypass`` is the right to break glass, not an ambient reach — a
    platform owner with no grant on the row is admitted nothing."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant(None)
    w.co_member.user.role = UserRole.owner
    session.add(w.co_member.user)
    await session.commit()
    row, _ = await w.as_reader(w.co_member.user)
    assert row is None


async def test_a_frozen_guild_caps_everyone_at_read(session, role_session, acting_user):
    """A read_only guild refuses every change — before the level is read, so
    full authority does not clear the hold — and still lets its owner export,
    which changes nothing.

    ``guild_suspension_test`` covers the same hold end-to-end through an
    endpoint; this pins where in the engine the cap sits.
    """
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant("owner", user=w.owner.user)
    await _freeze(session, w.guild)

    row, context = await w.as_reader(w.owner.user)
    assert context.content_read_only
    assert client_access(row, context.user_id, context=context) == {
        "contribute": False,
        "edit": False,
        "delete": False,
        "share": False,
        "export": True,
        "unarchive": False,
    }
    require_access(w.resource, row, context=context, access="read")
    assert (
        refused(w.resource, row, context=context, access="write").body
        == w.resource.name.write_required().body
    )
    refused(w.resource, row, context=context, action=Action.delete)

    row, context = await w.as_reader(w.admin.user)
    assert not client_access(row, context.user_id, context=context)["edit"]
    refused(w.resource, row, context=context, access="write")


# ── The clauses that survive the policies ───────────────────────────────────
#
# A statement confined to one initiative asks nothing: the table's own policy
# already applied the sharing gate. What is left here is the listing rule for a
# statement that SPANS initiatives, which is narrower than the policy on
# purpose, and the writable rule, which is narrower than any read policy.


def _compiled(clause: ColumnElement[bool]) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


def test_a_confined_listing_adds_nothing():
    """Named an initiative, the clause is a no-op whoever is asking.

    The rows come from a table whose policy has already asked gate 4, so a
    second copy of the question could only cost a query.
    """
    for context in (None, standing(7), standing(7, admin=True)):
        assert (
            _compiled(
                listing_scope_clause(
                    Tool.project, Project.id, 1, context=context, initiative_id=3
                )
            )
            == "true"
        )


def test_a_listing_across_initiatives_still_narrows_a_guild_admin():
    """Spanning initiatives, the question is what reaches the reader.

    A guild admin's authority is not a leg here — their sidebar lists what was
    shared with them, and they reach the rest by naming an initiative.
    """
    sql = _compiled(
        listing_scope_clause(
            Tool.project, Project.id, 1, context=standing(7, admin=True)
        )
    )
    assert sql != "true"
    assert "resource_granted(" in sql


def test_a_pam_window_is_a_no_op_across_initiatives():
    """A grantee holds no membership and no grant row, so the grant legs would
    answer nothing at all — the window is what they navigate by."""
    assert (
        _compiled(
            granted_scope_clause(
                Tool.file, File.id, 1, context=standing(7, grant="read")
            )
        )
        == "true"
    )


def test_the_window_opens_only_at_the_level_it_was_issued_at():
    """A read grant is a no-op for a read and not for a write."""
    read = standing(7, grant="read")
    assert (
        _compiled(granted_scope_clause(Tool.project, Project.id, 1, context=read))
        == "true"
    )
    assert (
        _compiled(
            granted_scope_clause(
                Tool.project, Project.id, 1, context=read, access="write"
            )
        )
        != "true"
    )
    assert (
        _compiled(
            granted_scope_clause(
                Tool.project,
                Project.id,
                1,
                context=standing(7, grant="read_write"),
                access="write",
            )
        )
        == "true"
    )


def test_no_standing_at_all_narrows_rather_than_opens():
    """A request with nothing behind it asks the grant rows, like a stranger."""
    assert (
        _compiled(granted_scope_clause(Tool.project, Project.id, 1, context=None))
        != "true"
    )


def test_the_writable_clause_asks_the_gate_when_confined():
    """Unlike the read listing, this one still has something to ask.

    A read policy admits a row shared at any level, so "which of these may I
    change" is a narrower question than the one already answered. Confined to
    one initiative it is the table's own gate, asked at write.
    """
    sql = _compiled(
        writable_scope_clause(
            Tool.project, Project.id, 1, context=standing(7), initiative_id=3
        )
    )
    assert sql != "true"
    assert "resource_access(" in sql
    assert ", true, (SELECT current_standing()" in sql


def test_the_writable_clause_spanning_initiatives_asks_the_grants_at_write():
    sql = _compiled(writable_scope_clause(Tool.project, Project.id, 1, context=None))
    assert "resource_granted(" in sql
    assert ", true, (SELECT current_standing()" in sql


@pytest.mark.parametrize("tool", list(Tool))
def test_every_tool_can_be_scoped(tool):
    """Every tool in the registry resolves through the clause, so a tool added
    later inherits the same listing rule."""
    sql = _compiled(granted_scope_clause(tool, Project.id, 1, context=standing(7)))
    assert "resource_granted(" in sql
    assert tool.value in sql


# ---------------------------------------------------------------------------
# The audience — who a resource's sharing reaches
# ---------------------------------------------------------------------------


async def test_the_audience_is_exactly_who_the_database_admits(
    session, role_session, acting_user
):
    """The invariant the post notifier hangs on.

    ``resource_audience`` reads the roster and the grant rows; the policies
    read the same rows when a member asks for the notice. A notifier built on
    the first must not address anyone the second would turn away, and must not
    miss anyone it would admit.
    """
    w = await build_world(session, role_session, acting_user, Tool.post)
    named = w.co_member
    by_role = w.owner  # the creator holds the manager role
    unnamed = await acting_user(
        guild_role=CommunityRole.member,
        guild=w.guild,
        initiative=w.initiative,
        initiative_role="member",
    )
    departed = await acting_user(guild_role=CommunityRole.member, guild=w.guild)

    await w.grant("owner", user=named.user)
    await create_resource_grant(
        session,
        w.row,
        role_id=await _role_id_of(session, w.initiative, by_role.user),
        level=ResourceAccessLevel.write,
    )
    # Named, but not a member of the initiative.
    await create_resource_grant(session, w.row, user=departed.user)

    s = await role_session("app_user")
    await route_as(s, user_id=w.owner.user.id, guild_id=w.guild.id)
    shared = (await audience(s, Tool.post, [w.row]))[w.row_id]
    assert shared == {named.user.id, by_role.user.id}

    for actor in (named, by_role, unnamed, departed):
        row, _ = await w.as_reader(actor.user)
        assert (row is not None) is (actor.user.id in shared), actor.user.id


async def test_everyone_is_the_roster_as_it_is_now_and_nobody_is_nobody(
    session, role_session, acting_user
):
    """An all-members grant reaches the initiative's members; a resource
    shared with nobody has no audience rather than falling back to them."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    s = await role_session("app_user")
    await route_as(s, user_id=w.owner.user.id, guild_id=w.guild.id)

    await w.grant(None)
    assert await audience(s, Tool.project, [w.row]) == {}

    await w.grant("read", everyone=True)
    assert (await audience(s, Tool.project, [w.row]))[w.row_id] == {
        w.owner.user.id,
        w.co_member.user.id,
    }


# ---------------------------------------------------------------------------
# Sharing and departure, as the database holds them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_only_the_owner_changes_who_it_is_shared_with(
    session, role_session, acting_user, tool: Tool
):
    """Sharing is the owner's in the database itself: a writer's own
    ``INSERT`` into ``resource_grants`` is refused by its policy, whatever the
    API would have said."""
    w = await build_world(session, role_session, acting_user, tool)
    await w.grant("write", user=w.co_member.user)
    s = await w.role_session("app_user")
    await route_as(s, user_id=w.co_member.user.id, guild_id=w.guild.id)
    s.add(
        ResourceGrant(
            resource_type=tool.value,
            resource_id=w.row_id,
            initiative_id=w.initiative.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.write,
        )
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()


async def _named_on(session, initiative, owner, person, **calendar) -> dict:
    """``person`` named on a task, an event, a person field and a queue item
    of ``initiative`` (the event on a calendar of the community itself with
    ``initiative_id=None``)."""
    project = await create_project(session, initiative, owner)
    task = await create_task(session, project, assignees=[person])
    calendar_ = await create_calendar(session, initiative, owner, **calendar)
    event = await create_calendar_event(session, calendar_, owner)
    session.add(CalendarEventAttendee(calendar_event_id=event.id, user_id=person.id))
    file = await create_file(session, initiative, owner)
    field = await create_property_definition(
        session, initiative, type=MetadataType.user_reference
    )
    await create_property_value(session, file, field, value_user_id=person.id)
    queue = await create_queue(session, initiative, owner)
    item = await create_queue_item(session, queue, user_id=person.id)
    await session.commit()
    return {
        "project": project,
        "calendar": calendar_,
        "task": task.id,
        "event": event.id,
        "file": file.id,
        "item": item.id,
    }


async def _still_named(session, person_id: int, named: dict) -> list[str]:
    session.expire_all()
    checks = {
        "assignee": select(TaskAssignee).where(
            TaskAssignee.task_id == named["task"],
            TaskAssignee.user_id == person_id,
        ),
        "attendee": select(CalendarEventAttendee).where(
            CalendarEventAttendee.calendar_event_id == named["event"],
            CalendarEventAttendee.user_id == person_id,
        ),
        "field": select(MetadataValue).where(MetadataValue.value_user_id == person_id),
        "queue item": select(QueueItem).where(
            QueueItem.id == named["item"], QueueItem.user_id == person_id
        ),
        "grant": select(ResourceGrant).where(ResourceGrant.user_id == person_id),
    }
    return [name for name, q in checks.items() if (await session.exec(q)).first()]


async def test_leaving_an_initiative_takes_you_off_its_content(
    session, role_session, acting_user
):
    """Every grant naming someone in an initiative goes with their membership
    of it, owner rows included, and they are taken off its content: archived
    content, and content the manager removing them cannot reach, included."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    member = w.co_member.user
    member_id = member.id
    await w.grant("owner", user=member)
    named = await _named_on(session, w.initiative, w.owner.user, member)
    await archive_entity(session, named["project"])
    await session.commit()

    s = await w.role_session("app_user")
    await route_as(s, user_id=w.owner.user.id, guild_id=w.guild.id)
    await s.exec(
        delete(InitiativeMember).where(
            InitiativeMember.initiative_id == w.initiative.id,
            InitiativeMember.user_id == member_id,
        )
    )
    await s.commit()

    assert await _still_named(session, member_id, named) == []
    # A person field and a queue item stay, with the person cleared.
    value = (
        await session.exec(
            select(MetadataValue).where(
                MetadataValue.entity_type == "file",
                MetadataValue.entity_id == named["file"],
            )
        )
    ).one()
    assert value.value_user_id is None
    assert (await session.get(QueueItem, named["item"])).user_id is None


async def test_leaving_the_community_takes_you_off_its_own_content(
    session, role_session, acting_user
):
    """The community's own tools, such as a calendar in no initiative, are
    left the same way when someone leaves the community, and what they kept
    about its items there goes with them."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    member = w.co_member.user
    member_id = member.id
    named = await _named_on(
        session, w.initiative, w.owner.user, member, initiative_id=None
    )
    await create_resource_grant(session, named["calendar"], user=member)
    session.add(
        PersonalItem(
            user_id=member_id,
            entity_type="project",
            entity_id=named["project"].id,
            subscribed_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    s = await w.role_session("app_user")
    await route_as(s, user_id=w.admin.user.id, guild_id=w.guild.id)
    await remove_user_from_guild_initiatives(s, guild_id=w.guild.id, user_id=member_id)
    await s.commit()

    assert await _still_named(session, member_id, named) == []
    assert (
        await session.exec(
            select(PersonalItem).where(PersonalItem.user_id == member_id)
        )
    ).all() == []
