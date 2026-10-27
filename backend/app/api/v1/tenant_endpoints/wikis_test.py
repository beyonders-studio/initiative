"""Tests for the wiki endpoints — CRUD, the page list, moves, drafts, and the
links both ways.

The wiki-specific concerns beyond the usual tool contract are the two things a
body of linked pages owns: the **spine** (a page's place in the list, and who
is shown it) and the **web** (what a page's body names, and what names it
back).
"""

from datetime import datetime
from types import SimpleNamespace
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import KINDS, Tool
from app.models.platform.guild import CommunityRole
from app.testing import (
    create_file,
    create_tag,
    create_wiki,
    create_wiki_page,
    lexical_body,
    strip_non_owner_grants,
)


async def _wikis_enabled(session: AsyncSession, initiative) -> None:
    initiative.wikis_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_wiki(client: AsyncClient, acting_user, session):
    """Creating seeds the creator's owner grant plus the default all-members
    read grant."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)

    response = await client.post(
        a.g("/wikis/"),
        headers=a.headers,
        json={
            "name": "Club handbook",
            "description": "How the bar float works, and the rest.",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Club handbook"
    assert body["can"]["delete"] is True
    assert body["home_page_id"] is None
    levels = {(g.get("all_initiative_members"), g["level"]) for g in body["grants"]}
    assert (True, "read") in levels


async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.wikis_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/wikis/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.wiki.disabled().body


async def test_a_member_outside_the_initiative_cannot_see_it(
    client: AsyncClient, acting_user, session
):
    """Gate 2: not being in the initiative reads as 404, not 403 — the row is
    hidden rather than refused."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    response = await client.get(a.g(f"/wikis/{wiki.id}"), headers=b.headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Pages — the spine
# ---------------------------------------------------------------------------


async def test_create_page_records_its_author_and_slug(
    client: AsyncClient, acting_user, session
):
    """The regression this file exists for: a page is written with the caller
    as its author, and its title becomes the slug that addresses it. It
    answers as a read does, with its tags and its body's version."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    tag = await create_tag(session, a.guild, name="rota")

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=a.headers,
        json={"title": "The bar float", "tag_ids": [tag.id]},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_by"] == a.user.id
    assert body["slug"] == "the-bar-float"
    assert [t["name"] for t in body["tags"]] == ["rota"]
    assert body["content_version"] is not None


async def test_a_page_starts_as_a_draft(client: AsyncClient, acting_user, session):
    """Nobody writes a page in one keystroke, and the people who only read this
    wiki have no use for an empty one — so it is published when it is ready."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    created = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=a.headers,
        json={"title": "The bar float"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_draft"] is True

    published = await client.patch(
        a.g(f"/wiki-pages/{created.json()['id']}"),
        headers=a.headers,
        json={"is_draft": False},
    )

    assert published.status_code == 200, published.text
    assert published.json()["is_draft"] is False
    assert datetime.fromisoformat(
        published.json()["updated_at"]
    ) > datetime.fromisoformat(created.json()["updated_at"])


async def test_a_page_starts_with_no_name(client: AsyncClient, acting_user, session):
    """A page is made before it is about anything, so nothing names it for you."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == ""
    # It still has an address, which is what a page needs to be linkable at all.
    assert body["slug"]


async def test_two_pages_with_one_title_get_distinct_slugs(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    slugs = []
    for _ in range(2):
        response = await client.post(
            a.g(f"/wikis/{wiki.id}/pages"),
            headers=a.headers,
            json={"title": "Rules"},
        )
        assert response.status_code == 201, response.text
        slugs.append(response.json()["slug"])

    assert slugs == ["rules", "rules-2"]


async def test_a_name_goes_back_into_circulation_with_the_trash(
    client: AsyncClient, acting_user, session
):
    """Write "Step 1", throw it away, write "Step 1" again.

    A page in the bin holds no address, so the second one gets the first one's
    slug rather than a suffix — and, before this was a partial index, rather
    than a unique violation nobody could see the cause of.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    assert first.status_code == 201, first.text
    assert first.json()["slug"] == "step-1"

    trashed = await client.delete(
        a.g(f"/wiki-pages/{first.json()['id']}"), headers=a.headers
    )
    assert trashed.status_code == 204, trashed.text

    second = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )

    assert second.status_code == 201, second.text
    assert second.json()["slug"] == "step-1"


