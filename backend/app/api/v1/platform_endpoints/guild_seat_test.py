"""The guild's top seat: who gets it, and who Postgres lets write as it."""

import pytest
from sqlalchemy import func
from sqlmodel import select
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)
from app.testing import route_as
from app.db.request_context import Platform


async def test_whoever_makes_a_community_holds_its_seat(
    client: AsyncClient, session: AsyncSession
):
    """Starting a community means holding all of it, billing and sign-in
    included — and there is somebody to pass the seat to only because the
    first person has it."""
    founder = await create_user(session)

    created = await client.post(
        "/api/v1/communities/",
        headers=get_auth_headers(founder),
        json={"name": "Founders"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "superadmin"


async def test_the_seat_is_read_from_postgres_not_from_the_enum(
    session: AsyncSession,
):
    """The app asks ``public.guild_superadmin`` rather than comparing a Python
    value, so the endpoint and the policies cannot drift apart."""
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await session.commit()

    for user, expected in ((seat, True), (admin, False)):
        await set_rls_context(session, Platform(user_id=int(user.id)))
        held = (
            await session.exec(
                select(func.guild_superadmin(int(guild.id), int(user.id)))
            )
        ).one()
        assert held is expected


async def test_postgres_refuses_the_write_to_anyone_but_the_seat(
    session: AsyncSession, role_session
):
    """The rule stands on its own, with no endpoint in front of it.

    Both members are routed into the guild exactly as a request would be, and
    the same INSERT is attempted as each. Twice over: the seat holder's
    ordinary routing is refused like the admin's — holding the seat is not
    using it — and the same person on the seat's own route writes.
    """
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await session.commit()

    insert = text(
        "INSERT INTO public.community_rules (guild_id, key, enabled, updated_at) "
        "VALUES (:g, 'allow_ai', false, now())"
    )
    # The request path's own login role, not the superuser the setup above
    # runs as — this is the boundary under test.
    writer = await role_session("app_user")

    await route_as(writer, user_id=int(admin.id), guild_id=int(guild.id))
    with pytest.raises(DBAPIError):
        await writer.exec(insert.bindparams(g=int(guild.id)))
    await writer.rollback()

    # The seat holder, on the routing an ordinary request gets.
    await route_as(writer, user_id=int(seat.id), guild_id=int(guild.id))
    with pytest.raises(DBAPIError):
        await writer.exec(insert.bindparams(g=int(guild.id)))
    await writer.rollback()

    # And on the one the configuration routes ask for.
    await route_as(writer, user_id=int(seat.id), guild_id=int(guild.id), seat=True)
    await writer.exec(insert.bindparams(g=int(guild.id)))
    await writer.rollback()

    # Asking is not enough either: the admin gets the ordinary routing back.
    await route_as(writer, user_id=int(admin.id), guild_id=int(guild.id), seat=True)
    with pytest.raises(DBAPIError):
        await writer.exec(insert.bindparams(g=int(guild.id)))
    await writer.rollback()


async def test_billing_is_the_seats_too(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """What a community pays for goes with its sign-in, not with running it."""
    # A deployment with no portal answers 404 before it asks who is calling,
    # so there has to be one for the question to be reached at all.
    from app.core.config import settings

    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example")
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await session.commit()

    refused = await client.post(
        f"/api/v1/communities/{guild.id}/billing/handoff",
        headers=get_auth_headers(admin),
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_SUPERADMIN_REQUIRED"

    # The seat gets past the gate; whether a portal is configured is the
    # deployment's business and the next thing the endpoint checks.
    allowed = await client.post(
        f"/api/v1/communities/{guild.id}/billing/handoff",
        headers=get_auth_headers(seat),
    )
    assert allowed.status_code != 403, allowed.text


async def test_the_seat_deletes_the_community_and_then_itself(
    client: AsyncClient, session: AsyncSession
):
    """The block is a fork in the road, not a dead end.

    Holding a community's only seat stops an account closing, and the way
    through is to delete the community — which the seat may do. Two deliberate
    acts rather than one, which is the point of refusing the first.
    """
    seat = await create_user(session)
    guild = await create_guild(session, name="Winding Down", creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=await create_user(session), guild=guild, role=CommunityRole.member
    )
    await session.commit()
    headers = get_auth_headers(seat)

    eligibility = await client.get("/api/v1/me/deletion-eligibility", headers=headers)
    assert eligibility.status_code == 200, eligibility.text
    assert eligibility.json()["can_delete"] is False
    assert eligibility.json()["sole_superadmin_communities"] == ["Winding Down"]

    refused = await client.post(
        "/api/v1/me/delete-account",
        headers=headers,
        json={
            "action": "deactivate",
            "password": "testpassword123",
            "confirmation_text": "DEACTIVATE MY ACCOUNT",
        },
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"

    # The seat's own way through: delete the community.
    deleted = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=headers,
        json={
            "password": "testpassword123",
            "confirmation_text": f"DELETE COMMUNITY {guild.name.upper()}",
        },
    )
    assert deleted.status_code == 204, deleted.text

    # And now nothing is in the way.
    after = await client.get("/api/v1/me/deletion-eligibility", headers=headers)
    assert after.json()["can_delete"] is True
