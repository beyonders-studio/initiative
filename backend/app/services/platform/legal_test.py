"""The terms an account agrees to, and the record that it did.

Two things these hold down. A self-hosted deployment must never ask anybody to
accept anything — it has no terms of its own and no portal to serve them — and
a hosted one must never fail a registration because the portal is having a bad
day: the acceptance is the fact, the version is the garnish.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.platform.legal_acceptance import LegalAcceptance
from app.services.platform import legal as legal_service
from app.testing import create_user

PORTAL = "https://billing.example.com"

INDEX_BODY = {
    "documents": [
        {
            "slug": "terms",
            "title": "Terms of Service",
            "version": "2.1",
            "effective_date": "2026-09-01",
            "sha256": "a" * 64,
            "required": True,
        },
        {
            "slug": "privacy",
            "title": "Privacy Policy",
            "version": "1.4",
            "effective_date": "2026-09-01",
            "sha256": "b" * 64,
            "required": True,
        },
    ]
}


@pytest.fixture(autouse=True)
def _clear_cache():
    legal_service.reset_index_cache()
    yield
    legal_service.reset_index_cache()


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_URL", PORTAL)


def _serve(monkeypatch, body=INDEX_BODY, *, fail: bool = False):
    """Stand in for the portal's index endpoint, counting the calls."""
    calls: list[str] = []

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return body

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url, **kwargs):
            calls.append(url)
            if fail:
                raise RuntimeError("portal is down")
            return _Response()

    monkeypatch.setattr(legal_service.httpx2, "AsyncClient", _Client)
    return calls


def test_a_self_hosted_deployment_has_no_terms(monkeypatch):
    """No portal, no legal entity behind the service, nothing to accept."""
    monkeypatch.setattr(settings, "BILLING_URL", None)
    assert legal_service.legal_documents_enabled() is False


def test_a_portal_makes_it_hosted(hosted):
    assert legal_service.legal_documents_enabled() is True


async def test_index_is_read_once_and_then_cached(hosted, monkeypatch):
    calls = _serve(monkeypatch)

    first = await legal_service.get_index()
    second = await legal_service.get_index()

    assert [d.slug for d in first] == ["terms", "privacy"]
    assert second == first
    assert len(calls) == 1


async def test_a_portal_that_goes_down_keeps_answering_from_the_last_read(
    hosted, monkeypatch
):
    _serve(monkeypatch)
    await legal_service.get_index()

    _serve(monkeypatch, fail=True)
    still = await legal_service.get_index(force=True)

    assert [d.version for d in still] == ["2.1", "1.4"]


async def test_a_portal_that_was_never_reached_raises(hosted, monkeypatch):
    _serve(monkeypatch, fail=True)
    with pytest.raises(legal_service.LegalPortalUnavailable):
        await legal_service.get_index()


