"""Jira sprints → calendar events (design D11).

A sprint is a named stretch of time, which is what a calendar event is. So
each one becomes an event, once, on a calendar named after the board it ran
on — and each task that was in it is ``related_to`` it, rather than carrying
the sprint's two dates on forty rows.

Pure, like the rest of the mapping. Sprints arrive inside the issues
themselves — the Sprint field holds the whole sprint, not a reference — so
this reads them out of what the fetch already has. The only thing it cannot
know is what a board is called; the fetch looks that up and passes it in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

#: The Sprint field's type in Jira Software. Its field id differs per site,
#: so it is found in the field catalog by this.
SPRINT_FIELD_CUSTOM = "com.pyxis.greenhopper.jira:gh-sprint"

#: The name a calendar gets when its board's own name could not be read.
FALLBACK_CALENDAR_NAME = "Jira sprints"


@dataclass(frozen=True)
class Sprint:
    id: int
    name: str
    state: str
    board_id: int | None
    goal: str
    start: str | None
    end: str | None
    completed: str | None


def sprint_ref(sprint_id: int) -> str:
    """The name an event answers to in the job's link pass."""
    return f"jira-sprint:{sprint_id}"


def sprint_field_ids(catalog: Any) -> list[str]:
    """The ids of the site's Sprint fields — usually one."""
    if not isinstance(catalog, list):
        return []
    return [
        str(entry.get("id"))
        for entry in catalog
        if isinstance(entry, dict)
        and entry.get("id")
        and isinstance(entry.get("schema"), dict)
        and entry["schema"].get("custom") == SPRINT_FIELD_CUSTOM
    ]


def _iso(value: Any) -> str | None:
    """A Jira agile timestamp (``2024-03-04T09:30:00.000Z``) as UTC ISO."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def read_sprint(value: Any) -> Sprint | None:
    """One sprint as the Sprint field carries it, or ``None`` if it is not
    one — a site's data is somebody else's, and a malformed entry is skipped
    rather than trusted."""
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int):
        return None
    name = str(value.get("name") or "").strip()
    if not name:
        return None
    board = value.get("boardId")
    return Sprint(
        id=raw_id,
        name=name,
        state=str(value.get("state") or "").strip().lower(),
        board_id=board
        if isinstance(board, int) and not isinstance(board, bool)
        else None,
        goal=str(value.get("goal") or "").strip(),
        start=_iso(value.get("startDate")),
        end=_iso(value.get("endDate")),
        completed=_iso(value.get("completeDate")),
    )


def issue_sprints(issue: Any, field_ids: list[str]) -> list[Sprint]:
    """Every sprint an issue was in. An issue carried over from one sprint to
    the next lists both, and was in both."""
    if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
        return []
    fields = issue["fields"]
    found: list[Sprint] = []
    for field_id in field_ids:
        for value in fields.get(field_id) or []:
            sprint = read_sprint(value)
            if sprint is not None and sprint.id not in {s.id for s in found}:
                found.append(sprint)
    return found


def _event(sprint: Sprint) -> dict[str, Any] | None:
    """The event a sprint becomes, or ``None`` for one with no dates yet.

    A sprint that was planned but never started has no stretch of time to
    put on a calendar. One that started and never had an end set runs to
    the day it was completed, or is a single moment if it was not.
    """
    start = sprint.start or sprint.end
    end = sprint.end or sprint.completed or start
    if start is None or end is None:
        return None
    end = max(end, start)
    lines = []
    if sprint.goal:
        lines.append(f"**Goal:** {sprint.goal}")
    if sprint.state:
        lines.append(f"**State:** {sprint.state}")
    if sprint.completed:
        lines.append(f"**Completed:** {sprint.completed[:10]}")
    return {
        "title": sprint.name,
        "description": "\n\n".join(lines) or None,
        "start_at": start,
        "end_at": end,
        "all_day": False,
        "external_ref": sprint_ref(sprint.id),
    }


def build_sprint_calendars(
    sprints: dict[int, Sprint], board_names: dict[int, str]
) -> tuple[list[dict[str, Any]], set[int]]:
    """One calendar envelope per board, holding its sprints as events.

    Returns the envelopes and the ids of the sprints that became events.
    The rest had no dates, and the tasks in them keep no link to them.
    """
    by_board: dict[int | None, list[dict[str, Any]]] = {}
    placed: set[int] = set()
    ordered = sorted(sprints.values(), key=lambda s: (s.start or s.end or "", s.id))
    for sprint in ordered:
        event = _event(sprint)
        if event is None:
            continue
        by_board.setdefault(sprint.board_id, []).append(event)
        placed.add(sprint.id)

    calendars = []
    for board_id, events in by_board.items():
        name = (
            board_names.get(board_id) if board_id is not None else None
        ) or FALLBACK_CALENDAR_NAME
        calendars.append(
            {
                "type": "initiative-calendar",
                "schema_version": 1,
                "name": name,
                "description": None,
                "color": None,
                "events": events,
            }
        )
    return calendars, placed
