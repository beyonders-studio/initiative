"""Custom properties: each initiative's definitions, and values on its tasks,
files and events."""

from __future__ import annotations

from datetime import timedelta

from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.schemas.tenant.property import PropertyValueInput
from app.services.tenant import metadata as metadata_service

from seed.common import NOW, Community

#: Each initiative's definitions, in position order. ``options`` — ``(value,
#: label[, colour])`` — are required for select / multi_select, and
#: ``currency`` for money.
DEFINITIONS: dict[str, dict[str, list[dict]]] = {
    "primary": {
        "strahd": [
            {
                "name": "Difficulty",
                "type": MetadataType.select,
                "color": "#DC2626",
                "options": [
                    ("trivial", "Trivial", "#10B981"),
                    ("moderate", "Moderate", "#F59E0B"),
                    ("hard", "Hard", "#DC2626"),
                    ("deadly", "Deadly", "#7F1D1D"),
                ],
            },
            {"name": "XP Reward", "type": MetadataType.number, "color": "#F59E0B"},
            {"name": "Prep Notes", "type": MetadataType.text},
            {
                "name": "Themes",
                "type": MetadataType.multi_select,
                "options": [
                    ("horror", "Horror", "#7F1D1D"),
                    ("investigation", "Investigation", "#3B82F6"),
                    ("social", "Social", "#10B981"),
                    ("combat", "Combat", "#DC2626"),
                ],
            },
            {"name": "Deadline", "type": MetadataType.date},
            {"name": "Owner", "type": MetadataType.user_reference, "color": "#8B5CF6"},
            {"name": "Public Knowledge", "type": MetadataType.checkbox},
            {"name": "Session Rating", "type": MetadataType.scale, "color": "#F59E0B"},
        ],
        "default": [
            {
                "name": "Cost",
                "type": MetadataType.currency,
                "currency": "USD",
                "color": "#10B981",
            },
        ],
        "lmop": [
            {"name": "Hook", "type": MetadataType.text},
            {"name": "Quest Giver", "type": MetadataType.user_reference},
            {"name": "Map Link", "type": MetadataType.url, "color": "#3B82F6"},
        ],
    },
    "starforge": {
        "starfall": [
            {
                "name": "System",
                "type": MetadataType.select,
                "options": [
                    ("starfinder", "Starfinder", "#3B82F6"),
                    ("stars_without_number", "Stars Without Number", "#10B981"),
                    ("homebrew", "Homebrew", "#F59E0B"),
                ],
            },
            {"name": "Tech Level", "type": MetadataType.number, "color": "#0EA5E9"},
            {
                "name": "Faction Tags",
                "type": MetadataType.multi_select,
                "options": [
                    ("exodus_fleet", "Exodus Fleet", "#3B82F6"),
                    ("krellix", "Krellix Dominion", "#DC2626"),
                    ("merchant_guild", "Merchant Guild", "#F59E0B"),
                ],
            },
            {"name": "Briefing Required", "type": MetadataType.checkbox},
            {"name": "Owner", "type": MetadataType.user_reference},
        ],
        "fringe": [
            {
                "name": "Mission Status",
                "type": MetadataType.select,
                "options": [
                    ("scoping", "Scoping"),
                    ("active", "Active", "#10B981"),
                    ("complete", "Complete", "#6B7280"),
                ],
            },
            {"name": "Payout (credits)", "type": MetadataType.number},
            {"name": "Map Link", "type": MetadataType.url},
        ],
    },
    "tides": {
        "crimson": [
            {
                "name": "Arc",
                "type": MetadataType.select,
                "color": "#DC2626",
                "options": [
                    ("shattered_seas", "Shattered Seas"),
                    ("tidestone_hunt", "Tidestone Hunt", "#0EA5E9"),
                    ("leviathan_finale", "Leviathan Finale", "#7F1D1D"),
                ],
            },
            {
                "name": "Crew Reward (gold)",
                "type": MetadataType.number,
                "color": "#F59E0B",
            },
            {
                "name": "Quest Hooks",
                "type": MetadataType.multi_select,
                "options": [
                    ("treasure", "Treasure", "#F59E0B"),
                    ("rescue", "Rescue", "#10B981"),
                    ("revenge", "Revenge", "#DC2626"),
                    ("exploration", "Exploration", "#0EA5E9"),
                ],
            },
            {"name": "Spoilers Allowed", "type": MetadataType.checkbox},
            {"name": "Quest Giver", "type": MetadataType.user_reference},
            {"name": "Map Link", "type": MetadataType.url},
        ],
        "navy": [
            {
                "name": "Threat Level",
                "type": MetadataType.select,
                "options": [
                    ("frigate", "Frigate", "#10B981"),
                    ("ship_of_the_line", "Ship of the Line", "#F59E0B"),
                    ("flagship", "Flagship", "#DC2626"),
                ],
            },
            {"name": "Engagement Date", "type": MetadataType.date},
        ],
    },
}

