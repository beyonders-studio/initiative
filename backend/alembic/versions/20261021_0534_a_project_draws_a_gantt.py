"""a project draws a gantt

A project lists its tasks as a table, a board, a Gantt or a calendar, and
shows in its menu the ones it has not hidden (``hidden`` on a list's layout),
always one at least. As shipped a project shows every list and opens on its
table, so no existing project needs a row written. The kinds a layout may be
are rendered at boot from the registry; this revision restates them only so
the Gantt layouts a project writes are admitted.

My Tasks (``view:me:tasks`` in ``user_view_preferences``) is a table only, so
its view keeps no layout or month.

The downgrade takes away the Gantt layouts and what opens on them, and the
shown or hidden each list keeps.

Revision ID: 20261021_0534
Revises: 20261021_0533
Create Date: 2026-10-21
"""

import json
from typing import Any, Callable

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261021_0534"
down_revision = "20261021_0533"
branch_labels = None
depends_on = None

LAYOUTS = "tool_layouts"
PREFERENCES = "public.user_view_preferences"
MY_TASKS_VIEW = "view:me:tasks"
CHECK = "ck_tool_layouts_kind"
_OTHER_KINDS = (
    "calendar",
    "task",
    "calendar_event",
    "queue_item",
    "gallery_image",
    "counter",
    "post",
    "default",
)
#: The kinds a layout may be, after and before this revision.
KINDS = {
    True: ("table", "board", "gantt", *_OTHER_KINDS),
    False: ("table", "board", *_OTHER_KINDS),
}
GANTT = "gantt"
DEFAULT = "default"


def _forced(table: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        )
        .scalar()
    )


def _unforced(table: str, write: Callable[[], None]) -> None:
    """Run ``write`` with the owner's row security lifted on ``table`` and its
    user triggers held, both restored after."""
    forced = _forced(table)
    if forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        write()
    finally:
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _restate_kinds(forward: bool) -> None:
    kinds = ", ".join(f"'{kind}'" for kind in KINDS[forward])
    op.execute(f"ALTER TABLE {LAYOUTS} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(
        f"ALTER TABLE {LAYOUTS} ADD CONSTRAINT {CHECK} CHECK (kind IN ({kinds}))"
    )


def _rewrite_layouts(forward: bool) -> None:
    bind = op.get_bind()

    def upgrade_rows() -> None:
        _restate_kinds(True)

    def downgrade_rows() -> None:
        bind.execute(
            sa.text(
                f"DELETE FROM {LAYOUTS} WHERE kind = :gantt"
                " OR kind = :default AND definition ->> 'kind' = :gantt"
            ),
            {"gantt": GANTT, "default": DEFAULT},
        )
        bind.execute(
            sa.text(
                f"UPDATE {LAYOUTS} SET definition = definition - 'hidden'"
                " WHERE definition ? 'hidden'"
            )
        )
        _restate_kinds(False)

    _unforced(LAYOUTS, upgrade_rows if forward else downgrade_rows)


def _my_tasks_view(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: kept for key, kept in value.items() if key not in ("layout", "mode")}


def _rewrite_my_tasks() -> None:
    bind = op.get_bind()

    def write() -> None:
        rows = bind.execute(
            sa.text(
                f"SELECT user_id, value FROM {PREFERENCES} WHERE scope_key = :mine"
            ),
            {"mine": MY_TASKS_VIEW},
        ).all()
        for user_id, value in rows:
            moved = _my_tasks_view(value)
            if moved != value:
                bind.execute(
                    sa.text(
                        f"UPDATE {PREFERENCES} SET value = CAST(:v AS json) "
                        "WHERE user_id = :u AND scope_key = :s"
                    ),
                    {"v": json.dumps(moved), "u": user_id, "s": MY_TASKS_VIEW},
                )

    _unforced(PREFERENCES, write)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _rewrite_layouts(True))
    # A table was all My Tasks drew before its calendar, too, so the downgrade
    # has nothing to put back.
    _rewrite_my_tasks()


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _rewrite_layouts(False))
