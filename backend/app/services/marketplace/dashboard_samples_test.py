"""A dashboard listing previews on rows shaped like its queries' answers."""

import pytest

from app.core.tools import Tool
from app.models.platform.marketplace import MarketplaceListingVersion
from app.services.marketplace.dashboard_samples import (
    SAMPLE_NOW,
    generate_dashboard_sample,
    normalize_dashboard_sample,
)
from app.services.marketplace.manifest_values import ListingDefinitionError
from app.services.marketplace.tool_listings import (
    installable_body,
    listing_example,
    normalize_tool_listing,
)


def _listing(*widgets: dict) -> dict:
    return normalize_tool_listing(Tool.dashboard, {"widgets": list(widgets)})


def _query(widget_id: str, sql: str, widget_type: str = "table") -> dict:
    return {
        "id": widget_id,
        "type": widget_type,
        "binding": {"source": "query", "sql": sql},
    }


class TestTheShapeIsTheQuerys:
    def test_columns_are_named_and_typed_as_the_statement_returns_them(self):
        envelope = _listing(
            _query(
                "w1",
                "SELECT priority, count(*) AS n FROM tasks GROUP BY priority",
            )
        )
        sample = generate_dashboard_sample(envelope, seed="x")["w1"]
        assert sample["columns"] == [
            {"name": "priority", "type": "enum"},
            {"name": "n", "type": "number"},
        ]
        # One row per group, drawn from the field's own vocabulary.
        labels = [row[0] for row in sample["rows"]]
        assert len(labels) == len(set(labels)) == 4
        assert set(labels) <= {"low", "medium", "high", "urgent"}
        assert all(isinstance(row[1], int) for row in sample["rows"])

    def test_a_lone_aggregate_is_one_row(self):
        envelope = _listing(_query("w1", "SELECT count(*) AS n FROM tasks", "stat"))
        assert len(generate_dashboard_sample(envelope, seed="x")["w1"]["rows"]) == 1

    def test_dates_are_moments_around_the_sample_day(self):
        envelope = _listing(_query("w1", "SELECT title, due_date FROM tasks"))
        rows = generate_dashboard_sample(envelope, seed="x")["w1"]["rows"]
        now_ms = int(SAMPLE_NOW.timestamp() * 1000)
        day = 86_400_000
        assert all(now_ms - 14 * day <= row[1] <= now_ms + 21 * day for row in rows)

    def test_a_widget_it_cannot_describe_has_no_sample(self):
        envelope = _listing(
            {"id": "w1", "type": "table", "binding": {"source": "query"}}
        )
        assert generate_dashboard_sample(envelope, seed="x") == {}


class TestItIsTheSameEveryTime:
    def test_the_same_listing_draws_the_same_rows(self):
        envelope = _listing(_query("w1", "SELECT title, due_date FROM tasks"))
        assert generate_dashboard_sample(envelope, seed="a") == (
            generate_dashboard_sample(envelope, seed="a")
        )

    def test_a_listing_with_no_sample_of_its_own_is_never_shown_empty(self):
        envelope = _listing(_query("w1", "SELECT count(*) AS n FROM tasks", "stat"))
        version = MarketplaceListingVersion(
            listing_id=1, version="1.0.0", definition=envelope
        )
        example = listing_example(Tool.dashboard, "UID", version)
        assert example is not None and "w1" in example

    def test_a_sample_is_never_installed(self):
        envelope = _listing(_query("w1", "SELECT count(*) AS n FROM tasks", "stat"))
        version = MarketplaceListingVersion(
            listing_id=1,
            version="1.0.0",
            definition=envelope,
            example={"w1": {"columns": [], "rows": []}},
        )
        assert installable_body(version, "example") is None


class TestThePublishersOwnSample:
    @pytest.mark.parametrize(
        ("sample", "problem"),
        [
            ({"w9": {"columns": [], "rows": []}}, "no widget"),
            (
                {
                    "w1": {
                        "columns": [{"name": "n", "type": "number"}],
                        "rows": [[1, 2]],
                    }
                },
                "fit",
            ),
        ],
        ids=["answers-another-widget", "row-wider-than-its-columns"],
    )
    def test_one_that_does_not_fit_the_listing_is_refused(self, sample, problem):
        envelope = _listing(_query("w1", "SELECT count(*) AS n FROM tasks", "stat"))
        with pytest.raises(ListingDefinitionError, match=problem):
            normalize_dashboard_sample(envelope, sample)

    def test_a_good_one_is_kept(self):
        envelope = _listing(_query("w1", "SELECT count(*) AS n FROM tasks", "stat"))
        sample = {"w1": {"columns": [{"name": "n", "type": "number"}], "rows": [[7]]}}
        assert normalize_dashboard_sample(envelope, sample)["w1"]["rows"] == [[7]]
