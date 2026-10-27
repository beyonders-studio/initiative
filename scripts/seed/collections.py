"""Collections: sets of pictures in Files, stored through the storage path itself.

Every picture is a file in its initiative: a real PNG written to the
community's storage with an ``uploads`` row behind it, and versions that wait
on a thumbnail as an uploaded picture's do, so the ``thumbnails`` sweep draws
them. A collection holds its pictures, each added when it was taken, and lists
them the way a collection made from a gallery does.
"""

from __future__ import annotations

from datetime import timedelta

from app.core.file_types import type_of_media
from app.core.tools import LAYOUT_DEFAULT, Tool
from app.models.platform.user import User
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.file import File
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.tool_layout import ToolLayout
from app.services.tenant import attachments as attachments_service
from app.services.tenant import file_versions

from seed.common import Community, days_ago, gradient_png, share, tag

#: Each collection, its pictures shared with the initiative for reading.
#: ``cover`` names the picture to use as its cover. A picture is dated
#: ``days_ago``, ``size`` is ``(width, height)``, and it is drawn as a gradient
#: between its two ``colours``; ``versions`` is how many renditions to record,
#: each earlier one a little darker. One with no ``title`` is named by its
#: ``filename``.
COLLECTIONS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Barovia maps and handouts",
            "initiative": "strahd",
            "description": "Every map, letter and prop the table has seen. Tagged by "
            "what it was for.",
            "created_by": "Dungeon Master",
            "tags": ["lore"],
            "cover": "Castle Ravenloft, ground floor",
            "pictures": [
                {
                    "title": "Castle Ravenloft, ground floor",
                    "created_by": "Dungeon Master",
                    "days_ago": 160,
                    "size": (1600, 1100),
                    "colours": ((72, 52, 104), (26, 18, 40)),
                    "tags": ["exploration"],
                    "versions": 3,
                },
                {
                    "title": "Castle Ravenloft, crypts",
                    "created_by": "Dungeon Master",
                    "days_ago": 158,
                    "size": (1400, 1400),
                    "colours": ((40, 40, 60), (12, 12, 20)),
                    "tags": ["exploration", "boss fight"],
                    "versions": 2,
                },
                {
                    "title": "Strahd's letter",
                    "created_by": "Dungeon Master",
                    "days_ago": 150,
                    "size": (900, 1300),
                    "colours": ((214, 190, 140), (150, 120, 70)),
                    "tags": ["roleplay", "lore"],
                },
                {
                    "title": "Village of Barovia",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 120,
                    "size": (1800, 1000),
                    "colours": ((60, 90, 70), (20, 40, 30)),
                    "tags": ["exploration"],
                },
                {
                    "title": "Death House, floor 1",
                    "created_by": "Dungeon Master",
                    "days_ago": 118,
                    "size": (1200, 1600),
                    "colours": ((100, 60, 60), (40, 20, 20)),
                    "tags": ["exploration", "combat"],
                },
                {
                    "title": "Death House, floor 2",
                    "created_by": "Dungeon Master",
                    "days_ago": 118,
                    "size": (1200, 1600),
                    "colours": ((110, 70, 60), (44, 22, 20)),
                    "tags": ["exploration", "combat"],
                },
                {
                    "title": "Death House, basement",
                    "created_by": "Dungeon Master",
                    "days_ago": 118,
                    "size": (1200, 1400),
                    "colours": ((60, 40, 50), (18, 10, 14)),
                    "tags": ["exploration", "combat", "boss fight"],
                    "versions": 2,
                },
                {
                    "title": "Tarokka reading",
                    "created_by": "Elara Moonwhisper",
                    "days_ago": 90,
                    "size": (1500, 1000),
                    "colours": ((160, 90, 40), (60, 30, 10)),
                    "tags": ["lore"],
                },
                {
                    "title": "Vallaki",
                    "created_by": "Dungeon Master",
                    "days_ago": 61,
                    "size": (2000, 1200),
                    "colours": ((80, 110, 130), (30, 45, 60)),
                    "tags": ["exploration"],
                },
                {
                    "title": "The Blue Water Inn",
                    "created_by": "Dungeon Master",
                    "days_ago": 61,
                    "size": (1000, 1000),
                    "colours": ((60, 100, 140), (20, 40, 70)),
                    "tags": ["roleplay"],
                },
                {
                    "title": "Wizard of Wines",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 30,
                    "size": (1600, 900),
                    "colours": ((120, 40, 80), (50, 10, 30)),
                    "tags": ["quest", "combat"],
                },
                {
                    "title": "Amber Temple, entrance",
                    "created_by": "Dungeon Master",
                    "days_ago": 4,
                    "size": (1400, 1800),
                    "colours": ((200, 150, 40), (90, 60, 10)),
                    "tags": ["quest", "puzzle"],
                },
                {
                    "title": "Amber Temple, vaults",
                    "created_by": "Dungeon Master",
                    "days_ago": 4,
                    "size": (1400, 1800),
                    "colours": ((180, 130, 30), (70, 45, 5)),
                    "tags": ["quest", "puzzle", "items/loot"],
                },
                {
                    "title": None,
                    "filename": "IMG_4471.png",
                    "created_by": "Vex Shadowstep",
                    "days_ago": 1,
                    "size": (1600, 1200),
                    "colours": ((90, 90, 90), (30, 30, 30)),
                },
            ],
        },
        {
            "name": "Phandelver props",
            "initiative": "lmop",
            "description": "Handouts for the table. Print at A4.",
            "created_by": "Dungeon Master",
            "pictures": [
                {
                    "title": "Cragmaw Hideout",
                    "created_by": "Dungeon Master",
                    "days_ago": 75,
                    "size": (1600, 1100),
                    "colours": ((70, 80, 60), (25, 30, 20)),
                    "tags": ["exploration"],
                },
                {
                    "title": "Gundren's map",
                    "created_by": "Dungeon Master",
                    "days_ago": 74,
                    "size": (1200, 900),
                    "colours": ((200, 170, 120), (140, 110, 60)),
                    "tags": ["quest", "lore"],
                },
                {
                    "title": "Wave Echo Cave",
                    "created_by": "Dungeon Master",
                    "days_ago": 20,
                    "size": (2000, 1400),
                    "colours": ((50, 70, 90), (15, 25, 35)),
                    "tags": ["exploration", "boss fight"],
                    "versions": 2,
                },
                {
                    "title": "Phandalin",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 20,
                    "size": (1500, 1500),
                    "colours": ((100, 120, 80), (40, 50, 30)),
                },
            ],
        },
    ],
    "starforge": [
        {
            "name": "Fleet concept art",
            "initiative": "starfall",
            "description": "Hull studies, bridge layouts and the one ship nobody liked.",
            "created_by": "Finley Goldtongue",
            "tags": ["engineering"],
            "pictures": [
                {
                    "title": "Exodus, hull study",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 140,
                    "size": (2200, 900),
                    "colours": ((30, 60, 110), (8, 16, 34)),
                    "tags": ["engineering"],
                    "versions": 4,
                },
                {
                    "title": "Exodus, bridge",
                    "created_by": "Aurelia Brightshield",
                    "days_ago": 96,
                    "size": (1600, 1000),
                    "colours": ((40, 90, 130), (10, 24, 44)),
                    "tags": ["engineering"],
                    "versions": 2,
                },
                {
                    "title": "Drop shuttle",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 95,
                    "size": (1400, 1400),
                    "colours": ((70, 80, 95), (20, 24, 30)),
                },
                {
                    "title": "Frontier station",
                    "created_by": "Kael Windrunner",
                    "days_ago": 52,
                    "size": (2400, 800),
                    "colours": ((90, 60, 130), (24, 14, 40)),
                    "tags": ["exploration"],
                },
                {
                    "title": "Reactor deck",
                    "created_by": "Aurelia Brightshield",
                    "days_ago": 51,
                    "size": (1200, 1600),
                    "colours": ((150, 90, 30), (50, 26, 6)),
                    "tags": ["engineering", "survival"],
                },
                {
                    "title": "Salvage hauler",
                    "created_by": "Vex Shadowstep",
                    "days_ago": 12,
                    "size": (1800, 1100),
                    "colours": ((60, 70, 60), (18, 22, 18)),
                    "tags": ["loot"],
                },
                {
                    "title": None,
                    "filename": "bridge-wip-final-2.png",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 3,
                    "size": (1000, 1200),
                    "colours": ((120, 40, 40), (40, 12, 12)),
                },
            ],
        },
    ],
    "tides": [
        {
            "name": "Charts of the Shattered Seas",
            "initiative": "crimson",
            "description": "Every chart the crew has bought, stolen or drawn themselves.",
            "created_by": "Finley Goldtongue",
            "tags": ["exploration"],
            "cover": "The Shattered Seas",
            "pictures": [
                {
                    "title": "The Shattered Seas",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 200,
                    "size": (2400, 1600),
                    "colours": ((30, 90, 120), (8, 30, 48)),
                    "tags": ["exploration"],
                    "versions": 2,
                },
                {
                    "title": "Port Blackwater",
                    "created_by": "Dungeon Master",
                    "days_ago": 150,
                    "size": (1400, 1000),
                    "colours": ((100, 80, 50), (36, 28, 16)),
                    "tags": ["NPC"],
                },
                {
                    "title": "The Leviathan's reach",
                    "created_by": "Dungeon Master",
                    "days_ago": 44,
                    "size": (1600, 1600),
                    "colours": ((20, 60, 70), (6, 18, 22)),
                    "tags": ["boss fight"],
                },
                {
                    "title": "Imperial patrol routes",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 9,
                    "size": (2000, 1200),
                    "colours": ((40, 50, 110), (12, 16, 40)),
                    "tags": ["naval combat", "stealth"],
                },
            ],
        }
    ],
}

#: How a collection lists its files: masonry and timeline shown, the table
#: hidden, opening on masonry, as 20261027_0545 lays out a converted gallery.
_LAYOUTS = (
    ("masonry", {"hidden": False}),
    ("timeline", {"hidden": False}),
    ("table", {"hidden": True}),
    (LAYOUT_DEFAULT, {"kind": "masonry"}),
)

_MEDIA_TYPE = "image/png"


async def seed(c: Community) -> None:
    for d in COLLECTIONS[c.key]:
        creator = c.users[d["created_by"]]
        initiative_id = c.initiatives[d["initiative"]].id
        pictures: dict[str, File] = {}
        for p in d["pictures"]:
            file = await _picture(c, initiative_id, creator, p)
            pictures[file.name] = file
        files = list(pictures.values())
        collection = Collection(
            initiative_id=initiative_id,
            name=d["name"],
            description=d.get("description"),
            cover_file_id=pictures[d["cover"]].id if "cover" in d else None,
            created_by=creator.id,
            created_at=min(f.created_at for f in files),
            updated_at=max(f.updated_at for f in files),
        )
        c.session.add(collection)
        await c.session.flush()
        c.ids["collections"].append(collection.id)
        for f in files:
            c.session.add(
                CollectionFile(
                    collection_id=collection.id,
                    file_id=f.id,
                    initiative_id=initiative_id,
                    added_by=f.created_by,
                    added_at=f.created_at,
                )
            )
            c.ids["collection_files"].append([collection.id, f.id])
        for kind, definition in _LAYOUTS:
            c.session.add(
                ToolLayout(
                    initiative_id=initiative_id,
                    tool="collection",
                    tool_id=collection.id,
                    kind=kind,
                    definition=definition,
                )
            )
        tag(c, collection, d.get("tags", ()))
    await c.session.flush()


