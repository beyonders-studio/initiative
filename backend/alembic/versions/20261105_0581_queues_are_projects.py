"""Queues are projects

The queue tool is gone: a queue becomes a project and each of its items a
task. In ``guild_template`` and every ``guild_<id>``:

* **Projects** — each ``queues`` row is a ``projects`` row with a new id, in
  the same initiative, with the same name, description, author, dates, trash,
  archive, hold and comment state. A queue that was running says which round
  it was on, as the last line of its description.
* **Statuses and type** — each converted project has five statuses: Waiting
  (to do, its default), Up now (in progress), Held (in progress), Sitting out
  (to do) and Done; and one task type, Turn. They are written in English
  because a migration has no maker whose language to write them in.
* **Tasks** — each ``queue_items`` row is a ``tasks`` row with a new id in its
  queue's project, titled by its label and described by its notes, in the
  order the queue showed it. The item a running queue was on is Up now, a held
  item Held, a hidden item Sitting out and every other Waiting. Its trash and
  hold state come with it; its colour does not.
* **An item's member** is a ``related_to`` link from its task to them.
* **What named a queue or an item** names its project or task: sharing
  (``resource_grants``, ``guest_invite_grants``, ``share_requests``), metadata
  values, personal items, engagement levels, relationships (both ends), holds,
  moderation reports and acts; ``comments.queue_id`` becomes
  ``comments.project_id``. A row naming neither a mapped queue nor a mapped
  item is removed. Their search entries are removed and the search generation
  cleared, so the next start indexes the projects and tasks.
* **Lists** — a converted project shows its board and table and opens on the
  board.
* **Projects** — an initiative holding a queue, with queues on, has projects
  on, and a role there that could view or create queues can view or create
  projects.
* **Gone** — queue layouts and view preferences, the queue rules
  (``queues_enabled``, ``create_queues`` and the community's), change-log rows
  and queued plug-in events, queue event types and columns in webhook
  subscriptions (a subscription left with no event type is removed), the
  ``queues:*`` scopes an install was granted or its definition lists (and
  entries naming a queue kind), and queued exports and imports of a queue.
* **Edges** — a symmetric relationship whose ends now sort the other way is
  stored with its ends swapped, as one written now would be.
* **Structure** — the CHECKs that list a queue value are restated without it,
  the two that list a link's ends with the person (``user``), and the comment
  single-parent rule without ``queue_id``. ``entity_presence`` is dropped,
  then ``queue_items``, ``queues``, ``comments.queue_id`` and
  ``initiatives.queues_enabled``, with the policies and triggers that read
  them; a start renders the view and the policies again from the registries.

**Links in stored content** to a queue name its project, and to an item its
task (``app.core.legacy_references``), in every body 20261027_0546 rewrote: a
Lexical body read and written back through the editor when its Yjs state holds
one, a post's, and the markdown in every description, a task's checklist and
what an edit of it kept back, a task type's starting values, event locations
and comments.

The writes run with each table's row security unforced and its user triggers
held, both restored in the same transaction once they are done.

In ``public``: ``public.relationship_kind_code`` reads every kind but the two
queue kinds once no edge names one; codes 11 and 12 are retired. A
notification, and one still queued, names the project or task the way the
guild rows now do. A plug-in service's scope ceiling drops ``queues:*``, queue
listings are removed, and the saved queue view preferences go.

The queue → project and item → task maps live in temporary tables for the
length of the revision.

The downgrade puts back empty queue tables, ``comments.queue_id`` (in the
single-parent rule) and ``initiatives.queues_enabled``, and the kind codes. It
does not turn projects back into queues, and nothing it removed comes back.

Revision ID: 20261105_0581
Revises: 20261105_0580
Create Date: 2026-11-05
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from alembic import op
from pycrdt import Doc
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.util import await_only

from app.core.legacy_references import Moved, rewrite_body, rewrite_text
from app.db.guild_migrations import run_for_each_guild_schema
import app.services.editor_engine as editor_engine

revision = "20261105_0581"
down_revision = "20261105_0580"
branch_labels = None
depends_on = None


_QUEUE_TABLES = ("queue_items", "queues")
_QUEUE = "queue"
_ITEM = "queue_item"
_PERMISSIONS = ("queues_enabled", "create_queues")
#: Every rule key that names the queue: a role's, and the community's.
_RULE_KEYS = (
    *_PERMISSIONS,
    "initiative_tool.queue",
    *(f"initiative_role.member.{key}" for key in _PERMISSIONS),
)
_SCOPES = ("queues:read", "queues:write")
#: The change log's resource names for the tool and its rows.
_RESOURCES = ("queues", "queue_items")
_EVENT_PREFIXES = ("queues.", "queue_items.")
#: Columns a webhook subscription may list that only a queue had.
_QUEUE_FIELDS = (
    "queue_id",
    "current_item_id",
    "current_round",
    "is_active",
    "is_visible",
    "held_at_round",
    "queues_enabled",
)
#: Keys in an install's definition whose value names a kind.
_KIND_KEYS = ("entity", "kind", "tool", "itemKind")

#: Every guild table this revision reads or writes.
_TOUCHED = (
    *_QUEUE_TABLES,
    "projects",
    "task_statuses",
    "task_types",
    "tasks",
    "resource_grants",
    "guest_invite_grants",
    "share_requests",
    "metadata_values",
    "personal_items",
    "engagement_levels",
    "relationships",
    "search_entries",
    "content_holds",
    "moderation_reports",
    "moderation_actions",
    "comments",
    "initiatives",
    "initiative_rules",
    "tool_layouts",
    "view_preferences",
    "event_outbox",
    "plugin_event_outbox",
    "webhook_subscriptions",
    "webhook_deliveries",
    "guild_plugins",
    "data_jobs",
)
#: (table, kind column, id column) for every row that names a thing by kind.
_NAMED_BY_KIND = (
    ("resource_grants", "resource_type", "resource_id"),
    ("guest_invite_grants", "resource_type", "resource_id"),
    ("share_requests", "resource_type", "resource_id"),
    ("metadata_values", "entity_type", "entity_id"),
    ("personal_items", "entity_type", "entity_id"),
    ("engagement_levels", "entity_type", "entity_id"),
    ("relationships", "source_type", "source_id"),
    ("relationships", "target_type", "target_id"),
    ("content_holds", "target_type", "target_id"),
    ("moderation_reports", "target_type", "target_id"),
    ("moderation_actions", "target_type", "target_id"),
)

#: Each converted project's statuses: name, category, colour and icon, in
#: order. The first is its default.
_STATUSES = (
    ("Waiting", "todo", "#94A3B8", "circle"),
    ("Up now", "in_progress", "#60A5FA", "circle-play"),
    ("Held", "in_progress", "#FBBF24", "circle-pause"),
    ("Sitting out", "todo", "#94A3B8", "circle-off"),
    ("Done", "done", "#34D399", "circle-check"),
)
_TURN = "Turn"
#: A converted project's lists: board and table shown as shipped, the rest
#: hidden, opening on the board.
_LAYOUTS = (
    ("gantt", "jsonb_build_object('hidden', true)"),
    ("calendar", "jsonb_build_object('hidden', true)"),
    ("default", "jsonb_build_object('kind', 'board')"),
)

#: ``public.relationship_kind_code`` as 20261105_0580 left it.
_KIND_CODES_BEFORE = (
    ("calendar", 1),
    ("calendar_event", 2),
    ("counter", 3),
    ("counter_group", 4),
    ("dashboard", 5),
    ("file", 6),
    ("post", 9),
    ("project", 10),
    (_QUEUE, 11),
    (_ITEM, 12),
    ("tag", 13),
    ("task", 14),
    ("wiki", 15),
    ("wiki_page", 16),
    ("collection", 17),
    ("user", 18),
)
_KIND_CODES_AFTER = tuple(
    (kind, code) for kind, code in _KIND_CODES_BEFORE if kind not in (_QUEUE, _ITEM)
)

_QUEUE_MAP = "pg_temp._queue_projects"
_ITEM_MAP = "pg_temp._queue_item_tasks"
_IN_SCHEMA = "m.schema_name = current_schema()"
_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"

#: Every value a CHECK may list that names the queue, and the CHECKs holding
#: one or ``queue_id``.
_QUEUE_VALUES = (_QUEUE, _ITEM, *_RULE_KEYS)
_QUEUE_CHECK = (
    "'(" + "|".join(re.escape(value) for value in _QUEUE_VALUES) + r")'::|\mqueue_id\M"
)
_SINGLE_PARENT_CHECK = "ck_comments_single_parent"
#: The CHECKs on a link's two ends, which admit the person (20261105_0580).
_END_CHECKS = ("ck_relationships_source_type", "ck_relationships_target_type")
#: A symmetric edge is stored once, its lower node first: lifted while the
#: nodes are rewritten, since their codes and ids both move.
_SYMMETRIC_CHECK = "ck_relationships_symmetric_order"
_SYMMETRIC_TYPES = ("attached", "related_to")

_VIEW_PREFERENCES = (
    "scope_key ~ '(^|:)queue(_item)?(:|$)' OR scope_key = 'queues' "
    "OR starts_with(scope_key, 'queues:')"
)


def _kind_code_fn(codes: tuple[tuple[str, int], ...]) -> str:
    arms = " ".join(f"WHEN '{kind}' THEN {code}" for kind, code in codes)
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _table_exists(bind: Connection, table: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar())


def _columns(bind: Connection, table: str) -> list[str]:
    return list(
        bind.execute(
            text(
                "SELECT attname FROM pg_attribute WHERE attrelid = to_regclass(:t) "
                "AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
            ),
            {"t": table},
        ).scalars()
    )


@contextmanager
def _held(bind: Connection, tables: tuple[str, ...]) -> Iterator[None]:
    """Unforce each table's row security and hold its user triggers, restoring
    both on the tables still there afterwards. A failure rolls the whole
    revision back, these changes with it, so nothing is restored on that path."""
    forced: list[str] = []
    held: list[str] = []
    for table in tables:
        state = bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
        if state is None:
            continue
        if state:
            bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            forced.append(table)
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        held.append(table)
    yield
    for table in held:
        if _table_exists(bind, table):
            bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        if _table_exists(bind, table):
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


# --- CHECKs ------------------------------------------------------------------


def _drop_element(definition: str, value: str) -> str:
    """``definition`` without ``value`` in its array, however it is cast."""
    element = rf"\(?'{re.escape(value)}'::[a-z ]+\)?(?:::text)?"
    out = re.sub(rf",\s*{element}", "", definition, count=1)
    if out == definition:
        out = re.sub(rf"{element},\s*", "", definition, count=1)
    return out


def _drop_column(definition: str, column: str) -> str:
    """``definition`` without ``column`` in the list it is named in."""
    out = re.sub(rf",\s*{column}\b", "", definition, count=1)
    return out if out != definition else re.sub(rf"\b{column},\s*", "", definition)


def _forward_check(name: str, definition: str) -> str:
    for value in _QUEUE_VALUES:
        definition = _drop_element(definition, value)
    definition = _drop_column(definition, "queue_id")
    if name in _END_CHECKS and "'user'::" not in definition:
        definition = definition.replace("ARRAY[", "ARRAY['user'::text, ", 1)
    return definition


def _drop_checks(
    bind: Connection, pattern: str, names: tuple[str, ...] = ()
) -> dict[tuple[str, str], str]:
    """Drop the CHECKs in this schema whose definition matches ``pattern`` or
    whose name is one of ``names``, returning each one's definition."""
    rows = bind.execute(
        text(
            "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE contype = 'c' "
            "AND connamespace = current_schema()::regnamespace "
            "AND (pg_get_constraintdef(oid) ~ :pattern "
            "OR CAST(conname AS text) = ANY(CAST(:names AS text[])))"
        ),
        {"pattern": pattern, "names": list(names)},
    ).all()
    dropped: dict[tuple[str, str], str] = {}
    for table, name, definition in rows:
        bind.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        dropped[(table, name)] = definition
    return dropped


