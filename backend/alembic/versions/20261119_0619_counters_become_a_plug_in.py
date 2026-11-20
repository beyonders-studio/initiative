"""counters become a plug-in

Counters stops being a built-in tool and becomes the Counters tool plug-in
(``TSJVTCM0S7GV2X``), whose kinds are ``counter_group.tsjvtcm0s7gv2x`` and
``counter.tsjvtcm0s7gv2x`` and whose tables are ``p_tsjvtcm0s7gv2x_counter_group``
and ``p_tsjvtcm0s7gv2x_counter``.

In ``public``:

* ``plugin_kind_codes`` gives the plug-in's kinds the built-in kinds' codes, 4
  and 3, so every stored node id keeps naming the same row. Its CHECK admits
  those two below the plug-in range. ``relationship_kind_code`` gains their
  arms here, before any edge is rewritten; a start renders it again from the
  registry and the table.
* ``counter_view_mode`` goes once no schema uses it.
* A marketplace listing of a counter group, a template of one, is deleted
  with its versions: its kind is gone, and no tool plug-in listing takes its
  shape. A community's groups made from one keep their rows.

In each community where a counter group exists (live, trashed or archived) or
Counters is switched on in an initiative:

* The plug-in is installed: its ``guild_plugins`` row, pinned to the version
  frozen beside this revision, and its row in ``public.plugin_installs``. It
  is placed in each initiative where Counters is on today. Each initiative's
  switch and each role's two keys are kept, renamed to the plug-in's keys; an
  initiative or role with no row gets the built-in tool's answer written, so
  nothing moves to the plug-in's defaults.
* ``counter_groups`` and ``counters`` become the plug-in's tables by name, and
  their sequences, keys, CHECKs and indexes take the names the plug-in's
  tables are built with. ``view_mode`` becomes text, ``progress_bar`` reading
  ``bar`` and ``segmented_clock`` reading ``clock``, and ``color`` text. Their
  policies, triggers and grants are dropped; a start renders the plug-in's.
  The columns the plug-in's tables have and these do not are added by that
  render too.
* Every row naming a counter kind takes the plug-in's: each ``<x>_type``
  column with an ``<x>_id`` beside it, each ``tool`` column, in the schema and
  in the ``public`` tables that name a community. A dashboard's
  query that reads ``counters`` or ``counter_groups`` reads the plug-in's
  tables. A counter's page someone laid out is kept as the plug-in's
  counter's.

Elsewhere, and in ``guild_template``, the rules and rows naming a counter kind
are deleted and the two tables dropped.

Every write runs with the table's row security unforced and its user
triggers held, both restored in the same transaction. The CHECKs that list
the kinds are dropped first; a start renders them for the community's tools.

The downgrade turns an install of the plug-in back into the built-in tool in
each community, and gives every other community the empty built-in tables.

Revision ID: 20261119_0619
Revises: 20261119_0618
Create Date: 2026-11-19
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema, split_sql_statements

revision = "20261119_0619"
down_revision = "20261119_0618"
branch_labels = None
depends_on = None

UID = "TSJVTCM0S7GV2X"
#: The version installed, as the plug-in's listing published it.
_FROZEN = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))

#: Each built-in kind, the plug-in's kind it becomes, and its code.
KINDS = {
    "counter_group": ("counter_group.tsjvtcm0s7gv2x", 4),
    "counter": ("counter.tsjvtcm0s7gv2x", 3),
}
#: Each built-in table and the plug-in's table it becomes.
TABLES = {
    "counter_groups": "p_tsjvtcm0s7gv2x_counter_group",
    "counters": "p_tsjvtcm0s7gv2x_counter",
}
_GROUP_KIND = KINDS["counter_group"][0]

#: Each rule key and the plug-in's key it becomes: the switch, the role keys,
#: and the community's own over them.
RULE_KEYS = {
    "counter_groups_enabled": f"{_GROUP_KIND}:enabled",
    "create_counter_groups": f"{_GROUP_KIND}:create",
    "initiative_tool.counter_group": f"initiative_tool.{_GROUP_KIND}",
    "initiative_role.member.counter_groups_enabled": (
        f"initiative_role.member.{_GROUP_KIND}:enabled"
    ),
    "initiative_role.member.create_counter_groups": (
        f"initiative_role.member.{_GROUP_KIND}:create"
    ),
}
#: The built-in roles that held every key, and so both counter keys.
_MANAGER_ROLES = ("moderator", "project_manager")

VIEW_MODES = {"progress_bar": "bar", "segmented_clock": "clock"}

#: Every ``<x>_type`` column with an ``<x>_id`` beside it, and every ``tool``
#: column: the columns naming a kind, in ``:schema``.
_KIND_COLUMNS = """
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = :schema AND t.table_type = 'BASE TABLE'
      AND c.data_type IN ('text', 'character varying')
      AND (c.column_name ~ '(^|_)tool$'
        OR (c.column_name ~ '_type$' AND EXISTS (
          SELECT 1 FROM information_schema.columns d
          WHERE d.table_schema = c.table_schema AND d.table_name = c.table_name
            AND d.column_name = regexp_replace(c.column_name, '_type$', '_id'))))
      AND (:schema <> 'public' OR EXISTS (
          SELECT 1 FROM information_schema.columns g
          WHERE g.table_schema = 'public' AND g.table_name = c.table_name
            AND g.column_name = 'guild_id'))
    ORDER BY 1, 2
