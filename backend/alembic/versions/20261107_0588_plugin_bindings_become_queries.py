"""rewrite every built-in widget's plug-in binding as a statement

Each built-in widget (a chart, a table, a total) bound to a plug-in's endpoint
through the ``plugin`` source, with a statement over the relation ``rows``,
becomes a ``query`` binding. Its statement reads the endpoint with
``plugin(public id, endpoint, name => value, …)`` under the name ``rows``, with
the parameters the binding held, and the rest of it is kept as written.

The public id is the one the plug-in's registration names: the container's
own, or the registration its listing applied. A binding is rewritten when its
plug-in is installed and its statement reads ``rows`` once; every other one is
left with no statement, which draws the panel asking for one, and is named in
the log. A plug-in's own widget keeps its binding.

Each widget's previous binding is kept under ``legacy``, which the downgrade
restores. Archived and trashed dashboards are rewritten as well.

Revision ID: 20261107_0588
Revises: 20261106_0587
Create Date: 2026-11-07
"""

import hashlib
import json
import logging

from alembic import op
import sqlalchemy as sa
from pglast import ast, parse_sql
from pglast.parser import ParseError, scan
from pglast.stream import RawStream
from pglast.visitors import Visitor

revision = "20261107_0588"
down_revision = "20261106_0587"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: The relation a statement over a plug-in binding's rows reads.
_ROWS = "rows"


def _fingerprint(statement: str | None) -> str:
    """A short stand-in for the statement this revision wrote, which the
    downgrade compares with the widget's statement."""
    return hashlib.sha256((statement or "").encode()).hexdigest()[:16]


def _constant(value) -> ast.Node:
    if isinstance(value, list):
        return ast.A_ArrayExpr(elements=tuple(_constant(entry) for entry in value))
    if isinstance(value, bool):
        return ast.A_Const(val=ast.Boolean(boolval=value))
    if isinstance(value, int):
        return ast.A_Const(val=ast.Integer(ival=value))
    return ast.A_Const(val=ast.String(sval=str(value)))


def _call(public_id: str, name: str, params: dict) -> str:
    """``plugin(public id, name, key => value, …)`` as SQL."""
    template = parse_sql("SELECT FROM plugin()")[0].stmt
    template.fromClause[0].functions[0][0].args = (
        _constant(public_id),
        _constant(name),
        *(
            ast.NamedArgExpr(name=key, arg=_constant(value), argnumber=-1)
            for key, value in sorted(params.items())
        ),
    )
    return RawStream()(template).split(" FROM ", 1)[1]


def _statement(sql: str, call: str) -> str | None:
    """*sql* with its one relation ``rows`` read through *call*, or ``None``
    when it reads ``rows`` other than once."""
    try:
        select = parse_sql(sql)[0].stmt
    except ParseError:
        return None
    found: list[ast.RangeVar] = []

    class Rows(Visitor):
        def visit_RangeVar(self, ancestors, node: ast.RangeVar) -> None:
            if node.relname == _ROWS and not node.schemaname:
                found.append(node)

    Rows()(select)
    if len(found) != 1:
        return None
    relation = found[0]
    token = next(
        (token for token in scan(sql) if token.start == relation.location), None
    )
    if token is None:
        return None
    named = call if relation.alias else f"{call} AS {_ROWS}"
    return f"{sql[: token.start]}{named}{sql[token.end + 1 :]}"


def _rewrite(
    definition: dict, config: dict, public_ids: dict
) -> tuple[dict, dict, int, list[str]]:
    """The definition with every built-in widget's plug-in binding turned into
    a statement, and the config without the entries those bindings spent.
    *public_ids* is each installed listing's public id."""
    changed = 0
    unbound: list[str] = []
    widgets = config.get("widgets")
    per_widget = dict(widgets) if isinstance(widgets, dict) else {}

    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict) or str(widget.get("type") or "").startswith(
            "plugin:"
        ):
            continue
        widget_id = widget.get("id")
        overrides = per_widget.get(widget_id)
        effective = (
            {**binding, **overrides} if isinstance(overrides, dict) else dict(binding)
        )
        if effective.get("source") != "plugin":
            continue
        legacy: dict = {"binding": binding}
        if isinstance(overrides, dict) and overrides:
            legacy["config"] = overrides
        rewritten: dict = {"source": "query", "legacy": legacy}
        public_id = public_ids.get(effective.get("plugin_uid"))
        endpoint_id = str(effective.get("endpoint_id") or "")
        prefix = f"plugin.{public_id}."
        params = effective.get("params")
        statement = (
            _statement(
                str(effective.get("sql") or ""),
                _call(
                    public_id,
                    endpoint_id[len(prefix) :],
                    params if isinstance(params, dict) else {},
                ),
            )
            if public_id and endpoint_id.startswith(prefix)
            else None
        )
        if statement is None:
            unbound.append(str(widget_id))
        else:
            rewritten["sql"] = statement
            legacy["sql"] = _fingerprint(statement)
            changed += 1
        widget["binding"] = rewritten
        per_widget.pop(widget_id, None)

    return definition, {**config, "widgets": per_widget}, changed, unbound


def _schemas(connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%' "
                "AND nspname !~ '_(template|ro|q)$' ORDER BY nspname"
            )
        )
    ]