async def test_a_page_can_be_renamed_onto_a_trashed_pages_name(
    client: AsyncClient, acting_user, session
):
    """The same freed name, taken by a rename rather than by a new page."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    assert first.status_code == 201, first.text
    await client.delete(a.g(f"/wiki-pages/{first.json()['id']}"), headers=a.headers)

    second = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Untitled"}
    )
    assert second.status_code == 201, second.text

    renamed = await client.patch(
        a.g(f"/wiki-pages/{second.json()['id']}"),
        headers=a.headers,
        json={"title": "Step 1"},
    )

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "step-1"


async def test_a_restored_page_takes_its_name_back(
    client: AsyncClient, acting_user, session
):
    """Out of the bin and back at its own address, when it is still free."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    page = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    page_id = page.json()["id"]
    await client.delete(a.g(f"/wiki-pages/{page_id}"), headers=a.headers)

    restored = await client.post(
        a.g(f"/trash/wiki_page/{page_id}/restore"), headers=a.headers
    )

    assert restored.status_code == 200, restored.text
    back = await client.get(a.g(f"/wiki-pages/{page_id}"), headers=a.headers)
    assert back.status_code == 200, back.text
    assert back.json()["slug"] == "step-1"


async def test_a_restored_page_comes_back_beside_the_one_that_took_its_name(
    client: AsyncClient, acting_user, session
):
    """The other end of the same rule: a page in the bin has no claim on a name
    somebody has used since, so it comes back under a suffixed one rather than
    not coming back at all."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    page_id = first.json()["id"]
    await client.delete(a.g(f"/wiki-pages/{page_id}"), headers=a.headers)
    replacement = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    assert replacement.json()["slug"] == "step-1"

    restored = await client.post(
        a.g(f"/trash/wiki_page/{page_id}/restore"), headers=a.headers
    )

    assert restored.status_code == 200, restored.text
    back = await client.get(a.g(f"/wiki-pages/{page_id}"), headers=a.headers)
    assert back.status_code == 200, back.text
    assert back.json()["slug"] == "step-1-2"
    # And the page that took the name in the meantime keeps it.
    held = await client.get(
        a.g(f"/wiki-pages/{replacement.json()['id']}"), headers=a.headers
    )
    assert held.json()["slug"] == "step-1"


async def test_a_wiki_restored_whole_keeps_its_pages_addresses(
    client: AsyncClient, acting_user, session
):
    """Nothing can take a name while the whole wiki is in the bin, so every
    page comes back at the address links point at."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    for title in ("Step 1", "Step 2"):
        response = await client.post(
            a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": title}
        )
        assert response.status_code == 201, response.text

    await client.delete(a.g(f"/wikis/{wiki.id}"), headers=a.headers)
    restored = await client.post(
        a.g(f"/trash/wiki/{wiki.id}/restore"), headers=a.headers
    )
    assert restored.status_code == 200, restored.text

    pages = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert pages.status_code == 200, pages.text
    assert [page["slug"] for page in pages.json()["items"]] == ["step-1", "step-2"]


