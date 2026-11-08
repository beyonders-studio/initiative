"""Integration tests for counter group endpoints."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import KINDS, Tool
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.counter import COUNTER_LIMIT
from app.services.tenant import counters as counters_service
from app.testing import (
    Actor,
    create_counter,
    create_counter_group,
    create_initiative,
    create_resource_grant,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_group(
    client: AsyncClient,
    actor: Actor,
    *,
    name: str = "Test Group",
) -> dict:
    response = await client.post(
        actor.g("/counter-groups/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_counter(
    client: AsyncClient,
    actor: Actor,
    group_id: int,
    *,
    name: str = "HP",
    count: str = "100",
    min_value: str | None = "0",
    max_value: str | None = "100",
    step: str = "1",
    initial_count: str = "100",
    view_mode: str = "progress_bar",
    position: str = "0",
) -> dict:
    payload = {
        "name": name,
        "count": count,
        "step": step,
        "initial_count": initial_count,
        "view_mode": view_mode,
        "position": position,
    }
    if min_value is not None:
        payload["min"] = min_value
    if max_value is not None:
        payload["max"] = max_value
    response = await client.post(
        actor.g(f"/counter-groups/{group_id}/counters"),
        headers=actor.headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Counter Group CRUD
# ---------------------------------------------------------------------------


async def test_create_counter_group(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    response = await client.post(
        a.g("/counter-groups/"),
        headers=a.headers,
        json={
            "name": "Combat Tracker",
            "description": "HP, AC, etc.",
            "initiative_id": a.initiative.id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Combat Tracker"
    assert data["description"] == "HP, AC, etc."
    assert data["initiative_id"] == a.initiative.id
    assert data["created_by"] == a.user.id

    blank = await client.post(
        a.g("/counter-groups/"),
        headers=a.headers,
        json={"name": "  ", "initiative_id": a.initiative.id},
    )
    assert blank.status_code == 422, blank.text


async def test_create_counter_group_non_pm_forbidden(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g("/counter-groups/"),
        headers=member.headers,
        json={"name": "Nope", "initiative_id": admin.initiative.id},
    )
    assert response.status_code == 403


async def test_feature_disabled_blocks_creation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.counter_groups_enabled = False
    await session.commit()

    response = await client.post(
        a.g("/counter-groups/"),
        headers=a.headers,
        json={"name": "X", "initiative_id": a.initiative.id},
    )
    assert response.status_code == 403
    assert response.json() == Tool.counter_group.disabled().body


async def test_list_counter_groups(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _create_group(client, a, name="Group A")
    await _create_group(client, a, name="Group B")

    response = await client.get(a.g("/counter-groups/"), headers=a.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert {item["name"] for item in body["items"]} == {"Group A", "Group B"}


async def test_list_counter_groups_previews_their_first_counters(
    client: AsyncClient, acting_user
):
    """Asked for previews, each group brings its first four counters in its own
    order, with their counts."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a, name="Scores")
    for index in range(5):
        await _add_counter(client, a, group["id"], name=f"C{index}", count=str(index))

    response = await client.get(
        a.g("/counter-groups/"), headers=a.headers, params={"include_preview": True}
    )

    assert [
        (counter["name"], counter["count"])
        for counter in response.json()["items"][0]["preview"]
    ] == [("C0", "0"), ("C1", "1"), ("C2", "2"), ("C3", "3")]


# ---------------------------------------------------------------------------
# Counter CRUD + view mode validation
# ---------------------------------------------------------------------------


async def test_add_counter_clamps_initial_and_count(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)

    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="999",
        min_value="0",
        max_value="50",
        initial_count="60",
    )
    assert Decimal(counter["count"]) == Decimal(50)
    assert Decimal(counter["initial_count"]) == Decimal(50)


