"""Reading and writing edges.

The table records; this module is where the shape is read. It refuses exactly
two things — an edge from a thing to itself, and a type nothing knows — and
otherwise stores what it is given, from whatever provenance. A loop between two
people's tasks is a fact about their work; a task somebody wants in two epics is
an ambiguity worth recording. Neither is this layer's business to prevent, and
both are a picker's business to warn about (see :func:`walk`).

Who may write an edge is the table's to decide: RLS gates both endpoints on
every statement. A link a person makes also answers to the rules of the surface
— both ends readable, in one initiative, neither archived, a directional link
written by its source, a link to a person written by the item on its other end
and naming somebody in the community — and :func:`link` is where those live, so
every writer of one goes through the same door. The *removal* rule — your own
edge, or one on a resource you can write — belongs to the endpoint, which is
where the resource and the caller's access to it are already in hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Iterable, Literal, Sequence

from fastapi import HTTPException, status
from sqlalchemy import text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import RelationshipMessages
from app.core.relationships import (
    DERIVED_TYPES,
    ENDPOINT_KINDS,
    PERSON,
    SPECS,
    EndpointKind,
    Related,
    Provenance,
    RelationshipType,
    is_symmetric,
    is_transitive,
    node_id,
)
from app.core.search import SearchEntityType
from app.db import reference_targets
from app.db.session import install_context, require_actor_context
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import named_people

#: How deep a walk may go, whatever it is asked for. A graph that permits cycles
#: needs this even with the CYCLE clause below, because a mixed-type path can
#: revisit a node the clause is not tracking.
MAX_WALK_DEPTH = 10

#: Which way an edge runs relative to the thing being asked about. ``inbound``
#: is the "what links here" question a backlinks panel asks.
Direction = Literal["inbound", "outbound", "both"]


@dataclass(frozen=True)
class Endpoint:
    """One end of an edge: what kind of thing, and which one."""

    kind: EndpointKind
    id: int

    @property
    def node(self) -> int:
        return node_id(self.kind, self.id)


def _ordered(
    source: Endpoint, target: Endpoint, relationship_type: RelationshipType
) -> tuple[Endpoint, Endpoint]:
    """The pair as it is stored.

    A symmetric relation describes neither end, so there is no source to choose
    — the row is stored once with the lower node id first, and the CHECK
    constraint says the same thing. A directional one is stored as given,
    because its source is the end it describes.
    """
    if is_symmetric(relationship_type) and target.node < source.node:
        return target, source
    return source, target


class SelfLoop(ValueError):
    """An edge from a thing to itself. No relation here means anything by it."""


class NotTransitive(ValueError):
    """A multi-hop walk was asked for along a relation that does not chain."""


async def create(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    target: Endpoint,
    provenance: Provenance = Provenance.manual,
    confidence: float | None = None,
    created_by: int | None = None,
) -> EntityRelationship | None:
    """Record one edge, or return None if it is already there.

    ``provenance`` is the caller's to state and a request's never: it is the
    weight any future scoring reads, and it decides whether a removal is
    remembered. The API hands this ``manual``; the content sync hands it
    ``content``; only the accept path hands it ``inferred``.
    """
    if source.node == target.node:
        raise SelfLoop(f"{source.kind.value}:{source.id} cannot relate to itself")

    stored_source, stored_target = _ordered(source, target, relationship_type)
    existing = await find(
        session,
        source=stored_source,
        relationship_type=relationship_type,
        target=stored_target,
    )
    if existing is not None:
        return None

    row = EntityRelationship(
        source_type=stored_source.kind.value,
        source_id=stored_source.id,
        relationship_type=relationship_type.value,
        target_type=stored_target.kind.value,
        target_id=stored_target.id,
        provenance=provenance.value,
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
    )
    if created_by is not None:
        row.created_by = created_by
    session.add(row)
    await session.flush()
    return row


class Refused(HTTPException):
    """A link the surface does not make, with the reason a caller can act on."""


@dataclass(frozen=True)
class Link:
    """One link to make on somebody's behalf."""

    source: Endpoint
    relationship_type: RelationshipType
    target: Endpoint
    provenance: Provenance = Provenance.manual
    confidence: float | None = None


