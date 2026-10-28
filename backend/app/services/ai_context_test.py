"""What a task's checklist and description are written from."""

import json
from datetime import datetime, timezone

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.metadata import MetadataType
from app.models.tenant.task import TaskStatusCategory
from app.services import ai_context
from app.services.tenant import task_queries
from app.testing import (
    checklist_items,
    create_comment,
    create_property_definition,
    create_property_value,
    create_relationship,
    create_task,
)


async def test_a_task_is_told_with_its_links_and_newest_comments(
    session, acting_user, reading_as
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )
    task = await create_task(
        session,
        a.project,
        title="Ship it",
        description=f"Ask @[]({b.user.id}) about the hall",
        checklist=checklist_items("Book the hall"),
    )
    caterer = await create_task(session, a.project, title="Find a caterer")
    date = await create_task(
        session, a.project, title="Pick a date", status_category=TaskStatusCategory.done
    )
    for other in (caterer, date):
        await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.task, task.id),
            target=(SearchEntityType.task, other.id),
            relationship_type=RelationshipType.depends_on,
        )
    sign_off = await create_property_definition(
        session,
        a.initiative,
        name="Sign-off",
        type=MetadataType.select,
        options=[{"value": "legal", "label": "Requires legal approval"}],
    )
    await create_property_value(session, task, sign_off, value_text="legal")
    first = None
    for text in ("first", "second", "third"):
        comment = await create_comment(session, a.user, task=task, content=text)
        first = first or comment
    # Written last, under the oldest conversation.
    await create_comment(
        session, a.user, task=task, content="reply", parent_comment_id=first.id
    )
    await create_comment(
        session, a.user, task=task, content="", removed_at=datetime.now(timezone.utc)
    )

    reading = await reading_as(a.user.id, a.guild.id)
    loaded = await task_queries.load_task(reading, task.id)

    async def told(budget: int) -> ai_context.TaskContext:
        return await ai_context.task_context(reading, loaded, budget=budget)

    whole = await told(3000)
    data = json.loads(whole.data)
    assert data["task"]["title"] == "Ship it"
    assert data["task"]["checklist"] == [{"text": "Book the hall", "done": False}]
    # An option reads as its label.
    assert data["task"]["properties"] == [
        {"name": "Sign-off", "value": "Requires legal approval"}
    ]
    # A mention reads as the name, not the id it is stored as.
    assert "@[]" not in data["task"]["description"]
    assert b.user.username in data["task"]["description"]
    # Only the linked task still to do; a finished one has nothing to add.
    assert data["linked_tasks"] == ["Find a caterer (this task depends_on it)"]
    # A removed comment is neither sent nor counted.
    texts = [c["text"] for c in data["comments"]]
    assert texts == ["first", "second", "third", "reply"]
    assert (whole.comments_read, whole.comments_total) == (4, 4)

    # With no room, the task still goes in, and the result says what was left.
    bare = await told(0)
    assert "comments" not in json.loads(bare.data)
    assert (bare.comments_read, bare.comments_total) == (0, 4)

    # Room for one: the newest, though it answers the oldest conversation.
    newest = data["comments"][-1]
    one = await ai_context._recent_comments(
        reading, task.id, room=len(ai_context._dumps(newest)) + 1
    )
    assert one == ([newest], 4)
