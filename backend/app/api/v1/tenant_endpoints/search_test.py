"""Searching a guild through the API.

The gates are the index's own policies, so these assert what a *request* gets
back: that a match is found across tools, that the caller's access decides the
result set, and that the two shapes a client depends on — exact totals and a
route to the thing found — hold.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

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
)

ActingUser = Callable[..., Awaitable[Actor]]


async def _search(client, actor: Actor, **params) -> dict:
    response = await client.get(
        actor.g("/search/"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_it_finds_a_task(client, session, acting_user: ActingUser) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="quarterly vendor renewal")

    body = await _search(client, a, search="vendor renewal")
    assert [h["title"] for h in body["items"]] == ["quarterly vendor renewal"]
    assert body["total_count"] == 1


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

    hit = (await _search(client, a, search="routable"))["items"][0]
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


async def test_it_returns_only_what_the_caller_may_see(
    client, session, acting_user: ActingUser
) -> None:
    """A member of the initiative holding no grant on the project."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted renewal")

    assert (await _search(client, a, search="restricted"))["total_count"] == 1
    assert (await _search(client, b, search="restricted"))["items"] == []


async def test_the_total_counts_what_the_caller_may_see(
    client, session, acting_user: ActingUser
) -> None:
    """The count is a predicate in the same statement, so it matches the rows —
    a pager built on it does not stop early or promise a page that is empty."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    for n in range(3):
        await create_task(session, a.project, title=f"renewal {n}")

    assert (await _search(client, b, search="renewal"))["total_count"] == 0
    mine = await _search(client, a, search="renewal", page_size=2)
    assert mine["total_count"] == 3
    assert len(mine["items"]) == 2
    assert mine["has_next"] is True


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


async def test_suggest_returns_titles_to_jump_to(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="jump target")

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"search": "jump"}
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [r["entity_id"] for r in rows] == [task.id]
    assert rows[0]["tool_id"] == a.project.id
    assert "snippet" not in rows[0]


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


async def test_suggest_narrows_to_the_types_it_is_given(
    client, session, acting_user: ActingUser
) -> None:
    """The palette's tabs and the results page ask the same question, so the
    palette can be on one slice while the guild holds matches in another."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="riverside")
    tag = await create_tag(session, a.guild, name="riverside")

    tags_only = await client.get(
        a.g("/search/suggest"),
        headers=a.headers,
        params={"search": "riverside", "types": ["tag"]},
    )
    assert tags_only.status_code == 200, tags_only.text
    assert [r["entity_id"] for r in tags_only.json()] == [tag.id]


async def test_an_unknown_type_is_refused_rather_than_ignored(
    client, session, acting_user: ActingUser
) -> None:
    """The accepted set is declared, so a name that is not one of them is a bad
    request — not a search that quietly returns everything."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"search": "x", "types": ["invoice"]}
    )
    assert response.status_code == 422, response.text


async def test_the_last_word_matches_as_a_prefix(
    client, session, acting_user: ActingUser
) -> None:
    """A results page searches as its reader types, so the word being typed is
    usually half-finished. Whole-word matching alone reads as nothing found."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    for query in ("thro", "barricade thro"):
        response = await client.get(
            a.g("/search/"), headers=a.headers, params={"search": query}
        )
        assert response.status_code == 200, response.text
        assert response.json()["total_count"] == 1, f"{query} found nothing"


async def test_what_the_reader_asked_for_exactly_is_left_exact(
    client, session, acting_user: ActingUser
) -> None:
    """A quoted phrase and an exclusion are deliberate, so neither is widened
    into a prefix.

    Both fall through to the close-match answer, which is itself the proof: a
    widened query would have matched exactly and never got there.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    for query in ('"barricade thro"', "barricade -throne"):
        response = await client.get(
            a.g("/search/"),
            headers=a.headers,
            params={"search": query},
        )
        assert response.status_code == 200, response.text
        assert response.json()["fuzzy"] is True, f"{query} was widened"


async def test_a_typo_is_offered_the_closest_titles(
    client, session, acting_user: ActingUser
) -> None:
    """Whole-word matching cannot answer a misspelling, so a search that finds
    nothing offers what is closest — flagged, so the reader is told which of
    the two they are reading."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"search": "thrne"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fuzzy"] is True
    assert body["items"][0]["title"] == "Barricade the Throne"


async def test_a_search_that_works_is_never_flagged_as_close(
    client, session, acting_user: ActingUser
) -> None:
    """The suggestion never blends into a search that worked."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"search": "throne"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["fuzzy"] is False


async def test_nothing_close_stays_nothing(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"search": "zzzzqqq"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["fuzzy"] is False


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


async def test_suggest_matches_a_partly_typed_word(
    client, session, acting_user: ActingUser
) -> None:
    """A palette answers while you are still typing."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="vendor renewal")

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"search": "ven"}
    )
    assert [r["title"] for r in response.json()] == ["vendor renewal"]


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


async def test_suggest_narrows_to_one_initiative(
    client, session, acting_user: ActingUser
) -> None:
    """A picker inside an initiative offers that initiative — a mention has to
    reach something the reader of the comment can open."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    here = await create_task(session, a.project, title="shared name")
    b = await acting_user(
        guild_role=CommunityRole.admin, guild=a.guild, initiative=True, project=True
    )
    await create_task(session, b.project, title="shared name")

    response = await client.get(
        a.g("/search/suggest"),
        headers=a.headers,
        params={"search": "shared", "initiative_id": a.initiative.id},
    )
    assert response.status_code == 200, response.text
    assert [r["entity_id"] for r in response.json()] == [here.id]


async def test_suggest_leaves_archived_work_out(
    client, session, acting_user: ActingUser
) -> None:
    """A picker offers somewhere to put work, so it offers live work."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(
        session,
        a.project,
        title="retired lantern",
        archived_at=datetime.now(UTC),
    )

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"search": "lantern"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


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


