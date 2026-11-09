"""every upload names its type

``uploads.content_type`` came after the table, so a file uploaded before it
had no type recorded, and serving such a file guessed from its name. This
revision gives every such row a type and makes the column required, in every
guild schema and ``guild_template``:

* the type a file version read off the same stored file, where one did;
* otherwise the type its extension names, for the pictures and PDFs the app
  shows in place, and ``application/octet-stream`` for anything else, which is
  served as a download.

The backfill runs with the table's user triggers off: the file is the same
file, so nothing is captured for it.

Revision ID: 20261109_0596
Revises: 20261109_0595
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0596"
down_revision = "20261109_0595"
branch_labels = None
depends_on = None

_BACKFILL = r"""
WITH known AS (
    SELECT DISTINCT ON (name) name, file_content_type
    FROM (
        SELECT regexp_replace(file_url, '^.*/', '') AS name, file_content_type, id
        FROM file_versions
        WHERE file_content_type IS NOT NULL
    ) AS versions
    ORDER BY name, id
)
UPDATE uploads AS u
SET content_type = coalesce(
    known.file_content_type,
    CASE lower(substring(u.filename from '\.([^./]+)$'))
        WHEN 'png' THEN 'image/png'
        WHEN 'jpg' THEN 'image/jpeg'
        WHEN 'jpeg' THEN 'image/jpeg'
        WHEN 'gif' THEN 'image/gif'
        WHEN 'webp' THEN 'image/webp'
        WHEN 'tif' THEN 'image/tiff'
        WHEN 'tiff' THEN 'image/tiff'
        WHEN 'ico' THEN 'image/x-icon'
        WHEN 'svg' THEN 'image/svg+xml'
        WHEN 'pdf' THEN 'application/pdf'
        ELSE 'application/octet-stream'
    END
)
FROM uploads AS untyped
LEFT JOIN known ON known.name = untyped.filename
WHERE untyped.id = u.id AND u.content_type IS NULL
"""


def _forced(table: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        )
        .scalar()
    )


def _upgrade() -> None:
    forced = [table for table in ("uploads", "file_versions") if _forced(table)]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE uploads DISABLE TRIGGER USER")
    try:
        op.execute(_BACKFILL)
    finally:
        op.execute("ALTER TABLE uploads ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.alter_column(
        "uploads", "content_type", existing_type=sa.String(255), nullable=False
    )


def _downgrade() -> None:
    op.alter_column(
        "uploads", "content_type", existing_type=sa.String(255), nullable=True
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
