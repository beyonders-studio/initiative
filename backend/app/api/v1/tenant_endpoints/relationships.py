"""One surface for how things connect.

Replaces the per-tool attach endpoints — a project's files, an event's
files — which said the same thing about each pair of kinds. What varies
between them is which two kinds are named, and that is a parameter.

**What a write asks is the table's to decide, not this router's.** RLS gates
both endpoints on every statement, per type: write on the end an edge describes
and read on the other, or read on both where it describes neither. So a caller
who cannot reach an end gets a 404 from the lookup below, and one who can reach
but not edit gets nothing written.

Two rules the per-tool endpoints applied that the policy deliberately does not,
carried over because they belong to the surface rather than to the table. They
live in ``relationships.link``, so a link made anywhere else on a person's
behalf answers to them too:

* **Both ends of a link made here are in one initiative.** The table permits a
  cross-initiative edge — that is where the graph gets its reach, and content
  references will make them — but choosing one in a picker is not how they
  should arrive.
* **An archived thing takes no new links, and gives none up.** Archiving is a
  statement that a project is finished with, and the policy has no opinion on
  it. Asked of whichever end has the state — only projects and tasks do.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import union
from sqlmodel import select

from app.api.deps import (
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.messages import RelationshipMessages
from app.core.relationships import (
    ENDPOINT_KINDS,
    PERSON,
    EndpointKind,
    Provenance,
    RelationshipType,
    node_id,
)
from app.core.search import SearchEntityType
from app.db import reference_targets
from app.models.platform.user import User
from app.models.tenant._mixins import ActorKind
from app.models.tenant.project import Project
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.relationship import (
    EndpointRef,
    LinkedTaskRead,
    NeighbourhoodEdge,
    NeighbourhoodNode,
    NeighbourhoodRead,
    RelatedEnd,
    RelationshipCreate,
    RelationshipRead,
    TaskEdgeRead,
    TaskEdgesRead,
)
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint

router = APIRouter()


def _parse_ref(value: str) -> EndpointRef:
    """``task:12`` as the reference vocabulary already spells it.

    The thing asked about is an item, never a person: nothing lists everything
    that links to somebody, so a person's links are read from each item's side.
    """
    kind, _, raw_id = value.partition(":")
    try:
        entity_type = EndpointKind(kind)
        entity_id = int(raw_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.BAD_ENDPOINT,
        ) from None
    if entity_type not in ENDPOINT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.BAD_ENDPOINT,
        )
    return EndpointRef(type=entity_type, id=entity_id)


def _related_end(
    kind: EndpointKind, entity_id: int, found: reference_targets.Resolved
) -> RelatedEnd:
    """A far end as the wire carries it."""
    return RelatedEnd(
        type=kind,
        id=entity_id,
        title=found.title,
        initiative_id=found.initiative_id,
        updated_at=found.updated_at,
        tool=found.tool,
        tool_id=found.tool_id,
        tool_title=found.tool_title,
        image_urls=found.image_urls,
        icon=found.icon,
        color=found.color,
        file_type=found.file_type,
        mime_type=found.mime_type,
        original_filename=found.original_filename,
        smart_link_url=found.smart_link_url,
        handle=found.handle,
        is_open=found.is_open,
        starts_at=found.starts_at,
    )


def _render(
    row: EntityRelationship,
    *,
    anchor: Endpoint,
    titles: dict[tuple[str, int], reference_targets.Resolved],
) -> RelationshipRead | None:
    """One edge from the asking entity's side, or None if its far end is gone.

    A far end that does not resolve is one in the trash. A link to something
    only the trash holds is nothing to offer, and the caller's next click would
    404 on it.
    """
    outbound = row.source_node == anchor.node
    other_type = row.target_type if outbound else row.source_type
    other_id = row.target_id if outbound else row.source_id
    found = titles.get((other_type, other_id))
    if found is None:
        return None
    return RelationshipRead(
        id=row.id,
        relationship_type=RelationshipType(row.relationship_type),
        direction="outbound" if outbound else "inbound",
        other=_related_end(EndpointKind(other_type), other_id, found),
        provenance=row.provenance,
        confidence=row.confidence,
        created_by=row.created_by,
        created_by_kind=row.created_by_kind,
        created_at=row.created_at,
    )


async def _titles_for(
    session: RLSSessionDep,
    rows: list[EntityRelationship],
    anchor: Endpoint,
    user_id: int,
) -> dict[tuple[str, int], reference_targets.Resolved]:
    """Resolve every far end named by a page of edges — one query per kind.

    A far end that resolves to nothing is one in the trash, and
    :func:`_render` leaves the edge out.
    """
    wanted: dict[str, list[int]] = {}
    for row in rows:
        outbound = row.source_node == anchor.node
        kind = row.target_type if outbound else row.source_type
        entity_id = row.target_id if outbound else row.source_id
        wanted.setdefault(kind, []).append(entity_id)

    found: dict[tuple[str, int], reference_targets.Resolved] = {}
    for kind, ids in wanted.items():
        resolved = await reference_targets.resolve_many(
            session, EndpointKind(kind), ids, user_id=user_id
        )
        for entity_id, row in resolved.items():
            found[(kind, entity_id)] = row
    return found


@router.get("/", response_model=list[RelationshipRead])
async def list_relationships(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity: str = Query(description="The thing to list edges for, as `kind:id`"),
    relationship_type: RelationshipType | None = Query(default=None),
    other_type: EndpointKind | None = Query(default=None),
    direction: relationships_service.Direction = Query(default="both"),
) -> list[RelationshipRead]:
    """Every live edge touching one thing, rendered from its side.

    ``direction=inbound`` is "what links here": the things naming this one,
    rather than the things it names.
    """
    ref = _parse_ref(entity)
    anchor = Endpoint(ref.type, ref.id)
    await relationships_service.resolve(session, anchor, current_user.id)

    rows = await relationships_service.list_for_entity(
        session,
        anchor,
        relationship_type=relationship_type,
        other_kind=other_type,
        direction=direction,
    )
    rows.sort(key=lambda r: (r.created_at, r.id or 0))
    titles = await _titles_for(session, rows, anchor, current_user.id)
    return [
        rendered
        for rendered in (_render(row, anchor=anchor, titles=titles) for row in rows)
        if rendered is not None
    ]


@router.get("/tasks", response_model=TaskEdgesRead)
async def list_task_edges(
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    project_id: int = Query(description="The project whose tasks' edges to list"),
) -> TaskEdgesRead:
    """Every live edge from or to a task of a project, to another task the
    reader can open, and those of the tasks it reaches that are another
    project's: what a Gantt draws its arrows, nesting and outside rows from."""
    task_ids = set(
        (await session.exec(select(Task.id).where(Task.project_id == project_id))).all()
    )
    nodes = [node_id(SearchEntityType.task, task_id) for task_id in task_ids]
    if not nodes:
        return TaskEdgesRead(edges=[], others=[])

    def arm(anchor):
        return select(
            EntityRelationship.id,
            EntityRelationship.source_id,
            EntityRelationship.target_id,
            EntityRelationship.relationship_type,
        ).where(
            anchor.in_(nodes),
            EntityRelationship.source_type == SearchEntityType.task.value,
            EntityRelationship.target_type == SearchEntityType.task.value,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )

    # Oldest first: a task part of several is nested under the first, as
    # ``task_hierarchy`` reads its parent.
    rows = sorted(
        (
            await session.exec(
                union(
                    arm(EntityRelationship.source_node),
                    arm(EntityRelationship.target_node),
                )
            )
        ).all(),
        key=lambda row: row[0],
    )
    outside = {end for _, *ends, _ in rows for end in ends if end not in task_ids}
    others = (
        (
            await session.exec(
                select(
                    Task.id,
                    Task.title,
                    Task.start_date,
                    Task.due_date,
                    Task.project_id,
                    Project.name,
                    Project.initiative_id,
                    TaskStatus.category,
                )
                .join(Project, Project.id == Task.project_id)
                .join(TaskStatus, TaskStatus.id == Task.task_status_id)
                .where(Task.id.in_(outside))  # type: ignore[union-attr]
            )
        ).all()
        if outside
        else []
    )
    return TaskEdgesRead(
        edges=[
            TaskEdgeRead(
                id=id, source_id=source, target_id=target, relationship_type=kind
            )
            for id, source, target, kind in rows
        ],
        others=[
            LinkedTaskRead(
                id=task,
                title=title,
                start_date=start,
                due_date=due,
                project_id=project,
                project_name=name,
                initiative_id=initiative,
                done=category == TaskStatusCategory.done,
            )
            for task, title, start, due, project, name, initiative, category in others
        ],
    )


