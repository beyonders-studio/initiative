"""What one provider sign-in does to the session behind it.

A step-up unions what the live session had already proved rather than starting
over, each provider keeps its own account of its own event, and the session it
replaces is revoked. None of that is about which community somebody is
heading for — see ``guild_gate_test`` for that.

Runs against the same fake IdP harness as the operator flow tests."""

from urllib.parse import parse_qs, urlsplit

import httpx2
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.auth_test import _wire_fake_idp
from app.core.encryption import hash_email
from app.core.security import REFRESH_COOKIE_NAME
from app.models.platform.auth_session import AuthSession
from app.models.platform.user_email import UserEmail
from app.services.auth import sessions as session_service
from app.services.auth import sign_in_locks
from app.testing.factories import (
    create_auth_provider,
    create_federated_identity,
    create_user,
)
from app.testing.oidc import ISSUER as OIDC_ISSUER
from app.testing.oidc import FakeIdp, mint_id_token


async def _a_provider(session: AsyncSession, **overrides):
    """A login-ready provider on the deployment."""
    return await create_auth_provider(session, slug="corp", **overrides)


async def _begin_login(
    client: AsyncClient, slug: str = "corp", params: dict | None = None
) -> tuple[str, str]:
    response = await client.get(
        f"/api/v1/auth/{slug}/login",
        params=params or {},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307), response.text
    location = response.headers["location"]
    assert location.startswith(f"{OIDC_ISSUER}/authorize?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    return query["state"], query["nonce"]


async def _run_flow(
    client: AsyncClient,
    idp: FakeIdp,
    *,
    slug: str = "corp",
    id_token_claims: dict | None = None,
):
    """Begin and complete one sign-in; returns the callback response."""
    state, nonce = await _begin_login(client, slug)
    idp.token_response = httpx2.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": mint_id_token(nonce=nonce, **(id_token_claims or {})),
            "token_type": "Bearer",
        },
    )
    return await client.get(
        f"/api/v1/auth/{slug}/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )


async def _latest_session(session: AsyncSession) -> AuthSession | None:
    session.expire_all()
    rows = (
        await session.exec(select(AuthSession).order_by(AuthSession.created_at.desc()))
    ).all()
    return rows[0] if rows else None


async def test_step_up_unions_satisfied_providers(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Completing a step-up carries the live session's satisfied set forward
    and revokes the session it replaces."""
    provider = await _a_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[41414],
    )
    await session.commit()
    prior_id = issued.session.id
    provider_id, provider_slug = provider.id, provider.slug
    refresh_token = issued.refresh_token
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    client.cookies.set(REFRESH_COOKIE_NAME, refresh_token)
    try:
        response = await _run_flow(client, idp)
    finally:
        client.cookies.delete(REFRESH_COOKIE_NAME)
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    row = await _latest_session(session)
    assert row is not None
    assert row.id != prior_id
    assert row.satisfied_providers == sorted([41414, provider_id])
    assert set(row.amr) >= {"pwd", f"oidc:{provider_slug}"}

    prior = await session.get(AuthSession, prior_id)
    assert prior is not None and prior.revoked_at is not None


async def test_a_provider_records_the_address_it_asserts(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An account a directory *links* rather than provisions already had an
    address. The one the directory asserts for it is new information, and it
    is kept against the provider that asserted it. The sign-in starts the
    account's count of wrong answers over, as every sign-in does."""
    from sqlmodel import select as sqlmodel_select

    from app.models.platform.sign_in_lock import SignInLock
    from app.models.platform.user_email_assertion import UserEmailAssertion

    provider = await _a_provider(session)
    user = await create_user(session, email="alice@personal.example.com")
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    user_id, provider_id = user.id, provider.id
    await sign_in_locks.record_failure(session, user_id)
    await session.commit()
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_flow(
        client,
        idp,
        id_token_claims={
            "email": "alice@acme.example.com",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    session.expire_all()
    assert (await session.get(SignInLock, user_id)).failures == 0
    rows = (
        await session.exec(
            sqlmodel_select(UserEmail).where(UserEmail.user_id == user_id)
        )
    ).all()
    held = {r.email_hash: r for r in rows}
    personal = held[hash_email("alice@personal.example.com")]
    work = held[hash_email("alice@acme.example.com")]
    assert (personal.is_primary, work.is_primary) == (True, False)

    claims = (
        await session.exec(
            sqlmodel_select(UserEmailAssertion).where(
                UserEmailAssertion.user_email_id.in_([personal.id, work.id])
            )
        )
    ).all()
    # The directory claims the address it asserted, and only that one.
    assert [(c.user_email_id, c.provider_id) for c in claims] == [
        (work.id, provider_id)
    ]


async def test_step_up_rewrites_only_the_stepping_providers_account(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Each provider's account of its own authentication stands on its own: a
    step-up into one guild's IdP records that IdP's claims and leaves the
    other provider's entry exactly as it was."""
    provider = await _a_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    elsewhere = {"41414": {"auth_time": 1757000000, "amr": ["pwd"], "acr": "loa1"}}
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[41414],
        provider_auth=elsewhere,
    )
    await session.commit()
    provider_id = provider.id
    refresh_token = issued.refresh_token
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    client.cookies.set(REFRESH_COOKIE_NAME, refresh_token)
    try:
        response = await _run_flow(
            client,
            idp,
            id_token_claims={"amr": ["mfa", "hwk"], "auth_time": 1757600000},
        )
    finally:
        client.cookies.delete(REFRESH_COOKIE_NAME)
    assert response.status_code in (302, 307), response.text

    row = await _latest_session(session)
    assert row is not None
    assert row.provider_auth == {
        "41414": {"auth_time": 1757000000, "amr": ["pwd"], "acr": "loa1"},
        str(provider_id): {"auth_time": 1757600000, "amr": ["mfa", "hwk"]},
    }


async def test_step_up_revokes_racing_rotation_child(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A /auth/refresh that rotates the presented session between the
    callback's read and its write must not leave the rotation child running
    beside the stepped-up session: the replacement chain-revokes. Simulated
    by rotating for real and pinning the callback's read to the original
    row (the pre-rotation interleaving)."""
    import app.api.v1.platform_endpoints.auth as auth_module

    provider = await _a_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[41414]
    )
    await session.commit()
    prior_id = issued.session.id
    provider_id = provider.id

    rotation = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    await session.commit()
    assert rotation.ok and rotation.issued is not None
    child_id = rotation.issued.session.id

    async def _read_prior(system_session, raw):
        return await system_session.get(AuthSession, prior_id)

    monkeypatch.setattr(
        auth_module.session_service, "get_live_session_by_refresh_token", _read_prior
    )
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    client.cookies.set(REFRESH_COOKIE_NAME, issued.refresh_token)
    try:
        response = await _run_flow(client, idp)
    finally:
        client.cookies.delete(REFRESH_COOKIE_NAME)
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    row = await _latest_session(session)
    assert row is not None
    assert row.id not in (prior_id, child_id)
    assert row.satisfied_providers == sorted([41414, provider_id])
    assert row.revoked_at is None

    child = await session.get(AuthSession, child_id)
    assert child is not None and child.revoked_at is not None
