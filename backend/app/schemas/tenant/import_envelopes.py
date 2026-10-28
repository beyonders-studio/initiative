"""Import-side pydantic mirrors of the export envelopes.

Each model parses the dict shape its export adapter emits (see
``services/export/adapters/{file,queue,counter_group,calendar,post}.py``)
with ``extra="ignore"``: informational export fields (queue member/file/
task display text, event ids and timestamps, linked file titles) parse
and drop — they reference guild-local state an import cannot rebind.

Every envelope is schema version 1. There is no support for reading an
earlier shape: the app imports what this build exports, and nothing else. The
one exception is a repeat, which older exports carry as JSON rather than RRULE
lines (``app.core.recurrence.imported``).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ConfigDict, Field, model_validator

from app.models.tenant.metadata import MetadataType
from app.models.tenant.wiki import WikiPageOrder, WikiReadingWidth
from app.schemas.base import SanitizedBaseModel

CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_IMPORT_VERSION = 1


class _EnvelopeBase(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_SCHEMA_VERSION
    #: Where the export was taken — the server and the community. A reference
    #: to something the envelope does not carry is kept only when both are
    #: where it is being imported, because only there does its id still name
    #: the same thing.
    source_instance_url: Optional[str] = None
    source_guild_id: Optional[int] = None


class EnvelopePropertyValue(SanitizedBaseModel):
    """Flat, by-name property value — the shared encoding written by
    ``export/property_values.py::property_export_dict``."""

    model_config = ConfigDict(extra="ignore")

    property_name: str
    property_type: MetadataType
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_json: Any = None
    value_handle: Optional[str] = None
    value_name: Optional[str] = None
    #: A money value's currency, which is its property's.
    currency: Optional[str] = None


class FileEnvelope(_EnvelopeBase):
    type: Literal["initiative-file"]
    file_type: str  # one of the editor's types: lexical | excalidraw | sheet | url
    name: str
    content: dict[str, Any] = {}
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    #: The handles the body's mention nodes name (``mentionHandle``). Each one
    #: the people step places is linked to that account on apply.
    mention_handles: list[str] = []


class WikiPageComment(SanitizedBaseModel):
    """One thing somebody said on a page.

    ``content`` is the body as an editor state, so it carries references the
    apply places — a page, an issue, a file, a person — the same way the
    page's own body does; it is written as the comment's text once they are.
    The author crosses as a handle and a name, never an id, like every
    person in an envelope.
    """

    model_config = ConfigDict(extra="ignore")

    content: dict[str, Any] = {}
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    created_at: Optional[str] = None
    #: What this comment was called where it came from, and the one it
    #: answers, so a thread arrives as a thread. Refs live for one job.
    external_ref: Optional[str] = None
    reply_to_ref: Optional[str] = None
    mention_handles: list[str] = []


class WikiPageEnvelope(SanitizedBaseModel):
    """One page: its body, where it sits, and what it is filed under.

    ``parent`` is a **slug**, not an id, and it is resolved after every page
    exists — the export writes pages in navigation order, which can put a
    child before its parent.
    """

    model_config = ConfigDict(extra="ignore")

    title: str
    slug: str
    parent: Optional[str] = None
    position: int = 0
    is_draft: bool = False
    content: dict[str, Any] = {}
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    #: When the page was written and when it was last edited. Absent in an
    #: export taken before they were carried, and absent is not "now" — the
    #: importer only uses a value it was actually given.
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    #: Who wrote it, where it came from: a handle the people step places, and
    #: the name to show when nobody answers to it.
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    #: The handles the body's mention nodes name without an account yet — by
    #: ``mentionHandle`` in an exported page, by ``mentionName`` in one mapped
    #: from Confluence. Each one the people step places is linked to that
    #: account on apply.
    mention_handles: list[str] = []
    #: What the page was called where it came from — ``confluence:123`` — for
    #: the job's links to point at. Never written to a column.
    external_ref: Optional[str] = None
    #: What was said on the page, oldest first, so a reply follows what it
    #: answers.
    comments: list[WikiPageComment] = []


class WikiFiledUpload(SanitizedBaseModel):
    """An uploaded file filed in a wiki: the row, and the key naming its bytes
    under ``assets/`` in the wiki's zip."""

    model_config = ConfigDict(extra="ignore")

    name: str
    storage_key: str
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []


