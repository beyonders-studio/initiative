"""demo samples

The demo deployment's sample accounts, ``demo_samples``: accounts its sign-in
page lists with their address and password, which anyone may sign in to. One
row per account, with what the page shows.

Empty on every deployment not started with ``DEMO_MODE``.

app_admin-only: RLS enabled and forced with no policies, and the schema's
default grants revoked from the two base roles. The table is new and empty, so
nothing is backfilled.

Revision ID: 20261021_0531
Revises: 20261020_0530
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261021_0531"
down_revision = "20261020_0530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_samples",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password", sa.String(length=128), nullable=False),
        sa.Column("about", sa.String(length=200), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        "ALTER TABLE public.demo_samples ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.demo_samples FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.demo_samples FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.demo_samples TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("demo_samples")
