"""plug-in pages say admin_only

Before kit 0.21 a plug-in's pages and endpoints said who opens them with
``visibility`` (``member``, ``initiative_manager``, ``guild_admin``); since
then, a page or endpoint for the community's admins alone says
``admin_only: true``, and who else opens it is the community's choice. A
definition stored under the earlier contract kept the old term, so the reader
honoured both. This revision writes each such page and endpoint the current
way, in every published listing version and every community's pinned install:
``visibility`` goes, and ``admin_only`` is true where it said ``guild_admin``
or already said true.

The rewrite runs with user triggers off: nothing about the rows changed but
their spelling, so nothing is captured or delivered for it.

Revision ID: 20261109_0595
Revises: 20261109_0594
Create Date: 2026-11-09
"""

from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20261109_0595"
down_revision = "20261109_0594"
branch_labels = None
depends_on = None

#: The parts of a definition that carried ``visibility``.
_DECLARED = ("pages", "endpoints")


def _with_rows_writable(bind, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with the table's RLS unforced and its user triggers off."""
    forced = bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )
    if forced:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    try:
        fn()
    finally:
        bind.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
        if forced:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _admin_only(bind, table: str) -> None:
    def run() -> None:
        for key in _DECLARED:
            declared = (
                "CASE WHEN jsonb_typeof(definition -> '{key}') = 'array' "
                "THEN definition -> '{key}' ELSE '[]'::jsonb END"
            ).format(key=key)
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET definition = jsonb_set(definition, "  # noqa: S608
                    f"'{{{key}}}', (SELECT jsonb_agg(CASE "
                    "WHEN jsonb_typeof(e) = 'object' AND e ? 'visibility' "
                    "THEN (e - 'visibility') || jsonb_build_object('admin_only', "
                    "coalesce(e ->> 'visibility' = 'guild_admin', false) "
                    "OR coalesce(e -> 'admin_only' = 'true'::jsonb, false)) "
                    "ELSE e END ORDER BY position) "
                    f"FROM jsonb_array_elements({declared}) "
                    "WITH ORDINALITY AS d(e, position))) "
                    f"WHERE EXISTS (SELECT 1 FROM jsonb_array_elements({declared}) "
                    "AS d(e) WHERE jsonb_typeof(e) = 'object' AND e ? 'visibility')"
                )
            )

    _with_rows_writable(bind, table, run)


def upgrade() -> None:
    bind = op.get_bind()
    _admin_only(bind, "public.marketplace_listing_versions")
    for schema in guild_schema_names(bind):
        _admin_only(bind, f'"{schema}".guild_plugins')


def downgrade() -> None:
    """Nothing to undo: every reader before this revision read ``admin_only``
    as well, and which pages once said ``member`` or ``initiative_manager``
    rather than nothing is not kept."""
