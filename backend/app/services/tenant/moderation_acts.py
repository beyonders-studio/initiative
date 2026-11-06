"""What a community's moderators do to content, and the log they do it in.

The **moderation set** of an initiative is whoever reaches everything in it:
the community's admins and the people whose role carries Full access — the
standing ``initiative_full_access`` answers in the database — and the platform
under a ``moderate`` grant. Managing an initiative is not moderating it: a
project manager runs the work, and takes down nobody's words.

Every act is written to ``moderation_actions``, the community's moderation
log, which is append-only (``app.db.moderation_log``):

- **remove** — a comment becomes a tombstone where it was, its words moved
  into the log, sealed; anything else goes to the trash with the moderator as
  the one who put it there. Either way its author is told why, and never by
  whom.
- **restore** — puts back what a removal took down.
- **lock_comments** / **unlock_comments** — a locked thread reads as it
  stood: nobody adds to it or edits in it, a moderator included, until it is
  unlocked (``comments._locked_now``). The acts here still reach what is in
  it, and its authors may still take their own words back.
- **clear_reactions** — every reaction on a comment or a post, gone.
- **warn** — the author is told, in the moderator's words.

Who may act, and on what, is read on the moderator's own session: they act on
what they can see, in an initiative they moderate. The act itself is written
on a system session, as the platform writes a hold, because what it touches —
someone else's words, a tombstone, the log — is no member's to write.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.encryption import (
    SALT_MODERATION_SNAPSHOT,
    decrypt_field,
    encrypt_field,
)
from app.core.errors import CodedError
from app.core.messages import HoldMessages, ModerationMessages
from app.core.moderation import ModerationAct, RemovalReason
from app.core.reactions import ReactionTarget
from app.core.search import SearchEntityType
from app.core.tools import plural_of
from app.db import cohorts
from app.db.guild_standing import GuildContext
from app.db.base import MODELS_BY_TABLE
from app.db.query import paginated_query
from app.db.request_context import SystemGuild
from app.db.session import routed_guild_id, set_rls_context
from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.notification import NotificationType
from app.models.tenant._mixins import CommentLockMixin, HoldMixin
from app.models.tenant.comment import Comment
from app.models.tenant.moderation import ModerationAction
from app.services import audit as audit_service

logger = logging.getLogger(__name__)


class ActError(CodedError):
    """An act that can't be done, and why."""


def may_moderate(context: GuildContext, initiative_id: Optional[int]) -> bool:
    """Whether this request is in ``initiative_id``'s moderation set: the
    community's admin, Full access in the initiative, or the platform under
    a ``moderate`` grant."""
    if context.pam_moderate or context.is_admin:
        return True
    return context.overrides_sharing(initiative_id)


# -- What an act is done to -----------------------------------------------------


def model_for(target_type: str) -> type[HoldMixin]:
    """The model a report or an act names by its ``SearchEntityType`` value."""
    model = MODELS_BY_TABLE.get(plural_of(target_type))
    if target_type not in SearchEntityType.__members__ or not (
        model and issubclass(model, HoldMixin)
    ):
        raise ActError(ModerationMessages.TARGET_NOT_FOUND, status.HTTP_404_NOT_FOUND)
    return model


#: Which acts each kind takes. A removal and a warning take anything a report
#: can name; a lock, what a thread hangs off; clearing, what reactions hang off.
def _takes(act: ModerationAct, model: type) -> bool:
    if act is ModerationAct.lock_comments or act is ModerationAct.unlock_comments:
        return issubclass(model, CommentLockMixin)
    if act is ModerationAct.clear_reactions:
        return str(model.__tablename__) in {t.table for t in ReactionTarget}
    return True


async def _locate(
    session: AsyncSession, context: GuildContext, target_type: str, target_id: int
) -> tuple[type[HoldMixin], int]:
    """The target's model and initiative, read on the moderator's own session
    so what they can't see isn't there, and refused unless they moderate
    that initiative."""
    model = model_for(target_type)
    seen = (
        await session.exec(
            select_including_deleted(model)
            .where(model.id == target_id)  # type: ignore[attr-defined]
            .with_only_columns(model.id)  # type: ignore[attr-defined]
        )
    ).first()
    initiative_id = None
    if seen is not None:
        initiative_id = (
            await session.exec(select(func.entity_initiative(target_type, target_id)))
        ).first()
    if seen is None or initiative_id is None:
        raise ActError(ModerationMessages.TARGET_NOT_FOUND, status.HTTP_404_NOT_FOUND)
    if not may_moderate(context, initiative_id):
        raise ActError(ModerationMessages.NOT_A_MODERATOR, status.HTTP_403_FORBIDDEN)
    return model, int(initiative_id)