async def test_the_tree_comes_back_in_reading_order(
    client: AsyncClient, acting_user, session
):
    """In the order somebody arranged them, so a client draws the list without
    sorting it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="Bar")
    await create_wiki_page(session, wiki, a.user, title="Float")
    await create_wiki_page(session, wiki, a.user, title="Kitchen")

    response = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)

    assert response.status_code == 200, response.text
    titles = [page["title"] for page in response.json()["items"]]
    assert titles == ["Bar", "Float", "Kitchen"]


async def test_moving_a_page_renumbers_its_new_siblings(
    client: AsyncClient, acting_user, session
):
    """A move is one fact — where in the list this page now goes — and the
    whole list is renumbered so the order it lands in is the order drawn."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="First")
    await create_wiki_page(session, wiki, a.user, title="Second")
    moved = await create_wiki_page(session, wiki, a.user, title="Third")

    response = await client.post(
        a.g(f"/wiki-pages/{moved.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )
    assert response.status_code == 200, response.text

    tree = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [p["title"] for p in tree.json()["items"]] == ["Third", "First", "Second"]


async def test_deleting_a_page_takes_its_sub_pages(
    client: AsyncClient, acting_user, session
):
    """The page goes, and the ones around it stay."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    doomed = await create_wiki_page(session, wiki, a.user, title="Bar")
    await create_wiki_page(session, wiki, a.user, title="Kitchen")

    response = await client.delete(a.g(f"/wiki-pages/{doomed.id}"), headers=a.headers)
    assert response.status_code == 204, response.text

    tree = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [p["title"] for p in tree.json()["items"]] == ["Kitchen"]


# ---------------------------------------------------------------------------
# Files put in a wiki
# ---------------------------------------------------------------------------


def _body(tag: str, heading: str) -> dict:
    """A Lexical body holding one heading, nested a level down, and a paragraph."""
    return {
        "root": {
            "type": "root",
            "children": [
                {"type": "paragraph", "children": [{"type": "text", "text": "Intro"}]},
                {
                    "type": "quote",
                    "children": [
                        {
                            "type": "heading",
                            "tag": tag,
                            "children": [{"type": "text", "text": heading}],
                        }
                    ],
                },
            ],
        }
    }


async def test_a_file_put_in_a_wiki_is_one_of_its_pages(
    client: AsyncClient, acting_user, session
):
    """It joins by an edge, so it reads as a page without becoming one — its
    headings drawn in the tree like a page's own."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(
        session, wiki, a.user, title="Written here", content=_body("h1", "Opening")
    )
    file = await create_file(
        session, a.initiative, a.user, content=_body("h3", "Loot table")
    )

    response = await client.put(
        a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers
    )
    assert response.status_code == 204, response.text

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    rows = {
        row["title"]: (row["kind"], row["headings"]) for row in listed.json()["items"]
    }
    assert rows == {
        "Written here": (
            "page",
            [{"text": "Opening", "level": 1, "anchor": "opening"}],
        ),
        file.name: (
            "file",
            [{"text": "Loot table", "level": 3, "anchor": "loot-table"}],
        ),
    }


async def test_a_page_filed_under_another_reads_after_it(
    client: AsyncClient, acting_user, session
):
    """Reading order is depth-first: a page, then what is filed under it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(session, wiki, a.user, title="Afterwards")

    filed = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=a.headers,
        json={"title": "Combat", "parent_page_id": parent.id},
    )

    assert filed.status_code == 201, filed.text
    assert filed.json()["parent_page_id"] == parent.id

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Rules",
        "Combat",
        "Afterwards",
    ]


async def test_a_drag_files_a_page_and_places_it_in_one_request(
    client: AsyncClient, acting_user, session
):
    """A drag is one gesture, so filing and ordering arrive together."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=parent.id, position=0
    )
    loose = await create_wiki_page(session, wiki, a.user, title="Travel")

    moved = await client.post(
        a.g(f"/wiki-pages/{loose.id}/move"),
        headers=a.headers,
        json={"parent_page_id": parent.id, "position": 0},
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_page_id"] == parent.id

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Rules",
        "Travel",
        "Combat",
    ]


async def test_a_page_cannot_be_filed_under_its_own_descendant(
    client: AsyncClient, acting_user, session
):
    """It would take the branch out of the wiki, so it is refused by name."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    child = await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=parent.id
    )

    response = await client.post(
        a.g(f"/wiki-pages/{parent.id}/move"),
        headers=a.headers,
        json={"parent_page_id": child.id, "position": 0},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "WIKI_PAGE_PARENT_DESCENDANT"


async def test_a_page_cannot_be_its_own_parent(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(session, wiki, a.user, title="Rules")

    response = await client.post(
        a.g(f"/wiki-pages/{page.id}/move"),
        headers=a.headers,
        json={"parent_page_id": page.id, "position": 0},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "WIKI_PAGE_PARENT_ITSELF"


async def test_trashing_a_page_takes_what_is_filed_under_it(
    client: AsyncClient, acting_user, session
):
    """A section is put away whole, and comes back whole."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=parent.id
    )

    trashed = await client.delete(a.g(f"/wiki-pages/{parent.id}"), headers=a.headers)
    assert trashed.status_code == 204, trashed.text

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert listed.json()["items"] == []

    restored = await client.post(
        a.g(f"/trash/wiki_page/{parent.id}/restore"), headers=a.headers
    )
    assert restored.status_code == 200, restored.text
    back = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in back.json()["items"]] == ["Rules", "Combat"]


