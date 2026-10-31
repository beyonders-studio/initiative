"""CRUD tests for the login provider registry owner endpoints."""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_OIDC_CLIENT_SECRET, decrypt_field
from app.db.session import set_rls_context
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.user import UserRole
from app.models.tenant.claim_rule_initiative import ClaimRuleInitiative
from app.models.tenant.initiative import InitiativeMember
from app.testing import route_session_to_guild
from app.testing.factories import (
    create_auth_provider,
    create_claim_rule,
    create_federated_identity,
    create_guild,
    create_initiative,
    create_initiative_member,
    create_user,
    get_auth_headers,
)
from app.db.request_context import Unattributed


BASE = "/api/v1/settings/auth/providers/"

_VALID_CREATE = {
    "slug": "corp",
    "display_name": "Corp SSO",
    "issuer": "https://idp.example.com",
    "client_id": "client-123",
    "client_secret": "s3cret-value",
}


async def _owner_headers(session: AsyncSession) -> dict[str, str]:
    owner = await create_user(session, role=UserRole.owner)
    return get_auth_headers(owner)


async def test_owner_creates_provider_secret_write_only(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    response = await client.post(BASE, headers=headers, json=_VALID_CREATE)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"] == "corp"
    assert body["secret_set"] is True
    # What the operator registers with their IdP, following the slug.
    assert body["callback_url"].endswith("/api/v1/auth/corp/callback")
    assert "client_secret" not in body
    assert "s3cret-value" not in response.text

    row = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "corp"))
    ).one()
    secret = await session.get(AuthProviderSecret, row.id)
    assert decrypt_field(secret.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET) == (
        "s3cret-value"
    )


@pytest.mark.parametrize("role", [UserRole.member, UserRole.operator])
async def test_non_owner_tiers_are_refused(
    client: AsyncClient, session: AsyncSession, role: UserRole
):
    """config.manage is owner-only; every verb refuses lower tiers."""
    user = await create_user(session, role=role)
    headers = get_auth_headers(user)
    provider = await create_auth_provider(session)

    assert (await client.get(BASE, headers=headers)).status_code == 403
    assert (
        await client.post(BASE, headers=headers, json=_VALID_CREATE)
    ).status_code == 403
    assert (
        await client.patch(
            f"{BASE}{provider.id}", headers=headers, json={"display_name": "X"}
        )
    ).status_code == 403
    assert (
        await client.delete(f"{BASE}{provider.id}", headers=headers)
    ).status_code == 403


async def test_the_platform_slug_is_an_ordinary_slug(
    client: AsyncClient, session: AsyncSession
):
    """``oidc`` is the slug the pre-generalization callback URL resolves to,
    and that is all it is: it creates, edits and deletes like any other."""
    headers = await _owner_headers(session)
    platform_row = await create_auth_provider(session, slug="oidc")

    update = await client.patch(
        f"{BASE}{platform_row.id}", headers=headers, json={"display_name": "X"}
    )
    assert update.status_code == 200, update.text
    assert update.json()["display_name"] == "X"

    listing = await client.get(BASE, headers=headers)
    entries = {e["slug"]: e for e in listing.json()}
    # The address an install has already registered with its IdP.
    assert entries["oidc"]["callback_url"].endswith("/api/v1/auth/oidc/callback")

    assert (
        await client.delete(f"{BASE}{platform_row.id}", headers=headers)
    ).status_code == 204


async def test_a_providers_address_is_fixed_for_its_lifetime(
    client: AsyncClient, session: AsyncSession
):
    """The callback URL follows the slug and a slug never changes, so the
    address an operator registers with their IdP is good for as long as the
    provider is — which is what makes showing it worth doing."""
    headers = await _owner_headers(session)
    row = await create_auth_provider(session, slug="corp")

    before = (await client.get(BASE, headers=headers)).json()[0]["callback_url"]
    await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"display_name": "Renamed", "slug": "acme"},
    )
    after = (await client.get(BASE, headers=headers)).json()[0]

    assert after["display_name"] == "Renamed"
    assert after["slug"] == "corp"
    assert after["callback_url"] == before


