"""Searching a guild through the API.

The gates are the index's own policies, so these assert what a *request* gets
back: that a match is found across tools, that the caller's access decides the
result set, and that the two shapes a client depends on — exact totals and a
route to the thing found — hold.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.core.tools import Tool
from app.db import cohorts
from app.models.platform.guild import CommunityRole
from app.models.tenant.engagement_level import LEVEL_MAX, EngagementLevel
from app.services.tenant.post_publication import publish_due_posts
from app.testing import (
    Actor,
    create_comment,
    create_file,
    create_post,
    create_project,
    create_resource_grant,
    create_tag,
    create_task,
    create_wiki,
    create_wiki_page,
    lexical_body,
    route_system,
    switch_tools,
)

ActingUser = Callable[..., Awaitable[Actor]]


async def _search(client, actor: Actor, **params) -> dict:
    response = await client.get(
        actor.g("/search/"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_person_is_found_where_they_are_mentioned(
    client, session, acting_user: ActingUser
) -> None:
    """By the words that name them now, with no name written in the text: their
    name in this community, or their handle. A name they no longer have, or a
    person no longer here, finds nothing."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    ada = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    membership = ada.membership
    assert membership is not None
    membership.display_name = "Ada Countess"
    session.add(membership)
    await session.commit()
    await create_task(
        session,
        a.project,
        title="budget review",
        description=f"with @[]({ada.user.id})",
    )
    await create_file(
        session,
        a.initiative,
        a.user,
        name="minutes",
        content=lexical_body("Thanks ", mentioning=ada.user.id),
    )

    async def found(q: str) -> list[str]:
        # What matched, not the close titles offered when nothing did.
        body = await _search(client, a, search=q)
        return [] if body["fuzzy"] else sorted(h["title"] for h in body["items"])

    both = ["budget review", "minutes"]
    assert await found("countess") == both
    # A name is matched whole: three letters do not name everyone they start.
    assert await found("Coun") == []
    assert await found(ada.user.username) == both
    assert await found(f"{ada.user.username}#{ada.user.discriminator:04d}") == both
    assert await found("countess budget") == ["budget review"]
    assert await found("budget -countess") == []
    assert await found('budget -"ada countess"') == []
    assert await found('ada "ada countess" budget') == ["budget review"]

    membership.display_name = "Duchess"
    session.add(membership)
    await session.commit()
    assert await found("duchess") == both
    assert await found("countess") == []

    await session.delete(membership)
    await session.commit()
    assert await found("duchess") == []
    assert await found(ada.user.username) == []


async def test_it_finds_across_tools_in_one_query(
    client, session, acting_user: ActingUser
) -> None:
    """The point of the whole thing: one query, not one per tool."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="renewal task")
    await create_file(session, a.initiative, a.user, name="renewal doc")
    await create_tag(session, a.guild, name="renewal")

    body = await _search(client, a, search="renewal")
    assert {h["entity_type"] for h in body["items"]} == {"task", "file", "tag"}


async def test_a_hit_carries_what_it_takes_to_reach_it(
    client, session, acting_user: ActingUser
) -> None:
    """A task is opened through its project, so the hit has to name it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="routable")

    body = await _search(client, a, search="routable")
    assert body["total_count"] == 1
    hit = body["items"][0]
    assert hit["entity_type"] == "task"
    assert hit["entity_id"] == task.id
    assert hit["tool"] == "project"
    assert hit["tool_id"] == a.project.id
    assert hit["initiative_id"] == a.initiative.id


