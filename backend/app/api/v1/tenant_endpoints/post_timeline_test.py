"""Jumping a board to a date.

Two halves that have to agree: the rail, which says which months have notices
and where to land in each, and the anchored feed, which starts there and reads
backwards. They are scoped by one helper for exactly that reason — a rail
offering a month the feed then shows as empty is worse than no rail.
"""

import json
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.testing import (
    assign_tag,
    create_post,
    create_property_definition,
    create_property_value,
    create_tag,
)

_JANUARY = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
_FEBRUARY = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)
_MARCH = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)


async def _posts_enabled(session: AsyncSession, initiative) -> None:
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _board(session: AsyncSession, actor):
    """Three months, one notice each, oldest first."""
    await _posts_enabled(session, actor.initiative)
    made = {}
    for label, when in (("jan", _JANUARY), ("feb", _FEBRUARY), ("mar", _MARCH)):
        made[label] = await create_post(
            session, actor.initiative, actor.user, name=label, published_at=when
        )
    return made


# ---------------------------------------------------------------------------
# The rail
# ---------------------------------------------------------------------------


async def test_the_rail_lists_a_months_notices_newest_first(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _board(session, a)

    response = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )

    assert response.status_code == 200, response.text
    buckets = response.json()["buckets"]
    assert [b["period"] for b in buckets] == ["2026-03", "2026-02", "2026-01"]
    assert [b["count"] for b in buckets] == [1, 1, 1]


async def test_a_months_count_is_its_notices(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    for day in (2, 9, 16):
        await create_post(
            session,
            a.initiative,
            a.user,
            name=f"March {day}",
            published_at=datetime(2026, 3, day, tzinfo=UTC),
        )

    response = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )

    buckets = response.json()["buckets"]
    assert [b["period"] for b in buckets] == ["2026-03"]
    assert buckets[0]["count"] == 3


async def test_the_anchor_lands_on_the_months_first_notice(
    client: AsyncClient, acting_user, session
):
    """The rail's anchor is the newest instant in the month, so asking the feed
    for "at or before this" puts that month at the top rather than the one
    above it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    made = await _board(session, a)

    rail = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )
    february = next(b for b in rail.json()["buckets"] if b["period"] == "2026-02")

    feed = await client.get(
        a.g("/posts/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "until": february["anchor"]},
    )

    assert feed.status_code == 200, feed.text
    names = [item["name"] for item in feed.json()["items"]]
    assert names == ["feb", "jan"]
    assert made["mar"].name not in names


async def test_the_month_boundary_is_cut_in_the_readers_zone(
    client: AsyncClient, acting_user, session
):
    """A notice posted at 23:00 UTC on the 31st is the 1st in Auckland, and a
    reader there should find it filed under the month they posted it in."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    await create_post(
        session,
        a.initiative,
        a.user,
        name="Late",
        published_at=datetime(2026, 1, 31, 23, 0, tzinfo=UTC),
    )

    utc = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )
    auckland = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "tz": "Pacific/Auckland"},
    )

    assert [b["period"] for b in utc.json()["buckets"]] == ["2026-01"]
    assert [b["period"] for b in auckland.json()["buckets"]] == ["2026-02"]


async def test_the_rail_shows_only_months_the_reader_can_open(
    client: AsyncClient, acting_user, session
):
    """The rail and the feed run through one scoping helper, so a month whose
    only notice is a draft is not a stop on somebody else's rail."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    await create_post(
        session,
        a.initiative,
        a.user,
        name="Draft",
        published_at=None,
        scheduled_for=datetime.now(UTC) + timedelta(days=40),
    )
    reader = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )

    author = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )
    other = await client.get(
        a.g("/posts/timeline"),
        headers=reader.headers,
        params={"initiative_id": a.initiative.id},
    )

    assert len(author.json()["buckets"]) == 1
    assert other.json()["buckets"] == []


async def test_the_rail_narrows_with_the_filters(
    client: AsyncClient, acting_user, session
):
    """The rail is a picture of the feed as it stands: with the unread filter
    on, a month that is fully read has nothing to offer, and with a tag or a
    property only the months holding a notice that carries it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    made = await _board(session, a)
    reader = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )
    board = await client.get(
        a.g("/posts/"),
        headers=reader.headers,
        params={"initiative_id": a.initiative.id},
    )
    march = next(p for p in board.json()["items"] if p["name"] == "mar")
    await client.post(
        a.g("/posts/read"), headers=reader.headers, json={"post_ids": [march["id"]]}
    )

    response = await client.get(
        a.g("/posts/timeline"),
        headers=reader.headers,
        params={"initiative_id": a.initiative.id, "unread": True},
    )

    assert [b["period"] for b in response.json()["buckets"]] == ["2026-02", "2026-01"]

    tag = await create_tag(session, a.guild, name="raid")
    await assign_tag(session, made["feb"], tag, commit=True)
    tagged = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "tag_ids": [tag.id]},
    )
    assert [b["period"] for b in tagged.json()["buckets"]] == ["2026-02"]

    stage = await create_property_definition(session, a.initiative, name="Stage")
    await create_property_value(session, made["jan"], stage, value_text="live")
    with_property = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "property_filters": json.dumps(
                [{"property_id": stage.id, "op": "eq", "value": "live"}]
            ),
        },
    )
    assert [b["period"] for b in with_property.json()["buckets"]] == ["2026-01"]


