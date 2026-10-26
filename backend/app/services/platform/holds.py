"""Holds: content kept in place for the platform.

A hold answers what neither removing content nor leaving it up does: a legal
request to keep something, or something unlawful reported. The content stops
being seen and can't be changed or destroyed, without disturbing the community
around it. The database does the hiding and the freezing (``app.db.holds``);
this places and releases holds, and keeps their record.

- **Placing.** A community moderator — the community's admin, or someone with
  Full access in the content's initiative — holds it *for the platform*: that
  opens a moderation case in the operations community, and from that moment the
  moderator can't see the content either. A platform moderator under a
  ``moderate`` grant on the community holds it directly, against a case.
- **What is held.** The content and everything inside it — a project's tasks
  and their comments, a wiki's pages — and the uploads any of it shows. A
  comment is held alone: its replies are other people's words, and stay, under
  a placeholder.
- **Releasing** is the platform's alone, under a ``moderate`` grant:
  ``restore`` puts it back as it was, ``remove`` takes it down through the
  community's moderation log (``app.services.tenant.moderation_acts``) — a
  comment to a tombstone, anything else to the trash — and ``purge``
  destroys it.

Each placement and release is recorded on the case and in the audit log, and
the hourly sweep reminds the case every 30 days while a hold stays in place.
Nothing is said to the author: held content reads as absent.
"""

from __future__ import annotations

from contextlib import nullcontext

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import status
from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.encryption import SALT_HOLD_NOTE, decrypt_field, encrypt_field
from app.core.errors import CodedError
from app.core.intake import IntakeStream
from app.core.messages import HoldMessages
from app.core.moderation import HoldReason, HoldRelease, HoldVia, LegalBasis
from app.core.search import SearchEntityType
from app.core.tools import plural_of
from app.db import cohorts, gucs
from app.db.guild_standing import GuildContext
from app.db.base import MODELS_BY_TABLE
from app.db.query import ids_in
from app.db.request_context import SystemGuild
from app.db.session import raise_flag, routed_guild_id, set_rls_context
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant._mixins import HoldMixin, hold_models
from app.models.tenant.content_hold import ContentHold
from app.services import audit as audit_service
from app.services.platform import case_activity

logger = logging.getLogger(__name__)

#: How often a case is reminded that a hold on it is still in place.
REMINDER_INTERVAL = timedelta(days=30)


class HoldError(CodedError):
    """A hold that can't be placed or released, and why."""


def model_for(target_type: str) -> type[HoldMixin]:
    """The model a hold names by its ``SearchEntityType`` value."""
    model = MODELS_BY_TABLE.get(plural_of(target_type))
    if target_type not in SearchEntityType.__members__ or not (
        model and issubclass(model, HoldMixin)
    ):
        raise HoldError(HoldMessages.TARGET_NOT_FOUND, status.HTTP_404_NOT_FOUND)
    return model


# -- Who may hold what ----------------------------------------------------------


async def _seen_in(
    session: AsyncSession, target_type: str, target_id: int
) -> tuple[bool, Optional[int]]:
    """Whether the reader's own session sees the target, and its initiative.
    Read under the reader's row security, so what they can't see isn't
    there."""
    from sqlalchemy import func

    model = model_for(target_type)
    seen = (
        await session.exec(
            select_including_deleted(model)
            .where(model.id == target_id)
            .with_only_columns(model.id)
        )
    ).first()
    if seen is None:
        return False, None
    initiative_id = (
        await session.exec(select(func.entity_initiative(target_type, target_id)))
    ).first()
    return True, initiative_id


def _via(context: GuildContext, initiative_id: Optional[int]) -> HoldVia:
    """Who is placing the hold: the platform, under a ``moderate`` grant, or
    one of the community's moderators — its admin, or Full access in the
    content's initiative."""
    if context.pam_moderate:
        return HoldVia.platform
    if context.is_admin or context.overrides_sharing(initiative_id):
        return HoldVia.community
    raise HoldError(HoldMessages.NOT_ALLOWED, status.HTTP_403_FORBIDDEN)