async def link(
    session: AsyncSession, made: Link, *, user_id: int | None
) -> EntityRelationship | None:
    """Make one link on a person's behalf, or return None if it is already there.

    Asks everything the relationships surface asks before :func:`create`
    stores the row, and raises :class:`Refused` for what it will not make.
    """
    refuse_derived(made.relationship_type)
    ends = await _resolve_ends(session, [made], user_id)
    writable = await _writable_ends(session, [made], user_id)
    _refuse_link(made, ends, writable)
    try:
        return await _create_link(session, made, user_id)
    except SelfLoop:
        raise Refused(
            status_code=status.HTTP_400_BAD_REQUEST, detail=RelationshipMessages.SELF
        ) from None


async def link_many(
    session: AsyncSession, links: Sequence[Link], *, user_id: int | None
) -> None:
    """:func:`link` for a batch, leaving behind each link it would refuse.

    The ends are resolved, and the written ends' access asked, once per kind
    for the whole batch rather than once per link.
    """
    ends = await _resolve_ends(session, links, user_id)
    writable = await _writable_ends(session, links, user_id)
    for made in links:
        try:
            refuse_derived(made.relationship_type)
            _refuse_link(made, ends, writable)
            await _create_link(session, made, user_id)
        except (Refused, SelfLoop):
            continue


async def _create_link(
    session: AsyncSession, made: Link, user_id: int | None
) -> EntityRelationship | None:
    return await create(
        session,
        source=made.source,
        relationship_type=made.relationship_type,
        target=made.target,
        provenance=made.provenance,
        confidence=made.confidence,
        created_by=user_id,
    )


def _refuse_link(
    made: Link,
    ends: dict[int, reference_targets.Resolved],
    writable: set[int],
) -> None:
    """The surface's rules for one link, over ends already resolved.

    A directional link is the source's to make. Direction is chosen so the
    source is the end an edge describes, which is what makes "who may write
    this" derivable: changing what is said *about* something asks to change
    that thing. A symmetric link describes neither end and asks only that both
    be readable, which resolving them already proved. A link to a person
    describes the item on its other end, whatever its type (see
    :func:`_written_end`). The table says the same thing and would refuse the
    write on its own; asking here is so the refusal arrives with a name the
    caller can act on.
    """
    if made.source.kind == PERSON.value and made.target.kind == PERSON.value:
        raise Refused(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.BETWEEN_PEOPLE,
        )
    source_row = ends.get(made.source.node)
    target_row = ends.get(made.target.node)
    if source_row is None or target_row is None:
        raise Refused(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RelationshipMessages.ENDPOINT_NOT_FOUND,
        )
    refuse_across_initiatives(source_row, target_row)
    refuse_archived(source_row, target_row)
    written = _written_end(made)
    if written is not None and written.node not in writable:
        raise Refused(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=RelationshipMessages.ITEM_NOT_WRITABLE
            if PERSON.value in (made.source.kind, made.target.kind)
            else RelationshipMessages.SOURCE_NOT_WRITABLE,
        )


def _written_end(made: Link) -> Endpoint | None:
    """The end making this link changes, if it changes either.

    The source of a directional link, and the item beside a person whatever the
    type: "this task depends on Jane" says something about the task. A person's
    end is never it. A link between two people has none, and is refused.
    """
    if made.target.kind == PERSON.value:
        return None if made.source.kind == PERSON.value else made.source
    if made.source.kind == PERSON.value:
        return made.target
    return None if is_symmetric(made.relationship_type) else made.source


async def _resolve_ends(
    session: AsyncSession, links: Sequence[Link], user_id: int | None
) -> dict[int, reference_targets.Resolved]:
    """Every end the reader may open, by node id: one query per kind."""
    wanted: dict[EndpointKind, list[int]] = {}
    for made in links:
        for end in (made.source, made.target):
            wanted.setdefault(end.kind, []).append(end.id)
    found: dict[int, reference_targets.Resolved] = {}
    for kind, ids in wanted.items():
        for entity_id, row in (await _linkable(session, kind, ids, user_id)).items():
            found[node_id(kind, entity_id)] = row
    return found


async def _linkable(
    session: AsyncSession, kind: EndpointKind, ids: Sequence[int], user_id: int | None
) -> dict[int, reference_targets.Resolved]:
    """The ends of one kind a link made for this reader may name, by id.

    A person has to be in the community, guests included while they are in, as
    the reader reads its roster; anyone else is absent, as an end the reader
    cannot open is.
    """
    if kind == PERSON.value:
        ids = sorted(await named_people.members(session, ids))
    return await reference_targets.resolve_many(session, kind, ids, user_id=user_id)