@router.get("/neighbourhood", response_model=NeighbourhoodRead)
async def get_relations_neighbourhood(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity: str = Query(description="The thing at the centre, as `kind:id`"),
    hops: int = Query(
        default=1,
        ge=1,
        le=relationships_service.MAX_NEIGHBOURHOOD_HOPS,
        description="How many links out to walk",
    ),
    include_tags: bool = Query(
        default=False, description="Walk through labels as well"
    ),
) -> NeighbourhoodRead:
    """Everything within some hops of one thing, in one request.

    What a graph of a thing's links draws. Each hop walks on from at most
    forty things, the earliest linked first, and every edge and far end is
    gated exactly as the per-entity list is.
    """
    ref = _parse_ref(entity)
    start = Endpoint(ref.type, ref.id)
    await relationships_service.resolve(session, start, current_user.id)

    walked = await relationships_service.neighbourhood(
        session,
        start,
        hops=hops,
        include_tags=include_tags,
        user_id=current_user.id,
    )
    return NeighbourhoodRead(
        nodes=[
            NeighbourhoodNode(
                end=_related_end(end.kind, end.id, walked.ends[end]), depth=depth
            )
            for end, depth in walked.depths.items()
        ],
        edges=[
            NeighbourhoodEdge(
                id=crossing.row.id,  # type: ignore[arg-type]
                relationship_type=RelationshipType(crossing.row.relationship_type),
                anchor=EndpointRef(type=crossing.anchor.kind, id=crossing.anchor.id),
                other=EndpointRef(type=crossing.other.kind, id=crossing.other.id),
                direction=(
                    "outbound"
                    if crossing.row.source_node == crossing.anchor.node
                    else "inbound"
                ),
                provenance=crossing.row.provenance,
            )
            for crossing in walked.edges
        ],
    )


