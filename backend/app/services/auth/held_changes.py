"""Changes to how an account is signed into, made now or after a wait.

Four changes can wait: making an address primary, removing a proved address,
turning two-factor authentication off, and removing the account's last
passkey. A risky request for one is held for :data:`HOLD_FOR` rather than
made. Every proved address is told, with a link that cancels it; the
account's settings list it with Cancel, and a session proved with a passkey
can make it at once. :func:`apply_due` makes the ones whose time has come.

The changes themselves are here too, so a route making one straight away and
a hold making it later do the same work and send the same notice.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.encryption import SALT_EMAIL, decrypt_field
from app.models.platform.account_change_hold import AccountChangeHold, HeldChangeKind
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_passkey import UserPasskey
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import account_changes, addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import identity as identity_service
from app.services.auth import passkeys as passkey_service
from app.services.auth import sessions as session_service
from app.services.auth import totp as totp_service
from app.services.content_sockets import sockets as content_sockets

logger = logging.getLogger(__name__)

#: How long a held change waits.
HOLD_FOR = timedelta(hours=48)

#: How often the sweep looks for held changes that are due.
HOLD_SWEEP_POLL_SECONDS = 60

#: How long a cancelled or applied hold is kept, for the run of changes it
#: counts towards.
SETTLED_KEPT = timedelta(days=1)

_ADDRESS_KINDS = frozenset({HeldChangeKind.primary, HeldChangeKind.remove_address})


class ChangePending(Exception):
    """The account already has a change waiting."""


class ChangeLapsed(Exception):
    """The account no longer allows the change a hold was waiting to make."""


def _pending():
    return col(AccountChangeHold.cancelled_at).is_(None) & col(
        AccountChangeHold.applied_at
    ).is_(None)


# ── The changes ─────────────────────────────────────────────────────────────


async def make_primary(
    session: AsyncSession, user: User, *, address_id: int, risky: bool
) -> UserEmail:
    """Make ``address_id`` the primary, commit, and tell the account, the
    previous primary among its addresses. Raises ``AddressError``."""
    # Read directly: the primary can be an address the account was minted
    # with, which the address list leaves out.
    previous = (
        await session.exec(
            select(UserEmail).where(
                UserEmail.user_id == user.id, col(UserEmail.is_primary).is_(True)
            )
        )
    ).first()
    row = await addresses.set_primary_for_user(
        session, user_id=user.id, address_id=address_id
    )
    await session.commit()
    await session.refresh(row)
    if previous is None or previous.id != row.id:
        await email_service.announce_address_change(
            session,
            user,
            change="primary",
            address=decrypt_field(row.email_encrypted, SALT_EMAIL),
            record=(
                await account_changes.change_record(
                    session,
                    user_id=user.id,
                    risky=risky,
                    undo={
                        "kind": "primary",
                        # A minted address takes no mail, so undoing a move
                        # away from one moves the primary to the address
                        # whose link was clicked.
                        "address_id": (
                            None
                            if previous.source == addresses.SOURCE_SYNTHETIC
                            else previous.id
                        ),
                        "made_primary": row.id,
                    },
                )
                if previous is not None
                else None
            ),
        )
    return row


async def remove_address(
    session: AsyncSession, user: User, *, address_id: int, risky: bool
) -> None:
    """Stop holding ``address_id``, commit, and tell the account and the
    address. Raises ``AddressError``."""
    # What undoing it would put back, read while the account still holds it.
    target = await session.get(UserEmail, address_id)
    record = (
        await account_changes.change_record(
            session,
            user_id=user.id,
            risky=risky,
            undo=account_changes.removal_undo(
                target,
                # Read directly: the primary can be an address the account
                # was minted with, which the address list leaves out.
                primary_id=(
                    await session.exec(
                        select(UserEmail.id).where(
                            UserEmail.user_id == user.id,
                            col(UserEmail.is_primary).is_(True),
                        )
                    )
                ).first(),
            ),
        )
        if target is not None
        and target.user_id == user.id
        and target.verified_at is not None
        else None
    )
    row = await addresses.remove_for_user(
        session, user_id=user.id, address_id=address_id
    )
    # Read before the commit, which leaves the deleted row behind.
    removed = decrypt_field(row.email_encrypted, SALT_EMAIL)
    proved = row.verified_at is not None
    await session.commit()
    # An address nobody proved was never a way in, nor known to be this
    # account's to write to.
    if proved:
        await email_service.announce_address_removed(
            session, user, address=removed, record=record
        )


async def turn_off_second_factor(
    session: AsyncSession, user: User, *, kept_session_id: uuid.UUID | str | None
) -> None:
    """Remove the factor, its seed and its recovery codes, end every session
    but ``kept_session_id`` and its renewals, commit, and tell the account."""
    if not await totp_service.disable(session, user_id=user.id):
        raise ChangeLapsed()
    await challenge_service.revoke_for_user(session, user_id=user.id)
    await session_service.revoke_all_for_user(
        session,
        user_id=user.id,
        except_session_id=str(kept_session_id) if kept_session_id else None,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_DISABLED,
        actor_user_id=user.id,
        detail={"method": "totp"},
    )
    await session.commit()
    # Connections opened on the ended sessions close; the kept one's stay.
    await content_sockets.revoke_user_everywhere(user.id)
    await email_service.announce_second_factor_change(session, user, enabled=False)


async def remove_passkey(
    session: AsyncSession, user: User, *, passkey_id: uuid.UUID
) -> bool:
    """Forget the passkey, commit, and tell the account. ``False`` where the
    account holds no such passkey."""
    existing = await session.get(UserPasskey, passkey_id)
    # Read the name while the row is still there, so the letter can say which
    # credential went.
    name = existing.name if existing is not None else ""
    if not await passkey_service.remove(
        session, user_id=user.id, passkey_id=passkey_id
    ):
        return False
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_PASSKEY_REMOVED,
        actor_user_id=user.id,
        detail={"passkey_id": str(passkey_id)},
    )
    await session.commit()
    await email_service.announce_passkey_change(session, user, added=False, name=name)
    return True


# ── Holding them ────────────────────────────────────────────────────────────


async def pending_for_user(
    session: AsyncSession, *, user_id: int
) -> AccountChangeHold | None:
    """The change this account has waiting, if any."""
    return (
        await session.exec(
            select(AccountChangeHold).where(
                AccountChangeHold.user_id == user_id, _pending()
            )
        )
    ).first()


async def pending_hold(
    session: AsyncSession, *, user_id: int, hold_id: object
) -> AccountChangeHold | None:
    """The waiting change ``hold_id``, while it is this account's and still
    waiting."""
    hold = await pending_for_user(session, user_id=user_id)
    return hold if hold is not None and hold.id == hold_id else None


async def subject_of(session: AsyncSession, hold: AccountChangeHold) -> str | None:
    """What a held change acts on: an address, or a passkey's name."""
    if hold.address_id is not None:
        row = await session.get(UserEmail, hold.address_id)
        return decrypt_field(row.email_encrypted, SALT_EMAIL) if row else None
    if hold.passkey_id is not None:
        passkey = await session.get(UserPasskey, hold.passkey_id)
        return passkey.name if passkey else None
    return None


