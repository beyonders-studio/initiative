"""a person's views of a community's lists are the community's

``public.user_view_preferences`` kept each person's view of a community's lists
under ``view:<community id>:…`` keys: a project's, an initiative tool's, a
queue's, a counter group's, a collection's, the roster's and the calendars'.
Those name rows in the community's own schema (projects, initiatives,
collections, and the tags and people a filter holds), which no key from
``public`` reaches. In ``guild_template`` and every ``guild_<id>``,
``view_preferences`` keeps them under ``(user_id, scope_key)``, the key without
the community id (``view:5:project:12`` is ``view:project:12`` in
``guild_5``).

Each community's rows are copied from ``public`` with their key rewritten, and
every ``view:<community id>:…`` row then leaves ``public``, those of a
community that no longer exists included. The account's own views (``view:me:…``,
the home page, older keys that name no community) stay where they are.
``user_view_preferences`` holds its rows for the request path's roles only, so
it is unforced for the copy and put back as it was. The new table's row
security is rendered at the next start, as always.

The downgrade copies each community's rows back under their
``view:<community id>:…`` key before the table goes.

Revision ID: 20261031_0576
Revises: 20261031_0575
Create Date: 2026-10-31
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261031_0576"
down_revision = "20261031_0575"
branch_labels = None
depends_on = None

TABLE = "view_preferences"
PREFERENCES = "public.user_view_preferences"

#: The community whose schema is first on the search path; NULL in
#: ``guild_template``, whose rows are nobody's.
_GUILD_ID = "substring(current_schema() FROM '^guild_([0-9]+)$')::int"
#: What a key of this community's starts with in ``public``.
_PUBLIC_PREFIX = f"'view:' || {_GUILD_ID} || ':'"


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
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "scope_key"),
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
    op.execute(
        f"INSERT INTO {TABLE} (user_id, scope_key, value, updated_at)"
        f" SELECT user_id, 'view:' || substr(scope_key, length({_PUBLIC_PREFIX}) + 1),"
        " value::jsonb, updated_at"
        f" FROM {PREFERENCES}"
        f" WHERE starts_with(scope_key, {_PUBLIC_PREFIX})"
    )


def _downgrade_schema() -> None:
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"INSERT INTO {PREFERENCES} (user_id, scope_key, value, updated_at)"
        f" SELECT user_id, {_PUBLIC_PREFIX} || substr(scope_key, length('view:') + 1),"
        " value::json, updated_at"
        f" FROM {TABLE}"
        f" WHERE {_GUILD_ID} IS NOT NULL AND starts_with(scope_key, 'view:')"
        f" AND length({_PUBLIC_PREFIX} || substr(scope_key, length('view:') + 1))"
        " <= 128"
        " ON CONFLICT (user_id, scope_key) DO UPDATE"
        " SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
        " WHERE user_view_preferences.updated_at < EXCLUDED.updated_at"
    )
    _drop()


def upgrade() -> None:
    with _unforced(PREFERENCES) as bind:
        run_for_each_guild_schema(bind, _upgrade_schema)
        op.execute(f"DELETE FROM {PREFERENCES} WHERE scope_key ~ '^view:[0-9]+:'")


def downgrade() -> None:
    with _unforced(PREFERENCES) as bind:
        run_for_each_guild_schema(bind, _downgrade_schema)
