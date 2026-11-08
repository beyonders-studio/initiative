"""Wikis and their pages.

They differ mostly in their settings, which is the thing the tool is for: a
setting bible nobody could hand-order sorts by title, a rules page read front
to back once keeps the order somebody chose, and a handbook reads at a
comfortable measure.
"""

from __future__ import annotations

from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.wiki import Wiki, WikiPage, WikiPageOrder, WikiReadingWidth
from app.services.tenant import relationships as relationships_service
from app.services.tenant.names import slugify
from seed.common import Community, chip, heading, lexical, para, share, tag

#: Each wiki, shared with the initiative for reading; the display settings
#: each default to what a wiki arrives with. ``home`` is the page it opens on
#: and ``template`` the one new pages are copied from.
#:
#: A page is an ``intro`` then ``sections`` under their own headings — the
#: contents list in the sidebar is built from those; a section is one
#: paragraph or a list of them. ``links``
#: close the page as a "See also": ``"Vallaki"`` is a page of the same wiki,
#: ``"Other wiki::Vallaki"`` a page of another, and ``("task", title)`` any
#: task or file the community already has.
WIKIS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Barovia gazetteer",
            "initiative": "strahd",
            "description": "Every place, person and faction the table has met.",
            "created_by": "Dungeon Master",
            "tags": ["lore"],
            "page_order": WikiPageOrder.title,
            "reading_width": WikiReadingWidth.comfortable,
            "accent_color": "#8b5cf6",
            "home": "Barovia",
            "template": "Entry template",
            "pages": [
                {
                    "title": "Barovia",
                    "created_by": "Dungeon Master",
                    "tags": ["lore"],
                    "intro": "A valley under permanent cloud, walled in by mist that "
                    "turns travellers back the way they came.",
                    "sections": {
                        "Where to start": [
                            (
                                "Start with Vallaki if the party has just arrived. Start "
                                "with Castle Ravenloft if they have done something unwise."
                            ),
                            "Everything below is somewhere in this valley. Nothing leaves it.",
                        ],
                        "The weather": "Overcast, always. Rain most evenings. The sun "
                        "is a rumour the older villagers repeat without conviction.",
                        "Getting out": "You do not. The mists return you to the road "
                        "you came in on, a day older and no further along.",
                    },
                    "links": [
                        "Vallaki",
                        "Castle Ravenloft",
                        ("file", "Campaign Setting: The Land of Barovia"),
                    ],
                },
                {
                    "title": "Entry template",
                    "created_by": "Dungeon Master",
                    "intro": "Copy this for a new place, person or faction. Delete what "
                    "does not apply; do not delete the headings.",
                    "sections": {
                        "What it is": "One sentence. No more.",
                        "What the party knows": "Only what happened at the table.",
                        "What they do not": "And what it would cost to find out. This "
                        "is the part worth writing down.",
                        "Who to ask": "Names, and where they usually are.",
                    },
                },
                {
                    "title": "Vallaki",
                    "created_by": "Dungeon Master",
                    "tags": ["exploration"],
                    "intro": "A walled town that insists everything is fine. Festivals "
                    "weekly, by order of the Baron.",
                    "sections": {
                        "The wall": "Closed at dusk and opened at dawn, and the guards "
                        "mean it. Arriving late means a night outside, which is how "
                        "most parties meet their first wolf.",
                        "Who runs it": "Baron Vargas Vallakovich, officially. The "
                        "Church of St. Andral, in practice, for anybody who needs "
                        "something done.",
                        "Where to sleep": "The Blue Water Inn, and nowhere else. The "
                        "other two beds in town are in the gaol.",
                    },
                    "links": [
                        "The Blue Water Inn",
                        "St. Andral's Church",
                        ("task", "Escort Ireena to Vallaki"),
                    ],
                },
                {
                    "title": "The Blue Water Inn",
                    "created_by": "Elara Moonwhisper",
                    "intro": "Run by the Martikovs, who are not what they appear and "
                    "would rather that stayed the case.",
                    "sections": {
                        "The family": "Urwin and Danika run the room. Their sons are "
                        "missing, which nobody will say out loud until you have been "
                        "drinking there a while.",
                        "What you can learn here": "More than anywhere else in Vallaki. "
                        "Buy a round and let Rictavio talk.",
                    },
                    "links": ["Vallaki"],
                },
                {
                    "title": "St. Andral's Church",
                    "created_by": "Seraphina Dawnlight",
                    "tags": ["quest"],
                    "intro": "The only consecrated ground for a day's ride, and it is "
                    "consecrated because of what is under the floor.",
                    "sections": {
                        "Father Lucian": "Knows what the bones do. Has told nobody, on "
                        "the grounds that the town would empty by morning.",
                        "The bones": "Gone, as of session three. The wards hold for now "
                        "and everyone is pretending not to count the days.",
                    },
                    "links": [
                        "Vallaki",
                        ("file", "Session 3 Recap: Festival of the Blazing Sun"),
                    ],
                },
                {
                    "title": "Castle Ravenloft",
                    "created_by": "Dungeon Master",
                    "tags": ["lore"],
                    "intro": "Strahd's seat, and the last place anybody should go first.",
                    "sections": {
                        "Ways in": "The ground floor alone has four, three of which are "
                        "a mistake. The front door is the one he expects and therefore "
                        "the safest.",
                        "What is actually here": "The Heart of Sorrow, the crypts, and "
                        "every treasure the Tarokka reading might have pointed at. "
                        "Read the cards before you plan the raid.",
                        "The welcome": "Dinner. He will insist. Declining is a choice "
                        "with consequences and so is accepting.",
                    },
                    "links": [
                        "The dining hall",
                        ("task", "Map Castle Ravenloft's layout"),
                        ("task", "Find the Heart of Sorrow"),
                        ("file", "Tarokka Card Reading Results"),
                    ],
                },
                {
                    "title": "The dining hall",
                    "created_by": "Dungeon Master",
                    "tags": ["roleplay"],
                    "intro": "Set for however many of you there are. It was set before "
                    "you decided to come.",
                    "sections": {
                        "The conversation": "He is a gracious host and a patient one. "
                        "Nothing said at this table is idle.",
                        "Leaving": "Permitted. That is the unsettling part.",
                    },
                    "links": ["Castle Ravenloft"],
                },
                {
                    "title": "The Village of Barovia",
                    "created_by": "Thorn Ironforge",
                    "intro": "Not the valley. The village, which shares its name and "
                    "roughly none of its energy.",
                    "sections": {
                        "The mood": "Nobody has swept anything in a year. The doors are "
                        "shut in the afternoon.",
                        "The Burgomaster's house": "Where Ireena was, and where the "
                        "party's involvement in all of this starts.",
                    },
                    "links": ["Bildrath's Mercantile", "Barovia"],
                },
                {
                    "title": "Bildrath's Mercantile",
                    "created_by": "Vex Shadowstep",
                    "tags": ["items/loot"],
                    "intro": "The only shop, at ten times the price, because where else "
                    "are you going to go.",
                    "sections": {
                        "Prices": "Ten times. He will not haggle and he is not bluffing "
                        "about that.",
                        "What is worth it anyway": "Rope. Oil. Anything silver, if he has it.",
                    },
                    "links": [("file", "Party Provisioning Ledger")],
                },
                {
                    "title": "Krezk",
                    "created_by": "Dungeon Master",
                    "intro": "A walled village that does not want visitors and says so "
                    "at the gate.",
                    "sections": {
                        "Getting in": "Bring wine, or bring the Abbot's name, or turn around.",
                        "The Abbey": "Above the village. The Abbot is helpful, "
                        "courteous, and the single most alarming person in the valley.",
                    },
                },
                {
                    "title": "The Amber Temple",
                    "is_draft": True,
                    "created_by": "Dungeon Master",
                    "tags": ["lore", "items/loot"],
                    "intro": "High in the mountains, cold, and full of things offering help.",
                    "sections": {
                        "The vestiges": "Each one is a bargain. Each bargain is worse "
                        "than it sounds and better than it looks.",
                        "Why anybody comes here": "The Sunsword, usually, if the cards "
                        "sent them. Otherwise: ambition.",
                    },
                    "links": [("task", "Find the Sunsword in the Amber Temple")],
                },
                {
                    "title": "Tser Pool",
                    "created_by": "Elara Moonwhisper",
                    "tags": ["NPC", "roleplay"],
                    "intro": "A Vistani camp by the water, and the one place in Barovia "
                    "where somebody is having a nice evening.",
                    "sections": {
                        "Madam Eva": "Reads the cards once. Do not ask for a second "
                        "reading; she has already told you what she is going to tell "
                        "you.",
                        "The camp": "Hospitable, watchful, and not on anybody's side but its own.",
                    },
                    "links": [
                        ("task", "Negotiate with the Vistani caravan"),
                        ("file", "Tarokka Card Reading Results"),
                    ],
                },
            ],
        },
        {
            "name": "Rules we actually use",
            "initiative": "strahd",
            "description": "House rules, in the order they come up at the table.",
            "created_by": "Dungeon Master",
            "page_order": WikiPageOrder.manual,
            "reading_width": WikiReadingWidth.comfortable,
            "contents_depth": 2,
            "accent_color": "#ef4444",
            "home": "The short version",
            "pages": [
                {
                    "title": "The short version",
                    "created_by": "Dungeon Master",
                    "intro": "Six rules. If you remember none of them the game still "
                    "works, because the DM remembers them.",
                    "sections": {
                        "The six": "Inspiration is handed out, not requested. Death "
                        "saves are rolled in the open. Flanking gives advantage. A "
                        "natural 1 is a miss and nothing else. Potions are a bonus "
                        "action to drink and an action to give. You may retrain one "
                        "thing per level."
                    },
                    "links": ["Rolling in the open", ("file", "House Rules v2")],
                },
                {
                    "title": "Rolling in the open",
                    "created_by": "Dungeon Master",
                    "intro": "Every roll that could kill somebody happens where "
                    "everyone can see it.",
                    "sections": {
                        "Why": "Because a death nobody watched land feels arbitrary, "
                        "and a death everybody watched land is a story.",
                        "The exception": "Perception against something hidden. Telling "
                        "you the number tells you the answer.",
                    },
                },
                {
                    "title": "Inspiration",
                    "created_by": "Dungeon Master",
                    "intro": "Given for playing your character in a way that cost you something.",
                    "sections": {
                        "How to get it": "You do not ask. Ask and the answer is no, warmly.",
                        "How to spend it": "Before the roll. You hold one at a time and "
                        "it does not carry between sessions.",
                    },
                },
                {
                    "title": "Resting",
                    "created_by": "Thorn Ironforge",
                    "intro": "Barovia does not let you rest the way the book assumes, "
                    "so this page exists.",
                    "sections": {
                        "Short rests": "An hour, and something usually interrupts it.",
                        "Long rests": "Somewhere safe, which in this valley means "
                        "consecrated, walled, or watched by somebody the party trusts.",
                    },
                    "links": [
                        "Barovia gazetteer::St. Andral's Church",
                        "The short version",
                    ],
                },
                {
                    "title": "Death and what happens after",
                    "created_by": "Dungeon Master",
                    "intro": "Read this before it matters, so nobody is reading it while upset.",
                    "sections": {
                        "At zero": "Three saves, rolled in the open. Healing brings you "
                        "back at one hit point and clears the failures.",
                        "If it goes the other way": "A new character arrives the same "
                        "session, at the party's level, with a reason to be in Barovia "
                        "that you and the DM agree on beforehand.",
                        "Raising the dead": "Possible. Expensive. And the valley takes "
                        "an interest, which is the actual cost.",
                    },
                },
                {
                    "title": "Table etiquette",
                    "created_by": "Seraphina Dawnlight",
                    "intro": "The rules that are not about dice.",
                    "sections": {
                        "Lines and veils": "Agreed in session zero and revisited "
                        "whenever somebody asks. Anybody may call one mid-scene, with "
                        "no explanation owed.",
                        "Phones": "Fine for the character sheet, fine for a photo of "
                        "the map, not fine for the twenty minutes somebody else has "
                        "the spotlight.",
                    },
                },
            ],
        },
        {
            "name": "How this table runs",
            "initiative": "lmop",
            "description": "Session zero, in writing, so nobody has to remember it.",
            "created_by": "Dungeon Master",
            "page_order": WikiPageOrder.manual,
            "reading_width": WikiReadingWidth.comfortable,
            "contents_depth": 2,
            "show_connections": False,
            "accent_color": "#0ea5e9",
            "home": "Start here",
            "pages": [
                {
                    "title": "Start here",
                    "created_by": "Dungeon Master",
                    "intro": "Four pages. Read them once and you will not need them again.",
                    "sections": {
                        "What this is": "Everything the group agreed at session zero, "
                        "written down so it survives somebody missing a week."
                    },
                },
                {
                    "title": "When we play",
                    "created_by": "Dungeon Master",
                    "intro": "Thursdays, 7pm, four hours.",
                    "sections": {
                        "Starting and stopping": "We start on time and finish on time; "
                        "nobody has to apologise for either.",
                        "Missing one": "Say so in the channel by Wednesday. Your "
                        "character is played by nobody and quietly survives.",
                        "Cancelling": "Three players is a session. Two is a board game "
                        "night, which is also fine.",
                    },
                },
                {
                    "title": "What we expect of each other",
                    "created_by": "Elara Moonwhisper",
                    "intro": "Short, and none of it is a surprise.",
                    "sections": {
                        "At the table": "Everybody gets a scene. If you have had three "
                        "and somebody has had none, hand them the next one.",
                        "Between sessions": "Level up before Thursday. Post your recap "
                        "if you said you would.",
                    },
                },
                {
                    "title": "Snacks",
                    "created_by": "Thorn Ironforge",
                    "intro": "A rota, because otherwise it is always the same person "
                    "and that person is Thorn.",
                    "sections": {
                        "The rota": "Whoever hosted least recently brings something. "
                        "There is no enforcement mechanism and there has never needed "
                        "to be one."
                    },
                },
            ],
        },
        {
            "name": "The Phandalin files",
            "initiative": "lmop",
            "description": "The Sword Coast, as far as this party has seen it.",
            "created_by": "Admin User",
            "tags": ["lore"],
            "page_order": WikiPageOrder.title,
            "reading_width": WikiReadingWidth.wide,
            "accent_color": "#10b981",
            "home": "Phandalin",
            "pages": [
                {
                    "title": "Phandalin",
                    "created_by": "Admin User",
                    "tags": ["exploration"],
                    "intro": "A frontier town rebuilding on top of an older one, which "
                    "is the whole plot if you squint.",
                    "sections": {
                        "Who is in charge": "Townmaster Harbin Wester, who would rather "
                        "not be, and the Redbrands, who very much are.",
                        "Where to go first": "Stonehill Inn for rumours, Barthen's for "
                        "supplies, Tresendar Manor when the party is ready for a "
                        "fight.",
                    },
                    "links": [
                        "Tresendar Manor",
                        ("task", "Clear the Redbrand Hideout"),
                        ("file", "NPC Compendium: Phandelver"),
                    ],
                },
                {
                    "title": "Tresendar Manor",
                    "created_by": "Dungeon Master",
                    "tags": ["combat"],
                    "intro": "A burnt-out house with a working cellar, which is the "
                    "part that matters.",
                    "sections": {
                        "The hideout": "Two ways in. The crevice is quieter; the front "
                        "is faster and louder.",
                        "Glasstaff": "Will talk his way out if given the chance, and is "
                        "worth more talking than fighting.",
                    },
                    "links": ["Phandalin"],
                },
                {
                    "title": "Cragmaw Hideout",
                    "created_by": "Dungeon Master",
                    "tags": ["combat", "quest"],
                    "intro": "A cave the goblins took, upstream of the road ambush.",
                    "sections": {
                        "The approach": "Watched. There is a lookout and there is "
                        "always a lookout.",
                        "Why it matters": "Sildar is in it, and Sildar is how the party "
                        "learns what happened to Gundren.",
                    },
                    "links": [("task", "Rescue Gundren Rockseeker")],
                },
                {
                    "title": "Wave Echo Cave",
                    "created_by": "Admin User",
                    "tags": ["quest", "boss fight"],
                    "intro": "The lost mine. The reason all of this started and the place it ends.",
                    "sections": {
                        "The Forge of Spells": "Still working, after everything. That "
                        "is the surprise the last session is built on.",
                        "The Black Spider": "Here, and expecting them. He has been "
                        "ahead of the party since session one.",
                    },
                    "links": [
                        ("task", "Defeat the Black Spider in Wave Echo Cave"),
                        ("task", "Activate the Forge of Spells"),
                    ],
                },
                {
                    "title": "Neverwinter Wood",
                    "created_by": "Elara Moonwhisper",
                    "tags": ["exploration"],
                    "intro": "Everything between the towns, and nothing in it is on the road.",
                    "sections": {
                        "Travel": "Two days to anywhere. One if the party knows "
                        "somebody who knows the paths.",
                        "Who lives here": "Reidoth, when he wants to be found, which is "
                        "rarely and never conveniently.",
                    },
                },
                {
                    "title": "Thundertree",
                    "created_by": "Vex Shadowstep",
                    "tags": ["exploration", "side quest"],
                    "intro": "A ruined village with ash on everything and a dragon in the tower.",
                    "sections": {
                        "The dragon": "Young, vain, and entirely willing to be "
                        "flattered into a conversation.",
                        "The cultists": "In the old druid's house. They are not subtle "
                        "and they are not expecting company.",
                    },
                    "links": ["Neverwinter Wood"],
                },
            ],
        },
    ],
    "starforge": [
        {
            "name": "Fleet codex",
            "initiative": "starfall",
            "description": "Ships, decks, factions and everything bolted to them.",
            "created_by": "Overseer Nova",
            "tags": ["main quest"],
            "page_order": WikiPageOrder.title,
            "reading_width": WikiReadingWidth.wide,
            "contents_depth": 3,
            "accent_color": "#0ea5e9",
            "home": "The Exodus Fleet",
            "template": "Ship entry",
            "pages": [
                {
                    "title": "The Exodus Fleet",
                    "created_by": "Overseer Nova",
                    "tags": ["main quest"],
                    "intro": "Eleven ships left. Nine are still under power. This is "
                    "what is left of everybody.",
                    "sections": {
                        "How the fleet is organised": "One flagship, three escorts, "
                        "five haulers. The haulers carry the people; everything else "
                        "exists to keep the haulers moving.",
                        "Who decides": "Fleet Command in theory. In practice, whoever "
                        "is awake on the bridge when the alarm goes.",
                        "The standing order": "Find a world. Everything else is a means "
                        "to that and is negotiable.",
                    },
                    "links": [
                        "Ark Perseverance",
                        "Krellix Dominion",
                        ("file", "Setting Bible: The Exodus Protocol"),
                    ],
                },
                {
                    "title": "Ship entry",
                    "created_by": "Overseer Nova",
                    "intro": "Copy this for a new hull. Every ship in the codex has "
                    "these four headings and nothing else.",
                    "sections": {
                        "Class and role": "What it is and what it is for.",
                        "Crew": "Complement, and who is in command.",
                        "Condition": "What is broken. Date it.",
                        "Notes": "Anything the next watch needs.",
                    },
                },
                {
                    "title": "Ark Perseverance",
                    "created_by": "Overseer Nova",
                    "tags": ["engineering"],
                    "intro": "The flagship, and the only hull with a working FTL core. "
                    "Working is doing some lifting in that sentence.",
                    "sections": {
                        "Class and role": "Colony ark, refitted. Command, medical, and "
                        "eleven thousand people in cold storage.",
                        "Condition": "The drive core is the open problem and has been "
                        "since the Sol transit. Everything else on this hull is "
                        "downstream of it.",
                        "Notes": "Deck 7 is a separate conversation and has its own page.",
                    },
                    "links": [
                        "Deck 7",
                        ("task", "Repair the FTL drive core"),
                        ("task", "Upgrade shield generators to Mark IV"),
                    ],
                },
                {
                    "title": "Deck 7",
                    "created_by": "Kael Windrunner",
                    "tags": ["NPC"],
                    "intro": "Hydroponics, berthing, and the part of the ship that "
                    "stopped taking orders in week nine.",
                    "sections": {
                        "What happened": "Rationing, then a rota nobody agreed to, then "
                        "a sealed bulkhead. In that order, over four days.",
                        "Where it stands": "Talking. Not resolved. Anybody going down "
                        "there goes unarmed or does not go.",
                    },
                    "links": [
                        "Ark Perseverance",
                        ("task", "Quell the mutiny on Deck 7"),
                        ("task", "Set up the hydroponics bay"),
                    ],
                },
                {
                    "title": "Krellix Dominion",
                    "created_by": "Aurelia Brightshield",
                    "tags": ["diplomacy", "NPC"],
                    "intro": "They hold the only corridor that goes anywhere, and they "
                    "know exactly what that is worth.",
                    "sections": {
                        "What they want": "Tariff, deference, and a say in where the "
                        "fleet settles. The third one is the problem.",
                        "How they negotiate": "Slowly, formally, and with every word "
                        "recorded. Nothing said to a Krellix envoy is off the record.",
                        "Where we stand": "Passage granted for one transit. It was not "
                        "granted cheaply and it was not granted twice.",
                    },
                    "links": [
                        ("task", "Negotiate passage through Krellix space"),
                        ("file", "Faction Guide: Krellix Dominion"),
                    ],
                },
                {
                    "title": "Kepler-442b",
                    "created_by": "Admin User",
                    "tags": ["exploration", "survival"],
                    "intro": "The candidate. Breathable, cold, and eleven light years "
                    "past the last place anybody wanted to stop.",
                    "sections": {
                        "The survey": "Three landing sites scouted, one viable. The "
                        "viable one is in the southern highlands and nobody likes the "
                        "weather data.",
                        "What is unresolved": "Whether anything already lives there. "
                        "The survey team has an opinion and no evidence.",
                    },
                    "links": [
                        ("task", "Survey landing sites on Kepler-442b"),
                        ("task", "Establish a perimeter defense grid"),
                    ],
                },
                {
                    "title": "Station Omega",
                    "created_by": "Vex Shadowstep",
                    "tags": ["stealth"],
                    "intro": "A relay nobody admits to owning, on the edge of Krellix space.",
                    "sections": {
                        "Getting aboard": "Cargo manifest, forged, and a window of "
                        "nineteen minutes on the docking rotation.",
                        "The vault": "Whatever is in it is worth more than the station. "
                        "That is the entire intelligence picture.",
                    },
                    "links": [
                        ("task", "Infiltrate Station Omega"),
                        ("task", "Crack the vault encryption"),
                    ],
                },
                {
                    "title": "Sector 7G",
                    "is_draft": True,
                    "created_by": "Elara Moonwhisper",
                    "tags": ["exploration"],
                    "intro": "Empty on every chart the fleet carries, and something in "
                    "it is transmitting.",
                    "sections": {
                        "The signal": "Repeating, forty-one second cycle, and in a "
                        "protocol that predates the Exodus.",
                        "What we have not done": "Answered it.",
                    },
                    "links": [
                        ("task", "Investigate the distress signal from Sector 7G")
                    ],
                },
            ],
        },
        {
            "name": "Standing orders",
            "initiative": "starfall",
            "description": "How the fleet runs when nobody is available to ask.",
            "created_by": "Overseer Nova",
            "page_order": WikiPageOrder.manual,
            "reading_width": WikiReadingWidth.comfortable,
            "contents_depth": 2,
            "show_connections": False,
            "accent_color": "#64748b",
            "home": "Read this first",
            "pages": [
                {
                    "title": "Read this first",
                    "created_by": "Overseer Nova",
                    "intro": "Five pages, in the order you will need them.",
                    "sections": {
                        "Who this is for": "Anybody standing a watch. That is "
                        "eventually everybody."
                    },
                },
                {
                    "title": "Rationing",
                    "created_by": "Overseer Nova",
                    "intro": "Set by Fleet Command, reviewed weekly, and not adjustable "
                    "by any individual ship.",
                    "sections": {
                        "The current tier": "Tier two. Full water, eighty percent "
                        "calories, no discretionary power after 2200.",
                        "Appeals": "Medical only, through your ship's surgeon, and they "
                        "are granted more often than people expect.",
                    },
                },
                {
                    "title": "Contact protocol",
                    "created_by": "Aurelia Brightshield",
                    "tags": ["diplomacy"],
                    "intro": "What to do when something answers.",
                    "sections": {
                        "First contact": "Do not transmit. Log, hold position, and wake "
                        "somebody senior. Nothing about this is a judgement call.",
                        "Known parties": "Krellix traffic is routine and has its own "
                        "handshake. Anything else is first contact.",
                    },
                },
                {
                    "title": "Salvage",
                    "created_by": "Finley Goldtongue",
                    "tags": ["loot"],
                    "intro": "Who gets what, decided before anybody is holding it.",
                    "sections": {
                        "The split": "Fleet takes anything structural or medical. The "
                        "crew that pulled it keeps the rest.",
                        "Disputes": "Go to the Overseer, who has never once ruled in "
                        "favour of whoever shouted first.",
                    },
                },
                {
                    "title": "If the drive fails again",
                    "created_by": "Kael Windrunner",
                    "tags": ["engineering"],
                    "intro": "The checklist, in the order it is run, because the last "
                    "time nobody could find it.",
                    "sections": {
                        "Immediate": "Cut the jump sequence, vent the coolant loop, get "
                        "engineering on the deck. Ninety seconds, all three.",
                        "Then": "Fleet-wide hold. Nobody jumps on a core the flagship "
                        "cannot vouch for.",
                    },
                    "links": [("task", "Repair the FTL drive core")],
                },
            ],
        },
        {
            "name": "Fringe space briefings",
            "initiative": "fringe",
            "description": "One job per page. Closed pages stay for the next crew.",
            "created_by": "Finley Goldtongue",
            "tags": ["side quest"],
            "page_order": WikiPageOrder.recently_updated,
            "reading_width": WikiReadingWidth.comfortable,
            "contents_depth": 2,
            "accent_color": "#f59e0b",
            "home": "How a briefing works",
            "template": "Briefing template",
            "pages": [
                {
                    "title": "How a briefing works",
                    "created_by": "Finley Goldtongue",
                    "intro": "Newest at the top, because the one you need is almost "
                    "always the one somebody just edited.",
                    "sections": {
                        "Before the job": "Copy the template, fill in the four "
                        "headings, and put the payout in writing where the crew can "
                        "see it.",
                        "After the job": "Do not delete it. A closed briefing is the "
                        "only record of what the sector was like last time.",
                    },
                },
                {
                    "title": "Briefing template",
                    "created_by": "Finley Goldtongue",
                    "intro": "Four headings. Fill them in before you leave.",
                    "sections": {
                        "The job": "One sentence.",
                        "Who is paying": "And whether they have before.",
                        "What could go wrong": "Be specific. Be pessimistic.",
                        "Payout": "Agreed in advance, in credits, in writing.",
                    },
                },
                {
                    "title": "Smuggler's Run",
                    "created_by": "Vex Shadowstep",
                    "tags": ["stealth", "side quest"],
                    "intro": "Cargo out to the belt, no questions, nineteen hours.",
                    "sections": {
                        "The job": "Move four crates. Do not open the crates.",
                        "What could go wrong": "Somebody opens the crates. It is always "
                        "somebody on our side.",
                        "Payout": "Forty thousand, half up front.",
                    },
                    "links": [("file", "One-Shot: Smuggler's Run Briefing")],
                },
                {
                    "title": "The Coriolis wreck",
                    "created_by": "Aurelia Brightshield",
                    "tags": ["exploration", "loot"],
                    "intro": "A hauler that went quiet six years ago and is still in a "
                    "stable orbit.",
                    "sections": {
                        "The job": "Board, survey, bring back the flight recorder.",
                        "What could go wrong": "Six years is long enough for something "
                        "else to have found it first.",
                        "Payout": "Salvage rights, under the fleet split.",
                    },
                },
                {
                    "title": "Escort: the Tanaka convoy",
                    "created_by": "Finley Goldtongue",
                    "tags": ["combat", "side quest"],
                    "intro": "Three haulers through a corridor that has been quiet for "
                    "two months, which is the part that worries people.",
                    "sections": {
                        "The job": "Get all three through. All three.",
                        "What could go wrong": "Quiet corridors are quiet because "
                        "somebody is waiting to be paid for them.",
                        "Payout": "Fuel, which is better than credits right now.",
                    },
                },
            ],
        },
    ],
    "tides": [
        {
            "name": "The Shattered Seas",
            "initiative": "crimson",
            "description": "Every port, reef and rumour the crew has charted.",
            "created_by": "Archivist Okoro",
            "tags": ["exploration"],
            "page_order": WikiPageOrder.title,
            "reading_width": WikiReadingWidth.comfortable,
            "contents_depth": 3,
            "accent_color": "#0ea5e9",
            "home": "The Shattered Seas",
            "template": "Port entry",
            "pages": [
                {
                    "title": "The Shattered Seas",
                    "created_by": "Archivist Okoro",
                    "tags": ["exploration"],
                    "intro": "Four hundred islands, nine of them worth landing on, and "
                    "one current that decides which.",
                    "sections": {
                        "How to read this": "Ports first, then waters, then the things "
                        "in the waters. Every entry says what the crew saw, not what "
                        "the charts claim.",
                        "The Tide": "Runs anticlockwise and reverses twice a year. Half "
                        "the navigation in this campaign is remembering which half of "
                        "the year it is.",
                        "Who claims what": "The Empire claims all of it. The Empire "
                        "patrols about a fifth of it.",
                    },
                    "links": [
                        "Port Vermillion",
                        "Skull Cove",
                        ("file", "The Shattered Seas: World Guide"),
                    ],
                },
                {
                    "title": "Port entry",
                    "created_by": "Archivist Okoro",
                    "intro": "Copy this for anywhere the ship can tie up. Four "
                    "headings, no exceptions.",
                    "sections": {
                        "Approach": "Depth, hazards, and who watches the harbour.",
                        "Who runs it": "And who actually runs it.",
                        "What you can get here": "Repairs, crew, cargo, trouble.",
                        "Standing with us": "Welcome, tolerated, or shot at.",
                    },
                },
                {
                    "title": "Port Vermillion",
                    "created_by": "Harbormaster Marisol",
                    "tags": ["NPC", "diplomacy"],
                    "intro": "A free port that stays free by being useful to everybody "
                    "and loyal to nobody.",
                    "sections": {
                        "Approach": "Deep water to the quay. Come in under half sail; "
                        "the harbour watch reads anything faster as an opinion.",
                        "Who runs it": "The Harbour Council, which is four merchants "
                        "and whoever is currently owed the most money.",
                        "What you can get here": "Anything, at a price that reflects "
                        "how badly you need it and how obviously you need it.",
                        "Standing with us": "Welcome, as of the Ironclad business. That "
                        "is worth more than it sounds and it will not last.",
                    },
                    "links": ["The Crimson Maiden", ("task", "Recruit a new helmsman")],
                },
                {
                    "title": "The Crimson Maiden",
                    "created_by": "Finley Goldtongue",
                    "tags": ["ship upgrades"],
                    "intro": "Ours. A brigantine that was a revenue cutter before it "
                    "was anything else, which is why she runs so fast and carries so "
                    "little.",
                    "sections": {
                        "Condition": "Hull repaired after the kraken. The repair is "
                        "sound and it is not pretty.",
                        "What is fitted": "Dragon-fire shot, which nobody is insured "
                        "for, and an enchanted compass that points at what you want "
                        "rather than north.",
                        "Crew": "Thirty-one aboard, two berths open, and the helmsman's "
                        "post vacant since Coral Keep.",
                    },
                    "links": [
                        ("task", "Repair the hull after the kraken attack"),
                        ("task", "Upgrade cannons to dragon-fire shot"),
                        ("task", "Install the enchanted compass"),
                        ("file", "Crew Manifest: The Crimson Maiden"),
                    ],
                },
                {
                    "title": "Skull Cove",
                    "created_by": "Thorn Ironforge",
                    "tags": ["exploration", "loot"],
                    "intro": "A drowned caldera with one entrance, and the entrance is "
                    "only an entrance at low tide.",
                    "sections": {
                        "Approach": "Three hours either side of low water. Outside that "
                        "window there is no cove, only rock.",
                        "What is in there": "Four wrecks the charts do not list and one "
                        "that three separate maps agree on.",
                    },
                    "links": [("task", "Explore Skull Cove")],
                },
                {
                    "title": "The Whispering Jungle",
                    "created_by": "Aurelia Brightshield",
                    "tags": ["exploration"],
                    "intro": "Inland, on the big southern island, and nobody who maps "
                    "it agrees with anybody else who has mapped it.",
                    "sections": {
                        "Why the maps disagree": "That is the open question and it is "
                        "not a joke about cartography.",
                        "The Coral Elves": "Live at the treeline, know exactly where "
                        "everything is, and will tell you for a price that is never "
                        "money.",
                    },
                    "links": [
                        ("task", "Map the Whispering Jungle"),
                        ("task", "Negotiate with the Coral Elves"),
                    ],
                },
                {
                    "title": "The Leviathan's Heart",
                    "created_by": "Dungeon Master",
                    "tags": ["main quest", "boss fight"],
                    "intro": "The thing all of this is about, and the only entry in the "
                    "gazetteer nobody has seen.",
                    "sections": {
                        "What is known": "Three Tidestones open the way. Two are "
                        "aboard. The third is a rumour with a location attached.",
                        "What is guessed": "That something is still guarding it, and "
                        "that it has been guarding it a very long time.",
                    },
                    "links": [
                        ("task", "Decipher the Leviathan Map"),
                        ("task", "Collect the three Tidestones"),
                        ("task", "Defeat the Leviathan guardian"),
                    ],
                },
                {
                    "title": "Ghost ship sightings",
                    "is_draft": True,
                    "created_by": "Seraphina Dawnlight",
                    "tags": ["side quest"],
                    "intro": "Nine reports in four months, from crews with no reason to "
                    "agree with each other.",
                    "sections": {
                        "The pattern": "All nine within a day's sail of the Tide's "
                        "reversal line. Somebody noticed that before we did.",
                        "What we have done about it": "Written it down. That is all, so far.",
                    },
                    "links": [("task", "Investigate the ghost ship sightings")],
                },
            ],
        },
        {
            "name": "Articles of the Crimson Maiden",
            "initiative": "crimson",
            "description": "Signed by everybody aboard. Amended twice.",
            "created_by": "Finley Goldtongue",
            "page_order": WikiPageOrder.manual,
            "reading_width": WikiReadingWidth.comfortable,
            "contents_depth": 2,
            "show_connections": False,
            "accent_color": "#dc2626",
            "home": "The Articles",
            "pages": [
                {
                    "title": "The Articles",
                    "created_by": "Finley Goldtongue",
                    "intro": "Every hand aboard signed these. Nobody gets to be "
                    "surprised by them later.",
                    "sections": {
                        "Amendments": "Two so far, both after arguments that would have "
                        "been shorter if the articles had said this already."
                    },
                },
                {
                    "title": "Shares",
                    "created_by": "Finley Goldtongue",
                    "tags": ["loot"],
                    "intro": "How a haul is divided, decided before anybody has seen it.",
                    "sections": {
                        "The split": "Captain two shares, officers one and a half, "
                        "hands one. The ship takes two off the top for repairs before "
                        "any of that.",
                        "The ship's two": "Spent on the ship. Audited by anybody who "
                        "asks, and people do ask.",
                    },
                    "links": [("file", "Crimson Maiden Cargo Manifest")],
                },
                {
                    "title": "Who gives orders",
                    "created_by": "Thorn Ironforge",
                    "intro": "In a chase and in a fight, one person. The rest of the "
                    "time, rather fewer people than you would think.",
                    "sections": {
                        "Under way": "The captain, and through the captain the helm. "
                        "Nobody else, for any reason.",
                        "At anchor": "Whoever has the watch. Everything else is a conversation.",
                        "Disagreeing": "At anchor, loudly, and it is welcome. Under "
                        "way, afterwards.",
                    },
                },
                {
                    "title": "Quarter and prisoners",
                    "created_by": "Seraphina Dawnlight",
                    "tags": ["diplomacy"],
                    "intro": "The rule the crew argued about longest and now nobody questions.",
                    "sections": {
                        "Quarter is given": "Every time it is asked for. There is no "
                        "version of this we are willing to be known for.",
                        "Prisoners": "Put ashore at the next port with water and a "
                        "coat. Not sold, not kept.",
                    },
                },
                {
                    "title": "Letters of marque",
                    "created_by": "Harbormaster Marisol",
                    "tags": ["stealth", "diplomacy"],
                    "intro": "Whether we carry them, and what happens when somebody checks them.",
                    "sections": {
                        "What we carry": "Two sets, from two flags that dislike each "
                        "other. Producing the wrong one is the whole risk.",
                        "If they are examined": "They are good enough for a "
                        "harbourmaster and not good enough for an admiralty court.",
                    },
                    "links": [("task", "Forge letters of marque")],
                },
            ],
        },
        {
            "name": "Imperial Navy dossiers",
            "initiative": "navy",
            "description": "Ships, captains, and what each of them does when pressed.",
            "created_by": "Dungeon Master",
            "tags": ["naval combat"],
            "page_order": WikiPageOrder.title,
            "reading_width": WikiReadingWidth.wide,
            "contents_depth": 2,
            "accent_color": "#1e40af",
            "home": "The Imperial Navy",
            "template": "Dossier template",
            "pages": [
                {
                    "title": "The Imperial Navy",
                    "created_by": "Dungeon Master",
                    "tags": ["naval combat"],
                    "intro": "Forty hulls in these waters, nine of which the crew has "
                    "actually met.",
                    "sections": {
                        "How they fight": "In line, patiently, and they do not chase. "
                        "They arrange to be where you are going.",
                        "Who commands": "Blackwood, out of Coral Keep, and every "
                        "captain below her is somebody she chose.",
                    },
                    "links": [
                        "Admiral Blackwood",
                        "HMS Vengeance",
                        ("file", "Intelligence Report: Admiral Blackwood"),
                    ],
                },
                {
                    "title": "Dossier template",
                    "created_by": "Dungeon Master",
                    "intro": "Three headings. Anything else is speculation.",
                    "sections": {
                        "Hull and guns": "Class, rate, and what she carries.",
                        "Who commands": "And how long they have had her.",
                        "How she behaves": "Observed. Not assumed.",
                    },
                },
                {
                    "title": "Admiral Blackwood",
                    "created_by": "Kael Windrunner",
                    "tags": ["NPC", "boss fight"],
                    "intro": "Commands the squadron and has never personally boarded "
                    "anything, which people mistake for caution.",
                    "sections": {
                        "How she behaves": "Sends two ships where one would do, and the "
                        "second one arrives late on purpose.",
                        "What she wants": "The Maiden, intact, with her crew alive to "
                        "be tried. That preference is the only reason anybody is still "
                        "alive.",
                    },
                    "links": [("file", "Intelligence Report: Admiral Blackwood")],
                },
                {
                    "title": "HMS Vengeance",
                    "created_by": "Thorn Ironforge",
                    "tags": ["naval combat"],
                    "intro": "Flagship. Faster than a ship that size has any business being.",
                    "sections": {
                        "Hull and guns": "Ship of the line, sixty-four guns, "
                        "copper-bottomed within the year.",
                        "How she behaves": "Cuts corners the charts say she cannot. "
                        "Somebody aboard knows these waters better than we do.",
                    },
                    "links": [("task", "Evade the HMS Vengeance")],
                },
                {
                    "title": "HMS Ironclad",
                    "created_by": "Finley Goldtongue",
                    "tags": ["naval combat", "boss fight"],
                    "intro": "Sunk off Coral Keep. This page is kept because the "
                    "squadron still sails as if she were in it.",
                    "sections": {
                        "How she behaved": "Closed to pistol range every time. That is "
                        "what finished her and it nearly finished us.",
                        "What it cost": "The foremast, the helmsman, and whatever "
                        "goodwill Port Vermillion had left for us.",
                    },
                    "links": [
                        ("task", "Sink the HMS Ironclad"),
                        ("file", "Session 4 Recap: The Ironclad Falls"),
                    ],
                },
                {
                    "title": "Coral Keep",
                    "created_by": "Kael Windrunner",
                    "tags": ["exploration"],
                    "intro": "The squadron's base, and the only deep-water yard in the "
                    "Shattered Seas.",
                    "sections": {
                        "The yard": "Two dry docks. A ship in either is out of the war "
                        "for six weeks, which is worth knowing before picking a fight.",
                        "The convoys": "Weekly, predictable, and escorted exactly as "
                        "heavily as the cargo deserves.",
                    },
                    "links": [("task", "Raid the supply convoy near Coral Keep")],
                },
            ],
        },
    ],
}