async def _writable_ends(
    session: AsyncSession, links: Sequence[Link], user_id: int | None
) -> set[int]:
    """The ends these links change (:func:`_written_end`) that the reader may
    edit, by node id: one query per kind."""
    wanted: dict[EndpointKind, set[int]] = {}
    for made in links:
        written = _written_end(made)
        if written is not None:
            wanted.setdefault(written.kind, set()).add(written.id)
    writable: set[int] = set()
    for kind, ids in wanted.items():
        rows = await session.exec(
            reference_targets.visible_ids(kind, user_id, need_write=True).where(
                reference_targets.id_column(kind).in_(ids)
            )
        )
        writable.update(node_id(kind, row[0]) for row in rows.all())
    return writable


async def resolve(
    session: AsyncSession, end: Endpoint, user_id: int | None
) -> reference_targets.Resolved:
    """The row behind one end, or a 404.

    Asked through ``visible_ids``, which joins the row to whatever governs it
    and calls ``resource_access`` — the same function the tables' own
    policies call. A thing the caller cannot open is absent rather than
    forbidden, which is what every other read here does with one.
    """
    resolved = await reference_targets.resolve_one(
        session, end.kind, end.id, user_id=user_id
    )
    if resolved is None:
        raise Refused(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RelationshipMessages.ENDPOINT_NOT_FOUND,
        )
    return resolved


def refuse_across_initiatives(
    a: reference_targets.Resolved, b: reference_targets.Resolved
) -> None:
    """Both ends of a link a person makes belong to the same place.

    Two things can have no initiative, and they are not the same thing:

    * A **tag** belongs to none by its nature — it is the guild's own
      vocabulary, which every initiative shares. It pairs with anything the
      guild holds.
    * An **event on a guild calendar** belongs to none because that is what a
      guild calendar is: an event takes its initiative from its calendar, and a
      guild calendar has none. So it is guild-level content, and initiative
      content is not its to link.

    What tells them apart is whether the KIND belongs to initiatives at all:
    ``calendar_events`` does and this row does not, where ``tags`` never does.
    """
    if a.initiative_id == b.initiative_id:
        return
    guild_vocabulary = any(
        end.initiative_id is None and not end.scoped_kind for end in (a, b)
    )
    if guild_vocabulary:
        return
    raise Refused(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=RelationshipMessages.CROSS_INITIATIVE,
    )


def refuse_archived(*ends: reference_targets.Resolved) -> None:
    """An archived thing is finished with, and its links are part of what it
    says. Asked of both ends, and of a removal as much as an addition."""
    for end in ends:
        if end.archived:
            raise Refused(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=RelationshipMessages.ENDPOINT_ARCHIVED,
            )


def refuse_derived(relationship_type: RelationshipType) -> None:
    """Some links are nobody's to make by hand.

    A ``references`` edge is read out of a body when it is saved, so asserting
    one here would state something no sentence says — and the next save would
    take it straight back out. Writing the sentence is how you make one.
    """
    if relationship_type in DERIVED_TYPES:
        raise Refused(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.DERIVED,
        )


async def create_many(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    targets: Sequence[Endpoint],
    provenance: Provenance,
    created_by: int | None = None,
) -> None:
    """Record several edges from one thing, skipping any already there.

    One statement, and the database decides what is new: two people saving at
    the same moment can each read no edge and each go on to write it, and the
    second one arriving is the answer being already correct rather than a
    failure. :func:`create` answers one at a time and reports the clash, which
    is what a person making a link by hand needs to be told.

    Self-loops are dropped rather than refused, for the same reason: a body
    naming its own page is ordinary.
    """
    rows = [
        {
            "source_type": source.kind.value,
            "source_id": source.id,
            "relationship_type": relationship_type.value,
            "target_type": target.kind.value,
            "target_id": target.id,
            "provenance": provenance.value,
            "created_at": datetime.now(timezone.utc),
            "created_by": created_by,
        }
        for target in _ordered_many(source, relationship_type, targets)
    ]
    if not rows:
        return
    await session.exec(
        pg_insert(EntityRelationship).values(rows).on_conflict_do_nothing()
    )
    await session.flush()


