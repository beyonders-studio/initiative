"""Collections: sets of pictures in Files, stored through the storage path itself.

Every picture is a file in its initiative: a real PNG written to the
community's storage with an ``uploads`` row behind it, and versions that wait
on a thumbnail as an uploaded picture's do, so the ``thumbnails`` sweep draws
them. A collection holds its pictures, each added when it was taken, and
starts as one of the ready-made shapes, its fields filled in for each file. A
collection can also hold pictures another one holds, so the same picture is
shown one way in one collection and another way in the next.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.collection_shapes import SHAPES_BY_KEY
from app.core.file_types import type_of_media
from app.core.image_headers import read_image_header
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.file import File
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.tenant.property import PropertyValueInput
from app.services.tenant import attachments as attachments_service
from app.services.tenant import collections as collections_service
from app.services.tenant import file_versions
from app.services.tenant import metadata as metadata_service

from seed.common import Community, days_ago, photo, share, tag

#: Each collection, its pictures shared with the initiative for reading.
#: ``shape`` is the ready-made shape it starts as, and ``cover`` names the
#: picture to use as its cover. A picture is dated ``days_ago`` and cut from
#: the front page's ``photo`` to the proportions of ``size``, ``(width,
#: height)``; ``versions`` is how many renditions to record, each earlier one
#: a little darker. One with no ``title`` is named by its ``filename``.
#: ``fields`` are a file's values for the collection's fields, by the shape's
#: key. ``files`` are pictures an earlier collection in the initiative holds,
#: added ``days_after`` they were taken.
COLLECTIONS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Barovia maps and handouts",
            "initiative": "strahd",
            "shape": "gallery",
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
                    "photo": "fantasy-map",
                    "tags": ["exploration"],
                    "versions": 3,
                    "fields": {"caption": "The one they keep asking for."},
                },
                {
                    "title": "Castle Ravenloft, crypts",
                    "created_by": "Dungeon Master",
                    "days_ago": 158,
                    "size": (1400, 1400),
                    "photo": "fantasy-map",
                    "tags": ["exploration", "boss fight"],
                    "versions": 2,
                },
                {
                    "title": "Strahd's letter",
                    "created_by": "Dungeon Master",
                    "days_ago": 150,
                    "size": (900, 1300),
                    "photo": "book-pages",
                    "tags": ["roleplay", "lore"],
                    "fields": {
                        "caption": "Read aloud in session 1. Nobody trusted it."
                    },
                },
                {
                    "title": "Village of Barovia",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 120,
                    "size": (1800, 1000),
                    "photo": "street",
                    "tags": ["exploration"],
                },
                {
                    "title": "Death House, floor 1",
                    "created_by": "Dungeon Master",
                    "days_ago": 118,
                    "size": (1200, 1600),
                    "photo": "family",
                    "tags": ["exploration", "combat"],
                },
                {
                    "title": "Death House, floor 2",
                    "created_by": "Dungeon Master",
                    "days_ago": 118,
                    "size": (1200, 1600),
                    "photo": "family",
                    "tags": ["exploration", "combat"],
                },
                {
                    "title": "Death House, basement",
                    "created_by": "Dungeon Master",
                    "days_ago": 118,
                    "size": (1200, 1400),
                    "photo": "theater",
                    "tags": ["exploration", "combat", "boss fight"],
                    "versions": 2,
                    "fields": {"caption": "Not before they find the stairs."},
                },
                {
                    "title": "Tarokka reading",
                    "created_by": "Elara Moonwhisper",
                    "days_ago": 90,
                    "size": (1500, 1000),
                    "photo": "book-pages",
                    "tags": ["lore"],
                    "fields": {"caption": "Madam Eva's spread, as drawn at the table."},
                },
                {
                    "title": "Vallaki",
                    "created_by": "Dungeon Master",
                    "days_ago": 61,
                    "size": (2000, 1200),
                    "photo": "street",
                    "tags": ["exploration"],
                },
                {
                    "title": "The Blue Water Inn",
                    "created_by": "Dungeon Master",
                    "days_ago": 61,
                    "size": (1000, 1000),
                    "photo": "breakfast-club",
                    "tags": ["roleplay"],
                },
                {
                    "title": "Wizard of Wines",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 30,
                    "size": (1600, 900),
                    "photo": "bakery",
                    "tags": ["quest", "combat"],
                },
                {
                    "title": "Amber Temple, entrance",
                    "created_by": "Dungeon Master",
                    "days_ago": 4,
                    "size": (1400, 1800),
                    "photo": "campus",
                    "tags": ["quest", "puzzle"],
                },
                {
                    "title": "Amber Temple, vaults",
                    "created_by": "Dungeon Master",
                    "days_ago": 4,
                    "size": (1400, 1800),
                    "photo": "campus",
                    "tags": ["quest", "puzzle", "items/loot"],
                    "fields": {"caption": "Unfinished. The north wing is a guess."},
                },
                {
                    "title": None,
                    "filename": "IMG_4471.webp",
                    "created_by": "Vex Shadowstep",
                    "days_ago": 1,
                    "size": (1600, 1200),
                    "photo": "meetup",
                },
            ],
        },
        {
            "name": "Prints for the table",
            "initiative": "strahd",
            "shape": "catalog",
            "description": "The maps people asked to take home. A3, from the print "
            "shop on the corner.",
            "created_by": "Elara Moonwhisper",
            "files": [
                {
                    "title": "Castle Ravenloft, ground floor",
                    "days_after": 30,
                    "fields": {"price": 6.5, "rating": 100},
                },
                {
                    "title": "Village of Barovia",
                    "days_after": 30,
                    "fields": {"price": 6.5, "rating": 80},
                },
                {
                    "title": "Tarokka reading",
                    "days_after": 12,
                    "fields": {"price": 4, "rating": 60},
                },
                {
                    "title": "Vallaki",
                    "days_after": 2,
                    "fields": {"price": 8, "rating": 40},
                },
            ],
        },
        {
            "name": "Phandelver props",
            "initiative": "lmop",
            "shape": "log",
            "description": "Handouts for the table, by the session they came out in. "
            "Print at A4.",
            "created_by": "Dungeon Master",
            "pictures": [
                {
                    "title": "Cragmaw Hideout",
                    "created_by": "Dungeon Master",
                    "days_ago": 75,
                    "size": (1600, 1100),
                    "photo": "fantasy-map",
                    "tags": ["exploration"],
                    "fields": {"date": days_ago(73).date()},
                },
                {
                    "title": "Gundren's map",
                    "created_by": "Dungeon Master",
                    "days_ago": 74,
                    "size": (1200, 900),
                    "photo": "book-pages",
                    "tags": ["quest", "lore"],
                    "fields": {"date": days_ago(73).date()},
                },
                {
                    "title": "Wave Echo Cave",
                    "created_by": "Dungeon Master",
                    "days_ago": 20,
                    "size": (2000, 1400),
                    "photo": "fantasy-map",
                    "tags": ["exploration", "boss fight"],
                    "versions": 2,
                    "fields": {"date": days_ago(17).date()},
                },
                {
                    "title": "Phandalin",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 20,
                    "size": (1500, 1500),
                    "photo": "street",
                    "fields": {"date": days_ago(17).date()},
                },
            ],
        },
    ],
    "starforge": [
        {
            "name": "Fleet concept art",
            "initiative": "starfall",
            "shape": "gallery",
            "description": "Hull studies, bridge layouts and the one ship nobody liked.",
            "created_by": "Finley Goldtongue",
            "tags": ["engineering"],
            "pictures": [
                {
                    "title": "Exodus, hull study",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 140,
                    "size": (2200, 900),
                    "photo": "robot",
                    "tags": ["engineering"],
                    "versions": 4,
                    "fields": {"caption": "Version four. The fins stay."},
                },
                {
                    "title": "Exodus, bridge",
                    "created_by": "Aurelia Brightshield",
                    "days_ago": 96,
                    "size": (1600, 1000),
                    "photo": "robot",
                    "tags": ["engineering"],
                    "versions": 2,
                },
                {
                    "title": "Drop shuttle",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 95,
                    "size": (1400, 1400),
                    "photo": "instruments",
                    "fields": {"caption": "The one nobody liked."},
                },
                {
                    "title": "Frontier station",
                    "created_by": "Kael Windrunner",
                    "days_ago": 52,
                    "size": (2400, 800),
                    "photo": "classroom",
                    "tags": ["exploration"],
                    "fields": {"caption": "Seen from the approach lane."},
                },
                {
                    "title": "Reactor deck",
                    "created_by": "Aurelia Brightshield",
                    "days_ago": 51,
                    "size": (1200, 1600),
                    "photo": "robot",
                    "tags": ["engineering", "survival"],
                },
                {
                    "title": "Salvage hauler",
                    "created_by": "Vex Shadowstep",
                    "days_ago": 12,
                    "size": (1800, 1100),
                    "photo": "food-bank",
                    "tags": ["loot"],
                },
                {
                    "title": None,
                    "filename": "bridge-wip-final-2.webp",
                    "created_by": "Finley Goldtongue",
                    "days_ago": 3,
                    "size": (1000, 1200),
                    "photo": "classroom",
                },
            ],
        },
    ],
    "tides": [
        {
            "name": "Charts of the Shattered Seas",
            "initiative": "crimson",
            "shape": "gallery",
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
                    "photo": "fantasy-map",
                    "tags": ["exploration"],
                    "versions": 2,
                    "fields": {
                        "caption": "Bought in Port Blackwater, corrected twice."
                    },
                },
                {
                    "title": "Port Blackwater",
                    "created_by": "Dungeon Master",
                    "days_ago": 150,
                    "size": (1400, 1000),
                    "photo": "street",
                    "tags": ["NPC"],
                },
                {
                    "title": "The Leviathan's reach",
                    "created_by": "Dungeon Master",
                    "days_ago": 44,
                    "size": (1600, 1600),
                    "photo": "book-pages",
                    "tags": ["boss fight"],
                    "fields": {"caption": "Drawn from the survivor's account."},
                },
                {
                    "title": "Imperial patrol routes",
                    "created_by": "Thorn Ironforge",
                    "days_ago": 9,
                    "size": (2000, 1200),
                    "photo": "fantasy-map",
                    "tags": ["naval combat", "stealth"],
                },
            ],
        }
    ],
}

_MEDIA_TYPE = "image/webp"


async def seed(c: Community) -> None:
    # Every picture made so far, by initiative and title, for a later
    # collection to hold too.
    made: dict[tuple[str, str], File] = {}
    for d in COLLECTIONS[c.key]:
        creator = c.users[d["created_by"]]
        initiative_id = c.initiatives[d["initiative"]].id
        # Each file, when and by whom it was added, and its values here.
        held: list[tuple[File, datetime, int, dict]] = []
        for p in d.get("pictures", ()):
            file = await _picture(c, initiative_id, creator, p)
            made[(d["initiative"], file.name)] = file
            held.append((file, file.created_at, file.created_by, p.get("fields", {})))
        for f in d.get("files", ()):
            file = made[(d["initiative"], f["title"])]
            added = file.created_at + timedelta(days=f["days_after"])
            held.append((file, added, creator.id, f["fields"]))
        collection = Collection(
            initiative_id=initiative_id,
            name=d["name"],
            description=d.get("description"),
            cover_file_id=made[(d["initiative"], d["cover"])].id
            if "cover" in d
            else None,
            created_by=creator.id,
            created_at=min(added for _, added, _, _ in held),
            updated_at=max(max(f.updated_at, added) for f, added, _, _ in held),
        )
        c.session.add(collection)
        await c.session.flush()
        c.ids["collections"].append(collection.id)
        for f, added, added_by, _ in held:
            c.session.add(
                CollectionFile(
                    collection_id=collection.id,
                    file_id=f.id,
                    initiative_id=initiative_id,
                    added_by=added_by,
                    added_at=added,
                )
            )
            c.ids["collection_files"].append([collection.id, f.id])
        await c.session.flush()
        fields = await collections_service.apply_shape(
            c.session, collection, SHAPES_BY_KEY[d["shape"]], locale="en"
        )
        c.ids["property_definitions"].extend(f.id for f in fields.values())
        # Through the service the field editor uses, so a seeded value is
        # held to the same rules a typed one is.
        for f, _, _, values in held:
            if not values:
                continue
            await metadata_service.write_values(
                c.session,
                f,
                [
                    PropertyValueInput(property_id=fields[key].id, value=value)
                    for key, value in values.items()
                ],
                initiative_id=initiative_id,
                collection_id=collection.id,
            )
            c.ids["property_values"].extend(values)
        tag(c, collection, d.get("tags", ()))
    await c.session.flush()


async def _picture(c: Community, initiative_id: int, owner: User, p: dict) -> File:
    """One picture as an uploaded file, shared as its collection is."""
    uploader = c.users[p["created_by"]].id
    created_at = days_ago(p["days_ago"])
    versions = p.get("versions", 1)
    filename = p.get("filename") or f"{p['title'].lower().replace(' ', '-')}.webp"
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
        data = photo(p["photo"], *p["size"], shade=shade)
        header = read_image_header(data)
        assert header is not None
        file_url = await attachments_service.store_upload(
            c.session,
            guild_id=c.guild.id,
            filename=attachments_service.new_upload_filename(".webp"),
            data=data,
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
            file_size=len(data),
            original_filename=filename,
            width=header.width,
            height=header.height,
            created_by=uploader,
            created_at=version_at,
        )
        # The next rendition is numbered after this one, which it reads back.
        await c.session.flush()
        c.ids["file_versions"].append(version.id)
    file.updated_at = version_at
    c.session.add(file)
    return file