async def hold(
    session: AsyncSession,
    user: User,
    *,
    kind: HeldChangeKind,
    session_id: uuid.UUID | None,
    address_id: int | None = None,
    passkey_id: uuid.UUID | None = None,
) -> AccountChangeHold:
    """Record the change to be made after :data:`HOLD_FOR`, commit what the
    request has staged with it, and tell the account. Raises
    :class:`ChangePending` while another change waits."""
    now = datetime.now(UTC)
    row = AccountChangeHold(
        user_id=user.id,
        kind=kind,
        address_id=address_id,
        passkey_id=passkey_id,
        session_id=session_id,
        requested_at=now,
        applies_at=now + HOLD_FOR,
    )
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError as exc:
        raise ChangePending() from exc
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_CHANGE_HELD,
        actor_user_id=user.id,
        detail={"hold_id": row.id, "kind": kind.value},
    )
    record = await account_changes.change_record(
        session,
        user_id=user.id,
        risky=True,
        undo={"kind": "hold", "hold_id": row.id},
        any_address=kind not in _ADDRESS_KINDS,
    )
    subject = await subject_of(session, row)
    await session.commit()
    await session.refresh(row)
    await email_service.announce_held_change(
        user,
        kind=kind.value,
        subject=subject,
        applies_at=row.applies_at,
        record=record,
    )
    return row


