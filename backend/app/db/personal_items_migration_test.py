"""Migration 20261017_0517 merges ``recent_views``, ``favorites`` and
``project_orders`` into ``personal_items``, one row per person per item, and
splits them back. Loaded by path and run on a guild the test builds, the way
``tool_layouts_migration_test`` runs its revisions: down to the old shape, rows
written as an older release wrote them, up, and down again."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import (
    create_counter_group,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str):
    path = _VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_opens_stars_and_orders_merge_and_come_back(session) -> None:
    """A view, a bookmark and an order on one project become one row; each alone
    becomes its own. The downgrade splits them back, leaving subscriptions behind and
    an order on a project that is gone."""
    user = await create_user(session)
    other = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user, name="All three")
    lone = await create_project(session, initiative, user, name="Ordered only")
    group = await create_counter_group(session, initiative, user)
    task = await create_task(session, project)
    migration = _load("20261017_0517_personal_items")

    def run(step):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                step(bind)

        return apply

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    jan = datetime(2026, 1, 1, tzinfo=UTC)
    feb = datetime(2026, 2, 1, tzinfo=UTC)

    # Back to the shape an older release had, with its rows as it wrote them.
    await session.run_sync(run(migration._apply_downgrade))
    await sql(
        f"INSERT INTO {schema}.recent_views"
        " (user_id, entity_type, entity_id, last_viewed_at, source) VALUES"
        " (:u, 'project', :p, :feb, 'search'), (:o, 'task', :t, :jan, 'direct')",
        u=user.id,
        o=other.id,
        p=project.id,
        t=task.id,
        jan=jan,
        feb=feb,
    )
    await sql(
        f"INSERT INTO {schema}.favorites (user_id, entity_type, entity_id, created_at)"
        " VALUES (:u, 'project', :p, :jan), (:u, 'counter_group', :g, :feb)",
        u=user.id,
        p=project.id,
        g=group.id,
        jan=jan,
        feb=feb,
    )
    await sql(
        f"INSERT INTO {schema}.project_orders (user_id, project_id, sort_order)"
        " VALUES (:u, :p, 1), (:u, :l, 0)",
        u=user.id,
        p=project.id,
        l=lone.id,
    )

    await session.run_sync(run(migration._apply_upgrade))
    rows = (
        await sql(
            "SELECT user_id, entity_type, entity_id, viewed_at, view_source,"
            f" bookmarked_at, subscribed_at, sort_order FROM {schema}.personal_items"
            " ORDER BY user_id, entity_type, entity_id"
        )
    ).all()
    assert [tuple(r) for r in rows] == sorted(
        [
            (user.id, "project", project.id, feb, "search", jan, None, 1.0),
            (user.id, "project", lone.id, None, None, None, None, 0.0),
            (user.id, "counter_group", group.id, None, None, feb, None, None),
            (other.id, "task", task.id, jan, "direct", None, None, None),
        ],
        key=lambda r: (r[0], r[1], r[2]),
    )
    for old in ("recent_views", "favorites", "project_orders"):
        assert (
            await sql("SELECT to_regclass(:t)", t=f"{schema}.{old}")
        ).scalar() is None

    # A subscription has no place in the old tables, nor an order on a project that
    # has gone.
    await sql(
        f"UPDATE {schema}.personal_items SET subscribed_at = now()"
        " WHERE entity_type = 'task'"
    )
    await sql(
        f"INSERT INTO {schema}.personal_items"
        " (user_id, entity_type, entity_id, sort_order)"
        " VALUES (:u, 'project', 999999, 2)",
        u=user.id,
    )
    await session.run_sync(run(migration._apply_downgrade))
    views = (
        await sql(
            "SELECT user_id, entity_type, entity_id, source FROM"
            f" {schema}.recent_views ORDER BY last_viewed_at"
        )
    ).all()
    assert [tuple(r) for r in views] == [
        (other.id, "task", task.id, "direct"),
        (user.id, "project", project.id, "search"),
    ]
    bookmarks = (
        await sql(f"SELECT entity_type FROM {schema}.favorites ORDER BY created_at")
    ).all()
    assert [r.entity_type for r in bookmarks] == ["project", "counter_group"]
    orders = (
        await sql(f"SELECT project_id FROM {schema}.project_orders ORDER BY sort_order")
    ).all()
    assert [r.project_id for r in orders] == [lone.id, project.id]

    # And up again, to leave the schema as the head has it.
    await session.run_sync(run(migration._apply_upgrade))
