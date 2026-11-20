import json

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


def _element(element_id: str, version: int = 1, **fields: object) -> dict:
    return {
        "id": element_id,
        "type": "rectangle",
        "version": version,
        "versionNonce": 7,
        "index": f"a{element_id}",
        "isDeleted": False,
        **fields,
    }


def _scene(*elements: dict) -> dict:
    return {"elements": list(elements), "appState": {}, "files": {}}


def _held(state: bytes, element_id: str) -> dict:
    doc = Doc()
    doc.apply_update(state)
    return doc.get("excalidraw.elements", type=Map)[element_id]


async def test_a_whiteboard_write_leaves_an_element_somebody_else_drew() -> None:
    """Each element is its own entry, so drawing one meanwhile survives a
    write that changes another."""
    base = await WHITEBOARD.bootstrap(_scene(_element("a")))
    tab = Doc()
    tab.apply_update(base)
    before = tab.get_state()
    tab.get("excalidraw.elements", type=Map)["b"] = _element("b")
    theirs = bytes(tab.get_update(before))
    ours = _scene(_element("a", version=2, x=40))

    rendered = await WHITEBOARD.render(
        _merged(base, theirs, await WHITEBOARD.apply(base, ours))
    )

    assert rendered is not None
    assert [(e["id"], e.get("x")) for e in rendered["elements"]] == [
        ("a", 40),
        ("b", None),
    ]


async def test_a_whiteboard_write_deletes_by_tombstone() -> None:
    """An element the content leaves out is kept deleted, at a version the
    editors take over the copy they hold, and reads as absent."""
    base = await WHITEBOARD.bootstrap(_scene(_element("a", version=4), _element("b")))

    state = _merged(base, await WHITEBOARD.apply(base, _scene(_element("b"))))

    held = _held(state, "a")
    assert held["isDeleted"] is True and held["version"] == 5
    rendered = await WHITEBOARD.render(state)
    assert rendered is not None
    assert [e["id"] for e in rendered["elements"]] == ["b"]


async def test_a_whiteboard_write_moves_an_older_element_past_the_held_one() -> None:
    """Content holding an older copy of an element, such as a restored
    version, is written as newer than what the editors hold, or they would
    keep their own."""
    base = await WHITEBOARD.bootstrap(_scene(_element("a", version=9, x=1)))

    state = _merged(base, await WHITEBOARD.apply(base, _scene(_element("a", x=2))))

    held = _held(state, "a")
    assert held["x"] == 2 and held["version"] == 10


async def test_a_whiteboard_from_before_the_element_layout_is_converted() -> None:
    """A state that held the whole scene as one string holds no body in the
    element layout, still reads as its scene, and a write moves it over."""
    scene = _scene(_element("a"))
    legacy = Doc()
    legacy.get("excalidraw", type=Map)["scene"] = json.dumps(scene)
    state = bytes(legacy.get_update())

    assert WHITEBOARD.holds_body(state) is False
    assert await WHITEBOARD.render(state) == scene

    converted = _merged(state, await WHITEBOARD.apply(state, scene))

    assert WHITEBOARD.holds_body(converted) is True
    assert await WHITEBOARD.render(converted) == scene
    doc = Doc()
    doc.apply_update(converted)
    assert "scene" not in doc.get("excalidraw", type=Map)


async def test_a_rendering_keeps_a_mention_by_id_with_no_name() -> None:
    state = await LEXICAL.bootstrap(lexical_body("Hi ", mentioning=7, name="Ada"))

    rendered = await LEXICAL.render(state)

    assert rendered is not None
    [paragraph] = rendered["root"]["children"]
    [mention] = [node for node in paragraph["children"] if node["type"] == "mention"]
    assert mention["mentionUserId"] == 7 and "Ada" not in str(mention)
