"""Files take their formats in public

The shared half of 20261026_0540:

* **Type** — no column uses ``public.file_type`` once every guild schema
  stores the format as text, so the type is dropped.
* **Listings** — a file a tool listing carries (its envelope and its example,
  and a file filed in a listed wiki) names its type the way an export now
  does: ``lexical``, ``excalidraw``, ``sheet`` or ``url``.
* **View preferences** — a saved files view drops its ``file_type`` filter:
  the list is filtered by kind now, and a former type is not one it takes.

The downgrade spells the listings' types the old way and creates the type
again, before 20261026_0540's downgrade needs it; the dropped filters stay
dropped.

Revision ID: 20261026_0541
Revises: 20261026_0540
Create Date: 2026-10-26
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision = "20261026_0541"
down_revision = "20261026_0540"
branch_labels = None
depends_on = None


_TYPES = {
    "native": "lexical",
    "whiteboard": "excalidraw",
    "spreadsheet": "sheet",
    "smart_link": "url",
}
_NOT_TOOL_LISTINGS = ("plugin", "auto", "profile_pack")


def _writable(bind: Connection, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with ``table``'s row security unforced and its user triggers
    held, both restored either way."""
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
        fn()
    finally:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _respeller(forward: bool) -> Callable[[Any], Any]:
    types = _TYPES if forward else {new: old for old, new in _TYPES.items()}

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {key: respell(item) for key, item in value.items()}
        if out.get("type") == "initiative-file" and out.get("file_type") in types:
            out["file_type"] = types[out["file_type"]]
        return out

    return respell


def _listings(bind: Connection, forward: bool) -> None:
    respell = _respeller(forward)

    def run() -> None:
        rows = bind.execute(
            text(
                "SELECT v.id, v.definition, v.example "
                "FROM public.marketplace_listing_versions v "
                "JOIN public.marketplace_listings l ON l.id = v.listing_id "
                "WHERE l.kind <> ALL(:skip)"
            ),
            {"skip": list(_NOT_TOOL_LISTINGS)},
        ).all()
        for version_id, definition, example in rows:
            for column, value in (("definition", definition), ("example", example)):
                if value is None:
                    continue
                if isinstance(value, str):
                    value = json.loads(value)
                respelled = respell(value)
                if respelled != value:
                    bind.execute(
                        text(
                            f"UPDATE public.marketplace_listing_versions "
                            f"SET {column} = CAST(:v AS jsonb) WHERE id = :id"
                        ),
                        {"v": json.dumps(respelled), "id": version_id},
                    )

    # Both unforced for the whole rewrite: the versions are found by joining
    # their listing, which a forced listings table would hide.
    _writable(
        bind,
        "public.marketplace_listings",
        lambda: _writable(bind, "public.marketplace_listing_versions", run),
    )


def _without_type_filter(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_type_filter(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _without_type_filter(item)
        for key, item in value.items()
        if key != "file_type"
    }


def _view_preferences(bind: Connection) -> None:
    def run() -> None:
        rows = bind.execute(
            text(
                "SELECT id, value FROM public.user_view_preferences "
                "WHERE scope_key ~ '(^|:)files(:|$)' "
                "AND CAST(value AS text) LIKE '%\"file_type\"%'"
            )
        ).all()
        for preference_id, value in rows:
            if isinstance(value, str):
                value = json.loads(value)
            bind.execute(
                text(
                    "UPDATE public.user_view_preferences "
                    "SET value = CAST(:v AS json) WHERE id = :id"
                ),
                {"v": json.dumps(_without_type_filter(value)), "id": preference_id},
            )

    _writable(bind, "public.user_view_preferences", run)


def upgrade() -> None:
    bind = op.get_bind()
    _listings(bind, True)
    _view_preferences(bind)
    op.execute("DROP TYPE IF EXISTS public.file_type")


def downgrade() -> None:
    op.execute(
        "CREATE TYPE public.file_type AS ENUM "
        "('native', 'file', 'whiteboard', 'smart_link', 'spreadsheet')"
    )
    _listings(op.get_bind(), False)