async def test_progress_bar_requires_bounds(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/counters"),
        headers=a.headers,
        json={
            "name": "Bad",
            "count": "10",
            "view_mode": "progress_bar",
            "step": "1",
            "initial_count": "0",
            "position": "0",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Value operations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "start", "landed"),
    [("up", "99", "100"), ("down", "2", "0")],
    ids=["up to the maximum", "down to the minimum"],
)
async def test_a_step_lands_on_the_bound_rather_than_past_it(
    client: AsyncClient, acting_user, direction: str, start: str, landed: str
):
    """A step wider than the room left stops at the bound it is heading for."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count=start,
        min_value="0",
        max_value="100",
        step="5",
    )

    response = await client.post(
        a.g(f"/counters/{counter['id']}/step"),
        headers=a.headers,
        json={"direction": direction},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal(landed)


async def test_a_step_moves_by_the_counter_s_step_or_the_amount_given(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(
        session, group, count=Decimal(10), step=Decimal(2), max=Decimal(100)
    )

    landed = []
    for body in (
        {"direction": "up"},
        {"direction": "down"},
        {"direction": "up", "amount": "5"},
        {"direction": "down", "amount": "0.5"},
        {"direction": "up", "amount": "1000"},
    ):
        response = await client.post(
            a.g(f"/counters/{counter.id}/step"), headers=a.headers, json=body
        )
        assert response.status_code == 200, response.text
        landed.append(Decimal(response.json()["count"]))
    assert landed == [12, 10, 15, Decimal("14.5"), 100]


@pytest.mark.parametrize(
    "amount",
    [
        "0",
        "-1",
        # More than a counter can store, before the point or after it.
        "10000000000",
        "0.00000000001",
    ],
)
async def test_a_step_moves_by_more_than_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, amount: str
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)

    response = await client.post(
        a.g(f"/counters/{counter.id}/step"),
        headers=a.headers,
        json={"direction": "up", "amount": amount},
    )
    assert response.status_code == 422


async def test_an_open_counter_stops_at_the_largest_number_it_can_store(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group, count=COUNTER_LIMIT - 1)

    response = await client.post(
        a.g(f"/counters/{counter.id}/step"),
        headers=a.headers,
        json={"direction": "up", "amount": "5"},
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["count"]) == COUNTER_LIMIT


async def test_a_deleted_counter_does_not_step(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group, deleted_at=datetime.now(UTC))

    response = await client.post(
        a.g(f"/counters/{counter.id}/step"),
        headers=a.headers,
        json={"direction": "up"},
    )
    assert response.status_code == 404
    assert response.json() == KINDS["counter"].not_found().body


async def test_a_reader_cannot_step_a_counter(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    group = await create_counter_group(session, a.initiative, a.user)
    await create_resource_grant(session, group, all_initiative_members=True)
    counter = await create_counter(session, group)

    response = await client.post(
        reader.g(f"/counters/{counter.id}/step"),
        headers=reader.headers,
        json={"direction": "up"},
    )
    assert response.status_code == 403, response.text


async def test_two_steps_that_overlap_both_count(
    session: AsyncSession, role_session, acting_user
):
    """Staged rather than raced, so it is deterministic: one connection holds
    the counter at 0 while a second step lands and commits. A step computed
    from that copy would write 1 back; one computed by the database makes 2."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)

    first = await role_session("app_admin")
    second = await role_session("app_admin")
    for held in (first, second):
        await set_rls_context(held, SystemGuild(a.guild.id))
    loaded = await counters_service.get_counter(first, counter.id)
    assert loaded is not None and loaded.count == 0

    await counters_service.step_counter(second, counter.id, up=True)
    await second.commit()
    await counters_service.step_counter(first, counter.id, up=True)
    await first.commit()

    await session.refresh(counter)
    assert counter.count == 2