async def is_held(guild_id: int, target_type: str, target_id: int) -> bool:
    """Whether the platform holds this target, read as the platform: a held
    row reads as absent to everyone in the community."""
    model = model_for(target_type)
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id, read_only=True))
        held = (
            await system.exec(
                select_including_deleted(model)
                .where(model.id == target_id)  # type: ignore[attr-defined]
                .where(model.held_at.is_not(None))  # type: ignore[union-attr]
                .with_only_columns(model.id)  # type: ignore[attr-defined]
            )
        ).first()
        await system.rollback()
    return held is not None


def platform_grant_id(context: Optional[GuildContext]) -> Optional[int]:
    """The moderate grant the reader acts under, where they act for the
    platform rather than as one of the community's own moderators."""
    if context is None or not context.pam_moderate or context.grant is None:
        return None
    return context.grant.id


# -- The log --------------------------------------------------------------------


@dataclass(frozen=True)
class Who:
    """Who did it, and on what grounds, for the log row."""

    actor_id: Optional[int]
    report_id: Optional[int] = None
    hold_id: Optional[int] = None
    via_grant_id: Optional[int] = None


#: The audit line an act the platform took writes beside its log row.
_AUDITED: dict[ModerationAct, AuditEventType] = {
    ModerationAct.remove: AuditEventType.MODERATION_CONTENT_REMOVED,
    ModerationAct.restore: AuditEventType.MODERATION_CONTENT_RESTORED,
    ModerationAct.lock_comments: AuditEventType.MODERATION_COMMENTS_LOCKED,
    ModerationAct.unlock_comments: AuditEventType.MODERATION_COMMENTS_UNLOCKED,
    ModerationAct.clear_reactions: AuditEventType.MODERATION_REACTIONS_CLEARED,
    ModerationAct.warn: AuditEventType.MODERATION_MEMBER_WARNED,
}


async def _record(
    system: AsyncSession,
    who: Who,
    *,
    act: ModerationAct,
    initiative_id: int,
    target_type: str,
    target_id: int,
    subject_user_id: Optional[int] = None,
    reason: Optional[RemovalReason] = None,
    note: Optional[str] = None,
    snapshot: Optional[str] = None,
) -> ModerationAction:
    row = ModerationAction(
        initiative_id=initiative_id,
        action=act.value,
        target_type=target_type,
        target_id=target_id,
        subject_user_id=subject_user_id,
        reason=reason.value if reason else None,
        note=note,
        snapshot=(
            encrypt_field(snapshot, SALT_MODERATION_SNAPSHOT) if snapshot else None
        ),
        report_id=who.report_id,
        hold_id=who.hold_id,
        via_grant_id=who.via_grant_id,
        created_by=who.actor_id,
    )
    system.add(row)
    await system.flush()
    # A community's own decisions are its log's alone; an act the platform
    # took under a grant is the platform's record too. Staged on the same
    # session, so the line and the row commit together.
    if who.via_grant_id is None:
        return row
    await audit_service.record(
        system,
        event_type=_AUDITED[act],
        actor_user_id=who.actor_id,
        target_user_id=subject_user_id,
        guild_id=routed_guild_id(system),
        target_type=target_type,
        target_id=target_id,
        detail={
            "action_id": row.id,
            "initiative_id": initiative_id,
            "reason": reason.value if reason else None,
            "report_id": who.report_id,
            "hold_id": who.hold_id,
            "via_grant_id": who.via_grant_id,
        },
    )
    return row


def open_snapshot(action: ModerationAction) -> Optional[str]:
    """The words a removal took down, for the moderation set."""
    if not action.snapshot:
        return None
    try:
        return decrypt_field(action.snapshot, SALT_MODERATION_SNAPSHOT)
    except Exception:  # pragma: no cover - sealed under a lost key
        logger.warning("moderation: a snapshot could not be opened")
        return None