def _ordered_many(
    source: Endpoint, relationship_type: RelationshipType, targets: Sequence[Endpoint]
) -> list[Endpoint]:
    """The far ends worth writing — everything but the source itself.

    A symmetric relation has no source to keep, so this is only for the
    directional ones; :func:`create` is the door a symmetric edge comes through.
    """
    if is_symmetric(relationship_type):
        raise ValueError(
            f"{relationship_type.value} is stored in node-id order, so a batch "
            "from one source is not how it is written"
        )
    return [target for target in targets if target.node != source.node]


async def find(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    target: Endpoint,
) -> EntityRelationship | None:
    """The live edge for this exact triple, if there is one."""
    stored_source, stored_target = _ordered(source, target, relationship_type)
    result = await session.exec(
        select(EntityRelationship).where(
            EntityRelationship.source_node == stored_source.node,
            EntityRelationship.relationship_type == relationship_type.value,
            EntityRelationship.target_node == stored_target.node,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )
    )
    return result.first()


async def remove(
    session: AsyncSession,
    row: EntityRelationship,
    *,
    removed_by: int | None,
    tombstone: bool = True,
) -> None:
    """Take an edge back.

    A person unlinking two things they had linked is the one negative signal
    nothing else in the schema records, so a manual removal keeps the row and
    marks it. An edge withdrawn because the sentence that implied it was edited
    asserts nothing and is deleted outright — counting ordinary editing as "these
    are not related" would bury the real signal in noise shaped exactly like it.
    """
    if tombstone and row.provenance == Provenance.manual.value:
        row.removed_at = datetime.now(timezone.utc)
        row.removed_by = removed_by
        session.add(row)
    else:
        await session.exec(
            delete(EntityRelationship).where(EntityRelationship.id == row.id)  # type: ignore[arg-type]
        )
    await session.flush()


async def list_for_entity(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType | None = None,
    other_kind: EndpointKind | None = None,
    direction: Direction = "both",
) -> list[EntityRelationship]:
    """Every live edge touching this entity, from either side.

    Two anchored index seeks unioned, never ``WHERE source = x OR target = x``:
    the OR form can use neither index and degrades to a scan of the table, and a
    scan happens *before* the policy has narrowed anything. Both directions are
    genuinely needed by default — a symmetric edge is stored in node-id order,
    so a given file sits on whichever side sorted lower.

    ``direction`` narrows to one side for the relations where the two sides are
    different questions: what this file names is one list, and what names
    it is another.
    """

    def arm(column, other_column):
        stmt = select(EntityRelationship).where(
            column == entity.node,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )
        if relationship_type is not None:
            stmt = stmt.where(
                EntityRelationship.relationship_type == relationship_type.value
            )
        if other_kind is not None:
            stmt = stmt.where(other_column == other_kind.value)
        return stmt

    rows: list[EntityRelationship] = []
    if direction in ("outbound", "both"):
        found = await session.exec(
            arm(EntityRelationship.source_node, EntityRelationship.target_type)
        )
        rows.extend(found.all())
    if direction in ("inbound", "both"):
        found = await session.exec(
            arm(EntityRelationship.target_node, EntityRelationship.source_type)
        )
        rows.extend(found.all())
    return rows


async def related_for_many(
    session: AsyncSession,
    kind: SearchEntityType,
    entity_ids: Sequence[int],
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
    model: type | None = None,
) -> dict[int, list[Related]]:
    """The far ends of one relation, for many entities at once.

    **Two queries, whatever the page size.** This is the helper every list page
    goes through, so it is written to be flat in N rather than convenient: one
    UNION ALL over the two anchored indexes for the edges, one ``IN`` for the
    entities they name. Fetching per row instead would put a query per card on
    a page that already shows dozens.

    Both queries are gated. The edge query ANDs both endpoints, so an id only
    comes back if the reader clears the far end as well; the entity query then
    passes through that kind's own policies. A far end the reader cannot open
    yields ``Related.entity is None`` and the caller renders nothing for it.
    """
    nodes = [node_id(kind, entity_id) for entity_id in entity_ids]
    if not nodes:
        return {}

    columns = (
        EntityRelationship.source_node,
        EntityRelationship.source_id,
        EntityRelationship.target_node,
        EntityRelationship.target_id,
        EntityRelationship.created_at,
    )

    def arm(anchor, other_kind_column):
        return select(*columns).where(
            anchor.in_(nodes),
            EntityRelationship.relationship_type == relationship_type.value,
            other_kind_column == other_kind.value,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )

    rows = (
        await session.exec(
            union_all(
                arm(EntityRelationship.source_node, EntityRelationship.target_type),
                arm(EntityRelationship.target_node, EntityRelationship.source_type),
            )
        )
    ).all()

    ours = set(nodes)
    edges: list[tuple[int, int, datetime]] = []
    for source_node, source_id, target_node, target_id, created_at in rows:
        if source_node in ours:
            edges.append((source_node, target_id, created_at))
        else:
            edges.append((target_node, source_id, created_at))

    entities: dict[int, object] = {}
    if model is not None and edges:
        found = await session.exec(
            select(model).where(
                model.id.in_({other for _, other, _ in edges})  # type: ignore[attr-defined]
            )
        )
        entities = {row.id: row for row in found.all()}

    grouped: dict[int, list[Related]] = {entity_id: [] for entity_id in entity_ids}
    by_node = {node_id(kind, entity_id): entity_id for entity_id in entity_ids}
    for node, other_id, created_at in sorted(edges, key=lambda e: e[2]):
        grouped[by_node[node]].append(
            Related(id=other_id, entity=entities.get(other_id), linked_at=created_at)
        )
    return grouped


