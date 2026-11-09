"""Migration 20261109_0598 writes the bodies older releases wrote in today's
shapes. Loaded by path and run on a guild holding rows written the old way."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pycrdt import Doc, Map, Text, XmlElement, XmlFragment, XmlText
from sqlalchemy import text

from app.core.file_types import FileType
from app.services.tenant.body_states import SPREADSHEET
from app.testing import create_file, create_guild, create_initiative, create_user

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(words: str, kind: str = "text") -> dict:
    return {
        "type": kind,
        "text": words,
        "format": 0,
        "style": "",
        "mode": "normal",
        "detail": 0,
        "version": 1,
    }


def _body(*children: dict) -> dict:
    return {
        "root": {
            "type": "root",
            "version": 1,
            "children": [
                {"type": "paragraph", "version": 1, "children": list(children)}
            ],
        }
    }


def _old_prose_state() -> bytes:
    """A paragraph holding a hashtag and a mention of user 7 named ``Ada``, as
    the editor's binding wrote them."""
    doc = Doc()
    paragraph = doc.get("root", type=XmlFragment).children.append(XmlText())
    paragraph.attributes["__type"] = "paragraph"
    paragraph.insert_embed(0, Map({"__type": "hashtag", "__format": 0}))
    paragraph.insert(1, "#idea")
    paragraph.insert_embed(
        6,
        XmlElement(
            "UNDEFINED",
            attributes={"__type": "mention", "__mention": "Ada", "__mentionUserId": 7},
        ),
    )
    return bytes(doc.get_update())


def _old_sheet_state() -> bytes:
    """A spreadsheet from before workbooks: its maps at the top."""
    doc = Doc()
    doc.get("cells", type=Map)["0:0"] = "kept"
    doc.get("columns", type=Map)["0"] = {"width": 200}
    doc.get("meta", type=Map)["rows"] = 50
    return bytes(doc.get_update())


async def test_bodies_take_today_s_shape(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    old_mention = {**_text("Ada", "mention"), "mentionUserId": 7}
    nobody = {**_text("Grace", "mention"), "mentionUserId": None}
    prose = await create_file(
        session,
        initiative,
        user,
        content=_body(_text("#idea", "hashtag"), old_mention, nobody),
        yjs_state=_old_prose_state(),
    )
    sheet = await create_file(
        session,
        initiative,
        user,
        file_type=FileType.sheet,
        content={
            "schema_version": 2,
            "kind": "spreadsheet",
            "dimensions": {"rows": 50, "cols": 26},
            "cells": {"0:0": "kept"},
            "columns": {"0": {"width": 200}},
        },
        yjs_state=_old_sheet_state(),
    )
    migration = _load("20261109_0598_bodies_take_todays_shape.py")

    def upgrade(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        migration._upgrade_schema(bind)

    await session.run_sync(upgrade)
    await session.commit()

    async def stored(file_id: int) -> tuple[dict, bytes]:
        row = (
            await (await session.connection()).execute(
                text(f"SELECT content, yjs_state FROM {schema}.files WHERE id = :id"),
                {"id": file_id},
            )
        ).one()
        return row[0], bytes(row[1])

    content, state = await stored(prose.id)
    assert content == _body(
        _text("#idea"),
        {**old_mention, "text": "", "mentionName": ""},
        {**nobody, "mentionName": "Grace"},
    )
    doc = Doc()
    doc.apply_update(state)
    [(paragraph, _)] = doc.get("root", type=Text).diff()
    nodes = [node for node, _ in paragraph.diff()]
    assert isinstance(nodes[0], Map) and nodes[0]["__type"] == "text"
    assert nodes[1] == "#idea"
    assert isinstance(nodes[2], XmlElement)
    assert dict(nodes[2].attributes) == {
        "__type": "mention",
        "__mention": "",
        "__mentionUserId": 7,
    }

    content, state = await stored(sheet.id)
    assert content == {
        "schema_version": 3,
        "kind": "spreadsheet",
        "sheets": [
            {
                "id": "s1",
                "name": "Sheet1",
                "dimensions": {"rows": 50, "cols": 26},
                "cells": {"0:0": "kept"},
                "columns": {"0": {"width": 200}},
                "rows": {},
                "cellStyles": {},
                "frozen": {"rows": 0, "cols": 0},
            }
        ],
    }
    doc = Doc()
    doc.apply_update(state)
    assert all(len(doc.get(key, type=Map)) == 0 for key in ("cells", "columns", "meta"))
    rendered = await SPREADSHEET.render(state)
    assert rendered is not None
    [live] = rendered["sheets"]
    assert (live["id"], live["name"], live["dimensions"]["rows"]) == (
        "s1",
        "Sheet1",
        50,
    )
    assert (live["cells"], live["columns"]) == ({"0:0": "kept"}, {"0": {"width": 200}})
