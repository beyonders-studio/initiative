from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import (
    SALT_OIDC_CLIENT_SECRET,
    decrypt_field,
    decrypt_token,
    encrypt_token,
)
from app.db import session as db_session
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.federated_identity_secret import FederatedIdentitySecret
from app.models.platform.user import User
from app.services.oidc_sync import (
    extract_claim_values,
    placement_claims,
    sync_oidc_assignments,
)
from app.services.platform import provider_placement

logger = logging.getLogger(__name__)

OIDC_SYNC_POLL_SECONDS = 300  # 5 minutes
_SYNC_INTERVAL = timedelta(minutes=15)


async def _fetch_oidc_metadata(issuer_url: str) -> dict:
    normalized = issuer_url.rstrip("/")
    well_known_suffix = "/.well-known/openid-configuration"
    normalized = normalized.removesuffix(well_known_suffix)
    discovery_url = f"{normalized}{well_known_suffix}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        return resp.json()


async def _refresh_and_sync_identity(
    session: AsyncSession,
    *,
    identity: FederatedIdentity,
    secret: FederatedIdentitySecret,
    user: User,
    token_endpoint: str,
    userinfo_endpoint: str,
    client_id: str,
    client_secret: str,
    claim_path: str | None,
    placement_claim_names: set[str],
) -> bool:
    """Refresh one identity link's token and sync claims. True on success.

    ``placement_claim_names`` are the claims the provider's rules are decided
    by besides the groups (:func:`placement_claims`). A refresh that carries no
    id_token and whose userinfo lacks one of them is not reconciled this pass:
    those claims are read from the id_token at sign-in, and a reconciliation
    without them would read as an arrival none of the rules count.
    """
    try:
        refresh_token = decrypt_token(secret.refresh_token_encrypted)
    except Exception:
        logger.warning("Failed to decrypt refresh token for user %s; clearing", user.id)
        secret.refresh_token_encrypted = None
        session.add(secret)
        await session.commit()
        return False

    token_payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(token_endpoint, data=token_payload)
            if token_resp.status_code in (400, 401):
                logger.warning(
                    "Refresh token revoked/expired for user %s (HTTP %d); clearing",
                    user.id,
                    token_resp.status_code,
                )
                secret.refresh_token_encrypted = None
                session.add(secret)
                await session.commit()
                return False
            token_resp.raise_for_status()
            token_data = token_resp.json()

            access_token = token_data.get("access_token")
            if not access_token:
                logger.warning(
                    "No access_token in refresh response for user %s", user.id
                )
                return False

            # Handle token rotation - commit immediately to prevent loss
            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                secret.refresh_token_encrypted = encrypt_token(new_refresh)
                session.add(secret)
                await session.commit()

            # Fetch userinfo
            userinfo_resp = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            profile = userinfo_resp.json()
    except httpx.HTTPStatusError:
        logger.exception("HTTP error during OIDC refresh for user %s", user.id)
        return False
    except httpx.RequestError:
        logger.exception("Network error during OIDC refresh for user %s", user.id)
        return False

    # Decode id_token claims if present
    id_token_claims = None
    raw_id_token = token_data.get("id_token")
    if raw_id_token:
        parts = raw_id_token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            try:
                id_token_claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            except (ValueError, binascii.Error) as exc:
                # Claims are optional here — the provider's userinfo response is
                # the primary source. A malformed id_token payload just means we
                # proceed without its claims, but log it so a misbehaving
                # provider is diagnosable rather than silently ignored.
                logger.debug(
                    "Could not decode OIDC id_token claims for user %s: %s",
                    user.id,
                    exc,
                )

    claim_values = (
        extract_claim_values(profile, id_token_claims, claim_path)
        if claim_path
        else set()
    )
    # The id_token came straight from the token endpoint; userinfo fills in
    # what it does not carry, as it does at sign-in.
    claims = dict(id_token_claims or {})
    for key, value in profile.items():
        claims.setdefault(key, value)
    if id_token_claims is None:
        missing = sorted(
            name
            for name in placement_claim_names
            if not extract_claim_values(claims, None, name)
        )
        if missing:
            logger.info(
                "OIDC refresh sync for %s: no id_token and userinfo lacks %s; "
                "memberships left as they are until the next sign-in or refresh",
                user.id,
                ", ".join(missing),
            )
            identity.last_synced_at = datetime.now(UTC)
            session.add(identity)
            await session.commit()
            return True
    sync_result = await sync_oidc_assignments(
        session,
        user_id=user.id,
        # The link being refreshed says whose claims these are, so the
        # reconciliation reaches only what that provider granted.
        provider_id=identity.provider_id,
        claim_values=claim_values,
        claims=claims,
    )
    logger.info(
        "OIDC refresh sync for %s: +%d/~%d/-%d guilds, +%d/~%d/-%d initiatives",
        user.id,
        len(sync_result.guilds_added),
        len(sync_result.guilds_updated),
        len(sync_result.guilds_removed),
        len(sync_result.initiatives_added),
        len(sync_result.initiatives_updated),
        len(sync_result.initiatives_removed),
    )

    identity.last_synced_at = datetime.now(UTC)
    session.add(identity)
    await session.commit()
    return True


