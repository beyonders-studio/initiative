"""An account's authenticator-app factor: enrolling it, and reading a code.

RFC 6238 arithmetic comes from ``pyotp``; what is here is the part that is
ours — where the seed is kept, when an enrolment becomes real, and which codes
count.

**Enrolling is two steps.** ``begin_enrolment`` mints a seed and writes it
unconfirmed; ``confirm_enrolment`` takes a code the authenticator produced and
sets ``confirmed_at``. Only a confirmed factor is asked for at sign-in, so an
enrolment that was started and abandoned asks nothing of anybody. A second
begin replaces an unconfirmed row.

**A code counts once.** ``user_totp.last_timestep`` records the interval an
accepted code came from, and a later code has to come from a later interval.

**Codes either side of now are accepted**, one interval each way, which is
RFC 6238's own allowance for clocks that disagree.

Everything here runs on the system engine: ``user_totp`` and its companion are
read while signing in, before there is an authenticated request to scope.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import pyotp
from sqlalchemy import delete, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.clock import utcnow
from app.core.encryption import SALT_TOTP_SECRET, decrypt_field, encrypt_field
from app.models.platform.mfa_recovery_code import MfaRecoveryCode
from app.models.platform.user_totp import UserTotp
from app.models.platform.user_totp_secret import UserTotpSecret

#: The shape every authenticator app assumes, and the one an ``otpauth://`` URI
#: does not need to spell out.
TOTP_DIGITS = 6
TOTP_PERIOD = 30

#: Intervals either side of the current one that a code may come from.
TOTP_DRIFT_STEPS = 1

#: How many recovery codes a set holds, and how much randomness each carries.
RECOVERY_CODE_COUNT = 10
_RECOVERY_CODE_BYTES = 16
#: When a set is running out. The settings page turns the count red at the
#: same number, so what the person is being warned about and what a route acts
#: on are the one figure.
LOW_ON_RECOVERY_CODES = 3
#: Characters a recovery code is written in — the digits and letters that
#: survive being read aloud or copied off a screen.
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_RECOVERY_GROUP = 5


@dataclass(frozen=True)
class Enrolment:
    """A started enrolment: the seed, and the URI an authenticator scans.

    Both carry the seed, and this is the only moment either exists outside the
    database — there is no path that reads it back afterwards.
    """

    secret: str
    uri: str


def _timestep(at: datetime) -> int:
    return int(at.timestamp()) // TOTP_PERIOD


def generate_secret() -> str:
    """A fresh base32 seed."""
    return pyotp.random_base32()


def issuer_name() -> str:
    """What an authenticator app files this account under.

    The deployment's own host, so two installs do not land on one entry in
    somebody's authenticator. There is no deployment name to use instead, and a
    host is what the person recognises.
    """
    from urllib.parse import urlsplit

    from app.core.config import settings

    host = urlsplit(settings.APP_URL.strip()).hostname
    return host or "Initiative"


def otpauth_uri(secret: str, *, account: str, issuer: str) -> str:
    """The ``otpauth://totp/`` URI an authenticator app reads.

    Rendered here rather than by ``pyotp.provisioning_uri`` so the label and
    issuer are quoted the one way, and so the caller gets a string it can put
    in a QR code without the server drawing one.
    """
    label = quote(f"{issuer}:{account}", safe="")
    query = "&".join(
        (
            f"secret={secret}",
            f"issuer={quote(issuer, safe='')}",
            f"digits={TOTP_DIGITS}",
            f"period={TOTP_PERIOD}",
            "algorithm=SHA1",
        )
    )
    return f"otpauth://totp/{label}?{query}"


def _matching_timestep(secret: str, code: str, *, at: datetime) -> int | None:
    """The interval a code belongs to, or ``None`` if it belongs to none of the
    ones on offer. Compared in constant time."""
    cleaned = code.strip().replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) != TOTP_DIGITS:
        return None
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_PERIOD)
    here = _timestep(at)
    for offset in range(-TOTP_DRIFT_STEPS, TOTP_DRIFT_STEPS + 1):
        step = here + offset
        if secrets.compare_digest(totp.at(step * TOTP_PERIOD), cleaned):
            return step
    return None


async def get_factor(session: AsyncSession, *, user_id: int) -> UserTotp | None:
    """The account's factor row, confirmed or not."""
    return (
        await session.exec(select(UserTotp).where(UserTotp.user_id == user_id))
    ).first()


async def is_enrolled(session: AsyncSession, *, user_id: int) -> bool:
    """Whether the account holds a factor it has proved."""
    factor = await get_factor(session, user_id=user_id)
    return factor is not None and factor.confirmed_at is not None


async def enrolled_among(session: AsyncSession, *, user_ids: list[int]) -> set[int]:
    """Which of these accounts hold a factor they have proved. One query for
    the whole page."""
    rows = await session.exec(
        select(UserTotp.user_id).where(
            UserTotp.user_id.in_(user_ids),
            UserTotp.confirmed_at.is_not(None),
        )
    )
    return set(rows.all())


async def _read_secret(session: AsyncSession, *, user_id: int) -> str | None:
    row = (
        await session.exec(
            select(UserTotpSecret).where(UserTotpSecret.user_id == user_id)
        )
    ).first()
    if row is None:
        return None
    return decrypt_field(row.secret_encrypted, SALT_TOTP_SECRET)


