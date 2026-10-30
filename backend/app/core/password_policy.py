"""Password policy enforcement for new and changed passwords.

Aligned with NIST SP 800-63B (rev. 3, 2017):

  - Minimum length 12. The schema layer enforces ``max_length=256``
    so an over-long payload is rejected before it ever reaches argon2
    or HIBP.
  - No character-class requirements (mandated complexity rules push
    users toward predictable patterns and reduce real entropy).
  - Reject passwords present in known breach corpora.

The login path is intentionally NOT routed through this module —
existing users with shorter or breached passwords keep working until
the next time they change one ("grandfathered"). All new password
material flows (register, password reset, self-update, operator-update)
must call ``validate_new_password`` immediately before hashing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.errors import CodedError
from app.core.messages import PasswordMessages
from app.services import hibp

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


# Mirrored by ``frontend/src/lib/passwordPolicy.ts`` — keep both in sync
# when you change the floor. The schemas hold no ``min_length`` of their
# own; short passwords reach the policy here and surface a flat
# ``PASSWORD_TOO_SHORT`` code rather than Pydantic's structured detail.
# The schema-level ``max_length=256`` does fire first for over-long
# input, by design — see ``hibp.is_password_breached`` and the
# argon2 cost of hashing huge payloads.
PASSWORD_MIN_LENGTH = 12


class PasswordPolicyError(CodedError):
    """Raised when a candidate password fails the policy, with one of the
    ``PasswordMessages`` constants as its code."""

    status_code = 422


async def validate_new_password(session: AsyncSession, password: str) -> None:
    """Validate a candidate password or raise ``PasswordPolicyError``.

    Order matters: cheap local check first, network check last, so
    obviously-short inputs never reach HIBP. The breach check runs while the
    deployment's rule ``breached_password_check_enabled`` is on.
    """
    from app.services.platform import rules

    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(PasswordMessages.TOO_SHORT)
    checks_breaches = (await rules.platform_values(session))[
        "breached_password_check_enabled"
    ]
    if checks_breaches and await hibp.is_password_breached(password):
        raise PasswordPolicyError(PasswordMessages.BREACHED)
