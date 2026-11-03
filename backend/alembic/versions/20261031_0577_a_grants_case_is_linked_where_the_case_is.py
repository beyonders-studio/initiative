"""a grant's case is linked where the case is

``public.access_grants.case_task_id`` named the operations case a grant
serves: a task in the operations community's schema, which no key from
``public`` reaches, so nothing removed the reference when the task went. In
``guild_template`` and every ``guild_<id>``, ``case_grants`` keeps the link
under the task, with a key that takes it with it, and names the grant by id.
Only the operations community's table holds rows.

The operations community is the one ``app_settings.operations_guild_id``
names. Each grant's case is copied into that community's table where the task
is still there, in the trash or not; the rest name nothing. The column then
goes. ``access_grants`` holds no policy for this revision's role and the
community's tasks are policy-bound for it, so both are unforced for the copy
and put back as they were. The new table's row security is rendered at the
next start, as always.

The downgrade puts the column back and copies the operations community's
links into it before the table goes.

Revision ID: 20261031_0577
Revises: 20261031_0576
Create Date: 2026-10-31
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20261031_0577"
down_revision = "20261031_0576"
branch_labels = None
depends_on = None

TABLE = "case_grants"
GRANTS = "public.access_grants"


@contextmanager
def _unforced(*tables: str) -> Iterator[sa.engine.Connection]:
    """Row security lifted from ``tables`` for the statements inside, and put
    back as it was."""
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
    try:
        yield bind
    finally:
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _operations_schema() -> Optional[str]:
    """The operations community's schema, where the deployment names one and
    it is there."""
    bind = op.get_bind()
    guild_id = bind.execute(
        sa.text("SELECT operations_guild_id FROM public.app_settings WHERE id = 1")
    ).scalar()
    if guild_id is None:
        return None
    schema = f"guild_{guild_id}"
    return schema if schema in guild_schema_names(bind) else None


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("grant_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("grant_id"),
    )
    op.create_index("ix_case_grants_task_id", TABLE, ["task_id"], unique=False)


def _drop() -> None:
    """Drop the table: its rendered policies first, then its row security,
    then the table."""
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": TABLE},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON {TABLE}')
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(TABLE)


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _create)
    schema = _operations_schema()
    if schema is not None:
        with _unforced(GRANTS, f'"{schema}".tasks'):
            op.execute(
                f'INSERT INTO "{schema}".{TABLE} (grant_id, task_id)'
                " SELECT g.id, g.case_task_id"
                f" FROM {GRANTS} g"
                f' JOIN "{schema}".tasks t ON t.id = g.case_task_id'
            )
    op.drop_column("access_grants", "case_task_id", schema="public")


def downgrade() -> None:
    op.add_column(
        "access_grants",
        sa.Column("case_task_id", sa.Integer(), nullable=True),
        schema="public",
    )
    schema = _operations_schema()
    if schema is not None:
        with _unforced(GRANTS, f'"{schema}".{TABLE}'):
            op.execute(
                f"UPDATE {GRANTS} g SET case_task_id = c.task_id"
                f' FROM "{schema}".{TABLE} c WHERE c.grant_id = g.id'
            )
    run_for_each_guild_schema(op.get_bind(), _drop)
