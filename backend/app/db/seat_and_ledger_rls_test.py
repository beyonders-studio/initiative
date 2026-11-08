"""Guild-level tables the database decides for itself.

``guild_ai_connections`` is read within the community — a member's AI request
reads the connection it runs on — and written by the seat alone.
``plugin_placements`` has the same shape: read within the community, placed by
the seat. ``guild_plugin_secrets`` and ``guild_ai_connection_keys`` are read and
written by the seat and the system engine alone, and the trigger on the first
keeps ``guild_plugins.secret_fields`` in step.
``webhook_deliveries`` is read through its subscription and written by the
system engine; ``webhook_refs`` is read and written by the system engine
alone. Each test acts on the real request login, routed through the
seam, and carries no guard of its own: what the database accepts is what the
policies allow.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.ai_connection import GuildAIConnection, GuildAIConnectionKey
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import webhook_refs
from app.testing import (
    create_access_grant,
    create_guild_plugin,
    create_initiative,
    create_user,
    create_webhook_subscription,
    route_as,
    route_session_to_guild,
)


async def _as(role_session, *, user_id: int, guild_id: int, settings=False):
    """A request-login session routed into the community, as a request is."""
    s = await role_session("app_user")
    await route_as(s, user_id=user_id, guild_id=guild_id, settings=settings)
    return s


async def _seed_connection(session, guild_id: int, user_id: int) -> None:
    await route_session_to_guild(session, guild_id)
    session.add(
        GuildAIConnection(
            label="Shared",
            provider="openai",
            created_by=user_id,
            created_by_kind=ActorKind.member,
        )
    )
    await session.commit()


async def _labels(session, guild_id: int) -> list[str]:
    await route_session_to_guild(session, guild_id)
    return sorted(
        (await session.exec(select(GuildAIConnection.label))).all()  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# guild_ai_connections
# ---------------------------------------------------------------------------


async def test_a_member_reads_a_connection_and_does_not_write_one(
    session, acting_user, role_session
):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await _seed_connection(session, seat.guild.id, seat.user.id)
    member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
    s = await _as(role_session, user_id=member.user.id, guild_id=seat.guild.id)
    assert list(await s.exec(select(GuildAIConnection.label))) == ["Shared"]
    s.add(GuildAIConnection(label="By a member", provider="openai"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert await _labels(session, seat.guild.id) == ["Shared"]


async def test_an_admin_below_the_seat_does_not_write_a_connection(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    s.add(GuildAIConnection(label="By an admin", provider="openai"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert await _labels(session, a.guild.id) == []


async def test_the_seat_writes_a_connection(session, acting_user, role_session):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    s = await _as(
        role_session, user_id=seat.user.id, guild_id=seat.guild.id, settings=True
    )
    s.add(GuildAIConnection(label="By the seat", provider="openai"))
    await s.commit()
    await s.exec(text("UPDATE guild_ai_connections SET label = 'Renamed by the seat'"))
    await s.commit()
    assert await _labels(session, seat.guild.id) == ["Renamed by the seat"]


async def test_a_lent_seat_writes_only_beside_read_write(
    session, acting_user, role_session
):
    """A superadmin settings grant reads; the read_write content grant beside
    it is what lets it change a connection."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await _seed_connection(session, seat.guild.id, seat.user.id)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session,
        user=support,
        guild=seat.guild,
        access_level="superadmin",
        purpose="settings",
    )
    s = await _as(
        role_session, user_id=support.id, guild_id=seat.guild.id, settings=True
    )
    assert list(await s.exec(select(GuildAIConnection.label))) == ["Shared"]
    s.add(GuildAIConnection(label="By the rung alone", provider="openai"))
    with pytest.raises(DBAPIError, match="permission denied|row-level security"):
        await s.commit()
    await s.rollback()

    await create_access_grant(
        session, user=support, guild=seat.guild, access_level="read_write"
    )
    s = await _as(
        role_session, user_id=support.id, guild_id=seat.guild.id, settings=True
    )
    s.add(GuildAIConnection(label="By the pair", provider="openai"))
    await s.commit()
    assert await _labels(session, seat.guild.id) == ["By the pair", "Shared"]


# ---------------------------------------------------------------------------
# plugin_placements
# ---------------------------------------------------------------------------

_PLUGIN_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": "tests.placed", "protocol": 1},
}


async def _placed_initiatives(session, guild_id: int) -> list[int]:
    await route_session_to_guild(session, guild_id)
    return sorted(
        (await session.exec(select(PluginPlacement.initiative_id))).all()  # type: ignore[arg-type]
    )


