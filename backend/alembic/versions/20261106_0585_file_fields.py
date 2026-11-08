"""file fields

A field holding one file of the item's initiative. In ``public``,
``public.metadata_type`` gains ``file``; the label is committed on its own
first, since a label cannot be used in the transaction that adds it. In
``guild_template`` and every ``guild_<id>``:

* ``metadata_values.value_file_id`` — the file a file field holds, with a
  foreign key to ``files`` that empties it when the file is purged, and a
  partial index the key's deletes look it up by.

The downgrade removes every file definition, and with them their values, with
each table's row security unforced and its user triggers held, both restored
in the same transaction. It leaves the label: Postgres cannot drop one, and no
row holds it after.

Revision ID: 20261106_0585
Revises: 20261106_0584
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261106_0585"
down_revision = "20261106_0584"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE public.metadata_type ADD VALUE IF NOT EXISTS 'file'")
    op.execute("BEGIN")
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "metadata_values",
        sa.Column("value_file_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_metadata_values_value_file_id",
        "metadata_values",
        "files",
        ["value_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_metadata_values_value_file_id",
        "metadata_values",
        ["value_file_id"],
        postgresql_where=sa.text("value_file_id IS NOT NULL"),
    )


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
        "(SELECT id FROM metadata_definitions WHERE type::text = 'file')"
    )
    bind.exec_driver_sql("DELETE FROM metadata_definitions WHERE type::text = 'file'")
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.drop_index("ix_metadata_values_value_file_id", table_name="metadata_values")
    op.drop_constraint(
        "fk_metadata_values_value_file_id", "metadata_values", type_="foreignkey"
    )
    op.drop_column("metadata_values", "value_file_id")