async def test_a_body_match_returns_a_snippet(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_file(
        session,
        a.initiative,
        a.user,
        name="Handbook",
        content={
            "root": {
                "children": [
                    {
                        "type": "paragraph",
                        "children": [
                            {"type": "text", "text": "the vendor renewal window"}
                        ],
                    }
                ]
            }
        },
    )
    hit = (await _search(client, a, search="renewal window"))["items"][0]
    assert hit["title"] == "Handbook"
    assert "renewal" in (hit["snippet"] or "")


async def test_it_can_be_narrowed_by_type_and_initiative(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="narrow me")
    await create_file(session, a.initiative, a.user, name="narrow me too")

    only_tasks = await _search(client, a, search="narrow", types=["task"])
    assert {h["entity_type"] for h in only_tasks["items"]} == {"task"}

    elsewhere = await _search(
        client, a, search="narrow", initiative_id=a.initiative.id + 999
    )
    assert elsewhere["items"] == []


async def test_an_empty_query_is_not_an_error(client, acting_user: ActingUser) -> None:
    a = await acting_user(guild_role=CommunityRole.admin)
    body = await _search(client, a, search="   ")
    assert body == {
        "items": [],
        "total_count": 0,
        "page": 1,
        "page_size": 20,
        "has_next": False,
        "has_prev": False,
        "fuzzy": False,
    }


async def test_comments_are_reached_by_asking_for_them(
    client, session, acting_user: ActingUser
) -> None:
    """Comments are out of the default scope — the busiest table in a guild is
    not something every bare query should pay for — so a caller names the type,
    which is what the results page's own tab does."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="stage build")
    # Its opening is its title, which leaves out a mention the cut goes through.
    opening = "the vendor confirmed the platform " + "." * 101 + " "
    await create_comment(
        session, a.user, task=task, content=f"{opening}@[]({a.user.id}) done"
    )

    unasked = await client.get(
        a.g("/search/"), headers=a.headers, params={"search": "vendor confirmed"}
    )
    assert unasked.status_code == 200, unasked.text
    assert unasked.json()["items"] == []

    asked = await client.get(
        a.g("/search/"),
        headers=a.headers,
        params={"search": "vendor confirmed", "types": ["comment"]},
    )
    assert asked.status_code == 200, asked.text
    items = asked.json()["items"]
    assert [i["entity_type"] for i in items] == ["comment"]
    # It names the project, because that is where a comment on a task is read.
    assert items[0]["tool"] == "project"
    assert items[0]["tool_id"] == a.project.id
    assert items[0]["title"] == opening


async def test_an_unknown_type_is_refused_rather_than_ignored(
    client, session, acting_user: ActingUser
) -> None:
    """A kind the community does not have is not found — not a search that
    quietly returns everything."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"search": "x", "types": ["invoice"]}
    )
    assert response.status_code == 404, response.text


async def test_a_non_member_cannot_search_the_guild(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    outsider = await acting_user(guild_role=CommunityRole.admin)
    await create_task(session, a.project, title="private renewal")

    response = await client.get(
        a.g("/search/"), headers=outsider.headers, params={"search": "renewal"}
    )
    assert response.status_code == 403


async def test_suggest_offers_only_titles_that_match(
    client, session, acting_user: ActingUser
) -> None:
    """The palette shows titles, so a hit whose title shows nothing of what was
    typed reads as a mistake — even when the word is genuinely in the body."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_file(
        session,
        a.initiative,
        a.user,
        name="Handbook",
        content={
            "root": {
                "children": [
                    {
                        "type": "paragraph",
                        "children": [{"type": "text", "text": "vendor renewal"}],
                    }
                ]
            }
        },
    )
    await create_file(session, a.initiative, a.user, name="Renewal calendar")

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"search": "renewal"}
    )
    assert response.status_code == 200, response.text
    assert [r["title"] for r in response.json()] == ["Renewal calendar"]

    # ...while the full search still finds the body match.
    body = await _search(client, a, search="renewal")
    assert {h["title"] for h in body["items"]} == {"Handbook", "Renewal calendar"}


async def test_paging_does_not_repeat_or_drop_a_hit(
    client, session, acting_user: ActingUser
) -> None:
    """Rank and timestamp both tie across these, so the order has to be total
    or a row shows on two pages and another on none."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    for n in range(6):
        await create_task(session, a.project, title=f"renewal item {n}")

    seen: list[int] = []
    for number in (1, 2, 3):
        page = await _search(client, a, search="renewal", page=number, page_size=2)
        seen.extend(h["entity_id"] for h in page["items"])
    assert len(seen) == 6
    assert len(set(seen)) == 6


async def test_archived_work_is_kept_back_until_it_is_asked_for(
    client, session, acting_user: ActingUser
) -> None:
    """Archived work stays indexed and out of the way — a search that says so
    reaches it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    live = await create_task(session, a.project, title="shelved cabinet")
    filed = await create_task(
        session,
        a.project,
        title="shelved cabinet too",
        archived_at=datetime.now(UTC),
    )

    default = await _search(client, a, search="shelved")
    assert [h["entity_id"] for h in default["items"]] == [live.id]
    assert default["total_count"] == 1

    asked = await _search(client, a, search="shelved", include_archived=True)
    assert {h["entity_id"] for h in asked["items"]} == {live.id, filed.id}


async def test_what_cannot_be_archived_goes_with_what_it_is_under(
    client, session, acting_user: ActingUser
) -> None:
    """A comment and a wiki page have no archive of their own: archiving the
    project or wiki they are under keeps them back with it, and bringing that
    back brings them back."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="ledger")
    on_task = await create_comment(session, a.user, task=task, content="walnut note")
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(session, wiki, a.user, title="walnut page")
    on_page = await create_comment(
        session, a.user, wiki_page=page, content="walnut too"
    )
    everything = {
        ("comment", on_task.id),
        ("wiki_page", page.id),
        ("comment", on_page.id),
    }

    async def found() -> set[tuple[str, int]]:
        body = await _search(client, a, search="walnut", types=["comment", "wiki_page"])
        return {(h["entity_type"], h["entity_id"]) for h in body["items"]}

    assert await found() == everything
    for verb, expected in (("archive", set()), ("unarchive", everything)):
        for kind, row in (("project", a.project), ("wiki", wiki)):
            moved = await client.post(
                a.g(f"/{verb}/{kind}/{row.id}"), headers=a.headers
            )
            assert moved.status_code == 200, moved.text
        assert await found() == expected


async def test_templates_are_found_by_name_and_pickable_on_their_own(
    client, session, acting_user: ActingUser
) -> None:
    """A template is ordinary content to a search and a category to a picker."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    real = await create_file(session, a.initiative, a.user, name="kickoff notes")
    blank = await create_file(
        session, a.initiative, a.user, name="kickoff notes template", is_template=True
    )

    both = await _search(client, a, search="kickoff")
    assert {h["entity_id"] for h in both["items"]} == {real.id, blank.id}

    assert [
        h["entity_id"]
        for h in (await _search(client, a, search="kickoff", is_template=True))["items"]
    ] == [blank.id]
    assert [
        h["entity_id"]
        for h in (await _search(client, a, search="kickoff", is_template=False))[
            "items"
        ]
    ] == [real.id]


async def test_a_template_picker_is_a_wider_net_not_a_looser_one(
    client, session, acting_user: ActingUser
) -> None:
    """Templates are picked across the whole community, under the same gates as
    everything else — a template the caller holds no grant on stays invisible."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    private_template = await create_file(
        session, owner.initiative, owner.user, name="Private Template", is_template=True
    )
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    response = await client.get(
        other.g("/search/suggest"),
        headers=other.headers,
        params={"search": "private", "types": ["file"], "is_template": True},
    )
    assert response.status_code == 200, response.text
    assert private_template.id not in {r["entity_id"] for r in response.json()}


