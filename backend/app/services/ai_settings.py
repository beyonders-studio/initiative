"""AI settings & connections service (mode-based, schema-per-guild).

AI config ownership is a single global **mode** (``platform`` or ``guild``,
never both). The mode's owner defines *connections* — the destination
(provider, base_url, model) plus its key. Members configure nothing: they use
the connection the owner chose.

Resolution (member M generating in guild G):
1. mode (cached, loaded on the system engine — the request path never queries
   ``platform_ai_connections`` under a guild role).
2. connection: the owner's default, else the first enabled.
3. key: the connection's own. A guild connection's key is in
   ``guild_ai_connection_keys``, which the seat and the system engine read, so
   generation reads it on the system engine (:func:`_load_guild_key`);
   everything else reads ``has_api_key``.
4. destination always comes from the connection (owner-set). ``allow_private``
   is server-computed as (provider == ollama and the connection is a platform
   connection) — never from request input.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, text, update
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.session import routed_guild_id, set_rls_context
from app.core.audit_events import AuditEventType
from app.core.encryption import SALT_AI_API_KEY, decrypt_field, encrypt_field
from app.core.messages import AIMessages, GuildMessages
from app.db import session as db_session
from app.models.platform.ai_connection import PlatformAIConnection
from app.models.platform.guild import CommunityStatus, Guild
from app.models.tenant.ai_connection import GuildAIConnection, GuildAIConnectionKey
from app.services.platform.app_settings import get_app_settings, locked_settings
from app.services.platform import rules
from app.schemas.ai_settings import (
    AIConfigMode,
    AIConnectionCommunity,
    AIConnectionCreate,
    AIConnectionResponse,
    AIConnectionTestResponse,
    AIConnectionUpdate,
    AIModelsResponse,
    AIProvider,
    ConnectionScope,
    PlatformAIModeResponse,
    ResolvedAISettings,
    ResolvedAISettingsResponse,
)
from app.services import ai_provider
from app.services import audit as audit_service
from app.services.ai_provider import AIRequestError, Target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
)
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)

#: What a connection consists of, for the record. The key is not among them —
#: it is reported as a boolean beside the diff.
AUDITED_CONNECTION_FIELDS: tuple[str, ...] = (
    "label",
    "provider",
    "base_url",
    "model",
    "enabled",
    "is_default",
)
#: An operator's connection also names the communities it serves.
AUDITED_PLATFORM_FIELDS = (*AUDITED_CONNECTION_FIELDS, "community_ids")


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _connection_base_url(provider: AIProvider, value: str | None) -> str | None:
    """The address a connection keeps: none for a hosted service, whose
    address is its preset's."""
    if not ai_provider.uses_base_url(provider):
        return None
    return _normalize_optional_string(value)


# ---------------------------------------------------------------------------
# Platform config cache (mode + operator connections)
# ---------------------------------------------------------------------------
# The global mode and the operator's connections change rarely and are shared by
# every guild, so they are loaded once on the system engine and cached in-process
# (short TTL + explicit invalidation on operator write). The request path reads
# the cache, never ``platform_ai_connections`` under a guild role — so the
# operator key ciphertext is never exposed to a guild/member session.


@dataclass(frozen=True)
class _ConnRow:
    scope: str  # "platform" | "community"
    id: int
    label: str
    provider: str
    base_url: str | None
    model: str | None
    # The ciphertext of a platform connection's key; a guild connection's is
    # read by :func:`_load_guild_key` when it is needed.
    api_key_encrypted: str | None
    has_key: bool
    enabled: bool
    is_default: bool
    # An operator's connection given to communities serves only them.
    community_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class _PlatformConfig:
    mode: str
    version: int
    connections: tuple[_ConnRow, ...]


# Only the owner-only platform CONNECTIONS are cached (the expensive read). The
# mode (the rule ai_config_mode) and a monotonic version (on app_settings) are
# read by every role, so each request reads them fresh on its own (guild) session and reloads the cached
# connections only when the version moves. An operator change therefore reaches
# every worker/replica at once — there is no per-process staleness window.
_cache: _PlatformConfig | None = None


