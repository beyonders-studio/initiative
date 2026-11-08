"""Resolving an address to an account, and keeping the set of them.

An account has many addresses and signs in with any of them. ``user_emails``
is where they live, in the same two representations ``users`` has always used:
a keyed HMAC for the equality lookup and a Fernet ciphertext for reading the
address back.

Runs on the system engine. ``user_emails`` carries no request-path grants for
the same reason ``auth_sessions`` carries none: resolving an address happens
before there is anybody to scope a policy to.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import (
    SALT_EMAIL,
    decrypt_field,
    encrypt_field,
    hash_email,
    normalize_email,
)
from app.core.errors import CodedError
from app.core.messages import AddressMessages
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_email_assertion import UserEmailAssertion

logger = logging.getLogger(__name__)

# Where an address came from, for whoever reads the row.
SOURCE_SIGNUP = "signup"
SOURCE_ADDED = "added"
SOURCE_OIDC = "oidc"
SOURCE_SYNTHETIC = "synthetic"

#: How many addresses one account keeps. A person collects a handful; a
#: listing that grows without end is nobody's account page.
MAX_ADDRESSES_PER_ACCOUNT = 10


async def find_user_by_address(session: AsyncSession, email: str) -> User | None:
    """The account that signs in with ``email``, or ``None``."""
    digest = hash_email(email)
    return (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(
                UserEmail.email_hash == digest,
                # Proven only (§6.2 rule 2). An unproven row is a claim
                # somebody is in the middle of making, and it signs in nobody.
                UserEmail.verified_at.is_not(None),
            )
        )
    ).one_or_none()


async def account_awaiting_confirmation(
    session: AsyncSession, email: str
) -> User | None:
    """The account that signed up with ``email`` and has not confirmed it.

    Only for telling somebody their address is unconfirmed rather than their
    password wrong. ``find_user_by_address`` is what admits anybody, and it
    reads proven rows alone; this reads the nominated address whether or not it
    has been proved, so the sign-in that follows can refuse in the words that
    say what to do about it.
    """
    digest = hash_email(email)
    return (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(
                UserEmail.email_hash == digest,
                UserEmail.is_primary,
                UserEmail.verified_at.is_(None),
                UserEmail.source != SOURCE_SYNTHETIC,
            )
            .order_by(User.id)
        )
    ).first()


async def account_holding(session: AsyncSession, email: str) -> User | None:
    """The account this address belongs to, confirmed or not.

    ``find_user_by_address`` answers a narrower question — who may *sign in*
    with it, which is proven rows alone (§6.2 rule 2). This answers who holds
    it at all, which is what is asked before a second account is made for the
    same address, before a registration is accepted, and before account mail is
    sent somewhere.
    """
    return await find_user_by_address(
        session, email
    ) or await account_awaiting_confirmation(session, email)


async def row_for(session: AsyncSession, email: str) -> UserEmail | None:
    """The address row itself, proved or not.

    :func:`account_holding` answers who holds an address; this hands back the
    row, for a caller that has to say something about that particular address
    rather than about the account behind it.
    """
    return await _by_hash(session, hash_email(email))


async def note_sign_in(
    session: AsyncSession, *, email: str, now: datetime | None = None
) -> None:
    """Stamp the address a sign-in resolved through.

    Staged in the caller's transaction, beside the session the sign-in opens.
    """
    await session.exec(
        update(UserEmail)
        .where(UserEmail.email_hash == hash_email(email))
        .values(last_login_at=now or datetime.now(UTC))
    )


async def proven_addresses(session: AsyncSession, *, user_id: int) -> list[str]:
    """Every address this account has proved, in full.

    Where account mail goes (§6.2 rule 4): a letter about the account itself
    reaches all of them, so somebody who no longer reads one address still
    hears about a change they did not make.

    An account that has proved none — it signed up before addresses had to be
    confirmed and never confirmed one — is written to at its primary, which is
    where its mail has always gone. Reset mail is how somebody in that position
    gets back in, so it has somewhere to arrive.
    """
    proved = await proved_only(session, user_id=user_id)
    if proved:
        return proved
    sole = await primary_address(session, user_id=user_id)
    return [sole] if sole else []


async def proved_only(session: AsyncSession, *, user_id: int) -> list[str]:
    """The addresses this account has proved, primary first — with no fallback.

    Where a code that confirms the account may go: an address somebody added
    and never proved is not known to be theirs.
    """
    rows = (
        await session.exec(
            select(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.verified_at.is_not(None),
                UserEmail.source != SOURCE_SYNTHETIC,
            )
            .order_by(UserEmail.is_primary.desc(), UserEmail.id)
        )
    ).all()
    return [decrypt_field(row.email_encrypted, SALT_EMAIL) for row in rows]


def _primary_clause(
    user_ids: Sequence[int],
) -> tuple[ColumnElement[bool] | bool, ...]:
    """The primary row, for accounts that have one.

    Proven or not: an account that never confirmed the address it signed up
    with still reads its mail there, which is why §6.3 carries no CHECK tying
    ``is_primary`` to ``verified_at``. Synthetic rows are excluded — they name
    a subject at an IdP, not a mailbox.
    """
    return (
        UserEmail.user_id.in_(user_ids),
        UserEmail.is_primary,
        UserEmail.source != SOURCE_SYNTHETIC,
    )


async def primary_address(session: AsyncSession, *, user_id: int) -> str | None:
    """The one address an account is written to, or ``None``.

    Where everything that is not account mail goes — a mention, a digest, an
    invitation. Account mail reaches every proven address instead
    (``proven_addresses``, §6.2 rule 4); ordinary mail reaches the one the
    person nominated.
    """
    return (await primary_addresses(session, user_ids=[user_id])).get(user_id)


async def primary_addresses(
    session: AsyncSession, *, user_ids: Sequence[int]
) -> dict[int, str]:
    """``primary_address`` for many accounts at once, keyed by account.

    An account with no primary row is absent rather than present and empty.
    """
    if not user_ids:
        return {}
    rows = (
        await session.exec(select(UserEmail).where(*_primary_clause(user_ids)))
    ).all()
    return {row.user_id: decrypt_field(row.email_encrypted, SALT_EMAIL) for row in rows}


async def has_proven_address(session: AsyncSession, *, user_id: int) -> bool:
    """Whether this account holds an address somebody has proved."""
    return user_id in await accounts_with_a_proven_address(session, user_ids=[user_id])


async def accounts_with_a_proven_address(
    session: AsyncSession, *, user_ids: Sequence[int]
) -> set[int]:
    """Which of these accounts hold an address somebody has proved."""
    if not user_ids:
        return set()
    return set(
        (
            await session.exec(
                select(UserEmail.user_id).where(
                    UserEmail.user_id.in_(user_ids),
                    UserEmail.verified_at.is_not(None),
                    UserEmail.source != SOURCE_SYNTHETIC,
                )
            )
        ).all()
    )


async def held_hashes(session: AsyncSession, *, user_id: int) -> set[str]:
    """The hashes of every address this account holds, proven or not.

    What erasure needs: an unproven claim is still a recorded address, and an
    invite bound to one keeps the same trace as an invite bound to a proven
    one.
    """
    rows = (
        await session.exec(
            select(UserEmail.email_hash).where(UserEmail.user_id == user_id)
        )
    ).all()
    return set(rows)


async def holds_address(session: AsyncSession, *, user_id: int, email: str) -> bool:
    """Whether this account holds ``email`` — any of its addresses, not just
    the one it was created with.

    Resolves through the same lookup a sign-in uses, so the proven-only rule is
    stated once.
    """
    resolved = await find_user_by_address(session, email)
    return resolved is not None and resolved.id == user_id


def record_address(
    session: AsyncSession,
    *,
    user_id: int,
    email: str,
    source: str,
    verified: bool,
    is_primary: bool = True,
    now: datetime | None = None,
) -> UserEmail:
    """Stage an address for ``user_id`` in ``session``'s own transaction.

    Staged rather than committed so the address lands with whatever created the
    account.
    """
    row = _build_address(
        user_id=user_id,
        email=email,
        source=source,
        verified=verified,
        is_primary=is_primary,
        now=now,
    )
    session.add(row)
    return row


def _build_address(
    *,
    user_id: int,
    email: str,
    source: str,
    verified: bool,
    is_primary: bool,
    now: datetime | None = None,
) -> UserEmail:
    """The row, unattached — so a caller can stage it inside a savepoint."""
    moment = now or datetime.now(UTC)
    normalized = normalize_email(email)
    return UserEmail(
        user_id=user_id,
        email_hash=hash_email(normalized),
        email_encrypted=encrypt_field(normalized, SALT_EMAIL),
        verified_at=moment if verified else None,
        is_primary=is_primary,
        source=source,
        created_at=moment,
    )


async def note_assertion(
    session: AsyncSession,
    *,
    user_email_id: int,
    provider_id: int,
    now: datetime | None = None,
) -> None:
    """Record that ``provider_id`` asserts this address, or refresh when it
    last did. Providers do not displace one another — two directories can name
    the same address and each keeps its own standing claim."""
    moment = now or datetime.now(UTC)
    await session.exec(
        pg_insert(UserEmailAssertion)
        .values(
            user_email_id=user_email_id,
            provider_id=provider_id,
            first_asserted_at=moment,
            last_asserted_at=moment,
        )
        .on_conflict_do_update(
            index_elements=["user_email_id", "provider_id"],
            set_={"last_asserted_at": moment},
        )
    )


async def ensure_address(
    session: AsyncSession,
    *,
    user_id: int,
    email: str,
    source: str,
    verified: bool,
    provider_id: int | None = None,
    now: datetime | None = None,
) -> UserEmail | None:
    """Make sure ``user_id`` holds ``email``, adding it if it does not, and
    record ``provider_id``'s claim on it.

    What a provider login needs. An account that is *provisioned* by a provider
    gets its address with it; one that is *linked* already existed, and the
    address the provider asserts for it is new information — a work address
    beside a personal one.

    Idempotent, because it runs on every sign-in: an address already on this
    account gains the verification it arrived with and this provider's claim,
    and keeps everything else. An address on a **different** account is left
    alone and ``None`` comes back — an address belongs to one account, and a
    provider naming somebody else's does not move it.

    Never primary. Which address receives account mail is its owner's to
    choose, not a directory's.
    """
    moment = now or datetime.now(UTC)
    digest = hash_email(email)
    existing = await _by_hash(session, digest)

    if existing is None:
        row = _build_address(
            user_id=user_id,
            email=email,
            source=source,
            verified=verified,
            is_primary=False,
            now=moment,
        )
        try:
            # Staged and flushed entirely inside a savepoint: losing the race
            # to a concurrent sign-in for the same address rolls back to here
            # and leaves the outer transaction usable, holding no dead row.
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            existing = await _by_hash(session, digest)
            if existing is None:  # pragma: no cover - the conflict implies a row
                raise
        else:
            if provider_id is not None and row.id is not None:
                await note_assertion(
                    session,
                    user_email_id=row.id,
                    provider_id=provider_id,
                    now=moment,
                )
            return row

    if existing.user_id != user_id:
        logger.warning(
            "provider asserted an address held by account %s for account %s; "
            "left where it is",
            existing.user_id,
            user_id,
        )
        return None

    if verified and existing.verified_at is None:
        existing.verified_at = moment
        session.add(existing)
    if provider_id is not None and existing.id is not None:
        await note_assertion(
            session,
            user_email_id=existing.id,
            provider_id=provider_id,
            now=moment,
        )
    return existing


async def _by_hash(session: AsyncSession, digest: str) -> UserEmail | None:
    return (
        await session.exec(select(UserEmail).where(UserEmail.email_hash == digest))
    ).one_or_none()


async def replace_all(
    session: AsyncSession, *, user_id: int, email: str, source: str
) -> UserEmail:
    """Drop every address this account has and leave it holding ``email``.

    What erasure needs: the addresses are the personal data, and a husk keeps
    one unusable stand-in so the account still has a primary.
    """
    await session.exec(delete(UserEmail).where(UserEmail.user_id == user_id))
    return record_address(
        session,
        user_id=user_id,
        email=email,
        source=source,
        verified=False,
    )


class AddressError(CodedError):
    """A refused address operation, carrying the code the endpoint reports."""


async def list_for_user(session: AsyncSession, *, user_id: int) -> list[UserEmail]:
    """The addresses an account has, oldest first.

    Synthetic placeholders are left out: ``{subject}@oidc.local`` is not a
    mailbox and there is nothing its owner can do with it.
    """
    rows = (
        await session.exec(
            select(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.source != SOURCE_SYNTHETIC,
            )
            .order_by(UserEmail.created_at, UserEmail.id)
        )
    ).all()
    return list(rows)


async def add_for_user(
    session: AsyncSession, *, user_id: int, email: str, now: datetime | None = None
) -> UserEmail | None:
    """Start holding ``email`` for this account, unproven — or return the claim
    this account already has on it, so the letter can go out again.

    Returns ``None`` only when somebody has **proven** the address. An unproven
    claim belongs to nobody yet: the person who holds the mailbox can still
    claim it, and proving it is what settles the matter.

    The caller answers the same way whatever comes back. What it is for is
    deciding whether to write, and to which pending claim.
    """
    digest = hash_email(email)
    mine = await _pending_for_user(session, user_id=user_id, digest=digest)
    if mine is not None:
        return mine

    # How full this account is, before the address is looked at. It is a fact
    # about the account and not about who holds what, so settling it first
    # keeps the answer the same either way — the same reason the endpoint
    # settles whether the deployment can send before it gets here.
    #
    # The lock makes two additions arriving together take turns, so they count
    # each other. An account with no addresses yet has nothing to lock, and
    # nothing near the limit either.
    await _lock_addresses(session, user_id)
    if await _address_count(session, user_id) >= MAX_ADDRESSES_PER_ACCOUNT:
        raise AddressError(AddressMessages.TOO_MANY_ADDRESSES)

    if await _proven_holder(session, digest) is not None:
        return None

    row = _build_address(
        user_id=user_id,
        email=email,
        source=SOURCE_ADDED,
        verified=False,
        is_primary=False,
        now=now,
    )
    try:
        # Two additions of one address race to here; the proven-uniqueness
        # index settles nothing between two unproven rows, so this is only
        # about the account's own duplicate.
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        return await _pending_for_user(session, user_id=user_id, digest=digest)
    return row


async def verify_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    address_id: int,
    now: datetime | None = None,
) -> UserEmail:
    """Mark one address proven. Idempotent — proving it twice is proving it."""
    row = await _owned(session, user_id=user_id, address_id=address_id)
    if row.verified_at is not None:
        return row

    holder = await _proven_holder(session, row.email_hash)
    if holder is not None and holder.user_id != user_id:
        raise AddressError(AddressMessages.ADDRESS_TAKEN)

    row.verified_at = now or datetime.now(UTC)
    session.add(row)
    try:
        # Two claims on one address can be proven at the same moment; the
        # proven-uniqueness index settles which, inside a savepoint so the
        # loser leaves the outer transaction usable.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        raise AddressError(AddressMessages.ADDRESS_TAKEN) from None

    # Proving it settles every other claim on the same address.
    await session.exec(
        delete(UserEmail).where(
            UserEmail.email_hash == row.email_hash,
            UserEmail.id != row.id,
            UserEmail.verified_at.is_(None),
        )
    )
    return row


async def proved_a_new_way_in(
    session: AsyncSession, row: UserEmail | None, *, at: datetime
) -> bool:
    """Whether ``row`` was proved at ``at`` on an account that already had a
    proved address.

    A new way into the account, which it is told about wherever the proof
    arrives: the emailed link, or a provider at sign-in, on the first assertion
    or a later one. An account's first proved address is not news.
    """
    if row is None or row.verified_at != at:
        return False
    others = (
        await session.exec(
            select(func.count())
            .select_from(UserEmail)
            .where(
                UserEmail.user_id == row.user_id,
                UserEmail.id != row.id,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).one()
    return others > 0


async def remove_for_user(
    session: AsyncSession, *, user_id: int, address_id: int
) -> UserEmail:
    """Stop holding one address.

    The primary stays until another address is made primary, and the last
    verified address stays full stop — an account has to keep a way back in
    and a place to be written to.
    """
    row = await removable(session, user_id=user_id, address_id=address_id)
    await session.delete(row)
    return row


async def removable(
    session: AsyncSession, *, user_id: int, address_id: int
) -> UserEmail:
    """The address :func:`remove_for_user` would remove, or ``AddressError``."""
    row = await _owned(session, user_id=user_id, address_id=address_id)
    if row.is_primary:
        raise AddressError(AddressMessages.PRIMARY_ADDRESS)
    if row.verified_at is not None and await _verified_count(session, user_id) <= 1:
        raise AddressError(AddressMessages.LAST_VERIFIED_ADDRESS)
    return row


async def set_primary_for_user(
    session: AsyncSession, *, user_id: int, address_id: int
) -> UserEmail:
    """Move the address account mail goes to.

    Only to one this account has proved it holds: the primary is where a
    password reset lands, so moving it is a change of that destination.
    """
    row = await primary_candidate(session, user_id=user_id, address_id=address_id)
    if row.is_primary:
        return row
    # One primary per account is a partial unique index, so two promotions
    # arriving together would both stand the old one down and then raise two.
    # The lock makes them take turns; the second reads the first's result.
    await _lock_addresses(session, user_id)
    # Every primary row, the one minted for an account with no address of its
    # own included, which the listing leaves out.
    others = await session.exec(
        select(UserEmail).where(
            UserEmail.user_id == user_id,
            UserEmail.is_primary.is_(True),
            UserEmail.id != row.id,
        )
    )
    for other in others.all():
        other.is_primary = False
        session.add(other)
    await session.flush()
    row.is_primary = True
    session.add(row)
    return row


async def primary_candidate(
    session: AsyncSession, *, user_id: int, address_id: int
) -> UserEmail:
    """The address :func:`set_primary_for_user` would make primary, or
    ``AddressError``."""
    row = await _owned(session, user_id=user_id, address_id=address_id)
    if row.verified_at is None:
        raise AddressError(AddressMessages.ADDRESS_NOT_VERIFIED)
    return row


async def _owned(session: AsyncSession, *, user_id: int, address_id: int) -> UserEmail:
    row = await session.get(UserEmail, address_id)
    if row is None or row.user_id != user_id or row.source == SOURCE_SYNTHETIC:
        raise AddressError(AddressMessages.ADDRESS_NOT_FOUND, 404)
    return row


async def _lock_addresses(session: AsyncSession, user_id: int) -> None:
    """Hold this account's address rows for the rest of the transaction, so
    two requests changing the set take turns rather than both acting on the
    same reading."""
    await session.exec(
        select(UserEmail.id)
        .where(UserEmail.user_id == user_id)
        .order_by(UserEmail.id)
        .with_for_update()
    )


async def _pending_for_user(
    session: AsyncSession, *, user_id: int, digest: str
) -> UserEmail | None:
    """This account's own unproven claim on an address, if it has one."""
    return (
        await session.exec(
            select(UserEmail).where(
                UserEmail.user_id == user_id,
                UserEmail.email_hash == digest,
                UserEmail.verified_at.is_(None),
            )
        )
    ).one_or_none()


