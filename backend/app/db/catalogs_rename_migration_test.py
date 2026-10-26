"""Migrations 20261026_0538 and 20261026_0539 call the galleries tool catalogs.

Loaded by path and run on a guild the test builds: down to the names an older
release wrote, rows written that way, then up, down and up again, the way
``files_rename_migration_test`` runs the documents rename.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.db.schema_provisioning import apply_guild_rls
from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import (
    create_catalog,
    create_catalog_item,
    create_dashboard,
    create_export_job,
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_project,
    create_property_definition,
    create_property_value,
    create_relationship,
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


# A statement's quoted values and its output aliases are left as written; the
# names it reads move, quoted or not.
_OLD_STATEMENT = (
    'SELECT i.title AS "galleries", i."gallery_id", gallery.name '
    'FROM "gallery_images" i JOIN galleries g ON g.id = i.gallery_id '
    "WHERE g.name <> 'galleries'"
)
_NEW_STATEMENT = (
    'SELECT i.title AS "galleries", i."catalog_id", catalog.name '
    'FROM "catalog_items" i JOIN catalogs g ON g.id = i.catalog_id '
    "WHERE g.name <> 'galleries'"
)
# A relation read through moves with the dataset; an alias somebody chose
# that happens to say ``gallery`` is theirs.
_ALIASED_OLD = "SELECT gallery.name FROM galleries gallery"
_ALIASED_NEW = "SELECT gallery.name FROM catalogs gallery"


def _guild_runner(schema: str):
    """Revision 0538 one way or the other, on one guild's schema only."""
    catalogs = _load("20261026_0538_galleries_are_catalogs.py")

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
                catalogs._convert(bind, forward, in_schema)

        return apply

    return run


async def _guild_values(session, schema: str, ids: dict[str, int]) -> dict:
    s = f'"{schema}"'
    return {
        "tables": await _rows(
            session,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name ~ '^(galler|catalog)' "
            "ORDER BY 1",
            schema=schema,
        ),
        "grants": await _rows(
            session,
            f"SELECT DISTINCT resource_type FROM {s}.resource_grants "
            "WHERE resource_id = :id AND resource_type IN ('catalog', 'gallery')",
            id=ids["catalog"],
        ),
        "property": await _rows(
            session, f"SELECT entity_type FROM {s}.property_values"
        ),
        "edge": await _rows(
            session,
            f"SELECT source_type, target_type, source_node, target_node "
            f"FROM {s}.relationships",
        ),
        "permissions": await _rows(
            session,
            f"SELECT DISTINCT permission_key FROM {s}.initiative_role_permissions "
            "WHERE permission_key ~ '(catalog|galler)' ORDER BY 1",
        ),
        "outbox": await _rows(
            session,
            f"SELECT resource_type, dac_tool, parents, changed FROM {s}.event_outbox "
            "WHERE id = :id",
            id=ids["outbox"],
        ),
        "webhook": await _rows(
            session, f"SELECT event_types, fields FROM {s}.webhook_subscriptions"
        ),
        "plugin": await _rows(
            session, f"SELECT granted_scopes, definition FROM {s}.guild_plugins"
        ),
        "dashboard": await _rows(
            session,
            f"SELECT definition FROM {s}.dashboards WHERE id = :id",
            id=ids["dashboard"],
        ),
        "export": await _rows(
            session,
            f"SELECT source, params FROM {s}.export_jobs WHERE id = :id",
            id=ids["export"],
        ),
    }


