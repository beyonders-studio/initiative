"""Bans and timeouts, through the members routes.

A ban removes somebody and refuses them at every way back in
(``ensure_membership``) until it is lifted. A timeout holds a member's content
read-only, the way a ``read_only`` community holds everybody's: routed into
``guild_<id>_ro``, so Postgres refuses the write.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access
from app.core.messages import GuildMessages
from app.core.tools import Tool
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.member_moderation import MemberModeration, ModerationKind
from app.services.platform import guilds as guilds_service
from app.services.platform import member_moderation as moderation_service
from app.services.tenant import task_statuses as task_statuses_service


def _entry(client_json, guild):
    return next((g for g in client_json if g["id"] == guild.id), None)


async def _invite_code(client: AsyncClient, admin) -> str:
    response = await client.post(
        f"/api/v1/communities/{admin.guild.id}/invites",
        headers=admin.headers,
        json={},
    )
    assert response.status_code == 201, response.text
    return response.json()["code"]


async def test_a_banned_member_stays_out_until_the_ban_is_lifted(
    client: AsyncClient, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    response = await client.delete(
        admin.g(f"/users/{member.user.id}?ban=true"), headers=admin.headers
    )
    assert response.status_code == 204, response.text
    mine = (await client.get("/api/v1/communities/", headers=member.headers)).json()
    assert _entry(mine, admin.guild) is None

    bans = (await client.get(admin.g("/users/bans"), headers=admin.headers)).json()
    assert [ban["user"]["id"] for ban in bans] == [member.user.id]

    refused = await client.post(
        "/api/v1/communities/invite/accept",
        headers=member.headers,
        json={"code": await _invite_code(client, admin)},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == GuildMessages.BANNED_FROM_COMMUNITY

    lifted = await client.delete(
        admin.g(f"/users/bans/{member.user.id}"), headers=admin.headers
    )
    assert lifted.status_code == 204, lifted.text
    accepted = await client.post(
        "/api/v1/communities/invite/accept",
        headers=member.headers,
        json={"code": await _invite_code(client, admin)},
    )
    assert accepted.status_code == 200, accepted.text


async def test_a_ban_is_a_refusal_a_sign_in_steps_around(
    session: AsyncSession, acting_user, client: AsyncClient
):
    """Sign-in rules and auto-join skip a community that refuses somebody, so
    a ban keeps them out without failing their sign-in."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await client.delete(
        admin.g(f"/users/{member.user.id}?ban=true"), headers=admin.headers
    )

    await set_rls_context(session, Unattributed())
    with pytest.raises(guilds_service.ADMISSION_REFUSALS) as refused:
        await guilds_service.ensure_membership(
            session, guild_id=admin.guild.id, user_id=member.user.id, via="sso"
        )
    assert refused.value.code == GuildMessages.BANNED_FROM_COMMUNITY


async def test_banning_follows_the_rules_for_removing(client: AsyncClient, acting_user):
    """Somebody who may not remove an admin may not ban one either."""
    holder = await acting_user(guild_role=CommunityRole.member)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=holder.guild)
    response = await client.delete(
        holder.g(f"/users/{admin.user.id}?ban=true"), headers=holder.headers
    )
    assert response.status_code == 403

    bans = await client.get(holder.g("/users/bans"), headers=holder.headers)
    assert bans.status_code == 403


async def _task_payload(session: AsyncSession, member) -> dict:
    await task_statuses_service.ensure_default_statuses(
        session, member.project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, member.project.id)
    await session.commit()
    return {
        "title": "while timed out",
        "project_id": member.project.id,
        "task_status_id": status.id,
    }


async def test_a_timed_out_member_reads_and_writes_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        project=True,
    )
    payload = await _task_payload(session, member)
    ends_at = datetime.now(UTC) + timedelta(hours=1)

    response = await client.put(
        admin.g(f"/users/{member.user.id}/timeout"),
        headers=admin.headers,
        json={"ends_at": ends_at.isoformat()},
    )
    assert response.status_code == 204, response.text

    entry = _entry(
        (await client.get("/api/v1/communities/", headers=member.headers)).json(),
        admin.guild,
    )
    assert entry["content_read_only"] is True
    assert datetime.fromisoformat(entry["timed_out_until"]) == ends_at

    reads = await client.get(member.g("/initiatives/"), headers=member.headers)
    assert reads.status_code == 200
    writes = await client.post(
        member.g("/tasks/"), headers=member.headers, json=payload
    )
    assert writes.status_code == 403, writes.text
    assert writes.json() == Tool.project.write_required().body

    roster = (await client.get(admin.g("/users/"), headers=admin.headers)).json()
    timed_out = {row["id"]: row["timed_out_until"] for row in roster["items"]}
    assert timed_out[member.user.id] is not None
    assert timed_out[admin.user.id] is None

    lifted = await client.delete(
        admin.g(f"/users/{member.user.id}/timeout"), headers=admin.headers
    )
    assert lifted.status_code == 204, lifted.text
    writes = await client.post(
        member.g("/tasks/"), headers=member.headers, json=payload
    )
    assert writes.status_code == 201, writes.text


