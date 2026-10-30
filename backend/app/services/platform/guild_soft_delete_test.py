"""Deleting a community keeps it, and the operator is what brings it back.

Covers the retention window end to end: what a delete leaves behind, who can
still reach it while it sits there, what the restore wizard's endpoint asks
for, and when the purge finally destroys it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import GuildMessages
from app.core.moderation import HoldReason, HoldVia
from app.db import cohorts, post_commit
from app.db.holds import HoldsInForce
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.core.rules import (
    DEFAULT_GUILD_RETENTION_DAYS,
    DEFAULT_HOLD_DELETION_DAYS,
)
from app.models.platform.guild import (
    LIVE_STATUSES,
    OPERATOR_SETTABLE_STATUSES,
    Guild,
    GuildMembership,
    CommunityRole,
    CommunityStatus,
)
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.models.tenant.content_hold import ContentHold
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.services import email as email_service
from app.services.platform import guild_purge
from app.services.platform import guilds as guilds_service
from app.services.platform.identity_refs import billing_ref, existing_ref
from app.testing import emitted, route_session_to_guild
from app.testing.billing_boundary import change_kinds
from app.testing.billing_managed import billing_manages_plans
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_plugin_user_connection,
    create_user,
    get_auth_headers,
)


PASSWORD = "testpassword123"


async def _seated_guild(session: AsyncSession, **overrides):
    """A community with somebody holding its seat — the factory makes the row
    but no roster, and every rule here is about who is in it."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, **overrides)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    return admin, guild


async def _delete_via_danger_zone(
    client: AsyncClient, *, guild: Guild, headers: dict[str, str]
) -> None:
    response = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=headers,
        json={
            "password": PASSWORD,
            "confirmation_text": f"DELETE COMMUNITY {guild.name.upper()}",
        },
    )
    assert response.status_code == 204, response.text
    # The deletion arms the community's plug-in hook timer once it commits, on
    # a task of its own that holds the guild row while it writes. A purge
    # claims the row SKIP LOCKED, so it waits for that work to finish.
    await post_commit.settle_all()


# ── The status set itself ───────────────────────────────────────────────────


def test_deleted_is_not_a_status_that_reaches_content():
    """The anti-drift guard.

    Every gate asks ``status in LIVE_STATUSES``. This pins what that set
    contains, so adding a status is a decision about which side it falls on
    rather than something that happens by default.
    """
    assert LIVE_STATUSES == {CommunityStatus.active, CommunityStatus.read_only}
    assert CommunityStatus.deleted not in LIVE_STATUSES
    assert CommunityStatus.deleted not in OPERATOR_SETTABLE_STATUSES
    # Every status is either live or refused — none is unaccounted for.
    assert set(CommunityStatus) - LIVE_STATUSES == {
        CommunityStatus.suspended,
        CommunityStatus.on_hold,
        CommunityStatus.deleted,
    }


# ── What a delete leaves behind ─────────────────────────────────────────────


async def test_deleting_keeps_the_row_the_roster_and_the_content(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seated_guild(session)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)

    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    assert row.status == CommunityStatus.deleted.value
    # The deletion time, which is what the purge date counts from.
    assert row.status_changed_at is not None
    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).all()
    assert len(roster) == 2, "the roster is what a restore brings back"


async def test_a_community_of_one_takes_its_roster_with_it(
    client: AsyncClient, session: AsyncSession
):
    """The single case where memberships go.

    That roster is one row describing the person doing the deleting. Every
    larger community keeps its own, because those rows are other people's.
    """
    admin, guild = await _seated_guild(session)

    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    session.expunge_all()
    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).all()
    assert roster == []
    # ...and what comes back therefore has to be seated.
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    assert row.status == CommunityStatus.deleted.value


async def test_a_deleted_community_is_gone_for_its_admin_too(
    client: AsyncClient, session: AsyncSession
):
    """The carve-out that survives ``suspended`` does not survive deletion.

    A suspended community stays in its admins' list so they can still reach
    billing and the danger zone. A deleted one has no billing surface left and
    its danger zone has already been used, so it leaves every list.
    """
    admin, guild = await _seated_guild(session)
    # A second member, so the roster survives the delete and this is genuinely
    # testing the carve-out rather than an empty list.
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    headers = get_auth_headers(admin)

    listed = await client.get("/api/v1/communities/", headers=headers)
    assert [g["id"] for g in listed.json()] == [guild.id]

    await _delete_via_danger_zone(client, guild=guild, headers=headers)

    listed = await client.get("/api/v1/communities/", headers=headers)
    assert listed.json() == []
    # And it is refused on the path, not merely hidden from the list.
    refused = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert refused.status_code == 403


