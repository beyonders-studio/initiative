"""Tests for the liveness and readiness probes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from prometheus_client import REGISTRY

from app.api.v1.platform_endpoints import health
from app.core.config import settings
from app.core.rate_limit import build_limiter
from app.testing import create_user


@pytest.fixture(autouse=True)
def request_engine_on_the_test_database(engine, monkeypatch: pytest.MonkeyPatch):
    """conftest already points the system and provisioning engines at this
    worker's database; the request engine is reached through the overridden
    session dependency, so nothing had moved it. The readiness check connects
    with the engine itself, which is what needs pointing here."""
    import app.db.session as db_session

    monkeypatch.setattr(db_session, "engine", engine)


@pytest.fixture(autouse=True)
def no_held_readiness_answer(monkeypatch: pytest.MonkeyPatch):
    """Each test swaps the checks, so none may be answered from the last."""
    monkeypatch.setattr(health, "_ready_run", None)


async def test_healthz_answers_without_touching_anything(client: AsyncClient):
    """Liveness is about this process only, so it answers the same whether or
    not its dependencies are reachable."""
    resp = await client.get("/api/v1/healthz")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}


async def test_readyz_reports_every_dependency(client: AsyncClient):
    """Readiness names each dependency it pinged. The three engines are
    reachable under test, so the verdict is never ``unavailable``."""
    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["checks"]) == set(health.CHECKS)
    for name in health.REQUIRED:
        assert body["checks"][name] == "ok", body
    assert body["status"] in {"ok", "degraded"}


def test_a_read_replica_is_reported_and_does_not_decide(monkeypatch):
    assert "database_query" not in health.declared_checks()

    monkeypatch.setattr(
        health.settings, "DATABASE_URL_QUERY", "postgresql+asyncpg://r/initiative"
    )
    assert "database_query" in health.declared_checks()
    assert "database_query" not in health.REQUIRED


async def test_readyz_is_503_when_a_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """A pod that cannot reach Postgres can serve nothing, so it leaves the
    Service's endpoints."""

    async def unreachable() -> None:
        raise RuntimeError("down")

    monkeypatch.setitem(health.CHECKS, "database", unreachable)
    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "error"


async def test_readyz_stays_in_rotation_when_only_a_reported_check_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Object storage, the bus and the rate-limit counters are reported, not
    voted on: losing one leaves most of the app serving, and removing every
    pod over it would leave none."""

    async def unreachable() -> None:
        raise RuntimeError("down")

    for name in set(health.CHECKS) - health.REQUIRED:
        monkeypatch.setitem(health.CHECKS, name, unreachable)
    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "degraded"


async def test_an_unreachable_rate_limit_store_is_reported_while_counting_in_memory(
    monkeypatch: pytest.MonkeyPatch,
):
    counting_in_memory = build_limiter("redis://127.0.0.1:1/0")
    counting_in_memory._storage_dead = True
    monkeypatch.setattr(health, "limiter", counting_in_memory)
    with pytest.raises(RuntimeError):
        await health._rate_limit_store()


async def test_readyz_reports_a_hung_dependency_rather_than_hanging(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """A check that never returns is bounded, so the probe answers inside its
    own timeout instead of being killed by it."""
    import asyncio

    async def never() -> None:
        await asyncio.sleep(60)

    async def immediately() -> None:
        return None

    for name in health.CHECKS:
        monkeypatch.setitem(health.CHECKS, name, immediately)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setitem(health.CHECKS, "storage", never)

    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json()["checks"]["storage"] == "error"


async def test_readyz_checks_once_per_window_however_often_it_is_called(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Callers share one run of the checks while it is running, even past the
    window, and reuse its answer until the window since it started has
    passed."""
    import asyncio
    from types import SimpleNamespace

    clock = 0.0
    monkeypatch.setattr(health, "time", SimpleNamespace(monotonic=lambda: clock))
    runs = 0
    release = asyncio.Event()

    async def counted() -> None:
        nonlocal runs
        runs += 1
        await release.wait()

    for name in health.CHECKS:
        monkeypatch.setitem(health.CHECKS, name, lambda: asyncio.sleep(0))
    monkeypatch.setitem(health.CHECKS, "database", counted)

    async def readyz() -> int:
        return (await client.get("/api/v1/readyz")).status_code

    waiting = [asyncio.create_task(readyz()) for _ in range(3)]
    while runs == 0:
        await asyncio.sleep(0)
    clock = health.READY_CACHE_SECONDS + 1
    waiting.append(asyncio.create_task(readyz()))
    await asyncio.sleep(0.01)
    release.set()
    assert await asyncio.gather(*waiting) == [200] * 4
    assert runs == 1

    # The finished run started at 0, so its answer has expired.
    assert await readyz() == 200
    assert runs == 2
    clock += health.READY_CACHE_SECONDS - 0.1
    assert await readyz() == 200
    assert runs == 2
    clock += 0.1
    assert await readyz() == 200
    assert runs == 3


