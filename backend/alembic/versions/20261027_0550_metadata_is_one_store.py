"""Metadata is one store

Every custom value is one definition with an owner and values in one table.
In ``guild_template`` and every ``guild_<id>``:

* ``property_definitions`` is ``metadata_definitions`` and
  ``property_values`` is ``metadata_values``, with their keys, indexes and the
  creator trigger named to match.
* A definition gains its owners beside ``collection_id``: ``project_id``, keyed
  with its ``initiative_id`` to the project (``projects`` gains the unique
  ``(id, initiative_id)`` that key names) and gone with it, and
  ``install_id``, an installed plug-in's, gone when it is uninstalled. At most
  one is set (a CHECK). A plug-in's names its metadata ``key``, unique per
  install, belongs to no initiative (``initiative_id`` may be null, exactly
  for a plug-in's), and says whether it is a ``list`` field and the item
  kinds it is ``shown_on``. ``link``, ``badge`` and ``json`` are a plug-in's
  types alone (a CHECK). A name is unique among a project's metadata, as among
  a collection's and the initiative's properties.
* A value gains ``ref``, which element of a plug-in's list field it holds
  (``''`` otherwise), in its key, and ``state``, the facets a plug-in's value
  is in.
* An install's pinned definition names a progress bar field ``scale``, as the
  plug-in kit now does, and so does every version of a listing in
  ``public.marketplace_listing_versions``.
* ``plugin_metadata``'s rows move across: a definition per install and key,
  typed from the field the install's pinned version declares for the key,
  ``json`` where it declares none, and each row's value into its typed
  column, with its ``ref`` and ``state``. A value that is not one of its
  type's is left behind. The table is dropped.
* A dashboard's statements read ``metadata_definitions`` and
  ``metadata_values``, as the datasets are named after the tables.
* The triggers and policies a start renders are dropped from the renamed
  tables; the next start renders them again under the new names, before any
  request is served. The CHECK listing a value's kinds takes ``plugin``.

``public.property_type`` is ``public.metadata_type`` and gains ``link``,
``badge`` and ``json``. A database that ran ``20261027_0545`` while it named
the scale ``rating`` has the label renamed.

Revision ID: 20261027_0550
Revises: 20261027_0549
Create Date: 2026-10-27
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261027_0550"
down_revision = "20261027_0549"
branch_labels = None
depends_on = None

#: (old, new) index names on the renamed tables.
_INDEXES = (
    ("ix_property_definitions_initiative_id", "ix_metadata_definitions_initiative_id"),
    ("ix_property_definitions_collection_id", "ix_metadata_definitions_collection_id"),
    (
        "ix_property_definitions_collection_lower_name",
        "ix_metadata_definitions_collection_lower_name",
    ),
    ("ix_property_values_property_id", "ix_metadata_values_property_id"),
    *(
        (f"ix_property_values_value_{column}", f"ix_metadata_values_value_{column}")
        for column in ("text", "number", "date", "datetime", "user_id", "json")
    ),
)
#: (table under its new name, old constraint, new constraint)
_CONSTRAINTS = (
    ("metadata_definitions", "property_definitions_pkey", "metadata_definitions_pkey"),
    (
        "metadata_definitions",
        "property_definitions_initiative_id_fkey",
        "metadata_definitions_initiative_id_fkey",
    ),
    (
        "metadata_definitions",
        "fk_property_definitions_collection",
        "fk_metadata_definitions_collection",
    ),
    (
        "metadata_definitions",
        "ck_property_definitions_currency",
        "ck_metadata_definitions_currency",
    ),
    (
        "metadata_values",
        "property_values_property_id_fkey",
        "metadata_values_property_id_fkey",
    ),
)
_SET_CREATED_BY = (
    "tr_property_definitions_set_created_by",
    "tr_metadata_definitions_set_created_by",
)
_PLUGIN_ONLY = "('badge', 'json', 'link')"
_TONES = frozenset({"accent", "positive", "negative", "warning", "neutral", "muted"})


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("COMMIT")
    renamed = bind.execute(
        text(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'property_type' AND e.enumlabel = 'rating'"
        )
    ).scalar()
    if renamed:
        op.execute("ALTER TYPE public.property_type RENAME VALUE 'rating' TO 'scale'")
    for label in ("scale", "link", "badge", "json"):
        op.execute(f"ALTER TYPE public.property_type ADD VALUE IF NOT EXISTS '{label}'")
    op.execute("BEGIN")
    op.execute("ALTER TYPE public.property_type RENAME TO metadata_type")
    # The listings' versions an install may move to say ``scale`` too.
    with _unforced(bind, "public.marketplace_listing_versions"):
        op.execute(
            _field_kind("public.marketplace_listing_versions", "progress", "scale")
        )
    run_for_each_guild_schema(bind, lambda: _apply(True))


def _apply(forward: bool) -> None:
    """One guild schema's tables one way or the other, with the search path on
    it."""
    bind = op.get_bind()
    if forward:
        _upgrade(bind)
    else:
        _downgrade(bind)


def _upgrade(bind: Connection) -> None:
    _drop_rendered(bind, "property_definitions", keep=_SET_CREATED_BY[0])
    _drop_rendered(bind, "property_values")
    op.execute("ALTER TABLE property_definitions RENAME TO metadata_definitions")
    op.execute("ALTER TABLE property_values RENAME TO metadata_values")
    op.execute(
        "ALTER SEQUENCE IF EXISTS property_definitions_id_seq "
        "RENAME TO metadata_definitions_id_seq"
    )
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
    op.execute(
        f"ALTER TRIGGER {_SET_CREATED_BY[0]} ON metadata_definitions "
        f"RENAME TO {_SET_CREATED_BY[1]}"
    )
    # A value may be on an install, as a plug-in's was.
    kinds = re.findall(
        r"'(\w+)'",
        bind.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = to_regclass('metadata_values') "
                "AND conname = 'ck_property_values_entity_type'"
            )
        ).scalar_one(),
    )
    op.execute(
        "ALTER TABLE metadata_values DROP CONSTRAINT ck_property_values_entity_type"
    )
    listed = ", ".join(f"'{kind}'" for kind in sorted({*kinds, "plugin"}))
    op.execute(
        "ALTER TABLE metadata_values ADD CONSTRAINT ck_metadata_values_entity_type "
        f"CHECK (entity_type IN ({listed}))"
    )

    op.execute(
        "ALTER TABLE projects ADD CONSTRAINT uq_projects_id_initiative "
        "UNIQUE (id, initiative_id)"
    )
    op.execute(
        "ALTER TABLE metadata_definitions ALTER COLUMN initiative_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE metadata_definitions "
        "ADD COLUMN project_id integer, "
        "ADD COLUMN install_id integer "
        "REFERENCES guild_plugins (id) ON DELETE CASCADE, "
        "ADD COLUMN key varchar(64), "
        "ADD COLUMN list boolean NOT NULL DEFAULT false, "
        "ADD COLUMN shown_on varchar(32)[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE metadata_definitions ADD CONSTRAINT "
        "fk_metadata_definitions_project FOREIGN KEY (project_id, initiative_id) "
        "REFERENCES projects (id, initiative_id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE metadata_definitions ADD CONSTRAINT "
        "ck_metadata_definitions_one_owner CHECK "
        "(num_nonnulls(project_id, collection_id, install_id) <= 1)"
    )
    op.execute(
        "ALTER TABLE metadata_definitions ADD CONSTRAINT "
        "ck_metadata_definitions_plugin CHECK "
        "((install_id IS NULL) = (initiative_id IS NOT NULL) "
        "AND (install_id IS NULL) = (key IS NULL))"
    )
    op.execute(
        "ALTER TABLE metadata_definitions ADD CONSTRAINT "
        "ck_metadata_definitions_plugin_types CHECK "
        f"(install_id IS NOT NULL OR type::text NOT IN {_PLUGIN_ONLY})"
    )
    op.execute(
        "CREATE INDEX ix_metadata_definitions_project_id "
        "ON metadata_definitions (project_id)"
    )
    op.execute(
        "CREATE INDEX ix_metadata_definitions_install_id "
        "ON metadata_definitions (install_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_property_definitions_initiative_lower_name")
    op.execute(
        "CREATE UNIQUE INDEX ix_metadata_definitions_initiative_lower_name "
        "ON metadata_definitions (initiative_id, lower((name)::text)) "
        "WHERE project_id IS NULL AND collection_id IS NULL AND install_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_metadata_definitions_project_lower_name "
        "ON metadata_definitions (project_id, lower((name)::text)) "
        "WHERE project_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_metadata_definitions_install_key "
        "ON metadata_definitions (install_id, key) WHERE install_id IS NOT NULL"
    )

    op.execute(
        "ALTER TABLE metadata_values "
        "ADD COLUMN ref varchar(255) NOT NULL DEFAULT '', "
        "ADD COLUMN state jsonb"
    )
    op.execute("ALTER TABLE metadata_values DROP CONSTRAINT property_values_pkey")
    op.execute(
        "ALTER TABLE metadata_values ADD CONSTRAINT metadata_values_pkey "
        "PRIMARY KEY (entity_type, entity_id, property_id, ref)"
    )
    op.execute(
        "CREATE INDEX ix_metadata_values_ref ON metadata_values (property_id, ref) "
        "WHERE ref <> ''"
    )

    _move_plugin_metadata(bind)
    op.execute("DROP TABLE plugin_metadata")
    _respell_dashboards(r"\mproperty_(values|definitions)\M", "metadata_\\1")


def _respell_dashboards(pattern: str, replacement: str) -> None:
    """A dashboard's statements read the datasets by the tables' names. The
    user triggers are held: nothing about the rows changed but their
    spelling."""
    with _unforced(op.get_bind(), "dashboards"):
        op.execute("ALTER TABLE dashboards DISABLE TRIGGER USER")
        op.execute(
            "UPDATE dashboards SET definition = CAST(regexp_replace(CAST(definition "
            f"AS text), '{pattern}', '{replacement}', 'g') AS jsonb) "
            f"WHERE CAST(definition AS text) ~ '{pattern}'"
        )
        op.execute("ALTER TABLE dashboards ENABLE TRIGGER USER")


@contextmanager
def _unforced(bind: Connection, *tables: str) -> Iterator[None]:
    """Row security lifted from ``tables`` for the statements inside, and put
    back as it was: it binds the owner too, and a migration has no standing to
    meet it. A failure rolls the whole revision back, so nothing is restored
    on that path."""
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
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    yield
    for table in forced:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_rendered(bind: Connection, table: str, keep: Optional[str] = None) -> None:
    """Drop the triggers and policies a start renders on ``table``; it renders
    them again under the table's new name."""
    for (name,) in bind.execute(
        text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:t) "
            "AND NOT tgisinternal"
        ),
        {"t": table},
    ).all():
        if name != keep:
            op.execute(f'DROP TRIGGER "{name}" ON {table}')
    for (name,) in bind.execute(
        text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": table},
    ).all():
        op.execute(f'DROP POLICY "{name}" ON {table}')