async def begin_enrolment(
    session: AsyncSession, *, user_id: int, account: str, issuer: str
) -> Enrolment:
    """Mint a seed and hold it unconfirmed. The caller commits.

    Replaces an enrolment that was started and never proved. A confirmed factor
    is not replaced — the caller checks for one first.
    """
    secret = generate_secret()
    factor = await get_factor(session, user_id=user_id)
    if factor is None:
        factor = UserTotp(user_id=user_id)
        session.add(factor)
        await session.flush()
    else:
        factor.confirmed_at = None
        factor.last_timestep = None
        factor.updated_at = utcnow()
        session.add(factor)

    stored = (
        await session.exec(
            select(UserTotpSecret).where(UserTotpSecret.user_id == user_id)
        )
    ).first()
    ciphertext = encrypt_field(secret, SALT_TOTP_SECRET)
    if stored is None:
        session.add(UserTotpSecret(user_id=user_id, secret_encrypted=ciphertext))
    else:
        stored.secret_encrypted = ciphertext
        stored.updated_at = utcnow()
        session.add(stored)
    await session.flush()
    return Enrolment(
        secret=secret, uri=otpauth_uri(secret, account=account, issuer=issuer)
    )


async def confirm_enrolment(session: AsyncSession, *, user_id: int, code: str) -> bool:
    """Turn a started enrolment into one that counts. The caller commits."""
    factor = await get_factor(session, user_id=user_id)
    if factor is None or factor.confirmed_at is not None:
        return False
    secret = await _read_secret(session, user_id=user_id)
    if secret is None:
        return False
    now = utcnow()
    step = _matching_timestep(secret, code, at=now)
    if step is None:
        return False
    result = await session.exec(
        update(UserTotp)
        .where(
            UserTotp.user_id == user_id,
            UserTotp.confirmed_at.is_(None),
        )
        .values(confirmed_at=now, last_timestep=step, last_used_at=now, updated_at=now)
    )
    if not result.rowcount:
        return False
    session.expire(factor)
    return True


async def verify_code(session: AsyncSession, *, user_id: int, code: str) -> bool:
    """Read a code against the account's confirmed factor. The caller commits.

    Records the interval it came from, which is what makes the next read of the
    same code answer ``False``.
    """
    factor = await get_factor(session, user_id=user_id)
    if factor is None or factor.confirmed_at is None:
        return False
    secret = await _read_secret(session, user_id=user_id)
    if secret is None:
        return False
    now = utcnow()
    step = _matching_timestep(secret, code, at=now)
    if step is None:
        return False
    # The interval has to still be ahead of the recorded one at the moment of
    # the write, so of two answers carrying the same code, one is accepted.
    result = await session.exec(
        update(UserTotp)
        .where(
            UserTotp.user_id == user_id,
            UserTotp.confirmed_at.is_not(None),
            or_(
                UserTotp.last_timestep.is_(None),
                UserTotp.last_timestep < step,
            ),
        )
        .values(last_timestep=step, last_used_at=now, updated_at=now)
    )
    if not result.rowcount:
        return False
    session.expire(factor)
    return True


async def disable(session: AsyncSession, *, user_id: int) -> bool:
    """Remove the factor, its seed and its recovery codes. The caller commits.

    Returns whether there was one. The seed goes with the factor by cascade;
    the codes are deleted here because they answer for the account rather than
    for this factor.
    """
    factor = await get_factor(session, user_id=user_id)
    await session.exec(
        delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id)
    )
    if factor is None:
        return False
    await session.delete(factor)
    await session.flush()
    return True


# --- Recovery codes --------------------------------------------------------


def _hash_recovery_code(normalised: str) -> bytes:
    """SHA-256 of an already-normalised code — deterministic, so a presented
    code is one indexed lookup. The value is ours and full-entropy, so a slow
    KDF would buy nothing and cost the lookup."""
    return hashlib.sha256(normalised.encode("utf-8")).digest()


def normalise_recovery_code(raw: str) -> str:
    """One written form, so the grouping dashes and casing a person copies do
    not decide whether their code works."""
    return "".join(ch for ch in raw.lower() if ch.isalnum())


def generate_recovery_code() -> str:
    """One code, in groups, from the alphabet that survives being read."""
    body = "".join(
        secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_CODE_BYTES)
    )
    return "-".join(
        body[i : i + _RECOVERY_GROUP] for i in range(0, len(body), _RECOVERY_GROUP)
    )


async def issue_recovery_codes(session: AsyncSession, *, user_id: int) -> list[str]:
    """Replace the account's set with a fresh one. The caller commits.

    The returned list is the only time the codes exist in the clear.
    """
    await session.exec(
        delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id)
    )
    codes = [generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        session.add(
            MfaRecoveryCode(
                user_id=user_id,
                code_hash=_hash_recovery_code(normalise_recovery_code(code)),
            )
        )
    await session.flush()
    return codes


async def consume_recovery_code(
    session: AsyncSession, *, user_id: int, code: str
) -> bool:
    """Spend one of the account's codes. The caller commits."""
    normalised = normalise_recovery_code(code)
    if not normalised:
        return False
    # Marked used by the same statement that finds it, so one code answers for
    # one sign-in.
    result = await session.exec(
        update(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user_id,
            MfaRecoveryCode.code_hash == _hash_recovery_code(normalised),
            MfaRecoveryCode.used_at.is_(None),
        )
        .values(used_at=utcnow())
    )
    return bool(result.rowcount)


async def remaining_recovery_codes(session: AsyncSession, *, user_id: int) -> int:
    """How many of the account's codes are still good."""
    return (
        await session.exec(
            select(func.count())
            .select_from(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.user_id == user_id,
                MfaRecoveryCode.used_at.is_(None),
            )
        )
    ).one()