async def test_guild_values_say_catalog_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    catalog = await create_catalog(session, initiative, user)
    item = await create_catalog_item(session, catalog, user, write_blob=False)
    definition = await create_property_definition(session, initiative)
    await create_property_value(session, item, definition, value_text="kept")
    await create_relationship(
        session,
        guild,
        source=(SearchEntityType.project, project.id),
        target=(SearchEntityType.catalog_item, item.id),
    )
    plugin_definition = {
        "service": {"scopes": ["galleries:read", "tasks:read"]},
        "fields": [{"key": "sku", "itemKind": "gallery_image"}],
    }
    await create_guild_plugin(
        session,
        guild,
        user,
        definition=plugin_definition,
        granted_scopes=["galleries:read", "galleries:write"],
    )
    dashboard = await create_dashboard(
        session,
        initiative,
        user,
        definition={
            "widgets": [
                {"id": "w1", "binding": {"source": "query", "sql": _OLD_STATEMENT}},
                {"id": "w2", "binding": {"entity": "gallery"}},
                {"id": "w3", "binding": {"source": "query", "sql": _ALIASED_OLD}},
            ]
        },
    )
    job = await create_export_job(
        session,
        guild,
        user,
        source="gallery",
        params={"gallery_ids": [catalog.id], "formats": {"gallery": "json"}},
    )
    await session.commit()

    run = _guild_runner(schema)

    try:
        await session.run_sync(run(False))
        outbox_id = (
            await _rows(
                session,
                f'INSERT INTO "{schema}".event_outbox (txn_id, occurred_at, '
                "resource_type, resource_id, action, dac_tool, parents, changed) "
                "VALUES (1, now(), 'galleries', :id, 'updated', 'gallery', "
                "CAST(:parents AS jsonb), ARRAY['cover_image_id', 'images']) "
                "RETURNING id",
                id=catalog.id,
                parents=json.dumps([{"id": catalog.id, "type": "galleries"}]),
            )
        )[0][0]
        await (await session.connection()).execute(
            text(
                f'INSERT INTO "{schema}".webhook_subscriptions (target_url, '
                "hmac_secret, event_types, fields) VALUES ('https://hook.test', "
                "'s', ARRAY['galleries.updated', 'tasks.created'], "
                "ARRAY['gallery_id', 'name'])"
            )
        )
        await session.commit()
        ids = {
            "catalog": catalog.id,
            "outbox": outbox_id,
            "dashboard": dashboard.id,
            "export": job.id,
        }
        old = await _guild_values(session, schema, ids)

        await session.run_sync(run(True))
        await session.commit()
        node = (8 << 32) | item.id
        new = await _guild_values(session, schema, ids)
        assert new["tables"] == [
            ("catalog_item_versions",),
            ("catalog_items",),
            ("catalogs",),
        ]
        # Row security comes back on and forced, with the policies the next
        # start renders from the registries not yet there.
        assert await _rows(
            session,
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) "
            "FROM pg_class c WHERE c.relnamespace = CAST(:schema AS regnamespace) "
            "AND c.relname IN ('catalogs', 'catalog_items', 'catalog_item_versions', "
            "'comments', 'initiatives') ORDER BY 1",
            schema=schema,
        ) == [
            ("catalog_item_versions", True, True, 0),
            ("catalog_items", True, True, 0),
            ("catalogs", True, True, 0),
            ("comments", True, True, 0),
            ("initiatives", True, True, 0),
        ]
        # What a start applies puts them back under the new names.
        await apply_guild_rls(await session.connection(), schema)
        assert (
            await _rows(
                session,
                "SELECT c.relname FROM pg_class c WHERE c.relnamespace = "
                "CAST(:schema AS regnamespace) AND c.relname IN ('catalogs', "
                "'catalog_items', 'catalog_item_versions', 'comments', 'initiatives') "
                "AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)",
                schema=schema,
            )
            == []
        )
        assert new["grants"] == [("catalog",)]
        assert new["property"] == [("catalog_item",)]
        ((source, target, *nodes),) = new["edge"]
        assert {source, target} == {"project", "catalog_item"} and node in nodes
        # The node ids are computed, and the item kind keeps its code.
        assert [edge[2:] for edge in new["edge"]] == [edge[2:] for edge in old["edge"]]
        assert new["permissions"] == [("catalogs_enabled",), ("create_catalogs",)]
        assert new["outbox"] == [
            (
                "catalogs",
                "catalog",
                [{"id": catalog.id, "type": "catalogs"}],
                ["cover_item_id", "items"],
            )
        ]
        assert new["webhook"] == [
            (["catalogs.updated", "tasks.created"], ["catalog_id", "name"])
        ]
        assert new["plugin"] == [
            (
                ["catalogs:read", "catalogs:write"],
                {
                    "service": {"scopes": ["catalogs:read", "tasks:read"]},
                    "fields": [{"key": "sku", "itemKind": "catalog_item"}],
                },
            )
        ]
        assert new["dashboard"] == [
            (
                {
                    "widgets": [
                        {
                            "id": "w1",
                            "binding": {"source": "query", "sql": _NEW_STATEMENT},
                        },
                        {"id": "w2", "binding": {"entity": "catalog"}},
                        {
                            "id": "w3",
                            "binding": {"source": "query", "sql": _ALIASED_NEW},
                        },
                    ]
                },
            )
        ]
        assert new["export"] == [
            ("catalog", {"catalog_ids": [catalog.id], "formats": {"catalog": "json"}})
        ]

        await session.run_sync(run(False))
        await session.commit()
        assert await _guild_values(session, schema, ids) == old
        assert old["grants"] == [("gallery",)]
        assert old["tables"] == [
            ("galleries",),
            ("gallery_image_versions",),
            ("gallery_images",),
        ]
    finally:
        await session.run_sync(run(True))
        await session.commit()


