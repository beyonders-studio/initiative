"""Two doors into an account, and the terms behind both of them.

An account created through the signup form agreed there — the notice sits
above the button, and the acceptance is written as the account is. An account
an identity provider provisioned met no form, so it is asked once, before it
can do anything else. Neither happens on a deployment with no terms of its
own.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import LegalMessages
from app.db.request_context import Platform
from app.models.platform.legal_acceptance import LegalAcceptance
from app.models.platform.user import User
from app.services.platform import legal as legal_service

PORTAL = "https://billing.example.com"

INDEX = (
    legal_service.LegalDocument(
        slug="terms",
        title="Terms of Service",
        version="2.1",
        effective_date="2026-09-01",
        sha256="a" * 64,
        required=True,
    ),
    legal_service.LegalDocument(
        slug="privacy",
        title="Privacy Policy",
        version="1.4",
        effective_date="2026-09-01",
        sha256="b" * 64,
        required=True,
    ),
)


@pytest.fixture(autouse=True)
def _clear_cache():
    legal_service.reset_index_cache()
    yield
    legal_service.reset_index_cache()


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_URL", PORTAL)

    async def _index(**kwargs):
        return INDEX

    monkeypatch.setattr(legal_service, "get_index", _index)


async def test_registering_on_a_hosted_deployment_records_the_agreement(
    client: AsyncClient, session: AsyncSession, hosted
):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "legal-signup@example.com",
            "username": "legalsignup",
            "password": "securepassword123",
            "accepted_documents": ["terms", "privacy"],
        },
    )

    assert response.status_code == 201
    rows = await _rows(session, response.json()["id"])
    assert [(r.document, r.version) for r in rows] == [
        ("terms", "2.1"),
        ("privacy", "1.4"),
    ]


async def test_only_the_documents_the_form_showed_are_recorded(
    client: AsyncClient, session: AsyncSession, hosted
):
    """A form whose index was still loading, or couldn't be read, showed
    nothing: what it didn't show is asked for after sign-in, not assumed."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "legal-partial@example.com",
            "username": "legalpartial",
            "password": "securepassword123",
            "accepted_documents": ["terms"],
        },
    )

    assert response.status_code == 201
    rows = await _rows(session, response.json()["id"])
    assert [r.document for r in rows] == ["terms"]
    user = await session.get(User, response.json()["id"])
    assert await legal_service.acceptance_outstanding(session, user=user) is True


async def test_registering_on_a_self_hosted_deployment_records_nothing(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", None)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "selfhost-signup@example.com",
            "username": "selfhostsignup",
            "password": "securepassword123",
        },
    )

    assert response.status_code == 201
    assert await _rows(session, response.json()["id"]) == []


async def test_an_account_that_signed_up_is_never_asked_again(
    client: AsyncClient, session: AsyncSession, hosted
):
    """The form is a door, so what it recorded has to settle the same
    question the after-sign-in screen asks."""
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "legal-noask@example.com",
            "username": "legalnoask",
            "password": "securepassword123",
            "accepted_documents": ["terms", "privacy"],
        },
    )
    user = await session.get(User, created.json()["id"])

    assert await legal_service.acceptance_outstanding(session, user=user) is False


async def test_an_account_that_met_no_form_is_asked(
    client: AsyncClient, acting_user, hosted
):
    """What an identity provider provisions on first sign-in — there was
    nobody at a keyboard to show a notice to."""
    actor = await acting_user()

    me = await client.get("/api/v1/me", headers=actor.headers)

    assert me.status_code == 200
    assert me.json()["legal_acceptance_required"] is True


async def test_nobody_is_asked_on_a_deployment_with_no_terms(
    client: AsyncClient, acting_user, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", None)
    actor = await acting_user()

    me = await client.get("/api/v1/me", headers=actor.headers)

    assert me.json()["legal_acceptance_required"] is False


async def test_accepting_settles_it(
    client: AsyncClient, session: AsyncSession, acting_user, hosted
):
    actor = await acting_user()

    accepted = await client.post("/api/v1/me/legal-acceptance", headers=actor.headers)

    assert accepted.status_code == 200
    assert accepted.json()["legal_acceptance_required"] is False
    rows = await _rows(session, actor.user.id)
    assert [(r.document, r.version, r.document_sha256) for r in rows] == [
        ("terms", "2.1", "a" * 64),
        ("privacy", "1.4", "b" * 64),
    ]

    me = await client.get("/api/v1/me", headers=actor.headers)
    assert me.json()["legal_acceptance_required"] is False


async def test_accepting_twice_does_not_write_it_twice(
    client: AsyncClient, session: AsyncSession, acting_user, hosted
):
    """The screen only shows while something is outstanding, so a second POST
    is a double-submit rather than consent to a new revision."""
    actor = await acting_user()

    await client.post("/api/v1/me/legal-acceptance", headers=actor.headers)
    await client.post("/api/v1/me/legal-acceptance", headers=actor.headers)

    rows = await _rows(session, actor.user.id)
    assert [r.document for r in rows] == ["terms", "privacy"]


async def test_there_is_nothing_to_accept_on_a_self_hosted_deployment(
    client: AsyncClient, acting_user, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", None)
    actor = await acting_user()

    response = await client.post("/api/v1/me/legal-acceptance", headers=actor.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == LegalMessages.NOT_CONFIGURED


async def test_a_consent_record_is_one_account_s_own(
    client: AsyncClient, acting_user, role_session, hosted
):
    """The row policy is own-row, so one account's agreement is invisible to
    another's session even though both run as the same platform tier.

    Asserted on a real ``app_user`` connection — the superuser-backed session
    fixture would let a missing policy pass — and in both directions, because
    a policy that admits nothing would also pass the first half.
    """
    from app.db.session import set_rls_context

    mine = await acting_user()
    theirs = await acting_user()
    await client.post("/api/v1/me/legal-acceptance", headers=mine.headers)
    await client.post("/api/v1/me/legal-acceptance", headers=theirs.headers)

    scoped = await role_session("app_user")
    await set_rls_context(
        scoped, Platform(user_id=theirs.user.id, tier=theirs.user.role.value)
    )
    rows = (await scoped.exec(select(LegalAcceptance.user_id))).all()

    assert set(rows) == {theirs.user.id}


async def _rows(session: AsyncSession, user_id: int) -> list[LegalAcceptance]:
    return list(
        (
            await session.exec(
                select(LegalAcceptance)
                .where(LegalAcceptance.user_id == user_id)
                .order_by(LegalAcceptance.id)
            )
        ).all()
    )
