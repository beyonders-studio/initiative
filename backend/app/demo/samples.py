"""Sample accounts: accounts the demo's sign-in page lists with their address
and password, so anyone may sign in to one and look around.

The demo plug-in names them on each of its runs, and :func:`keep` puts each
back as it says: its address and password, no other way in, nobody signed in,
nothing on its profile, every notification that would leave the app off. One
it no longer names goes back to being a persona, an account nobody signs in to.

Between runs a sample can do what any member can, but nothing that would change
how somebody else signs in to it or what they find there: its sign-in, its
devices and its sessions are not its own to change (:func:`refuse`), it is
never sent mail (:func:`addresses_of`), and wrong passwords do not lock it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_email, normalize_email
from app.core.messages import DemoMessages
from app.core.security import get_password_hash, verify_password
from app.db import cohorts
from app.demo import accounts
from app.models.platform.account_change_hold import AccountChangeHold
from app.models.platform.api_key import UserApiKey
from app.models.platform.demo import DemoSample
from app.models.platform.dm_conversation import DmConversationMember
from app.models.platform.dm_device import DmDevice
from app.models.platform.guild import GuildMembership
from app.models.platform.mfa_recovery_code import MfaRecoveryCode
from app.models.platform.push_token import PushToken
from app.models.platform.sign_in_lock import SignInLock
from app.models.platform.user import User
from app.models.platform.user_dm_settings import UserDmSettings
from app.models.platform.user_email import UserEmail
from app.models.platform.user_passkey import UserPasskey
from app.models.platform.user_token import UserToken
from app.models.platform.user_totp import UserTotp
from app.models.platform.user_totp_secret import UserTotpSecret
from app.services.auth import addresses
from app.services.auth import identity as identity_service
from app.services.auth import sessions as session_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import user_avatars
from app.services.platform import user_tokens
from app.services.platform.notification_prefs import save_prefs

#: How a sample's address is noted on its row (``UserEmail.source``).
ADDRESS_SOURCE = "demo"


@dataclass(frozen=True)
class Sample:
    """A sample account as the plug-in names it."""

    handle: str
    display_name: str
    email: str
    password: str
    about: str | None = None


@dataclass(frozen=True)
class Listed:
    """A sample as the sign-in page lists it."""

    display_name: str
    email: str
    password: str
    about: str | None


class AddressTaken(Exception):
    """The address signs in to an account that is not this sample."""


async def is_sample(user_id: int) -> bool:
    """Whether ``user_id`` is a sample account. Always false outside the
    demo."""
    if not settings.DEMO_MODE:
        return False
    async with cohorts.system_session(None) as session:
        return await session.get(DemoSample, user_id) is not None


async def refuse(user: User) -> None:
    """403 ``DEMO_SAMPLE_ACCOUNT`` for a sample account."""
    if await is_sample(cast(int, user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DemoMessages.DEMO_SAMPLE_ACCOUNT,
        )


async def addresses_of(emails: Sequence[str]) -> set[str]:
    """Those of ``emails`` that a sample account signs in with. Always empty
    outside the demo."""
    if not settings.DEMO_MODE or not emails:
        return set()
    by_hash = {hash_email(normalize_email(email)): email for email in emails}
    async with cohorts.system_session(None) as session:
        found = await session.exec(
            select(UserEmail.email_hash)
            .join(DemoSample, col(DemoSample.user_id) == UserEmail.user_id)
            .where(col(UserEmail.email_hash).in_(list(by_hash)))
        )
        return {by_hash[digest] for digest in found.all()}


async def listed() -> list[Listed]:
    """Every sample, in the order the sign-in page lists them."""
    async with cohorts.system_session(None) as session:
        rows = await session.exec(select(DemoSample).order_by(col(DemoSample.position)))
        return [
            Listed(
                display_name=row.display_name,
                email=row.email,
                password=row.password,
                about=row.about,
            )
            for row in rows.all()
        ]


async def keep(session: AsyncSession, samples: Sequence[Sample]) -> list[int]:
    """Make each of ``samples`` that is missing and put each back as it says,
    and make every other sample a persona again. Returns the accounts whose
    sessions ended, to be closed once committed. Staged; the caller commits.

    Raises :class:`accounts.HandleTaken` for a handle that is an account
    somebody signs in to and not a sample, and :class:`AddressTaken` for an
    address another account signs in with; nothing is changed then, once the
    caller rolls back."""
    now = datetime.now(timezone.utc)
    kept: list[int] = []
    for position, sample in enumerate(samples):
        user = await _account(session, sample.handle)
        user_id = cast(int, user.id)
        await _hold_address(session, user_id=user_id, email=sample.email, now=now)
        if not verify_password(sample.password, user.hashed_password):
            user.hashed_password = get_password_hash(sample.password)
            user.password_set_at = now
        user.age_confirmed_at = user.age_confirmed_at or now
        await _clear(session, user)
        await session.exec(
            update(GuildMembership)
            .where(col(GuildMembership.user_id) == user_id)
            .values(display_name=sample.display_name)
        )
        shown = {
            "display_name": sample.display_name,
            "email": normalize_email(sample.email),
            "password": sample.password,
            "about": sample.about,
            "position": position,
        }
        row = await session.get(DemoSample, user_id)
        if row is None:
            row = DemoSample(user_id=user_id, **shown)
        else:
            row.sqlmodel_update(shown)
        session.add(row)
        kept.append(user_id)
    retired = (
        await session.exec(
            select(DemoSample).where(col(DemoSample.user_id).not_in(kept))
        )
    ).all()
    for row in retired:
        user = await session.get(User, row.user_id)
        await session.delete(row)
        if user is None:
            continue
        await session.exec(delete(UserEmail).where(col(UserEmail.user_id) == user.id))
        user.hashed_password = None
        user.password_set_at = None
        await _clear(session, user)
        kept.append(cast(int, user.id))
    await session.flush()
    return kept


async def _account(session: AsyncSession, handle: str) -> User:
    """The account ``handle`` names when it is a sample or a persona, made
    when there is none."""
    user = await accounts.by_handle(session, handle)
    if user is None:
        return await accounts.create(session, handle=handle)
    if await session.get(DemoSample, user.id) is not None:
        return user
    persona = (
        await session.exec(
            select(User.id).where(
                User.id == user.id,
                accounts.unloginable(),
                ~accounts.visitor(),
            )
        )
    ).first()
    if persona is None or handle.lower() == accounts.HOST_HANDLE:
        raise accounts.HandleTaken(handle)
    return user


async def _hold_address(
    session: AsyncSession, *, user_id: int, email: str, now: datetime
) -> None:
    """Make ``email`` the account's one address, proven and primary."""
    owner = await addresses.find_user_by_address(session, email)
    if owner is not None and owner.id != user_id:
        raise AddressTaken(email)
    digest = hash_email(normalize_email(email))
    await session.exec(
        delete(UserEmail).where(
            col(UserEmail.user_id) == user_id, col(UserEmail.email_hash) != digest
        )
    )
    held = (
        await session.exec(
            select(UserEmail).where(
                col(UserEmail.user_id) == user_id, col(UserEmail.email_hash) == digest
            )
        )
    ).first()
    if held is None:
        addresses.record_address(
            session,
            user_id=user_id,
            email=email,
            source=ADDRESS_SOURCE,
            verified=True,
            is_primary=True,
            now=now,
        )
        return
    held.verified_at = held.verified_at or now
    held.is_primary = True
    session.add(held)


async def _clear(session: AsyncSession, user: User) -> None:
    """Every way in but the password, every device and session, what its
    profile wears, its direct messages, and its settings back to a fresh
    persona's."""
    user_id = cast(int, user.id)
    for model in (
        UserPasskey,
        UserTotpSecret,
        UserTotp,
        MfaRecoveryCode,
        UserApiKey,
        UserToken,
        AccountChangeHold,
        PushToken,
        SignInLock,
        DmDevice,
        DmConversationMember,
        UserDmSettings,
    ):
        await session.exec(delete(model).where(col(model.user_id) == user_id))
    await identity_service.delete_user_identities(session, user_id=user_id)
    await user_tokens.revoke_user_sessions(session, user=user)
    await session_service.delete_all_for_user(session, user_id=user_id)
    await user_avatars.delete_avatar(session, user_id=user_id, user=user)
    user.avatar_url = None
    user.custom_status = {}
    user.profile_decorations = {}
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await dm_settings_service.seed_for_new_account(session, user_id=user_id)
    await save_prefs(session, user_id, accounts.SILENT)
