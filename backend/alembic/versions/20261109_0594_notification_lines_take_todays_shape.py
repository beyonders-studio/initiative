"""notification lines take today's shape

A bell line keeps the payload it was written with, so lines from older releases
still spelled things the way those releases did, and the client and the
reaction rollup each carried a reader for them. This revision writes every
line in ``public.notifications`` the way the current writers would, so those
readers can go:

* ``target_path`` names today's address. In a community, a tool entity's old
  page (``/tasks/12``, ``/projects/3/settings``, ``/calendar-events/9``) is its
  ``/go`` reference, ``/go/event/9`` is ``/go/calendar-event/9``, an
  initiative's old page (``/initiatives/4/…``) is ``/i/4``, and the list pages
  that no longer exist (``/tasks``, ``/initiatives``, …) are the community
  home. Outside one, ``/settings/profile`` and ``/settings/account`` are
  ``/profile/account``. A line's ``smart_link`` names the same target.
* A reaction line carries its reactions as a list, each with the reaction's own
  id, beside its ``count`` and the roster of who reacted (``reactor_ids``,
  ``reactor_count``). A line from before the rollup named its one reaction in
  top-level fields; one from before the roster had none. A gesture without an
  id takes it from the community's ``reactions`` row it stands for, and one
  whose row is gone is dropped, with the line when nothing is left. A line with
  no ``target_path`` takes the thread its comment sits on.

Comment lines need nothing: a comment line from before the rollup is never
rolled into, so the comment rollup has no older shape to read.

The rewrite runs with user triggers off: nothing about the lines changed but
their spelling, so nothing is pushed for it.

Revision ID: 20261109_0594
Revises: 20261109_0593
Create Date: 2026-11-09
"""

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261109_0594"
down_revision = "20261109_0593"
branch_labels = None
depends_on = None

#: How many reactions a line remembers in detail, as the rollup caps it.
_MAX_REACTIONS = 20

#: The comment columns that name its thread, by the kind the ``/go`` resolver
#: speaks.
_THREADS = (
    ("task", "task_id"),
    ("file", "file_id"),
    ("project", "project_id"),
    ("counter-group", "counter_group_id"),
    ("calendar", "calendar_id"),
    ("dashboard", "dashboard_id"),
    ("post", "post_id"),
    ("wiki", "wiki_id"),
    ("contact", "contact_id"),
    ("wiki-page", "wiki_page_id"),
    ("collection", "collection_id"),
)

_PATHS = r"""
WITH moved AS (
    SELECT id, smart_link, original,
        CASE
            WHEN in_community AND p IN (
                '/initiatives', '/tasks', '/projects', '/files', '/queues',
                '/dashboards', '/counter-groups', '/calendars', '/calendar'
            ) THEN '/'
            WHEN in_community THEN regexp_replace(
                regexp_replace(
                    regexp_replace(
                        p,
                        '^/(task|project|file|calendar-event)s/([0-9]+)(/.*)?$',
                        '/go/\1/\2'
                    ),
                    '^/go/event/([0-9]+)$', '/go/calendar-event/\1'
                ),
                '^/initiatives/([0-9]+)(/.*)?$', '/i/\1'
            )
            WHEN p IN ('/settings/profile', '/settings/account')
                THEN '/profile/account'
            ELSE p
        END AS path
    FROM (
        SELECT id,
            data->>'target_path' AS original,
            data->>'smart_link' AS smart_link,
            '/' || ltrim(data->>'target_path', '/') AS p,
            nullif(data->>'community_id', '') IS NOT NULL AS in_community
        FROM public.notifications
        WHERE json_typeof(data->'target_path') = 'string'
    ) AS lines
)
UPDATE public.notifications AS n
SET data = (
    jsonb_set(n.data::jsonb, '{target_path}', to_jsonb(m.path))
    || CASE
        WHEN m.path <> '/' || ltrim(m.original, '/')
            AND m.smart_link LIKE '%&target=%'
            AND m.path ~ '^/[a-z0-9/-]*$'
        THEN jsonb_build_object(
            'smart_link',
            regexp_replace(
                m.smart_link, '&target=.*$', '&target=' || replace(m.path, '/', '%2F')
            )
        )
        ELSE '{}'::jsonb
    END
)::json
FROM moved AS m
WHERE n.id = m.id AND m.path <> m.original
"""

#: Reaction lines that are not yet in today's shape.
_OLD_REACTION_LINES = """
SELECT id, data::text FROM public.notifications
WHERE type = 'comment_reaction' AND (
    json_typeof(data->'reactions') IS DISTINCT FROM 'array'
    OR json_typeof(data->'reactor_ids') IS DISTINCT FROM 'array'
    OR json_typeof(data->'count') IS DISTINCT FROM 'number'
    OR json_typeof(data->'target_path') IS DISTINCT FROM 'string'
    OR EXISTS (
        SELECT 1
        FROM json_array_elements(
            CASE WHEN json_typeof(data->'reactions') = 'array'
                THEN data->'reactions' ELSE '[]'::json END
        ) AS entry
        WHERE json_typeof(entry->'id') IS DISTINCT FROM 'number'
    )
)
ORDER BY id
"""