async def _load_platform_connections() -> tuple[_ConnRow, ...]:
    """Read the operator connections on the system engine (app_admin-only table)."""
    async with db_session.system_engine.connect() as conn:
        conn_rows = (
            await conn.execute(
                text(
                    "SELECT id, label, provider, base_url, model, "
                    "api_key_encrypted, enabled, is_default, community_ids "
                    "FROM public.platform_ai_connections ORDER BY id"
                )
            )
        ).all()
    return tuple(
        _ConnRow(
            scope="platform",
            id=r[0],
            label=r[1],
            provider=r[2],
            base_url=r[3],
            model=r[4],
            api_key_encrypted=r[5],
            has_key=r[5] is not None,
            enabled=bool(r[6]),
            is_default=bool(r[7]),
            community_ids=tuple(r[8] or ()),
        )
        for r in conn_rows
    )


async def get_platform_ai_config(session: AsyncSession) -> _PlatformConfig:
    """Resolve the global mode + (in platform mode) operator connections.

    ``mode`` (the rule ``ai_config_mode``) and ``version`` (on ``app_settings``)
    come from the caller's own session
    (cheap, always fresh, seen by every worker). Only platform mode needs the
    operator connections, cached and reloaded whenever ``version`` changes.
    """
    global _cache
    mode = (await rules.platform_values(session))["ai_config_mode"].value
    version = (await get_app_settings(session)).ai_config_version
    if mode != AIConfigMode.platform.value:
        return _PlatformConfig(mode=mode, version=version, connections=())
    if _cache is not None and _cache.version == version:
        return _cache
    _cache = _PlatformConfig(
        mode=mode,
        version=version,
        connections=await _load_platform_connections(),
    )
    return _cache


def invalidate_platform_ai_cache() -> None:
    """Drop the cached operator connections. Belt-and-suspenders after an
    operator write in the serving worker; cross-worker freshness is guaranteed by
    the version bump, so other replicas reload on their next read."""
    global _cache
    _cache = None


async def bump_ai_config_version(session: AsyncSession) -> None:
    """Advance the version so every worker's cache reloads on its next read.
    Called on every operator write that changes the mode (as the rule's
    follow-up) or a platform connection. The caller owns the commit."""
    settings = await get_app_settings(session)
    settings.ai_config_version += 1
    session.add(settings)


def _conn_from_guild(row: GuildAIConnection) -> _ConnRow:
    return _ConnRow(
        scope="community",
        id=row.id,  # type: ignore[arg-type]
        label=row.label,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        api_key_encrypted=None,
        has_key=row.has_api_key,
        enabled=row.enabled,
        is_default=row.is_default,
    )


async def _load_guild_key(guild_id: int, connection_id: int) -> str | None:
    """A guild connection's shared key ciphertext, read on the system engine
    in ``guild_id``'s schema: the key table is read by the seat and the system
    engine, and a member's generation needs the key of the connection it runs
    on."""
    async with cohorts.system_session(guild_id) as system, system.begin():
        await set_rls_context(system, SystemGuild(guild_id))
        return (
            await system.exec(
                select(GuildAIConnectionKey.api_key_encrypted).where(
                    GuildAIConnectionKey.connection_id == connection_id
                )
            )
        ).first()


async def _guild_key(session: AsyncSession, connection_id: int) -> str | None:
    """A guild connection's shared key, decrypted, read on the seat's session."""
    ciphertext = (
        await session.exec(
            select(GuildAIConnectionKey.api_key_encrypted).where(
                GuildAIConnectionKey.connection_id == connection_id
            )
        )
    ).first()
    return decrypt_field(ciphertext, SALT_AI_API_KEY) if ciphertext else None


async def _set_guild_key(
    session: AsyncSession, connection_id: int, ciphertext: str | None
) -> None:
    """Store, replace or clear a guild connection's shared key."""
    await session.exec(
        delete(GuildAIConnectionKey).where(
            GuildAIConnectionKey.connection_id == connection_id
        )
    )
    if ciphertext is not None:
        session.add(
            GuildAIConnectionKey(
                connection_id=connection_id, api_key_encrypted=ciphertext
            )
        )
    await session.flush()


