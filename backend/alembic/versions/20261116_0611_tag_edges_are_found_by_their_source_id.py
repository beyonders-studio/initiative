"""tag edges are found by their source id

``ix_relationships_source`` on ``relationships (source_id, source_type,
relationship_type)``, live rows only, in ``guild_template`` and every
``guild_<id>``. A list sorting by tag, or counting what carries none, looks up
each row's own tag edges by its id; until now that read every tag edge in the
community for each row.

Revision ID: 20261116_0611
Revises: 20261115_0610
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261116_0611"
down_revision = "20261115_0610"
branch_labels = None
depends_on = None

INDEX = "ix_relationships_source"
TABLE = "relationships"


def _apply_upgrade() -> None:
    op.create_index(
        INDEX,
        TABLE,
        ["source_id", "source_type", "relationship_type"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def _apply_downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
