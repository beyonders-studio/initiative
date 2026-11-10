"""a community can ask its joiners to ask

``guilds.join_policy`` replaces ``guilds.is_community``: ``private`` where it
was false, ``open`` where it was true, and a third value, ``request``, for a
listed community whose admins approve each joiner. The two listing checks and
the directory's partial index are restated over it, and the community's admins
keep their column grant on it.

``public.community_join_requests`` holds the asks nobody has answered yet. It
is new and empty, so it is locked down as it is made. Its policies are rendered
at boot from ``SHARED_TABLE_REGISTRY``; this revision grants what the registry
records.

Revision ID: 20261110_0602
Revises: 20261109_0601
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261110_0602"
down_revision = "20261109_0601"
branch_labels = None
depends_on = None

_LISTED = "join_policy <> 'private'"


def _drop_listing() -> None:
    for statement in (
        "DROP INDEX IF EXISTS public.ix_guilds_community_categories",
        "ALTER TABLE public.guilds"
        " DROP CONSTRAINT IF EXISTS ck_guilds_community_adult_content,"
        " DROP CONSTRAINT IF EXISTS ck_guilds_community_categories",
    ):
        op.execute(statement)


def _restate_listing(listed: str) -> None:
    op.execute(
        "ALTER TABLE public.guilds"
        " ADD CONSTRAINT ck_guilds_community_adult_content"
        f" CHECK ((NOT ({listed})) OR (has_adult_content IS FALSE)),"
        " ADD CONSTRAINT ck_guilds_community_categories"
        f" CHECK ((NOT ({listed})) OR (cardinality(categories) > 0))"
    )
    op.execute(
        "CREATE INDEX ix_guilds_community_categories ON public.guilds"
        f" USING gin (categories) WHERE {listed}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    _drop_listing()
    op.add_column(
        "guilds",
        sa.Column(
            "join_policy",
            sa.String(length=16),
            nullable=False,
            server_default="private",
        ),
        schema="public",
    )
    bind.exec_driver_sql("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        bind.exec_driver_sql(
            "UPDATE public.guilds SET join_policy = 'open' WHERE is_community"
        )
    finally:
        bind.exec_driver_sql("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        "ck_guilds_join_policy",
        "guilds",
        "join_policy IN ('private', 'request', 'open')",
        schema="public",
    )
    op.drop_column("guilds", "is_community", schema="public")
    _restate_listing(_LISTED)
    op.execute("GRANT UPDATE (join_policy) ON TABLE public.guilds TO app_guild_base")

    op.create_table(
        "community_join_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["public.guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index(
        "uq_community_join_requests_guild_user",
        "community_join_requests",
        ["guild_id", "user_id"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ix_community_join_requests_user_id",
        "community_join_requests",
        ["user_id"],
        schema="public",
    )
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        "ALTER TABLE public.community_join_requests ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.community_join_requests FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table to both
        # floors, so they are wound back before anything is given.
        f'REVOKE ALL ON TABLE public.community_join_requests FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, DELETE ON TABLE public.community_join_requests"
        " TO app_admin",
        "GRANT SELECT, DELETE ON TABLE public.community_join_requests"
        " TO app_guild_base",
        "GRANT SELECT ON TABLE public.community_join_requests TO app_guild_base_ro",
        "GRANT USAGE, SELECT ON SEQUENCE public.community_join_requests_id_seq"
        " TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text(
            "SELECT polname FROM pg_policy"
            " WHERE polrelid = 'public.community_join_requests'::regclass"
        )
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON public.community_join_requests')
    op.drop_table("community_join_requests", schema="public")

    _drop_listing()
    op.add_column(
        "guilds",
        sa.Column("is_community", sa.Boolean(), nullable=False, server_default="false"),
        schema="public",
    )
    bind.exec_driver_sql("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        bind.exec_driver_sql(
            "UPDATE public.guilds SET is_community = (join_policy <> 'private')"
        )
    finally:
        bind.exec_driver_sql("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")
    op.drop_constraint("ck_guilds_join_policy", "guilds", schema="public")
    op.drop_column("guilds", "join_policy", schema="public")
    _restate_listing("is_community")
    op.execute("GRANT UPDATE (is_community) ON TABLE public.guilds TO app_guild_base")
