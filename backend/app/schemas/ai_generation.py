"""AI Generation request and response schemas."""

import string
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import ConfigDict, Field, model_validator

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


#: What a language tag is written with.
_LANGUAGE_TAG_CHARS = frozenset(string.ascii_letters + string.digits + "-")


class AIWriteAction(str, Enum):
    """What writing help is asked to do with a selection."""

    rewrite = "rewrite"
    shorten = "shorten"
    #: Spelling, grammar and punctuation, and nothing else.
    fix = "fix"
    #: Into ``language``.
    translate = "translate"
    #: Write on from the text before the cursor; there is no selection.
    continue_ = "continue"


class AIWriteRequest(SanitizedBaseModel):
    """Writing help for a selection in a document, with the text either side
    of it. Only this text is read; nothing is looked up."""

    action: AIWriteAction
    #: The selection, as markdown. Empty to continue writing.
    text: RawTextStr = Field(default="", max_length=100_000)
    #: The text before the selection, nearest last.
    before: RawTextStr = Field(default="", max_length=100_000)
    #: The text after the selection.
    after: RawTextStr = Field(default="", max_length=100_000)
    #: The language to translate into, as a language tag (``de``, ``pt-BR``).
    language: Optional[str] = Field(default=None, max_length=35)

    @model_validator(mode="after")
    def _says_what_to_work_on(self) -> "AIWriteRequest":
        if self.action is AIWriteAction.translate and not self.language:
            raise ValueError("translate needs a language")
        if self.language and not set(self.language) <= _LANGUAGE_TAG_CHARS:
            raise ValueError("language is a language tag")
        if self.action is not AIWriteAction.continue_ and not self.text.strip():
            raise ValueError("needs a selection")
        return self
