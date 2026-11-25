"""counter subscriptions and switches follow the plug-in

20261119_0619 made Counters the Counters tool plug-in in each community that
used it. In each community where the plug-in is installed this writes what
that left behind:

* **Webhook subscriptions** that name a built-in Counters event name the
  plug-in's. A built-in tool's events were named by its table
  (``counter_groups.updated``, ``counters.created``); a tool plug-in's are
  named by its kind (``counter_group.tsjvtcm0s7gv2x.updated``,
  ``counter.tsjvtcm0s7gv2x.created``).
* **The switch of an initiative 0619 did not read.** 0619 wrote the built-in
  tool's answer, off, into each initiative with no Counters switch of its
  own, reading the initiatives as the provisioning login with their row
  security forced, so a private initiative and one in the trash had no row
  written. A start then writes an installed tool's switch, on, wherever an
  initiative has none. Each initiative with no switch of its own is given the
  built-in answer here, off, before any start runs. A database that started
  after 0619 already has the start's rows, and cannot tell them from a switch
  someone turned on since, so they are left as they are. A community that
  installed the plug-in from the registry, and so was not converted, holds
  none of the plug-in's keys yet: it is left to the start, which switches
  an installed tool on.

The downgrade names the subscriptions' events the built-in way again. The
switches stay: 0619's downgrade renames them, and off is the built-in tool's
answer for an initiative that had none.

The writes run with each table's row security unforced and its user triggers
held, both restored in the same transaction.

Revision ID: 20261120_0621
Revises: 20261120_0620
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261120_0621"
down_revision = "20261120_0620"
branch_labels = None
depends_on = None

UID = "TSJVTCM0S7GV2X"
_CODE = UID.lower()
#: The plug-in's switch key, as 0619 renamed the built-in tool's.
SWITCH = f"counter_group.{_CODE}:enabled"
#: The plug-in's create key, as 0619 renamed the built-in tool's.
CREATE = f"counter_group.{_CODE}:create"

#: An event name and its spelling the other way: the built-in table's name is
#: its kind's plural.
_ACTIONS = "created|updated|deleted"
_FORWARD = (f"^(counter_group|counter)s\\.({_ACTIONS})$", f"\\1.{_CODE}.\\2")
_BACK = (f"^(counter_group|counter)\\.{_CODE}\\.({_ACTIONS})$", "\\1s.\\2")


@contextmanager
def _held(bind: Connection, *tables: str) -> Iterator[None]:
    """``tables`` with their row security unforced and their user triggers
    held, restored afterwards. The statements inside run under a savepoint,
    so a failure among them leaves the transaction able to restore both, and
    is what propagates."""
    forced = [
        table
        for table in tables
        if bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        with bind.begin_nested():
            yield
    finally:
        for table in tables:
            bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        for table in forced:
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _installed(bind: Connection) -> bool:
    with _held(bind, "guild_plugins"):
        return bool(
            bind.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM guild_plugins WHERE listing_uid = :u)"
                ),
                {"u": UID},
            ).scalar()
        )


def _subscriptions(bind: Connection, forward: bool) -> None:
    """Each subscription's counter events, named the other way."""
    pattern, replacement = _FORWARD if forward else _BACK
    with _held(bind, "webhook_subscriptions"):
        bind.execute(
            text(
                "UPDATE webhook_subscriptions SET event_types = ARRAY("
                " SELECT regexp_replace(e, :p, :r)"
                " FROM unnest(event_types) WITH ORDINALITY AS u(e, n) ORDER BY n"
                ")::varchar(100)[]"
                " WHERE EXISTS (SELECT 1 FROM unnest(event_types) e WHERE e ~ :p)"
            ),
            {"p": pattern, "r": replacement},
        )


def _switches(bind: Connection) -> None:
    """An off switch for each initiative with no Counters switch of its own,
    in a community 0619 converted: one holding the plug-in's keys with no
    install, as 0619 renamed the built-in tool's. An install from the
    registry was not converted and holds none; the start writes its
    switches, as it does for any installed tool, and its rule CHECK, rendered
    before the plug-in's keys were a built-in tool's, would refuse them
    here."""
    with _held(bind, "initiatives", "initiative_rules"):
        bind.execute(
            text(
                "INSERT INTO initiative_rules"
                " (initiative_id, initiative_role_id, key, enabled)"
                " SELECT i.id, NULL, :k, false FROM initiatives i"
                " WHERE EXISTS (SELECT 1 FROM initiative_rules r"
                "  WHERE r.install_id IS NULL AND r.key IN (:k, :c))"
                " ON CONFLICT ON CONSTRAINT uq_initiative_rules_subject DO NOTHING"
            ),
            {"k": SWITCH, "c": CREATE},
        )


def _apply(forward: bool) -> None:
    """The schema the search path leads with, where the plug-in is installed."""
    bind = op.get_bind()
    if not _installed(bind):
        return
    _subscriptions(bind, forward)
    if forward:
        _switches(bind)


def _apply_upgrade() -> None:
    _apply(True)


def _apply_downgrade() -> None:
    _apply(False)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
