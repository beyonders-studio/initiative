"""TickTick's CSV backup → this app's project envelope.

Pure, like every mapper here: text in, the document an ordinary import
already applies out.

**How the file is shaped.** A TickTick backup opens with a few lines of its
own metadata and only then the header row, so the header is found by looking
for it rather than by skipping a fixed number of lines — the preamble has
changed length between releases.

One file holds every list in the account. A list is what this app calls a
project, so the import takes one at a time and the wizard asks which. Within
a list, ``Column Name`` is the board column a task sits in, and those become
the project's statuses.

A row with a ``parentId`` is a subtask. This app nests once, so those land on
their parent's checklist rather than becoming tasks — which is also how they
read, since TickTick's own checklist items arrive the same way.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.models.tenant.task import TaskPriority
from app.services.import_engine.mapping import (
    DEFAULT_TAG_COLOR,
    POSITION_STEP,
    MappedProject,
    SourceOption,
    build_envelope,
    dedupe_names,
    iso_from_timestamp,
    repeat_fields,
    statuses_from_names,
)

#: TickTick's scale skips values, so this is a lookup rather than a range.
PRIORITY_BY_TICKTICK: dict[int, TaskPriority] = {
    0: TaskPriority.low,
    1: TaskPriority.low,
    3: TaskPriority.medium,
    5: TaskPriority.high,
}

#: ``Status`` values that mean the work is over. ``-1`` is TickTick's "won't
#: do", which is finished with rather than done, but it is still not open.
COMPLETED_STATUSES = {1, 2, -1}

#: What a task with no board column is placed under.
NO_COLUMN = "No Column"


def _find_header(lines: list[str]) -> int:
    """Where the real CSV starts, past TickTick's own preamble."""
    for index, line in enumerate(lines):
        if "List Name" in line and "Title" in line:
            return index
    return -1


def _rows(content: str) -> list[dict[str, str]]:
    text = content.lstrip("﻿")
    lines = text.splitlines(keepends=True)
    start = _find_header(lines)
    if start == -1:
        return []
    reader = csv.DictReader(io.StringIO("".join(lines[start:])))
    return [
        {(key or "").strip(): (value or "") for key, value in row.items()}
        for row in reader
    ]


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def _int(value: str, default: int) -> int:
    try:
        return int(float(value))
    except TypeError, ValueError:
        return default


def _list_name(row: dict[str, str]) -> str:
    """A list, qualified by its folder when it has one — two lists can share
    a name in different folders, and the import would otherwise merge them."""
    name = _cell(row, "List Name")
    folder = _cell(row, "Folder Name")
    return f"{folder} / {name}" if folder and name else name


def preview(content: str) -> list[SourceOption]:
    """Every list in the backup, largest first."""
    counts: dict[str, int] = {}
    for row in _rows(content):
        name = _list_name(row)
        if not name or not _cell(row, "Title") or _cell(row, "parentId"):
            continue
        counts[name] = counts.get(name, 0) + 1
    return sorted(
        (
            SourceOption(key=name, name=name, task_count=count)
            for name, count in counts.items()
        ),
        key=lambda option: (-option.task_count, option.name),
    )


def build_project_envelope(
    content: str,
    *,
    selection: str,
    app_version: str,
) -> MappedProject:
    """One TickTick list as the envelope an ordinary import applies."""
    rows = [row for row in _rows(content) if _list_name(row) == selection]
    column_names: list[str] = []
    tasks: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    children: list[tuple[str, str, bool]] = []
    skipped = 0

    for row in rows:
        title = _cell(row, "Title")
        if not title:
            skipped += 1
            continue

        status_value = _int(_cell(row, "Status"), 0)
        done = status_value in COMPLETED_STATUSES
        parent = _cell(row, "parentId")
        if parent:
            children.append((parent, title, done))
            continue

        column = _cell(row, "Column Name") or NO_COLUMN
        if column not in column_names:
            column_names.append(column)

        task: dict[str, Any] = {
            "title": title,
            "description": _cell(row, "Content") or None,
            "status_name": column,
            "priority": PRIORITY_BY_TICKTICK.get(
                _int(_cell(row, "Priority"), 0), TaskPriority.low
            ).value,
            # TickTick's own ``Order`` is an opaque sort key, so position
            # comes from the order of the file — which is the order it was
            # written in, and the order a person last saw.
            "position": (len(tasks) + 1) * POSITION_STEP,
            "tags": [
                {"name": tag, "color": DEFAULT_TAG_COLOR}
                for tag in dedupe_names(_cell(row, "Tags").split(","))
            ],
            "assignee_handles": [],
            "checklist": [],
            "properties": [],
            "links": [],
            "comments": [],
        }
        for field, column_name in (
            ("due_date", "Due Date"),
            ("start_date", "Start Date"),
            ("created_at", "Created Time"),
            ("completed_at", "Completed Time"),
        ):
            stamp = iso_from_timestamp(_cell(row, column_name))
            if stamp:
                task[field] = stamp
        # The Repeat column is an RRULE, picked in the task's own zone. A
        # finished task holds no repeat here; the series goes on in its next.
        if not done:
            task.update(
                repeat_fields(
                    _cell(row, "Repeat"),
                    task.get("due_date"),
                    _cell(row, "Timezone") or None,
                )
            )
        task_id = _cell(row, "taskId")
        if task_id:
            task["external_ref"] = f"ticktick:{task_id}"
            by_id[task_id] = task
        tasks.append(task)

    for parent_id, text, done in children:
        parent_task = by_id.get(parent_id)
        if parent_task is None:
            skipped += 1
            continue
        parent_task["checklist"].append({"text": text, "done": done})

    statuses = statuses_from_names(column_names)
    known = {status["name"] for status in statuses}
    default_name = next(
        (status["name"] for status in statuses if status["is_default"]),
        statuses[0]["name"],
    )
    for task in tasks:
        if task["status_name"] not in known:
            task["status_name"] = default_name

    return MappedProject(
        envelope=build_envelope(
            name=selection.rsplit(" / ", 1)[-1],
            description=None,
            statuses=statuses,
            tasks=tasks,
            app_version=app_version,
            source_url="https://ticktick.com",
        ),
        skipped_rows=skipped,
    )


__all__ = ["build_project_envelope", "preview"]
