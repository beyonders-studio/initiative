"""An installed plug-in asking a member to act as them, and the member's answer.

A plug-in asks for one **purpose** at a time (``purpose`` absent covers the
whole plug-in). The member answers on their own consent screen: grant ``read``, grant
``read_write`` (never more than the plug-in asked for), decline, or later revoke.
The community's administration can revoke every answer for one install at once
without uninstalling it.

The rows live in the community's schema. The functions here run on whatever
session their caller routed: the member's own request (own-row policies admit
their rows), the seat's (the admin leg admits every row), or the system engine
routed into the community (the request a plug-in makes, which names no person).

The install standing reads the row on every member-token request, so an answer
changes the next request without anything else being told.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete as sa_delete
from sqlalchemy import distinct, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.db.session import routed_guild_id
from app.models.tenant.plugin_member_consent import (
    ConsentAccess,
    ConsentStatus,
    PluginMemberConsent,
)
from app.services import audit as audit_service

__all__ = [
    "ConsentRequest",
    "ConsentTallies",
    "consent_tallies",
    "delete_install_consents",
    "delete_member_consents",
    "find_consent",
    "get_member_consent",
    "grant",
    "list_install_consents",
    "list_member_consents",
    "live_consent",
    "request_consent",
    "revoke",
    "revoke_all",
    "revoke_member_consents",
]


def _purpose_is(purpose: str | None):
    """``purpose IS NOT DISTINCT FROM :purpose``, which is what the unique key
    holds the column to."""
    return PluginMemberConsent.purpose.is_not_distinct_from(purpose)  # type: ignore[union-attr]


# --- a plug-in asking ------------------------------------------------------------


@dataclass(frozen=True)
class ConsentRequest:
    """What a plug-in asked for."""

    install_id: int
    user_id: int
    purpose: str | None
    label: str
    initiative_id: int | None
    access: ConsentAccess


async def find_consent(
    session: AsyncSession, *, install_id: int, user_id: int, purpose: str | None
) -> PluginMemberConsent | None:
    """The row for one (install, member, purpose), in whatever state it is."""
    return (
        await session.exec(
            select(PluginMemberConsent).where(
                PluginMemberConsent.install_id == install_id,
                PluginMemberConsent.user_id == user_id,
                _purpose_is(purpose),
            )
        )
    ).first()


async def request_consent(
    session: AsyncSession, request: ConsentRequest
) -> tuple[PluginMemberConsent, bool]:
    """Record a plug-in's request, or find the one it already made.

    Returns the row and whether this call created it. A repeated request for
    the same member and purpose returns the row as it stands, whatever the
    member answered: the member changes their answer on their own screen, and
    the plug-in asking again changes nothing and tells nobody.
    """
    inserted = (
        await session.exec(
            pg_insert(PluginMemberConsent)
            .values(
                install_id=request.install_id,
                user_id=request.user_id,
                purpose=request.purpose,
                label=request.label,
                initiative_id=request.initiative_id,
                requested_access=request.access.value,
                requested_at=utcnow(),
                updated_at=utcnow(),
            )
            .on_conflict_do_nothing(constraint="plugin_member_consents_unique_purpose")
            .returning(PluginMemberConsent.id)
        )
    ).first()
    row = await find_consent(
        session,
        install_id=request.install_id,
        user_id=request.user_id,
        purpose=request.purpose,
    )
    if row is None:
        raise RuntimeError("a consent request was neither written nor found")
    return row, inserted is not None


# --- the member's own ---------------------------------------------------------


async def list_member_consents(
    session: AsyncSession, *, install_id: int, user_id: int
) -> list[PluginMemberConsent]:
    """One member's rows for one install, whole-plug-in first, then by purpose.

    Filtered on the member explicitly: an administrator's session is admitted
    to every member's rows, and this is the member's own list.
    """
    rows = (
        await session.exec(
            select(PluginMemberConsent).where(
                PluginMemberConsent.install_id == install_id,
                PluginMemberConsent.user_id == user_id,
            )
        )
    ).all()
    return sorted(
        rows,
        key=lambda row: (row.purpose is not None, row.purpose or "", row.id or 0),
    )


async def list_install_consents(
    session: AsyncSession,
    *,
    install_id: int,
    user_ids: Sequence[int] | None = None,
) -> list[PluginMemberConsent]:
    """Every member's rows for one install, for the seat's members view:
    grouped by member, whole-plug-in first within each, then by purpose.
    ``user_ids`` narrows it to those members, one page of that view."""
    stmt = select(PluginMemberConsent).where(
        PluginMemberConsent.install_id == install_id
    )
    if user_ids is not None:
        stmt = stmt.where(PluginMemberConsent.user_id.in_(user_ids))
    rows = (await session.exec(stmt)).all()
    return sorted(
        rows,
        key=lambda row: (
            row.user_id,
            row.purpose is not None,
            row.purpose or "",
            row.id or 0,
        ),
    )


@dataclass(frozen=True)
class ConsentTallies:
    """Across one install: how many members answered, how many allowed at
    least one request, and how many answers still stand or wait."""

    members: int
    allowed: int
    open: int


async def consent_tallies(session: AsyncSession, *, install_id: int) -> ConsentTallies:
    """:class:`ConsentTallies` for one install, in one query."""
    standing = PluginMemberConsent.revoked_at.is_(None)
    members, allowed, open_count = (
        await session.exec(
            select(
                func.count(distinct(PluginMemberConsent.user_id)),
                func.count(distinct(PluginMemberConsent.user_id)).filter(
                    standing, PluginMemberConsent.granted_access.is_not(None)
                ),
                func.count().filter(standing),
            ).where(PluginMemberConsent.install_id == install_id)
        )
    ).one()
    return ConsentTallies(members=members, allowed=allowed, open=open_count)


async def get_member_consent(
    session: AsyncSession, *, consent_id: int, install_id: int, user_id: int
) -> PluginMemberConsent | None:
    """One of the member's own rows for one install, or ``None``."""
    return (
        await session.exec(
            select(PluginMemberConsent).where(
                PluginMemberConsent.id == consent_id,
                PluginMemberConsent.install_id == install_id,
                PluginMemberConsent.user_id == user_id,
            )
        )
    ).first()


