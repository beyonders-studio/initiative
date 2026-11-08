"""Payloads for filing a ticket, and for what a filing surface offers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import (
    AfterValidator,
    ConfigDict,
    Discriminator,
    Field as PydanticField,
    Tag,
    model_validator,
)

from app.core.intake import (
    APPEAL,
    COMMUNITY_SUPPORT_TOPICS,
    Conversation,
    FeedbackTopic,
    IntakeStream,
    SecurityTopic,
    SupportTopic,
)
from app.core.moderation import ReportVenue
from app.schemas.base import RichTextStr, SanitizedBaseModel
from app.schemas.tenant.evidence import EvidencePolicyRead, EvidenceRead
from app.schemas.tenant.moderation import ReportCreate
from app.services.platform.tickets import FilerState, TicketMode
from app.services.tenant.support import BODY_LENGTH, SUBJECT_LENGTH


def _said_something(value: str) -> str:
    """Trim, and refuse what is left if it is nothing.

    The length bounds count characters, and a space is one — so the minimum
    alone admits a case whose title is blank on the board somebody has to work
    from. Trimming here also means the stored value is the one that was meant,
    whatever the client did or did not tidy up.
    """
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


class SupportTicketCreate(SanitizedBaseModel):
    """Asking for help: about a community they are in, or about themselves."""

    stream: Literal["support"]
    #: What it is about. A question about a community (``community``,
    #: ``data_request``) names it in ``community_id``; any other is about the
    #: person asking.
    type: SupportTopic = SupportTopic.community
    #: The community they are asking about. Whether its members may ask is the
    #: operator's entitlement, checked against their own access to it.
    community_id: Optional[int] = None
    #: One line saying what this is about. Becomes the case's title.
    subject: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=SUBJECT_LENGTH
    )
    #: The rest of it, in their own words.
    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )

    @model_validator(mode="after")
    def _names_its_community(self) -> "SupportTicketCreate":
        if self.type in COMMUNITY_SUPPORT_TOPICS and self.community_id is None:
            raise ValueError("a question about a community names it")
        return self


class ModerationTicketCreate(ReportCreate):
    """Reporting something. The same shape from every surface."""

    stream: Literal["moderation"]


class SecurityTicketCreate(SanitizedBaseModel):
    """Telling whoever runs this server about a security problem."""

    stream: Literal["security"]
    #: What it is about.
    type: SecurityTopic
    #: One line saying what this is. Becomes the case's title.
    subject: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=SUBJECT_LENGTH
    )
    #: What they found, in their own words.
    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )


class AppealTicketCreate(SanitizedBaseModel):
    """Asking for a suspended account's suspension to be lifted. Filed by the
    account itself, from its time-out screen."""

    stream: Literal["moderation"]
    type: Literal["appeal"]
    #: Why it should be lifted, in their own words.
    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )


#: What a client's own context may hold: words, versions and route templates.
_CONTEXT_TEXT = r"^[\w./$:@+\- ]*$"


class FeedbackContext(SanitizedBaseModel):
    """Where the app was when feedback was sent, as the sender saw it before
    sending, and could remove. Nothing that names a person or a thing: the
    route is its template, with every id left out."""

    app_version: Optional[str] = PydanticField(
        default=None, max_length=32, pattern=_CONTEXT_TEXT
    )
    #: ``web``, ``android``, ``ios``, ``desktop``.
    platform: Optional[str] = PydanticField(
        default=None, max_length=16, pattern=_CONTEXT_TEXT
    )
    locale: Optional[str] = PydanticField(
        default=None, max_length=35, pattern=_CONTEXT_TEXT
    )
    theme: Optional[str] = PydanticField(
        default=None, max_length=16, pattern=_CONTEXT_TEXT
    )
    #: The page's route template, e.g. ``/c/$communityId/i/$initiativeId``.
    route: Optional[str] = PydanticField(
        default=None, max_length=200, pattern=_CONTEXT_TEXT
    )
    #: The width class the window was in.
    viewport: Optional[str] = PydanticField(
        default=None, max_length=16, pattern=_CONTEXT_TEXT
    )


class FeedbackTicketCreate(SanitizedBaseModel):
    """Telling the team what somebody thinks: an idea, something that got in
    their way, or what they love."""

    stream: Literal["feedback"]
    type: FeedbackTopic
    #: What they think, in their own words.
    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )
    #: Whether the team may write to them about it. Theirs to offer; off unless
    #: they tick it.
    contactable: bool = False
    #: Where the app was, where they chose to send it.
    context: Optional[FeedbackContext] = None


def _ticket_kind(value: Any) -> Optional[str]:
    """Which shape a filing is: its stream, and for moderation whether it is
    an appeal rather than a report."""
    if isinstance(value, dict):
        stream, topic = value.get("stream"), value.get("type")
    else:
        stream, topic = getattr(value, "stream", None), getattr(value, "type", None)
    if stream == IntakeStream.moderation.value and topic == APPEAL:
        return APPEAL
    return stream


#: One filing, told apart by its stream, and a moderation filing by whether it
#: is an appeal.
TicketCreate = Annotated[
    Union[
        Annotated[SupportTicketCreate, Tag(IntakeStream.support.value)],
        Annotated[ModerationTicketCreate, Tag(IntakeStream.moderation.value)],
        Annotated[SecurityTicketCreate, Tag(IntakeStream.security.value)],
        Annotated[FeedbackTicketCreate, Tag(IntakeStream.feedback.value)],
        Annotated[AppealTicketCreate, Tag(APPEAL)],
    ],
    Discriminator(_ticket_kind),
]


class TicketAccepted(SanitizedBaseModel):
    """What the filer is told: that it arrived.

    Not who will read it, and for a report not whether one already existed —
    a report is not a conversation with the person who sent it, so ``venue``
    is all it says, and only for a report.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    accepted: bool = True
    venue: Optional[ReportVenue] = None
    #: For an ``illegal`` report the platform takes no cases about: where to
    #: tell whoever runs this server, alongside the community.
    platform_contact: Optional[str] = None