@router.post("/", response_model=RelationshipRead, status_code=status.HTTP_201_CREATED)
async def create_relationship(
    body: RelationshipCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RelationshipRead:
    """Record one edge. 409 if it is already there."""
    row = await relationships_service.link(
        session,
        relationships_service.Link(
            source=Endpoint(body.source.type, body.source.id),
            relationship_type=body.relationship_type,
            target=Endpoint(body.target.type, body.target.id),
        ),
        user_id=current_user.id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=RelationshipMessages.EXISTS,
        )
    await session.commit()

    anchor = Endpoint(body.source.type, body.source.id)
    titles = await _titles_for(session, [row], anchor, current_user.id)
    made = _render(row, anchor=anchor, titles=titles)
    if made is None:
        # Both ends resolved a moment ago, so this is the far end having gone
        # into the trash in between.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RelationshipMessages.ENDPOINT_NOT_FOUND,
        )
    return made


@router.put("/", response_model=list[RelationshipRead])
async def replace_relationship_slice(
    ids: list[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity: str = Query(description="The thing whose edges are being set"),
    relationship_type: RelationshipType = Query(),
    other_type: EndpointKind = Query(),
) -> list[RelationshipRead]:
    """Replace one slice of an entity's edges — what a multi-select does.

    Every id named has to resolve for this caller, so a slice cannot be used to
    attach something out of reach. What is dropped is deleted rather than
    remembered: a replace is the surface restating a set, not a person taking
    one link back.
    """
    ref = _parse_ref(entity)
    anchor = Endpoint(ref.type, ref.id)

    # A replace is a bulk removal, so everything it drops answers the same
    # question a single removal does. One edge the caller may not remove fails
    # the whole request rather than being quietly kept, so the surface never
    # shows a set it did not ask for.
    keeping = set(ids)
    for row in await relationships_service.list_for_entity(
        session, anchor, relationship_type=relationship_type, other_kind=other_type
    ):
        other_id = row.target_id if row.source_node == anchor.node else row.source_id
        if other_id in keeping:
            continue
        if not await _may_remove(session, row, current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=RelationshipMessages.REMOVE_DENIED,
            )

    await relationships_service.set_related(
        session,
        anchor,
        relationship_type=relationship_type,
        other_kind=other_type,
        ids=ids,
        user_id=current_user.id,
    )
    await session.commit()

    rows = await relationships_service.list_for_entity(
        session, anchor, relationship_type=relationship_type, other_kind=other_type
    )
    rows.sort(key=lambda r: (r.created_at, r.id or 0))
    titles = await _titles_for(session, rows, anchor, current_user.id)
    return [
        rendered
        for rendered in (_render(row, anchor=anchor, titles=titles) for row in rows)
        if rendered is not None
    ]


@router.delete("/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_relationship(
    relationship_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Take an edge back.

    Your own edge, or one on a thing you can edit. Guarded here rather than by
    the policy, because the rule for making a link and the rule for undoing
    somebody else's are different questions, and a policy answers per statement
    rather than per author.

    An edge derived from content is not one to take back at all: what it says
    is what a body says, and the way to change that is to edit the body.
    """
    row = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.id == relationship_id,
                EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RelationshipMessages.NOT_FOUND,
        )

    if row.provenance != Provenance.manual.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.DERIVED,
        )
    if not await _may_remove(session, row, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=RelationshipMessages.REMOVE_DENIED,
        )

    await relationships_service.remove(session, row, removed_by=current_user.id)
    await session.commit()


async def _may_remove(
    session: RLSSessionDep, row: EntityRelationship, user_id: int
) -> bool:
    """Whether this caller may take one edge back.

    Your own edge, or one on a thing you can edit. The single removal and the
    replace both ask this, so a slice cannot do what a DELETE refuses. A
    person's end is never the thing you can edit.
    """
    if row.created_by_kind == ActorKind.member and row.created_by == user_id:
        return True
    for kind, entity_id in (
        (row.source_type, row.source_id),
        (row.target_type, row.target_id),
    ):
        if kind == PERSON.value:
            continue
        end = EndpointKind(kind)
        writable = await session.exec(
            reference_targets.visible_ids(end, user_id, need_write=True).where(
                reference_targets.id_column(end) == entity_id
            )
        )
        if writable.first() is not None:
            return True
    return False
