"""The app's window onto the hosted deployment's legal documents.

Unauthenticated, because the signup form links to them. The invariants are
about what each deployment shape answers, not about access control: a
self-hoster must find nothing here at all.
"""

from __future__ import annotations

import pytest
from httpx2 import AsyncClient

from app.core.config import settings
from app.core.messages import LegalMessages
from app.services.platform import legal as legal_service

PORTAL = "https://billing.example.com"


@pytest.fixture(autouse=True)
def _clear_cache():
    legal_service.reset_index_cache()
    yield
    legal_service.reset_index_cache()


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_URL", PORTAL)


async def test_a_self_hosted_deployment_publishes_no_terms(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", None)

    index = await client.get("/api/v1/legal")
    document = await client.get("/api/v1/legal/terms")

    assert index.status_code == 404
    assert index.json()["detail"] == LegalMessages.NOT_CONFIGURED
    assert document.status_code == 404


async def test_index_names_the_documents_and_which_are_required(
    client: AsyncClient, hosted, monkeypatch
):
    monkeypatch.setattr(
        legal_service,
        "get_index",
        _index(
            [
                legal_service.LegalDocument(
                    slug="terms",
                    title="Terms of Service",
                    version="2.1",
                    effective_date="2026-09-01",
                    sha256="a" * 64,
                    required=True,
                ),
                legal_service.LegalDocument(
                    slug="sla",
                    title="Service Level Agreement",
                    version="1.0",
                    effective_date=None,
                    sha256=None,
                    url="https://legal.customer.example/sla.pdf",
                ),
            ]
        ),
    )

    response = await client.get("/api/v1/legal")

    assert response.status_code == 200
    body = response.json()
    assert [d["slug"] for d in body["documents"]] == ["terms", "sla"]
    assert body["documents"][0]["version"] == "2.1"
    assert body["documents"][1]["url"] == "https://legal.customer.example/sla.pdf"
    # The portal says which are required; the app adds none of its own.
    assert body["required"] == ["terms"]


async def test_a_deployment_may_publish_no_documents(
    client: AsyncClient, hosted, monkeypatch
):
    monkeypatch.setattr(legal_service, "get_index", _index([]))

    response = await client.get("/api/v1/legal")

    assert response.status_code == 200
    assert response.json() == {"documents": [], "required": []}


async def test_an_unreachable_portal_says_so_rather_than_inventing_terms(
    client: AsyncClient, hosted, monkeypatch
):
    async def _down(**kwargs):
        raise legal_service.LegalPortalUnavailable("down")

    monkeypatch.setattr(legal_service, "get_index", _down)

    response = await client.get("/api/v1/legal")

    assert response.status_code == 503
    assert response.json()["detail"] == LegalMessages.PORTAL_UNAVAILABLE


async def test_a_document_is_served_as_markdown_with_the_portal_etag(
    client: AsyncClient, hosted, monkeypatch
):
    async def _document(slug, *, if_none_match=None):
        assert slug == "terms"
        return legal_service.FetchedDocument(
            content=b"# Terms of Service\n",
            media_type="text/markdown; charset=utf-8",
            etag='"abc"',
        )

    monkeypatch.setattr(legal_service, "get_document", _document)

    response = await client.get("/api/v1/legal/terms")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["etag"] == '"abc"'
    # Revalidated rather than held: a corrected policy has to reach a reader
    # who already has a copy, on their next look.
    assert "no-cache" in response.headers["cache-control"]
    assert "max-age" not in response.headers["cache-control"]
    assert response.text == "# Terms of Service\n"


async def test_a_document_the_portal_does_not_have_is_404(
    client: AsyncClient, hosted, monkeypatch
):
    async def _missing(slug, *, if_none_match=None):
        raise KeyError(slug)

    monkeypatch.setattr(legal_service, "get_document", _missing)

    response = await client.get("/api/v1/legal/teleportation")

    assert response.status_code == 404
    assert response.json()["detail"] == LegalMessages.DOCUMENT_NOT_FOUND


def _index(documents):
    async def _get(**kwargs):
        return tuple(documents)

    return _get
