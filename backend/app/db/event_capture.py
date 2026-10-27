"""Change capture — one trigger function, every evented content table.

The capture rule lives in ONE place, ``public.capture_change()``. Per-table
knowledge reaches it as trigger arguments rendered from the registry that already
describes these tables, so installing capture on a new table needs no new
declaration:

* **which initiative a row belongs to** — the ``INITIATIVE_PATHS`` entry that
  renders the table's RLS policies, so an event is scoped exactly like the row it
  describes;
* **which resource the event names** — the table's own primary key, or the parent
  it reports against (below).

What lands in ``event_outbox`` is identifiers, an action, and the **names** of
the columns that changed. Never a value: a consumer reads current state back
through the REST API, where the six gates apply to the read.

Every event names its parents
-----------------------------
A row is rarely interesting on its own: a comment moves a thread AND the count
on the card its parent shows, a task moves its project's board. So an event
also carries the ADDRESSABLE resources between it and its initiative,
innermost first — the chain the registry already walks to stamp
``initiative_id``, stopping at each thing that has a route of its own.

Identifiers, like the rest of the row. A consumer that wants the parent reads
it back through the route that already serves it.

Sub-resources report their parent
---------------------------------
Over half these tables are junctions with a composite primary key
(``task_assignees``, ``calendar_event_attendees``, …) and no id of their own.
Their first primary-key column is always the FK to the resource that owns them,
so a row appearing in ``task_assignees`` is reported as ``tasks.updated`` with
``changed = ['assignees']``.

That is also the semantics a subscriber wants: "this task was assigned", not "a
row appeared in a junction table". The owner and the label are both derived —
the owner from the FK, the label by stripping the owner's singular stem from the
junction's name — so a new junction is covered by construction.

The same shape covers sub-resources that DO have an id of their own but are
still a facet of something else (a project's statuses, a file's versions, an
initiative's roles, a resource's sharing). Derivation cannot see that, so those
say it once in ``EVENT_SOURCES`` as a ``ReportsAs``. Either way the resource an
event names is one that already has a detail route, which is what keeps every
id in the outbox resolvable without owing new API surface per table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import Column
from sqlmodel import SQLModel

from app.core.tools import Tool
from app.db import gucs
from app.db.initiative_rls import (
    EVENTED_TABLES,
    INITIATIVE_PATHS,
    NO_PARENTS,
    event_source,
    initiative_locator,
)

#: How a row reaches the trigger's dynamic lookups: as ``$1`` in an EXECUTE, so
#: every registry expression is rendered against this rather than NEW/OLD.
ROW = "($1)"

#: Alias for the parent row a reports-as table borrows its chain from. Long on
#: purpose: the borrowed chain brings the registry's own short aliases with it,
#: and an inner one shadowing this would silently join the wrong row.
_PARENT_ALIAS = "outbox_parent"

#: The channel the capture raises once per writing transaction, per guild.
#: Postgres itself is the sender here — no worker is involved in the write, so
#: no worker could have told the others about it. The payload is
#: ``<schema>:<txid>``, which is the whole of what a listener needs to find the
#: rows: identical payloads inside one transaction collapse to a single
#: notification, so a bulk write raises one rather than one per row.
OUTBOX_CHANNEL = "event_outbox"

#: The function name every per-table trigger calls. Created once in ``public``
#: (not per guild schema): the body names content tables unqualified, so it
#: resolves them through the caller's ``search_path`` — the routed guild schema —
#: exactly as ``initiative_access`` does.
CAPTURE_FUNCTION = "public.capture_change"

#: Columns whose changes are not worth reporting. ``updated_at`` moves on every
#: write, and search vectors / denormalized counters churn on their own, so
#: leaving them in would make every column filter match constantly.
HOUSEKEEPING_COLUMNS: frozenset[str] = frozenset(
    {"updated_at", "created_at", "search_vector"}
)

#: Same idea, by suffix, for generated text-search columns.
HOUSEKEEPING_SUFFIXES: tuple[str, ...] = ("_vector", "_tsv")


@dataclass(frozen=True)
class CaptureSpec:
    """How one table's changes are reported."""

    #: The table the trigger is installed on.
    table: str
    #: The resource types an event from this table can name — the table itself,
    #: or the parent it reports against. More than one only for a polymorphic
    #: facet (a grant names whichever tool it is on).
    resource_types: frozenset[str]
    #: Row expression yielding that resource's id.
    resource_id_expr: str
    #: When the table reports against a parent, the label used in ``changed``
    #: (e.g. ``tags``). ``None`` when the table is its own resource and real
    #: column names apply.
    facet: str | None
    #: Row expression yielding the resource type, for the polymorphic case.
    #: ``None`` when ``resource_types`` holds the single constant answer.
    resource_type_expr: str | None = None
    #: Set only where a table reports against more than one resource and so
    #: carries more than one trigger. ``None`` everywhere else, which keeps
    #: every existing trigger's name unchanged.
    label: str | None = None
    #: Row expression yielding the facet label, where one constant cannot say
    #: it — a table whose rows are facets of different things depending on what
    #: the row holds. ``None`` everywhere else, and then ``facet`` is the whole
    #: answer and no per-row lookup is paid for.
    facet_expr: str | None = None
    #: Every label ``facet_expr`` can yield, for the vocabularies that have to
    #: know the names before a row exists. Empty where ``facet`` is the answer.
    facet_values: frozenset[str] = frozenset()
    #: Row expression yielding the initiative this trigger's events are scoped
    #: to, where the table's own answer is not this report's. ``None`` leaves
    #: the table's registry entry to answer, which is the ordinary case.
    initiative_expr: str | None = None

    @property
    def trigger_name(self) -> str:
        suffix = f"_{self.label}" if self.label else ""
        return f"capture_{self.table}{suffix}"

    @property
    def static_resource_type(self) -> str:
        """The one type this names, for the ordinary non-polymorphic case."""
        (resource_type,) = self.resource_types
        return resource_type

    @property
    def quiet_expr(self) -> str:
        """Row expression that is true while this event is not news yet."""
        return _quiet_expr(
            table=self.table,
            facet=self.facet,
            resource_types=self.resource_types,
            resource_id_expr=self.resource_id_expr,
            resource_type_expr=self.resource_type_expr,
        )

    @property
    def parents_expr(self) -> str:
        """Row expression yielding this event's parent chain, or "" for none.

        Empty for the tool tables and everything reporting against one, so
        those pay nothing for the column.
        """
        return _parents_expr(
            table=self.table,
            facet=self.facet,
            resource_types=self.resource_types,
            resource_id_expr=self.resource_id_expr,
            resource_type_expr=self.resource_type_expr,
        )