async def test_the_database_holds_a_timed_out_member_read_only(
    session: AsyncSession, acting_user, client: AsyncClient
):
    """The seam routes them into the SELECT-only role, as for a frozen
    community, and the standing reports the hold the gates read."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await client.put(
        admin.g(f"/users/{member.user.id}/timeout"),
        headers=admin.headers,
        json={"ends_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )
    context = await establish_guild_access(session, member.user, admin.guild.id)
    assert context.content_read_only is True
    assert context.content_hold is True
    role = (await session.exec(text("SELECT current_user"))).one()[0]
    assert role.endswith("_ro")


async def test_a_timeout_ends_by_itself_and_outlives_leaving(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await client.put(
        admin.g(f"/users/{member.user.id}/timeout"),
        headers=admin.headers,
        json={"ends_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )

    left = await client.delete(
        f"/api/v1/communities/{admin.guild.id}/leave", headers=member.headers
    )
    assert left.status_code == 204, left.text
    accepted = await client.post(
        "/api/v1/communities/invite/accept",
        headers=member.headers,
        json={"code": await _invite_code(client, admin)},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["content_read_only"] is True

    await set_rls_context(session, Unattributed())
    await session.exec(
        update(MemberModeration)
        .where(MemberModeration.user_id == member.user.id)
        .values(ends_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()
    entry = _entry(
        (await client.get("/api/v1/communities/", headers=member.headers)).json(),
        admin.guild,
    )
    assert entry["content_read_only"] is False
    assert entry["timed_out_until"] is None


@pytest.mark.parametrize(
    "target_role,ends_in,status,code",
    [
        pytest.param(
            CommunityRole.admin,
            timedelta(hours=1),
            403,
            GuildMessages.TIMEOUT_NOT_FOR_ADMINS,
            id="not an administrator",
        ),
        pytest.param(
            CommunityRole.member,
            -timedelta(minutes=1),
            400,
            GuildMessages.TIMEOUT_MUST_END_LATER,
            id="not in the past",
        ),
    ],
)
async def test_a_timeout_is_refused(
    client: AsyncClient, acting_user, target_role, ends_in, status, code
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    target = await acting_user(guild_role=target_role, guild=admin.guild)
    response = await client.put(
        admin.g(f"/users/{target.user.id}/timeout"),
        headers=admin.headers,
        json={"ends_at": (datetime.now(UTC) + ends_in).isoformat()},
    )
    assert response.status_code == status, response.text
    assert response.json()["detail"] == code


async def test_a_timeout_never_replaces_a_ban(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A timeout set in the same moment as a ban leaves the ban in place."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await client.delete(
        admin.g(f"/users/{member.user.id}?ban=true"), headers=admin.headers
    )

    await set_rls_context(session, Unattributed())
    await moderation_service.time_out(
        session,
        guild_id=admin.guild.id,
        user_id=member.user.id,
        ends_at=datetime.now(UTC) + timedelta(hours=1),
        actor_user_id=admin.user.id,
    )
    await session.commit()
    row = (
        await session.exec(
            select(MemberModeration).where(MemberModeration.user_id == member.user.id)
        )
    ).one()
    assert row.kind == ModerationKind.ban
    assert row.ends_at is None


async def test_promotion_ends_the_hold(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Administrators are never timed out, so promoting a timed-out member
    lets them write again."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await client.put(
        admin.g(f"/users/{member.user.id}/timeout"),
        headers=admin.headers,
        json={"ends_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )
    promoted = await client.patch(
        f"/api/v1/communities/{admin.guild.id}/members/{member.user.id}",
        headers=admin.headers,
        json={"role": "admin"},
    )
    assert promoted.status_code == 204, promoted.text

    context = await establish_guild_access(session, member.user, admin.guild.id)
    assert context.content_read_only is False
    assert context.content_hold is False


async def test_a_timeout_names_its_offset(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    response = await client.put(
        admin.g(f"/users/{member.user.id}/timeout"),
        headers=admin.headers,
        json={"ends_at": "2099-01-01T12:00:00"},
    )
    assert response.status_code == 422, response.text