async def test_a_member_reads_placements_and_does_not_write_one(
    session, acting_user, role_session
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    plugin = await create_guild_plugin(
        session, seat.guild, seat.user, definition=_PLUGIN_DEFINITION
    )
    await route_session_to_guild(session, seat.guild.id)
    session.add(PluginPlacement(install_id=plugin.id, initiative_id=seat.initiative.id))
    await session.commit()
    other = await create_initiative(session, seat.guild, seat.user)

    member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
    s = await _as(role_session, user_id=member.user.id, guild_id=seat.guild.id)
    assert list(await s.exec(select(PluginPlacement.initiative_id))) == [
        seat.initiative.id
    ]
    s.add(PluginPlacement(install_id=plugin.id, initiative_id=other.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert await _placed_initiatives(session, seat.guild.id) == [seat.initiative.id]


async def test_an_admin_below_the_seat_does_not_place_a_plugin(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await create_guild_plugin(
        session, a.guild, a.user, definition=_PLUGIN_DEFINITION
    )
    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    s.add(PluginPlacement(install_id=plugin.id, initiative_id=a.initiative.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert await _placed_initiatives(session, a.guild.id) == []


async def test_the_seat_places_a_plugin(session, acting_user, role_session):
    """On the content route the placement endpoint uses."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    plugin = await create_guild_plugin(
        session, seat.guild, seat.user, definition=_PLUGIN_DEFINITION
    )
    s = await _as(role_session, user_id=seat.user.id, guild_id=seat.guild.id)
    s.add(PluginPlacement(install_id=plugin.id, initiative_id=seat.initiative.id))
    await s.commit()
    assert await _placed_initiatives(session, seat.guild.id) == [seat.initiative.id]


# ---------------------------------------------------------------------------
# guild_plugins.granted_scopes
# ---------------------------------------------------------------------------


async def _granted(session, guild_id: int, install_id: int) -> list[str]:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    row = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == install_id))
    ).one()
    return list(row.granted_scopes)


async def test_an_admin_below_the_seat_does_not_write_an_install(
    session, acting_user, role_session
):
    """Installing, configuring and granting are the seat's: an admin below it
    reads the install and changes nothing on it."""
    a = await acting_user(guild_role=CommunityRole.admin)
    plugin = await create_guild_plugin(
        session, a.guild, a.user, definition=_PLUGIN_DEFINITION
    )
    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    result = await s.exec(
        text(
            "UPDATE guild_plugins SET name = 'Renamed', "
            "granted_scopes = ARRAY['files:read'] WHERE id = :id"
        ).bindparams(id=plugin.id)
    )
    assert result.rowcount == 0
    await s.rollback()
    assert await _granted(session, a.guild.id, plugin.id) == []


async def test_the_seat_grants_scopes(session, acting_user, role_session):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    plugin = await create_guild_plugin(
        session, seat.guild, seat.user, definition=_PLUGIN_DEFINITION
    )
    s = await _as(role_session, user_id=seat.user.id, guild_id=seat.guild.id)
    row = (await s.exec(select(GuildPlugin).where(GuildPlugin.id == plugin.id))).one()
    row.granted_scopes = ["files:read"]
    s.add(row)
    await s.commit()
    assert await _granted(session, seat.guild.id, plugin.id) == ["files:read"]


# ---------------------------------------------------------------------------
# guild_plugin_secrets
# ---------------------------------------------------------------------------


async def test_only_the_seat_and_the_system_engine_read_secrets(
    session, acting_user, role_session
):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    plugin = await create_guild_plugin(
        session,
        seat.guild,
        seat.user,
        definition=_PLUGIN_DEFINITION,
        secrets={"admin": {"admin_token": "ciphertext"}},
    )
    await route_session_to_guild(session, seat.guild.id)
    connection = GuildAIConnection(
        label="Shared",
        provider="openai",
        created_by=seat.user.id,
        created_by_kind=ActorKind.member,
    )
    session.add(connection)
    await session.flush()
    session.add(
        GuildAIConnectionKey(connection_id=connection.id, api_key_encrypted="ct")
    )
    await session.commit()
    member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
    read = text(
        "SELECT install_id FROM guild_plugin_secrets "
        "UNION ALL SELECT connection_id FROM guild_ai_connection_keys"
    )
    both = [(plugin.id,), (connection.id,)]

    s = await _as(role_session, user_id=member.user.id, guild_id=seat.guild.id)
    assert list(await s.exec(read)) == []
    s = await _as(role_session, user_id=seat.user.id, guild_id=seat.guild.id)
    assert list(await s.exec(read)) == both
    system = await role_session("app_admin")
    await set_rls_context(system, SystemGuild(seat.guild.id))
    assert list(await system.exec(read)) == both


async def test_secret_fields_follow_the_stored_values(
    session, acting_user, role_session
):
    """Each key that holds a value, with the digest of its ciphertext, written
    by the trigger as the seat stores, replaces and removes the values."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    plugin = await create_guild_plugin(
        session, seat.guild, seat.user, definition=_PLUGIN_DEFINITION
    )
    s = await _as(role_session, user_id=seat.user.id, guild_id=seat.guild.id)
    row = (await s.exec(select(GuildPlugin).where(GuildPlugin.id == plugin.id))).one()
    assert row.secret_fields == {}

    for value in ("first", "second"):
        await guild_plugins_service.store_secrets(
            s, row, {"admin": {"admin_token": value}}
        )
        digest = hashlib.sha256(value.encode()).hexdigest()
        assert row.secret_fields == {"admin": {"admin_token": digest}}
    assert await guild_plugins_service.load_secrets(s, row) == {
        "admin": {"admin_token": "second"}
    }

    await guild_plugins_service.store_secrets(s, row, {})
    assert row.secret_fields == {}
    assert await guild_plugins_service.load_secrets(s, row) == {}
    await s.commit()


# ---------------------------------------------------------------------------
# webhook_deliveries
# ---------------------------------------------------------------------------


async def _subscription(session, *, guild_id: int, initiative_id, user_id: int):
    await route_session_to_guild(session, guild_id)
    now = datetime.now(UTC)
    sub = WebhookSubscription(
        initiative_id=initiative_id,
        created_by=user_id,
        created_by_kind=ActorKind.member,
        target_url="https://hooks.example.com/in",
        hmac_secret="s" * 32,
        event_types=["task.created"],
        created_at=now,
        updated_at=now,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    await session.exec(
        text(
            "INSERT INTO webhook_deliveries (subscription_id, txn_id, attempts) "
            "VALUES (:sid, 424242, 0)"
        ).bindparams(sid=sub.id)
    )
    await session.commit()
    return sub.id


async def _delivery_subscriptions(s) -> list[int]:
    rows = await s.exec(text("SELECT subscription_id FROM webhook_deliveries"))
    return [r[0] for r in rows]


async def test_deliveries_are_read_through_their_subscription(
    session, acting_user, role_session
):
    """A member of the subscription's initiative reads its deliveries; a
    member of the community who is not in that initiative reads none, and
    neither does anyone but the administrator for a community-wide one."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    inside = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    outside = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await create_initiative(session, a.guild, outside.user)
    scoped = await _subscription(
        session, guild_id=a.guild.id, initiative_id=a.initiative.id, user_id=a.user.id
    )
    wide = await _subscription(
        session, guild_id=a.guild.id, initiative_id=None, user_id=a.user.id
    )

    s = await _as(role_session, user_id=inside.user.id, guild_id=a.guild.id)
    assert await _delivery_subscriptions(s) == [scoped]
    s = await _as(role_session, user_id=outside.user.id, guild_id=a.guild.id)
    assert await _delivery_subscriptions(s) == []
    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    assert sorted(await _delivery_subscriptions(s)) == sorted([scoped, wide])


async def test_only_the_system_engine_writes_a_delivery(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    sid = await _subscription(
        session, guild_id=a.guild.id, initiative_id=a.initiative.id, user_id=a.user.id
    )
    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.exec(
            text(
                "INSERT INTO webhook_deliveries (subscription_id, txn_id, attempts) "
                "VALUES (:sid, 525252, 0)"
            ).bindparams(sid=sid)
        )
    await s.rollback()
    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    updated = await s.exec(
        text("UPDATE webhook_deliveries SET attempts = 9 RETURNING txn_id")
    )
    assert list(updated) == []
    await s.rollback()

    # A sweep routes with the community alone, as the poller does.
    system = await role_session("app_admin")
    await set_rls_context(system, SystemGuild(a.guild.id))
    updated = await system.exec(
        text("UPDATE webhook_deliveries SET attempts = 1 RETURNING txn_id")
    )
    assert list(updated) == [(424242,)]
    await system.commit()


# ---------------------------------------------------------------------------
# webhook_refs
# ---------------------------------------------------------------------------


async def test_a_subscriptions_names_are_the_system_engines_alone(
    session, acting_user, role_session
):
    """The administrator sees the subscription and the names on it, which the
    system engine reads out; the table itself is closed to them."""
    a = await acting_user(guild_role=CommunityRole.admin)
    subscription = await create_webhook_subscription(session, a.guild, a.user)
    named = await webhook_refs.name_for_subscriber(
        guild_id=a.guild.id, plugin=None, subscription_id=subscription.id
    )
    assert named is not None
    guild_ref, _ = named

    s = await _as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    assert list(await s.exec(text("SELECT ref FROM webhook_refs"))) == []
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.exec(
            text(
                "INSERT INTO webhook_refs"
                " (subscription_id, entity_type, entity_id, ref, created_at)"
                " VALUES (:sid, 'user', :uid, 'uweb_chosen', now())"
            ).bindparams(sid=subscription.id, uid=a.user.id)
        )
    await s.rollback()

    system = await role_session("app_admin")
    await set_rls_context(system, SystemGuild(a.guild.id))
    assert list(await system.exec(text("SELECT ref FROM webhook_refs"))) == [
        (guild_ref,)
    ]
