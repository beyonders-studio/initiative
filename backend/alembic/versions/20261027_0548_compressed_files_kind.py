"""The compressed files kind

The kind of a zip, a tarball and the like is ``compressed`` rather than
``archive``, a word the app uses for archiving. A kind is never stored on a
file; the one place it is kept is a saved files view's ``kind`` filter, in
``public.user_view_preferences``, which takes the new name. The downgrade
gives it the old one back.

Revision ID: 20261027_0548
Revises: 20261027_0547
Create Date: 2026-10-27
"""

from __future__ import annotations

import json
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision = "20261027_0548"
down_revision = "20261027_0547"
branch_labels = None
depends_on = None


def _respelled(value: Any, old: str, new: str) -> Any:
    if isinstance(value, list):
        return [_respelled(item, old, new) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: new if key == "kind" and item == old else _respelled(item, old, new)
        for key, item in value.items()
    }


def _view_preferences(bind: Connection, old: str, new: str) -> None:
    table = "public.user_view_preferences"
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        rows = bind.execute(
            text(
                f"SELECT id, value FROM {table} "
                "WHERE scope_key ~ '(^|:)files(:|$)' "
                "AND CAST(value AS text) LIKE :spelled"
            ),
            {"spelled": f'%"{old}"%'},
        ).all()
        for preference_id, value in rows:
            if isinstance(value, str):
                value = json.loads(value)
            respelled = _respelled(value, old, new)
            if respelled != value:
                bind.execute(
                    text(f"UPDATE {table} SET value = CAST(:v AS json) WHERE id = :id"),
                    {"v": json.dumps(respelled), "id": preference_id},
                )
    finally:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _view_preferences(op.get_bind(), "archive", "compressed")


def downgrade() -> None:
    _view_preferences(op.get_bind(), "compressed", "archive")
