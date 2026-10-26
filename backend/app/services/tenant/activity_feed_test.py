"""The activity feed: one entry per item people changed lately, gated and
ordered for the reader, and the catch-up written from it."""

import json
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.tools import Tool
from app.core.user_display import handle_of
from app.db.request_context import SystemGuild
from app.db.session import clear_rls_context, set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.schemas.ai_settings import AIProvider, ConnectionScope, ResolvedAISettings
from app.services import ai_context, ai_generation, ai_provider
from app.services.tenant import activity_feed, personal_items
from app.services.tenant.activity_feed import FeedView
from app.services.tenant.personal_items import Mark
from app.testing import (
    create_comment,
    create_project,
    create_resource_grant,
    create_task,
    emitted,
)


async def _log(session: AsyncSession, guild_id: int, sql: str, **params) -> None:
    await set_rls_context(session, SystemGuild(guild_id))
    await session.exec(text(sql).bindparams(**params))  # type: ignore[call-overload]
    await session.commit()
    clear_rls_context(session)


async def _by(session: AsyncSession, guild_id: int, user_id: int) -> None:
    """Whoever made the changes not yet put down to anybody: a factory writes
    as no one, which makes no entry."""
    await _log(
        session,
        guild_id,
        "UPDATE event_outbox SET actor_user_id = :who WHERE actor_user_id IS NULL",
        who=user_id,
    )


async def _start(session: AsyncSession, acting_user):
    """A member who owns a project, a second member it is shared with, and an
    empty log."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, a.project, user=b.user)
    await _log(session, a.guild.id, "DELETE FROM event_outbox")
    return a, b


async def _feed(reading_as, person, **narrowing):
    s = await reading_as(person.user.id, person.guild.id)
    entries, _more = await activity_feed.feed(s, reader_id=person.user.id, **narrowing)
    return entries


async def test_an_entry_is_an_item_and_what_people_did_to_it(
    session, acting_user, reading_as
):
    """A comment counts for the task it is on; the people are named latest
    first; the reader's own changes make no entry; a reaction makes none."""
    a, b = await _start(session, acting_user)
    task = await create_task(session, a.project, title="Book the hall")
    await _by(session, a.guild.id, b.user.id)
    await create_comment(session, a.user, task=task)
    await _by(session, a.guild.id, a.user.id)

    (entry,) = await _feed(reading_as, b)
    assert (entry.entity_type, entry.entity_id, entry.title) == (
        "task",
        task.id,
        "Book the hall",
    )
    assert entry.verbs == ["commented"]
    assert [p.id for p in entry.actors] == [a.user.id]
    assert entry.tool == Tool.project.value and entry.tool_id == a.project.id

    (entry,) = await _feed(reading_as, a)
    assert entry.verbs == ["created"] and entry.actor_count == 1

    await _log(
        session,
        a.guild.id,
        "UPDATE event_outbox SET action = 'updated', changed = '{reactions}'",
    )
    assert await _feed(reading_as, a) == []


async def test_only_what_the_reader_can_open(session, acting_user, reading_as):
    """A member the project is not shared with sees none of it."""
    a, _b = await _start(session, acting_user)
    outsider = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project)
    await _by(session, a.guild.id, a.user.id)

    assert await _feed(reading_as, outsider) == []


async def test_views_and_narrowing(session, acting_user, reading_as):
    """Yours is what the reader is assigned to, made or changed; Comments is
    what somebody commented on; a tool narrows to its own."""
    a, b = await _start(session, acting_user)
    other = await create_project(session, a.initiative, a.user)
    await create_resource_grant(session, other, user=b.user)
    assigned = await create_task(session, a.project, assignees=[b.user])
    commented = await create_task(session, a.project)
    elsewhere = await create_task(session, other)
    await _by(session, a.guild.id, a.user.id)
    await create_comment(session, a.user, task=commented)
    await _by(session, a.guild.id, a.user.id)

    def ids(entries):
        return {e.entity_id for e in entries if e.entity_type == "task"}

    assert ids(await _feed(reading_as, b, view=FeedView.yours)) == {assigned.id}
    assert ids(await _feed(reading_as, b, view=FeedView.comments)) == {commented.id}
    assert ids(await _feed(reading_as, b, tool=Tool.project, tool_id=a.project.id)) == {
        assigned.id,
        commented.id,
    }
    assert elsewhere.id in ids(await _feed(reading_as, b))


async def test_subscribing_to_an_item_or_its_tool_lifts_it(
    session, acting_user, reading_as
):
    """Unsubscribed, the newer change leads. Subscribing to the older item, or the
    project it is in, puts it first."""
    a, b = await _start(session, acting_user)
    other = await create_project(session, a.initiative, a.user)
    await create_resource_grant(session, other, user=b.user)
    older = await create_task(session, a.project)
    newer = await create_task(session, other)
    await _by(session, a.guild.id, a.user.id)

    async def tasks() -> list[int]:
        return [
            e.entity_id for e in await _feed(reading_as, b) if e.entity_type == "task"
        ]

    async def mark(kind: str, entity_id: int, on: bool) -> None:
        s = await reading_as(b.user.id, b.guild.id)
        change = personal_items.set_mark if on else personal_items.clear_mark
        await change(
            s, user_id=b.user.id, mark=Mark.subscribe, kind=kind, entity_id=entity_id
        )

    assert await tasks() == [newer.id, older.id]
    await mark("task", older.id, True)
    assert await tasks() == [older.id, newer.id]
    await mark("task", older.id, False)
    await mark("project", a.project.id, True)
    assert await tasks() == [older.id, newer.id]


