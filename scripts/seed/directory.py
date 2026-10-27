"""The community directory, and the small communities that exist to fill it.

Communities 1 and 2 stay invite-only, so the unlisted case is still there to
look at: no categories, no 18+ answer, no card. Community 3 is listed, which
puts one community with real content behind a card — the superuser is already
in it, so it shows the already-a-member state next to the joinable ones.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.schema_provisioning import provision_guild
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, CommunityCategory
from app.models.platform.user import User
from app.models.tenant.initiative import InitiativeJoinPolicy
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.task import TaskPriority, TaskStatusCategory

from seed import guilds, initiatives, projects
from seed.common import Community

#: Enough to be a believable card — a name, a description, artwork, its
#: shelves, and a roster whose size shows on it — and enough behind the card
#: to be worth arriving at. The first initiative is everybody's; only the
#: admin is in the second, so everyone else meets it the way a visitor does,
#: and the two carry different join policies so "Join" and "Request to join"
#: are both reachable. One community auto-joins its arrivals. The music shelf
#: is deliberately left empty, so "nothing on this shelf" is reachable too.
DIRECTORY: list[dict] = [
    {
        "name": "The Cartographers' Table",
        "description": "Hand-drawn maps for tables that want one. Weekly critique "
        "thread, monthly swap.",
        "categories": [CommunityCategory.art, CommunityCategory.ttrpg],
        "admin": "Elara Moonwhisper",
        "members": ["Thorn Ironforge", "Vex Shadowstep"],
        "photo": "book-pages",
        "initiatives": [
            {
                "name": "Map Swap",
                "description": "The running map exchange and its critique threads.",
                "color": "#0891b2",
                "join_policy": InitiativeJoinPolicy.open,
            },
            {
                "name": "Cartography Guild Critique",
                "description": "Line-by-line feedback on a map before it goes out.",
                "color": "#155e75",
                "join_policy": InitiativeJoinPolicy.request,
            },
        ],
        "project": {
            "name": "Autumn Swap",
            "icon": "\U0001f5fa\ufe0f",
            "description": "Everything owed for this round of the exchange.",
            "tasks": [
                {
                    "title": "Collect this round's submissions",
                    "category": TaskStatusCategory.in_progress,
                    "priority": TaskPriority.high,
                    "due_days": 4,
                },
                {
                    "title": "Pair each map with a critic",
                    "category": TaskStatusCategory.todo,
                    "priority": TaskPriority.medium,
                },
                {
                    "title": "Post the summer round-up",
                    "category": TaskStatusCategory.done,
                    "priority": TaskPriority.low,
                },
            ],
        },
    },
    {
        "name": "Midnight Homebrew",
        "description": "Homebrew rules, monsters, and subclasses — brought here to be "
        "broken before a table finds the cracks.",
        "categories": [CommunityCategory.ttrpg, CommunityCategory.writing],
        "admin": "Dungeon Master",
        "members": [
            "Seraphina Dawnlight",
            "Kael Windrunner",
            "Aurelia Brightshield",
            "Thorn Ironforge",
        ],
        "photo": "theater",
        "initiatives": [
            {
                "name": "Playtest Queue",
                "description": "Everything waiting on a table to try it.",
                "color": "#7c3aed",
                "join_policy": InitiativeJoinPolicy.open,
                "auto_join": True,
            },
            {
                "name": "Table Scars",
                "description": "The rules that broke, and what broke them.",
                "color": "#a21caf",
                "join_policy": InitiativeJoinPolicy.request,
            },
        ],
        "project": {
            "name": "Subclass Review",
            "icon": "\U0001f9ea",
            "description": "The subclasses currently in front of a table.",
            "tasks": [
                {
                    "title": "Break the Tidecaller's capstone",
                    "category": TaskStatusCategory.in_progress,
                    "priority": TaskPriority.urgent,
                    "due_days": 2,
                },
                {
                    "title": "Second table for the Grave Warden",
                    "category": TaskStatusCategory.todo,
                    "priority": TaskPriority.medium,
                },
            ],
        },
    },
    {
        "name": "Sunday Session Zero",
        "description": "Pick-up games for people without a regular table. Say what you "
        "play, find four others.",
        "categories": [CommunityCategory.gaming, CommunityCategory.social],
        "admin": "Finley Goldtongue",
        "members": [
            "Vex Shadowstep",
            "Kael Windrunner",
            "Platform Member",
            "Platform Support",
        ],
        "photo": "breakfast-club",
        "initiatives": [
            {
                "name": "This Month's Tables",
                "description": "Who is running what, and which seats are open.",
                "color": "#ea580c",
                "join_policy": InitiativeJoinPolicy.open,
            },
            {
                "name": "Table Hosts",
                "description": "For the people running a table, not sitting at one.",
                "color": "#9a3412",
                "join_policy": InitiativeJoinPolicy.request,
            },
        ],
        "project": {
            "name": "October Seats",
            "icon": "\U0001f3b2",
            "description": "Seats open, seats taken, and who is running what.",
            "tasks": [
                {
                    "title": "Confirm the two Saturday hosts",
                    "category": TaskStatusCategory.todo,
                    "priority": TaskPriority.high,
                    "due_days": 6,
                },
                {
                    "title": "Close the waitlist for the Friday table",
                    "category": TaskStatusCategory.backlog,
                    "priority": TaskPriority.low,
                },
            ],
        },
    },
    {
        "name": "Pixel & Palette",
        "description": "Digital art, tooling, and the pipelines behind them.",
        "categories": [CommunityCategory.art, CommunityCategory.technology],
        "admin": "Vex Shadowstep",
        "members": ["Elara Moonwhisper", "Seraphina Dawnlight"],
        "photo": "classroom",
        "initiatives": [
            {
                "name": "Studio",
                "description": "Works in progress and the tools that made them.",
                "color": "#db2777",
                "join_policy": InitiativeJoinPolicy.request,
            },
            {
                "name": "Tooling",
                "description": "The scripts and brushes the studio runs on.",
                "color": "#be185d",
                "join_policy": InitiativeJoinPolicy.open,
            },
        ],
        "project": {
            "name": "Brush Pack v3",
            "icon": "\U0001f3a8",
            "description": "The next pack, and what is still missing from it.",
            "tasks": [
                {
                    "title": "Redraw the inking set at 2x",
                    "category": TaskStatusCategory.in_progress,
                    "priority": TaskPriority.medium,
                },
                {
                    "title": "Licence file for the pack",
                    "category": TaskStatusCategory.todo,
                    "priority": TaskPriority.low,
                },
            ],
        },
    },
    {
        "name": "Dawn Patrol",
        "description": "An early-morning running club. Routes, times, and a standing "
        "excuse to be outside before work.",
        "categories": [CommunityCategory.sports, CommunityCategory.health],
        "admin": "Seraphina Dawnlight",
        "members": [
            "Thorn Ironforge",
            "Aurelia Brightshield",
            "Finley Goldtongue",
            "Dungeon Master",
            "Kael Windrunner",
        ],
        "photo": "street",
        "initiatives": [
            {
                "name": "Season Plan",
                "description": "The training block everyone is on.",
                "color": "#16a34a",
                "join_policy": InitiativeJoinPolicy.open,
            },
            {
                "name": "Race Day",
                "description": "The half-marathon block, for whoever is signed up.",
                "color": "#15803d",
                "join_policy": InitiativeJoinPolicy.request,
            },
        ],
        "project": {
            "name": "Spring Block",
            "icon": "\U0001f3c3",
            "description": "Twelve weeks, and who is holding which week.",
            "tasks": [
                {
                    "title": "Publish the week 6 route",
                    "category": TaskStatusCategory.todo,
                    "priority": TaskPriority.medium,
                    "due_days": 3,
                },
                {
                    "title": "Find a wet-weather alternative to the river loop",
                    "category": TaskStatusCategory.backlog,
                    "priority": TaskPriority.low,
                },
                {
                    "title": "Sort out the winter timing sheet",
                    "category": TaskStatusCategory.done,
                    "priority": TaskPriority.medium,
                },
            ],
        },
    },
    {
        "name": "Founders' Roundtable",
        "description": "Small-company operators comparing notes. No pitches, no recruiting.",
        "categories": [CommunityCategory.business, CommunityCategory.education],
        "admin": "Thorn Ironforge",
        "members": ["Platform Operator", "Platform Moderator"],
        "photo": "campus",
        "initiatives": [
            {
                "name": "Roundtable",
                "description": "The standing agenda and its notes.",
                "color": "#0f766e",
                "join_policy": InitiativeJoinPolicy.request,
            },
            {
                "name": "Hiring Notes",
                "description": "What worked, what did not, and what it cost.",
                "color": "#134e4a",
                "join_policy": InitiativeJoinPolicy.private,
            },
        ],
        "project": {
            "name": "Q1 Agenda",
            "icon": "\U0001f4c8",
            "description": "What each month's roundtable is about.",
            "tasks": [
                {
                    "title": "Pick February's topic",
                    "category": TaskStatusCategory.todo,
                    "priority": TaskPriority.high,
                    "due_days": 9,
                },
                {
                    "title": "Write up January's notes",
                    "category": TaskStatusCategory.in_progress,
                    "priority": TaskPriority.medium,
                },
            ],
        },
    },
]


async def seed(
    session: AsyncSession, ids: dict[str, list], users: dict[str, User], listed: Guild
) -> None:
    await set_rls_context(
        session, Unattributed()
    )  # shared/public tables — no community routing
    await guilds.enable_directory(session)
    await guilds.list_in_directory(
        session, listed, categories=[CommunityCategory.ttrpg, CommunityCategory.social]
    )
    await session.commit()
    for spec in DIRECTORY:
        print(f"  Listing community: {spec['name']}")
        await _community(session, ids, users, spec)


async def _community(
    session: AsyncSession, ids: dict[str, list], users: dict[str, User], spec: dict
) -> None:
    """A listed community, made in the order the others are. A listing is
    fixed at "no adult content" and "handles, not real names" — the two check
    constraints on a listed community leave no other answer."""
    guild = await guilds.create_guild(
        session,
        ids,
        name=spec["name"],
        description=spec["description"],
        creator=users[spec["admin"]],
    )
    await guilds.list_in_directory(session, guild, categories=spec["categories"])
    await guilds.set_images(session, guild, spec["photo"])
    await session.commit()
    guilds.expunge_guild_scoped(session)
    await provision_guild(guild.id)
    await guilds.add_members(session, guild, [users[n] for n in spec["members"]])
    await set_rls_context(session, SystemGuild(guild.id))
    c = Community(key=spec["name"], session=session, ids=ids, users=users, guild=guild)
    first, second = spec["initiatives"]
    await initiatives.create_initiative(
        c, "main", {**first, "pm": spec["admin"], "members": spec["members"]}
    )
    await initiatives.create_initiative(c, "second", {**second, "pm": spec["admin"]})
    await projects.create_project(
        c,
        {
            **spec["project"],
            "initiative": "main",
            "owner": spec["admin"],
            "general": ResourceAccessLevel.write,
        },
    )
    await session.commit()
    guilds.expunge_guild_scoped(session)
    await set_rls_context(session, Unattributed())
