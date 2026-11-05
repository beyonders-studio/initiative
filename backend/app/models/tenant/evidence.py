"""Evidence: what a person attached to a ticket or a report.

A guild-schema table, one row per stored object. A row hangs off exactly one
parent — the community report it came with, or the operations case — and is
reached exactly as that parent is: a report's evidence by those who settle the
report, a case's by those in the case's initiative, and its filer's own by the
filer through their filer role (``app.db.operations_schema``).

The object itself is never in ``uploads`` and never served by the upload route.
It is stored encrypted under a key of its own (``app.core.blob_crypto``), and
the row holds that key wrapped for the community the row is in. ``origin_*``
name the object as it was first made, which is what its bytes are bound to: a
copy carried into another community keeps them, and gets a key wrapped there.

How long a row is kept is read from its parent — when the case's task was
done or trashed, when the report was settled — by the retention sweep
(``app.services.platform.evidence.purge_due``), not stored on the row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Uuid,
)
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin

#: Longest a stored name may be, after it is cleaned.
DISPLAY_NAME_LENGTH = 200


class EvidenceKind(str, Enum):
    """What a stored object is."""

    #: A file a person sent with their filing or their answer.
    attachment = "attachment"


_KIND_SQL = ", ".join(f"'{kind.value}'" for kind in EvidenceKind)


class Evidence(CreatedByMixin, table=True):
    """One stored object attached to a report or a case."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(report_id, case_task_id) = 1", name="ck_evidence_one_parent"
        ),
        CheckConstraint(f"kind IN ({_KIND_SQL})", name="ck_evidence_kind"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    report_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("moderation_reports.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    #: The operations case, named by its task: a case is its task, and every
    #: community's schema has ``tasks``.
    case_task_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    #: The answer it came with, where it came with one: the opening words or
    #: a reply. Kept so the conversation shows each file beside what was said.
    comment_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    kind: EvidenceKind = Field(
        default=EvidenceKind.attachment,
        sa_column=Column(String(length=16), nullable=False),
    )

    #: The community the object was first stored in, and its identity there.
    #: What its bytes are bound to, unchanged by a copy.
    origin_guild_id: int = Field(sa_column=Column(Integer, nullable=False))
    origin_id: uuid.UUID = Field(sa_column=Column(Uuid, nullable=False))

    #: Where the stored bytes are, in this community's namespace.
    storage_key: str = Field(sa_column=Column(String(length=64), nullable=False))
    size_bytes: int = Field(sa_column=Column(Integer, nullable=False))
    #: What the bytes are, read from them rather than from their name.
    content_type: str = Field(sa_column=Column(String(length=100), nullable=False))
    display_name: str = Field(
        sa_column=Column(String(length=DISPLAY_NAME_LENGTH), nullable=False)
    )
    #: Of the plaintext as stored, after anything was taken out of it.
    sha256: str = Field(sa_column=Column(String(length=64), nullable=False))

    #: The object's key, wrapped for this community.
    wrapped_dek: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    kek_version: int = Field(sa_column=Column(SmallInteger, nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
