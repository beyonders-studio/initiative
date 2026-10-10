"""What a tool item becomes when it is shared to the marketplace.

A listing is the tool's export envelope, but not all of an export: what belongs
to the community rather than to the work stays behind. This module is that
difference, applied to every tool listing wherever it arrives from — a member
sharing an item, an operator's file, a registry — because a listing that
carried a person or a link would carry it into every community that installs
it.

What goes:

* **People.** Authors, assignees, attendees, comments and the people a mention
  or a person-type property names. A mention stays as the words it was written
  with, and names nobody.
* **Links to anything outside the item.** A task's link to another task in the
  same project survives; one to anything else is dropped, and a reference in a
  body is reduced to its label.
* **Uploads.** A file in the community's own storage stays there. A picture
  shared with the item is a new file in the marketplace's media
  (``listing_assets``), named by the path the marketplace serves it from; any
  other reference into a community's uploads is dropped.
* **When it happened.** Created, updated and archived times describe the
  original, not the copy.

What changes:

* **Dates become offsets.** Every date an item plans with is moved so that the
  earliest one falls on :data:`DATE_ANCHOR`. Installing moves them again, to
  the start date the installer picks, so a sprint template lands on next
  Monday rather than on the day its publisher happened to plan it.

Everything here is a pure function of the envelope, and applying it twice
changes nothing — the catalog compares a re-published version against what it
stored, so the stored form has to be a fixed point.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.core import recurrence
from app.core.references import REFERENCE_NODES, reference_as_text, text_node
from app.core.tools import Tool, tool_export_source

__all__ = [
    "DATE_ANCHOR",
    "anchor_dates",
    "export_for_listing",
    "shift_dates",
    "strip_for_listing",
]

#: The day a listing's earliest date falls on. A Monday, so a template planned
#: by the week reads naturally before anyone installs it.
DATE_ANCHOR = date(2000, 1, 3)

#: Property types whose value is a person, and whose value therefore stays
#: behind.
_PERSON_PROPERTY_TYPES = frozenset({"user_reference"})

#: Property types whose value is a date the item plans with.
_DATE_PROPERTY_TYPES = frozenset({"date", "datetime"})

#: Editor nodes that name a person.
_MENTION_NODES = frozenset({"mention", "custom-mention"})

#: Editor nodes that name something else in the community by id. A wikilink is
#: not among them: it names a page by title, and a link between two pages of
#: the same wiki is part of the wiki.
_REFERENCE_NODES = REFERENCE_NODES.keys() - {"wikilink"}

#: Editor nodes that carry a picture.
_IMAGE_NODES = frozenset({"image"})


# --- editor bodies ----------------------------------------------------------


def _mention_text(node: dict[str, Any]) -> str:
    name = str(node.get("mentionName") or node.get("text") or "").lstrip("@")
    return f"@{name}" if name else ""


def _in_marketplace(value: Any) -> bool:
    """Whether a reference names a picture in the marketplace's own media."""
    from app.services.marketplace.media import digest_of

    return digest_of(value) is not None


def _clean_editor_state(content: Any) -> Any:
    """An editor body with its mentions and references as plain words, and
    every picture that is not in the marketplace's own media gone."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        kind = node.get("type")
        if kind in _MENTION_NODES:
            return text_node(_mention_text(node), node.get("format") or 0)
        if kind in _REFERENCE_NODES:
            return reference_as_text(node)
        children = node.get("children")
        if isinstance(children, list):
            return {
                **node,
                "children": [
                    walk(child)
                    for child in children
                    if not (
                        isinstance(child, dict)
                        and child.get("type") in _IMAGE_NODES
                        and not _in_marketplace(child.get("src"))
                    )
                ],
            }
        return node

    return {**content, "root": walk(content["root"])}


def _clean_markdown(text: Any, handles: list[str]) -> Any:
    """A markdown body with its references reduced to their labels and each
    mention written as the name alone, without the number that picks out one
    account."""
    from app.services.import_engine.references import place_markdown_references

    if not isinstance(text, str) or not text:
        return text
    cleaned = place_markdown_references(text, lambda _ref: None) or ""
    for handle in handles:
        name = handle.split("#", 1)[0]
        cleaned = cleaned.replace(f"@{handle}", f"@{name}")
    return cleaned


def _clean_properties(values: Any) -> list[Any]:
    if not isinstance(values, list):
        return []
    return [
        value
        for value in values
        if not (
            isinstance(value, dict)
            and value.get("property_type") in _PERSON_PROPERTY_TYPES
        )
    ]


def _property_lists(node: Any) -> Iterator[tuple[dict[str, Any], str]]:
    """Every list of property values an envelope carries, wherever it sits —
    a tool row's own, each row inside it, a project's tasks'. A list is one
    only when every entry is a property value, so a key of the same name in a
    dashboard's configuration is left alone."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key in ("properties", "property_values")
                and isinstance(value, list)
                and all(isinstance(v, dict) and "property_type" in v for v in value)
            ):
                yield node, key
            else:
                yield from _property_lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _property_lists(item)


