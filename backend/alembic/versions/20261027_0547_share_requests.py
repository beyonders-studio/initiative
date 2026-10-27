"""Share requests

A member who can't open something in their initiative may know it is there,
and ask for it (``app.db.presence``):

* ``app_presence_reader`` — a NOLOGIN role that owns each community schema's
  ``entity_presence`` view. Provisioning makes the view and the policies the
  role reads it through; this only creates the role, and lets the migrating
  role hand the view to it.
* ``share_requests`` — in ``guild_template`` and every ``guild_<id>``: one
  person asking for read or write on one shared resource, and the answer.

Revision ID: 20261027_0547
Revises: 20261027_0546
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261027_0547"
down_revision = "20261027_0546"
branch_labels = None
depends_on = None

READER = "app_presence_reader"

#: The tables provisioning puts ``presence_read`` on, as it stood here.
ARM_TABLES = (
    "calendar_events",
    "calendars",
    "counter_groups",
    "counters",
    "dashboards",
    "files",
    "posts",
    "projects",
    "queue_items",
    "queues",
    "tasks",
    "wiki_pages",
    "wikis",
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE "{READER}" NOLOGIN;
            END IF;
        END $$;
        """
    )
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "share_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("granted_level", sa.String(length=16), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "level IN ('read', 'write')", name="ck_share_requests_level"
        ),
        sa.CheckConstraint(
            "granted_level IS NULL OR granted_level IN ('read', 'write')",
            name="ck_share_requests_granted_level",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined')",
            name="ck_share_requests_status",
        ),
        sa.CheckConstraint(
            "scope IS NULL OR scope IN ('user', 'initiative')",
            name="ck_share_requests_scope",
        ),
        sa.CheckConstraint(
            "(status = 'approved') = (granted_level IS NOT NULL AND scope IS NOT NULL)",
            name="ck_share_requests_answer",
        ),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_share_requests_initiative_id", "share_requests", ["initiative_id"]
    )
    op.create_index("ix_share_requests_user_id", "share_requests", ["user_id"])
    op.create_index("ix_share_requests_batch_id", "share_requests", ["batch_id"])
    op.create_index(
        "ix_share_requests_resource",
        "share_requests",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "uq_share_requests_pending",
        "share_requests",
        ["resource_type", "resource_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    op.execute(
        f"""
        DO $$
        BEGIN
            DROP ROLE IF EXISTS "{READER}";
        EXCEPTION WHEN dependent_objects_still_exist THEN
            NULL;
        END
        $$
        """
    )


def _apply_downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS entity_presence")
    op.execute(
        "DO $$ BEGIN EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM "
        f"{READER}; REVOKE ALL ON SCHEMA %I FROM {READER}', current_schema(), "
        "current_schema()); END $$"
    )
    for table in ARM_TABLES:
        op.execute(f"DROP POLICY IF EXISTS presence_read ON {table}")
    op.drop_table("share_requests")
