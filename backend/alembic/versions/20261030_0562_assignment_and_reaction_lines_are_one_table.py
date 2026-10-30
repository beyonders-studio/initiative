"""Assignment and reaction lines are one table

The lines a burst of assignments or reactions waits in, before going out as one
email and one push, were two tables of one shape. In ``guild_template`` and
every ``guild_<id>``:

* ``reaction_digest_items`` is ``batched_notices``, its rows of ``kind``
  ``reaction``. ``reactor_id``, ``reactor_name`` and ``context_title`` are
  ``actor_id``, ``actor_name`` and ``title``; ``emoji`` may be empty, and an
  assignment's ``project_id`` and ``project_name`` are added.
* ``task_assignment_digest_items``'s rows move across as ``task_assignment``
  lines naming their task as ``('task', task_id)``, with the path a notice
  about it opens, and the table is dropped.
* The sweep marks of the renamed sweeps (``digest_gc``, ``task_digest``,
  ``reaction_digest``) take their new names.
* The triggers and policies a start renders are dropped from the renamed table;
  the next start renders them again under the new name, before any request is
  served.

In ``public``, ``community_timers`` takes the sweeps' new names, and
``users.last_task_assignment_digest_at``, which nothing read, is dropped.

Revision ID: 20261030_0562
Revises: 20261030_0561
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261030_0562"
down_revision = "20261030_0561"
branch_labels = None
depends_on = None

#: (old, new) sweep names, in ``public.community_timers`` and each schema's
#: ``timer_marks``.
_SWEEPS = (
    ("digest_gc", "batch_gc"),
    ("task_digest", "task_assignment_batch"),
    ("reaction_digest", "reaction_batch"),
)
#: (old, new) columns of the renamed table.
_COLUMNS = (
    ("reactor_id", "actor_id"),
    ("reactor_name", "actor_name"),
    ("context_title", "title"),
)


def _renamed_sweeps(table: str, forward: bool) -> str:
    pairs = _SWEEPS if forward else tuple((new, old) for old, new in _SWEEPS)
    arms = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in pairs)
    olds = ", ".join(f"'{old}'" for old, _ in pairs)
    return f"UPDATE {table} SET kind = CASE kind {arms} END WHERE kind IN ({olds})"


def _forced(bind: Connection, table: str) -> bool:
    return bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


@contextmanager
def _unforced(bind: Connection, table: str) -> Iterator[None]:
    """Row security lifted from ``table`` for the statements inside, and put
    back as it was: it binds the owner too, and a migration has no standing to
    meet it."""
    forced = _forced(bind, table)
    if forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    yield
    if forced:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_rendered(bind: Connection, table: str) -> None:
    """Drop the triggers and policies a start renders on ``table``; it renders
    them again under the table's new name."""
    for (name,) in bind.execute(
        text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:t) "
            "AND NOT tgisinternal"
        ),
        {"t": table},
    ).all():
        op.execute(f'DROP TRIGGER "{name}" ON {table}')
    for (name,) in bind.execute(
        text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": table},
    ).all():
        op.execute(f'DROP POLICY "{name}" ON {table}')


def _count(bind: Connection, sql: str) -> int:
    return int(bind.execute(text(sql)).scalar_one())


def upgrade() -> None:
    bind = op.get_bind()
    with _unforced(bind, "public.community_timers"):
        op.execute(_renamed_sweeps("public.community_timers", True))
    op.execute("ALTER TABLE public.users DROP COLUMN last_task_assignment_digest_at")
    run_for_each_guild_schema(bind, lambda: _upgrade(op.get_bind()))