async def _suggest(client, actor: Actor, **params) -> list[dict]:
    response = await client.get(
        actor.g("/search/suggest"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _recent(client, actor: Actor, **params) -> list[dict]:
    response = await client.get(
        actor.g("/search/recent"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_scheduled_notice_is_not_searchable_until_it_goes_up(
    client, session, acting_user: ActingUser
) -> None:
    """A draft is not something the people it is destined for can find.

    The index is maintained by triggers and no trigger fires on the passage of
    time — but the write that records the publication is a write like any
    other, and ``published_at`` is one of the columns the trigger watches. So
    the statement that publishes is the statement that indexes.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    initiative = a.initiative
    assert initiative is not None
    await switch_tools(session, initiative, {Tool.post: True})

    draft = await create_post(
        session,
        initiative,
        a.user,
        name="embargoed announcement",
        published_at=None,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert (await _search(client, a, search="embargoed"))["items"] == []

    async with cohorts.system_session(a.guild.id) as system:
        await route_system(system, guild_id=a.guild.id)
        await publish_due_posts(system, now=datetime.now(UTC))
        await system.commit()

    body = await _search(client, a, search="embargoed")
    assert [h["entity_id"] for h in body["items"]] == [draft.id]


async def test_a_suggestion_says_whether_it_is_yours_to_change(
    client, acting_user, session
):
    """Not every link is the anchor's to make.

    A relation that describes its source is the source's to assert, so a picker
    offering "this blocks that" needs to know whether the thing being pointed at
    is one the reader may change — not merely one they may open.
    """
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    theirs = await create_file(session, a.initiative, b.user, name="Read only to me")
    await create_resource_grant(
        session, theirs, all_initiative_members=True, commit=False
    )
    mine = await create_file(session, a.initiative, a.user, name="Read only mine")
    await session.commit()

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"search": "Read only"}
    )
    assert response.status_code == 200, response.text
    by_id = {row["entity_id"]: row for row in response.json()}

    # Both are offered — they are both readable.
    assert theirs.id in by_id and mine.id in by_id
    # Only one of them is this reader's to change.
    assert by_id[mine.id]["can_write"] is True
    assert by_id[theirs.id]["can_write"] is False


def _task_ids(rows: list[dict]) -> list[int]:
    return [row["entity_id"] for row in rows if row["entity_type"] == "task"]


async def test_what_more_people_engaged_with_comes_first(
    client, session, acting_user: ActingUser
) -> None:
    """Among equal matches a level lifts the older one above the newer, in the
    search, the palette and a picker. It adds nothing a search did not find."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    older = await create_task(session, a.project, title="vendor renewal")
    newer = await create_task(session, a.project, title="vendor renewal")
    elsewhere = await create_task(session, a.project, title="office chairs")

    found = await _search(client, a, search="vendor")
    assert _task_ids(found["items"]) == [newer.id, older.id]

    for task in (older, elsewhere):
        session.add(
            EngagementLevel(entity_type="task", entity_id=task.id, level=LEVEL_MAX)
        )
    await session.commit()

    found = await _search(client, a, search="vendor")
    assert _task_ids(found["items"]) == [older.id, newer.id]
    assert found["total_count"] == 2
    suggested = await _suggest(client, a, search="vendor", types="task")
    assert _task_ids(suggested) == [older.id, newer.id]
    picked = await _recent(client, a, types="task")
    assert _task_ids(picked) == [elsewhere.id, older.id, newer.id]


async def test_a_picker_keeps_an_old_popular_item_within_its_limit(
    client, session, acting_user: ActingUser
) -> None:
    """The highest levels come first however old they are, then the newest, and
    an item that is both is offered once."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    old = await create_task(session, a.project, title="old")
    middle = [await create_task(session, a.project, title=f"t{i}") for i in range(2)]
    newest = await create_task(session, a.project, title="newest")
    for task, level in ((old, LEVEL_MAX), (newest, 3)):
        session.add(EngagementLevel(entity_type="task", entity_id=task.id, level=level))
    await session.commit()

    for limit, expected in (
        (1, [old.id]),
        (2, [old.id, newest.id]),
        (3, [old.id, newest.id, middle[1].id]),
    ):
        picked = await _recent(client, a, types="task", limit=limit)
        assert _task_ids(picked) == expected, limit


#: What a search for each query must put first, over the items below. The one
#: thing that catches a ranking change that makes search worse.
RELEVANCE = (
    ("login", "Fix the login page"),
    ("office chairs", "Order office chairs"),
    ("budget", "Quarterly budget"),
    ("vendor review", "Vendor review notes"),
)


async def test_each_query_puts_the_hit_it_should_first(
    client, session, acting_user: ActingUser
) -> None:
    """A level lifts a match but not past a much better one: the chairs task,
    which only mentions the budget in its description, stays below the budget's
    own title at the highest level."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_project(session, a.initiative, a.user, name="Quarterly budget")
    await create_task(session, a.project, title="Fix the login page")
    await create_task(session, a.project, title="Vendor review notes")
    chairs = await create_task(
        session,
        a.project,
        title="Order office chairs",
        description="Keep it within the budget.",
    )
    session.add(
        EngagementLevel(entity_type="task", entity_id=chairs.id, level=LEVEL_MAX)
    )
    await session.commit()

    for query, first in RELEVANCE:
        titles = [
            hit["title"] for hit in (await _search(client, a, search=query))["items"]
        ]
        assert titles[:1] == [first], (query, titles)


async def test_it_returns_only_what_the_caller_may_see(
    client, session, acting_user: ActingUser
) -> None:
    """A member of the initiative holding no grant on the project gets nothing,
    though the initiative gate admits the row — from the search, its total and
    the recents alike; a guild admin in the same seat is not narrowed by
    sharing. The count is a predicate in the same statement, so a pager built
    on it does not stop early or promise a page that is empty."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b, admin = [
        await acting_user(
            guild_role=role,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for role in (CommunityRole.member, CommunityRole.admin)
    ]
    for n in range(3):
        await create_task(session, a.project, title=f"renewal {n}")

    theirs = await _search(client, b, search="renewal")
    assert (theirs["items"], theirs["total_count"]) == ([], 0)
    assert (await _search(client, admin, search="renewal"))["total_count"] == 3
    mine = await _search(client, a, search="renewal", page_size=2)
    assert mine["total_count"] == 3
    assert len(mine["items"]) == 2
    assert mine["has_next"] is True
    assert await _recent(client, a, types="task") != []
    assert await _recent(client, b, types="task") == []


async def test_how_a_query_matches_a_title(
    client, session, acting_user: ActingUser
) -> None:
    """A results page searches as its reader types, so the last word matches as
    a prefix; a quoted phrase and an exclusion are deliberate and stay exact. A
    misspelling finds nothing whole-word, so the closest titles are offered,
    flagged — and never blended into a search that worked, nor invented when
    nothing is close."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    for query in ("thro", "barricade thro"):
        body = await _search(client, a, search=query)
        assert body["total_count"] == 1, f"{query} found nothing"
        assert body["fuzzy"] is False
    for query in ('"barricade thro"', "barricade -throne", "thrne"):
        body = await _search(client, a, search=query)
        assert body["fuzzy"] is True, f"{query} was widened"
    assert body["items"][0]["title"] == "Barricade the Throne"
    assert (await _search(client, a, search="throne"))["fuzzy"] is False
    nothing = await _search(client, a, search="zzzzqqq")
    assert nothing["items"] == []
    assert nothing["fuzzy"] is False


async def test_suggest_returns_titles_to_jump_to(
    client, session, acting_user: ActingUser
) -> None:
    """A palette answers while its reader is still typing, with no snippet. It
    narrows to the types it is given, as the results page's tabs do; a picker
    inside an initiative offers that initiative, so a mention reaches something
    the comment's reader can open; and it offers live work only."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="jump target")
    tag = await create_tag(session, a.guild, name="jump")
    await create_task(
        session, a.project, title="jump retired", archived_at=datetime.now(UTC)
    )
    b = await acting_user(
        guild_role=CommunityRole.admin, guild=a.guild, initiative=True, project=True
    )
    await create_task(session, b.project, title="jump target")

    rows = await _suggest(client, a, search="jum", initiative_id=a.initiative.id)
    assert [r["entity_id"] for r in rows] == [task.id]
    assert rows[0]["tool_id"] == a.project.id
    assert "snippet" not in rows[0]
    tags_only = await _suggest(client, a, search="jump", types=["tag"])
    assert [r["entity_id"] for r in tags_only] == [tag.id]


async def test_recent_answers_what_a_picker_opens_with(
    client, session, acting_user: ActingUser
) -> None:
    """A picker opens before anything is typed, which the search cannot answer.
    What it suggests and what it finds must be the same set of things, so it
    takes the same narrowing."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="older")
    await create_task(session, a.project, title="newer")
    await create_file(session, a.initiative, a.user)

    tasks = await _recent(client, a, types="task")
    assert {item["title"] for item in tasks} == {"older", "newer"}
    assert {item["entity_type"] for item in tasks} == {"task"}
    elsewhere = await _recent(
        client, a, types="task", initiative_id=a.initiative.id + 999
    )
    assert elsewhere == []


async def test_a_picker_is_not_offered_the_thing_it_is_writing_in(
    client, session, acting_user: ActingUser
) -> None:
    """A comment on a file, and the file itself, both compose inside something,
    so the list a picker opens with and what typing finds both leave it out —
    by its kind and id together: a task numbered the same is still offered. A
    subject this build cannot read costs the exclusion, not the answer."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    subject = await create_file(session, a.initiative, a.user, name="riverside")
    other = await create_file(session, a.initiative, a.user, name="riverside annex")
    task = await create_task(session, a.project, title="the job")
    pair = {("file", other.id), ("task", task.id)}

    def found(rows: list[dict]) -> set[tuple[str, int]]:
        return {(row["entity_type"], row["entity_id"]) for row in rows}

    subject_ref = f"file:{subject.id}"
    kinds = ["file", "task"]
    assert found(await _recent(client, a, types=kinds, subject=subject_ref)) == pair
    typed = await _suggest(
        client, a, search="riverside", types="file", subject=subject_ref
    )
    assert found(typed) == {("file", other.id)}
    unread = await _recent(client, a, types=kinds, subject="sandwich:3")
    assert found(unread) == pair | {("file", subject.id)}


async def test_a_suggestion_says_what_it_lives_in(
    client, session, acting_user: ActingUser
) -> None:
    """Two tasks of the same name in different projects are two different
    tasks, and a picker offering both has to say which is which — recents too.
    A project's own sharing gate is the project, so it names no container."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    first = await create_project(session, a.initiative, a.user, name="Harvest")
    second = await create_project(session, a.initiative, a.user, name="Winterhold")
    await create_task(session, first, title="Do a thing")
    await create_task(session, second, title="Do a thing")

    for rows in (
        await _suggest(client, a, search="Do a thing", types="task"),
        await _recent(client, a, types="task"),
    ):
        assert sorted(row["tool_title"] for row in rows) == ["Harvest", "Winterhold"]
        assert {row["initiative_name"] for row in rows} == {a.initiative.name}
    rows = await _suggest(client, a, search="Harvest", types="project")
    assert [row["tool_title"] for row in rows] == [None]
    assert [row["initiative_name"] for row in rows] == [a.initiative.name]