async def test_duplicate_slug_conflicts(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)
    await create_auth_provider(session, slug="corp")

    response = await client.post(BASE, headers=headers, json=_VALID_CREATE)
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_SLUG_TAKEN"


async def test_non_https_issuer_rejected(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)
    response = await client.post(
        BASE,
        headers=headers,
        json={**_VALID_CREATE, "issuer": "http://idp.example.com"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("slug", ["corp-", "-corp", "Corp", "a" * 65])
async def test_malformed_slug_rejected(
    client: AsyncClient, session: AsyncSession, slug: str
):
    """Slugs form the login URLs: lowercase alphanumerics and inner dashes
    only, no leading/trailing dash."""
    headers = await _owner_headers(session)
    response = await client.post(
        BASE, headers=headers, json={**_VALID_CREATE, "slug": slug}
    )
    assert response.status_code == 422, slug


async def test_update_secret_semantics(client: AsyncClient, session: AsyncSession):
    """client_secret: absent = keep, empty = clear, value = replace."""
    headers = await _owner_headers(session)
    created = await client.post(BASE, headers=headers, json=_VALID_CREATE)
    provider_id = created.json()["id"]

    kept = await client.patch(
        f"{BASE}{provider_id}", headers=headers, json={"display_name": "Renamed"}
    )
    assert kept.status_code == 200
    assert kept.json()["display_name"] == "Renamed"
    assert kept.json()["secret_set"] is True

    replaced = await client.patch(
        f"{BASE}{provider_id}", headers=headers, json={"client_secret": "rotated"}
    )
    assert replaced.json()["secret_set"] is True
    row_id = replaced.json()["id"]
    secret = await session.get(AuthProviderSecret, row_id)
    await session.refresh(secret)
    assert (
        decrypt_field(secret.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET)
        == "rotated"
    )

    cleared = await client.patch(
        f"{BASE}{provider_id}", headers=headers, json={"client_secret": ""}
    )
    assert cleared.json()["secret_set"] is False
    # Clearing removes the companion row rather than leaving an empty one.
    session.expire_all()
    assert await session.get(AuthProviderSecret, provider_id) is None


async def test_update_rejects_explicit_null_on_required_config(
    client: AsyncClient, session: AsyncSession
):
    """An explicit null on issuer/client_id/display_name would leave an
    enabled provider the login flow refuses — rejected at the schema."""
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session)

    for field_name in ("issuer", "client_id", "display_name", "enabled"):
        response = await client.patch(
            f"{BASE}{provider.id}", headers=headers, json={field_name: None}
        )
        assert response.status_code == 422, field_name


async def test_delete_cascades_identity_links(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    user = await create_user(session)
    await create_federated_identity(session, user, provider=provider)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    member = await create_initiative_member(
        session, initiative, await create_user(session)
    )
    member.oidc_provider_id = provider.id
    session.add(member)
    await session.commit()
    rule = await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        initiative=initiative,
        initiative_role_id=member.role_id,
    )
    await set_rls_context(session, Unattributed())
    provider_id, user_id, guild_id = provider.id, user.id, guild.id
    managed = (member.initiative_id, member.user_id)
    rule_id = rule.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 204

    session.expire_all()
    assert (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "corp"))
    ).one_or_none() is None
    identities = (
        await session.exec(
            select(FederatedIdentity).where(FederatedIdentity.user_id == user_id)
        )
    ).all()
    assert identities == []
    # The initiative membership the provider managed is released in the
    # guild's schema.
    await route_session_to_guild(session, guild_id)
    released = (
        await session.exec(
            select(InitiativeMember.oidc_provider_id).where(
                InitiativeMember.initiative_id == managed[0],
                InitiativeMember.user_id == managed[1],
            )
        )
    ).one()
    assert released is None
    # Its rules go with it, and so does the initiative one placed people in.
    assert await session.get(ClaimRuleInitiative, rule_id) is None


