"""A community's moderation surface.

**Whoever already sees everything in an initiative** reads and settles that
initiative's reports. Not a role name — the standing is
``override_share_restrictions`` ("Full access"), which is what the RLS policy on
these tables keys on too, so the endpoint and the database agree without the
endpoint re-deciding.

Reports are filed as tickets (``POST /me/tickets``, see
``app.api.v1.platform_endpoints.tickets``), the one way any kind of ticket is
filed; where a report goes is decided server-side.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.messages import ModerationMessages
from app.core.moderation import LegalBasis, ModerationAct, RemovalReason
from app.db.query import build_paginated_response
from app.models.platform.user import User
from app.models.tenant.moderation import ModerationAction
from app.schemas.tenant.evidence import EvidenceRead
from app.schemas.tenant.moderation import (
    InitiativeSharingRead,
    ModerationActCreate,
    ModerationActionRead,
    ModerationLogList,
    ModerationPerson,
    ModerationReportList,
    ModerationReportRead,
    ModerationRestore,
    ReportSettle,
    ReportTargetLink,
    SharedResourceRead,
)
from app.services.platform import evidence as evidence_service
from app.services.platform import grant_cases
from app.services.platform.holds import HoldWhy
from app.services.tenant import moderation as moderation_service
from app.services.tenant import moderation_acts, sharing_overview

router = APIRouter()


def _read(
    report,
    reporter_count: int,
    details: list[str],
    preview: moderation_service.TargetPreview | None = None,
    evidence: list | None = None,
) -> ModerationReportRead:
    return ModerationReportRead(
        id=report.id,
        initiative_id=report.initiative_id,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        reported_at=report.reported_at,
        reporter_count=reporter_count,
        details=details,
        outcome=report.outcome,
        note=report.note,
        decided_by=report.decided_by,
        decided_at=report.decided_at,
        # Absent where the target is gone or out of this reader's reach; the
        # report still stands, and the client says so rather than drawing a
        # link to nothing.
        target_excerpt=preview.excerpt if preview else None,
        target_link=(
            ReportTargetLink(
                entity_type=preview.location.entity_type,
                entity_id=preview.location.entity_id,
                tool=preview.location.tool,
                tool_id=preview.location.tool_id,
            )
            if preview and preview.location
            else None
        ),
        evidence=[
            EvidenceRead.model_validate(item, from_attributes=True)
            for item in evidence or ()
        ],
        legal_basis=LegalBasis(report.legal_basis) if report.legal_basis else None,
        platform_notified_at=report.platform_notified_at,
        action_id=report.action_id,
    )


@router.get("/initiatives/{initiative_id}/reports", response_model=ModerationReportList)
async def list_reports(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    settled: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ModerationReportList:
    """This initiative's reports.

    No capability check here: the tables carry RLS that admits exactly the
    people who already see everything in the initiative, plus the guild admin.
    A reader who is not one of them gets an empty list, the same way they get
    404 for any content they are not in.
    """
    rows, total_count, actual_page = await moderation_service.list_reports(
        session,
        initiative_id=initiative_id,
        settled=settled,
        page=page,
        page_size=page_size,
    )
    # One lookup for the page rather than one per card: a moderator deciding
    # from a list should not have to open each item to find out what it says.
    previews = await moderation_service.target_previews(
        session,
        [report for report, _, _ in rows],
    )
    attached = await evidence_service.listed(
        session, report_ids=[report.id for report, _, _ in rows]
    )
    return ModerationReportList(
        **build_paginated_response(
            [
                _read(
                    report,
                    count,
                    details,
                    previews.get(report.id),
                    attached.get(("report", report.id)),
                )
                for report, count, details in rows
            ],
            total_count,
            actual_page,
            page_size,
        )
    )


@router.post("/reports/{report_id}/settle", response_model=ModerationReportRead)
async def settle_report(
    report_id: int,
    payload: ReportSettle,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ModerationReportRead:
    """Settle a report. Every outcome closes it.

    ``content_removed`` takes the reported thing down, and ``member_warned``
    tells whoever wrote it ``message``; both are written to the moderation
    log. ``escalated`` opens a platform case carrying the references — the
    one crossing between a community's reports and the operator's, in one
    direction. ``held`` does the same and holds the reported thing where it
    is, out of the whole community's sight, until the platform releases it;
    ``hold`` says why.
    """
    report = await moderation_service.settle_report(
        session,
        report_id=report_id,
        outcome=payload.outcome,
        note=payload.note,
        decided_by=current_user.id,
        guild_id=guild_context.guild_id,
        context=guild_context,
        hold=(
            HoldWhy(
                reason=payload.hold.reason,
                legal_basis=payload.hold.legal_basis,
                note=payload.hold.note,
            )
            if payload.hold is not None
            else None
        ),
        removal_reason=payload.removal_reason,
        message=(payload.message or "").strip() or None,
    )
    await grant_cases.note_act(
        guild_context,
        f"Settled report {report.id} in community #{guild_context.guild_id} as "
        f"{payload.outcome.value.replace('_', ' ')}.",
    )
    # The same reporter figures the list carries: a settled report is the same
    # shape as an open one, and answering zero would have the page replace what
    # it already had with nothing.
    counts, details = await moderation_service.reporters_for(session, [report.id])
    previews = await moderation_service.target_previews(
        session,
        [report],
    )
    attached = await evidence_service.listed(session, report_ids=[report.id])
    return _read(
        report,
        counts.get(report.id, 0),
        details.get(report.id, []),
        previews.get(report.id),
        attached.get(("report", report.id)),
    )


@router.get(
    "/initiatives/{initiative_id}/sharing", response_model=InitiativeSharingRead
)
async def read_initiative_sharing(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
) -> InitiativeSharingRead:
    """Who can reach what, across this initiative.

    Gated here rather than by the tables: ``resource_grants`` is scoped to
    initiative *membership*, which is right for reading the grants on a
    resource you can already reach and too wide for an aggregate over every
    resource in the initiative. The standing required is the one the moderation
    tables admit — "Full access", or guild admin — read from the standing the
    seam computed for this request.
    """
    if not (guild_context.overrides_sharing(initiative_id) or guild_context.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ModerationMessages.NOT_A_MODERATOR,
        )
    items = await sharing_overview.initiative_sharing(
        session, initiative_id=initiative_id
    )
    return InitiativeSharingRead(
        items=[
            SharedResourceRead(
                resource_type=item.resource_type,
                resource_id=item.resource_id,
                name=item.name,
                all_initiative_members=item.all_initiative_members,
                user_grant_count=item.user_grant_count,
                role_grant_count=item.role_grant_count,
            )
            for item in items
        ]
    )


async def _people(session: AsyncSession, ids: set[int]) -> dict[int, ModerationPerson]:
    """Who the log names, as the community knows them."""
    from sqlmodel import select

    from app.core.user_display import display_name
    from app.models.platform.user_profile_view import MemberProfile

    if not ids:
        return {}
    rows = (
        await session.exec(select(MemberProfile).where(MemberProfile.id.in_(ids)))
    ).all()
    return {row.id: ModerationPerson(id=row.id, name=display_name(row)) for row in rows}


def _logged(
    entry: moderation_acts.LogEntry, people: dict[int, ModerationPerson]
) -> ModerationActionRead:
    action = entry.action
    return ModerationActionRead(
        id=int(action.id),  # type: ignore[arg-type]
        initiative_id=action.initiative_id,
        action=ModerationAct(action.action),
        target_type=action.target_type,
        target_id=action.target_id,
        reason=RemovalReason(action.reason) if action.reason else None,
        note=action.note,
        snapshot=entry.snapshot,
        actor=people.get(action.created_by) if action.created_by else None,
        subject=(
            people.get(action.subject_user_id) if action.subject_user_id else None
        ),
        report_id=action.report_id,
        hold_id=action.hold_id,
        created_at=action.created_at,
        restorable=entry.restorable,
    )


async def _one(session: AsyncSession, action: ModerationAction) -> ModerationActionRead:
    entry = moderation_acts.LogEntry(
        action=action,
        snapshot=moderation_acts.open_snapshot(action),
        restorable=action.action == ModerationAct.remove.value,
    )
    ids = {i for i in (action.created_by, action.subject_user_id) if i is not None}
    return _logged(entry, await _people(session, ids))


@router.post(
    "/moderation/acts",
    response_model=ModerationActionRead,
    status_code=status.HTTP_201_CREATED,
)
async def moderate(
    payload: ModerationActCreate,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ModerationActionRead:
    """Act on something as a moderator of its initiative: ``remove`` it (a
    comment to a tombstone, anything else to the trash), lock or unlock its
    thread, clear its reactions, or ``warn`` whoever wrote it. Written to the
    initiative's moderation log."""
    action = await moderation_acts.act(
        session,
        guild_context,
        guild_id=guild_context.guild_id,
        actor_id=current_user.id,
        request=moderation_acts.ActRequest(
            act=payload.act,
            target_type=payload.target_type,
            target_id=payload.target_id,
            reason=payload.reason,
            note=payload.note,
        ),
    )
    await grant_cases.note_act(
        guild_context,
        f"{payload.act.value.replace('_', ' ').capitalize()}: {payload.target_type} "
        f"{payload.target_id} in community #{guild_context.guild_id}"
        + (f", for {payload.reason.value}" if payload.reason else "")
        + f" (moderation act {action.id}).",
    )
    return await _one(session, action)