def _body(page: dict, chips: list[dict] | None = None) -> dict:
    children = [para(page["intro"])]
    for title, texts in page.get("sections", {}).items():
        children.append(heading(title))
        children.extend(
            para(text) for text in ([texts] if isinstance(texts, str) else texts)
        )
    if chips:
        children.append(heading("See also"))
        parts: list[dict] = []
        for one in chips:
            if parts:
                parts.append({"text": " · ", "type": "text"})
            parts.append(one)
        children.append({"children": parts, "type": "paragraph"})
    return lexical(children)


async def seed(c: Community) -> None:
    pages: dict[tuple[str, str], WikiPage] = {}
    for d in WIKIS[c.key]:
        creator = c.users[d["created_by"]]
        wiki = Wiki(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["name"],
            description=d.get("description"),
            created_by=creator.id,
            page_order=d.get("page_order", WikiPageOrder.manual),
            reading_width=d.get("reading_width", WikiReadingWidth.wide),
            contents_depth=d.get("contents_depth", 3),
            show_connections=d.get("show_connections", True),
            accent_color=d.get("accent_color"),
        )
        c.session.add(wiki)
        await c.session.flush()
        c.ids["wikis"].append(wiki.id)
        share(c, Tool.wiki, wiki, creator, general=ResourceAccessLevel.read)
        tag(c, wiki, d.get("tags", ()))
        for position, pd in enumerate(d["pages"]):
            page = WikiPage(
                wiki_id=wiki.id,
                position=position,
                is_draft=pd.get("is_draft", False),
                title=pd["title"],
                slug=slugify(pd["title"], fallback=f"page-{position}"),
                content=_body(pd),
                created_by=c.users[pd.get("created_by", d["created_by"])].id,
            )
            c.session.add(page)
            await c.session.flush()
            c.ids["wiki_pages"].append(page.id)
            pages[(d["name"], page.title)] = page
            tag(c, page, pd.get("tags", ()))
        home = pages.get((d["name"], d.get("home", "")))
        template = pages.get((d["name"], d.get("template", "")))
        wiki.home_page_id = home.id if home else None
        wiki.template_page_id = template.id if template else None
        c.session.add(wiki)
        await c.session.flush()

    # What each page points at. Every wiki exists by now, so a page may name
    # one in another, and the chip in the body and the ``references`` edge are
    # written together — the same pair the save path produces for "[[".
    for d in WIKIS[c.key]:
        for pd in d["pages"]:
            page = pages[(d["name"], pd["title"])]
            chips = []
            for target in pd.get("links", ()):
                if isinstance(target, tuple):
                    kind, label = target
                    entity_id = {"task": c.tasks, "file": c.files}[kind][label].id
                else:
                    wiki_name, _, label = target.rpartition("::")
                    kind = SearchEntityType.wiki_page.value
                    entity_id = pages[(wiki_name or d["name"], label)].id
                chips.append(chip(kind, entity_id, label))
                await relationships_service.create(
                    c.session,
                    source=relationships_service.Endpoint(
                        SearchEntityType.wiki_page, page.id
                    ),
                    relationship_type=RelationshipType.references,
                    target=relationships_service.Endpoint(
                        SearchEntityType(kind), entity_id
                    ),
                    provenance=Provenance.content,
                )
            if chips:
                page.content = _body(pd, chips)
                c.session.add(page)
    await c.session.flush()
