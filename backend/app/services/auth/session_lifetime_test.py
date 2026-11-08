"""The absolute limit on staying signed in, and the standard a community sets."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


from app.models.platform.guild import CommunityRole
from app.services.auth import session_lifetime, sessions as session_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
    guild_administration,
)
from app.services.platform import rules

_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


async def _set_platform_hours(session, hours):
    await rules.put(session, "session_max_hours", hours)
    await session.flush()


async def _hold_to_the_standard(session, guild):
    await rules.put(session, "enforce_compliance_session", True, guild_id=guild.id)
    await session.flush()


async def test_a_deployment_that_asks_for_no_limit_stamps_none(session):
    """The default. Nothing about an upgrade shortens a session."""
    user = await create_user(session, email="sl-none@example.com")
    await _set_platform_hours(session, None)

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    assert issued.session.chain_expires_at is None
    # The idle window is the only thing ending it, exactly as before.
    assert issued.session.expires_at > _AT + timedelta(days=29)


async def test_the_deployments_own_figure_ends_the_chain(session):
    user = await create_user(session, email="sl-platform@example.com")
    await _set_platform_hours(session, 48)

    # A device's session too, though it otherwise stands longer.
    for install in (None, uuid.uuid4()):
        issued = await session_service.create_session(
            session,
            user_id=user.id,
            amr=["pwd"],
            satisfied_providers=[],
            install_id=install,
            now=_AT,
        )
        assert issued.session.chain_expires_at == _AT + timedelta(hours=48)
        # The idle window never outlives the chain it belongs to.
        assert issued.session.expires_at == _AT + timedelta(hours=48)


async def test_a_community_holds_its_members_to_the_standard(session):
    """Belonging to one settles it, whatever the deployment's own figure says."""
    user = await create_user(session, email="sl-guild@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    await _hold_to_the_standard(session, guild)
    await _set_platform_hours(session, 720)

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    assert issued.session.chain_expires_at == _AT + timedelta(
        hours=session_lifetime.COMPLIANCE_SESSION_HOURS
    )

    # While it holds the ``restrictions`` option the standard needs.
    await guild_administration(session, guild, auth_options=[])
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    assert issued.session.chain_expires_at == _AT + timedelta(hours=720)


async def test_somebody_in_two_such_communities_has_one_answer(session):
    """One standard rather than a figure each, so there is nothing to compare."""
    user = await create_user(session, email="sl-two@example.com")
    for name in ("a", "b"):
        guild = await create_guild(session, name=f"sl-two-{name}")
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.member
        )
        await _hold_to_the_standard(session, guild)

    hours = await session_lifetime.resolve_max_hours(session, user_id=user.id)
    assert hours == session_lifetime.COMPLIANCE_SESSION_HOURS


async def test_a_communitys_standard_only_ever_tightens(session):
    """The deployment's own figure is free-form and may already be shorter.
    A community asking for a stricter session is not a place to lengthen one."""
    user = await create_user(session, email="sl-tighten@example.com")
    guild = await create_guild(session, name="sl-tighten-g")
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    await _hold_to_the_standard(session, guild)
    await _set_platform_hours(session, 4)

    hours = await session_lifetime.resolve_max_hours(session, user_id=user.id)
    assert hours == 4


async def test_renewing_does_not_move_the_chains_end(session):
    """The idle window slides; the chain's end is the thing that does not."""
    user = await create_user(session, email="sl-rotate@example.com")
    await _set_platform_hours(session, 48)

    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    await session.flush()
    rotated = await session_service.rotate_session(
        session,
        raw_refresh_token=first.refresh_token,
        now=_AT + timedelta(hours=1),
    )
    assert rotated.issued is not None
    assert rotated.issued.session.chain_expires_at == _AT + timedelta(hours=48)


async def test_a_chain_past_its_end_is_not_renewed(session):
    """Reached, the answer is a fresh sign-in rather than another renewal."""
    user = await create_user(session, email="sl-expired@example.com")
    await _set_platform_hours(session, 2)

    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    await session.flush()
    rotated = await session_service.rotate_session(
        session,
        raw_refresh_token=first.refresh_token,
        now=_AT + timedelta(hours=3),
    )
    assert rotated.outcome == session_service.RefreshOutcome.EXPIRED
    assert rotated.issued is None


# ---------------------------------------------------------------------------
# The idle half: how long a session may sit untouched
# ---------------------------------------------------------------------------


async def test_an_ordinary_session_keeps_the_deployments_idle_window(session):
    """Nothing asks for less, so the refresh row stands the usual length."""
    from app.core.config import settings as app_config

    user = await create_user(session, email="sl-idle-none@example.com")

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )

    assert issued.session.expires_at == _AT + timedelta(
        days=app_config.AUTH_REFRESH_TTL_DAYS
    )