# --- per tool ---------------------------------------------------------------


def _strip_project(env: dict[str, Any]) -> None:
    env["exported_by_handle"] = None
    env["exported_at"] = datetime(
        DATE_ANCHOR.year, DATE_ANCHOR.month, DATE_ANCHOR.day
    ).isoformat()
    project = env.get("project")
    if isinstance(project, dict):
        project["archived_at"] = None
        project["description"] = _clean_markdown(project.get("description"), [])
    tasks = [task for task in env.get("tasks") or [] if isinstance(task, dict)]
    internal = {task.get("external_ref") for task in tasks if task.get("external_ref")}
    for task in tasks:
        handles = [
            *(task.get("mention_handles") or []),
            *(task.get("assignee_handles") or []),
        ]
        task["description"] = _clean_markdown(task.get("description"), handles)
        task["assignee_handles"] = []
        task["assignee_names"] = []
        task["comments"] = []
        task["mention_handles"] = []
        task["archived_at"] = None
        task["created_at"] = None
        task["updated_at"] = None
        task["links"] = [
            link
            for link in task.get("links") or []
            if isinstance(link, dict) and link.get("target_external_ref") in internal
        ]


def _strip_file(env: dict[str, Any]) -> None:
    env["mention_handles"] = []
    content = env.get("content")
    if env.get("file_type") == "native":
        env["content"] = _clean_editor_state(content)


def _strip_post(env: dict[str, Any]) -> None:
    env["mention_handles"] = []
    env["body"] = _clean_editor_state(env.get("body"))


def _strip_wiki(env: dict[str, Any]) -> None:
    for page in env.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page["content"] = _clean_editor_state(page.get("content"))
        page["mention_handles"] = []
        page["comments"] = []
        page["author_handle"] = None
        page["author_name"] = None
        page["created_at"] = None
        page["updated_at"] = None


def _strip_calendar(env: dict[str, Any]) -> None:
    for event in env.get("events") or []:
        if not isinstance(event, dict):
            continue
        event["attendees"] = []
        event["created_at"] = None


def _strip_queue(env: dict[str, Any]) -> None:
    for item in env.get("items") or []:
        if isinstance(item, dict):
            item["member"] = None


def _strip_gallery(env: dict[str, Any]) -> None:
    env["images"] = [
        image
        for image in env.get("images") or []
        if isinstance(image, dict) and _in_marketplace(image.get("storage_key"))
    ]
    if not _in_marketplace(env.get("cover")):
        env["cover"] = None


def _strip_nothing(env: dict[str, Any]) -> None:
    """A counter group and a dashboard name nobody and point at nothing a
    listing could carry. (A dashboard's configuration, which does, is dropped
    by the dashboard's own canonical form.)"""


_STRIPPERS: dict[Tool, Callable[[dict[str, Any]], None]] = {
    Tool.project: _strip_project,
    Tool.file: _strip_file,
    Tool.queue: _strip_queue,
    Tool.counter_group: _strip_nothing,
    Tool.calendar: _strip_calendar,
    Tool.dashboard: _strip_nothing,
    Tool.post: _strip_post,
    Tool.gallery: _strip_gallery,
    Tool.wiki: _strip_wiki,
}


