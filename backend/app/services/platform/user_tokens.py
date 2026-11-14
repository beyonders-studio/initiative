"""Single-use tokens (``user_tokens``): address confirmation and password reset.

The table is read and written on the system engine alone, like
``auth_sessions`` and ``user_api_keys``: every function here takes a session on
``app_admin``.
"""

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlmodel import col, delete, select
from sqlmodel import update as sql_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services.auth import challenges as challenge_service
from app.services.auth import sessions as session_service
from app.services.platform import api_keys as api_keys_service

DEFAULT_TOKEN_TTL_MINUTES = 60


def _hash_token(token: str) -> str:
    """Hash a token for storage/lookup.

    Tokens are high-entropy random secrets (``secrets.token_urlsafe(48)``), so a
    single unsalted SHA-256 is sufficient and keeps lookups indexable — this
    mirrors ``app.services.api_keys._hash_token``.
    """
    return sha256(token.encode("utf-8")).hexdigest()


async def _delete_existing_tokens(
    session: AsyncSession,
    user_id: int,
    purpose: UserTokenPurpose,
    user_email_id: int | None = None,
) -> None:
    """Drop the outstanding tokens a new one replaces.

    Scoped to the address when there is one: an account proving two addresses
    has one pending token per address, and issuing the second must not spend
    the first.
    """
    stmt = delete(UserToken).where(
        UserToken.user_id == user_id,
        UserToken.purpose == purpose,
    )
    stmt = stmt.where(
        UserToken.user_email_id == user_email_id
        if user_email_id is not None
        else UserToken.user_email_id.is_(None)
    )
    await session.exec(stmt)


async def create_token(
    session: AsyncSession,
    *,
    user_id: int,
    purpose: UserTokenPurpose,
    expires_minutes: int = DEFAULT_TOKEN_TTL_MINUTES,
    user_email_id: int | None = None,
    invite_id: int | None = None,
    change: dict[str, Any] | None = None,
    commit: bool = True,
) -> str:
    """Issue a token of ``purpose``, replacing the outstanding one it supersedes.

    An ``account_change`` token replaces nothing: each letter carries its own,
    and a second notice must not spend the link in the first.

    ``commit=False`` stages the swap instead, for a caller that commits only
    once the token has been delivered, so the one it replaces stays good if
    delivery fails.
    """
    if purpose is not UserTokenPurpose.account_change:
        await _delete_existing_tokens(session, user_id, purpose, user_email_id)
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    token = UserToken(
        user_id=user_id,
        token=_hash_token(token_value),
        purpose=purpose,
        user_email_id=user_email_id,
        invite_id=invite_id,
        change=change,
        expires_at=expires_at,
    )
    session.add(token)
    if commit:
        await session.commit()
    # Return the raw token exactly once; only its hash is persisted.
    return token_value


async def get_valid_token(
    session: AsyncSession,
    *,
    token: str,
    purpose: UserTokenPurpose,
) -> UserToken | None:
    stmt = select(UserToken).where(
        UserToken.token == _hash_token(token),
        UserToken.purpose == purpose,
    )
    result = await session.exec(stmt)
    record = result.one_or_none()
    if not record:
        return None
    if record.consumed_at is not None:
        return None
    if record.expires_at < datetime.now(UTC):
        return None
    return record


async def consume_token(
    session: AsyncSession,
    *,
    token: str,
    purpose: UserTokenPurpose,
    commit: bool = True,
) -> UserToken | None:
    """Spend a live token and return it, or ``None``.

    One conditional update claims it, so a token is spent once however many
    requests present it at the same moment.

    ``commit=False`` stages the spend, for a caller whose work and spend must
    land together, so a link whose work failed stays good.
    """
    now = datetime.now(UTC)
    claimed = (
        await session.exec(
            sql_update(UserToken)
            .where(
                col(UserToken.token) == _hash_token(token),
                col(UserToken.purpose) == purpose,
                col(UserToken.consumed_at).is_(None),
                col(UserToken.expires_at) > now,
            )
            .values(consumed_at=now)
            .returning(col(UserToken.id))
        )
    ).first()
    if claimed is None:
        return None
    if commit:
        await session.commit()
    return await session.get(UserToken, claimed[0], populate_existing=True)


async def purge_expired_tokens(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    stmt = delete(UserToken).where(UserToken.expires_at < now)
    await session.exec(stmt)
    await session.commit()


# ``user_tokens`` and ``auth_challenges`` are read and written on the system
# engine alone (see app/db/system_grants.py), so the sweep runs on
# SystemSessionLocal with no guild routing.
TOKEN_PURGE_POLL_SECONDS = 3600


async def process_expired_token_purge() -> None:
    """Hourly background sweep: delete the rows nothing can use again.

    Covers consumed and expired password-reset and email-verify tokens, and the
    part-way sign-ins in ``auth_challenges``, which end the same way.
    Without it, those rows accumulate forever.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        await purge_expired_tokens(session)
        await challenge_service.purge_expired(session)
        await session.commit()


async def revoke_user_sessions(
    system_session: AsyncSession,
    *,
    user: User,
) -> None:
    """Invalidate every outstanding session for ``user`` after a credential
    change.

    Bumps ``token_version`` (which the JWT/WS authenticators compare against,
    invalidating any still-unexpired access token), deactivates their API keys,
    and revokes their rotating **refresh sessions**, so no refresh mints an
    access token at the new ``token_version`` either. Shared by every
    password write (``set_password``), the credentials retired when an address
    is first proved, and the sign-out an account notice answers.

    Every table this writes is the system engine's, so the revocations share
    ``system_session``'s transaction. ``token_version`` is bumped on ``user``
    wherever it is bound. Nothing is committed here: the caller commits the
    revocations with the change they follow, and with the session that
    replaces the caller's where it opens one, so a failure leaves the account
    holding everything it had.
    """
    user.token_version += 1
    await api_keys_service.deactivate_user_api_keys(system_session, user_id=user.id)
    await session_service.revoke_all_for_user(system_session, user_id=user.id)
    # A sign-in part-way through rests on the password it proved, so it goes
    # with the rest rather than standing until it expires.
    await challenge_service.revoke_for_user(system_session, user_id=user.id)