class StreamAvailabilityRead(SanitizedBaseModel):
    """What one stream offers the reader, from where they are."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    mode: TicketMode
    #: Who to write to about it, whatever the mode.
    contact: Optional[str] = None
    #: The topics the reader may file from here, in the order they are
    #: offered. Empty for a stream whose filings name no topic of their own.
    types: List[str] = PydanticField(default_factory=list)
    #: What may be attached to a filing or an answer in this stream.
    evidence: EvidencePolicyRead


class TicketAvailability(SanitizedBaseModel):
    """What every stream offers the reader. One entry per stream."""

    security: StreamAvailabilityRead
    moderation: StreamAvailabilityRead
    support: StreamAvailabilityRead
    feedback: StreamAvailabilityRead


class FiledTicketRead(SanitizedBaseModel):
    """One case its filer can follow: what they called it, and where it stands."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    task_id: int
    stream: IntakeStream
    #: What it is about within its stream, as they chose.
    topic: Optional[str] = None
    #: What they called it, in their own words.
    subject: Optional[str] = None
    state: FilerState
    opened_at: datetime
    updated_at: Optional[datetime] = None


class FiledTicketList(SanitizedBaseModel):
    """The cases the reader filed, most recently moved first."""

    items: List[FiledTicketRead]


class TicketMessageRead(SanitizedBaseModel):
    """One part of the conversation about a case, as its filer reads it.

    The people handling the case are not named here: ``mine`` says whether the
    reader wrote it, and everything else is the team's.
    """

    id: int
    mine: bool
    #: Kept as written, like any comment body.
    content: RichTextStr
    created_at: datetime
    #: The files that came with it. Only the reader's own: what they sent.
    attachments: List[EvidenceRead] = PydanticField(default_factory=list)


class FiledTicketDetailRead(FiledTicketRead):
    """One case its filer filed, with what has been said to them about it."""

    conversation: Conversation
    #: Whether the reader may answer now: the kind of case allows it, it is
    #: not closed, and where the people handling it speak first, they have.
    can_reply: bool
    #: What an answer may carry with it, for this kind of case.
    evidence: EvidencePolicyRead
    messages: List[TicketMessageRead]


class TicketReplyCreate(SanitizedBaseModel):
    """A filer's answer on their own case."""

    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )
