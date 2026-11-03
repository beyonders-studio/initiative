"""Integration tests for spreadsheet-type files.

Covers the JSON-snapshot path: create / get / patch / validation.
The live Y.Map collaboration layer is exercised separately on the
frontend; these tests are about the durable storage shape.
"""

from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.models.platform.guild import CommunityRole
from app.testing import Actor


def _sheet(content: dict, index: int = 0) -> dict:
    """One sheet out of a v3 workbook snapshot. Cells, dimensions, and the
    formatting maps live per sheet; only ``kind`` / ``schema_version`` sit
    at the top level."""
    return content["sheets"][index]


@pytest.fixture
async def author(acting_user) -> Actor:
    """A guild admin with an initiative to keep spreadsheets in.

    Per-test scope so each gets a fresh initiative — the round-trip and PATCH
    tests don't need to be isolated from each other but the validation tests
    do, and a function-scoped fixture is the cheap, consistent default.
    """
    return await acting_user(guild_role=CommunityRole.admin, initiative=True)


async def _create_sheet(
    client: AsyncClient, a: Actor, content: dict | None = None, **fields: Any
) -> Response:
    """Save a workbook through the create endpoint, whatever comes back.

    Omitting ``content`` sends a payload without one, which is a fresh
    spreadsheet; ``fields`` override the rest (``name``, ``file_type``).
    """
    payload: dict[str, Any] = {
        "name": "Sheet",
        "initiative_id": a.initiative.id,
        "file_type": "sheet",
        **fields,
    }
    if content is not None:
        payload["content"] = content
    return await client.post(a.g("/files/"), headers=a.headers, json=payload)


async def _stored_content(
    client: AsyncClient, a: Actor, content: dict | None = None, **fields: Any
) -> dict:
    """The snapshot a saved workbook came back as."""
    response = await _create_sheet(client, a, content, **fields)
    assert response.status_code == 201, response.text
    return response.json()["content"]


async def _stored_id(
    client: AsyncClient, a: Actor, content: dict | None = None, **fields: Any
) -> int:
    """The id of a saved workbook."""
    response = await _create_sheet(client, a, content, **fields)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_create_spreadsheet_round_trips_cells(client: AsyncClient, author: Actor):
    cells = {
        "0:0": "Date",
        "0:1": "Amount",
        "1:0": "2026-05-01",
        "1:1": 42.5,
        "2:1": True,
    }
    created = await _create_sheet(
        client,
        author,
        {
            "schema_version": 1,
            "kind": "spreadsheet",
            "dimensions": {"rows": 100, "cols": 26},
            "cells": cells,
        },
        name="Q2 Numbers",
    )
    assert created.status_code == 201, created.text
    assert created.json()["file_type"] == "sheet"

    # GET round-trip preserves the cell map exactly.
    response = await client.get(
        author.g(f"/files/{created.json()['id']}"), headers=author.headers
    )
    assert response.status_code == 200
    content = response.json()["content"]
    # v1 input is upcast to the current schema version on save.
    assert content["schema_version"] == 3
    assert content["kind"] == "spreadsheet"
    assert _sheet(content)["cells"] == cells


async def test_patch_spreadsheet_replaces_cells(client: AsyncClient, author: Actor):
    doc_id = await _stored_id(client, author, {"cells": {"0:0": "before"}})

    # PATCH replaces the content snapshot wholesale (snapshot path).
    patch_response = await client.patch(
        author.g(f"/files/{doc_id}"),
        headers=author.headers,
        json={"content": {"cells": {"0:0": "after", "5:7": 99}}},
    )
    assert patch_response.status_code == 200, patch_response.text
    cells = _sheet(patch_response.json()["content"])["cells"]
    assert cells == {"0:0": "after", "5:7": 99}


