"""Sending somebody something: a line in their bell that opens it.

Whoever can open a thing may point the people of its community at it, with a
note. Each person named lands in one of three places:

- they can open it, and the line names it;
- they can't, the sender may share it and gave a rung to share at, so they are
  let in first and the line names it;
- they can't, and are in its initiative, so may know it is there
  (``app.db.presence``): the line names its kind alone, and opening it offers
  to ask for it.

Anybody else named — outside its initiative, where it does not exist for them —
refuses the whole send. Nothing is stored but the lines and any sharing given.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import ActorContext
from app.core.messages import SendMessages
from app.core.tools import KINDS
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.initiative import InitiativeMember, PermissionKey
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services import notifications as notifications_service
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.permissions import Action
from app.services.tenant import share_requests as share_requests_service


@dataclass(frozen=True)
class Sent:
    """Who heard, by the way they heard it."""

    sent: list[int]
    let_in: list[int]
    may_ask: list[int]


async def send(
    session: AsyncSession,
    *,
    sender: User,
    context: ActorContext,
    kind: str,
    entity_id: int,
    user_ids: list[int],
    note: str | None,
    level: ResourceAccessLevel | None,
) -> Sent:
    """Point ``user_ids`` at ``(kind, entity_id)``. Rides the caller's
    transaction; the caller commits."""
    subject = await notifications_service.resolve_subject(session, (kind, entity_id))
    if subject is None:
        raise KINDS[kind].not_found()
    wanted = sorted(set(user_ids) - {sender.id})
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=SendMessages.NOBODY,
        )
    outside = [user_id for user_id in wanted if user_id not in subject.readers]
    members = (
        set(
            (
                await session.exec(
                    select(InitiativeMember.user_id).where(
                        InitiativeMember.initiative_id == subject.initiative_id,
                        InitiativeMember.user_id.in_(outside),
                    )
                )
            ).all()
        )
        if outside and subject.initiative_id is not None
        else set()
    )
    if set(outside) - members:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SendMessages.NOT_IN_INITIATIVE,
        )
    let_in: list[int] = []
    if outside and level is not None:
        await _let_in(session, sender, context, subject, outside, level)
        let_in = outside
    may_ask = [user_id for user_id in outside if user_id not in let_in]
    sent = [user_id for user_id in wanted if user_id not in may_ask]

    name = await notifications_service.actor_name(session, sender)
    note_values = {"note": note} if note else {}
    note_data = {"note": note} if note else {}
    suffix = "_note" if note else ""
    if sent:
        title = (await share_requests_service.names(session, [(kind, entity_id)])).get(
            (kind, entity_id), ""
        )
        await notifications_service.notify(
            session,
            NotificationType.item_sent,
            sent,
            # Read again where somebody was let in: the sharing just given is
            # what lets the line reach them.
            about=(kind, entity_id) if let_in else subject,
            key=f"item.sent{suffix}",
            values={"sender": name, "title": title, **note_values},
            data={
                "sender_name": name,
                "entity_type": kind,
                "entity_id": entity_id,
                **note_data,
            },
            actor=sender,
        )
    if may_ask:
        await notifications_service.notify(
            session,
            NotificationType.item_sent,
            may_ask,
            about=subject,
            key=f"item.sent_unnamed{suffix}",
            values={"sender": name, **note_values},
            data={
                "sender_name": name,
                "entity_type": kind,
                "entity_id": entity_id,
                **note_data,
            },
            actor=sender,
            present=may_ask,
        )
    return Sent(sent=sent, let_in=let_in, may_ask=may_ask)


async def _let_in(
    session: AsyncSession,
    sender: User,
    context: ActorContext,
    subject: notifications_service.Subject,
    user_ids: list[int],
    level: ResourceAccessLevel,
) -> None:
    """Share what governs ``subject`` with ``user_ids`` at ``level``, as the
    sharing settings would: only by somebody who may share it, and only with
    people whose role lets them use the tool."""
    if subject.resource_id is None or subject.initiative_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=SendMessages.NOTHING_TO_SHARE,
        )
    await resource_access.load_authorized(
        session,
        subject.tool,
        subject.resource_id,
        sender,
        context,
        action=Action.share,
    )
    permitted = await rls_service.members_permitted(
        session,
        initiative_id=subject.initiative_id,
        user_ids=set(user_ids),
        permission_key=PermissionKey(subject.tool.view_permission),
    )
    if set(user_ids) - permitted:
        raise subject.tool.grantee_lacks_access()
    for user_id in user_ids:
        await permissions_service.share_with(
            session,
            resource_type=subject.tool,
            resource_id=subject.resource_id,
            guild_id=context.guild_id,
            initiative_id=subject.initiative_id,
            user_id=user_id,
            level=level,
            actor_user_id=sender.id,
        )
    # Somebody who had asked has their answer; the send's own line tells them.
    await share_requests_service.settle_reached(
        session,
        tool=subject.tool,
        resource_id=subject.resource_id,
        sharing={("user", user_id): level.value for user_id in user_ids},
        answerer=sender,
        note=None,
        tell=False,
    )