# -- What a hold covers ---------------------------------------------------------


async def _covered(session: AsyncSession, target: HoldMixin) -> dict[type, list[int]]:
    """The target and everything a hold on it covers, by model. A comment is
    held alone; anything else takes everything inside it."""
    from app.models.tenant.comment import Comment
    from app.services.tenant.lifecycle_tree import subtree_levels

    if isinstance(target, Comment):
        return {Comment: [int(target.id)]}  # type: ignore[arg-type]
    covered: dict[type, list[int]] = {}
    for level in await subtree_levels(session, [target]):
        for model, ids in level.items():
            if issubclass(model, HoldMixin):
                covered.setdefault(model, []).extend(ids)
    return covered


async def _shown_uploads(
    session: AsyncSession, covered: dict[type, list[int]]
) -> set[str]:
    """The stored names of the uploads anything ``covered`` shows."""
    from app.models.tenant.file import File, FileVersion
    from app.models.tenant.catalog import CatalogItem, CatalogItemVersion
    from app.services.tenant.attachments import (
        _upload_columns,
        upload_names,
        upload_urls_in_markdown,
    )

    texts: list[str] = []
    parents = {
        FileVersion: (File, "file_id"),
        CatalogItemVersion: (CatalogItem, "catalog_item_id"),
    }
    for model, column in _upload_columns():
        if model in parents:
            parent, key = parents[model]
            ids = covered.get(parent)
            if not ids:
                continue
            where = ids_in(getattr(model, key), ids)
        else:
            ids = covered.get(model)
            if not ids:
                continue
            where = ids_in(model.id, ids)
        values = (await session.exec(select(getattr(model, column)).where(where))).all()
        texts.extend(str(value) for value in values if value)
    urls: set[str] = set()
    for value in texts:
        urls |= upload_urls_in_markdown(value)
    return upload_names(urls)


async def _stamp(
    session: AsyncSession,
    covered: dict[type, list[int]],
    names: set[str],
    hold: ContentHold,
) -> None:
    from app.models.tenant.upload import Upload

    now = hold.placed_at
    for model, ids in covered.items():
        await session.exec(
            update(model)
            .where(ids_in(model.id, ids))
            .where(model.held_at.is_(None))
            .values(held_at=now, hold_id=hold.id)
            .execution_options(synchronize_session=False)
        )
    if names:
        await session.exec(
            update(Upload)
            .where(ids_in(Upload.filename, names))
            .where(Upload.held_at.is_(None))  # type: ignore[union-attr]
            .values(held_at=now, hold_id=hold.id)
            .execution_options(synchronize_session=False)
        )


async def _unstamp(session: AsyncSession, hold_id: int) -> None:
    for model in hold_models():
        await session.exec(
            update(model)
            .where(model.hold_id == hold_id)
            .values(held_at=None, hold_id=None)
            .execution_options(synchronize_session=False)
        )


async def _cover_again(session: AsyncSession, released_id: int) -> None:
    """Hold again, under the hold that covers it, whatever releasing
    ``released_id`` let go that another open hold still covers: a comment
    held on its own and then inside its task, or an upload two held things
    show. Releasing one hold never releases another's content."""
    others = (
        await session.exec(
            select(ContentHold)
            .where(ContentHold.released_at.is_(None))  # type: ignore[union-attr]
            .where(ContentHold.id != released_id)
            .order_by(ContentHold.id)
        )
    ).all()
    for other in others:
        model = model_for(other.target_type)
        target = (
            await session.exec(
                select_including_deleted(model)
                .where(model.id == other.target_id)
                .execution_options(populate_existing=True)
            )
        ).first()
        if target is None:
            continue
        covered = await _covered(session, target)
        await _stamp(session, covered, await _shown_uploads(session, covered), other)