class WikiFiledFile(SanitizedBaseModel):
    """A file filed in a wiki, and where it sits there.

    Exactly one of ``envelope`` (a text document, spreadsheet, whiteboard or
    link, whole) and ``upload`` (a file, whose bytes ride under ``assets/``).
    ``page`` is the slug of the page it is filed under, or none for the top.
    """

    model_config = ConfigDict(extra="ignore")

    page: Optional[str] = None
    position: Optional[int] = None
    envelope: Optional[FileEnvelope] = None
    upload: Optional[WikiFiledUpload] = None
    #: What the file was called where it came from — ``file:7`` — so
    #: a reference to it in a page points at the file it became.
    external_ref: Optional[str] = None


class WikiEnvelope(_EnvelopeBase):
    """A wiki, its pages, and the shape they sit in.

    What it deliberately drops is the sharing, for the reason every envelope
    drops it: who may read this is a fact about the community it was written
    in, not about the writing. ``home_page`` and ``template_page`` cross as
    slugs like the tree.

    The settings are absent in an export taken before they were carried, and
    a wiki imported from one keeps the defaults.
    """

    type: Literal["initiative-wiki"]
    name: str
    description: Optional[str] = None
    home_page: Optional[str] = None
    template_page: Optional[str] = None
    page_order: Optional[WikiPageOrder] = None
    contents_depth: Optional[int] = Field(default=None, ge=2, le=4)
    show_connections: Optional[bool] = None
    show_updated_at: Optional[bool] = None
    reading_width: Optional[WikiReadingWidth] = None
    accent_color: Optional[str] = Field(default=None, max_length=32)
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    pages: list[WikiPageEnvelope] = []
    #: The files filed in the wiki, when its export carried them.
    files: list[WikiFiledFile] = []


class QueueEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    position: float = 0.0
    color: Optional[str] = None
    notes: Optional[str] = None
    is_visible: bool = True
    held_at_round: Optional[int] = None
    is_current: bool = False
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    # `member`, `files`, `tasks` are informational display text in the
    # export — ignored here (extra="ignore"), counted as a warning on apply.
    member: Optional[str] = None
    #: What this item was called where it came from — a thing a reference
    #: elsewhere in the same import can name. Refs live for one job.
    external_ref: Optional[str] = None


class QueueEnvelope(_EnvelopeBase):
    type: Literal["initiative-queue"]
    name: str
    description: Optional[str] = None
    is_active: bool = False
    current_round: int = 1
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    items: list[QueueEnvelopeItem] = []


class CounterEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    color: Optional[str] = None
    count: float = 0
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    initial_count: float = 0
    view_mode: str = "number"
    position: float = 0
    properties: list[EnvelopePropertyValue] = []
    #: What this counter was called where it came from — a thing a reference
    #: elsewhere in the same import can name. Refs live for one job.
    external_ref: Optional[str] = None


class CounterGroupEnvelope(_EnvelopeBase):
    type: Literal["initiative-counter-group"]
    name: str
    description: Optional[str] = None
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    counters: list[CounterEnvelopeItem] = []


class DashboardEnvelope(_EnvelopeBase):
    """A dashboard as a backup carries it: a presentation spec and its canvas
    config, and no content of its own.

    ``definition`` is ``dict`` here rather than a modelled shape on purpose —
    it is re-validated on import by
    ``dashboard_definition.normalize_dashboard_definition``, which is the same
    check the create endpoint runs. A file is not a trusted source, and there
    is no second definition validator.
    """

    type: Literal["initiative-dashboard"]
    name: str
    description: Optional[str] = None
    # Present only for a dashboard built on a built-in plug-in. Dropped on import
    # when the destination has no such listing, so the dashboard arrives as an
    # ordinary one rather than pointing at nothing.
    listing_uid: Optional[str] = None
    listing_version: Optional[str] = None
    definition: dict[str, Any] = {}
    config: dict[str, Any] = {}
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []


