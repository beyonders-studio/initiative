"""What a body says it is about, and which of it the graph keeps.

The first half decides what counts as a reference — one vocabulary, whether it
was written as ``[[ ]]`` in a file or as ``#`` in a comment. The second
decides which of those become ``references`` edges, and when one goes away.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from app.core.references import references_in_body, references_in_text
from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import content_references
from app.services.tenant.relationships import Endpoint
from app.testing import (
    add_counter,
    create_comment,
    create_file,
    create_project,
    create_task,
    install_tool_plugin,
)


def _doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"root": {"children": [{"type": "paragraph", "children": list(nodes)}]}}


def _reference(entity_type: str, entity_id: int) -> dict[str, Any]:
    return {"type": "entity-mention", "entityType": entity_type, "entityId": entity_id}


FILE = SearchEntityType.file
TASK = SearchEntityType.task


# ---------------------------------------------------------------------------
# What counts as a reference
# ---------------------------------------------------------------------------


def test_a_hash_reference_is_a_reference():
    assert references_in_body(_doc(_reference("file", 7))) == {(FILE, 7)}


def test_a_reference_to_something_that_is_not_a_file_counts_too():
    """The whole of what this phase adds: a page about a task refers to that
    task, and until now only the files were kept."""
    content = _doc(_reference("task", 12), _reference("calendar_event", 4))
    assert references_in_body(content) == {
        (TASK, 12),
        (SearchEntityType.calendar_event, 4),
    }


def test_a_chip_refers_to_the_thing_it_reads():
    """A page showing a task's status is about that task, so "what links here"
    finds it."""
    content = _doc({"type": "smart-chip", "chipKind": "task:status", "entityId": 9})
    assert references_in_body(content) == {(TASK, 9)}


def test_an_embed_refers_to_the_thing_it_shows():
    content = _doc(
        {"type": "reference-embed", "entityType": "calendar_event", "entityId": 4}
    )
    assert references_in_body(content) == {(SearchEntityType.calendar_event, 4)}


def test_references_are_found_however_deep_they_sit():
    nested = {
        "root": {
            "children": [
                {
                    "type": "list",
                    "children": [
                        {"type": "listitem", "children": [_reference("file", 5)]}
                    ],
                }
            ]
        }
    }
    assert references_in_body(nested) == {(FILE, 5)}


def test_content_that_is_not_a_body_yields_nothing():
    assert references_in_body(None) == set()
    assert references_in_body({}) == set()


def test_a_hash_in_running_text_is_a_reference():
    """What a comment is written in."""
    assert references_in_text("see #task[Fix the bug](12) first") == {(TASK, 12)}


def test_a_hash_reads_every_spelling_the_composer_writes():
    """The composer kebabs a kind after ``#``, which names the same things the
    kind's own spelling does."""
    assert references_in_text(
        "#wiki-page[Start](3) #calendar-event[Tally](4) #file[Spec](5) #wiki_page[A](6)"
    ) == {
        (SearchEntityType.wiki_page, 3),
        (SearchEntityType.calendar_event, 4),
        (SearchEntityType.file, 5),
        (SearchEntityType.wiki_page, 6),
    }


def test_a_hash_naming_no_known_kind_is_not_a_reference():
    assert references_in_text("#widget[Nope](3)") == set()


def test_a_hash_names_a_tool_plugins_kind_as_go_spells_it():
    """A tool plug-in's kind is its key kebabed, ``.`` and its uid, as a
    ``/go`` link spells it, and an editor node names it as it is."""
    group, counter = "counter_group.tsjvtcm0s7gv2x", "counter.tsjvtcm0s7gv2x"
    assert references_in_text(
        "#counter-group.tsjvtcm0s7gv2x[Tally](4) and #counter.tsjvtcm0s7gv2x[Laps](5)"
    ) == {(group, 4), (counter, 5)}
    assert references_in_body(_doc(_reference(group, 4), _reference(counter, 5))) == {
        (group, 4),
        (counter, 5),
    }


