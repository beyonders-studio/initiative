"""The operator-global platform OIDC provider — registry-row native.

The ``auth_providers`` row with slug ``oidc`` is the
**single source of truth** for the platform provider: the settings endpoints
write it directly, the login path and refresh sweep read it, and the client
secret lives in its ``auth_provider_secrets`` companion (write-only, shared
Fernet salt with the retired ``app_settings`` column). The old
reconcile-from-``app_settings`` shim is gone; migration 0153 folded the last
column state into the row and dropped the columns.

``OIDC_*`` env values remain a **first-boot seed only**: when no platform row
exists and the env carries an issuer + client id, :func:`seed_platform_provider_from_env`
creates the row once at startup. After that the row is owned by the settings
UI — the env never overwrites it.

Runs on the system engine (``auth_providers`` / ``auth_provider_secrets``
carry no request-path grants); callers pass their system session.
"""

from __future__ import annotations

import logging

from sqlalchemy import ColumnElement, and_, not_, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind
from app.models.platform.auth_provider_secret import AuthProviderSecret

logger = logging.getLogger(__name__)

# Fixed slug for the one platform provider: stable so every caller (login
# path, settings endpoints, refresh sweep) finds the same row. It is also the
# reason the pre-generalization /auth/oidc/* URLs still work — including the
# IdP-registered callback URL.
PLATFORM_OIDC_SLUG = "oidc"


def is_login_ready(row: AuthProvider) -> bool:
    """Whether a registry row can serve a login: enabled, OIDC, and carrying
    the non-secret client config discovery needs. The single predicate behind
    the login routes, the provider listing, and guild auth policies."""
    return bool(row.enabled and row.kind == "oidc" and row.issuer and row.client_id)


def login_ready_clause() -> ColumnElement[bool]:
    """:func:`is_login_ready` as a predicate over ``auth_providers``, for
    queries that must ask it of rows they are not loading. Kept in step with
    the row form by ``platform_provider_test``."""
    return and_(
        AuthProvider.enabled.is_(True),
        AuthProvider.kind == "oidc",
        AuthProvider.issuer.is_not(None),
        AuthProvider.issuer != "",
        AuthProvider.client_id.is_not(None),
        AuthProvider.client_id != "",
    )


def can_serve_login_clause() -> ColumnElement[bool]:
    """Whether a registry row could actually answer a login, as a predicate
    over ``auth_providers``.

    :func:`login_ready_clause` plus the platform row's extra condition: the
    platform flow has always required a stored client secret, where a row
    beside it may be a PKCE-only public client (see
    ``_active_platform_provider``). Row-form callers branch between the two
    halves; a query that must ask of rows it is not loading needs them as one.

    The platform row is the one carrying the platform slug, which is how
    :func:`get_platform_provider` names it. One registry means one namespace,
    so the slug alone identifies it.
    """
    is_platform_row = AuthProvider.slug == PLATFORM_OIDC_SLUG
    return and_(
        login_ready_clause(),
        or_(
            not_(is_platform_row),
            select(AuthProviderSecret.provider_id)
            .where(
                AuthProviderSecret.provider_id == AuthProvider.id,
                AuthProviderSecret.client_secret_encrypted.is_not(None),
                AuthProviderSecret.client_secret_encrypted != "",
            )
            .exists(),
        ),
    )


def scopes_list(row: AuthProvider) -> list[str]:
    """The row's space-joined scopes as the list the settings API speaks."""
    return row.scopes.split() if row.scopes else []


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _join_scopes(scopes: list[str] | None) -> str | None:
    cleaned = [s.strip() for s in (scopes or []) if s and s.strip()]
    return " ".join(cleaned) if cleaned else None


async def get_platform_provider(session: AsyncSession) -> AuthProvider | None:
    """The platform provider row — the one carrying the platform slug."""
    return (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).first()


