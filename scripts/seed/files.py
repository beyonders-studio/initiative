"""Files: native pages and spreadsheets, what they are attached to, and
what their bodies name in one another."""

from __future__ import annotations

from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.core.file_types import FileType
from app.models.tenant.file import File
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.tenant import relationships as relationships_service

from seed.common import Community, lexical, para, share, tag

# --- spreadsheets -----------------------------------------------------------

# The seeded workbook is the shape people actually build: a working sheet
# nobody else should have to read, a clean order form that pulls from it by
# cross-sheet reference, and a summary of aggregates. It exercises the bits
# that are easy to break — formulas reading other formula cells, references
# across tabs, hidden helper columns, frozen headers, currency and percent
# formats — so a dev environment has something real to open.

_MONEY = {"type": "currency", "currency": "USD", "decimals": 2, "grouping": True}
_PERCENT = {"type": "percent", "decimals": 1}
_HEAD = {"style": {"bold": True, "fill": "#e8eaf0"}}


def _sheet(
    sheet_id: str,
    name: str,
    *,
    cells: dict,
    columns: dict | None = None,
    rows: dict | None = None,
    cell_styles: dict | None = None,
    frozen: dict | None = None,
    dimensions: dict | None = None,
) -> dict:
    return {
        "id": sheet_id,
        "name": name,
        "dimensions": dimensions or {"rows": 100, "cols": 26},
        "cells": cells,
        "columns": columns or {},
        "rows": rows or {},
        "cellStyles": cell_styles or {},
        "frozen": frozen or {"rows": 0, "cols": 0},
    }


