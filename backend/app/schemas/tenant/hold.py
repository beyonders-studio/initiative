"""Holding content for the platform, and releasing a hold."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field as PydanticField

from app.core.moderation import HoldReason, HoldRelease, HoldVia, LegalBasis
from app.schemas.base import SanitizedBaseModel

#: Longest a hold's note may be.
NOTE_LENGTH = 2000


class HoldCreate(SanitizedBaseModel):
    """Hold something for the platform."""

    #: The kind of thing held — a ``SearchEntityType`` — and its id.
    target_type: str = PydanticField(min_length=1, max_length=32)
    target_id: int
    reason: HoldReason
    #: Required for ``illegal_content``.
    legal_basis: LegalBasis | None = None
    #: Who asked, a reference number. Read only by the platform.
    note: str | None = PydanticField(default=None, max_length=NOTE_LENGTH)
    #: The operations case a platform moderator is holding it under. A
    #: community moderator's hold opens its own.
    case_task_id: int | None = None


class HoldPlaced(SanitizedBaseModel):
    """A hold was placed. Nothing more is said: from now on, the content
    reads as absent to the community, the moderator who held it included."""

    placed: bool = True


class HoldReleaseCreate(SanitizedBaseModel):
    """End a hold."""

    outcome: HoldRelease


class ContentHoldRead(SanitizedBaseModel):
    """One hold, as the platform reads it."""

    id: int
    target_type: str
    target_id: int
    #: What the held thing is called, where it has a name.
    label: str | None = None
    case_task_id: int | None = None
    placed_via: HoldVia
    reason: HoldReason
    legal_basis: LegalBasis | None = None
    note: str | None = None
    placed_at: datetime
    released_at: datetime | None = None
    release_outcome: HoldRelease | None = None