async def test_recent_answers_what_a_picker_opens_with(
    client, session, acting_user: ActingUser
) -> None:
    """A picker opens before anything is typed, which the search cannot answer:
    it matches words, and there are none yet."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="older")
    await create_task(session, a.project, title="newer")

    titles = [item["title"] for item in await _recent(client, a, types="task")]
    assert set(titles) == {"older", "newer"}


async def test_recent_takes_the_same_narrowing_the_search_does(
    client, session, acting_user: ActingUser
) -> None:
    """What a picker suggests and what it finds must be the same set of things,
    or picking from the list offers what typing could not."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="a task")
    await create_file(session, a.initiative, a.user)

    tasks = await _recent(client, a, types="task")
    assert {item["entity_type"] for item in tasks} == {"task"}

    elsewhere = await _recent(
        client, a, types="task", initiative_id=a.initiative.id + 999
    )
    assert elsewhere == []


async def test_recent_stops_at_the_same_gate_the_search_does(
    client, session, acting_user: ActingUser
) -> None:
    """Suggestions are content, so they answer under the sharing that governs
    the things themselves."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="private work")

    assert await _recent(client, a, types="task") != []
    assert await _recent(client, b, types="task") == []


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
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()

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


async def test_a_picker_is_not_offered_the_thing_it_is_writing_in(
    client, session, acting_user: ActingUser
) -> None:
    """A comment on a file, and the file itself, both compose inside
    something. Naming it would point at the page the words are already on."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    subject = await create_file(session, a.initiative, a.user, name="the page")
    other = await create_file(session, a.initiative, a.user, name="another page")

    offered = await _recent(client, a, types="file", subject=f"file:{subject.id}")
    assert [item["entity_id"] for item in offered] == [other.id]


async def test_typing_its_name_does_not_find_it_either(
    client, session, acting_user: ActingUser
) -> None:
    """The list a picker opens with and what typing finds are the same set of
    things, so both leave the subject out."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    subject = await create_file(session, a.initiative, a.user, name="riverside")
    other = await create_file(session, a.initiative, a.user, name="riverside annex")

    response = await client.get(
        a.g("/search/suggest"),
        headers=a.headers,
        params={
            "search": "riverside",
            "types": ["file"],
            "subject": f"file:{subject.id}",
        },
    )
    assert response.status_code == 200, response.text
    assert [r["entity_id"] for r in response.json()] == [other.id]


async def test_only_the_subject_itself_is_left_out(
    client, session, acting_user: ActingUser
) -> None:
    """Its kind and its id together — a task numbered the same as the file
    being written in is a different thing and still offered."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    doc = await create_file(session, a.initiative, a.user, name="the page")
    task = await create_task(session, a.project, title="the job")

    offered = await _recent(client, a, types=["file", "task"], subject=f"file:{doc.id}")
    assert [(item["entity_type"], item["entity_id"]) for item in offered] == [
        ("task", task.id)
    ]


async def test_a_subject_that_names_nothing_narrows_nothing(
    client, session, acting_user: ActingUser
) -> None:
    """Stored content outlives the build that wrote it. A reference this build
    cannot read costs the exclusion, not the answer."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user, name="the page")

    offered = await _recent(client, a, types="file", subject="sandwich:3")
    assert [item["entity_id"] for item in offered] == [doc.id]


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


async def test_a_suggestion_says_what_it_lives_in(
    client, session, acting_user: ActingUser
) -> None:
    """Two tasks of the same name in different projects are two different
    tasks, and a picker offering both has to say which is which."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    first = await create_project(session, a.initiative, a.user, name="Harvest")
    second = await create_project(session, a.initiative, a.user, name="Winterhold")
    await create_task(session, first, title="Do a thing")
    await create_task(session, second, title="Do a thing")

    rows = [
        row
        for row in await _suggest(client, a, search="Do a thing", types="task")
        if row["title"] == "Do a thing"
    ]
    assert len(rows) == 2
    assert {row["tool_title"] for row in rows} == {"Harvest", "Winterhold"}
    assert {row["initiative_name"] for row in rows} == {a.initiative.name}


async def test_a_tool_does_not_live_in_itself(
    client, session, acting_user: ActingUser
) -> None:
    """A project's own sharing gate is the project, so naming its container
    would only repeat its title back."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_project(session, a.initiative, a.user, name="Harvest")

    rows = await _suggest(client, a, search="Harvest", types="project")
    assert [row["tool_title"] for row in rows] == [None]
    assert [row["initiative_name"] for row in rows] == [a.initiative.name]


async def test_recents_say_where_they_live_too(
    client, session, acting_user: ActingUser
) -> None:
    """A picker that has not been typed in yet shows recents, and they are the
    same rows — so they cannot be less legible than the ones typing finds."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="Harvest")
    await create_task(session, project, title="Do a thing")

    rows = await _recent(client, a, types="task")
    assert [row["tool_title"] for row in rows] == ["Harvest"]


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
