"""a case's evidence names its task

``evidence.case_id`` named the ``intake_cases`` row of the case a file was
attached to. It becomes ``case_task_id``, naming the case's task, with a key to
``tasks`` that takes the file with the task, as the case row did. Reaching a
case's evidence then walks to its task, which every community's schema has.

In ``guild_template`` and every ``guild_<id>``: the key to ``intake_cases``
goes, each row's case is replaced by that case's task, and the key to
``tasks`` and the index follow the column's new name. ``evidence`` and
``intake_cases`` are policy-bound for this revision's role, so both are
unforced for the copy and put back as they were. The policies that read the
column are rendered again at the next start, as always.

The downgrade turns each task back into its case.

Revision ID: 20261105_0578
Revises: 20261031_0577
Create Date: 2026-11-05
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261105_0578"
down_revision = "20261031_0577"
branch_labels = None
depends_on = None


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


def _upgrade() -> None:
    op.drop_constraint("evidence_case_id_fkey", "evidence", type_="foreignkey")
    op.alter_column("evidence", "case_id", new_column_name="case_task_id")
    with _unforced("evidence", "intake_cases"):
        op.execute(
            "UPDATE evidence e SET case_task_id = c.task_id"
            " FROM intake_cases c WHERE c.id = e.case_task_id"
        )
    op.create_foreign_key(
        "evidence_case_task_id_fkey",
        "evidence",
        "tasks",
        ["case_task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute("ALTER INDEX ix_evidence_case_id RENAME TO ix_evidence_case_task_id")


def _downgrade() -> None:
    op.drop_constraint("evidence_case_task_id_fkey", "evidence", type_="foreignkey")
    with _unforced("evidence", "intake_cases"):
        op.execute(
            "UPDATE evidence e SET case_task_id = c.id"
            " FROM intake_cases c WHERE c.task_id = e.case_task_id"
        )
    op.alter_column("evidence", "case_task_id", new_column_name="case_id")
    op.create_foreign_key(
        "evidence_case_id_fkey",
        "evidence",
        "intake_cases",
        ["case_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute("ALTER INDEX ix_evidence_case_task_id RENAME TO ix_evidence_case_id")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
