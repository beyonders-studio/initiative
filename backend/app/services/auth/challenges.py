"""A sign-in held between the thing it has proved and the thing it has not.

A password can be correct and the sign-in still unfinished, because the account
holds a second factor. Something has to carry that across two requests.

It is carried as a row: ``consumed_at`` spends it, ``attempts`` counts refused
answers against it, ``expires_at`` ends it, and :func:`revoke_for_user` drops
it when what it rests on moves. It has its own table because every row in
``auth_sessions`` means somebody is signed in, and this is the state of
somebody who is not.

The value handed to the client is random and stored only as a SHA-256 digest,
following ``auth_sessions.refresh_token_hash``: full entropy already, so the
digest is a single indexed lookup rather than a scan.

Everything here runs on the system engine — a challenge is resolved before
there is an authenticated request to scope.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.clock import utcnow
from app.core.encryption import SALT_EMAIL, decrypt_field, encrypt_field
from app.models.platform.auth_challenge import AuthChallenge

#: Bytes of randomness behind the value handed to the client.
_CHALLENGE_BYTES = 32

#: How long a challenge stands. Long enough to open an authenticator app and
#: read a code from it, and no longer.
CHALLENGE_TTL = timedelta(minutes=5)

#: Wrong codes one challenge will take before it is finished. A sixth attempt
#: does not extend it: the challenge goes and the password is presented again.
MAX_ATTEMPTS = 5


class ChallengePurpose(str, Enum):
    """What a challenge is waiting for. Carried on the row so one table serves
    more than one unfinished thing."""

    #: A password was accepted and the account's second factor is outstanding.
    sign_in = "sign_in"
    #: The same, from the native sign-in. Kept apart because the two hand back
    #: different things: a browser reads its refresh token from a cookie, and
    #: the app is given it to keep.
    sign_in_native = "sign_in_native"
    #: A code sent to one of the account's addresses was accepted and the
    #: account's second factor is outstanding. Kept apart from :attr:`sign_in`
    #: because the session it opens records what the first leg proved.
    sign_in_after_code = "sign_in_after_code"
    #: The same, from the native sign-in.
    sign_in_after_code_native = "sign_in_after_code_native"
    #: A passkey registration is under way. The value is the WebAuthn challenge
    #: itself, so the finish route reads it back out of the signed client data.
    passkey_register = "passkey_register"
    #: A passkey sign-in is under way. Like the one above, the value is the
    #: WebAuthn challenge; unlike it, the row names no account — the assertion
    #: that answers is what says whose credential it is.
    passkey_sign_in = "passkey_sign_in"
    #: A passkey is being presented against a session already open, to add it
    #: to what that session has proved. Like a registration the row names the
    #: account, because there already is one.
    passkey_step_up = "passkey_step_up"
    #: A passkey is being presented to break glass. Its own purpose rather than
    #: the step-up's: what it answers for is the request that spends it, not
    #: the session, so one may not be taken for the other.
    break_glass = "break_glass"
    #: A code has been sent to an address, and the page that asked for it is
    #: waiting for the code to be typed back. The row names the account when
    #: the address reaches one; where it reaches nobody the row still stands,
    #: so that asking about an address says nothing about whether it is held.
    email_otp = "email_otp"
    #: The same, from the native sign-in. Kept apart for the reason
    #: :attr:`sign_in_native` is: a browser reads its refresh token from a
    #: cookie, and the app is given one to keep.
    email_otp_native = "email_otp_native"
    #: A code sent to an address no account holds has been answered, and the
    #: handle screen is being filled in. The row carries the address the code
    #: proved; nothing else about the account exists yet.
    email_otp_register = "email_otp_register"
    #: The same, from the native sign-up.
    email_otp_register_native = "email_otp_register_native"
    #: A code has been sent to one of an account's proved addresses to confirm
    #: the session already open, the way a passkey step-up does. Its own
    #: purpose, so a code asked for at the sign-in page answers nothing here
    #: and one asked for here opens no session of its own.
    email_otp_step_up = "email_otp_step_up"
    #: A sign-in finished in the phone's browser, waiting for the app that
    #: began it. The value is the sealed code the browser hands back; the
    #: answer is the app's S256 challenge, so only the verifier behind it
    #: redeems the code.
    native_handoff = "native_handoff"
    #: A passkey is being registered for an account that does not exist yet.
    #: The row names nobody — there is nobody to name — and what it stands for
    #: is that the gates a registration has to pass were passed before the
    #: browser was sent to an authenticator.
    passkey_sign_up = "passkey_sign_up"
    #: An operator has been sent to a plug-in's vendor to create its client, and
    #: the vendor will send them back with a code. The row names the operator;
    #: the answer is the registration the setup is for.
    plugin_vendor_setup = "plugin_vendor_setup"


@dataclass(frozen=True)
class IssuedChallenge:
    """A stored challenge and the value that names it.

    ``value`` is the only time the raw value exists — hand it to the client and
    drop it; only its digest is kept.
    """

    challenge: AuthChallenge
    value: str


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


async def create(
    session: AsyncSession,
    *,
    user_id: int | None,
    purpose: ChallengePurpose,
    value: str | None = None,
    answer: str | None = None,
    ttl: timedelta | None = None,
    user_email_id: int | None = None,
    email: str | None = None,
) -> IssuedChallenge:
    """Open a challenge, for one account or for none. The caller commits.

    ``value`` lets a caller that already holds the value name it — a WebAuthn
    ceremony mints its own challenge and the browser signs it, so the row
    stands for that value rather than for a second one. Given no value, one is
    minted here. Either way only the digest is kept.

    ``answer`` is for a challenge whose value is not its own proof: the value
    names the row and the answer is what has to arrive with it. Digested
    together with the value, so the stored form of one code is particular to
    the challenge that issued it. :func:`answered_by` is what checks it.

    ``ttl`` overrides :data:`CHALLENGE_TTL` for a challenge whose answer has
    further to travel than an authenticator on the desk.

    ``email`` is for a challenge about an address no account holds yet; it is
    kept encrypted, and :func:`address_of` reads it back.

    ``user_id`` is ``None`` for a ceremony that starts before anybody is named:
    a passkey sign-in offers what the authenticator holds for this domain, and
    the account arrives with the assertion.
    """
    value = value or secrets.token_urlsafe(_CHALLENGE_BYTES)
    challenge = AuthChallenge(
        challenge_hash=_hash(value),
        answer_hash=_hash(f"{value}:{answer}") if answer is not None else None,
        user_id=user_id,
        user_email_id=user_email_id,
        email_encrypted=encrypt_field(email, SALT_EMAIL) if email else None,
        purpose=purpose.value,
        expires_at=utcnow() + (ttl or CHALLENGE_TTL),
    )
    session.add(challenge)
    await session.flush()
    return IssuedChallenge(challenge=challenge, value=value)


async def claim_attempt(
    session: AsyncSession,
    *,
    value: str,
    purposes: Sequence[ChallengePurpose],
) -> AuthChallenge | None:
    """Take one of the challenge's attempts, and hand back the challenge.

    ``None`` when there is nothing to take one from: no such challenge, not for
    any of these purposes, already spent, expired, or out of attempts. Every one
    of those reads the same from here.

    The caller names the purposes it will answer for, and the row says which it
    was — one endpoint can serve two sign-ins that differ in what they hand
    back without the client being asked which it is.

    Taking the attempt *is* the lookup, and it is one statement, so two answers
    arriving together take two attempts rather than reading the same count and
    each writing it back. The count is why this is a write and not a read.
    """
    digest = _hash(value)
    result = await session.exec(
        update(AuthChallenge)
        .where(
            AuthChallenge.challenge_hash == digest,
            AuthChallenge.purpose.in_([p.value for p in purposes]),
            AuthChallenge.consumed_at.is_(None),
            AuthChallenge.expires_at > utcnow(),
            AuthChallenge.attempts < MAX_ATTEMPTS,
        )
        .values(attempts=AuthChallenge.attempts + 1)
    )
    if not result.rowcount:
        return None
    return (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.challenge_hash == digest)
        )
    ).first()


def address_of(challenge: AuthChallenge) -> str | None:
    """The address this challenge names, where it names one no account holds."""
    if not challenge.email_encrypted:
        return None
    return decrypt_field(challenge.email_encrypted, SALT_EMAIL)


def answered_by(challenge: AuthChallenge, *, value: str, answer: str) -> bool:
    """Whether ``answer`` is the one this challenge is waiting for.

    For a challenge that carries no separate answer this is ``False``: such a
    row is proved by its value alone, and asking it this question means the
    caller has confused two kinds of challenge.

    Compared in constant time, and against a digest that was taken over the
    value as well, so it only means anything alongside the right handle.
    """
    if challenge.answer_hash is None:
        return False
    return hmac.compare_digest(challenge.answer_hash, _hash(f"{value}:{answer}"))


async def consume(session: AsyncSession, challenge: AuthChallenge) -> bool:
    """Spend the challenge, once.

    Returns whether this call is the one that spent it: the update carries its
    own ``consumed_at IS NULL``, so of two requests answering the same challenge
    at the same moment, one goes on to make a session.
    """
    result = await session.exec(
        update(AuthChallenge)
        .where(
            AuthChallenge.id == challenge.id,
            AuthChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=utcnow())
    )
    return bool(result.rowcount)


async def spend_answered(
    session: AsyncSession,
    *,
    value: str,
    purpose: ChallengePurpose,
    user_id: int,
    answer: str,
) -> bool:
    """Spend a challenge only when it is this account's and ``answer`` is the
    one it waits for, in one statement. A challenge that does not match is
    left as it was; returns whether this call spent it."""
    result = await session.exec(
        update(AuthChallenge)
        .where(
            AuthChallenge.challenge_hash == _hash(value),
            AuthChallenge.purpose == purpose.value,
            AuthChallenge.user_id == user_id,
            AuthChallenge.answer_hash == _hash(f"{value}:{answer}"),
            AuthChallenge.consumed_at.is_(None),
            AuthChallenge.expires_at > utcnow(),
        )
        .values(consumed_at=utcnow())
    )
    return bool(result.rowcount)


async def revoke_for_user(session: AsyncSession, *, user_id: int) -> int:
    """Drop every challenge standing for one account, spent or not.

    Called where what a challenge rests on has moved — a changed password, a
    factor removed. Returns how many went. The caller commits.
    """
    result = await session.exec(
        delete(AuthChallenge).where(AuthChallenge.user_id == user_id)
    )
    return int(result.rowcount or 0)


async def purge_expired(session: AsyncSession) -> int:
    """Clear out challenges nothing can use again. The caller commits.

    Two kinds qualify: one whose time has run out, and one already spent. A
    challenge answers once, so a spent row has nothing left to say and is not
    kept until it also expires.
    """
    result = await session.exec(
        delete(AuthChallenge).where(
            or_(
                AuthChallenge.expires_at <= utcnow(),
                AuthChallenge.consumed_at.is_not(None),
            )
        )
    )
    return int(result.rowcount or 0)
