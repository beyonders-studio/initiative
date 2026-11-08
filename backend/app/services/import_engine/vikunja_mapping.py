"""Vikunja's ``data.json`` → this app's project envelope.

Pure, like every mapper here.

**How the file is shaped.** A Vikunja export is a zip; ``data.json`` inside
it is a JSON array of projects, each carrying its ``buckets`` (the board
columns) and its ``tasks``. The import takes one project at a time and the
wizard asks which.

Vikunja writes task descriptions as HTML, and writes checklists inside that
HTML as ``taskItem`` list entries. Both are read here: the checklist is
lifted out into the task's own checklist, and what remains becomes markdown.
That is the same job ``adf.py`` does for Jira, for the same reason — the
description field on the far side is markdown, and a checklist is structure
rather than prose.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.relationships import RelationshipType
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

#: Vikunja's six levels onto our four. Its "DO NOW" and "urgent" both read as
#: urgent here; unset and low both read as low.
PRIORITY_BY_VIKUNJA: dict[int, TaskPriority] = {
    0: TaskPriority.low,
    1: TaskPriority.low,
    2: TaskPriority.medium,
    3: TaskPriority.high,
    4: TaskPriority.urgent,
    5: TaskPriority.urgent,
}

#: Vikunja relation kinds this app has a word for, in the direction the task
#: holding the relation can assert. The ones left out are the reverse halves
#: — "this task has subtask X" is a claim about X, and X makes it itself when
#: its own ``parenttask`` is read.
RELATION_TYPES: dict[str, RelationshipType] = {
    "parenttask": RelationshipType.part_of,
    "blocked": RelationshipType.depends_on,
    "related": RelationshipType.related_to,
    "duplicates": RelationshipType.related_to,
    "duplicateof": RelationshipType.related_to,
}

#: What a task whose bucket was deleted — or a project that never had any
#: — is placed under.
NO_BUCKET = "Tasks"

#: A Vikunja timestamp for "never".
_ZERO_TIME = "0001-01-01"

#: Vikunja's ``repeat_mode``: an interval from the due date (the default),
#: the same day each month, or an interval from when it was done.
_REPEAT_MONTHLY = 1
_REPEAT_FROM_DONE = 2
#: ``repeat_after`` is in seconds.
_DAY = 86400

#: Task-list entries Vikunja writes into a description.
_TASK_ITEM = re.compile(
    r'<li[^>]*data-checked="(true|false)"[^>]*data-type="taskItem"[^>]*>'
    r".*?<p>(.*?)</p>.*?</li>",
    flags=re.DOTALL,
)
_TASK_LIST = re.compile(r'<ul[^>]*data-type="taskList"[^>]*>.*?</ul>', flags=re.DOTALL)
_ANY_TAG = re.compile(r"<[^>]+>")


def extract_task_list_items(html: str) -> tuple[list[dict], str]:
    """The checklist Vikunja wrote into a description, and what is left."""
    if not html:
        return [], ""
    items: list[dict] = []
    for match in _TASK_ITEM.finditer(html):
        content = _ANY_TAG.sub("", match.group(2)).strip()
        if content:
            items.append({"content": content, "is_completed": match.group(1) == "true"})
    return items, _TASK_LIST.sub("", html)


def html_to_markdown(html: str) -> str:
    """Enough HTML to carry a description across without losing its shape."""
    if not html:
        return ""
    text = html
    for level in range(1, 7):
        text = re.sub(
            rf"<h{level}[^>]*>(.*?)</h{level}>",
            rf"{'#' * level} \1\n",
            text,
            flags=re.DOTALL,
        )
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"</?[ou]l[^>]*>", "", text)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<div[^>]*>(.*?)</div>", r"\1\n", text, flags=re.DOTALL)
    for tag, wrap in (("strong", "**"), ("b", "**"), ("em", "*"), ("i", "*")):
        text = re.sub(
            rf"<{tag}[^>]*>(.*?)</{tag}>", rf"{wrap}\1{wrap}", text, flags=re.DOTALL
        )
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    for tag in ("s", "strike"):
        text = re.sub(rf"<{tag}[^>]*>(.*?)</{tag}>", r"~~\1~~", text, flags=re.DOTALL)
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL
    )
    text = re.sub(
        r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*/?>', r"![\2](\1)", text
    )
    text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/?>', r"![](\1)", text)
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"```\n\1\n```\n", text, flags=re.DOTALL)
    text = re.sub(
        r"<blockquote[^>]*>(.*?)</blockquote>", r"> \1\n", text, flags=re.DOTALL
    )
    text = re.sub(r"<hr\s*/?>", "\n---\n", text)
    text = _ANY_TAG.sub("", text)
    for entity, char in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(entity, char)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _stamp(value: Any) -> str | None:
    """A Vikunja timestamp, or ``None`` for the zero value it writes when a
    date was never set."""
    text = str(value or "").strip()
    if not text or text.startswith(_ZERO_TIME):
        return None
    return iso_from_timestamp(text)


def _repeat(source: dict[str, Any]) -> tuple[str | None, bool]:
    """A task's repeat as a rule, and whether it counts from completion. An
    interval that is not whole days, or that is not a number, has no rule a
    task repeats by."""
    try:
        mode = int(source.get("repeat_mode") or 0)
        seconds = int(source.get("repeat_after") or 0)
    except (TypeError, ValueError):
        return None, False
    if mode == _REPEAT_MONTHLY:
        return "RRULE:FREQ=MONTHLY", False
    if seconds <= 0 or seconds % _DAY:
        return None, False
    days = seconds // _DAY
    rule = (
        f"RRULE:FREQ=WEEKLY;INTERVAL={days // 7}"
        if days % 7 == 0
        else f"RRULE:FREQ=DAILY;INTERVAL={days}"
    )
    return rule, mode == _REPEAT_FROM_DONE


def _projects(content: str) -> list[dict[str, Any]]:
    data = json.loads(content)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of projects")
    return [project for project in data if isinstance(project, dict)]


def preview(content: str) -> list[SourceOption]:
    """Every project in the export that has anything in it, largest first."""
    options: list[SourceOption] = []
    for project in _projects(content):
        tasks = project.get("tasks") or []
        if not tasks:
            continue
        options.append(
            SourceOption(
                key=str(project.get("id") or ""),
                name=str(project.get("title") or "Untitled project"),
                task_count=len(tasks),
            )
        )
    return sorted(options, key=lambda option: (-option.task_count, option.name))


def build_project_envelope(
    content: str,
    *,
    selection: str,
    app_version: str,
) -> MappedProject:
    """One Vikunja project as the envelope an ordinary import applies."""
    project = next(
        (p for p in _projects(content) if str(p.get("id") or "") == selection),
        None,
    )
    if project is None:
        raise ValueError("no such project in this export")

    bucket_names: dict[int, str] = {}
    ordered_columns: list[str] = []
    for bucket in project.get("buckets") or []:
        if not isinstance(bucket, dict):
            continue
        title = str(bucket.get("title") or "").strip()
        if not title:
            continue
        bucket_names[int(bucket.get("id") or 0)] = title
        if title not in ordered_columns:
            ordered_columns.append(title)

    tasks: list[dict[str, Any]] = []
    skipped = 0
    for index, source in enumerate(project.get("tasks") or []):
        if not isinstance(source, dict):
            skipped += 1
            continue
        title = str(source.get("title") or "").strip()
        if not title:
            skipped += 1
            continue

        checklist, remaining = extract_task_list_items(
            str(source.get("description") or "")
        )
        column = bucket_names.get(int(source.get("bucket_id") or 0)) or NO_BUCKET
        done = bool(source.get("done"))

        task: dict[str, Any] = {
            "title": title,
            "description": html_to_markdown(remaining) or None,
            "status_name": column,
            "priority": PRIORITY_BY_VIKUNJA.get(
                int(source.get("priority") or 0), TaskPriority.low
            ).value,
            "position": float(source.get("position") or 0.0)
            or (index + 1) * POSITION_STEP,
            "tags": [
                {"name": name, "color": DEFAULT_TAG_COLOR}
                for name in dedupe_names(
                    str((label or {}).get("title") or "")
                    for label in source.get("labels") or []
                    if isinstance(label, dict)
                )
            ],
            "assignee_handles": dedupe_names(
                str((who or {}).get("username") or "")
                for who in source.get("assignees") or []
                if isinstance(who, dict)
            ),
            "checklist": [
                {"text": item["content"], "done": item["is_completed"]}
                for item in checklist
            ],
            "properties": [],
            "links": [],
            "comments": [],
        }
        for field, key in (
            ("due_date", "due_date"),
            ("start_date", "start_date"),
            ("created_at", "created"),
            ("updated_at", "updated"),
        ):
            stamp = _stamp(source.get(key))
            if stamp:
                task[field] = stamp
        # Vikunja's dates are UTC, and so is the day its interval counts in. A
        # finished task holds no repeat here; the series goes on in its next.
        rule, rolling = _repeat(source)
        if not done:
            task.update(
                repeat_fields(rule, task.get("due_date"), None, rolling=rolling)
            )
        finished = _stamp(source.get("done_at"))
        if done and finished:
            task["completed_at"] = finished

        task_id = source.get("id")
        if task_id:
            task["external_ref"] = f"vikunja:{task_id}"

        related = source.get("related_tasks")
        if isinstance(related, dict):
            for kind, others in related.items():
                relation = RELATION_TYPES.get(str(kind).strip().lower())
                if relation is None or not isinstance(others, list):
                    continue
                for other in others:
                    other_id = (
                        (other or {}).get("id") if isinstance(other, dict) else None
                    )
                    if other_id:
                        task["links"].append(
                            {
                                "type": relation.value,
                                "target_external_ref": f"vikunja:{other_id}",
                            }
                        )
        tasks.append(task)

    # A task whose bucket was deleted still has to land somewhere, and a
    # project with no buckets at all is ordinary in Vikunja's list view.
    if (
        any(task["status_name"] == NO_BUCKET for task in tasks)
        and NO_BUCKET not in ordered_columns
    ):
        ordered_columns.append(NO_BUCKET)
    statuses = statuses_from_names(ordered_columns)
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
            name=str(project.get("title") or "Imported project"),
            description=html_to_markdown(str(project.get("description") or "")) or None,
            statuses=statuses,
            tasks=tasks,
            app_version=app_version,
        ),
        skipped_rows=skipped,
    )


__all__ = [
    "build_project_envelope",
    "extract_task_list_items",
    "html_to_markdown",
    "preview",
]
