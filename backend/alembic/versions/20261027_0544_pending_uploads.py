"""pending uploads

``pending_uploads``, in every guild schema: a file arriving in pieces over
tus, until the endpoint it is for takes it. Its policies are rendered from the
registry at boot.

Revision ID: 20261027_0544
Revises: 20261027_0543
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261027_0544"
down_revision = "20261027_0543"
branch_labels = None
depends_on = None


def _apply_upgrade() -> None:
    op.create_table(
        "pending_uploads",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("length", sa.BigInteger(), nullable=False),
        sa.Column("offset", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("staging_key", sa.Text(), nullable=False),
        sa.Column(
            "blob_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("lease_token", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_uploads_expires_at", "pending_uploads", ["expires_at"])


def _apply_downgrade() -> None:
    op.drop_index("ix_pending_uploads_expires_at", table_name="pending_uploads")
    op.drop_table("pending_uploads")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
