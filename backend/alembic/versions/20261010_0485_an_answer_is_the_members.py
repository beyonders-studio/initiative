"""an answer is the member's

Every RSVP answer moves into ``calendar_event_answers``, in every guild schema,
and ``calendar_event_attendees.rsvp_status`` is dropped: an attendee row says
only that someone is invited.

``calendar_event_answers`` is keyed by an event, or by a series and an
occurrence's start there, whether or not that occurrence has a row of its own:
it takes a surrogate ``id``, ``original_start`` becomes the nullable
``occurrence_start`` (NULL for an event that doesn't repeat), and the
composite primary key gives way to ``uq_calendar_event_answers_key``, unique
with NULLs not distinct.

Each answer on an attendee row is carried over: an override's to its series
and start, any other event's to the event. Where an answer is already kept at
that key, the attendee row's wins, since it was the later of the two. The
insert policy and the owner guard are rendered by the provisioning run.

The downgrade carries the answers back onto attendee rows.

Revision ID: 20261010_0485
Revises: 20261010_0484
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0485"
down_revision = "20261010_0484"
branch_labels = None
depends_on = None

ANSWERS = "calendar_event_answers"
ATTENDEES = "calendar_event_attendees"
KEY = "uq_calendar_event_answers_key"


def _forced(bind, tables: tuple[str, ...]) -> list[str]:
    """The tables of ``tables`` that force RLS on their owner here."""
    return [
        table
        for table in tables
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]


def _unforced(bind, write) -> None:
    """Run ``write`` with the owner's RLS lifted and the user triggers held on
    both tables, restored after."""
    tables = (ANSWERS, ATTENDEES)
    forced = _forced(bind, tables)
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        write()
    finally:
        for table in tables:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))


def _move_in(bind) -> None:
    bind.execute(
        sa.text(
            f"INSERT INTO {ANSWERS} "
            "(calendar_event_id, user_id, occurrence_start, rsvp_status) "
            "SELECT coalesce(e.series_id, e.id), a.user_id,"
            " CASE WHEN e.series_id IS NOT NULL THEN e.original_start END,"
            " a.rsvp_status "
            f"FROM {ATTENDEES} a JOIN calendar_events e ON e.id = a.calendar_event_id "
            "WHERE a.rsvp_status <> 'pending' "
            f"ON CONFLICT ON CONSTRAINT {KEY} "
            "DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status"
        )
    )


def _apply_upgrade(bind) -> None:
    op.drop_constraint(f"{ANSWERS}_pkey", ANSWERS, type_="primary")
    op.execute(f"ALTER TABLE {ANSWERS} ADD COLUMN id SERIAL PRIMARY KEY")
    op.alter_column(
        ANSWERS, "original_start", new_column_name="occurrence_start", nullable=True
    )
    op.execute(
        f"ALTER TABLE {ANSWERS} ADD CONSTRAINT {KEY} UNIQUE NULLS NOT DISTINCT"
        " (calendar_event_id, user_id, occurrence_start)"
    )
    _unforced(bind, lambda: _move_in(bind))
    op.drop_column(ATTENDEES, "rsvp_status")


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
    op.execute("DROP FUNCTION IF EXISTS public.fn_calendar_event_answer_owner_guard()")


def _move_out(bind) -> None:
    # An answer to an event, or to an occurrence with a row of its own, goes
    # onto that event's attendee row; the rest stay kept beside their series.
    bind.execute(
        sa.text(
            f"INSERT INTO {ATTENDEES} (calendar_event_id, user_id, rsvp_status, created_at) "
            "SELECT coalesce(o.id, k.calendar_event_id), k.user_id, k.rsvp_status, now() "
            f"FROM {ANSWERS} k LEFT JOIN calendar_events o"
            " ON o.series_id = k.calendar_event_id AND o.original_start = k.occurrence_start "
            "WHERE k.occurrence_start IS NULL OR o.id IS NOT NULL "
            "ON CONFLICT (calendar_event_id, user_id) "
            "DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status"
        )
    )
    bind.execute(
        sa.text(
            f"DELETE FROM {ANSWERS} k WHERE k.occurrence_start IS NULL OR EXISTS ("
            "SELECT 1 FROM calendar_events o WHERE o.series_id = k.calendar_event_id"
            " AND o.original_start = k.occurrence_start)"
        )
    )


def _apply_downgrade(bind) -> None:
    op.add_column(
        ATTENDEES,
        sa.Column(
            "rsvp_status",
            postgresql.ENUM(name="rsvp_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
    )
    _unforced(bind, lambda: _move_out(bind))
    op.drop_constraint(KEY, ANSWERS, type_="unique")
    op.drop_column(ANSWERS, "id")
    op.alter_column(
        ANSWERS, "occurrence_start", new_column_name="original_start", nullable=False
    )
    op.create_primary_key(
        f"{ANSWERS}_pkey", ANSWERS, ["calendar_event_id", "user_id", "original_start"]
    )
