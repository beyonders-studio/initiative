import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.guild import CommunityRole, CommunityStatus
from app.services.platform import billing_ping
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


@pytest.fixture
def asked(monkeypatch):
    calls: list[int] = []

    async def _payment_failed(guild_id: int) -> bool:
        calls.append(guild_id)
        return True

    monkeypatch.setattr(billing_ping, "guild_payment_failed", _payment_failed)
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example")
    return calls


async def _guild_with_seat(session: AsyncSession, status: CommunityStatus):
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    guild.status = status.value
    session.add(guild)
    await session.commit()
    return guild, seat, admin


def _url(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/billing/payment-issue"


async def test_only_the_seat_may_ask(client: AsyncClient, session: AsyncSession, asked):
    guild, _, admin = await _guild_with_seat(session, CommunityStatus.read_only)
    response = await client.get(_url(guild.id), headers=get_auth_headers(admin))
    assert response.status_code == 403
    assert asked == []


async def test_the_seat_of_a_read_only_guild_gets_the_answer(
    client: AsyncClient, session: AsyncSession, asked
):
    guild, seat, _ = await _guild_with_seat(session, CommunityStatus.read_only)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 200, response.text
    assert response.json() == {"payment_failed": True}
    assert asked == [guild.id]


async def test_the_seat_of_a_suspended_guild_is_refused(
    client: AsyncClient, session: AsyncSession, asked
):
    guild, seat, _ = await _guild_with_seat(session, CommunityStatus.suspended)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 403, response.text
    assert asked == []


async def test_an_active_guild_is_never_asked_about(
    client: AsyncClient, session: AsyncSession, asked
):
    guild, seat, _ = await _guild_with_seat(session, CommunityStatus.active)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.json() == {"payment_failed": False}
    assert asked == []


async def test_no_portal_is_never_asked_about(
    client: AsyncClient, session: AsyncSession, asked, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", "")
    guild, seat, _ = await _guild_with_seat(session, CommunityStatus.read_only)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.json() == {"payment_failed": False}
    assert asked == []
