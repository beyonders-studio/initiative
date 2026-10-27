"""Libraries: walls of pictures, stored through the storage path itself.

Every picture is a real PNG written to the guild's storage with an ``uploads``
row behind it, and its thumbnail is made the way an upload's is — so the wall,
the lightbox and the quota all read what they would for a picture somebody
dropped in.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.library import Library, LibraryItem, LibraryItemVersion
from app.models.tenant.upload import Upload
from app.services.storage import get_guild_storage
from app.services.tenant import file_versions
from app.services.tenant import libraries as libraries_service

from seed.common import Community, days_ago, gradient_png, share, tag

#: Each library, shared with the initiative for reading. ``cover`` names the
#: picture to use as its cover. A picture is dated ``days_ago``, ``size`` is
#: ``(width, height)``, and it is drawn as a gradient between its two
#: ``colours``; ``versions`` is how many renditions to record, each earlier one
#: a little darker.
LIBRARIES: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Barovia maps and handouts",
            "initiative": "strahd",
            "description": "Every map, letter and prop the table has seen. Tagged by "
            "what it was for.",
            "created_by": "Dungeon Master",
            "tags": ["lore"],
            "cover": "Castle Ravenloft, ground floor",
            "images": [
                {
                    "title": "Castle Ravenloft, ground floor",
                    "description": "The one the players have. Do not show them the crypts.",
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
                    "description": "Read aloud at the gates. Sera cried. Everyone pretended "
                    "not to notice.",
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
                    "description": "The spread as dealt. Photographed before Vex could touch it.",
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
                    "description": "The table, mid-session. Not sure who took this.",
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
            "images": [
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
                    "description": "Water-stained on purpose. Took three tea bags.",
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
            "images": [
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
                    "description": "Third pass. The viewscreen finally reads as a window.",
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
                    "description": "Whatever this was, it did not survive the review.",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 3,
                    "size": (1000, 1200),
                    "colours": ((120, 40, 40), (40, 12, 12)),
                },
            ],
        },
        {
            "name": "Crew portraits",
            "initiative": "starfall",
            "description": "One per member of the fleet. Nobody has started.",
            "created_by": "Aurelia Brightshield",
            "images": [],
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
            "images": [
                {
                    "title": "The Shattered Seas",
                    "description": "The whole map. Torn along the eastern edge, which is "
                    "where we are going.",
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
                    "description": "Do not leave this one on the table.",
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


def _store(
    c: Community,
    library: Library,
    data: bytes,
    extension: str,
    content_type: str,
    by: int,
) -> str:
    """Write one file to the guild's storage, with its ``uploads`` row claimed
    by the library's initiative, as saving it into the library would."""
    filename = f"{uuid.uuid4().hex}{extension}"
    get_guild_storage(c.guild.id).write(filename, data, content_type=content_type)
    c.session.add(
        Upload(
            filename=filename,
            created_by=by,
            size_bytes=len(data),
            content_type=content_type,
            initiative_id=library.initiative_id,
            claimed_at=datetime.now(timezone.utc),
        )
    )
    return f"/uploads/{c.guild.id}/{filename}"


async def seed(c: Community) -> None:
    for d in LIBRARIES[c.key]:
        creator = c.users[d["created_by"]]
        library = Library(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["name"],
            description=d.get("description"),
            created_by=creator.id,
        )
        c.session.add(library)
        await c.session.flush()
        c.ids["libraries"].append(library.id)
        share(c, Tool.library, library, creator, general=ResourceAccessLevel.read)
        tag(c, library, d.get("tags", ()))
        newest_at = library.created_at
        for im in d["images"]:
            item = await _picture(c, library, im)
            if im.get("title") and im["title"] == d.get("cover"):
                library.cover_item_id = item.id
            newest_at = max(newest_at, item.updated_at)
        library.updated_at = newest_at
        c.session.add(library)
    await c.session.flush()


async def _picture(c: Community, library: Library, im: dict) -> LibraryItem:
    uploader = c.users[im["created_by"]].id
    created_at = days_ago(im["days_ago"])
    top, bottom = im["colours"]
    width, height = im["size"]
    versions = im.get("versions", 1)
    filename = (
        im.get("filename")
        or f"{(im.get('title') or 'picture').lower().replace(' ', '-')}.png"
    )
    item: LibraryItem | None = None
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
        file_url = _store(c, library, png, ".png", "image/png", uploader)
        thumbnail = libraries_service.render_thumbnail(png)
        thumbnail_url = (
            _store(
                c,
                library,
                thumbnail.data,
                thumbnail.extension,
                thumbnail.content_type,
                uploader,
            )
            if thumbnail is not None
            else None
        )
        version_at = created_at + timedelta(days=3 * (number - 1))
        if item is None:
            item = LibraryItem(
                library_id=library.id,
                title=im.get("title"),
                description=im.get("description"),
                occurred_on=created_at.date(),
                created_by=uploader,
                created_at=created_at,
                updated_at=version_at,
            )
            c.session.add(item)
            await c.session.flush()
            c.ids["library_items"].append(item.id)
        await file_versions.add_version(
            c.session,
            item,
            file_url=file_url,
            thumbnail_url=thumbnail_url,
            file_content_type="image/png",
            file_size=len(png),
            original_filename=filename,
            width=width,
            height=height,
            created_by=uploader,
            created_at=version_at,
        )
        item.updated_at = version_at
        # The next rendition is numbered after this one, which it reads back.
        await c.session.flush()
    assert item is not None
    await c.session.flush()
    c.ids["library_item_versions"].extend(
        (
            await c.session.exec(
                select(LibraryItemVersion.id).where(
                    LibraryItemVersion.library_item_id == item.id
                )
            )
        ).all()
    )
    tag(c, item, im.get("tags", ()))
    return item
