"""A plug-in's state in a community, as the registration snapshot reads it.

Three things suspend a plug-in in a community: the owner suspending it
everywhere, staff suspending its install there, and being out of reach. Any of
them wins over the install's status; otherwise the status is the state.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import MappingProxyType

import asyncpg
import pytest
from sqlalchemy import update

from app.core.config import settings
from app.models.platform.plugin_install import PluginInstallStatus, PluginState
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.services.marketplace import registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.platform import notify_bus
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_plugin_service_registration,
    create_user,
    set_install_state,
)
from conftest import TEST_DATABASE_URL

GUILD = 7
OPERATIONS = 8
LISTING = "STATESNAPSHOT1"
PUBLIC_ID = "tests.states"


def _snapshot(*, suspension: str, status: PluginInstallStatus) -> RegistrationSnapshot:
    held = (
        PluginState.suspended if suspension == "install" else PluginState(status.value)
    )
    return RegistrationSnapshot(
        public_id=PUBLIC_ID,
        listing_uid=LISTING,
        base_url="https://plugin.example.test",
        page_origin=None,
        allowed_origins=(),
        keys=MappingProxyType({}),
        mandatory=False,
        suspended=suspension == "platform",
        live=suspension != "platform",
        operations_only=suspension == "reach",
        operations_guild_id=OPERATIONS,
        install_states=MappingProxyType(
            {} if held is PluginState.active else {GUILD: held}
        ),
    )


@pytest.mark.parametrize("status", list(PluginInstallStatus))
@pytest.mark.parametrize("suspension", ["none", "platform", "install", "reach"])
def test_a_suspension_wins_over_the_status(suspension, status):
    snapshot = _snapshot(suspension=suspension, status=status)
    expected = (
        PluginState(status.value) if suspension == "none" else PluginState.suspended
    )

    assert snapshot.state_in(GUILD) is expected
    serving = expected in (PluginState.active, PluginState.read_only)
    assert snapshot.serves(GUILD) is serving
    assert snapshot.live_in(GUILD) is serving
    # Another community, with no install that is not plain active, is only
    # suspended by the registration itself.
    assert snapshot.state_in(GUILD + 100) is (
        PluginState.suspended
        if suspension in ("platform", "reach")
        else PluginState.active
    )


def test_the_operations_community_is_in_reach():
    snapshot = _snapshot(suspension="reach", status=PluginInstallStatus.active)
    assert snapshot.state_in(OPERATIONS) is PluginState.active
    assert snapshot.state_in(None) is PluginState.suspended


async def _installed(session, status: PluginInstallStatus):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    plugin = await create_guild_plugin(
        session,
        guild,
        user,
        definition={"plugin_kind": "service", "service": {"public_id": PUBLIC_ID}},
        listing_uid=LISTING,
    )
    if status is not PluginInstallStatus.active:
        await set_install_state(session, guild.id, plugin.id, status=status.value)
    return guild, plugin


async def test_the_snapshot_carries_each_install_that_is_not_plain_active(session):
    await create_plugin_service_registration(
        session, public_id=PUBLIC_ID, listing_uid=LISTING
    )
    held, held_plugin = await _installed(session, PluginInstallStatus.on_hold)
    plain, _ = await _installed(session, PluginInstallStatus.active)
    read_only, _ = await _installed(session, PluginInstallStatus.read_only)
    suspended, suspended_plugin = await _installed(session, PluginInstallStatus.deleted)
    await set_install_state(session, suspended.id, suspended_plugin.id, suspended=True)

    snapshot = (await registration_lookup.load_registrations())[PUBLIC_ID]

    assert dict(snapshot.install_states) == {
        held.id: PluginState.on_hold,
        read_only.id: PluginState.read_only,
        suspended.id: PluginState.suspended,
    }
    assert snapshot.state_in(plain.id) is PluginState.active
    state = await registration_lookup.install_state(
        {"plugin_kind": "service", "service": {"public_id": PUBLIC_ID}},
        guild_id=held.id,
    )
    assert state.state is PluginState.on_hold and state.hidden
    assert not state.available

    await set_install_state(session, held.id, held_plugin.id, status="active")
    assert (await registration_lookup.load_registrations())[PUBLIC_ID].serves(held.id)


async def test_a_suspension_heard_on_the_bus_drops_the_snapshot(session, monkeypatch):
    """A suspension written by any process is announced on the channel at
    commit, and hearing it drops the snapshot this process holds."""
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)
    await create_plugin_service_registration(
        session, public_id=PUBLIC_ID, listing_uid=LISTING
    )
    cached = (await registration_lookup.load_registrations())[PUBLIC_ID]
    assert not cached.suspended
    heard = asyncio.Event()
    listener = await asyncpg.connect(dsn=notify_bus._dsn())
    try:
        await listener.add_listener(registration_lookup.CHANNEL, lambda *_: heard.set())
        await session.exec(
            update(PluginServiceRegistration)
            .where(PluginServiceRegistration.public_id == PUBLIC_ID)
            .values(suspended_at=datetime.now(UTC))
        )
        await session.commit()
        await asyncio.wait_for(heard.wait(), timeout=10)
    finally:
        await listener.close()

    assert (await registration_lookup.load_registrations())[PUBLIC_ID] is cached
    await registration_lookup.hint("")
    assert (await registration_lookup.load_registrations())[PUBLIC_ID].suspended
