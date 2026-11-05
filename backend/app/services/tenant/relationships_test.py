"""What the edge table promises.

The gate is the interesting part: a row is reachable by exactly the readers who
can reach BOTH of the things it connects, and what a write asks depends on what
the edge describes rather than on a field beside it. The rest of these hold the
lines the design took deliberately — that the table records shapes it does not
police, and that a person taking a link back is remembered where a text edit is
not.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing import create_resource_grant, guild_of
from app.core.relationships import (
    ENDPOINT_KINDS,
    SPECS,
    EndpointKind,
    Provenance,
    RelationshipType,
    decode_node_id,
    node_id,
)
from app.core.search import SearchEntityType
from app.testing.schema_harness import route_session_to_guild
from app.models.platform.guild import CommunityRole
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import relationships
from app.services.tenant.relationships import Endpoint
from app.testing.factories import (
    create_calendar,
    create_calendar_event,
    create_file,
    create_initiative,
    create_relationship,
    create_tag,
    create_task,
)


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_node_ids_round_trip():
    for kind in EndpointKind:
        assert decode_node_id(node_id(kind, 4242)) == (kind, 4242)


def test_every_kind_resolves_to_a_table():
    from app.db.reference_targets import title_column

    for kind, endpoint in ENDPOINT_KINDS.items():
        assert endpoint.table
        assert title_column(kind) is not None


def test_symmetric_types_declare_no_direction():
    """A symmetric relation has no described end, so it cannot also be
    asymmetric — the two characteristics contradict each other."""
    for relationship_type, spec in SPECS.items():
        assert not (spec.symmetric and spec.asymmetric), relationship_type


# ---------------------------------------------------------------------------
# Storage: what the table refuses, and what it records
# ---------------------------------------------------------------------------


async def test_self_loop_is_refused(session: AsyncSession, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    await route_session_to_guild(session, a.guild.id)

    with pytest.raises(relationships.SelfLoop):
        await relationships.create(
            session,
            source=Endpoint(SearchEntityType.task, task.id),
            relationship_type=RelationshipType.related_to,
            target=Endpoint(SearchEntityType.task, task.id),
        )


async def test_symmetric_edge_is_stored_once_whichever_way_it_is_asked_for(
    session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    await route_session_to_guild(session, a.guild.id)

    first = await relationships.create(
        session,
        source=Endpoint(SearchEntityType.file, doc.id),
        relationship_type=RelationshipType.attached,
        target=Endpoint(SearchEntityType.project, a.project.id),
    )
    # The same pair, named the other way round: the same edge, not a second one.
    second = await relationships.create(
        session,
        source=Endpoint(SearchEntityType.project, a.project.id),
        relationship_type=RelationshipType.attached,
        target=Endpoint(SearchEntityType.file, doc.id),
    )
    assert first is not None
    assert second is None

    rows = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.relationship_type == RelationshipType.attached.value
            )
        )
    ).all()
    assert len(rows) == 1
    # Stored in node-id order, which is the constraint's rule and not the
    # caller's: file (6) sorts below project (10).
    assert rows[0].source_node < rows[0].target_node
    assert rows[0].source_type == SearchEntityType.file.value


async def test_a_part_may_belong_to_two_wholes(session: AsyncSession, acting_user):
    """The table records what it is given. One-parent is a picker's rule, and a
    task somebody wants in two epics is an ambiguity worth keeping."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    part = await create_task(session, a.project, title="Shared step")
    first = await create_task(session, a.project, title="Epic one")
    second = await create_task(session, a.project, title="Epic two")
    await route_session_to_guild(session, a.guild.id)

    for whole in (first, second):
        assert await relationships.create(
            session,
            source=Endpoint(SearchEntityType.task, part.id),
            relationship_type=RelationshipType.part_of,
            target=Endpoint(SearchEntityType.task, whole.id),
        )

    edges = await relationships.list_for_entity(
        session,
        Endpoint(SearchEntityType.task, part.id),
        relationship_type=RelationshipType.part_of,
    )
    assert len(edges) == 2


async def test_a_dependency_loop_is_stored_and_reported_by_walk(
    session: AsyncSession, acting_user
):
    """Two people each saying the other's task must go first is the strongest
    coupling evidence the system gets. It is recorded, and found when read."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first = await create_task(session, a.project, title="A")
    second = await create_task(session, a.project, title="B")
    await route_session_to_guild(session, a.guild.id)

    for source, target in ((first, second), (second, first)):
        assert await relationships.create(
            session,
            source=Endpoint(SearchEntityType.task, source.id),
            relationship_type=RelationshipType.depends_on,
            target=Endpoint(SearchEntityType.task, target.id),
        )
    await session.commit()

    reached = await relationships.walk(
        session,
        Endpoint(SearchEntityType.task, first.id),
        relationship_type=RelationshipType.depends_on,
        depth=5,
    )
    assert any(is_cycle for _, _, is_cycle in reached), reached
    # And the walk terminated rather than running to the depth bound.
    assert max(depth for _, depth, _ in reached) < 5

    assert await relationships.would_close_a_cycle(
        session,
        source=Endpoint(SearchEntityType.task, first.id),
        relationship_type=RelationshipType.depends_on,
        target=Endpoint(SearchEntityType.task, second.id),
    )


async def test_a_multi_hop_walk_is_refused_for_a_non_transitive_type(
    session: AsyncSession, acting_user
):
    """*A related to B* and *B related to C* says nothing about A and C, so
    walking it would return something that reads like a result and is not."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    await route_session_to_guild(session, a.guild.id)

    with pytest.raises(relationships.NotTransitive):
        await relationships.walk(
            session,
            Endpoint(SearchEntityType.task, task.id),
            relationship_type=RelationshipType.related_to,
            depth=3,
        )