async def counts_for_many(
    session: AsyncSession,
    kind: SearchEntityType,
    entity_ids: Sequence[int],
    *,
    relationship_type: RelationshipType,
) -> dict[int, int]:
    """How many things of ANY kind a relation connects each entity to.

    The counting form of :func:`related_for_many`, and one query rather than its
    two: a count needs no far end resolved. No ``other_kind`` on purpose — a
    surface that says "3 attachments" means three things, not three files
    and separately two tasks, and the far ends may be any of the fourteen kinds.

    Gated the same way: the policy ANDs both endpoints, so something the reader
    cannot open is not counted at them.
    """
    nodes = [node_id(kind, entity_id) for entity_id in entity_ids]
    counted = {entity_id: 0 for entity_id in entity_ids}
    if not nodes:
        return counted

    def arm(anchor):
        return select(anchor.label("anchor")).where(
            anchor.in_(nodes),
            EntityRelationship.relationship_type == relationship_type.value,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )

    rows = (
        await session.exec(
            union_all(
                arm(EntityRelationship.source_node),
                arm(EntityRelationship.target_node),
            )
        )
    ).all()

    by_node = {node_id(kind, entity_id): entity_id for entity_id in entity_ids}
    for (node,) in rows:
        # A symmetric edge is stored once, so neither arm double-counts it —
        # but an edge between two of the entities asked about is one link for
        # each of them, and both arms are meant to see it.
        counted[by_node[node]] += 1
    return counted


async def related_for(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
    model: type | None = None,
) -> list[Related]:
    """:func:`related_for_many` for one entity — the same two queries."""
    grouped = await related_for_many(
        session,
        entity.kind,
        [entity.id],
        relationship_type=relationship_type,
        other_kind=other_kind,
        model=model,
    )
    return grouped.get(entity.id, [])


async def related_ids(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
) -> list[int]:
    """Ids of one kind connected to this entity by one type.

    What the per-tool read schemas ask for: a project's attached files. Order
    is by when the edge was made, which is the order the junctions produced.
    """
    rows = await list_for_entity(
        session,
        entity,
        relationship_type=relationship_type,
        other_kind=other_kind,
    )
    rows.sort(key=lambda r: (r.created_at, r.id or 0))
    return [r.target_id if r.source_node == entity.node else r.source_id for r in rows]


async def set_related(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType,
    other_kind: EndpointKind,
    ids: Sequence[int],
    user_id: int | None,
) -> None:
    """Replace one slice of an entity's edges on a person's behalf — what a
    multi-select dialog does.

    Asks of the entity and of every id named what :func:`link` asks of a link's
    two ends: each resolves for this reader, a person is in the community, they
    share an initiative, and neither is archived. Who may drop an edge is the
    caller's to ask first.

    Removing here is a plain delete rather than a tombstone: a replace is the UI
    restating the whole set, not a person pointing at one link and taking it
    back, and reading every dropped item as a considered negative would flood the
    signal that makes tombstones worth keeping.
    """
    refuse_derived(relationship_type)
    anchor = await resolve(session, entity, user_id)
    refuse_archived(anchor)
    wanted = list(dict.fromkeys(ids))
    resolved = await _linkable(session, other_kind, wanted, user_id)
    for other_id in wanted:
        found = resolved.get(other_id)
        if found is None:
            raise Refused(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=RelationshipMessages.ENDPOINT_NOT_FOUND,
            )
        refuse_across_initiatives(anchor, found)
        refuse_archived(found)
    current = await list_for_entity(
        session, entity, relationship_type=relationship_type, other_kind=other_kind
    )
    keep = set(wanted)

    for row in current:
        other = row.target_id if row.source_node == entity.node else row.source_id
        if other not in keep:
            await remove(session, row, removed_by=user_id, tombstone=False)

    have = {
        (row.target_id if row.source_node == entity.node else row.source_id)
        for row in current
    }
    for other_id in wanted:
        if other_id in have:
            continue
        await create(
            session,
            source=entity,
            relationship_type=relationship_type,
            target=Endpoint(other_kind, other_id),
            created_by=user_id,
        )


