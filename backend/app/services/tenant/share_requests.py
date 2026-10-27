"""Asking for something you can't open, or can't edit, and the answer.

A member who meets something in their initiative they can't open — a link, an
embed, a collection's or a wiki's files — may know it is there
(``app.db.presence``) and ask for it, at ``read`` or ``write``. So may anybody
who can open a thing but not edit it, an item guest included, ask to edit it.
Whoever may share the thing answers: a yes shares it through the ordinary
sharing rows, with the requester or with the whole initiative, at the rung the
answer gives; a no says so only if the person answering chooses to.

Who is told: the thing's owner, or the initiative's managers where it has none.
The requester can't see who that is, so it is looked up, and the notice
written, on a system session routed into the community.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ShareRequestMessages
from app.core.relationships import ENDPOINT_KINDS, RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.authorization import standing_arg
from app.db.base import MODELS_BY_TABLE
from app.db.presence import VIEW as PRESENCE_VIEW
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.share_request import (
    ShareRequest,
    ShareRequestScope,
    ShareRequestStatus,
)
from app.services import notifications as notifications_service
from app.services import permissions as permissions_service
from app.services.tenant import initiatives as initiatives_service

#: The rungs a person may ask for. Owner is given, never asked for.
ASKABLE = (ResourceAccessLevel.read, ResourceAccessLevel.write)


@dataclass(frozen=True)
class Standing:
    """Where the reader stands on one thing they can open or know is there."""

    initiative_id: int
    #: The rung they hold, or ``None`` where they can't open it.
    level: ResourceAccessLevel | None
    #: The rung they asked for and nobody has answered yet.
    pending: ResourceAccessLevel | None


def _table(tool: Tool) -> str:
    return ENDPOINT_KINDS[SearchEntityType(tool.value)].table


async def standing_on(
    session: AsyncSession, *, tool: Tool, resource_id: int, user_id: int
) -> Standing | None:
    """The reader's standing on one thing, or ``None`` when they can neither
    open it nor know it is there — the answer for something in an initiative
    they are not in, as for something that does not exist."""
    readable = (
        await session.exec(select(func.entity_initiative(tool.value, resource_id)))
    ).one()
    if readable is None:
        present = (
            await session.exec(
                text(
                    f"SELECT initiative_id FROM {PRESENCE_VIEW}"  # noqa: S608
                    " WHERE kind = :kind AND id = :id AND NOT trashed"
                ),
                params={"kind": tool.value, "id": resource_id},
            )
        ).scalar()
        if present is None:
            return None
    initiative_id = readable if readable is not None else present
    level = None
    if readable is not None:
        held = (
            await session.exec(
                select(
                    func.resource_level(
                        tool.value, resource_id, user_id, initiative_id, standing_arg()
                    )
                )
            )
        ).one()
        level = ResourceAccessLevel(held) if held is not None else None
    pending = (
        await session.exec(
            select(ShareRequest.level).where(
                ShareRequest.resource_type == tool.value,
                ShareRequest.resource_id == resource_id,
                ShareRequest.user_id == user_id,
                ShareRequest.status == ShareRequestStatus.pending.value,
            )
        )
    ).first()
    return Standing(
        initiative_id=initiative_id,
        level=level,
        pending=ResourceAccessLevel(pending) if pending is not None else None,
    )


async def hidden_files(
    session: AsyncSession,
    *,
    collection_id: int | None = None,
    wiki_id: int | None = None,
) -> list[int]:
    """The files in a collection or a wiki that the reader knows are there,
    out of the trash, and can't open."""
    if collection_id is not None:
        sql = (
            "SELECT cf.file_id FROM collection_files cf"
            f" JOIN {PRESENCE_VIEW} ep ON ep.kind = 'file' AND ep.id = cf.file_id"
            " AND NOT ep.trashed"
            " WHERE cf.collection_id = :place"
            " AND NOT EXISTS (SELECT 1 FROM files f WHERE f.id = cf.file_id)"
        )
        place = collection_id
    else:
        sql = (
            "SELECT r.source_id FROM relationships r"
            f" JOIN {PRESENCE_VIEW} ep ON ep.kind = 'file' AND ep.id = r.source_id"
            " AND NOT ep.trashed"
            " WHERE r.target_type = 'wiki' AND r.target_id = :place"
            " AND r.source_type = 'file'"
            f" AND r.relationship_type = '{RelationshipType.part_of.value}'"
            " AND r.removed_at IS NULL"
            " AND NOT EXISTS (SELECT 1 FROM files f WHERE f.id = r.source_id)"
        )
        place = wiki_id
    rows = await session.exec(text(sql), params={"place": place})  # noqa: S608
    return sorted({row[0] for row in rows.all()})


