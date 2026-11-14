from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import ColumnElement, and_, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.tools import Tool
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.api_key import UserApiKey
from app.models.platform.user import User, UserStatus
from app.services import audit as audit_service

API_KEY_PREFIX = "ppk_"
API_KEY_DISPLAY_PREFIX_LENGTH = 12
#: How stale ``last_used_at`` may be before a request writes it again.
API_KEY_LAST_USED_RESOLUTION = timedelta(hours=1)


def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _generate_secret() -> str:
    return f"{API_KEY_PREFIX}{token_urlsafe(32)}"


async def list_api_keys(session: AsyncSession, *, user: User) -> Sequence[UserApiKey]:
    statement = (
        select(UserApiKey)
        .where(UserApiKey.user_id == user.id)
        .order_by(UserApiKey.created_at.desc())
    )
    result = await session.exec(statement)
    return result.all()


async def create_api_key(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    expires_at: datetime | None = None,
    read_only: bool = False,
    guild_id: int | None = None,
    resource_type: Tool | None = None,
    resource_id: int | None = None,
) -> tuple[str, UserApiKey]:
    if not user.id:
        raise ValueError("User must be persisted before creating API keys")

    if resource_type is not None:
        # A person holds one key per resource; a new one replaces it. Two
        # replacements at once take turns.
        await advisory_lock(
            session,
            LockNamespace.API_KEY_RESOURCE,
            f"{user.id}:{guild_id}:{resource_type}:{resource_id}",
        )
        previous = (
            await session.exec(
                select(UserApiKey).where(
                    UserApiKey.user_id == user.id,
                    UserApiKey.guild_id == guild_id,
                    UserApiKey.resource_type == resource_type,
                    UserApiKey.resource_id == resource_id,
                )
            )
        ).one_or_none()
        if previous is not None:
            await _record_key_event(
                session,
                AuditEventType.API_KEY_DELETED,
                user_id=user.id,
                api_key=previous,
            )
            await session.delete(previous)
            await session.flush()

    secret = _generate_secret()
    api_key = UserApiKey(
        user_id=user.id,
        name=name,
        token_prefix=secret[:API_KEY_DISPLAY_PREFIX_LENGTH],
        token_hash=_hash_token(secret),
        expires_at=expires_at,
        read_only=read_only,
        guild_id=guild_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    session.add(api_key)
    # Flushed first so the record can name the key it describes.
    await session.flush()
    await _record_key_event(
        session, AuditEventType.API_KEY_CREATED, user_id=user.id, api_key=api_key
    )
    await session.commit()
    await session.refresh(api_key)
    return secret, api_key


async def _record_key_event(
    session: AsyncSession,
    event_type: AuditEventType,
    *,
    user_id: int,
    api_key: UserApiKey,
    actor_user_id: int | None = None,
) -> None:
    """Record one key's arrival or departure.

    A key is the account's own credential, so its holder is the actor unless
    staff revoked it. The record carries the key's scope — never its name, its
    prefix or its hash.
    """
    await audit_service.record(
        session,
        event_type=event_type,
        actor_user_id=actor_user_id if actor_user_id is not None else user_id,
        target_user_id=user_id,
        guild_id=api_key.guild_id,
        target_type="user_api_key",
        target_id=api_key.id,
        detail={
            "read_only": api_key.read_only,
            "expires_at": (
                api_key.expires_at.isoformat() if api_key.expires_at else None
            ),
            "guild_bound": api_key.guild_id is not None,
            "resource_type": api_key.resource_type,
        },
    )


async def delete_api_key(session: AsyncSession, *, user: User, api_key_id: int) -> bool:
    statement = select(UserApiKey).where(
        UserApiKey.id == api_key_id, UserApiKey.user_id == user.id
    )
    result = await session.exec(statement)
    api_key = result.one_or_none()
    if not api_key:
        return False

    await _record_key_event(
        session, AuditEventType.API_KEY_DELETED, user_id=user.id, api_key=api_key
    )
    await session.delete(api_key)
    await session.commit()
    return True


async def authenticate_api_key(
    session: AsyncSession, token: str
) -> tuple[User, UserApiKey] | None:
    """Resolve a ``ppk_`` token to its ``(user, key)`` pair, or ``None``.

    Returns the key alongside the user so callers can enforce its scope
    (``read_only`` / ``guild_id``) — the user object alone carries no record of
    which credential authenticated the request.

    ``user_api_keys`` is a pre-auth credential store (looked up by ``token_hash``
    before the user is known), so it carries no request-path grant and no own-row
    policy — the lookup runs on the system engine (``SystemSessionLocal``), like
    ``auth_sessions``. The resolved ``User`` is loaded on the caller's request
    ``session`` so it stays attached for the rest of the request; only the
    detached ``api_key``'s already-loaded scope columns are read downstream.
    """
    from app.db.session import SystemSessionLocal

    token_hash = _hash_token(token)
    async with SystemSessionLocal() as system_session:
        statement = select(UserApiKey).where(
            UserApiKey.token_hash == token_hash, UserApiKey.is_active.is_(True)
        )
        api_key = (await system_session.exec(statement)).one_or_none()
        if not api_key:
            return None

        now = datetime.now(UTC)
        if api_key.expires_at and api_key.expires_at <= now:
            return None

        user = (
            await session.exec(select(User).where(User.id == api_key.user_id))
        ).one_or_none()
        if not user or user.status != UserStatus.active:
            return None

        # Record use only once an active user is confirmed, and at most once
        # per resolution window, so a busy key does not write on every request.
        if (
            api_key.last_used_at is None
            or now - api_key.last_used_at >= API_KEY_LAST_USED_RESOLUTION
        ):
            api_key.last_used_at = now
            await system_session.commit()

    return user, api_key


async def delete_resource_keys(*, user_id: int, guild_id: int) -> None:
    """Delete the keys ``user_id`` holds for single resources of ``guild_id``.

    Called when they leave it. ``user_api_keys`` is the system engine's, and
    the caller's session is routed into the guild, so this commits on a session
    of its own, as :func:`authenticate_api_key` reads on one.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        keys = (
            await system_session.exec(
                select(UserApiKey).where(
                    UserApiKey.user_id == user_id,
                    UserApiKey.guild_id == guild_id,
                    UserApiKey.resource_type.is_not(None),
                )
            )
        ).all()
        for key in keys:
            await _record_key_event(
                system_session,
                AuditEventType.API_KEY_DELETED,
                user_id=user_id,
                api_key=key,
            )
            await system_session.delete(key)
        await system_session.commit()


def _live(now: datetime) -> ColumnElement[bool]:
    """A key that would still authenticate: switched on and not yet expired."""
    return and_(
        UserApiKey.is_active.is_(True),
        or_(UserApiKey.expires_at.is_(None), UserApiKey.expires_at > now),
    )


async def live_counts(session: AsyncSession, *, user_ids: list[int]) -> dict[int, int]:
    """How many keys that still work each of these accounts holds. One query
    for the whole page."""
    rows = await session.exec(
        select(UserApiKey.user_id, func.count())
        .where(UserApiKey.user_id.in_(user_ids), _live(datetime.now(UTC)))
        .group_by(UserApiKey.user_id)
    )
    return {user_id: count for user_id, count in rows.all()}


async def deactivate_user_api_keys(
    session: AsyncSession, *, user_id: int, revoked_by: int | None = None
) -> int:
    """Switch off every key of ``user_id`` that still works, and return the count.

    A password change or reset calls this so the account's keys go with the old
    password. Staff revoking them pass ``revoked_by``, and each key's departure
    is recorded against them. Does not commit — the caller owns the transaction.
    """
    statement = select(UserApiKey).where(
        UserApiKey.user_id == user_id, _live(datetime.now(UTC))
    )
    result = await session.exec(statement)
    keys = result.all()
    for key in keys:
        key.is_active = False
        session.add(key)
        if revoked_by is not None:
            await _record_key_event(
                session,
                AuditEventType.API_KEY_REVOKED,
                user_id=user_id,
                api_key=key,
                actor_user_id=revoked_by,
            )
    return len(keys)
