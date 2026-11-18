"""a skipped listing is named

``marketplace_registry_status.last_skipped``: what the last registry refresh
skipped, as a list of ``{"name", "code"}`` with the listing's or the
publisher's display name when known. The status panel names each one and says why,
rather than reading the first skip's code alone from ``last_error``. NULL
until the next refresh records it.

Revision ID: 20261118_0613
Revises: 20261117_0612
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261118_0613"
down_revision = "20261117_0612"
branch_labels = None
depends_on = None

TABLE = "marketplace_registry_status"
COLUMN = "last_skipped"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