async def test_delete_refused_when_provider_is_a_sole_credential(
    client: AsyncClient, session: AsyncSession
):
    """An account with no password, linked only to this provider, holds it as
    its only credential — so the delete is refused."""
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    sso_only = await create_user(session, hashed_password=None)
    await create_federated_identity(session, sso_only, provider=provider)
    provider_id = provider.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_SOLE_CREDENTIAL"

    session.expire_all()
    assert await session.get(AuthProvider, provider_id) is not None


async def test_delete_allowed_when_account_holds_another_provider(
    client: AsyncClient, session: AsyncSession
):
    """A second link is another way in, so the provider is free to go."""
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    spare = await create_auth_provider(session, slug="spare")
    sso_only = await create_user(session, hashed_password=None)
    await create_federated_identity(session, sso_only, provider=provider)
    await create_federated_identity(session, sso_only, provider=spare)
    provider_id = provider.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 204

    session.expire_all()
    assert await session.get(AuthProvider, provider_id) is None


async def test_delete_refused_when_the_stored_hash_cannot_verify(
    client: AsyncClient, session: AsyncSession
):
    """A hash no scheme accepts is not a password. The 0152 downgrade writes
    ``'!'`` into rows that had none, and such an account still reaches its
    account only through the provider."""
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    marked = await create_user(session, hashed_password="!")
    await create_federated_identity(session, marked, provider=provider)
    provider_id = provider.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_SOLE_CREDENTIAL"


async def test_delete_refused_when_the_only_other_provider_is_disabled(
    client: AsyncClient, session: AsyncSession
):
    """A disabled provider cannot serve a login, so a link to one is not a
    second way in."""
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    dormant = await create_auth_provider(session, slug="dormant", enabled=False)
    sso_only = await create_user(session, hashed_password=None)
    await create_federated_identity(session, sso_only, provider=provider)
    await create_federated_identity(session, sso_only, provider=dormant)
    provider_id = provider.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_SOLE_CREDENTIAL"


async def test_delete_refused_when_the_only_other_provider_is_the_secretless_platform_row(
    client: AsyncClient, session: AsyncSession
):
    """The platform login has always needed a stored client secret — PKCE-only
    is a guild-provider affordance — so a platform row without one cannot
    answer a login and is not a second way in."""
    from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG

    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    platform = await create_auth_provider(session, slug=PLATFORM_OIDC_SLUG)
    sso_only = await create_user(session, hashed_password=None)
    await create_federated_identity(session, sso_only, provider=provider)
    await create_federated_identity(session, sso_only, provider=platform)
    provider_id = provider.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_SOLE_CREDENTIAL"


async def test_delete_allowed_when_the_platform_row_carries_its_secret(
    client: AsyncClient, session: AsyncSession
):
    """With the secret stored, the platform row can answer a login, so it is a
    real alternative and the delete goes ahead."""
    from app.services.auth import provider_registry
    from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG

    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    platform = await create_auth_provider(session, slug=PLATFORM_OIDC_SLUG)
    await provider_registry.set_provider_secret(session, platform.id, "s3cret")
    await session.commit()
    sso_only = await create_user(session, hashed_password=None)
    await create_federated_identity(session, sso_only, provider=provider)
    await create_federated_identity(session, sso_only, provider=platform)
    provider_id = provider.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 204


async def test_created_provider_reaches_login_page_listing(
    client: AsyncClient, session: AsyncSession
):
    """A CRUD-created, enabled provider is offered by the public login-page
    listing; a disabled one is not."""
    headers = await _owner_headers(session)
    await client.post(BASE, headers=headers, json=_VALID_CREATE)
    await client.post(
        BASE,
        headers=headers,
        json={**_VALID_CREATE, "slug": "dark", "enabled": False},
    )

    listing = await client.get("/api/v1/auth/providers")
    slugs = [p["slug"] for p in listing.json()["providers"]]
    assert "corp" in slugs
    assert "dark" not in slugs