def _move_plugin_metadata(bind: Connection) -> None:
    """A definition per install and key, and each row's value in its typed
    column, read and written with row security lifted (:func:`_unforced`).
    Each install's pinned fields say ``scale`` for a progress bar first."""
    with _unforced(
        bind,
        "plugin_metadata",
        "guild_plugins",
        "metadata_definitions",
        "metadata_values",
    ):
        op.execute(_field_kind("guild_plugins", "progress", "scale"))
        _move_rows(bind)


def _field_kind(table: str, old: str, new: str) -> str:
    """The statement that names each ``old`` field ``new`` in each ``table``
    row's definition, the fields keeping their order."""
    return (
        f"UPDATE {table} SET definition = jsonb_set(definition, '{{fields}}', "
        f"(SELECT jsonb_agg(CASE WHEN f ->> 'kind' = '{old}' "
        f"THEN jsonb_set(f, '{{kind}}', '\"{new}\"') ELSE f END ORDER BY n) "
        "FROM jsonb_array_elements(definition -> 'fields') "
        "WITH ORDINALITY AS e (f, n))) "
        "WHERE jsonb_typeof(definition -> 'fields') = 'array' "
        f"AND definition -> 'fields' @> '[{{\"kind\": \"{old}\"}}]'"
    )


def _move_rows(bind: Connection) -> None:
    rows = bind.execute(
        text(
            "SELECT pm.install_id, pm.entity_type, pm.entity_id, pm.key, pm.ref, "
            "pm.value, pm.updated_at, gp.definition -> 'fields' "
            "FROM plugin_metadata pm JOIN guild_plugins gp ON gp.id = pm.install_id "
            "ORDER BY pm.install_id, pm.key"
        )
    ).all()
    defined: dict[tuple[int, str], tuple[int, str, bool]] = {}
    for install_id, entity_type, entity_id, key, ref, value, updated, fields in rows:
        if (install_id, key) not in defined:
            field = next(
                (
                    f
                    for f in (fields if isinstance(fields, list) else [])
                    if isinstance(f, dict) and f.get("key") == key
                ),
                None,
            )
            kind = "json" if field is None else str(field.get("kind"))
            listed = field is not None and field.get("list") is True
            shown = sorted(field.get("on") or ()) if field is not None else []
            defined[(install_id, key)] = (
                bind.execute(
                    text(
                        "INSERT INTO metadata_definitions (install_id, key, name, "
                        "type, list, shown_on, position, created_at, updated_at) "
                        "VALUES (:install, :key, :key, CAST(:kind AS metadata_type), "
                        ":list, CAST(:shown AS varchar(32)[]), 0, now(), now()) "
                        "RETURNING id"
                    ),
                    {
                        "install": install_id,
                        "key": key,
                        "kind": kind,
                        "list": listed,
                        "shown": shown,
                    },
                ).scalar_one(),
                kind,
                listed,
            )
        definition_id, kind, listed = defined[(install_id, key)]
        cols = _columns(kind, value, element=bool(ref) and listed)
        if cols is None or bool(ref) != listed:
            continue
        bind.execute(
            text(
                "INSERT INTO metadata_values (entity_type, entity_id, property_id, "
                "ref, value_text, value_number, value_boolean, value_date, "
                "value_datetime, value_json, state, created_at, updated_at) VALUES "
                "(:entity_type, :entity_id, :definition, :ref, :text, :number, "
                ":boolean, :date, :datetime, CAST(:json AS jsonb), "
                "CAST(:state AS jsonb), :updated, :updated)"
            ),
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "definition": definition_id,
                "ref": ref,
                "updated": updated,
                **cols,
            },
        )


