"""The operations community: where this deployment's own security,
moderation, support and feedback work lands, set up with the platform ladder
seated in it.

The ladder is a set of accounts with nowhere of their own to work until this
exists, which is what made every intake surface unreachable on a fresh dev
database. So it is seeded as an ordinary community with the ladder mapped onto
community roles: the platform owner holds the seat (as its creator), the
operator administers it, and everybody else is a member. Both halves are set
up, because either one missing leaves the streams unreachable: the
deployment's pointer (``app_settings.operations_guild_id``) and a binding per
stream, each from its committed blueprint the way the operator's own "set this
up for me" does.

A stream that keeps an initiative to itself (security, moderation) gets one
of its own, with only the people who would work it in it; the rest share the
Operations initiative.
"""

from __future__ import annotations

from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream, meta, offered_streams
from app.db.request_context import SystemGuild, Unattributed
from app.db.schema_provisioning import provision_guild
from app.db.session import set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.services.platform import intake_setup
from seed import guilds, initiatives
from seed.common import Community

#: Named for the product rather than for a company: a deployment runs one of
#: these, and what it is called is what everybody in it sees.
OPERATIONS_GUILD_NAME = "Initiative"

_OWNER = "Platform Owner"
_OPERATOR = "Platform Operator"
_MEMBERS = ["Platform Moderator", "Platform Support", "Platform Member"]

#: Who works each stream that keeps an initiative to itself, beside the owner
#: who manages it.
_ISOLATED_STAFF = {
    IntakeStream.security: [_OPERATOR],
    IntakeStream.moderation: [_OPERATOR, "Platform Moderator"],
}
_ISOLATED_COLORS = {
    IntakeStream.security: "#7c3aed",
    IntakeStream.moderation: "#ea580c",
}


async def seed(
    session: AsyncSession, ids: dict[str, list], users: dict[str, User]
) -> Guild:
    guild = await guilds.create_guild(
        session,
        ids,
        name=OPERATIONS_GUILD_NAME,
        description="Where this deployment's security, moderation, support and feedback work lands.",
        creator=users[_OWNER],
    )
    await session.commit()
    guilds.expunge_guild_scoped(session)
    await provision_guild(guild.id)
    await guilds.add_members(
        session,
        guild,
        [users[name] for name in (_OPERATOR, *_MEMBERS)],
        admins=[users[_OPERATOR]],
    )
    await session.commit()
    await set_rls_context(session, SystemGuild(guild.id))
    c = Community(key="operations", session=session, ids=ids, users=users, guild=guild)
    shared = await initiatives.create_initiative(
        c,
        "operations",
        {
            "name": "Operations",
            "description": "The deployment's own support and feedback cases.",
            "color": "#dc2626",
            "pm": _OWNER,
            "members": [_OPERATOR, *_MEMBERS],
        },
    )
    initiative_for: dict[IntakeStream, int] = {}
    for stream in IntakeStream:
        if not meta(stream).isolated:
            initiative_for[stream] = cast(int, shared.id)
            continue
        own = await initiatives.create_initiative(
            c,
            f"operations-{stream.value}",
            {
                "name": stream.value.capitalize(),
                "description": f"The deployment's {stream.value} cases, kept apart from the other streams.",
                "color": _ISOLATED_COLORS.get(stream, "#dc2626"),
                "pm": _OWNER,
                "members": _ISOLATED_STAFF.get(stream, [_OPERATOR]),
            },
        )
        initiative_for[stream] = cast(int, own.id)
    await session.commit()

    await set_rls_context(session, Unattributed())
    await intake_setup.set_operations_guild(session, guild.id)
    await session.commit()
    for stream in offered_streams():
        await intake_setup.provision_from_blueprint(
            session,
            stream=stream,
            initiative_id=initiative_for[stream],
            importer=users[_OWNER],
        )
    # provision_from_blueprint routes into the operations guild to write the
    # binding; hand the session back at the public baseline.
    await set_rls_context(session, Unattributed())
    return guild
