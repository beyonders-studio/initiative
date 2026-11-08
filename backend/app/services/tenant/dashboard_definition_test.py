"""Tests for dashboard definition/config validation.

The validator is a capability check: it admits only widget types we render and
binding sources we fetch, and leaves each binding's parameters to the fetcher
that consumes them. These tests pin both halves of that contract — what is
rejected, and what is deliberately passed through untouched.
"""

import pytest

from app.services.tenant.dashboard_definition import (
    MAX_WIDGETS,
    TABULAR_SOURCES,
    WIDGET_PRESETS,
    WIDGET_SPECS,
    WIDGET_TYPES,
    DashboardDefinitionError,
    normalize_dashboard_config,
    normalize_dashboard_definition,
)


def _definition(*widgets: dict) -> dict:
    return {"widgets": list(widgets)}


def test_every_slot_a_widget_declares_can_be_filled():
    """A slot nothing can fill is a widget nothing can drive. The table is the
    one widget with no shape, which is what makes it the fallback."""
    for widget_type, spec in WIDGET_SPECS.items():
        for slot in spec.shape:
            assert slot.types, f"{widget_type}.{slot.name} accepts no type"
        names = [slot.name for slot in spec.shape]
        assert len(names) == len(set(names)), widget_type
    assert WIDGET_SPECS["table"].shape == ()


def test_a_required_slot_comes_before_an_optional_one():
    """Inference walks the slots in order and takes the first column that fits,
    so anything a widget cannot draw without has to be asked for first."""
    for widget_type, spec in WIDGET_SPECS.items():
        required = [slot.required for slot in spec.shape]
        assert required == sorted(required, reverse=True), widget_type


def test_presets_resolve_to_a_primitive_and_never_shadow_one():
    """A preset is a named configuration of a first-party widget — it ships no
    renderer, which is what makes it a safe extension point for the
    marketplace."""
    assert WIDGET_TYPES == set(WIDGET_SPECS) | set(WIDGET_PRESETS)
    assert not (set(WIDGET_SPECS) & set(WIDGET_PRESETS))
    for name, preset in WIDGET_PRESETS.items():
        spec = WIDGET_SPECS[preset.primitive]
        for key, value in preset.options.items():
            assert value in spec.options[key], f"{name}: bad option {key}={value}"


def test_every_option_defaults_to_a_value_it_allows():
    """The default is what a widget draws when a definition names no value, and
    what the palette shows as chosen. One that is not in its own list would put
    the editor and the render out of step."""
    for widget_type, spec in WIDGET_SPECS.items():
        for key, option in spec.options.items():
            if option.kind != "choice":
                # A number or a day of its own: nothing to offer, unset by default.
                assert (option.values, option.default) == ((), ""), widget_type
                continue
            assert option.values, f"{widget_type}.{key} allows nothing"
            assert option.default in option.values, f"{widget_type}.{key} bad default"
            assert len(set(option.values)) == len(option.values), (
                f"{widget_type}.{key} repeats a value"
            )