def _number(raw: Any) -> Optional[Decimal]:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        number = Decimal(str(raw))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _columns(kind: str, value: Any, *, element: bool) -> Optional[dict[str, Any]]:
    """The columns that keep a plug-in's ``value`` of ``kind``, as the
    metadata service writes them, or ``None`` for a value that is not one of
    the kind's."""
    cols: dict[str, Any] = {
        "text": None,
        "number": None,
        "boolean": None,
        "date": None,
        "datetime": None,
        "json": None,
        "state": None,
    }
    if kind == "json":
        rest = (
            {k: v for k, v in value.items() if k != "ref"}
            if element and isinstance(value, dict)
            else value
        )
        cols["json"] = json.dumps(rest)
        return cols
    figure, whole = value, None
    if isinstance(value, dict):
        rest = {k: v for k, v in value.items() if k != "ref"}
        if isinstance(rest.get("state"), dict):
            cols["state"] = json.dumps(rest.pop("state"))
        if kind in ("link", "badge"):
            figure = rest
        elif set(rest) <= {"value", "max"} and "value" in rest:
            figure, whole = rest["value"], rest.get("max")
        else:
            return None
    if kind in ("link", "badge") and not isinstance(figure, dict):
        return None
    if kind == "link":
        url, words = figure.get("url"), figure.get("text")
        if not isinstance(url, str) or not (words is None or isinstance(words, str)):
            return None
        cols["json"] = json.dumps(
            {k: figure[k] for k in ("url", "text") if k in figure}
        )
        cols["text"] = words or url
    elif kind == "badge":
        words, tone = figure.get("text"), figure.get("tone")
        if not isinstance(words, str) or not (tone is None or tone in _TONES):
            return None
        cols["json"] = json.dumps(
            {k: figure[k] for k in ("text", "tone") if k in figure}
        )
        cols["text"] = words
    elif kind in ("number", "scale"):
        number = _number(figure)
        if number is not None and whole is not None:
            parts = _number(whole)
            number = number / parts * 100 if parts else None
        if number is None or (kind == "scale" and not 0 <= number <= 100):
            return None
        cols["number"] = number
    elif kind == "checkbox":
        if not isinstance(figure, bool):
            return None
        cols["boolean"] = figure
    elif kind in ("date", "datetime", "text"):
        if not isinstance(figure, str):
            return None
        try:
            if kind == "date":
                cols["date"] = date.fromisoformat(figure)
            elif kind == "datetime":
                moment = datetime.fromisoformat(figure.replace("Z", "+00:00"))
                cols["datetime"] = (
                    moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
                )
            else:
                cols["text"] = figure
        except ValueError:
            return None
    else:
        return None
    return cols


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply(False))
    with _unforced(bind, "public.marketplace_listing_versions"):
        op.execute(
            _field_kind("public.marketplace_listing_versions", "scale", "progress")
        )
    op.execute("ALTER TYPE public.metadata_type RENAME TO property_type")