def spreadsheet_workbook(
    *,
    order_title: str,
    unit_label: str,
    items: list[tuple[str, int, float]],
    tax_rate: float,
) -> dict:
    """A three-sheet workbook: Order form, Working, Summary.

    ``items`` is ``(name, quantity, unit price)``; prices carry fractions on
    purpose so ``=(C2-INT(C2))`` has something to show.
    """
    first_row = 1  # row index of the first item (A1 row 2)
    last_row = first_row + len(items) - 1
    total_row = last_row + 2

    # --- Working: the sheet the orderer never has to look at ---------------
    work: dict = {
        "0:0": unit_label,
        "0:1": "Qty",
        "0:2": "Unit price",
        "0:3": "Line total",
        "0:4": "Tax",
        "0:5": "Part of a unit",
    }
    for offset, (label, qty, price) in enumerate(items):
        r = first_row + offset
        n = r + 1  # the A1 row number
        work[f"{r}:0"] = label
        work[f"{r}:1"] = qty
        work[f"{r}:2"] = price
        work[f"{r}:3"] = f"=B{n}*C{n}"
        # Reads D, which is itself a formula — the shape that used to fail.
        work[f"{r}:4"] = f"=D{n}*{tax_rate}"
        work[f"{r}:5"] = f"=(C{n}-INT(C{n}))"
    work[f"{total_row}:0"] = "Total"
    work[f"{total_row}:3"] = f"=SUM(D{first_row + 1}:D{last_row + 1})"
    work[f"{total_row}:4"] = f"=SUM(E{first_row + 1}:E{last_row + 1})"
    work[f"{total_row}:5"] = f"=D{total_row + 1}+E{total_row + 1}"
    # A note that belongs to whoever maintains the sheet, not to a reader.
    work[f"{total_row + 2}:0"] = "Working notes — hidden from the order form."

    work_columns = {
        "0": {"width": 220},
        "2": {"format": _MONEY},
        "3": {"format": _MONEY},
        # The tax column is the working-out; the order form quotes the total.
        "4": {"format": _MONEY, "hidden": True},
        "5": {"format": {"type": "fixed", "decimals": 2}},
    }
    work_rows = {"0": {"style": _HEAD["style"]}, str(total_row + 2): {"hidden": True}}
    work_styles = {f"{total_row}:0": {"style": {"bold": True}}}
    for col in (3, 4, 5):
        work_styles[f"{total_row}:{col}"] = {"style": {"bold": True}}

    # --- Order form: everything by reference, nothing to scroll past -------
    order: dict = {
        "0:0": order_title,
        "2:0": unit_label,
        "2:1": "Qty",
        "2:2": "Cost",
    }
    for offset in range(len(items)):
        r = 3 + offset
        source = first_row + offset + 1  # A1 row on Working
        order[f"{r}:0"] = f"=Working!A{source}"
        order[f"{r}:1"] = f"=Working!B{source}"
        order[f"{r}:2"] = f"=Working!D{source}"
    sub_row = 3 + len(items) + 1
    order[f"{sub_row}:0"] = "Subtotal"
    order[f"{sub_row}:2"] = f"=SUM(C4:C{3 + len(items)})"
    order[f"{sub_row + 1}:0"] = "Tax"
    order[f"{sub_row + 1}:2"] = f"=Working!E{total_row + 1}"
    order[f"{sub_row + 2}:0"] = "Due"
    order[f"{sub_row + 2}:2"] = f"=Working!F{total_row + 1}"
    order[f"{sub_row + 4}:0"] = "Tax rate applied"
    order[f"{sub_row + 4}:2"] = tax_rate

    order_columns = {"0": {"width": 240}, "2": {"format": _MONEY}}
    order_styles = {
        "0:0": {"style": {"bold": True, "fontSize": 18}},
        "2:0": _HEAD,
        "2:1": _HEAD,
        "2:2": _HEAD,
        f"{sub_row + 2}:0": {"style": {"bold": True}},
        f"{sub_row + 2}:2": {"style": {"bold": True}, "format": _MONEY},
        f"{sub_row + 4}:2": {"format": _PERCENT},
    }

    # --- Summary: the aggregates, several of them newly available ----------
    span = f"Working!D{first_row + 1}:D{last_row + 1}"
    names = f"Working!A{first_row + 1}:A{last_row + 1}"
    summary = {
        "0:0": "Measure",
        "0:1": "Value",
        "1:0": "Lines",
        "1:1": f"=COUNTA({names})",
        "2:0": "Median line",
        "2:1": f"=MEDIAN({span})",
        "3:0": "Largest line",
        "3:1": f"=LARGE({span},1)",
        "4:0": "Smallest line",
        "4:1": f"=SMALL({span},1)",
        "5:0": "Spread",
        "5:1": f"=STDEV({span})",
        "6:0": "Biggest line is",
        "6:1": f"=INDEX({names},MATCH(LARGE({span},1),{span},0))",
        "7:0": "Everything, listed",
        "7:1": f'=UPPER(TEXTJOIN(", ",TRUE,{names}))',
        "8:0": "First price, fractional part",
        "8:1": f"=(Working!C{first_row + 1}-INT(Working!C{first_row + 1}))",
    }
    summary_columns = {"0": {"width": 220}, "1": {"width": 260}}
    summary_styles = {
        "0:0": _HEAD,
        "0:1": _HEAD,
        "2:1": {"format": _MONEY},
        "3:1": {"format": _MONEY},
        "4:1": {"format": _MONEY},
        "5:1": {"format": _MONEY},
    }

    return {
        "schema_version": 3,
        "kind": "spreadsheet",
        "sheets": [
            _sheet(
                "s1",
                "Order form",
                cells=order,
                columns=order_columns,
                cell_styles=order_styles,
                frozen={"rows": 3, "cols": 0},
            ),
            _sheet(
                "s2",
                "Working",
                cells=work,
                columns=work_columns,
                rows=work_rows,
                cell_styles=work_styles,
                frozen={"rows": 1, "cols": 1},
            ),
            _sheet(
                "s3",
                "Summary",
                cells=summary,
                columns=summary_columns,
                cell_styles=summary_styles,
                frozen={"rows": 1, "cols": 0},
            ),
        ],
    }


