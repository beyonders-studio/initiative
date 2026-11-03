"""Migration 20261031_0574 moves what a webhook subscription calls people into
its community.

Run on a guild the test builds, in one transaction rolled back at the end:
names minted where they live now, the revision stepped down so they are in
``public.identity_refs`` as an older release kept them, and up again. A
receiver holds the values, so each comes back exactly as it was; a name whose
subscription is gone, and one that was replaced, do not come back.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.services.tenant import webhook_refs
from app.testing import create_guild, create_user, create_webhook_subscription

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261031_0574_a_subscriptions_names_are_the_communitys.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


def _step(migration: ModuleType, forward: bool):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            (migration.upgrade if forward else migration.downgrade)()

    return apply


async def test_the_names_move_into_the_community_unchanged(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    subscription = await create_webhook_subscription(session, guild, user)
    await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=None,
        subscription_id=subscription.id,
        actor_ids=(user.id,),
    )
    held = (
        "SELECT subscription_id, entity_type, entity_id, ref, created_at"
        f' FROM "guild_{guild.id}".webhook_refs ORDER BY 1, 2, 3'
    )
    in_public = (
        "SELECT sector_id, entity_type, entity_id, ref, created_at"
        " FROM public.identity_refs WHERE purpose = 'webhook'"
        " AND sector_guild_id = :g ORDER BY 1, 2, 3"
    )
    migration = _load()

    try:
        names = await _rows(session, held)
        assert len(names) == 2

        await session.run_sync(_step(migration, False))
        assert await _rows(session, in_public, g=guild.id) == names
        assert await _rows(
            session, f"SELECT to_regclass('guild_{guild.id}.webhook_refs')"
        ) == [(None,)]

        # A name for a subscription since deleted, and one since replaced.
        await (await session.connection()).execute(
            text(
                "INSERT INTO public.identity_refs (ref, entity_type, entity_id,"
                " purpose, sector_guild_id, sector_id, created_at, retired_at)"
                " VALUES ('gweb_gone', 'guild', :g, 'webhook', :g, :gone, now(), NULL),"
                " ('uweb_replaced', 'user', :u, 'webhook', :g, :s, now(), now())"
            ),
            {
                "g": guild.id,
                "gone": subscription.id + 1,
                "u": user.id,
                "s": subscription.id,
            },
        )

        await session.run_sync(_step(migration, True))
        assert await _rows(session, held) == names
        assert await _rows(
            session,
            "SELECT count(*) FROM public.identity_refs WHERE purpose = 'webhook'",
        ) == [(0,)]
    finally:
        await session.rollback()
