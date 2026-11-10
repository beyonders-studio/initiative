"""Bans and timeouts: what a community's administrators have done to one person.

One row per person per community, in ``public`` rather than the community's own
schema, because the two checks that read it run before the person is routed
in: joining (``guilds.ensure_membership``, which refuses a ban) and the
membership lookup (which routes a timed-out member into the read-only role).

The row says nothing about who made it or why, because the person it names
reads it: their standing does, to hold their content read-only. The audit
record carries who.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

from app.models.platform.guild import GUILD_ADMIN_ROLES


class ModerationKind(str, Enum):
    """What was done to the person."""

    #: Removed, and kept out until it is lifted.
    ban = "ban"
    #: Kept a member, but reading only, until ``ends_at``.
    timeout = "timeout"


class MemberModeration(SQLModel, table=True):
    __tablename__ = "member_moderation"
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{kind.value}'" for kind in ModerationKind) + ")",
            name="ck_member_moderation_kind",
        ),
        # A timeout always ends; a ban lasts until it is lifted.
        CheckConstraint(
            f"(kind = '{ModerationKind.timeout.value}') = (ends_at IS NOT NULL)",
            name="ck_member_moderation_ends",
        ),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        )
    )
    kind: ModerationKind = Field(sa_column=Column(String(16), nullable=False))
    ends_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


def live_timeout_sql(alias: str, role: str) -> str:
    """The row ``alias`` is a timeout holding its person, whose membership's
    rung is ``role``: still running, and they are not an administrator, so
    one promoted while timed out is held no longer. The standing statements
    ask this; ``member_moderation.live_timeout_end`` asks the same in the
    membership lookup."""
    admin_rungs = ", ".join(f"'{rung.value}'" for rung in sorted(GUILD_ADMIN_ROLES))
    return (
        f"({alias}.kind = '{ModerationKind.timeout.value}' AND {alias}.ends_at > now()"
        f" AND {role}::text NOT IN ({admin_rungs}))"
    )
