"""
Unit tests for the properties service layer.

Focus areas:
- ``_validate_value_for_type`` — per-type coercion and rejection
- ``parse_property_filters`` — JSON-param parser
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.schemas.query import FilterOp
from app.services.tenant.metadata import (
    MAX_PROPERTY_FILTERS,
    _validate_value_for_type,
    parse_property_filters,
)


def _make_definition(
    type: MetadataType,
    *,
    options: list[dict] | None = None,
    initiative_id: int = 1,
) -> MetadataDefinition:
    """Build a non-persisted MetadataDefinition for pure-function tests."""
    defn = MetadataDefinition(
        initiative_id=initiative_id,
        name="Prop",
        type=type,
    )
    if options is not None:
        defn.options = options
    return defn


# ---------------------------------------------------------------------------
# _validate_value_for_type — text
# ---------------------------------------------------------------------------


def test_validate_text_accepts_string():
    defn = _make_definition(MetadataType.text)
    cols = _validate_value_for_type(defn, "hello")
    assert cols["value_text"] == "hello"
    assert cols["value_number"] is None


def test_validate_text_rejects_non_string():
    defn = _make_definition(MetadataType.text)
    with pytest.raises(HTTPException) as exc_info:
        _validate_value_for_type(defn, 123)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "PROPERTY_INVALID_VALUE_FOR_TYPE"


# ---------------------------------------------------------------------------
# number
# ---------------------------------------------------------------------------


def test_validate_number_accepts_int_float_and_string():
    defn = _make_definition(MetadataType.number)

    cols_int = _validate_value_for_type(defn, 10)
    assert cols_int["value_number"] == Decimal("10")

    cols_float = _validate_value_for_type(defn, 2.5)
    assert cols_float["value_number"] == Decimal("2.5")

    cols_str = _validate_value_for_type(defn, "42.0")
    assert cols_str["value_number"] == Decimal("42.0")


def test_validate_number_rejects_non_numeric():
    defn = _make_definition(MetadataType.number)
    with pytest.raises(HTTPException) as exc_info:
        _validate_value_for_type(defn, "abc")
    assert exc_info.value.detail == "PROPERTY_INVALID_VALUE_FOR_TYPE"


# ---------------------------------------------------------------------------
# checkbox
# ---------------------------------------------------------------------------


def test_validate_checkbox_accepts_bool():
    defn = _make_definition(MetadataType.checkbox)
    cols = _validate_value_for_type(defn, True)
    assert cols["value_boolean"] is True


# ---------------------------------------------------------------------------
# date
# ---------------------------------------------------------------------------


def test_validate_date_accepts_iso_string():
    defn = _make_definition(MetadataType.date)
    cols = _validate_value_for_type(defn, "2026-04-22")
    assert cols["value_date"] == date(2026, 4, 22)


# ---------------------------------------------------------------------------
# datetime
# ---------------------------------------------------------------------------


def test_validate_datetime_accepts_iso_with_tz():
    defn = _make_definition(MetadataType.datetime)
    cols = _validate_value_for_type(defn, "2026-04-22T10:00:00+00:00")
    assert isinstance(cols["value_datetime"], datetime)
    assert cols["value_datetime"].tzinfo is not None


# ---------------------------------------------------------------------------
# url
# ---------------------------------------------------------------------------


def test_validate_url_accepts_http_https():
    defn = _make_definition(MetadataType.url)

    for ok_url in ("https://example.com", "http://example.com/path?q=1"):
        cols = _validate_value_for_type(defn, ok_url)
        assert cols["value_text"] == ok_url


def test_validate_empty_values_are_attached_but_empty():
    """``None``, blank strings, and empty lists yield all-None columns.

    This lets a user attach a property definition to a doc/task without
    supplying a value (the "is empty" filter then matches the row).
    """
    text_defn = _make_definition(MetadataType.text)
    url_defn = _make_definition(MetadataType.url)
    multi_defn = _make_definition(
        MetadataType.multi_select,
        options=[{"value": "a", "label": "A"}],
    )

    for defn, empty in (
        (text_defn, None),
        (text_defn, ""),
        (text_defn, "   "),
        (url_defn, None),
        (url_defn, ""),
        (multi_defn, None),
        (multi_defn, []),
    ):
        cols = _validate_value_for_type(defn, empty)
        assert cols["value_text"] is None
        assert cols["value_number"] is None
        assert cols["value_boolean"] is None
        assert cols["value_user_id"] is None
        assert cols["value_json"] is None


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------


def test_validate_select_slug_in_options():
    defn = _make_definition(
        MetadataType.select,
        options=[{"value": "live", "label": "Live"}],
    )
    cols = _validate_value_for_type(defn, "live")
    assert cols["value_text"] == "live"


def test_validate_select_rejects_unknown_slug():
    defn = _make_definition(
        MetadataType.select,
        options=[{"value": "live", "label": "Live"}],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_value_for_type(defn, "ghost")
    assert exc_info.value.detail == "PROPERTY_OPTION_NOT_IN_DEFINITION"


# ---------------------------------------------------------------------------
# multi_select
# ---------------------------------------------------------------------------


def test_validate_multi_select_all_slugs_valid_and_deduped():
    defn = _make_definition(
        MetadataType.multi_select,
        options=[
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ],
    )
    cols = _validate_value_for_type(defn, ["a", "b", "a"])
    assert cols["value_json"] == ["a", "b"]


def test_validate_multi_select_rejects_unknown_slug():
    defn = _make_definition(
        MetadataType.multi_select,
        options=[{"value": "a", "label": "A"}],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_value_for_type(defn, ["a", "nope"])
    assert exc_info.value.detail == "PROPERTY_OPTION_NOT_IN_DEFINITION"


# ---------------------------------------------------------------------------
# user_reference
# ---------------------------------------------------------------------------


def test_validate_user_reference_takes_a_row_id():
    """A person value is the person's id; who may be named is asked of the
    whole set by ``named_people``."""
    defn = _make_definition(MetadataType.user_reference, initiative_id=1)
    assert _validate_value_for_type(defn, 7)["value_user_id"] == 7
    with pytest.raises(HTTPException):
        _validate_value_for_type(defn, True)


@pytest.mark.parametrize(
    ("prop_type", "bad"),
    [
        # Strict: no string or integer coercion into a bool.
        *((MetadataType.checkbox, v) for v in ("true", "false", 1, 0, "garbage")),
        (MetadataType.date, "notadate"),
        (MetadataType.datetime, "notadatetime"),
        (MetadataType.url, "ftp://example.com"),
        (MetadataType.url, "not a url"),
        # A user reference is an id, not the string form of one.
        (MetadataType.user_reference, "1"),
    ],
    ids=lambda v: str(getattr(v, "value", v)),
)
def test_validate_value_rejects_a_value_of_the_wrong_shape(
    prop_type: MetadataType, bad
):
    """A value the column cannot hold is refused at validation rather than
    stored in a coerced form."""
    defn = _make_definition(prop_type)
    with pytest.raises(HTTPException):
        _validate_value_for_type(defn, bad)


# ---------------------------------------------------------------------------
# parse_property_filters
# ---------------------------------------------------------------------------


def test_parse_property_filters_empty_input_returns_empty_list():
    assert parse_property_filters(None) == []
    assert parse_property_filters("") == []


def test_parse_property_filters_well_formed_input():
    raw = '[{"property_id": 5, "op": "eq", "value": "x"}]'
    parsed = parse_property_filters(raw)
    assert len(parsed) == 1
    assert parsed[0].property_id == 5
    assert parsed[0].op == FilterOp.eq
    assert parsed[0].value == "x"


def test_parse_property_filters_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_property_filters("not-json")


def test_parse_property_filters_caps_at_max():
    raw = (
        "["
        + ",".join(
            f'{{"property_id": {i}, "op": "eq", "value": 1}}'
            for i in range(MAX_PROPERTY_FILTERS + 1)
        )
        + "]"
    )
    with pytest.raises(ValueError):
        parse_property_filters(raw)


def test_parse_property_filters_missing_property_id_raises():
    with pytest.raises(ValueError):
        parse_property_filters('[{"op": "eq", "value": "x"}]')


def test_parse_property_filters_unknown_op_raises():
    with pytest.raises(ValueError):
        parse_property_filters('[{"property_id": 1, "op": "weird", "value": "x"}]')


def test_parse_property_filters_defaults_op_to_eq():
    """op defaults to ``eq`` when omitted."""
    parsed = parse_property_filters('[{"property_id": 1, "value": "x"}]')
    assert parsed[0].op == FilterOp.eq


def test_parse_property_filters_is_null_defaults_value_to_true():
    """Omitting ``value`` on an is_null filter means "is empty" (True)."""
    parsed = parse_property_filters('[{"property_id": 1, "op": "is_null"}]')
    assert parsed[0].op == FilterOp.is_null
    assert parsed[0].value is True


def test_parse_property_filters_is_null_preserves_explicit_booleans():
    parsed_true = parse_property_filters(
        '[{"property_id": 1, "op": "is_null", "value": true}]'
    )
    parsed_false = parse_property_filters(
        '[{"property_id": 1, "op": "is_null", "value": false}]'
    )
    assert parsed_true[0].value is True
    assert parsed_false[0].value is False


def test_parse_property_filters_is_null_rejects_non_bool_value():
    """Non-bool values on is_null raise rather than silently coerce."""
    with pytest.raises(ValueError, match="must be a boolean"):
        parse_property_filters('[{"property_id": 1, "op": "is_null", "value": "yes"}]')
    with pytest.raises(ValueError, match="must be a boolean"):
        parse_property_filters('[{"property_id": 1, "op": "is_null", "value": 1}]')
