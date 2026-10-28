"""Migration 20261027_0546 turns galleries into collections and their pictures
into files. Loaded by path and run on a guild the test builds: down to empty
gallery tables, a gallery written the way 0.68 stored one, then up again, the
way ``files_formats_migration_test`` runs its revisions."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from pycrdt import Doc, Map, Text
from sqlalchemy import text

from app.services import editor_engine
from app.testing import (
    create_file,
    create_guild,
    create_initiative,
    create_project,
    create_tag,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


async def _one(session, sql: str, **params: Any) -> Any:
    return (await _rows(session, sql, **params))[0][0]


def _runner(schema: str):
    """Revision 0546 one way or the other, on one guild's schema only, with
    the metadata store (20261027_0550) off first and back on last."""
    migration = _load("20261027_0546_galleries_are_collections.py")
    metadata = _load("20261027_0550_metadata_is_one_store.py")

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()

            def in_schema(step) -> None:
                bind.execute(
                    text("SELECT set_config('search_path', :sp, true)"),
                    {"sp": f"{schema}, public"},
                )
                step()

            with Operations.context(MigrationContext.configure(bind)):
                if not forward:
                    in_schema(lambda: metadata._apply(False))
                migration._convert(bind, forward, in_schema)
                if forward:
                    in_schema(lambda: metadata._apply(True))

        return apply

    return run


def _paragraph(*children: dict) -> dict:
    return {
        "root": {
            "type": "root",
            "version": 1,
            "children": [
                {"type": "paragraph", "version": 1, "children": list(children)}
            ],
        }
    }


def _words(words: str, fmt: int = 0) -> dict:
    return {
        "type": "text",
        "version": 1,
        "text": words,
        "format": fmt,
        "mode": "normal",
    }


async def _state_with_wikilink(body: dict, words: str, file_id: int) -> bytes:
    """``body``'s Yjs state with the text node reading ``words`` stored as a
    ``[[ ]]`` link to ``file_id``, as an editor before references were one
    thing wrote it."""
    doc = Doc()
    doc.apply_update(await editor_engine.bootstrap(body))
    root = doc.get("root", type=Text)
    paragraph = root._maybe_as_type_or_doc(root.diff()[0][0])
    pieces = [content for content, _ in paragraph.diff()]
    node = paragraph._maybe_as_type_or_doc(pieces[pieces.index(words) - 1])
    assert isinstance(node, Map)
    with doc.transaction():
        node["__type"] = "wikilink"
        node["__documentId"] = file_id
        node["__documentTitle"] = words
    return bytes(doc.get_update())


def _references(body: dict) -> list[tuple]:
    return [
        (node["type"], node.get("entityType"), node.get("entityId"))
        for node in body["root"]["children"][0]["children"]
        if node["type"] != "text"
    ]


async def test_a_gallery_becomes_a_collection_of_files(session) -> None:
    owner = await create_user(session)
    reader = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"
    s = f'"{schema}"'
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    tag = await create_tag(session, guild)
    elsewhere = await create_initiative(session, guild, owner)
    spec = await create_file(session, elsewhere, owner, name="Spec")
    page = await create_file(session, elsewhere, owner)
    await session.commit()
    run = _runner(schema)
    await session.run_sync(run(False))
    await session.commit()

    # A gallery as 0.68 stored one, archived: two pictures, the first replaced
    # once and captioned, a restricted grant, a comment, tags on it and on a
    # picture, and links.
    archived = datetime(2026, 1, 3, tzinfo=timezone.utc)
    connection = await session.connection()
    await connection.execute(text("SET LOCAL session_replication_role = replica"))
    # Galleries on and Files off, and a role that reaches galleries alone.
    await connection.execute(
        text(
            f"UPDATE {s}.initiatives SET galleries_enabled = true, "
            "files_enabled = false WHERE id = :i"
        ),
        {"i": initiative.id},
    )
    role = await _one(
        session,
        f"SELECT id FROM {s}.initiative_roles WHERE initiative_id = :i "
        "ORDER BY id DESC LIMIT 1",
        i=initiative.id,
    )
    await connection.execute(
        text(
            f"INSERT INTO {s}.initiative_role_permissions "
            "(initiative_role_id, permission_key, enabled) VALUES "
            "(:r, 'galleries_enabled', true), (:r, 'create_galleries', true), "
            "(:r, 'files_enabled', false) ON CONFLICT (initiative_role_id, "
            "permission_key) DO UPDATE SET enabled = EXCLUDED.enabled"
        ),
        {"r": role},
    )
    gallery = await _one(
        session,
        f"INSERT INTO {s}.galleries (initiative_id, name, description, created_by, "
        "created_at, updated_at, archived_at) VALUES (:i, 'Wall', 'Studio shots', "
        ":u, '2026-01-01', '2026-01-02', :archived) RETURNING id",
        i=initiative.id,
        u=owner.id,
        archived=archived,
    )
    pictures = []
    for title, caption, at in (
        ("Sunset", " Golden hour ", datetime(2026, 2, 1, tzinfo=timezone.utc)),
        (None, " ", datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ):
        pictures.append(
            await _one(
                session,
                f"INSERT INTO {s}.gallery_images (gallery_id, title, caption, "
                "created_by, created_at, updated_at) VALUES (:g, :t, :c, "
                ":u, :at, :at) RETURNING id",
                g=gallery,
                t=title,
                c=caption,
                u=owner.id,
                at=at,
            )
        )
    sunset, untitled = pictures
    versions = {}
    for image, number, url, media, filename, author, size in (
        (sunset, 1, "sunset-1.png", "image/png", "sunset.png", owner.id, (800, 600)),
        (sunset, 2, "sunset-2.jpg", "image/jpeg", "sunset.jpg", reader.id, (900, 1600)),
        (untitled, 1, "dunes.webp", "image/webp", "dunes.webp", None, (None, None)),
    ):
        versions[(image, number)] = await _one(
            session,
            f"INSERT INTO {s}.gallery_image_versions (gallery_image_id, "
            "version_number, file_url, file_content_type, original_filename, "
            "width, height, created_by, created_at) "
            "VALUES (:i, :n, :url, :m, :f, :w, :h, :u, now()) RETURNING id",
            i=image,
            n=number,
            url=f"/uploads/{guild.id}/{url}",
            m=media,
            f=filename,
            w=size[0],
            h=size[1],
            u=author,
        )
    for image, number in ((sunset, 2), (untitled, 1)):
        await connection.execute(
            text(
                f"UPDATE {s}.gallery_images SET current_version_id = :v WHERE id = :i"
            ),
            {"v": versions[(image, number)], "i": image},
        )
    await connection.execute(
        text(f"UPDATE {s}.galleries SET cover_image_id = :i WHERE id = :g"),
        {"i": sunset, "g": gallery},
    )
    for user, level in ((owner, "owner"), (reader, "read")):
        await connection.execute(
            text(
                f"INSERT INTO {s}.resource_grants (initiative_id, resource_type, "
                "resource_id, user_id, level, created_at, all_initiative_members) "
                "VALUES (:i, 'gallery', :g, :u, :l, now(), false)"
            ),
            {"i": initiative.id, "g": gallery, "u": user.id, "l": level},
        )
    comment = await _one(
        session,
        f"INSERT INTO {s}.comments (content, created_by, gallery_id, created_at) "
        "VALUES (:c, :u, :g, now()) RETURNING id",
        c=f"Lovely, as #doc[Spec]({spec.id}) says of #gallery-image[it]({sunset})",
        u=reader.id,
        g=gallery,
    )
    # A page whose editor state names a picture, and links a file the way
    # `[[ ]]` once did.
    body = _paragraph(
        _words("See "),
        {
            "type": "entity-mention",
            "version": 1,
            "entityType": "gallery_image",
            "entityId": sunset,
            "text": "Sunset",
        },
        _words(" and "),
        # Bold, so the editor keeps it a node of its own.
        _words("Spec", 1),
    )
    await connection.execute(
        text(
            f"UPDATE {s}.files SET content = CAST(:c AS jsonb), yjs_state = :y WHERE id = :f"
        ),
        {
            "c": json.dumps(body),
            "y": await _state_with_wikilink(body, "Spec", spec.id),
            "f": page.id,
        },
    )
    for source, relationship, target in (
        (("gallery", gallery), "tagged_with", ("tag", tag.id)),
        (("gallery_image", untitled), "tagged_with", ("tag", tag.id)),
        (("project", project.id), "references", ("gallery_image", sunset)),
        # Stored gallery first, as the gallery's code sorts below a project's.
        (("gallery", gallery), "attached", ("project", project.id)),
    ):
        await connection.execute(
            text(
                f"INSERT INTO {s}.relationships (source_type, source_id, "
                "relationship_type, target_type, target_id, provenance, created_at) "
                "VALUES (:st, :si, :r, :tt, :ti, 'manual', now())"
            ),
            {
                "st": source[0],
                "si": source[1],
                "r": relationship,
                "tt": target[0],
                "ti": target[1],
            },
        )
    notice = await _one(
        session,
        "INSERT INTO public.notifications (user_id, type, data, guild_id, tool, "
        "resource_id, subject_type, subject_id, created_at) VALUES (:u, 'mention', "
        "CAST(:d AS json), :guild, 'gallery', :g, 'gallery_image', :i, now()) "
        "RETURNING id",
        u=reader.id,
        d=json.dumps({"target_path": f"/go/gallery_image/{sunset}"}),
        guild=guild.id,
        g=gallery,
        i=sunset,
    )
    await connection.execute(text("SET LOCAL session_replication_role = origin"))
    await session.commit()

    await session.run_sync(run(True))
    await session.commit()

    files = {
        name: (file_id, file_type, number, archived_at)
        for file_id, name, file_type, number, archived_at in await _rows(
            session,
            f"SELECT f.id, f.name, f.file_type, v.version_number, f.archived_at "
            f"FROM {s}.files f "
            f"JOIN {s}.file_versions v ON v.id = f.current_version_id "
            "WHERE f.initiative_id = :i",
            i=initiative.id,
        )
    }
    # An archived gallery's pictures are archived with it.
    assert {name: rest[1:] for name, rest in files.items()} == {
        "Sunset": ("jpeg", 2, archived),
        "dunes.webp": ("webp", 1, archived),
    }
    sunset_file, dunes_file = files["Sunset"][0], files["dunes.webp"][0]
    assert await _rows(
        session,
        "SELECT file_id, version_number, file_url, created_by, width, height "
        f"FROM {s}.file_versions WHERE file_id IN (:a, :b) ORDER BY 1, 2",
        a=sunset_file,
        b=dunes_file,
    ) == sorted(
        [
            (sunset_file, 1, f"/uploads/{guild.id}/sunset-1.png", owner.id, 800, 600),
            (sunset_file, 2, f"/uploads/{guild.id}/sunset-2.jpg", reader.id, 900, 1600),
            # A version with no author takes its picture's.
            (dunes_file, 1, f"/uploads/{guild.id}/dunes.webp", owner.id, None, None),
        ]
    )
    assert await _rows(
        session,
        f"SELECT id, name, description, cover_file_id FROM {s}.collections",
    ) == [(gallery, "Wall", "Studio shots", sunset_file)]
    assert await _rows(
        session,
        f"SELECT file_id, added_by, added_at FROM {s}.collection_files "
        "WHERE collection_id = :g ORDER BY file_id",
        g=gallery,
    ) == sorted(
        [
            # Added when the picture was uploaded, as the gallery's timeline
            # dated it.
            (sunset_file, owner.id, datetime(2026, 2, 1, tzinfo=timezone.utc)),
            (dunes_file, owner.id, datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ]
    )
    # Each picture takes every grant its gallery gave, and the gallery none.
    assert await _rows(
        session,
        f"SELECT resource_type, resource_id, user_id, level FROM {s}.resource_grants "
        "WHERE (resource_type = 'gallery' AND resource_id = :g) "
        "OR (resource_type = 'file' AND resource_id IN (:a, :b)) "
        "ORDER BY 2, 3",
        a=sunset_file,
        b=dunes_file,
        g=gallery,
    ) == sorted(
        [
            ("file", file_id, user.id, level)
            for file_id in (sunset_file, dunes_file)
            for user, level in ((owner, "owner"), (reader, "read"))
        ],
        key=lambda row: (row[1], row[2]),
    )
    assert await _rows(
        session,
        f"SELECT collection_id, content FROM {s}.comments WHERE id = :c",
        c=comment,
    ) == [
        (
            gallery,
            f"Lovely, as #file[Spec]({spec.id}) says of #file[it]({sunset_file})",
        )
    ]
    # The page's links name the file each became, in its JSON and in the Yjs
    # state an editor opens.
    content, state = (
        await _rows(
            session,
            f"SELECT content, yjs_state FROM {s}.files WHERE id = :f",
            f=page.id,
        )
    )[0]
    expected = [
        ("entity-mention", "file", sunset_file),
        ("entity-mention", "file", spec.id),
    ]
    assert _references(content) == expected
    assert _references(await editor_engine.render(bytes(state))) == expected
    assert sorted(
        await _rows(
            session,
            "SELECT source_type, source_id, relationship_type, target_type, "
            f"target_id, source_node >> 32, target_node >> 32 FROM {s}.relationships",
        )
    ) == sorted(
        [
            ("collection", gallery, "tagged_with", "tag", tag.id, 17, 13),
            ("file", dunes_file, "tagged_with", "tag", tag.id, 6, 13),
            ("project", project.id, "references", "file", sunset_file, 10, 6),
            # Swapped, so the lower node still comes first.
            ("project", project.id, "attached", "collection", gallery, 10, 17),
        ]
    )
    # Made as the Gallery shape: a Caption field of its own, holding each
    # caption that says something, which its lists show as the gallery did.
    ((caption, name, kind),) = await _rows(
        session,
        f"SELECT id, name, CAST(type AS text) FROM {s}.metadata_definitions "
        "WHERE collection_id = :g",
        g=gallery,
    )
    assert (name, kind) == ("Caption", "text")
    assert await _rows(
        session,
        f"SELECT entity_type, entity_id, value_text FROM {s}.metadata_values "
        "WHERE property_id = :p",
        p=caption,
    ) == [("file", sunset_file, "Golden hour")]
    field = f"property:{caption}"
    card = {
        "type": "card",
        "children": [
            {"type": "field", "props": {"field": "name"}},
            {"type": "field", "props": {"field": field}},
        ],
    }
    assert await _rows(
        session,
        f"SELECT kind, definition FROM {s}.tool_layouts "
        "WHERE tool = 'collection' AND tool_id = :g ORDER BY kind",
        g=gallery,
    ) == [
        ("default", {"kind": "masonry"}),
        ("grid", {"hidden": False, "card": card}),
        ("masonry", {"hidden": False, "card": card}),
        ("table", {"hidden": True, "columns": ["name", field, "added"]}),
        ("timeline", {"hidden": False, "card": card}),
    ]
    assert await _rows(
        session,
        "SELECT tool, resource_id, subject_type, subject_id, CAST(data AS jsonb) "
        "FROM public.notifications WHERE id = :n",
        n=notice,
    ) == [
        (
            "file",
            sunset_file,
            "file",
            sunset_file,
            {"target_path": f"/go/file/{sunset_file}"},
        )
    ]
    assert (
        await _rows(
            session,
            "SELECT c.relname FROM pg_class c WHERE c.relnamespace = "
            "CAST(:schema AS regnamespace) AND c.relname ~ '^galler' "
            "UNION SELECT a.attname FROM pg_attribute a WHERE a.attrelid IN "
            "(CAST(:comments AS regclass), CAST(:initiatives AS regclass)) "
            "AND a.attname ~ 'galler' AND NOT a.attisdropped",
            schema=schema,
            comments=f"{schema}.comments",
            initiatives=f"{schema}.initiatives",
        )
        == []
    )
    assert await _rows(
        session,
        "SELECT public.relationship_kind_code('gallery'), "
        "public.relationship_kind_code('collection')",
    ) == [(None, 17)]
    assert await _rows(
        session,
        f"SELECT files_enabled FROM {s}.initiatives WHERE id = :i",
        i=initiative.id,
    ) == [(True,)]
    assert {("create_files", True), ("files_enabled", True)} <= set(
        await _rows(
            session,
            f"SELECT permission_key, enabled FROM {s}.initiative_role_permissions "
            "WHERE initiative_role_id = :r",
            r=role,
        )
    )