async def _community_stays(session: AsyncSession, guild_id: int) -> None:
    """Serialize with the community being destroyed (``guild_purge``), and
    refuse once it has been: a hold placed after that could never be reached
    to release it."""
    from app.db.advisory_locks import LockNamespace, advisory_lock
    from app.models.platform.guild import Guild

    await advisory_lock(session, LockNamespace.CONTENT_HOLDS, guild_id)
    present = (await session.exec(select(Guild.id).where(Guild.id == guild_id))).first()
    if present is None:
        raise HoldError(HoldMessages.COMMUNITY_GONE, status.HTTP_404_NOT_FOUND)


# -- Placing --------------------------------------------------------------------


@dataclass(frozen=True)
class HoldWhy:
    """Why something is held: the closed reason, the law where it may be
    illegal, and a note only the platform reads."""

    reason: HoldReason
    legal_basis: Optional[LegalBasis] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class HoldRequest:
    target_type: str
    target_id: int
    reason: HoldReason
    legal_basis: Optional[LegalBasis] = None
    note: Optional[str] = None
    #: The case the platform is holding it under. A community moderator's
    #: hold opens its own.
    case_task_id: Optional[int] = None


async def _open_case(guild_id: int, request: HoldRequest) -> int:
    from app.services.platform.intake import CaseRefs, open_case

    basis = request.legal_basis.value if request.legal_basis else None
    outcome = await open_case(
        IntakeStream.moderation,
        title=f"Held for the platform: {request.target_type} {request.target_id}",
        body=(
            f"A moderator of community {guild_id} held {request.target_type} "
            f"{request.target_id} for the platform ({request.reason.value}"
            + (f", {basis}" if basis else "")
            + "). Nobody in the community can see it until it is released here."
        ),
        refs=CaseRefs(
            subject_guild=guild_id,
            resource_type=request.target_type,
            resource_id=request.target_id,
            severity=basis or request.reason.value,
        ),
        dedupe_key=f"hold:{guild_id}:{request.target_type}:{request.target_id}",
    )
    if outcome is None:
        raise HoldError(
            HoldMessages.NOWHERE_TO_SEND, status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return outcome.task_id


async def _require_case(case_task_id: int) -> None:
    """Refuse a case that isn't one the operations community is working."""
    from app.models.tenant.intake import IntakeCase
    from app.services.platform.intake import configured_operations_guild_id

    operations = await configured_operations_guild_id()
    found = None
    if operations is not None:
        async with cohorts.system_session(operations) as session:
            await set_rls_context(session, SystemGuild(operations, read_only=True))
            found = (
                await session.exec(
                    select(IntakeCase.id).where(IntakeCase.task_id == case_task_id)
                )
            ).first()
            await session.rollback()
    if found is None:
        raise HoldError(HoldMessages.CASE_NOT_FOUND, status.HTTP_404_NOT_FOUND)


async def _note_on_case(
    case_task_id: Optional[int], kind: case_activity.ActivityKind, words: str
) -> bool:
    """Note ``words`` on the operations case, where there is one to note it
    on. Best effort: the hold stands whether or not its case hears of it.
    Returns whether the note was written."""
    from app.services.platform.intake import configured_operations_guild_id

    if case_task_id is None:
        return False
    operations = await configured_operations_guild_id()
    if operations is None:
        return False
    try:
        async with cohorts.system_session(operations) as session:
            await set_rls_context(session, SystemGuild(operations))
            await case_activity.post(
                session, task_id=case_task_id, kind=kind, text=words
            )
            await session.commit()
        return True
    except Exception:  # pragma: no cover - logged, and the sweep reminds again
        logger.exception("holds: could not note on case %s", case_task_id)
        return False


async def place(
    session: AsyncSession,
    context: GuildContext,
    *,
    guild_id: int,
    placed_by: int,
    request: HoldRequest,
    opened_case_task_id: Optional[int] = None,
) -> ContentHold:
    """Hold ``request``'s target in ``guild_id``'s community.

    ``session`` is the reader's own, routed into the community: whether they
    see the target, and may hold it, is read there. The hold itself is written
    on a system session, as the platform.

    ``opened_case_task_id`` is a case the caller has just opened for it — a
    report settled as held hands its reporters' words and files to one — and
    the hold is worked there rather than on a case of its own.
    """
    model = model_for(request.target_type)
    if request.reason is HoldReason.illegal_content and request.legal_basis is None:
        raise HoldError(HoldMessages.LEGAL_BASIS_REQUIRED)
    seen, initiative_id = await _seen_in(
        session, request.target_type, request.target_id
    )
    if not seen:
        raise HoldError(HoldMessages.TARGET_NOT_FOUND, status.HTTP_404_NOT_FOUND)
    via = _via(context, initiative_id)

    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id))
        target = (
            await system.exec(
                select_including_deleted(model).where(model.id == request.target_id)
            )
        ).first()
        if target is None:
            raise HoldError(HoldMessages.TARGET_NOT_FOUND, status.HTTP_404_NOT_FOUND)
        if target.held_at is not None:
            raise HoldError(HoldMessages.ALREADY_HELD, status.HTTP_409_CONFLICT)
        await system.rollback()

    # Every hold is worked on a case: the platform's names one it is working,
    # and any other opens its own.
    case_task_id = request.case_task_id
    naming = via is HoldVia.platform and opened_case_task_id is None
    if opened_case_task_id is not None:
        case_task_id = opened_case_task_id
    elif naming and case_task_id is not None:
        await _require_case(case_task_id)
    else:
        case_task_id = await _open_case(guild_id, request)

    from app.services.platform.intake import case_locked, claim_subject_guild

    # A case named here may be one long closed, whose files the retention
    # sweep is deciding. Its task is held locked, as the sweep locks it, until
    # the hold is committed, so the sweep either finishes first or sees it.
    keeping = (
        case_locked(case_task_id)
        if naming and request.case_task_id is not None
        else nullcontext()
    )
    async with keeping as locked:
        if naming and request.case_task_id is not None:
            # A case's holds sit in the community it is about: that is where
            # the keeping of its files looks for them.
            if await claim_subject_guild(case_task_id, guild_id) == "other":
                raise HoldError(
                    HoldMessages.CASE_OTHER_COMMUNITY, status.HTTP_400_BAD_REQUEST
                )
        # Holding something in the operations community itself — the case's
        # own task, or what holds it — is written on the session that holds
        # the case's lock, rather than waiting on it.
        shared = (
            locked
            if locked is not None and routed_guild_id(locked) == guild_id
            else None
        )
        async with (
            nullcontext(shared)
            if shared is not None
            else cohorts.system_session(guild_id)
        ) as system:
            await set_rls_context(system, SystemGuild(guild_id))
            await _community_stays(system, guild_id)
            # Writing the hold columns of archived or trashed rows is a write to
            # frozen content on purpose, as a purge's is (``gucs.PURGING``).
            await raise_flag(system, gucs.PURGING)
            target = (
                await system.exec(
                    select_including_deleted(model)
                    .where(model.id == request.target_id)
                    .with_for_update()
                )
            ).one()
            if target.held_at is not None:
                raise HoldError(HoldMessages.ALREADY_HELD, status.HTTP_409_CONFLICT)
            hold = ContentHold(
                target_type=request.target_type,
                target_id=request.target_id,
                case_task_id=case_task_id,
                placed_by=placed_by,
                placed_via=via.value,
                reason=request.reason.value,
                legal_basis=request.legal_basis.value if request.legal_basis else None,
                note=encrypt_field(request.note, SALT_HOLD_NOTE)
                if request.note
                else None,
            )
            system.add(hold)
            await system.flush()
            covered = await _covered(system, target)
            names = await _shown_uploads(system, covered)
            await _stamp(system, covered, names, hold)
            await raise_flag(system, gucs.PURGING, False)
            await audit_service.record(
                system,
                event_type=AuditEventType.HOLD_PLACED,
                actor_user_id=placed_by,
                guild_id=guild_id,
                target_type=request.target_type,
                target_id=request.target_id,
                detail={
                    "hold_id": hold.id,
                    "via": via.value,
                    "reason": hold.reason,
                    "legal_basis": hold.legal_basis,
                    "case_task_id": case_task_id,
                    "rows": sum(len(ids) for ids in covered.values()),
                    "uploads": len(names),
                },
            )
            await system.commit()
            await system.refresh(hold)
            if shared is not None:
                # The lock's session is let go after this, which would
                # expire what it loaded.
                system.expunge(hold)

    await _note_on_case(
        case_task_id,
        case_activity.ActivityKind.hold_placed,
        f"Hold {hold.id} placed on {hold.target_type} {hold.target_id} in community "
        f"{guild_id} ({hold.reason}"
        + (f", {hold.legal_basis}" if hold.legal_basis else "")
        + f"), by the {via.value}.",
    )
    return hold