async def hidden_file_counts(
    session: AsyncSession,
    *,
    user_id: int,
    collection_ids: list[int] | None = None,
    wiki_ids: list[int] | None = None,
) -> dict[int, tuple[int, int]]:
    """For each collection or wiki, how many of its files the reader knows
    are there and can't open, and how many of those they have asked for — what
    the card offering to ask for them says."""
    ids = collection_ids if collection_ids is not None else wiki_ids
    if not ids:
        return {}
    if collection_ids is not None:
        place, file_id, frm = "cf.collection_id", "cf.file_id", "collection_files cf"
        where = "cf.collection_id = ANY(:ids)"
    else:
        place, file_id, frm = "r.target_id", "r.source_id", "relationships r"
        where = (
            "r.target_type = 'wiki' AND r.target_id = ANY(:ids)"
            " AND r.source_type = 'file'"
            f" AND r.relationship_type = '{RelationshipType.part_of.value}'"
            " AND r.removed_at IS NULL"
        )
    sql = (
        f"SELECT {place}, count(*), count(*) FILTER (WHERE EXISTS ("
        "SELECT 1 FROM share_requests sr WHERE sr.resource_type = 'file'"
        f" AND sr.resource_id = {file_id} AND sr.user_id = :user"
        " AND sr.status = 'pending'))"
        f" FROM {frm}"
        f" JOIN {PRESENCE_VIEW} ep ON ep.kind = 'file' AND ep.id = {file_id}"
        " AND NOT ep.trashed"
        f" WHERE {where}"
        f" AND NOT EXISTS (SELECT 1 FROM files f WHERE f.id = {file_id})"
        f" GROUP BY {place}"
    )
    rows = await session.exec(text(sql), params={"ids": list(ids), "user": user_id})  # noqa: S608
    return {place_id: (count, asked) for place_id, count, asked in rows.all()}


async def ask(
    session: AsyncSession,
    *,
    user: User,
    tool: Tool,
    resource_ids: list[int],
    level: ResourceAccessLevel,
    message: str | None,
) -> list[ShareRequest]:
    """Ask for each of ``resource_ids`` at ``level``, as one batch.

    One thing asked for alone is refused where the reader can't reach it,
    already holds the rung, or asked already; in a batch those are left out,
    and a batch left with nothing is refused. Rides the caller's transaction.
    """
    batch = uuid4()
    made: list[ShareRequest] = []
    refusal = ShareRequestMessages.NOTHING_TO_ASK
    for resource_id in resource_ids:
        standing = await standing_on(
            session, tool=tool, resource_id=resource_id, user_id=user.id
        )
        if standing is None:
            refusal = ShareRequestMessages.NOT_FOUND
            continue
        if standing.level is not None and standing.level.reaches(level):
            refusal = ShareRequestMessages.ALREADY_SHARED
            continue
        if standing.pending is not None:
            refusal = ShareRequestMessages.ALREADY_PENDING
            continue
        row = ShareRequest(
            initiative_id=standing.initiative_id,
            resource_type=tool,
            resource_id=resource_id,
            user_id=user.id,
            batch_id=batch,
            level=level.value,
            message=(message or "").strip() or None,
        )
        session.add(row)
        made.append(row)
    if not made:
        code = (
            status.HTTP_404_NOT_FOUND
            if refusal == ShareRequestMessages.NOT_FOUND
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=refusal)
    await session.flush()
    return made


