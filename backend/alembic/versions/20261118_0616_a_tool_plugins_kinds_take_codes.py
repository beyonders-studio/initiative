"""a tool plug-in's kinds take codes

``plugin_kind_codes``: the code each tool plug-in's kind
(``<key>.<uid in lower case>``) is given on this deployment, from 1024 up,
when a listing version declaring it is registered. ``relationship_kind_code``
is rendered from it beside the built-in kinds at boot. The system engine reads
it and adds to it, and nothing else reaches it. Nothing to backfill, so it is
locked down as soon as it exists.

Revision ID: 20261118_0616
Revises: 20261118_0615
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261118_0616"
down_revision = "20261118_0615"
branch_labels = None
depends_on = None

TABLE = "plugin_kind_codes"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("code", sa.Integer(), nullable=False),
        sa.CheckConstraint("code >= 1024", name="ck_plugin_kind_codes_code"),
        sa.PrimaryKeyConstraint("kind"),
        sa.UniqueConstraint("code"),
        schema="public",
    )
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table to both
        # floors, so they are wound back before anything is given.
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_guild_base, "{base}"',
        f"GRANT SELECT, INSERT ON TABLE public.{TABLE} TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table(TABLE, schema="public")
