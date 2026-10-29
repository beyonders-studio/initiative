"""What an access token's ``sub`` names, and how it resolves back.

An access token names the account by a reference rather than by the row id —
the ``client`` sector of ``services.platform.identity_refs``. Audit rows,
joins and our own logs keep the integer, which is what they are for.

Resolution runs on the request-path session — the same single indexed query
that read ``users`` before. ``identity_refs`` is otherwise system-engine-only;
the grant and the policy that admit this lookup are scoped to this sector
alone (migration ``20260913_0267``).
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
)
from app.models.platform.user import User
from app.services.platform import rules
from app.services.platform.identity_refs import ensure_ref

__all__ = ["account_for_subject", "subject_for_user", "user_for_subject"]


async def subject_for_user(session: AsyncSession, *, user_id: int) -> str:
    """The reference this account's tokens name it by, minting on first use.

    Takes the caller's session — every mint site already holds a system-engine
    one for the session write — so the reference lands in the same transaction
    as the sign-in that needed it.
    """
    return await ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user_id,
        purpose=IdentityPurpose.client,
    )


async def account_for_subject(
    session: AsyncSession, *, subject: str
) -> tuple[User, str] | None:
    """Which account a token's ``sub`` names, with the deployment's
    second-factor rule beside it, or None.

    The rule rides along because every request that authenticates by session
    asks what the deployment requires of an account next, and reading it here
    is one statement rather than two.

    Live references only, and nothing re-issues one in this sector. A token
    holding a replaced reference resolves to nobody until it lapses: the
    caller turns that into 404, and the SPA renews on 401 alone. Wiring
    re-issue up means settling that first.
    """
    if not subject or len(subject) > REF_MAX_LENGTH:
        return None

    statement = (
        select(User, rules.platform_rule_sql("second_factor_requirement"))
        .join(IdentityRef, IdentityRef.entity_id == User.id)
        .where(
            IdentityRef.ref == subject,
            IdentityRef.entity_type == IdentityEntity.user,
            IdentityRef.purpose == IdentityPurpose.client,
            IdentityRef.retired_at.is_(None),
        )
    )
    row = (await session.exec(statement)).one_or_none()
    return None if row is None else (row[0], row[1])


async def user_for_subject(session: AsyncSession, *, subject: str) -> User | None:
    """Which account a token's ``sub`` names, or None. See
    :func:`account_for_subject`."""
    found = await account_for_subject(session, subject=subject)
    return None if found is None else found[0]