async def test_nothing_is_recorded_on_a_self_hosted_deployment(session, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_URL", None)
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    assert await _rows(session, user.id) == []
    assert await legal_service.acceptance_outstanding(session, user=user) is False


async def test_acceptance_records_the_revision_that_was_current(
    session, hosted, monkeypatch
):
    _serve(monkeypatch)
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    rows = await _rows(session, user.id)
    assert [(r.document, r.version, r.document_sha256) for r in rows] == [
        ("terms", "2.1", "a" * 64),
        ("privacy", "1.4", "b" * 64),
    ]
    assert await legal_service.acceptance_outstanding(session, user=user) is False


async def test_an_unreachable_portal_invents_no_required_document(
    session, hosted, monkeypatch
):
    """Registration still goes through, but nothing is recorded as agreed to a
    document nobody could name: the account is asked once the index can be
    read again."""
    _serve(monkeypatch, fail=True)
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    assert await _rows(session, user.id) == []
    assert await legal_service.acceptance_outstanding(session, user=user) is False

    legal_service.reset_index_cache()
    _serve(monkeypatch)
    assert await legal_service.acceptance_outstanding(session, user=user) is True


async def test_a_portal_never_read_is_left_alone_for_a_while(hosted, monkeypatch):
    calls = _serve(monkeypatch, fail=True)
    for _ in range(3):
        with pytest.raises(legal_service.LegalPortalUnavailable):
            await legal_service.get_index()
    assert len(calls) == 1


async def test_a_deployment_that_requires_nothing_asks_nothing(
    session, hosted, monkeypatch
):
    """An enterprise's terms may sit in its own contract, or in an employment
    one: the portal marks nothing required, or lists nothing at all."""
    for body in (
        {"documents": [{**d, "required": False} for d in INDEX_BODY["documents"]]},
        {"documents": []},
    ):
        legal_service.reset_index_cache()
        _serve(monkeypatch, body)
        user = await create_user(session)

        await legal_service.record_acceptance(session, user_id=user.id)
        await session.commit()

        assert await _rows(session, user.id) == []
        assert await legal_service.acceptance_outstanding(session, user=user) is False


async def test_only_the_documents_marked_required_are_recorded(
    session, hosted, monkeypatch
):
    terms, privacy = INDEX_BODY["documents"]
    _serve(monkeypatch, {"documents": [terms, {**privacy, "required": False}]})
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    assert [r.document for r in await _rows(session, user.id)] == ["terms"]
    assert await legal_service.acceptance_outstanding(session, user=user) is False


async def test_a_document_hosted_elsewhere_is_linked_not_fetched(
    session, hosted, monkeypatch
):
    contract = {
        "slug": "contract",
        "title": "Master Services Agreement",
        "version": "2026-01",
        "effective_date": None,
        "sha256": None,
        "required": True,
        "url": "https://legal.customer.example/msa.pdf",
    }
    _serve(monkeypatch, {"documents": [contract]})
    (document,) = await legal_service.get_index()
    assert document.url == contract["url"]

    with pytest.raises(KeyError):
        await legal_service.get_document("contract")

    user = await create_user(session)
    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()
    rows = await _rows(session, user.id)
    assert [(r.document, r.version, r.document_sha256) for r in rows] == [
        ("contract", "2026-01", None)
    ]


async def test_a_link_that_is_not_https_is_not_offered(hosted, monkeypatch):
    _serve(
        monkeypatch,
        {
            "documents": [
                {"slug": "x", "title": "X", "url": "javascript:alert(1)"},
                {"slug": "y", "title": "Y", "url": "http://plain.example/y"},
            ]
        },
    )
    assert await legal_service.get_index() == ()


async def test_a_half_finished_record_still_owes_the_rest(session, hosted, monkeypatch):
    _serve(monkeypatch)
    user = await create_user(session)
    session.add(LegalAcceptance(user_id=user.id, document="terms", version="2.1"))
    await session.commit()

    assert await legal_service.acceptance_outstanding(session, user=user) is True


async def test_a_document_nobody_asked_for_does_not_settle_the_debt(
    session, hosted, monkeypatch
):
    _serve(monkeypatch)
    user = await create_user(session)
    session.add(LegalAcceptance(user_id=user.id, document="sla", version="1.0"))
    session.add(LegalAcceptance(user_id=user.id, document="terms", version="2.1"))
    session.add(LegalAcceptance(user_id=user.id, document="sla", version="1.1"))
    await session.commit()

    assert await legal_service.acceptance_outstanding(session, user=user) is True


async def test_a_newer_revision_does_not_interrupt_somebody_already_here(
    session, hosted, monkeypatch
):
    """The question is whether they ever agreed, not whether they agreed to
    today's wording. Publishing a correction must not put every account in the
    deployment back in front of a consent screen."""
    _serve(monkeypatch)
    user = await create_user(session)
    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    moved = {
        "documents": [
            {**d, "version": "9.9", "sha256": "c" * 64} for d in INDEX_BODY["documents"]
        ]
    }
    legal_service.reset_index_cache()
    _serve(monkeypatch, moved)

    assert await legal_service.acceptance_outstanding(session, user=user) is False


async def _rows(session, user_id: int) -> list[LegalAcceptance]:
    from sqlmodel import select

    return list(
        (
            await session.exec(
                select(LegalAcceptance)
                .where(LegalAcceptance.user_id == user_id)
                .order_by(LegalAcceptance.id)
            )
        ).all()
    )


@pytest.mark.parametrize("slug", ["../admin", "terms?x=1", "Terms", ""])
async def test_a_slug_outside_the_slug_characters_is_not_asked_for(
    hosted, monkeypatch, slug
):
    """Only a slug written in the documents' own characters reaches the
    portal; any other is a document that does not exist."""

    class _NoPortal:
        def __init__(self, *args, **kwargs):
            raise AssertionError("the portal was asked")

    monkeypatch.setattr(legal_service.httpx2, "AsyncClient", _NoPortal)
    with pytest.raises(KeyError):
        await legal_service.get_document(slug)
