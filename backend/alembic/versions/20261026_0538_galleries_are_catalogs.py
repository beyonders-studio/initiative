"""Galleries are catalogs

The galleries tool is the catalogs tool, and a gallery's picture is a catalog
item. In ``guild_template`` and every ``guild_<id>``:

* **Tables** — ``galleries`` is ``catalogs``, ``gallery_images`` is
  ``catalog_items`` and ``gallery_image_versions`` is
  ``catalog_item_versions``, with their sequences, keys and indexes named to
  match.
* **Columns** — ``catalogs.cover_image_id`` is ``cover_item_id``,
  ``catalog_items.gallery_id`` and ``comments.gallery_id`` are ``catalog_id``,
  ``catalog_item_versions.gallery_image_id`` is ``catalog_item_id`` and
  ``initiatives.galleries_enabled`` is ``catalogs_enabled``.
* **Triggers** — the owner-row trigger names the kind ``catalog``. The rest a
  start renders from the registries, so they are dropped here and the next
  boot renders them again under the new names, before any request is served;
  the search generation is cleared so that boot re-sweeps the index.
* **Stored values** — the kinds ``gallery`` and ``gallery_image`` are
  ``catalog`` and ``catalog_item`` (sharing, guest invitations, property
  values, plug-in values, personal items, engagement levels, relationships,
  search entries, reactions, the reaction digest, holds, moderation reports
  and acts, layouts), and a digest line's address says ``/go/catalog/N`` or
  ``…/catalogs/N``; the resource ``galleries`` is ``catalogs`` (the change log,
  its parents and the tool it names, webhook event types), and a change to a catalog's pictures lists ``items`` where it listed
  ``images``; the column names a change or a subscription lists follow the
  columns; the scopes ``galleries:read``/``galleries:write`` are
  ``catalogs:*`` and an install's definition names the item kind
  ``catalog_item``; the role permissions ``galleries_enabled``/
  ``create_galleries`` are ``catalogs_enabled``/``create_catalogs``; a
  dashboard's statements read the datasets ``catalogs``, ``catalog_items`` and
  ``catalog_item_versions`` and their renamed columns (a string value in one is
  left as written); a queued export or import names the tool ``catalog``. The
  CHECK constraints holding a kind or a permission are restated for the writes.

``public.relationship_kind_code`` names the kinds ``catalog`` (still code 7)
and ``catalog_item`` (still code 8). The edges' node columns are computed from
it, and an edge's two ends are respelled one column at a time, so while they
are it reads both spellings; it reads only the new one once every schema says
it. The rewrites run with each table's row security unforced and its user
triggers held: nothing changed about the rows but their spelling.

Stored editor content is left as it was written; the reference reader takes
``gallery`` and ``gallery_image`` as the catalog kinds.

Revision ID: 20261026_0538
Revises: 20261026_0537
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

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261026_0538"
down_revision = "20261026_0537"
branch_labels = None
depends_on = None


_TABLES = (
    ("galleries", "catalogs"),
    ("gallery_images", "catalog_items"),
    ("gallery_image_versions", "catalog_item_versions"),
)
#: (table under its new name, old column, new column)
_COLUMNS = (
    ("catalogs", "cover_image_id", "cover_item_id"),
    ("catalog_items", "gallery_id", "catalog_id"),
    ("catalog_item_versions", "gallery_image_id", "catalog_item_id"),
    ("comments", "gallery_id", "catalog_id"),
    ("initiatives", "galleries_enabled", "catalogs_enabled"),
)
#: (table under its new name, old constraint, new constraint)
_CONSTRAINTS = (
    ("catalogs", "galleries_pkey", "catalogs_pkey"),
    ("catalogs", "galleries_initiative_id_fkey", "catalogs_initiative_id_fkey"),
    ("catalogs", "galleries_cover_image_id_fkey", "catalogs_cover_item_id_fkey"),
    ("catalog_items", "gallery_images_pkey", "catalog_items_pkey"),
    (
        "catalog_items",
        "gallery_images_gallery_id_fkey",
        "catalog_items_catalog_id_fkey",
    ),
    (
        "catalog_items",
        "gallery_images_current_version_id_fkey",
        "catalog_items_current_version_id_fkey",
    ),
    (
        "catalog_item_versions",
        "gallery_image_versions_pkey",
        "catalog_item_versions_pkey",
    ),
    (
        "catalog_item_versions",
        "gallery_image_versions_gallery_image_id_fkey",
        "catalog_item_versions_catalog_item_id_fkey",
    ),
    ("catalog_item_versions", "uq_giv_image_version", "uq_civ_item_version"),
    ("comments", "comments_gallery_id_fkey", "comments_catalog_id_fkey"),
)
_INDEXES = (
    ("ix_galleries_initiative_id", "ix_catalogs_initiative_id"),
    ("ix_galleries_purge", "ix_catalogs_purge"),
    ("ix_gallery_images_created_at", "ix_catalog_items_created_at"),
    ("ix_gallery_images_current_version_id", "ix_catalog_items_current_version_id"),
    ("ix_gallery_images_gallery_id", "ix_catalog_items_catalog_id"),
    ("ix_gallery_images_purge", "ix_catalog_items_purge"),
    (
        "ix_gallery_image_versions_gallery_image_id",
        "ix_catalog_item_versions_catalog_item_id",
    ),
    ("ix_comments_gallery_id", "ix_comments_catalog_id"),
)
_SEQUENCES = (
    ("galleries_id_seq", "catalogs_id_seq"),
    ("gallery_images_id_seq", "catalog_items_id_seq"),
    ("gallery_image_versions_id_seq", "catalog_item_versions_id_seq"),
)
_OWNS_TRIGGERS = ("tr_galleries_install_owns", "tr_catalogs_install_owns")

#: The value each name takes; the downgrade reads them the other way.
_KIND = {"gallery": "catalog", "gallery_image": "catalog_item"}
_RESOURCE = {"galleries": "catalogs"}
#: How a change to a catalog's pictures is labelled among its changes.
_FACET = {"images": "items"}
_FIELDS = {
    "cover_image_id": "cover_item_id",
    "gallery_id": "catalog_id",
    "gallery_image_id": "catalog_item_id",
    "galleries_enabled": "catalogs_enabled",
}
_PERMISSIONS = {
    "galleries_enabled": "catalogs_enabled",
    "create_galleries": "create_catalogs",
}
_SCOPES = {"galleries:read": "catalogs:read", "galleries:write": "catalogs:write"}
#: Names a dashboard's statement reads: datasets and their columns.
_DATASET_WORDS = {
    "gallery_image_versions": "catalog_item_versions",
    "gallery_images": "catalog_items",
    "galleries": "catalogs",
    "gallery_image_id": "catalog_item_id",
    "gallery_id": "catalog_id",
    "cover_image_id": "cover_item_id",
}
#: Keys a queued export or import names the tool by.
_JOB_KEYS = {"gallery": "catalog", "gallery_ids": "catalog_ids"}
_ENVELOPE_TYPES = {"initiative-gallery": "initiative-catalog"}
#: An address that names the tool: its ``/go/`` references and its page path.
_ADDRESSES = {
    "/go/gallery_image/": "/go/catalog_item/",
    "/go/gallery/": "/go/catalog/",
    "/galleries/": "/catalogs/",
}
#: Keys in an install's definition whose value names a kind.
_KIND_KEYS = ("entity", "kind", "tool", "itemKind")

#: ``public.relationship_kind_code``: kind -> its permanent code. The catalog
#: kinds keep 7 and 8, so every stored node id stays what it was.
_KIND_CODES_BEFORE = (
    ("calendar", 1),
    ("calendar_event", 2),
    ("counter", 3),
    ("counter_group", 4),
    ("dashboard", 5),
    ("file", 6),
    ("gallery", 7),
    ("gallery_image", 8),
    ("post", 9),
    ("project", 10),
    ("queue", 11),
    ("queue_item", 12),
    ("tag", 13),
    ("task", 14),
    ("wiki", 15),
    ("wiki_page", 16),
)
_KIND_CODES_AFTER = tuple(
    (_KIND.get(kind, kind), code) for kind, code in _KIND_CODES_BEFORE
)
#: Both spellings, while an edge's two ends say different ones.
_KIND_CODES_EITHER = _KIND_CODES_BEFORE + tuple(
    pair for pair in _KIND_CODES_AFTER if pair not in _KIND_CODES_BEFORE
)

_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"


def _flip(mapping: Mapping[str, str], forward: bool) -> dict[str, str]:
    return dict(mapping) if forward else {new: old for old, new in mapping.items()}


def _kind_code_fn(codes: tuple[tuple[str, int], ...]) -> str:
    arms = " ".join(f"WHEN '{kind}' THEN {code}" for kind, code in codes)
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def _exists(bind: Connection, sql: str, params: dict[str, Any]) -> bool:
    return bind.execute(text(sql), params).scalar() is not None


def _table_exists(bind: Connection, table: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar())


def _has_column(bind: Connection, table: str, column: str) -> bool:
    return _exists(
        bind,
        "SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(:t) "
        "AND attname = :c AND NOT attisdropped",
        {"t": table, "c": column},
    )


def _has_constraint(bind: Connection, table: str, name: str) -> bool:
    return _exists(
        bind,
        "SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass(:t) AND conname = :n",
        {"t": table, "n": name},
    )


# --- structure ---------------------------------------------------------------


def _rename_structure(bind: Connection, forward: bool) -> None:
    """Tables, columns, keys, indexes and sequences, in the current schema."""
    tables = _TABLES if forward else tuple((new, old) for old, new in _TABLES)
    for old, new in tables:
        if _table_exists(bind, old):
            bind.exec_driver_sql(f"ALTER TABLE {old} RENAME TO {new}")

    def table_now(name: str) -> str:
        """A table this list names by its new name, as it is called now."""
        return name if forward else dict((n, o) for o, n in _TABLES).get(name, name)

    for table, old, new in _COLUMNS:
        old, new = (old, new) if forward else (new, old)
        if _has_column(bind, table_now(table), old):
            bind.exec_driver_sql(
                f"ALTER TABLE {table_now(table)} RENAME COLUMN {old} TO {new}"
            )
    for table, old, new in _CONSTRAINTS:
        old, new = (old, new) if forward else (new, old)
        if _has_constraint(bind, table_now(table), old):
            bind.exec_driver_sql(
                f"ALTER TABLE {table_now(table)} RENAME CONSTRAINT {old} TO {new}"
            )
    for old, new in _INDEXES:
        old, new = (old, new) if forward else (new, old)
        bind.exec_driver_sql(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
    for old, new in _SEQUENCES:
        old, new = (old, new) if forward else (new, old)
        bind.exec_driver_sql(f"ALTER SEQUENCE IF EXISTS {old} RENAME TO {new}")


def _replace_triggers(bind: Connection, forward: bool) -> None:
    """Re-attach the owner row under the kind's name and drop the triggers a
    start renders (it renders them again).

    Runs while the tables carry their new names: after the upgrade's renames,
    and before the downgrade's."""
    owns_old, owns_new = _OWNS_TRIGGERS if forward else _OWNS_TRIGGERS[::-1]
    kind = "catalog" if forward else "gallery"
    owner = "catalogs"
    had_owns = False
    for _old, table in _TABLES:
        names = bind.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:t) "
                "AND NOT tgisinternal ORDER BY tgname"
            ),
            {"t": table},
        ).scalars()
        for name in list(names):
            had_owns = had_owns or name == owns_old
            bind.exec_driver_sql(f"DROP TRIGGER {name} ON {table}")
    if had_owns:
        bind.exec_driver_sql(
            f"CREATE TRIGGER {owns_new} AFTER INSERT ON {owner} "
            "FOR EACH ROW EXECUTE FUNCTION "
            f"public.fn_install_owns_what_it_creates('{kind}')"
        )


