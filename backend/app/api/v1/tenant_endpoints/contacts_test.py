"""The address book tool: an initiative's contacts, each shared on its own, and
the community's, which the community contacts plug-in holds.

Covers making, reading, changing and trashing one; who reads one by its
sharing; who makes and edits a community contact; an initiative's task naming
a community contact, which the contact's own links do not list; moving a
contact into the community's contacts; and contacts going out as a spreadsheet
and coming back in.
"""

import csv
import io

from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ContactMessages, InitiativeMessages
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.contact import Contact
from app.models.tenant.metadata import MetadataType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.testing import (
    create_contact,
    create_guest,
    create_guild_plugin,
    create_initiative,
    create_property_definition,
    create_property_value,
    create_resource_grant,
    create_tag,
    create_task,
    get_auth_headers,
    grant_role_permission,
    guild_url,
    route_session_to_guild,
    strip_non_owner_grants,
)
from app.testing.plugin_clients import install_headers, install_plugin


async def _install(session: AsyncSession, actor):
    """The community contacts plug-in, which holds the community's contacts."""
    return await create_guild_plugin(
        session,
        actor.guild,
        actor.user,
        definition={"plugin_kind": "tool_instance", "tool": Tool.contact.value},
        name="Community contacts",
        plugin_kind="tool_instance",
    )


async def _sharing(session: AsyncSession, guild_id: int, contact_id: int) -> set:
    """Each grant on a contact: to whom, at what level, and in which
    initiative."""
    await route_session_to_guild(session, guild_id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.contact.value,
                ResourceGrant.resource_id == contact_id,
            )
        )
    ).all()
    return {
        (
            g.plugin_install_id,
            g.user_id,
            str(g.level),
            g.all_initiative_members,
            g.initiative_id,
        )
        for g in grants
    }