#: Each file. ``paragraphs`` make a native page; a spreadsheet brings its
#: own ``content`` and ``file_type``. ``projects`` it is attached to (by
#: its creator) and ``links`` — other files its body names.
FILES: dict[str, list[dict]] = {
    "primary": [
        {
            "title": "Party Provisioning Ledger",
            "initiative": "strahd",
            "creator": "Dungeon Master",
            "file_type": FileType.sheet,
            "general": ResourceAccessLevel.read,
            "content": spreadsheet_workbook(
                order_title="Vallaki Market — Party Order",
                unit_label="Supply",
                items=[
                    ("Rations (1 day)", 40, 0.55),
                    ("Torches", 25, 0.12),
                    ("Holy water flask", 6, 24.75),
                    ("Silvered arrows (20)", 4, 61.4),
                    ("Wolfsbane sprig", 12, 9.25),
                    ("Healer's kit", 3, 5.8),
                    ("Riding horse", 2, 74.5),
                    ("Cart repairs", 1, 18.35),
                ],
                tax_rate=0.08,
            ),
        },
        {
            "title": "Campaign Setting: The Land of Barovia",
            "initiative": "strahd",
            "creator": "Dungeon Master",
            "writers": ["Admin User"],
            "readers": ["Thorn Ironforge", "Elara Moonwhisper"],
            "general": ResourceAccessLevel.read,
            "paragraphs": [
                "Barovia is a demiplane of dread, shrouded in perpetual mist. The land "
                "is ruled by Count Strahd von Zarovich, a vampire lord who has cursed "
                "this realm for centuries.",
                "No one enters or leaves without Strahd's permission. The sun never "
                "truly shines here, and the people live in constant fear of the "
                "creatures that stalk the night.",
                "Key locations: Village of Barovia, Vallaki, Krezk, the Amber Temple, "
                "Castle Ravenloft, Old Bonegrinder, Argynvostholt, and Yester Hill.",
            ],
            "tags": ["lore"],
            "projects": ["Barovia Arc"],
        },
        {
            "title": "NPC Roster: Curse of Strahd",
            "initiative": "strahd",
            "creator": "Dungeon Master",
            "roles": [("strahd", ResourceAccessLevel.read)],
            "paragraphs": [
                "Strahd von Zarovich — The vampire lord of Barovia. Ancient, cunning, "
                "and tragically cursed.",
                "Ireena Kolyana — Adopted daughter of the burgomaster. Strahd believes "
                "she is Tatyana reborn.",
                "Ismark the Lesser — Ireena's brother, desperate to protect her.",
                "Madam Eva — Vistani seer who reads the party's fortune with the Tarokka deck.",
                "Kasimir Velikov — Dusk elf mage who seeks to resurrect his sister from "
                "the Amber Temple.",
                "Ezmerelda d'Avenir — Monster hunter and Van Richten's former protege.",
            ],
            "tags": ["NPC", "lore"],
            "projects": ["Barovia Arc"],
            "links": ["Campaign Setting: The Land of Barovia"],
        },
        {
            "title": "NPC Compendium: Phandelver",
            "initiative": "lmop",
            "creator": "Admin User",
            "writers": ["Dungeon Master"],
            "paragraphs": [
                "Key NPCs: Gundren Rockseeker (quest giver), Sildar Hallwinter (Lords' "
                "Alliance agent), Sister Garaele (Harper contact in Phandalin), "
                "Nezznar the Black Spider (main antagonist), Glasstaff/Iarno Albrek "
                "(Redbrand leader).",
                "Phandalin Townfolk: Toblen Stonehill (innkeeper), Elmar Barthen "
                "(merchant), Linene Graywind (Lionshield Coster), Harbin Wester "
                "(cowardly townmaster).",
            ],
            "tags": ["NPC"],
            "projects": ["Phandalin Adventures"],
        },
        {
            "title": "Session 1 Recap: Into the Mists",
            "initiative": "default",
            "creator": "Dungeon Master",
            "readers": [
                "Thorn Ironforge",
                "Elara Moonwhisper",
                "Vex Shadowstep",
                "Seraphina Dawnlight",
            ],
            "paragraphs": [
                "The party received a mysterious letter and traveled to the village of "
                "Barovia. After surviving the Death House, they met Ismark and Ireena.",
                "The session ended with the party heading toward the church in the "
                "village center. Next session: travel to Vallaki.",
            ],
            "projects": ["Session Zero & Planning"],
            "links": [
                "Campaign Setting: The Land of Barovia",
                "NPC Roster: Curse of Strahd",
            ],
        },
        {
            "title": "Session 2 Recap: The Road to Vallaki",
            "initiative": "default",
            "creator": "Dungeon Master",
            "paragraphs": [
                "The party escorted Ireena through the Svalich Woods, fighting off dire "
                "wolves. They discovered the windmill at Old Bonegrinder was inhabited "
                "by night hags.",
                "Arrived at Vallaki and met Baron Vargas Vallakovich, who insists that "
                "'All Will Be Well.'",
            ],
            "projects": ["Session Zero & Planning"],
            "links": [
                "Campaign Setting: The Land of Barovia",
                "NPC Roster: Curse of Strahd",
            ],
        },
        {
            "title": "Session 3 Recap: Festival of the Blazing Sun",
            "initiative": "default",
            "creator": "Dungeon Master",
            "paragraphs": [
                "The Baron's festival went horribly wrong. The wicker sun failed to "
                "light, and the crowd nearly rioted. The party intervened to prevent "
                "bloodshed.",
                "Vex discovered a secret stash of bones beneath St. Andral's church. A "
                "vampire spawn attacked during the night.",
            ],
            "projects": ["Session Zero & Planning"],
            "links": ["NPC Roster: Curse of Strahd"],
        },
        {
            "title": "Tarokka Card Reading Results",
            "initiative": "strahd",
            "creator": "Dungeon Master",
            "paragraphs": [
                "The Tome of Strahd: Look for a wizard's tower on a lake (Van Richten's Tower).",
                "The Holy Symbol of Ravenkind: In a castle of bones (Argynvostholt).",
                "The Sunsword: A fallen temple of amber (Amber Temple).",
                "Strahd's Enemy: A young woman who has lost her family (Ezmerelda).",
                "Strahd's Location: The heart of his castle — the throne room.",
            ],
            "tags": ["lore", "items/loot"],
            "projects": ["Barovia Arc"],
            "links": ["Campaign Setting: The Land of Barovia"],
        },
        {
            "title": "DM Notes: Strahd's True Motives",
            "initiative": "strahd",
            "creator": "Dungeon Master",
            "paragraphs": [
                "Strahd is not hunting the party — he is auditioning them. He wants a "
                "successor who can break the curse he no longer believes he deserves "
                "to escape.",
                "If the players read this document, the seed data's private share "
                "status is broken.",
            ],
        },
        {
            "title": "House Rules v2",
            "initiative": "default",
            "creator": "Dungeon Master",
            "writers": ["Admin User"],
            "general": ResourceAccessLevel.write,
            "paragraphs": [
                "1. Critical hits: Roll damage dice twice plus modifiers (no doubling modifiers).",
                "2. Potions: Drinking a potion is a bonus action. Feeding one to "
                "another is an action.",
                "3. Inspiration: Can be given to other players. Max 1 at a time.",
                "4. Death saves: Hidden from other players unless Medicine check DC 10.",
                "5. Flanking: +2 bonus instead of advantage.",
            ],
            "tags": ["combat"],
            "projects": ["Homebrew Rules"],
            "links": ["Session 1 Recap: Into the Mists"],
        },
    ],
    "starforge": [
        {
            "title": "Fleet Requisition Sheet",
            "initiative": "starfall",
            "creator": "Admin User",
            "file_type": FileType.sheet,
            "general": ResourceAccessLevel.read,
            "content": spreadsheet_workbook(
                order_title="Exodus Fleet — Quartermaster Requisition",
                unit_label="Component",
                items=[
                    ("Hull plating (m²)", 180, 42.3),
                    ("Coolant cell", 24, 118.75),
                    ("Cryopod servicing", 60, 33.6),
                    ("Nav-computer core", 2, 2450.9),
                    ("Ration paste (crate)", 95, 7.45),
                    ("Atmo scrubber filter", 40, 21.15),
                    ("Jump drive capacitor", 3, 880.25),
                    ("Hydroponics seed tray", 18, 14.7),
                ],
                tax_rate=0.05,
            ),
        },
        {
            "title": "Setting Bible: The Exodus Protocol",
            "initiative": "starfall",
            "creator": "Admin User",
            "writers": ["Finley Goldtongue"],
            "readers": ["Kael Windrunner", "Aurelia Brightshield"],
            "paragraphs": [
                "The year is 2487. Earth was rendered uninhabitable by the Cascade "
                "Event — a catastrophic chain reaction in the planet's magnetic field. "
                "The last 50,000 humans fled aboard the Exodus Fleet: 12 ships of "
                "varying size and capability.",
                "The fleet has been traveling for 73 years. Most colonists are in "
                "cryosleep, rotated in shifts. The active crew numbers about 2,000 at "
                "any given time.",
                "FTL travel exists but is expensive and unreliable. The fleet's main "
                "FTL drive can make one jump per month. Smaller scout ships have "
                "limited-range jump drives.",
            ],
            "tags": ["main quest"],
            "projects": ["The Exodus Fleet"],
        },
        {
            "title": "Faction Guide: Krellix Dominion",
            "initiative": "starfall",
            "creator": "Admin User",
            "general": ResourceAccessLevel.read,
            "paragraphs": [
                "The Krellix are a territorial insectoid species that controls a swathe "
                "of space between the fleet and the target system. They are "
                "technologically advanced but not inherently hostile — diplomacy is "
                "possible.",
                "Krellix society is caste-based: Workers, Warriors, Diplomats, and the "
                "Overmind. Trade agreements require approval from a local Diplomat "
                "caste leader.",
            ],
            "tags": ["NPC", "diplomacy"],
            "projects": ["The Exodus Fleet"],
            "links": ["Setting Bible: The Exodus Protocol"],
        },
        {
            "title": "One-Shot: Smuggler's Run Briefing",
            "initiative": "fringe",
            "creator": "Finley Goldtongue",
            "roles": [("fringe", ResourceAccessLevel.write)],
            "paragraphs": [
                "Station Omega is a decommissioned military research station now "
                "operated by the Crimson Syndicate. Inside the vault: a prototype "
                "cloaking device worth enough credits to fund the fleet for a decade.",
                "The station has 5 levels. Security increases with each level. The "
                "vault is on Level 5. Self-destruct activates 10 minutes after the "
                "vault is breached.",
            ],
            "tags": ["stealth", "loot"],
            "projects": ["Smuggler's Run"],
            "links": ["Setting Bible: The Exodus Protocol"],
        },
        {
            "title": "Session 1 Recap: Into the Void",
            "initiative": "default",
            "creator": "Admin User",
            "paragraphs": [
                "The crew awoke from cryosleep to find the fleet's AI, ORACLE, had gone "
                "silent. Emergency protocols activated. The FTL drive was offline.",
                "The team discovered sabotage — someone had manually overridden "
                "ORACLE's core directives. Suspicion fell on the Deck 7 separatists.",
            ],
            "projects": ["Campaign Planning"],
            "links": ["Setting Bible: The Exodus Protocol"],
        },
    ],
    "tides": [
        {
            "title": "Crimson Maiden Cargo Manifest",
            "initiative": "crimson",
            "creator": "Finley Goldtongue",
            "file_type": FileType.sheet,
            "general": ResourceAccessLevel.read,
            "content": spreadsheet_workbook(
                order_title="Port of Saltmere — Cargo Order",
                unit_label="Cargo",
                items=[
                    ("Salt pork (barrel)", 30, 11.65),
                    ("Fresh water (cask)", 45, 3.4),
                    ("Sailcloth (bolt)", 12, 27.85),
                    ("Hemp rope (coil)", 20, 8.95),
                    ("Powder keg", 8, 96.2),
                    ("Lime (crate)", 15, 5.75),
                    ("Chart of the Shoals", 2, 145.5),
                    ("Carpenter's stores", 1, 63.1),
                ],
                tax_rate=0.12,
            ),
        },
        {
            "title": "The Shattered Seas: World Guide",
            "initiative": "crimson",
            "creator": "Finley Goldtongue",
            "writers": ["Dungeon Master"],
            "readers": ["Admin User", "Thorn Ironforge"],
            "general": ResourceAccessLevel.read,
            "paragraphs": [
                "The Shattered Seas are a vast archipelago formed when the old "
                "continent sank a thousand years ago. Hundreds of islands dot the warm "
                "waters, from volcanic peaks to coral atolls.",
                "Major factions: The Imperial Navy (law and order), the Pirate Lords "
                "(freedom and chaos), the Coral Elves (ancient guardians), and the "
                "Deep Ones (mysterious undersea dwellers).",
                "Currency: Gold doubloons, silver pieces, and trade goods. A good ship "
                "is worth more than gold — it's your life.",
            ],
            "tags": ["exploration"],
            "projects": ["Treasure of the Leviathan"],
        },
        {
            "title": "Crew Manifest: The Crimson Maiden",
            "initiative": "crimson",
            "creator": "Finley Goldtongue",
            "paragraphs": [
                "Captain: Finley 'Goldtongue' Ashford — Bard/Swashbuckler. Charisma is "
                "the real weapon.",
                "First Mate: Thorn Ironforge — Fighter/Battlemaster. Handles boarding actions.",
                "Navigator: Kael Windrunner — Ranger/Horizon Walker. Reads the stars and tides.",
                "Quartermaster: Aurelia Brightshield — Paladin of the Sea. Keeps the crew honest.",
                "Ship's Chaplain: Seraphina Dawnlight — Cleric of the Tide Mother.",
                "Crew complement: 47 sailors, 12 marines, 3 officers.",
            ],
            "tags": ["NPC"],
            "projects": ["The Crimson Maiden"],
            "links": ["The Shattered Seas: World Guide"],
        },
        {
            "title": "Intelligence Report: Admiral Blackwood",
            "initiative": "navy",
            "creator": "Dungeon Master",
            "readers": ["Finley Goldtongue", "Thorn Ironforge"],
            "roles": [("navy", ResourceAccessLevel.read)],
            "paragraphs": [
                "Admiral Helena Blackwood commands the 3rd Imperial Fleet from her "
                "flagship, the HMS Vengeance (a 74-gun ship of the line). She is "
                "ruthless, brilliant, and has a personal vendetta against Captain "
                "Ashford.",
                "Known ships: HMS Vengeance (flagship), HMS Ironclad (sunk by party), "
                "HMS Stormbreak, HMS Resolute, plus 8 frigates and 12 sloops.",
                "Weakness: Blackwood's supply lines are stretched thin. Hit the convoys.",
            ],
            "tags": ["NPC", "naval combat"],
            "projects": ["Admiral Blackwood's Fleet"],
            "links": ["The Shattered Seas: World Guide"],
        },
        {
            "title": "Session 5 Recap: The Kraken's Fury",
            "initiative": "default",
            "creator": "Finley Goldtongue",
            "paragraphs": [
                "The Crimson Maiden was ambushed by a kraken near the Abyssal Trench. "
                "The battle was fierce — we lost 6 crew and the mainmast before "
                "driving the beast off with alchemist's fire.",
                "Limped into Port Havoc for repairs. Made contact with a fence who "
                "claims to know a translator for the Leviathan Map.",
            ],
            "projects": ["Campaign Notes"],
            "links": [
                "Crew Manifest: The Crimson Maiden",
                "The Shattered Seas: World Guide",
            ],
        },
        {
            "title": "Session 4 Recap: The Ironclad Falls",
            "initiative": "default",
            "creator": "Finley Goldtongue",
            "paragraphs": [
                "Ambushed the HMS Ironclad in a fog bank near Dagger Isle. Thorn led "
                "the boarding party while Kael maneuvered us alongside. The Ironclad's "
                "captain surrendered after we took the helm.",
                "Salvaged: 200 gold doubloons, 50 barrels of gunpowder, a chest of "
                "maps, and the enchanted compass (which turned out to be a Tidestone "
                "detector).",
            ],
            "projects": ["Campaign Notes"],
            "links": [
                "Intelligence Report: Admiral Blackwood",
                "Crew Manifest: The Crimson Maiden",
            ],
        },
    ],
}


