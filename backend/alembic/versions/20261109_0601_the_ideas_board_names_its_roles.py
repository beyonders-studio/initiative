"""the Ideas board names its category, release and shipped status

Three columns on ``intake_bindings``, in ``guild_template`` and the operations
community's schema alone: the field holding an idea's category, the field
holding the release it shipped in, and the status that means it shipped. Each
is cleared when what it names is removed, as the binding's statuses and type
are. Setting the board up from its blueprint fills them; a board set up before
this has none until it is set up again.

Revision ID: 20261109_0601
Revises: 20261109_0600
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0601"
down_revision = "20261109_0600"
branch_labels = None
depends_on = None

#: Each new column, and the table it names.
_COLUMNS = (
    ("category_field_id", "metadata_definitions"),
    ("release_field_id", "metadata_definitions"),
    ("shipped_status_id", "task_statuses"),
)


def _add() -> None:
    for column, target in _COLUMNS:
        op.add_column("intake_bindings", sa.Column(column, sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"intake_bindings_{column}_fkey",
            "intake_bindings",
            target,
            [column],
            ["id"],
            ondelete="SET NULL",
        )


def _drop() -> None:
    for column, _ in reversed(_COLUMNS):
        op.execute(
            "ALTER TABLE intake_bindings"
            f" DROP CONSTRAINT IF EXISTS intake_bindings_{column}_fkey,"
            f" DROP COLUMN IF EXISTS {column}"
        )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add, operations=True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop, operations=True)