def test_a_hash_a_tool_plugins_kind_could_not_be_is_not_a_reference():
    """Only the shape of a kind is read here; one that is not the shape (a
    capital, a second ``.``, an empty side) is the words it was written with."""
    for written in (
        "#counter.TSJV[A](1)",
        "#counter.a.b[A](1)",
        "#counter.[A](1)",
        "#.abc[A](1)",
        "#Counter.abc[A](1)",
        "#1counter.abc[A](1)",
        "#counter.a-b[A](1)",
    ):
        assert references_in_text(written) == set(), written


def test_a_user_mention_is_not_a_hash_reference():
    """A person is not a thing ``#`` names: a body's mentions of people are
    read on their own."""
    assert references_in_text("thanks @[Ada](4)") == set()


# ---------------------------------------------------------------------------
# Which of them become edges
# ---------------------------------------------------------------------------


async def _references(session, entity: Endpoint) -> set[tuple[str, int]]:
    """What the graph says this thing refers to."""
    rows = await session.exec(
        select(EntityRelationship.target_type, EntityRelationship.target_id).where(
            EntityRelationship.source_node == entity.node,
            EntityRelationship.relationship_type == RelationshipType.references.value,
            EntityRelationship.removed_at.is_(None),
        )
    )
    return set(rows.all())


async def test_a_file_does_not_reference_itself(session, acting_user):
    """The page a self-link opens is the page it was written on, and the row
    would list the file among the ones that point at it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)
    anchor = Endpoint(FILE, doc.id)

    await content_references.sync_for_entity(
        session,
        anchor,
        body=_doc(_reference("file", doc.id), _reference("file", other.id)),
        author_id=a.user.id,
    )

    assert await _references(session, anchor) == {("file", other.id)}


async def test_a_task_showing_its_own_status_does_not_reference_itself(
    session, acting_user
):
    """A chip or an embed of the task a description is on is the same loop a
    self-link is, whatever shape it is written in."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)
    anchor = Endpoint(TASK, task.id)

    await content_references.sync_for_entity(
        session,
        anchor,
        body=_doc(
            {"type": "smart-chip", "chipKind": "task:status", "entityId": task.id},
            {"type": "reference-embed", "entityType": "task", "entityId": task.id},
        ),
        author_id=a.user.id,
    )

    assert await _references(session, anchor) == set()