@pytest.mark.parametrize(
    ("case", "content"),
    [
        ("a cell holding an object", {"cells": {"0:0": {"nested": "object"}}}),
        (
            "a schema version we do not speak",
            {"schema_version": 999, "cells": {"0:0": "ok"}},
        ),
        # isinstance(True, int) is True in Python, so the version guard has to
        # refuse a bool rather than read it as the integer 1.
        (
            "a bool where the version goes",
            {"schema_version": True, "cells": {"0:0": "ok"}},
        ),
        # Falsy non-dict containers must reach the type guard rather than being
        # coerced to an empty map.
        ("cells that are not a map", {"cells": []}),
        ("dimensions that are not a map", {"cells": {}, "dimensions": []}),
        (
            "v2 columns that are not a map",
            {"schema_version": 2, "cells": {}, "columns": []},
        ),
        (
            "v3 sheets that are not a list",
            {"schema_version": 3, "kind": "spreadsheet", "sheets": {}},
        ),
        # The cell invariant holds on every sheet, not only the first.
        (
            "a bad cell on a later v3 sheet",
            {
                "schema_version": 3,
                "kind": "spreadsheet",
                "sheets": [
                    {"id": "s1", "name": "Fine", "cells": {"0:0": "ok"}},
                    {"id": "s2", "name": "Broken", "cells": {"0:0": {"nested": 1}}},
                ],
            },
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
async def test_create_spreadsheet_refuses_a_malformed_payload(
    client: AsyncClient, author: Actor, case: str, content: dict
):
    """Every shape the sheet parser cannot trust is refused the same way, so a
    malformed payload never lands half-read."""
    response = await _create_sheet(client, author, content, name="Bad Sheet")

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "FILE_SPREADSHEET_INVALID_PAYLOAD"


async def test_create_spreadsheet_canonicalizes_cell_keys(
    client: AsyncClient, author: Actor
):
    """Non-canonical numeric keys ("01:2", "0001:0002") round-trip as
    canonical "r:c" — JS emits ``String(number)`` form when the snapshot
    is hydrated into a Y.Map, so any leading-zero form stored verbatim
    would silently disappear after a collaboration round-trip."""
    content = await _stored_content(
        client,
        author,
        {
            "cells": {
                "01:2": "padded row",
                "3:04": "padded col",
                "0005:0006": "padded both",
                "7:8": "canonical",
            }
        },
    )

    assert _sheet(content)["cells"] == {
        "1:2": "padded row",
        "3:4": "padded col",
        "5:6": "padded both",
        "7:8": "canonical",
    }


@pytest.mark.parametrize(
    "content",
    [None, {"schema_version": 3, "kind": "spreadsheet", "sheets": []}],
    ids=["no content at all", "an empty list of sheets"],
)
async def test_a_workbook_with_nothing_in_it_opens_on_one_empty_sheet(
    client: AsyncClient, author: Actor, content: dict | None
):
    """A fresh spreadsheet gets an empty cell map, a 100x26 canvas and empty
    formatting structures. An editor with no sheet at all has nothing to
    render, so an explicitly empty list is repaired into the same thing rather
    than persisted."""
    stored = await _stored_content(client, author, content, name="Empty Sheet")

    assert stored["kind"] == "spreadsheet"
    assert stored["schema_version"] == 3
    assert len(stored["sheets"]) == 1
    assert _sheet(stored)["id"] == "s1"
    assert _sheet(stored)["name"] == "Sheet1"
    assert _sheet(stored)["cells"] == {}
    assert _sheet(stored)["dimensions"] == {"rows": 100, "cols": 26}
    assert _sheet(stored)["columns"] == {}
    assert _sheet(stored)["rows"] == {}
    assert _sheet(stored)["cellStyles"] == {}
    assert _sheet(stored)["frozen"] == {"rows": 0, "cols": 0}


async def test_v1_payload_upcasts_to_current(client: AsyncClient, author: Actor):
    """An explicit v1 payload (no formatting keys) is accepted and saved
    as the current version with empty formatting structures — existing
    files keep working without a data migration and never 422."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 1,
            "kind": "spreadsheet",
            "dimensions": {"rows": 100, "cols": 26},
            "cells": {"0:0": "kept"},
        },
        name="Legacy Sheet",
    )

    assert content["schema_version"] == 3
    assert _sheet(content)["cells"] == {"0:0": "kept"}
    assert _sheet(content)["columns"] == {}
    assert _sheet(content)["rows"] == {}
    assert _sheet(content)["cellStyles"] == {}
    assert _sheet(content)["frozen"] == {"rows": 0, "cols": 0}


async def test_v2_formatting_round_trips(client: AsyncClient, author: Actor):
    """A full v2 payload round-trips: widths, styles, number formats,
    per-cell overrides, and the frozen-pane hint."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "kind": "spreadsheet",
            "dimensions": {"rows": 100, "cols": 26},
            "cells": {"0:0": "Revenue", "1:0": 1234.5},
            "columns": {
                "0": {
                    "width": 180,
                    "format": {"type": "currency", "currency": "USD", "decimals": 2},
                    "style": {"bold": True, "align": "right"},
                }
            },
            "rows": {"0": {"height": 32, "style": {"bold": True}}},
            "cellStyles": {
                "1:0": {
                    "style": {"fill": "#ffeecc"},
                    "format": {"type": "fixed", "decimals": 1},
                }
            },
            "frozen": {"rows": 1, "cols": 1},
        },
        name="Formatted",
    )

    assert content["schema_version"] == 3
    assert _sheet(content)["columns"] == {
        "0": {
            "width": 180,
            "format": {"type": "currency", "currency": "USD", "decimals": 2},
            "style": {"bold": True, "align": "right"},
        }
    }
    assert _sheet(content)["rows"] == {"0": {"height": 32, "style": {"bold": True}}}
    assert _sheet(content)["cellStyles"] == {
        "1:0": {
            "style": {"fill": "#ffeecc"},
            "format": {"type": "fixed", "decimals": 1},
        }
    }
    assert _sheet(content)["frozen"] == {"rows": 1, "cols": 1}


async def test_v2_clamps_sizes_and_frozen(client: AsyncClient, author: Actor):
    """Out-of-range widths/heights/decimals/frozen are clamped, not
    rejected."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "cells": {},
            "dimensions": {"rows": 100, "cols": 26},
            "columns": {
                "0": {"width": 99999, "format": {"type": "fixed", "decimals": 99}}
            },
            "rows": {"0": {"height": 0}},
            "frozen": {"rows": 50, "cols": -3},
        },
        name="Clamp",
    )

    assert _sheet(content)["columns"]["0"]["width"] == 2000
    assert _sheet(content)["columns"]["0"]["format"]["decimals"] == 10
    assert _sheet(content)["rows"]["0"]["height"] == 16
    assert _sheet(content)["frozen"] == {"rows": 8, "cols": 0}


async def test_v2_drops_malformed_formatting(client: AsyncClient, author: Actor):
    """A bad ``align``, bad hex, and an unknown style key are stripped — the
    file still saves (201, NOT 400) because formatting failures must never
    block the user's actual data."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "cells": {"0:0": "data"},
            "columns": {
                "0": {
                    "style": {
                        "align": "diagonal",
                        "color": "red",
                        "squiggly": True,
                        "bold": True,
                    },
                    "format": {"type": "bogus"},
                },
                "not-an-index": {"width": 100},
            },
            "cellStyles": {"garbage-key": {"style": {"bold": True}}},
        },
        name="Lenient",
    )

    # Only the valid ``bold`` survived; the column entry is kept.
    assert _sheet(content)["columns"] == {"0": {"style": {"bold": True}}}
    assert _sheet(content)["cellStyles"] == {}


