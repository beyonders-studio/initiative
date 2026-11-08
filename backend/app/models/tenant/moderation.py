"""Reports a community's moderators settle.

A moderation report is **not a task**. A task carries a checklist, a priority,
dates, recurrence, a drag position, several assignees with per-assignee
completion, custom properties, tags and a sharing model — a moderator needs
none of it. They look at what was reported and decide. So this is its own small
thing: one row per reported target, holding what it is, why, and what was done.

Platform-handled reports are different work and keep their own shape — they are
intake cases (tasks) in the operations guild, triaged and assigned by staff.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_MODERATION_SNAPSHOT
from app.core.moderation import ModerationAct, ReportOutcome, ReportReason
from app.models.tenant._mixins import CreatedByMixin

#: Longest a target-type value can be. A ``SearchEntityType`` or a
#: ``PlatformReportTarget``, stored as its string.
TARGET_TYPE_LENGTH = 32


class ModerationReport(SQLModel, table=True):
    """One reported target in one initiative, open until it is settled."""

    __tablename__ = "moderation_reports"

    id: int | None = Field(default=None, primary_key=True)

    # No index of its own: the migration's (initiative_id, outcome,
    # reported_at DESC) index leads on this column and answers both the
    # moderator's list and the open-report lookup.
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    # What was reported. A weak reference, never content: reaching the thing is
    # the moderator following the link, under the access they already hold.
    target_type: str = Field(
        sa_column=Column(String(length=TARGET_TYPE_LENGTH), nullable=False)
    )
    target_id: int = Field(sa_column=Column(Integer, nullable=False))

    #: Why the first reporter said they were reporting it.
    reason: ReportReason = Field(sa_column=Column(String(length=32), nullable=False))
    #: When the first report arrived. Later ones move nothing here.
    reported_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    # NULL while open. Every outcome closes the report: it is either work or a
    # record, never both.
    outcome: ReportOutcome | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    #: Who settled it, and when. Set by the act, not typed in.
    decided_by: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    decided_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: The law the first ``illegal`` report named. Null for every other reason.
    legal_basis: str | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    #: The platform's case about the same target, when the platform was told
    #: as well: an ``illegal`` report goes to both at once. A weak reference;
    #: the case is in the operations community.
    platform_case_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    platform_notified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: What settling it did to the target, in the moderation log.
    action_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )


class ModerationReportReporter(SQLModel, table=True):
    """One person's report of a target, joined to the open row for it.

    A row per reporter rather than a count on the report: the count has to mean
    *distinct people*, and only the identities make it mean that. They are held
    for that and for an escalation to carry. The community's own moderators are
    served the count; the names stay here.
    """

    __tablename__ = "moderation_report_reporters"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "reporter_id", name="uq_moderation_report_reporter"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # No index of its own: the unique constraint above leads on this column,
    # which is what reading a report's reporters looks up.
    report_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("moderation_reports.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: Weak ref, no FK — an erased account leaves a dangling id rather than a
    #: preserved person, like every other reference on this plane.
    reporter_id: int = Field(sa_column=Column(Integer, nullable=False))
    reported_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: This reporter's own words.
    detail: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


def _values(enum: type[Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


class ModerationAction(CreatedByMixin, table=True):
    """One thing a community's moderators did, in its moderation log.

    Append-only: a removal is undone by a ``restore`` row naming the same
    target, never by changing this one. It is the only place the words a
    moderator took down are kept (``snapshot``, sealed), so the log is what a
    removal is put back from. ``created_by`` is the moderator, or empty for
    the platform acting on a hold it released.
    """

    __tablename__ = "moderation_actions"
    __table_args__ = (
        CheckConstraint(
            f"action IN ({_values(ModerationAct)})",
            name="ck_moderation_actions_action",
        ),
        # The log, an initiative's newest first.
        Index("ix_moderation_actions_log", "initiative_id", "created_at"),
        # What was done to one thing, for a restore and a lock.
        Index("ix_moderation_actions_target", "target_type", "target_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    action: str = Field(sa_column=Column(String(length=32), nullable=False))
    #: What it was done to: a ``SearchEntityType`` and its id. A weak
    #: reference, so the row outlives what it names.
    target_type: str = Field(
        sa_column=Column(String(length=TARGET_TYPE_LENGTH), nullable=False)
    )
    target_id: int = Field(sa_column=Column(Integer, nullable=False))
    #: Whose work it was, where it was somebody's.
    subject_user_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: A ``RemovalReason``, for a removal.
    reason: str | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    #: The moderator's own words: why, for the log; for a warning, what the
    #: member was told.
    note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    #: The words a comment's removal took down, sealed.
    snapshot: str | None = Field(
        default=None,
        sa_column=Column(
            Text, nullable=True, info={FERNET_SALT: SALT_MODERATION_SNAPSHOT}
        ),
    )
    #: The report it settled, when it settled one.
    report_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("moderation_reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    #: The hold it ended, when the platform removed something it had held.
    hold_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    #: The access grant it was done under, when a platform moderator did it.
    via_grant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