# -- Telling the author ---------------------------------------------------------


async def _place(
    system: AsyncSession, row: HoldMixin, target_type: str, *, going: bool
) -> tuple[Optional[tuple[str, int]], Optional[str]]:
    """Where a notice about acting on ``row`` opens: what it is said on, or
    where it lived. Returns the thing to resolve the notice against, or, for
    a tool's own row that is going to the trash, the path to its list.

    A comment opens the thing it was said on. Anything else still standing
    opens itself; anything going to the trash opens the tool it was in, or —
    for a tool's own row, a post, say — the initiative's list of them.
    """
    from app.services import notifications

    row_id = int(row.id)  # type: ignore[attr-defined]
    if isinstance(row, Comment):
        from app.services.tenant.comments import COMMENT_PARENT_COLUMNS

        for column in COMMENT_PARENT_COLUMNS:
            parent = getattr(row, column)
            if parent is not None:
                return (column.removesuffix("_id"), int(parent)), None
        return None, None
    if not going:
        return (target_type, row_id), None
    subject = await notifications.resolve_subject(system, (target_type, row_id))
    if subject is None:
        return None, None
    # A row governed by no tool row of its own (a collection) opens its tool's
    # list, as a tool's own row does.
    if subject.resource_id is not None and (
        subject.tool.value != target_type or subject.resource_id != row_id
    ):
        return (subject.tool.value, subject.resource_id), None
    if subject.initiative_id is None:
        return None, None
    segment = subject.tool.plural.replace("_", "-")
    return None, f"/i/{subject.initiative_id}/{segment}"


async def _tell(
    system: AsyncSession,
    notification_type: NotificationType,
    recipient: Optional[int],
    *,
    place: tuple[Optional[tuple[str, int]], Optional[str]],
    key: str,
    values: dict[str, str],
    data: dict[str, object],
) -> None:
    """Tell ``recipient``, opening at ``place`` (``_place``) where they can
    still open it, and at the community otherwise. The moderator who acted is
    never named."""
    from app.services import notifications

    if recipient is None:
        return
    ref, path = place
    about = None
    if ref is not None:
        subject = await notifications.resolve_subject(system, ref)
        if subject is not None and recipient in subject.readers:
            about = subject
    payload = dict(data)
    if about is None and path is not None:
        payload["target_path"] = path
    await notifications.notify(
        system,
        notification_type,
        [recipient],
        about=about,
        key=key,
        values=values,
        data=payload,
    )


# -- Removing and restoring -----------------------------------------------------


@dataclass
class Removed:
    action: ModerationAction
    #: Picture addresses the removed words showed, for the caller to release
    #: once it has committed (``attachments.release_unshown``).
    let_go: set[str]


async def remove_on(
    system: AsyncSession,
    row: HoldMixin,
    who: Who,
    *,
    target_type: str,
    initiative_id: int,
    reason: RemovalReason,
    note: Optional[str] = None,
) -> Removed:
    """Take ``row`` down on ``system``, a session routed into its community
    as the platform. The caller commits.

    A comment becomes a tombstone: its words go into the log, sealed, and
    what they linked to, the reactions on it and the pictures pasted into it
    go with them; the replies under it stay. Anything else goes to the trash.
    """
    from app.services.tenant import content_references
    from app.services.tenant import reactions as reactions_service
    from app.services.tenant.attachments import upload_urls_in_markdown
    from app.services.tenant.soft_delete import trash

    if row.held_at is not None:
        raise ActError(HoldMessages.ALREADY_HELD, status.HTTP_409_CONFLICT)
    author = getattr(row, "created_by", None)
    # Where the author is sent, read before it goes.
    place = await _place(system, row, target_type, going=not isinstance(row, Comment))
    let_go: set[str] = set()
    if isinstance(row, Comment):
        if row.removed_at is not None or row.deleted_at is not None:
            raise ActError(ModerationMessages.ALREADY_REMOVED, status.HTTP_409_CONFLICT)
        words = row.content
        action = await _record(
            system,
            who,
            act=ModerationAct.remove,
            initiative_id=initiative_id,
            target_type=target_type,
            target_id=int(row.id),  # type: ignore[arg-type]
            subject_user_id=author,
            reason=reason,
            note=note,
            snapshot=words,
        )
        row.content = ""
        row.removed_at = datetime.now(timezone.utc)
        row.removed_reason = reason.value
        row.removal_id = action.id
        system.add(row)
        await system.flush()
        await content_references.sync_for_comment(system, row, author_id=who.actor_id)
        await reactions_service.purge_reactions_for(
            system,
            target=ReactionTarget.comment,
            target_ids=[int(row.id)],  # type: ignore[arg-type]
        )
        let_go = upload_urls_in_markdown(words)
    else:
        if getattr(row, "deleted_at", None) is not None:
            raise ActError(ModerationMessages.ALREADY_REMOVED, status.HTTP_409_CONFLICT)
        action = await _record(
            system,
            who,
            act=ModerationAct.remove,
            initiative_id=initiative_id,
            target_type=target_type,
            target_id=int(row.id),  # type: ignore[attr-defined]
            subject_user_id=author,
            reason=reason,
            note=note,
        )
        await trash(system, row, deleted_by_user_id=who.actor_id)  # type: ignore[arg-type]
    await _tell(
        system,
        NotificationType.moderation_removal,
        author,
        place=place,
        key="moderation.removed",
        values={},
        data={
            "target_type": target_type,
            "target_id": row.id,  # type: ignore[attr-defined]
            "reason": reason.value,
            "initiative_id": initiative_id,
        },
    )
    return Removed(action=action, let_go=let_go)


