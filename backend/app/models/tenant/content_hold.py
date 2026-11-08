"""Holds: content kept in place for the platform.

A guild-schema table, one row per hold. The held rows themselves carry
``held_at``/``hold_id`` (``HoldMixin``); this row says why, by whom, under which
case, and how it ended. It is the platform's record, not the community's: its
policy admits the system engine and a ``moderate`` grantee only, and no
community admin — the moderator who placed a hold can't read it back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Text
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_HOLD_NOTE
from app.core.moderation import HoldReason, HoldRelease, HoldVia, LegalBasis

#: Longest a target-type value can be: a ``SearchEntityType``.
TARGET_TYPE_LENGTH = 32


def _values(enum: type[Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


class ContentHold(SQLModel, table=True):
    """One hold on one piece of content and everything held with it."""

    __tablename__ = "content_holds"
    __table_args__ = (
        CheckConstraint(
            f"reason IN ({_values(HoldReason)})", name="ck_content_holds_reason"
        ),
        CheckConstraint(
            f"placed_via IN ({_values(HoldVia)})", name="ck_content_holds_via"
        ),
        CheckConstraint(
            f"legal_basis IS NULL OR legal_basis IN ({_values(LegalBasis)})",
            name="ck_content_holds_legal_basis",
        ),
        CheckConstraint(
            "reason <> 'illegal_content' OR legal_basis IS NOT NULL",
            name="ck_content_holds_basis_named",
        ),
        CheckConstraint(
            f"release_outcome IS NULL OR release_outcome IN ({_values(HoldRelease)})",
            name="ck_content_holds_outcome",
        ),
        CheckConstraint(
            "(released_at IS NULL) = (release_outcome IS NULL)",
            name="ck_content_holds_released",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    #: The ``SearchEntityType`` held, and its id.
    target_type: str = Field(
        sa_column=Column(String(length=TARGET_TYPE_LENGTH), nullable=False)
    )
    target_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    #: The operations case working it. A weak reference: the case is in
    #: another community.
    case_task_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: Who placed it. A weak reference, like every person on this row.
    placed_by: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    placed_via: str = Field(sa_column=Column(String(length=16), nullable=False))
    reason: str = Field(sa_column=Column(String(length=32), nullable=False))
    legal_basis: str | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    #: Free text — who asked, a reference number — sealed, and read only by
    #: the platform.
    note: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True, info={FERNET_SALT: SALT_HOLD_NOTE}),
    )
    placed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: When the case was last reminded the hold is still in place.
    reminded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    released_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    released_by: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    release_outcome: str | None = Field(
        default=None, sa_column=Column(String(length=16), nullable=True)
    )
