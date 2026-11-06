"""How long somebody may stay signed in before signing in again.

Two different questions, deliberately kept apart:

* ``AUTH_REFRESH_TTL_DAYS`` is how long a session may be *left alone*. Every
  rotation pushes it forward, so an app in daily use never reaches it.
* This module answers the other one — the **absolute** limit, which nothing
  pushes forward. It is what a deployment sets when it has to say "everybody
  signs in again at least this often".

It also answers the *idle* half for a community held to the compliance
standard, which is the same question asked of a shorter window: not "how long
may this session last" but "how long may it sit untouched". Both are windows
on a session rather than checks on a request, which is what keeps
authentication off the per-request path.

The absolute limit is stamped on the chain when the sign-in happens and
carried through every rotation unchanged. One consequence, and it is the right
one: joining a community that asks for the stricter standard shortens that
person's next sign-in rather than the session they are in.

The idle window is read again at every renewal, because a renewal is when it
is applied. So it follows a change of membership, or of the community's
setting, from the next renewal: joining starts the fifteen minutes there, and
leaving or lifting the standard ends them there.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildMembership
from app.services.platform import rules


#: What a community held to the compliance standard asks of its members.
#: HIPAA's automatic-logoff expectation and NIST SP 800-63B's AAL2
#: reauthentication limit land on the same number, so one constant serves both.
COMPLIANCE_SESSION_HOURS = 12

#: How long a session of theirs may sit untouched. PCI DSS 8.2.8 names fifteen
#: minutes and HIPAA's automatic-logoff expectation is satisfied by the same
#: number, so one constant serves both here too.
#:
#: Carried by the session's own two clocks rather than by a check on each
#: request: the refresh row expires this far out and the access token is minted
#: no longer-lived than that, so a session left alone lapses on its own. That
#: keeps the cost of the control at one sign-in rather than one database read
#: per request, which is the arrangement the rest of this design rests on.
COMPLIANCE_IDLE_MINUTES = 15


#: A community holds its members to the standard while it asks for it and
#: holds the option that asking needs.
_holds_the_standard = rules.community_rule_sql(
    GuildMembership.guild_id, "enforce_compliance_session"
).is_(True)


async def _belongs_to_a_compliance_guild(
    session: AsyncSession, *, user_id: int
) -> bool:
    found = (
        await session.exec(
            select(GuildMembership.guild_id)
            .where(
                GuildMembership.user_id == user_id,
                _holds_the_standard,
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def resolve_max_hours(session: AsyncSession, *, user_id: int) -> int | None:
    """The absolute limit that applies to this person, in hours.

    One standard rather than a number per community, so somebody in two of them
    has an answer rather than a comparison. ``None`` means no limit was asked
    for anywhere.

    A community's standard only ever tightens. The deployment's own figure is
    free-form and may already be shorter than twelve hours, and a community
    asking for a stricter session is not a place to lengthen one.
    """
    platform_hours = (await rules.platform_values(session))["session_max_hours"]
    if not await _belongs_to_a_compliance_guild(session, user_id=user_id):
        return platform_hours
    if platform_hours is None:
        return COMPLIANCE_SESSION_HOURS
    return min(COMPLIANCE_SESSION_HOURS, platform_hours)


async def resolve_idle_minutes(session: AsyncSession, *, user_id: int) -> int | None:
    """How long this account's session may sit untouched, in minutes.

    Two things can narrow it and the stricter wins: the deployment's own
    figure, and the standard a community holds its members to. ``None`` where
    neither speaks, which leaves ``AUTH_REFRESH_TTL_DAYS`` — where this
    question was answered before either existed.

    The community's half is a single standard rather than a figure each, so
    belonging to two of them is not a comparison. The deployment's half is a
    figure, because a deployment is only ever one.
    """
    platform_idle = (await rules.platform_values(session))["session_idle_minutes"]
    windows = [platform_idle] if platform_idle else []
    if await _belongs_to_a_compliance_guild(session, user_id=user_id):
        windows.append(COMPLIANCE_IDLE_MINUTES)
    return min(windows) if windows else None


async def idle_window(session: AsyncSession, *, user_id: int) -> timedelta | None:
    """:func:`resolve_idle_minutes` as a window, or ``None``."""
    minutes = await resolve_idle_minutes(session, user_id=user_id)
    return timedelta(minutes=minutes) if minutes is not None else None


async def chain_deadline(
    session: AsyncSession, *, user_id: int, issued: datetime
) -> datetime | None:
    """When the chain this sign-in starts must end. ``None`` for no limit."""
    hours = await resolve_max_hours(session, user_id=user_id)
    return None if hours is None else issued + timedelta(hours=hours)
