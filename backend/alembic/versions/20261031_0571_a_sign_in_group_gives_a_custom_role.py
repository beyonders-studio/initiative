"""a sign-in group gives a custom role

In ``guild_template`` and every ``guild_<id>``: ``custom_role_claim_rules``,
which custom role a group one of the community's sign-in providers asserts
gives, in order (the first matching rule wins), written by the community's
seat; and ``custom_role_members.oidc_provider_id``, the provider whose claims
gave a role, so a later sign-in changes or takes back only what it gave. Both
are the community's own: the sign-in sync reads the rules while it is routed
into the community. Policies are rendered at start, as always.

Revision ID: 20261031_0571
Revises: 20261031_0570
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261031_0571"
down_revision = "20261031_0570"
branch_labels = None
depends_on = None


def _upgrade() -> None:
    op.add_column(
        "custom_role_members",
        sa.Column("oidc_provider_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "custom_role_claim_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("claim_value", sa.String(length=500), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["custom_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_custom_role_claim_rules_claim",
        "custom_role_claim_rules",
        ["provider_id", sa.text("lower(claim_value)")],
        unique=True,
    )
    op.create_index(
        "ix_custom_role_claim_rules_role_id", "custom_role_claim_rules", ["role_id"]
    )


def _downgrade() -> None:
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": "custom_role_claim_rules"},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON custom_role_claim_rules')
    op.execute("ALTER TABLE custom_role_claim_rules DISABLE ROW LEVEL SECURITY")
    op.drop_table("custom_role_claim_rules")
    op.drop_column("custom_role_members", "oidc_provider_id")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
