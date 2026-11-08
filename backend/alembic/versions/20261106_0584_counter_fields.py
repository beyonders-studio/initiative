"""counter fields

A field people step up and down. In ``public``, ``public.metadata_type``
gains ``counter``; the label is committed on its own first, since a label
cannot be used in the transaction that adds it. In ``guild_template`` and
every ``guild_<id>``:

* ``metadata_definitions.counter`` — a counter's step, bounds and the value a
  reset goes back to, as ``{step, min, max, initial}``, set exactly when the
  field is a counter (a CHECK). Its values are kept in
  ``metadata_values.value_number``, as any number is.

The downgrade removes every counter definition, and with them their values,
and the ``clock`` display layouts give a field, with each table's row
security unforced and its user triggers held, both restored in the same
transaction. It leaves the label: Postgres cannot drop one, and no row holds
it after.

Revision ID: 20261106_0584
Revises: 20261106_0583
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261106_0584"
down_revision = "20261106_0583"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE public.metadata_type ADD VALUE IF NOT EXISTS 'counter'")
    op.execute("BEGIN")
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "metadata_definitions",
        sa.Column("counter", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_metadata_definitions_counter",
        "metadata_definitions",
        "(type = 'counter') = (counter IS NOT NULL)",
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    _held(
        ("metadata_values", "metadata_definitions"),
        "DELETE FROM metadata_values WHERE property_id IN "
        "(SELECT id FROM metadata_definitions WHERE type::text = 'counter')",
        "DELETE FROM metadata_definitions WHERE type::text = 'counter'",
    )
    _held(
        ("tool_layouts",),
        """
        UPDATE tool_layouts
        SET definition = jsonb_set(
            definition,
            '{displays}',
            COALESCE(
                (
                    SELECT jsonb_object_agg(field, display)
                    FROM jsonb_each(definition -> 'displays') AS d(field, display)
                    WHERE display <> '"clock"'::jsonb
                ),
                '{}'::jsonb
            )
        )
        WHERE jsonb_typeof(definition -> 'displays') = 'object'
          AND EXISTS (
              SELECT 1
              FROM jsonb_each(definition -> 'displays') AS d(field, display)
              WHERE display = '"clock"'::jsonb
          )
        """,
    )
    op.drop_constraint(
        "ck_metadata_definitions_counter", "metadata_definitions", type_="check"
    )
    op.drop_column("metadata_definitions", "counter")


def _held(tables: tuple[str, ...], *statements: str) -> None:
    """Run ``statements`` with the row security of ``tables`` unforced and
    their user triggers held, both restored after."""
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
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    for statement in statements:
        bind.exec_driver_sql(statement)
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