async def tell_answerers(
    *,
    guild_id: int,
    requester: User,
    tool: Tool,
    requests: list[ShareRequest],
    place: tuple[str, int] | None,
) -> None:
    """Tell whoever answers these requests, once each: the owner of each
    thing, or the initiative's managers where it has none.

    On a system session routed into the community, which can see who that is
    and what the notice names; the requester's session can see neither. A
    notice about one thing names it; about several, it names the collection
    or wiki they were asked for from.
    """
    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.session import set_rls_context

    if not requests:
        return
    by_id = {r.resource_id: r for r in requests}
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        owners = dict(
            (
                await session.exec(
                    select(ResourceGrant.resource_id, ResourceGrant.user_id).where(
                        ResourceGrant.resource_type == tool.value,
                        ResourceGrant.resource_id.in_(list(by_id)),  # type: ignore[attr-defined]
                        ResourceGrant.level == ResourceAccessLevel.owner.value,
                        ResourceGrant.user_id.is_not(None),  # type: ignore[union-attr]
                    )
                )
            ).all()
        )
        answerers: dict[int, list[int]] = defaultdict(list)
        unowned = [rid for rid in by_id if rid not in owners]
        managers: dict[int, list[int]] = {}
        for rid in unowned:
            initiative_id = by_id[rid].initiative_id
            if initiative_id not in managers:
                managers[initiative_id] = await initiatives_service.manager_user_ids(
                    session, initiative_id=initiative_id
                )
            for uid in managers[initiative_id]:
                answerers[uid].append(rid)
        for rid, uid in owners.items():
            answerers[uid].append(rid)
        answerers.pop(requester.id, None)

        first = requests[0]
        name = await notifications_service.actor_name(session, requester)
        called = await names(
            session, [ref(r) for r in requests] + ([place] if place else [])
        )
        for uid, rids in answerers.items():
            about = (tool.value, rids[0]) if len(rids) == 1 or place is None else place
            await notifications_service.notify(
                session,
                NotificationType.share_requested,
                [uid],
                about=about,
                key=f"share.requested.{first.level}",
                values={
                    "requester": name,
                    "count": str(len(rids)),
                    "title": called.get(about, ""),
                },
                data={
                    "batch_id": str(first.batch_id),
                    "requester_id": requester.id,
                    "requester_name": name,
                    "level": first.level,
                    "count": len(rids),
                    "entity_type": about[0],
                    "entity_id": about[1],
                },
                actor=requester,
            )
        await session.commit()


async def answerable(
    session: AsyncSession,
    *,
    user_id: int,
    batch_id: UUID | None = None,
    tool: Tool | None = None,
    resource_id: int | None = None,
) -> list[ShareRequest]:
    """The pending requests the reader may answer — from one batch, or on one
    thing — oldest first. Row security keeps a request to its requester and
    whoever may share its resource; the requester's own are left out."""
    stmt = select(ShareRequest).where(
        ShareRequest.status == ShareRequestStatus.pending.value,
        ShareRequest.user_id != user_id,
        func.resource_shares(
            ShareRequest.resource_type,
            ShareRequest.resource_id,
            user_id,
            ShareRequest.initiative_id,
            standing_arg(),
        ),
    )
    if batch_id is not None:
        stmt = stmt.where(ShareRequest.batch_id == batch_id)
    if tool is not None and resource_id is not None:
        stmt = stmt.where(
            ShareRequest.resource_type == tool.value,
            ShareRequest.resource_id == resource_id,
        )
    return list(
        (
            await session.exec(stmt.order_by(ShareRequest.created_at, ShareRequest.id))
        ).all()  # type: ignore[arg-type]
    )