async def test_a_file_can_be_moved_among_the_pages(
    client: AsyncClient, acting_user, session
):
    """A borrowed file is a row of the wiki's list, so it is arranged like
    one — and the file itself is never written to say so."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="First")
    await create_wiki_page(session, wiki, a.user, title="Second")
    file = await create_file(session, a.initiative, a.user, name="Borrowed")
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)

    moved = await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )

    assert moved.status_code == 204, moved.text

    # It stays there, because the order is the wiki's own record of it.
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Borrowed",
        "First",
        "Second",
    ]


async def test_a_file_can_be_filed_under_a_page(
    client: AsyncClient, acting_user, session
):
    """Where a file sits is this wiki's record, so filing it under a page
    is the same kind of fact as its place in the list — and it comes back out
    to the top the same way."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    rules = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=rules.id, position=0
    )
    await create_wiki_page(session, wiki, a.user, title="Afterwards")
    file = await create_file(session, a.initiative, a.user, name="Borrowed")
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)

    moved = await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"parent_page_id": rules.id, "position": 1},
    )
    assert moved.status_code == 204, moved.text
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    rows = listed.json()["items"]
    assert [row["title"] for row in rows] == [
        "Rules",
        "Combat",
        "Borrowed",
        "Afterwards",
    ]
    borrowed = next(row for row in rows if row["kind"] == "file")
    assert borrowed["parent_page_id"] == rules.id

    # A page dragged in beside it counts it among its neighbours.
    loose = await create_wiki_page(session, wiki, a.user, title="Travel")
    await client.post(
        a.g(f"/wiki-pages/{loose.id}/move"),
        headers=a.headers,
        json={"parent_page_id": rules.id, "position": 2},
    )
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Rules",
        "Combat",
        "Borrowed",
        "Travel",
        "Afterwards",
    ]

    unfiled = await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )
    assert unfiled.status_code == 204, unfiled.text
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    rows = listed.json()["items"]
    assert rows[0]["title"] == "Borrowed" and rows[0]["parent_page_id"] is None


async def test_a_file_is_not_filed_under_a_page_of_another_wiki(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    other = await create_wiki(session, a.initiative, a.user, name="Elsewhere")
    elsewhere = await create_wiki_page(session, other, a.user, title="Not here")
    file = await create_file(session, a.initiative, a.user)
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"parent_page_id": elsewhere.id, "position": 0},
    )
    assert response.status_code == 404, response.text
    assert response.json() == KINDS["wiki_page"].not_found().body


