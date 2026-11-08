import httpx
import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.guild import CommunityRole
from app.services.platform import billing_ping
from app.testing.billing_boundary import configure_outbound
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)

_ANSWER = billing_ping.PlanSummary.model_validate(
    {
        "tier_name": "Gold",
        "trial_ends_on": "2026-10-08",
        "renews_on": None,
        "next_charge": {"total": 1250, "currency": "USD"},
        "scheduled_change": None,
        "payment_failed": False,
        "can_upgrade": False,
        "can_cancel": True,
    },
    strict=False,
)


@pytest.fixture
def billing_answers(monkeypatch):
    """What billing answers, settable per test; the guilds it was asked about."""
    state: dict = {"answer": _ANSWER, "asked": []}

    async def _plan_summary(guild_id: int):
        state["asked"].append(guild_id)
        return state["answer"]

    monkeypatch.setattr(billing_ping, "guild_plan_summary", _plan_summary)
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example")
    return state


async def _guild_with_seat(session: AsyncSession):
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    member = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    await session.commit()
    return guild, seat, admin, member


def _url(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/billing/summary"


async def test_the_seat_gets_billings_answer(
    client: AsyncClient, session: AsyncSession, billing_answers
):
    guild, seat, _, _ = await _guild_with_seat(session)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": True,
        "tier_name": "Gold",
        "trial_ends_on": "2026-10-08",
        "renews_on": None,
        "next_charge": {"total": 1250, "currency": "USD"},
        "scheduled_change": None,
        "payment_failed": False,
        "can_upgrade": False,
        "can_cancel": True,
    }
    assert billing_answers["asked"] == [guild.id]


@pytest.mark.parametrize("who", ["admin", "member"])
async def test_only_the_seat_may_ask(
    client: AsyncClient, session: AsyncSession, billing_answers, who
):
    guild, _, admin, member = await _guild_with_seat(session)
    caller = admin if who == "admin" else member
    response = await client.get(_url(guild.id), headers=get_auth_headers(caller))
    assert response.status_code == 403
    assert billing_answers["asked"] == []


async def test_no_portal_is_not_found(
    client: AsyncClient, session: AsyncSession, billing_answers, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", "")
    guild, seat, _, _ = await _guild_with_seat(session)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 404
    assert billing_answers["asked"] == []


async def test_billing_without_an_answer_is_unavailable(
    client: AsyncClient, session: AsyncSession, billing_answers
):
    """Down, unreachable or malformed all reach here as ``None``."""
    billing_answers["answer"] = None
    guild, seat, _, _ = await _guild_with_seat(session)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": False,
        "tier_name": None,
        "trial_ends_on": None,
        "renews_on": None,
        "next_charge": None,
        "scheduled_change": None,
        "payment_failed": False,
        "can_upgrade": False,
        "can_cancel": False,
    }


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("down")


@pytest.mark.parametrize(
    "handler",
    [
        _down,
        lambda request: httpx.Response(503, json={"detail": "maintenance"}),
        lambda request: httpx.Response(200, json={"payment_failed": "yes"}),
        lambda request: httpx.Response(200, json={"renews_on": "soon"}),
        lambda request: httpx.Response(200, content=b"<html>gateway</html>"),
    ],
)
async def test_billing_down_or_malformed_is_unavailable_end_to_end(
    client: AsyncClient, session: AsyncSession, monkeypatch, handler
):
    """Through the real outbound call: billing unreachable, or its answer
    refused."""
    real_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    async def _known_ref(**kwargs):
        return "gbil_known"

    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example")
    configure_outbound(monkeypatch, "https://billing.internal")
    monkeypatch.setattr(billing_ping, "existing_ref", _known_ref)
    monkeypatch.setattr(billing_ping.httpx, "AsyncClient", _client)
    guild, seat, _, _ = await _guild_with_seat(session)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 200, response.text
    assert response.json()["available"] is False
