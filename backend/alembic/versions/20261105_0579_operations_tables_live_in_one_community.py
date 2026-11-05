"""the operations tables live in the operations community alone

``intake_bindings``, ``intake_cases`` and ``case_grants`` hold rows only in the
operations community, the one ``app_settings.operations_guild_id`` names, but
every community's schema had them. ``guild_template`` keeps them, and
provisioning now creates them in the operations community alone
(``app.db.operations_schema``).

Every other ``guild_<id>`` loses the three tables where they hold nothing:
their policies first, then their row security, then the table. One that holds
something was the operations community once; it keeps them until the next
start, which takes them, and its cases' files, if another community is the
operations one, and leaves them where none is. Every schema loses
``tr_tasks_timer_evidence``: the case half of evidence retention is a sweep of
its own, armed in the operations community alone.

The downgrade restores nothing by hand. The previous release's start renders
every community's schema again, and its render has these tables and that
trigger: no schema's stamp matches it, so every part is re-applied.

Revision ID: 20261105_0579
Revises: 20261105_0578
Create Date: 2026-11-05
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20261105_0579"
down_revision = "20261105_0578"
branch_labels = None
depends_on = None

TABLES = ("case_grants", "intake_cases", "intake_bindings")


@contextmanager
def _unforced(*tables: str) -> Iterator[None]:
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
        yield
    finally:
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _operations_schema() -> Optional[str]:
    """The operations community's schema, where the deployment names one."""
    guild_id = (
        op.get_bind()
        .execute(
            sa.text("SELECT operations_guild_id FROM public.app_settings WHERE id = 1")
        )
        .scalar()
    )
    return None if guild_id is None else f"guild_{guild_id}"


def _holds_anything(schema: str) -> bool:
    """Whether ``schema``'s operations tables, or its cases' files, hold a row."""
    tables = [f'"{schema}".{table}' for table in TABLES]
    evidence = f'"{schema}".evidence'
    with _unforced(*tables, evidence):
        return bool(
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT "
                    + " OR ".join(f"EXISTS (SELECT 1 FROM {t})" for t in tables)
                    + f" OR EXISTS (SELECT 1 FROM {evidence}"
                    " WHERE case_task_id IS NOT NULL)"
                )
            )
            .scalar()
        )


def _drop(schema: str) -> None:
    """Drop the operations tables from ``schema``: each one's policies first,
    then its row security, then the table."""
    bind = op.get_bind()
    for table in TABLES:
        qualified = f'"{schema}".{table}'
        for (name,) in bind.execute(
            sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
            {"t": qualified},
        ).all():
            op.execute(f'DROP POLICY IF EXISTS "{name}" ON {qualified}')
        op.execute(f"ALTER TABLE {qualified} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP TABLE {qualified}")


def upgrade() -> None:
    bind = op.get_bind()
    keep = _operations_schema()
    for schema in guild_schema_names(bind):
        op.execute(
            f'DROP TRIGGER IF EXISTS tr_tasks_timer_evidence ON "{schema}".tasks'
        )
        if schema in ("guild_template", keep):
            continue
        has_tables = bind.execute(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"),
            {"t": f'"{schema}".intake_cases'},
        ).scalar()
        if has_tables and not _holds_anything(schema):
            _drop(schema)


def downgrade() -> None:
    pass