def _provider_or_none(value: str) -> AIProvider | None:
    try:
        return AIProvider(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Base URL validation for a stored connection
# ---------------------------------------------------------------------------
async def _validate_connection_base_url(
    provider: AIProvider, base_url: str | None, scope: str
) -> None:
    """A connection's ``base_url`` is validated public-only, EXCEPT the
    operator's connection to a server somebody runs (they may target a private
    host they own). A guild connection is always public-only, so a guild admin
    can never persist a private/internal target."""
    if not base_url:
        return
    if ai_provider.allow_private(provider, scope):
        return
    try:
        await assert_target_url_is_public_async(base_url)
    except (WebhookTargetUrlError, WebhookTargetUrlPrivateError):
        raise HTTPException(status_code=400, detail=AIMessages.INVALID_BASE_URL)


# ---------------------------------------------------------------------------
# Health: how a connection's last request went
# ---------------------------------------------------------------------------
async def record_health(
    scope: ConnectionScope, connection_id: int, guild_id: int | None, code: str | None
) -> None:
    """Write that a request on this connection failed with ``code``, or
    succeeded (``None``). A failure keeps the time it began until a request
    succeeds; a write that changes nothing writes nothing. On the system
    engine: the member whose request it was does not write connections."""
    model = (
        PlatformAIConnection if scope is ConnectionScope.platform else GuildAIConnection
    )
    stmt = (
        update(model)
        .where(
            col(model.id) == connection_id,
            col(model.last_error).is_distinct_from(code),
        )
        .values(last_error=code, last_error_at=None if code is None else func.now())
    )
    if scope is ConnectionScope.platform:
        async with db_session.system_engine.begin() as conn:
            await conn.execute(stmt)
        return
    assert guild_id is not None
    async with cohorts.system_session(guild_id) as system, system.begin():
        await set_rls_context(system, SystemGuild(guild_id))
        await system.exec(stmt)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
async def resolve_ai_settings(
    session: AsyncSession,
    guild_id: int | None = None,
    *,
    with_key: bool = False,
) -> ResolvedAISettings:
    """Compute the AI settings for generating in guild ``guild_id``.

    The key itself is read and decrypted only ``with_key``, for a request that
    goes to the provider; otherwise ``has_api_key`` says whether there is one.
    """
    if guild_id is None:
        return ResolvedAISettings(enabled=False, source="disabled")

    cfg = await get_platform_ai_config(session)
    if cfg.mode not in ("platform", "community"):
        return ResolvedAISettings(enabled=False, source="disabled")

    # The community's own answer, while it holds the option that sets it.
    if not await rules.community_value(session, guild_id, "allow_ai"):
        return ResolvedAISettings(enabled=False, source=cfg.mode)

    # Connections available in the active mode.
    if cfg.mode == "platform":
        # A connection given to this community is its own, and the only one
        # it uses, even while it cannot answer: its spend is its own account's.
        # The rest share the connections given to nobody.
        given = [c for c in cfg.connections if guild_id in c.community_ids]
        conns = [
            c
            for c in given or [c for c in cfg.connections if not c.community_ids]
            if c.enabled
        ]
    else:
        rows = (
            await session.exec(
                select(GuildAIConnection).where(GuildAIConnection.enabled.is_(True))
            )
        ).all()
        conns = [_conn_from_guild(r) for r in rows]
    # A connection that names no model yet is not one a request can use.
    conns = [c for c in conns if c.model and _provider_or_none(c.provider) is not None]
    if not conns:
        return ResolvedAISettings(enabled=False, source=cfg.mode)

    chosen = next((c for c in conns if c.is_default), None) or conns[0]
    provider = _provider_or_none(chosen.provider)
    assert provider is not None  # filtered above

    api_key: str | None = None
    if with_key and chosen.has_key:
        ciphertext = chosen.api_key_encrypted or await _load_guild_key(
            guild_id, chosen.id
        )
        api_key = decrypt_field(ciphertext, SALT_AI_API_KEY) if ciphertext else None

    return ResolvedAISettings(
        enabled=chosen.has_key or not ai_provider.needs_key(provider),
        provider=provider,
        api_key=api_key,
        has_api_key=chosen.has_key,
        base_url=chosen.base_url,
        model=chosen.model,
        allow_private=ai_provider.allow_private(provider, chosen.scope),
        scope=ConnectionScope(chosen.scope),
        connection_id=chosen.id,
        source=cfg.mode,
    )


async def get_resolved_ai_settings_response(
    session: AsyncSession,
    guild_id: int | None = None,
) -> ResolvedAISettingsResponse:
    """Resolved settings for the frontend (no API key)."""
    resolved = await resolve_ai_settings(session, guild_id)
    return ResolvedAISettingsResponse(
        enabled=resolved.enabled,
        provider=resolved.provider,
        has_api_key=resolved.has_api_key,
        base_url=resolved.base_url,
        model=resolved.model,
        source=resolved.source,
    )


# ---------------------------------------------------------------------------
# Platform mode + connection CRUD (config.manage — owner only)
# ---------------------------------------------------------------------------
async def get_platform_ai_mode(session: AsyncSession) -> PlatformAIModeResponse:
    mode = (await rules.platform_values(session))["ai_config_mode"]
    return PlatformAIModeResponse(mode=mode)


def _platform_conn_response(
    row: PlatformAIConnection, names: dict[int, str]
) -> AIConnectionResponse:
    return AIConnectionResponse(
        id=row.id,  # type: ignore[arg-type]
        scope=ConnectionScope.platform,
        label=row.label,
        provider=AIProvider(row.provider),
        base_url=row.base_url,
        model=row.model,
        has_api_key=bool(row.api_key_encrypted),
        enabled=row.enabled,
        is_default=row.is_default,
        communities=sorted(
            (
                AIConnectionCommunity(id=gid, name=names.get(gid))
                for gid in row.community_ids
            ),
            key=lambda community: (community.name or "").casefold(),
        ),
        last_error=row.last_error,
        last_error_at=row.last_error_at,
    )


async def _community_names(
    session: AsyncSession, ids: Iterable[int], *, live: bool = False
) -> dict[int, str]:
    """The communities among ``ids`` that still exist, by name; with ``live``,
    only those not deleted."""
    wanted = set(ids)
    if not wanted:
        return {}
    statement = select(Guild.id, Guild.name).where(col(Guild.id).in_(wanted))
    if live:
        statement = statement.where(Guild.status != CommunityStatus.deleted)
    rows = await session.exec(statement)
    return {gid: name for gid, name in rows.all()}  # type: ignore[misc]


async def _platform_responses(
    session: AsyncSession, rows: Sequence[PlatformAIConnection]
) -> list[AIConnectionResponse]:
    names = await _community_names(
        session, (gid for row in rows for gid in row.community_ids)
    )
    return [_platform_conn_response(row, names) for row in rows]


async def _give_communities(
    session: AsyncSession, row: PlatformAIConnection, community_ids: list[int]
) -> None:
    """Give ``row`` these communities, and take them from any other
    connection they were given to: a community has one connection of its own.

    A community added must be live; one it already had stays until removed,
    deleted or not. Changes are made one at a time, under the settings row.
    """
    await locked_settings(session)
    wanted = set(community_ids)
    added = wanted - set(row.community_ids)
    if added - set(await _community_names(session, added, live=True)):
        raise HTTPException(status_code=404, detail=GuildMessages.COMMUNITY_NOT_FOUND)
    row.community_ids = sorted(wanted)
    others = (
        (
            await session.exec(
                select(PlatformAIConnection).where(
                    PlatformAIConnection.id != row.id,
                    col(PlatformAIConnection.community_ids).overlap(sorted(wanted)),
                )
            )
        ).all()
        if wanted
        else []
    )
    for other in others:
        other.community_ids = [g for g in other.community_ids if g not in wanted]
        session.add(other)


async def list_platform_connections(
    session: AsyncSession,
) -> list[AIConnectionResponse]:
    rows = (
        await session.exec(
            select(PlatformAIConnection).order_by(PlatformAIConnection.id)
        )
    ).all()
    return await _platform_responses(session, rows)


async def create_platform_connection(
    session: AsyncSession,
    payload: AIConnectionCreate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    base_url = _connection_base_url(payload.provider, payload.base_url)
    await _validate_connection_base_url(payload.provider, base_url, "platform")
    row = PlatformAIConnection(
        label=payload.label.strip(),
        provider=payload.provider.value,
        base_url=base_url,
        model=_normalize_optional_string(payload.model),
        api_key_encrypted=(
            encrypt_field(payload.api_key.strip(), SALT_AI_API_KEY)
            if payload.api_key and payload.api_key.strip()
            else None
        ),
        enabled=payload.enabled,
        is_default=payload.is_default,
    )
    if payload.is_default:
        await _clear_platform_default(session)
    session.add(row)
    await session.flush()
    await _give_communities(session, row, payload.community_ids)
    await bump_ai_config_version(session)
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_CREATED,
        actor_user_id=actor_user_id,
        target_type="ai_connection",
        target_id=row.id,
        detail={
            "scope": ConnectionScope.platform.value,
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_PLATFORM_FIELDS)
            ),
            "secret_changed": bool(row.api_key_encrypted),
        },
    )
    await session.commit()
    await session.refresh(row)
    invalidate_platform_ai_cache()
    return (await _platform_responses(session, [row]))[0]