async def test_an_initiative_contact_is_made_read_changed_and_trashed(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    made = await client.post(
        a.g("/contacts/"),
        headers=a.headers,
        json={
            "name": "Lakeside Lodge",
            "is_organization": True,
            "initiative_id": a.initiative.id,
            "emails": [{"label": "Bookings", "value": "events@lakeside.example"}],
            "phones": [{"label": "Office", "value": "+1 (555) 010-2000 x12"}],
            "addresses": [{"value": "1 Shore Road\nLakeside"}],
            "websites": [{"value": "lakeside.example"}],
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["name"], body["is_organization"], body["initiative_id"]) == (
        "Lakeside Lodge",
        True,
        a.initiative.id,
    )
    assert body["addresses"] == [{"label": "", "value": "1 Shore Road\nLakeside"}]
    # A website written without a scheme is an https one.
    assert body["websites"] == [{"label": "", "value": "https://lakeside.example"}]
    assert body["can"]["delete"] is True

    for refused in (
        {"phones": [{"value": "call the office"}]},
        {"emails": [{"value": "not an address"}]},
        {"websites": [{"value": "javascript:alert(1)"}]},
    ):
        response = await client.patch(
            a.g(f"/contacts/{body['id']}"), headers=a.headers, json=refused
        )
        assert response.status_code == 422, refused

    changed = await client.patch(
        a.g(f"/contacts/{body['id']}"),
        headers=a.headers,
        json={
            "name": "Lakeside Lodge & Gardens",
            "phones": [
                {"label": "Mobile", "value": "555 0100"},
                {"label": "Office", "value": "555 0101"},
            ],
            "websites": [{"value": "https://lakeside.example/" + "a" * 1500}],
        },
    )
    assert changed.status_code == 200, changed.text
    read = await client.get(a.g(f"/contacts/{body['id']}"), headers=a.headers)
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "Lakeside Lodge & Gardens"
    assert [p["value"] for p in read.json()["phones"]] == ["555 0100", "555 0101"]
    assert read.json()["emails"] == body["emails"]
    assert len(read.json()["websites"][0]["value"]) == 1525

    # A list names each person's organization, read for the page at once.
    person = await client.post(
        a.g("/contacts/"),
        headers=a.headers,
        json={"name": "Ada", "initiative_id": a.initiative.id},
    )
    assert person.status_code == 201, person.text
    linked = await client.post(
        a.g("/relationships/"),
        headers=a.headers,
        json={
            "source": {"type": "contact", "id": person.json()["id"]},
            "relationship_type": "part_of",
            "target": {"type": "contact", "id": body["id"]},
        },
    )
    assert linked.status_code == 201, linked.text
    listed = await client.get(
        a.g("/contacts/"), headers=a.headers, params={"initiative_id": a.initiative.id}
    )
    assert listed.status_code == 200, listed.text
    organizations = {row["name"]: row["organization"] for row in listed.json()["items"]}
    assert organizations == {
        "Ada": {
            "id": body["id"],
            "name": "Lakeside Lodge & Gardens",
            "initiative_id": a.initiative.id,
        },
        "Lakeside Lodge & Gardens": None,
    }

    trashed = await client.delete(a.g(f"/contacts/{body['id']}"), headers=a.headers)
    assert trashed.status_code == 204, trashed.text
    gone = await client.get(a.g(f"/contacts/{body['id']}"), headers=a.headers)
    assert gone.status_code == 404


async def test_a_contact_reaches_whom_it_is_shared_with(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member whose role uses contacts still reads only what is shared with
    them; a guest reads what is shared with them by name, and nothing else."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await grant_role_permission(session, a.initiative, Tool.contact.view_permission)
    private = await create_contact(session, a.initiative, a.user, name="The couple")
    await strip_non_owner_grants(session, private, a.user.id)
    shared = await create_contact(session, a.initiative, a.user, name="The venue")

    assert (
        await client.get(a.g(f"/contacts/{private.id}"), headers=member.headers)
    ).status_code == 403
    listed = await client.get(
        a.g("/contacts/"),
        headers=member.headers,
        params={"initiative_id": a.initiative.id},
    )
    assert [c["id"] for c in listed.json()["items"]] == [shared.id]

    await app_settings_service.ensure_settings_row(session)
    await rules.put(session, "guests_enabled", True)
    await session.commit()
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, shared, user=guest)
    guest_headers = get_auth_headers(guest)

    assert (
        await client.get(a.g(f"/contacts/{shared.id}"), headers=guest_headers)
    ).status_code == 200
    assert (
        await client.get(a.g(f"/contacts/{private.id}"), headers=guest_headers)
    ).status_code == 404


async def test_the_communitys_contacts_are_its_surface_holders_to_make(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A community contact needs the surface and the plug-in, whose install
    owns it. Members read it through the share with everyone; a guest only by
    a grant naming them. A plain member does not edit it, and one given write
    on it does."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    no_plugin = await client.post(
        admin.g("/contacts/"), headers=admin.headers, json={"name": "Bloom & Co"}
    )
    assert no_plugin.status_code == 403
    assert no_plugin.json()["detail"] == ContactMessages.PLUGIN_REQUIRED

    plugin = await _install(session, admin)
    not_theirs = await client.post(
        member.g("/contacts/"), headers=member.headers, json={"name": "Bloom & Co"}
    )
    assert not_theirs.status_code == 403
    assert not_theirs.json()["detail"] == "COMMUNITY_ADMIN_REQUIRED"

    made = await client.post(
        admin.g("/contacts/"),
        headers=admin.headers,
        json={"name": "Bloom & Co", "is_organization": True},
    )
    assert made.status_code == 201, made.text
    contact_id = made.json()["id"]
    assert made.json()["initiative_id"] is None
    # The install owns it, and the default sharing reads as the whole
    # community.
    assert await _sharing(session, admin.guild.id, contact_id) == {
        (plugin.id, None, "owner", False, None),
        (None, None, "read", True, None),
    }

    read = await client.get(member.g(f"/contacts/{contact_id}"), headers=member.headers)
    assert read.status_code == 200, read.text
    assert read.json()["can"]["edit"] is False
    refused = await client.patch(
        member.g(f"/contacts/{contact_id}"),
        headers=member.headers,
        json={"name": "Mine now"},
    )
    assert refused.status_code == 403
    assert refused.json() == Tool.contact.write_required().body

    contact = await session.get(Contact, contact_id)
    await create_resource_grant(
        session, contact, level=ResourceAccessLevel.write, user=member.user
    )
    edited = await client.patch(
        member.g(f"/contacts/{contact_id}"),
        headers=member.headers,
        json={"phones": [{"label": "Shop", "value": "555 0199"}]},
    )
    assert edited.status_code == 200, edited.text

    await app_settings_service.ensure_settings_row(session)
    await rules.put(session, "guests_enabled", True)
    await session.commit()
    guest = await create_guest(session, admin.guild)
    assert (
        await client.get(
            admin.g(f"/contacts/{contact_id}"), headers=get_auth_headers(guest)
        )
    ).status_code == 403
    await create_resource_grant(session, contact, user=guest)
    assert (
        await client.get(
            admin.g(f"/contacts/{contact_id}"), headers=get_auth_headers(guest)
        )
    ).status_code == 200


async def test_an_installed_plugin_makes_a_community_contact(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """On a token not narrowed to one initiative, as a person makes one: held
    by the community contacts plug-in's install and shared with every member,
    with the plug-in as its author. Not on a narrowed token, and not without
    the community contacts plug-in."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["contacts:write"]
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=installed.guild)
    url = guild_url(installed.guild.id, "/contacts/")
    headers = install_headers(installed, ["contacts:write"])

    no_plugin = await client.post(url, headers=headers, json={"name": "Bloom & Co"})
    assert no_plugin.status_code == 403
    assert no_plugin.json()["detail"] == ContactMessages.PLUGIN_REQUIRED

    holder = await _install(session, installed.seat)
    narrowed = await client.post(
        url,
        headers=install_headers(
            installed, ["contacts:write"], initiative_id=installed.placed.id
        ),
        json={"name": "Bloom & Co"},
    )
    assert narrowed.status_code == 403
    assert narrowed.json()["detail"] == ContactMessages.PLUGIN_INITIATIVE_REQUIRED

    made = await client.post(
        url, headers=headers, json={"name": "Bloom & Co", "is_organization": True}
    )
    assert made.status_code == 201, made.text
    contact_id = made.json()["id"]
    assert made.json()["initiative_id"] is None
    assert await _sharing(session, installed.guild.id, contact_id) == {
        (holder.id, None, "owner", False, None),
        (None, None, "read", True, None),
    }
    contact = await session.get(Contact, contact_id)
    assert contact is not None
    assert (contact.created_by, contact.created_by_kind) == (
        installed.plugin.id,
        ActorKind.plugin,
    )

    read = await client.get(member.g(f"/contacts/{contact_id}"), headers=member.headers)
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "Bloom & Co"


async def test_initiative_work_links_to_a_community_contact(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A task links to the community's contact across the initiative line,
    and a reader who can open the task sees the link from either end."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _install(session, a)
    made = await client.post(
        a.g("/contacts/"), headers=a.headers, json={"name": "Bloom & Co"}
    )
    contact_id = made.json()["id"]
    task = await create_task(session, a.project, title="Pay the florist's deposit")

    linked = await client.post(
        a.g("/relationships/"),
        headers=a.headers,
        json={
            "source": {"type": "task", "id": task.id},
            "relationship_type": "related_to",
            "target": {"type": "contact", "id": contact_id},
        },
    )
    assert linked.status_code == 201, linked.text

    from_task = await client.get(
        a.g("/relationships/"), headers=a.headers, params={"entity": f"task:{task.id}"}
    )
    assert [(e["other"]["type"], e["other"]["id"]) for e in from_task.json()] == [
        ("contact", contact_id)
    ]
    from_contact = await client.get(
        a.g("/relationships/"),
        headers=a.headers,
        params={"entity": f"contact:{contact_id}"},
    )
    assert from_contact.status_code == 200, from_contact.text
    assert [(e["other"]["type"], e["other"]["id"]) for e in from_contact.json()] == [
        ("task", task.id)
    ]


async def test_a_contact_moves_into_the_communitys_contacts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """It goes as a new community contact is made: owned by the plug-in's
    install and shared with everyone, its initiative's values left behind.
    Not out of an initiative that keeps its content in, and only once."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _install(session, a)
    contact = await create_contact(session, a.initiative, a.user, name="Bloom & Co")
    order = await create_property_definition(session, a.initiative, name="Order")
    await create_property_value(session, contact, order, value_text="Peonies")

    a.initiative.keep_content_in = True
    session.add(a.initiative)
    await session.commit()
    kept = await client.post(a.g(f"/contacts/{contact.id}/move"), headers=a.headers)
    assert kept.status_code == 403
    assert kept.json()["detail"] == InitiativeMessages.CONTENT_KEPT_IN

    a.initiative.keep_content_in = False
    session.add(a.initiative)
    await session.commit()
    moved = await client.post(a.g(f"/contacts/{contact.id}/move"), headers=a.headers)
    assert moved.status_code == 200, moved.text
    assert moved.json()["initiative_id"] is None
    assert moved.json()["properties"] == []
    assert await _sharing(session, a.guild.id, contact.id) == {
        (plugin.id, None, "owner", False, None),
        (None, None, "read", True, None),
    }
    listed = await client.get(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
    assert listed.json()["artifacts"] == [{"type": "contact", "id": contact.id}]

    again = await client.post(a.g(f"/contacts/{contact.id}/move"), headers=a.headers)
    assert again.status_code == 400
    assert again.json()["detail"] == ContactMessages.ALREADY_IN_COMMUNITY


async def test_contacts_go_out_as_a_spreadsheet_and_come_back_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One row a contact, each phone a pair of columns, several tags or
    choices in one cell one a line, and metadata headed as metadata, so one
    named ``Name`` is not the contact's name. Imported into another
    initiative with the columns its preview reads, it comes back as it went
    out — details and labels, type, organization, tags and metadata — and a
    row whose email is not one, or whose tag is too long to be one, is left
    out and named."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    other = await create_initiative(session, a.guild, a.user)
    venue = await create_tag(session, a.guild, name="Venue")
    food = await create_tag(session, a.guild, name="Food, drinks")
    meals = [
        {"value": "brunch", "label": "Brunch"},
        {"value": "dinner", "label": "Dinner, late"},
    ]
    meal = await create_property_definition(
        session,
        a.initiative,
        name="Name",
        type=MetadataType.multi_select,
        options=meals,
    )
    await create_property_definition(
        session, other, name="Name", type=MetadataType.multi_select, options=meals
    )
    lodge = await client.post(
        a.g("/contacts/"),
        headers=a.headers,
        json={
            "name": "Lakeside Lodge",
            "is_organization": True,
            "initiative_id": a.initiative.id,
        },
    )
    priya = await client.post(
        a.g("/contacts/"),
        headers=a.headers,
        json={
            "name": "Priya Shah",
            "initiative_id": a.initiative.id,
            "emails": [{"label": "Work", "value": "priya@lakeside.example"}],
            "phones": [
                {"label": "Mobile", "value": "+44 7700 900123"},
                {"label": "Office", "value": "020 7946 0000"},
            ],
            "tag_ids": [venue.id, food.id],
            "properties": [{"property_id": meal.id, "value": ["brunch", "dinner"]}],
        },
    )
    linked = await client.post(
        a.g("/relationships/"),
        headers=a.headers,
        json={
            "source": {"type": "contact", "id": priya.json()["id"]},
            "relationship_type": "part_of",
            "target": {"type": "contact", "id": lodge.json()["id"]},
        },
    )
    assert linked.status_code == 201, linked.text

    async def export(ids: list[int]) -> list[list[str]]:
        response = await client.get(
            a.g("/exports/contact"),
            headers=a.headers,
            params={"ids": ids, "format": "csv"},
        )
        assert response.status_code == 200, response.text
        return list(csv.reader(io.StringIO(response.text.removeprefix("\ufeff"))))

    sheet = await export([priya.json()["id"], lodge.json()["id"]])
    assert sheet == [
        [
            "Name",
            "Type",
            "Email 1",
            "Email 1 label",
            "Phone 1",
            "Phone 1 label",
            "Phone 2",
            "Phone 2 label",
            "Organization",
            "Tags",
            "Metadata: Name",
        ],
        [
            "Priya Shah",
            "Person",
            "priya@lakeside.example",
            "Work",
            "'+44 7700 900123",
            "Mobile",
            "020 7946 0000",
            "Office",
            "Lakeside Lodge",
            "Food, drinks\nVenue",
            "Brunch\nDinner, late",
        ],
        ["Lakeside Lodge", "Organization", "", "", "", "", "", "", "", "", ""],
    ]

    rows = io.StringIO()
    csv.writer(rows).writerows(
        [
            *sheet,
            ["Bad Address", "Person", "not an email", "", "", "", "", "", "", "", ""],
            ["Long Tag", "Person", "", "", "", "", "", "", "", "x" * 150, ""],
        ]
    )
    preview = await client.post(
        a.g("/imports/contacts/preview"),
        headers={**a.headers, "Content-Type": "text/plain"},
        params={"initiative_id": other.id},
        content=rows.getvalue(),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 4
    imported = await client.post(
        a.g("/imports/contacts"),
        headers=a.headers,
        json={
            "initiative_id": other.id,
            "content": rows.getvalue(),
            "columns": preview.json()["columns"],
        },
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()["result"]
    assert result["created"]["contacts"] == 2
    assert result["failed_rows"] == [
        {"row": 4, "field": "emails"},
        {"row": 5, "field": "tags"},
    ]

    await route_session_to_guild(session, a.guild.id)
    made = dict(
        (
            await session.exec(
                select(Contact.name, Contact.id).where(
                    Contact.initiative_id == other.id
                )
            )
        ).all()
    )
    assert set(made) == {"Priya Shah", "Lakeside Lodge"}
    assert await export([made["Priya Shah"], made["Lakeside Lodge"]]) == sheet
