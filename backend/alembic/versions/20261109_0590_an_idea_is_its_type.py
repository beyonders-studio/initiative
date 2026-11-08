"""an idea is its type

A published idea is a task on the Ideas board of the type its binding names,
so nothing writes an ``ideas`` case any more. This takes away the ones
``20261108_0589`` let the Ideas board's publish switch write, puts the check
on ``intake_cases.stream`` back to the four streams that file cases, and drops
the ideas role's policies on ``intake_cases``, which it no longer reads. The
role's other policies are rendered at the next start, as always.

The downgrade admits ``ideas`` on the check again; the cases it took away are
not put back.

Revision ID: 20261109_0590
Revises: 20261108_0589
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0590"
down_revision = "20261108_0589"
branch_labels = None
depends_on = None

#: The streams the check admitted before, and after.
_BEFORE = ("security", "moderation", "support", "feedback", "ideas")
_AFTER = ("security", "moderation", "support", "feedback")


def _streams_check(streams: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{stream}'" for stream in streams)
    op.execute(
        "ALTER TABLE intake_cases DROP CONSTRAINT IF EXISTS ck_intake_cases_stream"
    )
    op.execute(
        "ALTER TABLE intake_cases ADD CONSTRAINT ck_intake_cases_stream"
        f" CHECK (stream IN ({listed}))"
    )


def _upgrade() -> None:
    bind = op.get_bind()
    for name in ("ideas_read", "ideas_only"):
        op.execute(f"DROP POLICY IF EXISTS {name} ON intake_cases")
    forced = bind.execute(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = to_regclass('intake_cases')"
        )
    ).scalar()
    if forced:
        op.execute("ALTER TABLE intake_cases NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM intake_cases WHERE stream = 'ideas'")
    if forced:
        op.execute("ALTER TABLE intake_cases FORCE ROW LEVEL SECURITY")
    _streams_check(_AFTER)


def _downgrade() -> None:
    _streams_check(_BEFORE)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade, operations=True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade, operations=True)
