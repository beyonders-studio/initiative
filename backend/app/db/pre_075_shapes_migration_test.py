"""Migrations 20261109_0594 to 0596 write what releases before 0.75 stored in
today's shape: notification lines, plug-in definitions that said
``visibility``, and uploads with no recorded type. Loaded by path and run on
rows those releases would have written."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import (
    create_comment,
    create_file,
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
    create_project,
    create_reaction,
    create_task,
    create_upload,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

THUMBS = "\N{THUMBS UP SIGN}"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _sql(session, sql, params=None):
    return await (await session.connection()).execute(sql, params or {})


def _run(step, schema: str | None = None):
    def apply(sync_session) -> None:
        bind = sync_session.connection()
        if schema is not None:
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
        with Operations.context(MigrationContext.configure(bind)):
            step()

    return apply


async def test_notification_lines_take_todays_shape(session) -> None:
    owner = await create_user(session)
    reactor = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    task = await create_task(session, project)
    comment = await create_comment(session, owner, task=task)
    reaction = await create_reaction(session, reactor, comment=comment)
    await session.commit()

    gesture = {
        "community_id": guild.id,
        "target_type": "comment",
        "target_id": comment.id,
        "reactor_id": reactor.id,
        "reactor_name": "@reactor",
    }
    written = {
        "task": (
            "task_assignment",
            {
                "community_id": guild.id,
                "target_path": "tasks/12/details",
                "smart_link": f"http://app/navigate?community_id={guild.id}"
                "&target=%2Ftasks%2F12%2Fdetails",
            },
        ),
        "list": (
            "task_assignment",
            {"community_id": guild.id, "target_path": "/tasks"},
        ),
        "initiative": (
            "task_assignment",
            {"community_id": str(guild.id), "target_path": "/initiatives/4/projects"},
        ),
        "event": (
            "task_assignment",
            {"community_id": guild.id, "target_path": "/go/event/9"},
        ),
        "account": ("task_assignment", {"target_path": "/settings/account"}),
        "current": (
            "task_assignment",
            {"community_id": guild.id, "target_path": "/go/task/1"},
        ),
        "pre_rollup": ("comment_reaction", {**gesture, "emoji": THUMBS}),
        "withdrawn": ("comment_reaction", {**gesture, "emoji": "\N{PARTY POPPER}"}),
    }
    ids = {}
    for name, (kind, data) in written.items():
        ids[name] = (
            await _sql(
                session,
                text(
                    "INSERT INTO public.notifications (user_id, type, data, created_at)"
                    " VALUES (:user, :kind, CAST(:data AS json), now()) RETURNING id"
                ),
                {"user": owner.id, "kind": kind, "data": json.dumps(data)},
            )
        ).scalar_one()
    await session.commit()

    migration = _load("20261109_0594_notification_lines_take_todays_shape.py")
    await session.run_sync(_run(migration.upgrade))
    await session.commit()

    stored = {
        row_id: data
        for row_id, data in (
            await _sql(
                session,
                text("SELECT id, data FROM public.notifications WHERE id = ANY(:ids)"),
                {"ids": list(ids.values())},
            )
        ).all()
    }
    path = {
        name: stored[ids[name]].get("target_path")
        for name in ids
        if ids[name] in stored
    }
    assert path["task"] == "/go/task/12"
    assert stored[ids["task"]]["smart_link"].endswith("&target=%2Fgo%2Ftask%2F12")
    assert path["list"] == "/"
    assert path["initiative"] == "/i/4"
    assert path["event"] == "/go/calendar-event/9"
    assert path["account"] == "/profile/account"
    assert path["current"] == "/go/task/1"

    line = stored[ids["pre_rollup"]]
    assert line["reactions"] == [
        {
            "id": reaction.id,
            "emoji": THUMBS,
            "reactor_id": reactor.id,
            "reactor_name": "@reactor",
        }
    ]
    assert (line["count"], line["reactor_ids"], line["reactor_count"]) == (
        1,
        [reactor.id],
        1,
    )
    assert line["target_path"] == f"/go/task/{task.id}"
    # Its reaction was taken back, so there is nothing left for it to name.
    assert ids["withdrawn"] not in stored


async def test_plugin_pages_and_endpoints_say_admin_only(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    earlier = {
        "plugin_kind": "service",
        "pages": [
            {"id": "admin", "visibility": "guild_admin"},
            {"id": "member", "visibility": "member", "admin_only": True},
            {"id": "manager", "visibility": "initiative_manager"},
            {"id": "today", "admin_only": False},
        ],
        "endpoints": [{"id": "report", "visibility": "guild_admin"}],
    }
    plugin = await create_guild_plugin(
        session, guild, user, definition={"plugin_kind": "service"}
    )
    listing = await create_marketplace_listing(session)
    await session.commit()
    install_table = f'"guild_{guild.id}".guild_plugins'
    versions = "public.marketplace_listing_versions"
    migration = _load("20261109_0595_plugin_pages_say_admin_only.py")

    def seed(sync_session) -> None:
        bind = sync_session.connection()
        for table, key, value in (
            (install_table, "id", plugin.id),
            (versions, "listing_id", listing.id),
        ):
            migration._with_rows_writable(
                bind,
                table,
                lambda table=table, key=key, value=value: bind.execute(
                    text(
                        f"UPDATE {table} SET definition = CAST(:d AS jsonb)"
                        f" WHERE {key} = :v"
                    ),
                    {"d": json.dumps(earlier), "v": value},
                ),
            )

    await session.run_sync(seed)
    await session.commit()
    await session.run_sync(_run(migration.upgrade))
    await session.commit()

    expected = {
        "plugin_kind": "service",
        "pages": [
            {"id": "admin", "admin_only": True},
            {"id": "member", "admin_only": True},
            {"id": "manager", "admin_only": False},
            {"id": "today", "admin_only": False},
        ],
        "endpoints": [{"id": "report", "admin_only": True}],
    }
    install = (
        await _sql(
            session,
            text(f"SELECT definition FROM {install_table} WHERE id = :id"),
            {"id": plugin.id},
        )
    ).scalar_one()
    version = (
        await _sql(
            session,
            text(f"SELECT definition FROM {versions} WHERE listing_id = :id"),
            {"id": listing.id},
        )
    ).scalar_one()
    assert install == expected
    assert version == expected


async def test_every_upload_names_its_type(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    await create_file(
        session,
        initiative,
        user,
        file_url=f"/uploads/{guild.id}/scan.bin",
        file_content_type="image/tiff",
    )
    names = ("scan.bin", "photo.JPG", "drawing.svg", "notes.txt")
    for name in names:
        await create_upload(session, guild, user, filename=name, commit=False)
    await session.commit()

    migration = _load("20261109_0596_every_upload_names_its_type.py")
    await session.run_sync(_run(migration._downgrade, schema))
    await _sql(session, text(f'UPDATE "{schema}".uploads SET content_type = NULL'))
    await session.commit()
    await session.run_sync(_run(migration._upgrade, schema))
    await session.commit()

    stored = dict(
        (
            await _sql(
                session, text(f'SELECT filename, content_type FROM "{schema}".uploads')
            )
        ).all()
    )
    assert {name: stored[name] for name in names} == {
        "scan.bin": "image/tiff",
        "photo.JPG": "image/jpeg",
        "drawing.svg": "image/svg+xml",
        "notes.txt": "application/octet-stream",
    }
    nullable = (
        await _sql(
            session,
            text(
                "SELECT is_nullable FROM information_schema.columns"
                " WHERE table_schema = :schema AND table_name = 'uploads'"
                " AND column_name = 'content_type'"
            ),
            {"schema": schema},
        )
    ).scalar_one()
    assert nullable == "NO"
