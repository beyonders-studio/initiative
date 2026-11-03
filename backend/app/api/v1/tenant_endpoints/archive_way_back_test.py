"""The way back out: that an archived thing can be found, and taken back.

The freeze itself is covered by ``archive_test`` and ``frozen_test``. What is
covered here is the pair of things a client needs before it can use any of it —
somewhere to see what has been put away, and an answer to "may I take this
back", which the capped permission level cannot give.
"""

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.main import app
from app.models.platform.guild import CommunityRole
from app.schemas.tenant.archive import ArchivableType
from app.testing import create_file, create_queue


#: The wire name of every archivable tool (and the collection, a sub-tool with
#: a list of its own), paired with the list route that has
#: to be able to show it once it is archived. Read off ``ArchivableType`` rather
#: than written out, so a tool that becomes archivable joins this too.
_TOOL_LISTS = {
    "project": "projects",
    "file": "files",
    "queue": "queues",
    "counter_group": "counter-groups",
    "calendar": "calendars",
    "dashboard": "dashboards",
    "post": "posts",
    "wiki": "wikis",
    "collection": "collections",
}


def test_every_archivable_tool_has_somewhere_to_be_found():
    """A tool nobody can list once it is archived is a tool nobody can take
    back out, so the two sets are held together here rather than by memory.

    ``ArchivableType`` carries the two non-tools as well; they are archived from
    their own settings page and have no tool list of their own.
    """
    archivable = {t.value for t in ArchivableType} - {"task", "initiative"}
    assert archivable == set(_TOOL_LISTS), (
        f"an archivable tool with no archived list: {archivable ^ set(_TOOL_LISTS)}"
    )

    offered = {
        route.path.rsplit("/", 2)[-2]: {p.name for p in route.dependant.query_params}
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/c/{community_id}/")
        and "GET" in getattr(route, "methods", set())
        and getattr(route, "path", "").endswith("/")
    }
    missing = [
        segment
        for segment in _TOOL_LISTS.values()
        if "archived" not in offered.get(segment, set())
    ]
    assert not missing, f"list endpoints with no archived filter: {missing}"


async def test_an_archived_tool_is_off_the_list_and_on_the_archived_one(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    queue = await create_queue(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/queue/{queue.id}"), headers=a.headers)

    live = await client.get(a.g("/queues/"), headers=a.headers)
    assert [q["id"] for q in live.json()["items"]] == []

    archived = await client.get(a.g("/queues/?archived=true"), headers=a.headers)
    assert [q["id"] for q in archived.json()["items"]] == [queue.id]


async def test_an_archived_tool_says_it_can_be_taken_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The level is capped at read — that is what turns the edit affordances
    off — so the way out is a separate answer or there is no way out."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    file = await create_file(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/file/{file.id}"), headers=a.headers)
    read = await client.get(a.g(f"/files/{file.id}"), headers=a.headers)

    body = read.json()
    assert body["archived_at"] is not None
    assert body["can"]["edit"] is False
    assert body["can"]["unarchive"] is True
    # An export changes nothing, so its owner still has it.
    assert body["can"]["export"] is True


async def test_a_live_tool_offers_nothing_to_take_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    file = await create_file(session, a.initiative, a.user)

    read = await client.get(a.g(f"/files/{file.id}"), headers=a.headers)

    body = read.json()
    assert body["archived_at"] is None
    assert body["can"]["unarchive"] is False


async def test_a_reader_is_not_offered_the_way_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Coming back out is a write, and the answer is the level the reader would
    have had if it were live — which is read."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    created = await client.post(
        a.g("/files/"),
        headers=a.headers,
        json={
            "name": "Read only to the other one",
            "initiative_id": a.initiative.id,
            "grants": [{"user_id": b.user.id, "level": "read"}],
        },
    )
    file_id = created.json()["id"]
    await client.post(a.g(f"/archive/file/{file_id}"), headers=a.headers)

    read = await client.get(a.g(f"/files/{file_id}"), headers=b.headers)

    assert read.status_code == 200
    assert read.json()["can"]["unarchive"] is False


async def test_something_archived_with_its_initiative_comes_back_with_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Its stamp is the initiative's, so the button belongs on the initiative.
    Offering it here would be offering a write the database refuses."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    queue = await create_queue(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/initiative/{a.initiative.id}"), headers=a.headers)
    read = await client.get(a.g(f"/queues/{queue.id}"), headers=a.headers)

    body = read.json()
    assert body["archived_at"] is not None
    assert body["can"]["unarchive"] is False


async def test_the_archived_list_agrees_with_the_detail_about_the_way_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A list row and its own page have to answer the same, or the button is
    offered in one place and refused from the other."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    queue = await create_queue(session, a.initiative, a.user)
    await client.post(a.g(f"/archive/initiative/{a.initiative.id}"), headers=a.headers)

    listed = await client.get(a.g("/queues/?archived=true"), headers=a.headers)
    row = next(q for q in listed.json()["items"] if q["id"] == queue.id)
    detail = await client.get(a.g(f"/queues/{queue.id}"), headers=a.headers)

    assert row["can"]["unarchive"] == detail.json()["can"]["unarchive"]
    assert row["can"]["unarchive"] is False
