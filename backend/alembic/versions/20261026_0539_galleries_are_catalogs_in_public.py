"""Galleries are catalogs in public

The shared half of 20261026_0538:

* **Notices** — a notification, and one still queued, names the catalog kinds
  and their address the new way: ``tool``, ``subject_type``, ``entity_type``
  and ``context_entity_type`` say ``catalog`` or ``catalog_item``, a
  ``/go/gallery/N`` address is ``/go/catalog/N`` and a ``…/galleries/N`` page
  path is ``…/catalogs/N`` (each also in the encoded form a link carries), and
  a rollup key names the kind ``catalog`` or ``catalog_item``. Unread lines
  never expire, so the stored ones are rewritten.
* **Scopes** — a plug-in service's scope ceiling names ``catalogs:read`` and
  ``catalogs:write``.
* **Listings** — a tool listing of a gallery is a ``catalog`` listing, and
  what its versions store (its envelope and its example) names it the way an
  export now does: ``initiative-catalog``, its pictures under ``items``, a
  ``catalog:N`` or ``catalog_item:N`` ref and the tool's two permissions. A
  dashboard listing's statements read ``catalogs``, ``catalog_items`` and
  ``catalog_item_versions`` and their renamed columns (string values left as
  written). A plug-in's own manifest is not rewritten: one still asking for
  ``galleries:*`` is refused until its publisher republishes it.
* **View preferences** — the ones saved for the gallery views are removed;
  those views are the catalog views now and start from their defaults.

``public.member_departs``, ``public.capture_change`` and
``public.fn_comment_trash_follows`` are rendered by a start from the
registries, and the provisioning stamp moved with this change, so the next
boot restates them before any request is served.

The downgrade reverses each rewrite; the removed view preferences stay removed.

Revision ID: 20261026_0539
Revises: 20261026_0538
Create Date: 2026-10-26
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision = "20261026_0539"
down_revision = "20261026_0538"
branch_labels = None
depends_on = None


#: The payload keys that hold a kind.
_KIND_KEYS = ("tool", "subject_type", "entity_type", "context_entity_type")
_KIND = {"gallery_image": "catalog_item", "gallery": "catalog"}
#: An address that names the tool — its ``/go/`` references and its page
#: path — as a path and as a link carries it encoded.
_ADDRESSES = {
    "/go/gallery_image/": "/go/catalog_item/",
    "/go/gallery/": "/go/catalog/",
    "/galleries/": "/catalogs/",
    "%2Fgo%2Fgallery_image%2F": "%2Fgo%2Fcatalog_item%2F",
    "%2Fgo%2Fgallery%2F": "%2Fgo%2Fcatalog%2F",
    "%2Fgalleries%2F": "%2Fcatalogs%2F",
}
_SCOPES = {"galleries:read": "catalogs:read", "galleries:write": "catalogs:write"}
_VIEW_PREFERENCES = (
    "scope_key ~ '(^|:)gallery(:|$)' OR scope_key = 'galleries' "
    "OR starts_with(scope_key, 'galleries:')"
)
#: Listing kinds that are not a tool's: their definitions are not envelopes.
_NOT_TOOL_LISTINGS = ("plugin", "auto", "profile_pack")
_ENVELOPE_KEYS = {"galleries": "catalogs"}
#: The keys only a gallery's envelope spelled differently: its pictures.
_CATALOG_KEYS = {"images": "items"}
_ENVELOPE_TYPES = {"initiative-gallery": "initiative-catalog"}
_REF_KEYS = ("external_ref", "importSourceRef")
_PERMISSIONS = {
    "galleries_enabled": "catalogs_enabled",
    "create_galleries": "create_catalogs",
}
#: What a dashboard listing's statements name: datasets and their columns.
_DATASET_WORDS = {
    "gallery_image_versions": "catalog_item_versions",
    "gallery_images": "catalog_items",
    "galleries": "catalogs",
    "gallery_image_id": "catalog_item_id",
    "gallery_id": "catalog_id",
    "cover_image_id": "cover_item_id",
}
#: What a statement quotes. A string value (single- or dollar-quoted) is left
#: as written, and so is a double-quoted name right after ``AS`` — a column
#: name the statement answers with is its author's. Any other quoted name is a
#: reference, respelled as a bare one is.
_QUOTED = re.compile(r"'(?:[^']|'')*'|\$(\w*)\$.*?\$\1\$|\"((?:[^\"]|\"\")*)\"", re.S)
_ALIAS = re.compile(r"\bAS\s*$", re.I)


def _flip(mapping: Mapping[str, str], forward: bool) -> dict[str, str]:
    return dict(mapping) if forward else {new: old for old, new in mapping.items()}


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


def _rollup(expression: str, forward: bool) -> str:
    """``expression`` with the kind it names as one ``:``-separated segment
    respelled."""
    for old, new in _flip(_KIND, forward).items():
        expression = (
            f"regexp_replace({expression}, '(^|:){old}(:|$)', '\\1{new}\\2', 'g')"
        )
    return expression


def _payload(
    bind: Connection, table: str, column: str, cast: str, forward: bool
) -> None:
    """A notice's JSON: the kinds it names, its addresses and its rollup key."""
    doc = f"CAST({column} AS jsonb)"
    for key in _KIND_KEYS:
        for old, new in _flip(_KIND, forward).items():
            bind.execute(
                text(
                    f"UPDATE {table} SET {column} = CAST(jsonb_set({doc}, "
                    f"'{{{key}}}', to_jsonb(CAST(:new AS text))) AS {cast}) "
                    f"WHERE {doc} ->> '{key}' = :old"
                ),
                {"old": old, "new": new},
            )
    for old, new in _flip(_ADDRESSES, forward).items():
        bind.execute(
            text(
                f"UPDATE {table} SET {column} = CAST(replace(CAST({column} AS text), "
                f":old, :new) AS {cast}) WHERE strpos(CAST({column} AS text), :old) > 0"
            ),
            {"old": old, "new": new},
        )
    key = f"({doc} ->> 'rollup_key')"
    bind.execute(
        text(
            f"UPDATE {table} SET {column} = CAST(jsonb_set({doc}, '{{rollup_key}}', "
            f"to_jsonb({_rollup(key, forward)})) AS {cast}) "
            f"WHERE {key} IS NOT NULL AND {_rollup(key, forward)} <> {key}"
        )
    )


