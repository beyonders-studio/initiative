"""imports and exports are data jobs

``import_jobs`` and ``export_jobs`` become one table, ``data_jobs``, with a
``direction`` column (``import`` or ``export``, held by a CHECK). In
``guild_template`` and every ``guild_<id>``:

* ``import_jobs`` is renamed ``data_jobs``, with its sequence, primary key
  and ``created_by`` trigger, so every import keeps its id: a demo sandbox and
  a notification name an import by it. Its rows take ``direction = 'import'``
  and its ``payload_ref`` becomes ``file_ref``.
* Each ``export_jobs`` row moves across with a new id, past every id either
  table has used, and its ``artifact_ref`` becomes ``file_ref``. An id a
  notification names for an export from before is then an import's or
  nobody's, never another export's. ``template_id`` and ``format`` are no
  longer required, since an import has neither.
* The status index becomes one on ``(direction, status)``, and
  ``export_jobs`` is dropped.

The timer triggers on both old tables are dropped; a start renders the
policies and triggers of ``data_jobs`` from the registries before any request
is served. The rows move with each table's row security unforced and its user
triggers held, both restored in the same transaction.

In ``public``, a community's ``export_expiry`` and ``import_expiry`` timers
become ``data_job_expiry`` timers, the one sweep that now deletes a job's file
at its deadline.

The downgrade moves the export rows back into a new ``export_jobs``, keeping
their ids, renames the rest back to ``import_jobs``, and gives each
``data_job_expiry`` timer back to both old sweeps.

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


_TIMERS = "public.community_timers"
_EXPIRY = "data_job_expiry"
_OLD_EXPIRIES = ("export_expiry", "import_expiry")

_EXPORT_COLUMNS = (
    "created_by",
    "source",
    "template_id",
    "format",
    "params",
    "status",
    "error",
    "expires_at",
    "created_at",
    "updated_at",
    "destination_ref",
    "restarts",
    "initiative_ids",
)

_EXPORT_DDL = """
CREATE TABLE export_jobs (
    id serial PRIMARY KEY,
    created_by integer NOT NULL,
    source varchar NOT NULL,
    template_id varchar NOT NULL,
    format varchar NOT NULL,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar NOT NULL DEFAULT 'queued',
    artifact_ref varchar,
    error varchar,
    expires_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    destination_ref varchar,
    restarts integer NOT NULL DEFAULT 0,
    initiative_ids integer[]
)
"""


def _exists(bind: Connection, table: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar())


def _in_template(bind: Connection) -> bool:
    return bind.execute(text("SELECT current_schema()")).scalar() == "guild_template"


@contextmanager
def _held(bind: Connection, tables: tuple[str, ...]) -> Iterator[None]:
    """Unforce each table's row security and hold its user triggers, restoring
    both on the tables still there afterwards, under whatever name they have
    by then. A failure rolls the whole revision back, so nothing is restored
    on that path."""
    held: list[tuple[int, bool]] = []
    for table in tables:
        row = bind.execute(
            text(
                "SELECT oid, relforcerowsecurity FROM pg_class"
                " WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).first()
        if row is None:
            continue
        if row.relforcerowsecurity:
            bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        held.append((row.oid, row.relforcerowsecurity))
    yield
    for oid, forced in held:
        name = bind.execute(
            text("SELECT relname FROM pg_class WHERE oid = :o"), {"o": oid}
        ).scalar()
        if name is None:
            continue
        bind.exec_driver_sql(f"ALTER TABLE {name} ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")


def _drop_timer_triggers(bind: Connection, table: str) -> None:
    """The registry's timer triggers on ``table``; a start renders them again
    for the tables the registry names."""
    names = bind.execute(
        text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:t)"
            " AND NOT tgisinternal AND tgname LIKE :p"
        ),
        {"t": table, "p": f"tr\\_{table}\\_timer\\_%"},
    ).scalars()
    for name in list(names):
        bind.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{name}" ON {table}')


def _rename(bind: Connection, old: str, new: str) -> None:
    """The table, its sequence, primary key and ``created_by`` trigger."""
    bind.exec_driver_sql(f"ALTER TABLE {old} RENAME TO {new}")
    bind.exec_driver_sql(f"ALTER SEQUENCE {old}_id_seq RENAME TO {new}_id_seq")
    bind.exec_driver_sql(f"ALTER INDEX {old}_pkey RENAME TO {new}_pkey")
    bind.exec_driver_sql(
        f"ALTER TRIGGER tr_{old}_set_created_by ON {new}"
        f" RENAME TO tr_{new}_set_created_by"
    )


def _upgrade_schema() -> None:
    bind = op.get_bind()
    if not _exists(bind, "import_jobs"):
        return
    with _held(bind, ("import_jobs", "export_jobs")):
        for table in ("import_jobs", "export_jobs"):
            _drop_timer_triggers(bind, table)
        _rename(bind, "import_jobs", "data_jobs")
        bind.exec_driver_sql("DROP INDEX IF EXISTS ix_import_jobs_status")
        bind.exec_driver_sql("ALTER TABLE data_jobs ADD COLUMN direction varchar")
        bind.exec_driver_sql("UPDATE data_jobs SET direction = 'import'")
        bind.exec_driver_sql(
            "ALTER TABLE data_jobs ALTER COLUMN direction SET NOT NULL,"
            " ADD CONSTRAINT ck_data_jobs_direction"
            " CHECK (direction IN ('import', 'export'))"
        )
        bind.exec_driver_sql(
            "ALTER TABLE data_jobs RENAME COLUMN payload_ref TO file_ref"
        )
        bind.exec_driver_sql(
            "ALTER TABLE data_jobs"
            " ADD COLUMN template_id varchar,"
            " ADD COLUMN format varchar,"
            " ADD COLUMN destination_ref varchar,"
            " ADD COLUMN restarts integer NOT NULL DEFAULT 0,"
            " ADD COLUMN initiative_ids integer[]"
        )
        # Past every id either table has handed out, deleted rows included.
        bind.exec_driver_sql(
            "SELECT setval('data_jobs_id_seq', GREATEST("
            " (SELECT last_value FROM data_jobs_id_seq),"
            " (SELECT last_value FROM export_jobs_id_seq),"
            " (SELECT COALESCE(max(id), 0) FROM data_jobs),"
            " (SELECT COALESCE(max(id), 0) FROM export_jobs)))"
        )
        columns = ", ".join(_EXPORT_COLUMNS)
        bind.exec_driver_sql(
            f"INSERT INTO data_jobs (direction, file_ref, {columns})"
            f" SELECT 'export', artifact_ref, {columns} FROM export_jobs ORDER BY id"
        )
        bind.exec_driver_sql("DROP TABLE export_jobs")
        bind.exec_driver_sql(
            "CREATE INDEX ix_data_jobs_direction_status"
            " ON data_jobs (direction, status)"
        )


def _downgrade_schema() -> None:
    bind = op.get_bind()
    if not _exists(bind, "data_jobs"):
        return
    with _held(bind, ("data_jobs",)):
        _drop_timer_triggers(bind, "data_jobs")
        bind.exec_driver_sql(_EXPORT_DDL)
        bind.exec_driver_sql(
            "CREATE INDEX ix_export_jobs_status ON export_jobs (status)"
        )
        bind.exec_driver_sql(
            "CREATE TRIGGER tr_export_jobs_set_created_by BEFORE INSERT"
            " ON export_jobs FOR EACH ROW EXECUTE FUNCTION fn_set_created_by()"
        )
        bind.exec_driver_sql("ALTER TABLE export_jobs DISABLE TRIGGER USER")
        columns = ", ".join(_EXPORT_COLUMNS)
        bind.exec_driver_sql(
            f"INSERT INTO export_jobs (id, artifact_ref, {columns})"
            f" SELECT id, file_ref, {columns} FROM data_jobs"
            " WHERE direction = 'export'"
        )
        bind.exec_driver_sql("ALTER TABLE export_jobs ENABLE TRIGGER USER")
        bind.exec_driver_sql(
            "SELECT setval('export_jobs_id_seq',"
            " (SELECT COALESCE(max(id), 0) + 1 FROM export_jobs), false)"
        )
        bind.exec_driver_sql("DELETE FROM data_jobs WHERE direction = 'export'")
        bind.exec_driver_sql("DROP INDEX IF EXISTS ix_data_jobs_direction_status")
        bind.exec_driver_sql(
            "ALTER TABLE data_jobs"
            " DROP CONSTRAINT ck_data_jobs_direction,"
            " DROP COLUMN direction,"
            " DROP COLUMN template_id,"
            " DROP COLUMN format,"
            " DROP COLUMN destination_ref,"
            " DROP COLUMN restarts,"
            " DROP COLUMN initiative_ids"
        )
        bind.exec_driver_sql(
            "ALTER TABLE data_jobs RENAME COLUMN file_ref TO payload_ref"
        )
        _rename(bind, "data_jobs", "import_jobs")
        bind.exec_driver_sql(
            "CREATE INDEX ix_import_jobs_status ON import_jobs (status)"
        )
    if not _in_template(bind):
        # Closed until a start renders its policies.
        bind.exec_driver_sql("ALTER TABLE export_jobs ENABLE ROW LEVEL SECURITY")
        bind.exec_driver_sql("ALTER TABLE export_jobs FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _upgrade_schema)
    with _held(bind, (_TIMERS,)):
        bind.exec_driver_sql(
            f"UPDATE {_TIMERS} SET kind = '{_EXPIRY}'"
            f" WHERE kind IN ({', '.join(repr(k) for k in _OLD_EXPIRIES)})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _downgrade_schema)
    export_expiry, import_expiry = _OLD_EXPIRIES
    with _held(bind, (_TIMERS,)):
        bind.exec_driver_sql(
            f"INSERT INTO {_TIMERS} (community_id, kind, due_at)"
            f" SELECT community_id, '{import_expiry}', due_at FROM {_TIMERS}"
            f" WHERE kind = '{_EXPIRY}'"
        )
        bind.exec_driver_sql(
            f"UPDATE {_TIMERS} SET kind = '{export_expiry}' WHERE kind = '{_EXPIRY}'"
        )