def _upgrade(bind: Connection) -> None:
    forced = _forced(bind, "reaction_digest_items")
    for table in ("reaction_digest_items", "task_assignment_digest_items"):
        _drop_rendered(bind, table)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE reaction_digest_items RENAME TO batched_notices")
    op.execute(
        "ALTER SEQUENCE IF EXISTS reaction_digest_items_id_seq "
        "RENAME TO batched_notices_id_seq"
    )
    op.execute(
        "ALTER TABLE batched_notices "
        "RENAME CONSTRAINT reaction_digest_items_pkey TO batched_notices_pkey"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_reaction_digest_items_reaction_id "
        "RENAME TO ix_batched_notices_reaction_id"
    )
    op.execute("DROP INDEX IF EXISTS ix_reaction_digest_items_user_id")
    for old, new in _COLUMNS:
        op.execute(f"ALTER TABLE batched_notices RENAME COLUMN {old} TO {new}")
    op.execute("ALTER TABLE batched_notices ADD COLUMN kind varchar(32)")
    op.execute("UPDATE batched_notices SET kind = 'reaction'")
    op.execute(
        "ALTER TABLE batched_notices "
        "ALTER COLUMN kind SET NOT NULL, "
        "ALTER COLUMN emoji DROP NOT NULL, "
        "ADD COLUMN project_id integer "
        "CONSTRAINT batched_notices_project_id_fkey "
        "REFERENCES projects (id) ON DELETE CASCADE, "
        "ADD COLUMN project_name varchar(255), "
        "ADD CONSTRAINT ck_batched_notices_kind "
        "CHECK (kind IN ('task_assignment', 'reaction'))"
    )

    queued = _count(bind, "SELECT count(*) FROM task_assignment_digest_items")
    op.execute(
        "INSERT INTO batched_notices (user_id, kind, actor_id, actor_name, "
        "target_type, target_id, target_path, title, project_id, project_name, "
        "created_at, processed_at) "
        "SELECT user_id, 'task_assignment', assigned_by_id, assigned_by_name, "
        "'task', task_id, '/go/task/' || task_id, task_title, project_id, "
        "project_name, created_at, processed_at "
        "FROM task_assignment_digest_items"
    )
    moved = _count(
        bind, "SELECT count(*) FROM batched_notices WHERE kind = 'task_assignment'"
    )
    if moved != queued:
        raise RuntimeError(
            f"moved {moved} of {queued} assignment lines into batched_notices"
        )
    op.execute("DROP TABLE task_assignment_digest_items")

    op.execute(
        "CREATE INDEX ix_batched_notices_user_id_kind ON batched_notices (user_id, kind)"
    )
    op.execute(
        "CREATE INDEX idx_batched_notices_unprocessed ON batched_notices "
        "(processed_at) WHERE processed_at IS NULL"
    )
    if forced:
        op.execute("ALTER TABLE batched_notices FORCE ROW LEVEL SECURITY")

    with _unforced(bind, "timer_marks"):
        op.execute(_renamed_sweeps("timer_marks", True))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _downgrade(op.get_bind()))
    op.execute(
        "ALTER TABLE public.users "
        "ADD COLUMN last_task_assignment_digest_at timestamp with time zone"
    )
    with _unforced(bind, "public.community_timers"):
        op.execute(_renamed_sweeps("public.community_timers", False))


def _downgrade(bind: Connection) -> None:
    forced = _forced(bind, "batched_notices")
    _drop_rendered(bind, "batched_notices")
    op.execute("ALTER TABLE batched_notices NO FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE TABLE task_assignment_digest_items ("
        "id serial CONSTRAINT task_assignment_digest_items_pkey PRIMARY KEY, "
        "user_id integer NOT NULL, "
        "task_id integer NOT NULL CONSTRAINT task_assignment_digest_items_task_id_fkey "
        "REFERENCES tasks (id) ON DELETE CASCADE, "
        "project_id integer NOT NULL "
        "CONSTRAINT task_assignment_digest_items_project_id_fkey "
        "REFERENCES projects (id) ON DELETE CASCADE, "
        "task_title varchar(255) NOT NULL, "
        "project_name varchar(255) NOT NULL, "
        "assigned_by_name varchar(255) NOT NULL, "
        "assigned_by_id integer, "
        "created_at timestamp with time zone NOT NULL, "
        "processed_at timestamp with time zone)"
    )
    op.execute(
        "CREATE INDEX ix_task_assignment_digest_items_user_id "
        "ON task_assignment_digest_items (user_id)"
    )
    op.execute(
        "CREATE INDEX idx_task_assignment_digest_items_unprocessed "
        "ON task_assignment_digest_items (processed_at) WHERE processed_at IS NULL"
    )
    # A line whose task has gone has nothing left to name.
    op.execute(
        "INSERT INTO task_assignment_digest_items (user_id, task_id, project_id, "
        "task_title, project_name, assigned_by_name, assigned_by_id, created_at, "
        "processed_at) "
        "SELECT n.user_id, n.target_id, n.project_id, n.title, n.project_name, "
        "n.actor_name, n.actor_id, n.created_at, n.processed_at "
        "FROM batched_notices n JOIN tasks t ON t.id = n.target_id "
        "WHERE n.kind = 'task_assignment'"
    )
    op.execute("DELETE FROM batched_notices WHERE kind = 'task_assignment'")

    op.execute("DROP INDEX ix_batched_notices_user_id_kind")
    op.execute("DROP INDEX idx_batched_notices_unprocessed")
    op.execute(
        "ALTER TABLE batched_notices "
        "DROP CONSTRAINT ck_batched_notices_kind, "
        "DROP COLUMN kind, "
        "DROP COLUMN project_id, "
        "DROP COLUMN project_name, "
        "ALTER COLUMN emoji SET NOT NULL"
    )
    for old, new in _COLUMNS:
        op.execute(f"ALTER TABLE batched_notices RENAME COLUMN {new} TO {old}")
    op.execute(
        "ALTER TABLE batched_notices "
        "RENAME CONSTRAINT batched_notices_pkey TO reaction_digest_items_pkey"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_batched_notices_reaction_id "
        "RENAME TO ix_reaction_digest_items_reaction_id"
    )
    op.execute(
        "ALTER SEQUENCE IF EXISTS batched_notices_id_seq "
        "RENAME TO reaction_digest_items_id_seq"
    )
    op.execute("ALTER TABLE batched_notices RENAME TO reaction_digest_items")
    op.execute(
        "CREATE INDEX ix_reaction_digest_items_user_id "
        "ON reaction_digest_items (user_id)"
    )
    for table in ("reaction_digest_items", "task_assignment_digest_items"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        if forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    with _unforced(bind, "timer_marks"):
        op.execute(_renamed_sweeps("timer_marks", False))