async def test_deleting_the_community_unblocks_deleting_the_account(
    session: AsyncSession,
):
    """The ordinary way out: delete your community, then your account.

    The sole-seat rule exists so a *live* community always keeps somebody who
    can run it. A deleted one has nothing to run, so holding its seat blocks
    nothing.
    """
    from app.services.platform import users as users_service

    holder, guild = await _seated_guild(session)
    await create_guild_membership(session, user=await create_user(session), guild=guild)

    assert await users_service.is_last_guild_superadmin(session, holder.id) == [
        guild.name
    ], "precondition: the seat blocks"

    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    await guilds_service.soft_delete_guild(session, row, actor_user_id=holder.id)
    await session.commit()

    assert await users_service.is_last_guild_superadmin(session, holder.id) == []


# ── Restore ─────────────────────────────────────────────────────────────────


async def test_restore_brings_it_back_at_the_status_the_operator_names(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    # Two members, so the roster — and with it the seat — survives the delete
    # and the restore has nothing to ask about.
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    response = await client.post(
        f"/api/v1/settings/communities/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "read_only"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "read_only"
    assert response.json()["purge_at"] is None

    # And its admin has it back.
    listed = await client.get("/api/v1/communities/", headers=get_auth_headers(admin))
    assert [g["id"] for g in listed.json()] == [guild.id]


async def _billing_ref(guild_id: int) -> str | None:
    return await existing_ref(
        entity_type=IdentityEntity.guild,
        entity_id=guild_id,
        purpose=IdentityPurpose.billing,
    )


async def _lifecycle_changes(session: AsyncSession, guild_id: int) -> list[str]:
    """The lifecycle kinds billing's change log holds for one community,
    besides its creation."""
    session.expunge_all()
    return [
        kind
        for kind in await change_kinds(session, guild_id)
        if kind != "community.created"
    ]


async def test_billing_keeps_its_name_for_a_deleted_community_and_hears_both_ways(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A soft delete keeps the guild's billing reference, and both the delete
    and the restore are written to billing's change log."""
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    ref = await billing_ref(IdentityEntity.guild, guild.id)

    async with billing_manages_plans(session):
        await _delete_via_danger_zone(
            client, guild=guild, headers=get_auth_headers(admin)
        )
        assert await _billing_ref(guild.id) == ref
        assert await _lifecycle_changes(session, guild.id) == ["community.deleted"]

        response = await client.post(
            f"/api/v1/settings/communities/{guild.id}/restore",
            headers=operator.headers,
            json={"status": "active"},
        )
        assert response.status_code == 200, response.text
        assert await _billing_ref(guild.id) == ref
        assert await _lifecycle_changes(session, guild.id) == [
            "community.deleted",
            "community.restored",
        ]


async def test_the_purge_is_what_drops_billings_name(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seated_guild(session)
    await billing_ref(IdentityEntity.guild, guild.id)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))
    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()

    await guild_purge.purge_due_guilds(
        session,
        now=row.status_changed_at
        + timedelta(days=DEFAULT_GUILD_RETENTION_DAYS, minutes=1),
    )

    assert await _billing_ref(guild.id) is None


async def test_its_plugins_keep_their_names_until_the_purge_erases_them(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A deleted community can come back under the names its plug-ins hold, so
    the delete keeps them. The purge asks each plug-in holding one to erase
    what it has, while the community still has its row, and deletes the row
    only once that erase is finished; the names go with the erase."""
    from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
    from app.models.platform.plugin_community_hook import PluginCommunityHook
    from app.services.marketplace import community_hooks, plugin_refs
    from app.services.platform.identity_refs import ensure_ref

    admin, guild = await _seated_guild(session)
    guild_id = guild.id
    # The name a plug-in the community had installed holds for its admin.
    member = await ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=admin.id,
        purpose=IdentityPurpose.plugin,
        sector_guild_id=guild_id,
        sector_plugin="tests.purged",
    )
    await session.commit()
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))
    assert await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild_id)

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    later = row.status_changed_at + timedelta(
        days=DEFAULT_GUILD_RETENTION_DAYS, minutes=1
    )
    assert await guild_purge.purge_due_guilds(session, now=later) == 0

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert row.purge_started_at is not None
    erase = (
        await session.exec(
            select(PluginCommunityHook).where(PluginCommunityHook.guild_id == guild_id)
        )
    ).one()
    assert (erase.public_id, erase.hook, erase.done_at) == (
        "tests.purged",
        "erase",
        None,
    )
    await session.commit()

    # Nothing is registered under that name here, so it is never answered.
    monkeypatch.setattr(community_hooks, "MAX_ATTEMPTS", 1)
    async with cohorts.system_session(guild_id) as routed:
        await set_rls_context(routed, SystemGuild(guild_id))
        await community_hooks.visit(routed, guild_id)
        await routed.commit()
    assert (
        await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild_id)
        is None
    )
    session.expunge_all()
    assert await guild_purge.purge_due_guilds(session, now=later) == 1
    assert (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).first() is None


async def test_restore_refuses_a_community_that_is_not_deleted(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    guild = await create_guild(session, creator=await create_user(session))

    response = await client.post(
        f"/api/v1/settings/communities/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == GuildMessages.COMMUNITY_NOT_DELETED


async def test_restore_needs_a_capability(
    client: AsyncClient, session: AsyncSession, acting_user
):
    plain = await acting_user("member")
    guild = await create_guild(session, creator=await create_user(session))

    response = await client.post(
        f"/api/v1/settings/communities/{guild.id}/restore",
        headers=plain.headers,
        json={"status": "active"},
    )
    assert response.status_code == 403


async def test_restore_asks_for_a_seat_when_the_roster_holds_none(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """What the operator deletion leaves, and what the wizard's second step is
    for: a community with nobody who can run it cannot simply be switched on."""
    operator = await acting_user("owner")
    _admin, guild = await _seated_guild(session)
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    # A community of one takes its roster with it, which is what leaves a
    # restore with nobody to run it.
    await guilds_service.soft_delete_guild(
        session, row, actor_user_id=operator.user.id, via="operator"
    )
    await session.commit()
    session.expunge_all()

    listed = await client.get("/api/v1/settings/communities", headers=operator.headers)
    entry = next(g for g in listed.json()["items"] if g["id"] == guild.id)
    assert entry["has_seat"] is False
    assert entry["purge_at"] is not None

    refused = await client.post(
        f"/api/v1/settings/communities/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active"},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == GuildMessages.COMMUNITY_RESTORE_SEAT_REQUIRED

    seated = await create_user(session)
    response = await client.post(
        f"/api/v1/settings/communities/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active", "seat_user_id": seated.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_seat"] is True

    session.expunge_all()
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == seated.id,
            )
        )
    ).one()
    assert membership.role == CommunityRole.superadmin


async def test_the_status_control_cannot_delete_a_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``deleted`` is reached by deleting and left by restoring, never by the
    dropdown — which would skip revoking the community's plug-in grants."""
    operator = await acting_user("owner")
    guild = await create_guild(session, creator=await create_user(session))

    response = await client.patch(
        f"/api/v1/settings/communities/{guild.id}",
        headers=operator.headers,
        json={"status": "deleted"},
    )
    assert response.status_code == 422


# ── The purge ───────────────────────────────────────────────────────────────


async def test_the_purge_waits_out_the_whole_window(
    client: AsyncClient, session: AsyncSession, capfd, monkeypatch
):
    """Nothing is destroyed a minute early. Each due community is then
    destroyed on its own and recorded once: one whose destruction fails is left
    for the next pass while the one behind it goes, and one another sweep holds
    is left to that sweep."""
    from app.db.session import SystemSessionLocal

    admin, guild = await _seated_guild(session)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))
    other_admin, other = await _seated_guild(session)
    await _delete_via_danger_zone(
        client, guild=other, headers=get_auth_headers(other_admin)
    )
    guild_id, other_id = guild.id, other.id
    session.expunge_all()

    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    deleted_at = row.status_changed_at
    assert deleted_at is not None

    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session,
            now=deleted_at
            + timedelta(days=DEFAULT_GUILD_RETENTION_DAYS)
            - timedelta(minutes=1),
        )
        == 0
    )
    assert (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).one_or_none() is not None

    later = datetime.now(timezone.utc) + timedelta(
        days=DEFAULT_GUILD_RETENTION_DAYS, minutes=1
    )
    destroy = guild_purge._destroy

    async def _first_fails(session, row, days):
        if row.id == guild_id:
            raise RuntimeError("destroying failed")
        return await destroy(session, row, days)

    monkeypatch.setattr(guild_purge, "_destroy", _first_fails)
    capfd.readouterr()
    session.expunge_all()
    assert await guild_purge.purge_due_guilds(session, now=later) == 1
    monkeypatch.setattr(guild_purge, "_destroy", destroy)
    remaining = (
        await session.exec(
            select(Guild.id).where(col(Guild.id).in_([guild_id, other_id]))
        )
    ).all()
    assert list(remaining) == [guild_id]

    async with SystemSessionLocal() as other_sweep:
        await other_sweep.exec(
            select(Guild.id).where(Guild.id == guild_id).with_for_update()
        )
        assert await guild_purge.purge_due_guilds(session, now=later) == 0
        await other_sweep.rollback()

    session.expunge_all()
    assert await guild_purge.purge_due_guilds(session, now=later) == 1
    session.expunge_all()
    assert await guild_purge.purge_due_guilds(session, now=later) == 0
    assert (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).one_or_none() is None
    purged = [row["guild_id"] for row in emitted(capfd, AuditEventType.GUILD_PURGED)]
    assert sorted(purged) == sorted([guild_id, other_id])


