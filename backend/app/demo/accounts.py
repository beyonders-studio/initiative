"""The demo's own accounts: the demo host, the personas its communities cast,
and each visitor's account.

All are made with no password and no address, so nothing can sign in to one
but the session the demo opens for it, and every notification that would
leave the app is off.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ColumnElement, and_, exists, func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.notification_categories import CATEGORY_SPECS, Channel
from app.models.platform.demo import DemoAccount
from app.models.platform.guild import GuildMembership
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.services import audit as audit_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import usernames as username_service
from app.services.platform.notification_prefs import save_prefs

#: The account every pitch and pool community is created by.
HOST_HANDLE = "demo-host#0001"

#: Nothing leaves the app.
_SILENT = {
    "categories": {
        category.value: {
            channel.value: False
            for channel in spec.mutable_channels
            if channel is not Channel.in_app
        }
        for category, spec in CATEGORY_SPECS.items()
    }
}


def unloginable() -> ColumnElement[bool]:
    """Accounts with no password and no address."""
    return and_(
        User.hashed_password.is_(None),
        ~exists().where(UserEmail.user_id == User.id),
    )


async def by_handle(session: AsyncSession, handle: str) -> User | None:
    """The account whose whole handle, ``name#1234``, is ``handle``."""
    name, number = _split(handle)
    return (
        await session.exec(
            select(User).where(
                func.lower(User.username) == name.lower(),
                User.discriminator == number,
            )
        )
    ).one_or_none()


async def demo_host(session: AsyncSession) -> User:
    """The demo host's account, made the first time it is needed."""
    return await by_handle(session, HOST_HANDLE) or await create(
        session, handle=HOST_HANDLE
    )


class HandleTaken(Exception):
    """The handle belongs to an account that is not a persona."""


async def ensure_persona(
    session: AsyncSession, *, handle: str, display_name: str
) -> User:
    """The persona ``handle`` names, made when there is none, called
    ``display_name`` in every community it is in. Raises :class:`HandleTaken`
    when the handle is somebody's account, a visitor's or the demo host's.
    Staged; the caller commits."""
    user = await by_handle(session, handle)
    if user is None:
        user = await create(session, handle=handle)
    elif (
        handle.lower() == HOST_HANDLE
        or (
            await session.exec(
                select(User.id).where(
                    User.id == user.id,
                    ~unloginable() | exists().where(DemoAccount.user_id == User.id),
                )
            )
        ).first()
    ):
        raise HandleTaken(handle)
    if user.age_confirmed_at is None:
        user.age_confirmed_at = datetime.now(timezone.utc)
        session.add(user)
    await session.exec(
        update(GuildMembership)
        .where(GuildMembership.user_id == user.id)
        .values(display_name=display_name)
    )
    return user


async def create(session: AsyncSession, *, handle: str | None = None) -> User:
    """A new account with ``handle``, or a generated one when it is ``None``.
    Staged; the caller commits."""
    if handle is None:
        name, number = await username_service.allocate_from_seed(session)
    else:
        name, number = _split(handle)
    user = User(
        username=name,
        discriminator=number,
        username_chosen=True,
        # Listed communities seat only accounts that answered the age
        # question, and nobody can answer it for the host or a persona.
        age_confirmed_at=None if handle is None else datetime.now(timezone.utc),
    )
    session.add(user)
    await session.flush()
    await dm_settings_service.seed_for_new_account(session, user_id=user.id)
    await save_prefs(session, user.id, _SILENT)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_CREATED,
        actor_user_id=None,
        target_user_id=user.id,
        detail={"via": "demo"},
    )
    return user


def _split(handle: str) -> tuple[str, int]:
    name, _, number = handle.partition("#")
    return name, int(number)
