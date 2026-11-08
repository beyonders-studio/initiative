"""The channels that paired one party's name for a community with another's
are gone, and nothing still names them.

Pairing was the reference sectors' only job — a registration naming
``reference_sectors``, the ``community-reference`` route answering a
sector's reference, and the bundled service's own HMAC channel behind it — and
entitlement statements replaced it: the plug-in is told its community's terms
under the name it already holds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.always

BACKEND = Path(__file__).resolve().parents[2]
RETIRED = (
    "community-reference",
    "BUNDLED_SERVICE_",
    "bundled_channel",
    "BundledChannel",
    "reference_sectors",
    "REFERENCE_SECTORS",
)


async def test_the_community_reference_route_is_gone(client: AsyncClient):
    body = {"purpose": "billing", "community_ref": "gplu_x"}
    response = await client.post(
        "/api/v1/plugin-platform/community-reference", json=body
    )
    nowhere = await client.post("/api/v1/plugin-platform/never-a-route", json=body)

    # Answered as any path no route serves is.
    assert response.status_code == nowhere.status_code
    assert response.status_code in (404, 405)


def test_nothing_in_the_app_names_them():
    """Migrations that shipped keep their history; nothing else may."""
    here = Path(__file__).resolve()
    named = sorted(
        f"{path.relative_to(BACKEND)}: {word}"
        for path in (BACKEND / "app").rglob("*.py")
        if path != here
        for word in RETIRED
        if word in path.read_text(encoding="utf-8")
    )
    assert named == []


def test_the_environment_contract_names_no_bundled_service():
    contract = json.loads((BACKEND.parent / "env-contract.json").read_text())
    names = json.dumps(contract)
    assert "BUNDLED_SERVICE" not in names
