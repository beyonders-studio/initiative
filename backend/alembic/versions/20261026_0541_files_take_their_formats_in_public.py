"""Files take their formats in public

The shared half of 20261026_0540: no column uses ``public.file_type`` once
every guild schema stores the format as text, so the type is dropped. The
downgrade creates it again before 20261026_0540's downgrade needs it.

Revision ID: 20261026_0541
Revises: 20261026_0540
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "20261026_0541"
down_revision = "20261026_0540"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TYPE IF EXISTS public.file_type")


def downgrade() -> None:
    op.execute(
        "CREATE TYPE public.file_type AS ENUM "
        "('native', 'file', 'whiteboard', 'smart_link', 'spreadsheet')"
    )
