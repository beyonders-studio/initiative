"""The login-provider registry's CRUD core.

``auth_providers`` is the **operator's**, all of it. A community does not own a
provider; it owns a connection to one (see
``app.services.auth.guild_provider_connections``), so there is one namespace
here and one set of slugs.

The client secret is write-only: encrypted into the ``auth_provider_secrets``
companion and never returned; reads carry ``secret_set`` instead. Every caller
runs on the system engine — neither table carries request-path grants.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.encryption import SALT_OIDC_CLIENT_SECRET, encrypt_field
from app.core.config import API_V1_STR, settings as app_config
from app.core.messages import AuthProviderMessages
from app.db.errors import (
    STILL_REFERENCED_SQLSTATES,
    UNIQUE_VIOLATION_SQLSTATE,
    dbapi_sqlstate,
)
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.oidc_claim_mapping import (
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.schemas.platform.settings import (
    AuthProviderOwnerRead,
    AuthProviderCreate,
    AuthProviderUpdate,
)
from app.services import audit as audit_service
from app.services.auth import identity as identity_service
from app.services.platform import auth_posture

logger = logging.getLogger(__name__)

#: The provider columns a record names when one of them moves. The secret is
#: not among them — it lives in the companion row and is reported as a
#: boolean beside the diff.
AUDITED_FIELDS: tuple[str, ...] = (
    "display_name",
    "kind",
    "enabled",
    "issuer",
    "client_id",
    "scopes",
    "role_claim_path",
    "allow_jit",
    "asserts_second_factor",
    "icon",
    "button_style",
)


def provider_callback_url(slug: str) -> str:
    """Where a provider sends the browser back, which is what an operator
    registers with their IdP.

    One provider, one address. Built here so the address shown in settings and
    the address sent to the IdP come from one place.
    """
    base = app_config.APP_URL.rstrip("/")
    return f"{base}{API_V1_STR}/auth/{slug}/callback"


def frontend_callback_url() -> str:
    """The web app's page a provider sign-in finishes on, after the callback
    above has done its work."""
    return f"{app_config.APP_URL.rstrip('/')}/oidc/callback"


def owner_read(row: AuthProvider, *, secret_set: bool) -> AuthProviderOwnerRead:
    return AuthProviderOwnerRead(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        kind=row.kind,
        enabled=row.enabled,
        issuer=row.issuer,
        client_id=row.client_id,
        scopes=row.scopes,
        role_claim_path=row.role_claim_path,
        allow_jit=row.allow_jit,
        asserts_second_factor=row.asserts_second_factor,
        icon=row.icon,
        button_style=row.button_style,
        secret_set=secret_set,
        callback_url=provider_callback_url(row.slug),
    )


async def secret_is_set(session: AsyncSession, provider_id: int) -> bool:
    secret = await session.get(AuthProviderSecret, provider_id)
    return bool(secret and secret.client_secret_encrypted)


async def set_provider_secret(
    session: AsyncSession, provider_id: int, client_secret: str | None
) -> None:
    """Store (or clear, with ``None``/empty) the encrypted client secret in
    the companion row; clearing deletes the row rather than leaving an empty
    one. Stages only — the caller commits."""
    secret = await session.get(AuthProviderSecret, provider_id)
    if not client_secret:
        if secret is not None:
            await session.delete(secret)
        return
    encrypted = encrypt_field(client_secret, SALT_OIDC_CLIENT_SECRET)
    if secret is None:
        secret = AuthProviderSecret(
            provider_id=provider_id, client_secret_encrypted=encrypted
        )
    else:
        secret.client_secret_encrypted = encrypted
    session.add(secret)


async def editable_provider(session: AsyncSession, provider_id: int) -> AuthProvider:
    """The row for one id, or the 404 the CRUD contract promises."""
    row = (
        await session.exec(select(AuthProvider).where(AuthProvider.id == provider_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.NOT_FOUND,
        )
    return row


async def list_providers(session: AsyncSession) -> list[AuthProviderOwnerRead]:
    rows = (
        await session.exec(select(AuthProvider).order_by(AuthProvider.display_name))
    ).all()
    row_ids = [row.id for row in rows]
    with_secret: set[int] = set()
    if row_ids:
        with_secret = set(
            (
                await session.exec(
                    select(AuthProviderSecret.provider_id).where(
                        AuthProviderSecret.provider_id.in_(row_ids),
                        AuthProviderSecret.client_secret_encrypted.is_not(None),
                    )
                )
            ).all()
        )
    return [owner_read(row, secret_set=row.id in with_secret) for row in rows]


async def create_provider(
    session: AsyncSession,
    provider_in: AuthProviderCreate,
    *,
    actor_user_id: int | None = None,
) -> AuthProviderOwnerRead:
    """Create a provider. Slugs are unique across the registry (409).

    ``actor_user_id`` is who made it, for the record staged beside the insert.
    """
    existing = (
        await session.exec(
            select(AuthProvider.id).where(AuthProvider.slug == provider_in.slug)
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.SLUG_TAKEN,
        )

    row = AuthProvider(**provider_in.model_dump(exclude={"client_secret"}))
    session.add(row)
    # The unique constraint backs the check above; a concurrent create that
    # slips between them still gets the promised 409.
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if dbapi_sqlstate(exc) != UNIQUE_VIOLATION_SQLSTATE:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.SLUG_TAKEN,
        ) from exc
    await set_provider_secret(session, row.id, provider_in.client_secret)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_PROVIDER_CREATED,
        actor_user_id=actor_user_id,
        target_type="auth_provider",
        target_id=row.id,
        detail={
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_FIELDS)
            ),
            "secret_set": bool(provider_in.client_secret),
        },
    )
    await session.commit()
    await session.refresh(row)
    logger.info("auth provider %s (%s) created", row.slug, row.id)
    return owner_read(row, secret_set=bool(provider_in.client_secret))


async def update_provider(
    session: AsyncSession,
    provider_id: int,
    provider_in: AuthProviderUpdate,
    *,
    actor_user_id: int | None = None,
) -> AuthProviderOwnerRead:
    row = await editable_provider(session, provider_id)
    update_data = provider_in.model_dump(exclude_unset=True)
    before = audit_service.snapshot(row, AUDITED_FIELDS)
    # Absent leaves the stored secret alone; present replaces or clears it.
    secret_changed = "client_secret" in update_data

    # Write-only secret: absent = keep, empty = clear, value = replace.
    if "client_secret" in update_data:
        await set_provider_secret(session, row.id, update_data.pop("client_secret"))

    for field_name, value in update_data.items():
        setattr(row, field_name, value)
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if changed["changed"] or secret_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.AUTH_PROVIDER_UPDATED,
            actor_user_id=actor_user_id,
            target_type="auth_provider",
            target_id=row.id,
            detail={**changed, "secret_changed": secret_changed},
        )
    await session.commit()
    await session.refresh(row)
    return owner_read(row, secret_set=await secret_is_set(session, row.id))


async def _release_in_each_guild(
    provider_id: int, rule_ids: dict[int, list[int]]
) -> None:
    """Clear a deleted provider from every guild's ``initiative_members``, and
    drop the initiatives its rules placed people in: ``rule_ids``, by guild.

    Guild by guild, because the tables exist once per schema. Provider
    deletion is rare, so the walk is not on any hot path.
    """
    from app.models.tenant.claim_rule_initiative import ClaimRuleInitiative
    from app.models.tenant.initiative import InitiativeMember
    from app.services.guild_sweeps import Scope, each_guild

    async def release(guild_session: AsyncSession, guild_id: int) -> None:
        await guild_session.exec(
            update(InitiativeMember)
            .where(InitiativeMember.oidc_provider_id == provider_id)
            .values(oidc_provider_id=None)
        )
        if guild_id in rule_ids:
            await guild_session.exec(
                delete(ClaimRuleInitiative).where(
                    ClaimRuleInitiative.rule_id.in_(rule_ids[guild_id])
                )
            )

    await each_guild(
        [(Scope.PROVISIONED, release)], name="auth-provider-initiative-release"
    )


async def delete_provider(
    session: AsyncSession, provider_id: int, *, actor_user_id: int | None = None
) -> None:
    """Delete a provider. Its linked identities (and their stored refresh
    tokens) go with it via cascade — users who signed in through it keep their
    accounts and any other sign-in methods.

    Three refusals, all 409. A provider some community's sign-in requirement
    names, or one some community connects through: both are foreign keys with
    ``RESTRICT``, and both mean somebody's way in. And a provider that is some
    account's only credential: those people set a password or link another
    provider first, and then it deletes.
    """
    row = await editable_provider(session, provider_id)
    # Lock the row before counting. Inserting a ``federated_identities`` row
    # takes FOR KEY SHARE on the provider it references, which FOR UPDATE
    # conflicts with — so a login provisioning an account either lands before
    # the count and is seen by it, or waits and then fails the foreign key.
    await session.exec(
        select(AuthProvider.id).where(AuthProvider.id == row.id).with_for_update()
    )
    stranded = await identity_service.sole_credential_user_count(
        session,
        provider_id=row.id,
        permitted=await auth_posture.resolve_login_methods(session),
    )
    if stranded:
        logger.info(
            "auth provider %s (%s) delete refused: sole credential for %d account(s)",
            row.slug,
            provider_id,
            stranded,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.SOLE_CREDENTIAL,
        )
    kind = row.kind
    # Its rules go with it (``ON DELETE CASCADE``); the initiatives they place
    # people in are kept in each community's schema, under their ids.
    rule_ids: dict[int, list[int]] = {}
    for guild_id, rule_id in (
        await session.exec(
            select(OIDCClaimMapping.guild_id, OIDCClaimMapping.id).where(
                OIDCClaimMapping.provider_id == row.id,
                OIDCClaimMapping.target_type == OIDCMappingTargetType.initiative,
            )
        )
    ).all():
        if rule_id is not None:
            rule_ids.setdefault(guild_id, []).append(rule_id)
    secret = await session.get(AuthProviderSecret, row.id)
    if secret is not None:
        await session.delete(secret)
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_PROVIDER_DELETED,
        actor_user_id=actor_user_id,
        target_type="auth_provider",
        target_id=provider_id,
        detail={"kind": kind},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if dbapi_sqlstate(exc) not in STILL_REFERENCED_SQLSTATES:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.IN_USE,
        ) from exc
    # Guild-side memberships release their manager once the provider is gone.
    # The shared table's foreign key does it on its own (``ON DELETE SET
    # NULL``); ``initiative_members`` lives in a guild schema and carries no
    # key across that line, so the same clearing is written by hand. The row is
    # then unmanaged, which is what it is: no provider answers for it.
    await _release_in_each_guild(provider_id, rule_ids)
    logger.info("auth provider %s (%s) deleted", row.slug, provider_id)
