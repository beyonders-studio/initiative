"""Timers: the writes that give a background sweep work, and the wake each one
leaves for it.

A sweep that works community by community (publishing scheduled posts,
purging trash, expiring records) used to visit every community on a fixed
cadence to find out whether anything was due. Now the write that makes work
arms a timer for it, in its own transaction: one row in
``public.community_timers`` naming the community, the sweep and when.
``app.services.sweep_timers`` claims due timers and visits only those.

Which writes arm which sweep is declared with the sweep, as its
:class:`TimerSource` entries (``app.services.sweep_timers.sweeps``). Rendered
from there into each community's schema as triggers, the way the change
capture is (``app.db.event_capture``): every trigger calls the one shared
``public.arm_timer_on_write()``, which works out the due time and hands it to
``public.arm_timer()``.

A timer due at once wakes the worker on every process: ``arm_timer`` sends
:data:`WAKE_CHANNEL` in the arming transaction, so the wake goes out only if
the write commits. A lost wake costs one tick.

A timer is a wake, not the work. The visit reads what is due from the
community's own tables and arms the next one, so a timer may come early (the
visit finds nothing) but a source must never arm one later than its work.

``timer_marks`` keeps, per sweep, the earliest timer the community already has
waiting. A write whose work is due no earlier adds nothing, so a busy community
adds one row per sweep until it fires rather than one per write. A transaction-
local setting does the same within one transaction, before the mark is read.

Arming never fails the write that caused it. A session that is not routed into
the community whose schema it writes, or holds no right to add a timer (a
filer, a migration), arms nothing, and the daily reconcile finds the work.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

from app.db import gucs

#: How a row source's due time reads the written row: as ``$1`` in the
#: trigger's EXECUTE, the way the capture triggers read theirs.
ROW = "($1)"

#: Where a timer armed to run at once wakes the worker.
WAKE_CHANNEL = "community_timers"

#: The shared trigger function every timer trigger calls.
ARM_ON_WRITE_FUNCTION = "public.arm_timer_on_write"

#: A mark this far past its time is taken to have lost its timer, and the next
#: write arms again.
MARK_STALE_AFTER = timedelta(hours=1)

#: Where a transaction notes the earliest timer it armed for a sweep.
_MEMO_PREFIX = "initiative.timer_"


def interval(delta: timedelta) -> str:
    """``delta`` as a SQL interval literal's text."""
    return f"{int(delta.total_seconds())} seconds"


@dataclass(frozen=True)
class TimerSource:
    """One table whose writes give a sweep work."""

    table: str
    #: For a row source: SQL over the written row, as ``{row}``, giving when
    #: the work is due. ``None`` for a statement source.
    due: str | None = None
    #: How long after the write the work is due: added to ``due`` for a row
    #: source, to ``now()`` for a statement source.
    after: timedelta = timedelta(0)
    #: For a row source: which writes arm (``INSERT``, ``UPDATE OF col``, …).
    events: str = "INSERT"
    #: For a row source: the trigger's ``WHEN``, over ``NEW``.
    when: str | None = None

    @property
    def per_statement(self) -> bool:
        return self.due is None


def on_row(
    table: str,
    due: str,
    *,
    after: timedelta = timedelta(0),
    events: str = "INSERT",
    when: str | None = None,
) -> TimerSource:
    """A source that arms from each written row, for the writes ``events`` and
    ``when`` admit."""
    return TimerSource(table=table, due=due, after=after, events=events, when=when)


def on_insert(table: str, *, after: timedelta) -> TimerSource:
    """A source that arms ``after`` from now on any insert: once per statement,
    for a table written on nearly every action."""
    return TimerSource(table=table, after=after)


ARM_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION public.arm_timer(p_kind text, p_due timestamp with time zone)
    RETURNS void
    LANGUAGE plpgsql
AS $arm$
DECLARE
    v_memo_name text := '{_MEMO_PREFIX}' || p_kind;
    v_memo text := current_setting(v_memo_name, true);
    v_community integer := {gucs.ROUTED_GUILD_ID};
    v_mark timestamp with time zone;
    v_moved boolean;
