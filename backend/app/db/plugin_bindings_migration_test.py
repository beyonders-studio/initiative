"""Migration 20261107_0588 turns built-in widgets' plug-in bindings into
statements.

Loaded by path, as the other migration tests load theirs, and asked of the
rewrite itself: what each binding becomes, and what the downgrade puts back.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from app.services.query.resolve import PluginCall, resolve

_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261107_0588_plugin_bindings_become_queries.py"
)
_spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
assert _spec and _spec.loader
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)


def test_a_builtin_widgets_plugin_binding_becomes_its_statement():
    """The statement keeps its text, with ``rows`` read through ``plugin()``
    under the same name and the binding's parameters written into the call.
    A binding whose plug-in is not installed is left with no statement, a
    plug-in's own widget keeps its binding, and the downgrade puts every
    rewritten one back, the install's half into the config."""
    definition = {
        "widgets": [
            {
                "id": "w1",
                "type": "bar",
                "binding": {
                    "source": "plugin",
                    "plugin_uid": "SHPAPP00000001",
                    "endpoint_id": "plugin.acme.shop.orders",
                    "sql": "SELECT status, count(*) AS n\nFROM rows -- by status\nGROUP BY status",
                },
                "mapping": {"label": [0], "value": [1]},
            },
            {
                "id": "w2",
                "type": "table",
                "binding": {
                    "source": "plugin",
                    "plugin_uid": "SHPAPP00000001",
                    "endpoint_id": "plugin.acme.shop.orders",
                    "sql": "SELECT r.status FROM rows r WHERE r.total > 5",
                },
            },
            {
                "id": "w3",
                "type": "stat",
                "binding": {
                    "source": "plugin",
                    "plugin_uid": "GONEAPP0000001",
                    "endpoint_id": "plugin.gone.app.orders",
                    "sql": "SELECT count(*) FROM rows",
                },
            },
            {
                "id": "w4",
                "type": "plugin:SHPAPP00000001:summary",
                "binding": {
                    "source": "plugin",
                    "plugin_uid": "SHPAPP00000001",
                    "endpoint_id": "plugin.acme.shop.orders",
                },
            },
        ]
    }
    config = {"widgets": {"w2": {"params": {"range": "30d", "tags": ["a", "b"]}}}}
    before = copy.deepcopy((definition, config))

    rewritten, pruned, changed, unbound = revision._rewrite(
        definition, config, {"SHPAPP00000001": "acme.shop"}
    )

    assert (changed, unbound) == (2, ["w3"])
    first, second, third, fourth = rewritten["widgets"]
    assert first["binding"]["sql"] == (
        "SELECT status, count(*) AS n\n"
        "FROM plugin('acme.shop', 'orders') AS rows -- by status\n"
        "GROUP BY status"
    )
    assert first["mapping"] == {"label": [0], "value": [1]}
    assert second["binding"]["sql"] == (
        "SELECT r.status FROM plugin('acme.shop', 'orders', range => '30d', "
        "tags => ARRAY['a', 'b']) r WHERE r.total > 5"
    )
    assert resolve(second["binding"]["sql"]).unread == (
        PluginCall("acme.shop", "orders", (("range", "30d"), ("tags", ("a", "b")))),
    )
    assert "sql" not in third["binding"]
    assert fourth == before[0]["widgets"][3]
    assert pruned == {"widgets": {}}

    assert revision._restore(rewritten, pruned) == (*before, 3)