def _notifications(bind: Connection, forward: bool) -> None:
    kind = _flip(_KIND, forward)

    def run() -> None:
        for column in ("tool", "subject_type"):
            for old, new in kind.items():
                bind.execute(
                    text(
                        f"UPDATE public.notifications SET {column} = :new "
                        f"WHERE {column} = :old"
                    ),
                    {"old": old, "new": new},
                )
        _payload(bind, "public.notifications", "data", "json", forward)

    _writable(bind, "public.notifications", run)


def _notice_outbox(bind: Connection, forward: bool) -> None:
    def run() -> None:
        _payload(bind, "public.notice_outbox", "data", "jsonb", forward)
        _payload(bind, "public.notice_outbox", "push_data", "jsonb", forward)
        for old, new in _flip(_ADDRESSES, forward).items():
            bind.execute(
                text(
                    "UPDATE public.notice_outbox SET email_link = "
                    "replace(email_link, :old, :new) WHERE strpos(email_link, :old) > 0"
                ),
                {"old": old, "new": new},
            )
        bind.execute(
            text(
                f"UPDATE public.notice_outbox SET rollup_key = "
                f"{_rollup('rollup_key', forward)} "
                f"WHERE {_rollup('rollup_key', forward)} <> rollup_key"
            )
        )

    _writable(bind, "public.notice_outbox", run)


def _scope_ceilings(bind: Connection, forward: bool) -> None:
    def run() -> None:
        bind.execute(
            text(
                "UPDATE public.plugin_service_registrations SET scope_ceiling = "
                "ARRAY(SELECT coalesce(CAST(:pairs AS jsonb) ->> CAST(v AS text), "
                "CAST(v AS text)) FROM unnest(scope_ceiling) WITH ORDINALITY "
                "AS u(v, i) ORDER BY i) WHERE EXISTS (SELECT 1 FROM "
                "unnest(scope_ceiling) v WHERE CAST(:pairs AS jsonb) ? CAST(v AS text))"
            ),
            {"pairs": json.dumps(_flip(_SCOPES, forward))},
        )

    _writable(bind, "public.plugin_service_registrations", run)


