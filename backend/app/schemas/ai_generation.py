"""AI Generation request and response schemas."""

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
    """How much of what was asked about was read: the first ``percent`` of it."""

    percent: int


class AIStreamEvent(SanitizedBaseModel):
    """One line of an answer streamed as it is written. Exactly one field is
    set: ``cut`` first, when only part of what was asked about fit; ``text``,
    the next piece of the answer; or ``error``, the code it ended on."""

    cut: Optional[AIStreamCut] = None
    text: Optional[RawTextStr] = None
    error: Optional[str] = None