async def test_v2_canonicalizes_formatting_keys(client: AsyncClient, author: Actor):
    """Leading-zero index/cell keys collapse to canonical form so they
    survive the JS Y.Map round-trip, exactly like the cell map."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "cells": {},
            "columns": {"007": {"width": 90}},
            "cellStyles": {"01:02": {"style": {"italic": True}}},
        },
        name="Canon",
    )

    assert _sheet(content)["columns"] == {"7": {"width": 90}}
    assert _sheet(content)["cellStyles"] == {"1:2": {"style": {"italic": True}}}


async def test_v2_border_round_trips_and_drops_bad_edges(
    client: AsyncClient, author: Actor
):
    """Valid border edges round-trip (color lowercased); a bad style
    enum, a bad hex, and an unknown edge are dropped without 400."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "cells": {"0:0": "x"},
            "cellStyles": {
                "0:0": {
                    "style": {
                        "border": {
                            "top": {"style": "thin", "color": "#ABCDEF"},
                            "bottom": {"style": "huge", "color": "#000000"},
                            "left": {"style": "thick", "color": "red"},
                            "diagonal": {"style": "thin", "color": "#000000"},
                        }
                    }
                }
            },
        },
        name="Borders",
    )

    assert _sheet(content)["cellStyles"] == {
        "0:0": {"style": {"border": {"top": {"style": "thin", "color": "#abcdef"}}}}
    }