BEGIN
    IF p_due IS NULL
       OR (COALESCE(v_memo, '') <> '' AND v_memo::numeric <= extract(epoch FROM p_due))
    THEN
        RETURN;
    END IF;
    -- Arming never fails the write that caused it: a session routed elsewhere,
    -- or with no right to add a timer, leaves the work to the daily reconcile.
    IF v_community IS NULL
       OR current_schema() IS DISTINCT FROM 'guild_' || v_community
       OR NOT has_table_privilege('public.community_timers', 'INSERT')
    THEN
        RETURN;
    END IF;
    SELECT due_at INTO v_mark FROM timer_marks WHERE kind = p_kind;
    IF v_mark IS NULL
       OR v_mark > p_due
       OR v_mark < now() - interval '{interval(MARK_STALE_AFTER)}'
    THEN
        -- Writers arming at once decide one at a time: the mark only moves
        -- earlier (or past a stale one), and only the writer that moved it
        -- adds the timer.
        INSERT INTO timer_marks (kind, due_at) VALUES (p_kind, p_due)
            ON CONFLICT (kind) DO UPDATE SET due_at = EXCLUDED.due_at
            WHERE timer_marks.due_at > EXCLUDED.due_at
               OR timer_marks.due_at < now() - interval '{interval(MARK_STALE_AFTER)}'
            RETURNING true INTO v_moved;
        IF v_moved THEN
            INSERT INTO public.community_timers (community_id, kind, due_at)
                VALUES (v_community, p_kind, p_due);
            IF p_due <= now() THEN
                PERFORM pg_notify('{WAKE_CHANNEL}', '');
            END IF;
        END IF;
    END IF;
    PERFORM set_config(v_memo_name, extract(epoch FROM p_due)::text, true);
END
$arm$;
"""

ARM_ON_WRITE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {ARM_ON_WRITE_FUNCTION}()
    RETURNS trigger
    LANGUAGE plpgsql
AS $arm_on_write$
DECLARE
    v_kind text := TG_ARGV[0];
    v_memo text := current_setting('{_MEMO_PREFIX}' || v_kind, true);
    v_due timestamp with time zone;
BEGIN
    IF TG_LEVEL = 'ROW' THEN
        EXECUTE 'SELECT ' || TG_ARGV[1] INTO v_due USING NEW;
    ELSE
        v_due := now() + TG_ARGV[1]::interval;
    END IF;
    IF v_due IS NULL
       OR (COALESCE(v_memo, '') <> '' AND v_memo::numeric <= extract(epoch FROM v_due))
    THEN
        RETURN NULL;
    END IF;
    PERFORM public.arm_timer(v_kind, v_due);
    RETURN NULL;
END
$arm_on_write$;
"""


def _quoted(expr: str) -> str:
    return "'" + expr.replace("'", "''") + "'"


def _trigger(name: str, kind: str, source: TimerSource) -> str:
    if source.per_statement:
        due = interval(source.after)
        events, level, when = "INSERT", "STATEMENT", None
    else:
        assert source.due is not None
        due = source.due.format(row=ROW)
        if source.after:
            due = f"({due} + interval '{interval(source.after)}')"
        events, level, when = source.events, "ROW", source.when
    return "\n".join(
        [
            f"DROP TRIGGER IF EXISTS {name} ON {source.table};",
            f"CREATE TRIGGER {name}",
            f"  AFTER {events} ON {source.table}",
            f"  FOR EACH {level}",
            *([f"  WHEN ({when})"] if when else []),
            f"  EXECUTE FUNCTION {ARM_ON_WRITE_FUNCTION}(",
            f"    '{kind}', {_quoted(due)}",
            "  );",
        ]
    )


_HEADER = """\
-- ============================================================================
-- SWEEP TIMERS — GENERATED, DO NOT EDIT BY HAND
-- RENDERED AT RUNTIME from app/db/timers.py, from the sources each sweep in
-- app.services.sweep_timers.sweeps() declares. Every trigger calls
-- public.arm_timer_on_write(), which arms public.community_timers.
-- ============================================================================"""


def _triggers(operations: bool) -> Iterator[tuple[str, str, TimerSource]]:
    """Each timer trigger's name, sweep and source: every community's, or with
    ``operations`` those of the sweeps only the operations community runs."""
    from app.services.guild_sweeps import Scope
    from app.services.sweep_timers import sweeps

    named: dict[str, int] = {}
    for sweep in sweeps():
        if (sweep.scope is Scope.OPERATIONS) != operations:
            continue
        for source in sweep.sources:
            name = f"tr_{source.table}_timer_{sweep.kind}"
            # A second source on one table for one sweep is numbered.
            named[name] = named.get(name, 0) + 1
            if named[name] > 1:
                name = f"{name}_{named[name]}"
            yield name, sweep.kind, source


def render_guild_timer_ddl(*, operations: bool = False) -> str:
    """Per-table timer triggers, applied inside each guild schema: every
    community's, or with ``operations`` the operations community's own."""
    blocks = [
        _trigger(name, kind, source) for name, kind, source in _triggers(operations)
    ]
    return _HEADER + "\n\n" + "\n\n".join(blocks) + "\n"


def drop_operations_timers_ddl() -> str:
    """Removes the triggers only the operations community's schema has."""
    return "".join(
        f"DROP TRIGGER IF EXISTS {name} ON {source.table};\n"
        for name, _kind, source in _triggers(operations=True)
    )