"""


def _bind() -> sa.engine.Connection:
    return op.get_bind()


def _scalar(sql: str, **params: Any) -> Any:
    return _bind().execute(sa.text(sql), params).scalar()


def _rows(sql: str, **params: Any) -> list[tuple]:
    return [tuple(row) for row in _bind().execute(sa.text(sql), params).all()]


def _run(*statements: str) -> None:
    for statement in statements:
        _bind().exec_driver_sql(statement)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _case(column: str, mapping: Mapping[str, str]) -> str:
    arms = " ".join(
        f"WHEN {_literal(a)} THEN {_literal(b)}" for a, b in mapping.items()
    )
    return f"CASE {column} {arms} ELSE {column} END"


def _listed(values: Any) -> str:
    return ", ".join(_literal(value) for value in values)


def _exists(table: str) -> bool:
    return bool(_scalar("SELECT to_regclass(:t) IS NOT NULL", t=table))


@contextmanager
def _held(*tables: str) -> Iterator[None]:
    """``tables`` (those that exist) with their row security unforced and
    their user triggers held, so the statements inside read and write every
    row; each is restored after."""
    present = [t for t in dict.fromkeys(tables) if _exists(t)]
    forced = [
        t
        for t in present
        if _scalar(
            "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)",
            t=t,
        )
    ]
    for table in forced:
        _run(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in present:
        _run(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        yield
    finally:
        for table in present:
            _run(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        for table in forced:
            _run(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _kind_columns(schema: str) -> list[tuple[str, str]]:
    return _rows(_KIND_COLUMNS, schema=schema)


def _drop_kind_checks(names: Any) -> None:
    """Drop the CHECKs in this schema that list a kind or key of ``names``,
    on tables other than the tool's: a start renders them for the
    community's tools."""
    pattern = "|".join(names)
    for table, name in _rows(
        "SELECT c.conrelid::regclass::text, c.conname FROM pg_constraint c"
        " WHERE c.connamespace = current_schema()::regnamespace AND c.contype = 'c'"
        " AND pg_get_constraintdef(c.oid) ~ :pattern"
        " AND c.conrelid::regclass::text <> ALL (:tools)",
        pattern=pattern,
        tools=[*TABLES, *TABLES.values()],
    ):
        _run(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {_q(name)}")


def _with_arms(body: str, arms: Mapping[str, int]) -> str:
    """``relationship_kind_code``'s body with an arm for each of ``arms`` it
    lacks."""
    missing = "".join(
        f"WHEN {_literal(kind)} THEN {code} "
        for kind, code in arms.items()
        if f"WHEN {_literal(kind)} THEN" not in body
    )
    head, end = body.rsplit(" END)::bigint", 1)
    return f"{head} {missing.strip()} END)::bigint{end}" if missing else body


def _add_kind_code_arms(arms: Mapping[str, int]) -> None:
    body = _scalar(
        "SELECT prosrc FROM pg_proc"
        " WHERE oid = to_regprocedure('public.relationship_kind_code(text)')"
    )
    _run(
        "CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)\n"
        " RETURNS bigint\n LANGUAGE sql\n IMMUTABLE STRICT\n"
        f"AS $function${_with_arms(body, arms)}$function$"
    )


#: The views that read one of ``:tables``, and the views reading those, in
#: the order they can be dropped.
_DEPENDENT_VIEWS = """
    WITH RECURSIVE reads(oid, depth) AS (
        SELECT DISTINCT r.ev_class, 1
        FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid
        WHERE d.classid = 'pg_rewrite'::regclass
          AND d.refobjid = ANY (CAST(:tables AS regclass[]))
          AND r.ev_class <> d.refobjid
        UNION
        SELECT r.ev_class, reads.depth + 1
        FROM reads JOIN pg_depend d ON d.refobjid = reads.oid
        JOIN pg_rewrite r ON r.oid = d.objid
        WHERE d.classid = 'pg_rewrite'::regclass AND r.ev_class <> reads.oid
    )
    SELECT oid::regclass::text FROM reads GROUP BY oid ORDER BY max(depth) DESC
"""

#: The policies that read one of ``:relations``.
_DEPENDENT_POLICIES = """
    SELECT DISTINCT p.polname, p.polrelid::regclass::text
    FROM pg_depend d JOIN pg_policy p ON p.oid = d.objid
    WHERE d.classid = 'pg_policy'::regclass
      AND d.refobjid = ANY (CAST(:relations AS regclass[]))
"""


def _drop_dependents(tables: list[str]) -> None:
    """Drop what a start rendered that reads ``tables``: the views over them
    and the policies on other tables reading those, so the tables can be
    renamed, retyped and dropped. The schema's stamp is cleared, so the next
    start renders all of it again from the registry."""
    views = [view for (view,) in _rows(_DEPENDENT_VIEWS, tables=tables)]
    relations = [*tables, *views]
    for name, table in _rows(_DEPENDENT_POLICIES, relations=relations):
        _run(f"DROP POLICY {_q(name)} ON {table}")
    for view in views:
        _run(f"DROP VIEW {view}")
    schema = _scalar("SELECT current_schema()")
    if schema != "guild_template":
        _run(f"COMMENT ON SCHEMA {_q(schema)} IS NULL")


# --- upgrade -----------------------------------------------------------------


def upgrade() -> None:
    adopted = {kind: code for kind, code in KINDS.values()}
    with _held("public.plugin_kind_codes"):
        _run(
            "ALTER TABLE public.plugin_kind_codes"
            " DROP CONSTRAINT ck_plugin_kind_codes_code",
            "ALTER TABLE public.plugin_kind_codes ADD CONSTRAINT"
            " ck_plugin_kind_codes_code CHECK (code >= 1024 OR (kind, code) IN ("
            + ", ".join(f"({_literal(k)}, {c})" for k, c in adopted.items())
            + "))",
        )
        for kind, code in adopted.items():
            # A kind already given a code from the plug-in range takes the
            # built-in kind's instead; the edges naming it are rewritten below.
            _bind().execute(
                sa.text(
                    "INSERT INTO public.plugin_kind_codes (kind, code)"
                    " VALUES (:k, :c) ON CONFLICT (kind) DO UPDATE SET code = :c"
                ),
                {"k": kind, "c": code},
            )
    _add_kind_code_arms(adopted)
    # A listed counter group (a template of one) names a kind no listing has
    # any more, and no tool plug-in's listing takes its shape: it is retired.
    with _held("public.marketplace_listings"):
        _run("DELETE FROM public.marketplace_listings WHERE kind = 'counter_group'")
    converted: list[int] = []
    run_for_each_guild_schema(_bind(), lambda: _upgrade_schema(converted))
    if converted:
        _rewrite_public(converted, {old: new for old, (new, _) in KINDS.items()})
    _run("DROP TYPE IF EXISTS public.counter_view_mode")


def _upgrade_schema(converted: list[int]) -> None:
    schema = _scalar("SELECT current_schema()")
    guild_id = (
        None if schema == "guild_template" else int(schema.removeprefix("guild_"))
    )
    if not _exists("counter_groups"):
        return
    _drop_dependents(list(TABLES))
    with _held("counter_groups", "initiatives", "initiative_rules", "guild_plugins"):
        on_in = [
            row[0]
            for row in _rows(
                "SELECT i.id FROM initiatives i WHERE COALESCE("
                " (SELECT cd.enabled FROM initiative_rules cd"
                "  WHERE cd.initiative_id IS NULL AND cd.initiative_role_id IS NULL"
                "    AND cd.install_id IS NULL"
                "    AND cd.key = 'initiative_tool.counter_group'),"
                " (SELECT sw.enabled FROM initiative_rules sw"
                "  WHERE sw.initiative_id = i.id AND sw.initiative_role_id IS NULL"
                "    AND sw.install_id IS NULL AND sw.key = 'counter_groups_enabled'),"
                " false) ORDER BY i.id"
            )
        ]
        in_use = guild_id is not None and (
            bool(on_in) or bool(_scalar("SELECT EXISTS (SELECT 1 FROM counter_groups)"))
        )
        installed = bool(
            _scalar(
                "SELECT EXISTS (SELECT 1 FROM guild_plugins WHERE listing_uid = :u)",
                u=UID,
            )
        )
    if in_use and installed:
        raise RuntimeError(
            f"{schema} has the Counters plug-in installed beside built-in counters;"
            " uninstall the plug-in there before upgrading"
        )

    kind_columns = _kind_columns(schema)
    kind_tables = [table for table, _ in kind_columns]
    if in_use:
        _drop_kind_checks(["counter_group"])
    with _held(
        "initiative_rules",
        "initiative_roles",
        "tool_layouts",
        "dashboards",
        *kind_tables,
    ):
        if in_use:
            _keep_rules()
            # A counter's page someone laid out is the plug-in's counter's;
            # its target, the group, follows with the kind columns below.
            _run(
                "ALTER TABLE tool_layouts DROP CONSTRAINT IF EXISTS ck_tool_layouts_kind",
                f"UPDATE tool_layouts SET kind = {_literal(KINDS['counter'][0])}"
                " WHERE tool = 'counter_group' AND kind = 'counter'",
            )
            for table, column in kind_columns:
                mapping = {old: new for old, (new, _) in KINDS.items()}
                _run(
                    f"UPDATE {_q(table)} SET {_q(column)} = {_case(_q(column), mapping)}"
                    f" WHERE {_q(column)} IN ({_listed(mapping)})"
                )
            _rewrite_queries(TABLES)
        else:
            _run(f"DELETE FROM initiative_rules WHERE key IN ({_listed(RULE_KEYS)})")
            for table, column in kind_columns:
                _run(
                    f"DELETE FROM {_q(table)} WHERE {_q(column)} IN ({_listed(KINDS)})"
                )
        # An edge naming a plug-in kind is written again, so its node ids read
        # the code its kind has now.
        plugin_kinds = _listed(new for new, _ in KINDS.values())
        _run(
            "UPDATE relationships SET source_type = source_type"
            f" WHERE source_type IN ({plugin_kinds}) OR target_type IN ({plugin_kinds})"
        )
    if not in_use:
        _run("DROP TABLE counters", "DROP TABLE counter_groups")
        return

    # Installed in the name of the community's seat, or else its longest
    # standing admin, or else whoever made it: an install is a member's.
    with _held("public.guild_memberships", "public.guilds"):
        installer = _scalar(
            "SELECT COALESCE((SELECT m.user_id FROM public.guild_memberships m"
            " WHERE m.guild_id = :g AND m.role::text IN ('superadmin', 'admin')"
            " ORDER BY m.role::text = 'superadmin' DESC, m.joined_at, m.user_id"
            " LIMIT 1), (SELECT created_by FROM public.guilds WHERE id = :g))",
            g=guild_id,
        )
    with _held("guild_plugins", "plugin_placements"):
        install_id = _scalar(
            "INSERT INTO guild_plugins (listing_uid, listing_version, plugin_kind,"
            " name, definition, created_by, created_by_kind, created_at, updated_at)"
            " VALUES (:uid, :version, 'tool', :name, CAST(:definition AS jsonb),"
            " :installer, 'member', now(), now()) RETURNING id",
            installer=installer,
            uid=UID,
            version=_FROZEN["version"],
            name=_FROZEN["definition"]["default_name"],
            definition=json.dumps(_FROZEN["definition"]),
        )
        for initiative_id in on_in:
            _bind().execute(
                sa.text(
                    "INSERT INTO plugin_placements"
                    " (install_id, initiative_id, created_at, updated_at)"
                    " VALUES (:p, :i, now(), now())"
                ),
                {"p": install_id, "i": initiative_id},
            )
    with _held("public.plugin_installs"):
        _bind().execute(
            sa.text(
                "INSERT INTO public.plugin_installs"
                " (guild_id, install_id, listing_uid, enabled)"
                " VALUES (:g, :p, :uid, true) ON CONFLICT DO NOTHING"
            ),
            {"g": guild_id, "p": install_id, "uid": UID},
        )
    _adopt_tables()
    converted.append(guild_id)


def _keep_rules() -> None:
    """Write the built-in tool's answer where an initiative or role has no
    row for a counter key, then rename every counter key to the plug-in's."""
    _run(
        # Each initiative's switch: off where it had none.
        "INSERT INTO initiative_rules (initiative_id, initiative_role_id, key, enabled)"
        " SELECT i.id, NULL, 'counter_groups_enabled', false FROM initiatives i"
        " ON CONFLICT ON CONSTRAINT uq_initiative_rules_subject DO NOTHING",
        # Each role's two keys: on for a built-in manager role, off otherwise.
        "INSERT INTO initiative_rules (initiative_id, initiative_role_id, key, enabled)"
        " SELECT r.initiative_id, r.id, k.key,"
        f" r.is_builtin AND r.name IN ({_listed(_MANAGER_ROLES)})"
        " FROM initiative_roles r"
        " CROSS JOIN (VALUES ('counter_groups_enabled'), ('create_counter_groups'))"
        " AS k(key)"
        " ON CONFLICT ON CONSTRAINT uq_initiative_rules_subject DO NOTHING",
        f"UPDATE initiative_rules SET key = {_case('key', RULE_KEYS)}"
        f" WHERE install_id IS NULL AND key IN ({_listed(RULE_KEYS)})",
    )


def _rewrite_sql(sql: str, mapping: Mapping[str, str]) -> str | None:
    """``sql`` reading ``mapping``'s tables by their new names, or None where it
    names none of them (or cannot be read). A table read by its bare name
    keeps that name as its alias, so whatever names it, a column or a
    subquery, still does; a name the query gives a ``WITH`` of its own is
    that, and is left as it is."""
    from pglast import ast, parse_sql
    from pglast.stream import RawStream
    from pglast.visitors import Visitor

    try:
        tree = parse_sql(sql)
    except Exception:
        return None
    named: set[str] = set()
    changed = False

    class Named(Visitor):
        def visit_CommonTableExpr(
            self, ancestors: Any, node: ast.CommonTableExpr
        ) -> None:
            named.add(node.ctename)

    class Rename(Visitor):
        def visit_RangeVar(self, ancestors: Any, node: ast.RangeVar) -> Any:
            nonlocal changed
            if (
                node.schemaname is None
                and node.relname in mapping
                and node.relname not in named
            ):
                changed = True
                return ast.RangeVar(
                    relname=mapping[node.relname],
                    inh=node.inh,
                    relpersistence=node.relpersistence,
                    alias=node.alias or ast.Alias(aliasname=node.relname),
                )
            return None

    Named()(tree)
    Rename()(tree)
    return RawStream()(tree) if changed else None


def _rewrite_queries(mapping: Mapping[str, str]) -> None:
    """Each dashboard query reading a table of ``mapping`` reads its new
    name."""
    for dashboard_id, definition in _rows(
        "SELECT id, definition FROM dashboards WHERE definition::text ~ :names",
        names="|".join(mapping),
    ):
        changed = False
        for widget in (definition or {}).get("widgets") or []:
            binding = widget.get("binding") if isinstance(widget, dict) else None
            if not isinstance(binding, dict) or not isinstance(binding.get("sql"), str):
                continue
            if (new := _rewrite_sql(binding["sql"], mapping)) is not None:
                binding["sql"] = new
                changed = True
        if changed:
            _bind().execute(
                sa.text(
                    "UPDATE dashboards SET definition = CAST(:d AS jsonb) WHERE id = :i"
                ),
                {"d": json.dumps(definition), "i": dashboard_id},
            )


def _rename_objects(old: str, new: str) -> None:
    """``old``'s table, sequence, keys, CHECKs and indexes, named as ``new``'s
    are built."""
    _run(f"ALTER TABLE {old} RENAME TO {new}")
    named = _rows(
        "SELECT 'CONSTRAINT', conname FROM pg_constraint WHERE conrelid = to_regclass(:t)"
        " UNION ALL SELECT 'INDEX', c.relname FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indexrelid"
        " WHERE i.indrelid = to_regclass(:t) AND NOT EXISTS ("
        "  SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid)"
        " UNION ALL SELECT 'SEQUENCE', s.relname FROM pg_depend d"
        " JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'"
        " WHERE d.refobjid = to_regclass(:t) AND d.deptype IN ('a', 'i')",
        t=new,
    )
    for what, name in named:
        if old not in name:
            continue
        renamed = name.replace(old, new, 1)
        if what == "CONSTRAINT":
            _run(f"ALTER TABLE {new} RENAME CONSTRAINT {_q(name)} TO {_q(renamed)}")
        else:
            _run(f"ALTER {what} {_q(name)} RENAME TO {_q(renamed)}")


def _strip(table: str) -> None:
    """Drop ``table``'s policies and user triggers and take back every grant
    on it and its sequence: a start renders what the build has."""
    for (name,) in _rows(
        "SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)", t=table
    ):
        _run(f"DROP POLICY {_q(name)} ON {table}")
    for (name,) in _rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:t) AND NOT tgisinternal",
        t=table,
    ):
        _run(f"DROP TRIGGER {_q(name)} ON {table}")
    for relation in (table, f"{table}_id_seq"):
        for (grantee,) in _rows(
            "SELECT DISTINCT a.grantee::regrole::text FROM pg_class c,"
            " aclexplode(c.relacl) a WHERE c.oid = to_regclass(:t)"
            " AND a.grantee <> c.relowner AND a.grantee <> 0",
            t=relation,
        ):
            _run(f"REVOKE ALL ON {relation} FROM {grantee}")
        _run(f"REVOKE ALL ON {relation} FROM PUBLIC")


