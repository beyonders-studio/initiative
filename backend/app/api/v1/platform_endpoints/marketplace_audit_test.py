"""What re-reading the catalogue writes down.

An operator deciding what this deployment carries is deployment configuration,
so the rescan is recorded with the counts it moved — which source, and what was
published, withdrawn and skipped. A refused scan moved nothing and records
nothing.
"""

from __future__ import annotations

import json

import pytest

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.testing import emitted

RESCAN_URL = "/api/v1/marketplace/operator-catalog/rescan"


def _manifest() -> dict:
    return {
        "uid": "0PRT0R00000002",
        "public_id": "acme.standup",
        "kind": "dashboard",
        "name": "Standup board",
        "publisher": "Acme",
        "description": "What everyone is on today.",
        "avatar_url": "/marketplace/acme-standup.svg",
        "version": "1.0.0",
        "definition": {
            "widgets": [
                {
                    "id": "w1",
                    "type": "stat",
                    "binding": {
                        "source": "query",
                        "sql": "SELECT count(*) AS n FROM tasks",
                    },
                }
            ]
        },
    }


@pytest.fixture
def catalog_dir(tmp_path, monkeypatch):
    directory = tmp_path / "marketplace"
    directory.mkdir()
    monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(directory))
    return directory


async def test_a_rescan_records_its_source_and_what_it_moved(
    client, acting_user, catalog_dir, capfd
):
    (catalog_dir / "standup.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    actor = await acting_user("owner")
    actor_id = actor.user.id
    capfd.readouterr()

    response = await client.post(RESCAN_URL, headers=actor.headers)
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.MARKETPLACE_CATALOG_REFRESHED)
    assert [(r["actor_user_id"], r["guild_id"], r["target"]) for r in rows] == [
        (actor_id, None, None)
    ]
    assert rows[0]["detail"] == {
        "source": "operator_catalog",
        "published": 1,
        "withdrawn": 0,
        "skipped": 0,
    }


async def test_a_scan_with_nowhere_to_read_from_records_nothing(
    client, acting_user, monkeypatch, capfd
):
    monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", None)
    actor = await acting_user("owner")
    capfd.readouterr()

    refused = await client.post(RESCAN_URL, headers=actor.headers)
    assert refused.status_code == 400, refused.text

    assert emitted(capfd, AuditEventType.MARKETPLACE_CATALOG_REFRESHED) == []


async def test_a_rescan_a_lower_tier_asked_for_records_nothing(
    client, acting_user, catalog_dir, capfd
):
    (catalog_dir / "standup.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    actor = await acting_user("moderator")
    capfd.readouterr()

    refused = await client.post(RESCAN_URL, headers=actor.headers)
    assert refused.status_code == 403, refused.text

    assert emitted(capfd, AuditEventType.MARKETPLACE_CATALOG_REFRESHED) == []
