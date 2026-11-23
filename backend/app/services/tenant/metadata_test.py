"""The property value validator and the property-filter parser."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.schemas.query import FilterOp
from app.services.tenant.metadata import (
    _validate_value_for_type,
    parse_property_filters,
)

_OPTIONS = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]


def _make_definition(type: MetadataType) -> MetadataDefinition:
    """Build a non-persisted MetadataDefinition for pure-function tests."""
    defn = MetadataDefinition(initiative_id=1, name="Prop", type=type)
    if type in (MetadataType.select, MetadataType.multi_select):
        defn.options = _OPTIONS
    return defn


@pytest.mark.parametrize(
    ("prop_type", "value", "column", "stored"),
    [
        (MetadataType.number, 10, "value_number", Decimal(10)),
        (MetadataType.checkbox, True, "value_boolean", True),
        (
            MetadataType.datetime,
            "2026-04-22T10:00:00+00:00",
            "value_datetime",
            datetime(2026, 4, 22, 10, tzinfo=UTC),
        ),
        (MetadataType.url, "http://e.com/p?q=1", "value_text", "http://e.com/p?q=1"),
        (MetadataType.select, "a", "value_text", "a"),
        (MetadataType.multi_select, ["a", "b", "a"], "value_json", ["a", "b"]),
        # A person value is the person's id; who may be named is asked of the
        # whole set by ``named_people``.
        (MetadataType.user_reference, 7, "value_user_id", 7),
    ],
    ids=lambda v: str(getattr(v, "value", v)),
)
def test_a_value_is_stored_in_its_types_column(prop_type, value, column, stored):
    cols = _validate_value_for_type(_make_definition(prop_type), value)
    assert cols[column] == stored
    if column != "value_number":
        assert cols["value_number"] is None


@pytest.mark.parametrize(
    ("prop_type", "empty"),
    [
        (MetadataType.text, None),
        (MetadataType.text, ""),
        (MetadataType.text, "   "),
        (MetadataType.url, None),
        (MetadataType.url, ""),
        (MetadataType.multi_select, None),
        (MetadataType.multi_select, []),
    ],
)
def test_an_empty_value_is_attached_but_empty(prop_type, empty):
    """A property can sit on a row with no value, which "is empty" matches."""
    cols = _validate_value_for_type(_make_definition(prop_type), empty)
    for column in (
        "value_text",
        "value_number",
        "value_boolean",
        "value_user_id",
        "value_json",
    ):
        assert cols[column] is None


@pytest.mark.parametrize(
    ("prop_type", "bad"),
    [
        # Strict: no string or integer coercion into a bool.
        *((MetadataType.checkbox, v) for v in ("true", "false", 1, 0, "x")),
        (MetadataType.datetime, "notadatetime"),
        (MetadataType.url, "ftp://example.com"),
        # A user reference is an id, not the string form of one, nor a bool.
        (MetadataType.user_reference, "1"),
        (MetadataType.user_reference, True),
    ],
    ids=lambda v: str(getattr(v, "value", v)),
)
def test_a_value_of_the_wrong_shape_is_refused(prop_type, bad):
    """A value the column cannot hold is refused rather than stored coerced.
    The shapes a request refuses for every type are held in
    ``properties_surface_test``; these are the ones only this reads."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_value_for_type(_make_definition(prop_type), bad)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        (None, []),
        ("", []),
        ('[{"property_id": 5, "op": "eq", "value": "x"}]', [(5, FilterOp.eq, "x")]),
        # ``op`` defaults to ``eq``; an is_null filter's value to "is empty".
        ('[{"property_id": 1, "value": "x"}]', [(1, FilterOp.eq, "x")]),
        ('[{"property_id": 1, "op": "is_null"}]', [(1, FilterOp.is_null, True)]),
        (
            '[{"property_id": 1, "op": "is_null", "value": false}]',
            [(1, FilterOp.is_null, False)],
        ),
    ],
)
def test_property_filters_parse(raw, parsed):
    assert [
        (f.property_id, f.op, f.value) for f in parse_property_filters(raw)
    ] == parsed


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ('[{"op": "eq", "value": "x"}]', None),
        ('[{"property_id": 1, "op": "weird", "value": "x"}]', None),
        ('[{"property_id": 1, "op": "is_null", "value": "yes"}]', "must be a boolean"),
        ('[{"property_id": 1, "op": "is_null", "value": 1}]', "must be a boolean"),
    ],
)
def test_malformed_property_filters_are_refused(raw, match):
    """Unreadable JSON and too many predicates are held through a request in
    ``properties_surface_test``."""
    with pytest.raises(ValueError, match=match):
        parse_property_filters(raw)