def strip_for_listing(tool: Tool, envelope: dict[str, Any]) -> dict[str, Any]:
    """``envelope`` with everything that belongs to the community removed.

    Works on a copy; the argument is left as it was.
    """
    import copy

    from app.services.tenant.attachments import (
        extract_upload_urls,
        replace_upload_urls,
    )

    stripped = copy.deepcopy(envelope)
    _STRIPPERS[tool](stripped)
    # Every target carries properties; none of them takes a person along.
    for owner, key in list(_property_lists(stripped)):
        owner[key] = _clean_properties(owner[key])
    # Whatever still points into a community's uploads — a whiteboard's
    # picture, a link in a body — points nowhere once it leaves.
    return replace_upload_urls(
        stripped, {url: "" for url in extract_upload_urls(stripped)}
    )


# --- dates ------------------------------------------------------------------


def _property_date_slots(values: Any) -> Iterator[tuple[dict[str, Any], str]]:
    for value in values or []:
        if (
            isinstance(value, dict)
            and value.get("property_type") in _DATE_PROPERTY_TYPES
        ):
            yield value, "value_text"


def _recurrence_slot(owner: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str]]:
    # A template published before RRULE keeps its repeat's end in JSON.
    repeat = owner.get("recurrence")
    if isinstance(repeat, dict):
        yield repeat, "end_date"


