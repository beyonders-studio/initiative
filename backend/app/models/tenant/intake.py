"""Where operations work lands, and which cases are already open.

Two guild-schema tables:

``intake_bindings``
    *This stream lands in that project.* One row per stream per guild, naming
    an initiative, a project, and optionally the status a new case starts in.
    Guild-schema because every id on it — initiative, project, status — is a
    per-schema id and belongs beside the rows it points at.

``intake_cases``
    The key -> task map the writer reads to answer "is this already a case?",
    and the window mark a repeating source is measured against. One row per
    case; ``last_seen_at`` is stamped by the writer, so an unrelated edit to
    the task does not move the window.

Both are initiative-scoped for RLS (see ``app.db.initiative_rls``): a binding
through its project, a case through the task it points at. Reading a case is
therefore exactly as hard as reading the task it describes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.core.intake import IntakeStream
from app.models.tenant._mixins import CreatedByMixin

#: Longest a stream value can be. The column is a CHECKed text rather than a
#: Postgres enum so that adding a stream is a release, not a type migration in
#: every guild schema.
STREAM_LENGTH = 32

#: Longest subject a filer may give a case: a line, as a task's title is.
FILER_SUBJECT_LENGTH = 200

#: Longest topic a case may carry: one of a stream's topic values.
TOPIC_LENGTH = 32

#: Longest dedupe key the writer will store. A key is built from a rule's name
#: plus the ids it keys on, never from anything a submitter typed.
DEDUPE_KEY_LENGTH = 200


class IntakeBinding(CreatedByMixin, table=True):
    """One stream, routed to one project in this guild."""

    __tablename__ = "intake_bindings"
    __table_args__ = (UniqueConstraint("stream", name="uq_intake_bindings_stream"),)

    id: int | None = Field(default=None, primary_key=True)

    stream: IntakeStream = Field(
        sa_column=Column(String(length=STREAM_LENGTH), nullable=False)
    )

    # The project is the whole address. Which initiative it belongs to is the
    # project's own column, read from there by everything that needs it, so
    # this table keeps no second copy of an answer that already has one place.
    project_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    # The status a new case starts in. NULL means the project's default, which
    # is what the task endpoints already fall back to — so a project whose
    # statuses are rearranged keeps working without anybody revisiting this row.
    default_status_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("task_statuses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # The type a new case is. NULL means the project's default, read against
    # the project when used, as the landing status is.
    task_type_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("task_types.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # The status that means "waiting on whoever filed it", and the one a case
    # goes back to when they answer. NULL where the project has no such
    # status: a filer is then never told the case is waiting on them, and
    # their answer moves nothing. Read, like the landing status, against the
    # project when used.
    awaiting_filer_status_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("task_statuses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    active_status_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("task_statuses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Whether the writer routes to this project right now. A disabled binding
    # keeps the project and the history; it just stops receiving.
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    created_by: int | None = Field(default=None, nullable=True)


class IntakeCase(SQLModel, table=True):
    """One case the writer opened, and how often its source has recurred.

    The case names its **task** and nothing else about where the work lives.
    Which project it is in is the task's own column, read through it by the one
    query that asks — so a task moved into another project takes its case with
    it, and there is never a second answer to disagree with the first.

    That also makes the mark mean what it should: "is this incident already
    being worked *here*?" is asked of the bound project, so repointing a stream
    starts fresh in the new project and rebinding to the same one finds the
    case that is still open.

    Every case gets a row, keyed or not, so "when did this stream last open a
    case" is answerable exactly rather than inferred from whatever tasks happen
    to be in the project.
    """

    __tablename__ = "intake_cases"

    id: int | None = Field(default=None, primary_key=True)

    stream: IntakeStream = Field(
        sa_column=Column(String(length=STREAM_LENGTH), nullable=False)
    )
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    #: NULL for a case nothing keys on — a report, a help request. A keyed case
    #: is one a repeating source can find again.
    dedupe_key: str | None = Field(
        default=None,
        sa_column=Column(String(length=DEDUPE_KEY_LENGTH), nullable=True),
    )

    opened_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: When the source was last seen at all. Every occurrence moves it.
    last_seen_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: When a recurrence was last recorded on the case. The window is measured
    #: from here, so a run in progress does not note itself once per event.
    noted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: How many times the source has been seen, the opening included.
    occurrences: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )

    #: What the case is about within its stream, as its filer chose: a support
    #: topic, a security topic, an appeal. NULL where nobody chose one. Read
    #: by whoever handles the case, and by its filer, for whom it can change
    #: how the case talks (``IntakeStreamMeta.conversation_for``).
    topic: str | None = Field(
        default=None,
        sa_column=Column(String(length=TOPIC_LENGTH), nullable=True),
    )

    #: The account that filed the case, when a person did. A weak ref like
    #: every other on this plane: an erased account leaves a dangling id. What
    #: connects somebody to the case they filed, so they can follow it.
    filer_user_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    #: What they called it, as they wrote it. Their own words and never
    #: changed: the task's title is the people handling it's to rename.
    filer_subject: str | None = Field(
        default=None,
        sa_column=Column(String(length=FILER_SUBJECT_LENGTH), nullable=True),
    )
    #: What the filer was last told about the case: the state they were shown,
    #: and the newest reply said to them. The ticket sweep compares these with
    #: the case as it is now and tells them only about what moved.
    filer_notified_state: str | None = Field(
        default=None, sa_column=Column(String(length=16), nullable=True)
    )
    filer_notified_comment_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )


class IdeaVote(SQLModel, table=True):
    """One account's vote for one idea, and the status they were last told it
    was in."""

    __tablename__ = "idea_votes"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_idea_votes_task_user"),
    )

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Who voted: a weak ref like ``filer_user_id``. They are not a member of
    #: the community that keeps the idea.
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    voted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: The status the voter was last told the idea was in. The vote sweep
    #: tells them when the idea's status is another.
    notified_status_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