async def test_a_file_under_a_trashed_page_is_drawn_at_the_top(
    client: AsyncClient, acting_user, session
):
    """The page is the wiki's to put away; the file is not. It stays in
    the wiki, at the top, and goes back under the page when it is restored."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    rules = await create_wiki_page(session, wiki, a.user, title="Rules")
    file = await create_file(session, a.initiative, a.user, name="Borrowed")
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)
    await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"parent_page_id": rules.id, "position": 0},
    )

    await client.delete(a.g(f"/wiki-pages/{rules.id}"), headers=a.headers)
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    (row,) = listed.json()["items"]
    assert row["title"] == "Borrowed" and row["parent_page_id"] is None

    await client.post(a.g(f"/trash/wiki_page/{rules.id}/restore"), headers=a.headers)
    back = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    rows = back.json()["items"]
    assert [row["title"] for row in rows] == ["Rules", "Borrowed"]
    assert rows[1]["parent_page_id"] == rules.id


async def test_a_file_row_says_what_kind_of_file_it_is(
    client: AsyncClient, acting_user, session
):
    """So the navigation can draw a spreadsheet as a spreadsheet."""
    from app.core.file_types import FileType

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="Written here")
    file = await create_file(
        session,
        a.initiative,
        a.user,
        name="Budget",
        file_type=FileType.sheet,
    )

    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    rows = {row["title"]: row for row in listed.json()["items"]}
    assert rows["Budget"]["file_type"] == "spreadsheet"
    assert rows["Written here"]["file_type"] is None


async def test_a_page_can_be_moved_past_a_file(
    client: AsyncClient, acting_user, session
):
    """The other half of one list: moving a page counts the files in it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    first = await create_wiki_page(session, wiki, a.user, title="First")
    await create_wiki_page(session, wiki, a.user, title="Second")
    file = await create_file(session, a.initiative, a.user, name="Borrowed")
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)

    moved = await client.post(
        a.g(f"/wiki-pages/{first.id}/move"),
        headers=a.headers,
        json={"position": 2},
    )
    assert moved.status_code == 200, moved.text

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Second",
        "Borrowed",
        "First",
    ]


async def test_a_file_taken_out_gives_up_its_place(
    client: AsyncClient, acting_user, session
):
    """Put back in later, it arrives at the end like a new one rather than in
    the spot it held last time."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="First")
    file = await create_file(session, a.initiative, a.user, name="Borrowed")
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)
    await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )

    removed = await client.delete(
        a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers
    )
    assert removed.status_code == 204, removed.text
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)

    again = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in again.json()["items"]] == ["First", "Borrowed"]


async def test_a_file_in_a_wiki_is_never_a_draft(
    client: AsyncClient, acting_user, session
):
    """It is readable wherever else it lives, so this wiki cannot hold it back."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    file = await create_file(session, a.initiative, a.user)

    response = await client.put(
        a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers
    )
    assert response.status_code == 204, response.text
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    row = next(r for r in listed.json()["items"] if r["kind"] == "file")
    assert row["is_draft"] is False


async def test_taking_a_file_out_leaves_the_file(
    client: AsyncClient, acting_user, session
):
    """The wiki loses a page. The file loses nothing."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    file = await create_file(session, a.initiative, a.user)

    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)
    removed = await client.delete(
        a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers
    )
    assert removed.status_code == 204, removed.text

    pages = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert pages.json()["items"] == []

    still_there = await client.get(a.g(f"/files/{file.id}"), headers=a.headers)
    assert still_there.status_code == 200


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


async def test_a_draft_is_not_in_the_list_a_reader_gets(
    client: AsyncClient, acting_user, session
):
    """A page somebody is still writing belongs to the people writing it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="Finished")
    await create_wiki_page(session, wiki, a.user, title="Half written", is_draft=True)

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    response = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=b.headers)

    assert response.status_code == 200, response.text
    assert [p["title"] for p in response.json()["items"]] == ["Finished"]


async def test_a_writer_sees_their_own_drafts(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="Finished")
    await create_wiki_page(session, wiki, a.user, title="Half written", is_draft=True)

    response = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)

    assert response.status_code == 200, response.text
    titles = {p["title"]: p["is_draft"] for p in response.json()["items"]}
    assert titles == {"Finished": False, "Half written": True}


