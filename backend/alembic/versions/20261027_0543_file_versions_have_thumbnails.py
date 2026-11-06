"""File versions have thumbnails

In ``guild_template`` and every ``guild_<id>``, ``file_versions`` gains
``thumbnail_url`` and ``thumbnail_state``, and a partial index over the
versions waiting for one. A version of a picture the app makes thumbnails of
is ``pending``, so the ``thumbnails`` sweep makes one for every picture
uploaded before this revision too.

The rewrite runs with row security unforced and user triggers held: nothing a
reader sees changed.

The downgrade drops the columns and the index, and first the triggers a start
rendered from them (the sweep's). A thumbnail already stored stays in
``uploads`` until nothing shows it.

Revision ID: 20261027_0543
Revises: 20261026_0541
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261027_0543"
down_revision = "20261026_0541"
branch_labels = None
depends_on = None


_INDEX = "ix_file_versions_thumbnail_pending"
#: The media types a thumbnail was made of when this revision was written.
_PICTURES = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/tiff",
)


def _writable(bind: Connection, statement: str) -> None:
    """Run ``statement`` against ``file_versions`` with its row security
    unforced and its user triggers held, both restored either way."""
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid = to_regclass('file_versions')"
            )
        ).scalar()
    )
    if forced:
        bind.exec_driver_sql("ALTER TABLE file_versions NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql("ALTER TABLE file_versions DISABLE TRIGGER USER")
    try:
        bind.exec_driver_sql(statement)
    finally:
        bind.exec_driver_sql("ALTER TABLE file_versions ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql("ALTER TABLE file_versions FORCE ROW LEVEL SECURITY")


def _upgrade_schema(bind: Connection) -> None:
    bind.exec_driver_sql(
        "ALTER TABLE file_versions ADD COLUMN thumbnail_url VARCHAR(512)"
    )
    bind.exec_driver_sql("ALTER TABLE file_versions ADD COLUMN thumbnail_state TEXT")
    bind.exec_driver_sql(
        f"CREATE INDEX {_INDEX} ON file_versions (id) WHERE thumbnail_state = 'pending'"
    )
    pictures = ", ".join(f"'{media}'" for media in _PICTURES)
    _writable(
        bind,
        "UPDATE file_versions SET thumbnail_state = 'pending' "
        f"WHERE lower(trim(split_part(file_content_type, ';', 1))) IN ({pictures})",
    )


def _drop_dependent_triggers(bind: Connection) -> None:
    """Drop the triggers whose definition names a thumbnail column."""
    names = bind.execute(
        text(
            "SELECT DISTINCT t.tgname FROM pg_depend d "
            "JOIN pg_trigger t ON t.oid = d.objid "
            "JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid "
            "WHERE d.classid = 'pg_trigger'::regclass "
            "AND d.refobjid = to_regclass('file_versions') "
            "AND a.attname IN ('thumbnail_url', 'thumbnail_state')"
        )
    ).scalars()
    for name in list(names):
        bind.exec_driver_sql(f'DROP TRIGGER "{name}" ON file_versions')


def _downgrade_schema(bind: Connection) -> None:
    _drop_dependent_triggers(bind)
    bind.exec_driver_sql(f"DROP INDEX IF EXISTS {_INDEX}")
    bind.exec_driver_sql("ALTER TABLE file_versions DROP COLUMN thumbnail_state")
    bind.exec_driver_sql("ALTER TABLE file_versions DROP COLUMN thumbnail_url")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _upgrade_schema(bind))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _downgrade_schema(bind))
