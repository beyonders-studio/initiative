"""Webhook subscriptions in the audit log.

A subscription is a standing instruction to send a community's changes
somewhere outside it, so registering, rewriting and removing one are all worth
writing down. What the record carries is bounded by the same rule the
subscription itself lives under: the host it points at, never the path, the
query or the signing secret.
"""

import json
import socket
from contextlib import contextmanager
from unittest.mock import patch

from httpx2 import AsyncClient

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import emitted

_WEBHOOK_HOST = "hooks.example.com"
_TARGET_URL = f"https://{_WEBHOOK_HOST}/in/secret-path"
# A public unicast IPv4 (example.com) with a real stream socket type/proto, so
# constructing a socket from the tuple is valid.
_FAKE_INFOS = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
]


@contextmanager
def _mock_public_dns():
    """Resolve the webhook host to a fixed public IP without hitting the network.

    Scoped to the webhook host: the patch target is the shared ``socket``
    module, and a blanket answer would also field asyncpg's own lookup for the
    database host mid-request.
    """
    real_getaddrinfo = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == _WEBHOOK_HOST:
            return _FAKE_INFOS
        return real_getaddrinfo(host, *args, **kwargs)

    with patch("app.services.webhook_target_url.socket.getaddrinfo", side_effect=fake):
        yield


def _url(guild_id: int, suffix: str = "") -> str:
    return f"/api/v1/c/{guild_id}/webhooks/subscriptions{suffix}"


def _body(**overrides) -> dict:
    return {
        "target_url": _TARGET_URL,
        "event_types": ["tasks.created"],
        **overrides,
    }


async def _create(client: AsyncClient, actor) -> dict:
    with _mock_public_dns():
        response = await client.post(
            _url(actor.guild.id),
            json=_body(initiative_id=actor.initiative.id),
            headers=actor.headers,
        )
    assert response.status_code == 201, response.text
    return response.json()


async def test_registering_records_the_host_and_never_the_rest_of_the_url(
    client: AsyncClient, acting_user, capfd
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    capfd.readouterr()
    created = await _create(client, a)

    (row,) = emitted(capfd, AuditEventType.WEBHOOK_CREATED)
    assert row["actor_user_id"] == a.user.id
    assert row["guild_id"] == a.guild.id
    assert row["target"] == {
        "type": "webhook_subscription",
        "id": created["id"],
    }
    assert row["detail"] == {
        "target_host": _WEBHOOK_HOST,
        "event_types": ["tasks.created"],
        "plugin_install_id": None,
    }
    # The whole envelope, not just the key somebody remembered to leave out.
    assert "secret-path" not in json.dumps(row)
    assert created["hmac_secret"] not in json.dumps(row)


async def test_a_refused_registration_records_nothing(
    client: AsyncClient, acting_user, capfd
):
    """Nothing was registered, so there is nothing to write down."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    capfd.readouterr()

    with _mock_public_dns():
        response = await client.post(
            _url(a.guild.id),
            json=_body(initiative_id=a.initiative.id, event_types=["taks.updated"]),
            headers=a.headers,
        )
    assert response.status_code == 400

    assert emitted(capfd, AuditEventType.WEBHOOK_CREATED) == []


async def test_a_rewrite_records_which_fields_moved(
    client: AsyncClient, acting_user, capfd
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, a)
    capfd.readouterr()

    response = await client.patch(
        _url(a.guild.id, f"/{created['id']}"),
        json={"active": False},
        headers=a.headers,
    )
    assert response.status_code == 200, response.text

    (row,) = emitted(capfd, AuditEventType.WEBHOOK_UPDATED)
    assert row["actor_user_id"] == a.user.id
    assert row["guild_id"] == a.guild.id
    assert row["target"] == {
        "type": "webhook_subscription",
        "id": created["id"],
    }
    assert row["detail"] == {
        "changed": ["active"],
        "values": {"active": {"from": True, "to": False}},
        "target_host_changed": False,
    }


async def test_a_rewrite_that_moves_nothing_records_nothing(
    client: AsyncClient, acting_user, capfd
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, a)
    capfd.readouterr()

    response = await client.patch(
        _url(a.guild.id, f"/{created['id']}"),
        json={"active": True, "event_types": ["tasks.created"]},
        headers=a.headers,
    )
    assert response.status_code == 200, response.text

    assert emitted(capfd, AuditEventType.WEBHOOK_UPDATED) == []


async def test_removing_one_records_where_it_had_been_pointing(
    client: AsyncClient, acting_user, capfd
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, a)
    capfd.readouterr()

    response = await client.delete(
        _url(a.guild.id, f"/{created['id']}"), headers=a.headers
    )
    assert response.status_code == 204, response.text

    (row,) = emitted(capfd, AuditEventType.WEBHOOK_DELETED)
    assert row["actor_user_id"] == a.user.id
    assert row["guild_id"] == a.guild.id
    assert row["target"] == {
        "type": "webhook_subscription",
        "id": created["id"],
    }
    assert row["detail"] == {
        "target_host": _WEBHOOK_HOST,
        "plugin_install_id": None,
    }