async def grant(
    session: AsyncSession,
    row: PluginMemberConsent,
    *,
    access: ConsentAccess,
    confirmed_factor: str | None,
    actor_user_id: int,
) -> PluginMemberConsent:
    """The member allows the request at ``access``.

    Raises ``ValueError`` when ``access`` is more than the plug-in asked for. An
    answer given before (a grant at another level, a decline, a revocation) is
    replaced, and ``granted_at`` restarts, so it reads as the age of what is in
    force now.
    """
    if not ConsentAccess(row.requested_access).covers(access):
        raise ValueError("more than the plug-in asked for")
    now = utcnow()
    row.granted_access = access.value
    row.granted_at = now
    row.revoked_at = None
    row.revoked_by_id = None
    row.confirmed_factor = confirmed_factor
    row.updated_at = now
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_CONSENT_GRANTED,
        actor_user_id=actor_user_id,
        target_user_id=row.user_id,
        guild_id=routed_guild_id(session),
        target_type="plugin",
        target_id=row.install_id,
        detail={
            "consent_id": row.id,
            "purpose": row.purpose,
            "access": access.value,
            "via": "self",
        },
    )
    return row


def _mark_revoked(row: PluginMemberConsent, *, revoked_by_id: int) -> None:
    now = utcnow()
    row.revoked_at = now
    row.revoked_by_id = revoked_by_id
    row.updated_at = now


async def revoke(
    session: AsyncSession,
    row: PluginMemberConsent,
    *,
    revoked_by_id: int,
    actor_user_id: int,
    via: str = "self",
) -> bool:
    """Decline a pending request, or withdraw a granted one.

    Returns whether anything changed: an answer already ended is left as it
    is, and records nothing. ``via`` is ``self`` for the member, ``admin`` for
    the seat ending it for them.
    """
    if row.revoked_at is not None:
        return False
    status = row.status
    _mark_revoked(row, revoked_by_id=revoked_by_id)
    session.add(row)
    if status is ConsentStatus.granted:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_CONSENT_REVOKED,
            actor_user_id=actor_user_id,
            target_user_id=row.user_id,
            guild_id=routed_guild_id(session),
            target_type="plugin",
            target_id=row.install_id,
            detail={"consent_id": row.id, "purpose": row.purpose, "via": via},
        )
    return True


async def revoke_member_consents(
    session: AsyncSession,
    *,
    install_id: int,
    user_id: int,
    revoked_by_id: int,
    actor_user_id: int,
) -> int:
    """The seat ending every answer one member gave one install."""
    rows = (
        await session.exec(
            select(PluginMemberConsent).where(
                PluginMemberConsent.install_id == install_id,
                PluginMemberConsent.user_id == user_id,
                PluginMemberConsent.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    changed = 0
    for row in rows:
        if await revoke(
            session,
            row,
            revoked_by_id=revoked_by_id,
            actor_user_id=actor_user_id,
            via="admin",
        ):
            changed += 1
    return changed


async def revoke_all(
    session: AsyncSession,
    *,
    install_id: int,
    revoked_by_id: int,
    actor_user_id: int,
) -> int:
    """End every member's answer for one install, pending requests included.

    The seat's switch for stopping a plug-in acting as anybody without
    uninstalling it. Members may grant again afterwards.
    """
    rows = (
        await session.exec(
            select(PluginMemberConsent).where(
                PluginMemberConsent.install_id == install_id,
                PluginMemberConsent.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    changed = 0
    for row in rows:
        if await revoke(
            session,
            row,
            revoked_by_id=revoked_by_id,
            actor_user_id=actor_user_id,
            via="admin",
        ):
            changed += 1
    return changed


async def delete_install_consents(session: AsyncSession, *, install_id: int) -> int:
    """Every member's rows for one install, for its uninstall. Returns how many
    went, which the uninstall records."""
    result = await session.exec(
        sa_delete(PluginMemberConsent).where(
            PluginMemberConsent.install_id == install_id
        )  # type: ignore[arg-type]
    )
    return result.rowcount or 0


async def delete_member_consents(session: AsyncSession, *, user_id: int) -> int:
    """Every answer one member gave in the routed community, for the paths
    where their relationship with it ends. The session must be routed into
    the community."""
    result = await session.exec(
        sa_delete(PluginMemberConsent).where(PluginMemberConsent.user_id == user_id)  # type: ignore[arg-type]
    )
    return result.rowcount or 0


# --- the token endpoint -------------------------------------------------------


async def live_consent(
    session: AsyncSession, *, install_id: int, user_id: int, purpose: str | None
) -> PluginMemberConsent | None:
    """The member's consent for this install and purpose, when it is granted
    and not revoked; ``None`` otherwise."""
    row = await find_consent(
        session, install_id=install_id, user_id=user_id, purpose=purpose
    )
    if row is None or row.status is not ConsentStatus.granted:
        return None
    return row
