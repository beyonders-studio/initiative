"""The scheduled sweep that re-reads group claims.

About the things that are invisible when they break: the sweep visits every
provider sign-in reconciles, a provider it cannot finish is skipped rather than
taking the rest of the run with it, and a refresh that cannot say what a rule is
decided by leaves memberships where they are.
"""

import base64
import json

import httpx2
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_OIDC_CLIENT_SECRET, encrypt_field
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.oidc_claim_mapping import (
    ClaimRuleAuthor,
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.services import oidc_refresh
from app.services.auth.identity import set_identity_refresh_token
from app.services.oidc_sync import sync_oidc_assignments
from app.testing.factories import (
    NARROWED_CLAIM,
    NARROWED_VALUE,
    create_auth_provider,
    create_federated_identity,
    create_guild,
    create_guild_provider_connection,
    create_user,
)


async def _configured(session: AsyncSession, slug: str):
    """A provider the sweep will pick up: enabled, with a claim path."""
    return await create_auth_provider(
        session,
        slug=slug,
        enabled=True,
        issuer=f"https://{slug}.example.com",
        client_id=f"{slug}-client",
        role_claim_path="groups",
    )


async def test_every_configured_provider_is_visited(session, monkeypatch):
    await _configured(session, "corp")
    await _configured(session, "partner")
    # Enabled, but asserts no groups — nothing for this sweep to read.
    await create_auth_provider(
        session, slug="social", enabled=True, role_claim_path=None
    )
    # Asserts no groups either, but a rule of its own places by directory.
    bridge = await create_auth_provider(
        session,
        slug="bridge",
        enabled=True,
        issuer="https://bridge.example.com",
        client_id="bridge-client",
        role_claim_path=None,
    )
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    session.add(_directory_rule(provider_id=bridge.id, guild_id=guild.id))
    await session.commit()

    seen: list[str] = []

    async def _record(_session, provider):
        seen.append(provider.slug)

    monkeypatch.setattr(oidc_refresh, "_sweep_provider", _record)
    await oidc_refresh.process_oidc_refresh_sync()

    assert sorted(seen) == ["bridge", "corp", "partner"]


async def test_a_provider_that_fails_does_not_take_the_others_with_it(
    session, monkeypatch
):
    """Each provider is swept in a session of its own, so the one after a
    failure still has a usable transaction to work in."""
    await _configured(session, "aaa-broken")
    await _configured(session, "zzz-healthy")
    await session.commit()

    finished: list[str] = []

    async def _sometimes_fails(db_session, provider):
        if provider.slug == "aaa-broken":
            # A database error, not a network one — the server aborts the
            # transaction, which is the state a shared session would carry
            # into the provider swept next.
            await db_session.exec(text("SELECT this_is_not_a_column"))
        # Proves the session handed to this provider can still do work.
        await db_session.exec(text("SELECT 1"))
        finished.append(provider.slug)

    monkeypatch.setattr(oidc_refresh, "_sweep_provider", _sometimes_fails)
    await oidc_refresh.process_oidc_refresh_sync()

    assert finished == ["zzz-healthy"]


# ── A directory-only rule, re-checked by the sweep ───────────────────────────

_TOKEN_ENDPOINT = "https://bridge.example.com/token"
_USERINFO_ENDPOINT = "https://bridge.example.com/userinfo"
_REAL_ASYNC_CLIENT = httpx2.AsyncClient


def _directory_rule(*, provider_id: int, guild_id: int) -> OIDCClaimMapping:
    """A provider rule that places everybody from one upstream directory."""
    return OIDCClaimMapping(
        author=ClaimRuleAuthor.provider,
        provider_id=provider_id,
        claim_value=None,
        scope_claim="idp",
        scope_value="acme-adfs",
        target_type=OIDCMappingTargetType.guild,
        guild_id=guild_id,
        guild_role=CommunityRole.member.value,
    )


def _unsigned_jwt(claims: dict) -> str:
    def _part(data: dict) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{_part({'alg': 'none'})}.{_part(claims)}.sig"


def _idp(monkeypatch, *, id_token_claims: dict | None, userinfo: dict) -> None:
    """Answer the sweep's discovery, token and userinfo calls."""

    async def _metadata(_issuer: str) -> dict:
        return {
            "token_endpoint": _TOKEN_ENDPOINT,
            "userinfo_endpoint": _USERINFO_ENDPOINT,
        }

    def _handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == _TOKEN_ENDPOINT:
            body: dict = {"access_token": "access"}
            if id_token_claims is not None:
                body["id_token"] = _unsigned_jwt(id_token_claims)
            return httpx2.Response(200, json=body)
        return httpx2.Response(200, json=userinfo)

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx2.MockTransport(_handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(oidc_refresh, "_fetch_oidc_metadata", _metadata)
    monkeypatch.setattr(oidc_refresh.httpx2, "AsyncClient", _client)


async def _placed_by_directory(session: AsyncSession):
    """A bridge provider reporting no groups, a community that accepts its
    rules, and somebody its directory-only rule placed there at sign-in."""
    provider = await create_auth_provider(
        session,
        slug="bridge",
        issuer="https://bridge.example.com",
        client_id="bridge-client",
        role_claim_path=None,
    )
    session.add(
        AuthProviderSecret(
            provider_id=provider.id,
            client_secret_encrypted=encrypt_field("secret", SALT_OIDC_CLIENT_SECRET),
        )
    )
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, accepts_provider_placement=True
    )
    session.add(_directory_rule(provider_id=provider.id, guild_id=guild.id))
    person = await create_user(session)
    identity = await create_federated_identity(session, person, provider=provider)
    identity_id = identity.id
    await set_identity_refresh_token(
        session, identity_id=identity_id, refresh_token="refresh"
    )
    await session.commit()

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=provider.id,
        claim_values=set(),
        claims={NARROWED_CLAIM: NARROWED_VALUE, "idp": "acme-adfs"},
    )
    await session.commit()
    assert await _joined(session, person.id) == {guild.id}
    return provider, guild, person, identity_id