async def _restore_on(
    system: AsyncSession, removal: ModerationAction, who: Who, note: Optional[str]
) -> ModerationAction:
    from app.services.tenant import content_references
    from app.services.tenant.soft_delete import restore_entity

    model = model_for(removal.target_type)
    row = (
        await system.exec(
            select_including_deleted(model)
            .where(model.id == removal.target_id)  # type: ignore[attr-defined]
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise ActError(ModerationMessages.NOT_REMOVED, status.HTTP_409_CONFLICT)
    # Only the removal standing on its target is undone: not one a restore
    # already answered, and not one a later removal took the place of.
    standing = (await _standing(system, [removal])).get(
        (removal.target_type, removal.target_id)
    )
    if standing != removal.id:
        raise ActError(ModerationMessages.NOT_REMOVED, status.HTTP_409_CONFLICT)
    if row.held_at is not None:
        raise ActError(HoldMessages.ALREADY_HELD, status.HTTP_409_CONFLICT)
    if isinstance(row, Comment):
        if row.removal_id != removal.id:
            raise ActError(ModerationMessages.NOT_REMOVED, status.HTTP_409_CONFLICT)
        row.content = open_snapshot(removal) or ""
        row.removed_at = None
        row.removed_reason = None
        row.removal_id = None
        system.add(row)
        await system.flush()
        await content_references.sync_for_comment(system, row, author_id=who.actor_id)
    else:
        # In the trash because this removal put it there — not because its
        # author deleted it since, after it was brought back another way.
        deleted_at = getattr(row, "deleted_at", None)
        if (
            deleted_at is None
            or deleted_at < removal.created_at
            or getattr(row, "deleted_by", None) != removal.created_by
        ):
            raise ActError(ModerationMessages.NOT_REMOVED, status.HTTP_409_CONFLICT)
        await restore_entity(system, row)  # type: ignore[arg-type]
    return await _record(
        system,
        who,
        act=ModerationAct.restore,
        initiative_id=removal.initiative_id,
        target_type=removal.target_type,
        target_id=removal.target_id,
        subject_user_id=removal.subject_user_id,
        note=note,
    )


# -- The acts, as a moderator asks for them -------------------------------------


@dataclass(frozen=True)
class ActRequest:
    act: ModerationAct
    target_type: str
    target_id: int
    #: For a removal.
    reason: Optional[RemovalReason] = None
    #: Why, for the log; for a warning, what the member is told.
    note: Optional[str] = None


async def act(
    session: AsyncSession,
    context: GuildContext,
    *,
    guild_id: int,
    actor_id: int,
    request: ActRequest,
    report_id: Optional[int] = None,
) -> ModerationAction:
    """Do ``request``, as a moderator of the content's initiative.

    ``session`` is the moderator's own, routed into the community: whether
    they see the target and moderate its initiative is read there. The act is
    written on a system session, and committed before this returns.
    """
    from app.services.tenant import reactions as reactions_service
    from app.services.tenant.attachments import delete_blobs, release_unshown

    if request.act not in (
        ModerationAct.remove,
        ModerationAct.lock_comments,
        ModerationAct.unlock_comments,
        ModerationAct.clear_reactions,
        ModerationAct.warn,
    ):
        raise ActError(ModerationMessages.ACT_NOT_TAKEN)
    model, initiative_id = await _locate(
        session, context, request.target_type, request.target_id
    )
    if not _takes(request.act, model):
        raise ActError(ModerationMessages.ACT_NOT_TAKEN)
    if request.act is ModerationAct.remove and request.reason is None:
        raise ActError(ModerationMessages.ACT_NOT_TAKEN)
    note = (request.note or "").strip() or None
    if request.act is ModerationAct.warn and note is None:
        raise ActError(ModerationMessages.MESSAGE_REQUIRED)

    who = Who(
        actor_id=actor_id, report_id=report_id, via_grant_id=platform_grant_id(context)
    )
    let_go: set[str] = set()
    locks_thread = request.act in (
        ModerationAct.lock_comments,
        ModerationAct.unlock_comments,
    )
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id))
        if locks_thread:
            from app.db.advisory_locks import LockNamespace, advisory_lock
            from app.services.tenant.comments import thread_key

            # Takes turns with a comment being written in the thread, so one
            # landing now is either in before the lock or refused by it. Taken
            # before the row, in the order a comment's write takes the two.
            await advisory_lock(
                system,
                LockNamespace.COMMENT_THREAD,
                thread_key(guild_id, str(model.__tablename__), request.target_id),
            )
        row = (
            await system.exec(
                select_including_deleted(model)
                .where(model.id == request.target_id)  # type: ignore[attr-defined]
                .with_for_update()
            )
        ).first()
        if row is None:
            raise ActError(
                ModerationMessages.TARGET_NOT_FOUND, status.HTTP_404_NOT_FOUND
            )
        if request.act is ModerationAct.remove:
            removed = await remove_on(
                system,
                row,
                who,
                target_type=request.target_type,
                initiative_id=initiative_id,
                reason=request.reason,  # type: ignore[arg-type]
                note=note,
            )
            action, let_go = removed.action, removed.let_go
        elif locks_thread:
            locking = request.act is ModerationAct.lock_comments
            # Read under this act's turn on the thread, taken above.
            locked = getattr(row, "comments_locked_at", None) is not None
            if locking and locked:
                raise ActError(
                    ModerationMessages.ALREADY_LOCKED, status.HTTP_409_CONFLICT
                )
            if not locking and not locked:
                raise ActError(ModerationMessages.NOT_LOCKED, status.HTTP_409_CONFLICT)
            row.comments_locked_at = (  # type: ignore[attr-defined]
                datetime.now(timezone.utc) if locking else None
            )
            system.add(row)
            await system.flush()
            action = await _record(
                system,
                who,
                act=request.act,
                initiative_id=initiative_id,
                target_type=request.target_type,
                target_id=request.target_id,
                note=note,
            )
        elif request.act is ModerationAct.clear_reactions:
            target = next(
                t for t in ReactionTarget if t.table == str(model.__tablename__)
            )
            await reactions_service.purge_reactions_for(
                system, target=target, target_ids=[request.target_id]
            )
            action = await _record(
                system,
                who,
                act=request.act,
                initiative_id=initiative_id,
                target_type=request.target_type,
                target_id=request.target_id,
                note=note,
            )
        else:
            action = await warn_on(
                system,
                row,
                who,
                target_type=request.target_type,
                initiative_id=initiative_id,
                message=note,  # type: ignore[arg-type]
            )
        await system.commit()
        await system.refresh(action)
    if let_go:
        delete_blobs(
            guild_id, await release_unshown(guild_id, let_go, pasted_only=True)
        )
    return action


