"""Integration tests for the unified bulk resource-grants endpoint.

``PUT /c/{guild}/resource-grants/bulk`` replaces sharing on many resources
(possibly of different types) in one call, best-effort per item: each item is
authorized independently and reported ``ok`` / ``forbidden`` / ``not_found``,
and a bad item never blocks the good ones.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.testing import add_counter, install_tool_plugin
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
    create_wiki,
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
    """One request mixing a project and a wiki routes each to the
    right adapter."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member, role_name="member")
    project = await create_project(session, initiative, owner)
    wiki = await create_wiki(session, initiative, owner)
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
                    "resource_type": "wiki",
                    "resource_id": wiki.id,
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
    assert statuses[("wiki", wiki.id)] == "ok"


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
    archived.archived_at = datetime.now(UTC)
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


async def test_bulk_shares_a_tool_plugins_row_and_unsharing_lets_go_of_its_people(
    client: AsyncClient, session: AsyncSession, acting_user, reading_as
):
    """A tool plug-in's row is shared as a built-in tool's is. An item inside
    it, and a kind the community lacks, are not things sharing is set on.
    Unshared from the row, a person is let go from the people inside it: a
    declared person field on its item, and a person property on the row and
    its item."""
    from app.models.tenant.metadata import MetadataType, MetadataValue
    from app.testing import counters_tool_manifest
    from app.testing.factories import create_property_definition
    from app.testing.schema_harness import route_session_to_guild

    moderator = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild=moderator.guild, initiative=moderator.initiative, initiative_role="member"
    )
    await session.commit()
    seat = await acting_user(guild=moderator.guild, guild_role=CommunityRole.superadmin)
    manifest = counters_tool_manifest()
    manifest["tool"]["items"][0]["fields"].append(
        {"key": "keeper", "name": {"en": "Keeper"}, "kind": "user_reference"}
    )
    await install_tool_plugin(client, session, seat, definition=manifest)
    adding = await reading_as(moderator.user.id, moderator.guild.id)
    tools, group, counter = await add_counter(
        adding, moderator.guild.id, moderator.initiative.id, keeper=member.user.id
    )
    await adding.commit()
    (tool,) = tools.installed
    (item,) = tool.items
    kind, item_kind = tool.kind, tool.children[0].value
    stranger = f"stranger.{'x' * 14}"
    url = BULK.format(guild=moderator.guild.id)

    resp = await client.put(
        url,
        headers=moderator.headers,
        json={
            "items": [
                {
                    "resource_type": kind,
                    "resource_id": group,
                    "grants": [{"user_id": member.user.id, "level": "write"}],
                },
                {"resource_type": item_kind, "resource_id": counter, "grants": []},
                {"resource_type": stranger, "resource_id": 1, "grants": []},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert [(r["resource_type"], r["status"]) for r in resp.json()["results"]] == [
        (kind, "ok"),
        (item_kind, "not_found"),
        (stranger, "not_found"),
    ]
    reading = await reading_as(member.user.id, moderator.guild.id)
    levels = (
        await reading.exec(
            sa.text(
                "SELECT user_id, level FROM resource_grants"
                " WHERE resource_type = :k AND resource_id = :g ORDER BY level"
            ),
            params={"k": kind, "g": group},
        )
    ).all()
    assert sorted(tuple(row) for row in levels) == sorted(
        [(moderator.user.id, "owner"), (member.user.id, "write")]
    )
    await reading.rollback()

    definition = await create_property_definition(
        session, moderator.initiative, type=MetadataType.user_reference
    )
    await route_session_to_guild(session, moderator.guild.id)
    for entity_type, entity_id in ((kind, group), (item_kind, counter)):
        session.add(
            MetadataValue(
                entity_type=entity_type,
                entity_id=entity_id,
                property_id=definition.id,
                value_user_id=member.user.id,
            )
        )
    await session.commit()

    async def named() -> tuple[list, list]:
        await route_session_to_guild(session, moderator.guild.id)
        keepers = (await session.exec(sa.select(item.c.keeper))).scalars().all()
        values = (
            (
                await session.exec(
                    sa.select(MetadataValue.value_user_id).where(
                        MetadataValue.property_id == definition.id
                    )
                )
            )
            .scalars()
            .all()
        )
        await session.commit()
        return list(keepers), list(values)

    assert await named() == ([member.user.id], [member.user.id] * 2)
    resp = await client.put(
        url,
        headers=moderator.headers,
        json={"items": [{"resource_type": kind, "resource_id": group, "grants": []}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["status"] == "ok"
    assert await named() == ([None], [None, None])