def _drop_checks(bind: Connection, forward: bool) -> dict[tuple[str, str], str]:
    """Drop the CHECKs in this schema that hold one of the names being
    respelled, returning each one's definition."""
    values = {**_flip(_KIND, forward), **_flip(_PERMISSIONS, forward)}
    pattern = "|".join(f"'{re.escape(old)}'::" for old in values)
    rows = bind.execute(
        text(
            "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE contype = 'c' "
            "AND connamespace = current_schema()::regnamespace "
            "AND pg_get_constraintdef(oid) ~ :pattern"
        ),
        {"pattern": pattern},
    ).all()
    dropped: dict[tuple[str, str], str] = {}
    for table, name, definition in rows:
        bind.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        dropped[(table, name)] = definition
    return dropped


def _restore_checks(
    bind: Connection, dropped: dict[tuple[str, str], str], forward: bool
) -> None:
    """Put each CHECK back with the values it holds respelled."""
    values = {**_flip(_KIND, forward), **_flip(_PERMISSIONS, forward)}
    for (table, name), definition in dropped.items():
        for old, new in values.items():
            definition = definition.replace(f"'{old}'::", f"'{new}'::")
        bind.exec_driver_sql(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")


# --- stored values -----------------------------------------------------------


def _writable(bind: Connection, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with ``table``'s row security unforced and its user triggers
    held, then restore both. A failure rolls the whole revision back, so
    nothing is restored on that path: a statement there would only replace
    the error with "current transaction is aborted"."""
    if not _table_exists(bind, table):
        return
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
    fn()
    bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _set_values(
    bind: Connection, table: str, columns: tuple[str, ...], mapping: Mapping[str, str]
) -> None:
    def run() -> None:
        for column in columns:
            if not _has_column(bind, table, column):
                continue
            for old, new in mapping.items():
                bind.execute(
                    text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
                    {"old": old, "new": new},
                )

    _writable(bind, table, run)


def _replace_in(
    bind: Connection, table: str, column: str, mapping: Mapping[str, str]
) -> None:
    """Replace each substring in a text column."""

    def run() -> None:
        for old, new in mapping.items():
            bind.execute(
                text(
                    f"UPDATE {table} SET {column} = replace({column}, :old, :new) "
                    f"WHERE strpos({column}, :old) > 0"
                ),
                {"old": old, "new": new},
            )

    _writable(bind, table, run)


def _map_array(
    bind: Connection,
    table: str,
    column: str,
    mapping: Mapping[str, str],
    *,
    prefix: bool = False,
    where: str = "TRUE",
) -> None:
    """Respell each element of a text array: a whole element, or with
    ``prefix`` its leading part (``galleries.`` in ``galleries.updated``)."""
    if prefix:
        match = "starts_with(CAST(v AS text), m.key)"
        element = "m.value || substr(CAST(v AS text), length(m.key) + 1)"
    else:
        match = "CAST(v AS text) = m.key"
        element = "m.value"
    pairs = "jsonb_each_text(CAST(:pairs AS jsonb)) m"

    def run() -> None:
        bind.execute(
            text(
                f"UPDATE {table} SET {column} = ARRAY("
                f"SELECT coalesce((SELECT {element} FROM {pairs} WHERE {match} "
                "LIMIT 1), CAST(v AS text)) "
                f"FROM unnest({column}) WITH ORDINALITY AS u(v, i) ORDER BY i) "
                f"WHERE ({where}) AND EXISTS (SELECT 1 FROM unnest({column}) v, "
                f"{pairs} WHERE {match})"
            ),
            {"pairs": json.dumps(mapping)},
        )

    _writable(bind, table, run)


def _respell_json(
    bind: Connection, table: str, column: str, respell: Callable[[Any], Any]
) -> None:
    def run() -> None:
        rows = bind.execute(
            text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
        ).all()
        for row_id, value in rows:
            if isinstance(value, str):
                value = json.loads(value)
            respelled = respell(value)
            if respelled != value:
                bind.execute(
                    text(
                        f"UPDATE {table} SET {column} = CAST(:v AS jsonb) WHERE id = :id"
                    ),
                    {"v": json.dumps(respelled), "id": row_id},
                )

    _writable(bind, table, run)


#: What a statement quotes. A string value (single- or dollar-quoted) is left
#: as written, and so is a double-quoted name right after ``AS`` — a column
#: name the statement answers with is its author's. Any other quoted name is a
#: reference, respelled as a bare one is.
_QUOTED = re.compile(r"'(?:[^']|'')*'|\$(\w*)\$.*?\$\1\$|\"((?:[^\"]|\"\")*)\"", re.S)
_ALIAS = re.compile(r"\bAS\s*$", re.I)


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


def _definition_respeller(forward: bool) -> Callable[[Any], Any]:
    """A dashboard's or an install's definition: its scopes, its statements,
    and the kinds it names."""
    scopes = _flip(_SCOPES, forward)
    words = _flip(_DATASET_WORDS, forward)
    kinds = _flip(_KIND, forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if isinstance(value, str):
            return scopes.get(value, value)
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "sql" and isinstance(item, str):
                out[key] = _statement(item, words)
            elif key in _KIND_KEYS and isinstance(item, str):
                out[key] = kinds.get(item, item)
            elif key in _KIND_KEYS and isinstance(item, list):
                out[key] = [
                    kinds.get(one, one) if isinstance(one, str) else respell(one)
                    for one in item
                ]
            else:
                out[scopes.get(key, key)] = respell(item)
        return out

    return respell


def _job_respeller(forward: bool) -> Callable[[Any], Any]:
    """A queued job's parameters: the tool keys its maps and ids use, and an
    envelope type."""
    keys = _flip(_JOB_KEYS, forward)
    types = _flip(_ENVELOPE_TYPES, forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if isinstance(value, str):
            return types.get(value, value)
        if isinstance(value, dict):
            return {keys.get(key, key): respell(item) for key, item in value.items()}
        return value

    return respell


def _parents(bind: Connection, mapping: Mapping[str, str]) -> None:
    """The change log's parents: ``[{"id": 2, "type": "galleries"}]``."""

    def run() -> None:
        bind.execute(
            text(
                "UPDATE event_outbox SET parents = (SELECT jsonb_agg(CASE "
                "WHEN CAST(:pairs AS jsonb) ? (p ->> 'type') THEN jsonb_set(p, "
                "'{type}', CAST(:pairs AS jsonb) -> (p ->> 'type')) ELSE p END "
                "ORDER BY i) FROM jsonb_array_elements(parents) WITH ORDINALITY "
                "AS e(p, i)) WHERE jsonb_typeof(parents) = 'array' AND EXISTS ("
                "SELECT 1 FROM jsonb_array_elements(parents) p "
                "WHERE CAST(:pairs AS jsonb) ? (p ->> 'type'))"
            ),
            {"pairs": json.dumps(mapping)},
        )

    _writable(bind, "event_outbox", run)


def _respell_values(bind: Connection, forward: bool) -> None:
    kind = _flip(_KIND, forward)
    resource = _flip(_RESOURCE, forward)
    fields = _flip(_FIELDS, forward)
    catalogs = "catalogs" if forward else "galleries"

    _set_values(bind, "resource_grants", ("resource_type",), kind)
    _set_values(bind, "guest_invite_grants", ("resource_type",), kind)
    _set_values(bind, "property_values", ("entity_type",), kind)
    _set_values(bind, "plugin_metadata", ("entity_type",), kind)
    _set_values(bind, "personal_items", ("entity_type",), kind)
    _set_values(bind, "engagement_levels", ("entity_type",), kind)
    _set_values(bind, "relationships", ("source_type", "target_type"), kind)
    _set_values(bind, "search_entries", ("entity_type", "dac_tool"), kind)
    _set_values(bind, "reactions", ("target_type",), kind)
    _set_values(bind, "reaction_digest_items", ("target_type",), kind)
    _replace_in(
        bind, "reaction_digest_items", "target_path", _flip(_ADDRESSES, forward)
    )
    _set_values(bind, "content_holds", ("target_type",), kind)
    _set_values(bind, "moderation_reports", ("target_type",), kind)
    _set_values(bind, "moderation_actions", ("target_type",), kind)
    _set_values(bind, "tool_layouts", ("tool", "kind"), kind)
    _set_values(
        bind,
        "initiative_role_permissions",
        ("permission_key",),
        _flip(_PERMISSIONS, forward),
    )

    _set_values(bind, "event_outbox", ("resource_type",), resource)
    _set_values(bind, "event_outbox", ("dac_tool",), kind)
    _parents(bind, resource)
    _map_array(bind, "event_outbox", "changed", fields)
    _map_array(
        bind,
        "event_outbox",
        "changed",
        _flip(_FACET, forward),
        where=f"resource_type = '{catalogs}'",
    )
    _map_array(
        bind,
        "webhook_subscriptions",
        "event_types",
        {f"{old}.": f"{new}." for old, new in resource.items()},
        prefix=True,
    )
    _map_array(bind, "webhook_subscriptions", "fields", fields)

    _map_array(bind, "guild_plugins", "granted_scopes", _flip(_SCOPES, forward))
    definitions = _definition_respeller(forward)
    _respell_json(bind, "guild_plugins", "definition", definitions)
    _respell_json(bind, "dashboards", "definition", definitions)

    jobs = _job_respeller(forward)
    _set_values(bind, "export_jobs", ("source",), kind)
    _respell_json(bind, "export_jobs", "params", jobs)
    _set_values(bind, "import_jobs", ("source",), _flip(_ENVELOPE_TYPES, forward))
    _respell_json(bind, "import_jobs", "params", jobs)


# --- entry points ------------------------------------------------------------


def _apply(forward: bool) -> None:
    bind = op.get_bind()
    checks = _drop_checks(bind, forward)
    if forward:
        _rename_structure(bind, forward)
        _replace_triggers(bind, forward)
    else:
        _replace_triggers(bind, forward)
        _rename_structure(bind, forward)
    _respell_values(bind, forward)
    _restore_checks(bind, checks, forward)
    bind.exec_driver_sql(_CLEAR_SEARCH_GENERATION)


def _convert(
    bind: Connection,
    forward: bool,
    each_schema: Callable[[Callable[[], None]], None],
) -> None:
    """Run ``_apply`` through ``each_schema`` with the kind code reading both
    spellings, then leave it reading only the one the rows now say."""
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_EITHER))
    each_schema(lambda: _apply(forward))
    bind.exec_driver_sql(
        _kind_code_fn(_KIND_CODES_AFTER if forward else _KIND_CODES_BEFORE)
    )


def upgrade() -> None:
    bind = op.get_bind()
    _convert(bind, True, lambda apply: run_for_each_guild_schema(bind, apply))


def downgrade() -> None:
    bind = op.get_bind()
    _convert(bind, False, lambda apply: run_for_each_guild_schema(bind, apply))