def _walk_sql(frm: str, to: str) -> str:
    """The recursive walk, one direction of it.

    Written out per direction rather than interpolated: the request path builds
    no SQL text, and a walk has exactly two directions, so there is nothing a
    format string would save.

    A person is reached and not walked on from: what links to somebody is read
    from each item's side, never gathered from theirs.
    """
    return f"""
        WITH RECURSIVE reachable(node, depth) AS (
            SELECT CAST(:start AS bigint), 0
          UNION ALL
            SELECT r.{to}_node, w.depth + 1
            FROM reachable w
            JOIN relationships r
              ON r.{frm}_node = w.node
             AND r.relationship_type = :rtype
             AND r.removed_at IS NULL
             AND r.{frm}_type <> '{PERSON.value}'
            WHERE w.depth < :depth
        ) CYCLE node SET is_cycle USING path
        SELECT node, depth, is_cycle FROM reachable WHERE depth > 0
    """


#: The two walks, rendered once at import. ``CYCLE … SET … USING path`` is the
#: SQL-standard clause (PG14+), so a cyclic graph terminates on its own.
_WALK_OUTBOUND = _walk_sql("source", "target")
_WALK_INBOUND = _walk_sql("target", "source")


async def walk(
    session: AsyncSession,
    start: Endpoint,
    *,
    relationship_type: RelationshipType,
    outbound: bool = True,
    depth: int = MAX_WALK_DEPTH,
) -> list[tuple[int, int, bool]]:
    """Follow one relation, returning ``(node, depth, closes_a_cycle)``.

    Uses the SQL-standard ``CYCLE`` clause, so a cyclic graph terminates on its
    own: the row that revisits a node is flagged and not expanded, while every
    other branch carries on. That is the whole of what this design needs from
    cycles — they are recorded, and found when read — and it is why the table
    needs no rule against them.

    A multi-hop walk along a relation that does not chain is refused rather than
    answered: *A related to B* and *B related to C* says nothing about A and C,
    so walking it would return something that reads like a result and is not.
    """
    if depth > 1 and not is_transitive(relationship_type):
        raise NotTransitive(
            f"{relationship_type.value} is not transitive, so a walk deeper "
            "than one hop has no meaning"
        )
    bounded = max(1, min(depth, MAX_WALK_DEPTH))

    rows = await session.exec(
        text(_WALK_OUTBOUND if outbound else _WALK_INBOUND).bindparams(
            start=start.node, rtype=relationship_type.value, depth=bounded
        )
    )
    return [(row[0], row[1], row[2]) for row in rows.all()]


async def would_close_a_cycle(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    target: Endpoint,
) -> bool:
    """Whether adding this edge would make a loop — a warning, never a refusal.

    A picker asks before it offers a candidate. The answer is shown to the
    person, who may mean it: two tasks that each wait on the other usually means
    they are one piece of work, which is worth surfacing and worth recording.
    """
    if not is_transitive(relationship_type):
        return source.node == target.node
    reachable = await walk(
        session, target, relationship_type=relationship_type, outbound=True
    )
    return any(node == source.node for node, _, _ in reachable)


#: How far out a neighbourhood goes. About as much as a picture can say.
MAX_NEIGHBOURHOOD_HOPS = 3

#: How many things one hop may walk on from.
#:
#: A thing at the centre of a busy initiative can name a great many, and a
#: picture of a thousand nodes says less than one of forty, so the limit costs
#: nothing worth drawing. The nearest are kept: what was linked first is walked
#: first.
HOP_BUDGET = 40

