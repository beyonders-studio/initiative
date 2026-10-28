"""
Integration tests for property definition endpoints.

Covers /api/v1/property-definitions CRUD including:
- RLS initiative isolation
- Union-across-initiatives list behavior
- Duplicate-name protection (per initiative)
- Option validation on create/update
- Orphaned-value counting on PATCH
- Cascade delete to attached values
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.metadata import (
    MetadataDefinition,
    MetadataType,
    MetadataValue,
)
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.tool_layout import ToolLayout
from app.testing import (
    create_collection,
    create_file,
    create_initiative,
    create_project,
    create_property_definition,
    create_property_value,
    create_resource_grant,
    create_task,
)
from app.testing.factories import grant_role_permission


# ---------------------------------------------------------------------------
# GET / — scope behavior
# ---------------------------------------------------------------------------


async def test_list_property_definitions_returns_union_across_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Without ``initiative_id`` the list endpoint returns the caller's
    accessible union — definitions across every initiative they're in."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    response = await client.get(
        a.g("/property-definitions/"),
        headers=a.headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert defn_a.id in ids
    assert defn_b.id in ids


async def test_list_property_definitions_filtered_by_initiative_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``?initiative_id=X`` filters to that initiative's definitions only."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    response = await client.get(
        a.g(f"/property-definitions/?initiative_id={init_a.id}"),
        headers=a.headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert defn_a.id in ids
    assert defn_b.id not in ids


async def test_list_property_definitions_scoped_by_initiative_id_query(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Requesting a specific ``initiative_id`` scopes the result even when
    the caller technically has visibility across multiple initiatives
    (guild-admin visibility still respects explicit
    filtering through the query param).
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    # Scoped to A
    response_a = await client.get(
        a.g(f"/property-definitions/?initiative_id={init_a.id}"),
        headers=a.headers,
    )
    assert response_a.status_code == 200
    ids_a = {item["id"] for item in response_a.json()}
    assert defn_a.id in ids_a
    assert defn_b.id not in ids_a

    # Scoped to B
    response_b = await client.get(
        a.g(f"/property-definitions/?initiative_id={init_b.id}"),
        headers=a.headers,
    )
    assert response_b.status_code == 200
    ids_b = {item["id"] for item in response_b.json()}
    assert defn_b.id in ids_b
    assert defn_a.id not in ids_b


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


async def test_create_text_property_definition(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    payload = {
        "name": "Status",
        "type": "text",
        "position": 1.0,
        "initiative_id": a.initiative.id,
    }
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Status"
    assert data["type"] == "text"
    assert data["initiative_id"] == a.initiative.id


async def test_create_rejected_when_not_initiative_member(
    client: AsyncClient, acting_user
):
    """A plain (non-admin) guild member can't create definitions on an
    initiative they don't belong to.
    """
    # Alice owns the initiative; Bob is a guild member but NOT an initiative member.
    alice = await acting_user(guild_role=CommunityRole.member, initiative=True)
    bob = await acting_user(guild_role=CommunityRole.member, guild=alice.guild)

    payload = {
        "name": "Foo",
        "type": "text",
        "initiative_id": alice.initiative.id,
    }
    response = await client.post(
        bob.g("/property-definitions/"), headers=bob.headers, json=payload
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "PROPERTY_NOT_INITIATIVE_MEMBER"


async def test_create_allowed_for_initiative_member(client: AsyncClient, acting_user):
    """A plain (non-admin) guild member who belongs to the initiative can
    create a definition on it.

    This is the schema-per-guild regression case: the membership check runs on
    the routed request session against the active guild's schema, so a
    legitimate member is not false-403'd by a lookup in the wrong schema.
    """
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    payload = {
        "name": "Owner Tag",
        "type": "text",
        "initiative_id": admin.initiative.id,
    }
    response = await client.post(
        member.g("/property-definitions/"), headers=member.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Owner Tag"
    assert data["initiative_id"] == admin.initiative.id


async def test_create_rejected_for_guild_member_not_in_initiative(
    client: AsyncClient, acting_user
):
    """A guild member who is NOT in the target initiative is rejected with
    the canonical NOT_INITIATIVE_MEMBER code."""
    # Admin's initiative; outsider is a guild member but not an initiative member.
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    payload = {
        "name": "Foo",
        "type": "text",
        "initiative_id": admin.initiative.id,
    }
    response = await client.post(
        outsider.g("/property-definitions/"), headers=outsider.headers, json=payload
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "PROPERTY_NOT_INITIATIVE_MEMBER"


async def test_create_allowed_for_guild_admin_not_in_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin can create a definition on any initiative in their
    guild even without an explicit initiative-member row — mirroring the
    restrictive RLS policy's admin bypass, now resolved off
    ``GuildContext.role``."""
    # The creator owns the initiative; the guild admin is not a member of it.
    creator = await acting_user(guild_role=CommunityRole.member, initiative=True)
    guild_admin = await acting_user(guild_role=CommunityRole.admin, guild=creator.guild)

    payload = {
        "name": "Admin Field",
        "type": "text",
        "initiative_id": creator.initiative.id,
    }
    response = await client.post(
        guild_admin.g("/property-definitions/"),
        headers=guild_admin.headers,
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["initiative_id"] == creator.initiative.id


async def test_create_select_requires_options(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    payload = {"name": "State", "type": "select", "initiative_id": a.initiative.id}
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("PROPERTY_OPTIONS_REQUIRED" in str(err) for err in detail)


async def test_create_duplicate_name_case_insensitive_conflicts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    await create_property_definition(session, a.initiative, name="Priority")

    payload = {"name": "priority", "type": "text", "initiative_id": a.initiative.id}
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "PROPERTY_NAME_ALREADY_EXISTS"


async def test_create_same_name_in_different_initiatives_allowed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The uniqueness index is on (initiative_id, lower(name)) — two
    initiatives can each have their own 'Priority' without clashing."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    await create_property_definition(session, init_a, name="Priority")

    payload = {"name": "Priority", "type": "text", "initiative_id": init_b.id}
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )
    assert response.status_code == 201


async def test_create_select_duplicate_option_values_rejected(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    payload = {
        "name": "Phase",
        "type": "select",
        "initiative_id": a.initiative.id,
        "options": [
            {"value": "draft", "label": "Draft"},
            {"value": "draft", "label": "Also Draft"},
        ],
    }
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("PROPERTY_DUPLICATE_OPTION_VALUE" in str(err) for err in detail)


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


async def test_patch_missing_definition_returns_404(client: AsyncClient, acting_user):
    """Unknown definition id → 404 with the canonical error code."""
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.patch(
        a.g("/property-definitions/99999"),
        headers=a.headers,
        json={"name": "Gone"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


async def test_patch_renames_color_and_position(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    defn = await create_property_definition(
        session, a.initiative, name="Old Name", position=0.0
    )

    payload = {"name": "New Name", "color": "#FF00AA", "position": 5.5}
    response = await client.patch(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["definition"]["name"] == "New Name"
    assert data["definition"]["color"] == "#FF00AA"
    assert data["definition"]["position"] == 5.5
    assert data["orphaned_value_count"] == 0


async def test_patch_ignores_type_change_silently(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The Update schema has no `type` field, so sending one is ignored."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    defn = await create_property_definition(
        session, a.initiative, name="Immutable", type=MetadataType.text
    )

    payload = {"type": "number", "name": "Renamed"}
    response = await client.patch(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["definition"]["type"] == "text"
    assert response.json()["definition"]["name"] == "Renamed"


async def test_patch_removing_option_reports_orphaned_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Removing an option on a select with attached values reports the orphans."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    defn = await create_property_definition(
        session,
        a.initiative,
        name="Stage",
        type=MetadataType.select,
        options=[
            {"value": "draft", "label": "Draft"},
            {"value": "live", "label": "Live"},
        ],
    )

    # Attach a file value that uses the "live" slug.
    doc = await create_file(session, a.initiative, a.user)
    await create_property_value(session, doc, defn, value_text="live")

    # Remove "live" from the option list.
    payload = {"options": [{"value": "draft", "label": "Draft"}]}
    response = await client.patch(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["orphaned_value_count"] >= 1

    # DB value should still be present — orphans are preserved.
    result = await session.exec(
        select(MetadataValue).where(
            MetadataValue.property_id == defn.id,
            MetadataValue.entity_type == "file",
            MetadataValue.entity_id == doc.id,
        )
    )
    assert result.one_or_none() is not None


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------


async def test_a_member_adds_options_and_a_manager_reshapes(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Offering a new value is part of filling a field in; renaming it,
    changing or dropping its options or removing it is setting the initiative
    up."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    stage = {"value": "todo", "label": "To do"}
    defn = await create_property_definition(
        session, admin.initiative, type=MetadataType.select, options=[stage]
    )
    route = member.g(f"/property-definitions/{defn.id}")
    added = [stage, {"value": "done", "label": "Done"}]

    response = await client.patch(
        route, headers=member.headers, json={"options": added}
    )
    assert response.status_code == 200, response.text

    # Sent from a list that was already out of date, the other addition stays.
    later = {"value": "later", "label": "Later"}
    response = await client.patch(
        route, headers=member.headers, json={"options": [later, stage]}
    )
    assert response.status_code == 200, response.text
    options = response.json()["definition"]["options"]
    assert [opt["value"] for opt in options] == ["todo", "done", "later"]

    # An option already there is left as it is.
    relabelled = {**stage, "label": "Backlog"}
    response = await client.patch(
        route, headers=member.headers, json={"options": [relabelled]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["definition"]["options"][0]["label"] == "To do"

    response = await client.patch(route, headers=member.headers, json={"name": "New"})
    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"
    response = await client.delete(route, headers=member.headers)
    assert response.status_code == 403

    response = await client.patch(
        route, headers=admin.headers, json={"options": [added[1]]}
    )
    assert response.status_code == 200, response.text


async def test_delete_definition_cascades_to_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    defn = await create_property_definition(session, a.initiative, name="Meta")

    project = await create_project(session, a.initiative, a.user, name="Proj")
    task = await create_task(session, project)
    doc = await create_file(session, a.initiative, a.user)

    await create_property_value(session, doc, defn, value_text="a doc value")
    await create_property_value(session, task, defn, value_text="a task value")

    response = await client.delete(
        a.g(f"/property-definitions/{defn.id}"), headers=a.headers
    )
    assert response.status_code == 204

    # The doc's and the task's value rows are gone
    values = await session.exec(
        select(MetadataValue).where(MetadataValue.property_id == defn.id)
    )
    assert values.all() == []

    # Definition gone
    defn_row = await session.exec(
        select(MetadataDefinition).where(MetadataDefinition.id == defn.id)
    )
    assert defn_row.one_or_none() is None


# ---------------------------------------------------------------------------
# A collection's own fields, scales and money
# ---------------------------------------------------------------------------


async def test_a_collection_field_is_made_by_whoever_may_change_the_collection(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    shared = await create_file(session, owner.initiative, owner.user)
    await create_resource_grant(session, shared, all_initiative_members=True)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )
    payload = {
        "name": "Rating",
        "type": "scale",
        "initiative_id": owner.initiative.id,
        "collection_id": collection.id,
    }

    refused = await client.post(
        member.g("/property-definitions/"), headers=member.headers, json=payload
    )
    assert refused.status_code == 403

    await grant_role_permission(session, owner.initiative, "create_files")
    created = await client.post(
        member.g("/property-definitions/"), headers=member.headers, json=payload
    )
    assert created.status_code == 201, created.text
    field_id = created.json()["id"]
    assert created.json()["collection_id"] == collection.id

    async def listed(**params) -> list[int]:
        found = await client.get(
            member.g("/property-definitions/"), headers=member.headers, params=params
        )
        return [item["id"] for item in found.json()]

    assert field_id not in await listed(initiative_id=owner.initiative.id)
    assert await listed(collection_id=collection.id) == [field_id]

    # Not an initiative manager, and changing the collection is enough.
    renamed = await client.patch(
        member.g(f"/property-definitions/{field_id}"),
        headers=member.headers,
        json={"name": "Stars"},
    )
    assert renamed.status_code == 200, renamed.text
    removed = await client.delete(
        member.g(f"/property-definitions/{field_id}"), headers=member.headers
    )
    assert removed.status_code == 204


async def test_money_names_its_currency_and_keeps_its_amount(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    payload = {"name": "Deal", "type": "currency", "initiative_id": a.initiative.id}

    unnamed = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )
    assert unnamed.status_code == 422
    assert "PROPERTY_CURRENCY_REQUIRED" in str(unnamed.json()["detail"])

    created = await client.post(
        a.g("/property-definitions/"),
        headers=a.headers,
        json={**payload, "currency": "EUR"},
    )
    assert created.status_code == 201, created.text
    definition_id = created.json()["id"]
    project = await create_project(session, a.initiative, a.user)
    task = await create_task(session, project)

    written = await client.put(
        a.g(f"/properties/task/{task.id}"),
        headers=a.headers,
        json={"values": [{"property_id": definition_id, "value": "1234.56"}]},
    )
    assert written.status_code == 200, written.text
    assert [(v["value"], v["currency"]) for v in written.json()] == [(1234.56, "EUR")]
    stored = await session.exec(
        select(MetadataValue.value_number).where(
            MetadataValue.property_id == definition_id
        )
    )
    assert stored.one() == Decimal("1234.56")


# ---------------------------------------------------------------------------
# A project's metadata
# ---------------------------------------------------------------------------


async def test_a_projects_metadata_is_defined_by_whoever_may_write_its_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Listed only with its project, unique by name there and not among the
    initiative's properties, and gone with the project. Nobody types in a
    plug-in's types."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)
    await create_resource_grant(session, project, all_initiative_members=True)
    await create_property_definition(session, owner.initiative, name="Points")
    payload = {
        "name": "Points",
        "type": "number",
        "initiative_id": owner.initiative.id,
        "project_id": project.id,
    }

    refused = await client.post(
        reader.g("/property-definitions/"), headers=reader.headers, json=payload
    )
    assert refused.status_code == 403, refused.text
    created = await client.post(
        owner.g("/property-definitions/"), headers=owner.headers, json=payload
    )
    assert created.status_code == 201, created.text
    assert created.json()["project_id"] == project.id
    again = await client.post(
        owner.g("/property-definitions/"), headers=owner.headers, json=payload
    )
    assert again.status_code == 409, again.text
    for kind in ("link", "badge", "json"):
        plugins = await client.post(
            owner.g("/property-definitions/"),
            headers=owner.headers,
            json={**payload, "name": kind, "type": kind},
        )
        assert plugins.status_code == 422, plugins.text

    async def listed(actor, **params) -> list[int]:
        found = await client.get(
            actor.g("/property-definitions/"), headers=actor.headers, params=params
        )
        return [item["id"] for item in found.json()]

    metadata_id = created.json()["id"]
    assert metadata_id not in await listed(owner, initiative_id=owner.initiative.id)
    assert await listed(reader, project_id=project.id) == [metadata_id]
    renamed = await client.patch(
        reader.g(f"/property-definitions/{metadata_id}"),
        headers=reader.headers,
        json={"name": "Effort"},
    )
    assert renamed.status_code == 403, renamed.text

    await session.delete(project)
    await session.commit()
    gone = await session.exec(
        select(MetadataDefinition).where(MetadataDefinition.id == metadata_id)
    )
    assert gone.one_or_none() is None


# ---------------------------------------------------------------------------
# The initiative's settings: every owner's, bulk delete and promote
# ---------------------------------------------------------------------------


async def test_the_settings_list_only_the_properties_the_reader_may_edit(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member who may edit one project and only read another sees the
    first's properties and not the second's, and can neither delete nor
    promote the second's; the community's admin sees both."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    initiative = owner.initiative
    editable = await create_project(session, initiative, owner.user, name="Alpha")
    readable = await create_project(session, initiative, owner.user, name="Beta")
    await create_resource_grant(
        session, editable, user=member.user, level=ResourceAccessLevel.write
    )
    await create_resource_grant(session, readable, all_initiative_members=True)
    metadata = await create_property_definition(session, initiative, name="Stage")
    alpha = await create_property_definition(
        session, initiative, name="Points", type=MetadataType.number, project=editable
    )
    beta = await create_property_definition(
        session, initiative, name="Effort", type=MetadataType.number, project=readable
    )

    async def groups(actor) -> list[tuple]:
        listed = await client.get(
            actor.g("/property-definitions/by-owner"),
            headers=actor.headers,
            params={"initiative_id": initiative.id},
        )
        assert listed.status_code == 200, listed.text
        return [
            (
                group["owner"],
                group["name"],
                group["can_edit"],
                [definition["id"] for definition in group["definitions"]],
            )
            for group in listed.json()["groups"]
        ]

    assert await groups(member) == [
        ("initiative", None, False, [metadata.id]),
        ("project", "Alpha", True, [alpha.id]),
    ]
    assert await groups(admin) == [
        ("initiative", None, True, [metadata.id]),
        ("project", "Alpha", True, [alpha.id]),
        ("project", "Beta", True, [beta.id]),
    ]

    url = member.g("/property-definitions/")
    for ids in ([beta.id], [alpha.id, beta.id]):
        refused = await client.post(
            f"{url}bulk-delete",
            headers=member.headers,
            json={"initiative_id": initiative.id, "ids": ids},
        )
        assert refused.status_code == 403, refused.text
    promoted = await client.post(
        f"{url}promote",
        headers=member.headers,
        json={
            "initiative_id": initiative.id,
            "ids": [alpha.id, beta.id],
            "name": "Size",
        },
    )
    assert promoted.status_code == 403, promoted.text
    kept = await session.exec(
        select(MetadataDefinition.id).where(
            col(MetadataDefinition.id).in_([alpha.id, beta.id])
        )
    )
    assert sorted(kept.all()) == sorted([alpha.id, beta.id])

    # What they may edit, they promote and delete.
    task = await create_task(session, editable)
    await create_property_value(session, task, alpha, value_number=Decimal(3))
    promoted = await client.post(
        f"{url}promote",
        headers=member.headers,
        json={"initiative_id": initiative.id, "ids": [alpha.id], "name": "Points"},
    )
    assert promoted.status_code == 200, promoted.text
    moved = await session.exec(
        select(MetadataValue.value_number).where(
            MetadataValue.property_id == promoted.json()["id"]
        )
    )
    assert moved.all() == [Decimal(3)]
    other = await create_property_definition(session, initiative, project=editable)
    deleted = await client.post(
        f"{url}bulk-delete",
        headers=member.headers,
        json={"initiative_id": initiative.id, "ids": [other.id]},
    )
    assert deleted.status_code == 204, deleted.text
    # The initiative's metadata is reshaped by its managers.
    refused = await client.post(
        f"{url}bulk-delete",
        headers=member.headers,
        json={"initiative_id": initiative.id, "ids": [metadata.id]},
    )
    assert refused.status_code == 403, refused.text


async def test_promote_merges_properties_into_one_metadata_field(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Options join by value, values move with the newest kept where an item
    holds several, layouts show the merged field once in their place, and the
    sources go."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    initiative = a.initiative
    first = await create_project(session, initiative, a.user, name="One")
    second = await create_project(session, initiative, a.user, name="Two")
    shared = await create_file(session, initiative, a.user)
    walls = [
        await create_collection(session, initiative, a.user, files=[shared])
        for _ in range(2)
    ]

    def options(*values: str) -> list[dict]:
        return [{"value": value, "label": value.title()} for value in values]

    sizes = [
        await create_property_definition(
            session,
            initiative,
            name="Size",
            type=MetadataType.select,
            options=options(*values),
            **owner,
        )
        for values, owner in (
            (("small", "medium"), {"project": first}),
            (("medium", "large"), {"project": second}),
            (("tiny",), {"collection": walls[0]}),
            (("huge",), {"collection": walls[1]}),
        )
    ]
    one, two = await create_task(session, first), await create_task(session, second)
    await create_property_value(session, one, sizes[0], value_text="small")
    await create_property_value(session, two, sizes[1], value_text="large")
    now = datetime.now(timezone.utc)
    await create_property_value(
        session, shared, sizes[2], value_text="tiny", updated_at=now
    )
    await create_property_value(
        session,
        shared,
        sizes[3],
        value_text="huge",
        updated_at=now - timedelta(days=1),
    )
    existing = await create_property_definition(
        session,
        initiative,
        name="size",
        type=MetadataType.select,
        options=options("medium"),
    )
    laid_out = await client.put(
        a.g("/layouts/"),
        params={"tool": "project", "tool_id": first.id},
        headers=a.headers,
        json={
            "kind": "table",
            "definition": {
                "columns": [
                    "title",
                    f"property:{sizes[0].id}",
                    f"property:{existing.id}",
                ]
            },
        },
    )
    assert laid_out.status_code == 200, laid_out.text
    url = a.g("/property-definitions/")
    every = [size.id for size in sizes]

    number = await create_property_definition(
        session, initiative, type=MetadataType.number, project=second
    )
    await create_property_definition(
        session, initiative, name="Count", type=MetadataType.number
    )
    for ids, name, status_code, detail in (
        ([sizes[0].id, number.id], "Size", 400, "PROPERTY_PROMOTE_TYPES_DIFFER"),
        # The initiative's own metadata is not a property to promote.
        ([existing.id], "Size", 404, "PROPERTY_DEFINITION_NOT_FOUND"),
        # Of that name, but not of that type.
        (every, "count", 409, "PROPERTY_NAME_ALREADY_EXISTS"),
    ):
        refused = await client.post(
            f"{url}promote",
            headers=a.headers,
            json={"initiative_id": initiative.id, "ids": ids, "name": name},
        )
        assert refused.status_code == status_code, refused.text
        assert refused.json()["detail"] == detail

    promoted = await client.post(
        f"{url}promote",
        headers=a.headers,
        json={"initiative_id": initiative.id, "ids": every, "name": "Size"},
    )
    assert promoted.status_code == 200, promoted.text
    merged = promoted.json()
    assert merged["id"] == existing.id
    assert (merged["project_id"], merged["collection_id"]) == (None, None)
    assert [option["value"] for option in merged["options"]] == [
        "medium",
        "small",
        "large",
        "tiny",
        "huge",
    ]

    values = await session.exec(
        select(MetadataValue.entity_type, MetadataValue.value_text).where(
            MetadataValue.property_id == existing.id
        )
    )
    assert sorted(values.all()) == [
        ("file", "tiny"),
        ("task", "large"),
        ("task", "small"),
    ]
    gone = await session.exec(
        select(MetadataDefinition.id).where(col(MetadataDefinition.id).in_(every))
    )
    assert gone.all() == []
    layout = await session.exec(
        select(ToolLayout.definition).where(
            ToolLayout.tool == "project", ToolLayout.tool_id == first.id
        )
    )
    assert layout.one()["columns"] == ["title", f"property:{existing.id}"]


async def test_promote_moves_no_value_onto_what_the_reader_may_not_edit(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A collection's values are written by whoever may change it, and the
    initiative's metadata only by whoever may edit the file: a value on a
    file the reader only reads refuses the merge, and nothing changes."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await grant_role_permission(session, owner.initiative, "create_files")
    shared = await create_file(session, owner.initiative, owner.user)
    await create_resource_grant(session, shared, all_initiative_members=True)
    wall = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )
    rating = await create_property_definition(
        session, owner.initiative, type=MetadataType.scale, collection=wall
    )
    await create_property_value(session, shared, rating, value_number=Decimal(80))

    refused = await client.post(
        member.g("/property-definitions/promote"),
        headers=member.headers,
        json={
            "initiative_id": owner.initiative.id,
            "ids": [rating.id],
            "name": "Rating",
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "PROPERTY_PROMOTE_VALUE_NOT_EDITABLE"
    kept = await session.exec(
        select(MetadataDefinition.id).where(
            MetadataDefinition.initiative_id == owner.initiative.id
        )
    )
    assert kept.all() == [rating.id]


async def test_the_database_refuses_a_projects_property_to_whoever_only_reads_it(
    session: AsyncSession, acting_user, reading_as
):
    """Written on the request's own login and routing, with no route in front:
    a member who reads project B and may not edit it reads B's property and
    can't make, change or delete one; on project A, which they may edit, the
    same statements land."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    initiative = owner.initiative
    editable = await create_project(session, initiative, owner.user, name="Alpha")
    readable = await create_project(session, initiative, owner.user, name="Beta")
    await create_resource_grant(
        session, editable, user=member.user, level=ResourceAccessLevel.write
    )
    await create_resource_grant(session, readable, all_initiative_members=True)
    alpha = await create_property_definition(session, initiative, project=editable)
    beta = await create_property_definition(session, initiative, project=readable)

    writer = await reading_as(member.user.id, owner.guild.id)
    seen = await writer.exec(
        select(MetadataDefinition.id).where(
            col(MetadataDefinition.id).in_([alpha.id, beta.id])
        )
    )
    assert sorted(seen.all()) == sorted([alpha.id, beta.id])

    def renamed(definition: MetadataDefinition):
        return (
            update(MetadataDefinition)
            .where(col(MetadataDefinition.id) == definition.id)
            .values(name="Renamed")
        )

    assert (await writer.exec(renamed(beta))).rowcount == 0
    removed = delete(MetadataDefinition).where(col(MetadataDefinition.id) == beta.id)
    assert (await writer.exec(removed)).rowcount == 0
    assert (await writer.exec(renamed(alpha))).rowcount == 1
    await writer.commit()

    for project, refused in ((editable, False), (readable, True)):
        writer.add(
            MetadataDefinition(
                initiative_id=initiative.id,
                project_id=project.id,
                name=f"Made in {project.name}",
                type=MetadataType.text,
            )
        )
        if refused:
            with pytest.raises(DBAPIError):
                await writer.commit()
            await writer.rollback()
        else:
            await writer.commit()
