"""Guild lifecycle wires schema-per-guild provisioning.

Creating a guild provisions its `guild_<id>` schema + role. Deleting one no
longer drops them — the community is retained for the restore window, and the
purge worker is what eventually drops them. The `client` fixture points the
provisioning engine at the test DB and cleans up any schemas/roles created.
"""

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.v1.platform_endpoints.guilds as guilds_endpoint
from app.db import post_commit
from app.db.schema_provisioning import guild_role_name, guild_schema_name
from app.models.platform.guild import Guild, CommunityStatus
from app.core.rules import DEFAULT_GUILD_RETENTION_DAYS
from app.services.platform import guild_purge
from app.testing.factories import (
    create_user,
    get_auth_headers,
)


#: A fresh test database carries the shipped window.
RETENTION = DEFAULT_GUILD_RETENTION_DAYS


async def _schema_exists(engine: AsyncEngine, schema: str) -> bool:
    async with engine.connect() as conn:
        return (
            await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": schema},
            )
        ) == 1


async def _role_exists(engine: AsyncEngine, role: str) -> bool:
    async with engine.connect() as conn:
        return (
            await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
        ) == 1


async def test_create_guild_provisions_schema_and_role(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine
):
    user = await create_user(session, email="prov-create@example.com")
    headers = get_auth_headers(user)

    resp = await client.post(
        "/api/v1/communities/", headers=headers, json={"name": "Prov Guild"}
    )
    assert resp.status_code == 201
    gid = resp.json()["id"]
    schema = guild_schema_name(gid)

    assert await _schema_exists(engine, schema)
    assert await _role_exists(engine, guild_role_name(gid))
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text(f"SELECT to_regclass('{schema}.tasks')")) is not None
        )


async def test_delete_guild_keeps_the_schema_until_the_purge(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine
):
    """Deleting keeps everything; the purge is what destroys it.

    The whole point of the retention window is that the community is still
    there to restore, so the schema and role have to survive the delete and go
    only when the window has run out.
    """
    user = await create_user(session, email="prov-delete@example.com")
    headers = get_auth_headers(user)

    resp = await client.post(
        "/api/v1/communities/", headers=headers, json={"name": "Del Prov"}
    )
    gid = resp.json()["id"]
    schema, role = guild_schema_name(gid), guild_role_name(gid)
    assert await _schema_exists(engine, schema), "precondition: schema provisioned"

    resp = await client.request(
        "DELETE",
        f"/api/v1/communities/{gid}",
        headers=headers,
        json={
            "password": "testpassword123",
            "confirmation_text": "DELETE COMMUNITY DEL PROV",
        },
    )
    assert resp.status_code == 204
    # The deletion arms the community's plug-in hook timer once it commits, on
    # a task of its own that holds the guild row while it writes. A purge
    # claims the row SKIP LOCKED, so it waits for that work to finish.
    await post_commit.settle_all()

    guild = (await session.exec(select(Guild).where(Guild.id == gid))).one()
    assert guild.status == CommunityStatus.deleted.value
    assert await _schema_exists(engine, schema), "retained for the restore window"
    assert await _role_exists(engine, role)

    # A day short of the window: still nothing to do.
    session.expunge_all()
    deleted_at = guild.status_changed_at
    assert deleted_at is not None
    assert (
        await guild_purge.purge_due_guilds(
            session, now=(deleted_at + timedelta(days=RETENTION)) - timedelta(days=1)
        )
        == 0
    )
    assert await _schema_exists(engine, schema)

    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session,
            now=(deleted_at + timedelta(days=RETENTION)) + timedelta(seconds=1),
        )
        == 1
    )
    assert (await session.exec(select(Guild).where(Guild.id == gid))).all() == []
    assert not await _schema_exists(engine, schema)
    assert not await _role_exists(engine, role)


async def test_create_guild_rolls_back_when_provisioning_fails(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """If provisioning fails, the guild is rolled back (no orphaned row)."""

    async def boom(*args, **kwargs):
        raise RuntimeError("provisioning failed")

    # Provisioning + schema seeding now run inside the service helper.
    monkeypatch.setattr(guilds_endpoint.guilds_service, "seed_guild_content", boom)

    user = await create_user(session, email="rollback@example.com")
    headers = get_auth_headers(user)
    resp = await client.post(
        "/api/v1/communities/", headers=headers, json={"name": "Rollback Guild"}
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "COMMUNITY_PROVISION_FAILED"
    remaining = (
        await session.exec(select(Guild).where(Guild.name == "Rollback Guild"))
    ).all()
    assert remaining == [], "guild row must be rolled back when provisioning fails"


async def test_purge_succeeds_even_if_deprovision_fails(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine, monkeypatch
):
    """The guild row is deleted FIRST (the guild is gone from the app), then the
    schema is dropped. A deprovision failure must NOT fail the purge — the row
    is already gone — and the schema it leaves is reclaimed on the next pass,
    while a live guild's schema is left alone."""
    user = await create_user(session, email="deprov-fail@example.com")
    headers = get_auth_headers(user)
    resp = await client.post(
        "/api/v1/communities/", headers=headers, json={"name": "Teardown Fail"}
    )
    gid = resp.json()["id"]

    resp = await client.request(
        "DELETE",
        f"/api/v1/communities/{gid}",
        headers=headers,
        json={
            "password": "testpassword123",
            "confirmation_text": "DELETE COMMUNITY TEARDOWN FAIL",
        },
    )
    assert resp.status_code == 204
    await post_commit.settle_all()

    async def boom(_guild_id):
        raise RuntimeError("deprovisioning failed")

    deprovision_guild = guild_purge.deprovision_guild
    monkeypatch.setattr(guild_purge, "deprovision_guild", boom)
    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session, now=datetime.now(timezone.utc) + timedelta(days=91)
        )
        == 1
    )

    remaining = (await session.exec(select(Guild).where(Guild.id == gid))).all()
    assert remaining == [], "guild row is deleted even when schema cleanup fails"
    assert await _schema_exists(engine, guild_schema_name(gid))

    resp = await client.post(
        "/api/v1/communities/", headers=headers, json={"name": "Still Here"}
    )
    live_gid = resp.json()["id"]

    monkeypatch.setattr(guild_purge, "deprovision_guild", deprovision_guild)
    assert await guild_purge.reclaim_orphaned_guilds(session) == 1
    assert not await _schema_exists(engine, guild_schema_name(gid))
    assert not await _role_exists(engine, guild_role_name(gid))
    assert await _schema_exists(engine, guild_schema_name(live_gid))
    assert await guild_purge.reclaim_orphaned_guilds(session) == 0
