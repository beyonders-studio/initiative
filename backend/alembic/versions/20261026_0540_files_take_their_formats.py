"""Files take their formats

A file's ``file_type`` is its format rather than how it is kept. In
``guild_template`` and every ``guild_<id>``, ``files.file_type`` becomes text:

* the editor's types take their formats' names: ``native`` is ``lexical``,
  ``whiteboard`` is ``excalidraw``, ``spreadsheet`` is ``sheet`` and
  ``smart_link`` is ``url``;
* an uploaded file (``file``) is the format of its current version's media
  type, ``other`` where the format is not one the app names;
* a picture no longer shows itself as its featured image: a featured image
  that is the file's own current version is cleared. The version still shows
  the upload, so nothing is released.

The rewrite runs with row security unforced and user triggers held: nothing
about the rows changed but their spelling. The search index's update trigger
names the column, so it is dropped first; a start renders it again from the
registry, before any request is served.

The downgrade spells the editor's types the old way and every other type
``file``; cleared featured images stay cleared.

Revision ID: 20261026_0540
Revises: 20261026_0539
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261026_0540"
down_revision = "20261026_0539"
branch_labels = None
depends_on = None


_EDITOR_TYPES = (
    ("native", "lexical"),
    ("whiteboard", "excalidraw"),
    ("spreadsheet", "sheet"),
    ("smart_link", "url"),
)
#: The formats an uploaded file could be when this revision was written.
_UPLOADED = (
    ("application/pdf", "pdf"),
    ("application/msword", "doc"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    ("application/vnd.ms-excel", "xls"),
    ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ("application/vnd.ms-powerpoint", "ppt"),
    (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
    ),
    ("text/plain", "txt"),
    ("text/html", "html"),
    ("text/markdown", "md"),
    ("text/x-markdown", "md"),
    ("image/png", "png"),
    ("image/jpeg", "jpeg"),
    ("image/jpg", "jpeg"),
    ("image/gif", "gif"),
    ("image/webp", "webp"),
    ("image/svg+xml", "svg"),
)


def _case(expression: str, pairs: tuple[tuple[str, str], ...], otherwise: str) -> str:
    arms = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in pairs)
    return f"(CASE {expression} {arms} ELSE '{otherwise}' END)"


def _writable(bind: Connection, statements: tuple[str, ...]) -> None:
    """Run ``statements`` against ``files`` with its row security unforced and
    its user triggers held, then restore both."""
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass('files')"
            )
        ).scalar()
    )
    if forced:
        bind.exec_driver_sql("ALTER TABLE files NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql("ALTER TABLE files DISABLE TRIGGER USER")
    for statement in statements:
        bind.exec_driver_sql(statement)
    bind.exec_driver_sql("ALTER TABLE files ENABLE TRIGGER USER")
    if forced:
        bind.exec_driver_sql("ALTER TABLE files FORCE ROW LEVEL SECURITY")


def _drop_dependent_triggers(bind: Connection) -> None:
    """Drop the triggers whose definition names ``files.file_type``."""
    names = bind.execute(
        text(
            "SELECT t.tgname FROM pg_depend d "
            "JOIN pg_trigger t ON t.oid = d.objid "
            "JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid "
            "WHERE d.classid = 'pg_trigger'::regclass "
            "AND d.refobjid = to_regclass('files') AND a.attname = 'file_type'"
        )
    ).scalars()
    for name in list(names):
        bind.exec_driver_sql(f'DROP TRIGGER "{name}" ON files')


def _upgrade_schema(bind: Connection) -> None:
    _drop_dependent_triggers(bind)
    bind.exec_driver_sql("ALTER TABLE files ALTER COLUMN file_type DROP DEFAULT")
    bind.exec_driver_sql(
        "ALTER TABLE files ALTER COLUMN file_type TYPE text USING "
        + _case("file_type::text", _EDITOR_TYPES, "file")
    )
    bind.exec_driver_sql(
        "ALTER TABLE files ALTER COLUMN file_type SET DEFAULT 'lexical'"
    )
    media = "lower(trim(split_part(v.file_content_type, ';', 1)))"
    _writable(
        bind,
        (
            "UPDATE files f SET "
            f"file_type = {_case(media, _UPLOADED, 'other')}, "
            "featured_image_url = NULLIF(f.featured_image_url, v.file_url) "
            "FROM file_versions v "
            "WHERE f.file_type = 'file' AND v.id = f.current_version_id",
            "UPDATE files SET file_type = 'other' WHERE file_type = 'file'",
        ),
    )


def _downgrade_schema(bind: Connection) -> None:
    former = tuple((new, old) for old, new in _EDITOR_TYPES)
    _drop_dependent_triggers(bind)
    bind.exec_driver_sql("ALTER TABLE files ALTER COLUMN file_type DROP DEFAULT")
    bind.exec_driver_sql(
        "ALTER TABLE files ALTER COLUMN file_type TYPE file_type USING "
        + _case("file_type", former, "file")
        + "::file_type"
    )
    bind.exec_driver_sql(
        "ALTER TABLE files ALTER COLUMN file_type SET DEFAULT 'native'"
    )


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _upgrade_schema(bind))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _downgrade_schema(bind))