def upgrade() -> None:
    connection = op.get_bind()
    schemas = _schemas(connection)
    widgets = 0
    left = 0
    connection.execute(
        sa.text(
            "ALTER TABLE public.plugin_service_registrations NO FORCE ROW LEVEL SECURITY"
        )
    )
    try:
        registered = {
            row.listing_uid: row.public_id
            for row in connection.execute(
                sa.text(
                    "SELECT listing_uid, public_id FROM public.plugin_service_registrations "
                    "WHERE listing_uid IS NOT NULL"
                )
            )
        }
        for schema in schemas:
            connection.execute(sa.text(f'SET LOCAL search_path = "{schema}", public'))
            for table in ("dashboards", "guild_plugins"):
                connection.execute(
                    sa.text(
                        f'ALTER TABLE "{schema}".{table} NO FORCE ROW LEVEL SECURITY'
                    )
                )
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards DISABLE TRIGGER USER')
            )
            try:
                public_ids = {
                    row.listing_uid: ((row.definition or {}).get("service") or {}).get(
                        "public_id"
                    )
                    or registered.get(row.listing_uid)
                    for row in connection.execute(
                        sa.text(
                            f'SELECT listing_uid, definition FROM "{schema}".guild_plugins'  # noqa: S608
                        )
                    )
                }
                stored = connection.execute(
                    sa.text(f'SELECT id, definition, config FROM "{schema}".dashboards')  # noqa: S608
                ).fetchall()
                for dashboard_id, definition, config in stored:
                    if not isinstance(definition, dict):
                        continue
                    rewritten, pruned, changed, unbound = _rewrite(
                        definition,
                        config if isinstance(config, dict) else {},
                        public_ids,
                    )
                    for widget_id in unbound:
                        left += 1
                        logger.warning(
                            "dashboard widget left with no statement: "
                            "%s.dashboards id=%s widget=%s",
                            schema,
                            dashboard_id,
                            widget_id,
                        )
                    if not changed and not unbound:
                        continue
                    connection.execute(
                        sa.text(
                            f'UPDATE "{schema}".dashboards '  # noqa: S608
                            "SET definition = CAST(:body AS jsonb), "
                            "config = CAST(:config AS jsonb) WHERE id = :id"
                        ),
                        {
                            "body": json.dumps(rewritten),
                            "config": json.dumps(pruned),
                            "id": dashboard_id,
                        },
                    )
                    widgets += changed
            finally:
                connection.execute(
                    sa.text(f'ALTER TABLE "{schema}".dashboards ENABLE TRIGGER USER')
                )
                for table in ("dashboards", "guild_plugins"):
                    connection.execute(
                        sa.text(
                            f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY'
                        )
                    )
    finally:
        connection.execute(
            sa.text(
                "ALTER TABLE public.plugin_service_registrations FORCE ROW LEVEL SECURITY"
            )
        )
    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "plug-in bindings rewritten: %s widget(s) in %s schema(s); "
        "%s left with no statement",
        widgets,
        len(schemas),
        left,
    )


def _restore(definition: dict, config: dict) -> tuple[dict, dict, int]:
    """Every widget this revision rewrote whose statement is still the one it
    wrote, with its previous binding."""
    restored = 0
    widgets = config.get("widgets")
    per_widget = dict(widgets) if isinstance(widgets, dict) else {}
    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        legacy = binding.get("legacy")
        if (
            not isinstance(legacy, dict)
            or not isinstance(legacy.get("binding"), dict)
            or legacy["binding"].get("source") != "plugin"
            or legacy.get("sql", _fingerprint(None)) != _fingerprint(binding.get("sql"))
        ):
            continue
        widget["binding"] = legacy["binding"]
        if isinstance(legacy.get("config"), dict):
            per_widget[str(widget.get("id"))] = legacy["config"]
        restored += 1
    return definition, {**config, "widgets": per_widget}, restored


def downgrade() -> None:
    """Restore each plug-in binding this revision rewrote whose statement is
    still the one it wrote."""
    connection = op.get_bind()
    for schema in _schemas(connection):
        connection.execute(sa.text(f'SET LOCAL search_path = "{schema}", public'))
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards NO FORCE ROW LEVEL SECURITY')
        )
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards DISABLE TRIGGER USER')
        )
        try:
            stored = connection.execute(
                sa.text(f'SELECT id, definition, config FROM "{schema}".dashboards')  # noqa: S608
            ).fetchall()
            for dashboard_id, definition, config in stored:
                if not isinstance(definition, dict):
                    continue
                restored, put_back, count = _restore(
                    definition, config if isinstance(config, dict) else {}
                )
                if not count:
                    continue
                connection.execute(
                    sa.text(
                        f'UPDATE "{schema}".dashboards '  # noqa: S608
                        "SET definition = CAST(:body AS jsonb), "
                        "config = CAST(:config AS jsonb) WHERE id = :id"
                    ),
                    {
                        "body": json.dumps(restored),
                        "config": json.dumps(put_back),
                        "id": dashboard_id,
                    },
                )
        finally:
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards ENABLE TRIGGER USER')
            )
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards FORCE ROW LEVEL SECURITY')
            )
    connection.execute(sa.text("SET LOCAL search_path = public"))
