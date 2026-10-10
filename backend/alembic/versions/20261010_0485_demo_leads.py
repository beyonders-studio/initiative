"""demo leads

``demo_leads``: an address a visitor left on a demo link, kept for 30 days.
Empty on every deployment not started
with ``DEMO_MODE``.

app_admin-only: RLS enabled and forced with no policies, and the schema's
default grants revoked from the two base roles. The system engine is also
granted the sequence of ``demo_leads``. The table is new and empty, so nothing
is backfilled.

Revision ID: 20261010_0485
Revises: 20261010_0484
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261010_0485"
down_revision = "20261010_0484"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link_id", sa.Integer(), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("email_encrypted", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["demo_links.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("link_id", "email_hash", name="uq_demo_leads_link_email"),
    )
    op.create_index("ix_demo_leads_created_at", "demo_leads", ["created_at"])

    if op.get_bind().dialect.name != "postgresql":
        return

    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        "ALTER TABLE public.demo_leads ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.demo_leads FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.demo_leads FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.demo_leads TO app_admin",
        # The system engine draws the ids of the leads it inserts.
        "REVOKE ALL ON SEQUENCE public.demo_leads_id_seq "
        f'FROM app_guild_base, "{base}", app_user',
        "GRANT USAGE, SELECT ON SEQUENCE public.demo_leads_id_seq TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("demo_leads")