async def test_a_draft_page_reads_as_missing_to_a_reader(
    client: AsyncClient, acting_user, session
):
    """Missing rather than refused: being told a page exists is being told
    something about it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(
        session, wiki, a.user, title="Half written", is_draft=True
    )

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    # Its writer reads it, and a reader is told nothing.
    url = a.g(f"/wiki-pages/{page.id}")
    written = await client.get(url, headers=a.headers)
    assert written.status_code == 200, written.text
    assert written.json()["wiki_id"] == wiki.id
    assert (await client.get(url, headers=b.headers)).status_code == 404


# ---------------------------------------------------------------------------
# Live editing
# ---------------------------------------------------------------------------


async def test_a_body_saved_outside_a_live_session_is_refused(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """A page being edited live has its room as the writer of its body, as a
    file's does. A body arriving over REST is refused; a rename is not."""
    from app.services.tenant.collaboration import collaboration_manager

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(session, wiki, a.user, title="Live")
    url = a.g(f"/wiki-pages/{page.id}")
    monkeypatch.setattr(
        collaboration_manager,
        "live_room",
        # A room somebody is in; reads leave a room the browser renders alone.
        lambda *_a: SimpleNamespace(renders_content=False),
    )

    refused = await client.patch(
        url, headers=a.headers, json={"content": {"root": "written outside"}}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "LIVE_SESSION_OWNS_CONTENT"
    await session.refresh(page, ["content"])
    assert page.content != {"root": "written outside"}

    renamed = await client.patch(url, headers=a.headers, json={"title": "Renamed"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Renamed"


async def test_a_body_saved_with_no_session_clears_the_stored_yjs_state(
    client: AsyncClient, acting_user, session
):
    """Stored Yjs state predates a body saved over REST; left in place, the
    next live session would load it and save it back over the edit."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(
        session, wiki, a.user, title="Stale", yjs_state=b"stale yjs blob"
    )

    saved = await client.patch(
        a.g(f"/wiki-pages/{page.id}"),
        headers=a.headers,
        json={"content": {"root": {"children": [], "type": "root"}}},
    )

    assert saved.status_code == 200, saved.text
    await session.refresh(page, ["yjs_state"])
    assert page.yjs_state is None


async def test_a_page_write_naming_a_version_since_changed_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(session, wiki, a.user, title="Versioned")
    url = a.g(f"/wiki-pages/{page.id}")
    version = (await client.get(url, headers=a.headers)).json()["content_version"]
    taken = await client.patch(
        url,
        headers=a.headers,
        json={"content": lexical_body("second"), "content_version": version},
    )
    stale = await client.patch(
        url,
        headers=a.headers,
        json={"content": lexical_body("third"), "content_version": version},
    )

    assert taken.status_code == 200, taken.text
    assert stale.status_code == 409
    assert stale.json()["detail"] == "CONTENT_CHANGED"


# ---------------------------------------------------------------------------
# The home page
# ---------------------------------------------------------------------------


async def test_home_page_has_to_be_one_of_this_wikis_pages(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    mine = await create_wiki(session, a.initiative, a.user)
    theirs = await create_wiki(session, a.initiative, a.user)
    stray = await create_wiki_page(session, theirs, a.user, title="Elsewhere")

    response = await client.patch(
        a.g(f"/wikis/{mine.id}"),
        headers=a.headers,
        json={"home_page_id": stray.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "WIKI_HOME_NOT_IN_WIKI"

    # A setting is saved, and the change dates the wiki.
    before = (await client.get(a.g(f"/wikis/{mine.id}"), headers=a.headers)).json()
    response = await client.patch(
        a.g(f"/wikis/{mine.id}"),
        headers=a.headers,
        json={"show_updated_at": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["show_updated_at"] is False
    assert datetime.fromisoformat(
        response.json()["updated_at"]
    ) > datetime.fromisoformat(before["updated_at"])
    read = await client.get(a.g(f"/wikis/{mine.id}"), headers=a.headers)
    assert read.json()["show_updated_at"] is False


# ---------------------------------------------------------------------------
# The web — links both ways
# ---------------------------------------------------------------------------


async def test_a_page_reports_what_links_to_it(
    client: AsyncClient, acting_user, session
):
    """The backlink. One page's body names another, and the named page says so
    without anybody recording it twice."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    target = await create_wiki_page(session, wiki, a.user, title="The bar float")
    source = await create_wiki_page(session, wiki, a.user, title="Opening up")

    # A body that names the other page, in the shape the editor writes.
    body = {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {
                            # What both `[[ ]]` and `#` write now: the kind is
                            # part of the node, so a page can name anything.
                            "type": "entity-mention",
                            "entityType": "wiki_page",
                            "entityId": target.id,
                            "text": "The bar float",
                        }
                    ],
                }
            ],
        }
    }
    patched = await client.patch(
        a.g(f"/wiki-pages/{source.id}"),
        headers=a.headers,
        json={"content": body},
    )
    assert patched.status_code == 200, patched.text

    links = await client.get(
        a.g("/relationships/"),
        headers=a.headers,
        params={"entity": f"wiki_page:{target.id}"},
    )
    assert links.status_code == 200, links.text
    [incoming] = links.json()
    assert incoming["direction"] == "inbound"
    assert (incoming["other"]["type"], incoming["other"]["id"]) == (
        "wiki_page",
        source.id,
    )
    # Enough to address the far end without a second request.
    assert incoming["other"]["tool"] == "wiki"
    assert incoming["other"]["tool_id"] == wiki.id


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------