def _repeating(tool: Tool, env: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every item whose repeat is RRULE lines, which keep their dates inside."""
    if tool not in (Tool.project, Tool.calendar):
        return
    for item in env.get("tasks" if tool is Tool.project else "events") or []:
        if isinstance(item, dict) and isinstance(item.get("recurrence"), str):
            yield item


def _date_slots(tool: Tool, env: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Every place an item keeps a date it plans with."""
    slots: list[tuple[dict[str, Any], str]] = []
    if tool is Tool.project:
        project = env.get("project")
        if isinstance(project, dict):
            slots += [(project, "start_date"), (project, "end_date")]
        for task in env.get("tasks") or []:
            if isinstance(task, dict):
                slots += [
                    (task, "start_date"),
                    (task, "due_date"),
                    (task, "completed_at"),
                ]
                slots += _recurrence_slot(task)
    elif tool is Tool.calendar:
        for event in env.get("events") or []:
            if isinstance(event, dict):
                slots += [
                    (event, "start_at"),
                    (event, "end_at"),
                    (event, "original_start"),
                ]
                slots += _recurrence_slot(event)
    # A date-typed property plans with its date, on whatever carries it.
    for owner, key in _property_lists(env):
        slots += _property_date_slots(owner[key])
    return slots


def _history_slots(tool: Tool, env: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Every place an item records when something happened to it. A listing
    carries none of them (:func:`strip_for_listing`); a backup carries them
    all."""
    slots: list[tuple[dict[str, Any], str]] = []
    if tool is Tool.project:
        project = env.get("project")
        if isinstance(project, dict):
            slots.append((project, "archived_at"))
        for task in env.get("tasks") or []:
            if isinstance(task, dict):
                slots += [
                    (task, "archived_at"),
                    (task, "created_at"),
                    (task, "updated_at"),
                    *_comment_slots(task),
                ]
    elif tool is Tool.calendar:
        for event in env.get("events") or []:
            if isinstance(event, dict):
                slots.append((event, "created_at"))
    elif tool is Tool.wiki:
        for page in env.get("pages") or []:
            if isinstance(page, dict):
                slots += [
                    (page, "created_at"),
                    (page, "updated_at"),
                    *_comment_slots(page),
                ]
    return slots


def _comment_slots(owner: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    return [
        (comment, "created_at")
        for comment in owner.get("comments") or []
        if isinstance(comment, dict)
    ]


def _parse(value: Any) -> date | datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if "T" in value or " " in value:
            return datetime.fromisoformat(value)
        return date.fromisoformat(value)
    except ValueError:
        return None


def _day_of(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def shift_dates(tool: Tool, envelope: dict[str, Any], days: int) -> dict[str, Any]:
    """``envelope`` with every date it carries moved by ``days``, the ones it
    plans with and the ones it records. Works on a copy; a value that is not a
    date is left as it was."""
    import copy

    shifted = copy.deepcopy(envelope)
    if days == 0:
        return shifted
    delta = timedelta(days=days)
    done = _move_series(tool, shifted, delta)
    for owner, key in [*_date_slots(tool, shifted), *_history_slots(tool, shifted)]:
        parsed = _parse(owner.get(key))
        if parsed is not None and (id(owner), key) not in done:
            owner[key] = (parsed + delta).isoformat()
    return shifted


def _move_series(
    tool: Tool, env: dict[str, Any], delta: timedelta
) -> set[tuple[int, str]]:
    """Move each repeating item by about ``delta`` on its own rule
    (:func:`recurrence.moved`), with the occurrences of its that have items of
    their own; the dates it moved, by owner and key."""
    done: set[tuple[int, str]] = set()
    items = env.get("tasks" if tool is Tool.project else "events") or []
    keys = (
        ("due_date", "start_date") if tool is Tool.project else ("start_at", "end_at")
    )
    for item in _repeating(tool, env):
        key = next((k for k in keys if _instant(item.get(k)) is not None), None)
        start = _instant(item.get(key)) if key else None
        if start is None:
            continue
        ref = item.get("external_ref")
        rows = [
            (other, was)
            for other in items
            if ref
            and isinstance(other, dict)
            and other.get("series_ref") == ref
            and (was := _instant(other.get("original_start"))) is not None
        ]
        series = recurrence.moved(
            item["recurrence"],
            start,
            int(item.get("recurrence_shift") or 0),
            delta,
            occurrences=[was for _, was in rows],
        )
        item["recurrence"] = series.text
        done |= _moved_by(item, keys, series.start - start)
        for row, was in rows:
            by = series.occurrences[was] - was
            done |= _moved_by(row, (*keys, "original_start"), by)
    return done


def _moved_by(
    owner: dict[str, Any], keys: tuple[str, ...], by: timedelta
) -> set[tuple[int, str]]:
    """``owner``'s dates at ``keys`` moved by ``by``; the slots it moved."""
    moved: set[tuple[int, str]] = set()
    for key in keys:
        parsed = _parse(owner.get(key))
        if parsed is not None:
            owner[key] = (
                parsed + by
                if isinstance(parsed, datetime)
                else parsed + timedelta(days=round(by / timedelta(days=1)))
            ).isoformat()
            moved.add((id(owner), key))
    return moved


def _instant(value: Any) -> datetime | None:
    """A date the envelope keeps, as an instant: a date at midnight UTC, as is
    a time without a zone. None for anything that is not a date."""
    parsed = _parse(value)
    if isinstance(parsed, datetime):
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if parsed is None:
        return None
    return datetime.combine(parsed, datetime.min.time(), timezone.utc)


def anchor_dates(tool: Tool, envelope: dict[str, Any]) -> dict[str, Any]:
    """``envelope`` with its earliest planning date on :data:`DATE_ANCHOR`,
    and every other date moved with it."""
    days = [
        _day_of(parsed)
        for owner, key in _date_slots(tool, envelope)
        if (parsed := _parse(owner.get(key))) is not None
    ]
    if not days:
        return envelope
    return shift_dates(tool, envelope, (DATE_ANCHOR - min(days)).days)


# --- the export -------------------------------------------------------------


async def export_for_listing(
    session: Any, *, tool: Tool, entity_id: int, user: Any, guild_id: int
) -> dict[str, Any]:
    """One item's export envelope, read the way its exporter reads it.

    The exporter's own fetch is the access check — the member must be able to
    read the item, or, for a project, to write it, exactly as exporting it to
    a file asks — and it runs on the member's session. The caller normalizes
    the result into a listing, which is where :func:`strip_for_listing` and
    :func:`anchor_dates` apply.
    """
    from app.services.export.adapters import ADAPTERS

    adapter = ADAPTERS[tool_export_source(tool)]
    request = await adapter.build(
        session,
        user=user,
        guild_id=guild_id,
        params={f"{tool.value}_id": entity_id},
        format="json",
    )
    return dict(request.batch[0].data)
