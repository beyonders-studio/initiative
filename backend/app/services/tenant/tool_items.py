"""Tool rows named by ``(entity_type, entity_id)``, read as what a list of them
shows: a name, an icon, where it lives.

The tabs bar and the bookmarks both hold such pairs and both draw them
the same way, so the reading is here once. It runs on a routed session, which
decides: a tool the reader may not read does not load, and the caller leaves
it out — the same verdict its own page reaches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.tenant.file import File
from app.services.tenant.tags import TOOL_TAG_LINKS


@dataclass(frozen=True)
class ToolItemSpec:
    """How one tool's rows are read for a list of them.

    Derived per tool, not hand-listed: the model comes from the tag registry
    (every tool is taggable) and the label column from the model's own
    ``_display_field``.
    """

    model: type
    name_attr: str
    extra: Callable[[Any], dict[str, Any]] | None = None


def _file_extra(file: File) -> dict[str, Any]:
    version = file.current_version
    return {
        "file_type": file.file_type,
        "mime_type": getattr(version, "file_content_type", None),
        "original_filename": getattr(version, "original_filename", None),
    }


# The only per-tool code here: render-only fields beyond the common id/name.
# Everything else about a tool is derived below, so adding a tool needs no edit
# in this module.
_EXTRAS: dict[Tool, Callable[[Any], dict[str, Any]]] = {
    Tool.project: lambda project: {"icon": project.icon},
    Tool.file: _file_extra,
}

TOOL_ITEM_SPECS: dict[Tool, ToolItemSpec] = {
    tool: ToolItemSpec(
        model=TOOL_TAG_LINKS[tool].entity,
        name_attr=TOOL_TAG_LINKS[tool].entity.display_field(),
        extra=_EXTRAS.get(tool),
    )
    for tool in Tool
}


@dataclass(frozen=True)
class ToolItem:
    """One loaded tool, as a list shows it."""

    tool: Tool
    entity_id: int
    initiative_id: int | None
    name: str
    extra: dict[str, Any] = field(default_factory=dict)


async def load_tool_items(
    session: AsyncSession, refs: Iterable[tuple[str, int]]
) -> dict[tuple[str, int], ToolItem]:
    """The tools these pairs name that the reader may read, by pair. One query
    per tool that appears; a pair whose tool is unknown or unreadable is absent."""
    ids_by_type: dict[str, list[int]] = {}
    for entity_type, entity_id in refs:
        ids_by_type.setdefault(entity_type, []).append(entity_id)

    items: dict[tuple[str, int], ToolItem] = {}
    for tool, spec in TOOL_ITEM_SPECS.items():
        ids = ids_by_type.get(tool.value)
        if not ids:
            continue
        model = spec.model
        result = await session.exec(select(model).where(model.id.in_(ids)))  # type: ignore[attr-defined]
        for row in result.all():
            items[(tool.value, row.id)] = ToolItem(
                tool=tool,
                entity_id=row.id,
                initiative_id=getattr(row, "initiative_id", None),
                name=getattr(row, spec.name_attr),
                extra=spec.extra(row) if spec.extra else {},
            )
    return items
