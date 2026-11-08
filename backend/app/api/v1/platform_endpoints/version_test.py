"""Tests for the version/changelog endpoints."""

from __future__ import annotations

import httpx2
import pytest
from httpx2 import AsyncClient

from app.api.v1.platform_endpoints import version as version_endpoint
from app.schemas.base import MAX_PLAIN_TEXT_LENGTH


async def test_changelog_returns_typed_entries(client: AsyncClient):
    """The changelog is served as ``{entries: [{version, date, changes}]}`` —
    the typed shape Orval generates from ChangelogResponse."""
    resp = await client.get("/api/v1/changelog?limit=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "entries" in body
    for entry in body["entries"]:
        assert set(entry.keys()) == {"version", "date", "changes"}


async def test_changelog_returns_large_sections_verbatim(client: AsyncClient):
    """A single version's ``changes`` routinely exceeds the plain-text
    sanitizer's length cap. ``changes`` is RawTextStr, so the section is
    returned verbatim rather than rejected — pinning that a plain ``str`` field
    (which raises past the cap) is never reintroduced."""
    resp = await client.get("/api/v1/changelog?limit=1000")
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    assert entries, "the repo CHANGELOG.md should yield released entries"
    assert any(len(entry["changes"]) > MAX_PLAIN_TEXT_LENGTH for entry in entries), (
        "expected at least one released section to exceed the plain-text cap; "
        "the endpoint must return it intact, not 500 on sanitization"
    )


@pytest.fixture
def latest(monkeypatch):
    """A fresh cache and a stand-in for GitHub that counts its calls."""
    monkeypatch.setattr(version_endpoint, "_latest", version_endpoint._LatestVersion())
    hub = {"calls": 0, "answer": "1.2.3"}

    async def fetch():
        hub["calls"] += 1
        if isinstance(hub["answer"], Exception):
            raise hub["answer"]
        return hub["answer"]

    monkeypatch.setattr(version_endpoint, "_fetch_latest_version", fetch)
    return hub


def _expire():
    version_endpoint._latest.expires_at = 0.0


async def test_latest_version_is_fetched_once_for_every_caller(
    client: AsyncClient, latest
):
    for _ in range(3):
        response = await client.get("/api/v1/version/latest")
        assert response.json() == {"version": "1.2.3"}
    assert latest["calls"] == 1


async def test_latest_version_keeps_the_last_answer_while_offline(
    client: AsyncClient, latest, caplog
):
    await client.get("/api/v1/version/latest")
    latest["answer"] = httpx2.ConnectError("no route to host")

    for _ in range(2):
        _expire()
        response = await client.get("/api/v1/version/latest")
        assert response.json() == {"version": "1.2.3"}

    assert latest["calls"] == 3
    offline = [r for r in caplog.records if "GitHub" in r.getMessage()]
    assert len(offline) == 1


async def test_latest_version_is_none_when_never_reached(client: AsyncClient, latest):
    latest["answer"] = httpx2.ConnectError("no route to host")
    response = await client.get("/api/v1/version/latest")
    assert response.json() == {"version": None}


async def test_latest_version_is_the_highest_published_release(monkeypatch):
    """Drafts, pre-releases and tags that are not a version are passed over,
    and a fix on an older line released last does not win."""
    releases = [
        {"tag_name": "v0.73.3", "draft": False, "prerelease": False},
        {"tag_name": "v0.75.0", "draft": True, "prerelease": False},
        {"tag_name": "v0.74.1-rc.1", "draft": False, "prerelease": True},
        {"tag_name": "v0.74.0", "draft": False, "prerelease": False},
        {"tag_name": "nightly", "draft": False, "prerelease": False},
        {"tag_name": "v0.9.0", "draft": False, "prerelease": False},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url).startswith(version_endpoint._RELEASES_URL)
        return httpx2.Response(200, json=releases)

    real_client = httpx2.AsyncClient

    def client_with(**kwargs):
        return real_client(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr(version_endpoint.httpx2, "AsyncClient", client_with)
    assert await version_endpoint._fetch_latest_version() == "0.74.0"