async def warn_on(
    system: AsyncSession,
    row: HoldMixin,
    who: Who,
    *,
    target_type: str,
    initiative_id: int,
    message: str,
) -> ModerationAction:
    """Warn whoever wrote ``row``, in ``message``. The caller commits."""
    author = getattr(row, "created_by", None)
    if author is None:
        raise ActError(ModerationMessages.NOBODY_TO_WARN)
    action = await _record(
        system,
        who,
        act=ModerationAct.warn,
        initiative_id=initiative_id,
        target_type=target_type,
        target_id=int(row.id),  # type: ignore[attr-defined]
        subject_user_id=author,
        note=message,
    )
    await _tell(
        system,
        NotificationType.moderation_warning,
        author,
        place=await _place(system, row, target_type, going=False),
        key="moderation.warned",
        values={"message": message},
        data={
            "target_type": target_type,
            "target_id": row.id,  # type: ignore[attr-defined]
            "message": message,
            "initiative_id": initiative_id,
        },
    )
    return action


async def restore(
    session: AsyncSession,
    context: GuildContext,
    *,
    guild_id: int,
    actor_id: int,
    action_id: int,
    note: Optional[str] = None,
) -> ModerationAction:
    """Put back what removal ``action_id`` took down. Read on the moderator's
    own session, where the log is theirs to read; written as the platform."""
    removal = (
        await session.exec(
            select(ModerationAction).where(ModerationAction.id == action_id)
        )
    ).first()
    if removal is None:
        raise ActError(ModerationMessages.ACTION_NOT_FOUND, status.HTTP_404_NOT_FOUND)
    if removal.action != ModerationAct.remove.value:
        raise ActError(ModerationMessages.NOT_A_REMOVAL)
    if not may_moderate(context, removal.initiative_id):
        raise ActError(ModerationMessages.NOT_A_MODERATOR, status.HTTP_403_FORBIDDEN)
    who = Who(actor_id=actor_id, via_grant_id=platform_grant_id(context))
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id))
        removal = (
            await system.exec(
                select(ModerationAction).where(ModerationAction.id == action_id)
            )
        ).one()
        restored = await _restore_on(system, removal, who, (note or "").strip() or None)
        await system.commit()
        await system.refresh(restored)
    return restored


