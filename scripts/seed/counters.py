"""Counter groups: hit points, clocks and tallies, kept in the Counters tool
plug-in, which the server lists as one with no registry does and the
community installs from the marketplace and places in the initiatives that
keep them. Its rows are written as the plug-in's routes write them."""

from __future__ import annotations

from types import SimpleNamespace

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import SystemGuild
from app.db.schema_provisioning import provision_community_tools
from app.db.session import set_rls_context
from app.models.tenant._mixins import ActorKind
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.marketplace.tool_plugins import tool_kinds
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant.initiative_tools import write_installed_tools
from app.services.tenant.plugin_tool_rows import column_values, insert, located_kind
from app.testing.tool_plugins import counters_listing, list_counters
from seed.common import Community, share
from seed.guilds import COMMUNITIES
from seed.plugins import install

#: The Counters plug-in's listing.
COUNTERS = counters_listing()["public_id"]

#: Each group, shared the way ``share`` reads it. A counter is ``(name, colour,
#: count, min, max, step, initial count, view mode)``, in position order.
COUNTER_GROUPS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Party Vitals (Strahd)",
            "initiative": "strahd",
            "description": "Combat-relevant counters for the Curse of Strahd party.",
            "created_by": "Dungeon Master",
            "roles": [("strahd", ResourceAccessLevel.write)],
            "counters": [
                ("Thorn HP", "#DC2626", 38, 0, 42, 1, 42, "bar"),
                ("Elara HP", "#3B82F6", 24, 0, 28, 1, 28, "bar"),
                ("Inspiration Pool", "#F59E0B", 2, 0, 5, 1, 0, "number"),
                ("Long Rest Clock", "#7C3AED", 3, 0, 8, 1, 0, "clock"),
            ],
        },
        {
            "name": "Castle Ravenloft Doom Clock",
            "initiative": "strahd",
            "description": "Strahd's awareness of the party. At 8 he comes for them.",
            "created_by": "Dungeon Master",
            "counters": [
                ("Strahd's Awareness", "#991B1B", 4, 0, 8, 1, 0, "clock"),
                ("Holy Symbols Found", "#FBBF24", 2, 0, 3, 1, 0, "number"),
                ("Tarokka Cards Drawn", "#A855F7", 3, 0, 5, 1, 0, "number"),
            ],
        },
        {
            "name": "Phandelver Reputation",
            "initiative": "lmop",
            "description": "Faction standing for the Lost Mine of Phandelver party.",
            "created_by": "Admin User",
            "general": ResourceAccessLevel.read,
            "counters": [
                ("Phandalin Reputation", "#10B981", 3, -5, 10, 1, 0, "number"),
                ("Redbrand Hideout Cleared", "#DC2626", 4, 0, 6, 1, 0, "bar"),
            ],
        },
    ],
    "starforge": [
        {
            "name": "Fleet Status",
            "initiative": "starfall",
            "description": "Ship integrity and resource levels for The Exodus Protocol.",
            "created_by": "Admin User",
            "roles": [("starfall", ResourceAccessLevel.write)],
            "counters": [
                ("Hull Integrity", "#3B82F6", 78, 0, 100, 5, 100, "bar"),
                ("Plasma Reserves", "#F59E0B", 42, 0, 80, 1, 80, "bar"),
                ("Colonists in Cryo", "#10B981", 4870, 0, None, 1, 5000, "number"),
                ("Days to Kepler-442b", "#7C3AED", 6, 0, 8, 1, 8, "clock"),
            ],
        },
        {
            "name": "Krellix Diplomatic Tracker",
            "initiative": "starfall",
            "description": "Relations with the Krellix Dominion.",
            "created_by": "Admin User",
            "general": ResourceAccessLevel.read,
            "counters": [
                ("Treaty Progress", "#0EA5E9", 2, 0, 5, 1, 0, "clock"),
                ("Hostility Score", "#DC2626", 3, 0, 10, 1, 0, "number"),
            ],
        },
        {
            "name": "Heist Crew Funds",
            "initiative": "fringe",
            "description": "Loot stash and expenses for the Smuggler's Run crew.",
            "created_by": "Finley Goldtongue",
            "counters": [
                ("Credits", "#F59E0B", 12500, 0, None, 100, 8000, "number"),
                ("Bribes Spent", "#7F1D1D", 1800, 0, None, 50, 0, "number"),
            ],
        },
    ],
    "tides": [
        {
            "name": "The Crimson Maiden",
            "initiative": "crimson",
            "description": "Ship state for the pirate vessel.",
            "created_by": "Finley Goldtongue",
            "roles": [("crimson", ResourceAccessLevel.write)],
            "counters": [
                ("Hull HP", "#92400E", 87, 0, 120, 1, 120, "bar"),
                ("Sails", "#FBBF24", 4, 0, 4, 1, 4, "number"),
                ("Crew Morale", "#10B981", 6, 0, 10, 1, 7, "bar"),
                ("Rations (days)", "#65A30D", 18, 0, None, 1, 30, "number"),
                ("Storm Brewing", "#1E40AF", 2, 0, 6, 1, 0, "clock"),
            ],
        },
        {
            "name": "Plunder Vault",
            "initiative": "crimson",
            "description": "Treasure recovered toward the Leviathan's Heart.",
            "created_by": "Finley Goldtongue",
            "general": ResourceAccessLevel.write,
            "counters": [
                ("Tidestones Recovered", "#0EA5E9", 1, 0, 3, 1, 0, "bar"),
                ("Gold (doubloons)", "#F59E0B", 4200, 0, None, 100, 0, "number"),
            ],
        },
        {
            "name": "Navy Threat Tracker",
            "initiative": "navy",
            "description": "How close the Imperial Navy is to catching us.",
            "created_by": "Dungeon Master",
            "counters": [
                ("Bounty Level", "#DC2626", 3, 0, 5, 1, 0, "clock"),
                ("Ships of the Line Sunk", "#1E40AF", 2, 0, None, 1, 0, "number"),
            ],
        },
    ],
}