def _forced(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _with_rows_writable(bind, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with the table's RLS unforced and its user triggers off."""
    forced = _forced(bind, table)
    if forced:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    try:
        fn()
    finally:
        bind.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
        if forced:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _with_rows_readable(bind, tables: list[str], fn: Callable[[], None]) -> None:
    """Run ``fn`` with the tables' RLS unforced, so their owner reads every row."""
    forced = [table for table in tables if _forced(bind, table)]
    for table in forced:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    try:
        fn()
    finally:
        for table in forced:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _community(data: dict[str, Any]) -> int | None:
    value = data.get("community_id")
    if _is_id(value):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _gestures(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The reactions a line names, in either older shape."""
    rolled = data.get("reactions")
    if isinstance(rolled, list):
        return [entry for entry in rolled if isinstance(entry, dict)]
    if data.get("emoji"):
        return [
            {
                "id": None,
                "emoji": data.get("emoji"),
                "reactor_id": data.get("reactor_id"),
                "reactor_name": data.get("reactor_name"),
            }
        ]
    return []


def _thread_path(bind, schema: str, comment_id: Any) -> str:
    """Where a line about a reaction to this comment opens: its thread."""
    if not _is_id(comment_id):
        return "/"
    arms = " ".join(
        f"WHEN {column} IS NOT NULL THEN '/go/{kind}/' || {column}"
        for kind, column in _THREADS
    )
    path = bind.execute(
        sa.text(
            f'SELECT CASE {arms} END FROM "{schema}".comments WHERE id = :id'  # noqa: S608
        ),
        {"id": comment_id},
    ).scalar()
    return path or "/"


def _smart_link(path: str, community_id: int) -> str:
    base = settings.APP_URL.rstrip("/") or "http://localhost:5173"
    return f"{base}/navigate?community_id={community_id}&target={quote(path, safe='')}"


def _today(bind, data: dict[str, Any], schema: str | None) -> dict[str, Any] | None:
    """The line in today's shape, or ``None`` when it names no reaction left."""
    community_id = _community(data)
    target_type, target_id = data.get("target_type"), data.get("target_id")
    before = _gestures(data)
    kept: list[dict[str, Any]] = []
    for entry in before:
        if not _is_id(entry.get("id")):
            if schema is None or not _is_id(entry.get("reactor_id")):
                continue
            found = bind.execute(
                sa.text(
                    f'SELECT id FROM "{schema}".reactions '  # noqa: S608
                    "WHERE created_by_kind = 'member' AND created_by = :reactor "
                    "AND target_type = :target_type AND target_id = :target_id "
                    "AND emoji = :emoji"
                ),
                {
                    "reactor": entry["reactor_id"],
                    "target_type": target_type,
                    "target_id": target_id,
                    "emoji": entry.get("emoji"),
                },
            ).scalar()
            if found is None:
                continue
            entry = {**entry, "id": found}
        kept.append(entry)
    if not kept or community_id is None:
        return None
    raw_count = data.get("count")
    had = raw_count if _is_id(raw_count) and raw_count > 0 else len(before)
    count = max(had - (len(before) - len(kept)), len(kept))
    rostered = data.get("reactor_ids")
    # A line that has rolled reactions past its cap knows more of its crowd
    # than the reactions it still holds; one that holds them all knows exactly.
    if isinstance(rostered, list) and had > len(before):
        roster = list(dict.fromkeys(v for v in rostered if _is_id(v)))
    else:
        roster = list(
            dict.fromkeys(e["reactor_id"] for e in kept if _is_id(e.get("reactor_id")))
        )
    latest = kept[-1]
    line = {
        **data,
        "emoji": latest.get("emoji"),
        "reactor_name": latest.get("reactor_name"),
        "reactor_id": latest.get("reactor_id"),
        "count": count,
        "reactor_count": len(roster),
        "reactor_ids": roster,
        "reactions": kept[-_MAX_REACTIONS:],
    }
    if not isinstance(data.get("target_path"), str):
        path = (
            _thread_path(bind, schema, target_id)
            if schema is not None and target_type == "comment"
            else "/"
        )
        line["target_path"] = path
        line["smart_link"] = _smart_link(path, community_id)
    return line


def _reaction_lines(bind) -> None:
    by_community: dict[int | None, list[tuple[int, dict[str, Any]]]] = {}
    for row_id, text in bind.execute(sa.text(_OLD_REACTION_LINES)).all():
        data = json.loads(text)
        by_community.setdefault(_community(data), []).append((row_id, data))

    rewritten: list[tuple[int, dict[str, Any] | None]] = []
    for community_id, lines in by_community.items():
        schema: str | None = None
        if (
            community_id is not None
            and bind.execute(
                sa.text("SELECT to_regclass(:t) IS NOT NULL"),
                {"t": f'"guild_{community_id}".reactions'},
            ).scalar()
        ):
            schema = f"guild_{community_id}"

        def run(lines=lines, schema=schema) -> None:
            for row_id, data in lines:
                rewritten.append((row_id, _today(bind, data, schema)))

        if schema is None:
            run()
        else:
            _with_rows_readable(
                bind, [f'"{schema}".reactions', f'"{schema}".comments'], run
            )

    def write() -> None:
        for row_id, line in rewritten:
            if line is None:
                bind.execute(
                    sa.text("DELETE FROM public.notifications WHERE id = :id"),
                    {"id": row_id},
                )
            else:
                bind.execute(
                    sa.text(
                        "UPDATE public.notifications SET data = CAST(:data AS json) "
                        "WHERE id = :id"
                    ),
                    {"id": row_id, "data": json.dumps(line)},
                )

    _with_rows_writable(bind, "public.notifications", write)


def upgrade() -> None:
    bind = op.get_bind()
    _with_rows_writable(
        bind, "public.notifications", lambda: bind.execute(sa.text(_PATHS))
    )
    _reaction_lines(bind)


def downgrade() -> None:
    """Nothing to undo: the older shapes were spellings of the same lines, and
    every reader since this revision reads the one it leaves."""
