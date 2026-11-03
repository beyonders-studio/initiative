"""a webhook subscription's names are the community's

``public.identity_refs`` kept what a member's own webhook subscription calls
the community and each person (``purpose = 'webhook'``) under the
subscription's id in a community's schema, which no key from ``public``
reaches: deleting the subscription left the names to be deleted separately,
and deleting the initiative it watched left them for good. In
``guild_template`` and every ``guild_<id>``, ``webhook_refs`` keeps them under
the subscription, with a key that takes them with it.

Each community's live names are copied as they are from the rows naming one
of its subscriptions that is still there, so every receiver goes on being told
the names it already holds; the rest name nothing. Every ``webhook`` row then
leaves ``identity_refs``, and so does ``sector_id``, the column only that
sector used, with its index and its place in the live-reference index. The
CHECK now holds a sector inside a community to a plug-in's, and keeps the
``webhook`` purpose out. The billing change log's read of a community's
billing reference is restated without the column. ``identity_refs`` holds no
policy for this revision's role and a community's subscriptions are
policy-bound for it, so both are unforced for the copy and put back as they
were. The new table's row security is rendered at the next start, as always.

The downgrade puts the column, its indexes, the CHECK and the column grant
back, and copies each community's names into ``identity_refs`` before the
table goes.

Revision ID: 20261031_0574
Revises: 20261031_0573
Create Date: 2026-10-31
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261031_0574"
down_revision = "20261031_0573"
branch_labels = None
depends_on = None

TABLE = "webhook_refs"
REFS = "public.identity_refs"

#: The community whose schema is first on the search path; NULL in
#: ``guild_template``, whose rows are nobody's.
_GUILD_ID = "substring(current_schema() FROM '^guild_([0-9]+)$')::int"

_CHECK = "identity_refs_plugin_sector"
_CHECK_BEFORE = (
    "(purpose = 'plugin') = (sector_plugin IS NOT NULL)"
    " AND (purpose <> 'plugin' OR sector_id IS NULL)"
)
_CHECK_AFTER = (
    "(purpose = 'plugin') = (sector_plugin IS NOT NULL)"
    " AND (purpose = 'plugin') = (sector_guild_id IS NOT NULL)"
    " AND purpose <> 'webhook'"
)

_LIVE_BEFORE = (
    "(entity_type, entity_id, purpose, sector_guild_id, sector_id, sector_plugin)"
)
_LIVE_AFTER = "(entity_type, entity_id, purpose, sector_guild_id, sector_plugin)"

#: The billing change log's writer, which reads the community's billing
#: reference (20261021_0532).
_WRITER = '"app_billing_log"'

_SECTORS_BEFORE = (
    "sector_guild_id IS NULL AND sector_id IS NULL AND sector_plugin IS NULL"
)
_SECTORS_AFTER = "sector_guild_id IS NULL AND sector_plugin IS NULL"


def _change_row(sectors: str) -> str:
    """``public.billing_change_row`` as 20261021_0532 wrote it, reading the
    billing reference in the sectors ``sectors`` names."""
    return f"""
CREATE OR REPLACE FUNCTION public.billing_change_row(
    p_guild integer, p_kind text, p_data jsonb
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
DECLARE v_ref text;
BEGIN
    IF NOT public.billing_managed() THEN
        RETURN;
    END IF;
    -- The community's billing reference, while it has one: a purge removes
    -- the references after the row, and this is the last chance to read it.
    SELECT ref INTO v_ref FROM public.identity_refs
     WHERE entity_type = 'guild' AND entity_id = p_guild AND purpose = 'billing'
       AND {sectors}
       AND retired_at IS NULL;
    INSERT INTO public.billing_changes (xid, guild_id, kind, community_ref, data)
    VALUES ((pg_current_xact_id()::text)::bigint, p_guild, p_kind, v_ref,
            coalesce(p_data, '{{}}'::jsonb));
    PERFORM pg_notify('billing_changes', '');
END $fn$;
"""


def _live_index(columns: str) -> str:
    return (
        "CREATE UNIQUE INDEX ix_identity_refs_live ON public.identity_refs "
        f"{columns} NULLS NOT DISTINCT WHERE retired_at IS NULL"
    )


@contextmanager
def _unforced(*tables: str) -> Iterator[sa.engine.Connection]:
    """Row security lifted from ``tables`` for the statements inside, and put
    back as it was."""
    bind = op.get_bind()
    forced = [
        table
        for table in tables
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield bind
    finally:
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["webhook_subscriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("subscription_id", "entity_type", "entity_id"),
        sa.UniqueConstraint("ref", name="webhook_refs_unique_ref"),
    )


def _drop() -> None:
    """Drop the table: its rendered policies first, then its row security,
    then the table."""
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": TABLE},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON {TABLE}')
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(TABLE)


def _upgrade_schema() -> None:
    _create()
    with _unforced("webhook_subscriptions") as bind:
        bind.execute(
            sa.text(
                f"INSERT INTO {TABLE}"
                " (subscription_id, entity_type, entity_id, ref, created_at)"
                " SELECT r.sector_id, r.entity_type, r.entity_id, r.ref, r.created_at"
                f" FROM {REFS} r"
                " JOIN webhook_subscriptions s ON s.id = r.sector_id"
                " WHERE r.purpose = 'webhook' AND r.retired_at IS NULL"
                f" AND r.sector_guild_id = {_GUILD_ID}"
            )
        )


def _downgrade_schema() -> None:
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {REFS} (ref, entity_type, entity_id, purpose,"
            " sector_guild_id, sector_id, created_at)"
            f" SELECT ref, entity_type, entity_id, 'webhook', {_GUILD_ID},"
            " subscription_id, created_at"
            f" FROM {TABLE} WHERE {_GUILD_ID} IS NOT NULL"
        )
    )
    _drop()


def upgrade() -> None:
    with _unforced(REFS) as bind:
        run_for_each_guild_schema(bind, _upgrade_schema)
        op.execute(f"DELETE FROM {REFS} WHERE purpose = 'webhook'")
    op.drop_constraint(_CHECK, "identity_refs", schema="public", type_="check")
    op.drop_index("ix_identity_refs_sector", "identity_refs", schema="public")
    op.execute("DROP INDEX public.ix_identity_refs_live")
    # Its column grant goes with it.
    op.drop_column("identity_refs", "sector_id", schema="public")
    op.execute(_live_index(_LIVE_AFTER))
    op.create_check_constraint(_CHECK, "identity_refs", _CHECK_AFTER, schema="public")
    op.execute(_change_row(_SECTORS_AFTER))


def downgrade() -> None:
    op.add_column(
        "identity_refs",
        sa.Column("sector_id", sa.Integer(), nullable=True),
        schema="public",
    )
    op.execute(f"GRANT SELECT (sector_id) ON TABLE {REFS} TO {_WRITER}")
    op.execute(_change_row(_SECTORS_BEFORE))
    op.drop_constraint(_CHECK, "identity_refs", schema="public", type_="check")
    op.create_check_constraint(_CHECK, "identity_refs", _CHECK_BEFORE, schema="public")
    op.execute("DROP INDEX public.ix_identity_refs_live")
    op.execute(_live_index(_LIVE_BEFORE))
    op.create_index(
        "ix_identity_refs_sector",
        "identity_refs",
        ["sector_guild_id", "sector_id"],
        schema="public",
    )
    with _unforced(REFS) as bind:
        run_for_each_guild_schema(bind, _downgrade_schema)
