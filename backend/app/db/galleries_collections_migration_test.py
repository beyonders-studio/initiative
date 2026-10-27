"""Migration 20261027_0545 turns galleries into collections and their pictures
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
from sqlalchemy import text

from app.testing import (
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
    """Revision 0543 one way or the other, on one guild's schema only."""
    migration = _load("20261027_0545_galleries_are_collections.py")

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
                migration._convert(bind, forward, in_schema)

        return apply

    return run


async def test_a_gallery_becomes_a_collection_of_files(session) -> None:
    owner = await create_user(session)
    reader = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"
    s = f'"{schema}"'
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    tag = await create_tag(session, guild)
    await session.commit()
    run = _runner(schema)
    await session.run_sync(run(False))
    await session.commit()

    # A gallery as 0.68 stored one: two pictures, the first replaced once, a
    # restricted grant, a comment, tags on it and on a picture, and links.
    connection = await session.connection()
    await connection.execute(text("SET LOCAL session_replication_role = replica"))
    gallery = await _one(
        session,
        f"INSERT INTO {s}.galleries (initiative_id, name, description, created_by, "
        "created_at, updated_at) VALUES (:i, 'Wall', 'Studio shots', :u, "
        "'2026-01-01', '2026-01-02') RETURNING id",
        i=initiative.id,
        u=owner.id,
    )
    pictures = []
    for title, at in (
        ("Sunset", datetime(2026, 2, 1, tzinfo=timezone.utc)),
        (None, datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ):
        pictures.append(
            await _one(
                session,
                f"INSERT INTO {s}.gallery_images (gallery_id, title, caption, "
                "created_by, created_at, updated_at) VALUES (:g, :t, 'a caption', "
                ":u, :at, :at) RETURNING id",
                g=gallery,
                t=title,
                u=owner.id,
                at=at,
            )
        )
    sunset, untitled = pictures
    versions = {}
    for image, number, url, media, filename, author in (
        (sunset, 1, "sunset-1.png", "image/png", "sunset.png", owner.id),
        (sunset, 2, "sunset-2.jpg", "image/jpeg", "sunset.jpg", reader.id),
        (untitled, 1, "dunes.webp", "image/webp", "dunes.webp", None),
    ):
        versions[(image, number)] = await _one(
            session,
            f"INSERT INTO {s}.gallery_image_versions (gallery_image_id, "
            "version_number, file_url, file_content_type, original_filename, "
            "created_by, created_at) VALUES (:i, :n, :url, :m, :f, :u, now()) "
            "RETURNING id",
            i=image,
            n=number,
            url=f"/uploads/{guild.id}/{url}",
            m=media,
            f=filename,
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
        "VALUES ('Lovely', :u, :g, now()) RETURNING id",
        u=reader.id,
        g=gallery,
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
        name: (file_id, file_type, number)
        for file_id, name, file_type, number in await _rows(
            session,
            f"SELECT f.id, f.name, f.file_type, v.version_number FROM {s}.files f "
            f"JOIN {s}.file_versions v ON v.id = f.current_version_id "
            "WHERE f.initiative_id = :i",
            i=initiative.id,
        )
    }
    assert {name: rest[1:] for name, rest in files.items()} == {
        "Sunset": ("jpeg", 2),
        "dunes.webp": ("webp", 1),
    }
    sunset_file, dunes_file = files["Sunset"][0], files["dunes.webp"][0]
    assert await _rows(
        session,
        "SELECT file_id, version_number, file_url, created_by "
        f"FROM {s}.file_versions WHERE file_id IN (:a, :b) ORDER BY 1, 2",
        a=sunset_file,
        b=dunes_file,
    ) == sorted(
        [
            (sunset_file, 1, f"/uploads/{guild.id}/sunset-1.png", owner.id),
            (sunset_file, 2, f"/uploads/{guild.id}/sunset-2.jpg", reader.id),
            # A version with no author takes its picture's.
            (dunes_file, 1, f"/uploads/{guild.id}/dunes.webp", owner.id),
        ]
    )
    assert await _rows(
        session,
        f"SELECT id, name, description, cover_file_id FROM {s}.collections",
    ) == [(gallery, "Wall", "Studio shots", sunset_file)]
    assert await _rows(
        session,
        f"SELECT file_id, added_by FROM {s}.collection_files "
        "WHERE collection_id = :g ORDER BY file_id",
        g=gallery,
    ) == sorted([(sunset_file, owner.id), (dunes_file, owner.id)])
    # Each picture takes every grant its gallery gave, and the gallery none.
    assert await _rows(
        session,
        f"SELECT resource_type, resource_id, user_id, level FROM {s}.resource_grants "
        "WHERE resource_type IN ('gallery', 'file') AND resource_id IN (:a, :b, :g) "
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
        session, f"SELECT collection_id FROM {s}.comments WHERE id = :c", c=comment
    ) == [(gallery,)]
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
    assert await _rows(
        session,
        f"SELECT kind, definition FROM {s}.tool_layouts "
        "WHERE tool = 'collection' AND tool_id = :g ORDER BY kind",
        g=gallery,
    ) == [
        ("default", {"kind": "masonry"}),
        ("masonry", {"hidden": False}),
        ("table", {"hidden": True}),
        ("timeline", {"hidden": False}),
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