async def _joined(session: AsyncSession, user_id: int) -> set[int]:
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    return set(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )


async def _sweep(session: AsyncSession, provider_id: int) -> None:
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    provider = await session.get(AuthProvider, provider_id)
    await oidc_refresh._sweep_provider(session, provider)


async def test_the_sweep_releases_somebody_who_left_the_directory(session, monkeypatch):
    """A provider that reports no groups is still swept when a rule of its own
    places by directory, and an arrival now from another directory hands back
    what that rule gave them."""
    provider, _guild, person, _identity_id = await _placed_by_directory(session)
    _idp(
        monkeypatch,
        id_token_claims={NARROWED_CLAIM: NARROWED_VALUE, "idp": "globex-okta"},
        userinfo={"sub": "someone"},
    )

    await _sweep(session, provider.id)

    assert await _joined(session, person.id) == set()


async def test_the_sweep_keeps_somebody_still_in_the_directory(session, monkeypatch):
    provider, guild, person, _identity_id = await _placed_by_directory(session)
    _idp(
        monkeypatch,
        id_token_claims={NARROWED_CLAIM: NARROWED_VALUE, "idp": "acme-adfs"},
        userinfo={"sub": "someone"},
    )

    await _sweep(session, provider.id)

    assert await _joined(session, person.id) == {guild.id}


async def test_a_refresh_without_an_id_token_leaves_memberships_alone(
    session, monkeypatch
):
    """The directory and the community's narrowing are read from the id_token.
    A refresh that returns none, with userinfo that carries neither, is not
    reconciled this pass — and the link is stamped, so it waits its turn."""
    provider, guild, person, identity_id = await _placed_by_directory(session)
    _idp(monkeypatch, id_token_claims=None, userinfo={"sub": "someone"})

    await _sweep(session, provider.id)

    assert await _joined(session, person.id) == {guild.id}
    identity = await session.get(FederatedIdentity, identity_id)
    assert identity is not None and identity.last_synced_at is not None


async def test_a_refresh_without_an_id_token_reads_userinfo_when_it_has_them(
    session, monkeypatch
):
    """Userinfo carrying the claims the rules are decided by is enough to
    reconcile on."""
    provider, _guild, person, _identity_id = await _placed_by_directory(session)
    _idp(
        monkeypatch,
        id_token_claims=None,
        userinfo={NARROWED_CLAIM: NARROWED_VALUE, "idp": "globex-okta"},
    )

    await _sweep(session, provider.id)

    assert await _joined(session, person.id) == set()
