"""A surface the deployment closes for one community: its seat's routes refuse,
its tables refuse the seat's writes, and what it set up stays, unused."""

import pytest
from sqlalchemy import text

from app.core.messages import GuildMessages
from app.core.rules import SURFACE_AI_CONNECTIONS, SetBy
from app.models.platform.guild import CommunityRole
from app.services import ai_settings as ai_settings_service
from app.services.platform import rules
from app.testing.routing import route_as


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    ai_settings_service.invalidate_platform_ai_cache()
    yield
    ai_settings_service.invalidate_platform_ai_cache()


async def _set(session, guild_id: int, key: str, is_open: bool) -> None:
    await rules.put(session, key, is_open, guild_id=guild_id, set_by=SetBy.deployment)
    await session.commit()


async def test_a_closed_ai_surface_refuses_its_seat_and_goes_unused(
    client, acting_user, session, role_session
):
    owner = await acting_user()
    mode = await client.put(
        "/api/v1/settings/ai/platform/mode",
        headers=owner.headers,
        json={"mode": "community"},
    )
    assert mode.status_code == 200, mode.text
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    made = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json={"label": "Ours", "provider": "openai", "model": "gpt-4o", "api_key": "k"},
    )
    assert made.status_code == 200, made.text

    async def resolved() -> bool:
        response = await client.get(
            seat.g("/settings/ai/resolved"), headers=seat.headers
        )
        assert response.status_code == 200, response.text
        return response.json()["enabled"]

    assert await resolved() is True

    await _set(session, seat.guild.id, SURFACE_AI_CONNECTIONS, False)
    refused = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json={"label": "More", "provider": "openai", "model": "gpt-4o"},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == GuildMessages.COMMUNITY_SURFACE_CLOSED
    assert await resolved() is False

    s = await role_session("app_user")
    await route_as(s, user_id=seat.user.id, guild_id=seat.guild.id, seat=True)
    changed = await s.exec(text("UPDATE guild_ai_connections SET label = 'Renamed'"))
    assert changed.rowcount == 0
    await s.rollback()

    await _set(session, seat.guild.id, SURFACE_AI_CONNECTIONS, True)
    assert await resolved() is True


async def test_the_operator_closes_the_plugin_surface_and_its_seat_is_refused(
    client, acting_user
):
    operator = await acting_user("operator")
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    closed = await client.patch(
        f"/api/v1/settings/communities/{seat.guild.id}",
        headers=operator.headers,
        json={"plugins_open": False},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["plugins_open"] is False
    assert closed.json()["ai_connections_open"] is True

    refused = await client.patch(
        seat.g("/plugins/999999"), headers=seat.headers, json={}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == GuildMessages.COMMUNITY_SURFACE_CLOSED