def _singular(table: str) -> str:
    """Junction owners are all regular plurals in this schema — ``posts``,
    ``counter_groups``, ``collections`` — so one spelling rule reads them back:
    ``ies`` was a ``y``, and otherwise the ``s`` comes off."""
    if table.endswith("ies"):
        return table[:-3] + "y"
    return table[:-1] if table.endswith("s") else table


def _owner_of(column: Column[Any]) -> str | None:
    """The table a FK column points at, or None if it is not a FK."""
    for fk in column.foreign_keys:
        return fk.column.table.name
    return None


def _borrowed(
    *,
    resource_types: frozenset[str],
    resource_id_expr: str,
    resource_type_expr: str | None,
    of_parent: Callable[[str, str], str],
) -> str:
    """One declaration, read off the resource the event NAMES.

    A table that reports against a parent is describing that parent, so the
    parent's declarations are the ones that apply — a tag landing on a task
    wants the task's project, and a grant on a draft is as quiet as the draft.
    That costs one indexed lookup by primary key, and not even that where the
    parent has nothing to say. The polymorphic case asks per kind, since the
    arms are different tables.

    ``of_parent`` answers "" for a parent with nothing to say; so does this.
    """
    answers = {
        parent: of_parent(parent, _PARENT_ALIAS) for parent in sorted(resource_types)
    }
    if not any(answers.values()):
        return ""

    def lookup(parent: str) -> str:
        if not answers[parent]:
            return "NULL"
        return (
            f"(SELECT {answers[parent]} FROM {parent} {_PARENT_ALIAS} "  # noqa: S608
            f"WHERE {_PARENT_ALIAS}.id = {resource_id_expr})"
        )

    if resource_type_expr is None:
        (parent,) = resource_types
        return lookup(parent)

    arms = " ".join(f"WHEN '{parent}' THEN {lookup(parent)}" for parent in answers)
    return f"(CASE {resource_type_expr} {arms} END)"