async def _create_platform_row(session: AsyncSession, **fields) -> AuthProvider:
    """Insert the platform row; a concurrent-creation race resolves to the
    winner's row (the savepoint keeps the outer transaction usable).

    The row is the deployment's first provider and nobody signed in makes it,
    so the record it stages carries no actor and says the environment is
    where it came from. A lost race writes no record: the winner's row is
    returned instead of one being created here.
    """
    from app.core.audit_events import AuditEventType
    from app.services import audit as audit_service
    from app.services.auth.provider_registry import AUDITED_FIELDS

    provider = AuthProvider(
        slug=PLATFORM_OIDC_SLUG,
        kind=AuthProviderKind.oidc.value,
        allow_jit=True,  # the platform flow JIT-provisions unknown users
        **fields,
    )
    try:
        async with session.begin_nested():
            session.add(provider)
            await session.flush()
        await audit_service.record(
            session,
            event_type=AuditEventType.AUTH_PROVIDER_CREATED,
            actor_user_id=None,
            target_type="auth_provider",
            target_id=provider.id,
            detail={
                "via": "env",
                **audit_service.changed_fields(
                    {}, audit_service.snapshot(provider, AUDITED_FIELDS)
                ),
            },
        )
        await session.commit()
        await session.refresh(provider)
        return provider
    except IntegrityError:
        winner = await get_platform_provider(session)
        if winner is None:  # pragma: no cover - the conflict implies a winner
            raise
        return winner


async def upsert_platform_provider(
    session: AsyncSession,
    *,
    enabled: bool,
    issuer: str | None,
    client_id: str | None,
    provider_name: str | None,
    scopes: list[str],
    client_secret: str | None,
) -> AuthProvider:
    """Create or update the platform provider row from the settings surface.

    ``client_secret`` follows the write-only convention: ``None`` keeps the
    stored secret, an empty string clears it, a value replaces it (delegated
    to the shared registry secret helper).
    """
    from app.services.auth.provider_registry import set_provider_secret

    provider = await get_platform_provider(session)
    desired = {
        "display_name": _normalize(provider_name) or "SSO",
        "enabled": bool(enabled),
        "issuer": _normalize(issuer),
        "client_id": _normalize(client_id),
        "scopes": _join_scopes(scopes),
    }
    if provider is None:
        provider = await _create_platform_row(session, **desired)
    # Apply the desired state regardless of which branch produced the row: a
    # freshly created row already matches (no-op), but a row returned from a
    # lost concurrent-creation race carries the winner's fields — this
    # caller's payload must still land.
    changed = False
    for field, value in desired.items():
        if getattr(provider, field) != value:
            setattr(provider, field, value)
            changed = True
    if changed:
        session.add(provider)
    if client_secret is not None:
        await set_provider_secret(session, provider.id, client_secret)
    await session.commit()
    await session.refresh(provider)
    return provider


async def seed_platform_provider_from_env(session: AsyncSession) -> bool:
    """First-boot seed: create the platform row from ``OIDC_*`` env values.

    Runs at startup; a no-op unless the env carries an issuer + client id AND
    no platform row exists yet — after creation the settings UI owns the row
    and the env never overwrites it. Returns True when a row was created.
    """
    issuer = _normalize(app_config.OIDC_ISSUER)
    client_id = _normalize(app_config.OIDC_CLIENT_ID)
    if not issuer or not client_id:
        return False
    if await get_platform_provider(session) is not None:
        return False
    provider = await upsert_platform_provider(
        session,
        enabled=bool(app_config.OIDC_ENABLED),
        issuer=issuer,
        client_id=client_id,
        provider_name=app_config.OIDC_PROVIDER_NAME,
        scopes=app_config.OIDC_SCOPES,
        client_secret=app_config.OIDC_CLIENT_SECRET or None,
    )
    logger.info(
        "Seeded platform OIDC provider %s from environment (enabled=%s)",
        provider.slug,
        provider.enabled,
    )
    return True