def test_preset_is_stored_resolved():
    """What lands in the row is always a primitive, with the preset name kept
    only as a label."""
    result = normalize_dashboard_definition(
        _definition(
            {
                "id": "bars",
                "type": "bar_chart",
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    widget = result["widgets"][0]
    assert widget["type"] == "chart"
    assert widget["preset"] == "bar_chart"
    assert widget["options"]["mark"] == "bar"


def test_preset_options_win_over_supplied_ones():
    """A preset's own options are its identity — a bar_chart stays a bar."""
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "bar_chart",
                "options": {"mark": "pie"},
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    assert result["widgets"][0]["options"]["mark"] == "bar"


def test_rejects_unknown_option_value():
    with pytest.raises(DashboardDefinitionError, match="WIDGET_OPTION_INVALID"):
        normalize_dashboard_definition(
            _definition(
                {
                    "type": "chart",
                    "options": {"mark": "hologram"},
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                }
            )
        )


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        (
            {"target": 50, "target_date": "2026-06-30"},
            {"target": "50", "target_date": "2026-06-30"},
        ),
        ({"target": "2.5"}, {"target": "2.5"}),
        # Past exact whole numbers, the shortest form that reads back the same.
        ({"target": "1e32"}, {"target": "1e+32"}),
        ({"target": 123456789012345678}, {"target": "1.2345678901234568e+17"}),
        # Left empty, there is no target.
        ({"target": "", "target_date": ""}, {}),
    ],
)
def test_a_target_is_stored_as_a_plain_number_and_day(given, stored):
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "chart",
                "options": given,
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    assert result["widgets"][0].get("options", {}) == stored
    # What was stored saves again unchanged.
    again = normalize_dashboard_definition(result)
    assert again["widgets"][0].get("options", {}) == stored


@pytest.mark.parametrize(
    "given",
    [
        {"target": True},
        {"target": "nan"},
        {"target": "1e400"},
        {"target": "fifty"},
        {"target_date": "20260630"},
        {"target_date": "2026-02-30"},
    ],
)
def test_a_target_that_is_not_a_number_or_a_day_is_refused(given):
    with pytest.raises(DashboardDefinitionError, match="WIDGET_OPTION_INVALID"):
        normalize_dashboard_definition(
            _definition(
                {
                    "type": "chart",
                    "options": given,
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                }
            )
        )


def test_unknown_option_keys_are_dropped():
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "chart",
                "options": {"mark": "line", "onClick": "steal"},
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    assert result["widgets"][0]["options"] == {"mark": "line"}


def test_normalizes_to_canonical_shape():
    result = normalize_dashboard_definition(
        _definition(
            {
                "id": "w1",
                "type": "gantt",
                "title": "  Delivery  ",
                "grid": {"x": 0, "y": 0, "w": 12, "h": 6},
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )

    assert result["schema_version"] == 1
    assert result["kind"] == "dashboard"
    assert result["layout"] == {"columns": 12}
    widget = result["widgets"][0]
    assert widget["title"] == "Delivery"
    assert widget["grid"] == {"x": 0, "y": 0, "w": 12, "h": 6}


def test_widget_ids_are_assigned_and_must_be_unique():
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "stat",
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            },
            {
                "type": "stat",
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            },
        )
    )
    assert [w["id"] for w in result["widgets"]] == ["w1", "w2"]

    with pytest.raises(DashboardDefinitionError, match="WIDGET_ID_DUPLICATE"):
        normalize_dashboard_definition(
            _definition(
                {
                    "id": "same",
                    "type": "stat",
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                },
                {
                    "id": "same",
                    "type": "stat",
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                },
            )
        )


def test_size_floor_is_enforced_per_widget_type():
    """A layout can't squeeze a widget below what it can legibly render."""
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "grid": {"w": 1, "h": 1},
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    grid = result["widgets"][0]["grid"]
    assert grid["w"] == WIDGET_SPECS["gantt"].min_w
    assert grid["h"] == WIDGET_SPECS["gantt"].min_h


def test_widget_is_kept_inside_the_grid():
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "grid": {"x": 9, "y": 0, "w": 12, "h": 6},
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    grid = result["widgets"][0]["grid"]
    assert grid["x"] + grid["w"] <= 12


@pytest.mark.parametrize(
    "payload,code",
    [
        (
            {
                "widgets": [
                    {
                        "type": "evil",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT title FROM tasks",
                        },
                    }
                ]
            },
            "WIDGET_TYPE_UNKNOWN",
        ),
        (
            {"widgets": [{"type": "stat", "binding": {"source": "shell_exec"}}]},
            "BINDING_SOURCE_UNKNOWN",
        ),
        # A real source, but not one this widget can draw.
        (
            {
                "widgets": [
                    {
                        "type": "stat",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT secret FROM pg_shadow",
                        },
                    }
                ]
            },
            "UNKNOWN_RELATION",
        ),
        ({"widgets": [{"type": "stat"}]}, "BINDING_INVALID"),
        ({"widgets": "nope"}, "DEFINITION_INVALID"),
        ({"schema_version": 99, "widgets": []}, "DEFINITION_VERSION_UNSUPPORTED"),
    ],
)
def test_rejects_unknown_vocabulary(payload, code):
    with pytest.raises(DashboardDefinitionError, match=code):
        normalize_dashboard_definition(payload)


