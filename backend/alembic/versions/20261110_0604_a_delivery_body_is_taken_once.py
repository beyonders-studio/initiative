"""a delivery body is taken once

``plugin_hook_deliveries.body_digest``, in every guild schema: the SHA-256 of
a vendor delivery's body, kept beside its delivery id for as long as the id,
and unique for each install, so a delivery whose body the install already
has is not queued again under another id. The rows already there have no
digest and keep their 24 hours as before.

Revision ID: 20261110_0604
Revises: 20261110_0603
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261110_0604"
down_revision = "20261110_0603"
branch_labels = None
depends_on = None

TABLE = "plugin_hook_deliveries"
CONSTRAINT = "uq_plugin_hook_deliveries_body_digest"


def _apply_upgrade() -> None:
    op.add_column(TABLE, sa.Column("body_digest", sa.LargeBinary(), nullable=True))
    op.create_unique_constraint(CONSTRAINT, TABLE, ["install_id", "body_digest"])


def _apply_downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
    op.drop_column(TABLE, "body_digest")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
