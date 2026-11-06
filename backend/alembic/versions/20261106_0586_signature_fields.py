"""signature fields

A field a member signs. In ``public``, ``public.metadata_type`` gains
``signature``; the label is committed on its own first, since a label cannot be
used in the transaction that adds it. No guild table changes: a signature
keeps its signer, time and typed name in the columns ``metadata_values``
already has.

The downgrade removes every signature definition, and with them their values,
in ``guild_template`` and every ``guild_<id>``, with each table's row security
unforced and its user triggers held, both restored in the same transaction. It
leaves the label: Postgres cannot drop one, and no row holds it after.

Revision ID: 20261106_0586
Revises: 20261106_0585
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261106_0586"
down_revision = "20261106_0585"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE public.metadata_type ADD VALUE IF NOT EXISTS 'signature'")
    op.execute("BEGIN")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    bind = op.get_bind()
    tables = ("metadata_values", "metadata_definitions")
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
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    bind.exec_driver_sql(
        "DELETE FROM metadata_values WHERE property_id IN "
        "(SELECT id FROM metadata_definitions WHERE type::text = 'signature')"
    )
    bind.exec_driver_sql(
        "DELETE FROM metadata_definitions WHERE type::text = 'signature'"
    )
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