async def test_the_window_is_the_deployments_to_set(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One figure for the whole server, set by whoever runs it."""
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_community_retention_days": 7,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_community_retention_days"] == 7

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    deleted_at = row.status_changed_at
    assert deleted_at is not None

    # The window is counted from each deletion rather than stamped at the time,
    # so shortening it moves what is already deleted.
    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(session, now=deleted_at + timedelta(days=6))
        == 0
    )
    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(session, now=deleted_at + timedelta(days=8))
        == 1
    )


async def test_a_deployment_can_keep_deleted_communities_forever(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Clearing the figure means never destroy one.

    For a deployment that has undertaken to keep what its members put in it:
    deleted communities sit in the operator's list until somebody acts.
    """
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_community_retention_days": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_community_retention_days"] is None

    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session, now=datetime.now(timezone.utc) + timedelta(days=3650)
        )
        == 0
    )
    assert (
        await session.exec(select(Guild).where(Guild.id == guild.id))
    ).one_or_none() is not None

    # And the operator's list says there is no date, rather than inventing one.
    listed = await client.get("/api/v1/settings/communities", headers=operator.headers)
    entry = next(g for g in listed.json()["items"] if g["id"] == guild.id)
    assert entry["status"] == "deleted"
    assert entry["purge_at"] is None