async def seed(c: Community) -> None:
    for d in FILES[c.key]:
        creator = c.users[d["creator"]]
        doc = File(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["title"],
            content=d.get("content")
            or lexical([para(text) for text in d["paragraphs"]]),
            file_type=d.get("file_type", FileType.lexical),
            created_by=creator.id,
        )
        c.session.add(doc)
        await c.session.flush()
        c.files[doc.name] = doc
        c.ids["files"].append(doc.id)
        share(
            c,
            Tool.file,
            doc,
            creator,
            writers=d.get("writers", ()),
            readers=d.get("readers", ()),
            roles=d.get("roles", ()),
            general=d.get("general"),
        )
        tag(c, doc, d.get("tags", ()))
        for name in d.get("projects", ()):
            await relationships_service.create(
                c.session,
                source=relationships_service.Endpoint(
                    SearchEntityType.project, c.projects[name].id
                ),
                relationship_type=RelationshipType.attached,
                target=relationships_service.Endpoint(SearchEntityType.file, doc.id),
                created_by=creator.id,
            )
    # A wikilink is a ``references`` edge with ``content`` provenance — what
    # the save-path sync writes when it reads a body. Every file exists by
    # now, so any may name any other.
    for d in FILES[c.key]:
        for target in d.get("links", ()):
            await relationships_service.create(
                c.session,
                source=relationships_service.Endpoint(
                    SearchEntityType.file, c.files[d["title"]].id
                ),
                relationship_type=RelationshipType.references,
                target=relationships_service.Endpoint(
                    SearchEntityType.file, c.files[target].id
                ),
                provenance=Provenance.content,
            )
            c.ids["content_references"].append((d["title"], target))
    await c.session.flush()
