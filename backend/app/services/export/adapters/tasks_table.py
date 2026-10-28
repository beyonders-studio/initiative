"""Tasks-table source adapter: "export tasks" is "list tasks, but render".

Queries through ``query_task_reads_for_export`` — the same visibility/filter/sort
pipeline as the ``list_tasks`` endpoint, executed under the caller's RLS
session (that query IS the authorization) — then shapes rows into the
backend-agnostic data payload the ``task-table`` template reads.

``params`` is the user's own filter selector, exactly what the list endpoint
accepts: ``{"conditions", "sorting", "tz", "include_archived"}``, the field
their view of the list is grouped by (``group_by``), the layout fields its
table shows (``columns``) and, for the detailed report, the parts of the task
page in its order (``detail``). It is what an ExportJob row persists, and what
the worker replays here at render time.

Rows are the task list's own (``TaskListRead``), and a column is a field of
the task's layout written by the kind of value it holds
(``app.services.export.values``), so an export reads as the list does.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


from app.core.identity_boundary import STORED_MENTION
from app.models.platform.user import User
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.task import TaskStatusCategory
from app.schemas.tenant.task import TaskListRead
from app.schemas.tenant.tool_layout import (
    PLUGIN_FIELD_PREFIX,
    PROPERTY_FIELD_PREFIX,
    TaskFieldId,
)
from app.services.export.adapters._common import (
    grouped_for_export,
    grouped_row_count,
    require_may_leave,
)
from app.services.export import values
from app.services.marketplace.widget_meta import in_language
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import et, export_locale
from app.services.export.markdown import blocks_from_markdown
from app.services.import_engine.mentions import mention_namer
from app.core.user_display import display_name
from app.services.export import limits as export_limits
from app.services.tenant import metadata as metadata_service
from app.services.tenant import task_queries

# A person's mention reaches a report as ``@[Display Name](id)``, the name
# written in as the report was made (``mention_namer``). A description or a
# comment prints through its Markdown blocks, which read it as ``@Display
# Name`` and a thing's as its name; the description column holds the list's
# plain-text excerpt, where only the person's markup is left to flatten.


#: How each field of a task's layout fills a table export's column: the field
#: as the registry names it, which heads the column, and what fills its cell.
#: ``None`` for one an export leaves out. Every ``TaskFieldId`` has an entry
#: (``tasks_table_test``), so a new layout field cannot quietly miss exports.
TASK_EXPORT_FIELDS: dict[
    str, Optional[tuple[str, Callable[[TaskListRead, str], Any]]]
] = {
    TaskFieldId.title: ("title", lambda t, loc: t.title),
    TaskFieldId.type: ("task_type_id", lambda t, loc: t.task_type.name),
    # The excerpt the list shows; its mentions are named where it is written.
    TaskFieldId.description: ("description", lambda t, loc: t.description_excerpt),
    TaskFieldId.assignees: (
        "assignee_ids",
        lambda t, loc: ", ".join(display_name(a) for a in t.assignees),
    ),
    TaskFieldId.startDate: ("start_date", lambda t, loc: values.date(t.start_date)),
    TaskFieldId.dueDate: ("due_date", lambda t, loc: values.date(t.due_date)),
    # Written in words only by the app.
    TaskFieldId.recurrence: None,
    TaskFieldId.checklist: (
        "checklist",
        lambda t, loc: (
            f"{t.checklist_progress.completed}/{t.checklist_progress.total}"
            if t.checklist_progress
            else ""
        ),
    ),
    TaskFieldId.priority: (
        "priority",
        lambda t, loc: et(f"priority.{t.priority.value}", loc),
    ),
    TaskFieldId.comments: ("comments", lambda t, loc: t.comment_count),
    TaskFieldId.blockers: ("blockers", lambda t, loc: t.blocked_by_open_count),
    TaskFieldId.tags: (
        "tag_ids",
        lambda t, loc: ", ".join(
            sorted((tag.name for tag in t.tags), key=str.casefold)
        ),
    ),
}

#: What a table export shows when its view names no columns: an export queued
#: before views sent them.
_DEFAULT_COLUMNS = ("title", "assignees", "dueDate", "priority")

#: The task page's parts in its order, where the export names none: the
#: shipped page on one column.
_DEFAULT_DETAIL = (
    "description",
    "status",
    "priority",
    "assignees",
    "dates",
    "tags",
    "properties",
    "checklist",
    "comments",
)

_WIDE = frozenset({"title", "description"})

_MAX_ROW_ID = 2**31 - 1


class TasksTableAdapter:
    source = "tasks"
    template_id = "task-table"
    # The one-task-per-page detailed report (layout=detailed, PDF only).
    detail_template_id = "task-detail"
    formats = ("pdf", "csv", "xlsx", "md")

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        if params.get("group_by") is None:
            return await task_queries.count_tasks_for_export(
                session, user, **_selector(params)
            )
        # Grouped, a task is a row under every group it is in, so the rows are
        # counted from the groups; past the ceiling, the count is over it.
        ids = await task_queries.task_ids_for_export(
            session, user, **_selector(params), limit=export_limits.EXPORT_MAX_ROWS + 1
        )
        if len(ids) > export_limits.EXPORT_MAX_ROWS:
            return len(ids)
        return await grouped_row_count(session, "tasks", params, ids)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        tasks = await task_queries.query_task_reads_for_export(
            session,
            user,
            **_selector(params),
            max_rows=export_limits.EXPORT_MAX_ROWS,
        )
        reach = await require_may_leave(
            session, {t.initiative_id for t in tasks if t.initiative_id is not None}
        )
        loc = export_locale(user)
        group_label, grouped = await grouped_for_export(
            session, "tasks", params, tasks, loc
        )
        data: dict[str, Any] = {
            "title": et("title.tasks", loc),
            "subtitle": et("summary.tasks", loc, count=len(tasks)),
            "footer": et("footer.tasks", loc),
            "page_of": et("pageOf", loc),
            "empty_message": et("empty.tasks", loc),
        }
        # The detailed report is one task per page, its parts in the task
        # page's order, PDF only; for other formats ``layout=detailed`` falls
        # through to the table.
        if format == "pdf" and params.get("layout") == "detailed":
            detail = [str(part) for part in params.get("detail") or _DEFAULT_DETAIL]
            details, comments = await task_queries.task_details_for_export(
                session, [t.id for t in tasks]
            )
            named = await mention_namer(
                session,
                [
                    [
                        details.get(t.id, (None, []))[0],
                        *(c.content for c in comments.get(t.id, [])),
                    ]
                    for t in tasks
                ],
                missing=et("fallback.formerMember", loc),
            )
            fields = {
                column.key: column
                for column in await task_columns(
                    session,
                    [part for part in detail if part not in _SECTIONS]
                    + (["startDate", "dueDate"] if "dates" in detail else []),
                    tasks,
                    loc,
                    params.get("tz"),
                )
            }
            placed = {
                part.removeprefix(PROPERTY_FIELD_PREFIX)
                for part in detail
                if part.startswith(PROPERTY_FIELD_PREFIX)
            }

            def parts(task: TaskListRead) -> list[dict[str, Any]]:
                description, checklist = details.get(task.id, (None, []))
                # Each part as the (label, value) lines or the section it draws.
                lines: list[tuple[str, Any]] = []
                out: list[dict[str, Any]] = []
                for part in detail:
                    if part == "description":
                        section: Any = blocks_from_markdown(named(description or ""))
                        out.append(
                            {
                                "kind": part,
                                "label": et("detail.description", loc),
                                "empty": et("detail.noDescription", loc),
                                "items": section,
                            }
                        )
                        continue
                    if part == "checklist":
                        section = [
                            {
                                "text": item.get("text", ""),
                                "done": bool(item.get("done")),
                            }
                            for item in checklist
                            if item.get("text")
                        ]
                    elif part == "comments":
                        section = [
                            {
                                "author": display_name(c.author) if c.author else "",
                                "date": c.created_at.strftime("%Y-%m-%d"),
                                "blocks": blocks_from_markdown(
                                    named(c.content or ""), line_breaks=True
                                ),
                                # A reply indents under its parent, as on screen.
                                "depth": depth,
                            }
                            for c, depth in _thread_comments(comments.get(task.id, []))
                        ]
                    else:
                        if part == "dates":
                            columns = [fields.get("startDate"), fields.get("dueDate")]
                        elif part != TaskFieldId.title:
                            columns = [fields.get(part)]
                        else:
                            columns = []
                        lines = [
                            (c.label, c.cell(task)) for c in columns if c is not None
                        ]
                        if part == "properties":
                            lines = [
                                (
                                    summary.name,
                                    values.property_value(
                                        summary, loc, params.get("tz")
                                    ),
                                )
                                for summary in task.properties
                                if str(summary.property_id) not in placed
                            ]
                        out += [
                            {"kind": "field", "label": label, "value": str(value)}
                            for label, value in lines
                            if value not in (None, "")
                        ]
                        continue
                    if section:
                        out.append(
                            {
                                "kind": part,
                                "label": et(f"detail.{part}", loc),
                                "items": section,
                            }
                        )
                return out

            data["tasks"] = [
                {
                    "title": t.title,
                    "project": t.project_name or "",
                    "group": group and f"{group_label}: {group}",
                    "parts": parts(t),
                }
                for group, t in grouped
            ]
            template_id = self.detail_template_id
        else:
            columns = await task_columns(
                session, params.get("columns"), tasks, loc, params.get("tz")
            )
            group = [{"key": "group", "label": group_label, "width": "1fr"}]
            data |= {
                "columns": (group if group_label else []) + values.head(columns),
                "rows": [
                    values.cells(columns, t)
                    | {
                        "group": group,
                        # Not a column: what the checklist layout ticks.
                        "done": t.task_status.category == TaskStatusCategory.done,
                    }
                    for group, t in grouped
                ],
                "untitled": et("fallback.untitled", loc),
            }
            # Layout variant within a format (markdown table vs checklist) —
            # part of the selector, so a queued job renders the same shape.
            if params.get("layout") == "checklist":
                data["layout"] = "checklist"
            template_id = self.template_id
        return RenderRequest(
            guild_id=guild_id,
            template_id=template_id,
            format=format,
            batch=(RenderItem(key="tasks", data=data),),
            initiative_ids=reach,
        )


async def task_columns(
    session: AsyncSession,
    names: Optional[list[str]],
    tasks: list[TaskListRead],
    locale: str,
    tz: Optional[str],
) -> list[values.Column]:
    """The columns a table of ``tasks`` shows: the layout fields ``names``
    (the shipped few where none), the title first, the project after it where
    the tasks are in more than one, and the status last, as the table draws
    it. A field an export leaves out, a property the community no longer has,
    and a plug-in field its install does not declare on a task are passed
    over; a plug-in value is only there where the task list draws it."""
    names = [str(name) for name in names or _DEFAULT_COLUMNS]
    if TaskFieldId.title not in names:
        names.insert(0, TaskFieldId.title)
    named = await mention_namer(
        session,
        [[t.description_excerpt] for t in tasks],
        missing=et("fallback.formerMember", locale),
    )
    # A row id is a Postgres ``integer``; a longer one names no row.
    property_ids = {
        name: int(name.removeprefix(PROPERTY_FIELD_PREFIX))
        for name in names
        if name.startswith(PROPERTY_FIELD_PREFIX)
        and name.removeprefix(PROPERTY_FIELD_PREFIX).isdigit()
        and int(name.removeprefix(PROPERTY_FIELD_PREFIX)) <= _MAX_ROW_ID
    }
    definitions = await metadata_service.load_definitions_by_ids(
        session, list(property_ids.values())
    )
    plugin_keys = {
        name: (int(install), key)
        for name in names
        if name.startswith(PLUGIN_FIELD_PREFIX)
        for install, _, key in [name.removeprefix(PLUGIN_FIELD_PREFIX).partition(":")]
        if install.isdigit() and int(install) <= _MAX_ROW_ID and key
    }
    declared = dict(
        await session.exec(
            select(GuildPlugin.id, GuildPlugin.definition["fields"]).where(
                GuildPlugin.id.in_({install for install, _ in plugin_keys.values()})
            )
        )
        if plugin_keys
        else []
    )

    columns: list[values.Column] = []
    for name in names:
        if name in TASK_EXPORT_FIELDS:
            entry = TASK_EXPORT_FIELDS[name]
            if entry is None:
                continue
            field, read = entry
            title = values.label(field, locale)
            if name == TaskFieldId.description:
                cell = lambda t, read=read: STORED_MENTION.sub(  # noqa: E731
                    lambda m: f"@{m.group(1)}", named(read(t, locale) or "")
                )
            else:
                cell = lambda t, read=read: read(t, locale)  # noqa: E731
        elif property_ids.get(name) in definitions:
            pid = property_ids[name]
            title = definitions[pid].name
            cell = lambda t, pid=pid: values.property_value(  # noqa: E731
                next((p for p in t.properties if p.property_id == pid), None),
                locale,
                tz,
            )
        elif name in plugin_keys:
            install, key = plugin_keys[name]
            decl = next(
                (
                    f
                    for f in declared.get(install) or []
                    if isinstance(f, dict)
                    and f.get("key") == key
                    and "task" in (f.get("on") or ())
                ),
                None,
            )
            if decl is None:
                continue
            given = decl.get("name")
            title = (
                in_language(given, locale) or key
                if isinstance(given, dict)
                else given or key
            )
            cell = lambda t, install=install, key=key, kind=decl.get("kind"): (  # noqa: E731
                values.plugin_value(
                    next(
                        (
                            v.value
                            for v in t.properties
                            if v.install_id == install and v.key == key
                        ),
                        None,
                    ),
                    str(kind or "text"),
                    locale,
                    tz,
                )
            )
        else:
            continue
        columns.append(
            values.Column(name, title, cell, "2fr" if name in _WIDE else "auto")
        )
    if len({task.project_id for task in tasks}) > 1:
        columns.insert(
            1,
            values.Column(
                "project", values.label("project_id", locale), lambda t: t.project_name
            ),
        )
    columns.append(
        values.Column(
            "status",
            values.label("task_status_id", locale),
            lambda t: t.task_status.name,
            "auto",
        )
    )
    return columns


#: The task page's parts that are sections of a page rather than fields.
_SECTIONS = frozenset({"description", "checklist", "comments", "dates", "properties"})


def _selector(params: dict) -> dict[str, Any]:
    """Whitelist the selector keys — a job row's params round-trip through
    JSON, so never splat them into the query functions unfiltered."""
    return {
        "conditions": params.get("conditions"),
        "sorting": params.get("sorting"),
        "tz": params.get("tz"),
        "include_archived": bool(params.get("include_archived", False)),
    }


def _thread_comments(comments: list) -> list[tuple]:
    """Order comments as a reply tree — each parent immediately followed by its
    replies (indented one level deeper), preserving the incoming chronological
    order within every level. Returns ``(comment, depth)`` pairs.

    A comment whose parent isn't in the set (parent deleted, or a reply loaded
    without its root) is treated as a root, so nothing is dropped."""
    ids = {c.id for c in comments}
    children: dict[int, list] = {}
    roots: list = []
    for comment in comments:
        parent_id = comment.parent_comment_id
        if parent_id is None or parent_id not in ids:
            roots.append(comment)
        else:
            children.setdefault(parent_id, []).append(comment)

    # Explicit-stack DFS rather than recursion: a reply chain can be
    # arbitrarily deep (``parent_comment_id`` is unrestricted and reachable
    # from the public API), so recursion could hit Python's limit and abort the
    # export on a 1000+ deep thread. Push siblings reversed so each is popped in
    # order and a parent is immediately followed by its own subtree (pre-order).
    ordered: list[tuple] = []
    stack: list[tuple] = [(root, 0) for root in reversed(roots)]
    while stack:
        comment, depth = stack.pop()
        ordered.append((comment, depth))
        for child in reversed(children.get(comment.id, [])):
            stack.append((child, depth + 1))
    return ordered
