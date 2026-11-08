"""Migration 20261031_0576 moves each person's views of a community's lists into
that community.

Run on a guild the test builds, in one transaction rolled back at the end:
views kept where they live now, the revision stepped down so they are in
``public.user_view_preferences`` under ``view:<community id>:…`` as an older
release kept them, and up again. Each comes back as it was, the account's own
views stay in ``public``, and a view of a community that is gone leaves it.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models.tenant.view_preference import ViewPreference
from app.testing import create_guild, create_user, route_session_to_guild

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261031_0576_a_persons_views_of_a_community_are_its.py"
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


async def test_the_views_move_into_the_community_unchanged(session) -> None:
    owner = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=owner)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    await route_session_to_guild(session, guild.id)
    for person, key, value in (
        (owner.id, "view:project:12", {"layout": "table", "parts": {"table": {}}}),
        (owner.id, "view:members", {"parts": {"list": {"columns": {"email": False}}}}),
        (member.id, "view:project:12", {"layout": "board"}),
    ):
        session.add(
            ViewPreference(user_id=person, scope_key=key, value=value, updated_at=at)
        )
    await session.commit()

    held = (
        "SELECT user_id, scope_key, value::text, updated_at"
        f' FROM "guild_{guild.id}".view_preferences ORDER BY 1, 2'
    )
    in_public = (
        "SELECT user_id, scope_key FROM public.user_view_preferences ORDER BY 1, 2"
    )
    migration = _load()

    try:
        views = await _rows(session, held)
        assert len(views) == 3

        await session.run_sync(_step(migration, False))
        assert await _rows(session, in_public) == [
            (owner.id, f"view:{guild.id}:members"),
            (owner.id, f"view:{guild.id}:project:12"),
            (member.id, f"view:{guild.id}:project:12"),
        ]
        assert await _rows(
            session, f"SELECT to_regclass('guild_{guild.id}.view_preferences')"
        ) == [(None,)]

        # The account's own views, and a view of a community since deleted.
        await (await session.connection()).execute(
            text(
                "INSERT INTO public.user_view_preferences"
                " (user_id, scope_key, value, updated_at) VALUES"
                " (:u, 'view:me:tasks', '{}', now()),"
                " (:u, 'project:42:tasks', '{}', now()),"
                " (:u, :gone, '{}', now())"
            ),
            {"u": owner.id, "gone": f"view:{guild.id + 1000}:project:3"},
        )

        await session.run_sync(_step(migration, True))
        assert await _rows(session, held) == views
        assert await _rows(session, in_public) == [
            (owner.id, "project:42:tasks"),
            (owner.id, "view:me:tasks"),
        ]
    finally:
        await session.rollback()
