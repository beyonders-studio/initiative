"""A sign-in finished in the phone's browser, handed back to the app.

The app cannot hold an identity provider's redirect itself, so it opens the
phone's browser and the sign-in finishes there. What
comes back through ``initiative://oidc/callback`` is a one-time code, not a
credential: the app redeems it over HTTPS with the PKCE verifier it generated
when it began (RFC 8252 §7.1, RFC 7636), and the session opens then.

The code is the sign-in's outcome sealed under :data:`SALT_NATIVE_HANDOFF`, and
it is recorded as an ``auth_challenges`` row answered by the app's challenge, so
it is spent once, counts its attempts, expires in :data:`CODE_TTL` and goes
when the account's password or factors change.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import SALT_NATIVE_HANDOFF, decrypt_field, encrypt_field
from app.services.auth import challenges as challenge_service
from app.services.auth.oidc.flow_state import s256

CODE_TTL = timedelta(minutes=2)

#: What an S256 challenge is made of: unpadded base64url of a SHA-256 digest.
_CHALLENGE_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
_CHALLENGE_LENGTH = 43


#: RFC 7636 §4.1: a verifier is 43–128 unreserved characters.
_VERIFIER_CHARS = _CHALLENGE_CHARS | {".", "~"}


def is_challenge(value: str) -> bool:
    """Whether ``value`` has the shape of an S256 ``code_challenge``."""
    return len(value) == _CHALLENGE_LENGTH and set(value) <= _CHALLENGE_CHARS


def is_verifier(value: str) -> bool:
    """Whether ``value`` has the shape of a PKCE ``code_verifier``."""
    return 43 <= len(value) <= 128 and set(value) <= _VERIFIER_CHARS


@dataclass(frozen=True)
class Handoff:
    """What the sign-in proved, carried to the session the app opens."""

    user_id: int
    #: How the sign-in was made, for the record written when the session opens.
    method: str
    amr: list[str]
    device_name: str
    satisfied_providers: list[int] = field(default_factory=list)
    provider_auth: dict[str, Any] | None = None


async def issue(
    system_session: AsyncSession, *, handoff: Handoff, app_challenge: str
) -> str:
    """Seal the sign-in into a code bound to ``app_challenge``. The caller commits."""
    code = encrypt_field(json.dumps(asdict(handoff)), SALT_NATIVE_HANDOFF)
    await challenge_service.create(
        system_session,
        user_id=handoff.user_id,
        purpose=challenge_service.ChallengePurpose.native_handoff,
        value=code,
        answer=app_challenge,
        ttl=CODE_TTL,
    )
    return code


async def redeem(
    system_session: AsyncSession, *, code: str, code_verifier: str
) -> Handoff | None:
    """The sign-in a code carries, when ``code_verifier`` answers it.

    Any answer spends the code, right or wrong. ``None`` for anything that does
    not redeem; the caller commits either way.
    """
    challenge = await challenge_service.claim_attempt(
        system_session,
        value=code,
        purposes=[challenge_service.ChallengePurpose.native_handoff],
    )
    if challenge is None:
        return None
    answered = challenge_service.answered_by(
        challenge, value=code, answer=s256(code_verifier)
    )
    spent = await challenge_service.consume(system_session, challenge)
    if not (answered and spent):
        return None
    try:
        data = json.loads(decrypt_field(code, SALT_NATIVE_HANDOFF))
    except (InvalidToken, UnicodeDecodeError, ValueError):
        return None
    return Handoff(**data)