async def names(
    session: AsyncSession, refs: list[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """What each ``(kind, id)`` is called, as the session reads it."""
    by_kind: dict[str, set[int]] = defaultdict(set)
    for kind, rid in refs:
        by_kind[kind].add(rid)
    out: dict[tuple[str, int], str] = {}
    for kind, ids in by_kind.items():
        model = MODELS_BY_TABLE[ENDPOINT_KINDS[SearchEntityType(kind)].table]
        column = getattr(model, model.display_field())
        rows = await session.exec(select(model.id, column).where(model.id.in_(ids)))
        out.update({(kind, rid): name or "" for rid, name in rows.all()})
    return out


def ref(request: ShareRequest) -> tuple[str, int]:
    """What a request asks for, as a ``(kind, id)``."""
    return (Tool(request.resource_type).value, request.resource_id)


async def answer(
    session: AsyncSession,
    *,
    guild_id: int,
    answerer: User,
    request_ids: list[int],
    approve: bool,
    level: ResourceAccessLevel | None,
    scope: ShareRequestScope,
    tell: bool,
) -> list[ShareRequest]:
    """Answer the pending requests among ``request_ids`` the answerer may
    answer, and tell each requester where they are told.

    A yes shares each thing at ``level`` — the rung asked for where it is
    ``None`` — with the requester, or with every member of its initiative;
    an item guest is not one of those, so they are shared with by name as
    well. A grant already giving that much is left as it is. A no tells the
    requester only where ``tell`` asks. Rides the caller's transaction.
    """
    found = [
        r
        for r in await answerable(session, user_id=answerer.id)
        if r.id in set(request_ids)
    ]
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ShareRequestMessages.CANNOT_ANSWER,
        )
    # Whose initiatives a share with the whole initiative reaches.
    memberships = set(
        (
            await session.exec(
                select(InitiativeMember.user_id, InitiativeMember.initiative_id).where(
                    InitiativeMember.user_id.in_({r.user_id for r in found})  # type: ignore[attr-defined]
                )
            )
        ).all()
    )
    now = datetime.now(timezone.utc)
    for r in found:
        tool = Tool(getattr(r.resource_type, "value", r.resource_type))
        r.resolved_at = now
        r.resolved_by = answerer.id
        if not approve:
            r.status = ShareRequestStatus.declined.value
            session.add(r)
            continue
        given = level or ResourceAccessLevel(r.level)
        everyone = scope is ShareRequestScope.initiative
        await permissions_service.share_with(
            session,
            resource_type=tool,
            resource_id=r.resource_id,
            guild_id=guild_id,
            initiative_id=r.initiative_id,
            user_id=None if everyone else r.user_id,
            level=given,
            actor_user_id=answerer.id,
            raise_lower=True,
        )
        if everyone and (r.user_id, r.initiative_id) not in memberships:
            await permissions_service.share_with(
                session,
                resource_type=tool,
                resource_id=r.resource_id,
                guild_id=guild_id,
                initiative_id=r.initiative_id,
                user_id=r.user_id,
                level=given,
                actor_user_id=answerer.id,
                raise_lower=True,
            )
        r.status = ShareRequestStatus.approved.value
        r.granted_level = given.value
        r.scope = scope.value
        session.add(r)
    await session.flush()

    if approve or tell:
        name = await notifications_service.actor_name(session, answerer)
        called = await names(session, [ref(r) for r in found])
        by_requester: dict[int, list[ShareRequest]] = defaultdict(list)
        for r in found:
            by_requester[r.user_id].append(r)
        for requester_id, rows in by_requester.items():
            first = rows[0]
            kind = str(getattr(first.resource_type, "value", first.resource_type))
            await notifications_service.notify(
                session,
                NotificationType.share_granted
                if approve
                else NotificationType.share_declined,
                [requester_id],
                # Somebody declined can't open it, so that notice names nothing.
                about=(kind, first.resource_id) if approve else None,
                key=(
                    f"share.granted.{first.granted_level}"
                    if approve
                    else "share.declined"
                ),
                values={
                    "answerer": name,
                    "count": str(len(rows)),
                    "title": called.get(ref(first), ""),
                },
                data={
                    "answerer_name": name,
                    "level": first.granted_level,
                    "count": len(rows),
                    **(
                        {"entity_type": kind, "entity_id": first.resource_id}
                        if approve
                        else {}
                    ),
                },
                actor=answerer,
            )
    return found