async def _clear_platform_default(session: AsyncSession) -> None:
    rows = (
        await session.exec(
            select(PlatformAIConnection).where(
                PlatformAIConnection.is_default.is_(True)
            )
        )
    ).all()
    for r in rows:
        r.is_default = False
        session.add(r)


async def update_platform_connection(
    session: AsyncSession,
    connection_id: int,
    payload: AIConnectionUpdate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    before = audit_service.snapshot(row, AUDITED_PLATFORM_FIELDS)
    key_before = row.api_key_encrypted
    destination = (row.provider, row.base_url)
    provider = payload.provider or AIProvider(row.provider)
    if "base_url" in data or "provider" in data:
        base_url = _connection_base_url(
            provider, payload.base_url if "base_url" in data else row.base_url
        )
        await _validate_connection_base_url(provider, base_url, "platform")
        row.base_url = base_url
    if "label" in data and payload.label is not None:
        row.label = payload.label.strip()
    if "provider" in data and payload.provider is not None:
        row.provider = payload.provider.value
    if "model" in data:
        row.model = _normalize_optional_string(payload.model)
    if "api_key" in data:
        normalized = _normalize_optional_string(payload.api_key)
        row.api_key_encrypted = (
            encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None
        )
    elif (row.provider, row.base_url) != destination:
        # A key goes only where it was given for.
        row.api_key_encrypted = None
    if "enabled" in data and payload.enabled is not None:
        row.enabled = payload.enabled
    if "is_default" in data and payload.is_default is not None:
        if payload.is_default:
            await _clear_platform_default(session)
        row.is_default = payload.is_default
    if payload.community_ids is not None:
        await _give_communities(session, row, payload.community_ids)
    session.add(row)
    await bump_ai_config_version(session)
    secret_changed = row.api_key_encrypted != key_before
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_PLATFORM_FIELDS)
    )
    if changed["changed"] or secret_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.AI_CONNECTION_UPDATED,
            actor_user_id=actor_user_id,
            target_type="ai_connection",
            target_id=row.id,
            detail={
                "scope": ConnectionScope.platform.value,
                **changed,
                "secret_changed": secret_changed,
            },
        )
    await session.commit()
    await session.refresh(row)
    invalidate_platform_ai_cache()
    return (await _platform_responses(session, [row]))[0]