async def test_a_community_holds_its_members_to_an_idle_window(session):
    """Belonging to one shortens how long a session may be left alone, the
    same way it shortens how long the session may last at all."""
    user = await create_user(session, email="sl-idle@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    await _hold_to_the_standard(session, guild)

    # A device's session is held to it as a browser's is.
    for install in (None, uuid.uuid4()):
        issued = await session_service.create_session(
            session,
            user_id=user.id,
            amr=["pwd"],
            satisfied_providers=[],
            install_id=install,
            now=_AT,
        )

        assert issued.session.expires_at == _AT + timedelta(
            minutes=session_lifetime.COMPLIANCE_IDLE_MINUTES
        )


async def test_renewing_keeps_the_narrow_idle_window(session):
    """The window travels with the chain. A rotation that read the
    deployment's own figure would widen a narrowed session on its first
    renewal, which is the whole thing this control is for."""
    user = await create_user(session, email="sl-idle-renew@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    await _hold_to_the_standard(session, guild)
    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )

    later = _AT + timedelta(minutes=5)
    result = await session_service.rotate_session(
        session, raw_refresh_token=first.refresh_token, now=later
    )

    assert result.issued is not None
    assert result.issued.session.expires_at == later + timedelta(
        minutes=session_lifetime.COMPLIANCE_IDLE_MINUTES
    )


async def test_the_idle_window_never_outlasts_the_chain(session):
    """Both clocks bind and the earlier one wins.

    Reached the only way it can be: by renewing. A narrow idle window means a
    session that lives to the end of its chain got there one rotation at a
    time, and the last of them is the one that would overshoot.
    """
    user = await create_user(session, email="sl-idle-chain@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    await _hold_to_the_standard(session, guild)
    await _set_platform_hours(session, 1)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    chain_end = issued.session.chain_expires_at
    window = timedelta(minutes=session_lifetime.COMPLIANCE_IDLE_MINUTES)

    # Renewed inside the window each time, up to the last few minutes of the
    # chain — where the window would reach past it.
    for minutes in (14, 28, 42, 56):
        at = _AT + timedelta(minutes=minutes)
        result = await session_service.rotate_session(
            session, raw_refresh_token=issued.refresh_token, now=at
        )
        assert result.issued is not None, f"refused at +{minutes}m"
        issued = result.issued
        assert issued.session.expires_at == min(at + window, chain_end)

    assert issued.session.expires_at == chain_end


def test_an_access_token_does_not_outlive_the_session_it_names():
    """Where the row ends sooner than the deployment's access-token life, the
    token takes the row's remaining time instead."""

    from app.api.v1.platform_endpoints.session_opening import access_ttl_for
    from app.core.config import settings as app_config

    standard = timedelta(minutes=app_config.AUTH_ACCESS_TTL_MINUTES)

    roomy = SimpleNamespace(expires_at=_AT + timedelta(days=30))
    assert access_ttl_for(roomy, now=_AT) is None

    narrow = SimpleNamespace(expires_at=_AT + timedelta(minutes=2))
    assert access_ttl_for(narrow, now=_AT) == timedelta(minutes=2)

    exact = SimpleNamespace(expires_at=_AT + standard)
    assert access_ttl_for(exact, now=_AT) is None


async def test_the_deployment_can_set_its_own_idle_window(session):
    """A figure here narrows the window every session is opened with."""
    user = await create_user(session, email="sl-idle-platform@example.com")
    await rules.put(session, "session_idle_minutes", 45)
    await session.flush()

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )

    assert issued.session.expires_at == _AT + timedelta(minutes=45)


async def test_the_stricter_idle_window_wins(session):
    """The deployment's figure and a community's standard both narrow it, and
    the answer is whichever is shorter — in either direction."""
    guild = await create_guild(session)
    await _hold_to_the_standard(session, guild)

    lenient = await create_user(session, email="sl-idle-lenient@example.com")
    await create_guild_membership(
        session, user=lenient, guild=guild, role=CommunityRole.member
    )
    # Deployment is looser than the standard, so the standard binds.
    await rules.put(session, "session_idle_minutes", 60)
    await session.flush()
    issued = await session_service.create_session(
        session, user_id=lenient.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    assert issued.session.expires_at == _AT + timedelta(
        minutes=session_lifetime.COMPLIANCE_IDLE_MINUTES
    )

    # Deployment is stricter than the standard, so the deployment binds.
    strict = await create_user(session, email="sl-idle-strict@example.com")
    await create_guild_membership(
        session, user=strict, guild=guild, role=CommunityRole.member
    )
    await rules.put(session, "session_idle_minutes", 5)
    await session.flush()
    issued = await session_service.create_session(
        session, user_id=strict.id, amr=["pwd"], satisfied_providers=[], now=_AT
    )
    assert issued.session.expires_at == _AT + timedelta(minutes=5)
