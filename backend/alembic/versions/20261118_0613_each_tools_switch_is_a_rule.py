"""each tool's switch is a rule

In ``guild_template`` and every ``guild_<id>``, an initiative's switch for each
tool moves from its ``<plural>_enabled`` column on ``initiatives`` to an
``initiative_rules`` row: the initiative, no role, no install, the column's
name as its key, the column's value as ``enabled``. Every initiative gets a row
per tool, on or off, so each keeps the value it had; the community's own
switches (its rows with no initiative) are untouched. The rule CHECK, as the
last start rendered it, already admits the row.

The rows are written and counted against the initiatives before the eight
columns go. Both tables are policy-bound for this revision's role, so each is
unforced for the copy and put back as it was, with their user triggers off:
the rows restate what the initiative already said.

Down again, each column comes back with the default it had and takes its
row's value (no row is off), and the rows go.

Revision ID: 20261118_0613
Revises: 20261117_0612
Create Date: 2026-11-18
"""

from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261118_0613"
down_revision = "20261117_0612"
branch_labels = None
depends_on = None

#: Each tool's switch column at this revision, and its default.
COLUMNS: dict[str, bool] = {
    "projects_enabled": True,
    "files_enabled": True,
    "counter_groups_enabled": False,
    "calendars_enabled": False,
    "dashboards_enabled": False,
    "posts_enabled": False,
    "wikis_enabled": False,
    "contacts_enabled": False,
}
_KEYS = ", ".join(f"'{key}'" for key in COLUMNS)
#: An initiative's own switch row: no role and no install.
_SWITCH_ROW = (
    "initiative_id IS NOT NULL AND initiative_role_id IS NULL"
    f" AND install_id IS NULL AND key IN ({_KEYS})"
)


def _unforced(tables: tuple[str, ...], fn: Callable[[], None]) -> None:
    """Run ``fn`` with each table's FORCE row security, where it has it,
    lifted and its user triggers off, and put both back after."""
    bind = op.get_bind()
    forced = [
        table
        for table in tables
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        fn()
    finally:
        for table in tables:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _write_rows() -> None:
    columns = " UNION ALL ".join(
        f"SELECT id, '{column}', {column} FROM initiatives" for column in COLUMNS
    )
    op.execute(
        "INSERT INTO initiative_rules (initiative_id, key, enabled) "
        f"SELECT * FROM ({columns}) AS s "
        "ON CONFLICT ON CONSTRAINT uq_initiative_rules_subject "
        "DO UPDATE SET enabled = EXCLUDED.enabled"
    )
    expected = _count("SELECT count(*) FROM initiatives") * len(COLUMNS)
    written = _count(f"SELECT count(*) FROM initiative_rules WHERE {_SWITCH_ROW}")
    if written != expected:
        raise RuntimeError(f"tool switches: wrote {written} of {expected} rows")


def _upgrade() -> None:
    _unforced(("initiatives", "initiative_rules"), _write_rows)
    for column in COLUMNS:
        op.drop_column("initiatives", column)


def _read_rows() -> None:
    for column in COLUMNS:
        op.execute(
            f"UPDATE initiatives i SET {column} = EXISTS ("
            "SELECT 1 FROM initiative_rules r WHERE r.initiative_id = i.id"
            " AND r.initiative_role_id IS NULL AND r.install_id IS NULL"
            f" AND r.key = '{column}' AND r.enabled)"
        )
    op.execute(f"DELETE FROM initiative_rules WHERE {_SWITCH_ROW}")


def _downgrade() -> None:
    for column, default in COLUMNS.items():
        op.add_column(
            "initiatives",
            sa.Column(
                column,
                sa.Boolean(),
                server_default=sa.text(str(default).lower()),
                nullable=False,
            ),
        )
    _unforced(("initiatives", "initiative_rules"), _read_rows)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