async def test_set_count_clamps(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"], min_value="0", max_value="100")

    response = await client.post(
        a.g(f"/counters/{counter['id']}/set"),
        headers=a.headers,
        json={"count": "9999"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal(100)


async def test_reset_returns_to_initial(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="50",
        initial_count="80",
        min_value="0",
        max_value="100",
    )

    # Drop the value first
    await client.post(
        a.g(f"/counters/{counter['id']}/set"),
        headers=a.headers,
        json={"count": "10"},
    )

    response = await client.post(
        a.g(f"/counters/{counter['id']}/reset"),
        headers=a.headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal(80)


async def test_reset_all_counters(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    c1 = await _add_counter(
        client,
        a,
        group["id"],
        name="A",
        initial_count="50",
        min_value="0",
        max_value="100",
    )
    c2 = await _add_counter(
        client,
        a,
        group["id"],
        name="B",
        initial_count="25",
        min_value="0",
        max_value="100",
        position="1",
    )

    # Mutate both
    await client.post(
        a.g(f"/counters/{c1['id']}/set"),
        headers=a.headers,
        json={"count": "1"},
    )
    await client.post(
        a.g(f"/counters/{c2['id']}/set"),
        headers=a.headers,
        json={"count": "1"},
    )

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/reset-all"), headers=a.headers
    )
    assert response.status_code == 200
    counts = {c["name"]: Decimal(c["count"]) for c in response.json()["counters"]}
    assert counts["A"] == Decimal(50)
    assert counts["B"] == Decimal(25)


# ---------------------------------------------------------------------------
# Position / re-clamp on update
# ---------------------------------------------------------------------------


async def test_update_min_max_reclamps_count(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client, a, group["id"], count="100", min_value="0", max_value="100"
    )

    response = await client.patch(
        a.g(f"/counters/{counter['id']}"),
        headers=a.headers,
        json={"max": "50"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal(50)


async def test_update_null_non_nullable_fields_is_refused(
    client: AsyncClient, acting_user
):
    """A required field is omitted to keep it, never nulled."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"])

    for field in ("name", "step", "initial_count", "view_mode", "position"):
        response = await client.patch(
            a.g(f"/counters/{counter['id']}"),
            headers=a.headers,
            json={field: None},
        )
        assert response.status_code == 422, field

    # Nor is a name blanked, on a counter or its group, or given blank.
    for path, method, body in (
        (f"/counters/{counter['id']}", "PATCH", {"name": "  "}),
        (f"/counter-groups/{group['id']}", "PATCH", {"name": None}),
        (f"/counter-groups/{group['id']}", "PATCH", {"name": "  "}),
        (f"/counter-groups/{group['id']}/counters", "POST", {"name": "  "}),
    ):
        response = await client.request(method, a.g(path), headers=a.headers, json=body)
        assert response.status_code == 422, (path, body)


async def test_update_step_zero_rejected(client: AsyncClient, acting_user):
    """A provided step of 0 is a clean 422, not a 500."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"])

    response = await client.patch(
        a.g(f"/counters/{counter['id']}"),
        headers=a.headers,
        json={"step": "0"},
    )
    assert response.status_code == 422


async def test_decimal_serialization_no_exponent(client: AsyncClient, acting_user):
    """Numeric(20, 10) zeros must not round-trip as ``0E-10``."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="0",
        min_value="0",
        max_value="100",
        initial_count="0",
        step="1",
    )
    # The response body strings should be plain, no scientific notation.
    assert counter["count"] == "0"
    assert counter["initial_count"] == "0"
    assert counter["min"] == "0"
    assert counter["step"] == "1"
    assert counter["position"] == "0"


async def test_delete_counter_soft_deletes_to_trash(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Deleting a counter sets deleted_at and shows it in the trash list."""
    from app.db.soft_delete_filter import select_including_deleted
    from app.models.tenant.counter import Counter

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"], name="HP")

    resp = await client.delete(
        a.g(f"/counters/{counter['id']}"),
        headers=a.headers,
    )
    assert resp.status_code == 204

    # Confirm soft-delete stamp on the row.
    stmt = select_including_deleted(Counter).where(Counter.id == counter["id"])
    row = (await session.exec(stmt)).one()
    assert row.deleted_at is not None
    assert row.deleted_by == a.user.id

    # And it should appear in the trash list.
    trash = await client.get("/api/v1/me/trash", headers=a.headers)
    assert trash.status_code == 200
    entries = trash.json()["items"]
    assert any(
        item["entity_type"] == "counter" and item["entity_id"] == counter["id"]
        for item in entries
    )


async def test_deleted_counter_group_hidden_from_list_and_read(
    client: AsyncClient, acting_user
):
    """Soft-deleted groups must not appear in list/read or accept counter
    adds. The session-level soft-delete filter is what enforces this."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    keep = await _create_group(client, a, name="Keep")
    trashed = await _create_group(client, a, name="Trash me")

    # Delete the second one.
    assert (
        await client.delete(a.g(f"/counter-groups/{trashed['id']}"), headers=a.headers)
    ).status_code == 204

    # List returns only the surviving group.
    listing = (await client.get(a.g("/counter-groups/"), headers=a.headers)).json()
    names = {item["name"] for item in listing["items"]}
    assert names == {"Keep"}
    assert listing["total_count"] == 1

    # Detail read returns 404.
    assert (
        await client.get(a.g(f"/counter-groups/{trashed['id']}"), headers=a.headers)
    ).status_code == 404

    # Trying to add a counter to it also 404s (the group is no longer reachable).
    add_resp = await client.post(
        a.g(f"/counter-groups/{trashed['id']}/counters"),
        headers=a.headers,
        json={
            "name": "Phantom",
            "count": "0",
            "step": "1",
            "initial_count": "0",
            "view_mode": "number",
            "position": "0",
        },
    )
    assert add_resp.status_code == 404

    # The surviving group still accepts adds.
    add_keep = await client.post(
        a.g(f"/counter-groups/{keep['id']}/counters"),
        headers=a.headers,
        json={
            "name": "OK",
            "count": "0",
            "step": "1",
            "initial_count": "0",
            "view_mode": "number",
            "position": "0",
        },
    )
    assert add_keep.status_code == 201


async def test_delete_counter_group_soft_deletes_and_cascades(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Deleting a counter group soft-deletes it AND its counters; the group
    appears in the trash list but the cascaded counters are deduped out."""
    from app.db.soft_delete_filter import select_including_deleted
    from app.models.tenant.counter import Counter, CounterGroup

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"], name="HP")

    resp = await client.delete(
        a.g(f"/counter-groups/{group['id']}"),
        headers=a.headers,
    )
    assert resp.status_code == 204

    group_row = (
        await session.exec(
            select_including_deleted(CounterGroup).where(CounterGroup.id == group["id"])
        )
    ).one()
    counter_row = (
        await session.exec(
            select_including_deleted(Counter).where(Counter.id == counter["id"])
        )
    ).one()

    assert group_row.deleted_at is not None
    assert counter_row.deleted_at is not None
    assert (
        counter_row.deleted_at == group_row.deleted_at
    )  # cascaded with same timestamp

    trash = await client.get("/api/v1/me/trash", headers=a.headers)
    assert trash.status_code == 200
    entries = trash.json()["items"]
    # Group is listed.
    assert any(
        item["entity_type"] == "counter_group" and item["entity_id"] == group["id"]
        for item in entries
    )
    # The cascaded counter is deduplicated out (same deleted_at as parent).
    assert not any(
        item["entity_type"] == "counter" and item["entity_id"] == counter["id"]
        for item in entries
    )


async def test_fractional_position_sort(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group_resp = await _create_group(client, a)
    group_id = group_resp["id"]

    counter_a = await _add_counter(client, a, group_id, name="A", position="10.0")
    await _add_counter(client, a, group_id, name="B", position="20.0")

    # Drop "A" between (would equal 15.0)
    response = await client.patch(
        a.g(f"/counters/{counter_a['id']}"),
        headers=a.headers,
        json={"position": "15.5"},
    )
    assert response.status_code == 200

    group = (
        await client.get(a.g(f"/counter-groups/{group_id}"), headers=a.headers)
    ).json()
    ordered = [c["name"] for c in group["counters"]]
    assert ordered == ["A", "B"] or ordered == ["B", "A"]  # position-ordered
    # Specifically: A position=15.5, B position=20.0 -> A first
    a_pos = next(Decimal(c["position"]) for c in group["counters"] if c["name"] == "A")
    b_pos = next(Decimal(c["position"]) for c in group["counters"] if c["name"] == "B")
    assert a_pos < b_pos


# ---------------------------------------------------------------------------
# Sort all counters
# ---------------------------------------------------------------------------


def _ordered_names(group: dict) -> list[str]:
    counters = sorted(group["counters"], key=lambda c: Decimal(c["position"]))
    return [c["name"] for c in counters]


async def test_sort_counters(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    gid = group["id"]

    # Scrambled order; "alpha" is lowercase to exercise case-insensitive sort.
    await _add_counter(client, a, gid, name="Charlie", count="5", position="0")
    await _add_counter(client, a, gid, name="alpha", count="1", position="1")
    await _add_counter(client, a, gid, name="Bravo", count="3", position="2")

    async def sort(field: str, direction: str) -> dict:
        resp = await client.post(
            a.g(f"/counter-groups/{gid}/sort"),
            headers=a.headers,
            json={"field": field, "direction": direction},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    body = await sort("name", "asc")
    assert _ordered_names(body) == ["alpha", "Bravo", "Charlie"]
    # Positions are reassigned to a clean 1..N sequence.
    positions = sorted(Decimal(c["position"]) for c in body["counters"])
    assert positions == [Decimal(1), Decimal(2), Decimal(3)]

    assert _ordered_names(await sort("name", "desc")) == ["Charlie", "Bravo", "alpha"]
    assert _ordered_names(await sort("count", "asc")) == ["alpha", "Bravo", "Charlie"]
    assert _ordered_names(await sort("count", "desc")) == ["Charlie", "Bravo", "alpha"]

    # The reorder persists on a fresh read.
    fetched = (
        await client.get(a.g(f"/counter-groups/{gid}"), headers=a.headers)
    ).json()
    assert _ordered_names(fetched) == ["Charlie", "Bravo", "alpha"]


async def test_sort_counters_read_only_forbidden(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    group = await _create_group(client, admin)
    gid = group["id"]
    await _add_counter(client, admin, gid, name="A", position="0")

    # Grant the member read-only access on the group.
    grant = await client.put(
        admin.g(f"/counter-groups/{gid}/grants"),
        headers=admin.headers,
        json=[{"user_id": member.user.id, "level": "read"}],
    )
    assert grant.status_code == 200, grant.text

    resp = await client.post(
        member.g(f"/counter-groups/{gid}/sort"),
        headers=member.headers,
        json={"field": "name", "direction": "asc"},
    )
    assert resp.status_code == 403
    assert resp.json() == Tool.counter_group.write_required().body


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


async def test_duplicate_counter_group(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    source = await _create_group(client, a, name="Original")
    sid = source["id"]
    await _add_counter(
        client,
        a,
        sid,
        name="HP",
        count="40",
        initial_count="100",
        position="0",
    )
    await _add_counter(
        client,
        a,
        sid,
        name="Mana",
        count="5",
        min_value=None,
        max_value=None,
        view_mode="number",
        initial_count="0",
        position="1",
    )

    response = await client.post(
        a.g(f"/counter-groups/{sid}/duplicate"), headers=a.headers, json={}
    )
    assert response.status_code == 201, response.text
    copy = response.json()

    # Counters are copied with their values, bounds and order preserved.
    by_name = {
        c["name"]: c
        for c in sorted(copy["counters"], key=lambda c: Decimal(c["position"]))
    }
    assert [
        c["name"]
        for c in sorted(copy["counters"], key=lambda c: Decimal(c["position"]))
    ] == ["HP", "Mana"]
    assert Decimal(by_name["HP"]["count"]) == Decimal(40)
    assert Decimal(by_name["HP"]["initial_count"]) == Decimal(100)
    assert by_name["Mana"]["view_mode"] == "number"

    # The source group is untouched.
    src = (await client.get(a.g(f"/counter-groups/{sid}"), headers=a.headers)).json()
    assert src["name"] == "Original"
    assert len(src["counters"]) == 2


async def test_counter_group_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts mirror the list: DAC-visible groups in counters-enabled
    initiatives only, with no entry for unjoined initiatives."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other_initiative = await create_initiative(session, admin.guild, admin.user)
    disabled_initiative = await create_initiative(
        session, admin.guild, admin.user, counter_groups_enabled=False
    )

    await create_counter_group(session, admin.initiative, member.user)
    await create_counter_group(session, admin.initiative, admin.user)
    await create_counter_group(session, other_initiative, admin.user)
    await create_counter_group(session, disabled_initiative, admin.user)

    # Guild admin: the counts span initiatives, so they count what reaches the
    # reader — the admin's own group in each, not the member's beside it. The
    # disabled initiative is absent either way.
    response = await client.get(
        admin.g("/tools/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"]["counter_group"] == {
        str(admin.initiative.id): 1,
        str(other_initiative.id): 1,
    }

    # Member: only groups shared with them, and no entry for initiatives
    # they are not in.
    response = await client.get(
        member.g("/tools/counts/by-initiative"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"]["counter_group"] == {str(admin.initiative.id): 1}


async def test_a_counter_resolves_by_its_own_id(client, session, acting_user):
    """An envelope names ``(counters, id)`` and no parent, so the id has to be
    the whole address."""
    from app.models.platform.guild import CommunityRole
    from app.testing import create_counter, create_counter_group

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    await session.commit()

    response = await client.get(a.g(f"/counters/{counter.id}"), headers=a.headers)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == counter.id


async def test_a_deleted_counter_reads_back(client, session, acting_user):
    """The read-back a ``counters.deleted`` event depends on. A hand-written
    deleted check used to refuse this even when the request asked for it."""
    from datetime import datetime

    from app.models.platform.guild import CommunityRole
    from app.testing import create_counter, create_counter_group

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    counter_id = counter.id
    counter.deleted_at = datetime.now(UTC)
    session.add(counter)
    await session.commit()

    hidden = await client.get(a.g(f"/counters/{counter_id}"), headers=a.headers)
    assert hidden.status_code == 404

    found = await client.get(
        a.g(f"/counters/{counter_id}"),
        params={"include_deleted": "true"},
        headers=a.headers,
    )
    assert found.status_code == 200, found.text
    assert found.json()["id"] == counter_id


async def test_a_copied_counter_keeps_its_count_at_the_end_of_its_group(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await _create_group(client, a)
    hp = await _add_counter(client, a, group["id"], count="42", position="1")
    await _add_counter(client, a, group["id"], name="MP", position="5")

    response = await client.post(
        a.g(f"/counters/{hp['id']}/duplicate"), headers=a.headers
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert (copy["name"], Decimal(copy["count"]), Decimal(copy["position"])) == (
        "HP (Copy)",
        Decimal(42),
        Decimal(6),
    )
