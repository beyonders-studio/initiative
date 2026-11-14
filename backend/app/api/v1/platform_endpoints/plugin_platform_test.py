"""Publishing the key a plug-in verifies calls with.

The platform's own signing key, as a JWKS document. It is **public** — a plug-in
fetching the key it will check a credential with cannot be asked for a
credential first. An unconfigured platform key answers **503 rather than an
empty key set**: the two look similar and mean opposite things, and a plug-in that
cached `{"keys": []}` would refuse every later token from a platform that had
simply not been wired up yet.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx2 import AsyncClient

from app.core.config import settings
from app.core.messages import PluginServiceMessages
from app.services.marketplace import context_jwt

JWKS_URL = "/api/v1/plugin-platform/jwks.json"

_keypair = ed25519.Ed25519PrivateKey.generate()
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM
    )
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "plugin-platform-1")
    monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
    monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)


async def test_the_key_set_is_served_without_any_credential(
    client: AsyncClient, configured
):
    response = await client.get(JWKS_URL)
    assert response.status_code == 200, response.text

    keys = response.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kty"] == "OKP"
    assert keys[0]["crv"] == "Ed25519"
    assert keys[0]["alg"] == "EdDSA"
    assert keys[0]["kid"] == "plugin-platform-1"
    assert keys[0]["x"]


async def test_it_never_serves_private_material(client: AsyncClient, configured):
    entry = (await client.get(JWKS_URL)).json()["keys"][0]
    assert set(entry) <= {"kty", "crv", "use", "alg", "kid", "x"}


async def test_an_unconfigured_deployment_says_so_rather_than_publishing_nothing(
    client: AsyncClient, unconfigured
):
    response = await client.get(JWKS_URL)
    assert response.status_code == 503
    assert response.json()["detail"] == PluginServiceMessages.SIGNING_NOT_CONFIGURED