class PostPollEnvelope(SanitizedBaseModel):
    """The question a notice asks, as a backup carries it.

    The **choices** cross; the **answers** do not. A ballot is one person in
    one community saying something, and the ids naming them mean nothing in the
    guild this is restored into — the same reason the sharing is not carried
    either. So an imported poll arrives open and unanswered, which is what a
    question somebody has just asked is.

    ``closes_at`` is dropped for the reason the pin and the schedule are: it
    said when this question stopped mattering on the board it came from.
    """

    model_config = ConfigDict(extra="ignore")

    question: Optional[str] = None
    options: list[str] = []
    allows_multiple: bool = False
    is_anonymous: bool = False
    hide_results: bool = False

    @model_validator(mode="after")
    def _options_within_limits(self) -> "PostPollEnvelope":
        # The same bounds the endpoints hold a poll to. An import is a write
        # like any other, and one that skipped them would store a question the
        # app would refuse to accept or to save again.
        from app.models.tenant.post_poll import (
            MAX_POLL_OPTION_CHARS,
            MAX_POLL_OPTIONS,
            MIN_POLL_OPTIONS,
        )

        cleaned = [option.strip() for option in self.options]
        if not MIN_POLL_OPTIONS <= len(cleaned) <= MAX_POLL_OPTIONS:
            raise ValueError("poll has more or fewer choices than a poll may have")
        if any(not option or len(option) > MAX_POLL_OPTION_CHARS for option in cleaned):
            raise ValueError("a poll choice is empty or longer than one may be")
        if len({option.casefold() for option in cleaned}) != len(cleaned):
            raise ValueError("two poll choices say the same thing")
        self.options = cleaned
        return self


class PostEnvelope(_EnvelopeBase):
    """One bulletin-board notice: its headline, its Lexical body, its tags,
    and the question it asks.

    The pin is deliberately not carried. A pin says "this matters on this
    board right now", which is a fact about the board it was pinned to, not
    about the notice — an import that restored it would put a stranger's
    notice at the top of somebody else's board.

    The body's ceiling is enforced here rather than left to the column: an
    import is a write like any other, and one that skipped the limit would
    store a post the endpoints would refuse to accept or to save again. The
    headline is not — it is display text, so the importer trims it and says
    so rather than failing a whole restore over a long title.
    """

    type: Literal["initiative-post"]
    name: str
    body: dict[str, Any] = {}
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    poll: Optional[PostPollEnvelope] = None
    #: The handles the body's mention nodes name, as a file's are.
    mention_handles: list[str] = []

    @model_validator(mode="after")
    def _body_within_limits(self) -> "PostEnvelope":
        # The same rule the endpoints apply, not a second copy of it: an
        # envelope that checked only the character count let a large, low-text
        # Lexical structure through, which a normal write would then refuse.
        # Imported here because the schema module is dependency-light on
        # purpose, and this is the one place it needs the post rules.
        from app.schemas.tenant.post import post_body_too_long

        if post_body_too_long(self.body):
            raise ValueError("post body exceeds the limits a post is held to")
        return self


class EventEnvelopeAttendee(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    #: ``foobar#1234`` — the handle names one account and is what the export
    #: writes. An address is not a person's identifier here.
    handle: Optional[str] = None
    rsvp: str = "pending"


class EventEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: str
    end_at: str
    all_day: bool = False
    # RRULE lines; an export taken before RRULE carries the older JSON shape.
    recurrence: Optional[str | dict[str, Any]] = None
    recurrence_shift: int = 0
    attendees: list[EventEnvelopeAttendee] = []
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    #: What this event was called where it came from. An event is a thing
    #: other entries point at — a sprint with its tasks in it — so it needs a
    #: name the job's deferred link pass can resolve, exactly as a task does.
    external_ref: Optional[str] = None
    #: When the event was written down (not when it happens — that is
    #: ``start_at``). The export has always emitted it; it is read now.
    created_at: Optional[str] = None
    #: An occurrence with a row of its own: its series' ``external_ref``, and
    #: its start there.
    series_ref: Optional[str] = None
    original_start: Optional[str] = None


class CalendarEnvelope(_EnvelopeBase):
    type: Literal["initiative-calendar"]
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    events: list[EventEnvelopeItem] = []