async def test_a_body_naming_a_task_records_it(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    anchor = Endpoint(FILE, doc.id)

    await content_references.sync_for_entity(
        session, anchor, body=_doc(_reference("task", task.id)), author_id=a.user.id
    )

    assert await _references(session, anchor) == {("task", task.id)}


async def test_a_reference_to_something_that_is_not_there_is_not_recorded(
    session, acting_user
):
    """An id nothing answers to leaves no edge — the far end has to exist for
    the pair to mean anything."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    anchor = Endpoint(FILE, doc.id)

    await content_references.sync_for_entity(
        session, anchor, body=_doc(_reference("file", 999_999)), author_id=a.user.id
    )

    assert await _references(session, anchor) == set()


async def test_editing_the_sentence_out_takes_the_edge_with_it(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)
    anchor = Endpoint(FILE, doc.id)

    await content_references.sync_for_entity(
        session, anchor, body=_doc(_reference("file", other.id)), author_id=a.user.id
    )
    await content_references.sync_for_entity(
        session, anchor, body=_doc(), author_id=a.user.id
    )

    assert await _references(session, anchor) == set()
    remaining = await session.exec(
        select(EntityRelationship).where(
            EntityRelationship.source_node == anchor.node,
            EntityRelationship.relationship_type == RelationshipType.references.value,
        )
    )
    assert remaining.all() == [], (
        "a link that went away because somebody rewrote a sentence asserts "
        "nothing, so it is deleted rather than kept as a tombstone"
    )


# ---------------------------------------------------------------------------
# A comment's `#` belongs to what the comment is about
# ---------------------------------------------------------------------------


async def test_a_comment_records_its_reference_against_its_parent(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    task = await create_task(session, a.project)

    comment = await create_comment(
        session, a.user, file=doc, content=f"see #task[Do it]({task.id})"
    )
    await content_references.sync_for_comment(session, comment, author_id=a.user.id)

    assert await _references(session, Endpoint(FILE, doc.id)) == {("task", task.id)}


async def test_one_comment_going_does_not_drop_what_another_still_says(
    session, acting_user
):
    """The recompute reads every source at once, so two people naming the same
    thing hold the edge up between them."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    project = await create_project(session, a.initiative, a.user)
    task = await create_task(session, project)
    doc = await create_file(session, a.initiative, a.user)

    first = await create_comment(
        session, a.user, file=doc, content=f"#task[Do it]({task.id})"
    )
    await create_comment(
        session, a.user, file=doc, content=f"agreed, #task[Do it]({task.id})"
    )
    await content_references.sync_for_comment(session, first, author_id=a.user.id)
    assert await _references(session, Endpoint(FILE, doc.id)) == {("task", task.id)}

    await session.delete(first)
    await session.flush()
    await content_references.sync_for_comment(session, first, author_id=a.user.id)

    assert await _references(session, Endpoint(FILE, doc.id)) == {("task", task.id)}, (
        "the other comment still says it"
    )


async def test_the_body_and_the_comments_are_read_together(session, acting_user):
    """A save recomputes from both, so writing a file does not wipe what
    its conversation refers to."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    await create_comment(session, a.user, file=doc, content=f"#task[Do it]({task.id})")

    await content_references.sync_for_entity(
        session,
        Endpoint(FILE, doc.id),
        body=_doc(_reference("file", other.id)),
        author_id=a.user.id,
    )

    assert await _references(session, Endpoint(FILE, doc.id)) == {
        ("file", other.id),
        ("task", task.id),
    }


async def test_an_edge_a_body_makes_is_marked_as_nobody_s_assertion(
    session, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)

    await content_references.sync_for_entity(
        session,
        Endpoint(FILE, doc.id),
        body=_doc(_reference("file", other.id)),
        author_id=a.user.id,
    )

    row = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.relationship_type
                == RelationshipType.references.value
            )
        )
    ).first()
    assert row is not None
    assert row.provenance == Provenance.content.value
    assert row.created_by == a.user.id, (
        "whoever saved the content is the honest attributor for what it says"
    )


async def test_saving_the_same_body_twice_changes_nothing(session, acting_user):
    """Two saves racing on the same new mention each read no edge and each go
    on to write it, and the second arriving is the answer being already
    correct."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)
    anchor = Endpoint(FILE, doc.id)
    body = _doc(_reference("file", other.id))

    await content_references.sync_for_entity(
        session, anchor, body=body, author_id=a.user.id
    )
    await content_references.sync_for_entity(
        session, anchor, body=body, author_id=a.user.id
    )

    assert await _references(session, anchor) == {("file", other.id)}


async def test_an_archived_thing_takes_no_new_reference(session, acting_user):
    """Archiving says the work is finished with, and a link shows on both ends
    — so a mention of one records nothing rather than failing the save."""
    from app.services.tenant.archive import archive_entity

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    await archive_entity(session, task)

    anchor = Endpoint(FILE, doc.id)
    await content_references.sync_for_entity(
        session, anchor, body=_doc(_reference("task", task.id)), author_id=a.user.id
    )

    assert await _references(session, anchor) == set()


async def test_archiving_the_far_end_leaves_a_reference_standing(session, acting_user):
    """The mention is still in the body, so the edge is still what the body
    says. A later save does not quietly drop it."""
    from app.services.tenant.archive import archive_entity

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    anchor = Endpoint(FILE, doc.id)
    body = _doc(_reference("task", task.id))

    await content_references.sync_for_entity(
        session, anchor, body=body, author_id=a.user.id
    )
    assert await _references(session, anchor) == {("task", task.id)}

    await archive_entity(session, task)
    await content_references.sync_for_entity(
        session, anchor, body=body, author_id=a.user.id
    )

    assert await _references(session, anchor) == {("task", task.id)}


# ---------------------------------------------------------------------------
# A task's description is its body
# ---------------------------------------------------------------------------


async def test_a_task_description_is_read_as_the_task_s_body(session, acting_user):
    """A description is markdown rather than an editor state, and names things
    with the same `#` a comment does."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    task = await create_task(
        session, a.project, description=f"see #file[Spec]({doc.id})"
    )

    assert await content_references.own_body(session, Endpoint(TASK, task.id)) == (
        f"see #file[Spec]({doc.id})"
    )
    await content_references.sync_for_entity(
        session,
        Endpoint(TASK, task.id),
        body=task.description,
        author_id=a.user.id,
    )

    assert await _references(session, Endpoint(TASK, task.id)) == {("file", doc.id)}


async def test_a_comment_on_a_task_keeps_what_its_description_says(
    session, acting_user
):
    """A comment's save recomputes its task's edges, and the description is one
    of the things it recomputes from."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_task(session, a.project)
    task = await create_task(session, a.project, description=f"#file[Spec]({doc.id})")

    comment = await create_comment(
        session, a.user, task=task, content=f"and #task[That]({other.id})"
    )
    await content_references.sync_for_comment(session, comment, author_id=a.user.id)

    assert await _references(session, Endpoint(TASK, task.id)) == {
        ("file", doc.id),
        ("task", other.id),
    }


async def _referenced(client, actor, entity: str) -> set[tuple[str, int]]:
    """What the API lists ``entity`` as referring to, for ``actor``."""
    response = await client.get(
        actor.g("/relationships/"),
        headers=actor.headers,
        params={"entity": entity, "relationship_type": "references"},
    )
    assert response.status_code == 200, response.text
    return {
        (edge["other"]["type"], edge["other"]["id"])
        for edge in response.json()
        if edge["direction"] == "outbound"
    }


async def test_a_tool_plugins_rows_are_referenced_as_a_built_in_tools_are(
    client, session, acting_user
):
    """A ``#`` naming a tool plug-in's row or item in a comment is recorded
    against what the comment is on, and a ``#`` in the row's own text field
    is recorded against the row, as a task's description is. Taking the
    sentence out takes the edge with it, and the system's own resync keeps
    what the comment says."""
    seat = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    await install_tool_plugin(client, session, seat)
    tools, group, counter = await add_counter(
        session, seat.guild.id, seat.initiative.id
    )
    (tool,) = tools.installed
    (item_kind,) = (child.value for child in tool.children)
    task = await create_task(session, seat.project)
    group_word = tool.kind.replace("_", "-")
    item_word = item_kind.replace("_", "-")

    response = await client.post(
        seat.g("/comments/"),
        headers=seat.headers,
        json={
            "subject_type": "task",
            "subject_id": task.id,
            "content": f"see #{group_word}[Scores]({group}) "
            f"and #{item_word}[Laps]({counter})",
        },
    )
    assert response.status_code == 201, response.text
    assert await _referenced(client, seat, f"task:{task.id}") == {
        (tool.kind, group),
        (item_kind, counter),
    }
    # The system's own resync (a comment trashed and restored) reads the
    # community's installs, so it keeps them.
    await content_references.sync_for_entity(session, Endpoint(TASK, task.id))
    await session.commit()
    assert await _referenced(client, seat, f"task:{task.id}") == {
        (tool.kind, group),
        (item_kind, counter),
    }

    written = f"/plugin-tools/{tool.kind}/{group}"
    response = await client.patch(
        seat.g(written),
        headers=seat.headers,
        json={"fields": {"description": f"for #task[Do it]({task.id})"}},
    )
    assert response.status_code == 200, response.text
    assert await _referenced(client, seat, f"{tool.kind}:{group}") == {
        ("task", task.id)
    }

    response = await client.patch(
        seat.g(written),
        headers=seat.headers,
        json={"fields": {"description": "for nothing"}},
    )
    assert response.status_code == 200, response.text
    assert await _referenced(client, seat, f"{tool.kind}:{group}") == set()