def _parents_expr(
    *,
    table: str,
    facet: str | None,
    resource_types: frozenset[str],
    resource_id_expr: str,
    resource_type_expr: str | None,
) -> str:
    """The chain an event from ``table`` carries, or "" for none."""
    if facet is None:
        path = INITIATIVE_PATHS.get(table)
        own = path.parents(ROW) if path is not None else NO_PARENTS
        return "" if own == NO_PARENTS else own

    def chain_of(parent: str, alias: str) -> str:
        if parent not in INITIATIVE_PATHS:
            return ""
        rendered = INITIATIVE_PATHS[parent].parents(alias)
        return "" if rendered == NO_PARENTS else rendered

    borrowed = _borrowed(
        resource_types=resource_types,
        resource_id_expr=resource_id_expr,
        resource_type_expr=resource_type_expr,
        of_parent=chain_of,
    )
    return f"COALESCE({borrowed}, {NO_PARENTS})" if borrowed else ""


def _quiet_expr(
    *,
    table: str,
    facet: str | None,
    resource_types: frozenset[str],
    resource_id_expr: str,
    resource_type_expr: str | None,
) -> str:
    """While this holds, the event is not news yet — or "" where none applies.

    A facet answers to the rule of the thing it is a facet OF: sharing a draft,
    or tagging one, is as quiet as the draft itself. Otherwise the row that
    stays quiet would be announced by every child it acquires.
    """
    if facet is None:
        quiet = event_source(table).quiet_when
        return quiet(ROW) if quiet is not None else ""

    def quiet_of(parent: str, alias: str) -> str:
        quiet = event_source(parent).quiet_when
        return quiet(alias) if quiet is not None else ""

    borrowed = _borrowed(
        resource_types=resource_types,
        resource_id_expr=resource_id_expr,
        resource_type_expr=resource_type_expr,
        of_parent=quiet_of,
    )
    return f"COALESCE({borrowed}, false)" if borrowed else ""


