"""What every "somebody else's export" mapper shares.

A mapper takes a foreign payload and returns the envelope an ordinary import
already knows how to apply — the same document a project export writes. The
apply path never learns which product the file came from. Each source's own
reading of its format stays in its own module; what lives here is only the
part that would otherwise be copied four times.

Pure, like the mappers themselves: no session, no network, no storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core import recurrence
from app.models.tenant.task import RecurrenceStrategy, TaskStatusCategory

#: What an imported tag is coloured. A foreign label rarely carries a colour,
#: so this is the app's own default rather than a translation of anything — a
#: tag that already exists here keeps whatever colour it was given, because
#: ``ensure_tag`` matches by name and never repaints.
DEFAULT_TAG_COLOR = "#6366F1"

#: The gap between adjacent task positions. Matches what the app's own
#: reordering leaves room for, so a hand move after the import does not have
#: to renumber the board.
POSITION_STEP = 1000.0


@dataclass
class MappedProject:
    """A project envelope and what mapping it cost.

    The counts ride beside the envelope rather than inside it — the envelope
    has to validate as the same document a project export writes, and a
    casualty count is not part of that. They are what the plan shows somebody
    before they commit to the import.
    """

    envelope: dict[str, Any]
    #: Rows the source offered that were not usable as tasks.
    skipped_rows: int = 0
    #: Rich-text nodes no rule could render, summed over every description.
    dropped_nodes: int = 0
    #: Anything the reader wants to say about the file, shown before confirm.
    warnings: list[str] = field(default_factory=list)
    #: Each property definition the mapping declared, by name, with its type
    #: and how many tasks carry a value for it — what the review step lists.
    properties: dict[str, tuple[str, int]] = field(default_factory=dict)
    #: Source fields something filled that have no home here, by name.
    dropped_fields: list[str] = field(default_factory=list)


@dataclass
class SourceOption:
    """One importable thing inside an uploaded file — a TickTick list, a
    Vikunja project, or the single implicit project a Todoist CSV holds.

    ``key`` is what the import request quotes back to name the selection; it
    is the source's own identifier, so it is a string even where the source
    numbers them.
    """

    key: str
    name: str
    task_count: int


def iso_from_date(value: Any) -> str | None:
    """A plain ``YYYY-MM-DD`` to the envelope's datetime, at midnight UTC.

    A date with no time is the only thing several of these sources record for
    a deadline, and midnight is the reading the rest of the app already makes.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC).isoformat()


def iso_from_timestamp(value: Any) -> str | None:
    """An ISO 8601 stamp to a normalized one, or ``None`` if it is not one.

    Accepts the ``+0000`` and ``Z`` offsets these exports use alongside the
    ``+00:00`` form ``fromisoformat`` has always taken. Returns ``None``
    rather than raising: one unreadable stamp costs its own field, never the
    whole import.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return None


def repeat_fields(
    rule: str | None, due: str | None, tz: str | None, *, rolling: bool = False
) -> dict[str, Any]:
    """A source's repeat as a task's envelope fields: ``rule`` picked in
    ``tz`` (UTC without one) from the task's ``due`` date, the way the app's
    own form stores a pick. Empty when there is no due date to repeat from or
    the rule is not one a task can repeat by, so the task imports as a
    one-off rather than the import failing."""
    if not rule or not due:
        return {}
    try:
        text, shift = recurrence.stored(
            rule, datetime.fromisoformat(due), tz, kind="task"
        )
        if not rolling and recurrence.parse(text).rule.get("FREQ") == ["HOURLY"]:
            return {}
    except (ValueError, TypeError):
        return {}
    return {
        "recurrence": text,
        "recurrence_shift": shift,
        "recurrence_strategy": (
            RecurrenceStrategy.rolling if rolling else RecurrenceStrategy.fixed
        ),
    }


def dedupe_names(values: Any) -> list[str]:
    """Trimmed, case-insensitively deduplicated, first-seen casing kept.

    What tag names need everywhere: the app matches a tag by name and treats
    case as noise, so two spellings of one label must not become two tags.
    """
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        name = str(value or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


#: Words a column name is read for when the source says nothing else about
#: what its columns mean. Every product here lets people name their own
#: columns, and the name is the only evidence of intent that survives; a name
#: matching nothing lands in ``todo``, which is where unstarted work belongs.
_CATEGORY_KEYWORDS: tuple[tuple[TaskStatusCategory, tuple[str, ...]], ...] = (
    (
        TaskStatusCategory.done,
        ("done", "complete", "finished", "closed", "shipped", "resolved"),
    ),
    (
        TaskStatusCategory.in_progress,
        ("in progress", "doing", "working", "active", "current", "wip", "review"),
    ),
    (
        TaskStatusCategory.backlog,
        ("backlog", "inbox", "later", "someday", "icebox", "unassigned"),
    ),
    (
        TaskStatusCategory.todo,
        ("to do", "todo", "to-do", "planned", "next", "open", "not started"),
    ),
)


def category_for_name(name: str) -> TaskStatusCategory | None:
    """Which of our four columns a foreign column name reads as, if any.

    Checked most-specific first: "done" before "to do", so a column called
    "Ready for review" is in flight rather than not started.
    """
    lowered = (name or "").strip().lower()
    if not lowered:
        return None
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return None


def statuses_from_names(names: list[str]) -> list[dict[str, Any]]:
    """Ordered column names to the envelope's ``task_statuses``.

    The order given is the order the person arranged, so it is kept. The
    default — where a task with no column lands — is the first not-started
    column, the same reading the Jira mapping makes.
    """
    if not names:
        return fallback_statuses()
    statuses: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        statuses.append(
            {
                "name": name,
                "category": (category_for_name(name) or TaskStatusCategory.todo).value,
                "position": index,
                "is_default": False,
            }
        )
    default_index = next(
        (
            i
            for i, status in enumerate(statuses)
            if status["category"]
            in (TaskStatusCategory.todo.value, TaskStatusCategory.backlog.value)
        ),
        0,
    )
    statuses[default_index]["is_default"] = True
    return statuses


def fallback_statuses() -> list[dict[str, Any]]:
    """The one column an envelope needs when the source named none.

    The importer refuses a statusless envelope, so a file whose tasks sit in
    no list at all still has somewhere to land.
    """
    return [
        {
            "name": "To Do",
            "category": TaskStatusCategory.todo.value,
            "position": 0,
            "is_default": True,
        }
    ]


def collect_tag_names(tasks: list[dict[str, Any]]) -> list[str]:
    """Every tag the tasks carry, so the project can declare them once."""
    return dedupe_names(tag["name"] for task in tasks for tag in task.get("tags") or [])


def build_envelope(
    *,
    name: str,
    description: str | None,
    statuses: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    app_version: str,
    source_url: str | None = None,
    property_definitions: list[dict[str, Any]] | None = None,
    task_types: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The project envelope itself — the same shape a project export writes.
    Without ``task_types`` the project gets the ones a new project starts
    with."""
    return {
        "type": "initiative-project",
        "schema_version": 1,
        "app_version": app_version,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_instance_url": source_url,
        "project": {
            "name": name.strip() or "Imported project",
            "description": description or None,
        },
        "tags": [
            {"name": tag_name, "color": DEFAULT_TAG_COLOR}
            for tag_name in collect_tag_names(tasks)
        ],
        "task_statuses": statuses,
        **({"task_types": task_types} if task_types else {}),
        "property_definitions": property_definitions or [],
        "tasks": tasks,
        "layouts": [],
    }
