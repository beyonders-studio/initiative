"""Staff on the communities list: who reads it, what each row offers them,
and a moderator suspending a community under a ``moderate`` grant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthMessages, GuildMessages
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild import CommunityRole, CommunityStatus, Guild
from app.models.platform.user import User, UserRole
from app.testing import create_guild, create_user, get_auth_headers

COMMUNITIES = "/api/v1/settings/communities"


async def _moderate_grant(
    session: AsyncSession, *, user: User, guild: Guild
) -> AccessGrant:
    """A live ``moderate`` grant on ``guild``, approved by somebody else."""
    approver = await create_user(session, role=UserRole.operator)
    now = datetime.now(UTC)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level="moderate",
        status="approved",
        reason="case",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=approver.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


async def _row(client: AsyncClient, user: User, guild: Guild) -> dict:
    response = await client.get(
        COMMUNITIES,
        params={"search": guild.name},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    (row,) = [r for r in response.json()["items"] if r["id"] == guild.id]
    return row


async def _set_status(
    session: AsyncSession,
    guild: Guild,
    status: CommunityStatus,
    *,
    at: datetime | None = None,
) -> None:
    guild.status = status.value
    guild.status_changed_at = at or datetime.now(UTC)
    session.add(guild)
    await session.commit()


async def _suspend(
    client: AsyncClient, user: User, guild: Guild, suspended: bool = True
) -> Response:
    return await client.post(
        f"{COMMUNITIES}/{guild.id}/suspension",
        json={"suspended": suspended},
        headers=get_auth_headers(user),
    )


# ── Reading the list ─────────────────────────────────────────────────────────


async def test_support_reads_the_list_and_sets_nothing(client, session):
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)

    row = await _row(client, support, guild)
    assert row["status"] == "active"
    assert row["status_choices"] == []
    assert row["allowed_actions"] == ["billing_support", "request_access"]

    refused = await client.patch(
        f"{COMMUNITIES}/{guild.id}",
        json={"status": "read_only"},
        headers=get_auth_headers(support),
    )
    assert refused.status_code == 403, refused.text


async def test_a_member_reads_no_list(client, session):
    member = await create_user(session)
    response = await client.get(COMMUNITIES, headers=get_auth_headers(member))
    assert response.status_code == 403, response.text


async def test_deleted_and_suspended_communities_are_listed(client, session):
    support = await create_user(session, role=UserRole.support)
    deleted = await create_guild(session)
    await _set_status(session, deleted, CommunityStatus.deleted)
    suspended = await create_guild(session)
    await _set_status(session, suspended, CommunityStatus.suspended)

    assert (await _row(client, support, deleted))["status"] == "deleted"
    assert (await _row(client, support, suspended))["status"] == "suspended"


async def test_an_operator_is_offered_everything_but_suspending(client, session):
    operator = await create_user(session, role=UserRole.operator)
    guild = await create_guild(session)

    row = await _row(client, operator, guild)
    assert row["allowed_actions"] == [
        "manage",
        "set_status",
        "billing_support",
        "billing_operator",
        "request_access",
        "break_glass",
    ]
    assert row["status_choices"]


async def test_an_owner_breaks_glass_rather_than_asking(client, session):
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session)
    actions = (await _row(client, owner, guild))["allowed_actions"]
    assert "request_access" not in actions
    assert "break_glass" in actions


async def test_support_may_not_open_the_operator_billing_console(client, session):
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)
    response = await client.post(
        f"{COMMUNITIES}/{guild.id}/billing/service-handoff",
        params={"console": "operator"},
        headers=get_auth_headers(support),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == AuthMessages.INSUFFICIENT_PRIVILEGES

    # The support console is theirs; this deployment just has no billing.
    response = await client.post(
        f"{COMMUNITIES}/{guild.id}/billing/service-handoff",
        params={"console": "support"},
        headers=get_auth_headers(support),
    )
    assert response.status_code != 403, response.text


# ── Suspending ───────────────────────────────────────────────────────────────


async def test_a_moderator_without_a_grant_cannot_suspend(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    guild = await create_guild(session)

    assert "suspend" not in (await _row(client, moderator, guild))["allowed_actions"]
    refused = await _suspend(client, moderator, guild)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == GuildMessages.COMMUNITY_SUSPENSION_NEEDS_GRANT


async def test_a_grant_without_the_capability_cannot_suspend(client, session):
    member = await create_user(session)
    guild = await create_guild(session)
    await _moderate_grant(session, user=member, guild=guild)
    assert (await _suspend(client, member, guild)).status_code == 403


async def test_a_moderator_suspends_and_lifts_under_a_grant(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    guild = await create_guild(session)
    await _set_status(session, guild, CommunityStatus.read_only)
    await _moderate_grant(session, user=moderator, guild=guild)

    assert "suspend" in (await _row(client, moderator, guild))["allowed_actions"]
    suspended = await _suspend(client, moderator, guild)
    assert suspended.status_code == 200, suspended.text
    body = suspended.json()
    assert body["status"] == "suspended"
    assert body["lifts_to"] == "read_only"
    assert "lift" in body["allowed_actions"]

    lifted = await _suspend(client, moderator, guild, suspended=False)
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["status"] == "read_only"


async def test_lifting_what_is_not_suspended_is_refused(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    guild = await create_guild(session)
    await _moderate_grant(session, user=moderator, guild=guild)
    refused = await _suspend(client, moderator, guild, suspended=False)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == GuildMessages.COMMUNITY_NOT_SUSPENDED


async def test_suspending_a_deleted_community_stops_its_countdown_and_lifting_restarts_it(
    client, session
):
    """The answer to a community deleting itself to destroy evidence: it is
    held as suspended, and lifting puts it back into deletion with the whole
    window ahead of it rather than what was left."""
    from app.db.request_context import Unattributed
    from app.db.session import set_rls_context
    from app.services.platform.guild_purge import purge_due_guilds

    moderator = await create_user(session, role=UserRole.moderator)
    guild = await create_guild(session)
    guild_id = guild.id
    long_ago = datetime.now(UTC) - timedelta(days=3650)
    await _set_status(session, guild, CommunityStatus.deleted, at=long_ago)
    await _moderate_grant(session, user=moderator, guild=guild)

    row = await _row(client, moderator, guild)
    assert "suspend" in row["allowed_actions"]
    suspended = await _suspend(client, moderator, guild)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["lifts_to"] == "deleted"

    await set_rls_context(session, Unattributed())
    assert await purge_due_guilds(session, now=datetime.now(UTC)) == 0
    session.expire_all()
    kept = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert kept.status == CommunityStatus.suspended.value
    await session.refresh(moderator)

    lifted = await _suspend(client, moderator, kept, suspended=False)
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["status"] == "deleted"
    session.expire_all()
    back = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert back.status_changed_at > long_ago + timedelta(days=3000)


async def test_an_operator_suspension_is_lifted_back_where_it_began(client, session):
    operator = await create_user(session, role=UserRole.operator)
    moderator = await create_user(session, role=UserRole.moderator)
    guild = await create_guild(session)
    await _set_status(session, guild, CommunityStatus.on_hold)

    response = await client.patch(
        f"{COMMUNITIES}/{guild.id}",
        json={"status": "suspended"},
        headers=get_auth_headers(operator),
    )
    assert response.status_code == 200, response.text
    assert response.json()["lifts_to"] == "on_hold"

    await _moderate_grant(session, user=moderator, guild=guild)
    lifted = await _suspend(client, moderator, guild, suspended=False)
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["status"] == "on_hold"


@pytest.mark.parametrize("status", [CommunityStatus.deleted, CommunityStatus.suspended])
async def test_a_moderate_grant_reads_a_community_that_is_closed(
    client, session, acting_user, status
):
    """A moderator looks before deciding, whatever the community's status."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    moderator = await create_user(session, role=UserRole.moderator)
    await _moderate_grant(session, user=moderator, guild=owner.guild)
    await _set_status(session, owner.guild, status)

    response = await client.get(
        owner.g("/initiatives/"), headers=get_auth_headers(moderator)
    )
    assert response.status_code == 200, response.text


async def test_a_community_is_found_by_its_number(client: AsyncClient, session) -> None:
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)
    for term in (str(guild.id), f"#{guild.id}"):
        response = await client.get(
            COMMUNITIES, params={"search": term}, headers=get_auth_headers(support)
        )
        assert response.status_code == 200, response.text
        assert guild.id in [row["id"] for row in response.json()["items"]]


@pytest.mark.parametrize("term", ["²", "#٣", "99999999999999999999"])
async def test_what_is_not_an_id_is_searched_as_a_name(
    client: AsyncClient, session, term: str
) -> None:
    support = await create_user(session, role=UserRole.support)
    response = await client.get(
        COMMUNITIES, params={"search": term}, headers=get_auth_headers(support)
    )
    assert response.status_code == 200, response.text