def _restore_checks(
    bind: Connection,
    dropped: dict[tuple[str, str], str],
    restate: Callable[[str, str], str],
) -> None:
    for (table, name), definition in dropped.items():
        bind.exec_driver_sql(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} {restate(name, definition)}"
        )


# --- structure ---------------------------------------------------------------


_READERS = """
    SELECT 'POLICY', p.polname, p.polrelid::regclass::text, p.polrelid
    FROM pg_depend d JOIN pg_policy p ON p.oid = d.objid
    LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_policy'::regclass AND d.refobjid = to_regclass(:t)
      AND (CAST(:c AS text) = '' OR a.attname = CAST(:c AS text))
    UNION
    SELECT 'TRIGGER', g.tgname, g.tgrelid::regclass::text, g.tgrelid
    FROM pg_depend d JOIN pg_trigger g ON g.oid = d.objid
    LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_trigger'::regclass AND NOT g.tgisinternal
      AND d.refobjid = to_regclass(:t) AND (CAST(:c AS text) = '' OR a.attname = CAST(:c AS text))
"""


def _drop_readers(bind: Connection, tables: tuple[str, ...], column: str = "") -> None:
    """Drop the policies and triggers that read ``column`` of the one table,
    or, with no column, those on other tables that read any of ``tables``."""
    owned = {
        bind.execute(text("SELECT to_regclass(:t)::oid"), {"t": t}).scalar()
        for t in tables
    }
    for table in tables:
        if not _table_exists(bind, table):
            continue
        rows = bind.execute(text(_READERS), {"t": table, "c": column}).all()
        for what, name, on, relid in rows:
            if column or relid not in owned:
                bind.exec_driver_sql(f'DROP {what} IF EXISTS "{name}" ON {on}')