async def test_omitting_the_window_leaves_it_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``null`` is an answer here, so only sending the field counts as one."""
    operator = await acting_user("owner")

    await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_community_retention_days": 30,
        },
    )
    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={"community_directory_enabled": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_community_retention_days"] == 30


async def test_the_purge_leaves_live_communities_alone(session: AsyncSession):
    """Every status but ``deleted`` is somebody's community, however frozen."""
    kept = []
    for status in OPERATOR_SETTABLE_STATUSES:
        guild = await create_guild(session, creator=await create_user(session))
        row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
        row.status = status.value
        row.status_changed_at = datetime.now(timezone.utc) - timedelta(days=365)
        session.add(row)
        kept.append(guild.id)
    await session.commit()
    session.expunge_all()

    assert (
        await guild_purge.purge_due_guilds(session, now=datetime.now(timezone.utc)) == 0
    )
    for guild_id in kept:
        assert (
            await session.exec(select(Guild).where(Guild.id == guild_id))
        ).one_or_none() is not None


async def test_destroying_now_leaves_a_held_community_and_its_connections(
    session: AsyncSession,
):
    admin, guild = await _seated_guild(session)
    guild_id = guild.id
    plugin = await create_guild_plugin(
        session,
        guild,
        admin,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.purge", "protocol": 1},
            "connections": [{"id": "github", "scope": "member"}],
        },
    )
    await create_plugin_user_connection(session, plugin, admin)
    session.add(
        ContentHold(
            target_type="task",
            target_id=1,
            placed_via=HoldVia.community.value,
            reason=HoldReason.legal_request.value,
        )
    )
    await session.commit()

    with pytest.raises(HoldsInForce):
        await guild_purge.destroy_now(session, guild)
    await session.rollback()

    await route_session_to_guild(session, guild_id)
    assert (await session.exec(select(GuildPluginUserConnection))).all()
    assert await session.get(Guild, guild_id) is not None


