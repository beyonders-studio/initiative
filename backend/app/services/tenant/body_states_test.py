from pycrdt import Doc, Map

from app.services.tenant.body_states import LEXICAL, SPREADSHEET, WHITEBOARD
from app.services.tenant.files_spreadsheet import normalize_spreadsheet_content
from app.testing import lexical_body

WORKBOOK = normalize_spreadsheet_content(
    {
        "schema_version": 3,
        "kind": "spreadsheet",
        "sheets": [
            {
                "id": "s1",
                "name": "Budget",
                "cells": {"0:0": "Rent", "0:1": 1200, "1:1": 3.5, "2:0": True},
                "columns": {"0": {"width": 160}},
                "rows": {"0": {"height": 30}},
                "cellStyles": {"0:0": {"style": {"bold": True, "fill": "#ffeeaa"}}},
                "frozen": {"rows": 1, "cols": 0},
            },
            {"id": "s2", "name": "Notes", "hidden": True, "cells": {"0:0": "x"}},
        ],
    }
)


def _merged(*updates: bytes) -> bytes:
    doc = Doc()
    for update in updates:
        doc.apply_update(update)
    return bytes(doc.get_update())


async def test_a_spreadsheet_reads_back_as_it_was_written() -> None:
    assert await SPREADSHEET.render(await SPREADSHEET.bootstrap(WORKBOOK)) == WORKBOOK


async def test_a_spreadsheet_write_leaves_a_cell_somebody_else_edited() -> None:
    """Only the entries that differ are written, so an edit made meanwhile to
    another cell survives the merge."""
    base = await SPREADSHEET.bootstrap(WORKBOOK)
    tab = Doc()
    tab.apply_update(base)
    before = tab.get_state()
    tab.get("sheets", type=Map)["s1"]["cells"]["5:5"] = "theirs"
    theirs = bytes(tab.get_update(before))
    ours = WORKBOOK | {
        "sheets": [
            WORKBOOK["sheets"][0]
            | {"cells": WORKBOOK["sheets"][0]["cells"] | {"0:0": "Mortgage"}},
            WORKBOOK["sheets"][1],
        ]
    }

    rendered = await SPREADSHEET.render(
        _merged(base, theirs, await SPREADSHEET.apply(base, ours))
    )

    assert rendered is not None
    cells = rendered["sheets"][0]["cells"]
    assert cells["0:0"] == "Mortgage" and cells["5:5"] == "theirs"


async def test_a_whiteboard_reads_back_as_it_was_drawn() -> None:
    scene = {
        "elements": [{"id": "a", "type": "rectangle", "x": 10, "y": 2.5}],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }

    state = await WHITEBOARD.bootstrap(scene)

    assert await WHITEBOARD.render(state) == scene
    assert WHITEBOARD.holds_body(state) is True
    assert WHITEBOARD.holds_body(bytes(Doc().get_update())) is False


async def test_a_rendering_keeps_a_mention_by_id_with_no_name() -> None:
    state = await LEXICAL.bootstrap(lexical_body("Hi ", mentioning=7, name="Ada"))

    rendered = await LEXICAL.render(state)

    assert rendered is not None
    [paragraph] = rendered["root"]["children"]
    [mention] = [node for node in paragraph["children"] if node["type"] == "mention"]
    assert mention["mentionUserId"] == 7 and "Ada" not in str(mention)