def _drop_queue_structure(bind: Connection) -> None:
    bind.exec_driver_sql("DROP VIEW IF EXISTS entity_presence CASCADE")
    _drop_readers(bind, ("comments",), "queue_id")
    bind.exec_driver_sql("ALTER TABLE comments DROP COLUMN IF EXISTS queue_id")
    _drop_readers(bind, ("initiatives",), "queues_enabled")
    bind.exec_driver_sql("ALTER TABLE initiatives DROP COLUMN IF EXISTS queues_enabled")
    _drop_readers(bind, _QUEUE_TABLES)
    bind.exec_driver_sql(f"DROP TABLE IF EXISTS {', '.join(_QUEUE_TABLES)}")


_QUEUE_DDL = (
    """
    CREATE TABLE queues (
        id serial NOT NULL,
        initiative_id integer NOT NULL,
        name character varying(255) NOT NULL,
        description character varying,
        created_by integer,
        current_round integer DEFAULT 1 NOT NULL,
        is_active boolean DEFAULT false NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        current_item_id integer,
        deleted_at timestamp with time zone,
        deleted_by integer,
        purge_at timestamp with time zone,
        comments_enabled boolean DEFAULT true NOT NULL,
        archived_at timestamp with time zone,
        listing_uid character varying(14),
        listing_version character varying(32),
        held_at timestamp with time zone,
        hold_id integer,
        comments_locked_at timestamp with time zone,
        CONSTRAINT queues_pkey PRIMARY KEY (id),
        CONSTRAINT queues_initiative_id_fkey FOREIGN KEY (initiative_id)
            REFERENCES initiatives(id)
    )
    """,
    "CREATE INDEX ix_queues_active ON queues (deleted_at) WHERE deleted_at IS NULL",
    "CREATE INDEX ix_queues_initiative_id ON queues (initiative_id)",
    "CREATE INDEX ix_queues_purge ON queues (purge_at) WHERE purge_at IS NOT NULL",
    """
    CREATE TABLE queue_items (
        id serial NOT NULL,
        queue_id integer NOT NULL,
        label character varying(255) NOT NULL,
        "position" numeric(20,10) DEFAULT 0 NOT NULL,
        user_id integer,
        color character varying(32),
        notes text,
        is_visible boolean DEFAULT true NOT NULL,
        created_at timestamp with time zone NOT NULL,
        deleted_at timestamp with time zone,
        deleted_by integer,
        purge_at timestamp with time zone,
        held_at_round integer,
        created_by integer,
        held_at timestamp with time zone,
        hold_id integer,
        CONSTRAINT queue_items_pkey PRIMARY KEY (id),
        CONSTRAINT queue_items_queue_id_fkey FOREIGN KEY (queue_id)
            REFERENCES queues(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_queue_items_active ON queue_items (deleted_at) "
    "WHERE deleted_at IS NULL",
    "CREATE INDEX ix_queue_items_purge ON queue_items (purge_at) "
    "WHERE purge_at IS NOT NULL",
    "CREATE INDEX ix_queue_items_queue_id ON queue_items (queue_id)",
    "ALTER TABLE queues ADD CONSTRAINT fk_queues_current_item_id "
    "FOREIGN KEY (current_item_id) REFERENCES queue_items(id) ON DELETE SET NULL",
    "CREATE TRIGGER tr_queues_set_created_by BEFORE INSERT ON queues "
    "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()",
    "CREATE TRIGGER tr_queue_items_set_created_by BEFORE INSERT ON queue_items "
    "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()",
    "CREATE TRIGGER tr_queues_install_owns AFTER INSERT ON queues "
    "FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('queue')",
    "ALTER TABLE comments ADD COLUMN queue_id integer",
    "ALTER TABLE comments ADD CONSTRAINT comments_queue_id_fkey "
    "FOREIGN KEY (queue_id) REFERENCES queues(id) ON DELETE CASCADE",
    "CREATE INDEX ix_comments_queue_id ON comments (queue_id)",
    "ALTER TABLE initiatives ADD COLUMN queues_enabled boolean DEFAULT false NOT NULL",
)
#: A community's schema keeps its tables' row security; the template has none.
_QUEUE_RLS = tuple(
    statement
    for table in _QUEUE_TABLES
    for statement in (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    )
)


# --- the conversion ----------------------------------------------------------


def _create_maps(bind: Connection) -> None:
    bind.exec_driver_sql(
        f"CREATE TEMP TABLE IF NOT EXISTS {_QUEUE_MAP} ("
        "schema_name text NOT NULL, queue_id integer NOT NULL, "
        "project_id integer NOT NULL, PRIMARY KEY (schema_name, queue_id)) "
        "ON COMMIT DROP"
    )
    bind.exec_driver_sql(
        f"CREATE TEMP TABLE IF NOT EXISTS {_ITEM_MAP} ("
        "schema_name text NOT NULL, item_id integer NOT NULL, "
        "task_id integer NOT NULL, project_id integer NOT NULL, "
        "PRIMARY KEY (schema_name, item_id)) ON COMMIT DROP"
    )


def _map(bind: Connection) -> None:
    """A project id for each queue and a task id for each item."""
    _create_maps(bind)
    for table in (_QUEUE_MAP, _ITEM_MAP):
        bind.exec_driver_sql(f"DELETE FROM {table} m WHERE {_IN_SCHEMA}")
    bind.exec_driver_sql(
        f"INSERT INTO {_QUEUE_MAP} (schema_name, queue_id, project_id) "
        "SELECT current_schema(), id, nextval(pg_get_serial_sequence('projects', 'id')) "
        "FROM queues ORDER BY id"
    )
    bind.exec_driver_sql(
        f"INSERT INTO {_ITEM_MAP} (schema_name, item_id, task_id, project_id) "
        "SELECT current_schema(), i.id, nextval(pg_get_serial_sequence('tasks', 'id')), "
        f"m.project_id FROM queue_items i JOIN {_QUEUE_MAP} m "
        f"ON m.queue_id = i.queue_id AND {_IN_SCHEMA} ORDER BY i.id"
    )


def _projects(bind: Connection) -> None:
    kept = set(_columns(bind, "projects")) - {
        "id",
        "description",
        "listing_uid",
        "listing_version",
    }
    columns = [c for c in _columns(bind, "queues") if c in kept]
    names = ", ".join(columns)
    picked = ", ".join(f"q.{c}" for c in columns)
    bind.exec_driver_sql(
        f"INSERT INTO projects (id, description, is_template, {names}) "
        "SELECT m.project_id, CASE WHEN q.is_active THEN concat_ws(E'\\n\\n', "
        "nullif(btrim(q.description), ''), "
        "'Round ' || q.current_round || ' when this was a queue.') "
        f"ELSE q.description END, false, {picked} "
        f"FROM queues q JOIN {_QUEUE_MAP} m ON m.queue_id = q.id AND {_IN_SCHEMA}"
    )


def _require_written(bind: Connection, map_table: str, table: str, column: str) -> None:
    """Fail the revision unless every row the map names was written."""
    missing = bind.execute(
        text(
            f"SELECT count(*) FROM {map_table} m WHERE {_IN_SCHEMA} AND NOT EXISTS "
            f"(SELECT 1 FROM {table} t WHERE t.id = m.{column})"
        )
    ).scalar()
    if missing:
        raise RuntimeError(f"{missing} {table} rows of the queues were not written")


def _statuses_and_types(bind: Connection) -> None:
    rows = ", ".join(
        f"('{name}', {position}, '{category}', {position == 0}, '{color}', '{icon}')"
        for position, (name, category, color, icon) in enumerate(_STATUSES)
    )
    bind.exec_driver_sql(
        "INSERT INTO task_statuses (project_id, name, position, category, "
        "is_default, color, icon, created_by) "
        "SELECT m.project_id, s.name, s.position, "
        "CAST(s.category AS task_status_category), s.is_default, s.color, s.icon, "
        f"q.created_by FROM queues q JOIN {_QUEUE_MAP} m "
        f"ON m.queue_id = q.id AND {_IN_SCHEMA} "
        f"CROSS JOIN (VALUES {rows}) AS s(name, position, category, is_default, "
        "color, icon)"
    )
    bind.exec_driver_sql(
        "INSERT INTO task_types (project_id, name, position, is_default, created_by) "
        f"SELECT m.project_id, '{_TURN}', 0, true, q.created_by "
        f"FROM queues q JOIN {_QUEUE_MAP} m ON m.queue_id = q.id AND {_IN_SCHEMA}"
    )


def _tasks(bind: Connection) -> None:
    waiting, up_now, held, sitting_out, _done = (name for name, *_ in _STATUSES)
    bind.exec_driver_sql(
        "INSERT INTO tasks (id, project_id, task_status_id, task_type_id, title, "
        "description, priority, position, created_by, created_at, updated_at, "
        "deleted_at, deleted_by, purge_at, held_at, hold_id) "
        "SELECT m.task_id, m.project_id, s.id, t.id, i.label, i.notes, "
        "CAST('medium' AS task_priority), "
        "row_number() OVER (PARTITION BY i.queue_id ORDER BY i.position DESC, i.id) - 1, "
        "i.created_by, i.created_at, i.created_at, i.deleted_at, i.deleted_by, "
        "i.purge_at, i.held_at, i.hold_id "
        f"FROM queue_items i JOIN {_ITEM_MAP} m ON m.item_id = i.id AND {_IN_SCHEMA} "
        "JOIN queues q ON q.id = i.queue_id "
        "JOIN task_types t ON t.project_id = m.project_id "
        "JOIN task_statuses s ON s.project_id = m.project_id AND s.name = CASE "
        f"WHEN q.is_active AND q.current_item_id = i.id THEN '{up_now}' "
        f"WHEN i.held_at_round IS NOT NULL THEN '{held}' "
        f"WHEN NOT i.is_visible THEN '{sitting_out}' ELSE '{waiting}' END"
    )
    bind.exec_driver_sql(
        "INSERT INTO relationships (source_type, source_id, relationship_type, "
        "target_type, target_id, provenance, created_at) "
        "SELECT 'task', m.task_id, 'related_to', 'user', i.user_id, 'manual', "
        f"i.created_at FROM queue_items i JOIN {_ITEM_MAP} m "
        f"ON m.item_id = i.id AND {_IN_SCHEMA} WHERE i.user_id IS NOT NULL"
    )


def _retarget(bind: Connection, table: str, kind: str, row_id: str) -> None:
    """A queue's rows name its project, an item's its task; any other row
    naming either goes."""
    for old, new, map_table, old_id, new_id in (
        (_QUEUE, "project", _QUEUE_MAP, "queue_id", "project_id"),
        (_ITEM, "task", _ITEM_MAP, "item_id", "task_id"),
    ):
        bind.exec_driver_sql(
            f"UPDATE {table} t SET {kind} = '{new}', {row_id} = m.{new_id} "
            f"FROM {map_table} m WHERE {_IN_SCHEMA} AND t.{kind} = '{old}' "
            f"AND t.{row_id} = m.{old_id}"
        )
    bind.exec_driver_sql(f"DELETE FROM {table} WHERE {kind} IN ('{_QUEUE}', '{_ITEM}')")


def _retarget_all(bind: Connection) -> None:
    for table, kind, row_id in _NAMED_BY_KIND:
        _retarget(bind, table, kind, row_id)
    symmetric = _quoted(_SYMMETRIC_TYPES)
    bind.exec_driver_sql(
        "UPDATE relationships SET source_type = target_type, "
        "source_id = target_id, target_type = source_type, target_id = source_id "
        f"WHERE relationship_type IN ({symmetric}) AND source_node > target_node"
    )
    kinds = _quoted((_QUEUE, _ITEM))
    bind.exec_driver_sql(
        f"DELETE FROM search_entries WHERE entity_type IN ({kinds}) "
        f"OR dac_tool IN ({kinds})"
    )
    bind.exec_driver_sql(
        "UPDATE comments c SET project_id = m.project_id, queue_id = NULL "
        f"FROM {_QUEUE_MAP} m WHERE {_IN_SCHEMA} AND c.queue_id = m.queue_id"
    )


def _layouts(bind: Connection) -> None:
    bind.exec_driver_sql(
        f"DELETE FROM tool_layouts WHERE tool = '{_QUEUE}' OR kind = '{_ITEM}'"
    )
    rows = ", ".join(f"('{kind}', {body})" for kind, body in _LAYOUTS)
    bind.exec_driver_sql(
        "INSERT INTO tool_layouts (initiative_id, tool, tool_id, kind, definition, "
        "created_at, updated_at) "
        "SELECT q.initiative_id, 'project', m.project_id, l.kind, l.definition, "
        f"now(), now() FROM queues q JOIN {_QUEUE_MAP} m "
        f"ON m.queue_id = q.id AND {_IN_SCHEMA} "
        f"CROSS JOIN LATERAL (VALUES {rows}) AS l(kind, definition)"
    )
    bind.exec_driver_sql(f"DELETE FROM view_preferences WHERE {_VIEW_PREFERENCES}")


def _without_queues(value: Any) -> Any:
    """An install's definition with no queue scope, event type or entry naming
    a queue kind."""

    def names_queue(item: Any) -> bool:
        if isinstance(item, str):
            return (
                item in _SCOPES
                or item in (_QUEUE, _ITEM)
                or item.startswith(_EVENT_PREFIXES)
            )
        if isinstance(item, dict):
            return any(item.get(key) in (_QUEUE, _ITEM) for key in _KIND_KEYS)
        return False

    if isinstance(value, list):
        return [_without_queues(v) for v in value if not names_queue(v)]
    if isinstance(value, dict):
        return {k: _without_queues(v) for k, v in value.items() if k not in _SCOPES}
    return value


def _array_without(bind: Connection, table: str, column: str, where: str) -> None:
    """Remove from a text array every element ``where`` holds of ``v``."""
    bind.exec_driver_sql(
        f"UPDATE {table} SET {column} = ARRAY(SELECT v FROM unnest({column}) "
        f"WITH ORDINALITY AS u(v, i) WHERE NOT ({where}) ORDER BY i) "
        f"WHERE EXISTS (SELECT 1 FROM unnest({column}) v WHERE {where})"
    )


def _queue_event(column: str) -> str:
    return " OR ".join(
        f"starts_with(CAST({column} AS text), '{prefix}')" for prefix in _EVENT_PREFIXES
    )


def _settle_plugins_and_hooks(bind: Connection) -> None:
    _array_without(
        bind, "guild_plugins", "granted_scopes", f"v IN ({_quoted(_SCOPES)})"
    )
    rows = bind.execute(
        text(
            "SELECT id, definition FROM guild_plugins "
            "WHERE CAST(definition AS text) ~ 'queue'"
        )
    ).all()
    for row_id, definition in rows:
        if isinstance(definition, str):
            definition = json.loads(definition)
        cleaned = _without_queues(definition)
        if cleaned != definition:
            bind.execute(
                text(
                    "UPDATE guild_plugins SET definition = CAST(:d AS jsonb) WHERE id = :id"
                ),
                {"d": json.dumps(cleaned), "id": row_id},
            )
    _array_without(bind, "webhook_subscriptions", "event_types", _queue_event("v"))
    _array_without(
        bind,
        "webhook_subscriptions",
        "fields",
        f"CAST(v AS text) IN ({_quoted(_QUEUE_FIELDS)})",
    )
    empty = "cardinality(event_types) = 0"
    bind.exec_driver_sql(
        "DELETE FROM webhook_deliveries WHERE subscription_id IN "
        f"(SELECT id FROM webhook_subscriptions WHERE {empty})"
    )
    bind.exec_driver_sql(f"DELETE FROM webhook_subscriptions WHERE {empty}")


def _open_projects(bind: Connection) -> None:
    """Let whoever reached a queue reach its project: projects are switched on
    in an initiative that holds a queue, and a role that could view or create
    queues can view or create projects."""
    held = "SELECT initiative_id FROM queues"
    bind.exec_driver_sql(
        "UPDATE initiatives SET projects_enabled = true WHERE queues_enabled "
        f"AND NOT projects_enabled AND id IN ({held})"
    )
    for queue_key, project_key in zip(
        _PERMISSIONS, ("projects_enabled", "create_projects"), strict=True
    ):
        bind.exec_driver_sql(
            "INSERT INTO initiative_rules (initiative_id, initiative_role_id, key, "
            f"enabled) SELECT initiative_id, initiative_role_id, '{project_key}', true "
            f"FROM initiative_rules WHERE key = '{queue_key}' AND enabled "
            f"AND initiative_id IN ({held}) "
            "ON CONFLICT ON CONSTRAINT uq_initiative_rules_subject "
            "DO UPDATE SET enabled = true"
        )


def _forget(bind: Connection) -> None:
    """What only the queue tool had."""
    resources = _quoted(_RESOURCES)
    bind.exec_driver_sql(
        f"DELETE FROM initiative_rules WHERE key IN ({_quoted(_RULE_KEYS)})"
    )
    bind.exec_driver_sql(
        f"DELETE FROM event_outbox WHERE resource_type IN ({resources}) "
        f"OR dac_tool IN ({_quoted((_QUEUE, _ITEM))}) "
        "OR (jsonb_typeof(parents) = 'array' AND EXISTS (SELECT 1 FROM "
        f"jsonb_array_elements(parents) p WHERE p ->> 'type' IN ({resources})))"
    )
    bind.exec_driver_sql(
        f"DELETE FROM plugin_event_outbox WHERE {_queue_event('event_type')}"
    )
    bind.exec_driver_sql(
        "DELETE FROM data_jobs WHERE ((direction = 'export' AND source = 'queue') "
        "OR (direction = 'import' AND source = 'initiative-queue')) "
        "AND status IN ('staged', 'fetching', 'queued', 'running')"
    )


# --- links in stored content ----------------------------------------------

#: Bodies an editor session edits, each with a Yjs state beside its JSON, and
#: which of their rows hold a Lexical body.
_LIVE_BODIES = (("files", "file_type = 'lexical'"), ("wiki_pages", "true"))
#: Lexical bodies with no Yjs state.
_STATE_BODIES = (("posts", "body"),)
#: Markdown: a text column, or every string in a JSON one.
_MARKDOWN = (
    ("initiatives", "description"),
    ("projects", "description"),
    ("counter_groups", "description"),
    ("calendars", "description"),
    ("dashboards", "description"),
    ("wikis", "description"),
    ("collections", "description"),
    ("tasks", "description"),
    ("tasks", "checklist"),
    ("tasks", "recurrence_carry"),
    ("task_types", "starting_values"),
    ("calendar_events", "description"),
    ("calendar_events", "location"),
    ("comments", "content"),
)
_LINK_TABLES = tuple(
    dict.fromkeys(t for t, *_ in (*_LIVE_BODIES, *_STATE_BODIES, *_MARKDOWN))
)
#: A queue kind in a Lexical body's JSON, and in running text.
_OLD_IN_STATE = r'"(queue|queue_item)[":]'
_OLD_IN_TEXT = r"#queue"
#: A queue kind in a Yjs state: a kind is stored as a whole string value, its
#: length before it, and a ref as ``kind:id``.
_OLD_IN_YJS = (b"\x77\x05queue", b"\x77\x0aqueue_item", b"queue:", b"queue_item:")


def _nameless(value: Any) -> Any:
    """A Lexical body as it is stored: a mention of somebody by id carries no
    name."""
    if isinstance(value, list):
        return [_nameless(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _nameless(item) for key, item in value.items()}
    if out.get("mentionUserId") is None:
        return out
    return {**out, "mentionName": "", "text": ""}


def _rewrite_live(state: bytes, moved: Moved) -> tuple[Any, bytes] | None:
    """A body's JSON and Yjs state with its links rewritten, read and written
    through the editor; ``None`` when its state names no queue kind. Raises
    :class:`editor_engine.EditorError` for a state the editor refuses."""
    reading = await_only(editor_engine.render(state))
    rewritten = rewrite_body(reading, moved)
    if rewritten == reading:
        return None
    doc = Doc()
    doc.apply_update(state)
    doc.apply_update(await_only(editor_engine.apply(state, rewritten)))
    return _nameless(rewritten), bytes(doc.get_update())


def _as_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _is_json(bind: Connection, table: str, column: str) -> bool:
    return (
        bind.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) IN ('json', 'jsonb') "
                "FROM pg_attribute WHERE attrelid = to_regclass(:t) AND attname = :c"
            ),
            {"t": table, "c": column},
        ).scalar()
        is True
    )


def _strings(value: Any, moved: Moved) -> Any:
    if isinstance(value, str):
        return rewrite_text(value, moved)
    if isinstance(value, list):
        return [_strings(item, moved) for item in value]
    if isinstance(value, dict):
        return {key: _strings(item, moved) for key, item in value.items()}
    return value


def _write(
    bind: Connection,
    table: str,
    row_id: int,
    values: dict[str, Any],
    json_columns: set[str],
) -> None:
    sets = ", ".join(
        f"{column} = CAST(:{column} AS jsonb)"
        if column in json_columns
        else f"{column} = :{column}"
        for column in values
    )
    bind.execute(
        text(f"UPDATE {table} SET {sets} WHERE id = :row_id"),
        {
            **{
                column: json.dumps(value) if column in json_columns else value
                for column, value in values.items()
            },
            "row_id": row_id,
        },
    )


def _schema_maps(bind: Connection) -> Moved:
    return {
        _QUEUE: dict(
            bind.execute(
                text(
                    f"SELECT queue_id, project_id FROM {_QUEUE_MAP} m WHERE {_IN_SCHEMA}"
                )
            ).all()
        ),
        _ITEM: dict(
            bind.execute(
                text(f"SELECT item_id, task_id FROM {_ITEM_MAP} m WHERE {_IN_SCHEMA}")
            ).all()
        ),
    }


def _rewrite_links(bind: Connection) -> None:
    moved = _schema_maps(bind)
    in_yjs = " OR ".join(
        f"position(CAST(:n{i} AS bytea) IN yjs_state) > 0"
        for i in range(len(_OLD_IN_YJS))
    )
    needles = {f"n{i}": needle for i, needle in enumerate(_OLD_IN_YJS)}
    editor_runs = False
    for table, lexical in _LIVE_BODIES:
        if not _table_exists(bind, table):
            continue
        rows = bind.execute(
            text(
                f"SELECT id, content, yjs_state FROM {table} WHERE {lexical} AND "
                f"((yjs_state IS NOT NULL AND ({in_yjs})) "
                "OR CAST(content AS text) ~ :old)"
            ),
            {**needles, "old": _OLD_IN_STATE},
        ).all()
        for row_id, content, state in rows:
            content = _as_json(content)
            live = None
            if state is not None and any(n in bytes(state) for n in _OLD_IN_YJS):
                if not editor_runs:
                    # An editor that cannot start fails the revision here.
                    await_only(editor_engine.bootstrap(None))
                    editor_runs = True
                try:
                    live = _rewrite_live(bytes(state), moved)
                except editor_engine.EditorError:
                    # A state the editor refuses opens nowhere: the body is its
                    # JSON, and the next session makes a state from it.
                    live = (rewrite_body(content, moved), None)
            if live is not None:
                bind.execute(
                    text(
                        f"UPDATE {table} SET content = CAST(:c AS jsonb), "
                        "yjs_state = :s, yjs_updated_at = now() WHERE id = :id"
                    ),
                    {"c": json.dumps(live[0]), "s": live[1], "id": row_id},
                )
                continue
            rewritten = rewrite_body(content, moved)
            if rewritten != content:
                _write(bind, table, row_id, {"content": rewritten}, {"content"})
    for table, column in _STATE_BODIES:
        if not _table_exists(bind, table):
            continue
        rows = bind.execute(
            text(
                f"SELECT id, {column} FROM {table} WHERE CAST({column} AS text) ~ :old"
            ),
            {"old": _OLD_IN_STATE},
        ).all()
        for row_id, body in rows:
            body = _as_json(body)
            rewritten = rewrite_body(body, moved)
            if rewritten != body:
                _write(bind, table, row_id, {column: rewritten}, {column})
    for table, column in _MARKDOWN:
        if not _table_exists(bind, table):
            continue
        json_columns = {column} if _is_json(bind, table, column) else set()
        rows = bind.execute(
            text(
                f"SELECT id, {column} FROM {table} WHERE CAST({column} AS text) ~ :old"
            ),
            {"old": _OLD_IN_TEXT},
        ).all()
        for row_id, value in rows:
            value = _as_json(value) if json_columns else value
            rewritten = _strings(value, moved)
            if rewritten != value:
                _write(bind, table, row_id, {column: rewritten}, json_columns)


def _upgrade_schema(bind: Connection) -> None:
    checks = _drop_checks(bind, _QUEUE_CHECK, (_SYMMETRIC_CHECK,))
    if _table_exists(bind, "queues"):
        with _held(bind, _TOUCHED):
            _map(bind)
            _projects(bind)
            _statuses_and_types(bind)
            _tasks(bind)
            _require_written(bind, _QUEUE_MAP, "projects", "project_id")
            _require_written(bind, _ITEM_MAP, "tasks", "task_id")
            _retarget_all(bind)
            _layouts(bind)
            _settle_plugins_and_hooks(bind)
            _open_projects(bind)
            _forget(bind)
            _drop_queue_structure(bind)
        with _held(bind, _LINK_TABLES):
            _rewrite_links(bind)
    _restore_checks(bind, checks, _forward_check)
    bind.exec_driver_sql(_CLEAR_SEARCH_GENERATION)


def _downgrade_schema(bind: Connection) -> None:
    if _table_exists(bind, "queues"):
        return
    checks = _drop_checks(bind, "^$", (_SINGLE_PARENT_CHECK,))
    template = (
        bind.execute(text("SELECT current_schema()")).scalar() == "guild_template"
    )
    for statement in _QUEUE_DDL + (() if template else _QUEUE_RLS):
        bind.exec_driver_sql(statement)
    _restore_checks(
        bind,
        checks,
        lambda _name, definition: definition.replace(
            "num_nonnulls(", "num_nonnulls(queue_id, ", 1
        ),
    )


def _apply(forward: bool) -> None:
    """One guild schema, the one the search_path names."""
    bind = op.get_bind()
    (_upgrade_schema if forward else _downgrade_schema)(bind)


# --- public ------------------------------------------------------------------


class _Unmapped(Exception):
    """A queue or an item with no project or task."""


_GO = re.compile(r"(/|%2F)go\1(queue-item|queue_item|queue)\1(\d+)")
_PAGE = re.compile(r"(/|%2F)c\1\d+\1i\1\d+\1queues\1(\d+)")
_ROLLUP = re.compile(r"(^|:)(queue_item|queue):(\d+)(?=:|$)")
#: (kind key, id key) pairs a notice's data carries.
_DATA_KINDS = (
    ("entity_type", "entity_id"),
    ("subject_type", "subject_id"),
    ("context_entity_type", "context_entity_id"),
)
_NEW_KIND = {_QUEUE: "project", _ITEM: "task"}


def _notice_respeller(moved: Moved) -> dict[str, Callable[..., Any]]:
    """How each part of a notice reads with its queue a project and its item a
    task. Raises :class:`_Unmapped` for one with neither."""

    def kind(old: str, value: Any) -> tuple[str, Any]:
        if value is None:
            return _NEW_KIND[old], None
        try:
            return _NEW_KIND[old], moved[old][int(value)]
        except (KeyError, TypeError, ValueError):
            raise _Unmapped from None

    def go(new: str, ident: Any, sep: str) -> str:
        return f"{sep}go{sep}{new}{sep}{ident}"

    def address(value: str) -> str:
        def one(m: re.Match[str]) -> str:
            old = _ITEM if m.group(2) != _QUEUE else _QUEUE
            return go(*kind(old, m.group(3)), m.group(1))

        value = _GO.sub(one, value)
        return _PAGE.sub(lambda m: go(*kind(_QUEUE, m.group(2)), m.group(1)), value)

    def rollup(value: str) -> str:
        def one(m: re.Match[str]) -> str:
            new, ident = kind(m.group(2), m.group(3))
            return f"{m.group(1)}{new}:{ident}"

        return _ROLLUP.sub(one, value)

    def data(value: Any) -> Any:
        if isinstance(value, list):
            return [data(item) for item in value]
        if isinstance(value, str):
            return address(value)
        if not isinstance(value, dict):
            return value
        out = dict(value)
        for kind_key, id_key in _DATA_KINDS:
            if out.get(kind_key) in _NEW_KIND:
                out[kind_key], ident = kind(out[kind_key], out.get(id_key))
                if id_key in out:
                    out[id_key] = ident
        if out.get("tool") == _QUEUE:
            out["tool"] = "project"
            for key in ("tool_id", "resource_id"):
                if key in out:
                    out[key] = kind(_QUEUE, out[key])[1]
        return {
            key: rollup(item)
            if key == "rollup_key" and isinstance(item, str)
            else item
            if key
            in ("tool", "tool_id", "resource_id", *(k for p in _DATA_KINDS for k in p))
            else data(item)
            for key, item in out.items()
        }

    return {"address": address, "rollup": rollup, "data": data, "kind": kind}


def _all_maps(bind: Connection) -> dict[int | None, Moved]:
    """The maps, by community."""
    found: dict[int | None, dict[str, dict[int, int]]] = {}

    def guild_of(schema: str) -> int | None:
        return (
            int(schema.removeprefix("guild_")) if schema != "guild_template" else None
        )

    for map_table, old_id, new_id, old in (
        (_QUEUE_MAP, "queue_id", "project_id", _QUEUE),
        (_ITEM_MAP, "item_id", "task_id", _ITEM),
    ):
        for schema, from_id, to_id in bind.execute(
            text(f"SELECT schema_name, {old_id}, {new_id} FROM {map_table}")
        ).all():
            found.setdefault(guild_of(schema), {}).setdefault(old, {})[from_id] = to_id
    return found


def _notifications(bind: Connection, maps: dict[int | None, Moved]) -> None:
    rows = bind.execute(
        text(
            "SELECT id, guild_id, tool, resource_id, subject_type, subject_id, data "
            "FROM public.notifications WHERE tool = :q OR subject_type IN (:q, :i) "
            "OR CAST(data AS text) ~ 'queue'"
        ),
        {"q": _QUEUE, "i": _ITEM},
    ).all()
    for row_id, guild, tool, resource, subject_type, subject_id, payload in rows:
        respell = _notice_respeller(maps.get(guild, {}))
        try:
            if subject_type in _NEW_KIND:
                subject_type, subject_id = respell["kind"](subject_type, subject_id)
            if tool == _QUEUE:
                tool, resource = respell["kind"](_QUEUE, resource)
            payload = respell["data"](_as_json(payload))
        except _Unmapped:
            bind.execute(
                text("DELETE FROM public.notifications WHERE id = :id"), {"id": row_id}
            )
            continue
        bind.execute(
            text(
                "UPDATE public.notifications SET tool = :tool, resource_id = :resource, "
                "subject_type = :subject_type, subject_id = :subject_id, "
                "data = CAST(:data AS json) WHERE id = :id"
            ),
            {
                "tool": tool,
                "resource": resource,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "data": json.dumps(payload),
                "id": row_id,
            },
        )


def _notice_outbox(bind: Connection, maps: dict[int | None, Moved]) -> None:
    rows = bind.execute(
        text(
            "SELECT id, guild_id, data, push_data, rollup_key, email_link "
            "FROM public.notice_outbox WHERE CAST(data AS text) ~ 'queue' "
            "OR CAST(push_data AS text) ~ 'queue' OR rollup_key ~ 'queue' "
            "OR email_link ~ 'queue'"
        )
    ).all()
    for row_id, guild, payload, push, rollup_key, link in rows:
        respell = _notice_respeller(maps.get(guild, {}))
        try:
            payload = respell["data"](_as_json(payload))
            push = respell["data"](_as_json(push))
            rollup_key = None if rollup_key is None else respell["rollup"](rollup_key)
            link = None if link is None else respell["address"](link)
        except _Unmapped:
            bind.execute(
                text("DELETE FROM public.notice_outbox WHERE id = :id"), {"id": row_id}
            )
            continue
        bind.execute(
            text(
                "UPDATE public.notice_outbox SET data = CAST(:data AS jsonb), "
                "push_data = CAST(:push AS jsonb), rollup_key = :rollup, "
                "email_link = :link WHERE id = :id"
            ),
            {
                "data": json.dumps(payload),
                "push": None if push is None else json.dumps(push),
                "rollup": rollup_key,
                "link": link,
                "id": row_id,
            },
        )


def _public(bind: Connection) -> None:
    maps = _all_maps(bind)
    tables = (
        "public.notifications",
        "public.notice_outbox",
        "public.plugin_service_registrations",
        "public.marketplace_listings",
        "public.user_view_preferences",
    )
    with _held(bind, tables):
        _notifications(bind, maps)
        _notice_outbox(bind, maps)
        _array_without(
            bind,
            "public.plugin_service_registrations",
            "scope_ceiling",
            f"CAST(v AS text) IN ({_quoted(_SCOPES)})",
        )
        bind.exec_driver_sql(
            f"DELETE FROM public.marketplace_listings WHERE kind = '{_QUEUE}'"
        )
        bind.exec_driver_sql(
            f"DELETE FROM public.user_view_preferences WHERE {_VIEW_PREFERENCES}"
        )


# --- entry points ------------------------------------------------------------


def _convert(
    bind: Connection,
    forward: bool,
    each_schema: Callable[[Callable[[], None]], None],
) -> None:
    """Run ``_apply`` through ``each_schema``; upgrading, with the maps there
    for it, then the public half and the kind code without the queue kinds,
    and downgrading, with the kind code reading them first."""
    if forward:
        _create_maps(bind)
    else:
        bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_BEFORE))
    each_schema(lambda: _apply(forward))
    if forward:
        _public(bind)
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {_QUEUE_MAP}, {_ITEM_MAP}")
        bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_AFTER))


def upgrade() -> None:
    bind = op.get_bind()
    _convert(bind, True, lambda apply: run_for_each_guild_schema(bind, apply))


def downgrade() -> None:
    bind = op.get_bind()
    _convert(bind, False, lambda apply: run_for_each_guild_schema(bind, apply))