async def list_plugin(session: AsyncSession) -> None:
    """List Counters on the marketplace as a server's owner does where no
    registry brings it: an upload of its listing file, the version the
    upgrade installs."""
    await list_counters(session)
    await session.commit()


async def seed(c: Community) -> None:
    groups = COUNTER_GROUPS[c.key]
    plugin = await install(c, COUNTERS, COMMUNITIES[c.key]["admins"][0])
    await guild_plugins_service.set_placed_initiatives(
        c.session, plugin, {c.initiatives[d["initiative"]].id for d in groups}
    )
    await c.session.commit()
    # Its tables, then its switch and role keys in every initiative, as the
    # install route does once the install commits.
    c.tools = await provision_community_tools(c.guild.id)
    await set_rls_context(c.session, SystemGuild(c.guild.id))
    await write_installed_tools(c.session, c.tools)
    group_kind, counter_kind = tool_kinds(
        plugin.definition, listing_uid=plugin.listing_uid
    )
    tool = c.tools.by_kind[group_kind]
    group_at, counter_at = (
        located_kind(c.tools, group_kind),
        located_kind(c.tools, counter_kind),
    )
    for d in groups:
        creator = c.users[d["created_by"]]
        initiative_id = c.initiatives[d["initiative"]].id
        group_id = await insert(
            c.session,
            group_at.table,
            {
                **column_values(
                    group_at, {"description": d.get("description")}, current=None
                ),
                "initiative_id": initiative_id,
                "name": d["name"],
                "created_by": creator.id,
                "created_by_kind": ActorKind.member,
            },
        )
        c.counter_groups[d["name"]] = group_id
        c.ids["counter_groups"].append(group_id)
        share(
            c,
            tool,
            SimpleNamespace(id=group_id, initiative_id=initiative_id),
            creator,
            roles=d.get("roles", ()),
            general=d.get("general"),
        )
        for position, (name, color, count, low, high, step, initial, look) in enumerate(
            d["counters"], start=1
        ):
            values = {
                "color": color,
                "count": count,
                "min": low,
                "max": high,
                "step": step,
                "initial_count": initial,
                "view_mode": look,
            }
            counter_id = await insert(
                c.session,
                counter_at.table,
                {
                    **column_values(counter_at, values, current=None),
                    "counter_group_id": group_id,
                    "name": name,
                    "position": position,
                    "created_by": creator.id,
                    "created_by_kind": ActorKind.member,
                },
            )
            c.counters[(d["name"], name)] = counter_id
            c.ids["counters"].append(counter_id)
    await c.session.flush()
