"""digests keep their own time

The overdue reminder leaves "Assigned to you" for a digests row of its own,
beside a new "Coming up" digest, and each digest keeps its own schedule
rather than borrowing the email's.

Every account keeps what it had: an "Assigned to you" email or push switched
off now switches off the overdue digest too, and the overdue digest goes out
at the email's time, weekly where the email was. ``users`` gains the stamp
that claims each day's "Coming up", as ``last_overdue_notification_at`` does
the overdue digest's, granted to the request floors with every other
``users`` column (0144).

The downgrade drops the stamp and the new settings; the old rows read the
email's time again.

Revision ID: 20261028_0553
Revises: 20261028_0552
Create Date: 2026-10-28
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261028_0553"
down_revision = "20261028_0552"
branch_labels = None
depends_on = None

#: The stamp that claims each day's "Coming up".
COLUMN = "last_coming_up_digest_at"

#: The channels a digest has.
_CHANNELS = ("email", "push")


def separate(doc: dict[str, Any]) -> dict[str, Any]:
    """One account's settings, with the overdue digest on its own row."""
    out = dict(doc)
    categories = doc.get("categories")
    categories = categories if isinstance(categories, dict) else {}
    assigned = categories.get("assignments")
    assigned = assigned if isinstance(assigned, dict) else {}
    overdue = {
        channel: assigned[channel]
        for channel in _CHANNELS
        if isinstance(assigned.get(channel), bool)
    }
    if overdue:
        out["categories"] = {**categories, "overdue": overdue}
    email = doc.get("email")
    email = email if isinstance(email, dict) else {}
    schedule = {key: email[key] for key in ("at", "weekday") if key in email}
    if email.get("cadence") == "weekly":
        schedule["cadence"] = "weekly"
    if schedule:
        out["digests"] = {"overdue": schedule}
    return out


@contextmanager
def _writing(table: str) -> Iterator[None]:
    # A FORCE-RLS table the migration role owns binds it to policies keyed on
    # request settings a migration has no value for, so a forced table has
    # the force lifted for the write and restored with it.
    conn = op.get_bind()
    forced = conn.execute(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = CAST(:table AS regclass)"
        ),
        {"table": f"public.{table}"},
    ).scalar_one()
    if forced:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield
    finally:
        if forced:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _rewrite(change: Any) -> None:
    conn = op.get_bind()
    with _writing("user_notification_prefs"):
        rows = conn.execute(
            sa.text("SELECT user_id, prefs FROM public.user_notification_prefs")
        ).all()
        for user_id, prefs in rows:
            doc = prefs if isinstance(prefs, dict) else json.loads(prefs or "{}")
            moved = change(doc)
            if moved != doc:
                conn.execute(
                    sa.text(
                        "UPDATE public.user_notification_prefs"
                        " SET prefs = CAST(:prefs AS jsonb), updated_at = now()"
                        " WHERE user_id = :user_id"
                    ),
                    {"prefs": json.dumps(moved), "user_id": user_id},
                )


def _join(doc: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in doc.items() if key != "digests"}
    categories = doc.get("categories")
    if isinstance(categories, dict):
        rows = {
            name: value
            for name, value in categories.items()
            if name not in ("overdue", "coming_up")
        }
        if rows:
            out["categories"] = rows
        else:
            out.pop("categories", None)
    return out


def upgrade() -> None:
    op.add_column("users", sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        for role in (f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"', "app_user"):
            op.execute(f"GRANT UPDATE ({COLUMN}) ON TABLE public.users TO {role}")
    _rewrite(separate)


def downgrade() -> None:
    _rewrite(_join)
    # The grant goes with the column it names.
    op.drop_column("users", COLUMN)