async def test_the_rail_follows_the_archive_view(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    made = await _board(session, a)
    made["jan"].archived_at = datetime.now(UTC)
    session.add(made["jan"])
    await session.commit()

    async def periods(**params) -> list[str]:
        response = await client.get(
            a.g("/posts/timeline"),
            headers=a.headers,
            params={"initiative_id": a.initiative.id, **params},
        )
        assert response.status_code == 200, response.text
        return [b["period"] for b in response.json()["buckets"]]

    assert await periods() == ["2026-03", "2026-02"]
    assert await periods(archived=True) == ["2026-01"]


# ---------------------------------------------------------------------------
# The anchored feed
# ---------------------------------------------------------------------------


async def test_an_anchored_board_is_strictly_chronological(
    client: AsyncClient, acting_user, session
):
    """A pin says what matters now. A reader who has jumped to January is
    reading what mattered then, so the pinned band steps aside rather than
    following them into every month they visit."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    made = await _board(session, a)
    pinned = await client.put(
        a.g(f"/posts/{made['mar'].id}/pin"), headers=a.headers, json={"pinned": True}
    )
    assert pinned.status_code == 200, pinned.text

    unanchored = await client.get(
        a.g("/posts/"), headers=a.headers, params={"initiative_id": a.initiative.id}
    )
    anchored = await client.get(
        a.g("/posts/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "until": _FEBRUARY.isoformat(),
        },
    )

    assert next(p["name"] for p in unanchored.json()["items"]) == "mar"
    assert [p["name"] for p in anchored.json()["items"]] == ["feb", "jan"]


async def test_the_anchor_is_inclusive(client: AsyncClient, acting_user, session):
    """The instant a rail names is a notice's own, so the notice it names has
    to be the first one back — not the one just above it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _board(session, a)

    response = await client.get(
        a.g("/posts/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "until": _FEBRUARY.isoformat()},
    )

    assert next(p["name"] for p in response.json()["items"]) == "feb"


async def test_anchoring_keeps_the_other_filters(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _board(session, a)

    response = await client.get(
        a.g("/posts/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "until": _MARCH.isoformat(),
            "search": "feb",
        },
    )

    assert [p["name"] for p in response.json()["items"]] == ["feb"]


async def test_a_zone_that_is_not_one_falls_back_to_utc(
    client: AsyncClient, acting_user, session
):
    """The zone only draws month lines; a browser sending one the server does
    not know still gets its rail, cut in UTC."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _board(session, a)

    responses = [
        await client.get(
            a.g("/posts/timeline"),
            headers=a.headers,
            params={"initiative_id": a.initiative.id, "tz": tz},
        )
        for tz in ("Not/AZone", "UTC")
    ]

    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()


async def test_a_lifted_pin_is_still_in_its_own_month(
    client: AsyncClient, acting_user, session
):
    """The board lifts a pin to the top, but the rail counts it where it was
    written — otherwise pinning a notice would empty its month from the rail
    and add a phantom to whichever month is current."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    made = await _board(session, a)
    await client.put(
        a.g(f"/posts/{made['jan'].id}/pin"), headers=a.headers, json={"pinned": True}
    )

    response = await client.get(
        a.g("/posts/timeline"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )

    buckets = {b["period"]: b["count"] for b in response.json()["buckets"]}
    assert buckets == {"2026-03": 1, "2026-02": 1, "2026-01": 1}
