"""Filing a ticket: one way in, for every kind of operations work.

A ticket is an intake case — a task in the operations guild — filed by a
person. This module is what every filing surface goes through: it says, per
stream, whether a form can be offered at all, holds each account to the
stream's pace, and hands the filing to the stream that knows what it means.

Where a stream cannot take a filing — nothing is bound to receive it, or the
person is not entitled to file it from where they are — the answer is the
stream's contact address rather than a form, and where there is no address
either, nothing. A form that can only answer "nowhere to send this" is worse
than the address it replaces.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, AsyncIterator, Optional, Sequence

from limits import parse
from sqlalchemy import String, cast
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import (
    Conversation,
    FeedbackTopic,
    IntakeStream,
    SecurityTopic,
    conversation_for,
    meta,
)
from app.core.rate_limit import take_allowance
from app.db import cohorts
from app.db.session import routed_guild_id
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform import intake as intake_service
from app.services.tenant import support as support_service

if TYPE_CHECKING:
    from app.services.platform.evidence import PreparedEvidence

#: The counter namespace a filing's pace is kept under.
_PACE_NAMESPACE = "tickets"


class TicketMode(str, Enum):
    """What a filing surface offers for a stream."""

    #: The form: there is somewhere to send it, and this person may.
    form = "form"
    #: The stream's contact address, and nothing to fill in.
    email = "email"
    #: Nothing at all: no form and nobody to write to.
    none = "none"


@dataclass(frozen=True)
class StreamAvailability:
    """What one stream offers this person, from where they are."""

    mode: TicketMode
    #: Who to write to about the stream, whatever the mode — a form whose
    #: filing turns out to have nowhere to go falls back to it.
    contact: Optional[str]
    #: The topics the form offers this person from here, in offering order.
    types: tuple[str, ...] = ()


class FilingTooFast(Exception):
    """This account has filed into the stream as often as its pace allows."""


async def _contacts(session: AsyncSession) -> dict[IntakeStream, Optional[str]]:
    """Every stream's contact address, from one read of the settings row.

    The stream's own address, else the deployment's general one — the rule
    :func:`app.services.platform.intake.contact_for` applies, for all four.
    """
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        return {stream: None for stream in IntakeStream}
    own = row.intake_contacts or {}
    return {
        stream: own.get(stream.value) or row.intake_general_contact
        for stream in IntakeStream
    }


def _fallback(contact: Optional[str]) -> StreamAvailability:
    return StreamAvailability(
        mode=TicketMode.email if contact else TicketMode.none, contact=contact
    )


async def availability(
    session: AsyncSession, *, user: User, guild_id: Optional[int]
) -> dict[IntakeStream, StreamAvailability]:
    """What each stream offers ``user``, standing in ``guild_id`` if anywhere.

    ``session`` is the caller's own platform session; whether they may file
    from a community is asked on a session of theirs routed into it.
    """
    contacts = await _contacts(session)
    offered: dict[IntakeStream, StreamAvailability] = {}
    for stream in IntakeStream:
        contact = contacts[stream]
        if stream is IntakeStream.moderation:
            # A report about a community's own content goes to that
            # community's moderators and needs no platform at all, so the
            # form is always there; a report the platform would have to take
            # falls back to the address when nothing is bound.
            offered[stream] = StreamAvailability(TicketMode.form, contact)
        elif not await intake_service.stream_is_bound(stream):
            offered[stream] = _fallback(contact)
        elif stream is IntakeStream.support:
            # Their own account is always theirs to ask about; a community
            # only where it takes help requests, and its data only for the
            # seat holder.
            community = (
                await support_service.community_topics(user, guild_id)
                if guild_id is not None
                else frozenset()
            )
            offered[stream] = StreamAvailability(
                TicketMode.form,
                contact,
                tuple(t.value for t in support_service.offered_topics(community)),
            )
        else:
            # Anybody signed in may tell the server about a security problem,
            # or what they think.
            topics = SecurityTopic if stream is IntakeStream.security else FeedbackTopic
            offered[stream] = StreamAvailability(
                TicketMode.form, contact, tuple(t.value for t in topics)
            )
    return offered


async def hold_pace(user: User, stream: IntakeStream) -> None:
    """Refuse a filing past the stream's pace.

    Counted per account, under the stream's declared rate. The stream's cap on
    open cases is the writer's to hold, in the transaction that opens the case
    (``intake.CaseCapReached``).
    """
    if not await take_allowance(
        parse(meta(stream).filing_rate),
        _PACE_NAMESPACE,
        f"{stream.value}:user:{user.id}",
    ):
        raise FilingTooFast


# ── Following a ticket ───────────────────────────────────────────────────────


class FilerState(str, Enum):
    """Where a filed case stands, as its filer is shown it.

    Derived from the case's status when read, never stored: the people working
    the case move it, and this follows.
    """

    received = "received"
    in_progress = "in_progress"
    waiting_on_you = "waiting_on_you"
    closed = "closed"


def derive_state(
    *,
    category: str,
    status_id: Optional[int],
    awaiting_status_id: Optional[int],
    stream: IntakeStream,
    topic: Optional[str] = None,
    trashed: bool = False,
) -> FilerState:
    """The state a case's status shows its filer.

    A case the team put in the trash is closed to its filer. A case with no
    conversation never waits on its filer, who has no way to answer.
    """
    if trashed or category == TaskStatusCategory.done:
        return FilerState.closed
    if (
        awaiting_status_id is not None
        and status_id == awaiting_status_id
        and conversation_for(stream, topic) is not Conversation.none
    ):
        return FilerState.waiting_on_you
    if category == TaskStatusCategory.todo:
        return FilerState.received
    return FilerState.in_progress


@dataclass(frozen=True)
class FiledTicket:
    """One case its filer can follow."""

    task_id: int
    stream: IntakeStream
    subject: Optional[str]
    state: FilerState
    opened_at: datetime
    updated_at: Optional[datetime]
    status_id: Optional[int] = None
    #: What it is about within its stream, as they chose.
    topic: Optional[str] = None


@dataclass(frozen=True)
class TicketMessage:
    """One part of the conversation, as its filer reads it."""

    id: int
    #: Written by the filer; otherwise by the people handling the case, who
    #: are shown as the team rather than by name.
    mine: bool
    content: str
    created_at: datetime
    #: What they sent with it.
    attachments: tuple["TicketAttachment", ...] = ()


@dataclass(frozen=True)
class TicketAttachment:
    """A file the filer sent, as they read it back."""

    id: int
    display_name: str
    content_type: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class FiledTicketDetail:
    #: The operations community the case was read in, which is where an
    #: answer to it is written.
    guild_id: int
    ticket: FiledTicket
    conversation: Conversation
    can_reply: bool
    messages: list[TicketMessage]


class TicketNotFound(Exception):
    """No case of theirs by that id."""


class ReplyRefused(Exception):
    """The case takes no answer from its filer now."""


@asynccontextmanager
async def _as_filer(user: User) -> AsyncIterator[Optional[AsyncSession]]:
    """A request session routed as ``user`` reading the cases they filed, or
    ``None`` where there is no operations community to read them in.

    From the operations community's cohort on the request engine, through the
    seam: what the session reads is the filer role's to decide.
    """
    from app.api.deps import FilerAccessError, establish_filer_access

    guild_id = await intake_service.configured_operations_guild_id()
    if guild_id is None:
        yield None
        return
    async with cohorts.request_sessionmaker(guild_id)() as session:
        try:
            await establish_filer_access(session, user)
        except FilerAccessError:
            yield None
            return
        yield session


def _ticket_columns():
    return (
        IntakeCase.task_id,
        IntakeCase.stream,
        IntakeCase.topic,
        IntakeCase.filer_subject,
        IntakeCase.opened_at,
        Task.updated_at,
        Task.task_status_id,
        # As text: the filer role decodes no enum type, which the driver would
        # first have to look up in the catalog with privileges it does not hold.
        cast(TaskStatus.category, String),
        IntakeBinding.awaiting_filer_status_id,
        Task.deleted_at,
    )


def _ticket_from(row) -> FiledTicket:
    (
        task_id,
        stream,
        topic,
        subject,
        opened_at,
        updated_at,
        status_id,
        category,
        awaiting,
        deleted_at,
    ) = row
    return FiledTicket(
        task_id=task_id,
        stream=IntakeStream(stream),
        subject=subject,
        state=derive_state(
            category=category,
            status_id=status_id,
            awaiting_status_id=awaiting,
            stream=IntakeStream(stream),
            topic=topic,
            trashed=deleted_at is not None,
        ),
        opened_at=opened_at,
        updated_at=updated_at,
        status_id=status_id,
        topic=topic,
    )


def _tickets_query():
    return (
        select(*_ticket_columns())
        .join(Task, Task.id == IntakeCase.task_id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .outerjoin(IntakeBinding, IntakeBinding.stream == IntakeCase.stream)
    )


async def list_filed(user: User) -> list[FiledTicket]:
    """The cases ``user`` filed, the most recently moved first."""
    async with _as_filer(user) as session:
        if session is None:
            return []
        rows = (
            await session.exec(
                _tickets_query().order_by(Task.updated_at.desc(), Task.id.desc())
            )
        ).all()
    return [_ticket_from(row) for row in rows]


def _can_reply(
    conversation: Conversation, state: FilerState, messages: list[TicketMessage]
) -> bool:
    if state is FilerState.closed or conversation is Conversation.none:
        return False
    if conversation is Conversation.staff_first:
        return any(not message.mine for message in messages)
    return True


async def read_filed(user: User, task_id: int) -> FiledTicketDetail:
    """One case ``user`` filed, with the conversation said to them."""
    async with _as_filer(user) as session:
        if session is None:
            raise TicketNotFound
        row = (
            await session.exec(_tickets_query().where(IntakeCase.task_id == task_id))
        ).first()
        if row is None:
            raise TicketNotFound
        said = (
            await session.exec(
                select(
                    Comment.id, Comment.created_by, Comment.content, Comment.created_at
                )
                .where(Comment.task_id == task_id)
                .order_by(Comment.created_at, Comment.id)
            )
        ).all()
        sent = (
            await session.exec(
                select(
                    Evidence.comment_id,
                    Evidence.id,
                    Evidence.display_name,
                    Evidence.content_type,
                    Evidence.size_bytes,
                    Evidence.created_at,
                )
                .where(Evidence.case_task_id == task_id)
                .order_by(Evidence.created_at, Evidence.id)
            )
        ).all()
        guild_id = routed_guild_id(session)
    if guild_id is None:
        raise TicketNotFound
    ticket = _ticket_from(row)
    attached: dict[Optional[int], list[TicketAttachment]] = {}
    for comment_id, *fields in sent:
        attached.setdefault(comment_id, []).append(TicketAttachment(*fields))
    messages = [
        TicketMessage(
            id=comment_id,
            mine=author == user.id,
            content=content,
            created_at=created_at,
            attachments=tuple(attached.get(comment_id, ())),
        )
        for comment_id, author, content, created_at in said
    ]
    conversation = conversation_for(ticket.stream, ticket.topic)
    return FiledTicketDetail(
        guild_id=guild_id,
        ticket=ticket,
        conversation=conversation,
        can_reply=_can_reply(conversation, ticket.state, messages),
        messages=messages,
    )


async def filed_evidence(user: User, task_id: int, evidence_id: int) -> int:
    """The operations community holding file ``evidence_id`` of case
    ``task_id``, where it is one ``user`` sent with it. Raises
    :class:`TicketNotFound` otherwise, the same for a file that is not theirs
    as for one that does not exist.

    Read through their filer role, which admits only their own files on their
    own cases; serving it reads the rest on the operations community's system
    session once this has answered.
    """
    async with _as_filer(user) as session:
        if session is None:
            raise TicketNotFound
        found = (
            await session.exec(
                select(Evidence.id)
                .where(Evidence.id == evidence_id)
                .where(Evidence.case_task_id == task_id)
            )
        ).first()
        guild_id = routed_guild_id(session)
    if found is None or guild_id is None:
        raise TicketNotFound
    return guild_id


async def reply(
    user: User,
    detail: FiledTicketDetail,
    words: str,
    evidence: Sequence["PreparedEvidence"] = (),
) -> None:
    """Add ``user``'s answer to a case they filed.

    ``detail`` is the case as read through their filer access, which is what
    says it is theirs and takes an answer now. The answer is written on the
    writer's own session, said to them like the rest of the conversation. A
    case waiting on them goes back to the status the stream's binding names for
    that, where it names one, and the case's assignees are told as they are of
    any comment on it.
    """
    if not detail.can_reply:
        raise ReplyRefused
    taken = await intake_service.add_filer_reply(
        guild_id=detail.guild_id,
        task_id=detail.ticket.task_id,
        filer=user,
        words=words,
        stream=detail.ticket.stream,
        evidence=evidence,
    )
    if not taken:
        raise ReplyRefused