def build_specs() -> list[CaptureSpec]:
    """One spec per evented table.

    Three sources, tried in order: a declared ``ReportsAs`` (the explicit facet),
    a composite primary key (the derived facet), or the table's own primary key.

    Raises when a table can be reported none of those ways — capture would
    otherwise install a trigger that emits rows naming no resource, and a
    silently unaddressable event is worse than a failed boot.
    """
    specs: list[CaptureSpec] = []
    for table_name in sorted(EVENTED_TABLES):
        table = SQLModel.metadata.tables.get(table_name)
        if table is None:
            raise RuntimeError(
                f"{table_name} is in EVENTED_TABLES but has no mapped model"
            )

        source = event_source(table_name)
        declared = source.reports_as
        if declared is not None:
            # A tuple reports the row against several resources — one trigger
            # each, so the capture function itself needs to know nothing about
            # the case: it is the same per-table arguments, twice.
            for report in declared if isinstance(declared, tuple) else (declared,):
                specs.append(
                    CaptureSpec(
                        table=table_name,
                        resource_types=report.resource_types,
                        resource_id_expr=report.id_expr(ROW),
                        facet=report.facet,
                        resource_type_expr=(
                            report.type_expr(ROW)
                            if report.type_expr is not None
                            else None
                        ),
                        label=report.label,
                        facet_expr=(
                            report.facet_expr(ROW)
                            if report.facet_expr is not None
                            else None
                        ),
                        facet_values=report.facet_values,
                        initiative_expr=(
                            report.initiative_expr(ROW)
                            if report.initiative_expr is not None
                            else None
                        ),
                    )
                )
            continue

        pk = list(table.primary_key.columns)
        if len(pk) == 1:
            specs.append(
                CaptureSpec(
                    table=table_name,
                    # Its own resource, under its own name — or the declared
                    # one, where the API segment differs from the table's.
                    resource_types=frozenset({source.resource_type or table_name}),
                    resource_id_expr=f'{ROW}."{pk[0].name}"',
                    facet=None,
                )
            )
            continue

        owner_column = pk[0]
        owner = _owner_of(owner_column)
        if owner is None:
            raise RuntimeError(
                f"{table_name} has a composite primary key whose first column "
                f"({owner_column.name}) is not a foreign key, so its events "
                "cannot name an owning resource"
            )
        specs.append(
            CaptureSpec(
                table=table_name,
                resource_types=frozenset({owner}),
                resource_id_expr=f'{ROW}."{owner_column.name}"',
                facet=table_name.removeprefix(f"{_singular(owner)}_"),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# The capture function
# ---------------------------------------------------------------------------

#: Each tool's table and the tool it is, for the governing-tool lookup the
#: function makes from a change's resource and parents. From the enum, so a new
#: tool is governed without an edit here.
_GOVERNING_TOOLS = ", ".join(f"('{tool.plural}', '{tool.value}')" for tool in Tool)

#: Rendered once into ``public``. Per-table knowledge arrives as TG_ARGV, where
#: every "expression" is SQL text evaluated with the changed row as ``$1``:
#:   0 — expression resolving the row's initiative id
#:   1 — resource type the event names
#:   2 — expression resolving that resource's id
#:   3 — facet label, or '' when the table is its own resource
#:   4 — array literal of column names excluded from ``changed``
#:   5 — 'guild' when this table has no initiative and a NULL is expected
#:   6 — expression resolving the resource TYPE, or '' when arg 1 is the answer
#:   7 — expression resolving the resource's parent chain, or '' when it has none
#:   8 — expression that is true while the row is not news yet, or '' for none
#:   9 — 'anonymous' when this table's events name no actor
#:  10 — expression resolving the facet label, or '' when arg 3 is the answer
CAPTURE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {CAPTURE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $capture$
DECLARE
    v_row        record;
    v_initiative integer;
    v_action     text;
    v_changed    text[] := '{{}}';
    v_resource   integer;
    v_type       text := TG_ARGV[1];
    v_actor      integer;
    v_install    integer;
    v_new        jsonb;
    v_old        jsonb;
    v_facet      text := TG_ARGV[3];
    v_parents    jsonb := '[]'::jsonb;
    v_was_quiet  boolean := false;
    v_is_quiet   boolean := false;
    v_dac_tool   text;
    v_dac_id     integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    -- Some content exists before it is anybody else's business. While a row is
    -- quiet it says nothing at all, and crossing out of that is what gets
    -- reported — as a create, so a consumer never has to know the convention.
    -- Asked first, so a row nobody is to hear about pays for no lookup either.
    IF TG_ARGV[8] <> '' THEN
        IF TG_OP <> 'INSERT' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_was_quiet USING OLD;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_is_quiet USING NEW;
        END IF;
        IF (TG_OP = 'INSERT' AND v_is_quiet)
           OR (TG_OP = 'DELETE' AND v_was_quiet)
           OR (TG_OP = 'UPDATE' AND v_was_quiet AND v_is_quiet) THEN
            RETURN NULL;
        END IF;
    END IF;

    -- Which initiative this row belongs to, per its registry entry. A NULL is
    -- expected for a guild-wide table and means exactly that; anywhere else it
    -- means the initiative no longer resolves — an orphaned child during a
    -- parent cascade, whose parent emits its own delete — so the row is skipped
    -- rather than broadcast without a scope.
    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    IF v_initiative IS NULL AND TG_ARGV[5] <> 'guild' THEN
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_resource USING v_row;
    IF v_resource IS NULL THEN
        RETURN NULL;
    END IF;

    -- A polymorphic facet names its parent's type per row (a grant reports
    -- against whichever tool it shares). An unrecognized value resolves to NULL
    -- and the row is skipped, so what a subscription may name and what can be
    -- emitted stay the same set.
    IF TG_ARGV[6] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_type USING v_row;
        IF v_type IS NULL THEN
            RETURN NULL;
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_action := 'created';
    ELSIF TG_OP = 'DELETE' THEN
        -- On a table with the trash lifecycle, deleting is soft: the row moves
        -- to the trash, which is the event a subscriber acts on, and this hard
        -- delete is retention clearing it out afterwards. Never surface that —
        -- it is a repeat of an announced delete, and by now nothing can resolve
        -- the id anyway, not even a read-back asking for trashed rows.
        --
        -- Carrying no deleted_at means the table has no other kind of delete,
        -- so that one IS the event: a junction row going away is how a task
        -- loses a tag.
        --
        -- Tested for through jsonb rather than as OLD.deleted_at, because most
        -- evented tables have no such column and naming one that is absent
        -- raises at runtime.
        IF to_jsonb(OLD) ? 'deleted_at' THEN
            RETURN NULL;
        END IF;
        v_action := 'deleted';
    ELSE
        v_new := to_jsonb(NEW);
        v_old := to_jsonb(OLD);

        -- Coming out of quiet is the row arriving, whatever else moved with it.
        IF v_was_quiet AND NOT v_is_quiet THEN
            v_action := 'created';
        ELSIF NOT v_was_quiet AND v_is_quiet THEN
            v_action := 'deleted';
        -- Soft delete and restore are reported as what they are, so a consumer
        -- never has to know the deleted_at convention to see a row come or go.
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NULL
           AND v_new ->> 'deleted_at' IS NOT NULL THEN
            v_action := 'deleted';
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NOT NULL
           AND v_new ->> 'deleted_at' IS NULL THEN
            v_action := 'created';
        ELSE
            v_action := 'updated';
            SELECT coalesce(array_agg(key ORDER BY key), '{{}}')
              INTO v_changed
              FROM jsonb_each(v_new) AS e(key, value)
             WHERE value IS DISTINCT FROM (v_old -> e.key)
               AND NOT (key = ANY (TG_ARGV[4]::text[]));

            -- Nothing a subscriber can act on changed.
            IF cardinality(v_changed) = 0 THEN
                RETURN NULL;
            END IF;
        END IF;
    END IF;

    -- A facet whose label the row decides. Resolved here rather than passed as
    -- a literal, for a table whose rows are facets of different things.
    IF COALESCE(TG_ARGV[10], '') <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[10] INTO v_facet USING v_row;
        v_facet := COALESCE(v_facet, '');
    END IF;

    -- A facet has no columns of its own worth naming; report the change as the
    -- owning resource being updated in one respect.
    IF v_facet <> '' THEN
        v_changed := ARRAY[v_facet];
        IF v_action <> 'updated' THEN
            v_action := 'updated';
        END IF;
    END IF;

    -- The addressable resources between this row and its initiative. Resolved
    -- last, so a row that turned out not to be worth reporting never paid for
    -- the lookup, and skipped entirely where the resource has no parents.
    IF TG_ARGV[7] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[7] INTO v_parents USING v_row;
        v_parents := COALESCE(v_parents, '[]'::jsonb);
    END IF;

    -- The tool whose sharing governs the change: the resource itself when it
    -- is a tool, else the outermost tool among its parents. None for a change
    -- under no tool, which the initiative gate alone answers.
    SELECT m.tool, x.id INTO v_dac_tool, v_dac_id
      FROM (
            SELECT v_type AS type, v_resource AS id, 0::bigint AS ord
            UNION ALL
            SELECT p ->> 'type', (p ->> 'id')::integer, o
              FROM jsonb_array_elements(v_parents) WITH ORDINALITY AS e(p, o)
           ) x
      JOIN (VALUES {_GOVERNING_TOOLS}) AS m(tbl, tool) ON m.tbl = x.type
     ORDER BY x.ord DESC
     LIMIT 1;

    -- Who wrote it: the person, the installed plug-in, or both when a plug-in acts
    -- for a member. Each is read on its own from the request context, and an
    -- anonymous table names neither.
    IF TG_ARGV[9] <> 'anonymous' THEN
        v_actor := {gucs.USER_ID};
        v_install := {gucs.INSTALL_ID};
    END IF;

    -- Write to the outbox of the schema the CHANGED ROW lives in, named from
    -- TG_TABLE_SCHEMA rather than resolved through the caller's search_path.
    -- The row's own schema is the authoritative answer to which guild this
    -- event belongs to, and it is what the trigger is attached to.
    EXECUTE format(
        'INSERT INTO %I.event_outbox ('
        '  txn_id, occurred_at, actor_user_id, actor_install_id, initiative_id,'
        '  resource_type, resource_id, action, changed, parents, dac_tool, dac_id'
        ') VALUES (txid_current(), now(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10)',
        TG_TABLE_SCHEMA
    ) USING v_actor, v_install, v_initiative, v_type, v_resource, v_action,
            v_changed, v_parents, v_dac_tool, v_dac_id;

    -- Wake whoever is holding sockets for this guild. A hint, not the message:
    -- the row above is the truth, and one that reaches nobody costs a listener
    -- the sweep's latency rather than the update itself. Delivered at COMMIT,
    -- so the rows it points at are visible by the time anyone looks.
    PERFORM pg_notify('{OUTBOX_CHANNEL}', TG_TABLE_SCHEMA || ':' || txid_current());

    RETURN NULL;
END
$capture$;
"""


def _housekeeping_literal(table_name: str) -> str:
    """SQL array literal of column names excluded from ``changed`` for a table."""
    table = SQLModel.metadata.tables[table_name]
    excluded = sorted(
        c.name
        for c in table.columns
        if c.name in HOUSEKEEPING_COLUMNS or c.name.endswith(HOUSEKEEPING_SUFFIXES)
    )
    inner = ",".join(f'"{name}"' for name in excluded)
    return f"'{{{inner}}}'"


def _quoted(expr: str) -> str:
    """A SQL expression as a trigger-argument string literal."""
    return "'" + expr.replace("'", "''") + "'"


def _trigger_block(spec: CaptureSpec) -> str:
    source = event_source(spec.table)
    # A polymorphic facet resolves its type per row; everything else names one
    # constant, and passing that as a literal keeps the extra EXECUTE off the
    # write path of every other table.
    type_expr = spec.resource_type_expr
    static_type = "" if type_expr is not None else spec.static_resource_type
    call = "\n".join(
        [
            f"  EXECUTE FUNCTION {CAPTURE_FUNCTION}(",
            f"    {_quoted(spec.initiative_expr or initiative_locator(spec.table)(ROW))},",
            f"    '{static_type}',",
            f"    {_quoted(spec.resource_id_expr)},",
            f"    '{spec.facet or ''}',",
            f"    {_housekeeping_literal(spec.table)},",
            f"    '{'guild' if source.guild_wide else ''}',",
            f"    {_quoted(type_expr or '')},",
            f"    {_quoted(spec.parents_expr)},",
            f"    {_quoted(spec.quiet_expr)},",
            f"    '{'anonymous' if source.anonymous else ''}',",
            f"    {_quoted(spec.facet_expr or '')}",
            "  );",
        ]
    )
    name = spec.trigger_name
    when = source.when
    if when is None:
        triggers = [(name, "INSERT OR UPDATE OR DELETE", None)]
    else:
        # A WHEN may name only the rows its events have, so a condition takes
        # one trigger per event: the row after an insert, the row before a
        # delete, and either side of an update.
        triggers = [
            (name, "UPDATE", f"{when('OLD')} OR {when('NEW')}"),
            (f"{name}_insert", "INSERT", when("NEW")),
            (f"{name}_delete", "DELETE", when("OLD")),
        ]
    blocks = []
    for trigger, events, condition in triggers:
        blocks += [
            f"DROP TRIGGER IF EXISTS {trigger} ON {spec.table};",
            f"CREATE TRIGGER {trigger}",
            f"  AFTER {events} ON {spec.table}",
            "  FOR EACH ROW",
            *([f"  WHEN ({condition})"] if condition is not None else []),
            call,
        ]
    return "\n".join(blocks)


_HEADER = """\
-- ============================================================================
-- CHANGE CAPTURE — GENERATED, DO NOT EDIT BY HAND
-- RENDERED AT RUNTIME from app/db/event_capture.py.
--
-- One trigger per evented content table, all calling public.capture_change().
-- Per-table knowledge is passed as trigger arguments derived from
-- INITIATIVE_PATHS (which initiative a row belongs to), the model metadata
-- (which resource an event names), and EVENT_SOURCES (the deviations from
-- those), so a new content table is captured without a second declaration.
--
-- The outbox carries identifiers, a parent chain and changed column NAMES only.
-- Values are read back through the REST API, where the six gates apply to the
-- read.
-- ============================================================================"""


def render_guild_capture_ddl() -> str:
    """Per-table trigger DDL, applied inside each guild schema."""
    blocks = [_trigger_block(spec) for spec in build_specs()]
    return _HEADER + "\n\n" + "\n\n".join(blocks) + "\n"
