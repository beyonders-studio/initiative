"""Projects and their tasks, bookmarks and recent views — and archiving, which
waits until everything a project holds exists.

Every community seeds template and archived projects beside its active ones,
with a spread of archive dates, tags, tasks and share statuses, so the
Templates and Archive tabs have the same variety the active list does.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.tenant._mixins import archive_models
from app.models.tenant.project import Project
from app.models.tenant.personal_item import PersonalItem, ViewSource
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskType,
    TaskStatusCategory,
)
from app.schemas.tenant.task import mint_checklist_item_id
from app.services.tenant import relationships as relationships_service
from app.services.tenant.archive import archive_entity
from app.services.tenant.task_completion import sync_completed_at
from app.services.tenant.task_statuses import ensure_default_statuses
from app.services.tenant.task_types import ensure_default_types

from seed.common import NOW, Community, share, tag

_DUNGEON_AREAS = [
    "Entrance Hall",
    "Crypt of Whispers",
    "The Bone Catalog",
    "Flooded Caverns",
    "Shadow Forge",
    "Hall of Mirrors",
    "Spider Nest",
    "Collapsed Library",
    "Throne of Ashes",
    "Ritual Chamber",
    "Fungal Grotto",
    "Iron Cage Arena",
    "Ember Vaults",
    "Wailing Cells",
    "Clockwork Passage",
    "Dread Pantry",
    "Ossuary",
    "Sunken Chapel",
    "Alchemist Lab",
    "Guard Barracks",
]
_DUNGEON_VERBS = [
    "Clear",
    "Explore",
    "Map",
    "Loot",
    "Secure",
    "Investigate",
    "Disarm traps in",
    "Search for secrets in",
    "Barricade",
    "Purify",
]
_DUNGEON_ADJECTIVES = [
    "Cursed",
    "Hidden",
    "Burning",
    "Frozen",
    "Ancient",
    "Ruined",
    "Enchanted",
    "Haunted",
    "Gilded",
    "Shattered",
    "Verdant",
    "Infernal",
]
_DUNGEON_USERS = [
    "Dungeon Master",
    "Thorn Ironforge",
    "Elara Moonwhisper",
    "Vex Shadowstep",
    "Admin User",
]


def mega_dungeon_tasks() -> list[dict]:
    """1 000 TTRPG-themed task defs, for stress-testing large task lists."""
    rng = random.Random(42)  # deterministic for reproducible seeds
    priorities = [
        TaskPriority.low,
        TaskPriority.medium,
        TaskPriority.high,
        TaskPriority.urgent,
    ]
    categories = [
        TaskStatusCategory.backlog,
        TaskStatusCategory.todo,
        TaskStatusCategory.in_progress,
        TaskStatusCategory.done,
    ]
    tasks: list[dict] = []
    for i in range(1, 1_001):
        area = _DUNGEON_AREAS[i % len(_DUNGEON_AREAS)]
        verb = _DUNGEON_VERBS[i % len(_DUNGEON_VERBS)]
        adj = _DUNGEON_ADJECTIVES[i % len(_DUNGEON_ADJECTIVES)]
        floor = (i - 1) // 20 + 1
        room = (i - 1) % 20 + 1
        td: dict = {
            "title": f"Floor {floor}, Room {room}: {verb} the {adj} {area}",
            "description": f"Level {floor} exploration — {verb.lower()} the "
            f"{adj.lower()} {area} and report findings to the party.",
            "priority": rng.choice(priorities),
            "category": rng.choice(categories),
        }
        # ~20% have assignees, ~10% due dates, ~8% start dates, ~5% a checklist
        if rng.random() < 0.2:
            td["assignees"] = rng.sample(_DUNGEON_USERS, k=rng.randint(1, 2))
        if rng.random() < 0.1:
            td["due_days"] = rng.randint(-5, 30)
        if rng.random() < 0.08:
            td["start_days"] = rng.randint(-10, 5)
        if rng.random() < 0.05:
            td["checklist"] = [
                f"Check {area} entrance",
                f"Search {area} for treasure",
                f"Neutralize {area} hazards",
            ]
        tasks.append(td)
    return tasks


#: Each project, in the order it is made. ``owner`` holds it; ``writers``,
#: ``readers``, ``roles`` and ``general`` share it (see ``share``).
#: ``template`` puts it on the Templates tab; ``archived_days_ago`` archives it
#: that many days back so the Archive tab has a spread of dates to sort by.
#: A task names the stage it wants (``category``), ``due_days``/``start_days``
#: relative to now, ``type`` (a default task type, Task if unnamed),
#: ``waits_on`` (titles of tasks in the same project it depends on), and
#: ``archived`` to archive it on its own.
PROJECTS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Barovia Arc",
            "initiative": "strahd",
            "icon": "\U0001f9db",
            "description": "The main horror campaign storyline through Castle Ravenloft",
            "owner": "Dungeon Master",
            "writers": ["Thorn Ironforge", "Elara Moonwhisper"],
            "readers": ["Vex Shadowstep", "Seraphina Dawnlight"],
            "general": ResourceAccessLevel.read,
            "tags": ["combat", "lore", "quest"],
            "tasks": [
                {
                    "title": "Defeat Strahd von Zarovich",
                    "description": "The vampire lord must be destroyed to free Barovia "
                    "from his curse.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.backlog,
                    "assignees": ["Thorn Ironforge", "Elara Moonwhisper"],
                    "type": "Milestone",
                    "start_days": 20,
                    "due_days": 24,
                    "waits_on": [
                        "Find the Sunsword in the Amber Temple",
                        "Retrieve the Tome of Strahd",
                    ],
                    "tags": ["quest", "combat", "boss fight"],
                },
                {
                    "title": "Survive the Death House",
                    "description": "Navigate the haunted mansion on the outskirts of "
                    "the Village of Barovia.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master"],
                    "start_days": -6,
                    "due_days": 2,
                    "checklist": [
                        "Explore the basement",
                        "Find the hidden altar",
                        "Escape before the house collapses",
                    ],
                    "tags": ["quest", "combat", "exploration"],
                },
                # The Death House's rooms, as tasks of their own under it.
                {
                    "title": "Search the library for the secret door",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Vex Shadowstep"],
                    "start_days": -6,
                    "due_days": -4,
                    "part_of": "Survive the Death House",
                    "tags": ["exploration"],
                },
                {
                    "title": "Lay the ghosts of Rose and Thorn to rest",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Elara Moonwhisper"],
                    "start_days": -3,
                    "due_days": 0,
                    "part_of": "Survive the Death House",
                    "tags": ["roleplay"],
                },
                {
                    "title": "Destroy the shambling mound",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Thorn Ironforge"],
                    "start_days": 0,
                    "due_days": 2,
                    "part_of": "Survive the Death House",
                    "tags": ["combat"],
                },
                {
                    "title": "Find the Sunsword in the Amber Temple",
                    "description": "The legendary weapon is key to defeating the Dark Lord.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "start_days": 5,
                    "due_days": 14,
                    "waits_on": ["Survive the Death House"],
                    "assignees": ["Thorn Ironforge"],
                    "tags": ["quest", "lore", "items/loot"],
                },
                {
                    "title": "Negotiate with the Vistani caravan",
                    "description": "The Vistani hold secrets about Strahd and safe "
                    "passage through the mists.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Vex Shadowstep"],
                    "start_days": -10,
                    "due_days": -5,
                    "tags": ["NPC", "roleplay"],
                },
                {
                    "title": "Retrieve the Tome of Strahd",
                    "description": "The tome reveals Strahd's history and weaknesses.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Elara Moonwhisper"],
                    "start_days": 1,
                    "due_days": 7,
                    "waits_on": ["Survive the Death House"],
                    "tags": ["quest", "lore", "items/loot"],
                },
                {
                    "title": "Ally with the werewolf pack",
                    "description": "The werewolves of Barovia could be powerful allies "
                    "against Strahd if convinced.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                    "type": "Idea",
                },
                {
                    "title": "Escort Ireena to Vallaki",
                    "description": "Protect Ireena Kolyana from Strahd's minions on the "
                    "road to Vallaki.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Seraphina Dawnlight", "Thorn Ironforge"],
                    "start_days": -12,
                    "due_days": -8,
                    "checklist": [
                        "Pack supplies for the journey",
                        "Guard Ireena through the Svalich Woods",
                        "Arrive at Vallaki gates",
                    ],
                    "tags": ["quest", "NPC", "roleplay"],
                },
            ],
        },
        {
            "name": "Castle Ravenloft",
            "initiative": "strahd",
            "icon": "\U0001f3f0",
            "description": "The final dungeon — Strahd's fortress atop the Pillarstone",
            "owner": "Dungeon Master",
            "writers": ["Thorn Ironforge"],
            "roles": [("strahd", ResourceAccessLevel.read)],
            "tags": ["combat", "exploration", "boss fight"],
            "tasks": [
                {
                    "title": "Map Castle Ravenloft's layout",
                    "description": "Sketch out known rooms and passages for the final assault.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master"],
                    "checklist": [
                        "Map the main floor",
                        "Map the crypts",
                        "Map the towers",
                        "Map Strahd's tomb",
                    ],
                    "tags": ["exploration", "puzzle"],
                },
                {
                    "title": "Disable the castle traps",
                    "description": "Ravenloft is full of deadly traps protecting the vampire lord.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Vex Shadowstep"],
                },
                {
                    "title": "Find the Heart of Sorrow",
                    "description": "The crystal heart protects Strahd and must be destroyed first.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.backlog,
                    "due_days": 21,
                    "tags": ["quest", "boss fight"],
                },
            ],
        },
        {
            "name": "Phandalin Adventures",
            "initiative": "lmop",
            "icon": "\u2694\ufe0f",
            "description": "Classic starter campaign in the Sword Coast region",
            "owner": "Admin User",
            "writers": ["Dungeon Master", "Thorn Ironforge", "Elara Moonwhisper"],
            "tags": ["quest", "NPC"],
            "tasks": [
                {
                    "title": "Rescue Gundren Rockseeker",
                    "description": "The dwarf was kidnapped on the road to Phandalin. Find him!",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Admin User", "Thorn Ironforge"],
                    "due_days": 3,
                    "tags": ["quest", "NPC"],
                },
                {
                    "title": "Clear the Redbrand Hideout",
                    "description": "The Redbrand ruffians terrorize Phandalin from "
                    "their base under Tresendar Manor.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Thorn Ironforge", "Elara Moonwhisper"],
                    "tags": ["quest", "combat"],
                },
                {
                    "title": "Escort merchant supplies to Phandalin",
                    "description": "Deliver the wagon of supplies safely along the Triboar Trail.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                },
                {
                    "title": "Investigate the Cragmaw goblins",
                    "description": "A tribe of goblins ambushed the party. Their "
                    "hideout must be cleared.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "checklist": [
                        "Find the Cragmaw Hideout",
                        "Defeat Klarg the bugbear",
                        "Free Sildar Hallwinter",
                    ],
                    "checklist_done": True,
                    "tags": ["quest", "combat", "exploration"],
                },
                {
                    "title": "Talk to Halia Thornton at the Miner's Exchange",
                    "description": "She may have intel about the Redbrands and the Black Spider.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Elara Moonwhisper"],
                },
                {
                    "title": "Visit Old Owl Well",
                    "description": "Reports of undead activity near the old watchtower ruins.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Wave Echo Cave",
            "initiative": "lmop",
            "icon": "\U0001f48e",
            "description": "The lost mine of Phandelver and the Forge of Spells",
            "owner": "Admin User",
            "writers": ["Dungeon Master"],
            "readers": ["Thorn Ironforge", "Elara Moonwhisper"],
            "tags": ["quest", "exploration", "items/loot"],
            "tasks": [
                {
                    "title": "Defeat the Black Spider in Wave Echo Cave",
                    "description": "Nezznar the Black Spider seeks the Forge of Spells.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.backlog,
                    "checklist": [
                        "Find the entrance to Wave Echo Cave",
                        "Navigate the mine tunnels",
                        "Confront Nezznar",
                    ],
                    "due_days": 10,
                    "tags": ["quest", "combat", "boss fight"],
                },
                {
                    "title": "Activate the Forge of Spells",
                    "description": "The ancient dwarven forge could create powerful magic items.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.backlog,
                    "assignees": ["Elara Moonwhisper"],
                    "tags": ["lore", "items/loot", "puzzle"],
                },
                {
                    "title": "Clear the undead miners",
                    "description": "Ghosts and skeletons of the original miners still "
                    "haunt the tunnels.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Seraphina Dawnlight"],
                },
            ],
        },
        {
            "name": "Session Zero & Planning",
            "initiative": "default",
            "icon": "\U0001f4cb",
            "description": "Meta-campaign logistics and session planning",
            "owner": "Dungeon Master",
            "writers": ["Admin User"],
            "tags": ["roleplay"],
            "tasks": [
                {
                    "title": "Finalize character backstories",
                    "description": "All players need to submit their character "
                    "backstories before Session 1.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                },
                {
                    "title": "Schedule Session 4",
                    "description": "Find a date that works for all five players.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                    "due_days": 5,
                    "assignees": ["Dungeon Master"],
                },
                {
                    "title": "Review leveling rules for Tier 2",
                    "description": "Characters approaching level 5 — review "
                    "multiclassing and feat rules.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
                {
                    "title": "Prepare battle maps for next session",
                    "description": "Print or prepare VTT maps for the upcoming dungeon crawl.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master"],
                    "due_days": 2,
                },
                {
                    "title": "Order new dice set for the table",
                    "description": "The group agreed to get matching dice for the campaign.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.done,
                },
            ],
        },
        {
            "name": "Homebrew Rules",
            "initiative": "default",
            "icon": "\U0001f4dc",
            "description": "Custom house rules, variant options, and homebrew content",
            "owner": "Dungeon Master",
            "writers": ["Admin User", "Thorn Ironforge"],
            "general": ResourceAccessLevel.write,
            "tags": ["combat", "items/loot"],
            "tasks": [
                {
                    "title": "Write critical hit tables",
                    "description": "Custom critical hit effects for each damage type.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master"],
                    "checklist": [
                        "Slashing crits",
                        "Piercing crits",
                        "Bludgeoning crits",
                        "Fire crits",
                        "Cold crits",
                        "Lightning crits",
                    ],
                    "tags": ["combat"],
                },
                {
                    "title": "Balance the Gunslinger subclass",
                    "description": "Homebrew fighter subclass needs playtesting feedback.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Thorn Ironforge"],
                    "tags": ["combat"],
                },
                {
                    "title": "Revise potion crafting rules",
                    "description": "Current rules are too restrictive — allow crafting "
                    "during short rests.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Admin User"],
                },
                {
                    "title": "Retire the old initiative-tracker house rule",
                    "description": "Superseded by the queues feature. Kept for the archive view.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.done,
                    "archived": True,
                },
            ],
        },
        {
            "name": "DM's Secret Vault",
            "initiative": "strahd",
            "icon": "\U0001f512",
            "description": "Unshared DM prep — plot twists the players must not see. "
            "Tests the private (owner-only) share status.",
            "owner": "Dungeon Master",
            "tasks": [
                {
                    "title": "Plan the Ireena/Tatyana reveal",
                    "description": "Session 15 twist. Absolutely no player visibility.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master"],
                },
                {
                    "title": "Stat the secret final boss variant",
                    "description": "Strahd's heart-linked form if the party destroys "
                    "the Heart of Sorrow first.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Scrapped subplot: the mongrelfolk uprising",
                    "description": "Cut for pacing. Archived so it stops cluttering the board.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                    "archived": True,
                },
            ],
        },
        {
            "name": "Mega Dungeon: Halls of the Dread Lord",
            "initiative": "strahd",
            "icon": "\U0001f3f0",
            "description": "A sprawling 200-room dungeon crawl beneath Castle "
            "Ravenloft. Used to stress-test large task lists.",
            "owner": "Dungeon Master",
            "writers": ["Admin User", "Thorn Ironforge", "Elara Moonwhisper"],
            "readers": ["Vex Shadowstep", "Seraphina Dawnlight"],
            "tasks": mega_dungeon_tasks(),
        },
        {
            "name": "Template: One-Shot Night",
            "initiative": "default",
            "icon": "\U0001f3b2",
            "description": "Skeleton for a single-session adventure — hook, three "
            "scenes, a set-piece fight, and a payoff.",
            "owner": "Dungeon Master",
            "writers": ["Admin User"],
            "general": ResourceAccessLevel.read,
            "template": True,
            "tags": ["quest", "roleplay"],
            "tasks": [
                {
                    "title": "Write the hook",
                    "description": "Two sentences the table hears in the first five minutes.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Sketch three scenes",
                    "description": "Investigation, complication, confrontation.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "checklist": ["Investigation", "Complication", "Confrontation"],
                },
                {
                    "title": "Stat the set-piece fight",
                    "description": "One interesting terrain feature, one reason to move.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.backlog,
                },
                {
                    "title": "Prep the payoff and handouts",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Template: Dungeon Prep",
            "initiative": "strahd",
            "icon": "\U0001f5fa\ufe0f",
            "description": "Room-by-room prep checklist reused for every dungeon in the arc.",
            "owner": "Dungeon Master",
            "writers": ["Thorn Ironforge"],
            "roles": [("strahd", ResourceAccessLevel.read)],
            "template": True,
            "tags": ["exploration", "puzzle"],
            "tasks": [
                {
                    "title": "Draw the map key",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Populate rooms with encounters",
                    "description": "Third empty, third obstacle, third payoff.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Seed two secrets per level",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Template: NPC Workshop",
            "initiative": "lmop",
            "icon": "\U0001f3ad",
            "description": "Voice, want, secret, and a stat block to reskin. Private to "
            "the DM until it is polished.",
            "owner": "Dungeon Master",
            "template": True,
            "tags": ["NPC", "roleplay"],
            "tasks": [
                {
                    "title": "Pick a voice and a verbal tic",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Write want, fear, and secret",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                },
            ],
        },
        {
            "name": "Tomb of Annihilation (Completed)",
            "initiative": "default",
            "icon": "\U0001f480",
            "description": "Wrapped after 22 sessions. Kept for the recap notes and the "
            "loot ledger.",
            "owner": "Dungeon Master",
            "writers": ["Admin User", "Thorn Ironforge"],
            "readers": ["Elara Moonwhisper", "Vex Shadowstep"],
            "archived_days_ago": 12,
            "tags": ["quest", "exploration", "boss fight"],
            "tasks": [
                {
                    "title": "Escape the Tomb of the Nine Gods",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Thorn Ironforge", "Elara Moonwhisper"],
                },
                {
                    "title": "Destroy the Soulmonger",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Dungeon Master"],
                },
                {
                    "title": "Write the campaign post-mortem",
                    "description": "What landed, what dragged, what to reuse.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.done,
                },
            ],
        },
        {
            "name": "Planescape Detour",
            "initiative": "strahd",
            "icon": "\U0001f300",
            "description": "Side arc the table voted against. Shelved rather than deleted.",
            "owner": "Dungeon Master",
            "writers": ["Thorn Ironforge"],
            "general": ResourceAccessLevel.read,
            "archived_days_ago": 64,
            "tags": ["lore", "side quest"],
            "tasks": [
                {
                    "title": "Map Sigil's wards",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master"],
                },
                {
                    "title": "Write the faction primer",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                },
            ],
        },
        {
            "name": "Rules Playtest: Old Initiative Tracker",
            "initiative": "lmop",
            "icon": "\U0001f570\ufe0f",
            "description": "Superseded by the queues feature. Archived long enough ago "
            "to sort last.",
            "owner": "Admin User",
            "archived_days_ago": 210,
            "tasks": [
                {
                    "title": "Compare the tracker against queues",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Admin User"],
                }
            ],
        },
    ],
    "starforge": [
        {
            "name": "The Exodus Fleet",
            "initiative": "starfall",
            "icon": "\U0001f680",
            "description": "Managing the fleet's journey across the void between stars",
            "owner": "Admin User",
            "writers": ["Finley Goldtongue", "Kael Windrunner"],
            "readers": ["Aurelia Brightshield", "Vex Shadowstep", "Elara Moonwhisper"],
            "tags": ["main quest", "exploration"],
            "tasks": [
                {
                    "title": "Repair the FTL drive core",
                    "description": "The main drive is failing. Without repairs, the "
                    "fleet is stranded.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Kael Windrunner"],
                    "checklist": [
                        "Diagnose the plasma leak",
                        "Source replacement crystals",
                        "Recalibrate the nav array",
                    ],
                    "due_days": 2,
                    "tags": ["main quest", "engineering"],
                },
                {
                    "title": "Investigate the distress signal from Sector 7G",
                    "description": "An automated distress beacon is broadcasting from "
                    "an uncharted system.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Aurelia Brightshield", "Vex Shadowstep"],
                    "due_days": 7,
                    "tags": ["exploration", "side quest"],
                },
                {
                    "title": "Negotiate passage through Krellix space",
                    "description": "The Krellix Dominion controls the only safe "
                    "corridor to the target system.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.backlog,
                    "assignees": ["Finley Goldtongue"],
                    "tags": ["diplomacy", "main quest"],
                },
                {
                    "title": "Quell the mutiny on Deck 7",
                    "description": "A group of colonists is threatening to take a "
                    "shuttle and break from the fleet.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Admin User", "Aurelia Brightshield"],
                    "tags": ["main quest", "NPC"],
                },
                {
                    "title": "Map the nebula passage",
                    "description": "Chart a safe course through the Verdant Nebula to "
                    "save 3 months of travel.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Elara Moonwhisper"],
                },
                {
                    "title": "Decommission the Icarus VII",
                    "description": "The oldest ship in the fleet is no longer "
                    "spaceworthy. Salvage what we can.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Colony Alpha",
            "initiative": "starfall",
            "icon": "\U0001f30d",
            "description": "Establishing the first settlement on the candidate planet",
            "owner": "Admin User",
            "writers": ["Finley Goldtongue", "Aurelia Brightshield"],
            "roles": [("starfall", ResourceAccessLevel.read)],
            "tags": ["main quest", "survival"],
            "tasks": [
                {
                    "title": "Survey landing sites on Kepler-442b",
                    "description": "Send probes to evaluate three candidate sites for the colony.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Admin User"],
                    "checklist": [
                        "Deploy orbital probes",
                        "Analyze atmospheric data",
                        "Check for hostile fauna",
                    ],
                    "due_days": 14,
                    "tags": ["exploration", "main quest"],
                },
                {
                    "title": "Design the colony habitat modules",
                    "description": "Prefab habitats need to support 500 colonists in "
                    "the first wave.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Kael Windrunner"],
                },
                {
                    "title": "Establish a perimeter defense grid",
                    "description": "Unknown life forms detected. We need automated defenses.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.backlog,
                    "assignees": ["Aurelia Brightshield"],
                    "tags": ["combat", "survival"],
                },
                {
                    "title": "Set up the hydroponics bay",
                    "description": "Food production must begin within 48 hours of landing.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.todo,
                    "due_days": 3,
                    "tags": ["survival"],
                },
            ],
        },
        {
            "name": "Smuggler's Run",
            "initiative": "fringe",
            "icon": "\U0001f4b0",
            "description": "A one-shot heist adventure on a derelict space station",
            "owner": "Finley Goldtongue",
            "writers": ["Kael Windrunner", "Vex Shadowstep"],
            "readers": ["Aurelia Brightshield"],
            "tags": ["side quest", "stealth", "loot"],
            "tasks": [
                {
                    "title": "Infiltrate Station Omega",
                    "description": "The heist begins: get past security and reach the vault level.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Vex Shadowstep", "Finley Goldtongue"],
                    "checklist": [
                        "Forge ID badges",
                        "Disable security cameras on Level 3",
                        "Create a distraction",
                    ],
                    "tags": ["stealth", "side quest"],
                },
                {
                    "title": "Crack the vault encryption",
                    "description": "The vault uses quantum encryption. We need a specialist AI.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Kael Windrunner"],
                    "tags": ["stealth", "engineering"],
                },
                {
                    "title": "Escape before station self-destructs",
                    "description": "Once the vault opens, the station's failsafe "
                    "triggers. 10 minutes to escape.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Engineering Bay",
            "initiative": "starfall",
            "icon": "\U0001f527",
            "description": "Ship upgrades, tech research, and equipment management",
            "owner": "Kael Windrunner",
            "writers": ["Admin User", "Elara Moonwhisper"],
            "general": ResourceAccessLevel.write,
            "tags": ["engineering"],
            "tasks": [
                {
                    "title": "Upgrade shield generators to Mark IV",
                    "description": "Current shields can't handle Krellix plasma weapons.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Kael Windrunner", "Elara Moonwhisper"],
                    "tags": ["engineering"],
                },
                {
                    "title": "Research cloaking technology",
                    "description": "Salvaged alien tech might allow partial cloaking of "
                    "smaller vessels.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.backlog,
                    "assignees": ["Elara Moonwhisper"],
                },
                {
                    "title": "Fabricate replacement hull plating",
                    "description": "Asteroid impacts have weakened the port side. "
                    "Fabricate and install repairs.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Kael Windrunner"],
                },
            ],
        },
        {
            "name": "Campaign Planning",
            "initiative": "default",
            "icon": "\U0001f4c5",
            "description": "Session scheduling and campaign logistics",
            "owner": "Admin User",
            "writers": ["Finley Goldtongue"],
            "tasks": [
                {
                    "title": "Schedule Session 5: Colony Landfall",
                    "description": "The big session where the fleet arrives at Kepler-442b.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Admin User"],
                    "due_days": 10,
                },
                {
                    "title": "Prep NPC stat blocks for Krellix diplomats",
                    "description": "Need stats for 3 Krellix NPCs with unique abilities.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Admin User"],
                },
                {
                    "title": "Session 3 scheduling poll",
                    "description": "Closed poll — session happened. Archived.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.done,
                    "archived": True,
                },
            ],
        },
        {
            "name": "Template: Away Mission",
            "initiative": "starfall",
            "icon": "\U0001f6f0\ufe0f",
            "description": "Boilerplate for every planetside excursion — landing party, "
            "hazards, extraction plan.",
            "owner": "Finley Goldtongue",
            "writers": ["Admin User", "Kael Windrunner"],
            "general": ResourceAccessLevel.read,
            "template": True,
            "tags": ["exploration", "survival"],
            "tasks": [
                {
                    "title": "Pick the landing party",
                    "description": "Two specialists, one liability, one wildcard.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Define the environmental hazard",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Write the extraction complication",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Template: Ship Refit",
            "initiative": "default",
            "icon": "\U0001f527",
            "description": "Checklist for taking a vessel apart and putting it back together.",
            "owner": "Kael Windrunner",
            "roles": [("starfall", ResourceAccessLevel.read)],
            "template": True,
            "tags": ["engineering"],
            "tasks": [
                {
                    "title": "Inventory the salvage",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Cost the upgrade in fuel and days",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Prologue: Leaving Sol",
            "initiative": "starfall",
            "icon": "\U0001f31e",
            "description": "The first six sessions, closed out when the fleet cleared "
            "the heliopause.",
            "owner": "Admin User",
            "writers": ["Finley Goldtongue"],
            "readers": ["Kael Windrunner", "Aurelia Brightshield"],
            "archived_days_ago": 21,
            "tags": ["main quest", "survival"],
            "tasks": [
                {
                    "title": "Break orbit ahead of the blockade",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Finley Goldtongue"],
                },
                {
                    "title": "Ration the first year of supplies",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Kael Windrunner"],
                },
            ],
        },
        {
            "name": "Derelict Station Heist (Cancelled)",
            "initiative": "fringe",
            "icon": "\U0001f6a7",
            "description": "Scheduling never worked out. Archived with the prep intact.",
            "owner": "Finley Goldtongue",
            "archived_days_ago": 95,
            "tags": ["side quest", "stealth"],
            "tasks": [
                {
                    "title": "Map the station's power grid",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                },
                {
                    "title": "Decide what the vault actually holds",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
    ],
    "tides": [
        {
            "name": "The Crimson Maiden",
            "initiative": "crimson",
            "icon": "\u2693",
            "description": "Managing the party's ship, crew, and upgrades",
            "owner": "Finley Goldtongue",
            "writers": ["Admin User", "Thorn Ironforge"],
            "readers": [
                "Kael Windrunner",
                "Aurelia Brightshield",
                "Seraphina Dawnlight",
            ],
            "tags": ["ship upgrades"],
            "tasks": [
                {
                    "title": "Recruit a new helmsman",
                    "description": "Old Barnaby fell overboard. We need someone who can "
                    "navigate the Shattered Reefs.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Finley Goldtongue"],
                    "due_days": 5,
                    "tags": ["NPC"],
                },
                {
                    "title": "Repair the hull after the kraken attack",
                    "description": "Three breaches below the waterline. She's taking on water.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Thorn Ironforge", "Kael Windrunner"],
                    "checklist": [
                        "Patch the port breach",
                        "Reinforce the keel",
                        "Replace the damaged mast",
                    ],
                    "tags": ["ship upgrades"],
                },
                {
                    "title": "Upgrade cannons to dragon-fire shot",
                    "description": "Alchemical ammunition from the black market in Port Havoc.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.backlog,
                    "assignees": ["Thorn Ironforge"],
                    "tags": ["ship upgrades", "loot"],
                },
                {
                    "title": "Restock provisions at Port Havoc",
                    "description": "Fresh water, hardtack, rum, and gunpowder. The essentials.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                },
                {
                    "title": "Install the enchanted compass",
                    "description": "The compass from the Sea Witch should point to the "
                    "Leviathan's lair.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Aurelia Brightshield"],
                    "tags": ["ship upgrades", "loot"],
                },
            ],
        },
        {
            "name": "Treasure of the Leviathan",
            "initiative": "crimson",
            "icon": "\U0001f4b0",
            "description": "The legendary hoard guarded by the sea beast",
            "owner": "Finley Goldtongue",
            "writers": ["Admin User", "Dungeon Master"],
            "general": ResourceAccessLevel.read,
            "tags": ["main quest", "exploration", "boss fight"],
            "tasks": [
                {
                    "title": "Decipher the Leviathan Map",
                    "description": "The map is written in Old Merfolk. Find someone who "
                    "can read it.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Finley Goldtongue", "Admin User"],
                    "checklist": [
                        "Find a translator in Port Havoc",
                        "Cross-reference with known charts",
                        "Identify the three key landmarks",
                    ],
                    "tags": ["main quest", "exploration"],
                },
                {
                    "title": "Collect the three Tidestones",
                    "description": "Legend says three enchanted stones unlock the "
                    "Leviathan's vault.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.backlog,
                    "checklist": [
                        "Tidestone of Storms (Tempest Isle)",
                        "Tidestone of Depths (Abyssal Trench)",
                        "Tidestone of Calm (Sanctuary Reef)",
                    ],
                    "tags": ["main quest", "exploration"],
                },
                {
                    "title": "Defeat the Leviathan guardian",
                    "description": "An ancient sea serpent guards the entrance to the "
                    "vault. This won't be easy.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.backlog,
                    "due_days": 45,
                    "tags": ["main quest", "boss fight"],
                },
                {
                    "title": "Research the Leviathan's weakness",
                    "description": "The old legends mention a weakness. Check the "
                    "library at Coral Keep.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Admin User"],
                },
            ],
        },
        {
            "name": "Island Exploration",
            "initiative": "crimson",
            "icon": "\U0001f3dd\ufe0f",
            "description": "Uncharted islands and their mysteries",
            "owner": "Dungeon Master",
            "writers": ["Finley Goldtongue", "Kael Windrunner"],
            "readers": ["Aurelia Brightshield"],
            "tags": ["exploration", "side quest"],
            "tasks": [
                {
                    "title": "Explore Skull Cove",
                    "description": "A hidden cove on the south side of Dagger Isle. "
                    "Rumored to hold pirate treasure.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Kael Windrunner", "Finley Goldtongue"],
                    "tags": ["exploration", "loot"],
                },
                {
                    "title": "Map the Whispering Jungle",
                    "description": "The interior of Tempest Isle is unmapped. Strange "
                    "sounds at night.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Kael Windrunner"],
                    "checklist": [
                        "Chart the coastline",
                        "Find the source of the whispers",
                        "Locate the ruined temple",
                    ],
                    "tags": ["exploration"],
                },
                {
                    "title": "Negotiate with the Coral Elves",
                    "description": "The Coral Elves of Sanctuary Reef may know where a "
                    "Tidestone is hidden.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Finley Goldtongue", "Aurelia Brightshield"],
                    "tags": ["diplomacy", "NPC"],
                },
                {
                    "title": "Investigate the ghost ship sightings",
                    "description": "Multiple ships report a phantom vessel near the "
                    "Abyssal Trench.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                    "tags": ["exploration", "side quest"],
                },
            ],
        },
        {
            "name": "Admiral Blackwood's Fleet",
            "initiative": "navy",
            "icon": "\u2694\ufe0f",
            "description": "Tracking the movements and strength of the Imperial Navy",
            "owner": "Dungeon Master",
            "writers": ["Finley Goldtongue", "Thorn Ironforge"],
            "roles": [("navy", ResourceAccessLevel.write)],
            "tags": ["naval combat", "stealth"],
            "tasks": [
                {
                    "title": "Evade the HMS Vengeance",
                    "description": "Blackwood's flagship is patrolling the straits. We "
                    "need an alternate route.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Dungeon Master", "Finley Goldtongue"],
                    "tags": ["naval combat", "stealth"],
                },
                {
                    "title": "Raid the supply convoy near Coral Keep",
                    "description": "Three merchant ships carrying weapons and gold, "
                    "lightly guarded.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Thorn Ironforge"],
                    "due_days": 7,
                    "tags": ["naval combat", "loot"],
                },
                {
                    "title": "Forge letters of marque",
                    "description": "If we can forge royal papers, we can pass as "
                    "privateers instead of pirates.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Finley Goldtongue"],
                    "tags": ["stealth", "diplomacy"],
                },
                {
                    "title": "Sink the HMS Ironclad",
                    "description": "Blackwood's second-in-command's ship. Remove it and "
                    "weaken the fleet.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Thorn Ironforge", "Kael Windrunner"],
                    "tags": ["naval combat", "boss fight"],
                },
            ],
        },
        {
            "name": "Campaign Notes",
            "initiative": "default",
            "icon": "\U0001f4dd",
            "description": "Session recaps and campaign logistics",
            "owner": "Finley Goldtongue",
            "writers": ["Admin User", "Dungeon Master"],
            "tasks": [
                {
                    "title": "Write session 6 recap",
                    "description": "The kraken fight and arrival at Port Havoc.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                    "assignees": ["Admin User"],
                },
                {
                    "title": "Schedule next session",
                    "description": "Probably the weekend after next. Check with everyone.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                    "assignees": ["Finley Goldtongue"],
                    "due_days": 4,
                },
            ],
        },
        {
            "name": "Template: Voyage Leg",
            "initiative": "crimson",
            "icon": "\U0001f5fa\ufe0f",
            "description": "Every stretch of open water: weather, a sighting, a port, a rumor.",
            "owner": "Finley Goldtongue",
            "writers": ["Dungeon Master"],
            "general": ResourceAccessLevel.read,
            "template": True,
            "tags": ["exploration"],
            "tasks": [
                {
                    "title": "Roll the weather and the wind",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Place one sighting on the horizon",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Stock the port with a rumor and a debt",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "Template: Boarding Action",
            "initiative": "navy",
            "icon": "\u2694\ufe0f",
            "description": "Ship-to-ship combat beats, from first broadside to the "
            "surrender terms.",
            "owner": "Dungeon Master",
            "roles": [("navy", ResourceAccessLevel.read)],
            "template": True,
            "tags": ["naval combat", "boss fight"],
            "tasks": [
                {
                    "title": "Set the opening broadside",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "title": "Write the surrender terms",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
            ],
        },
        {
            "name": "The Mutiny at Saltmarsh",
            "initiative": "crimson",
            "icon": "\U0001f5e1\ufe0f",
            "description": "Resolved three sessions ago. Archived once the new "
            "quartermaster settled in.",
            "owner": "Finley Goldtongue",
            "writers": ["Admin User", "Thorn Ironforge"],
            "readers": ["Kael Windrunner"],
            "archived_days_ago": 8,
            "tags": ["NPC", "diplomacy"],
            "tasks": [
                {
                    "title": "Put down the mutiny",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Finley Goldtongue", "Thorn Ironforge"],
                },
                {
                    "title": "Appoint a new quartermaster",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                    "assignees": ["Admin User"],
                },
                {
                    "title": "Rewrite the articles of the ship",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.in_progress,
                },
            ],
        },
        {
            "name": "Privateer Paperwork",
            "initiative": "default",
            "icon": "\U0001f4dc",
            "description": "Bookkeeping experiment nobody enjoyed. Archived, not deleted.",
            "owner": "Admin User",
            "archived_days_ago": 140,
            "tasks": [
                {
                    "title": "Track every share of plunder",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                }
            ],
        },
    ],
}

#: ``(person, project)`` — each person's bookmarked projects.
BOOKMARKS: dict[str, list[tuple[str, str]]] = {
    "primary": [
        ("Dungeon Master", "Barovia Arc"),
        ("Dungeon Master", "Castle Ravenloft"),
        ("Dungeon Master", "Session Zero & Planning"),
        ("Thorn Ironforge", "Barovia Arc"),
        ("Thorn Ironforge", "Phandalin Adventures"),
        ("Elara Moonwhisper", "Barovia Arc"),
        ("Elara Moonwhisper", "Wave Echo Cave"),
        ("Vex Shadowstep", "Castle Ravenloft"),
        ("Seraphina Dawnlight", "Barovia Arc"),
        ("Admin User", "Phandalin Adventures"),
        ("Admin User", "Wave Echo Cave"),
        ("Guildmaster Aldric", "Barovia Arc"),
    ],
    "starforge": [
        ("Admin User", "The Exodus Fleet"),
        ("Admin User", "Colony Alpha"),
        ("Finley Goldtongue", "Smuggler's Run"),
        ("Finley Goldtongue", "The Exodus Fleet"),
        ("Kael Windrunner", "Engineering Bay"),
        ("Kael Windrunner", "The Exodus Fleet"),
        ("Aurelia Brightshield", "Colony Alpha"),
        ("Vex Shadowstep", "Smuggler's Run"),
    ],
    "tides": [
        ("Finley Goldtongue", "The Crimson Maiden"),
        ("Finley Goldtongue", "Treasure of the Leviathan"),
        ("Admin User", "Treasure of the Leviathan"),
        ("Admin User", "Admiral Blackwood's Fleet"),
        ("Dungeon Master", "Admiral Blackwood's Fleet"),
        ("Dungeon Master", "Island Exploration"),
        ("Thorn Ironforge", "The Crimson Maiden"),
        ("Thorn Ironforge", "Admiral Blackwood's Fleet"),
        ("Kael Windrunner", "Island Exploration"),
        ("Kael Windrunner", "The Crimson Maiden"),
        ("Aurelia Brightshield", "The Crimson Maiden"),
    ],
}

#: ``(person, project)`` — the order each person opened them in.
RECENT_VIEWS: dict[str, list[tuple[str, str]]] = {
    "primary": [
        ("Dungeon Master", "Barovia Arc"),
        ("Dungeon Master", "Castle Ravenloft"),
        ("Dungeon Master", "Session Zero & Planning"),
        ("Dungeon Master", "Homebrew Rules"),
        ("Thorn Ironforge", "Barovia Arc"),
        ("Thorn Ironforge", "Phandalin Adventures"),
        ("Elara Moonwhisper", "Barovia Arc"),
        ("Elara Moonwhisper", "Wave Echo Cave"),
        ("Admin User", "Phandalin Adventures"),
        ("Admin User", "Session Zero & Planning"),
    ],
    "starforge": [
        ("Admin User", "The Exodus Fleet"),
        ("Admin User", "Colony Alpha"),
        ("Admin User", "Campaign Planning"),
        ("Finley Goldtongue", "Smuggler's Run"),
        ("Finley Goldtongue", "The Exodus Fleet"),
        ("Kael Windrunner", "Engineering Bay"),
        ("Kael Windrunner", "The Exodus Fleet"),
    ],
    "tides": [
        ("Finley Goldtongue", "The Crimson Maiden"),
        ("Finley Goldtongue", "Treasure of the Leviathan"),
        ("Finley Goldtongue", "Campaign Notes"),
        ("Admin User", "Treasure of the Leviathan"),
        ("Admin User", "Admiral Blackwood's Fleet"),
        ("Dungeon Master", "Admiral Blackwood's Fleet"),
        ("Dungeon Master", "Island Exploration"),
        ("Thorn Ironforge", "The Crimson Maiden"),
        ("Thorn Ironforge", "Admiral Blackwood's Fleet"),
        ("Kael Windrunner", "Island Exploration"),
    ],
}

# A task def names the stage it wants, not a column, and a project need not
# have a column in that stage: a project seeded today has no backlog one, so
# every def asking for backlog has to land somewhere. Each stage lists where to
# look next, nearest first, so the seed follows the board it was actually given
# instead of failing the next time the defaults move.
_CATEGORY_FALLBACKS: dict[TaskStatusCategory, tuple[TaskStatusCategory, ...]] = {
    TaskStatusCategory.backlog: (
        TaskStatusCategory.todo,
        TaskStatusCategory.in_progress,
        TaskStatusCategory.done,
    ),
    TaskStatusCategory.todo: (
        TaskStatusCategory.backlog,
        TaskStatusCategory.in_progress,
        TaskStatusCategory.done,
    ),
    TaskStatusCategory.in_progress: (
        TaskStatusCategory.todo,
        TaskStatusCategory.backlog,
        TaskStatusCategory.done,
    ),
    TaskStatusCategory.done: (
        TaskStatusCategory.in_progress,
        TaskStatusCategory.todo,
        TaskStatusCategory.backlog,
    ),
}


def resolve_status(
    statuses: dict[TaskStatusCategory, TaskStatus], category: TaskStatusCategory
) -> TaskStatus:
    """The column a task def's stage lands in on this particular board."""
    for candidate in (category, *_CATEGORY_FALLBACKS[category]):
        if candidate in statuses:
            return statuses[candidate]
    raise RuntimeError(f"project has no task status to put a {category} task in")