def _statement(sql: str, words: Mapping[str, str]) -> str:
    def respell(part: str) -> str:
        for old, new in words.items():
            part = re.sub(rf"\b{re.escape(old)}\b", new, part)
        return part

    parts: list[str] = []
    last = 0
    for quoted in _QUOTED.finditer(sql):
        name = quoted.group(2)
        kept = quoted.group(0)
        if name in words and not _ALIAS.search(sql[: quoted.start()]):
            kept = f'"{words[name]}"'
        parts += [respell(sql[last : quoted.start()]), kept]
        last = quoted.end()
    return "".join(parts) + respell(sql[last:])


def _envelope_respeller(forward: bool, dashboard: bool) -> Callable[[Any], Any]:
    """A tool listing's envelope, spelled the way an export of this build
    spells it. A dashboard's also has its statements."""
    keys = _flip(_ENVELOPE_KEYS, forward)
    catalog_keys = _flip(_CATALOG_KEYS, forward)
    kinds = _flip(_KIND, forward)
    types = _flip(_ENVELOPE_TYPES, forward)
    permissions = _flip(_PERMISSIONS, forward)
    catalog_type = "initiative-catalog" if forward else "initiative-gallery"
    words = _flip(_DATASET_WORDS, forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {keys.get(key, key): respell(item) for key, item in value.items()}
        if isinstance(out.get("type"), str):
            out["type"] = types.get(out["type"], out["type"])
        if out.get("type") == catalog_type:
            out = {catalog_keys.get(key, key): item for key, item in out.items()}
        for key in ("tool", "entity"):
            if isinstance(out.get(key), str):
                out[key] = kinds.get(out[key], out[key])
        for key in _REF_KEYS:
            ref = out.get(key)
            if isinstance(ref, str):
                kind, colon, rest = ref.partition(":")
                if colon and kind in kinds:
                    out[key] = f"{kinds[kind]}:{rest}"
        if isinstance(out.get("permissions"), dict):
            out["permissions"] = {
                permissions.get(key, key): item
                for key, item in out["permissions"].items()
            }
        if dashboard and isinstance(out.get("sql"), str):
            out["sql"] = _statement(out["sql"], words)
        return out

    return respell


def _listings(bind: Connection, forward: bool) -> None:
    kinds = _flip(_KIND, forward)

    def run_kinds() -> None:
        for old, new in kinds.items():
            bind.execute(
                text(
                    "UPDATE public.marketplace_listings SET kind = :new WHERE kind = :old"
                ),
                {"old": old, "new": new},
            )

    def run_versions() -> None:
        rows = bind.execute(
            text(
                "SELECT v.id, l.kind, v.definition, v.example "
                "FROM public.marketplace_listing_versions v "
                "JOIN public.marketplace_listings l ON l.id = v.listing_id "
                "WHERE l.kind <> ALL(:skip)"
            ),
            {"skip": list(_NOT_TOOL_LISTINGS)},
        ).all()
        for version_id, kind, definition, example in rows:
            respell = _envelope_respeller(forward, kind == "dashboard")
            changed = {}
            for column, value in (("definition", definition), ("example", example)):
                if value is None:
                    continue
                if isinstance(value, str):
                    value = json.loads(value)
                respelled = respell(value)
                if respelled != value:
                    changed[column] = json.dumps(respelled)
            for column, value in changed.items():
                bind.execute(
                    text(
                        f"UPDATE public.marketplace_listing_versions "
                        f"SET {column} = CAST(:v AS jsonb) WHERE id = :id"
                    ),
                    {"v": value, "id": version_id},
                )

    def run() -> None:
        run_kinds()
        run_versions()

    # Both unforced for the whole rewrite: the versions are found by joining
    # their listing, which a forced listings table would hide.
    _writable(
        bind,
        "public.marketplace_listings",
        lambda: _writable(bind, "public.marketplace_listing_versions", run),
    )


def upgrade() -> None:
    bind = op.get_bind()
    _notifications(bind, True)
    _notice_outbox(bind, True)
    _scope_ceilings(bind, True)
    _listings(bind, True)
    _writable(
        bind,
        "public.user_view_preferences",
        lambda: bind.exec_driver_sql(
            f"DELETE FROM public.user_view_preferences WHERE {_VIEW_PREFERENCES}"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    _listings(bind, False)
    _scope_ceilings(bind, False)
    _notice_outbox(bind, False)
    _notifications(bind, False)
