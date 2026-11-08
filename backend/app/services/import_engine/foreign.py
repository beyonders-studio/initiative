"""Which other products an export can come from, and how to read one.

One entry per product. Each names a pure mapper that turns that product's
export into the envelope an ordinary import already applies, so everything
past this module is the path a project export takes on its way back in — the
same seam ``jira_mapping`` sits on.

The registry is the only place a source is named. An unknown one is refused
here rather than at the route, so every caller gets the same answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.messages import ImportEngineMessages
from app.services.import_engine import (
    ticktick_mapping,
    todoist_mapping,
    vikunja_mapping,
)
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.mapping import MappedProject, SourceOption


@dataclass(frozen=True)
class ForeignSource:
    """One product an export can be read from.

    ``picks_one`` says what the wizard's middle step is for. Where a file
    holds several importable things — a TickTick account's lists, a Vikunja
    export's projects — the step chooses between them. Where it holds one,
    as a Todoist CSV does, the step collects the name to file it under
    instead, because the file does not carry one.
    """

    key: str
    preview: Callable[[str], list[SourceOption]]
    build: Callable[..., MappedProject]
    picks_one: bool


SOURCES: dict[str, ForeignSource] = {
    "todoist": ForeignSource(
        key="todoist",
        preview=todoist_mapping.preview,
        build=todoist_mapping.build_project_envelope,
        picks_one=False,
    ),
    "ticktick": ForeignSource(
        key="ticktick",
        preview=ticktick_mapping.preview,
        build=ticktick_mapping.build_project_envelope,
        picks_one=True,
    ),
    "vikunja": ForeignSource(
        key="vikunja",
        preview=vikunja_mapping.preview,
        build=vikunja_mapping.build_project_envelope,
        picks_one=True,
    ),
}


def get_source(key: str) -> ForeignSource:
    """The named source, or a 400 naming the path segment that was wrong."""
    source = SOURCES.get((key or "").strip().lower())
    if source is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_UNKNOWN_SOURCE)
    return source


def read_preview(source: ForeignSource, content: str) -> list[SourceOption]:
    """What the upload holds, or a 400 if it does not read as this product.

    Every mapper here parses somebody else's file, so the failure modes are
    whatever a truncated, half-edited or simply-wrong file produces. They are
    all the same answer to the person holding it: this is not that export.
    """
    try:
        return source.preview(content)
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_FILE_UNREADABLE) from exc


def build(
    source: ForeignSource, content: str, *, selection: str, app_version: str
) -> MappedProject:
    """The chosen part of the upload as a project envelope."""
    try:
        return source.build(content, selection=selection, app_version=app_version)
    except ImportEngineError:
        raise
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_FILE_UNREADABLE) from exc


__all__ = ["SOURCES", "ForeignSource", "build", "get_source", "read_preview"]
