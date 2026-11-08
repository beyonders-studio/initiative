"""The operator's registry routes: the switch, the status, refresh, and the
offline bundle.

Deployment configuration, so every route is ``config.manage``. The repository
is built in memory with keys made for the test and served through a stand-in
fetcher; the bundle route reads the same repository as a tar.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.services.marketplace import tuf_registry
from app.testing.tuf_repository import BASE_URL, TufRepository

STATUS_URL = "/api/v1/marketplace/registry/status"
SETTINGS_URL = "/api/v1/marketplace/registry/settings"
REFRESH_URL = "/api/v1/marketplace/registry/refresh"
BUNDLE_URL = "/api/v1/marketplace/registry/bundle"

UID = "ACME0000000009"


@pytest.fixture
def repo(monkeypatch, tmp_path) -> TufRepository:
    repository = TufRepository()
    repository.add_publisher("acme", name="Acme")
    repository.add_listing("acme", UID, slug="board", kind="dashboard")
    repository.publish()
    root = tmp_path / "root.json"
    root.write_bytes(repository.root_bytes())
    monkeypatch.setattr(tuf_registry, "BUILTIN_ROOT_PATH", root)
    monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ROOT", None)
    monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", BASE_URL)
    monkeypatch.setattr(
        tuf_registry, "SafeHttpFetcher", lambda _loop: repository.fetcher()
    )
    return repository


async def test_the_status_says_it_is_on_and_never_run(client, acting_user, repo):
    actor = await acting_user("owner")

    response = await client.get(STATUS_URL, headers=actor.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["configured"] is True
    assert body["custom_root"] is False
    assert body["registry_url"] == BASE_URL
    assert body["last_success_at"] is None


async def test_refresh_applies_and_the_status_follows(client, acting_user, repo):
    actor = await acting_user("owner")

    response = await client.post(REFRESH_URL, headers=actor.headers)

    assert response.status_code == 200, response.text
    assert response.json()["upserted"] == 1
    status = (await client.get(STATUS_URL, headers=actor.headers)).json()
    assert status["root_version"] == 1
    assert status["listing_count"] == 1
    assert status["last_error"] is None
    assert status["last_success_at"] is not None


async def test_switched_off_refresh_is_refused(client, acting_user, repo):
    actor = await acting_user("owner")

    switched = await client.put(
        SETTINGS_URL, json={"enabled": False}, headers=actor.headers
    )
    refreshed = await client.post(REFRESH_URL, headers=actor.headers)

    assert switched.status_code == 200, switched.text
    assert switched.json() == {"enabled": False}
    assert refreshed.status_code == 409
    assert refreshed.json()["detail"] == Codes.DISABLED
    status = (await client.get(STATUS_URL, headers=actor.headers)).json()
    assert status["enabled"] is False


async def test_a_bundle_upload_applies(client, acting_user, repo):
    actor = await acting_user("owner")

    response = await client.post(
        BUNDLE_URL,
        files={"file": ("registry.tgz", repo.bundle(), "application/gzip")},
        headers=actor.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["upserted"] == 1


async def test_a_bundle_that_does_not_verify_is_refused(client, acting_user, repo):
    actor = await acting_user("owner")
    path = "metadata/1.targets.json"
    repo.files[path] = repo.files[path].replace(b'"acme"', b'"acmf"', 1)

    response = await client.post(
        BUNDLE_URL,
        files={"file": ("registry.tgz", repo.bundle(), "application/gzip")},
        headers=actor.headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == Codes.METADATA_REJECTED


async def test_a_file_that_is_not_a_bundle_is_a_400(client, acting_user, repo):
    actor = await acting_user("owner")

    response = await client.post(
        BUNDLE_URL,
        files={"file": ("registry.tgz", b"not an archive", "application/gzip")},
        headers=actor.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == Codes.BUNDLE_INVALID


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", STATUS_URL),
        ("post", REFRESH_URL),
        ("put", SETTINGS_URL),
    ],
)
async def test_a_lower_tier_reaches_none_of_it(client, acting_user, repo, method, url):
    actor = await acting_user("operator")

    kwargs = {"json": {"enabled": False}} if method == "put" else {}
    response = await getattr(client, method)(url, headers=actor.headers, **kwargs)

    assert response.status_code == 403