async def delete_platform_connection(
    session: AsyncSession, connection_id: int, *, actor_user_id: int | None = None
) -> None:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    await session.delete(row)
    await bump_ai_config_version(session)
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_DELETED,
        actor_user_id=actor_user_id,
        target_type="ai_connection",
        target_id=connection_id,
        detail={"scope": ConnectionScope.platform.value},
    )
    await session.commit()
    invalidate_platform_ai_cache()


# ---------------------------------------------------------------------------
# Guild connection CRUD (guild admin — guild config mode)
# ---------------------------------------------------------------------------
def _guild_conn_response(row: GuildAIConnection) -> AIConnectionResponse:
    return AIConnectionResponse(
        id=row.id,  # type: ignore[arg-type]
        scope=ConnectionScope.community,
        label=row.label,
        provider=AIProvider(row.provider),
        base_url=row.base_url,
        model=row.model,
        has_api_key=row.has_api_key,
        enabled=row.enabled,
        is_default=row.is_default,
        last_error=row.last_error,
        last_error_at=row.last_error_at,
    )


async def list_guild_connections(
    session: AsyncSession,
) -> list[AIConnectionResponse]:
    rows = (
        await session.exec(select(GuildAIConnection).order_by(GuildAIConnection.id))
    ).all()
    return [_guild_conn_response(r) for r in rows]