def _adopt_tables() -> None:
    """The two tables, as the plug-in's: named, typed and stripped of what a
    start renders."""
    groups, counters = TABLES["counter_groups"], TABLES["counters"]
    _run("DROP INDEX IF EXISTS ix_counters_group_position")
    for old, new in TABLES.items():
        _rename_objects(old, new)
        _strip(new)
    with _held(groups, counters):
        _run(
            f"ALTER TABLE {counters}"
            " ALTER COLUMN view_mode DROP DEFAULT,"
            " ALTER COLUMN view_mode TYPE text USING"
            f" {_case('view_mode::text', VIEW_MODES)},"
            " ALTER COLUMN view_mode SET DEFAULT 'number',"
            " ALTER COLUMN color TYPE text",
            *(
                f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now(),"
                " ALTER COLUMN updated_at SET DEFAULT now()"
                for table in (groups, counters)
            ),
        )


def _rewrite_public(guild_ids: list[int], mapping: Mapping[str, str]) -> None:
    """The ``public`` rows of ``guild_ids`` naming a kind of ``mapping``, and
    the notifications whose data names one, naming its new kind."""
    columns = _kind_columns("public")
    keys = ("entity_type", "target_type", "subject_type", "resource_type", "tool")
    with _held(*(f"public.{table}" for table, _ in columns)):
        for table, column in columns:
            _bind().execute(
                sa.text(
                    f"UPDATE public.{_q(table)} SET {_q(column)} = {_case(_q(column), mapping)}"
                    f" WHERE guild_id = ANY(:g) AND {_q(column)} IN ({_listed(mapping)})"
                ),
                {"g": guild_ids},
            )
        _bind().execute(
            sa.text(
                "UPDATE public.notifications n SET data = ("
                " SELECT json_object_agg(e.key, CASE WHEN e.key IN"
                f" ({_listed(keys)}) AND e.value #>> '{{}}' IN ({_listed(mapping)})"
                f" THEN to_json({_case('(e.value #>> ' + _literal('{}') + ')', mapping)})"
                " ELSE e.value END) FROM json_each(n.data) e)"
                " WHERE n.guild_id = ANY(:g) AND json_typeof(n.data) = 'object'"
                " AND EXISTS (SELECT 1 FROM json_each(n.data) e"
                f"  WHERE e.key IN ({_listed(keys)})"
                f"  AND e.value #>> '{{}}' IN ({_listed(mapping)}))"
            ),
            {"g": guild_ids},
        )


