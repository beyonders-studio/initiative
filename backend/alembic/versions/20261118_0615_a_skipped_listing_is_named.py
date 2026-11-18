"""a skipped listing is named

``marketplace_registry_status.last_skipped``: what the last registry refresh
skipped, as a list of ``{"name", "code"}`` with the listing's or the
publisher's display name when known. The status panel names each one and says why,
rather than reading the first skip's code alone from ``last_error``. NULL
until the next refresh records it.

A database that ran this as ``20261118_0613`` already has the column, so both
directions are conditional.

Revision ID: 20261118_0615
Revises: 20261118_0614
Create Date: 2026-11-18
"""

from alembic import op

revision = "20261118_0615"
down_revision = "20261118_0614"
branch_labels = None
depends_on = None

TABLE = "marketplace_registry_status"
COLUMN = "last_skipped"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {COLUMN} JSONB")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {COLUMN}")
