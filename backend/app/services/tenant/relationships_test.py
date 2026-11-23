"""What the edge table promises.

The gate is the interesting part: a row is reachable by exactly the readers who
can reach BOTH of the things it connects, and what a write asks depends on what
the edge describes rather than on a field beside it. The rest of these hold the
lines the design took deliberately — that the table records shapes it does not
police, and that a person taking a link back is remembered where a text edit is
not.
"""

from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import (
    ENDPOINT_CODES,
    ENDPOINT_KINDS,
    NODE_ID_SHIFT,
    Provenance,
    RelationshipType,
    node_id,
)
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import relationships
from app.services.tenant.relationships import Endpoint
from app.testing import create_resource_grant, guild_of
from app.testing.factories import (
    create_calendar,
    create_calendar_event,
    create_file,
    create_initiative,
    create_relationship,
    create_task,
)
from app.testing.schema_harness import route_session_to_guild

# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_node_ids_keep_kind_and_id_apart():
    for kind, code in ENDPOINT_CODES.items():
        node = node_id(kind, 4242)
        assert (node >> NODE_ID_SHIFT, node & ((1 << NODE_ID_SHIFT) - 1)) == (
            code,
            4242,
        )


def test_every_kind_resolves_to_a_table():
    from app.core.tool_set import BUILTIN_TOOLS
    from app.db.reference_targets import title_column

    for kind, endpoint in ENDPOINT_KINDS.items():
        assert endpoint.table
        assert title_column(kind, tools=BUILTIN_TOOLS) is not None


# ---------------------------------------------------------------------------
# Storage: what the table refuses, and what it records
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tombstones
# ---------------------------------------------------------------------------


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

    await relationships.purge_for_entities(
        session, ENDPOINT_CODES[SearchEntityType.file], [file_id]
    )
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