async def _clear_guild_default(session: AsyncSession) -> None:
    rows = (
        await session.exec(
            select(GuildAIConnection).where(GuildAIConnection.is_default.is_(True))
        )
    ).all()
    for r in rows:
        r.is_default = False
        session.add(r)


async def create_guild_connection(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    payload: AIConnectionCreate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    base_url = _connection_base_url(payload.provider, payload.base_url)
    # Guild connections are always public-only (scope="community" => no private).
    await _validate_connection_base_url(payload.provider, base_url, "community")
    row = GuildAIConnection(
        created_by=user_id,
        label=payload.label.strip(),
        provider=payload.provider.value,
        base_url=base_url,
        model=_normalize_optional_string(payload.model),
        enabled=payload.enabled,
        is_default=payload.is_default,
    )
    key = (
        encrypt_field(payload.api_key.strip(), SALT_AI_API_KEY)
        if payload.api_key and payload.api_key.strip()
        else None
    )
    if payload.is_default:
        await _clear_guild_default(session)
    session.add(row)
    await session.flush()
    await _set_guild_key(session, row.id, key)  # type: ignore[arg-type]
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_CREATED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="ai_connection",
        target_id=row.id,
        detail={
            "scope": ConnectionScope.community.value,
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
            ),
            "secret_changed": key is not None,
        },
    )
    await session.commit()
    await session.refresh(row)
    return _guild_conn_response(row)


async def update_guild_connection(
    session: AsyncSession,
    connection_id: int,
    payload: AIConnectionUpdate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    before = audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
    key_before = (
        await session.exec(
            select(GuildAIConnectionKey.api_key_encrypted).where(
                GuildAIConnectionKey.connection_id == connection_id
            )
        )
    ).first()
    key = key_before
    destination = (row.provider, row.base_url)
    provider = payload.provider or AIProvider(row.provider)
    if "base_url" in data or "provider" in data:
        base_url = _connection_base_url(
            provider, payload.base_url if "base_url" in data else row.base_url
        )
        await _validate_connection_base_url(provider, base_url, "community")
        row.base_url = base_url
    if "label" in data and payload.label is not None:
        row.label = payload.label.strip()
    if "provider" in data and payload.provider is not None:
        row.provider = payload.provider.value
    if "model" in data:
        row.model = _normalize_optional_string(payload.model)
    if "api_key" in data:
        normalized = _normalize_optional_string(payload.api_key)
        key = encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None
    elif (row.provider, row.base_url) != destination:
        # A key goes only where it was given for.
        key = None
    if "enabled" in data and payload.enabled is not None:
        row.enabled = payload.enabled
    if "is_default" in data and payload.is_default is not None:
        if payload.is_default:
            await _clear_guild_default(session)
        row.is_default = payload.is_default
    session.add(row)
    secret_changed = key != key_before
    if secret_changed:
        await _set_guild_key(session, connection_id, key)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
    )
    if changed["changed"] or secret_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.AI_CONNECTION_UPDATED,
            actor_user_id=actor_user_id,
            guild_id=routed_guild_id(session),
            target_type="ai_connection",
            target_id=row.id,
            detail={
                "scope": ConnectionScope.community.value,
                **changed,
                "secret_changed": secret_changed,
            },
        )
    await session.commit()
    await session.refresh(row)
    return _guild_conn_response(row)