async def test_read_access_cannot_write_a_page(
    client: AsyncClient, acting_user, session
):
    """Gate 4: a page is the wiki's content, so adding one asks for write on
    the wiki."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=b.headers,
        json={"title": "Sneaking one in"},
    )

    assert response.status_code == 403


async def test_an_unshared_wiki_is_invisible_to_a_co_member(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await strip_non_owner_grants(session, wiki, a.user.id)

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(
        a.g("/wikis/"), headers=b.headers, params={"initiative_id": a.initiative.id}
    )
    assert listing.status_code == 200
    assert listing.json()["items"] == []


async def test_a_copy_has_its_published_pages_in_their_tree(
    client: AsyncClient, acting_user, session
):
    """Drafts stay behind; a published page or borrowed file under a
    draft moves up to the draft's own parent, and the home page points at its
    copy."""
    from sqlmodel import select

    from app.models.tenant.wiki import Wiki, WikiPage
    from app.testing import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    home = await create_wiki_page(session, wiki, a.user, title="Home")
    draft = await create_wiki_page(
        session, wiki, a.user, title="Draft", parent_page_id=home.id, is_draft=True
    )
    await create_wiki_page(session, wiki, a.user, title="Leaf", parent_page_id=draft.id)
    file = await create_file(session, a.initiative, a.user, name="Borrowed")
    wiki = await session.get(Wiki, wiki.id)
    wiki.home_page_id = home.id
    session.add(wiki)
    await session.commit()
    await client.put(a.g(f"/wikis/{wiki.id}/files/{file.id}"), headers=a.headers)
    await client.post(
        a.g(f"/wikis/{wiki.id}/files/{file.id}/move"),
        headers=a.headers,
        json={"parent_page_id": draft.id, "position": 0},
    )

    response = await client.post(a.g(f"/wikis/{wiki.id}/duplicate"), headers=a.headers)

    assert response.status_code == 201, response.text
    copy_id = response.json()["id"]
    await route_session_to_guild(session, a.guild.id)
    pages = {
        page.title: page
        for page in (
            await session.exec(select(WikiPage).where(WikiPage.wiki_id == copy_id))
        ).all()
    }
    assert set(pages) == {"Home", "Leaf"}
    assert pages["Leaf"].parent_page_id == pages["Home"].id
    copied = (
        await session.exec(
            select(Wiki)
            .where(Wiki.id == copy_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    assert copied.home_page_id == pages["Home"].id
    listed = await client.get(a.g(f"/wikis/{copy_id}/pages"), headers=a.headers)
    (borrowed,) = [row for row in listed.json()["items"] if row["kind"] == "file"]
    assert borrowed["parent_page_id"] == pages["Home"].id


async def test_a_copied_page_goes_last_where_it_is_filed_without_its_subpages(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    rules = await create_wiki_page(session, wiki, a.user, title="Rules")
    combat, travel = [
        await create_wiki_page(
            session, wiki, a.user, title=title, parent_page_id=rules.id, position=n
        )
        for n, title in enumerate(("Combat", "Travel"))
    ]
    await create_wiki_page(
        session, wiki, a.user, title="Grapple", parent_page_id=combat.id
    )

    response = await client.post(
        a.g(f"/wiki-pages/{combat.id}/duplicate"), headers=a.headers
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert (copy["title"], copy["slug"], copy["parent_page_id"]) == (
        "Combat (Copy)",
        "combat-copy",
        rules.id,
    )
    assert copy["position"] > travel.position
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    titles = [row["title"] for row in listed.json()["items"]]
    assert titles.count("Grapple") == 1
