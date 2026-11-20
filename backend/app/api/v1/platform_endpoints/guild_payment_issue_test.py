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


@pytest.mark.parametrize(
    "status,caller,portal,expected,answer",
    [
        pytest.param(
            CommunityStatus.read_only, "admin", True, 403, None, id="only the seat"
        ),
        pytest.param(
            CommunityStatus.read_only, "seat", True, 200, True, id="read-only seat"
        ),
        pytest.param(
            CommunityStatus.suspended, "seat", True, 403, None, id="suspended seat"
        ),
        pytest.param(
            CommunityStatus.active, "seat", True, 200, False, id="active is not asked"
        ),
        pytest.param(
            CommunityStatus.read_only, "seat", False, 200, False, id="no portal"
        ),
    ],
)
async def test_billing_is_asked_only_for_the_seat_of_a_read_only_guild(
    client: AsyncClient,
    session: AsyncSession,
    asked,
    monkeypatch,
    status: CommunityStatus,
    caller: str,
    portal: bool,
    expected: int,
    answer: bool | None,
):
    if not portal:
        monkeypatch.setattr(settings, "BILLING_URL", "")
    guild, seat, admin = await _guild_with_seat(session, status)
    headers = get_auth_headers(seat if caller == "seat" else admin)

    response = await client.get(_url(guild.id), headers=headers)

    assert response.status_code == expected, response.text
    if answer is not None:
        assert response.json() == {"payment_failed": answer}
    assert asked == ([guild.id] if answer else [])
