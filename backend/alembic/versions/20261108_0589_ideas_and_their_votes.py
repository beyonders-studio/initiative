"""ideas and their votes

Two operations tables, in ``guild_template`` and the operations community's
schema alone. ``ideas`` holds the Ideas board's published tasks, one row each:
the row is what publishes a task. ``idea_votes`` holds who voted for which
idea, and the status each voter was last told it was in. Neither holds rows
yet. Their row security is rendered at the next start, as always.

The Ideas board is a stream, so the check on ``intake_bindings.stream`` and
``intake_cases.stream`` admits ``ideas`` beside the four it held. The
downgrade takes away an Ideas binding before it puts the four back.

Revision ID: 20261108_0589
Revises: 20261107_0588
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261108_0589"
down_revision = "20261107_0588"
branch_labels = None
depends_on = None

TABLES = ("idea_votes", "ideas")

#: The streams each check admitted before, and after.
_BEFORE = ("security", "moderation", "support", "feedback")
_AFTER = (*_BEFORE, "ideas")


def _streams_check(streams: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{stream}'" for stream in streams)
    for table in ("intake_bindings", "intake_cases"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_stream")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_stream"
            f" CHECK (stream IN ({listed}))"
        )


def _create() -> None:
    _streams_check(_AFTER)
    op.create_table(
        "ideas",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.execute(
        "CREATE TRIGGER tr_ideas_set_created_by BEFORE INSERT "
        "ON ideas FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )
    op.create_table(
        "idea_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("voted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_status_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_idea_votes_task_user"),
    )
    op.create_index("ix_idea_votes_task_id", "idea_votes", ["task_id"], unique=False)


def _drop() -> None:
    """Drop both tables: their rendered policies first, then their row
    security, then the tables."""
    bind = op.get_bind()
    for table in TABLES:
        if bind.execute(
            sa.text("SELECT to_regclass(:t) IS NULL"), {"t": table}
        ).scalar():
            continue
        for (name,) in bind.execute(
            sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
            {"t": table},
        ).all():
            op.execute(f'DROP POLICY IF EXISTS "{name}" ON {table}')
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
    forced = bind.execute(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = to_regclass('intake_bindings')"
        )
    ).scalar()
    if forced:
        op.execute("ALTER TABLE intake_bindings NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM intake_bindings WHERE stream = 'ideas'")
    if forced:
        op.execute("ALTER TABLE intake_bindings FORCE ROW LEVEL SECURITY")
    _streams_check(_BEFORE)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _create, operations=True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop, operations=True)
