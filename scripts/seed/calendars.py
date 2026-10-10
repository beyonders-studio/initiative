"""Calendars and their events, with who is coming and what each is about."""

from __future__ import annotations

from datetime import timedelta

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR, Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAnswer,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.tenant import relationships as relationships_service

from seed.common import NOW, Community, share, tag

#: Each event. ``recurrence`` is RRULE lines repeating on the start's own
#: weekday, ``attendees`` are ``(person, RSVP)``, and ``files`` are
#: attached by the creator.
EVENTS: dict[str, list[dict]] = {
    "primary": [
        {
            "title": "Session 12: Into the Amber Temple",
            "initiative": "strahd",
            "description": "The party finally reaches the Amber Temple to bargain with "
            "the Dark Powers.",
            "location": "Tabletop @ DM's house",
            "start_at": NOW + timedelta(days=2, hours=2),
            "end_at": NOW + timedelta(days=2, hours=6),
            "created_by": "Dungeon Master",
            "attendees": [
                ("Dungeon Master", RSVPStatus.accepted),
                ("Thorn Ironforge", RSVPStatus.accepted),
                ("Elara Moonwhisper", RSVPStatus.accepted),
                ("Vex Shadowstep", RSVPStatus.tentative),
                ("Seraphina Dawnlight", RSVPStatus.declined),
                ("Platform Operator", RSVPStatus.pending),
            ],
            "tags": ["quest", "lore"],
            "files": ["NPC Roster: Curse of Strahd"],
        },
        {
            "title": "Weekly Strahd Session",
            "initiative": "strahd",
            "description": "Standing campaign night.",
            "location": "Roll20",
            "start_at": NOW + timedelta(days=7, hours=1),
            "end_at": NOW + timedelta(days=7, hours=5),
            "created_by": "Dungeon Master",
            "recurrence": "RRULE:FREQ=WEEKLY;COUNT=12",
            "attendees": [
                ("Dungeon Master", RSVPStatus.accepted),
                ("Thorn Ironforge", RSVPStatus.accepted),
                ("Elara Moonwhisper", RSVPStatus.accepted),
            ],
        },
        {
            "title": "Player Off-Site Retrospective",
            "initiative": "strahd",
            "description": "All-day session: replay session 8-11 with snacks.",
            "location": "Cabin in the woods",
            "start_at": NOW + timedelta(days=14),
            "end_at": NOW + timedelta(days=14),
            "all_day": True,
            "created_by": "Dungeon Master",
            "tags": ["roleplay"],
        },
        {
            "title": "Session 11: Vallaki Festival",
            "initiative": "strahd",
            "description": "Wrapped up: the Festival of the Blazing Sun.",
            "location": "Tabletop @ DM's house",
            "start_at": NOW - timedelta(days=5, hours=22),
            "end_at": NOW - timedelta(days=5, hours=18),
            "created_by": "Dungeon Master",
            "attendees": [
                ("Dungeon Master", RSVPStatus.accepted),
                ("Thorn Ironforge", RSVPStatus.accepted),
            ],
        },
        {
            "title": "Session: Cragmaw Hideout",
            "initiative": "lmop",
            "description": "Rescue Gundren Rockseeker from the goblins.",
            "location": "Roll20",
            "start_at": NOW + timedelta(days=4, hours=3),
            "end_at": NOW + timedelta(days=4, hours=7),
            "created_by": "Admin User",
            "attendees": [
                ("Admin User", RSVPStatus.accepted),
                ("Dungeon Master", RSVPStatus.tentative),
            ],
            "tags": ["combat", "quest"],
        },
        {
            "title": "Prep: Wave Echo Cave maps",
            "initiative": "lmop",
            "description": "DM-only prep slot for the finale dungeon.",
            "start_at": NOW + timedelta(days=10, hours=20),
            "end_at": NOW + timedelta(days=10, hours=22),
            "created_by": "Admin User",
        },
    ],
    "starforge": [
        {
            "title": "Session 5: Colony Landfall",
            "initiative": "starfall",
            "description": "The fleet arrives at Kepler-442b.",
            "location": "Discord voice",
            "start_at": NOW + timedelta(days=3, hours=1),
            "end_at": NOW + timedelta(days=3, hours=4),
            "created_by": "Admin User",
            "attendees": [
                ("Admin User", RSVPStatus.accepted),
                ("Finley Goldtongue", RSVPStatus.accepted),
                ("Kael Windrunner", RSVPStatus.accepted),
                ("Aurelia Brightshield", RSVPStatus.tentative),
                ("Vex Shadowstep", RSVPStatus.declined),
                ("Elara Moonwhisper", RSVPStatus.pending),
            ],
            "tags": ["combat"],
            "files": ["Setting Bible: The Exodus Protocol"],
        },
        {
            "title": "Bi-weekly Starfall Session",
            "initiative": "starfall",
            "description": "Standing campaign night.",
            "start_at": NOW + timedelta(days=10, hours=2),
            "end_at": NOW + timedelta(days=10, hours=5),
            "created_by": "Admin User",
            "recurrence": "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=8",
            "attendees": [
                ("Admin User", RSVPStatus.accepted),
                ("Kael Windrunner", RSVPStatus.accepted),
            ],
        },
        {
            "title": "Session 4: Distress Signal",
            "initiative": "starfall",
            "description": "Past session — investigated Sector 7G.",
            "start_at": NOW - timedelta(days=10, hours=23),
            "end_at": NOW - timedelta(days=10, hours=20),
            "created_by": "Admin User",
        },
        {
            "title": "Worldbuilding Day",
            "initiative": "starfall",
            "description": "All-day workshop with the players for the post-landfall arc.",
            "start_at": NOW + timedelta(days=21),
            "end_at": NOW + timedelta(days=21),
            "all_day": True,
            "created_by": "Admin User",
        },
        {
            "title": "One-shot: Smuggler's Run",
            "initiative": "fringe",
            "description": "Heist night.",
            "location": "Discord voice",
            "start_at": NOW + timedelta(days=5, hours=3),
            "end_at": NOW + timedelta(days=5, hours=7),
            "created_by": "Finley Goldtongue",
            "attendees": [
                ("Finley Goldtongue", RSVPStatus.accepted),
                ("Vex Shadowstep", RSVPStatus.accepted),
                ("Kael Windrunner", RSVPStatus.pending),
            ],
            "files": ["One-Shot: Smuggler's Run Briefing"],
        },
    ],
    "tides": [
        {
            "title": "Session 7: The Leviathan's Maw",
            "initiative": "crimson",
            "description": "Descent into the underwater grotto.",
            "location": "Captain's quarters (Roll20)",
            "start_at": NOW + timedelta(days=1, hours=2),
            "end_at": NOW + timedelta(days=1, hours=6),
            "created_by": "Finley Goldtongue",
            "attendees": [
                ("Finley Goldtongue", RSVPStatus.accepted),
                ("Thorn Ironforge", RSVPStatus.accepted),
                ("Kael Windrunner", RSVPStatus.accepted),
                ("Aurelia Brightshield", RSVPStatus.accepted),
                ("Seraphina Dawnlight", RSVPStatus.tentative),
                ("Platform Owner", RSVPStatus.declined),
            ],
            "files": ["The Shattered Seas: World Guide"],
        },
        {
            "title": "Voyage to the Abyssal Trench",
            "initiative": "crimson",
            "description": "Three in-game days of open-sea travel, storms, and random encounters.",
            "location": "The Crimson Maiden",
            "start_at": NOW + timedelta(days=8),
            "end_at": NOW + timedelta(days=10, hours=6),
            "created_by": "Finley Goldtongue",
            "attendees": [
                ("Finley Goldtongue", RSVPStatus.accepted),
                ("Kael Windrunner", RSVPStatus.accepted),
                ("Aurelia Brightshield", RSVPStatus.pending),
            ],
            "tags": ["exploration"],
        },
        {
            "title": "Sunday Pirate Night",
            "initiative": "crimson",
            "description": "Weekly campaign session.",
            "start_at": NOW + timedelta(days=6, hours=2),
            "end_at": NOW + timedelta(days=6, hours=5),
            "created_by": "Finley Goldtongue",
            "recurrence": "RRULE:FREQ=WEEKLY",
            "attendees": [
                ("Finley Goldtongue", RSVPStatus.accepted),
                ("Kael Windrunner", RSVPStatus.accepted),
            ],
        },
        {
            "title": "Session 6: The Ironclad Falls",
            "initiative": "crimson",
            "description": "Past session — sank the HMS Ironclad.",
            "start_at": NOW - timedelta(days=7, hours=22),
            "end_at": NOW - timedelta(days=7, hours=19),
            "created_by": "Finley Goldtongue",
        },
        {
            "title": "Naval Engagement: HMS Vengeance Pursuit",
            "initiative": "navy",
            "description": "Cat-and-mouse with Admiral Blackwood's flagship.",
            "start_at": NOW + timedelta(days=4, hours=3),
            "end_at": NOW + timedelta(days=4, hours=6),
            "created_by": "Dungeon Master",
            "attendees": [
                ("Dungeon Master", RSVPStatus.accepted),
                ("Finley Goldtongue", RSVPStatus.accepted),
                ("Thorn Ironforge", RSVPStatus.pending),
            ],
            "files": ["Intelligence Report: Admiral Blackwood"],
        },
        {
            "title": "Shore Leave (all-day)",
            "initiative": "navy",
            "description": "Crew gets a day in Port Havoc.",
            "start_at": NOW + timedelta(days=12),
            "end_at": NOW + timedelta(days=12),
            "all_day": True,
            "created_by": "Dungeon Master",
        },
    ],
}