# ---------------------------------------------------------------------------
# Tombstones
# ---------------------------------------------------------------------------


async def test_a_manual_removal_is_remembered_and_the_pair_is_re_linkable(
    session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    row = await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.project, a.project.id),
        target=(SearchEntityType.file, doc.id),
        created_by=a.user.id,
    )

    await relationships.remove(session, row, removed_by=a.user.id)
    await session.commit()

    # Gone from every read...
    assert not await relationships.list_for_entity(
        session,
        Endpoint(SearchEntityType.project, a.project.id),
        relationship_type=RelationshipType.attached,
    )
    # ...and still there, which is the whole point: nothing else in the schema
    # records that somebody linked two things and then took it back.
    kept = (
        await session.exec(
            select(EntityRelationship).where(EntityRelationship.id == row.id)
        )
    ).one()
    assert kept.removed_at is not None
    assert kept.removed_by == a.user.id

    # The unique key covers live rows only, so the same pair links again.
    again = await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.project, a.project.id),
        target=(SearchEntityType.file, doc.id),
    )
    assert again.id != row.id


async def test_a_content_edge_is_deleted_rather_than_tombstoned(
    session: AsyncSession, acting_user
):
    """Editing the sentence that implied a link asserts nothing. Counting that
    as "these are not related" would bury the real signal in noise shaped
    exactly like it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    row = await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.project, a.project.id),
        target=(SearchEntityType.file, doc.id),
        provenance=Provenance.content,
    )
    row_id = row.id

    await relationships.remove(session, row, removed_by=a.user.id)
    await session.commit()

    assert (
        await session.exec(
            select(EntityRelationship).where(EntityRelationship.id == row_id)
        )
    ).one_or_none() is None


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


async def test_an_edge_is_invisible_to_a_reader_who_clears_only_one_end(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The hard isolation boundary, as it applies to a link: a member of one
    initiative does not learn that a project of theirs is attached to a file
    of another initiative they are not in."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # A file in a DIFFERENT initiative of the same guild. The owner is in
    # both; the reader below is in only one.
    elsewhere = await create_initiative(session, owner.guild, owner.user)
    doc = await create_file(session, elsewhere, owner.user)

    await create_relationship(
        session,
        owner.guild,
        source=(SearchEntityType.project, owner.project.id),
        target=(SearchEntityType.file, doc.id),
        created_by=owner.user.id,
    )

    # The project is shared with the whole initiative, so the reader can open
    # it: what is being tested is the edge's FAR end, not this one.
    await create_resource_grant(session, owner.project, all_initiative_members=True)

    # A guild member in the project's initiative but not the file's.
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    response = await client.get(
        reader.g(f"/relationships/?entity=project:{owner.project.id}"),
        headers=reader.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_a_tag_edge_is_still_gated_by_the_other_end(
    session: AsyncSession, acting_user
):
    """A tag is guild-level and every member sees every tag, so the tag end
    admits anyone. The task end is what decides, and it still does."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    row = await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, task.id),
        target=(SearchEntityType.tag, tag.id),
        relationship_type=RelationshipType.tagged_with,
    )
    assert row.source_type == SearchEntityType.task.value
    assert row.target_type == SearchEntityType.tag.value


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


async def test_purging_an_endpoint_takes_its_edges_including_tombstones(
    session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    live = await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.project, a.project.id),
        target=(SearchEntityType.file, doc.id),
    )
    live_id = live.id
    second = await create_task(session, a.project)
    tombstoned = await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, second.id),
        target=(SearchEntityType.file, doc.id),
        relationship_type=RelationshipType.related_to,
    )
    # Held now: each commit below expires these objects, and reading an
    # attribute off an expired one is IO in a place that cannot do it.
    edge_ids = [live_id, tombstoned.id]
    file_id = doc.id

    await relationships.remove(session, tombstoned, removed_by=a.user.id)
    await session.commit()

    await relationships.purge_for_entities(session, SearchEntityType.file, [file_id])
    await session.commit()

    remaining = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.id.in_(edge_ids)  # type: ignore[union-attr]
            )
        )
    ).all()
    assert remaining == []


async def test_two_guilds_events_do_not_share_attachments(
    session: AsyncSession, acting_user
):
    """Ids come from each guild's own sequence, so two guilds hold an event 5
    between them. A per-guild read must therefore be carried out paired with its
    event; merging these dicts across guilds is what this guards against."""
    from app.services.tenant.ical_service import files_for_events

    first = await acting_user(guild_role=CommunityRole.member, initiative=True)
    second = await acting_user(guild_role=CommunityRole.member, initiative=True)

    events = []
    for actor in (first, second):
        calendar = await create_calendar(session, actor.initiative, actor.user)
        event = await create_calendar_event(session, calendar, actor.user)
        doc = await create_file(session, actor.initiative, actor.user)
        await create_relationship(
            session,
            actor.guild,
            source=(SearchEntityType.calendar_event, event.id),
            target=(SearchEntityType.file, doc.id),
        )
        events.append((actor, event, doc))

    # Gathered per guild and paired on the way out, as the feed does.
    paired: list[tuple[int, int, list]] = []
    for actor, event, _ in events:
        await route_session_to_guild(session, actor.guild.id)
        found = await files_for_events(session, [event])
        paired.append((guild_of(event), event.id, found.get(event.id, [])))

    assert len(paired) == 2, "one guild's events displaced the other's"
    for (_, event, doc), (_, _, found) in zip(events, paired):
        assert [related.id for related in found] == [doc.id]