#: How many far ends one lookup asks about. A hop is bounded in what it walks on
#: from, not in what those name — forty busy tags can name tens of thousands —
#: and each id is a bound parameter, of which a statement takes a limited number.
RESOLVE_CHUNK = 1000


@dataclass(frozen=True)
class Crossing:
    """One edge a neighbourhood walk crossed, from the side it reached it on."""

    row: EntityRelationship
    anchor: Endpoint
    other: Endpoint


@dataclass
class Neighbourhood:
    """Everything within some hops of one thing, as a walk found it."""

    #: Each thing reached, at the fewest hops it takes to get there.
    depths: dict[Endpoint, int]
    #: What each thing reached resolved to for this reader.
    ends: dict[Endpoint, reference_targets.Resolved]
    #: Every edge crossed on the way, once each.
    edges: list[Crossing]


async def _edges_for_many(
    session: AsyncSession,
    entities: Sequence[Endpoint],
    *,
    include_tags: bool,
) -> list[EntityRelationship]:
    """Every live edge touching any of these, oldest first, each once.

    :func:`list_for_entity` for a whole hop at a time: the same two anchored
    seeks, with ``IN`` in place of ``=``, so the cost of a hop is two queries
    whatever its width.
    """
    nodes = [entity.node for entity in entities]
    if not nodes:
        return []

    def arm(column, other_column):
        stmt = select(EntityRelationship).where(
            column.in_(nodes),
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )
        if not include_tags:
            stmt = stmt.where(
                EntityRelationship.relationship_type
                != RelationshipType.tagged_with.value,
                other_column != SearchEntityType.tag.value,
            )
        return stmt

    found: dict[int, EntityRelationship] = {}
    for column, other_column in (
        (EntityRelationship.source_node, EntityRelationship.target_type),
        (EntityRelationship.target_node, EntityRelationship.source_type),
    ):
        for row in (await session.exec(arm(column, other_column))).all():
            found.setdefault(row.id, row)  # type: ignore[arg-type]
    return sorted(found.values(), key=lambda r: (r.created_at, r.id or 0))


async def neighbourhood(
    session: AsyncSession,
    start: Endpoint,
    *,
    hops: int,
    include_tags: bool,
    user_id: int | None,
) -> Neighbourhood:
    """Everything within ``hops`` of one thing, walked a hop at a time.

    Each hop is one batch: the edges of everything it walks on from, then the
    far ends of those, one query per kind. So three hops cost a handful of
    queries in one request, where asking per neighbour cost a request each.

    Gated as the per-entity read is: the edge policy asks of both ends, and a
    far end that does not resolve for this reader — out of reach, or in the
    trash — is left out, and so is never walked on from.

    Labels are left out of the walk unless asked for. A tag is shared by
    everything carrying it, so walking through one reaches the whole community
    in a hop. A person is reached and never walked on from, as in :func:`walk`.
    """
    bounded = max(1, min(hops, MAX_NEIGHBOURHOOD_HOPS))
    depths: dict[Endpoint, int] = {start: 0}
    ends: dict[Endpoint, reference_targets.Resolved] = {}
    edges: dict[int, Crossing] = {}

    frontier = [start]
    for depth in range(1, bounded + 1):
        if not frontier:
            break
        anchors = {end.node: end for end in frontier}
        crossings: list[Crossing] = []
        for row in await _edges_for_many(session, frontier, include_tags=include_tags):
            # An edge between two things on the same hop is crossed from both.
            for anchor_node, kind, other_id in (
                (row.source_node, row.target_type, row.target_id),
                (row.target_node, row.source_type, row.source_id),
            ):
                anchor = anchors.get(anchor_node)
                if anchor is not None:
                    other = Endpoint(EndpointKind(kind), other_id)
                    crossings.append(Crossing(row=row, anchor=anchor, other=other))

        wanted: dict[EndpointKind, list[int]] = {}
        for crossing in crossings:
            if crossing.other not in depths:
                wanted.setdefault(crossing.other.kind, []).append(crossing.other.id)
        for kind, ids in wanted.items():
            unique = list(dict.fromkeys(ids))
            for offset in range(0, len(unique), RESOLVE_CHUNK):
                resolved = await reference_targets.resolve_many(
                    session,
                    kind,
                    unique[offset : offset + RESOLVE_CHUNK],
                    user_id=user_id,
                )
                for entity_id, found in resolved.items():
                    ends[Endpoint(kind, entity_id)] = found

        frontier = []
        for crossing in crossings:
            if crossing.other not in depths and crossing.other not in ends:
                continue
            edges.setdefault(crossing.row.id, crossing)  # type: ignore[arg-type]
            if crossing.other in depths:
                continue
            depths[crossing.other] = depth
            if len(frontier) < HOP_BUDGET and crossing.other.kind != PERSON.value:
                frontier.append(crossing.other)

    del depths[start]
    return Neighbourhood(depths=depths, ends=ends, edges=list(edges.values()))