async def test_v2_tier1_style_and_number_options(client: AsyncClient, author: Actor):
    """Underline/strike/valign/fontSize and number-format grouping +
    negatives round-trip; fontSize is clamped, bad valign/negatives are
    dropped without a 400."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "cells": {"0:0": -5},
            "cellStyles": {
                "0:0": {
                    "style": {
                        "underline": True,
                        "strike": False,
                        "valign": "sideways",
                        "fontSize": 9999,
                    },
                    "format": {
                        "type": "fixed",
                        "decimals": 2,
                        "grouping": True,
                        "negatives": "redParens",
                    },
                },
                "1:0": {
                    "format": {
                        "type": "currency",
                        "currency": "EUR",
                        "decimals": 0,
                        "negatives": "bogus",
                    }
                },
            },
        },
        name="Tier1",
    )

    assert _sheet(content)["cellStyles"]["0:0"]["style"] == {
        "underline": True,
        "strike": False,
        "fontSize": 96,
    }
    assert _sheet(content)["cellStyles"]["0:0"]["format"] == {
        "type": "fixed",
        "decimals": 2,
        "grouping": True,
        "negatives": "redParens",
    }
    # Unknown negative style dropped; currency otherwise preserved.
    assert _sheet(content)["cellStyles"]["1:0"]["format"] == {
        "type": "currency",
        "currency": "EUR",
        "decimals": 0,
    }


# ---------------------------------------------------------------------------
# v3: multiple sheets
# ---------------------------------------------------------------------------


async def test_v3_multiple_sheets_round_trip(client: AsyncClient, author: Actor):
    """A workbook keeps its sheets, their order, and each sheet's own cells,
    dimensions, and formatting."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                {
                    "id": "s1",
                    "name": "Summary",
                    "dimensions": {"rows": 100, "cols": 26},
                    "cells": {"0:0": "=SUM(Data!A1:A3)"},
                    "frozen": {"rows": 1, "cols": 0},
                },
                {
                    "id": "sabc123",
                    "name": "Data",
                    "dimensions": {"rows": 100, "cols": 26},
                    "cells": {"0:0": 1, "1:0": 2, "2:0": 3},
                    "columns": {"0": {"width": 140}},
                },
            ],
        },
        name="Workbook",
    )

    assert content["schema_version"] == 3
    assert [s["name"] for s in content["sheets"]] == ["Summary", "Data"]
    assert [s["id"] for s in content["sheets"]] == ["s1", "sabc123"]
    # The cross-sheet formula is opaque text to the backend and survives.
    assert _sheet(content, 0)["cells"] == {"0:0": "=SUM(Data!A1:A3)"}
    assert _sheet(content, 0)["frozen"] == {"rows": 1, "cols": 0}
    assert _sheet(content, 1)["cells"] == {"0:0": 1, "1:0": 2, "2:0": 3}
    assert _sheet(content, 1)["columns"] == {"0": {"width": 140}}


async def test_v2_payload_upcasts_to_single_sheet(client: AsyncClient, author: Actor):
    """A pre-multi-sheet payload is read as the workbook's one sheet, keeping
    its cells and formatting — existing files never 422 and never lose
    data on their next save."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 2,
            "kind": "spreadsheet",
            "dimensions": {"rows": 100, "cols": 26},
            "cells": {"0:0": "kept"},
            "columns": {"0": {"width": 200}},
            "frozen": {"rows": 1, "cols": 1},
        },
        name="Legacy",
    )

    assert content["schema_version"] == 3
    assert len(content["sheets"]) == 1
    assert _sheet(content)["id"] == "s1"
    assert _sheet(content)["name"] == "Sheet1"
    assert _sheet(content)["cells"] == {"0:0": "kept"}
    assert _sheet(content)["columns"] == {"0": {"width": 200}}
    assert _sheet(content)["frozen"] == {"rows": 1, "cols": 1}


async def test_v3_sheet_names_are_sanitized_and_deduplicated(
    client: AsyncClient, author: Actor
):
    """Names are load-bearing (a formula addresses a sheet by name), so the
    forbidden characters are stripped, the length is capped at Excel's 31,
    and collisions are broken case-insensitively."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                {"id": "s1", "name": "Q1/Q2: *plan*?", "cells": {}},
                {"id": "s2", "name": "budget", "cells": {}},
                {"id": "s3", "name": "BUDGET", "cells": {}},
                {"id": "s4", "name": "   ", "cells": {}},
                {"id": "s5", "name": "x" * 50, "cells": {}},
            ],
        },
        name="Names",
    )

    names = [s["name"] for s in content["sheets"]]
    assert names[0] == "Q1Q2 plan"
    assert names[1] == "budget"
    # Case-insensitive collision — a reference resolves case-insensitively.
    assert names[2] == "BUDGET 2"
    # Nothing usable left; falls back to the positional default.
    assert names[3] == "Sheet4"
    assert names[4] == "x" * 31