async def _proven_holder(session: AsyncSession, digest: str) -> UserEmail | None:
    """The row that has proven this address, if anybody has."""
    return (
        await session.exec(
            select(UserEmail).where(
                UserEmail.email_hash == digest,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).one_or_none()


async def _address_count(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            select(func.count())
            .select_from(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.source != SOURCE_SYNTHETIC,
            )
        )
    ).one()


async def _verified_count(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            select(func.count())
            .select_from(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).one()


async def prove_at_sign_in(
    session: AsyncSession,
    *,
    user: User,
    address_id: int,
    now: datetime | None = None,
) -> bool:
    """Record that a sign-in proved this address, and say whether that is new.

    Reached where arriving at an address proves it: an emailed code, or an
    identity provider vouching for it. The first proof of an address nobody
    had proved drops every credential the account held before it — the
    password, its passkeys, its second factor and its sessions — and the
    account's open connections are rechecked once the transaction commits.
    The account keeps its handle, its memberships and its content; whoever
    proved the address signs in, and sets up what they want afterwards.

    ``False`` where it was already proved, and nothing else changes. Staged in
    the caller's transaction, so the session the sign-in opens lands beside the
    retirement and the account never sits with nothing.
    """
    from app.core.audit_events import AuditEventType
    from app.db import post_commit
    from app.models.platform.user_passkey import UserPasskey
    from app.services import audit as audit_service
    from app.services import content_sockets
    from app.services.auth import totp as totp_service
    from app.services.platform import user_tokens

    result = await session.exec(
        update(UserEmail)
        .where(UserEmail.id == address_id, UserEmail.verified_at.is_(None))
        .values(verified_at=now or datetime.now(UTC))
    )
    if not result.rowcount:
        return False

    user.hashed_password = None
    user.password_set_at = None
    session.add(user)
    await session.exec(delete(UserPasskey).where(UserPasskey.user_id == user.id))
    await totp_service.disable(session, user_id=user.id)
    await user_tokens.revoke_user_sessions(session, user=user)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_CREDENTIALS_RETIRED,
        actor_user_id=user.id,
        target_user_id=user.id,
        target_type="user",
        target_id=user.id,
        detail={"reason": "address_first_proved"},
    )
    user_id = user.id
    post_commit.after_commit(
        session,
        lambda: content_sockets.sockets.revoke_user_everywhere(user_id),
        key=("content_sockets", "recheck_user", user_id),
    )
    return True