async def seed(c: Community) -> None:
    """Events live inside a calendar: one "Default Calendar" per initiative,
    in the initiative's colour so it renders intentionally, shared as creator
    owner + all-initiative-members read."""
    calendars: dict[str, Calendar] = {}
    for d in EVENTS[c.key]:
        creator = c.users[d["created_by"]]
        calendar = calendars.get(d["initiative"])
        if calendar is None:
            initiative = c.initiatives[d["initiative"]]
            calendar = Calendar(
                initiative_id=initiative.id,
                name="Default Calendar",
                color=initiative.color or DEFAULT_CALENDAR_COLOR,
                created_by=creator.id,
            )
            c.session.add(calendar)
            await c.session.flush()
            calendars[d["initiative"]] = calendar
            c.ids["calendars"].append(calendar.id)
            share(c, Tool.calendar, calendar, creator, general=ResourceAccessLevel.read)
        event = CalendarEvent(
            calendar_id=calendar.id,
            title=d["title"],
            description=d.get("description"),
            location=d.get("location"),
            start_at=d["start_at"],
            end_at=d["end_at"],
            all_day=d.get("all_day", False),
            recurrence=d.get("recurrence"),
            created_by=creator.id,
        )
        c.session.add(event)
        await c.session.flush()
        c.events[event.title] = event
        c.ids["calendar_events"].append(event.id)
        for name, rsvp in d.get("attendees", ()):
            c.session.add(
                CalendarEventAttendee(
                    calendar_event_id=event.id, user_id=c.users[name].id
                )
            )
            if rsvp is not RSVPStatus.pending:
                c.session.add(
                    CalendarEventAnswer(
                        calendar_event_id=event.id,
                        user_id=c.users[name].id,
                        rsvp_status=rsvp,
                    )
                )
            c.ids["calendar_event_attendees"].append((event.id, name))
        tag(c, event, d.get("tags", ()))
        for title in d.get("files", ()):
            await relationships_service.create(
                c.session,
                source=relationships_service.Endpoint(
                    SearchEntityType.calendar_event, event.id
                ),
                relationship_type=RelationshipType.attached,
                target=relationships_service.Endpoint(
                    SearchEntityType.file, c.files[title].id
                ),
                created_by=creator.id,
            )
        await c.session.flush()
