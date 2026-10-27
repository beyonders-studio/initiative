"""Migration 20261026_0542 gives catalog items a description and a date.

Loaded by path and run on a guild the test builds: down to the caption an
older release wrote, rows written that way, then up, down and up again, the
way ``catalogs_rename_migration_test`` runs the rename before it.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.schema_provisioning import apply_guild_rls
from app.testing import (
    create_catalog,
    create_catalog_item,
    create_dashboard,
    create_guild,
    create_initiative,
    create_marketplace_listing,
    create_user,
)

_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261026_0542_catalog_items_have_a_description_and_a_date.py"
)

# Only a statement that reads catalog items moves; a string value and a
# quoted output alias are left as written.
_ITEMS_OLD = (
    'SELECT i.caption, i."caption" AS "caption" FROM catalog_items i '
    "WHERE i.caption <> 'caption'"
)
_ITEMS_NEW = (
    'SELECT i.description, i."description" AS "caption" FROM catalog_items i '
    "WHERE i.description <> 'caption'"
)
_ELSEWHERE = "SELECT caption FROM files"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


def _runner(migration: ModuleType, step):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            step()

    return apply


def _in_guild(migration: ModuleType, schema: str, forward: bool):
    def step() -> None:
        migration.op.get_bind().execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        migration._guild(forward)

    return _runner(migration, step)


async def _values(session, schema: str, ids: dict[str, int], column: str) -> dict:
    s = f'"{schema}"'
    return {
        "item": await _rows(
            session,
            f"SELECT {column} FROM {s}.catalog_items WHERE id = :id",
            id=ids["item"],
        ),
        "layout": await _rows(
            session,
            f"SELECT definition FROM {s}.tool_layouts WHERE id = :id",
            id=ids["layout"],
        ),
        "outbox": await _rows(
            session,
            f"SELECT changed FROM {s}.event_outbox WHERE id = :id",
            id=ids["outbox"],
        ),
        "webhook": await _rows(
            session, f"SELECT fields FROM {s}.webhook_subscriptions"
        ),
        "dashboard": await _rows(
            session,
            f"SELECT definition FROM {s}.dashboards WHERE id = :id",
            id=ids["dashboard"],
        ),
    }


async def test_a_caption_is_a_description_and_an_item_gains_its_date(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    catalog = await create_catalog(session, initiative, user)
    item = await create_catalog_item(
        session,
        catalog,
        user,
        created_at=datetime(2026, 3, 9, 23, 30, tzinfo=timezone.utc),
        write_blob=False,
    )
    dashboard = await create_dashboard(
        session,
        initiative,
        user,
        definition={
            "widgets": [
                {"id": "w1", "binding": {"source": "query", "sql": _ITEMS_OLD}},
                {"id": "w2", "binding": {"source": "query", "sql": _ELSEWHERE}},
            ]
        },
    )
    await session.commit()
    migration = _load()
    s = f'"{schema}"'

    await session.run_sync(_in_guild(migration, schema, False))
    # Written past the triggers a start renders, which name the columns as
    # this build spells them until the next start renders them again.
    for statement in (
        f"ALTER TABLE {s}.catalog_items DISABLE TRIGGER USER",
        f"UPDATE {s}.catalog_items SET caption = 'Dawn' WHERE id = {item.id}",
        f"ALTER TABLE {s}.catalog_items ENABLE TRIGGER USER",
    ):
        await (await session.connection()).execute(text(statement))
    layout_id = (
        await _rows(
            session,
            f"INSERT INTO {s}.tool_layouts (initiative_id, tool, tool_id, kind, "
            "definition, created_at, updated_at) VALUES (:i, 'catalog', :c, "
            "'catalog_item', CAST(:d AS jsonb), now(), now()) RETURNING id",
            i=initiative.id,
            c=catalog.id,
            d=json.dumps({"type": "field", "props": {"field": "caption"}}),
        )
    )[0][0]
    outbox_id = (
        await _rows(
            session,
            f"INSERT INTO {s}.event_outbox (txn_id, occurred_at, resource_type, "
            "resource_id, action, dac_tool, changed) VALUES (1, now(), "
            "'catalog_items', :id, 'updated', 'catalog', "
            "ARRAY['caption', 'title']) RETURNING id",
            id=item.id,
        )
    )[0][0]
    await (await session.connection()).execute(
        text(
            f"INSERT INTO {s}.webhook_subscriptions (target_url, hmac_secret, "
            "event_types, fields) VALUES ('https://hook.test', 's', "
            "ARRAY['catalog_items.updated'], ARRAY['caption', 'title'])"
        )
    )
    await session.commit()
    ids = {
        "item": item.id,
        "layout": layout_id,
        "outbox": outbox_id,
        "dashboard": dashboard.id,
    }
    old = await _values(session, schema, ids, "caption")

    await session.run_sync(_in_guild(migration, schema, True))
    await session.commit()
    assert await _values(session, schema, ids, "description, occurred_on") == {
        # Dated the day it was added, in UTC.
        "item": [("Dawn", date(2026, 3, 9))],
        "layout": [({"type": "field", "props": {"field": "description"}},)],
        "outbox": [(["description", "title"],)],
        "webhook": [(["description", "title"],)],
        "dashboard": [
            (
                {
                    "widgets": [
                        {"id": "w1", "binding": {"source": "query", "sql": _ITEMS_NEW}},
                        {"id": "w2", "binding": {"source": "query", "sql": _ELSEWHERE}},
                    ]
                },
            )
        ],
    }
    # Row security comes back on and forced, with the policies the next
    # start renders not yet there; what a start applies puts them back.
    assert await _rows(
        session,
        "SELECT c.relrowsecurity, c.relforcerowsecurity, "
        "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) "
        f"FROM pg_class c WHERE c.oid = to_regclass('{schema}.catalog_items')",
    ) == [(True, True, 0)]
    await apply_guild_rls(await session.connection(), schema)
    assert (
        await _rows(
            session,
            "SELECT count(*) FROM pg_policy "
            f"WHERE polrelid = to_regclass('{schema}.catalog_items')",
        )
    )[0][0] > 0

    await session.run_sync(_in_guild(migration, schema, False))
    await session.commit()
    assert await _values(session, schema, ids, "caption") == old
    await session.run_sync(_in_guild(migration, schema, True))
    await session.commit()


async def test_listings_say_description_and_back(session) -> None:
    catalog_definition = {
        "type": "initiative-catalog",
        "name": "Wall",
        "items": [{"storage_key": "a.png", "caption": "Dawn"}],
    }
    dashboard_definition = {
        "type": "initiative-dashboard",
        "name": "Board",
        "definition": {
            "widgets": [{"id": "w1", "binding": {"source": "query", "sql": _ITEMS_OLD}}]
        },
    }
    for uid, name, kind, body in (
        ("RENAMETEST0021", "describe.catalog", "catalog", catalog_definition),
        ("RENAMETEST0022", "describe.dashboard", "dashboard", dashboard_definition),
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
    await session.commit()
    migration = _load()

    async def definitions() -> list[tuple]:
        return await _rows(
            session,
            "SELECT l.public_id, v.definition FROM public.marketplace_listings l "
            "JOIN public.marketplace_listing_versions v ON v.listing_id = l.id "
            "WHERE l.public_id LIKE 'describe.%' ORDER BY 1",
        )

    old = await definitions()
    await session.run_sync(_runner(migration, lambda: migration._public(True)))
    await session.commit()
    assert await definitions() == [
        (
            "describe.catalog",
            {
                **catalog_definition,
                "items": [{"storage_key": "a.png", "description": "Dawn"}],
            },
        ),
        (
            "describe.dashboard",
            {
                **dashboard_definition,
                "definition": {
                    "widgets": [
                        {"id": "w1", "binding": {"source": "query", "sql": _ITEMS_NEW}}
                    ]
                },
            },
        ),
    ]

    await session.run_sync(_runner(migration, lambda: migration._public(False)))
    await session.commit()
    assert await definitions() == old
