"""the deployment defines custom roles

In ``guild_template`` and every ``guild_<id>``: ``custom_roles.set_by``, who
defined a role, the community (every role so far) or the deployment, which
defines its roles once for every community through billing's sync. Only the
system engine changes or deletes a deployment's role; its CHECK and policies
are rendered at start, as always.

The downgrade drops the column, and a role the deployment set stays as one the
community has.

Revision ID: 20261031_0575
Revises: 20261031_0574
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261031_0575"
down_revision = "20261031_0574"
branch_labels = None
depends_on = None


def _upgrade() -> None:
    op.add_column(
        "custom_roles",
        sa.Column(
            "set_by",
            sa.String(length=16),
            nullable=False,
            server_default="community",
        ),
    )


def _downgrade() -> None:
    op.execute(
        "ALTER TABLE custom_roles DROP CONSTRAINT IF EXISTS ck_custom_roles_set_by"
    )
    op.drop_column("custom_roles", "set_by")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