async def _picture(c: Community, initiative_id: int, owner: User, p: dict) -> File:
    """One picture as an uploaded file, shared as its collection is."""
    uploader = c.users[p["created_by"]].id
    created_at = days_ago(p["days_ago"])
    top, bottom = p["colours"]
    width, height = p["size"]
    versions = p.get("versions", 1)
    filename = p.get("filename") or f"{p['title'].lower().replace(' ', '-')}.png"
    file = File(
        initiative_id=initiative_id,
        name=p.get("title") or filename,
        content={},
        file_type=type_of_media(_MEDIA_TYPE),
        created_by=uploader,
        created_at=created_at,
    )
    c.session.add(file)
    await c.session.flush()
    c.ids["files"].append(file.id)
    share(c, Tool.file, file, owner, general=ResourceAccessLevel.read)
    tag(c, file, p.get("tags", ()))
    version_at = created_at
    for number in range(1, versions + 1):
        # Earlier renditions lean darker, so the history reads as a picture
        # that was worked on rather than uploaded twice.
        shade = versions - number
        png = gradient_png(
            width,
            height,
            tuple(max(0, v - 25 * shade) for v in top),
            tuple(max(0, v - 25 * shade) for v in bottom),
        )
        file_url = await attachments_service.store_upload(
            c.session,
            guild_id=c.guild.id,
            filename=attachments_service.new_upload_filename(".png"),
            data=png,
            content_type=_MEDIA_TYPE,
            created_by=uploader,
            initiative_id=initiative_id,
        )
        version_at = created_at + timedelta(days=3 * (number - 1))
        version = await file_versions.add_version(
            c.session,
            file,
            file_url=file_url,
            file_content_type=_MEDIA_TYPE,
            file_size=len(png),
            original_filename=filename,
            width=width,
            height=height,
            created_by=uploader,
            created_at=version_at,
        )
        # The next rendition is numbered after this one, which it reads back.
        await c.session.flush()
        c.ids["file_versions"].append(version.id)
    file.updated_at = version_at
    c.session.add(file)
    return file
