"""Reading live smart chip state through the API.

A chip stores nothing, so what these assert is that the chip reflects the row
it points at right now — including after the row changes — and that it answers
under the same gates as the thing it is about.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.smart_chips import SMART_CHIP_KINDS, SmartChipKind, kind_value
from app.models.platform.guild import CommunityRole
from sqlmodel import select

from app.models.tenant.task import TaskPriority, TaskStatus, TaskStatusCategory
from app.core.references import NOT_REFERENCEABLE, REFERENCEABLE_TYPES
from app.db.reference_targets import referenceable_types
from app.schemas.tenant.smart_chip import MAX_EMBEDS, MAX_REFS
from app.services.tenant.smart_chips import SMART_CHIP_SOURCES
from app.testing import (
    create_resource_grant,
    Actor,
    create_calendar,
    create_calendar_event,
    create_counter,
    create_comment,
    create_counter_group,
    create_file,
    create_queue,
    create_queue_item,
    create_task,
    create_task_status,
    create_user,
    create_wiki,
    create_wiki_page,
)
from app.core.file_types import FileType


ActingUser = Callable[..., Awaitable[Actor]]


async def _status_of(session, task) -> TaskStatus:
    """The column a task currently sits in."""
    return (
        await session.exec(
            select(TaskStatus).where(TaskStatus.id == task.task_status_id)
        )
    ).one()


async def _move_to(session, task, project, category: TaskStatusCategory) -> None:
    """Move a card, the way a person would — the file is not touched."""
    status = await create_task_status(
        session, project, name=category.value.title(), category=category
    )
    task.task_status_id = status.id
    session.add(task)
    await session.commit()


async def _chips(client, actor: Actor, *refs: str) -> dict[str, dict]:
    response = await client.post(
        actor.g("/smart-chips/"), headers=actor.headers, json={"refs": list(refs)}
    )
    assert response.status_code == 200, response.text
    return {item["ref"]: item for item in response.json()["items"]}


async def test_a_task_chip_shows_the_column_it_sits_in(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(
        session,
        a.project,
        title="Ship it",
        status_category=TaskStatusCategory.in_progress,
    )

    body = await _chips(client, a, f"task:{task.id}:status")
    assert body[f"task:{task.id}:status"]["text"]
    assert body[f"task:{task.id}:status"]["tone"] == "warn"


async def test_moving_the_card_moves_the_chip(
    client, session, acting_user: ActingUser
) -> None:
    """The file is not edited and the chip still changes — which is the
    whole point of a chip over a mention."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    ref = f"task:{task.id}:status"
    before = (await _chips(client, a, ref))[ref]
    assert before["tone"] != "good"

    await _move_to(session, task, a.project, TaskStatusCategory.done)

    after = (await _chips(client, a, ref))[ref]
    assert after["tone"] == "good"
    assert after["text"] != before["text"]


async def test_a_status_sends_its_own_colour(
    client, session, acting_user: ActingUser
) -> None:
    """A project picks its own colours, so the chip wears them rather than a
    tone this end invented."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Waiting")
    status = await _status_of(session, task)
    status.color = "#FF00AA"
    session.add(status)
    await session.commit()

    body = await _chips(client, a, f"task:{task.id}:status")
    assert body[f"task:{task.id}:status"]["color"] == "#FF00AA"


async def test_a_date_is_late_only_while_the_work_is_not_done(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    task = await create_task(session, a.project, title="Overdue", due_date=yesterday)

    ref = f"task:{task.id}:due"
    assert (await _chips(client, a, ref))[ref]["tone"] == "danger"

    await _move_to(session, task, a.project, TaskStatusCategory.done)

    # Delivered late is delivered, not overdue.
    assert (await _chips(client, a, ref))[ref]["tone"] == "neutral"


async def test_the_date_itself_comes_back_for_the_reader_to_format(
    client, session, acting_user: ActingUser
) -> None:
    """A date belongs in the reader's locale, which only their browser knows."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    due = datetime.now(timezone.utc) + timedelta(days=3)
    task = await create_task(session, a.project, title="Soon", due_date=due)

    body = await _chips(client, a, f"task:{task.id}:due")
    assert body[f"task:{task.id}:due"]["date"] is not None


