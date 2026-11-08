"""Unit tests for CSV export helpers, focused on formula neutralization.

``build_csv`` is the single choke point through which every exported cell
flows (used by the guild and platform user exports). A cell whose value begins
with a formula trigger (``=``, ``+``, ``-``, ``@``, tab, or carriage return)
must be prefixed with a single quote so spreadsheet apps treat it as text
rather than evaluating it as a formula.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.services.platform import csv_export


def _parse(body: bytes) -> list[list[str]]:
    """Strip the UTF-8 BOM and parse the CSV body into a list of rows."""
    text = body.decode("utf-8")
    text = text.removeprefix("﻿")
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_build_csv_neutralizes_formula_triggers(trigger: str) -> None:
    """A cell starting with any trigger character is prefixed with a quote."""
    payload = f'{trigger}HYPERLINK("http://evil","x")'
    body = csv_export.build_csv(["display_name"], [[payload]])
    rows = _parse(body)

    assert rows[1][0] == f"'{payload}"
    # The literal formula text must NOT survive unprefixed.
    assert rows[1][0] != payload


def test_build_csv_neutralizes_classic_cmd_payload() -> None:
    """A DDE-style formula value is neutralized."""
    payload = "=cmd|'/c calc'!A1"
    body = csv_export.build_csv(["email"], [[payload]])
    rows = _parse(body)

    assert rows[1][0] == "'" + payload


@pytest.mark.parametrize(
    "benign",
    [
        "Ada Admin",
        "ada.admin@example.com",
        "Initiative: project_manager",
        "0.50.2",
        "https://example.com",
        "",
    ],
)
def test_build_csv_leaves_benign_values_untouched(benign: str) -> None:
    """Values that don't begin with a trigger are written verbatim."""
    body = csv_export.build_csv(["value"], [[benign]])
    rows = _parse(body)

    assert rows[1][0] == benign


def test_build_csv_neutralizes_header_cells() -> None:
    """Headers flow through the same neutralization as data cells."""
    body = csv_export.build_csv(["=evil"], [["safe"]])
    rows = _parse(body)

    assert rows[0][0] == "'=evil"
    assert rows[1][0] == "safe"


def test_build_csv_stringifies_non_string_values() -> None:
    """Non-string cells (ints, bools) are preserved without spurious quoting."""
    body = csv_export.build_csv(
        ["user_id", "email_verified"],
        [[42, True]],
    )
    rows = _parse(body)

    assert rows[1] == ["42", "True"]


def test_build_csv_treats_none_as_empty() -> None:
    """``None`` is rendered as an empty cell, not the string 'None'."""
    body = csv_export.build_csv(["display_name"], [[None]])
    rows = _parse(body)

    assert rows[1][0] == ""


def testneutralize_cell_only_targets_leading_trigger() -> None:
    """A trigger character in the middle of a value is not escaped."""
    assert csv_export.neutralize_cell("Foo=Bar") == "Foo=Bar"
    assert csv_export.neutralize_cell("a-b-c") == "a-b-c"
    assert csv_export.neutralize_cell("=danger") == "'=danger"