async def test_v3_duplicate_sheet_ids_are_repaired(client: AsyncClient, author: Actor):
    """Two sheets sharing an id would share one Yjs container on the client,
    so the second is re-issued rather than rejected."""
    content = await _stored_content(
        client,
        author,
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                {"id": "s1", "name": "One", "cells": {"0:0": "a"}},
                {"id": "s1", "name": "Two", "cells": {"0:0": "b"}},
            ],
        },
        name="Ids",
    )

    assert len({s["id"] for s in content["sheets"]}) == 2
    assert _sheet(content, 1)["cells"] == {"0:0": "b"}


# ── import ───────────────────────────────────────────────────────────────────


async def test_import_returns_sheets_without_writing_the_file(
    client: AsyncClient, author: Actor
):
    """The file is the permission scope, not the destination — the editor
    adds what comes back to its live workbook itself."""
    doc_id = await _stored_id(client, author, name="Inventory")

    response = await client.post(
        author.g(f"/files/{doc_id}/spreadsheet/import"),
        headers=author.headers,
        files={"file": ("Q1 sales.csv", b"Item,Qty\nWidget,3\n", "text/csv")},
    )

    assert response.status_code == 200, response.text
    sheets = response.json()["sheets"]
    assert len(sheets) == 1
    assert sheets[0]["name"] == "Q1 sales"
    assert sheets[0]["cells"] == {
        "0:0": "Item",
        "0:1": "Qty",
        "1:0": "Widget",
        "1:1": 3,
    }

    # The file itself is untouched.
    response = await client.get(author.g(f"/files/{doc_id}"), headers=author.headers)
    assert _sheet(response.json()["content"])["cells"] == {}


async def test_import_refuses_a_file_it_cannot_read(client: AsyncClient, author: Actor):
    doc_id = await _stored_id(client, author, name="Inventory")

    response = await client.post(
        author.g(f"/files/{doc_id}/spreadsheet/import"),
        headers=author.headers,
        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "FILE_SPREADSHEET_UNREADABLE_FILE"


async def test_import_refuses_a_file_that_is_not_a_spreadsheet(
    client: AsyncClient, author: Actor
):
    created = await client.post(
        author.g("/files/"),
        headers=author.headers,
        json={
            "name": "Just notes",
            "initiative_id": author.initiative.id,
            "file_type": "lexical",
            "content": {},
        },
    )
    doc_id = created.json()["id"]

    response = await client.post(
        author.g(f"/files/{doc_id}/spreadsheet/import"),
        headers=author.headers,
        files={"file": ("x.csv", b"a,b\n", "text/csv")},
    )

    assert response.status_code == 400


async def test_import_needs_write_access(
    client: AsyncClient, author: Actor, acting_user
):
    """Reading a file through somebody else's file is still a write to it
    as far as permission goes — it is their workbook the sheets are for."""
    doc_id = await _stored_id(client, author, name="Inventory")
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=author.guild,
        initiative=author.initiative,
        initiative_role="member",
    )

    response = await client.post(
        reader.g(f"/files/{doc_id}/spreadsheet/import"),
        headers=reader.headers,
        files={"file": ("x.csv", b"a,b\n", "text/csv")},
    )

    assert response.status_code in (403, 404)
