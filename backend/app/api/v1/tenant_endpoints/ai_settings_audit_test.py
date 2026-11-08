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
    owner = await acting_user()
    owner_id = owner.user.id
    capfd.readouterr()

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


async def test_setting_the_mode_it_is_already_on_records_nothing(
    client, acting_user, capfd
):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    capfd.readouterr()

    await _set_mode(client, owner, "platform")

    assert emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED) == []


# --- the operator's own connections ------------------------------------------


async def test_an_operator_connection_is_recorded_through_its_life(
    client, acting_user, capfd
):
    owner = await acting_user()
    owner_id = owner.user.id
    await _set_mode(client, owner, "platform")
    capfd.readouterr()

    created = await client.post(
        PLATFORM_CONNS, headers=owner.headers, json=_shared_key("Company OpenAI")
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]

    disabled = await client.put(
        f"{PLATFORM_CONNS}/{connection_id}",
        headers=owner.headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    gone = await client.delete(
        f"{PLATFORM_CONNS}/{connection_id}", headers=owner.headers
    )
    assert gone.status_code == 204, gone.text

    envelopes = emitted(capfd)
    for event in (
        AuditEventType.AI_CONNECTION_CREATED,
        AuditEventType.AI_CONNECTION_UPDATED,
        AuditEventType.AI_CONNECTION_DELETED,
    ):
        rows = _of(envelopes, event)
        assert [(r["actor_user_id"], r["guild_id"], r["target"]) for r in rows] == [
            (owner_id, None, {"type": "ai_connection", "id": connection_id})
        ], event
        assert rows[0]["detail"]["scope"] == "platform"

    born = _of(envelopes, AuditEventType.AI_CONNECTION_CREATED)[0]
    assert born["detail"]["secret_changed"] is True
    assert {"label", "provider", "model", "enabled"} <= set(born["detail"]["changed"])
    # The label, the provider and the model name it; only the switches carry a
    # value.
    assert set(born["detail"]["values"]) == {"enabled", "is_default", "community_ids"}

    moved = _of(envelopes, AuditEventType.AI_CONNECTION_UPDATED)[0]
    assert moved["detail"]["changed"] == ["enabled"]
    assert moved["detail"]["secret_changed"] is False


async def test_no_record_of_a_connection_carries_its_key(client, acting_user, capfd):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    capfd.readouterr()

    created = await client.post(
        PLATFORM_CONNS, headers=owner.headers, json=_shared_key("Company OpenAI")
    )
    assert created.status_code == 200, created.text
    rotated = await client.put(
        f"{PLATFORM_CONNS}/{created.json()['id']}",
        headers=owner.headers,
        json={"api_key": API_KEY},
    )
    assert rotated.status_code == 200, rotated.text

    written = emitted(capfd)
    envelopes = [
        envelope
        for event in (
            AuditEventType.AI_CONNECTION_CREATED,
            AuditEventType.AI_CONNECTION_UPDATED,
        )
        for envelope in _of(written, event)
    ]
    assert envelopes
    for envelope in envelopes:
        assert API_KEY not in json.dumps(envelope)


# --- a community's own connections -------------------------------------------


async def test_a_community_connection_is_recorded_against_its_community(
    client, acting_user, capfd
):
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    seat_id, guild_id = seat.user.id, seat.guild.id
    capfd.readouterr()

    created = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json=_shared_key("Team OpenAI"),
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]

    renamed = await client.put(
        seat.g(f"/settings/ai/connections/{connection_id}"),
        headers=seat.headers,
        json={"enabled": False},
    )
    assert renamed.status_code == 200, renamed.text
    gone = await client.delete(
        seat.g(f"/settings/ai/connections/{connection_id}"), headers=seat.headers
    )
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


async def test_a_community_connection_edit_that_changes_nothing_records_nothing(
    client, acting_user, capfd
):
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)

    created = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json=_shared_key("Team OpenAI"),
    )
    assert created.status_code == 200, created.text
    capfd.readouterr()

    same = await client.put(
        seat.g(f"/settings/ai/connections/{created.json()['id']}"),
        headers=seat.headers,
        json={"enabled": True},
    )
    assert same.status_code == 200, same.text

    assert emitted(capfd, AuditEventType.AI_CONNECTION_UPDATED) == []


async def test_a_refused_connection_write_records_nothing(client, acting_user, capfd):
    """Running a community is not the seat that connects it to a provider."""
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    capfd.readouterr()

    refused = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json=_shared_key("Not theirs"),
    )
    assert refused.status_code == 403, refused.text

    assert emitted(capfd, AuditEventType.AI_CONNECTION_CREATED) == []
