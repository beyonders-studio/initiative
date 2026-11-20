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


_FORMULA = 'HYPERLINK("http://evil","x")'


@pytest.mark.parametrize(
    "cell,written",
    [
        # A cell starting with any trigger character is prefixed with a quote.
        *(
            (f"{t}{_FORMULA}", f"'{t}{_FORMULA}")
            for t in ("=", "+", "-", "@", "\t", "\r")
        ),
        # Values that don't begin with one are written verbatim, a trigger in
        # the middle included.
        *(
            (benign, benign)
            for benign in (
                "Ada Admin",
                "ada.admin@example.com",
                "Initiative: project_manager",
                "0.50.2",
                "https://example.com",
                "",
                "Foo=Bar",
                "a-b-c",
            )
        ),
        # Non-string cells are stringified without spurious quoting, and None
        # is an empty cell rather than 'None'.
        (42, "42"),
        (True, "True"),
        (None, ""),
    ],
)
def test_build_csv_neutralizes_only_a_leading_formula_trigger(cell, written) -> None:
    body = csv_export.build_csv(["value"], [[cell]])

    assert _parse(body)[1][0] == written


def test_build_csv_neutralizes_header_cells() -> None:
    """Headers flow through the same neutralization as data cells."""
    body = csv_export.build_csv(["=evil"], [["safe"]])
    rows = _parse(body)

    assert rows[0][0] == "'=evil"
    assert rows[1][0] == "safe"