@router.post(
    "/moderation/acts/{action_id}/restore", response_model=ModerationActionRead
)
async def restore_removal(
    action_id: int,
    payload: ModerationRestore,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ModerationActionRead:
    """Put back what removal ``action_id`` took down: a comment's words where
    they were, anything else out of the trash."""
    action = await moderation_acts.restore(
        session,
        guild_context,
        guild_id=guild_context.guild_id,
        actor_id=current_user.id,
        action_id=action_id,
        note=payload.note,
    )
    await grant_cases.note_act(
        guild_context,
        f"Put back what moderation act {action_id} removed, in community "
        f"#{guild_context.guild_id}.",
    )
    read = await _one(session, action)
    read.restorable = False
    return read


@router.get(
    "/initiatives/{initiative_id}/moderation/log", response_model=ModerationLogList
)
async def read_moderation_log(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ModerationLogList:
    """What this initiative's moderators have done, newest first.

    Read through the log's own row policy, which admits the initiative's
    moderation set: anyone else is told so rather than shown an empty log.
    """
    if not moderation_acts.may_moderate(guild_context, initiative_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ModerationMessages.NOT_A_MODERATOR,
        )
    entries, total, actual_page = await moderation_acts.log(
        session, initiative_id=initiative_id, page=page, page_size=page_size
    )
    ids = {
        i
        for entry in entries
        for i in (entry.action.created_by, entry.action.subject_user_id)
        if i is not None
    }
    people = await _people(session, ids)
    return ModerationLogList(
        **build_paginated_response(
            [_logged(entry, people) for entry in entries],
            total,
            actual_page,
            page_size,
        )
    )
