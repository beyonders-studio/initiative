"""Filing a ticket: help, a report, a security problem, feedback, an appeal.

Two routes, both the signed-in person's own:

- ``GET /me/tickets/availability`` — what every stream offers them from where
  they are standing: a form, the stream's contact address, or nothing.
- ``POST /me/tickets`` — the filing itself. The body names its stream, and the
  stream decides what it means.

And the cases they filed, which they follow: the list, one case with what has
been said to them about it, and their answer. What a filer reads is decided by
the operations community's filer role (``app.db.operations_schema``), which these
routes read through.

A suspended account reaches these too, for one shape: it may appeal its
suspension, and follow and answer that appeal. Anything else it files or
answers is refused as every other route refuses it.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError

from app.api.deps import (
    TicketHolder,
    TicketHolderSessionDep,
    UploadUserDep,
    UserSessionDep,
    get_current_active_user,
)
from app.core.audit_events import AuditEventType
from app.core.intake import APPEAL, EvidencePolicy, IntakeStream, meta
from app.core.messages import (
    AppealMessages,
    AuthMessages,
    EvidenceMessages,
    FeedbackMessages,
    ModerationMessages,
    SecurityMessages,
    SupportMessages,
    TicketMessages,
)
from app.core.moderation import parse_target
from app.models.platform.user import User, UserStatus
from app.schemas.platform.ticket import (
    AppealTicketCreate,
    FeedbackTicketCreate,
    FiledTicketDetailRead,
    FiledTicketList,
    FiledTicketRead,
    ModerationTicketCreate,
    SecurityTicketCreate,
    StreamAvailabilityRead,
    SupportTicketCreate,
    TicketAccepted,
    TicketAvailability,
    TicketCreate,
    TicketMessageRead,
    TicketReplyCreate,
)
from app.schemas.tenant.evidence import EvidencePolicyRead, EvidenceRead
from app.services import audit as audit_service
from app.services.platform import appeals as appeals_service
from app.services.platform import disclosure as disclosure_service
from app.services.platform import evidence as evidence_service
from app.services.platform import feedback as feedback_service
from app.services.platform import tickets as tickets_service
from app.services.platform.intake import CaseCapReached
from app.services.tenant import moderation as moderation_service
from app.services.tenant import support as support_service

me_router = APIRouter(prefix="/tickets")

CurrentUser = Annotated[User, Depends(get_current_active_user)]


@me_router.get("/availability", response_model=TicketAvailability)
async def read_ticket_availability(
    session: UserSessionDep,
    current_user: CurrentUser,
    guild_id: Optional[int] = Query(
        default=None,
        description="The community the reader is standing in.",
        alias="community_id",
    ),
) -> TicketAvailability:
    """What each kind of ticket offers the reader from where they are.

    A form where there is somewhere to send it and they may; otherwise the
    kind's contact address; otherwise nothing. Asked by every surface that
    files one, so none of them decides it.
    """
    offered = await tickets_service.availability(
        session, user=current_user, guild_id=guild_id
    )
    return TicketAvailability(
        **{
            stream.value: StreamAvailabilityRead(
                mode=answer.mode,
                contact=answer.contact,
                types=list(answer.types),
                evidence=EvidencePolicyRead.of(meta(stream).evidence),
            )
            for stream, answer in offered.items()
        }
    )


_TICKET = TypeAdapter(TicketCreate)

#: How the filing is sent: the ticket as JSON in one part, and its files.
TICKET_PART_DESCRIPTION = (
    "The ticket, as JSON: a support request, a report, a security problem, "
    "feedback or an appeal, told apart by ``stream`` (and an appeal by its "
    "``type``)."
)


def _parse_ticket(raw: str) -> TicketCreate:
    try:
        return _TICKET.validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


async def _read_files(
    files: list[UploadFile], policy: EvidencePolicy
) -> list[evidence_service.PreparedEvidence]:
    """Read the files sent with a filing or an answer, held to ``policy``.

    Counted before anything is read, and each read no further than one byte
    past the largest a file may be.
    """
    from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded

    files = [f for f in files if f.filename or f.size]
    if not files:
        return []
    incoming: list[evidence_service.IncomingFile] = []
    try:
        if policy.max_files == 0:
            raise evidence_service.EvidenceRefused(EvidenceMessages.NOT_TAKEN)
        if len(files) > policy.max_files:
            raise evidence_service.EvidenceRefused(EvidenceMessages.TOO_MANY)
        for upload in files:
            try:
                data = await read_upload_bounded(upload, policy.max_bytes)
            except FileTooLargeError:
                raise evidence_service.EvidenceRefused(
                    EvidenceMessages.TOO_LARGE
                ) from None
            incoming.append(
                evidence_service.IncomingFile(filename=upload.filename, data=data)
            )
        # Reading a picture is work for a thread, not the event loop.
        return await asyncio.to_thread(evidence_service.prepare, incoming, policy)
    except evidence_service.EvidenceRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc


def _refuse_suspended() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.ACCOUNT_SUSPENDED
    )


@me_router.post("", response_model=TicketAccepted, status_code=status.HTTP_202_ACCEPTED)
async def file_ticket(
    session: TicketHolderSessionDep,
    current_user: TicketHolder,
    payload: Annotated[str, Form(description=TICKET_PART_DESCRIPTION)],
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006
) -> TicketAccepted:
    """File a ticket. One route, whatever kind and from wherever.

    Sent as ``multipart/form-data``: the ticket as JSON in ``payload``, and up
    to as many ``files`` as the stream takes (``/availability`` says how many,
    how large and of which types). The reply says that it arrived and nothing
    more: not who will read it, and for a report not whether one already
    existed. A suspended account may file an appeal and nothing else.
    """
    ticket = _parse_ticket(payload)
    appealing = isinstance(ticket, AppealTicketCreate)
    if current_user.status == UserStatus.suspended and not appealing:
        raise _refuse_suspended()
    stream = IntakeStream(ticket.stream)
    try:
        await tickets_service.hold_pace(current_user, stream)
    except tickets_service.FilingTooFast as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TicketMessages.FILING_TOO_FAST,
        ) from exc
    attached = await _read_files(
        files, meta(stream).evidence_for(APPEAL if appealing else None)
    )

    if isinstance(ticket, SupportTicketCreate):
        accepted = await _ask_for_help(current_user, ticket, attached)
    elif isinstance(ticket, SecurityTicketCreate):
        accepted = await _report_security_problem(current_user, ticket, attached)
    elif isinstance(ticket, FeedbackTicketCreate):
        accepted = await _send_feedback(current_user, ticket, attached)
    elif isinstance(ticket, AppealTicketCreate):
        accepted = await _appeal(current_user, ticket, attached)
    else:
        accepted = await _report(session, current_user, ticket, attached)
    if not isinstance(ticket, ModerationTicketCreate):
        # Which stream and what about; never what it said. A report is not
        # written here: one about a community is that community's business,
        # and its own log keeps it.
        topic = getattr(ticket, "type", None)
        audit_service.emit(
            event_type=AuditEventType.TICKET_FILED,
            actor_user_id=current_user.id,
            detail={
                "stream": stream.value,
                "topic": getattr(topic, "value", topic),
                "attachments": len(attached),
            },
        )
    return accepted


async def _send_feedback(
    sender: User,
    payload: FeedbackTicketCreate,
    attached: list[evidence_service.PreparedEvidence],
) -> TicketAccepted:
    try:
        await feedback_service.send(
            sender=sender,
            topic=payload.type,
            body=payload.body,
            contactable=payload.contactable,
            context=payload.context,
            evidence=attached,
        )
    except feedback_service.NowhereToSend as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=FeedbackMessages.NOWHERE_TO_SEND,
        ) from exc
    return TicketAccepted()


async def _appeal(
    account: User,
    payload: AppealTicketCreate,
    attached: list[evidence_service.PreparedEvidence],
) -> TicketAccepted:
    try:
        await appeals_service.appeal(
            account=account, body=payload.body, evidence=attached
        )
    except appeals_service.NotSuspended as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AppealMessages.NOT_SUSPENDED,
        ) from exc
    except CaseCapReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TicketMessages.TOO_MANY_OPEN,
        ) from exc
    except appeals_service.NowhereToSend as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppealMessages.NOWHERE_TO_SEND,
        ) from exc
    return TicketAccepted()


async def _report_security_problem(
    filer: User,
    payload: SecurityTicketCreate,
    attached: list[evidence_service.PreparedEvidence],
) -> TicketAccepted:
    try:
        await disclosure_service.report(
            filer=filer,
            topic=payload.type,
            subject=payload.subject,
            body=payload.body,
            evidence=attached,
        )
    except CaseCapReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TicketMessages.TOO_MANY_OPEN,
        ) from exc
    except disclosure_service.NowhereToSend as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SecurityMessages.NOWHERE_TO_SEND,
        ) from exc
    return TicketAccepted()


async def _ask_for_help(
    requester: User,
    payload: SupportTicketCreate,
    attached: list[evidence_service.PreparedEvidence],
) -> TicketAccepted:
    try:
        await support_service.request_help(
            guild_id=payload.community_id,
            requester=requester,
            subject=payload.subject,
            body=payload.body,
            topic=payload.type,
            evidence=attached,
        )
    except support_service.SupportUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SupportMessages.NOT_AVAILABLE,
        ) from exc
    except CaseCapReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TicketMessages.TOO_MANY_OPEN,
        ) from exc
    except support_service.NowhereToSend as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SupportMessages.NOWHERE_TO_SEND,
        ) from exc
    return TicketAccepted()


async def _report(
    session: UserSessionDep,
    reporter: User,
    payload: ModerationTicketCreate,
    attached: list[evidence_service.PreparedEvidence],
) -> TicketAccepted:
    try:
        target = parse_target(payload.target_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ModerationMessages.UNKNOWN_TARGET_TYPE,
        ) from None

    filed = await moderation_service.file_report(
        session,
        reporter=reporter,
        target=target,
        target_id=payload.target_id,
        reason=payload.reason,
        detail=payload.detail,
        guild_id=payload.community_id,
        evidence=attached,
        legal_basis=payload.legal_basis,
    )
    return TicketAccepted(venue=filed.venue, platform_contact=filed.platform_contact)


def _filed(ticket: tickets_service.FiledTicket) -> FiledTicketRead:
    return FiledTicketRead(
        task_id=ticket.task_id,
        stream=ticket.stream,
        topic=ticket.topic,
        subject=ticket.subject,
        state=ticket.state,
        opened_at=ticket.opened_at,
        updated_at=ticket.updated_at,
    )


@me_router.get("", response_model=FiledTicketList)
async def list_filed_tickets(current_user: TicketHolder) -> FiledTicketList:
    """The cases the reader filed, most recently moved first."""
    filed = await tickets_service.list_filed(current_user)
    return FiledTicketList(items=[_filed(ticket) for ticket in filed])


@me_router.get("/{task_id}", response_model=FiledTicketDetailRead)
async def read_filed_ticket(
    task_id: int, current_user: TicketHolder
) -> FiledTicketDetailRead:
    """One case the reader filed, with what has been said to them about it.

    A case that is not theirs answers exactly as one that does not exist.
    """
    try:
        detail = await tickets_service.read_filed(current_user, task_id)
    except tickets_service.TicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=TicketMessages.NOT_FOUND,
        ) from exc
    return FiledTicketDetailRead(
        **_filed(detail.ticket).model_dump(),
        conversation=detail.conversation,
        can_reply=detail.can_reply,
        evidence=EvidencePolicyRead.of(
            meta(detail.ticket.stream).evidence_for(detail.ticket.topic)
        ),
        messages=[
            TicketMessageRead(
                id=message.id,
                mine=message.mine,
                content=message.content,
                created_at=message.created_at,
                attachments=[
                    EvidenceRead.model_validate(attachment, from_attributes=True)
                    for attachment in message.attachments
                ],
            )
            for message in detail.messages
        ],
    )


@me_router.post(
    "/{task_id}/replies",
    response_model=FiledTicketDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def reply_to_filed_ticket(
    task_id: int,
    body: Annotated[str, Form()],
    current_user: TicketHolder,
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006
) -> FiledTicketDetailRead:
    """Answer on a case the reader filed. Returns the case as it now stands.

    Sent as ``multipart/form-data``: the answer in ``body``, and any ``files``
    the stream takes. Paced like a filing into the case's stream: each answer
    is something a person reads. A suspended account answers on its appeal
    alone.
    """
    try:
        answer = TicketReplyCreate(body=body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    try:
        detail = await tickets_service.read_filed(current_user, task_id)
        if (
            current_user.status == UserStatus.suspended
            and detail.ticket.topic != APPEAL
        ):
            raise _refuse_suspended()
        await tickets_service.hold_pace(current_user, detail.ticket.stream)
        attached = await _read_files(
            files, meta(detail.ticket.stream).evidence_for(detail.ticket.topic)
        )
        await tickets_service.reply(current_user, detail, answer.body, attached)
        audit_service.emit(
            event_type=AuditEventType.TICKET_REPLIED,
            actor_user_id=current_user.id,
            target_type="task",
            target_id=task_id,
            detail={
                "stream": detail.ticket.stream.value,
                "attachments": len(attached),
            },
        )
    except tickets_service.TicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=TicketMessages.NOT_FOUND,
        ) from exc
    except tickets_service.FilingTooFast as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TicketMessages.FILING_TOO_FAST,
        ) from exc
    except tickets_service.ReplyRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TicketMessages.REPLY_NOT_TAKEN,
        ) from exc
    return await read_filed_ticket(task_id, current_user)


@me_router.get("/{task_id}/evidence/{evidence_id}", include_in_schema=False)
async def read_filed_evidence(
    task_id: int,
    evidence_id: int,
    current_user: UploadUserDep,
):
    """One file the reader sent with a case they filed, opened.

    Only their own: what they sent. Served without a header, so a page can
    show a picture by address alone.
    """
    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.session import set_rls_context

    try:
        guild_id = await tickets_service.filed_evidence(
            current_user, task_id, evidence_id
        )
    except tickets_service.TicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=EvidenceMessages.NOT_FOUND,
        ) from exc
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        obj = await evidence_service.sealed(session, evidence_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=EvidenceMessages.NOT_FOUND
        )
    audit_service.emit(
        event_type=AuditEventType.EVIDENCE_ACCESSED,
        actor_user_id=int(current_user.id),
        guild_id=guild_id,
        target_type="evidence",
        target_id=evidence_id,
        detail={"as": "filer", "task_id": task_id},
    )
    return evidence_service.serve(guild_id, obj)