async def test_an_edge_between_two_items_is_respelled(session) -> None:
    """Both ends name the kind, and the rewrite reaches them one column at a
    time, so the code reads both spellings while it does."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    catalog = await create_catalog(session, initiative, user)
    first = await create_catalog_item(session, catalog, user, write_blob=False)
    second = await create_catalog_item(session, catalog, user, write_blob=False)
    await create_relationship(
        session,
        guild,
        source=(SearchEntityType.catalog_item, first.id),
        target=(SearchEntityType.catalog_item, second.id),
        relationship_type=RelationshipType.related_to,
    )
    await session.commit()
    run = _guild_runner(schema)
    edge = (
        "SELECT source_type, target_type, source_node, target_node "
        f'FROM "{schema}".relationships'
    )
    nodes = ((8 << 32) | first.id, (8 << 32) | second.id)
    code = "SELECT public.relationship_kind_code(:kind)"

    try:
        await session.run_sync(run(False))
        await session.commit()
        assert sorted(await _rows(session, edge)) == sorted(
            [("gallery_image", "gallery_image", *nodes)]
        )
        assert await _rows(session, code, kind="catalog_item") == [(None,)]
    finally:
        # A failed step aborts the transaction; restore from a fresh one.
        await session.rollback()
        await session.run_sync(run(True))
        await session.commit()
    assert await _rows(session, edge) == [("catalog_item", "catalog_item", *nodes)]
    assert await _rows(session, code, kind="gallery_image") == [(None,)]


async def _public_values(session, user_id: int, registration_id: int) -> dict:
    return {
        "lines": await _rows(
            session,
            "SELECT tool, subject_type, CAST(data AS jsonb) FROM public.notifications "
            "WHERE user_id = :u ORDER BY id",
            u=user_id,
        ),
        "queued": await _rows(
            session,
            "SELECT data, push_data, rollup_key, email_link FROM public.notice_outbox "
            "WHERE user_id = :u",
            u=user_id,
        ),
        "ceiling": await _rows(
            session,
            "SELECT scope_ceiling FROM public.plugin_service_registrations "
            "WHERE id = :id",
            id=registration_id,
        ),
        "listings": await _rows(
            session,
            "SELECT l.public_id, l.kind, v.definition "
            "FROM public.marketplace_listings l "
            "JOIN public.marketplace_listing_versions v ON v.listing_id = l.id "
            "WHERE l.public_id LIKE 'rename.%' ORDER BY l.public_id",
        ),
    }


async def test_public_values_say_catalog_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    line = {
        "tool": "gallery",
        "subject_type": "gallery_image",
        "entity_type": "gallery_image",
        "entity_id": 5,
        "target_path": "/go/gallery_image/5",
        "smart_link": "https://app.test/navigate?community_id=1"
        "&target=%2Fgo%2Fgallery_image%2F5",
        "rollup_key": "subscription:gallery_image:5",
    }
    page = {"target_path": "/c/1/i/2/galleries/5", "rollup_key": "gallery:5"}
    for data in (line, page):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.mention,
            data=data,
        )
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                user.id,
                guild.id,
                NotificationType.mention,
                {"context_entity_type": "gallery", "target_path": "/go/gallery/5"},
                push_data={"target_path": "/go/gallery/5"},
            )
        ],
    )
    registration = await create_plugin_service_registration(
        session, scope_ceiling=["galleries:read", "tasks:read"]
    )
    await (await session.connection()).execute(
        text(
            "UPDATE public.notifications SET tool = 'gallery', "
            "subject_type = 'gallery_image' WHERE user_id = :u"
        ),
        {"u": user.id},
    )
    await (await session.connection()).execute(
        text(
            "UPDATE public.notice_outbox SET rollup_key = 'gallery:5', "
            "email_link = 'https://app.test/navigate?target=%2Fgo%2Fgallery%2F5' "
            "WHERE user_id = :u"
        ),
        {"u": user.id},
    )
    # Published before the rename: a gallery, a dashboard and a plug-in.
    # Built valid, then written back the way the old build stored them.
    gallery_definition = {
        "type": "initiative-gallery",
        "name": "Wall",
        "images": [{"storage_key": "a.png", "external_ref": "gallery_image:4"}],
        "permissions": {"galleries_enabled": True},
    }
    dashboard_definition = {
        "type": "initiative-dashboard",
        "name": "Board",
        "definition": {
            "widgets": [
                {"id": "w1", "binding": {"source": "query", "sql": _OLD_STATEMENT}}
            ]
        },
    }
    plugin_definition = {"service": {"scopes": ["galleries:read"]}}
    for uid, name, kind, body in (
        ("RENAMETEST0011", "rename.catalog", "gallery", gallery_definition),
        ("RENAMETEST0012", "rename.dashboard", "dashboard", dashboard_definition),
        ("RENAMETEST0013", "rename.plugin", "plugin", plugin_definition),
    ):
        listing = await create_marketplace_listing(session, uid=uid, public_id=name)
        await (await session.connection()).execute(
            text("UPDATE public.marketplace_listings SET kind = :k WHERE id = :id"),
            {"k": kind, "id": listing.id},
        )
        await (await session.connection()).execute(
            text(
                "UPDATE public.marketplace_listing_versions "
                "SET definition = CAST(:d AS jsonb) WHERE listing_id = :id"
            ),
            {"d": json.dumps(body), "id": listing.id},
        )
    for key in ("view:1:gallery:5", "galleries:view-mode", "my-tasks"):
        await (await session.connection()).execute(
            text(
                "INSERT INTO public.user_view_preferences "
                "(user_id, scope_key, value, updated_at) "
                "VALUES (:u, :k, CAST('{}' AS json), now())"
            ),
            {"u": user.id, "k": key},
        )
    await session.commit()
    migration = _load("20261026_0539_galleries_are_catalogs_in_public.py")
    old = await _public_values(session, user.id, registration.id)

    def run(step):
        def apply(sync_session) -> None:
            with Operations.context(
                MigrationContext.configure(sync_session.connection())
            ):
                step()

        return apply

    await session.run_sync(run(migration.upgrade))
    await session.commit()
    try:
        assert await _public_values(session, user.id, registration.id) == {
            "lines": [
                (
                    "catalog",
                    "catalog_item",
                    {
                        **line,
                        "tool": "catalog",
                        "subject_type": "catalog_item",
                        "entity_type": "catalog_item",
                        "target_path": "/go/catalog_item/5",
                        "smart_link": "https://app.test/navigate?community_id=1"
                        "&target=%2Fgo%2Fcatalog_item%2F5",
                        "rollup_key": "subscription:catalog_item:5",
                    },
                ),
                (
                    "catalog",
                    "catalog_item",
                    {"target_path": "/c/1/i/2/catalogs/5", "rollup_key": "catalog:5"},
                ),
            ],
            "queued": [
                (
                    {"context_entity_type": "catalog", "target_path": "/go/catalog/5"},
                    {"target_path": "/go/catalog/5"},
                    "catalog:5",
                    "https://app.test/navigate?target=%2Fgo%2Fcatalog%2F5",
                )
            ],
            "ceiling": [(["catalogs:read", "tasks:read"],)],
            "listings": [
                (
                    "rename.catalog",
                    "catalog",
                    {
                        "type": "initiative-catalog",
                        "name": "Wall",
                        "items": [
                            {"storage_key": "a.png", "external_ref": "catalog_item:4"}
                        ],
                        "permissions": {"catalogs_enabled": True},
                    },
                ),
                (
                    "rename.dashboard",
                    "dashboard",
                    {
                        "type": "initiative-dashboard",
                        "name": "Board",
                        "definition": {
                            "widgets": [
                                {
                                    "id": "w1",
                                    "binding": {
                                        "source": "query",
                                        "sql": _NEW_STATEMENT,
                                    },
                                }
                            ]
                        },
                    },
                ),
                # A plug-in manifest is its publisher's: refused, not rewritten.
                ("rename.plugin", "plugin", plugin_definition),
            ],
        }
        kept = await _rows(
            session,
            "SELECT scope_key FROM public.user_view_preferences WHERE user_id = :u",
            u=user.id,
        )
        assert kept == [("my-tasks",)]
    finally:
        await session.run_sync(run(migration.downgrade))
        await session.commit()
    assert await _public_values(session, user.id, registration.id) == old
    await session.run_sync(run(migration.upgrade))
    await session.commit()