# -- Releasing ------------------------------------------------------------------


async def release(
    context: GuildContext,
    *,
    guild_id: int,
    hold_id: int,
    outcome: HoldRelease,
    released_by: int,
) -> ContentHold:
    """End hold ``hold_id`` with ``outcome``. The platform's alone."""
    from app.services.tenant.attachments import delete_blobs
    from app.services.tenant.soft_delete import hard_purge_entity

    if not context.pam_moderate:
        raise HoldError(HoldMessages.NOT_FOUND, status.HTTP_404_NOT_FOUND)
    released: set[str] = set()
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id))
        hold = (
            await system.exec(
                select(ContentHold).where(ContentHold.id == hold_id).with_for_update()
            )
        ).first()
        if hold is None:
            raise HoldError(HoldMessages.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        if hold.released_at is not None:
            raise HoldError(HoldMessages.ALREADY_RELEASED, status.HTTP_409_CONFLICT)
        await _community_stays(system, guild_id)
        await raise_flag(system, gucs.PURGING)
        await _unstamp(system, int(hold.id))
        await _cover_again(system, int(hold.id))
        await raise_flag(system, gucs.PURGING, False)
        model = model_for(hold.target_type)
        target = (
            await system.exec(
                select_including_deleted(model)
                .where(model.id == hold.target_id)
                .execution_options(populate_existing=True)
            )
        ).first()
        if (
            target is not None
            and outcome is not HoldRelease.restore
            and target.held_at is not None
        ):
            # Another hold covers it: it stays as it is until that one ends.
            raise HoldError(HoldMessages.COVERED_BY_ANOTHER, status.HTTP_409_CONFLICT)
        let_go: set[str] = set()
        if target is not None and outcome is HoldRelease.remove:
            let_go = await _remove_released(
                system, context, hold, target, released_by=released_by
            )
        elif target is not None and outcome is HoldRelease.purge:
            released = await hard_purge_entity(system, target)
        now = datetime.now(timezone.utc)
        hold.released_at = now
        hold.released_by = released_by
        hold.release_outcome = outcome.value
        system.add(hold)
        await audit_service.record(
            system,
            event_type=AuditEventType.HOLD_RELEASED,
            actor_user_id=released_by,
            guild_id=guild_id,
            target_type=hold.target_type,
            target_id=hold.target_id,
            detail={
                "hold_id": hold.id,
                "outcome": outcome.value,
                "case_task_id": hold.case_task_id,
            },
        )
        await system.commit()
        await system.refresh(hold)
    if released:
        delete_blobs(guild_id, released)
    if let_go:
        from app.services.tenant.attachments import release_unshown

        delete_blobs(
            guild_id, await release_unshown(guild_id, let_go, pasted_only=True)
        )
    await _note_on_case(
        hold.case_task_id,
        case_activity.ActivityKind.hold_released,
        f"Hold {hold.id} on {hold.target_type} {hold.target_id} in community "
        f"{guild_id} released: {outcome.value}.",
    )
    return hold


async def _remove_released(
    system: AsyncSession,
    context: GuildContext,
    hold: ContentHold,
    target: HoldMixin,
    *,
    released_by: int,
) -> set[str]:
    """Take down what a hold kept, through the community's moderation log —
    a comment to a tombstone, anything else to the trash — and return the
    picture addresses its words showed, to release once committed."""
    from sqlalchemy import func

    from app.core.moderation import RemovalReason
    from app.services.tenant import moderation_acts

    removed_already = getattr(target, "deleted_at", None) is not None or (
        getattr(target, "removed_at", None) is not None
    )
    if removed_already:
        return set()
    initiative_id = (
        await system.exec(
            select(func.entity_initiative(hold.target_type, hold.target_id))
        )
    ).first()
    if initiative_id is None:
        # Something no initiative owns has no moderation log to be in.
        from app.services.tenant.soft_delete import trash

        await trash(system, target, deleted_by_user_id=released_by)  # type: ignore[arg-type]
        return set()
    removed = await moderation_acts.remove_on(
        system,
        target,
        moderation_acts.Who(
            actor_id=released_by,
            hold_id=hold.id,
            via_grant_id=context.grant.id if context.grant is not None else None,
        ),
        target_type=hold.target_type,
        initiative_id=int(initiative_id),
        # Held for the law, so taken down for it.
        reason=RemovalReason.illegal,
    )
    return removed.let_go


# -- Reading --------------------------------------------------------------------


@dataclass(frozen=True)
class HoldView:
    hold: ContentHold
    #: What the held thing is called, read as the platform reads it.
    label: Optional[str]
    note: Optional[str]


async def listed(
    session: AsyncSession,
    *,
    case_task_id: Optional[int] = None,
    open_only: bool = False,
) -> list[HoldView]:
    """The holds ``session`` may read — none, but for the system engine and a
    ``moderate`` grantee — newest first."""
    query = select(ContentHold).order_by(
        ContentHold.placed_at.desc(), ContentHold.id.desc()
    )
    if case_task_id is not None:
        query = query.where(ContentHold.case_task_id == case_task_id)
    if open_only:
        query = query.where(ContentHold.released_at.is_(None))  # type: ignore[union-attr]
    holds = (await session.exec(query)).all()
    views: list[HoldView] = []
    for hold in holds:
        views.append(
            HoldView(
                hold=hold,
                label=await _label(session, hold),
                note=open_note(hold.note),
            )
        )
    return views


def open_note(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    try:
        return decrypt_field(note, SALT_HOLD_NOTE)
    except Exception:  # pragma: no cover - a note sealed under a lost key
        logger.warning("holds: a note could not be opened")
        return None


async def _label(session: AsyncSession, hold: ContentHold) -> Optional[str]:
    try:
        model = model_for(hold.target_type)
    except HoldError:
        return None
    display = getattr(model, "display_field", None)
    column = display() if callable(display) else "name"
    if column not in model.model_fields:
        return None
    value = (
        await session.exec(
            select_including_deleted(model)
            .where(model.id == hold.target_id)
            .with_only_columns(getattr(model, column))
        )
    ).first()
    return str(value)[:200] if value else None


# -- The sweep ------------------------------------------------------------------


async def remind_due(session: AsyncSession, guild_id: int) -> int:
    """Note on each case whose hold in ``guild_id`` has stood another 30 days.
    ``session`` is the sweep's, routed into the community."""
    now = datetime.now(timezone.utc)
    due = (
        await session.exec(
            select(ContentHold)
            .where(ContentHold.released_at.is_(None))  # type: ignore[union-attr]
            .where(ContentHold.case_task_id.is_not(None))  # type: ignore[union-attr]
            .where(
                (
                    ContentHold.reminded_at.is_(None)
                    & (ContentHold.placed_at < now - REMINDER_INTERVAL)
                )  # type: ignore[union-attr]
                | (ContentHold.reminded_at < now - REMINDER_INTERVAL)  # type: ignore[operator]
            )
        )
    ).all()
    reminded = 0
    for hold in due:
        days = (now - hold.placed_at).days
        noted = await _note_on_case(
            hold.case_task_id,
            case_activity.ActivityKind.hold_reminder,
            f"Hold {hold.id} on {hold.target_type} {hold.target_id} in community "
            f"{guild_id} is still in place, {days} days on.",
        )
        if not noted:
            # Tried again on the next pass, not in a month.
            continue
        hold.reminded_at = now
        session.add(hold)
        reminded += 1
    if reminded:
        await session.commit()
    return reminded