def test_rejects_too_many_widgets():
    widgets = [
        {
            "id": f"w{i}",
            "type": "stat",
            "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
        }
        for i in range(MAX_WIDGETS + 1)
    ]
    with pytest.raises(DashboardDefinitionError, match="TOO_MANY_WIDGETS"):
        normalize_dashboard_definition({"widgets": widgets})


def test_no_definition_can_name_an_endpoint():
    """The closed source vocabulary is what keeps a URL out of a definition —
    there is no source that carries a URL."""
    for candidate in ("https://evil.test/steal", "//evil.test", "file:///etc/passwd"):
        with pytest.raises(DashboardDefinitionError, match="BINDING_SOURCE_UNKNOWN"):
            normalize_dashboard_definition(
                _definition({"type": "stat", "binding": {"source": candidate}})
            )


def test_binding_parameters_pass_through_untouched():
    """Parameters belong to the fetcher: the filter DSL enforces its own limits
    and ids are authorized by RLS at fetch time, so they are stored as given."""
    conditions = {
        "logic": "and",
        "conditions": [{"field": "priority", "op": "eq", "value": "high"}],
    }
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "binding": {
                    "source": "query",
                    "sql": "SELECT title FROM tasks",
                    "conditions": conditions,
                    "group_by": "project",
                },
            }
        )
    )
    binding = result["widgets"][0]["binding"]
    assert binding["conditions"] == conditions
    assert binding["group_by"] == "project"


def test_a_binding_cannot_name_its_own_initiative_or_guild():
    """Scope comes from the row the dashboard lives on, not from the definition.

    Every source at launch reads within one initiative, so there is nothing for
    these to express — and dropping them means an authored (or downloaded)
    definition has no field to point at somewhere else with.
    """
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "binding": {
                    "source": "query",
                    "sql": "SELECT title FROM tasks",
                    "initiative_id": 999,
                    "guild_id": 42,
                    "project_id": 7,
                },
            }
        )
    )
    binding = result["widgets"][0]["binding"]
    assert "initiative_id" not in binding
    assert "guild_id" not in binding
    # A project is still the author's to choose; the fetcher scopes it.
    assert binding["project_id"] == 7


def test_unknown_structural_keys_are_dropped():
    result = normalize_dashboard_definition(
        {
            "widgets": [
                {
                    "type": "stat",
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                    "onClick": {"action": "delete_everything"},
                }
            ],
            "scripts": ["alert(1)"],
        }
    )
    assert "scripts" not in result
    assert "onClick" not in result["widgets"][0]


