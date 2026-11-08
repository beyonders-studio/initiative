"""The database decides sharing for the search index.

Every other gate on ``search_entries`` is a policy; sharing used to be applied
only by the query that read the table. These assert the policy answers it now —
each test reads the table with a plain SELECT, carrying no clause of its own, so
what comes back is what the database allowed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.search_entry import SearchEntry
from app.testing import Actor, create_tag, create_task

#: The ``acting_user`` fixture: called with role keywords, yields an actor.
ActingUser = Callable[..., Awaitable[Actor]]


async def _unfiltered(reading_as, guild_id: int, actor) -> list[str]:
    """Titles the database hands back for a bare SELECT — no query-side gate,
    and on the request login, which is the one the policies bind."""
    session = await reading_as(actor.user.id, guild_id)
    rows = await session.exec(
        select(SearchEntry.title).where(SearchEntry.entity_type == "task")
    )
    return sorted(rows)


async def test_a_member_without_a_grant_is_refused_by_the_database(
    session, acting_user, reading_as
):
    """In the initiative — so the membership gate admits the row — but holding
    no grant on the project it belongs to."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _unfiltered(reading_as, a.guild.id, b) == []


async def test_the_owner_is_admitted(
    session: AsyncSession, acting_user: ActingUser, reading_as
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _unfiltered(reading_as, a.guild.id, a) == ["restricted vendor renewal"]


async def test_a_guild_admin_is_admitted(
    session: AsyncSession, acting_user: ActingUser, reading_as
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.admin,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _unfiltered(reading_as, a.guild.id, b) == ["restricted vendor renewal"]


async def test_full_access_is_carried_into_the_database(
    session: AsyncSession, acting_user: ActingUser, reading_as
) -> None:
    """The override is computed in Python per request; the policy reads it from
    a session setting. If that plumbing breaks, a full-access member silently
    loses rows they can reach everywhere else."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    # Without the override: refused, as above.
    assert await _unfiltered(reading_as, a.guild.id, b) == []

    # With it: admitted, without any grant being issued. The override is a
    # property of the role, so it is the role that gets it and the standing
    # that reads it back.
    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == a.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()
    member_role.override_share_restrictions = True
    session.add(member_role)
    await session.commit()

    reader = await reading_as(b.user.id, a.guild.id)
    rows = await reader.exec(
        select(SearchEntry.title).where(SearchEntry.entity_type == "task")
    )
    assert sorted(rows) == ["restricted vendor renewal"]


async def test_guild_vocabulary_answers_to_no_sharing(
    session: AsyncSession, acting_user: ActingUser, reading_as
) -> None:
    """A tag carries no sharing identity, so the sharing gate has nothing to
    decide and must not filter it out."""
    a = await acting_user(guild_role=CommunityRole.admin)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await create_tag(session, a.guild, name="urgent")

    reader = await reading_as(b.user.id, a.guild.id)
    rows = await reader.exec(
        select(SearchEntry.title).where(SearchEntry.entity_type == "tag")
    )
    assert sorted(rows) == ["urgent"]


async def test_the_override_setting_defaults_to_empty(
    session: AsyncSession, acting_user: ActingUser, reading_as
) -> None:
    """An unset override must read as "no initiatives", not as an error that
    faults the policy for every row."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader = await reading_as(a.user.id, a.guild.id)
    value = (
        await reader.exec(
            text("SELECT current_setting('app.override_initiatives', true)")
        )
    ).one()[0]
    assert value == ""
