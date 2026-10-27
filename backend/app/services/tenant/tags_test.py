"""What a tag assignment is now that it is an edge.

The surfaces are covered where they live (``tenant_endpoints/tags_test``); what
these hold is the storage change underneath them — direction, the gate a write
asks, and the three things a junction used to do by foreign key that something
explicit now has to do instead: drop with the tag, drop with the tagged thing,
and disappear the moment the tag is trashed.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import ENDPOINT_KINDS, RelationshipType, node_id
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.relationship import EntityRelationship
from app.db.session import set_rls_context
from app.services.tenant import tags as tags_service
from app.services.tenant.soft_delete import hard_purge_entity
from app.testing.factories import (
    assign_tag,
    create_collection,
    create_file,
    create_resource_grant,
    create_tag,
    create_task,
)
from app.testing.schema_harness import route_session_to_guild
from app.testing import create_guild_membership, route_as
from app.db.request_context import SystemGuild


def test_every_taggable_kind_can_sit_on_an_edge():
    """The registry is one list now: a spec names a model and the kind an edge
    addresses it by, and a kind no edge may name would be a tag surface with
    nowhere to store an assignment."""
    for name, spec in tags_service.TAG_LINKS.items():
        assert spec.kind in ENDPOINT_KINDS, name


async def _edges(session, guild_id: int, kind, entity_id: int):
    await route_session_to_guild(session, guild_id)
    return (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node == node_id(kind, entity_id)
            )
        )
    ).all()


async def test_a_tag_is_stored_as_an_edge_the_tagged_thing_owns(
    session: AsyncSession, acting_user
):
    """Direction is the whole of the write rule: a tag is a label, so the edge
    describes the thing carrying it. Source is the task, target is the tag —
    which is what makes tagging ask write on the task and nothing of the tag."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    await assign_tag(session, task, tag, commit=True)

    rows = await _edges(session, a.guild.id, SearchEntityType.task, task.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.relationship_type == RelationshipType.tagged_with.value
    assert (row.source_type, row.source_id) == (SearchEntityType.task.value, task.id)
    assert (row.target_type, row.target_id) == (SearchEntityType.tag.value, tag.id)


async def test_two_kinds_sharing_an_id_do_not_share_tags(
    session: AsyncSession, acting_user
):
    """Ids are unique within a table, not across them. The packed node id is
    what keeps a file's tags off a task that happens to have the same
    number — the one thing a per-entity junction got for free."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task_tag = await create_tag(session, a.guild, name="for-the-task")
    doc_tag = await create_tag(session, a.guild, name="for-the-doc")
    task = await create_task(session, a.project)
    doc = await create_file(session, a.initiative, a.user)
    await assign_tag(session, task, task_tag)
    await assign_tag(session, doc, doc_tag)
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    assert await tags_service.active_tag_ids(
        session, tags_service.TAG_LINKS["task"], task.id
    ) == [task_tag.id]
    assert await tags_service.active_tag_ids(
        session, tags_service.spec_for(doc), doc.id
    ) == [doc_tag.id]


async def test_a_trashed_tag_stops_being_an_assignment(
    session: AsyncSession, acting_user
):
    """The junction era decided this by joining ``tags`` on every read; the
    edge era has to decide it the same way, or a trashed tag would come back
    everywhere at once."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    await assign_tag(session, task, tag, commit=True)

    await route_session_to_guild(session, a.guild.id)
    tag.deleted_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    assert (
        await tags_service.active_tag_ids(
            session, tags_service.TAG_LINKS["task"], task.id
        )
        == []
    )
    # The edge itself is still there: trashing is reversible, and a restore has
    # to bring the assignments back with it.
    assert len(await _edges(session, a.guild.id, SearchEntityType.task, task.id)) == 1


async def test_purging_a_tag_takes_its_assignments(session: AsyncSession, acting_user):
    """A junction row went with its tag by foreign key. Nothing carries an edge
    out now, so the purge path has to name it — and it does, from the endpoint
    registry rather than a second list of tables."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    await assign_tag(session, task, tag, commit=True)
    tag.deleted_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()

    await set_rls_context(session, SystemGuild(a.guild.id))
    await hard_purge_entity(session, tag)
    await session.commit()

    assert await _edges(session, a.guild.id, SearchEntityType.task, task.id) == []


async def test_replacing_a_tag_set_leaves_no_tombstone(
    session: AsyncSession, acting_user
):
    """A replace is the UI restating a set, not a person taking one link back.
    Reading every dropped assignment as a considered negative would flood the
    signal tombstones exist to keep."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first = await create_tag(session, a.guild, name="one")
    second = await create_tag(session, a.guild, name="two")
    task = await create_task(session, a.project)

    await route_session_to_guild(session, a.guild.id)
    spec = tags_service.TAG_LINKS["task"]
    await tags_service.replace_entity_tags(session, spec, task.id, [first.id])
    await session.commit()
    await route_session_to_guild(session, a.guild.id)
    await tags_service.replace_entity_tags(session, spec, task.id, [second.id])
    await session.commit()

    rows = await _edges(session, a.guild.id, SearchEntityType.task, task.id)
    assert [r.target_id for r in rows] == [second.id]


async def test_a_tag_assignment_is_invisible_to_a_reader_outside_the_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Every member of a guild sees every tag, so the tag end of this edge
    admits anyone. The other end is initiative content, and it is the one that
    decides — which is why a guild-level endpoint had to declare its leg rather
    than default to one."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, owner.guild, name="secret-project")
    doc = await create_file(session, owner.initiative, owner.user)
    await assign_tag(session, doc, tag, commit=True)

    outsider = await acting_user(
        guild_role=CommunityRole.member, guild=owner.guild, initiative=True
    )
    response = await client.get(
        outsider.g(f"/tags/{tag.id}/entities"),
        headers=outsider.headers,
        params={"kind": "file"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    counts = await client.get(
        outsider.g(f"/tags/{tag.id}/counts"), headers=outsider.headers
    )
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {}


async def test_the_endpoint_gate_answers_in_the_schema_the_request_is_routed_to(
    session: AsyncSession, acting_user, role_session
):
    """The gate is one function in ``public`` that reads guild-local tables
    through ``search_path``, so a connection that has served one community must
    not answer the next one from what it saw first. Asked here on the same
    connection, twice, with only the routing changed: the second guild has no
    task by that id, and the answer has to be no."""
    from sqlalchemy import text

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    task_id = task.id
    other = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # The same reader belongs to both, so what changes between the two calls
    # below is the routing and nothing else.
    await create_guild_membership(session, user=a.user, guild=other.guild)

    # On the request login: the gate is a policy question, and the setup
    # session's own login is one the database treats as trusted.
    reader = await role_session("app_user")

    async def reachable(guild_id: int) -> bool:
        await route_as(reader, user_id=a.user.id, guild_id=guild_id)
        return (
            await reader.exec(
                text(
                    "SELECT entity_access('task', :id, false, false, (SELECT current_standing()))"
                ).bindparams(id=task_id)
            )
        ).one()[0]

    assert await reachable(a.guild.id) is True
    assert await reachable(other.guild.id) is False


async def test_tagging_a_collection_takes_the_role_that_makes_files(
    session: AsyncSession, acting_user, role_session
):
    """A collection has no sharing of its own, so the gate an edge asks of its
    source holds it to what its own table does: its initiative's file makers."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    shared = await create_file(session, owner.initiative, owner.user)
    await create_resource_grant(session, shared, all_initiative_members=True)
    collection_id = (
        await create_collection(session, owner.initiative, owner.user, files=[shared])
    ).id
    tag_id = (await create_tag(session, owner.guild)).id
    guild_id = owner.guild.id
    spec = tags_service.TAG_LINKS["collection"]
    db = await role_session("app_user")

    await route_as(db, user_id=reader.user.id, guild_id=guild_id)
    db.add(tags_service.tag_edge(spec, collection_id, tag_id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await db.flush()
    await db.rollback()

    await route_as(db, user_id=owner.user.id, guild_id=guild_id)
    db.add(tags_service.tag_edge(spec, collection_id, tag_id))
    await db.flush()
