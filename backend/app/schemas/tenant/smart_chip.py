"""What a smart chip shows right now."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.search import SearchEntityType
from app.core.smart_chips import SmartChipAspect, SmartChipKind, SmartChipTone

#: Ceiling on one chips request, so the cost of answering one is bounded.
#:
#: The endpoint REFUSES a request carrying more rather than answering part of
#: it, because a partial answer is indistinguishable from a page whose things
#: were all deleted. A longer page asks in several requests instead — see
#: ``REFS_PER_REQUEST`` in the client's ``useSmartChips``, which batches to this
#: number. A request costs a few queries per kind it names, however many it
#: names, so this is set to cover a whole document in one.
MAX_REFS = 500

#: Ceiling on one embeds request. Lower than a chip's: an embed answers with
#: the whole body of what it names, and the editor asks for one at a time.
MAX_EMBEDS = 25

_REFS_DESCRIPTION = (
    "References to read. `task:12` names a thing, `task:12:status` a fact "
    "about it. One that names nothing is ignored."
)


class ReferenceRead(BaseModel):
    """The references one page asks about, read together.

    A body rather than a query string: what a page points at is its own
    business, and a URL is rewritten and recorded by whatever it passes
    through.
    """

    refs: list[str] = Field(
        default_factory=list,
        max_length=MAX_REFS,
        description=_REFS_DESCRIPTION
        + " Chips: "
        + ", ".join(kind.value for kind in SmartChipKind),
    )


class EmbedRead(BaseModel):
    """The references to show in full, as `kind:id`."""

    refs: list[str] = Field(
        default_factory=list, max_length=MAX_EMBEDS, description=_REFS_DESCRIPTION
    )


class SmartChipState(BaseModel):
    """One chip's current reading.

    ``text`` is always set, so a client that understands nothing else can still
    render the chip. ``date`` and ``number`` are sent alongside it where the
    value is one of those, because a date and a number belong in the reader's
    own locale and only the client knows what that is.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The ``kind:id:aspect`` this answers, echoed back so a client can match
    #: it to the chip that asked without relying on order.
    ref: str
    #: What the reference names.
    entity_type: SearchEntityType
    #: Which fact about it, or absent where this is simply what it is called.
    aspect: SmartChipAspect | None = None
    text: str
    #: What the thing is called right now. Sent with every answer so a chip
    #: showing a fact can also name what the fact is about — the reading goes
    #: in the sentence, the name goes on the card behind it — without the
    #: caller spending a second reference on the same row.
    title: str | None = None
    tone: SmartChipTone
    #: A colour the thing carries itself — a task status has one. Overrides the
    #: tone where present.
    color: str | None = None
    date: datetime | None = None
    number: Decimal | None = None
    #: Whether this reader may change the fact from the chip itself. Only a chip
    #: that can be acted on — a task's box — is ever ``True``.
    writable: bool = False


class ReferenceEmbed(BaseModel):
    """A reference shown in full — ``![[ ]]`` rather than ``#``.

    The same reference and the same gate as a link; what it adds is what the
    thing says about itself: its description, for the kinds that carry one,
    or its whole body, for the kinds that are prose.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The bare ``kind:id`` this answers.
    ref: str
    entity_type: SearchEntityType
    #: What the thing is called right now.
    title: str
    #: Its description, where the kind has one and it is filled in.
    description: str | None = None
    #: Its body as the editor stores it (Lexical JSON), where the thing is
    #: prose — a text document, a wiki page — and has anything written in it.
    body: dict[str, Any] | None = None


class ReferenceEmbedList(BaseModel):
    """The embeds that could be read; anything gone or out of reach is absent."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[ReferenceEmbed]


class SmartChipStateList(BaseModel):
    """The chips that could be read.

    A ref that names nothing, or something this caller cannot see, is simply
    absent: the two are the same answer, and the chip falls back to the label
    the file already stored.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[SmartChipState]
