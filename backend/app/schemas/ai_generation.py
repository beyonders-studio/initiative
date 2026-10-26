"""AI Generation request and response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel


class _WrittenFromComments(SanitizedBaseModel):
    """How many of the task's comments a suggestion was written from: the
    newest, as many as fit. Fewer than ``comments_total`` when some did not."""

    comments_read: int
    comments_total: int


class GenerateChecklistResponse(_WrittenFromComments):
    """Suggested checklist lines, as text — the caller decides which to keep."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[str]


class GenerateDescriptionResponse(_WrittenFromComments):
    """A description for the reader to start from."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    description: RawTextStr


class AIStreamCut(SanitizedBaseModel):
    """How much of what was asked about was read: ``percent`` of it, from its
    start (a document) or from the top of its order (a catch-up)."""

    percent: int


class AIStreamEvent(SanitizedBaseModel):
    """One line of an answer streamed as it is written. Exactly one field is
    set: ``since`` first on a catch-up, where the changes it read start;
    ``cut`` next, when only part of what was asked about fit; ``text``, the
    next piece of the answer; or ``error``, the code it ended on. A catch-up
    with nothing to read ends after ``since``."""

    since: Optional[datetime] = None
    cut: Optional[AIStreamCut] = None
    text: Optional[RawTextStr] = None
    error: Optional[str] = None
