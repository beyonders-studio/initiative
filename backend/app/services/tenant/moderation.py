"""Filing a report, and settling one.

Where a report goes is not the client's decision. This resolves the target,
derives the venue from the registry the RLS policies are rendered from, and
sends it to one of two places:

- **platform** — an intake case in the operations guild, which is project work
  our own staff triage and assign;
- **initiative** — a row in that community, which its moderators look at and
  decide.

A reporter gains nothing by reporting: the write happens on a routed system
session, and reading the report stays with the people who already see
everything in that initiative.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

from fastapi import HTTPException, status as http_status
from sqlalchemy import Table, select as sa_select, text, tuple_
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.intake import IntakeStream
from app.core.messages import HoldMessages, ModerationMessages
from app.core.moderation import (
    PLATFORM_TARGET_RELATION,
    LegalBasis,
    ModerationAct,
    PlatformReportTarget,
    RemovalReason,
    ReportOutcome,
    ReportReason,
    ReportVenue,
    removal_reason_for,
    target_table,
    venue_for,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.query import paginated_query
from app.db.session import set_rls_context
from app.models.platform import user_profile_view
from app.models.platform.user import User
from app.models.tenant.moderation import ModerationReport, ModerationReportReporter
from app.models.tenant.search_entry import SearchEntry
from app.services import audit as audit_service
from app.services.platform import evidence as evidence_service
from app.services.platform.intake import CaseFiler, CaseOutcome, CaseRefs, open_case
from app.db.request_context import SystemGuild

if TYPE_CHECKING:
    from app.db.guild_standing import GuildContext
    from app.services.platform.evidence import PreparedEvidence
    from app.services.platform.holds import HoldWhy

logger = logging.getLogger(__name__)


class ReportFiled:
    """What filing a report did. Deliberately tells the reporter nothing else
    — but, for an ``illegal`` report the platform takes no cases about, where
    to tell whoever runs this server themselves."""

    __slots__ = ("venue", "platform_contact")

    def __init__(
        self, venue: ReportVenue, platform_contact: Optional[str] = None
    ) -> None:
        self.venue = venue
        self.platform_contact = platform_contact


def _refuse(code: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=code)


def check_report(
    *,
    reason: ReportReason,
    detail: Optional[str],
    legal_basis: Optional[LegalBasis],
    attached: int,
) -> None:
    """What a report must say for its reason. An ``illegal`` one names the
    law and says what is wrong, and an ``other`` one says what is wrong. A
    child-safety one names where the material is and carries none of it."""
    said = bool((detail or "").strip())
    if reason is ReportReason.illegal:
        if legal_basis is None:
            raise _refuse(ModerationMessages.LEGAL_BASIS_REQUIRED)
        if not said:
            raise _refuse(ModerationMessages.DETAIL_REQUIRED)
        if legal_basis is LegalBasis.child_safety and attached:
            raise _refuse(ModerationMessages.NO_ATTACHMENTS)
    elif legal_basis is not None:
        raise _refuse(ModerationMessages.LEGAL_BASIS_NOT_TAKEN)
    if reason is ReportReason.other and not said:
        raise _refuse(ModerationMessages.DETAIL_REQUIRED)


def public_relation(name: str) -> Table:
    """The table object for a relation ``PLATFORM_TARGET_RELATION`` names.

    Two registries are asked in turn because ``user_profiles`` is a view, and a
    view deliberately keeps its own metadata rather than sitting among the
    models. Asking both is what keeps this from being a second list saying
    which relation is which. ``moderation_test`` resolves every entry, so a
    target added later cannot name a relation that is not there.
    """
    view = user_profile_view.metadata.tables.get(f"public.{name}")
    return view if view is not None else SQLModel.metadata.tables[name]


async def _resolve_initiative(
    session: AsyncSession, target: SearchEntityType, target_id: int
) -> Optional[int]:
    """The initiative a community target belongs to, or ``None``.

    The initiative is read with the expression
    ``app.db.initiative_rls.INITIATIVE_PATHS`` already declares for that table —
    the same declaration the table's policies are rendered from, so a target's
    venue and its access gate cannot answer differently.

    Runs on the reporter's own session, so what they can see decides what
    resolves. It reads **ids only**.

    The query is built from the table's own column objects and one bound id —
    the shape ``app.db.reference_targets`` already uses to ask the registry the
    same question — so the only text in it is the registry's own expression.
    """
    from app.db.initiative_rls import INITIATIVE_PATHS

    table_name = target_table(target)
    path = INITIATIVE_PATHS.get(table_name)
    relation = SQLModel.metadata.tables.get(table_name)
    if path is None or relation is None:
        return None

    row = (
        await session.exec(
            sa_select(text(path.initiative_expr(table_name)))
            .select_from(relation)
            .where(relation.c["id"] == target_id)
        )
    ).first()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def file_report(
    reporter_session: AsyncSession,
    *,
    reporter: "User",
    target: SearchEntityType | PlatformReportTarget,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    guild_id: Optional[int] = None,
    evidence: Sequence["PreparedEvidence"] = (),
    now: Optional[datetime] = None,
    legal_basis: Optional[LegalBasis] = None,
) -> ReportFiled:
    """Route one report to whoever handles that kind of thing.

    The target is resolved as the reporter — a platform target on
    ``reporter_session``, their own platform session, and a community target
    on a session of theirs from that community's cohort — so a person can only
    report something they can already see, and the database is what decides
    that rather than a check here. ``guild_id`` says which community they were
    standing in; it is validated as theirs before it is used, and it decides
    nothing about the venue. ``evidence`` is stored with the report wherever
    it lands: on the community's report, or on the operations case.

    An ``illegal`` report about community content goes to **both**: the
    community's moderators get it as any report, and the platform opens a case
    of its own, which the reporter follows from their tickets. Where the
    platform takes no moderation cases, the reply says who to tell instead.
    """
    check_report(
        reason=reason, detail=detail, legal_basis=legal_basis, attached=len(evidence)
    )
    moment = now or datetime.now(timezone.utc)
    venue = venue_for(target)

    if venue is ReportVenue.initiative:
        assert isinstance(target, SearchEntityType)
        located = await _locate_as_reporter(
            reporter=reporter,
            target=target,
            target_id=target_id,
            guild_id=guild_id,
        )
        if located is not None:
            report_id = await _place_in_initiative(
                guild_id=located[0],
                initiative_id=located[1],
                reporter_id=reporter.id,
                target=target,
                target_id=target_id,
                reason=reason,
                detail=detail,
                moment=moment,
                evidence=evidence,
                legal_basis=legal_basis,
            )
            contact = None
            if reason is ReportReason.illegal:
                contact = await _tell_the_platform(
                    reporter_session,
                    guild_id=located[0],
                    report_id=report_id,
                    reporter_id=reporter.id,
                    target=target,
                    target_id=target_id,
                    detail=detail,
                    legal_basis=legal_basis,
                    moment=moment,
                    evidence=evidence,
                )
            return ReportFiled(ReportVenue.initiative, platform_contact=contact)
        # Nothing in the community answers to that id for this reader, and a
        # report names only something its reporter can see.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=ModerationMessages.TARGET_NOT_FOUND,
        )

    if isinstance(target, PlatformReportTarget) and not await _platform_target_visible(
        reporter_session, target, target_id
    ):
        # Checked before it becomes somebody's work, so no operations task
        # names something the reporter could not see. Refused the same way
        # whether the row is hidden from them or not there at all.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=ModerationMessages.TARGET_NOT_FOUND,
        )

    opened = await _open_platform_case(
        target=target,
        target_id=target_id,
        reason=reason,
        detail=detail,
        moment=moment,
        note=(
            await _listing_note(reporter_session, target_id)
            if target is PlatformReportTarget.marketplace_listing
            else None
        ),
        evidence=evidence,
        evidence_by=reporter.id,
        legal_basis=legal_basis,
    )
    if opened is None:
        # Nothing is bound to receive it. Say so rather than answering 202 to
        # a report that reached nobody.
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ModerationMessages.NOWHERE_TO_SEND,
        )
    return ReportFiled(ReportVenue.platform)


async def _place_in_initiative(
    *,
    guild_id: int,
    initiative_id: int,
    reporter_id: int,
    target: SearchEntityType,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    moment: datetime,
    evidence: Sequence["PreparedEvidence"] = (),
    legal_basis: Optional[LegalBasis] = None,
) -> int:
    """Open or join the community's report for this target, and return its
    id.

    Its own system session from the community's cohort, routed as the guild
    admin: the row belongs to the initiative's moderators, and the reporter
    must not be able to read it back.
    """
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        # Two people reporting the same thing in the same instant both look for
        # an open row before either writes one. They queue here instead, so the
        # second joins the first rather than losing the unique index. Held for
        # the rest of the transaction; the guild id is part of the key
        # because advisory locks span the database where a schema is per-guild.
        await advisory_lock(
            session,
            LockNamespace.MODERATION_REPORT,
            f"{guild_id}:{initiative_id}:{target.value}:{target_id}",
        )
        existing = (
            await session.exec(
                select(ModerationReport)
                .where(ModerationReport.initiative_id == initiative_id)
                .where(ModerationReport.target_type == target.value)
                .where(ModerationReport.target_id == target_id)
                .where(ModerationReport.outcome.is_(None))
                .execution_options(populate_existing=True)
            )
        ).first()

        if existing is None:
            existing = ModerationReport(
                initiative_id=initiative_id,
                target_type=target.value,
                target_id=target_id,
                reason=reason,
                reported_at=moment,
                legal_basis=legal_basis.value if legal_basis else None,
            )
            session.add(existing)
            await session.flush()
        elif reason is ReportReason.illegal and (
            existing.reason != ReportReason.illegal or existing.legal_basis is None
        ):
            # The gravest reason wins: an open report somebody has now called
            # illegal is one, and carries the law they named.
            existing.reason = ReportReason.illegal
            existing.legal_basis = existing.legal_basis or (
                legal_basis.value if legal_basis else None
            )
            session.add(existing)
            await session.flush()

        already = (
            await session.exec(
                select(ModerationReportReporter.id)
                .where(ModerationReportReporter.report_id == existing.id)
                .where(ModerationReportReporter.reporter_id == reporter_id)
            )
        ).first()
        if already is None:
            session.add(
                ModerationReportReporter(
                    report_id=existing.id,
                    reporter_id=reporter_id,
                    reported_at=moment,
                    detail=detail,
                )
            )
        report_id = int(existing.id)  # type: ignore[arg-type]
        with evidence_service.Sealing(guild_id) as sealing:
            sealing.store(
                session,
                prepared=evidence,
                created_by=reporter_id,
                report_id=report_id,
            )
            await session.commit()
            sealing.keep()
    return report_id


async def _tell_the_platform(
    reporter_session: AsyncSession,
    *,
    guild_id: int,
    report_id: int,
    reporter_id: int,
    target: SearchEntityType,
    target_id: int,
    detail: Optional[str],
    legal_basis: Optional[LegalBasis],
    moment: datetime,
    evidence: Sequence["PreparedEvidence"],
) -> Optional[str]:
    """Open the platform's case about an ``illegal`` report beside the
    community's, with the reporter following it, and mark the community's
    report as one the platform was told about. Returns the address to tell
    the platform at instead, where it takes no moderation cases.

    A child-safety case opens asking for a hold: the material is kept where
    it is, never copied, and only the platform under a grant may hold it if
    the community has not.
    """
    from app.core.intake import IntakeStream as _Stream
    from app.services.platform import case_activity
    from app.services.platform.intake import configured_operations_guild_id
    from app.services.platform.intake import contact_for

    opened = await _open_platform_case(
        target=target,
        target_id=target_id,
        reason=ReportReason.illegal,
        detail=detail,
        moment=moment,
        guild_id=guild_id,
        evidence=evidence,
        evidence_by=reporter_id,
        legal_basis=legal_basis,
        filer=CaseFiler(user_id=reporter_id, subject=None, words=detail or ""),
    )
    if opened is None:
        return await contact_for(reporter_session, _Stream.moderation)

    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        report = (
            await session.exec(
                select(ModerationReport)
                .where(ModerationReport.id == report_id)
                .with_for_update()
            )
        ).one()
        if report.platform_case_id is None:
            report.platform_case_id = opened.task_id
            report.platform_notified_at = moment
            session.add(report)
            await session.commit()

    if legal_basis is LegalBasis.child_safety:
        # Asked once per case, whichever report brought child safety to it:
        # the case may have been opened by a report naming another law.
        from app.models.tenant.comment import Comment

        operations = await configured_operations_guild_id()
        if operations is not None:
            async with cohorts.system_session(operations) as ops:
                await set_rls_context(ops, SystemGuild(operations))
                asked = (
                    await ops.exec(
                        select(Comment.id)
                        .where(Comment.task_id == opened.task_id)
                        .where(
                            Comment.system_kind
                            == case_activity.ActivityKind.hold_requested.value
                        )
                    )
                ).first()
                if asked is not None:
                    return None
                await case_activity.post(
                    ops,
                    task_id=opened.task_id,
                    kind=case_activity.ActivityKind.hold_requested,
                    text=(
                        f"Child safety: hold {target.value} {target_id} in community "
                        f"{guild_id} where it is, under a moderate grant, unless "
                        "the community has held it already. Never copy it."
                    ),
                )
                await ops.commit()
    return None


#: Identity targets whose id names an account. For these the case's subject is
#: the account itself, not the thing it hangs off.
_ACCOUNT_TARGETS = frozenset(
    {
        PlatformReportTarget.user_profile,
        PlatformReportTarget.username,
        PlatformReportTarget.avatar,
        PlatformReportTarget.decoration,
    }
)

#: Identity targets whose id names a community. For these the case is about
#: that community.
_GUILD_TARGETS = frozenset(
    {
        PlatformReportTarget.guild,
        PlatformReportTarget.directory_listing,
    }
)


async def _locate_as_reporter(
    *,
    reporter: "User",
    target: SearchEntityType,
    target_id: int,
    guild_id: Optional[int],
) -> Optional[tuple[int, int]]:
    """``(guild_id, initiative_id)`` for a target this reporter can see.

    On a request session from the community's cohort, routed as the reporter
    through the ordinary entry point, so membership, the auth policy and every
    gate apply exactly as they do on a read. A row the reporter cannot see
    resolves to nothing, and so does an id that names a different row in a
    community they merely claimed to be in — ids are unique only within a
    schema.
    """
    if guild_id is None:
        return None
    from app.api.deps import GuildAccessError, establish_guild_access

    async with cohorts.request_sessionmaker(guild_id)() as session:
        account = await session.merge(reporter, load=False)
        try:
            await establish_guild_access(session, account, guild_id)
        except GuildAccessError:
            return None
        initiative_id = await _resolve_initiative(session, target, target_id)
    return None if initiative_id is None else (guild_id, initiative_id)


async def _platform_target_visible(
    reporter_session: AsyncSession,
    target: PlatformReportTarget,
    target_id: int,
) -> bool:
    """Whether this reporter can see the platform target they named.

    Asked on their own session, against the relation that already serves the
    thing publicly (``PLATFORM_TARGET_RELATION``) — so a row they may not see
    and a row that is not there answer identically, and reporting reaches
    exactly as far as looking does. The community half works the same way.
    """
    relation = public_relation(PLATFORM_TARGET_RELATION[target])
    stmt = sa_select(relation.c["id"]).where(relation.c["id"] == target_id)
    if target is PlatformReportTarget.directory_listing:
        stmt = stmt.where(relation.c["is_community"].is_(True))
    return (await reporter_session.exec(stmt)).first() is not None


async def _listing_note(session: AsyncSession, listing_id: int) -> Optional[str]:
    """Which listing a report names, in the words the catalog uses.

    A listing's row id means nothing to the person triaging the case, so the
    case carries its public id, publisher and where it came from.
    """
    relation = public_relation(
        PLATFORM_TARGET_RELATION[PlatformReportTarget.marketplace_listing]
    )
    row = (
        await session.exec(
            sa_select(
                relation.c["public_id"],
                relation.c["uid"],
                relation.c["publisher"],
                relation.c["source"],
            ).where(relation.c["id"] == listing_id)
        )
    ).first()
    if row is None:
        return None
    public_id, uid, publisher, source = row
    return f"Listing: {public_id} (uid {uid})\nPublisher: {publisher}\nSource: {source}"


async def _open_platform_case(
    *,
    target: SearchEntityType | PlatformReportTarget,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    moment: datetime,
    note: Optional[str] = None,
    reporters: tuple[tuple[int, Optional[str]], ...] = (),
    guild_id: Optional[int] = None,
    evidence: Sequence["PreparedEvidence"] = (),
    evidence_by: Optional[int] = None,
    legal_basis: Optional[LegalBasis] = None,
    filer: Optional[CaseFiler] = None,
) -> Optional[CaseOutcome]:
    """File the report as an intake case in the operations guild.

    Returns the case, or ``None`` where none opened. ``open_case`` answers ``None`` on
    a deployment that has bound no moderation project — which is every fresh
    install — and a report that opened nothing has not been received.

    ``reporters`` — each reporter's id and their own words — are carried only
    on an escalation, where judging whether a report was made in good faith is
    the platform's job and the reporters are not somebody's neighbours. An
    ordinary platform report carries none: who said it adds nothing to a
    complaint about a username.
    """
    parts = [part for part in (detail, note) if part]
    if reporters:
        listed = ", ".join(str(reporter_id) for reporter_id, _ in reporters)
        parts.append(f"Reported by account(s): {listed}")
        said = [
            f"Account {reporter_id}: {words}"
            for reporter_id, words in reporters
            if words
        ]
        if said:
            parts.append("What they said:\n\n" + "\n\n".join(said))
    outcome = await open_case(
        IntakeStream.moderation,
        title=f"Reported {target.value} {target_id} ({reason.value})",
        body="\n\n".join(parts) or None,
        # A second report of an open case brings somebody's own words.
        detail="\n\n".join(parts) or None,
        refs=CaseRefs(
            # The subject is who or what was reported — never the reporter.
            subject_user=target_id if target in _ACCOUNT_TARGETS else None,
            subject_guild=(target_id if target in _GUILD_TARGETS else guild_id),
            resource_type=target.value,
            resource_id=target_id,
            reported_at=moment,
            severity=reason.value,
            legal_basis=legal_basis.value if legal_basis else None,
        ),
        # Content ids are numbered per community, so its community is part
        # of what names it.
        dedupe_key=(
            f"report:{guild_id}:{target.value}:{target_id}"
            if guild_id is not None
            else f"report:{target.value}:{target_id}"
        ),
        evidence=evidence,
        evidence_by=evidence_by,
        filer=filer,
    )
    return outcome


async def settle_report(
    session: AsyncSession,
    *,
    report_id: int,
    outcome: ReportOutcome,
    note: Optional[str],
    decided_by: int,
    guild_id: int,
    now: Optional[datetime] = None,
    context: Optional["GuildContext"] = None,
    hold: Optional["HoldWhy"] = None,
    removal_reason: Optional[RemovalReason] = None,
    message: Optional[str] = None,
) -> ModerationReport:
    """Close a community report. Every outcome closes it, and the ones that
    say something was done do it.

    The session must already be routed into the guild; RLS is what decides
    whether this reader may see the row at all. ``context`` is the reader's
    standing, which decides whether they may act on the reported thing.

    - ``content_removed`` takes it down (``moderation_acts``), for
      ``removal_reason`` or else the reason it was reported for.
    - ``member_warned`` tells whoever wrote it ``message``. Never who
      reported it, or how many did.
    - ``escalated`` and ``held`` both hand the report to the platform as a
      case. ``held`` also holds the reported thing where it is, worked on that
      case (``app.services.platform.holds``): ``hold`` says why.

    A report the platform was told about as well notes on the platform's case
    how the community settled it.
    """
    moment = now or datetime.now(timezone.utc)
    # Locked before it is read, so two moderators deciding at once resolve in
    # order: the second finds it settled rather than overwriting the first's
    # outcome, note and name. Not a key lock: the log row an act writes names
    # this report, from a transaction of its own.
    report = (
        await session.exec(
            select(ModerationReport)
            .where(ModerationReport.id == report_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if report is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=ModerationMessages.REPORT_NOT_FOUND,
        )
    if report.outcome is not None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=ModerationMessages.REPORT_ALREADY_SETTLED,
        )

    if outcome in (ReportOutcome.escalated, ReportOutcome.held):
        # The one crossing between the two shapes, and one direction only.
        #
        # The case is opened before the report closes, and on its own
        # transaction. If closing then fails, the report stays open and a
        # moderator escalates again — which opens no second case, because the
        # writer keys on the target and joins the one already open. The other
        # order would risk a closed report whose escalation never left.
        reporters = (
            await session.exec(
                select(
                    ModerationReportReporter.reporter_id,
                    ModerationReportReporter.detail,
                )
                .where(ModerationReportReporter.report_id == report.id)
                .order_by(
                    ModerationReportReporter.reported_at,
                    ModerationReportReporter.id,
                )
            )
        ).all()
        opened = await _open_platform_case(
            target=SearchEntityType(report.target_type),
            target_id=report.target_id,
            reason=ReportReason(report.reason),
            detail=None,
            moment=moment,
            note=note,
            reporters=tuple((reporter_id, words) for reporter_id, words in reporters),
            guild_id=guild_id,
        )
        if opened is None:
            # Nothing is bound to receive it, so the report stays open and the
            # moderator is told. Closing it as escalated would record a handover
            # that never happened.
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=ModerationMessages.NOWHERE_TO_SEND,
            )
        # What the reporters attached goes with it: the stored bytes copied
        # as they are, their keys wrapped for the operations community.
        await evidence_service.carry_report(
            session,
            source_guild_id=guild_id,
            report_id=report.id,
            case_task_id=opened.task_id,
        )
        if outcome is ReportOutcome.held:
            from app.services.platform import holds as holds_service

            if hold is None or context is None:  # pragma: no cover - the schema refuses
                raise ValueError(
                    "a held outcome needs a hold and the reader's standing"
                )
            try:
                await holds_service.place(
                    session,
                    context,
                    guild_id=guild_id,
                    placed_by=decided_by,
                    request=holds_service.HoldRequest(
                        target_type=report.target_type,
                        target_id=report.target_id,
                        reason=hold.reason,
                        legal_basis=hold.legal_basis,
                        note=hold.note,
                    ),
                    opened_case_task_id=opened.task_id,
                )
            except holds_service.HoldError as exc:
                # Held already — an earlier attempt to settle it got that far
                # before the report itself failed to close — or gone from the
                # moderator's sight since. Either way there is nothing left
                # for them to hold, and the case has it.
                if exc.code not in (
                    HoldMessages.ALREADY_HELD,
                    HoldMessages.TARGET_NOT_FOUND,
                ):
                    raise

    if outcome in (ReportOutcome.content_removed, ReportOutcome.member_warned):
        report.action_id = await _act_on_report(
            session,
            context,
            report=report,
            outcome=outcome,
            decided_by=decided_by,
            guild_id=guild_id,
            note=note,
            removal_reason=removal_reason,
            message=message,
        )

    report.outcome = outcome
    report.note = note
    report.decided_by = decided_by
    report.decided_at = moment
    session.add(report)
    # The community's own decision is its record alone; one the platform
    # made under a grant is the platform's too.
    from app.services.tenant.moderation_acts import platform_grant_id

    via_grant_id = platform_grant_id(context)
    if via_grant_id is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.MODERATION_REPORT_SETTLED,
            actor_user_id=decided_by,
            guild_id=guild_id,
            target_type=report.target_type,
            target_id=report.target_id,
            detail={
                "report_id": report.id,
                "outcome": outcome.value,
                "action_id": report.action_id,
                "platform_case_task_id": report.platform_case_id,
                "via_grant_id": via_grant_id,
            },
        )
    await session.commit()
    await session.refresh(report)
    if report.platform_case_id is not None:
        await _note_settled(report, guild_id)
    return report


async def _act_on_report(
    session: AsyncSession,
    context: Optional["GuildContext"],
    *,
    report: ModerationReport,
    outcome: ReportOutcome,
    decided_by: int,
    guild_id: int,
    note: Optional[str],
    removal_reason: Optional[RemovalReason],
    message: Optional[str],
) -> Optional[int]:
    """Do what settling ``report`` as ``outcome`` says was done, and return
    the log row it wrote.

    The act commits on its own, before the report closes. If closing then
    fails, the report stays open, and settling it again finds the thing
    already taken down and closes on the removal it made.
    """
    from app.services.tenant import moderation_acts

    if context is None:  # pragma: no cover - the endpoint always passes one
        raise ValueError("acting on a report needs the reader's standing")
    removing = outcome is ReportOutcome.content_removed
    request = moderation_acts.ActRequest(
        act=ModerationAct.remove if removing else ModerationAct.warn,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=(
            (removal_reason or removal_reason_for(ReportReason(report.reason)))
            if removing
            else None
        ),
        note=note if removing else message,
    )
    try:
        action = await moderation_acts.act(
            session,
            context,
            guild_id=guild_id,
            actor_id=decided_by,
            request=request,
            report_id=report.id,
        )
    except moderation_acts.ActError as exc:
        if not removing or exc.code not in (
            ModerationMessages.ALREADY_REMOVED,
            ModerationMessages.TARGET_NOT_FOUND,
        ):
            raise
        if await moderation_acts.is_held(
            guild_id, report.target_type, report.target_id
        ):
            # Out of the moderator's sight because the platform holds it, not
            # because it is down: it can come back when the hold ends.
            raise moderation_acts.ActError(
                HoldMessages.ALREADY_HELD, http_status.HTTP_409_CONFLICT
            ) from exc
        # Taken down already — by an earlier attempt at this, or by someone
        # else — or gone. Either way it is down, which is what the report
        # says.
        from app.models.tenant.moderation import ModerationAction

        return (
            await session.exec(
                select(ModerationAction.id)
                .where(ModerationAction.report_id == report.id)
                .where(ModerationAction.action == ModerationAct.remove.value)
                .order_by(ModerationAction.id.desc())  # type: ignore[union-attr]
            )
        ).first()
    return action.id


async def _note_settled(report: ModerationReport, guild_id: int) -> None:
    """Tell the platform's case how the community settled its half. Best
    effort: the report is settled whether or not the case hears of it."""
    from app.services.platform import case_activity
    from app.services.platform.intake import configured_operations_guild_id

    operations = await configured_operations_guild_id()
    if operations is None or report.platform_case_id is None:
        return
    try:
        async with cohorts.system_session(operations) as ops:
            await set_rls_context(ops, SystemGuild(operations))
            await case_activity.post(
                ops,
                task_id=report.platform_case_id,
                kind=case_activity.ActivityKind.community_settled,
                text=(
                    f"Community {guild_id} settled its report of "
                    f"{report.target_type} {report.target_id}: "
                    f"{getattr(report.outcome, 'value', report.outcome)}."
                ),
            )
            await ops.commit()
    except Exception:  # pragma: no cover - logged; the settlement stands
        logger.exception("moderation: could not note a settlement on its case")


async def reporters_for(
    session: AsyncSession, report_ids: list[int]
) -> tuple[dict[int, int], dict[int, list[str]]]:
    """How many people reported each, and what they said — never who."""
    if not report_ids:
        return {}, {}
    rows = (
        await session.exec(
            select(
                ModerationReportReporter.report_id,
                ModerationReportReporter.detail,
            ).where(ModerationReportReporter.report_id.in_(report_ids))
        )
    ).all()
    counts: dict[int, int] = {}
    details: dict[int, list[str]] = {}
    for report_id, detail in rows:
        counts[report_id] = counts.get(report_id, 0) + 1
        if detail:
            details.setdefault(report_id, []).append(detail)
    return counts, details


#: The entity type a comment's parent column names. Every declared parent is a
#: kind in its own right, so the column's own name is the answer and there is no
#: second list to keep in step.
def _parent_entity(column: str) -> SearchEntityType:
    return SearchEntityType(column.removesuffix("_id"))


class TargetLocation:
    """What to open to go and read a reported thing.

    The target itself for everything with a page of its own, and the thing a
    comment was said on for a comment — a comment is read where it was written,
    and its own id addresses nothing. ``tool`` is what it is addressed inside,
    since a task needs its project's id to be addressed at all.
    """

    __slots__ = ("entity_type", "entity_id", "tool", "tool_id")

    def __init__(
        self, entity_type: str, entity_id: int, tool: Tool, tool_id: int
    ) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.tool = tool
        self.tool_id = tool_id


class TargetPreview:
    """A line of a reported thing, and where to go and read it.

    Either half can be absent on its own: a comment whose parent this reader
    cannot reach still shows what it said, and a thing whose own index entry has
    gone can still be opened.
    """

    __slots__ = ("excerpt", "location")

    def __init__(
        self, excerpt: Optional[str], location: Optional[TargetLocation]
    ) -> None:
        self.excerpt = excerpt
        self.location = location


async def _comment_parents(
    session: AsyncSession, comment_ids: list[int]
) -> dict[int, tuple[str, int]]:
    """What each of these comments was said on — the kind, and which one.

    Read from the comment's own parent columns, declared once in
    ``COMMENT_PARENT_COLUMNS``, rather than from the index's sharing pair: the
    two differ for the one parent whose sharing is not its own — a comment on a
    task is shared as part of the task's *project*, and read on the task.
    """
    from app.db.initiative_rls import COMMENT_PARENT_COLUMNS

    if not comment_ids:
        return {}

    comments = SQLModel.metadata.tables["comments"]
    columns = [comments.c[name] for name in COMMENT_PARENT_COLUMNS]
    rows = (
        await session.exec(
            sa_select(comments.c["id"], *columns).where(
                comments.c["id"].in_(comment_ids)
            )
        )
    ).all()

    parents: dict[int, tuple[str, int]] = {}
    for row in rows:
        for name, value in zip(COMMENT_PARENT_COLUMNS, row[1:]):
            if value is not None:
                # Exactly one is set — the table's own check constraint says so.
                parents[row[0]] = (_parent_entity(name).value, int(value))
                break
    return parents


async def target_previews(
    session: AsyncSession,
    reports: list[ModerationReport],
) -> dict[int, TargetPreview]:
    """A line of each report's target, and what to open to reach it.

    Read from ``search_entries`` rather than from each kind's own table: the
    index already holds, per row, the one line that stands for it — a comment's
    opening, everything else's name — and the tool it is addressed inside,
    which is what a link to a thing with no page of its own is built from. So
    every reportable kind is covered here without a switch over kinds, and a
    kind added later arrives with one.

    Narrowed by the table's own policies, sharing included. A moderator's
    standing already clears them for their initiative; a target they cannot
    reach comes back absent, and so does one that has since been deleted — the
    index drops with the row.
    """
    if not reports:
        return {}

    # A comment is read on the thing it was said on, so that is what a link to
    # it opens. Everything else answers for itself.
    parents = await _comment_parents(
        session,
        [r.target_id for r in reports if r.target_type == SearchEntityType.comment],
    )
    destination = {
        (r.target_type, r.target_id): (
            parents.get(r.target_id)
            if r.target_type == SearchEntityType.comment
            else (r.target_type, r.target_id)
        )
        for r in reports
    }

    pairs = set(destination) | {d for d in destination.values() if d is not None}
    rows = (
        await session.exec(
            select(
                SearchEntry.entity_type,
                SearchEntry.entity_id,
                SearchEntry.title,
                SearchEntry.dac_tool,
                SearchEntry.dac_id,
            )
            .where(
                tuple_(SearchEntry.entity_type, SearchEntry.entity_id).in_(
                    sorted(pairs)
                )
            )
            # The first chunk. Long text is split across rows, and the title is
            # the same on each of them.
            .where(SearchEntry.chunk_ix == 0)
        )
    ).all()
    found = {(row[0], row[1]): row for row in rows}

    previews: dict[int, TargetPreview] = {}
    for report in reports:
        report_id = report.id
        if report_id is None:  # read back from a SELECT; the guard narrows it
            continue
        target = found.get((report.target_type, report.target_id))
        reached = destination[(report.target_type, report.target_id)]
        # Reachable is the index's answer for BOTH: a moderator who cannot see
        # what a comment was said on is not sent to it, whatever they can see
        # of the comment itself.
        where = found.get(reached) if reached is not None else None
        location = (
            TargetLocation(where[0], where[1], Tool(where[3]), where[4])
            # A kind carrying no tool at all — the guild's own vocabulary — is
            # not something a community report can name, and is not addressed
            # from here if one ever does.
            if where is not None and where[3] and where[4] is not None
            else None
        )
        if target is None and location is None:
            continue
        previews[report_id] = TargetPreview(
            excerpt=target[2] if target is not None else None,
            location=location,
        )
    return previews


async def list_reports(
    session: AsyncSession,
    *,
    initiative_id: int,
    settled: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[tuple[ModerationReport, int, list[str]]], int, int]:
    """One page of an initiative's reports, with how many people reported
    each. Returns ``(rows, total_count, page)``.

    The session must already be routed; RLS decides whether this reader sees
    any of it. Reporter **identities** are deliberately not returned — the
    count is what a moderator needs, and the words come unattributed.
    """
    stmt = select(ModerationReport).where(
        ModerationReport.initiative_id == initiative_id
    )
    stmt = (
        stmt.where(ModerationReport.outcome.is_not(None))
        if settled
        else stmt.where(ModerationReport.outcome.is_(None))
    )
    reports, total_count, page = await paginated_query(
        session,
        # A second key, because two reports can share a timestamp and a page
        # needs one order to be paged through.
        stmt.order_by(
            ModerationReport.reported_at.desc(), ModerationReport.id.desc()
        ).execution_options(populate_existing=True),
        select(func.count()).select_from(stmt.subquery()),
        page,
        page_size,
    )
    if not reports:
        return [], total_count, page

    counts, details = await reporters_for(session, [r.id for r in reports])
    return (
        [
            (report, counts.get(report.id, 0), details.get(report.id, []))
            for report in reports
        ],
        total_count,
        page,
    )