async def cancel(
    session: AsyncSession, *, user_id: int, hold_id: object, via: str
) -> bool:
    """Cancel the waiting change ``hold_id``, staged in ``session``. ``False``
    where it is not this account's or no longer waits."""
    if not isinstance(hold_id, int):
        return False
    kind = (
        await session.exec(
            update(AccountChangeHold)
            .where(
                col(AccountChangeHold.id) == hold_id,
                col(AccountChangeHold.user_id) == user_id,
                _pending(),
            )
            .values(cancelled_at=datetime.now(UTC))
            .returning(AccountChangeHold.kind)
        )
    ).scalar_one_or_none()
    if kind is None:
        return False
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_HELD_CHANGE_CANCELLED,
        actor_user_id=user_id,
        detail={"hold_id": hold_id, "kind": kind, "via": via},
    )
    return True


async def apply(
    session: AsyncSession,
    user: User,
    *,
    hold_id: int,
    risky: bool,
    keep_session: uuid.UUID | None = None,
) -> bool:
    """Make the waiting change ``hold_id`` now, and tell the account as the
    change itself would. ``False`` where it no longer waits, or the account
    no longer allows it, which cancels it.

    A change that ends other sessions keeps ``keep_session``, or else the one
    that asked for it."""
    now = datetime.now(UTC)
    user_id = user.id
    # Claimed and made in one transaction, so a second sweep finds it gone.
    claimed = (
        await session.exec(
            update(AccountChangeHold)
            .where(
                col(AccountChangeHold.id) == hold_id,
                col(AccountChangeHold.user_id) == user_id,
                _pending(),
            )
            .values(applied_at=now)
            .returning(
                AccountChangeHold.kind,
                AccountChangeHold.address_id,
                AccountChangeHold.passkey_id,
                AccountChangeHold.session_id,
                AccountChangeHold.requested_at,
            )
        )
    ).first()
    if claimed is None:
        return False
    kind, address_id, passkey_id, session_id, requested_at = claimed
    # The hold is kept past the address or passkey it removes, for the run of
    # changes it counts towards.
    await session.exec(
        update(AccountChangeHold)
        .where(col(AccountChangeHold.id) == hold_id)
        .values(address_id=None, passkey_id=None)
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_HELD_CHANGE_APPLIED,
        actor_user_id=user_id,
        detail={"hold_id": hold_id, "kind": kind},
    )
    try:
        if kind == HeldChangeKind.primary:
            await make_primary(session, user, address_id=address_id, risky=risky)
        elif kind == HeldChangeKind.remove_address:
            await remove_address(session, user, address_id=address_id, risky=risky)
        elif kind == HeldChangeKind.second_factor_off:
            # Only the factor the account held when it asked.
            factor = await totp_service.get_factor(session, user_id=user_id)
            if (
                factor is None
                or factor.confirmed_at is None
                or factor.confirmed_at > requested_at
            ):
                raise ChangeLapsed()
            await turn_off_second_factor(
                session, user, kept_session_id=keep_session or session_id
            )
        elif kind == HeldChangeKind.last_passkey:
            if await identity_service.passkey_is_last_way_in(
                session, user_id=user_id
            ) or not await remove_passkey(session, user, passkey_id=passkey_id):
                raise ChangeLapsed()
        else:
            raise ChangeLapsed()
    except addresses.AddressError, ChangeLapsed:
        await session.rollback()
        await cancel(session, user_id=user_id, hold_id=hold_id, via="lapsed")
        await session.commit()
        return False
    return True


async def apply_due(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Make every held change whose wait is over, and forget the ones settled
    a day ago. Returns how many were made."""
    now = now or datetime.now(UTC)
    due = (
        await session.exec(
            select(AccountChangeHold.id, AccountChangeHold.user_id).where(
                _pending(), AccountChangeHold.applies_at <= now
            )
        )
    ).all()
    made = 0
    for hold_id, user_id in due:
        user = await session.get(User, user_id)
        if user is None:
            continue
        try:
            made += await apply(session, user, hold_id=hold_id, risky=True)
        except Exception:
            await session.rollback()
            logger.exception("held change %s could not be made", hold_id)
    await session.exec(
        delete(AccountChangeHold).where(
            or_(
                col(AccountChangeHold.cancelled_at) < now - SETTLED_KEPT,
                col(AccountChangeHold.applied_at) < now - SETTLED_KEPT,
            )
        )
    )
    await session.commit()
    return made


async def process_due_holds() -> None:
    """Background sweep: make the held changes that are due."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        made = await apply_due(session)
    if made:
        logger.info("held account changes: made %s", made)