# -- Reading the log ------------------------------------------------------------


async def _standing(
    session: AsyncSession, removals: list[ModerationAction]
) -> dict[tuple[str, int], int]:
    """For each target these removals name, the newest remove or restore on
    it: a removal is still standing when it is that row."""
    from sqlalchemy import tuple_

    targets = sorted({(a.target_type, a.target_id) for a in removals})
    if not targets:
        return {}
    initiatives = sorted({a.initiative_id for a in removals})
    rows = (
        await session.exec(
            select(
                ModerationAction.target_type,
                ModerationAction.target_id,
                func.max(ModerationAction.id),
            )
            .where(ModerationAction.initiative_id.in_(initiatives))  # type: ignore[attr-defined]
            .where(
                tuple_(ModerationAction.target_type, ModerationAction.target_id).in_(
                    targets
                )
            )
            .where(
                ModerationAction.action.in_(  # type: ignore[attr-defined]
                    (ModerationAct.remove.value, ModerationAct.restore.value)
                )
            )
            .group_by(ModerationAction.target_type, ModerationAction.target_id)
        )
    ).all()
    return {(t, i): int(latest) for t, i, latest in rows}


@dataclass(frozen=True)
class LogEntry:
    action: ModerationAction
    #: The words a comment's removal took down.
    snapshot: Optional[str]
    #: Whether this removal is the one standing on its target, so restoring
    #: it is open.
    restorable: bool


async def log(
    session: AsyncSession,
    *,
    initiative_id: int,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[LogEntry], int, int]:
    """One page of an initiative's moderation log, newest first. Returns
    ``(entries, total_count, page)``. Read on the reader's session: the log's
    policy admits the initiative's moderation set and nobody else."""
    stmt = select(ModerationAction).where(
        ModerationAction.initiative_id == initiative_id
    )
    actions, total, page = await paginated_query(
        session,
        stmt.order_by(ModerationAction.created_at.desc(), ModerationAction.id.desc()),
        select(func.count()).select_from(stmt.subquery()),
        page,
        page_size,
    )
    removals = [a for a in actions if a.action == ModerationAct.remove.value]
    standing = await _standing(session, removals)
    entries = [
        LogEntry(
            action=action,
            snapshot=open_snapshot(action),
            restorable=(
                action.action == ModerationAct.remove.value
                and standing.get((action.target_type, action.target_id)) == action.id
            ),
        )
        for action in actions
    ]
    return entries, total, page
