"""Integration tests for the unified bulk resource-grants endpoint.

``PUT /c/{guild}/resource-grants/bulk`` replaces sharing on many resources
(possibly of different types) in one call, best-effort per item: each item is
authorized independently and reported ``ok`` / ``forbidden`` / ``not_found``,
and a bad item never blocks the good ones.
"""

from datetime import datetime, timezone
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing.factories import (
    create_counter_group,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
    get_auth_headers,
)

BULK = "/api/v1/c/{guild}/resource-grants/bulk"


def _results_by_id(body: dict) -> dict[int, str]:
    return {r["resource_id"]: r["status"] for r in body["results"]}


async def test_bulk_applies_grants_across_many_projects(
    client: AsyncClient, session: AsyncSession
):
    """A single bulk call shares several projects with a member — all report ``ok``
    and the grants actually land."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member, role_name="member")
    p1 = await create_project(session, initiative, owner)
    p2 = await create_project(session, initiative, owner)
    headers = get_auth_headers(owner)

    resp = await client.put(
        BULK.format(guild=guild.id),
        headers=headers,
        json={
            "items": [
                {
                    "resource_type": "project",
                    "resource_id": p1.id,
                    "grants": [{"user_id": member.id, "level": "write"}],
                },
                {
                    "resource_type": "project",
                    "resource_id": p2.id,
                    "grants": [{"user_id": member.id, "level": "read"}],
                },
            ]
        },
    )
    assert resp.status_code == 200
    assert _results_by_id(resp.json()) == {p1.id: "ok", p2.id: "ok"}

    # The grants actually applied (visible on the project reads).
    for pid, level in ((p1.id, "write"), (p2.id, "read")):
        detail = await client.get(
            f"/api/v1/c/{guild.id}/projects/{pid}", headers=headers
        )
        assert detail.status_code == 200
        grants = detail.json()["grants"]
        assert any(g["user_id"] == member.id and g["level"] == level for g in grants), (
            grants
        )


async def test_bulk_dispatches_across_resource_types(
    client: AsyncClient, session: AsyncSession
):
    """One request mixing a project and a counter group routes each to the
    right adapter."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member, role_name="member")
    project = await create_project(session, initiative, owner)
    group = await create_counter_group(session, initiative, owner)
    headers = get_auth_headers(owner)

    resp = await client.put(
        BULK.format(guild=guild.id),
        headers=headers,
        json={
            "items": [
                {
                    "resource_type": "project",
                    "resource_id": project.id,
                    "grants": [{"user_id": member.id, "level": "read"}],
                },
                {
                    "resource_type": "counter_group",
                    "resource_id": group.id,
                    "grants": [{"all_initiative_members": True, "level": "write"}],
                },
            ]
        },
    )
    assert resp.status_code == 200
    statuses = {
        (r["resource_type"], r["resource_id"]): r["status"]
        for r in resp.json()["results"]
    }
    assert statuses[("project", project.id)] == "ok"
    assert statuses[("counter_group", group.id)] == "ok"


async def test_bulk_is_best_effort_per_item(client: AsyncClient, session: AsyncSession):
    """A missing resource (``not_found``) is skipped without blocking a valid item
    (``ok``) in the same request."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member, role_name="member")
    project = await create_project(session, initiative, owner)
    headers = get_auth_headers(owner)

    resp = await client.put(
        BULK.format(guild=guild.id),
        headers=headers,
        json={
            "items": [
                {
                    "resource_type": "project",
                    "resource_id": project.id,
                    "grants": [{"user_id": member.id, "level": "write"}],
                },
                {
                    "resource_type": "project",
                    "resource_id": 9_999_999,
                    "grants": [{"user_id": member.id, "level": "read"}],
                },
            ]
        },
    )
    assert resp.status_code == 200
    assert _results_by_id(resp.json()) == {project.id: "ok", 9_999_999: "not_found"}

    # The valid item applied despite its bad sibling.
    detail = await client.get(
        f"/api/v1/c/{guild.id}/projects/{project.id}", headers=headers
    )
    assert any(g["user_id"] == member.id for g in detail.json()["grants"])


async def test_bulk_reports_forbidden_for_unmanageable_item(
    client: AsyncClient, session: AsyncSession
):
    """A member who can't manage a project's sharing gets ``forbidden`` for it, and
    the resource is left untouched."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member, role_name="member")
    project = await create_project(session, initiative, owner)
    member_headers = get_auth_headers(member)

    resp = await client.put(
        BULK.format(guild=guild.id),
        headers=member_headers,
        json={
            "items": [
                {
                    "resource_type": "project",
                    "resource_id": project.id,
                    "grants": [{"user_id": member.id, "level": "write"}],
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert _results_by_id(resp.json()) == {project.id: "forbidden"}

    # Nothing changed — the member did not self-grant write.
    owner_headers = get_auth_headers(owner)
    detail = await client.get(
        f"/api/v1/c/{guild.id}/projects/{project.id}", headers=owner_headers
    )
    assert not any(
        g["user_id"] == member.id and g["level"] == "write"
        for g in detail.json()["grants"]
    )


async def test_bulk_skips_archived_project_but_applies_the_rest(
    client: AsyncClient, session: AsyncSession
):
    """An archived project can't have its sharing changed (reported ``forbidden``),
    while a live project in the same request still applies."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member, role_name="member")
    live = await create_project(session, initiative, owner)
    archived = await create_project(session, initiative, owner)
    archived.archived_at = datetime.now(timezone.utc)
    session.add(archived)
    await session.commit()
    headers = get_auth_headers(owner)

    resp = await client.put(
        BULK.format(guild=guild.id),
        headers=headers,
        json={
            "items": [
                {
                    "resource_type": "project",
                    "resource_id": live.id,
                    "grants": [{"user_id": member.id, "level": "read"}],
                },
                {
                    "resource_type": "project",
                    "resource_id": archived.id,
                    "grants": [{"user_id": member.id, "level": "read"}],
                },
            ]
        },
    )
    assert resp.status_code == 200
    assert _results_by_id(resp.json()) == {live.id: "ok", archived.id: "forbidden"}


async def test_bulk_rejects_too_many_items(client: AsyncClient, session: AsyncSession):
    """A request over the item cap is rejected (422) before any work is done."""
    from app.schemas.tenant.resource_grant import MAX_BULK_GRANT_ITEMS

    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    headers = get_auth_headers(owner)

    item = {"resource_type": "project", "resource_id": 1, "grants": []}
    resp = await client.put(
        BULK.format(guild=guild.id),
        headers=headers,
        json={"items": [item] * (MAX_BULK_GRANT_ITEMS + 1)},
    )
    assert resp.status_code == 422


async def test_bulk_rejects_empty_items(client: AsyncClient, session: AsyncSession):
    """An empty item list is rejected (422)."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    headers = get_auth_headers(owner)

    resp = await client.put(
        BULK.format(guild=guild.id), headers=headers, json={"items": []}
    )
    assert resp.status_code == 422
