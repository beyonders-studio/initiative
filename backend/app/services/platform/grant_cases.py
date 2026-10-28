"""An access grant and the operations case it serves.

A support or moderation errand starts as a case in the operations community,
and the access it needs is asked for *for* that case: the request names it,
and the case hears what became of the grant — that it was asked for, how it
was decided, each act taken under it, and what it did, hourly while it is
live and in full once it ends.

What the case is told is ids, counts, route templates and the names of acts,
never anything from the community the grant reaches: the case is read by
staff of the operations community, who may not be cleared for it.

Whoever names a case must be able to read it, as themselves: their own
session, routed into the operations community through the ordinary entry
point, reads it, so a case they cannot see answers exactly as one that does
not exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from fastapi import status
from sqlalchemy import String, cast, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.clock import utcnow
from app.core.intake import STREAMS, CaseField, IntakeStream
from app.core.messages import AccessGrantMessages
from app.core.user_display import handle_of
from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.access_grant import AccessGrant, AccessGrantStatus
from app.models.platform.access_grant_activity import AccessGrantActivity
from app.models.platform.user import User
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.metadata import MetadataDefinition, MetadataValue
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.services.platform import case_activity
from app.services.platform.intake import configured_operations_guild_id

logger = logging.getLogger(__name__)

#: How often a live grant's case hears what it has been doing.
DIGEST_INTERVAL = timedelta(minutes=60)
#: How long after a grant ends its case waits for the full account of it: a
#: request the grant let in may still be finishing, and is recorded when it
#: does.
ENDED_GRACE = timedelta(minutes=10)
#: How far back a grant closed out may still hear of a request it let in.
LATE_LOOKBACK = timedelta(days=1)
#: How many changes a digest lists before it says how many more there were.
WRITES_LISTED = 20
#: How many open cases the picker offers.
PICKER_LIMIT = 50

_LINKABLE = tuple(
    stream.value for stream, meta in STREAMS.items() if meta.grant_linkable
)


class GrantCaseError(Exception):
    """The named case cannot be what this grant is for."""

    def __init__(self, code: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class OpenCase:
    """An open case somebody may name as the reason for a grant."""

    task_id: int
    title: str
    stream: IntakeStream
    #: The community the case is about, where it names one.
    subject_guild_id: Optional[int]
    #: Assigned to the reader.
    mine: bool


async def cases_required() -> bool:
    """Whether an access request must name a case: the operations community
    takes a kind of case a grant may serve. Where it takes none there is
    nothing to name."""
    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return False
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id, read_only=True))
        found = (
            await session.exec(
                select(IntakeBinding.id)
                .where(IntakeBinding.stream.in_(_LINKABLE))
                .where(IntakeBinding.enabled.is_(True))
                .limit(1)
            )
        ).first()
        await session.rollback()
    return found is not None


def _subject_guild():
    """The case's ``subject_guild`` reference, as a correlated read."""
    return (
        select(MetadataValue.value_number)
        .join(MetadataDefinition, MetadataDefinition.id == MetadataValue.property_id)
        .where(MetadataDefinition.name == CaseField.subject_guild.value)
        .where(MetadataValue.entity_type == "task")
        .where(MetadataValue.entity_id == IntakeCase.task_id)
        .correlate(IntakeCase)
        .limit(1)
        .scalar_subquery()
    )


