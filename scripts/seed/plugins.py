"""The built-in plug-ins a community installs from the marketplace, and what
it keeps in them: Community calendar's events and Community contacts' address
book. Installed through the service the marketplace's install button calls."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.tenant._mixins import ActorKind
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.contact import Contact
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.tenant.resource_grant import initiative_readable
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace.installs import resolve_listing_install
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import relationships as relationships_service
from seed.common import NOW, Community

#: Who installs the plug-ins: a community admin, as the marketplace requires.
INSTALLER: dict[str, str] = {"primary": "Guildmaster Aldric"}


def _evening(days: int, hour: int) -> datetime:
    """``hour`` o'clock (UTC) ``days`` from today, so an evening event starts
    on the hour and ends the same day."""
    return (NOW + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


#: Community calendar's events, as ``seed.calendars`` writes an initiative's.
EVENTS: dict[str, list[dict]] = {
    "primary": [
        {
            "title": "Open game night",
            "description": "Bring a character or borrow one. Tables for every system.",
            "location": "The Gilded Dragon",
            "start_at": _evening(3, 18),
            "end_at": _evening(3, 22),
            "recurrence": "RRULE:FREQ=WEEKLY;COUNT=10",
        },
        {
            "title": "Painting night: minis for the Amber Temple",
            "location": "Copper Kettle Café",
            "start_at": _evening(5, 18),
            "end_at": _evening(5, 21),
        },
        {
            "title": "Community meetup",
            "description": "Plans for next season, and the convention table.",
            "location": "Harbor Hall",
            "start_at": _evening(9, 17),
            "end_at": _evening(9, 19),
        },
        {
            "title": "Session zero for the new campaign",
            "location": "Roll20",
            "start_at": _evening(12, 19),
            "end_at": _evening(12, 22),
        },
        {
            "title": "Tidecon",
            "location": "Harbor Hall",
            "start_at": _evening(16, 0),
            "end_at": _evening(18, 0),
            "all_day": True,
        },
    ],
}

#: Community contacts' address book. ``part_of`` names the organization a
#: person works for, as the contact page links it.
CONTACTS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "The Gilded Dragon",
            "is_organization": True,
            "emails": [{"label": "work", "value": "tables@gildeddragon.example"}],
            "phones": [{"label": "work", "value": "(555) 014-2290"}],
            "addresses": [
                {"label": "work", "value": "42 Lantern Row\nPort Havoc, OR 97000"}
            ],
            "websites": [{"label": "work", "value": "https://gildeddragon.example"}],
        },
        {
            "name": "Tessa Ravenwood",
            "part_of": "The Gilded Dragon",
            "emails": [{"label": "work", "value": "tessa@gildeddragon.example"}],
            "phones": [{"label": "mobile", "value": "(555) 014-7781"}],
        },
        {
            "name": "Copper Kettle Café",
            "is_organization": True,
            "emails": [{"label": "work", "value": "hello@copperkettle.example"}],
            "phones": [{"label": "work", "value": "(555) 019-3304"}],
            "addresses": [
                {"label": "work", "value": "7 Mill Street\nPort Havoc, OR 97000"}
            ],
        },
        {
            "name": "Harbor Hall",
            "is_organization": True,
            "emails": [{"label": "work", "value": "bookings@harborhall.example"}],
            "phones": [{"label": "work", "value": "(555) 017-6600"}],
            "addresses": [
                {"label": "work", "value": "1 Quay Road\nPort Havoc, OR 97000"}
            ],
            "websites": [{"label": "work", "value": "https://harborhall.example"}],
        },
        {
            "name": "Mira Okafor",
            "part_of": "Harbor Hall",
            "emails": [{"label": "work", "value": "mira@harborhall.example"}],
            "phones": [{"label": "work", "value": "(555) 017-6612"}],
        },
        {
            "name": "Anvil Minis",
            "is_organization": True,
            "emails": [{"label": "work", "value": "orders@anvilminis.example"}],
            "websites": [{"label": "work", "value": "https://anvilminis.example"}],
        },
        {
            "name": "Jonah Pike",
            "part_of": "Anvil Minis",
            "emails": [{"label": "work", "value": "jonah@anvilminis.example"}],
            "phones": [{"label": "mobile", "value": "(555) 013-4471"}],
        },
        {
            "name": "Rosalind Thatch",
            "emails": [{"label": "personal", "value": "ros.thatch@mail.example"}],
            "phones": [{"label": "mobile", "value": "(555) 012-9035"}],
        },
    ],
}


async def install(c: Community, public_id: str, installer: str) -> GuildPlugin:
    """Install a plug-in the catalogue ships as ``installer``, one of the
    community's admins, would."""
    admin = c.users[installer]
    found = await catalog_service.get_listing(c.session, public_id)
    assert found is not None, f"{public_id} is not in the catalog"
    listing, version = await resolve_listing_install(
        c.session, found.uid, kind="plugin"
    )
    definition = dict(version.definition)
    return await guild_plugins_service.install_plugin(
        c.session,
        listing_uid=listing.uid,
        listing_version=version.version,
        definition=definition,
        guild_id=c.guild.id,
        name=(definition.get("default_name") or listing.name).strip(),
        created_by=admin.id,
        actor_user_id=admin.id,
    )


async def seed(c: Community) -> None:
    """Install Community calendar and fill the calendar it brings, then
    Community contacts and add the address book to it."""
    if c.key not in INSTALLER:
        return
    admin = c.users[INSTALLER[c.key]]

    calendar_install = await install(c, "core.guild-calendar", INSTALLER[c.key])
    [calendar] = await guild_plugins_service.plugin_artifacts(
        c.session, calendar_install
    )
    c.ids["calendars"].append(calendar["id"])
    for d in EVENTS[c.key]:
        event = CalendarEvent(
            calendar_id=calendar["id"],
            title=d["title"],
            description=d.get("description"),
            location=d.get("location"),
            start_at=d["start_at"],
            end_at=d["end_at"],
            all_day=d.get("all_day", False),
            recurrence=d.get("recurrence"),
            created_by=admin.id,
            created_by_kind=ActorKind.member,
        )
        c.session.add(event)
        await c.session.flush()
        c.ids["calendar_events"].append(event.id)

    contacts_install = await install(c, "core.community-contacts", INSTALLER[c.key])
    contacts: dict[str, Contact] = {}
    for d in CONTACTS[c.key]:
        contact = Contact(
            initiative_id=None,
            name=d["name"],
            is_organization=d.get("is_organization", False),
            emails=d.get("emails", []),
            phones=d.get("phones", []),
            addresses=d.get("addresses", []),
            websites=d.get("websites", []),
            created_by=admin.id,
            created_by_kind=ActorKind.member,
        )
        c.session.add(contact)
        await c.session.flush()
        await ownership_service.give_to_install(
            c.session,
            Tool.contact,
            contact,
            install_id=contacts_install.id,
            guild_id=c.guild.id,
            grants=initiative_readable(),
            actor_user_id=admin.id,
        )
        contacts[contact.name] = contact
        c.ids["contacts"].append(contact.id)
        if "part_of" in d:
            await relationships_service.create(
                c.session,
                source=relationships_service.Endpoint(
                    SearchEntityType.contact, contact.id
                ),
                relationship_type=RelationshipType.part_of,
                target=relationships_service.Endpoint(
                    SearchEntityType.contact, contacts[d["part_of"]].id
                ),
                created_by=admin.id,
            )
    await c.session.flush()