def test_config_is_scoped_to_the_definitions_widgets():
    definition = normalize_dashboard_definition(
        _definition(
            {
                "id": "w1",
                "type": "stat",
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    config = normalize_dashboard_config(
        {"widgets": {"w1": {"counter_id": 42}, "ghost": {"counter_id": 9}}},
        definition,
    )
    assert config == {"widgets": {"w1": {"counter_id": 42}}}


def test_config_fills_only_what_the_definition_left_open():
    """Config carries parameter values. What the widget reads — its source,
    statement, plug-in and endpoint — and any value the definition already set
    stay the definition's."""
    definition = normalize_dashboard_definition(
        _definition(
            {
                "id": "w1",
                "type": "table",
                "binding": {
                    "source": "query",
                    "sql": "SELECT title FROM tasks",
                    "spec": {"dataset": "tasks"},
                },
            }
        )
    )
    config = normalize_dashboard_config(
        {
            "widgets": {
                "w1": {
                    "counter_id": 9,
                    "spec": {"dataset": "projects"},
                    "source": "plugin",
                    "sql": "SELECT name FROM projects",
                    "initiative_id": 5,
                }
            }
        },
        definition,
    )
    assert config == {"widgets": {"w1": {"counter_id": 9}}}


def test_config_for_a_removed_widget_is_dropped():
    """Updating to a definition without that widget can't leave config behind."""
    definition = normalize_dashboard_definition(
        _definition(
            {
                "id": "w2",
                "type": "stat",
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
            }
        )
    )
    assert normalize_dashboard_config(
        {"widgets": {"w1": {"counter_id": 1}}}, definition
    ) == {"widgets": {}}


# ---------------------------------------------------------------------------
# Plug-in widgets and the `plugin` binding source
# ---------------------------------------------------------------------------
#
# A service plug-in's widget is a *separate* vocabulary from the built-ins, and the
# separation is what these pin. A plug-in widget is namespaced, binds only `plugin`,
# and binds only its own plug-in's sources — so a definition can never point one
# vendor's module at another vendor's data, and never resolve a plug-in's widget to
# a built-in renderer.
#
# What a source *is* — its parameters, its credentials, its freshness — lives in
# the installed plug-in's pinned definition and is enforced when the data is
# fetched. The validator's job here is shape, not authority.

PLUGIN_UID = "SHPAPP00000001"
OTHER_UID = "OTHERAPP000001"


def _plugin_widget(**overrides) -> dict:
    return {
        "id": "w1",
        "type": f"plugin:{PLUGIN_UID}:summary",
        "binding": {
            "source": "plugin",
            "plugin_uid": PLUGIN_UID,
            "endpoint_id": "plugin.acme.shop.orders-summary",
        },
        **overrides,
    }


def test_a_plugin_widget_keeps_its_namespaced_type():
    result = normalize_dashboard_definition(_definition(_plugin_widget()))
    widget = result["widgets"][0]
    assert widget["type"] == f"plugin:{PLUGIN_UID}:summary"
    assert widget["binding"] == {
        "source": "plugin",
        "plugin_uid": PLUGIN_UID,
        "endpoint_id": "plugin.acme.shop.orders-summary",
    }
    # It still gets a grid, from the plugin-widget floor rather than a primitive's.
    assert widget["grid"]["w"] >= 2 and widget["grid"]["h"] >= 2


def test_a_definition_outlives_the_plugin_its_widgets_came_from():
    """The check on a plug-in widget is shape, never an install lookup.

    A stored dashboard is the guild's, so re-normalizing it — an edit, an
    upgrade — must keep accepting its plug-in widgets whether or not the plug-in is
    still installed. `plugin:<uid>:<widget>` with valid parts stores verbatim; the
    client renders the not-installed state and asks for the plug-in to be
    reconnected. Only a malformed type is a rejection (the tests below).
    """
    definition = _definition(_plugin_widget())
    first = normalize_dashboard_definition(definition)
    # Idempotent under re-normalization: what was stored stays storable.
    assert normalize_dashboard_definition(first) == first


def test_declared_parameters_are_kept_as_the_scalars_they_are():
    """Not coerced: the source's own params_schema declares the type, and
    turning a bool into an int here would satisfy a check the fetch path is
    meant to refuse."""
    result = normalize_dashboard_definition(
        _definition(
            _plugin_widget(
                binding={
                    "source": "plugin",
                    "plugin_uid": PLUGIN_UID,
                    "endpoint_id": "plugin.acme.shop.orders",
                    "params": {"range": "30d", "limit": 5, "detailed": True},
                }
            )
        )
    )
    assert result["widgets"][0]["binding"]["params"] == {
        "range": "30d",
        "limit": 5,
        "detailed": True,
    }


def test_a_parameter_may_hold_several_values():
    """An endpoint may declare a parameter takes several — several labels,
    several assignees — and a binding that could hold only one of them could not
    say what such a parameter is for.

    This is the shape a widget's own form produces the moment a plug-in declares
    `list`, and storing it is what makes that form's Save mean anything: a
    binding refused here fails the whole dashboard write, taking every unrelated
    edit in the same request — a renamed tile, a moved one — down with it.
    """
    result = normalize_dashboard_definition(
        _definition(
            _plugin_widget(
                binding={
                    "source": "plugin",
                    "plugin_uid": PLUGIN_UID,
                    "endpoint_id": "plugin.acme.shop.orders",
                    "params": {"labels": ["bug", "regression"], "state": "open"},
                }
            )
        )
    )
    assert result["widgets"][0]["binding"]["params"] == {
        "labels": ["bug", "regression"],
        "state": "open",
    }


def test_values_inside_a_list_are_held_to_the_same_shapes():
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(
            _definition(
                _plugin_widget(
                    binding={
                        "source": "plugin",
                        "plugin_uid": PLUGIN_UID,
                        "endpoint_id": "plugin.acme.shop.orders",
                        "params": {"labels": [{"nested": "object"}]},
                    }
                )
            )
        )


def test_a_list_longer_than_a_definition_may_carry_is_refused():
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(
            _definition(
                _plugin_widget(
                    binding={
                        "source": "plugin",
                        "plugin_uid": PLUGIN_UID,
                        "endpoint_id": "plugin.acme.shop.orders",
                        "params": {"labels": ["x"] * 65},
                    }
                )
            )
        )


def test_a_plugin_widget_cannot_bind_another_plugins_data():
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(
            _definition(
                _plugin_widget(
                    binding={
                        "source": "plugin",
                        "plugin_uid": OTHER_UID,
                        "endpoint_id": "plugin.acme.shop.orders",
                    }
                )
            )
        )


def test_a_plugin_widget_binds_only_the_plugin_source():
    for source in sorted(TABULAR_SOURCES):
        with pytest.raises(DashboardDefinitionError):
            normalize_dashboard_definition(
                _definition(_plugin_widget(binding={"source": source}))
            )


def test_a_builtin_widget_reads_a_plugin_through_its_statement():
    """A built-in widget binds a statement, and the statement reads the
    plug-in; the plug-in source is its own widgets'."""
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(
            _definition(
                {
                    "id": "w1",
                    "type": "stat",
                    "binding": {
                        "source": "plugin",
                        "plugin_uid": PLUGIN_UID,
                        "endpoint_id": "plugin.acme.shop.orders",
                        "sql": "SELECT shop FROM rows",
                    },
                }
            )
        )
    statement = "SELECT o.shop FROM plugin('acme.shop', 'orders', range => '30d') AS o"
    definition = normalize_dashboard_definition(
        _definition(
            {
                "id": "w1",
                "type": "stat",
                "binding": {"source": "query", "sql": statement},
            }
        )
    )
    assert definition["widgets"][0]["binding"] == {"source": "query", "sql": statement}


def test_the_plugin_source_is_not_in_the_builtin_vocabulary():
    """`TABULAR_SOURCES` and `WIDGET_TYPES` stay the built-ins' own, so the
    served widget catalog and every drift test keep describing this build's
    renderers rather than whatever some guild happens to have installed."""
    assert "plugin" not in TABULAR_SOURCES
    assert not any(name.startswith("plugin:") for name in WIDGET_TYPES)


@pytest.mark.parametrize(
    "widget_type",
    [
        "plugin:",
        "plugin:SHPAPP00000001",  # no widget id
        "plugin:SHPAPP00000001:",  # empty widget id
        "plugin:short:summary",  # uid is the wrong length
        "plugin:SHOPAPP000000!:summary",  # outside the uid alphabet
        "plugin:SHPAPP00000001:Summary!",  # outside the identifier set
    ],
)
def test_a_malformed_plugin_widget_type_is_refused(widget_type):
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(_definition(_plugin_widget(type=widget_type)))


@pytest.mark.parametrize(
    "binding",
    [
        {
            "source": "plugin",
            "endpoint_id": "plugin.acme.shop.orders",
        },  # no plug-in named
        {"source": "plugin", "plugin_uid": PLUGIN_UID},  # no source named
        {"source": "plugin", "plugin_uid": PLUGIN_UID, "endpoint_id": "Orders!"},
        {
            "source": "plugin",
            "plugin_uid": PLUGIN_UID,
            "endpoint_id": "plugin.acme.shop.orders",
            "params": [],
        },
        {
            "source": "plugin",
            "plugin_uid": PLUGIN_UID,
            "endpoint_id": "plugin.acme.shop.orders",
            "params": {"range": {"nested": 1}},
        },
        {
            "source": "plugin",
            "plugin_uid": PLUGIN_UID,
            "endpoint_id": "plugin.acme.shop.orders",
            "params": {"bad key": "x"},
        },
    ],
)
def test_a_malformed_plugin_binding_is_refused(binding):
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(_definition(_plugin_widget(binding=binding)))


def test_a_plugin_binding_still_has_nowhere_to_put_an_address():
    """The rule that makes a stored definition safe: it names capabilities, not
    hosts. Where the plug-in lives comes from the deployment's registration."""
    result = normalize_dashboard_definition(
        _definition(
            _plugin_widget(
                binding={
                    "source": "plugin",
                    "plugin_uid": PLUGIN_UID,
                    "endpoint_id": "plugin.acme.shop.orders",
                    "url": "https://evil.test/steal",
                    "base_url": "https://evil.test",
                }
            )
        )
    )
    binding = result["widgets"][0]["binding"]
    assert set(binding) == {"source", "plugin_uid", "endpoint_id"}


def test_a_statement_is_read_before_it_is_stored():
    """A definition that cannot be fetched should not be storable: the author is
    looking at the query, so the refusal names the word that has to change."""
    with pytest.raises(DashboardDefinitionError, match="UNKNOWN_FIELD"):
        normalize_dashboard_definition(
            _definition(
                {
                    "type": "stat",
                    "binding": {"source": "query", "sql": "SELECT nope FROM tasks"},
                }
            )
        )


def test_a_query_binding_may_have_no_statement_yet():
    """A widget is placed before it is pointed anywhere, and an installed
    listing may ship one for its guild to fill in. Nothing is fetched for it
    and it draws its own panel asking to be configured."""
    definition = normalize_dashboard_definition(
        _definition({"type": "stat", "binding": {"source": "query"}})
    )
    assert definition["widgets"][0]["binding"] == {"source": "query"}


def test_a_statement_that_is_not_text_is_refused():
    with pytest.raises(DashboardDefinitionError, match="BINDING_SQL_MISSING"):
        normalize_dashboard_definition(
            _definition({"type": "stat", "binding": {"source": "query", "sql": 7}})
        )


def test_a_mapping_names_the_widgets_own_slots():
    """Slots are the widget's, and a mapping keying on anything else would be
    read by nothing."""
    definition = normalize_dashboard_definition(
        _definition(
            {
                "type": "chart",
                "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                "mapping": {"label": 0, "value": [1, 2]},
            }
        )
    )
    assert definition["widgets"][0]["mapping"] == {"label": [0], "value": [1, 2]}

    with pytest.raises(DashboardDefinitionError, match="WIDGET_MAPPING_INVALID"):
        normalize_dashboard_definition(
            _definition(
                {
                    "type": "chart",
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                    "mapping": {"nonsense": 0},
                }
            )
        )


def test_only_a_repeatable_slot_takes_several_columns():
    """A funnel draws one measure. Two would be a chart."""
    with pytest.raises(DashboardDefinitionError, match="WIDGET_MAPPING_INVALID"):
        normalize_dashboard_definition(
            _definition(
                {
                    "type": "funnel",
                    "binding": {"source": "query", "sql": "SELECT title FROM tasks"},
                    "mapping": {"value": [1, 2]},
                }
            )
        )


def test_config_cannot_repoint_a_plugin_widget_and_is_checked_like_a_binding():
    definition = normalize_dashboard_definition(_definition(_plugin_widget()))
    config = normalize_dashboard_config(
        {
            "widgets": {
                "w1": {
                    "plugin_uid": OTHER_UID,
                    "endpoint_id": "plugin.other.orders",
                    "params": {"range": "30d"},
                }
            }
        },
        definition,
    )
    assert config == {"widgets": {"w1": {"params": {"range": "30d"}}}}

    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_config(
            {"widgets": {"w1": {"params": {"range": {"nested": True}}}}}, definition
        )
