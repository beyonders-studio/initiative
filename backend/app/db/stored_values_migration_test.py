"""Migrations 20261003_0445 and 20261003_0448 rename the stored guild values to
community and back, 20261005_0457 respells the stored plug-in values, and
20261006_0460 names a notice's document as its entity and back, and
20261008_0470 calls a plug-in's pages pages and back. Loaded
by path and run on rows an older release would have written, the way
``upload_initiative_backfill_test`` runs its revision."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import (
    create_plugin_service_registration,
    create_export_job,
    create_guild,
    create_dashboard,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
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


async def _sql(session, sql, params=None):
    return await (await session.connection()).execute(sql, params or {})


async def _scalar(session, sql, params=None):
    return (await _sql(session, sql, params)).scalar()


async def _stored(session, schema: str, job_id: int) -> dict:
    notification = (
        await _sql(session, text("SELECT type, data FROM public.notifications"))
    ).one()
    outbox = (
        await _sql(
            session, text("SELECT type, data, push_data FROM public.notice_outbox")
        )
    ).one()
    source = await _scalar(
        session,
        text(f'SELECT source FROM "{schema}".data_jobs WHERE id = :id'),
        {"id": job_id},
    )
    return {
        "notification": (notification.type, notification.data),
        "outbox": (outbox.type, outbox.data, outbox.push_data),
        "source": source,
    }


def _guild_source(migration: ModuleType, bind, source: dict[str, str]) -> None:
    """The guild half of 0445 on the table that is still there, by the name it
    has now (20261030_0562). The members' AI key and preference tables it also
    respelled went in 20261021_0533."""
    migration._unforced(
        bind,
        ("data_jobs",),
        lambda: migration._set_value(bind, "data_jobs", "source", source),
    )


async def test_stored_values_say_community_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    job = await create_export_job(session, guild, user, source="guild")
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.export_ready,
        data={},
    )
    await notice_outbox.enqueue(
        session,
        [notice_outbox.row(user.id, guild.id, NotificationType.export_ready, {})],
    )
    old_data = {"guild_id": guild.id, "guild_name": None, "source": "guild"}
    await _sql(
        session,
        text("UPDATE public.notifications SET type = 'guild_welcome', data = :d"),
        {"d": json.dumps({"guild_id": guild.id, "guild_name": "Acme"})},
    )
    await _sql(
        session,
        text(
            "UPDATE public.notice_outbox SET type = 'export_ready', "
            "data = CAST(:d AS jsonb), push_data = CAST(:p AS jsonb)"
        ),
        {"d": json.dumps(old_data), "p": json.dumps({"guild_id": str(guild.id)})},
    )
    await session.commit()

    migration = _load("20261003_0445_stored_values_say_community.py")
    old = await _stored(session, schema, job.id)

    def upgrade(sync_session) -> None:
        bind = sync_session.connection()
        migration._public(
            bind,
            migration.NOTIFICATION_TYPES,
            migration.PAYLOAD_KEYS,
            ("guild", "community"),
            {"guild": "community"},
        )
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        _guild_source(migration, bind, {"guild": "community"})

    await session.run_sync(upgrade)
    await session.commit()
    assert await _stored(session, schema, job.id) == {
        "notification": (
            "community_welcome",
            {"community_id": guild.id, "community_name": "Acme"},
        ),
        "outbox": (
            "export_ready",
            {"community_id": guild.id, "community_name": None, "source": "community"},
            {"community_id": str(guild.id)},
        ),
        "source": "community",
    }

    def downgrade(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        _guild_source(migration, bind, {"community": "guild"})
        migration._public(
            bind,
            {new: o for o, new in migration.NOTIFICATION_TYPES.items()},
            {new: o for o, new in migration.PAYLOAD_KEYS.items()},
            ("community", "guild"),
            {"community": "guild"},
        )

    await session.run_sync(downgrade)
    await session.commit()
    assert await _stored(session, schema, job.id) == old


_ENDPOINT = "app.tests.plugin-service.summary"
_OLD_DEFINITION = {
    "app_kind": "service",
    "service": {
        "public_id": "tests.plugin-service",
        "protocol": 1,
        "scopes": ["documents:read", "apps:tests.other"],
    },
    "endpoints": [{"id": _ENDPOINT, "direction": "read"}],
    "events": ["app.tests.plugin-service.opened"],
    "community_summary": _ENDPOINT,
    "hosts": ["app.example.com"],
}
_NEW_DEFINITION = {
    "plugin_kind": "service",
    "service": {
        "public_id": "tests.plugin-service",
        "protocol": 1,
        "scopes": ["documents:read", "plugins:tests.other"],
    },
    "endpoints": [{"id": "plugin.tests.plugin-service.summary", "direction": "read"}],
    "events": ["plugin.tests.plugin-service.opened"],
    "community_summary": "plugin.tests.plugin-service.summary",
    "hosts": ["app.example.com"],
}
_OLD_WIDGET = {
    "type": "app:SHPAPP00000001:summary",
    "binding": {"source": "app", "app_uid": "SHPAPP00000001", "endpoint_id": _ENDPOINT},
    "sample_data": {_ENDPOINT: {"rows": []}},
}
_NEW_WIDGET = {
    "type": "plugin:SHPAPP00000001:summary",
    "binding": {
        "source": "plugin",
        "plugin_uid": "SHPAPP00000001",
        "endpoint_id": "plugin.tests.plugin-service.summary",
    },
    "sample_data": {"plugin.tests.plugin-service.summary": {"rows": []}},
}


async def _plug_in_values(session, schema: str, ids: dict[str, int]) -> dict:
    async def one(sql: str, **params):
        return (await _sql(session, text(sql), params)).one()

    install = await one(
        f'SELECT definition, granted_scopes FROM "{schema}".guild_plugins'
    )
    dashboard = await one(
        f'SELECT definition FROM "{schema}".dashboards WHERE id = :id',
        id=ids["dashboard"],
    )
    hook = await one(f'SELECT event_types FROM "{schema}".webhook_subscriptions')
    listing = await one(
        "SELECT l.kind, v.definition FROM public.marketplace_listings l "
        "JOIN public.marketplace_listing_versions v ON v.listing_id = l.id "
        "WHERE l.id = :id",
        id=ids["listing"],
    )
    ceiling = await one(
        "SELECT scope_ceiling FROM public.plugin_service_registrations WHERE id = :id",
        id=ids["registration"],
    )
    notification = await one("SELECT type, data FROM public.notifications")
    return {
        "installed": install.definition,
        "granted": install.granted_scopes,
        "widgets": dashboard.definition["widgets"],
        "events": hook.event_types,
        "listing": (listing.kind, listing.definition),
        "ceiling": ceiling.scope_ceiling,
        "notification": (notification.type, notification.data),
    }


async def test_plug_in_values_are_respelled(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    install = await create_guild_plugin(
        session, guild, user, definition=_OLD_DEFINITION
    )
    initiative = await create_initiative(session, guild, user)
    dashboard = await create_dashboard(
        session, initiative, user, definition={"widgets": [_OLD_WIDGET]}
    )
    listing = await create_marketplace_listing(session)
    registration = await create_plugin_service_registration(
        session, scope_ceiling=["documents:read", "apps:tests.other"]
    )
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.plugin_consent_requested,
        data={},
    )
    await session.commit()
    migration = _load("20261005_0457_apps_are_plug_ins.py")

    def seed(sync_session) -> None:
        bind = sync_session.connection()

        def install_rows() -> None:
            bind.execute(
                text(
                    f'UPDATE "{schema}".guild_plugins '
                    "SET definition = CAST(:d AS jsonb), granted_scopes = :g"
                ),
                {"d": json.dumps(_OLD_DEFINITION), "g": ["apps:tests.other"]},
            )
            bind.execute(
                text(
                    f'INSERT INTO "{schema}".webhook_subscriptions '
                    "(plugin_install_id, target_url, hmac_secret, event_types, active, "
                    "created_at, updated_at) VALUES (:i, 'https://hooks.test/x', 's', "
                    ":e, true, now(), now())"
                ),
                {
                    "i": install.id,
                    "e": [
                        "apps.created",
                        "app.tests.plugin-service.opened",
                        "tasks.created",
                    ],
                },
            )

        migration._with_rows_writable(
            bind,
            schema,
            "webhook_subscriptions",
            lambda: migration._with_rows_writable(
                bind, schema, "guild_plugins", install_rows
            ),
        )

        def write(table: str, sql: str, params: dict) -> None:
            migration._with_rows_writable(
                bind, "public", table, lambda: bind.execute(text(sql), params)
            )

        write(
            "marketplace_listings",
            "UPDATE public.marketplace_listings SET kind = 'app' WHERE id = :id",
            {"id": listing.id},
        )
        write(
            "marketplace_listing_versions",
            "UPDATE public.marketplace_listing_versions "
            "SET definition = CAST(:d AS jsonb) WHERE listing_id = :id",
            {"d": json.dumps(_OLD_DEFINITION), "id": listing.id},
        )
        # The plug-in references 0457 respelled were named by install, a
        # shape ``identity_refs`` no longer holds (20261016_0515, which also
        # deletes them), so they are not seeded here.
        write(
            "notifications",
            "UPDATE public.notifications SET type = 'app_consent_requested', "
            "data = CAST(:d AS json)",
            {
                "d": json.dumps(
                    {"app_id": install.id, "target_path": f"/?app={install.id}"}
                )
            },
        )

    await session.run_sync(seed)
    await session.commit()

    def respell(sync_session) -> None:
        bind = sync_session.connection()
        migration._respell_public_values(bind)
        migration._respell_guild_values(bind, schema)

    await session.run_sync(respell)
    await session.commit()
    ids = {
        "dashboard": dashboard.id,
        "listing": listing.id,
        "registration": registration.id,
        "user": user.id,
        "install": install.id,
    }
    assert await _plug_in_values(session, schema, ids) == {
        "installed": _NEW_DEFINITION,
        "granted": ["plugins:tests.other"],
        "widgets": [_NEW_WIDGET],
        "events": [
            "plugins.created",
            "plugin.tests.plugin-service.opened",
            "tasks.created",
        ],
        "listing": ("plugin", _NEW_DEFINITION),
        "ceiling": ["documents:read", "plugins:tests.other"],
        "notification": (
            "plugin_consent_requested",
            {"plugin_id": install.id, "target_path": f"/?plugin={install.id}"},
        ),
    }


_PREFERENCES = {
    "my-tasks:focus": {
        "open": True,
        "pins": [{"guild_id": 3, "task_id": 4}, {"guild_id": None, "task_id": 5}, "x"],
    },
    "initiative-my-tasks-filters": {"statusFilters": ["todo"], "guildFilters": [3]},
    "initiative-my-calendar-prefs": {"calendarViewMode": "week", "guildFilters": []},
    "project:1:view-filters": {"guildFilters": [3]},
}


async def _view_state(session, user_id: int) -> dict:
    rows = (
        await _sql(
            session,
            text(
                "SELECT scope_key, value FROM public.user_view_preferences "
                "WHERE user_id = :u"
            ),
            {"u": user_id},
        )
    ).all()
    notification = await _scalar(session, text("SELECT data FROM public.notifications"))
    queued = await _scalar(session, text("SELECT data FROM public.notice_outbox"))
    return {
        "preferences": {row.scope_key: row.value for row in rows},
        "links": (notification["smart_link"], queued["smart_link"]),
    }


async def test_view_preferences_say_community_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    for scope, value in _PREFERENCES.items():
        await _sql(
            session,
            text(
                "INSERT INTO public.user_view_preferences (user_id, scope_key, value) "
                "VALUES (:u, :s, CAST(:v AS json))"
            ),
            {"u": user.id, "s": scope, "v": json.dumps(value)},
        )
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.export_ready,
        data={},
    )
    await notice_outbox.enqueue(
        session,
        [notice_outbox.row(user.id, guild.id, NotificationType.export_ready, {})],
    )
    link = {"smart_link": "https://app.example/navigate?guild_id=3&target=%2Fi"}
    await _sql(
        session,
        text("UPDATE public.notifications SET data = :d"),
        {"d": json.dumps(link)},
    )
    await _sql(
        session,
        text("UPDATE public.notice_outbox SET data = CAST(:d AS jsonb)"),
        {"d": json.dumps(link)},
    )
    await session.commit()
    migration = _load("20261003_0448_view_preferences_say_community.py")
    old = await _view_state(session, user.id)

    def run(names):
        return lambda sync_session: migration._rewrite(sync_session.connection(), names)

    await session.run_sync(run(migration.FORWARD))
    await session.commit()
    new_link = "https://app.example/navigate?community_id=3&target=%2Fi"
    assert await _view_state(session, user.id) == {
        "preferences": {
            "my-tasks:focus": {
                "open": True,
                "pins": [
                    {"community_id": 3, "task_id": 4},
                    {"community_id": None, "task_id": 5},
                    "x",
                ],
            },
            "initiative-my-tasks-filters": {
                "statusFilters": ["todo"],
                "communityFilters": [3],
            },
            "initiative-my-calendar-prefs": {
                "calendarViewMode": "week",
                "communityFilters": [],
            },
            "project:1:view-filters": {"guildFilters": [3]},
        },
        "links": (new_link, new_link),
    }

    await session.run_sync(run(migration.BACKWARD))
    await session.commit()
    assert await _view_state(session, user.id) == old


async def _notice_payloads(session) -> dict:
    lines = (
        await _sql(session, text("SELECT data FROM public.notifications ORDER BY id"))
    ).scalars()
    outbox = (
        await _sql(session, text("SELECT data, push_data FROM public.notice_outbox"))
    ).one()
    return {"lines": list(lines), "queued": (outbox.data, outbox.push_data)}


async def test_document_notices_name_their_entity_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    reply = {"comment_id": 1, "task_id": None, "document_id": 5, "replier_id": 2}
    # A task's reply carried the document key empty; it names no document.
    task_reply = {"comment_id": 2, "task_id": 9, "document_id": None, "replier_id": 2}
    task_mention = {
        "comment_id": 1,
        "mentioned_task_id": 7,
        "context_task_id": None,
        "context_document_id": 5,
        "context_entity_type": None,
        "context_entity_id": None,
    }
    for data in (reply, task_reply):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.comment_reply,
            data=data,
        )
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                user.id,
                guild.id,
                NotificationType.mention,
                task_mention,
                push_data={"mentioned_task_id": "7", "context_document_id": "5"},
            )
        ],
    )
    await session.commit()
    migration = _load("20261006_0460_document_notices_name_their_entity.py")
    old = await _notice_payloads(session)

    def run(step):
        return lambda sync_session: migration._unforced(
            sync_session.connection(), lambda: step(sync_session.connection())
        )

    await session.run_sync(run(migration._forward))
    await session.commit()
    assert await _notice_payloads(session) == {
        "lines": [
            {
                "comment_id": 1,
                "task_id": None,
                "entity_type": "document",
                "entity_id": 5,
                "replier_id": 2,
            },
            task_reply,
        ],
        "queued": (
            {
                "comment_id": 1,
                "mentioned_task_id": 7,
                "context_task_id": None,
                "context_entity_type": "document",
                "context_entity_id": 5,
            },
            {"mentioned_task_id": "7", "context_entity_id": "5"},
        ),
    }

    await session.run_sync(run(migration._backward))
    await session.commit()
    assert await _notice_payloads(session) == old


_EMBEDS_DEFINITION = {
    "plugin_kind": "service",
    "features": ["embeds", "endpoints"],
    "embeds": [{"id": "board", "path": "/board"}],
}
_PAGES_DEFINITION = {
    "plugin_kind": "service",
    "features": ["endpoints", "pages"],
    "pages": [{"id": "board", "path": "/board"}],
}


async def test_plugin_pages_are_pages_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    await create_guild_plugin(session, guild, user, definition=_EMBEDS_DEFINITION)
    listing = await create_marketplace_listing(session)
    await session.commit()
    migration = _load("20261008_0470_a_plugin_page_is_a_page.py")
    install_table = f'"{schema}".guild_plugins'
    versions = "public.marketplace_listing_versions"

    def seed(sync_session) -> None:
        bind = sync_session.connection()
        for table in (install_table, versions):
            migration._with_rows_writable(
                bind,
                table,
                lambda table=table: bind.execute(
                    text(f"UPDATE {table} SET definition = CAST(:d AS jsonb)"),
                    {"d": json.dumps(_EMBEDS_DEFINITION)},
                ),
            )

    async def stored() -> tuple[dict, dict]:
        install = await _scalar(
            session, text(f"SELECT definition FROM {install_table}")
        )
        version = await _scalar(
            session,
            text(f"SELECT definition FROM {versions} WHERE listing_id = :id"),
            {"id": listing.id},
        )
        return install, version

    async def respell(old: str, new: str) -> None:
        await session.run_sync(
            lambda sync_session: migration._definitions(
                sync_session.connection(), old, new
            )
        )
        await session.commit()

    await session.run_sync(seed)
    await session.commit()

    await respell("embeds", "pages")
    assert await stored() == (_PAGES_DEFINITION, _PAGES_DEFINITION)

    await respell("pages", "embeds")
    assert await stored() == (_EMBEDS_DEFINITION, _EMBEDS_DEFINITION)