#: ``(kind, title, {property: value})`` per initiative. A person-valued
#: property names the person; everything else is the value as written.
VALUES: dict[str, dict[str, list[tuple]]] = {
    "primary": {
        "strahd": [
            (
                "task",
                "Defeat Strahd von Zarovich",
                {
                    "Difficulty": "deadly",
                    "XP Reward": 50000,
                    "Themes": ["horror", "combat"],
                    "Owner": "Dungeon Master",
                    "Deadline": (NOW + timedelta(days=30)).date(),
                },
            ),
            (
                "task",
                "Survive the Death House",
                {
                    "Difficulty": "hard",
                    "XP Reward": 4500,
                    "Themes": ["horror", "investigation"],
                },
            ),
            (
                "file",
                "Campaign Setting: The Land of Barovia",
                {"Public Knowledge": True},
            ),
            ("file", "NPC Roster: Curse of Strahd", {"Public Knowledge": False}),
            (
                "calendar_event",
                "Session 12: Into the Amber Temple",
                {"Difficulty": "deadly", "Themes": ["horror", "investigation"]},
            ),
            (
                "calendar_event",
                "Session 11: Vallaki Festival",
                {"Difficulty": "moderate", "Session Rating": 90},
            ),
            ("calendar_event", "Weekly Strahd Session", {"Owner": "Dungeon Master"}),
        ],
        "default": [
            ("task", "Order new dice set for the table", {"Cost": 48.5}),
            ("task", "Prepare battle maps for next session", {"Cost": 12}),
        ],
        "lmop": [
            (
                "file",
                "NPC Compendium: Phandelver",
                {"Map Link": "https://example.com/maps/lmop-overview"},
            )
        ],
    },
    "starforge": {
        "starfall": [
            (
                "task",
                "Repair the FTL drive core",
                {
                    "System": "starfinder",
                    "Tech Level": 9,
                    "Briefing Required": True,
                    "Owner": "Kael Windrunner",
                },
            ),
            (
                "task",
                "Negotiate passage through Krellix space",
                {
                    "System": "homebrew",
                    "Tech Level": 7,
                    "Faction Tags": ["exodus_fleet", "krellix"],
                    "Owner": "Finley Goldtongue",
                },
            ),
            (
                "file",
                "Faction Guide: Krellix Dominion",
                {"Faction Tags": ["krellix"]},
            ),
            ("task", "Quell the mutiny on Deck 7", {"Briefing Required": False}),
            ("file", "Setting Bible: The Exodus Protocol", {"Owner": "Admin User"}),
        ],
        "fringe": [
            (
                "task",
                "Infiltrate Station Omega",
                {"Mission Status": "active", "Payout (credits)": 75000},
            ),
            ("task", "Crack the vault encryption", {"Mission Status": "scoping"}),
        ],
    },
    "tides": {
        "crimson": [
            (
                "task",
                "Defeat the Leviathan guardian",
                {
                    "Arc": "leviathan_finale",
                    "Crew Reward (gold)": 25000,
                    "Quest Hooks": ["treasure", "revenge"],
                },
            ),
            (
                "task",
                "Decipher the Leviathan Map",
                {
                    "Arc": "tidestone_hunt",
                    "Quest Hooks": ["treasure", "exploration"],
                    "Quest Giver": "Finley Goldtongue",
                },
            ),
            (
                "task",
                "Collect the three Tidestones",
                {"Arc": "tidestone_hunt", "Crew Reward (gold)": 9000},
            ),
            (
                "file",
                "The Shattered Seas: World Guide",
                {
                    "Spoilers Allowed": True,
                    "Map Link": "https://example.com/maps/shattered-seas",
                },
            ),
            (
                "file",
                "Crew Manifest: The Crimson Maiden",
                {"Spoilers Allowed": False},
            ),
        ],
        "navy": [
            (
                "task",
                "Evade the HMS Vengeance",
                {
                    "Threat Level": "flagship",
                    "Engagement Date": (NOW + timedelta(days=4)).date(),
                },
            )
        ],
    },
}

#: Where each target's seeded rows are held on the community, by title.
_ROWS = {"task": "tasks", "file": "files", "calendar_event": "events"}


async def seed(c: Community) -> None:
    for key, definitions in DEFINITIONS[c.key].items():
        initiative = c.initiatives[key]
        by_name: dict[str, MetadataDefinition] = {}
        for position, d in enumerate(definitions, start=1):
            definition = MetadataDefinition(
                initiative_id=initiative.id,
                name=d["name"],
                type=d["type"],
                position=float(position),
                color=d.get("color"),
                currency=d.get("currency"),
                options=[
                    dict(zip(("value", "label", "color"), option))
                    for option in d["options"]
                ]
                if "options" in d
                else None,
            )
            c.session.add(definition)
            await c.session.flush()
            by_name[definition.name] = definition
            c.ids["property_definitions"].append(definition.id)
        # Through the service the value editor uses, so a seeded value is
        # held to the same type, option and membership rules a typed one is.
        for kind, title, values in VALUES[c.key].get(key, ()):
            inputs = [
                PropertyValueInput(
                    property_id=by_name[name].id,
                    value=c.users[value].id
                    if by_name[name].type is MetadataType.user_reference
                    else value,
                )
                for name, value in values.items()
            ]
            await metadata_service.write_values(
                c.session,
                getattr(c, _ROWS[kind])[title],
                inputs,
                initiative_id=initiative.id,
            )
            c.ids["property_values"].extend(values)
    await c.session.flush()