def _downgrade(bind: Connection) -> None:
    _respell_dashboards(r"\mmetadata_(values|definitions)\M", "property_\\1")
    with _unforced(bind, "guild_plugins"):
        op.execute(_field_kind("guild_plugins", "scale", "progress"))
    op.execute(
        "CREATE TABLE plugin_metadata ("
        "install_id integer NOT NULL REFERENCES guild_plugins (id) ON DELETE CASCADE, "
        "entity_type varchar(32) NOT NULL, entity_id integer NOT NULL, "
        "key varchar(64) NOT NULL, ref varchar(255) NOT NULL DEFAULT '', "
        "value jsonb NOT NULL, lookup varchar(255), text_form text, "
        "number_form double precision, shown boolean NOT NULL DEFAULT false, "
        "updated_at timestamptz NOT NULL, "
        "PRIMARY KEY (install_id, entity_type, entity_id, key, ref))"
    )
    op.execute(
        "CREATE INDEX ix_plugin_metadata_lookup ON plugin_metadata "
        "(install_id, key, lookup) WHERE lookup IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_plugin_metadata_entity ON plugin_metadata "
        "(entity_type, entity_id)"
    )
    op.execute("ALTER TABLE plugin_metadata ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plugin_metadata FORCE ROW LEVEL SECURITY")
    _drop_rendered(bind, "metadata_definitions", keep=_SET_CREATED_BY[1])
    _drop_rendered(bind, "metadata_values")
    op.execute("ALTER TABLE metadata_definitions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE metadata_values NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plugin_metadata NO FORCE ROW LEVEL SECURITY")
    # A plug-in's values go back as JSON, each as its typed column holds it.
    op.execute(
        "INSERT INTO plugin_metadata (install_id, entity_type, entity_id, key, ref, "
        "value, shown, updated_at) "
        "SELECT md.install_id, mv.entity_type, mv.entity_id, md.key, mv.ref, "
        "COALESCE(mv.value_json, to_jsonb(mv.value_text), to_jsonb(mv.value_number), "
        "to_jsonb(mv.value_boolean), to_jsonb(mv.value_date), "
        "to_jsonb(mv.value_datetime), 'null'::jsonb), "
        "mv.entity_type = ANY (md.shown_on), mv.updated_at "
        "FROM metadata_values mv JOIN metadata_definitions md "
        "ON md.id = mv.property_id WHERE md.install_id IS NOT NULL"
    )
    op.execute(
        "DELETE FROM metadata_definitions WHERE install_id IS NOT NULL "
        "OR project_id IS NOT NULL"
    )
    op.execute("ALTER TABLE plugin_metadata FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE metadata_values FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE metadata_definitions FORCE ROW LEVEL SECURITY")

    op.execute("DROP INDEX ix_metadata_values_ref")
    op.execute("ALTER TABLE metadata_values DROP CONSTRAINT metadata_values_pkey")
    op.execute("DELETE FROM metadata_values WHERE ref <> ''")
    op.execute(
        "ALTER TABLE metadata_values ADD CONSTRAINT property_values_pkey "
        "PRIMARY KEY (entity_type, entity_id, property_id)"
    )
    op.execute("ALTER TABLE metadata_values DROP COLUMN state, DROP COLUMN ref")
    op.execute("DROP INDEX ix_metadata_definitions_install_key")
    op.execute("DROP INDEX ix_metadata_definitions_project_lower_name")
    op.execute("DROP INDEX ix_metadata_definitions_initiative_lower_name")
    op.execute(
        "CREATE UNIQUE INDEX ix_property_definitions_initiative_lower_name "
        "ON metadata_definitions (initiative_id, lower((name)::text)) "
        "WHERE collection_id IS NULL"
    )
    op.execute("DROP INDEX ix_metadata_definitions_install_id")
    op.execute("DROP INDEX ix_metadata_definitions_project_id")
    for name in (
        "ck_metadata_definitions_plugin_types",
        "ck_metadata_definitions_plugin",
        "ck_metadata_definitions_one_owner",
        "fk_metadata_definitions_project",
    ):
        op.execute(f"ALTER TABLE metadata_definitions DROP CONSTRAINT {name}")
    op.execute(
        "ALTER TABLE metadata_definitions DROP COLUMN shown_on, DROP COLUMN list, "
        "DROP COLUMN key, DROP COLUMN install_id, DROP COLUMN project_id"
    )
    op.execute(
        "ALTER TABLE metadata_definitions ALTER COLUMN initiative_id SET NOT NULL"
    )
    op.execute("ALTER TABLE projects DROP CONSTRAINT uq_projects_id_initiative")
    op.execute(
        "ALTER TABLE metadata_values RENAME CONSTRAINT "
        "ck_metadata_values_entity_type TO ck_property_values_entity_type"
    )
    op.execute(
        f"ALTER TRIGGER {_SET_CREATED_BY[1]} ON metadata_definitions "
        f"RENAME TO {_SET_CREATED_BY[0]}"
    )
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX IF EXISTS {new} RENAME TO {old}")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    op.execute(
        "ALTER SEQUENCE IF EXISTS metadata_definitions_id_seq "
        "RENAME TO property_definitions_id_seq"
    )
    op.execute("ALTER TABLE metadata_values RENAME TO property_values")
    op.execute("ALTER TABLE metadata_definitions RENAME TO property_definitions")