def _open_cases():
    """Open cases of the kinds a grant may serve, read as whoever is routed."""
    return (
        select(
            IntakeCase.task_id,
            Task.title,
            IntakeCase.stream,
            _subject_guild().label("subject_guild"),
            cast(TaskStatus.category, String),
        )
        .join(Task, Task.id == IntakeCase.task_id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(IntakeCase.stream.in_(_LINKABLE))
        .where(Task.deleted_at.is_(None))
    )


async def _as_reader(user: User):
    """A session of ``user``'s own, routed into the operations community, or
    ``None`` where they cannot reach it."""
    from app.api.deps import GuildAccessError, establish_guild_access

    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return None, None
    session = cohorts.request_sessionmaker(guild_id)()
    account = await session.merge(user, load=False)
    try:
        await establish_guild_access(session, account, guild_id)
    except GuildAccessError:
        await session.close()
        return None, None
    return session, guild_id


async def readable_open_cases(
    user: User, *, search: Optional[str] = None
) -> list[OpenCase]:
    """The open cases ``user`` can read that a grant may serve, the ones
    assigned to them first, then the newest. ``search`` narrows them to a
    title holding it, or the case with that number."""
    session, _guild_id = await _as_reader(user)
    if session is None:
        return []
    try:
        mine = (
            select(TaskAssignee.task_id)
            .where(TaskAssignee.user_id == user.id)
            .where(TaskAssignee.task_id == IntakeCase.task_id)
            .correlate(IntakeCase)
            .exists()
        )
        query = (
            _open_cases()
            .add_columns(mine.label("mine"))
            .where(TaskStatus.category != TaskStatusCategory.done)
        )
        if search and (term := search.strip()):
            number = term.removeprefix("#")
            matches = Task.title.ilike(f"%{term}%")
            if number.isascii() and number.isdigit() and int(number) < 2**31:
                matches = or_(matches, IntakeCase.task_id == int(number))
            query = query.where(matches)
        rows = (
            await session.exec(
                query.order_by(mine.desc(), IntakeCase.task_id.desc()).limit(
                    PICKER_LIMIT
                )
            )
        ).all()
    finally:
        await session.close()
    return [
        OpenCase(
            task_id=int(task_id),
            title=title,
            stream=IntakeStream(stream),
            subject_guild_id=int(subject) if subject is not None else None,
            mine=bool(is_mine),
        )
        for task_id, title, stream, subject, _category, is_mine in rows
    ]


async def _readable_case(user: User, case_task_id: int) -> tuple[str, str, object]:
    """Case ``case_task_id`` as ``user`` reads it: its stream, its status's
    category and the community it is about. Refused unless they can read it,
    it is open, and it is a kind of case staff act for."""
    session, _ops = await _as_reader(user)
    if session is None:
        raise GrantCaseError(
            AccessGrantMessages.CASE_NOT_FOUND, status.HTTP_404_NOT_FOUND
        )
    try:
        row = (
            await session.exec(
                select(
                    IntakeCase.stream,
                    cast(TaskStatus.category, String),
                    _subject_guild(),
                )
                .join(Task, Task.id == IntakeCase.task_id)
                .join(TaskStatus, TaskStatus.id == Task.task_status_id)
                .where(IntakeCase.task_id == case_task_id)
                .where(Task.deleted_at.is_(None))
            )
        ).first()
    finally:
        await session.close()
    if row is None:
        raise GrantCaseError(
            AccessGrantMessages.CASE_NOT_FOUND, status.HTTP_404_NOT_FOUND
        )
    stream, category, subject = row
    if stream not in _LINKABLE:
        raise GrantCaseError(AccessGrantMessages.CASE_NOT_LINKABLE)
    if category == TaskStatusCategory.done.value:
        raise GrantCaseError(AccessGrantMessages.CASE_CLOSED, status.HTTP_409_CONFLICT)
    return stream, category, subject


async def check_case(user: User, *, case_task_id: int, guild_id: int) -> bool:
    """Refuse ``case_task_id`` as the reason ``user`` asks for access to
    ``guild_id``, unless they can read it, it is open, it is a kind a grant may
    serve, and it is about that community or no community yet. Returns
    whether it names no community, so the link can name it."""
    _stream, _category, subject = await _readable_case(user, case_task_id)
    if subject is not None and int(subject) != guild_id:
        raise GrantCaseError(AccessGrantMessages.CASE_OTHER_COMMUNITY)
    return subject is None


async def check_account_case(user: User, *, case_task_id: int) -> None:
    """Refuse ``case_task_id`` as the case an act on an account is for,
    unless ``user`` can read it, it is open, and it is a kind of case staff
    act for. Any account the case concerns may be acted on for it."""
    await _readable_case(user, case_task_id)


async def note(
    task_id: Optional[int], kind: case_activity.ActivityKind, text: str
) -> bool:
    """Note ``text`` on case ``task_id``, as the platform. Best effort: what the
    note is about stands whether or not its case hears of it."""
    if task_id is None:
        return False
    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return False
    try:
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            await case_activity.post(session, task_id=task_id, kind=kind, text=text)
            await session.commit()
        return True
    except Exception:  # noqa: BLE001 — logged; the note is a courtesy to the case
        logger.exception("grant cases: could not note on case %s", task_id)
        return False


async def case_exists(task_id: int) -> bool:
    """Whether case ``task_id`` is still there to be told: the operations
    community is configured and the case has not been purged. A case in the
    trash may yet be restored, so it is still there; where it cannot be read,
    it is taken to be there."""
    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return False
    try:
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            found = (
                await session.exec(
                    select_including_deleted(Task.id).where(Task.id == task_id)
                )
            ).first()
    except Exception:  # noqa: BLE001 — logged; asked again on the next pass
        logger.exception("grant cases: could not read case %s", task_id)
        return True
    return found is not None


async def _tell_digest(task_id: int, text: str) -> Optional[bool]:
    """Note a digest on case ``task_id``: ``True`` once it is told, ``False``
    where it could not be and is worth trying again, and ``None`` where the
    case is gone and never will be."""
    if await note(task_id, case_activity.ActivityKind.grant_digest, text):
        return True
    return False if await case_exists(task_id) else None


async def claim(task_id: int, *, guild_id: int) -> str:
    """Settle that the case a grant is asked for is about the grant's
    community, naming it where the case names none: ``named`` (named now),
    ``held`` (it already was) or ``other`` (it is about another). Under a
    lock, so two requests at once for one unnamed case cannot each name it."""
    from app.services.platform.intake import claim_subject_guild

    return await claim_subject_guild(task_id, guild_id)


async def unclaim(task_id: int, *, guild_id: int) -> None:
    """Undo a :func:`claim` that named the case, for a grant not made."""
    from app.services.platform.intake import release_subject_guild

    await release_subject_guild(task_id, guild_id)


async def activate(task_id: Optional[int]) -> None:
    """Move a case still waiting to be picked up to the status its stream's
    binding calls active: access approved for it means somebody is on it."""
    if task_id is None:
        return
    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return
    try:
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            found = (
                await session.exec(
                    select(Task, IntakeBinding.active_status_id)
                    .join(IntakeCase, IntakeCase.task_id == Task.id)
                    .join(TaskStatus, TaskStatus.id == Task.task_status_id)
                    .join(IntakeBinding, IntakeBinding.stream == IntakeCase.stream)
                    .where(Task.id == task_id)
                    .where(TaskStatus.category == TaskStatusCategory.todo)
                    .with_for_update(of=Task)
                )
            ).first()
            if found is None or found[1] is None:
                return
            task, active = found
            belongs = (
                await session.exec(
                    select(TaskStatus.id)
                    .where(TaskStatus.id == active)
                    .where(TaskStatus.project_id == task.project_id)
                )
            ).first()
            if belongs is None:
                return
            task.task_status_id = active
            session.add(task)
            await session.commit()
    except Exception:  # noqa: BLE001 — logged; the approval stands
        logger.exception("grant cases: could not move case %s", task_id)


# ── What a grant did ─────────────────────────────────────────────────────────


def _describe(
    grant: AccessGrant, guild_name: Optional[str], holder: Optional[User]
) -> str:
    who = handle_of(holder) if holder is not None else f"account {grant.user_id}"
    where = f"{guild_name} (#{grant.guild_id})" if guild_name else f"#{grant.guild_id}"
    return f"{who}'s {grant.purpose} grant at {grant.access_level} on {where}"


def requested_text(
    grants: Sequence[AccessGrant], *, guild_name: Optional[str], holder: User
) -> str:
    asked = ", ".join(f"{g.purpose} at {g.access_level}" for g in grants)
    first = grants[0]
    where = f"{guild_name} (#{first.guild_id})" if guild_name else f"#{first.guild_id}"
    return (
        f"{handle_of(holder)} asked for access to {where} for this case: {asked}, "
        f"for {first.requested_duration_minutes} minutes. Reason: {first.reason}"
    )


def decided_text(
    grant: AccessGrant,
    *,
    guild_name: Optional[str],
    holder: Optional[User],
    decided_by: Optional[User],
) -> str:
    by = f" by {handle_of(decided_by)}" if decided_by is not None else ""
    status_ = AccessGrantStatus(grant.status)
    what = {
        AccessGrantStatus.approved: "approved",
        AccessGrantStatus.denied: "denied",
        AccessGrantStatus.revoked: "revoked",
        AccessGrantStatus.expired: "ended",
        AccessGrantStatus.pending: "asked for",
    }.get(status_, status_.value)
    line = f"{_describe(grant, guild_name, holder)} was {what}{by}."
    if status_ is AccessGrantStatus.approved and grant.expires_at is not None:
        line += f" It ends at {grant.expires_at.strftime('%Y-%m-%d %H:%M UTC')}."
    return line


@dataclass(frozen=True)
class ActivitySummary:
    """What a grant did over a stretch, counted in the database: reads by the
    kind of thing they named, how many changes, and the first changes."""

    reads: dict[str, int]
    write_count: int
    writes: list[AccessGrantActivity]
    #: When the latest request counted was recorded, where any was.
    latest: Optional[datetime] = None


async def _activity(
    session: AsyncSession, grant_id: int, since: Optional[datetime]
) -> ActivitySummary:
    """Count a grant's requests since ``since`` (all of them where ``None``)
    and fetch only the changes a note lists."""
    window = [AccessGrantActivity.grant_id == grant_id]
    if since is not None:
        window.append(AccessGrantActivity.occurred_at > since)
    read_counts = (
        await session.exec(
            select(AccessGrantActivity.target_type, func.count())
            .where(*window)
            .where(AccessGrantActivity.is_write.is_(False))
            .group_by(AccessGrantActivity.target_type)
        )
    ).all()
    write_count = (
        await session.exec(
            select(func.count())
            .select_from(AccessGrantActivity)
            .where(*window)
            .where(AccessGrantActivity.is_write.is_(True))
        )
    ).one()
    writes = (
        await session.exec(
            select(AccessGrantActivity)
            .where(*window)
            .where(AccessGrantActivity.is_write.is_(True))
            .order_by(AccessGrantActivity.occurred_at, AccessGrantActivity.id)
            .limit(WRITES_LISTED)
        )
    ).all()
    latest = (
        await session.exec(
            select(func.max(AccessGrantActivity.occurred_at)).where(*window)
        )
    ).one()
    return ActivitySummary(
        reads={kind or "other": int(n) for kind, n in read_counts},
        write_count=int(write_count),
        writes=list(writes),
        latest=latest,
    )


def _accounted_to(grant: AccessGrant, summary: ActivitySummary) -> datetime:
    """How far a case has been told of what ``grant`` did: the latest request
    counted, or where none was, when the grant ended. A request recorded
    after this — one the grant let in that was still finishing — is told on
    its own later."""
    ended = grant.revoked_at or grant.expires_at or grant.decided_at
    candidates = [moment for moment in (summary.latest, ended) if moment is not None]
    return max(candidates) if candidates else utcnow()


def digest_text(summary: ActivitySummary, *, heading: str) -> str:
    """What a grant did, as its case reads it: reads counted by the kind of
    thing they named, changes listed (the first :data:`WRITES_LISTED`)."""
    lines = [heading]
    if not summary.reads and not summary.write_count:
        lines.append("Nothing was opened or changed.")
        return "\n".join(lines)
    if summary.reads:
        counted = ", ".join(f"{kind} ×{n}" for kind, n in sorted(summary.reads.items()))
        lines.append(f"Read {sum(summary.reads.values())} times: {counted}.")
    if summary.write_count:
        lines.append(f"Changed {summary.write_count} times:")
        for row in summary.writes:
            named = f" ({row.target_type} {row.target_id})" if row.target_type else ""
            lines.append(
                f"- {row.occurred_at.strftime('%H:%M')} {row.method} {row.route}"
                f"{named} → {row.status}"
            )
        if summary.write_count > len(summary.writes):
            lines.append(f"- …and {summary.write_count - len(summary.writes)} more.")
    return "\n".join(lines)


async def report_activity(
    session: AsyncSession, *, now: Optional[datetime] = None
) -> int:
    """One pass: tell each case what the grants serving it did. A grant that
    ended is closed out with what it did in all; a live one with something
    new to tell is told once an hour. Returns how many cases were told.

    ``session`` is the system engine's, unrouted: grants and their activity
    are shared rows. Each case is written on its own session in the
    operations community.
    """
    from app.models.platform.guild import Guild

    moment = now or utcnow()
    told = 0
    ended = (
        await session.exec(
            select(AccessGrant)
            .where(AccessGrant.case_task_id.is_not(None))
            .where(AccessGrant.closed_out_at.is_(None))
            .where(
                or_(
                    AccessGrant.status == AccessGrantStatus.denied.value,
                    # Ended long enough ago that a request it let in has
                    # finished, and been recorded.
                    func.coalesce(AccessGrant.revoked_at, AccessGrant.expires_at)
                    <= moment - ENDED_GRACE,
                )
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    live = (
        await session.exec(
            select(AccessGrant)
            .where(AccessGrant.case_task_id.is_not(None))
            .where(AccessGrant.closed_out_at.is_(None))
            .where(AccessGrant.live(moment))
            .where(
                func.coalesce(AccessGrant.activity_noted_at, AccessGrant.decided_at)
                <= moment - DIGEST_INTERVAL
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    # A request a grant let in that was still running when the grant was
    # closed out is recorded after it: its case hears of it on its own.
    late = (
        await session.exec(
            select(AccessGrant)
            .where(AccessGrant.case_task_id.is_not(None))
            .where(AccessGrant.closed_out_at.is_not(None))
            .where(AccessGrant.closed_out_at >= moment - LATE_LOOKBACK)
            .where(
                select(AccessGrantActivity.id)
                .where(AccessGrantActivity.grant_id == AccessGrant.id)
                .where(AccessGrantActivity.occurred_at > AccessGrant.closed_out_at)
                .exists()
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    names = {
        g.id: g.name
        for g in (
            await session.exec(
                select(Guild).where(
                    Guild.id.in_({grant.guild_id for grant in [*ended, *live, *late]})
                )
            )
        ).all()
    }
    users = {
        u.id: u
        for u in (
            await session.exec(
                select(User).where(
                    User.id.in_(
                        {grant.user_id for grant in [*ended, *live, *late]}
                        | {g.revoked_by_id for g in ended if g.revoked_by_id}
                    )
                )
            )
        ).all()
    }
    for grant in ended:
        summary = await _activity(session, int(grant.id), None)
        if grant.status == AccessGrantStatus.denied.value:
            # Never used, and its case was told of the denial.
            grant.closed_out_at = _accounted_to(grant, summary)
            session.add(grant)
            continue
        how = (
            f"was revoked by {handle_of(users[grant.revoked_by_id])}"
            if grant.revoked_by_id in users
            else "has ended"
        )
        heading = (
            f"{_describe(grant, names.get(grant.guild_id), users.get(grant.user_id))} "
            f"{how}. What it did in all:"
        )
        # Marked told only once it is, or once there is no case left to tell:
        # a note that could not be written is tried again on the next pass.
        outcome = await _tell_digest(
            int(grant.case_task_id), digest_text(summary, heading=heading)
        )
        if outcome is not False:
            grant.closed_out_at = _accounted_to(grant, summary)
            session.add(grant)
            told += outcome is True
    for grant in live:
        since = grant.activity_noted_at or grant.decided_at
        summary = await _activity(session, int(grant.id), since)
        if not summary.reads and not summary.write_count:
            grant.activity_noted_at = moment
            session.add(grant)
            continue
        heading = (
            f"{_describe(grant, names.get(grant.guild_id), users.get(grant.user_id))}"
            " since the last note:"
        )
        outcome = await _tell_digest(
            int(grant.case_task_id), digest_text(summary, heading=heading)
        )
        if outcome is not False:
            grant.activity_noted_at = moment
            session.add(grant)
            told += outcome is True
    for grant in late:
        summary = await _activity(session, int(grant.id), grant.closed_out_at)
        heading = (
            f"After {_describe(grant, names.get(grant.guild_id), users.get(grant.user_id))}"
            " ended, requests it had let in finished:"
        )
        outcome = await _tell_digest(
            int(grant.case_task_id), digest_text(summary, heading=heading)
        )
        if outcome is not False:
            grant.closed_out_at = _accounted_to(grant, summary)
            session.add(grant)
            told += outcome is True
    await session.commit()
    return told


async def note_act(context: object, text: str) -> bool:
    """Tell the case behind the grant a request was served through, where it
    was served through one that names a case, of an act taken under it."""
    grant = getattr(context, "grant", None)
    case = getattr(grant, "case_task_id", None)
    if case is None:
        return False
    return await note(case, case_activity.ActivityKind.moderation_act, text)