async def test_deleting_a_community_writes_to_the_seat_that_could_restore_it(session):
    """The superadmin seat hears. An ordinary admin cannot ask for a restore,
    and members learn from it leaving their lists."""
    from app.models.platform.guild import CommunityRole
    from app.services.platform import guilds as guilds_service
    from app.testing import create_guild_membership, create_user

    seat = await create_user(session, email="gd-seat@example.com")
    guild = await create_guild(session, creator=seat, name="Allotment Society")
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    boss = await create_user(session, email="gd-admin@example.com")
    await create_guild_membership(
        session, user=boss, guild=guild, role=CommunityRole.admin
    )
    hand = await create_user(session, email="gd-member@example.com")
    await create_guild_membership(
        session, user=hand, guild=guild, role=CommunityRole.member
    )

    notice = await guilds_service.soft_delete_guild(
        session, guild, actor_user_id=seat.id
    )

    assert notice.community_name == "Allotment Society"
    assert notice.recipients == ["gd-seat@example.com"]


async def test_the_notice_is_gathered_before_the_roster_goes(session):
    """A community of one loses its roster on the way out, so the person to
    tell has to be read while they are still in it."""
    from app.models.platform.guild import CommunityRole
    from app.services.platform import guilds as guilds_service
    from app.testing import create_guild_membership, create_user

    alone = await create_user(session, email="gd-solo@example.com")
    guild = await create_guild(session, creator=alone, name="Just Me")
    await create_guild_membership(
        session, user=alone, guild=guild, role=CommunityRole.superadmin
    )

    notice = await guilds_service.soft_delete_guild(
        session, guild, actor_user_id=alone.id
    )

    assert notice.recipients == ["gd-solo@example.com"]


# ── When a hold runs out ────────────────────────────────────────────────────


async def _hold_since(session: AsyncSession, guild_id: int, held_at: datetime) -> None:
    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    row.status = CommunityStatus.on_hold.value
    row.status_changed_at = held_at
    session.add(row)
    await session.commit()
    session.expunge_all()


async def test_a_hold_that_runs_out_deletes_the_community(
    session: AsyncSession, monkeypatch
):
    """Deleted, not destroyed: the retention window starts from here, the seat
    hears as it would from any deletion, and billing's change log says so.
    Nobody asked for it, so even a community of one keeps its roster."""
    seat = await create_user(session, email="hold-seat@example.com")
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    guild_id, name = guild.id, guild.name
    held_at = datetime.now(timezone.utc) - timedelta(
        days=DEFAULT_HOLD_DELETION_DAYS + 1
    )
    await _hold_since(session, guild_id, held_at)
    letters = []

    async def _capture(_session, notice, **_kwargs) -> None:
        letters.append(notice)

    monkeypatch.setattr(email_service, "announce_community_deleted", _capture)

    async with billing_manages_plans(session):
        assert (
            await guild_purge.delete_expired_holds(
                session, now=datetime.now(timezone.utc)
            )
            == 1
        )

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert row.status == CommunityStatus.deleted.value
    assert row.status_changed_at > held_at, "the retention window counts from now"
    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild_id)
        )
    ).all()
    assert len(roster) == 1
    assert await _lifecycle_changes(session, guild_id) == ["community.deleted"]
    assert [(n.community_name, n.recipients) for n in letters] == [
        (name, ["hold-seat@example.com"])
    ]


async def test_a_hold_waits_out_its_whole_window(session: AsyncSession):
    _, guild = await _seated_guild(session)
    guild_id = guild.id
    held_at = datetime.now(timezone.utc) - timedelta(days=1)
    await _hold_since(session, guild_id, held_at)
    deletes_at = held_at + timedelta(days=DEFAULT_HOLD_DELETION_DAYS)

    assert (
        await guild_purge.delete_expired_holds(
            session, now=deletes_at - timedelta(minutes=1)
        )
        == 0
    )
    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert row.status == CommunityStatus.on_hold.value

    session.expunge_all()
    assert (
        await guild_purge.delete_expired_holds(
            session, now=deletes_at + timedelta(minutes=1)
        )
        == 1
    )


