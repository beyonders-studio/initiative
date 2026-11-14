"""Billing's change log (``app.services.platform.billing_changes``).

Pinned:

* the facts are written by the transactions that change them, and only
  where billing manages plans: a community made (with its name and its
  owner, who is the first superadmin even when staff made it), renamed,
  deleted, restored, suspended, unsuspended and purged; its member and guest
  counts; its stored bytes;
* every row names the community by billing's reference, and a purge's
  reference is the one it had;
* the cursor never skips a row that commits late, and an aborted
  transaction holds nothing up;
* no request role can write a row.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityStatus, Guild
from app.models.platform.identity_ref import IdentityEntity
from app.services.platform import billing_changes
from app.services.platform import guilds as guilds_service
from app.services.platform.identity_refs import billing_ref
from app.testing import (
    create_guest,
    create_guild,
    create_guild_membership,
    create_user,
)
from app.testing.billing_boundary import change_kinds, change_rows, served_changes
from app.testing.billing_managed import billing_manages_plans


async def _set_status(session: AsyncSession, guild_id: int, status: CommunityStatus):
    session.expire_all()
    guild = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    guild.status = status.value
    session.add(guild)
    await session.commit()


async def test_nothing_is_written_unless_billing_manages_plans(session: AsyncSession):
    guild = await create_guild(session)
    assert await change_rows(session, guild.id) == []


async def test_a_communitys_lifecycle_is_served_in_order_by_reference(
    session: AsyncSession,
):
    staff = await create_user(session, email="staff@example.com")
    owner = await create_user(session, email="owner@example.com")
    owner_id = owner.id
    async with billing_manages_plans(session):
        guild = await guilds_service.provision_new_guild(
            session, name="Acme", description=None, creator=staff, owner=owner
        )
        await session.commit()
        guild_id = guild.id
        await _set_status(session, guild_id, CommunityStatus.suspended)
        await _set_status(session, guild_id, CommunityStatus.active)
        await _set_status(session, guild_id, CommunityStatus.deleted)
        await _set_status(session, guild_id, CommunityStatus.active)
        session.expire_all()
        renamed = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
        renamed.name = "Acme Club"
        session.add(renamed)
        await session.commit()

        served, _cursor = await served_changes()

    ref = await billing_ref(IdentityEntity.guild, guild_id)
    mine = [c for c in served if c["community_ref"] == ref]
    assert [
        c["kind"] for c in mine if not c["kind"].startswith("community.members")
    ] == [
        "community.created",
        "community.suspended",
        "community.unsuspended",
        "community.deleted",
        "community.restored",
        "community.renamed",
    ]
    created = mine[0]
    # The community is for the owner, whoever made it.
    assert created["owner_user_ref"] == await billing_ref(IdentityEntity.user, owner_id)
    assert created["name"] == "Acme"
    assert "owner_user_id" not in created
    assert [c["name"] for c in mine if c["kind"] == "community.renamed"] == [
        "Acme Club"
    ]
    assert len({c["id"] for c in mine}) == len(mine)


async def test_members_and_guests_are_totals_counted_as_served(session: AsyncSession):
    """Counted when the page is read, so every change for the community says
    what it holds now: two joins in flight can't each report only their own."""
    guild = await create_guild(session)
    guild_id = guild.id
    ref = await billing_ref(IdentityEntity.guild, guild_id)
    async with billing_manages_plans(session):
        member = await create_user(session)
        await create_guild_membership(session, user=member, guild=guild)
        await create_guest(session, guild=guild)
        await session.commit()
        written = await change_rows(session, guild_id, kinds=("community.members",))
        served, _ = await served_changes()

    assert len(written) >= 2 and all(data == {} for _kind, data in written)
    counts = [
        (c["members"], c["guests"])
        for c in served
        if c["kind"] == "community.members" and c["community_ref"] == ref
    ]
    assert len(counts) == len(written)
    assert set(counts) == {(1, 1)}


