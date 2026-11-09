"""Integration tests for the native OTA bundle endpoints.

The native (Capacitor) app polls these to decide whether to download a matching web bundle.
A local dev/test checkout has no ``/app/ota`` directory, so the endpoints must 404 cleanly;
when an image ships the artifacts, the manifest names the bundle and, in a release image,
carries its signed statement.
"""

from __future__ import annotations

import hashlib

from httpx2 import AsyncClient

from app.api.v1.platform_endpoints import native
from app.core.messages import NativeMessages
from app.core.version import __version__


async def test_manifest_404_when_bundle_absent(client: AsyncClient):
    """No OTA artifacts present (the default outside a built image) → 404, not a 500."""
    response = await client.get("/api/v1/native/bundle/manifest")
    assert response.status_code == 404
    assert response.json()["detail"] == NativeMessages.OTA_BUNDLE_NOT_AVAILABLE


async def test_download_404_when_bundle_absent(client: AsyncClient):
    response = await client.get("/api/v1/native/bundle/download")
    assert response.status_code == 404
    assert response.json()["detail"] == NativeMessages.OTA_BUNDLE_NOT_AVAILABLE


async def test_manifest_names_the_bundle_and_its_statement(
    client: AsyncClient, tmp_path, monkeypatch
):
    """The manifest names the bundle, and carries the signed statement the updater
    verifies the zip against when the image has one."""
    bundle = tmp_path / "bundle.zip"
    bundle.write_bytes(b"PK\x03\x04 fake zip payload")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

    statement = tmp_path / "statement.json"
    signature = tmp_path / "statement.sig"
    monkeypatch.setattr(native, "_BUNDLE_PATH", bundle)
    monkeypatch.setattr(native, "_STATEMENT_PATH", statement)
    monkeypatch.setattr(native, "_SIGNATURE_PATH", signature)

    response = await client.get("/api/v1/native/bundle/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["url"] == "/api/v1/native/bundle/download"
    # An image built without the release key carries no statement.
    assert "statement" not in body and "signature" not in body

    statement.write_text(f'{{"v":1,"sha256":"{digest}"}}')
    signature.write_text("c2lnbmVk\n")
    body = (await client.get("/api/v1/native/bundle/manifest")).json()
    assert body["statement"] == f'{{"v":1,"sha256":"{digest}"}}'
    assert body["signature"] == "c2lnbmVk"


async def test_download_serves_zip(client: AsyncClient, tmp_path, monkeypatch):
    bundle = tmp_path / "bundle.zip"
    payload = b"PK\x03\x04 fake zip payload"
    bundle.write_bytes(payload)

    monkeypatch.setattr(native, "_BUNDLE_PATH", bundle)

    response = await client.get("/api/v1/native/bundle/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "immutable" in response.headers["cache-control"]
    assert response.content == payload
