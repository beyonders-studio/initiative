"""a demo copy keeps its import inside

``public.demo_sandboxes.import_job_id`` named a ``data_jobs`` row in the
copy's own schema, which no key from ``public`` reaches. The copy's import is
its first import, read inside the copy, so the column goes.

Revision ID: 20261031_0572
Revises: 20261031_0571
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20261031_0572"
down_revision = "20261031_0571"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("demo_sandboxes", "import_job_id", schema="public")


def downgrade() -> None:
    op.add_column(
        "demo_sandboxes",
        sa.Column("import_job_id", sa.Integer(), nullable=True),
        schema="public",
    )
