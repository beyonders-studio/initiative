#!/usr/bin/env python3
"""Publish the tool records to the frontend, as data.

Each tool's record (``app.core.tools.TOOL_SPECS``) holds the facts about it
that are not a rule every tool follows: which tools start switched on, what
each exports to, which have rows of the whole community, and the kinds that
live inside each; the role keys of the built-in tools; what a file of each
type exports as; the colours a new row's colour is picked from; and the
pattern of the word after ``#`` that names a kind in running text. The frontend imports this file rather than
copying those facts by hand, so the two cannot drift.

Written beside the generated API types, by ``frontend/scripts/generate-api.sh``
after Orval has regenerated them (Orval empties that folder first), and
committed with them; ``scripts/ci/check codegen`` fails while it differs.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.file_types import FileType, export_formats
from app.core.palette import COLOR_PALETTE
from app.core.references import TRIGGER_WORD
from app.core.tools import KINDS, TOOL_SPECS
from app.models.platform.plugin_kind_code import ADOPTED_KIND_CODES
from app.models.tenant.initiative import PermissionKey

OUT = REPO_ROOT / "frontend" / "src" / "api" / "generated" / "tools.json"


def build() -> dict[str, object]:
    return {
        "tools": {
            tool.value: dataclasses.asdict(spec) for tool, spec in TOOL_SPECS.items()
        },
        # The kinds that live inside a tool, keyed by their wire name.
        "child_kinds": {
            kind.value: {
                field: getattr(kind, field)
                for field in (f.name for f in dataclasses.fields(kind))
                if field != "value"
            }
            for kind in KINDS.values()
            if kind.parent is not None
        },
        # Every role key of the built-in tools: each tool's pair, and the
        # capabilities inside one. A tool plug-in's are its kind's.
        "permission_keys": [key.value for key in PermissionKey],
        # What a file of each type exports as, in the order offered: the
        # editor's formats for its own types, the stored file for the rest.
        "file_types": {
            file_type.value: {"export_formats": list(export_formats(file_type))}
            for file_type in FileType
        },
        # The colours a new row's colour is picked from.
        "colors": list(COLOR_PALETTE),
        # The word after ``#`` that names a kind in running text, as a pattern.
        "trigger_word": TRIGGER_WORD,
        # The kinds of a tool that moved out of Initiative into a plug-in,
        # which the tool's old pages lead to.
        "moved_kinds": list(ADOPTED_KIND_CODES),
    }


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