async def seed(c: Community) -> None:
    for d in PROJECTS[c.key]:
        await create_project(c, d)
    # A bookmark and an open on one project are one row.
    kept: dict[tuple[int | None, int | None], PersonalItem] = {}

    def row(name: str, project: str) -> PersonalItem:
        key = (c.users[name].id, c.projects[project].id)
        if key not in kept:
            kept[key] = PersonalItem(
                user_id=key[0], entity_type=Tool.project.value, entity_id=key[1]
            )
        return kept[key]

    now = datetime.now(timezone.utc)
    for name, project in BOOKMARKS[c.key]:
        row(name, project).bookmarked_at = now
        c.ids["bookmarks"].append(c.projects[project].id)
    for name, project in RECENT_VIEWS[c.key]:
        item = row(name, project)
        item.viewed_at, item.view_source = now, ViewSource.direct.value
    c.session.add_all(kept.values())
    await c.session.flush()


async def create_project(c: Community, d: dict) -> Project:
    """A project, its sharing, its default statuses, and its tasks.

    The seed builds Project rows directly rather than going through the create
    endpoint, so it owns every default that endpoint would have applied — the
    statuses included. Archived last, not first: archived work is
    read-only all the way down, so the date is remembered and stamped once the
    community holds everything it is meant to hold.
    """
    project = Project(
        name=d["name"],
        icon=d["icon"],
        description=d["description"],
        initiative_id=c.initiatives[d["initiative"]].id,
        is_template=d.get("template", False),
    )
    c.session.add(project)
    await c.session.flush()
    c.projects[project.name] = project
    c.ids["projects"].append(project.id)
    share(
        c,
        Tool.project,
        project,
        c.users[d["owner"]],
        writers=d.get("writers", ()),
        readers=d.get("readers", ()),
        roles=d.get("roles", ()),
        general=d.get("general"),
    )
    tag(c, project, d.get("tags", ()))
    statuses = {
        status.category: status
        for status in await ensure_default_statuses(c.session, project.id, locale="en")
    }
    types = {
        task_type.name: task_type
        for task_type in await ensure_default_types(c.session, project.id, locale="en")
    }
    for position, td in enumerate(d.get("tasks", ())):
        status = resolve_status(statuses, td["category"])
        # A task names its type ("Bug"), or is a Task.
        task_type = types.get(td.get("type", "Task"), types["Task"])
        await _create_task(c, project, status, task_type, position, td)
    # Once every task exists, so a task may wait on, or be part of, one listed
    # after it.
    for td in d.get("tasks", ()):
        if td.get("part_of"):
            await relationships_service.create(
                c.session,
                source=relationships_service.Endpoint(
                    SearchEntityType.task, c.tasks[td["title"]].id
                ),
                relationship_type=RelationshipType.part_of,
                target=relationships_service.Endpoint(
                    SearchEntityType.task, c.tasks[td["part_of"]].id
                ),
                created_by=c.users[d["owner"]].id,
            )
        for title in td.get("waits_on", ()):
            await relationships_service.create(
                c.session,
                source=relationships_service.Endpoint(
                    SearchEntityType.task, c.tasks[td["title"]].id
                ),
                relationship_type=RelationshipType.depends_on,
                target=relationships_service.Endpoint(
                    SearchEntityType.task, c.tasks[title].id
                ),
                created_by=c.users[d["owner"]].id,
            )
    if d.get("archived_days_ago") is not None:
        c.archives.append((project, NOW - timedelta(days=d["archived_days_ago"])))
    await c.session.flush()
    return project