@pytest.mark.parametrize("path", ["/api/v1/healthz", "/api/v1/readyz"])
async def test_probes_are_not_rate_limited(
    client: AsyncClient, rate_limit_of_one_per_minute, path: str
):
    """A cluster calls these on a fixed interval, so they must never be
    answered with a 429 — and the marker slowapi offers for that does not
    reach the middleware in an app with a catch-all route, so this asks the
    running limiter rather than the decorator."""
    first = await client.get(path)
    second = await client.get(path)
    assert (first.status_code, second.status_code) != (200, 429), second.text
    assert first.status_code == 200 and second.status_code == 200, second.text


async def test_probes_stay_out_of_the_api_schema(client: AsyncClient):
    """Infrastructure routes, with no client generated for them."""
    resp = await client.get("/api/v1/openapi.json")
    assert resp.status_code == 200, resp.text
    paths = resp.json()["paths"]
    assert "/api/v1/healthz" not in paths
    assert "/api/v1/readyz" not in paths


METRICS = "/api/v1/metrics"


async def test_metrics_is_not_there_until_a_token_is_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)
    resp = await client.get(METRICS, headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong", "Basic c2NyYXBlOnM=", "s3cret-token"]
)
async def test_metrics_wants_the_token_as_a_bearer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, authorization: str | None
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    headers = {"Authorization": authorization} if authorization else {}
    resp = await client.get(METRICS, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_metrics_answers_a_scrape_presenting_the_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    await client.get("/api/v1/version")

    # The token is compared with the space around it trimmed.
    resp = await client.get(METRICS, headers={"Authorization": "Bearer  s3cret-token"})

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert (
        'initiative_http_requests_total{method="GET",route="/api/v1/version",status="200"}'
        in body
    )
    assert "initiative_build_info{version=" in body
    assert 'initiative_db_pool_connections{engine="request",state="idle"}' in body
    assert "initiative_sessions_active " in body
    assert "process_cpu_seconds_total" in body or "python_gc_objects" in body


async def test_metrics_counts_accounts_active_in_each_window(
    client: AsyncClient, session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    now = datetime.now(UTC)
    await create_user(session, last_active_at=now - timedelta(hours=2))
    await create_user(session, last_active_at=now - timedelta(days=3))
    await create_user(session, last_active_at=now - timedelta(days=40))
    await create_user(session)

    resp = await client.get(METRICS, headers={"Authorization": "Bearer s3cret-token"})

    assert resp.status_code == 200, resp.text
    assert 'initiative_active_users{window="1d"} 1.0' in resp.text
    assert 'initiative_active_users{window="7d"} 2.0' in resp.text
    assert 'initiative_active_users{window="30d"} 2.0' in resp.text


async def test_page_views_are_counted_by_route_template(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    def views(route: str) -> float:
        return (
            REGISTRY.get_sample_value("initiative_page_views_total", {"route": route})
            or 0.0
        )

    known = "/c/$communityId/i/$initiativeId/projects/$projectId/"
    before_known, before_other = views(known), views("other")

    monkeypatch.setattr(settings, "METRICS_TOKEN", None)
    resp = await client.post("/api/v1/page-views", json={"route": known})
    assert resp.status_code == 204, resp.text
    assert views(known) == before_known

    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    for route in (known, "/c/42/projects/913"):
        resp = await client.post("/api/v1/page-views", json={"route": route})
        assert resp.status_code == 204, resp.text

    assert views(known) == before_known + 1
    assert views("other") == before_other + 1