async def process_oidc_refresh_sync() -> None:
    """Re-read claims for every provider whose arrivals are reconciled
    against its rules (:func:`provider_placement.syncs_placement`).

    Each provider is swept on its own: its identities, its claim path, its
    credentials. A membership one provider granted is reconciled by that
    provider's sweep and no other.
    """
    async with db_session.SystemSessionLocal() as session:
        provider_ids = (
            await session.exec(
                select(AuthProvider.id).where(
                    AuthProvider.enabled == True,
                    provider_placement.syncs_placement(),
                    AuthProvider.issuer.is_not(None),
                    AuthProvider.client_id.is_not(None),
                )
            )
        ).all()

    # A session each, rather than one shared across the loop. A sweep commits
    # as it goes, so a shared session would carry one provider's half-finished
    # transaction into the next, and a failure would leave every provider after
    # it querying a session that has nothing to give.
    for provider_id in provider_ids:
        try:
            async with db_session.SystemSessionLocal() as session:
                provider = await session.get(AuthProvider, provider_id)
                if provider is None:
                    continue
                await _sweep_provider(session, provider)
        except Exception:
            logger.exception(
                "oidc-refresh-sync: provider %s did not complete", provider_id
            )


async def _sweep_provider(session: AsyncSession, provider: AuthProvider) -> None:
    claim_path = provider.role_claim_path
    if not provider.issuer or not provider.client_id:
        return
    if not await provider_placement.provider_syncs_placement(
        session, provider_id=provider.id
    ):
        return
    secret_row = await session.get(AuthProviderSecret, provider.id)
    secret_ciphertext = secret_row.client_secret_encrypted if secret_row else None
    if not secret_ciphertext:
        return

    try:
        metadata = await _fetch_oidc_metadata(provider.issuer)
    except Exception:
        logger.exception(
            "Failed to fetch OIDC metadata for background sync (provider %s)",
            provider.slug,
        )
        return

    token_endpoint = metadata.get("token_endpoint")
    userinfo_endpoint = metadata.get("userinfo_endpoint")
    if not token_endpoint or not userinfo_endpoint:
        logger.warning(
            "OIDC metadata missing token/userinfo endpoint for provider %s; "
            "skipping sync",
            provider.slug,
        )
        return

    cutoff = datetime.now(UTC) - _SYNC_INTERVAL
    stmt = (
        select(FederatedIdentity, FederatedIdentitySecret, User)
        .join(
            FederatedIdentitySecret,
            FederatedIdentitySecret.identity_id == FederatedIdentity.id,
        )
        .join(User, User.id == FederatedIdentity.user_id)
        .where(
            FederatedIdentity.provider_id == provider.id,
            FederatedIdentitySecret.refresh_token_encrypted.is_not(None),
            (FederatedIdentity.last_synced_at < cutoff)
            | FederatedIdentity.last_synced_at.is_(None),
        )
    )
    due = (await session.exec(stmt)).all()

    if not due:
        logger.debug(
            "oidc-refresh-sync: no identities due for provider %s", provider.slug
        )
        return

    placement_claim_names = await placement_claims(session, provider_id=provider.id)
    succeeded = 0
    revoked = 0
    for identity, secret, user in due:
        ok = await _refresh_and_sync_identity(
            session,
            identity=identity,
            secret=secret,
            user=user,
            token_endpoint=token_endpoint,
            userinfo_endpoint=userinfo_endpoint,
            client_id=provider.client_id,
            client_secret=decrypt_field(secret_ciphertext, SALT_OIDC_CLIENT_SECRET),
            claim_path=claim_path,
            placement_claim_names=placement_claim_names,
        )
        if ok:
            succeeded += 1
        elif secret.refresh_token_encrypted is None:
            revoked += 1

    logger.info(
        "OIDC refresh sync (%s): processed %d identities, %d succeeded, "
        "%d token(s) revoked",
        provider.slug,
        len(due),
        succeeded,
        revoked,
    )