async def _create_task(
    c: Community,
    project: Project,
    status: TaskStatus,
    task_type: TaskType,
    position: int,
    td: dict,
) -> None:
    due, start = td.get("due_days"), td.get("start_days")
    task = Task(
        project_id=project.id,
        task_status_id=status.id,
        task_type_id=task_type.id,
        title=td["title"],
        description=td.get("description"),
        priority=td["priority"],
        position=float(position),
        due_date=NOW + timedelta(days=due) if due is not None else None,
        start_date=NOW + timedelta(days=start) if start is not None else None,
        checklist=[
            {
                "id": mint_checklist_item_id(),
                "text": text,
                "done": td.get("checklist_done", False),
            }
            for text in td.get("checklist", ())
        ],
    )
    # Done-ness and completed_at always agree, as they do on every write path.
    sync_completed_at(task, status.category, now=NOW)
    c.session.add(task)
    await c.session.flush()
    c.tasks[task.title] = task
    c.ids["tasks"].append(task.id)
    for name in td.get("assignees", ()):
        c.session.add(TaskAssignee(task_id=task.id, user_id=c.users[name].id))
    tag(c, task, td.get("tags", ()))
    if td.get("archived"):
        c.archives.append((task, NOW))


async def apply_archives(c: Community) -> None:
    """Archive the rows that asked for it, now that they have contents.

    Archived content takes no writes, so statuses, tasks, tags, comments and
    bookmarks all have to be in place first — the order a real archive
    happens in. Archiving stamps one moment across everything it touched; the
    whole set is then moved to the date the def asked for, so the tasks inside
    still read as archived with their project and unarchiving still puts back
    exactly this much.
    """
    for entity, archived_at in c.archives:
        stamped = await archive_entity(c.session, entity)
        if stamped == archived_at:
            continue
        for model in archive_models():
            await c.session.exec(
                update(model)
                .where(model.archived_at == stamped)
                .values(archived_at=archived_at)
                .execution_options(synchronize_session=False)
            )
    c.archives.clear()
    await c.session.flush()