async def delete_guild_connection(
    session: AsyncSession, connection_id: int, *, actor_user_id: int | None = None
) -> None:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    guild_id = routed_guild_id(session)
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_DELETED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="ai_connection",
        target_id=connection_id,
        detail={"scope": ConnectionScope.community.value},
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Connection probe (test / list models on a STORED connection)
# ---------------------------------------------------------------------------
# The destination + key both come from a stored connection (never a request
# body), so a probe sends a key only to the destination it was saved with.
# ``allow_private`` is server-computed from the provider and the scope.


def _probe_target(conn: _ConnRow, api_key: str | None) -> Target:
    provider = AIProvider(conn.provider)
    return Target(
        provider=provider,
        model=conn.model,
        api_key=api_key,
        base_url=conn.base_url,
        allow_private=ai_provider.allow_private(provider, conn.scope),
    )


async def _models(conn: _ConnRow, api_key: str | None) -> AIModelsResponse:
    try:
        models = await ai_provider.list_models(_probe_target(conn, api_key))
    except AIRequestError as exc:
        return AIModelsResponse(models=[], error=exc.code)
    return AIModelsResponse(models=models)


async def _probe(conn: _ConnRow, api_key: str | None) -> AIConnectionTestResponse:
    listed = await _models(conn, api_key)
    if listed.error is not None:
        return AIConnectionTestResponse(success=False, message=listed.error)
    models = listed.models
    if not conn.model:
        return AIConnectionTestResponse(
            success=False, message=AIMessages.MODEL_REQUIRED, available_models=models
        )
    listing_is_complete = len(models) < ai_provider.MODEL_LIST_CAP
    if models and listing_is_complete and conn.model not in models:
        # Ollama lists a model with its tag (``llama3.2:latest``).
        base = {m.split(":")[0] for m in models}
        if conn.model.split(":")[0] not in base:
            return AIConnectionTestResponse(
                success=False,
                message=AIMessages.MODEL_NOT_FOUND,
                available_models=models,
            )
    return AIConnectionTestResponse(success=True, available_models=models or None)


async def _record_probe(
    scope: ConnectionScope,
    connection_id: int,
    guild_id: int | None,
    result: AIConnectionTestResponse,
) -> None:
    """A test is a request too: what the provider answered is the
    connection's health. A test that never asked the provider says nothing."""
    if result.success:
        await record_health(scope, connection_id, guild_id, None)
    elif result.message in ai_provider.PROVIDER_CODES:
        await record_health(scope, connection_id, guild_id, result.message)


def _platform_conn(row: PlatformAIConnection) -> _ConnRow:
    return _ConnRow(
        scope="platform",
        id=row.id,  # type: ignore[arg-type]
        label=row.label,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        api_key_encrypted=row.api_key_encrypted,
        has_key=row.api_key_encrypted is not None,
        enabled=row.enabled,
        is_default=row.is_default,
    )


def _platform_key(row: PlatformAIConnection) -> str | None:
    return (
        decrypt_field(row.api_key_encrypted, SALT_AI_API_KEY)
        if row.api_key_encrypted
        else None
    )


async def test_platform_connection(
    session: AsyncSession, connection_id: int
) -> AIConnectionTestResponse:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    result = await _probe(_platform_conn(row), _platform_key(row))
    await _record_probe(ConnectionScope.platform, connection_id, None, result)
    return result


async def fetch_platform_connection_models(
    session: AsyncSession, connection_id: int
) -> AIModelsResponse:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    return await _models(_platform_conn(row), _platform_key(row))


async def test_guild_connection(
    session: AsyncSession, connection_id: int
) -> AIConnectionTestResponse:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    result = await _probe(
        _conn_from_guild(row), await _guild_key(session, connection_id)
    )
    await _record_probe(
        ConnectionScope.community, connection_id, routed_guild_id(session), result
    )
    return result


async def fetch_guild_connection_models(
    session: AsyncSession, connection_id: int
) -> AIModelsResponse:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    return await _models(
        _conn_from_guild(row), await _guild_key(session, connection_id)
    )
