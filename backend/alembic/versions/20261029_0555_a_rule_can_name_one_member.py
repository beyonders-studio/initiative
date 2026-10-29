"""a rule can name one member

A community's rule may now say something of one member as well as of the
whole community: ``community_rules.user_id``, NULL for the whole community.
The row goes with the membership (a foreign key to ``guild_memberships``), and
a community holds at most one row per rule and member, the whole community
counting as one (``NULLS NOT DISTINCT``). The key that pair would have made
moves to a surrogate ``id``.

The first rule to use it is ``api_keys``: whether a member's personal API keys
reach the community, which the seat sets one member at a time. It moves off
``guild_memberships.api_keys_allowed``, each member whose keys were refused
becoming a row, and the column is dropped.

Both tables are policy-bound for this revision's own role, so each is unforced
for the copy and forced again in the same transaction, and the copy is counted
against its source.

Revision ID: 20261029_0555
Revises: 20261028_0554
Create Date: 2026-10-29
"""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "20261029_0555"
down_revision = "20261028_0554"
branch_labels = None
depends_on = None

TABLES = ("guild_memberships", "community_rules")


@contextmanager
def _unforced():
    """Both tables unforced for this revision's role, forced again after."""
    bind = op.get_bind()
    for table in TABLES:
        bind.exec_driver_sql(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield bind
    finally:
        for table in TABLES:
            bind.exec_driver_sql(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _check(what: str, copied: int, source: int) -> None:
    if copied != source:
        raise RuntimeError(f"{what}: copied {copied} of {source} rows")


def upgrade() -> None:
    op.add_column(
        "community_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        schema="public",
    )
    # The schema's default privileges hand every new sequence to the guild
    # floor; nothing writes this one but the identity itself.
    op.execute(
        "REVOKE ALL ON SEQUENCE public.community_rules_id_seq FROM app_guild_base"
    )
    op.drop_constraint("community_rules_pkey", "community_rules", schema="public")
    op.create_primary_key(
        "community_rules_pkey", "community_rules", ["id"], schema="public"
    )
    op.add_column(
        "community_rules",
        sa.Column("user_id", sa.Integer(), nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "fk_community_rules_member",
        "community_rules",
        "guild_memberships",
        ["guild_id", "user_id"],
        ["guild_id", "user_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_community_rules_subject",
        "community_rules",
        ["guild_id", "key", "user_id"],
        schema="public",
        postgresql_nulls_not_distinct=True,
    )

    with _unforced() as bind:
        source = bind.exec_driver_sql(
            "SELECT count(*) FROM public.guild_memberships WHERE NOT api_keys_allowed"
        ).scalar_one()
        bind.exec_driver_sql(
            "INSERT INTO public.community_rules"
            " (guild_id, key, user_id, enabled, updated_at)"
            " SELECT m.guild_id, 'api_keys', m.user_id, false, now()"
            " FROM public.guild_memberships m WHERE NOT m.api_keys_allowed"
        )
        copied = bind.exec_driver_sql(
            "SELECT count(*) FROM public.community_rules"
            " WHERE key = 'api_keys' AND user_id IS NOT NULL"
        ).scalar_one()
    _check("community_rules.api_keys", copied, source)
    op.drop_column("guild_memberships", "api_keys_allowed", schema="public")


def downgrade() -> None:
    op.add_column(
        "guild_memberships",
        sa.Column(
            "api_keys_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="public",
    )
    with _unforced() as bind:
        source = bind.exec_driver_sql(
            "SELECT count(*) FROM public.community_rules"
            " WHERE key = 'api_keys' AND user_id IS NOT NULL"
        ).scalar_one()
        bind.exec_driver_sql(
            "UPDATE public.guild_memberships m SET api_keys_allowed = r.enabled"
            " FROM public.community_rules r"
            " WHERE r.guild_id = m.guild_id AND r.user_id = m.user_id"
            " AND r.key = 'api_keys'"
        )
        copied = bind.exec_driver_sql(
            "SELECT count(*) FROM public.guild_memberships WHERE NOT api_keys_allowed"
        ).scalar_one()
        bind.exec_driver_sql(
            "DELETE FROM public.community_rules WHERE user_id IS NOT NULL"
        )
    _check("guild_memberships.api_keys_allowed", copied, source)
    op.drop_constraint("uq_community_rules_subject", "community_rules", schema="public")
    op.drop_constraint("fk_community_rules_member", "community_rules", schema="public")
    op.drop_column("community_rules", "user_id", schema="public")
    op.drop_constraint("community_rules_pkey", "community_rules", schema="public")
    op.drop_column("community_rules", "id", schema="public")
    op.create_primary_key(
        "community_rules_pkey", "community_rules", ["guild_id", "key"], schema="public"
    )
