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
from app.models.platform.plugin_service_registration import (
    PluginAvailability,
    PluginServiceRegistration,
)
from app.services.marketplace import contract, registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.platform import notify_bus
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_plugin_service_registration,
    create_user,
    set_beta_communities,
    set_install_state,
)
from conftest import TEST_DATABASE_URL

GUILD = 7
OPERATIONS = 8
LISTING = "STATESNAPSHOT1"
PUBLIC_ID = "tests.states"


#: Out of reach: limited to the operations community, or beta with the
#: community off its list.
_OUT_OF_REACH = {
    "operations": PluginAvailability.operations,
    "beta": PluginAvailability.beta,
}


def _snapshot(
    *,
    suspension: str,
    status: PluginInstallStatus,
    availability: PluginAvailability | None = None,
    beta: frozenset[int] = frozenset({OPERATIONS}),
) -> RegistrationSnapshot:
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
        availability=(
            availability or _OUT_OF_REACH.get(suspension, PluginAvailability.none)
        ).value,
        operations_guild_id=OPERATIONS,
        beta_communities=beta,
        install_states=MappingProxyType(
            {} if held is PluginState.active else {GUILD: held}
        ),
    )


@pytest.mark.parametrize("status", list(PluginInstallStatus))
@pytest.mark.parametrize(
    "suspension", ["none", "platform", "install", "operations", "beta"]
)
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
        if suspension in ("platform", *_OUT_OF_REACH)
        else PluginState.active
    )


@pytest.mark.parametrize(
    ("availability", "beta", "in_reach"),
    [
        (PluginAvailability.none, frozenset(), {GUILD, OPERATIONS}),
        (PluginAvailability.operations, frozenset({GUILD}), {OPERATIONS}),
        (PluginAvailability.beta, frozenset({GUILD}), {GUILD}),
        (PluginAvailability.beta, frozenset(), set()),
    ],
)
def test_reach_follows_availability(availability, beta, in_reach):
    """Every community; the operations community; the beta list, nobody
    while it is empty."""
    snapshot = _snapshot(
        suspension="none",
        status=PluginInstallStatus.active,
        availability=availability,
        beta=beta,
    )
    for guild_id in (GUILD, OPERATIONS):
        assert snapshot.serves(guild_id) is (guild_id in in_reach)
    assert snapshot.serves(None) is (availability is PluginAvailability.none)


def test_the_contract_declares_each_availability():
    assert contract.enum("availability") == {
        value.value for value in PluginAvailability
    }


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


async def test_the_snapshot_carries_a_beta_plugins_list(session):
    await create_plugin_service_registration(
        session, public_id=PUBLIC_ID, listing_uid=LISTING, availability="beta"
    )
    picked, _ = await _installed(session, PluginInstallStatus.active)
    other, _ = await _installed(session, PluginInstallStatus.active)
    await set_beta_communities(session, LISTING, picked.id)

    snapshot = (await registration_lookup.load_registrations())[PUBLIC_ID]

    assert snapshot.beta_communities == {picked.id}
    assert snapshot.live_in(picked.id)
    assert snapshot.state_in(other.id) is PluginState.suspended


@pytest.mark.parametrize("moved", ["suspension", "availability", "beta_list"])
async def test_a_suspension_heard_on_the_bus_drops_the_snapshot(
    session, monkeypatch, moved
):
    """A suspension, a reach or a beta list written by any process is
    announced on the channel at commit, and hearing it drops the snapshot
    this process holds."""
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)
    await create_plugin_service_registration(
        session, public_id=PUBLIC_ID, listing_uid=LISTING
    )
    guild, _ = await _installed(session, PluginInstallStatus.active)
    cached = (await registration_lookup.load_registrations())[PUBLIC_ID]
    assert cached.live_in(guild.id)
    heard = asyncio.Event()
    listener = await asyncpg.connect(dsn=notify_bus._dsn())
    try:
        await listener.add_listener(registration_lookup.CHANNEL, lambda *_: heard.set())
        if moved == "beta_list":
            await set_beta_communities(session, LISTING, guild.id)
        else:
            await session.exec(
                update(PluginServiceRegistration)
                .where(PluginServiceRegistration.public_id == PUBLIC_ID)
                .values(
                    suspended_at=datetime.now(UTC) if moved == "suspension" else None,
                    availability=PluginAvailability.beta.value
                    if moved == "availability"
                    else PluginAvailability.none.value,
                )
            )
            await session.commit()
        await asyncio.wait_for(heard.wait(), timeout=10)
    finally:
        await listener.close()

    if moved != "beta_list":
        assert (await registration_lookup.load_registrations())[PUBLIC_ID] is cached
    await registration_lookup.hint("")
    assert (await registration_lookup.load_registrations())[PUBLIC_ID].live_in(
        guild.id
    ) is (moved == "beta_list")
