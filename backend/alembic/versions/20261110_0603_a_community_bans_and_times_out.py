"""a community bans and times out

``public.member_moderation``: one row per person per community, a ban (kept
out until lifted) or a timeout (reading only until ``ends_at``). Joining reads
it on the system engine; the community's roster holders keep it on a routed
request; the person reads their own row, before routing (on the login and the
platform floor) and in their standing.

Nothing to backfill, so the table is locked down as soon as it exists. Its
policies are rendered from the shared-table registry at boot.

Revision ID: 20261110_0603
Revises: 20261110_0602
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261110_0603"
down_revision = "20261110_0602"
branch_labels = None
depends_on = None

TABLE = "member_moderation"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["public.guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "user_id"),
        sa.CheckConstraint(
            "kind IN ('ban', 'timeout')", name="ck_member_moderation_kind"
        ),
        sa.CheckConstraint(
            "(kind = 'timeout') = (ends_at IS NOT NULL)",
            name="ck_member_moderation_ends",
        ),
        schema="public",
    )
    op.create_index("ix_member_moderation_user_id", TABLE, ["user_id"], schema="public")
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    read_floor = f"{settings.PLATFORM_ROLE_PREFIX}platform_base_ro"
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table to both
        # floors, so they are wound back before anything is given.
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_guild_base, "{base}"',
        f"GRANT SELECT ON TABLE public.{TABLE} TO app_admin",
        f"GRANT SELECT ON TABLE public.{TABLE} TO app_user",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{TABLE}"
        " TO app_guild_base",
        f"GRANT SELECT ON TABLE public.{TABLE} TO app_guild_base_ro",
        f'GRANT SELECT ON TABLE public.{TABLE} TO "{base}"',
        f'GRANT SELECT ON TABLE public.{TABLE} TO "{read_floor}"',
        f"GRANT SELECT ON TABLE public.{TABLE} TO guest_base",
        f"GRANT SELECT ON TABLE public.{TABLE} TO plugin_install_base",
    ):
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": f"public.{TABLE}"},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON public.{TABLE}')
    op.execute(f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(TABLE, schema="public")
