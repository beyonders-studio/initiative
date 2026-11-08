"""Plug-ins the deployment places itself, in the audit log.

These arrive without anybody choosing them, and the record has to say so —
``via`` is what separates one of these from a guild admin picking a plug-in out of
the catalog.

The actor is the other half. A guild creation runs as its new owner and the
record names them; the boot sweep runs as nobody and the record names nobody.
"""

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.services.tenant.mandatory_plugins import backfill_mandatory_plugins
from app.testing import (
    create_guild,
    create_guild_membership,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_user,
    emitted,
    get_auth_headers,
    marketplace_uid,
)

PROVIDED_ID = "platform.auditprovided"
PROVIDED_UID = marketplace_uid("auditprovided")

PROVIDED_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": PROVIDED_ID, "protocol": 1},
    "features": [],
    "default_name": "Provided plug-in",
}


@pytest.fixture
async def mandatory_registration(session: AsyncSession):
    await create_marketplace_listing(
        session,
        uid=PROVIDED_UID,
        public_id=PROVIDED_ID,
        kind="plugin",
        name="Provided plug-in",
        definition=PROVIDED_DEFINITION,
    )
    return await create_plugin_service_registration(
        session,
        public_id=PROVIDED_ID,
        base_url="https://auditprovided.example.test",
        listing_uid=PROVIDED_UID,
        mandatory=True,
    )


async def test_a_new_guild_records_its_provided_plugin_against_the_owner(
    client: AsyncClient, session: AsyncSession, mandatory_registration, capfd
):
    user = await create_user(session, email="audit-founder@example.com")
    user_id = user.id
    capfd.readouterr()

    response = await client.post(
        "/api/v1/communities/",
        headers=get_auth_headers(user),
        json={"name": "Fresh guild"},
    )
    assert response.status_code == 201, response.text
    guild_id = response.json()["id"]

    (row,) = emitted(capfd, AuditEventType.PLUGIN_INSTALLED)
    assert row["actor_user_id"] == user_id
    assert row["guild_id"] == guild_id
    assert row["target"]["type"] == "plugin"
    assert row["target"]["id"] is not None
    assert row["detail"] == {
        "listing_uid": PROVIDED_UID,
        "version": "1.0.0",
        "via": "mandatory",
        "granted_scopes": [],
    }


async def test_the_boot_sweep_records_an_install_nobody_made(
    session: AsyncSession, mandatory_registration, capfd
):
    """The sweep routes into each guild without an account behind it, so the
    record names none — and the install is still recorded as provided."""
    creator = await create_user(session, email="audit-existing@example.com")
    guild = await create_guild(session, creator=creator, name="Existing guild")
    guild_id = guild.id
    await create_guild_membership(
        session, user=creator, guild=guild, role=CommunityRole.admin
    )
    capfd.readouterr()

    result = await backfill_mandatory_plugins()
    assert (result.installed, result.failed) == (1, 0)

    (row,) = emitted(capfd, AuditEventType.PLUGIN_INSTALLED)
    assert row["actor_user_id"] is None
    assert row["guild_id"] == guild_id
    assert row["detail"] == {
        "listing_uid": PROVIDED_UID,
        "version": "1.0.0",
        "via": "mandatory",
        "granted_scopes": [],
    }
