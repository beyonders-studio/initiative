"""The export enumeration answers with the same calendars every other surface
shows.

One test class, one property: `list_calendar_ids_for_export` is the seam the
export adapter trusts to say "these are the calendars this user may take out",
so its scope rules must be the ones the list endpoints enforce — the tool
switch applies whether or not the query is narrowed to an initiative, and a
guild calendar (no initiative) is exportable at guild scope but never part of
any initiative's export. The narrowed path lost the switch once, which is why
it is pinned separately from the unfiltered one.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import Guild, GuildMembership
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.services.tenant.calendars import list_calendar_ids_for_export
from app.testing import (
    create_calendar,
    create_guild,
    create_guild_calendar,
    create_guild_membership,
    create_initiative,
    create_user,
    route_session_to_guild,
)


async def _workspace(
    session: AsyncSession, *, calendars_enabled: bool
) -> tuple[User, Guild, GuildMembership, Initiative]:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    membership = await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(
        session, guild, user, tools={Tool.calendar: calendars_enabled}
    )
    return user, guild, membership, initiative


class TestExportEnumeration:
    async def test_a_disabled_initiative_exports_nothing(self, session):
        """Narrowing to an initiative must not sidestep its tool switch — the
        same initiative lists no calendars anywhere else."""
        user, guild, _, initiative = await _workspace(session, calendars_enabled=False)
        await create_calendar(session, initiative, user)

        await route_session_to_guild(session, guild.id)
        ids = await list_calendar_ids_for_export(session, initiative_id=initiative.id)
        assert ids == []

    async def test_an_enabled_initiative_exports_its_calendars(self, session):
        user, guild, _, initiative = await _workspace(session, calendars_enabled=True)
        calendar = await create_calendar(session, initiative, user)

        await route_session_to_guild(session, guild.id)
        ids = await list_calendar_ids_for_export(session, initiative_id=initiative.id)
        assert ids == [calendar.id]

    async def test_a_guild_calendar_is_exportable_at_guild_scope_only(self, session):
        """No initiative owns it, so it rides the unfiltered export and stays
        out of every narrowed one — the same NULL read the list queries make."""
        user, guild, _, initiative = await _workspace(session, calendars_enabled=True)
        guild_calendar = await create_guild_calendar(session, guild, user)

        await route_session_to_guild(session, guild.id)
        everything = await list_calendar_ids_for_export(session)
        assert guild_calendar.id in everything

        narrowed = await list_calendar_ids_for_export(
            session, initiative_id=initiative.id
        )
        assert guild_calendar.id not in narrowed
