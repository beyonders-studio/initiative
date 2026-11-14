"""Migration 20261008_0470 calls a plug-in's pages pages and back. Loaded by
path and run on rows an older release would have written."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from app.testing import (
    create_guild,
    create_guild_plugin,
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
