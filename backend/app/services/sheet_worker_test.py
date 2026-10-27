"""The spreadsheet worker's reading of OpenDocument formulas."""

import pytest

from app.services.sheet_worker import grid_formula


@pytest.mark.parametrize(
    ("written", "read"),
    [
        ("of:=SUM([.A1:.A3])", "=SUM(A1:A3)"),
        ("of:=[.$A$1]*2", "=$A$1*2"),
        ('of:=IF([.B2]>0;"yes";"no")', '=IF(B2>0,"yes","no")'),
        ('of:="a;[.b]""c"', '="a;[.b]""c"'),
        ("of:=[Data.A1]+[$Data.B1]", "=Data!A1+Data!B1"),
        ("of:=SUM(['Q1 Actuals'.C2:.C9])", "=SUM('Q1 Actuals'!C2:C9)"),
        ("of:=SUM([.A:.A])", "=SUM(A:A)"),
        ("of:=COM.MICROSOFT.IFERROR([.A1];0)", "=IFERROR(A1,0)"),
        ("msoxl:=SUM(A1:A2)", "=SUM(A1:A2)"),
    ],
)
def test_an_opendocument_formula_is_written_as_the_grid_writes_one(written, read):
    assert grid_formula(written) == read


@pytest.mark.parametrize(
    "written",
    [
        "of:=['file:///budget.ods'#$Sheet1.A1]",
        "of:=[.#REF!]",
        "of:=SUM([Jan.A1:Feb.A1])",
        "=SUM(A1)",
    ],
    ids=["another-file", "an-error", "across-sheets", "no-namespace"],
)
def test_a_formula_the_grid_cannot_write_is_left_to_its_value(written):
    assert grid_formula(written) is None
