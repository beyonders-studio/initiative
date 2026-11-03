"""a community defines custom roles

In ``guild_template`` and every ``guild_<id>``: ``custom_roles``, a named set
of admin surfaces on the rung it applies to, and ``custom_role_members``, who
holds which, one role each, from when it was given. Both are the community's
own: the request's standing reads them in its schema, and nothing outside it
does. Their policies, and the trigger that keeps a role on its rung, are
rendered at start, as always.

The surface key ``surface.custom_roles`` joins the community rules, open until
the deployment closes it for one community; only the deployment writes one,
so ``rule_key_writers`` gains a ``deployment`` row for it.

Revision ID: 20261031_0570
Revises: 20261031_0569
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from collections.abc import Iterator
from contextlib import contextmanager

from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261031_0570"
down_revision = "20261031_0569"
branch_labels = None
depends_on = None

#: The admin surfaces as they stand at this revision, and those a role on the
#: member rung may hold.
SURFACES = (
    "profile",
    "invites",
    "members",
    "initiatives",
    "community_calendars",
    "webhooks",
    "trash",
    "usage",
    "roles",
)
MEMBER_SURFACES = ("community_calendars", "invites", "members", "profile", "usage")


def _array(values) -> str:
    return "ARRAY[" + ", ".join(f"'{value}'" for value in values) + "]::text[]"


def _upgrade() -> None:
    op.create_table(
        "custom_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("base_rung", sa.String(length=16), nullable=False),
        sa.Column(
            "surfaces",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "base_rung IN ('member', 'admin')", name="ck_custom_roles_base_rung"
        ),
        sa.CheckConstraint(
            f"surfaces <@ {_array(SURFACES)} AND (base_rung <> 'member'"
            f" OR surfaces <@ {_array(MEMBER_SURFACES)})",
            name="ck_custom_roles_surfaces",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "custom_role_members",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["role_id"], ["custom_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_custom_role_members_role_id", "custom_role_members", ["role_id"]
    )


def _drop(table: str) -> None:
    """Drop ``table``: its rendered policies first, then its row security,
    then the table."""
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": table},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON {table}')
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table(table)


def _downgrade() -> None:
    _drop("custom_role_members")
    _drop("custom_roles")


SURFACE = "surface.custom_roles"


@contextmanager
def _unforced(table: str) -> Iterator[sa.engine.Connection]:
    """``table`` unforced for this revision's role, forced again after."""
    bind = op.get_bind()
    bind.exec_driver_sql(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield bind
    finally:
        bind.exec_driver_sql(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)
    with _unforced("rule_key_writers") as bind:
        bind.exec_driver_sql(
            "INSERT INTO public.rule_key_writers (key, set_by)"
            f" VALUES ('{SURFACE}', 'deployment')"
        )


def downgrade() -> None:
    with _unforced("community_rules") as bind:
        bind.exec_driver_sql(
            f"DELETE FROM public.community_rules WHERE key = '{SURFACE}'"
        )
    with _unforced("rule_key_writers") as bind:
        bind.exec_driver_sql(
            f"DELETE FROM public.rule_key_writers WHERE key = '{SURFACE}'"
        )
    run_for_each_guild_schema(op.get_bind(), _downgrade)
    op.execute("DROP FUNCTION IF EXISTS public.fn_custom_role_rung_fixed()")