async def purge_for_entities(
    session: AsyncSession,
    kind: EndpointKind,
    entity_ids: Iterable[int],
) -> None:
    """Drop every edge naming one of these, tombstones included.

    Nothing carries an edge out with its endpoint — the endpoints are weak
    references, as on every polymorphic table here — so the purge path says so
    explicitly. A tombstone goes too: what it remembers is a link between two
    things, and one of them is about to stop existing.
    """
    nodes = [node_id(kind, entity_id) for entity_id in entity_ids]
    if not nodes:
        return
    await session.exec(
        delete(EntityRelationship).where(  # type: ignore[arg-type]
            EntityRelationship.source_node.in_(nodes)  # type: ignore[union-attr]
            | EntityRelationship.target_node.in_(nodes)  # type: ignore[union-attr]
        )
    )


__all__ = [
    "ENDPOINT_KINDS",
    "MAX_WALK_DEPTH",
    "SPECS",
    "Direction",
    "Endpoint",
    "HOP_BUDGET",
    "MAX_NEIGHBOURHOOD_HOPS",
    "Neighbourhood",
    "NotTransitive",
    "SelfLoop",
    "Related",
    "create",
    "create_many",
    "find",
    "list_for_entity",
    "neighbourhood",
    "purge_for_entities",
    "related_for",
    "related_for_many",
    "counts_for_many",
    "related_ids",
    "remove",
    "set_related",
    "walk",
    "would_close_a_cycle",
]


def records_edges(session: AsyncSession) -> bool:
    """Whether this request writes ``references`` edges. An installed plug-in
    writes relationships only under its ``relationships:write`` scope; without
    it, what its content points at is left unrecorded."""
    context = install_context(session)
    return context is None or "relationships" in context.install_write


#: Edge types a copy does not carry. Tags travel through ``copy_entity_tags``,
#: and a derived edge is read out of a body on save rather than asserted, so
#: neither is copied here.
_UNCOPIED_TYPES = frozenset({RelationshipType.tagged_with}) | DERIVED_TYPES


async def copy_links(
    session: AsyncSession, kind: SearchEntityType, copies: Mapping[int, int]
) -> None:
    """Carry the links of rows of ``kind`` onto their copies
    (``{source_id: copy_id}``).

    Every live edge touching a source is re-created on its copy. An end that is
    itself one of the sources is remapped to its copy, so a dependency between
    two copied tasks joins the two copies; any other end is kept as it is.

    Each is a link made on the copier's behalf, through :func:`link_many`, so
    one it would refuse is left behind: a far end the copier cannot open, one
    in another initiative than the copy, an archived one.
    """
    if not copies or not records_edges(session):
        return
    nodes = [node_id(kind, source_id) for source_id in copies]
    live = EntityRelationship.removed_at.is_(None)  # type: ignore[union-attr]
    rows = [
        *await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node.in_(nodes),  # type: ignore[union-attr]
                live,
            )
        ),
        *await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.target_node.in_(nodes),  # type: ignore[union-attr]
                live,
            )
        ),
    ]
    edges = {row.id: row for row in rows if row.id is not None}

    def remapped(end_kind: str, entity_id: int) -> Endpoint:
        resolved = EndpointKind(end_kind)
        if resolved == kind:
            entity_id = copies.get(entity_id, entity_id)
        return Endpoint(resolved, entity_id)

    await link_many(
        session,
        [
            Link(
                source=remapped(row.source_type, row.source_id),
                relationship_type=RelationshipType(row.relationship_type),
                target=remapped(row.target_type, row.target_id),
                provenance=Provenance(row.provenance),
                confidence=row.confidence,
            )
            for row in sorted(edges.values(), key=lambda r: (r.created_at, r.id or 0))
            if RelationshipType(row.relationship_type) not in _UNCOPIED_TYPES
        ],
        user_id=require_actor_context(session).user_id,
    )