# --- downgrade ---------------------------------------------------------------

_BUILTIN_TABLES = """
CREATE TABLE counter_groups (
    id serial PRIMARY KEY,
    initiative_id integer NOT NULL REFERENCES initiatives(id),
    name character varying(255) NOT NULL,
    description text,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32),
    held_at timestamp with time zone,
    hold_id integer,
    comments_locked_at timestamp with time zone,
    created_by_kind character varying(16) NOT NULL,
    deleted_by_kind character varying(16)
);
CREATE TABLE counters (
    id serial PRIMARY KEY,
    counter_group_id integer NOT NULL
        REFERENCES counter_groups(id) ON DELETE CASCADE,
    name character varying(255) NOT NULL,
    color character varying(32),
    count numeric(20,10) DEFAULT 0 NOT NULL,
    min numeric(20,10),
    max numeric(20,10),
    step numeric(20,10) DEFAULT 1 NOT NULL,
    initial_count numeric(20,10) DEFAULT 0 NOT NULL,
    view_mode public.counter_view_mode DEFAULT 'number' NOT NULL,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    created_by integer,
    held_at timestamp with time zone,
    hold_id integer,
    created_by_kind character varying(16) NOT NULL,
    deleted_by_kind character varying(16)
);
"""

_ACTORS = "('member', 'plugin', 'system')"


