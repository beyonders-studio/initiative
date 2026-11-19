"""a layout names a tool plug-in's kind

In ``guild_template`` and every ``guild_<id>``, ``tool_layouts.tool`` widens
from 32 characters to 64, so a row can name a tool plug-in's kind (its key of
up to 40 characters, ``.`` and the plug-in's 14-character uid): the starting
layouts each of its tables declares, written when it is installed. The
policies and triggers that read the column go first, as a column a policy
reads changes no type; a start renders the ones the build has again. Down
again, a row naming a kind wider than 32 goes first.

Revision ID: 20261118_0618
Revises: 20261118_0617
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261118_0618"
down_revision = "20261118_0617"
branch_labels = None
depends_on = None


#: The policies and triggers that read one column of a table.
_READERS = """
    SELECT 'POLICY', p.polname, p.polrelid::regclass::text
    FROM pg_depend d JOIN pg_policy p ON p.oid = d.objid
    JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_policy'::regclass AND d.refobjid = to_regclass(:t)
      AND a.attname = :c
    UNION
    SELECT 'TRIGGER', g.tgname, g.tgrelid::regclass::text
    FROM pg_depend d JOIN pg_trigger g ON g.oid = d.objid
    JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_trigger'::regclass AND NOT g.tgisinternal
      AND d.refobjid = to_regclass(:t) AND a.attname = :c
"""


def _drop_readers() -> None:
    """Drop the policies and triggers that read ``tool_layouts.tool``."""
    bind = op.get_bind()
    for what, name, on in bind.execute(
        sa.text(_READERS), {"t": "tool_layouts", "c": "tool"}
    ).all():
        bind.exec_driver_sql(f'DROP {what} IF EXISTS "{name}" ON {on}')


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    _drop_readers()
    op.alter_column(
        "tool_layouts",
        "tool",
        type_=sa.String(length=64),
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    # Policy-bound for this revision's role where the table is forced, so
    # unforced for the delete and put back as it was.
    forced = op.get_bind().scalar(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = to_regclass('tool_layouts')"
        )
    )
    if forced:
        op.execute("ALTER TABLE tool_layouts NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM tool_layouts WHERE length(tool) > 32")
    finally:
        if forced:
            op.execute("ALTER TABLE tool_layouts FORCE ROW LEVEL SECURITY")
    _drop_readers()
    op.alter_column(
        "tool_layouts",
        "tool",
        type_=sa.String(length=32),
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
