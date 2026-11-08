"""Counter groups: hit points, clocks and tallies."""

from __future__ import annotations

from decimal import Decimal

from app.core.tools import Tool
from app.models.tenant.counter import Counter, CounterGroup, CounterViewMode
from app.models.tenant.resource_grant import ResourceAccessLevel
from seed.common import Community, share

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
                ("Thorn HP", "#DC2626", 38, 0, 42, 1, 42, "progress_bar"),
                ("Elara HP", "#3B82F6", 24, 0, 28, 1, 28, "progress_bar"),
                ("Inspiration Pool", "#F59E0B", 2, 0, 5, 1, 0, "number"),
                ("Long Rest Clock", "#7C3AED", 3, 0, 8, 1, 0, "segmented_clock"),
            ],
        },
        {
            "name": "Castle Ravenloft Doom Clock",
            "initiative": "strahd",
            "description": "Strahd's awareness of the party. At 8 he comes for them.",
            "created_by": "Dungeon Master",
            "counters": [
                ("Strahd's Awareness", "#991B1B", 4, 0, 8, 1, 0, "segmented_clock"),
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
                ("Redbrand Hideout Cleared", "#DC2626", 4, 0, 6, 1, 0, "progress_bar"),
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
                ("Hull Integrity", "#3B82F6", 78, 0, 100, 5, 100, "progress_bar"),
                ("Plasma Reserves", "#F59E0B", 42, 0, 80, 1, 80, "progress_bar"),
                ("Colonists in Cryo", "#10B981", 4870, 0, None, 1, 5000, "number"),
                ("Days to Kepler-442b", "#7C3AED", 6, 0, 8, 1, 8, "segmented_clock"),
            ],
        },
        {
            "name": "Krellix Diplomatic Tracker",
            "initiative": "starfall",
            "description": "Relations with the Krellix Dominion.",
            "created_by": "Admin User",
            "general": ResourceAccessLevel.read,
            "counters": [
                ("Treaty Progress", "#0EA5E9", 2, 0, 5, 1, 0, "segmented_clock"),
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
                ("Hull HP", "#92400E", 87, 0, 120, 1, 120, "progress_bar"),
                ("Sails", "#FBBF24", 4, 0, 4, 1, 4, "number"),
                ("Crew Morale", "#10B981", 6, 0, 10, 1, 7, "progress_bar"),
                ("Rations (days)", "#65A30D", 18, 0, None, 1, 30, "number"),
                ("Storm Brewing", "#1E40AF", 2, 0, 6, 1, 0, "segmented_clock"),
            ],
        },
        {
            "name": "Plunder Vault",
            "initiative": "crimson",
            "description": "Treasure recovered toward the Leviathan's Heart.",
            "created_by": "Finley Goldtongue",
            "general": ResourceAccessLevel.write,
            "counters": [
                ("Tidestones Recovered", "#0EA5E9", 1, 0, 3, 1, 0, "progress_bar"),
                ("Gold (doubloons)", "#F59E0B", 4200, 0, None, 100, 0, "number"),
            ],
        },
        {
            "name": "Navy Threat Tracker",
            "initiative": "navy",
            "description": "How close the Imperial Navy is to catching us.",
            "created_by": "Dungeon Master",
            "counters": [
                ("Bounty Level", "#DC2626", 3, 0, 5, 1, 0, "segmented_clock"),
                ("Ships of the Line Sunk", "#1E40AF", 2, 0, None, 1, 0, "number"),
            ],
        },
    ],
}


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


async def seed(c: Community) -> None:
    for d in COUNTER_GROUPS[c.key]:
        creator = c.users[d["created_by"]]
        group = CounterGroup(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["name"],
            description=d.get("description"),
            created_by=creator.id,
        )
        c.session.add(group)
        await c.session.flush()
        c.counter_groups[group.name] = group
        c.ids["counter_groups"].append(group.id)
        share(
            c,
            Tool.counter_group,
            group,
            creator,
            roles=d.get("roles", ()),
            general=d.get("general"),
        )
        for position, (name, color, count, low, high, step, initial, mode) in enumerate(
            d["counters"], start=1
        ):
            counter = Counter(
                counter_group_id=group.id,
                name=name,
                color=color,
                count=_decimal(count),
                min=_decimal(low),
                max=_decimal(high),
                step=_decimal(step),
                initial_count=_decimal(initial),
                view_mode=CounterViewMode(mode),
                position=_decimal(position),
            )
            c.session.add(counter)
            await c.session.flush()
            c.ids["counters"].append(counter.id)
