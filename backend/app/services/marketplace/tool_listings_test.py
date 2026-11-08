"""A tool's listing is its export envelope, held to its own importer."""

import pytest

from app.core.tools import BULK_EXPORT_TOOLS, Tool
from app.services.import_engine import limits as import_limits
from app.services.marketplace.definitions import (
    KIND_AUDIENCE,
    LISTING_KINDS,
    TOOL_LISTING_KINDS,
    normalize_listing_definition,
    normalize_listing_example,
)
from app.services.marketplace.manifest_values import ListingDefinitionError
from app.services.marketplace.tool_listings import (
    example_is_generated,
    normalize_tool_listing,
)
from app.services.tenant.dashboard_definition import normalize_dashboard_definition

CANVAS = {
    "widgets": [
        {
            "id": "w1",
            "type": "stat",
            "binding": {"source": "query", "sql": "SELECT count(*) AS n FROM tasks"},
        }
    ]
}


def _counters(count: int = 1, **extra) -> dict:
    return {
        "type": "initiative-counter-group",
        "name": "Hit points",
        "counters": [{"name": f"Counter {i}", "count": i} for i in range(count)],
        **extra,
    }


class TestEveryToolHasAMarketplace:
    def test_the_kinds_are_the_exportable_tools(self):
        assert set(TOOL_LISTING_KINDS) == {tool.value for tool in BULK_EXPORT_TOOLS}
        assert set(TOOL_LISTING_KINDS) <= LISTING_KINDS

    def test_a_tools_marketplace_installs_to_a_community(self):
        for kind in TOOL_LISTING_KINDS:
            assert KIND_AUDIENCE[kind] == "guild"

    @pytest.mark.parametrize("tool", list(Tool))
    def test_a_listing_is_refused_unless_it_is_that_tools_envelope(self, tool):
        with pytest.raises(ListingDefinitionError):
            normalize_tool_listing(tool, {"type": "initiative-something-else"})


class TestTheEnvelopeIsStoredAsTheImporterReadsIt:
    def test_unknown_keys_are_dropped(self):
        stored = normalize_tool_listing(
            Tool.counter_group, _counters(stray="not part of the envelope")
        )
        assert "stray" not in stored
        assert stored["counters"][0]["name"] == "Counter 0"

    def test_where_it_was_exported_from_is_not_kept(self):
        stored = normalize_tool_listing(
            Tool.counter_group,
            _counters(source_instance_url="https://elsewhere", source_guild_id=4),
        )
        assert "source_instance_url" not in stored
        assert "source_guild_id" not in stored

    @pytest.mark.parametrize(
        ("tool", "body"),
        [
            (Tool.counter_group, _counters()),
            (
                Tool.dashboard,
                {"type": "initiative-dashboard", "name": "Board", "definition": CANVAS},
            ),
            (Tool.dashboard, CANVAS),
        ],
    )
    def test_normalizing_twice_changes_nothing(self, tool, body):
        # A re-published version is compared against what is stored, so the
        # stored form has to be a fixed point or every re-seed is refused.
        once = normalize_tool_listing(tool, body)
        assert normalize_tool_listing(tool, once) == once

    def test_a_listing_is_bounded_by_the_inline_import_ceiling(self):
        too_many = _counters(count=import_limits.IMPORT_INLINE_MAX_ROWS + 1)
        with pytest.raises(ListingDefinitionError, match="rows"):
            normalize_tool_listing(Tool.counter_group, too_many)


class TestADashboardListing:
    def test_a_bare_canvas_is_wrapped_in_the_envelope(self):
        # The exact shape migration 20260923_0370 writes for a stored one, so
        # a listing re-published at the same version still matches.
        assert normalize_listing_definition("dashboard", CANVAS) == {
            "schema_version": 1,
            "type": "initiative-dashboard",
            "name": "",
            "description": None,
            "definition": normalize_dashboard_definition(CANVAS),
            "config": {},
            "tags": [],
            "properties": [],
        }

    def test_its_configuration_is_the_installers(self):
        stored = normalize_tool_listing(
            Tool.dashboard,
            {
                "type": "initiative-dashboard",
                "name": "Board",
                "definition": CANVAS,
                "config": {"widgets": {"w1": {"counter_id": 12}}},
            },
        )
        assert stored["config"] == {}

    def test_a_canvas_this_build_cannot_draw_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="dashboard"):
            normalize_tool_listing(
                Tool.dashboard,
                {"widgets": [{"id": "w1", "type": "hologram", "binding": {}}]},
            )


class TestExamples:
    def test_a_content_tool_takes_its_publishers_example(self):
        assert not example_is_generated(Tool.counter_group)
        example = normalize_listing_example(
            "counter_group", _counters(count=3), _counters()
        )
        assert example is not None
        assert len(example["counters"]) == 3

    def test_the_example_is_held_to_the_same_rules(self):
        with pytest.raises(ListingDefinitionError):
            normalize_listing_example(
                "counter_group", {"type": "initiative-post"}, _counters()
            )

    def test_none_is_no_example(self):
        assert normalize_listing_example("counter_group", None, _counters()) is None

    def test_a_dashboards_example_is_sample_data_not_a_canvas(self):
        # A dashboard's example is its sample answers, by widget, never another
        # dashboard to install.
        assert example_is_generated(Tool.dashboard)
        definition = normalize_listing_definition("dashboard", CANVAS)
        with pytest.raises(ListingDefinitionError, match="no widget"):
            normalize_listing_example("dashboard", CANVAS, definition)

    def test_a_kind_that_is_no_tool_carries_none(self):
        with pytest.raises(ListingDefinitionError):
            normalize_listing_example("profile_pack", _counters(), {})


class TestGeneratedExamples:
    def test_every_tool_whose_example_is_generated_can_draw_one(self):
        from app.services.marketplace.tool_listings import _sample_makers

        generated = {tool for tool in Tool if example_is_generated(tool)}
        assert generated <= set(_sample_makers())
