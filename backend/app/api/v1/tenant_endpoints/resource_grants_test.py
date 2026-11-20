"""Integration tests for the unified bulk resource-grants endpoint.

``PUT /c/{guild}/resource-grants/bulk`` replaces sharing on many resources
(possibly of different types) in one call, best-effort per item: each item is
authorized independently and reported ``ok`` / ``forbidden`` / ``not_found``,
and a bad item never blocks the good ones.
"""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.schemas.tenant.resource_grant import MAX_BULK_GRANT_ITEMS
from app.testing import COUNTERS_UID, add_counter, install_tool_plugin
from app.testing.factories import (
    create_project,
    create_wiki,
)


async def test_bulk_applies_each_item_on_its_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One call shares several resources of different types, each routed to its
    own adapter, and the grants land. A missing resource is ``not_found`` and an
    archived one ``forbidden``, without blocking their siblings; a member who
    cannot manage a project's sharing gets ``forbidden`` and changes nothing."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild=owner.guild, initiative=owner.initiative, initiative_role="member"
    )
    p1, p2, untouched, archived = [
        await create_project(session, owner.initiative, owner.user) for _ in range(4)
    ]
    archived.archived_at = datetime.now(UTC)
    session.add(archived)
    await session.commit()
    wiki = await create_wiki(session, owner.initiative, owner.user)
    url = owner.g("/resource-grants/bulk")

    def item(resource_type: str, resource_id: int, level: str, **grantee) -> dict:
        grantee = grantee or {"user_id": member.user.id}
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "grants": [{**grantee, "level": level}],
        }

    resp = await client.put(
        url,
        headers=owner.headers,
        json={
            "items": [
                item("project", p1.id, "write"),
                item("project", p2.id, "read"),
                item("wiki", wiki.id, "write", all_initiative_members=True),
                item("project", 9_999_999, "read"),
                item("project", archived.id, "read"),
            ]
        },
    )
    assert resp.status_code == 200
    assert [(r["resource_type"], r["status"]) for r in resp.json()["results"]] == [
        ("project", "ok"),
        ("project", "ok"),
        ("wiki", "ok"),
        ("project", "not_found"),
        ("project", "forbidden"),
    ]

    resp = await client.put(
        url,
        headers=member.headers,
        json={"items": [item("project", untouched.id, "write")]},
    )
    assert resp.status_code == 200
    assert [r["status"] for r in resp.json()["results"]] == ["forbidden"]

    for pid, level in ((p1.id, "write"), (p2.id, "read"), (untouched.id, None)):
        detail = await client.get(owner.g(f"/projects/{pid}"), headers=owner.headers)
        assert detail.status_code == 200
        levels = [
            g["level"]
            for g in detail.json()["grants"]
            if g["user_id"] == member.user.id
        ]
        assert levels == ([level] if level else []), detail.json()["grants"]


@pytest.mark.parametrize("count", [0, MAX_BULK_GRANT_ITEMS + 1], ids=["empty", "over"])
async def test_bulk_rejects_an_item_count_outside_its_bounds(
    client: AsyncClient, acting_user, count: int
):
    """An empty list, or one over the cap, is rejected before any work is done."""
    owner = await acting_user(guild_role=CommunityRole.member)
    item = {"resource_type": "project", "resource_id": 1, "grants": []}
    resp = await client.put(
        owner.g("/resource-grants/bulk"),
        headers=owner.headers,
        json={"items": [item] * count},
    )
    assert resp.status_code == 422


async def test_bulk_shares_a_tool_plugins_row(
    client: AsyncClient, session: AsyncSession, acting_user, reading_as
):
    """A tool plug-in's row is shared as a built-in tool's is. An item inside
    it, and a kind the community lacks, are not things sharing is set on."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    moderator = await acting_user(
        guild=admin.guild, initiative=admin.initiative, initiative_role="moderator"
    )
    member = await acting_user(
        guild=moderator.guild, initiative=moderator.initiative, initiative_role="member"
    )
    await session.commit()
    seat = await acting_user(guild=moderator.guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    adding = await reading_as(moderator.user.id, moderator.guild.id)
    group, counter = (
        await add_counter(adding, moderator.guild.id, moderator.initiative.id)
    )[1:]
    await adding.commit()
    kind, item_kind = (
        f"{key}.{COUNTERS_UID.lower()}" for key in ("counter_group", "counter")
    )
    stranger = f"stranger.{'x' * 14}"

    resp = await client.put(
        moderator.g("/resource-grants/bulk"),
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


async def test_unsharing_a_tool_plugins_row_lets_go_of_who_it_names(
    client: AsyncClient, session: AsyncSession, acting_user, reading_as
):
    """Unshared from a tool plug-in's row, a person is let go from the people
    inside it: a declared person field on its item, and a person property on
    the row and its item."""
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
    url = moderator.g("/resource-grants/bulk")

    async def share(grants: list[dict]) -> None:
        resp = await client.put(
            url,
            headers=moderator.headers,
            json={
                "items": [
                    {"resource_type": kind, "resource_id": group, "grants": grants}
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["results"][0]["status"] == "ok"

    await share([{"user_id": member.user.id, "level": "write"}])
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
    await share([])
    assert await named() == ([None], [None, None])
