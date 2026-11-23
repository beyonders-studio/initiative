"""What connecting somewhere to an AI provider writes down.

A connection decides what leaves the deployment and for whom, at either level,
so both levels record the same event and say which in ``detail.scope``. The
key itself never appears — the record says it moved, and nothing more. The
global mode is an area of the deployment's settings row, and is recorded as
one.
"""

import json

import pytest

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.services import ai_settings as ai_settings_service
from app.testing.audit import emitted

PLATFORM_MODE = "/api/v1/settings/ai/platform/mode"
PLATFORM_CONNS = "/api/v1/settings/ai/platform/connections"
API_KEY = "sk-never-in-the-log"


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    """The platform config is cached in-process; drop it around each test so a
    mode or connection change never leaks into the next."""
    ai_settings_service.invalidate_platform_ai_cache()
    yield
    ai_settings_service.invalidate_platform_ai_cache()


async def _set_mode(client, actor, mode: str) -> None:
    response = await client.put(
        PLATFORM_MODE, headers=actor.headers, json={"mode": mode}
    )
    assert response.status_code == 200, response.text


def _shared_key(label: str) -> dict:
    """A connection with the operator's key."""
    return {
        "label": label,
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": API_KEY,
    }


def _of(envelopes: list[dict], event: AuditEventType) -> list[dict]:
    """The envelopes of one event type, out of a single read of the stream."""
    return [e for e in envelopes if e["event_type"] == event.value]


# --- the global mode ---------------------------------------------------------


async def test_changing_the_global_mode_is_an_area_of_the_settings_row(
    client, acting_user, capfd
):
    """Setting the mode it is already on records nothing."""
    owner = await acting_user()
    owner_id = owner.user.id
    capfd.readouterr()

    await _set_mode(client, owner, "platform")
    await _set_mode(client, owner, "platform")

    rows = emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED)
    assert [(r["actor_user_id"], r["guild_id"]) for r in rows] == [(owner_id, None)]
    detail = rows[0]["detail"]
    assert detail["area"] == "ai_mode"
    assert detail["changed"] == ["ai_config_mode"]
    # The mode is one of a fixed set, so its values ride along.
    assert detail["values"] == {
        "ai_config_mode": {"from": "disabled", "to": "platform"}
    }


# --- the operator's own connections ------------------------------------------


async def test_an_operator_connection_is_recorded_through_its_life(
    client, acting_user, capfd
):
    """No record of it carries its key, whether it was set at creation or
    rotated later."""
    owner = await acting_user()
    owner_id = owner.user.id
    await _set_mode(client, owner, "platform")
    capfd.readouterr()

    created = await client.post(
        PLATFORM_CONNS, headers=owner.headers, json=_shared_key("Company OpenAI")
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]
    url = f"{PLATFORM_CONNS}/{connection_id}"

    for change in ({"api_key": API_KEY}, {"enabled": False}):
        response = await client.put(url, headers=owner.headers, json=change)
        assert response.status_code == 200, response.text
    gone = await client.delete(url, headers=owner.headers)
    assert gone.status_code == 204, gone.text

    envelopes = emitted(capfd)
    target = (owner_id, None, {"type": "ai_connection", "id": connection_id})
    for event, count in (
        (AuditEventType.AI_CONNECTION_CREATED, 1),
        (AuditEventType.AI_CONNECTION_UPDATED, 2),
        (AuditEventType.AI_CONNECTION_DELETED, 1),
    ):
        rows = _of(envelopes, event)
        assert [(r["actor_user_id"], r["guild_id"], r["target"]) for r in rows] == [
            target
        ] * count, event
        assert {r["detail"]["scope"] for r in rows} == {"platform"}
        for row in rows:
            assert API_KEY not in json.dumps(row)

    born = _of(envelopes, AuditEventType.AI_CONNECTION_CREATED)[0]
    assert born["detail"]["secret_changed"] is True
    assert {"label", "provider", "model", "enabled"} <= set(born["detail"]["changed"])
    # The label, the provider and the model name it; only the switches carry a
    # value.
    assert set(born["detail"]["values"]) == {"enabled", "is_default", "community_ids"}

    moved = _of(envelopes, AuditEventType.AI_CONNECTION_UPDATED)[1]
    assert moved["detail"]["changed"] == ["enabled"]
    assert moved["detail"]["secret_changed"] is False


# --- a community's own connections -------------------------------------------


async def test_a_community_connection_is_recorded_against_its_community(
    client, acting_user, capfd
):
    """Running a community is not the seat that connects it to a provider, so
    an admin's write is refused and records nothing; an edit that changes
    nothing records nothing either."""
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)
    seat_id, guild_id = seat.user.id, seat.guild.id
    connections = seat.g("/settings/ai/connections")
    capfd.readouterr()

    refused = await client.post(
        connections, headers=admin.headers, json=_shared_key("Not theirs")
    )
    assert refused.status_code == 403, refused.text

    created = await client.post(
        connections, headers=seat.headers, json=_shared_key("Team OpenAI")
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]
    url = f"{connections}/{connection_id}"

    for change in ({"enabled": True}, {"enabled": False}):
        response = await client.put(url, headers=seat.headers, json=change)
        assert response.status_code == 200, response.text
    gone = await client.delete(url, headers=seat.headers)
    assert gone.status_code == 204, gone.text

    envelopes = emitted(capfd)
    for event in (
        AuditEventType.AI_CONNECTION_CREATED,
        AuditEventType.AI_CONNECTION_UPDATED,
        AuditEventType.AI_CONNECTION_DELETED,
    ):
        rows = _of(envelopes, event)
        assert [(r["actor_user_id"], r["guild_id"], r["target"]) for r in rows] == [
            (seat_id, guild_id, {"type": "ai_connection", "id": connection_id})
        ], event
        assert rows[0]["detail"]["scope"] == "community"