async def test_a_purge_is_served_under_the_reference_it_had(session: AsyncSession):
    guild = await create_guild(session)
    guild_id = guild.id
    ref = await billing_ref(IdentityEntity.guild, guild_id)
    async with billing_manages_plans(session):
        await session.exec(
            text("DELETE FROM public.guilds WHERE id = :g"), params={"g": guild_id}
        )
        await session.commit()
        served, _ = await served_changes()

    assert [
        (c["kind"], c["community_ref"])
        for c in served
        if c["kind"] == "community.purged"
    ] == [("community.purged", ref)]


async def test_a_community_billing_never_knew_is_not_served_once_gone(
    session: AsyncSession,
):
    maker = await create_user(session)
    async with billing_manages_plans(session):
        guild = await guilds_service.provision_new_guild(
            session, name="Gone", description=None, creator=maker
        )
        await session.commit()
        guild_id = guild.id
        await session.exec(
            text("DELETE FROM public.guilds WHERE id = :g"), params={"g": guild_id}
        )
        await session.commit()
        assert await change_kinds(session, guild_id) == [
            "community.created",
            "community.purged",
        ]
        served, _ = await served_changes()

    assert [c for c in served if c["kind"].startswith("community.")] == []


async def test_stored_bytes_are_reported_as_a_total(session: AsyncSession, monkeypatch):
    monkeypatch.setattr(billing_changes, "STORAGE_WINDOW_SECONDS", 0)
    guild = await create_guild(session)
    guild_id = guild.id
    async with billing_manages_plans(session):
        await billing_changes._report_storage(guild_id)
        rows = await change_rows(session, guild_id, kinds=("community.storage",))

    assert rows == [("community.storage", {"bytes": 0})]


async def _write(conn, guild_id: int, kind: str) -> None:
    await conn.execute(
        text("SELECT public.billing_change_row(:g, :k, CAST(:d AS jsonb))"),
        {"g": guild_id, "k": kind, "d": json.dumps({"n": kind})},
    )


async def test_a_late_commit_is_never_skipped(session: AsyncSession, engine):
    guild = await create_guild(session)
    guild_id = guild.id
    await billing_ref(IdentityEntity.guild, guild_id)
    async with billing_manages_plans(session):
        async with engine.connect() as early, engine.connect() as late:
            early_txn = await early.begin()
            await _write(early, guild_id, "test.early")
            async with late.begin():
                await _write(late, guild_id, "test.late")
            # The later transaction has committed, but one older than it is
            # still open: nothing past the older one's start is served yet.
            served, cursor = await billing_changes.page(None, 500)
            assert [c["kind"] for c in served if c["kind"].startswith("test.")] == []
            await early_txn.commit()
        served, cursor = await served_changes(cursor)
        assert [c["kind"] for c in served if c["kind"].startswith("test.")] == [
            "test.early",
            "test.late",
        ]
        assert await served_changes(cursor) == ([], cursor)


async def test_an_aborted_transaction_holds_nothing_up(session: AsyncSession, engine):
    guild = await create_guild(session)
    guild_id = guild.id
    await billing_ref(IdentityEntity.guild, guild_id)
    async with billing_manages_plans(session):
        async with engine.connect() as aborted:
            txn = await aborted.begin()
            await _write(aborted, guild_id, "test.aborted")
            await txn.rollback()
        async with engine.connect() as later, later.begin():
            await _write(later, guild_id, "test.later")
        served, _ = await served_changes()

    assert [c["kind"] for c in served if c["kind"].startswith("test.")] == [
        "test.later"
    ]


async def test_a_cursor_that_was_not_handed_out_is_refused():
    with pytest.raises(billing_changes.CursorInvalid):
        await billing_changes.page("not-a-cursor", 10)


@pytest.mark.parametrize("role", ["app_user", "app_admin"])
async def test_no_role_writes_a_row_directly(role_session, role):
    s = await role_session(role)
    with pytest.raises(DBAPIError):
        await s.exec(
            text(
                "INSERT INTO public.billing_changes (xid, guild_id, kind)"
                " VALUES (1, 1, 'community.purged')"
            )
        )
    await s.rollback()


async def test_a_request_role_cannot_call_the_writer(role_session):
    s = await role_session("app_user")
    with pytest.raises(DBAPIError):
        await s.exec(
            text("SELECT public.billing_change_row(1, 'community.purged', NULL)")
        )
    await s.rollback()