async def test_only_a_hold_runs_out(session: AsyncSession):
    """Every other status is left as it is, however long it has been."""
    kept = {}
    for status in OPERATOR_SETTABLE_STATUSES:
        if status is CommunityStatus.on_hold:
            continue
        guild = await create_guild(session, creator=await create_user(session))
        row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
        row.status = status.value
        row.status_changed_at = datetime.now(timezone.utc) - timedelta(days=365)
        session.add(row)
        kept[guild.id] = status.value
    await session.commit()
    session.expunge_all()

    assert (
        await guild_purge.delete_expired_holds(session, now=datetime.now(timezone.utc))
        == 0
    )
    for guild_id, status in kept.items():
        row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
        assert row.status == status


async def test_a_deployment_can_leave_holds_in_place(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Clearing the figure means a hold never runs out on its own."""
    operator = await acting_user("owner")
    _, guild = await _seated_guild(session)
    guild_id = guild.id
    await _hold_since(session, guild_id, datetime.now(timezone.utc))

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "on_hold_community_deletion_days": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["on_hold_community_deletion_days"] is None

    session.expunge_all()
    assert (
        await guild_purge.delete_expired_holds(
            session, now=datetime.now(timezone.utc) + timedelta(days=3650)
        )
        == 0
    )
    row = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert row.status == CommunityStatus.on_hold.value


async def test_the_hold_is_told_in_each_seats_language(
    session: AsyncSession, monkeypatch
):
    """Each seat holder gets a letter at every address they have proved, in
    the language they read, as account mail."""
    from unittest.mock import AsyncMock

    from app.core.encryption import SALT_EMAIL, decrypt_field
    from app.models.platform.email_outbox import EmailOutboxItem
    from app.models.platform.notification import Notification, NotificationType
    from app.services.auth import addresses
    from app.testing import drain_notices

    seat = await create_user(session, email="hold-en@example.com")
    addresses.record_address(
        session,
        user_id=seat.id,
        email="hold-en-2@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    german = await create_user(session, email="hold-de@example.com", locale="de")
    await create_guild_membership(
        session, user=german, guild=guild, role=CommunityRole.superadmin
    )
    guild_id, seat_id = guild.id, seat.id
    held_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    await _hold_since(session, guild_id, held_at)
    sent: list[dict] = []
    written = email_service.community_on_hold_pieces

    def _capture(**kwargs):
        sent.append(kwargs)
        return written(**kwargs)

    monkeypatch.setattr(email_service, "community_on_hold_pieces", _capture)
    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))

    await guilds_service.announce_on_hold(session, guild_id)

    assert sorted(letter["locale"] for letter in sent) == ["de", "en"]
    letters = (
        await session.exec(
            select(EmailOutboxItem).where(
                col(EmailOutboxItem.user_id).in_([seat_id, german.id])
            )
        )
    ).all()
    assert sorted(
        (
            decrypt_field(letter.recipient_encrypted or "", SALT_EMAIL),
            letter.locale,
            letter.security,
        )
        for letter in letters
    ) == [
        ("hold-de@example.com", "de", True),
        ("hold-en-2@example.com", "en", True),
        ("hold-en@example.com", "en", True),
    ]
    delete_at = held_at + timedelta(days=DEFAULT_HOLD_DELETION_DAYS)
    assert {letter["delete_at"] for letter in sent} == {delete_at}
    assert {letter["guild_id"] for letter in sent} == {guild_id}
    # The bell carries the day too, and writes it in the reader's language.
    await drain_notices()
    session.expire_all()
    (line,) = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == seat_id,
                Notification.type == NotificationType.community_on_hold,
            )
        )
    ).all()
    assert line.data["delete_on"] == delete_at.date().isoformat()


async def test_the_hold_notice_names_the_day_it_is_deleted(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    operator = await acting_user("owner")
    _, guild = await _seated_guild(session)
    guild_id = guild.id
    held_at = datetime.now(timezone.utc)
    await _hold_since(session, guild_id, held_at)
    sent = []
    written = email_service.community_on_hold_pieces

    def _capture(**kwargs):
        sent.append(kwargs["delete_at"])
        return written(**kwargs)

    monkeypatch.setattr(email_service, "community_on_hold_pieces", _capture)

    await guilds_service.announce_on_hold(session, guild_id)
    assert sent == [held_at + timedelta(days=DEFAULT_HOLD_DELETION_DAYS)]

    await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "on_hold_community_deletion_days": None,
        },
    )
    session.expunge_all()
    await guilds_service.announce_on_hold(session, guild_id)
    assert sent[1] is None