async def test_an_unassigned_task_says_so_rather_than_going_missing(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Nobody's")

    body = await _chips(client, a, f"task:{task.id}:assignee")
    assert body[f"task:{task.id}:assignee"]["tone"] == "muted"


async def test_two_holders_are_named_and_more_are_counted(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    second = await create_user(session)
    third = await create_user(session)
    pair = await create_task(
        session, a.project, title="Pair", assignees=[a.user, second]
    )
    crowd = await create_task(
        session, a.project, title="Crowd", assignees=[a.user, second, third]
    )

    body = await _chips(
        client, a, f"task:{pair.id}:assignee", f"task:{crowd.id}:assignee"
    )
    pair_text = body[f"task:{pair.id}:assignee"]["text"]
    assert ", " in pair_text and "+" not in pair_text
    crowd_text = body[f"task:{crowd.id}:assignee"]["text"]
    assert crowd_text.startswith(pair_text) and crowd_text.endswith(" +1")


async def test_a_priority_carries_its_own_urgency(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(
        session, a.project, title="Now", priority=TaskPriority.urgent
    )

    body = await _chips(client, a, f"task:{task.id}:priority")
    assert body[f"task:{task.id}:priority"]["tone"] == "danger"


async def test_a_checkbox_reads_whether_the_task_is_finished(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Take attendance")

    open_state = (await _chips(client, a, f"task:{task.id}:checklist"))[
        f"task:{task.id}:checklist"
    ]
    assert open_state["tone"] == "neutral"
    assert open_state["title"] == "Take attendance"
    assert open_state["writable"] is True

    await _move_to(session, task, a.project, TaskStatusCategory.done)
    done_state = (await _chips(client, a, f"task:{task.id}:checklist"))[
        f"task:{task.id}:checklist"
    ]
    assert done_state["tone"] == "good"


async def test_a_checkbox_is_offered_only_to_whoever_may_tick_it(
    client, session, acting_user: ActingUser
) -> None:
    """Read access shows the box; only write access lets it be ticked. Every
    other chip is a reading, so none of them claims to be writable."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, a.project, user=b.user)
    task = await create_task(session, a.project)

    body = await _chips(
        client, b, f"task:{task.id}:checklist", f"task:{task.id}:status"
    )
    assert body[f"task:{task.id}:checklist"]["writable"] is False
    assert body[f"task:{task.id}:status"]["writable"] is False


async def test_an_embed_shows_the_name_and_the_description(
    client, session, acting_user: ActingUser
) -> None:
    """A kind without a description column embeds as its name alone, and
    something that is not there is absent, as it is for a chip."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(
        session, a.project, title="Roll call", description="Bring the **sheet**."
    )
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group, name="Signups")
    missing = f"task:{task.id + 999}"

    response = await client.post(
        a.g("/smart-chips/embeds"),
        headers=a.headers,
        json={"refs": [f"task:{task.id}", f"counter:{counter.id}", missing]},
    )
    assert response.status_code == 200, response.text
    body = {item["ref"]: item for item in response.json()["items"]}
    assert body[f"task:{task.id}"]["title"] == "Roll call"
    assert body[f"task:{task.id}"]["description"] == "Bring the **sheet**."
    assert body[f"counter:{counter.id}"]["title"] == "Signups"
    assert body[f"counter:{counter.id}"]["description"] is None
    assert missing not in body


def _prose(text: str) -> dict:
    """A Lexical body holding one paragraph."""
    return {
        "root": {
            "type": "root",
            "version": 1,
            "children": [
                {
                    "type": "paragraph",
                    "version": 1,
                    "children": [{"type": "text", "version": 1, "text": text}],
                }
            ],
        }
    }


async def _embeds(client, actor: Actor, *refs: str) -> dict[str, dict]:
    response = await client.post(
        actor.g("/smart-chips/embeds"),
        headers=actor.headers,
        json={"refs": list(refs)},
    )
    assert response.status_code == 200, response.text
    return {item["ref"]: item for item in response.json()["items"]}


async def test_an_embedded_text_file_shows_its_body(
    client, session, acting_user: ActingUser
) -> None:
    """Prose embeds as what it says; a file that is not prose, one with
    nothing written in it, and a kind with no body at all embed as a name."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    written = await create_file(
        session, a.initiative, a.user, name="Lore", content=_prose("Here be dragons.")
    )
    blank = await create_file(session, a.initiative, a.user, name="Blank")
    sheet = await create_file(
        session,
        a.initiative,
        a.user,
        name="Ledger",
        file_type=FileType.sheet,
        content={"cells": {"A1": "1"}},
    )
    task = await create_task(session, a.project, title="Roll call")

    body = await _embeds(
        client,
        a,
        f"file:{written.id}",
        f"file:{blank.id}",
        f"file:{sheet.id}",
        f"task:{task.id}",
    )
    assert body[f"file:{written.id}"]["title"] == "Lore"
    assert body[f"file:{written.id}"]["body"] == _prose("Here be dragons.")
    assert body[f"file:{blank.id}"]["body"] is None
    assert body[f"file:{sheet.id}"]["title"] == "Ledger"
    assert body[f"file:{sheet.id}"]["body"] is None
    assert body[f"task:{task.id}"]["body"] is None


async def test_an_embedded_wiki_page_shows_its_body_but_not_a_draft(
    client, session, acting_user: ActingUser
) -> None:
    """A draft is hidden from a reader everywhere else, so an embed of one is
    absent to them rather than a window onto it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    initiative = a.initiative
    assert initiative is not None
    initiative.wikis_enabled = True
    session.add(initiative)
    await session.commit()
    wiki = await create_wiki(session, initiative, a.user)
    page = await create_wiki_page(
        session, wiki, a.user, title="Rota", content=_prose("Tuesdays.")
    )
    draft = await create_wiki_page(
        session,
        wiki,
        a.user,
        title="Half written",
        content=_prose("Secret."),
        is_draft=True,
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    body = await _embeds(client, b, f"wiki_page:{page.id}", f"wiki_page:{draft.id}")
    assert body[f"wiki_page:{page.id}"]["body"] == _prose("Tuesdays.")
    assert f"wiki_page:{draft.id}" not in body

    written = await _embeds(client, a, f"wiki_page:{draft.id}")
    assert written[f"wiki_page:{draft.id}"]["body"] == _prose("Secret.")


async def test_a_counter_reads_its_number_and_its_ceiling(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    counter.count = Decimal("7")
    counter.max = Decimal("10")
    session.add(counter)
    await session.commit()

    body = await _chips(client, a, f"counter:{counter.id}:value")
    state = body[f"counter:{counter.id}:value"]
    # Trailing zeros are storage, not something to read.
    assert state["text"] == "7 / 10"
    assert state["tone"] == "neutral"


async def test_a_project_reads_how_much_of_its_work_is_done(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, status_category=TaskStatusCategory.done)
    await create_task(session, a.project, status_category=TaskStatusCategory.todo)
    await create_task(session, a.project, status_category=TaskStatusCategory.todo)

    body = await _chips(client, a, f"project:{a.project.id}:progress")
    state = body[f"project:{a.project.id}:progress"]
    assert state["text"] == "1 / 3"
    assert state["tone"] == "neutral"


async def test_a_project_with_all_its_work_done_reads_as_arrived(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, status_category=TaskStatusCategory.done)
    await create_task(session, a.project, status_category=TaskStatusCategory.done)

    body = await _chips(client, a, f"project:{a.project.id}:progress")
    state = body[f"project:{a.project.id}:progress"]
    assert state["text"] == "2 / 2"
    assert state["tone"] == "good"


async def test_a_project_with_no_work_in_it_does_not_read_as_finished(
    client, session, acting_user: ActingUser
) -> None:
    """0 / 0 is not an achievement."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    body = await _chips(client, a, f"project:{a.project.id}:progress")
    state = body[f"project:{a.project.id}:progress"]
    assert state["text"] == "0 / 0"
    assert state["tone"] == "muted"


async def test_a_counter_at_its_ceiling_reads_as_arrived(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    counter.count = Decimal("10")
    counter.max = Decimal("10")
    session.add(counter)
    await session.commit()

    body = await _chips(client, a, f"counter:{counter.id}:value")
    assert body[f"counter:{counter.id}:value"]["tone"] == "good"


async def test_an_event_dims_once_it_has_happened(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    calendar = await create_calendar(session, a.initiative, a.user)
    past = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    soon = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=datetime.now(timezone.utc) + timedelta(days=2),
    )
    # A repeat reads as its next occurrence, and dims on its last once it ends.
    began = (datetime.now(timezone.utc) - timedelta(days=10, hours=-1)).replace(
        microsecond=0
    )
    daily = await create_calendar_event(
        session, calendar, a.user, start_at=began, recurrence="RRULE:FREQ=DAILY"
    )
    ended = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=began,
        recurrence="RRULE:FREQ=DAILY;COUNT=3",
    )

    body = await _chips(
        client,
        a,
        *(f"calendar_event:{event.id}:when" for event in (past, soon, daily, ended)),
    )
    assert body[f"calendar_event:{past.id}:when"]["tone"] == "muted"
    assert body[f"calendar_event:{soon.id}:when"]["tone"] == "neutral"
    assert [
        (
            body[f"calendar_event:{event.id}:when"]["tone"],
            datetime.fromisoformat(body[f"calendar_event:{event.id}:when"]["date"]),
        )
        for event in (daily, ended)
    ] == [
        ("neutral", began + timedelta(days=10)),
        ("muted", began + timedelta(days=2)),
    ]


async def test_a_page_of_chips_is_read_together(
    client, session, acting_user: ActingUser
) -> None:
    """Two aspects of one task, and a second thing entirely, in one request."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)

    body = await _chips(
        client,
        a,
        f"task:{task.id}:status",
        f"task:{task.id}:priority",
        f"counter:{counter.id}:value",
    )
    assert len(body) == 3


async def test_a_reference_naming_nothing_is_simply_absent(
    client, session, acting_user: ActingUser
) -> None:
    """A build that stopped offering a chip leaves references behind in
    files; they read as nothing rather than as an error."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")

    body = await _chips(
        client,
        a,
        f"task:{task.id}:status",
        "task:999999:status",
        "file:1:status",
        "not-a-ref",
        "task:abc:status",
    )
    assert list(body) == [f"task:{task.id}:status"]


async def test_a_chip_reads_nothing_the_caller_could_not_open(
    client, session, acting_user: ActingUser
) -> None:
    """The reference is in a file, which anyone in the initiative may read.
    What it points at is gated separately, and this is that gate."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, owner.project, title="Private work")

    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    body = await _chips(client, outsider, f"task:{task.id}:status")
    assert body == {}


def test_every_declared_chip_has_a_reader():
    """The vocabulary and the readers are two lists in two layers; this is what
    keeps them the same list. Titles are not here — one reader answers those
    for every kind."""
    assert set(SMART_CHIP_SOURCES) == set(SMART_CHIP_KINDS)


def test_the_pairs_the_api_declares_are_the_pairs_that_exist():
    """The editor builds its insert menu from this enum, so it must not be able
    to offer a chip nothing reads."""
    assert {kind.value for kind in SmartChipKind} == {
        kind_value(entity_type, aspect) for entity_type, aspect in SMART_CHIP_KINDS
    }


async def test_a_chip_stops_at_the_sharing_gate_not_just_the_initiative(
    client, session, acting_user: ActingUser
) -> None:
    """Being in the initiative is not being given the project.

    A chip is live state, so it answers under every gate the thing itself
    answers under — the same reading the search index takes.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="restricted renewal")

    assert (await _chips(client, a, f"task:{task.id}:status")) != {}
    assert await _chips(client, b, f"task:{task.id}:status") == {}


def test_every_chippable_thing_can_be_gated():
    """A chip reads live state, so its kind must resolve to a gate. Those are
    derived from the search registry, so this is what proves the derivation
    covers everything a chip can be about."""
    referenceable = set(referenceable_types())
    assert {entity_type for entity_type, _aspect in SMART_CHIP_KINDS} <= referenceable


def test_the_reference_surface_is_everything_indexed_but_a_comment():
    """Referenceable is derived, not listed. A tool added to the search
    registry becomes linkable, resolvable and gated with no edit here."""
    from app.db.search_index import SEARCH_SOURCES

    indexed = {source.entity_type for source in SEARCH_SOURCES.values()}
    assert set(referenceable_types()) == indexed - NOT_REFERENCEABLE


def test_what_can_be_referred_to_and_what_can_be_resolved_are_the_same_set():
    """One is declared from the kinds a reference may name, the other derived
    from the tables that can answer. A tool in one and not the other would be
    linkable and unresolvable, or resolvable and unreachable."""
    assert set(REFERENCEABLE_TYPES) == set(referenceable_types())


@pytest.mark.parametrize(
    "aspect", ["status", "assignee", "due", "priority", "checklist"]
)
async def test_no_task_chip_answers_without_the_project(
    client, session, acting_user: ActingUser, aspect: str
) -> None:
    """Walked per aspect: the gate is applied once for the thing, so adding a
    fifth fact about a task cannot open a hole."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="restricted")

    assert await _chips(client, b, f"task:{task.id}:{aspect}") == {}


async def test_a_chip_follows_the_thing_own_sharing_either_way(
    client, session, acting_user: ActingUser
) -> None:
    """The gate is the resource's own sharing, not a rule chips invented.

    Both of these are made by a factory, which shares a calendar with the
    initiative and leaves a counter group to its owner. Whichever way the
    sharing goes, the chip follows it — which is the thing being asserted. (The
    create endpoints both default to Viewer for the initiative; the factories
    are not trying to mirror them.)
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    calendar = await create_calendar(session, a.initiative, a.user)
    event = await create_calendar_event(session, calendar, a.user)

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    body = await _chips(
        client,
        b,
        f"counter:{counter.id}:value",
        f"calendar_event:{event.id}:when",
    )
    assert f"counter:{counter.id}:value" not in body
    assert f"calendar_event:{event.id}:when" in body


async def test_the_ceiling_is_refused_rather_than_quietly_trimmed(
    client, session, acting_user: ActingUser
) -> None:
    """A page asking about more than one request carries is told so.

    Answering the first ``MAX_REFS`` and dropping the rest would look exactly
    like a page whose remaining things had all been deleted, which is a worse
    answer than none: the client batches to this number instead.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")

    at_the_line = [f"task:{task.id}:status"] * 1 + [
        f"task:{9000 + i}:status" for i in range(MAX_REFS - 1)
    ]
    response = await client.post(
        a.g("/smart-chips/"), headers=a.headers, json={"refs": at_the_line}
    )
    assert response.status_code == 200

    over = [*at_the_line, f"task:{9999}:status"]
    response = await client.post(
        a.g("/smart-chips/"), headers=a.headers, json={"refs": over}
    )
    assert response.status_code == 422

    # An embed answers with a whole body, so its ceiling is its own.
    embeds = [f"task:{task.id + i}" for i in range(MAX_EMBEDS + 1)]
    response = await client.post(
        a.g("/smart-chips/embeds"), headers=a.headers, json={"refs": embeds}
    )
    assert response.status_code == 422


async def test_a_chip_names_what_its_reading_is_about(
    client, session, acting_user: ActingUser
) -> None:
    """A chip answers with the thing's current name beside the fact, so showing
    a fact costs one reference rather than two — and the name is as live as the
    reading is."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Old name")
    ref = f"task:{task.id}:status"

    assert (await _chips(client, a, ref))[ref]["title"] == "Old name"

    task.title = "New name"
    session.add(task)
    await session.commit()

    answer = (await _chips(client, a, ref))[ref]
    assert answer["title"] == "New name"
    # The reading itself is still the column, not the name.
    assert answer["text"] != "New name"


async def test_a_reference_reads_the_current_name(
    client, session, acting_user: ActingUser
) -> None:
    """The point of the whole thing: rename it, and what points at it says the
    new name without being touched."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Old name")
    ref = f"task:{task.id}"

    assert (await _chips(client, a, ref))[ref]["text"] == "Old name"

    task.title = "New name"
    session.add(task)
    await session.commit()

    assert (await _chips(client, a, ref))[ref]["text"] == "New name"


async def test_every_kind_answers_with_whatever_it_calls_its_name(
    client, session, acting_user: ActingUser
) -> None:
    """A queue item has a label, a task a title, a project a name. The column is
    derived from the search registry, so none of them is written down twice."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="A task")
    queue = await create_queue(session, a.initiative, a.user)
    item = await create_queue_item(session, queue, label="An item")

    body = await _chips(
        client,
        a,
        f"task:{task.id}",
        f"project:{a.project.id}",
        f"queue:{queue.id}",
        f"queue_item:{item.id}",
    )
    assert body[f"task:{task.id}"]["text"] == "A task"
    assert body[f"project:{a.project.id}"]["text"] == a.project.name
    assert body[f"queue:{queue.id}"]["text"] == queue.name
    assert body[f"queue_item:{item.id}"]["text"] == "An item"


async def test_a_title_stops_at_the_same_gate_a_chip_does(
    client, session, acting_user: ActingUser
) -> None:
    """A name is content. Reading one is gated exactly as reading a status is."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="restricted")

    assert await _chips(client, b, f"task:{task.id}") == {}


async def test_a_comment_is_not_something_you_point_at(
    client, session, acting_user: ActingUser
) -> None:
    """Comments are indexed but not referenceable — the thing a remark is on is
    what a reader wants, and a comment has no name to render."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    comment = await create_comment(session, a.user, task=task)

    assert await _chips(client, a, f"comment:{comment.id}") == {}
