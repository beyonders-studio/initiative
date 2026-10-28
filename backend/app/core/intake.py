"""The intake streams: what kinds of work arrive, and what feeds each one.

A **stream** is a named kind of operations work — security, moderation,
support, feedback. It is code rather than configuration because *its sources
are code*: what feeds ``security`` is a set of rules that watch the running
system, and what feeds ``moderation`` is a report endpoint. Adding a stream is
a release, exactly as adding an ``AuditEventType`` or a ``Tool`` is, and for
the same reason — one registry drives every surface.

A **binding** is the data half: *this stream, in this guild, lands in that
project.* Bindings live in the guild schema (``intake_bindings``); the
platform's pointer to the guild that holds them is
``app_settings.operations_guild_id``.

Nothing here names a company or a deployment. A deployment that has bound no
stream shows none of these surfaces and every writer call is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional


class IntakeStream(str, Enum):
    """The kinds of operations work a deployment can route into a project."""

    security = "security"
    moderation = "moderation"
    support = "support"
    feedback = "feedback"


class Source(str, Enum):
    """Where a case in a stream comes from."""

    #: A rule watching the running system decided a line was crossed.
    alerted = "alerted"
    #: A signed-in person sent it to us.
    submitted = "submitted"
    #: Somebody opened the task by hand, in the project, like any other task.
    manual = "manual"


class Submitter(str, Enum):
    """Who the writer acts for when a case is opened."""

    system = "system"
    member = "member"


class Conversation(str, Enum):
    """Whether the people handling a case and the person who filed it talk."""

    #: Nobody writes back. The filer is told the case arrived, and nothing of
    #: what is decided — a report, which is not a conversation.
    none = "none"
    #: The filer may answer once somebody handling it has written to them.
    staff_first = "staff_first"
    #: Either side may write first.
    open = "open"


class SecurityTopic(str, Enum):
    """What a security report is about, as its filer says."""

    #: A weakness in this server.
    vulnerability = "vulnerability"
    #: Somebody else got into their account.
    account_compromise = "account_compromise"
    other = "other"


class SupportTopic(str, Enum):
    """What somebody asking for help is asking about."""

    #: Their own account: signing in, their email, their age answer.
    account = "account"
    #: A community they are in.
    community = "community"
    #: Paying for something.
    billing = "billing"
    #: A copy of a community's data, or its erasure. Asked by whoever holds
    #: the community's seat, since it is theirs to ask for.
    data_request = "data_request"
    other = "other"


#: The help a person asks for from inside a community, about it. Offered only
#: where the deployment takes help requests from that community; every other
#: topic is about the person themselves, and is offered wherever support is
#: taken at all.
COMMUNITY_SUPPORT_TOPICS = frozenset(
    {SupportTopic.community, SupportTopic.data_request}
)


class FeedbackTopic(str, Enum):
    """What kind of feedback somebody is sending."""

    idea = "idea"
    problem = "problem"
    praise = "praise"
    other = "other"


#: The one moderation case a person files about themselves: asking for their
#: account's suspension to be lifted. Unlike a report it is a conversation.
APPEAL = "appeal"


#: Pictures a person may attach, by the type their bytes say they are.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
#: Documents a person may attach beside pictures.
DOCUMENT_TYPES = frozenset({"application/pdf", "text/plain"})

_MB = 1024 * 1024


@dataclass(frozen=True)
class EvidencePolicy:
    """What a person may attach when filing into a stream, or answering on a
    case in it."""

    #: Files on one filing or one answer. 0 takes none.
    max_files: int
    #: The largest one file may be.
    max_bytes: int
    #: The types a file may be, read from its bytes rather than its name.
    types: frozenset[str]


#: Nothing attached.
NO_EVIDENCE = EvidencePolicy(max_files=0, max_bytes=0, types=frozenset())


@dataclass(frozen=True)
class IntakeStreamMeta:
    """What a stream is fed by, how people file into it, and the blueprint
    that sets its project up."""

    sources: frozenset[Source]
    submitter: Submitter
    #: Filename under ``app/blueprints/intake/`` holding the export envelope
    #: that "set this up for me" imports.
    blueprint: str
    conversation: Conversation
    #: How often one account may file into the stream, as a ``limits`` string.
    #: Each filing is something a person reads.
    filing_rate: str
    #: How many of one account's cases may be open at once, or ``None`` for no
    #: cap — where every filing is about something different, a cap would turn
    #: away the second thing somebody saw.
    max_open_per_filer: int | None
    #: What a person may attach to a case.
    evidence: EvidencePolicy
    #: How long a case's evidence is kept once the case is closed.
    retention_days: int
    #: Whether the stream's cases keep an initiative to themselves. Membership
    #: of an initiative is what lets staff read a case, so a stream whose
    #: cases name people at risk binds where no other stream's staff work.
    isolated: bool = False
    #: Whether staff may name one of the stream's cases as the reason for an
    #: access grant, which then reports what the grant did on the case.
    grant_linkable: bool = False
    #: Topics whose cases talk differently from the stream's own.
    topic_conversation: Mapping[str, Conversation] = field(default_factory=dict)
    #: Topics with a cap of their own on one account's open cases, counted
    #: among that topic's cases alone.
    topic_open_caps: Mapping[str, int] = field(default_factory=dict)
    #: Topics that take different attachments from the stream's own.
    topic_evidence: Mapping[str, "EvidencePolicy"] = field(default_factory=dict)

    def evidence_for(self, topic: Optional[str]) -> "EvidencePolicy":
        """What may be attached to a case on ``topic``, or an answer on one."""
        if topic is None:
            return self.evidence
        return self.topic_evidence.get(topic, self.evidence)

    def conversation_for(self, topic: Optional[str]) -> Conversation:
        """How a case on ``topic`` talks."""
        if topic is None:
            return self.conversation
        return self.topic_conversation.get(topic, self.conversation)

    def open_cap_for(self, topic: Optional[str]) -> tuple[Optional[int], bool]:
        """One account's cap on open cases like this, and whether it counts
        that topic's cases alone rather than the stream's."""
        if topic is not None and topic in self.topic_open_caps:
            return self.topic_open_caps[topic], True
        return self.max_open_per_filer, False


#: Every stream, declared once. ``intake_test`` holds the enum and this map in
#: step, so a stream cannot exist without saying what feeds it.
STREAMS: dict[IntakeStream, IntakeStreamMeta] = {
    IntakeStream.security: IntakeStreamMeta(
        # The rules raise their own cases; a person reports a problem, or
        # says a change to their account wasn't them.
        sources=frozenset({Source.alerted, Source.submitted, Source.manual}),
        submitter=Submitter.member,
        blueprint="security.json",
        conversation=Conversation.open,
        filing_rate="5/day",
        max_open_per_filer=10,
        evidence=EvidencePolicy(5, 10 * _MB, IMAGE_TYPES | DOCUMENT_TYPES),
        retention_days=365,
        isolated=True,
        grant_linkable=True,
    ),
    IntakeStream.moderation: IntakeStreamMeta(
        sources=frozenset({Source.submitted, Source.manual}),
        submitter=Submitter.member,
        blueprint="moderation.json",
        conversation=Conversation.none,
        filing_rate="30/hour",
        max_open_per_filer=None,
        evidence=EvidencePolicy(5, 10 * _MB, IMAGE_TYPES | DOCUMENT_TYPES),
        retention_days=90,
        isolated=True,
        grant_linkable=True,
        # A report is not a conversation; an appeal is one, with the person
        # whose account it is, and they keep one open at a time. It is
        # written from the time-out screen, which opens nothing but itself,
        # so it is words alone.
        topic_conversation={APPEAL: Conversation.open},
        topic_open_caps={APPEAL: 1},
        topic_evidence={APPEAL: NO_EVIDENCE},
    ),
    IntakeStream.support: IntakeStreamMeta(
        # Alerted too: a community claiming sign-in claim values opens a
        # support case on its own, with nobody filing it.
        sources=frozenset({Source.submitted, Source.alerted, Source.manual}),
        submitter=Submitter.member,
        blueprint="support.json",
        conversation=Conversation.open,
        filing_rate="10/hour",
        max_open_per_filer=5,
        evidence=EvidencePolicy(5, 10 * _MB, IMAGE_TYPES | DOCUMENT_TYPES),
        retention_days=90,
        grant_linkable=True,
    ),
    IntakeStream.feedback: IntakeStreamMeta(
        sources=frozenset({Source.submitted, Source.manual}),
        submitter=Submitter.member,
        blueprint="feedback.json",
        conversation=Conversation.staff_first,
        filing_rate="5/day",
        max_open_per_filer=None,
        evidence=EvidencePolicy(3, 10 * _MB, IMAGE_TYPES),
        retention_days=30,
    ),
}


def meta(stream: IntakeStream) -> IntakeStreamMeta:
    """What feeds ``stream``. Raises for a stream with no declaration."""
    return STREAMS[stream]


def conversation_for(stream: IntakeStream, topic: Optional[str]) -> Conversation:
    """How a case in ``stream`` on ``topic`` talks with whoever filed it."""
    return STREAMS[stream].conversation_for(topic)


class CaseField(str, Enum):
    """The named fields a case carries besides its title and body.

    Each is a **property** on the task rather than a column, so a stream grows
    a field without a migration, and the project a team restructures keeps
    them. The writer fills the ones it has values for and leaves the rest
    empty.
    """

    #: Who the case is about, as the weak integer ref the audit envelope uses.
    #: A number rather than a person-picker: the subject of a case is not a
    #: member of the initiative handling it, and an erased account should leave
    #: a dangling id rather than a preserved person.
    subject_user = "subject_user"
    #: Which guild the case is about, same weak-ref reasoning.
    subject_guild = "subject_guild"
    #: The audit event this case was projected from, by uuid. What makes the
    #: population defensible: every case traces back to a row.
    source_event = "source_event"
    #: What the case is about, when it is about one thing in particular.
    resource_type = "resource_type"
    resource_id = "resource_id"
    #: When the thing happened, as distinct from when the case was filed.
    reported_at = "reported_at"
    #: Free text the stream's own project decides the vocabulary of.
    severity = "severity"
    #: The key of the finding in the private security repository, written in by
    #: a person when a case turns out to need a code change. One-way, by hand.
    tracker_key = "tracker_key"
    #: The law an ``illegal`` report or hold names (``LegalBasis``).
    legal_basis = "legal_basis"
    #: A link that opens what the case is about, in the community it is in,
    #: built from ``subject_guild``, ``resource_type`` and ``resource_id``. It
    #: opens only for somebody who can read it there: a grant still decides.
    subject_link = "subject_link"


#: Each field's property type, as a ``MetadataType`` value. Declared as plain
#: strings so this module stays free of model imports; ``intake_test`` checks
#: every one against the real enum, and against what the blueprints declare.
CASE_FIELD_TYPES: dict[CaseField, str] = {
    CaseField.subject_user: "number",
    CaseField.subject_guild: "number",
    CaseField.source_event: "text",
    CaseField.resource_type: "text",
    CaseField.resource_id: "number",
    CaseField.reported_at: "datetime",
    CaseField.severity: "text",
    CaseField.tracker_key: "text",
    CaseField.legal_basis: "text",
    CaseField.subject_link: "url",
}

#: Which fields each stream's blueprint defines. ``tracker_key`` is security's
#: alone — it names a finding in the private repository, which is a thing only
#: a security case becomes.
STREAM_FIELDS: dict[IntakeStream, tuple[CaseField, ...]] = {
    IntakeStream.security: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.source_event,
        CaseField.severity,
        CaseField.reported_at,
        CaseField.tracker_key,
    ),
    IntakeStream.moderation: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.resource_type,
        CaseField.resource_id,
        CaseField.subject_link,
        CaseField.severity,
        CaseField.reported_at,
        CaseField.legal_basis,
    ),
    IntakeStream.support: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.reported_at,
    ),
    IntakeStream.feedback: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.reported_at,
    ),
}