def _builtin_rules(table: str, *, tool: bool) -> list[str]:
    """What the built-in tables carry from their migrations beside their
    columns."""
    rules = [
        f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_created_by"
        " CHECK ((created_by_kind = 'system') = (created_by IS NULL))",
        f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_created_by_kind"
        f" CHECK (created_by_kind IN {_ACTORS})",
        f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_deleted_by CHECK (CASE"
        " WHEN deleted_at IS NULL THEN deleted_by IS NULL AND deleted_by_kind IS NULL"
        " ELSE deleted_by_kind IS NOT NULL"
        " AND (deleted_by_kind = 'system') = (deleted_by IS NULL) END)",
        f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_deleted_by_kind"
        f" CHECK (deleted_by_kind IN {_ACTORS})",
        f"CREATE INDEX ix_{table}_purge ON {table} (purge_at) WHERE purge_at IS NOT NULL",
        f"CREATE TRIGGER tr_{table}_set_created_by BEFORE INSERT ON {table}"
        " FOR EACH ROW EXECUTE FUNCTION public.fn_set_author()",
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    ]
    if tool:
        rules += [
            f"CREATE INDEX ix_{table}_initiative_id ON {table} (initiative_id)",
            f"CREATE TRIGGER tr_{table}_install_owns AFTER INSERT ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION"
            " public.fn_install_owns_what_it_creates('counter_group')",
        ]
    else:
        rules += [
            f"CREATE INDEX ix_{table}_counter_group_id ON {table} (counter_group_id)",
            f"CREATE INDEX ix_{table}_group_position ON {table}"
            ' (counter_group_id, "position")',
        ]
    return rules


def downgrade() -> None:
    _run(
        "CREATE TYPE public.counter_view_mode AS ENUM"
        " ('number', 'progress_bar', 'segmented_clock')"
    )
    _add_kind_code_arms({old: code for old, (_, code) in KINDS.items()})
    converted: list[int] = []
    run_for_each_guild_schema(_bind(), lambda: _downgrade_schema(converted))
    if converted:
        _rewrite_public(converted, {new: old for old, (new, _) in KINDS.items()})
    with _held("public.plugin_kind_codes"):
        _run(
            "DELETE FROM public.plugin_kind_codes"
            f" WHERE kind IN ({_listed(new for new, _ in KINDS.values())})",
            "ALTER TABLE public.plugin_kind_codes"
            " DROP CONSTRAINT ck_plugin_kind_codes_code",
            "ALTER TABLE public.plugin_kind_codes ADD CONSTRAINT"
            " ck_plugin_kind_codes_code CHECK (code >= 1024)",
        )


def _downgrade_schema(converted: list[int]) -> None:
    schema = _scalar("SELECT current_schema()")
    with _held("guild_plugins"):
        install_id = _scalar(
            "SELECT id FROM guild_plugins WHERE listing_uid = :u", u=UID
        )
    if install_id is None or not _exists(TABLES["counter_groups"]):
        _run(*split_sql_statements(_BUILTIN_TABLES))
        for table in TABLES:
            _run(*_builtin_rules(table, tool=table == "counter_groups"))
        if install_id is None:
            return
    else:
        _drop_dependents(list(TABLES.values()))
        for new in TABLES.values():
            _strip(new)
        for old, new in TABLES.items():
            _drop_plugin_only(new)
            _rename_objects(new, old)
        with _held("counter_groups", "counters"):
            back = {new: old for old, new in VIEW_MODES.items()}
            _run(
                "ALTER TABLE counter_groups DROP COLUMN IF EXISTS position",
                "ALTER TABLE counters DROP COLUMN IF EXISTS archived_at",
                "UPDATE counters SET count = 0 WHERE count IS NULL",
                "ALTER TABLE counters"
                " ALTER COLUMN view_mode DROP DEFAULT,"
                " ALTER COLUMN view_mode TYPE public.counter_view_mode USING"
                f" ({_case('view_mode', back)})::public.counter_view_mode,"
                " ALTER COLUMN view_mode SET DEFAULT 'number',"
                " ALTER COLUMN color TYPE character varying(32),"
                " ALTER COLUMN count SET NOT NULL,"
                " ALTER COLUMN count SET DEFAULT 0",
                *(
                    f"ALTER TABLE {table} ALTER COLUMN created_at DROP DEFAULT,"
                    " ALTER COLUMN updated_at DROP DEFAULT"
                    for table in TABLES
                ),
                "CREATE INDEX ix_counters_group_position"
                ' ON counters (counter_group_id, "position")',
                "CREATE TRIGGER tr_counter_groups_set_created_by BEFORE INSERT"
                " ON counter_groups FOR EACH ROW EXECUTE FUNCTION public.fn_set_author()",
                "CREATE TRIGGER tr_counters_set_created_by BEFORE INSERT"
                " ON counters FOR EACH ROW EXECUTE FUNCTION public.fn_set_author()",
                "CREATE TRIGGER tr_counter_groups_install_owns AFTER INSERT"
                " ON counter_groups FOR EACH ROW EXECUTE FUNCTION"
                " public.fn_install_owns_what_it_creates('counter_group')",
            )

    back_kinds = {new: old for old, (new, _) in KINDS.items()}
    back_keys = {new: old for old, new in RULE_KEYS.items()}
    kind_columns = _kind_columns(schema)
    _drop_kind_checks([kind.replace(".", r"\.") for kind in back_kinds])
    with _held(
        "initiative_rules",
        "plugin_placements",
        "guild_plugins",
        *(table for table, _ in kind_columns),
    ):
        _run(
            f"UPDATE initiative_rules SET key = {_case('key', back_keys)}"
            f" WHERE install_id IS NULL AND key IN ({_listed(back_keys)})"
        )
        _run(
            "ALTER TABLE tool_layouts DROP CONSTRAINT IF EXISTS ck_tool_layouts_kind",
            f"UPDATE tool_layouts SET kind = 'counter'"
            f" WHERE kind = {_literal(KINDS['counter'][0])}",
        )
        for table, column in kind_columns:
            _run(
                f"UPDATE {_q(table)} SET {_q(column)} = {_case(_q(column), back_kinds)}"
                f" WHERE {_q(column)} IN ({_listed(back_kinds)})"
            )
        _bind().execute(
            sa.text("DELETE FROM plugin_placements WHERE install_id = :p"),
            {"p": install_id},
        )
        _bind().execute(
            sa.text("DELETE FROM guild_plugins WHERE id = :p"), {"p": install_id}
        )
        _rewrite_queries({new: old for old, new in TABLES.items()})
    guild_id = int(schema.removeprefix("guild_"))
    with _held("public.plugin_installs"):
        _bind().execute(
            sa.text(
                "DELETE FROM public.plugin_installs WHERE guild_id = :g AND install_id = :p"
            ),
            {"g": guild_id, "p": install_id},
        )
    converted.append(guild_id)


def _drop_plugin_only(table: str) -> None:
    """What the plug-in's table has that the built-in one never did: its
    option and declared CHECKs and the index on its archive stamp."""
    for (name,) in _rows(
        "SELECT conname FROM pg_constraint WHERE conrelid = to_regclass(:t)"
        " AND contype = 'c' AND (conname LIKE '%\\_option' OR conname ~ '_check_[0-9]+$')",
        t=table,
    ):
        _run(f"ALTER TABLE {table} DROP CONSTRAINT {_q(name)}")