async def test_only_the_latest_completion_reads_as_completed(
    session, acting_user, reading_as
):
    """The log says only that completion changed. One person reopens a done
    task and another completes it again: the reopening reads as moved."""
    a, b = await _start(session, acting_user)
    task = await create_task(
        session, a.project, status_category=TaskStatusCategory.done
    )
    await _log(session, a.guild.id, "DELETE FROM event_outbox")
    for who, completed in ((a.user.id, "NULL"), (b.user.id, "now()")):
        await _log(
            session,
            a.guild.id,
            f"UPDATE tasks SET completed_at = {completed} WHERE id = :task",
            task=task.id,
        )
        await _by(session, a.guild.id, who)

    (entry,) = await _feed(reading_as, b)
    assert entry.verbs == ["moved"]
    (entry,) = await _feed(reading_as, a)
    assert entry.verbs == ["completed"]


async def test_the_endpoint_narrows_to_a_tool_only_with_its_id(client, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.get(a.g("/activity/?tool=project"), headers=a.headers)
    assert response.status_code == 422

    response = await client.get(a.g("/activity/"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "has_next": False,
    }


async def test_a_feed_since_a_moment_reads_the_changes_after_it(
    session, acting_user, reading_as
):
    """A moment before the change log's window reads the whole window."""
    a, b = await _start(session, acting_user)
    old = await create_task(session, a.project, title="Old news")
    await _log(
        session,
        a.guild.id,
        "UPDATE event_outbox SET occurred_at = now() - interval '3 days'",
    )
    new = await create_task(session, a.project, title="Fresh")
    await _by(session, a.guild.id, a.user.id)

    def ids(entries):
        return {e.entity_id for e in entries if e.entity_type == "task"}

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    assert ids(await _feed(reading_as, b, since=yesterday)) == {new.id}
    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    assert ids(await _feed(reading_as, b, since=long_ago)) == {old.id, new.id}


def _answering(monkeypatch, text: str) -> list[tuple]:
    """A connection that answers ``text``; keeps the prompts it was sent."""
    resolved = ResolvedAISettings(
        enabled=True,
        provider=AIProvider.openai,
        api_key="sk-not-a-real-key",
        model="m",
        scope=ConnectionScope.platform,
        connection_id=1,
        source="platform",
    )
    asked: list[tuple] = []

    async def resolve(*args, **kwargs):
        return resolved

    async def record_health(*args):
        pass

    async def stream_text(target, job, prompt, *, guild_id):
        asked.append(prompt)
        yield text

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", resolve)
    monkeypatch.setattr(ai_generation, "record_health", record_health)
    monkeypatch.setattr(ai_provider, "stream_text", stream_text)
    return asked


async def test_a_catch_up_tells_only_what_the_reader_can_see(
    client, session, acting_user, monkeypatch, capfd
):
    a, b = await _start(session, acting_user)
    elsewhere = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=True, project=True
    )
    await create_task(session, a.project, title="Book the hall")
    await create_task(session, elsewhere.project, title="Plan the surprise")
    await _by(session, a.guild.id, a.user.id)
    asked = _answering(monkeypatch, "The hall is being booked.")
    capfd.readouterr()

    response = await client.post(b.g("/activity/catch-up"), headers=b.headers, json={})

    assert response.status_code == 200, response.text
    since, *rest = (json.loads(line) for line in response.text.splitlines())
    assert "since" in since
    assert rest == [{"text": "The hall is being booked."}]
    ((_system, data),) = asked
    # An initiative the reader is not in tells them nothing.
    assert "Book the hall" in data and "Plan the surprise" not in data
    (row,) = emitted(capfd, AuditEventType.AI_REQUEST_SENT)
    assert row["target"] == {"type": "community", "id": a.guild.id}
    assert row["detail"]["purpose"] == "catch_up"


async def test_a_catch_up_with_nothing_new_sends_nothing(
    client, session, acting_user, monkeypatch, capfd
):
    """It says where it looked from, a week back at the most, and stops."""
    a, b = await _start(session, acting_user)
    asked = _answering(monkeypatch, "Unused.")
    capfd.readouterr()
    asked_from = datetime.now(timezone.utc) - timedelta(days=30)

    response = await client.post(
        b.g("/activity/catch-up"),
        headers=b.headers,
        json={
            "since": asked_from.isoformat(),
            "tool": Tool.project.value,
            "tool_id": a.project.id,
        },
    )

    assert response.status_code == 200, response.text
    (line,) = (json.loads(line) for line in response.text.splitlines())
    since = datetime.fromisoformat(line["since"])
    assert since - asked_from > timedelta(days=22)
    assert asked == []
    assert emitted(capfd, AuditEventType.AI_REQUEST_SENT) == []


async def test_a_catch_up_tells_as_much_as_its_budget_holds(
    session, acting_user, reading_as
):
    a, b = await _start(session, acting_user)
    await create_task(session, a.project, title="Book the hall")
    await create_task(session, a.project, title="Order the chairs")
    await _by(session, a.guild.id, a.user.id)
    s = await reading_as(b.user.id, b.guild.id)

    async def told(budget: int) -> ai_context.ActivityContext:
        return await ai_context.activity_context(
            s, reader_id=b.user.id, since=None, tool=None, tool_id=None, budget=budget
        )

    whole = await told(6000)
    assert (whole.entries_read, whole.entries_total) == (2, 2)
    first = whole.data.splitlines()[0]
    assert json.loads(first)["by"] == [handle_of(a.user)]

    one = await told(math.ceil((len(first) + 1) / 4))
    assert (one.entries_read, one.entries_total) == (1, 2)
    assert one.data == first
