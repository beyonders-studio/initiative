"""PAM access grants, for the platform-role testing paths.

Every grant targets a community the grantee is NOT a member of — PAM is the
only way a platform user reaches a foreign community. Covers the lifecycle:
pending, live, self-approved break-glass, denied, and expired.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.access_grant import (
    AccessGrant,
    AccessGrantStatus,
    AccessLevel,
)
from app.models.platform.user import User

from seed.common import NOW

#: ``requested_delta``/``decided_delta``/``expires_delta`` are relative to now;
#: leaving one out leaves the column empty. ``requested_by`` defaults to the
#: grantee.
ACCESS_GRANTS: list[dict] = [
    {
        "user": "Platform Support",
        "community": "starforge",
        "access_level": AccessLevel.read,
        "status": AccessGrantStatus.pending,
        "reason": "Investigating a reported sync issue in Starforge Collective (ticket #4821).",
        "requested_duration_minutes": 120,
        "requested_delta": -timedelta(hours=2),
    },
    {
        "user": "Platform Moderator",
        "community": "tides",
        "access_level": AccessLevel.read,
        "status": AccessGrantStatus.approved,
        "reason": "Reviewing a content report against a project in Realm of Tides.",
        "requested_duration_minutes": 480,
        "approved_by": "Admin User",
        "requested_delta": -timedelta(hours=2),
        "decided_delta": -timedelta(hours=1),
        "expires_delta": timedelta(hours=7),
    },
    {
        "user": "Platform Operator",
        "community": "starforge",
        "access_level": AccessLevel.read_write,
        "status": AccessGrantStatus.approved,
        "reason": "Break-glass: restoring a corrupted project after a failed import.",
        "requested_duration_minutes": 90,
        "approved_by": "Platform Operator",
        "requested_delta": -timedelta(minutes=30),
        "decided_delta": -timedelta(minutes=30),
        "expires_delta": timedelta(hours=1),
    },
    {
        "user": "Platform Support",
        "community": "tides",
        "access_level": AccessLevel.read_write,
        "status": AccessGrantStatus.denied,
        "reason": "Wanted to fix a typo in a user's document directly.",
        "requested_duration_minutes": 60,
        "approved_by": "Platform Owner",
        "requested_delta": -timedelta(days=2),
        "decided_delta": -timedelta(days=2) + timedelta(hours=1),
    },
    {
        "user": "Platform Moderator",
        "community": "primary",
        "access_level": AccessLevel.read,
        "status": AccessGrantStatus.expired,
        "reason": "Audited invite spam originating from the primary guild.",
        "requested_duration_minutes": 240,
        "approved_by": "Admin User",
        "requested_delta": -timedelta(days=3),
        "decided_delta": -timedelta(days=3) + timedelta(minutes=10),
        "expires_delta": -timedelta(days=3) + timedelta(hours=4),
    },
]


async def seed(
    session: AsyncSession,
    ids: dict[str, list],
    users: dict[str, User],
    guild_ids: dict[str, int],
) -> None:
    await set_rls_context(session, Unattributed())  # a platform-scoped shared table
    for d in ACCESS_GRANTS:
        grantee = users[d["user"]]
        grant = AccessGrant(
            user_id=grantee.id,
            guild_id=guild_ids[d["community"]],
            access_level=d["access_level"].value,
            status=d["status"].value,
            reason=d["reason"],
            requested_duration_minutes=d["requested_duration_minutes"],
            requested_by_id=users.get(d.get("requested_by"), grantee).id,
            approved_by_id=users[d["approved_by"]].id if "approved_by" in d else None,
            requested_at=NOW + d.get("requested_delta", timedelta(0)),
            decided_at=NOW + d["decided_delta"] if "decided_delta" in d else None,
            expires_at=NOW + d["expires_delta"] if "expires_delta" in d else None,
        )
        session.add(grant)
        await session.flush()
        ids["access_grants"].append(grant.id)
