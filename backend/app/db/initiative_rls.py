"""Single source of truth for the initiative-member RLS layer.

Each per-guild CONTENT table that is scoped to initiative membership is declared
exactly once here, in ``INITIATIVE_PATHS`` — mapping the table to *how a row
resolves its initiative* for ``initiative_access(...)``. From that one
declaration we derive:

- ``INITIATIVE_SCOPED_TABLES`` (``app.db.tenancy`` re-exports it and folds it
  into ``GUILD_SCOPED_TABLES``),
- the rendered RLS DDL (``app.db.guild_ddl`` stamps the
  uniform policy boilerplate around each path), and
- change capture: the table emits events, scoped by that same path and naming
  itself, unless ``EVENT_SOURCES`` (below) says otherwise.

So a new initiative-scoped table is added in ONE place — add a path here — and
the classification, the generated policies, and its event stream all follow.
``tenancy_test.py``, ``guild_rls_test.py`` and ``event_readback_test.py``
enforce that nothing drifts.

This module is intentionally dependency-free (no models, no SQLAlchemy) so it can
be imported by ``tenancy`` and by the build-time generator alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from app.db import gucs
from app.core.plugin_scopes import tool_resource
from app.core.reactions import ReactionTarget
from app.core.relationships import (
    ENDPOINT_KINDS,
    FACETS,
    SYMMETRIC_TYPES,
    Provenance,
    RelationshipType,
)
from app.core.tools import (
    DEFAULT_ENABLED_TOOLS,
    INSTALL_METADATA_KIND,
    CONTENT_KINDS,
    ITEM_KINDS,
    KINDS,
    PROPERTY_TARGETS,
    LAYOUT_INSTANCE_TABLES,
    Tool,
)
from app.models.platform.guild import AdminSurface
from app.models.tenant.batched_notice import BatchedNoticeKind
from app.db.presence import present, present_to_member
from app.db.authorization import (
    IN_POLICY,
    POLICY_SETTINGS_ADMIN,
    STANDING,
    plugin_narrowed,
    plugin_scope,
    in_body,
    sql_values,
)

#: The legs a policy reads, off this statement's standing.
_P = IN_POLICY

# A write flag is a Python bool where the render knows the answer, or the name
# of a SQL boolean where it does not — inside a function body, its parameter.
WriteFlag = bool | str

# A path builder takes (table_name, write_flag) and returns the SQL predicate
# (an initiative_access(...) call, possibly wrapped in an EXISTS join) shared by
# the four policies — read uses write=False, write commands use write=True.
PathBuilder = Callable[[str, WriteFlag], str]

# A folded builder takes (table_name, write_flag, share_write_flag) and returns
# ONE predicate answering membership and sharing together — the shape of a
# table whose gate is a function of a (kind, id) pair the row names.
FoldedBuilder = Callable[[str, WriteFlag, WriteFlag], str]

# A row-locator takes a trigger row alias ("NEW"/"OLD") and returns a scalar SQL
# expression yielding that row's initiative id (or NULL).
RowLocator = Callable[[str], str]

# A parents-locator has the same shape and yields a jsonb ARRAY of the
# ADDRESSABLE resources between a row and its initiative, innermost first —
# ``[{"type": "tasks", "id": 4}, {"type": "projects", "id": 7}]`` for a comment
# on a task. Identifiers only, like everything else on this log: a consumer
# reads each one back through the route that already serves it.
ParentsLocator = Callable[[str], str]

#: A row that hangs off nothing but its initiative.
NO_PARENTS = "'[]'::jsonb"


def _sql_bool(flag: WriteFlag) -> str:
    """``true``/``false`` for a decided flag, the expression itself otherwise."""
    if isinstance(flag, str):
        return flag
    return "true" if flag else "false"


def _parent(table: str, id_expr: str) -> str:
    """One ancestor, as the ``{type, id}`` object an event carries."""
    return f"jsonb_build_object('type', '{table}', 'id', {id_expr})"


#: Reads back what ``_parent`` writes. One formatter, one reader, so the drift
#: test can ask a rendered chain which resources it names without a second
#: declaration of the set.
_PARENT_TYPE_RE = re.compile(r"'type', '([a-z_]+)'")


def parent_types(chain_expr: str) -> frozenset[str]:
    """The resource types a rendered parent chain can name."""
    return frozenset(_PARENT_TYPE_RE.findall(chain_expr))


def _no_parents(_row: str) -> str:
    return NO_PARENTS


def _one_parent(table: str, id_expr: str) -> str:
    """A single-hop chain, read off a column the row already carries."""
    return (
        f"(CASE WHEN {id_expr} IS NULL THEN {NO_PARENTS} "
        f"ELSE jsonb_build_array({_parent(table, id_expr)}) END)"
    )


def _parent_chain(frm: str, tie: str, id_expr: str, *hops: tuple[str, str]) -> str:
    """A chain read from ONE intermediate row — the lookup the path already does.

    ``frm``/``tie`` are that path's own join; each hop names an addressable
    table and the column of the joined row yielding its id, so every ancestor
    comes back together and a vanished intermediate yields no chain at all.
    """
    built = ", ".join(_parent(table, column) for table, column in hops)
    return (
        f"COALESCE((SELECT jsonb_build_array({built}) "  # noqa: S608
        f"FROM {frm} WHERE {tie} = {id_expr}), {NO_PARENTS})"
    )


# A DAC builder has the same shape as a PathBuilder but may answer None, for a
# table no tool's sharing governs — the guild's own vocabulary, an initiative's
# configuration. None renders no leg at all rather than a `true` one.
DacBuilder = Callable[[str, str, WriteFlag], "str | None"]

#: Every tool's own table, keyed by table name. The sharing gate is DERIVED from
#: this rather than declared per table: a row is governed by the tool it belongs
#: to, and a table that belongs to none is governed by none. So a seventh tool
#: gates its own rows and its children's the day its table exists.
_TOOL_BY_TABLE: dict[str, Tool] = {tool.plural: tool for tool in Tool}


@dataclass(frozen=True)
class DacPath:
    """How a row names the tool that governs it — gates 3 and 4.

    ``predicate`` renders the tool gate that the table's policies AND onto the
    membership one, or None where no tool governs the table. Both gates come
    from the same declaration and the same join, so a child table asks its
    parent about its role and its sharing once rather than twice.

    ``tool`` and ``via`` are the SAME declaration as data rather than SQL, so
    the app layer can answer "which tool governs a task, and how does a task
    reach it" from the registry the policies are rendered from instead of
    restating it per endpoint.

    ``via`` is the join chain from this table to the governing resource,
    outermost first, as ``(column, table_it_points_at)`` pairs — the column
    belongs to the PREVIOUS table in the walk, starting with this one:

    - ``tasks``      → ``(("project_id", "projects"),)``
    - ``task_tags``  → ``(("task_id", "tasks"), ("project_id", "projects"))``
    - ``projects``   → ``()`` — the row IS the resource

    Naming the table at every hop and not just the column is what lets the
    walk be checked end to end: a renamed intermediate is caught where it is
    declared rather than where something later follows it.

    Both are None/empty for a polymorphic table, whose governing tool is a
    property of the row rather than of the table.
    """

    predicate: DacBuilder
    tool: Tool | None = None
    via: tuple[tuple[str, str], ...] = ()


def _switch_leg(tool: "Tool", initiative: str) -> str:
    """Whether ``tool`` is switched on for ``initiative``, for this reader."""
    return (
        f"({_GUILD_ADMIN} OR {_PAM_ANY} OR {initiative} IS NULL"
        f" OR ({_P.this_guild} AND ({initiative}::text || ':{tool.value}')"
        f" = ANY ({_P.field('enabled_tools')})))"
    )


def _resource_call(tool: str, resource_id: str, initiative: str, write: bool) -> str:
    """Gate 4 alone, for a row that names its governing tool in a COLUMN.

    The search index is the one: which tool governs an entry differs per row,
    so the tool cannot be rendered into the policy and gate 3 — whose switch is
    a different column per tool — has nothing static to ask. The index is
    derived from content that carries both gates already, and the query that
    reads it applies the tool switches.
    """
    return (
        f"resource_access({tool}, {resource_id}, {gucs.USER_ID}, "
        f"{initiative}, {_sql_bool(write)}, {STANDING})"
    )


def _tool_gate(
    tool: Tool,
    resource_id: str,
    initiative: str,
    command: str,
    write: bool,
    *,
    creating: bool,
) -> str:
    """Gates 3 and 4 for one tool, against one row's initiative.

    Gate 3 is two conditions the schema already holds: the initiative's master
    switch for the tool, and what the reader's role in that initiative permits.
    The switch is a different column per tool, so it renders here where the tool
    is known rather than inside the function.

    ``creating`` is the INSERT of the governed resource itself — that asks for
    the tool's create right, where every other command asks to view it, and it
    asks gate 4 nothing.

    An installed plug-in is asked two more things first: that it holds the tool's
    scope, read for SELECT and write for every other command, and, where its
    token is narrowed to one initiative, that the row belongs to an initiative
    at all.
    """
    legs: list[str] = [
        plugin_scope(tool_resource(tool), command != "SELECT", _P),
        plugin_narrowed(initiative, _P),
    ]

    # Every tool carries a switch on the initiative. A community admin or a PAM
    # grantee reaches the content of a tool that is switched off — the endpoints
    # still refuse them, and a maintenance sweep has to be able to see it.
    #
    # Which initiatives have it on is in the request's standing, as one pair per
    # initiative the reader is in: an admin, a grantee and a system sweep are
    # already admitted above, so those are the only ones whose switch can decide
    # anything for them.
    legs.append(_switch_leg(tool, initiative))

    key = tool.create_permission if creating else tool.view_permission
    default = "false" if creating else str(tool in DEFAULT_ENABLED_TOOLS).lower()
    legs.append(
        f"initiative_role_permits({initiative}, {gucs.USER_ID}, '{key}', {default}, {STANDING})"
    )

    if not creating:
        legs.append(
            f"resource_access('{tool.value}', {resource_id}, {gucs.USER_ID}, "
            f"{initiative}, {_sql_bool(write)}, {STANDING})"
        )

    return "(" + " AND ".join(legs) + ")"


def _dac_self(tool: Tool | None = None) -> DacPath:
    """The row IS the shared resource. Which tool that is comes from the table
    name at render time, so a table that is no tool's renders nothing; a caller
    reaching the table under an alias (reactions, below) names the tool itself.
    """

    def build(t: str, command: str, w: bool) -> str | None:
        governing = tool if tool is not None else _TOOL_BY_TABLE.get(t)
        if governing is None:
            return None
        return _tool_gate(
            governing,
            f"{t}.id",
            f"{t}.initiative_id",
            command,
            w,
            # An INSERT is the resource being made only where the table IS the
            # resource. A caller that names the tool reached it under an alias
            # (a reaction on a notice), and there the INSERT is the reaction's:
            # the notice already exists and answers for itself.
            creating=command == "INSERT" and tool is None,
        )

    # ``tool`` here is only the explicitly-named one: without it the governing
    # tool is read off the table name at render time, and the caller asking
    # this registry knows its own table.
    return DacPath(predicate=build, tool=tool)


def _dac_via(
    parent: str, fk: str, *, parent_pk: str = "id", alias: str = "dac"
) -> DacPath:
    """The row is shared as part of its parent — a task by its project."""
    tool = _TOOL_BY_TABLE.get(parent)
    if tool is None:
        return DacPath(predicate=lambda t, c, w: None)

    def build(t: str, c: str, w: bool) -> str | None:
        # For a read the membership walk above already reached this parent, and
        # that walk ran the parent's own SELECT policy, which asks this same
        # question. Asking it again would consult ``resource_grants`` a second
        # time per row for the same answer. ``ANSWERED`` rather than nothing,
        # because a polymorphic path composes these arms per target type.
        if c == "SELECT" and parent_answers_for_reads(parent):
            return ANSWERED
        return (
            f"EXISTS (SELECT 1 FROM {parent} {alias} "
            f"WHERE {alias}.{parent_pk} = {t}.{fk} AND "
            + _tool_gate(
                tool,
                f"{alias}.id",
                f"{alias}.initiative_id",
                c,
                w,
                creating=False,
            )
            + ")"
        )

    return DacPath(tool=tool, via=((fk, parent),), predicate=build)


def _dac_two_hop(mid: str, mid_fk: str, parent: str, fk: str) -> DacPath:
    """Two hops to the governing resource: ``table.<fk> -> mid -> parent`` — a
    task's tag link by its task's project, an attendee by its event's calendar."""
    tool = _TOOL_BY_TABLE[parent]

    def build(t: str, c: str, w: bool) -> str | None:
        if c == "SELECT" and parent_answers_for_reads(mid):
            return ANSWERED
        return (
            f"EXISTS (SELECT 1 FROM {mid} dmid JOIN {parent} dpar "
            f"ON dpar.id = dmid.{mid_fk} WHERE dmid.id = {t}.{fk} AND "
            + _tool_gate(tool, "dpar.id", "dpar.initiative_id", c, w, creating=False)
            + ")"
        )

    return DacPath(tool=tool, via=((fk, mid), (mid_fk, parent)), predicate=build)


@dataclass(frozen=True)
class InitiativePath:
    """How one table's rows resolve an initiative, rendered two ways.

    ``predicate`` builds the RLS policy body; ``initiative_expr`` builds the
    scalar lookup the change-capture trigger stamps onto an outbox row. Both come
    from the SAME declaration, so a table cannot be gated by one initiative and
    have its events attributed to another. Adding a table still means one entry
    in ``INITIATIVE_PATHS`` — the builders below produce both forms.
    """

    predicate: PathBuilder
    initiative_expr: RowLocator
    #: The addressable resources between a row and its initiative, for the
    #: event the capture trigger writes. Same declaration as the gate above, so
    #: a row cannot be gated through one parent and have its events attributed
    #: through another.
    parents: ParentsLocator = _no_parents
    #: The sharing leg (gate 4), ANDed onto ``predicate`` by the DDL renderer.
    #: Derived by the factories below from the parent a table already declares,
    #: so it is never a second list to keep in step.
    dac: DacPath | None = None
    #: Membership and sharing as ONE call, for a table whose gate is a function
    #: of a (kind, id) pair its row names. The renderer passes both flags here
    #: and renders no separate ``dac`` leg; ``predicate`` is the read form of
    #: the same call.
    folded: FoldedBuilder | None = None
    #: What a row responding to this one (a comment, an edge end) asks of its
    #: initiative, where that is less than writing the row itself; ``None``
    #: when the two are the same. Read by :func:`_entity_arm`.
    responding: PathBuilder | None = None


#: Types stored once per unordered pair, as a SQL list. A symmetric edge
#: describes neither end, so it has no source for a write rule to key on.
_SYMMETRIC_SQL = ", ".join(f"'{t.value}'" for t in sorted(SYMMETRIC_TYPES))

#: Rows nobody asserted: the save path read them out of a body.
_FROM_CONTENT = f"'{Provenance.content.value}'"

#: The community-administrator leg, for rows that span every initiative in a
#: community, beside the one that admits trusted system maintenance. Both are
#: the same legs the gate functions carry — one definition, in
#: :mod:`app.db.authorization`.
_GUILD_ADMIN = _P.system_or_admin

#: An installed plug-in acting in this community on a token that is not narrowed
#: to one initiative.
_UNNARROWED_INSTALL = _P.unnarrowed_install

#: A live PAM window, either level. Used where a leg is about what a guild has
#: switched on rather than about what one person may reach.
_PAM_ANY = _P.pam_any


def _access(initiative_expr: str, write: bool) -> str:
    return f"initiative_access({initiative_expr}, {gucs.USER_ID}, {_sql_bool(write)}, {STANDING})"


def _full_access(initiative_expr: str, write: bool) -> str:
    """Defer to the narrower standing: full access in this initiative.

    ``initiative_full_access`` reads ``app.override_initiatives`` — the
    GUC the request already sets from the reader's roles, and the one
    ``resource_access`` already consults for the sharing override. So a
    table taking this path is reachable by whoever already sees everything in
    the initiative, and by the guild admin, and by nobody else.
    """
    return f"initiative_full_access({initiative_expr}, {_sql_bool(write)}, {STANDING})"


def direct_full_access() -> InitiativePath:
    """Own ``initiative_id`` column, gated on full access rather than membership."""
    return InitiativePath(
        predicate=lambda t, w: _full_access(f"{t}.initiative_id", w),
        initiative_expr=lambda r: f"{r}.initiative_id",
        parents=_no_parents,
    )


def via_full_access(parent: str, fk: str) -> InitiativePath:
    """One hop to a parent that is itself gated on full access."""

    def predicate(t: str, w: bool) -> str:
        walk = f"EXISTS (SELECT 1 FROM {parent} WHERE {parent}.id = {t}.{fk}"
        if not w and parent_answers_for_reads(parent):
            return walk + ")"
        return f"{walk} AND {_full_access(f'{parent}.initiative_id', w)})"

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: (
            f"(SELECT {parent}.initiative_id FROM {parent} "  # noqa: S608
            f"WHERE {parent}.id = {r}.{fk})"
        ),
        parents=lambda r: _one_parent(parent, f"{r}.{fk}"),
    )


def direct() -> InitiativePath:
    """The table has its own ``initiative_id`` column."""
    return InitiativePath(
        predicate=lambda t, w: _access(f"{t}.initiative_id", w),
        initiative_expr=lambda r: f"{r}.initiative_id",
        # Nothing between the row and its initiative: it IS the addressable
        # thing, which is why the tool tables all take this path.
        parents=_no_parents,
        dac=_dac_self(),
    )


def direct_or_guild() -> InitiativePath:
    """Own ``initiative_id`` column, or none: a tool made for the whole guild.

    A row naming an initiative is gated like any :func:`direct` row. A row
    naming none belongs to the guild, where the initiative gate has nothing to
    decide: every member reads it as its sharing allows, and writing it is the
    guild admin's (or a live write grant's), or the installed plug-in's on a token
    not narrowed to one initiative. Sharing still applies on top, which is how
    the admin decides who writes what the row holds. ``resource_actions``
    asks the same writer for ``edit``.
    """
    writer = _P.guild_row_writer
    return InitiativePath(
        predicate=lambda t, w: (
            f"({_access(f'{t}.initiative_id', w)}"
            f" AND ({t}.initiative_id IS NOT NULL OR {writer}))"
            if w
            else _access(f"{t}.initiative_id", w)
        ),
        initiative_expr=lambda r: f"{r}.initiative_id",
        parents=_no_parents,
        dac=_dac_self(),
        # Commenting on a guild-level row is a member's, as adding an event to
        # it is: the writer rule above is for the row itself.
        responding=lambda t, w: _access(f"{t}.initiative_id", w),
    )


#: A sharing leg that the walk to the parent has already answered. Rendered as
#: a literal rather than left out, because a polymorphic path composes one arm
#: per target type and an arm has to be something; the planner folds it away,
#: and :func:`app.db.guild_ddl` leaves it off the top level entirely.
ANSWERED = "true"


def parent_answers_for_reads(parent: str) -> bool:
    """Whether walking to ``parent`` is, on its own, the read answer.

    A child's read leg is an ``EXISTS`` into its parent, and that inner scan
    runs the parent's own ``SELECT`` policy — which is the same question the
    child was about to ask a second time. So where the parent carries one, the
    walk is the whole of it.

    A parent that carries none (the structural initiative tables, which are
    guild-scoped by the schema boundary) answers nothing, and a child of one
    keeps asking for itself.
    """
    return parent in INITIATIVE_PATHS


def via(parent: str, fk: str, *, parent_pk: str = "id") -> InitiativePath:
    """One hop: ``table.<fk> -> parent.<parent_pk>``; parent has ``initiative_id``."""

    def predicate(t: str, w: bool) -> str:
        walk = f"EXISTS (SELECT 1 FROM {parent} WHERE {parent}.{parent_pk} = {t}.{fk}"
        if not w and parent_answers_for_reads(parent):
            return walk + ")"
        return f"{walk} AND {_access(f'{parent}.initiative_id', w)})"

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: (
            f"(SELECT {parent}.initiative_id FROM {parent} "  # noqa: S608
            f"WHERE {parent}.{parent_pk} = {r}.{fk})"
        ),
        parents=lambda r: _one_parent(parent, f"{r}.{fk}"),
        dac=_dac_via(parent, fk, parent_pk=parent_pk),
    )


def via_task_project(fk: str = "task_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> tasks -> projects.initiative_id``."""

    def predicate(t: str, w: bool) -> str:
        if not w and parent_answers_for_reads("tasks"):
            # One hop is enough for a read: the task's own policy is what walks
            # on to its project.
            return f"EXISTS (SELECT 1 FROM tasks tk WHERE tk.id = {t}.{fk})"
        return (
            f"EXISTS (SELECT 1 FROM tasks tk JOIN projects pr ON pr.id = tk.project_id "
            f"WHERE tk.id = {t}.{fk} "
            f"AND {_access('pr.initiative_id', w)})"
        )

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: (
            f"(SELECT pr.initiative_id FROM tasks tk "  # noqa: S608
            f"JOIN projects pr ON pr.id = tk.project_id WHERE tk.id = {r}.{fk})"
        ),
        parents=lambda r: _parent_chain(
            "tasks tk",
            "tk.id",
            f"{r}.{fk}",
            ("tasks", "tk.id"),
            ("projects", "tk.project_id"),
        ),
        dac=_dac_two_hop("tasks", "project_id", "projects", fk),
    )


def via_post_poll(fk: str = "poll_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> post_polls -> posts.initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM post_polls pp JOIN posts po ON po.id = pp.post_id "
            f"WHERE pp.id = {t}.{fk} "
            f"AND {_access('po.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT po.initiative_id FROM post_polls pp "  # noqa: S608
            f"JOIN posts po ON po.id = pp.post_id WHERE pp.id = {r}.{fk})"
        ),
        # A poll has no route of its own — the notice that asks the question is
        # the addressable thing, so the chain skips straight to it.
        parents=lambda r: _parent_chain(
            "post_polls pp", "pp.id", f"{r}.{fk}", ("posts", "pp.post_id")
        ),
        dac=_dac_two_hop("post_polls", "post_id", "posts", fk),
    )


def via_event_calendar(fk: str = "calendar_event_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> calendar_events -> calendars.initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM calendar_events ce "
            f"JOIN calendars cal ON cal.id = ce.calendar_id "
            f"WHERE ce.id = {t}.{fk} "
            f"AND {_access('cal.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT cal.initiative_id FROM calendar_events ce "  # noqa: S608
            f"JOIN calendars cal ON cal.id = ce.calendar_id WHERE ce.id = {r}.{fk})"
        ),
        parents=lambda r: _parent_chain(
            "calendar_events ce",
            "ce.id",
            f"{r}.{fk}",
            ("calendar_events", "ce.id"),
            ("calendars", "ce.calendar_id"),
        ),
        dac=_dac_two_hop("calendar_events", "calendar_id", "calendars", fk),
    )


@dataclass(frozen=True)
class CommentParent:
    """One thing a comment can hang off, declared once and rendered five ways.

    ``frm``/``tie``/``initiative`` give the membership legs and the outbox
    locator; ``chain`` names the addressable resources an event about the
    comment carries, read off that same join. So a comment cannot be gated
    through one parent and have its events attributed through another.

    ``table``/``governed_by``/``tool_fk`` say which tool's SHARING answers for
    the thread, which is not always the parent itself: a task is shared as part
    of its project and a wiki page as part of its wiki. Everything that has to
    resolve a comment's tool — the DAC legs here, the search index's sharing
    columns, the freeze check, the initiative lookup — reads them from here
    rather than carrying its own special case per parent.
    """

    #: The ``comments`` column naming this parent.
    column: str
    #: FROM clause reaching the parent.
    frm: str
    #: What ties the parent row to ``column``.
    tie: str
    #: The parent's initiative column.
    initiative: str
    #: (addressable table, column of ``frm`` holding its id), innermost first.
    chain: tuple[tuple[str, str], ...]
    #: The parent's own table.
    table: str
    #: The tool whose sharing governs this parent's rows, or ``None`` for a
    #: parent no sharing governs (a collection), whose own row answers.
    governed_by: Tool | None
    #: The column of :attr:`table` holding that tool's id, or ``None`` when the
    #: parent IS the tool row and ``column`` already names it.
    tool_fk: str | None = None

    @property
    def kind(self) -> str:
        """The parent's kind as ``entity_access`` is asked about it — the
        column name without its ``_id``, which is the vocabulary an edge end
        and a search entry already use for the same thing."""
        return self.column.removesuffix("_id")


def _tool_comment_parent(tool: Tool) -> CommentParent:
    """The comment parent for one tool — every tool's is the same shape.

    A tool entity names its own initiative, so the join is the table itself and
    the table stands as its own alias. Derived rather than listed so a comment
    thread arrives with a new tool instead of waiting to be wired.
    """
    table = tool.plural
    return CommentParent(
        f"{tool.value}_id",
        table,
        f"{table}.id",
        f"{table}.initiative_id",
        ((table, f"{table}.id"),),
        table=table,
        governed_by=tool,
    )


#: Every Tool appears here plus the content-level extras, matching the comment
#: table's single-parent constraint. The extras are written out rather than
#: derived because each names its own way up to a tool: a comment on a task
#: names the project too — it is the surface a task comment shows up on, and
#: the join is already made — and a comment on a wiki page names its wiki too.
_COMMENT_PARENTS: tuple[CommentParent, ...] = (
    CommentParent(
        "task_id",
        "tasks tk JOIN projects pr ON pr.id = tk.project_id",
        "tk.id",
        "pr.initiative_id",
        (("tasks", "tk.id"), ("projects", "pr.id")),
        table="tasks",
        governed_by=Tool.project,
        tool_fk="project_id",
    ),
    CommentParent(
        "wiki_page_id",
        "wiki_pages wp JOIN wikis wkp ON wkp.id = wp.wiki_id",
        "wp.id",
        "wkp.initiative_id",
        (("wiki_pages", "wp.id"), ("wikis", "wkp.id")),
        table="wiki_pages",
        governed_by=Tool.wiki,
        tool_fk="wiki_id",
    ),
    CommentParent(
        "collection_id",
        "collections",
        "collections.id",
        "collections.initiative_id",
        (("collections", "collections.id"),),
        table="collections",
        governed_by=None,
    ),
    *(_tool_comment_parent(tool) for tool in Tool),
)


#: Every comment parent by its column — what the other derivations look it up
#: by, so the parent set is stated once and they cannot disagree.
COMMENT_PARENTS: dict[str, CommentParent] = {p.column: p for p in _COMMENT_PARENTS}

#: The comment columns naming a parent, in declaration order. Search reads this
#: to work out which tool's sharing governs a comment, so the parent set is
#: stated once and the two derivations cannot disagree.
COMMENT_PARENT_COLUMNS: tuple[str, ...] = tuple(COMMENT_PARENTS)


def _comment_parent_kind(t: str) -> str:
    """The kind of the one parent a comment row names, read off its columns."""
    arms = " ".join(
        f"WHEN {t}.{p.column} IS NOT NULL THEN '{p.kind}'" for p in _COMMENT_PARENTS
    )
    return f"(CASE {arms} END)"


def _comment_parent_id(t: str) -> str:
    return "COALESCE(" + ", ".join(f"{t}.{p.column}" for p in _COMMENT_PARENTS) + ")"


def _entity_call(kind: str, entity_id: str, write: WriteFlag, share: WriteFlag) -> str:
    return (
        f"{ENTITY_ACCESS_FN}({kind}, {entity_id}, "
        f"{_sql_bool(write)}, {_sql_bool(share)}, {STANDING})"
    )


def comments_path() -> InitiativePath:
    """Comments hang off exactly one parent — a task, a wiki page or any tool
    entity — declared once in ``_COMMENT_PARENTS``.

    The policy names that parent as the ``(kind, id)`` pair read off the row
    and asks :data:`ENTITY_ACCESS_FN` about it, so a comment on a task is gated
    by the same arm an edge to that task is. Membership and sharing ride in
    the one call; a comment is a response, so the renderer passes read for the
    sharing flag on every command (``DAC_WRITE_COMMANDS``).
    """

    def folded(t: str, w: WriteFlag, sw: WriteFlag) -> str:
        return _entity_call(_comment_parent_kind(t), _comment_parent_id(t), w, sw)

    def locate(r: str) -> str:
        lookups = ", ".join(
            f"(SELECT {p.initiative} FROM {p.frm} WHERE {p.tie} = {r}.{p.column})"  # noqa: S608
            for p in _COMMENT_PARENTS
        )
        return f"COALESCE({lookups})"

    def chain(r: str) -> str:
        # Same COALESCE as the locator, over the same joins: the first parent
        # that resolves is the one parent a comment has.
        lookups = ", ".join(
            "(SELECT jsonb_build_array("  # noqa: S608
            + ", ".join(_parent(table, column) for table, column in p.chain)
            + f") FROM {p.frm} WHERE {p.tie} = {r}.{p.column})"
            for p in _COMMENT_PARENTS
        )
        return f"COALESCE({lookups}, {NO_PARENTS})"

    return InitiativePath(
        predicate=lambda t, w: folded(t, w, False),
        initiative_expr=locate,
        parents=chain,
        folded=folded,
    )


def _target_path(
    legs: dict[str, tuple[str, InitiativePath]],
    share_write: Callable[[str], str] | None = None,
) -> InitiativePath:
    """A row reached by whoever can reach the ``(target_type, target_id)`` it
    names, which is the pair :data:`ENTITY_ACCESS_FN` takes, so the policy is
    one call and the target's own entry decides inside it. ``legs`` names each
    target kind's table and path, for the row's initiative and parents.

    Sharing rides in the call as read unless a command asks write of it
    (``DAC_WRITE_COMMANDS``), and then only for the rows ``share_write`` names.
    """

    def folded(t: str, w: WriteFlag, sw: WriteFlag) -> str:
        if share_write is not None and sw is True:
            sw = share_write(t)
        elif share_write is not None and isinstance(sw, str):
            sw = f"({sw} AND {share_write(t)})"
        return _entity_call(f"{t}.target_type", f"{t}.target_id", w, sw)

    def locate(r: str) -> str:
        arms = " ".join(
            f"WHEN '{kind}' THEN "
            f"(SELECT {path.initiative_expr('rt')} FROM {table} rt "  # noqa: S608
            f"WHERE rt.id = {r}.target_id)"
            for kind, (table, path) in legs.items()
        )
        return f"(CASE {r}.target_type {arms} END)"

    def chain(r: str) -> str:
        arms = " ".join(
            f"WHEN '{kind}' THEN "
            f"(SELECT {path.parents('rt')} FROM {table} rt "  # noqa: S608
            f"WHERE rt.id = {r}.target_id)"
            for kind, (table, path) in legs.items()
        )
        return f"COALESCE((CASE {r}.target_type {arms} END), {NO_PARENTS})"

    return InitiativePath(
        predicate=lambda t, w: folded(t, w, False),
        initiative_expr=locate,
        parents=chain,
        folded=folded,
    )


def _reaction_legs() -> dict[str, tuple[str, InitiativePath]]:
    paths: dict[ReactionTarget, InitiativePath] = {
        ReactionTarget.comment: comments_path(),
        ReactionTarget.post: direct(),
    }
    return {target.value: (target.table, path) for target, path in paths.items()}


def reactions_path() -> InitiativePath:
    """A reaction is reached by whoever can reach the thing it is on: the
    comment arm walks to the comment's parent, the post arm asks the post. A
    new reactable kind adds a ``ReactionTarget`` member, which puts its table on
    the function's arms; nothing about the gate is written twice. Sharing rides
    in the call as read — reacting is responding.
    """
    return _target_path(_reaction_legs())


def batched_notices_path() -> InitiativePath:
    """A queued line is reached like what it is about: the task assigned, or
    what was reacted to. An assignment's line is queued by whoever assigned,
    who writes to the task, so inserting one asks write of its sharing; taking
    or clearing it is the recipient's own business, and a reaction's line
    answers as the reaction did.
    """
    return _target_path(
        {**_reaction_legs(), "task": ("tasks", via("projects", "project_id"))},
        share_write=lambda t: f"{t}.kind = '{BatchedNoticeKind.task_assignment.value}'",
    )


def _relationship_end(
    r: str, side: str, render: Callable[["InitiativePath", str], str]
) -> str:
    """One end of an edge, read through the registry entry of whatever it names.

    A CASE over that end's type, each arm joining to the kind's own table and
    asking the question there — so an edge never answers for itself what its
    endpoints already answer for themselves. An end no entry covers (a tag, and
    guild-level things generally) yields NULL, which each caller reads its own
    way. Built on call rather than at import, because ``INITIATIVE_PATHS`` is
    still being assembled when the callers are defined.
    """
    arms = " ".join(
        f"WHEN '{kind.value}' THEN (SELECT {render(path, 'rl')} "  # noqa: S608
        f"FROM {endpoint.table} rl WHERE rl.id = {r}.{side}_id)"
        for kind, endpoint in ENDPOINT_KINDS.items()
        if (path := INITIATIVE_PATHS.get(endpoint.table)) is not None
    )
    return f"(CASE {r}.{side}_type {arms} ELSE NULL END)"


#: The function every polymorphic policy defers to. One call per (kind, id)
#: instead of one EXISTS per kind: the policy stays a few hundred bytes, and
#: the per-kind walk is planned once per session inside the function, where
#: inlining it made every statement on the table plan a thousand-node tree.
ENTITY_ACCESS_FN = "entity_access"


def entity_tables() -> dict[str, str]:
    """Every kind :data:`ENTITY_ACCESS_FN` answers for, and the table its ids
    point at — what an edge end, a reaction target, a recent view or a
    comment's parent may name. Derived from those four registries, so a kind
    reaches the gate the moment one of them names it, and refused at import
    if two of them point one kind at different tables.
    """
    tables: dict[str, str] = {}
    for kind, table in (
        *((k.value, e.table) for k, e in ENDPOINT_KINDS.items()),
        *((t.value, t.table) for t in ReactionTarget),
        *CONTENT_KIND_TABLES.items(),
        *((p.kind, p.table) for p in _COMMENT_PARENTS),
    ):
        if tables.setdefault(kind, table) != table:
            raise ValueError(f"kind {kind!r} names two tables: {tables[kind]}, {table}")
    return tables


def _entity_dac(table: str) -> DacPath | None:
    """The sharing leg for one kind, with its tool NAMED.

    Every kind is reached under an alias here. Where the row IS the governing
    resource (``via`` empty), ``_dac_self`` reads the tool off the name it is
    handed — which under an alias is not a table name, so it would find no tool
    and render no gate at all. The lookup it wants is the same one, against the
    real table, so the tool is named.

    A kind that reaches its resource through a parent keeps the leg its own
    entry declares: that walk names each table, so it survives the alias. So
    does a kind no tool governs whose entry states its own leg (a collection's
    writer rule), which reads only the row it is handed.
    """
    path = INITIATIVE_PATHS.get(table)
    dac = path.dac if path is not None else None
    if dac is None or dac.via:
        return dac
    tool = dac.tool or _TOOL_BY_TABLE.get(table)
    return _dac_self(tool) if tool is not None else dac


def _entity_arm(table: str) -> str:
    """What one kind asks of a reader beyond being able to see the row.

    The arm looks the row up in the kind's own table, so the kind's SELECT
    policies decide whether the reader may see it at all — and those policies
    ARE the read form of the two legs ``guild_ddl`` renders for the table
    (membership and sharing), plus the trash restrictions. Restating them here
    would evaluate the same predicate twice on the same row, so the arm states
    only what a read does not answer: the write standing, when a flag asks
    for it, rendered with the flag decided so the planner sees a constant.

    A kind whose own entry is folded asks it whole, for the same reason only
    when a flag is set: a comment's arm is one more call, to its parent.
    """
    path = INITIATIVE_PATHS.get(table)
    if path is None:
        # Guild-level, and stated rather than defaulted. A tag is the guild's
        # own vocabulary: every member already sees every tag, so existence
        # inside the routed schema IS the gate. A kind with no entry and no
        # statement here is not an endpoint at all — ENDPOINT_KINDS refuses it,
        # because the permissive reading of a missing initiative admits any
        # member rather than nobody.
        return "TRUE"
    if path.folded is not None:
        return "(NOT p_need_write AND NOT p_need_share_write) OR " + path.folded(
            "re", "p_need_write", "p_need_share_write"
        )
    member = path.responding or path.predicate
    legs = [f"(NOT p_need_write OR ({member('re', True)}))"]
    dac = _entity_dac(table)
    if dac is not None:
        sharing = dac.predicate("re", "UPDATE", True)
        if sharing is not None:
            legs.append(f"(NOT p_need_share_write OR ({sharing}))")
    return " AND ".join(legs)


def render_entity_access_fn() -> str:
    """The per-kind gate, as one function every polymorphic policy calls.

    Rendered from ``INITIATIVE_PATHS`` like every policy here, so a kind's gate
    is still declared once. ``plpgsql`` rather than ``LANGUAGE sql``: a SQL
    function of this shape gets inlined back into the calling query, which is
    the thing being avoided. Not ``SECURITY DEFINER`` — it runs as the caller,
    so each kind's own policies apply inside it too, and the guild schema it
    reads is whichever one the request is routed to.

    ``p_need_write`` is what the reader needs of the initiative;
    ``p_need_share_write`` what they need of the resource's sharing. A table
    whose writes are edits passes the same flag twice; one whose writes are
    responses passes read for the second whatever the command. ``p_st`` is the
    statement's standing, which each arm hands on to the gates it calls.
    """
    arms = "\n".join(
        f"        WHEN '{kind}' THEN\n"
        f"            RETURN EXISTS (SELECT 1 FROM {table} re "
        f"WHERE re.id = p_entity_id AND ({_entity_arm(table)}));"
        for kind, table in sorted(entity_tables().items())
    )
    arms = in_body(arms)
    return f"""
CREATE OR REPLACE FUNCTION {ENTITY_ACCESS_FN}(
    p_kind text, p_entity_id integer, p_need_write boolean, p_need_share_write boolean,
    p_st standing
) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $entity_access$
BEGIN
    CASE p_kind
{arms}
        ELSE
            RETURN false;
    END CASE;
END;
$entity_access$;
"""


#: The initiative a ``(kind, id)`` pair belongs to, for a policy that needs to
#: compare it with something else on the row.
ENTITY_INITIATIVE_FN = "entity_initiative"


def render_entity_initiative_fn() -> str:
    """The initiative of whatever a ``(kind, id)`` pair names, as one function.

    One arm per kind :data:`ENTITY_ACCESS_FN` answers for, each asking the
    kind's own ``initiative_expr`` — the same lookup its change capture stamps
    events with. NULL for a row the reader cannot see, for a kind that belongs
    to no initiative, and for a guild-level row. ``plpgsql`` and run as the
    caller, like :func:`render_entity_access_fn`.
    """
    arms = "\n".join(
        f"        WHEN '{kind}' THEN\n"
        f"            RETURN (SELECT {path.initiative_expr('re')} FROM {table} re "
        f"WHERE re.id = p_entity_id);"
        for kind, table in sorted(entity_tables().items())
        if (path := INITIATIVE_PATHS.get(table)) is not None
    )
    return f"""
CREATE OR REPLACE FUNCTION {ENTITY_INITIATIVE_FN}(p_kind text, p_entity_id integer)
    RETURNS integer
    LANGUAGE plpgsql STABLE
    AS $entity_initiative$
BEGIN
    CASE p_kind
{arms}
        ELSE
            RETURN NULL;
    END CASE;
END;
$entity_initiative$;
"""


#: The item a change counts for, for every reader of the change log that asks.
CONTENT_ITEM_FN = "content_item_of"


def render_content_item_fn() -> str:
    """The item a change log row counts for, as ``(kind, id)``.

    The changed row itself when it is a tool or something inside one, else the
    innermost of its ``parents`` that is: a comment or a reaction counts for
    what it sits on. No row for a change that is about none (a tag). SQL, so a
    lateral call is planned as the join it stands for, and it reads no table.
    """
    kinds = ", ".join(
        f"('{table}', '{kind}')" for kind, table in sorted(CONTENT_KIND_TABLES.items())
    )
    return f"""
CREATE OR REPLACE FUNCTION {CONTENT_ITEM_FN}(p_type text, p_id integer, p_parents jsonb)
    RETURNS TABLE (kind text, id integer)
    LANGUAGE sql IMMUTABLE
    AS $content_item_of$
    SELECT k.kind, c.id
    FROM (
        SELECT p_type AS tbl, p_id AS id, 0::bigint AS depth
      UNION ALL
        SELECT p.value ->> 'type', (p.value ->> 'id')::integer, p.depth
        FROM jsonb_array_elements(p_parents) WITH ORDINALITY AS p (value, depth)
    ) c
    JOIN (VALUES {kinds}) AS k (tbl, kind) ON k.tbl = c.tbl
    ORDER BY c.depth
    LIMIT 1
$content_item_of$;
"""


def _entity_readable(t: str, kinds: Iterable[str]) -> str:
    """A row on a ``(entity_type, entity_id)`` pair is read by whoever can see
    the thing it is on: one ``EXISTS`` into that thing's own table, whose
    SELECT policies decide it. A kind outside ``kinds`` reads as nothing.

    The same lookup :data:`ENTITY_ACCESS_FN` makes for a read, written inline
    so the planner sees it. A filter reads thousands of values; inline, a scan
    builds the readable set once, where a call would run once per value.
    """
    tables = entity_tables()
    arms = " ".join(
        f"WHEN '{kind}' THEN EXISTS (SELECT 1 FROM {tables[kind]} re "  # noqa: S608
        f"WHERE re.id = {t}.entity_id)"
        for kind in kinds
    )
    return f"(CASE {t}.entity_type {arms} ELSE false END)"


def metadata_values_path() -> InitiativePath:
    """A metadata value is reached through the thing it is on and what its
    definition's owner adds, read off the definition in one ``EXISTS``.

    Polymorphic over ``(entity_type, entity_id)``. Reading asks that the thing
    can be read: one ``EXISTS`` per kind (:func:`_entity_readable`). Writing
    asks one :data:`ENTITY_ACCESS_FN` call, since a write touches a row at a
    time. Then, by the definition's owner:

    * the initiative (a property): a write edits the thing, and the definition
      belongs to the thing's own initiative, so a value from another
      initiative's definition, or on a thing that belongs to none, is refused;
    * a project: as a property, on a task in that project;
    * a collection: its value is on a file in the collection, and written by
      whoever may change the collection, with no edit on the file asked;
    * a plug-in: written by the install that keeps it, on an item it can read,
      and on the install itself (``entity_type = 'plugin'``), which belongs to
      no initiative and is reached by that install alone. On an item, the
      community's admin reaches it too (as the item is purged), and whoever
      can read the item reads it where its definition is shown on the item's
      kind.

    The system engine reaches every value.
    """

    def build(t: str, w: bool) -> str:
        own = f"(md.install_id = {_P.install_id} AND {_P.this_guild} AND {_P.auth_ok})"
        on_install = f"{t}.entity_type = '{INSTALL_METADATA_KIND}'"
        if not w:
            # The thing a value is on is read once, whoever owns the value: a
            # plug-in's is on an item, or on the install itself, which only
            # the install reads; on an item, its install, the community's
            # admin, and whoever reads it where the definition is shown.
            items = ", ".join(f"'{kind}'" for kind in ITEM_KINDS)
            return (
                f"({_P.system} OR EXISTS (SELECT 1 FROM metadata_definitions md "  # noqa: S608
                f"WHERE md.id = {t}.property_id AND (CASE WHEN {on_install}"
                f" THEN md.install_id IS NOT NULL AND {t}.entity_id = md.install_id"
                f" ELSE (md.install_id IS NULL OR {t}.entity_type IN ({items}))"
                f" AND {_entity_readable(t, PROPERTY_TARGETS)} END)"
                f" AND (md.install_id IS NULL OR {own} OR (NOT {on_install}"
                f" AND ({_P.admin} OR {t}.entity_type = ANY (md.shown_on))))))"
            )
        held = f"{ENTITY_INITIATIVE_FN}({t}.entity_type, {t}.entity_id)"
        field = (
            f"{t}.entity_type = '{Tool.file.value}' AND EXISTS (SELECT 1 "  # noqa: S608
            f"FROM collection_files cf WHERE cf.collection_id = md.collection_id "
            f"AND cf.file_id = {t}.entity_id) AND {_access('md.initiative_id', True)}"
            f" AND {_collection_writer('md.initiative_id')}"
        )
        on_task = (
            f"{t}.entity_type = 'task' AND EXISTS (SELECT 1 FROM tasks tk "  # noqa: S608
            f"WHERE tk.id = {t}.entity_id AND tk.project_id = md.project_id)"
        )
        # One call asks of the item what its owner's values take: an edit of
        # it, and of a plug-in's, only that it can be read.
        unowned = "md.install_id IS NULL"
        need = unowned if w is True else f"({unowned} AND {_sql_bool(w)})"
        item = (
            f"{ENTITY_ACCESS_FN}({t}.entity_type, {t}.entity_id, {need}, "
            f"{need}, {STANDING})"
        )
        return (
            f"({_P.system} OR EXISTS (SELECT 1 FROM metadata_definitions md "  # noqa: S608
            f"WHERE md.id = {t}.property_id AND ({unowned} OR {own}"
            f" OR ({_P.admin} AND NOT {on_install})) AND (CASE"
            f" WHEN md.collection_id IS NOT NULL THEN ({field})"
            f" WHEN {on_install} THEN NOT {unowned} AND {t}.entity_id = md.install_id"
            f" ELSE {item} AND (NOT {unowned} OR (CASE WHEN md.project_id IS NOT NULL"
            f" THEN {on_task} ELSE md.initiative_id = {held} END)) END)))"
        )

    return InitiativePath(
        predicate=build,
        initiative_expr=lambda r: (
            f"{ENTITY_INITIATIVE_FN}({r}.entity_type, {r}.entity_id)"
        ),
    )


def _administration(surface: AdminSurface) -> str:
    """Who administers ``surface``: its holder, a settings rung writing beside
    a read_write grant, or the system engine."""
    return (
        f"({_P.system} OR {_P.holds(surface)}"
        f" OR ({POLICY_SETTINGS_ADMIN} AND {_P.pam_write}))"
    )


def managed_write(initiative_expr: str) -> str:
    """Who changes what an initiative is set up with: its managers by the
    standing, or the community's administration of its initiatives. The
    structural initiative tables' ``managed_*`` policies, and a shared page's
    views."""
    return (
        f"({_administration(AdminSurface.initiatives)} OR ({_P.this_guild}"
        f" AND ({initiative_expr}) = ANY ({_P.field('manager_initiatives')})))"
    )


def administration_path() -> InitiativePath:
    """A row the community's administration of its invites alone reads and
    writes, whatever initiative it names: what a guest invite gives, which the
    invites themselves answer to. Naming any initiative takes the admin rung's
    reach into all of them beside the surface."""
    predicate = (
        f"({_P.system} OR ({POLICY_SETTINGS_ADMIN} AND {_P.pam_write})"
        f" OR ({_P.holds(AdminSurface.invites)} AND {_P.admin}))"
    )
    return InitiativePath(
        predicate=lambda t, w: predicate,
        initiative_expr=lambda r: f"{r}.initiative_id",
    )


def tool_layouts_path() -> InitiativePath:
    """A layout is read by the members of its initiative. A layout of one
    instance of a tool is written by whoever may write that instance, in the
    layout's own initiative: :data:`ENTITY_ACCESS_FN` asks the instance's own
    entry, sharing included, as a property value's write does. A layout of a
    shared tool (no instance) is written as the initiative's setup is
    (:func:`managed_write`).
    """

    def build(t: str, w: bool) -> str:
        if not w:
            return _access(f"{t}.initiative_id", False)
        instance = (
            f"({_entity_call(f'{t}.tool', f'{t}.tool_id', True, True)}"
            f" AND {ENTITY_INITIATIVE_FN}({t}.tool, {t}.tool_id) = {t}.initiative_id)"
        )
        return (
            f"(CASE WHEN {t}.tool_id IS NULL THEN {managed_write(f'{t}.initiative_id')}"
            f" ELSE ({_P.system} OR {instance}) END)"
        )

    return InitiativePath(
        predicate=build, initiative_expr=lambda r: f"{r}.initiative_id"
    )


def relationships_path() -> InitiativePath:
    """An edge is reached by whoever can reach BOTH of the things it connects.

    Polymorphic on both ends, so each end defers to :func:`render_entity_access_fn`
    — which asks that kind's OWN entry here for the membership predicate and
    the sharing leg. The two ends are ANDed: a row is invisible unless the
    reader clears each of them. A
    link can therefore never widen access — it only ever surfaces for someone
    who already held both sides — and an edge naming something the reader cannot
    see is simply absent, indistinguishable from never having existed.

    **What a write asks depends on what the edge describes.** Direction is
    chosen so the source is the end an edge describes, which makes this
    derivable rather than declared:

    * asymmetric (``depends_on``, ``part_of``, ``tagged_with``) — the edge is
      part of the source's own description, so making one is editing that thing:
      WRITE on the source, read on the target.
    * symmetric (``attached``, ``related_to``) — the edge describes neither end,
      so creating one edits neither. READ on both, the way a table whose writes
      are responses rather than edits already asks. Removal is guarded by the
      service instead: your own edge, or one on a thing you can edit.
    * derived from content, whatever its type — nobody asserted it. The save
      path read it out of a body, and the authority for it was the authority to
      put those words there, which that body's own gate already asked. READ on
      both, and the endpoint refuses to unlink one by hand at all.

    Those distinctions are per ROW, and they ride as the function's
    ``need_write`` argument — plain boolean expressions over the row's own
    columns, where a ``DAC_WRITE_COMMANDS`` entry could not say either: that
    registry answers per command, and neither question is one a command can
    answer.
    """

    def build(t: str, w: bool) -> str:
        # A write asks write of the source only where the edge describes it AND
        # a person is the one saying so.
        need_write = (
            f"({t}.relationship_type NOT IN ({_SYMMETRIC_SQL})"
            f" AND {t}.provenance <> {_FROM_CONTENT})"
            if w
            else "false"
        )
        source = _entity_call(
            f"{t}.source_type", f"{t}.source_id", need_write, need_write
        )
        target = _entity_call(f"{t}.target_type", f"{t}.target_id", False, False)
        if w:
            return f"({source} AND {target})"
        # What files a thing under a place reads wherever the place does, even
        # where the thing is only known to be there (``app.db.presence``): a
        # wiki can say how many of its files a member can't open.
        filed = (
            f"({t}.relationship_type = '{RelationshipType.part_of.value}'"
            f" AND {present(f'{t}.source_type', f'{t}.source_id')})"
        )
        return f"({target} AND ({source} OR {filed}))"

    def locate(r: str) -> str:
        """The initiative this edge belongs to, either end answering.

        The events are scoped more precisely than this — each one to its OWN
        end (:func:`relationships_report_on_both_ends`), which is what keeps a
        cross-initiative edge from telling one side about the other. This is
        the table's answer for anything that asks it of the row itself, where a
        guild-level end has none to give and the other end's decides.
        """

        def init(path: InitiativePath, alias: str) -> str:
            return path.initiative_expr(alias)

        return (
            f"COALESCE({_relationship_end(r, 'source', init)}, "
            f"{_relationship_end(r, 'target', init)})"
        )

    # Sharing is inside the function with membership: both legs ask the same
    # endpoint the same question, and splitting them here would render the walk
    # to each kind twice.
    return InitiativePath(predicate=build, initiative_expr=locate)


# The tables that name a piece of content by (entity_type, entity_id), recent
# views and engagement levels, take every tool and everything inside one, keyed
# by its wire name, with the table its ids point at.
CONTENT_KIND_TABLES: dict[str, str] = {k: KINDS[k].table for k in CONTENT_KINDS}


def webhook_subscription_path() -> InitiativePath:
    """A subscription is reached by whoever can reach what it watches.

    Naming an initiative makes it that initiative's integration config, seen and
    managed by its members exactly like the content it reports on — the same gate
    as everything else in a guild, not a private note belonging to whoever typed
    the URL.

    Naming NO initiative is the guild-wide case, and there the ordinary
    ``initiative_access`` answer is wrong: a NULL means "the initiative gate has
    nothing to decide", which admits any member. A guild-wide subscription
    reports across every initiative, so reaching it is the holder of
    ``AdminSurface.webhooks``'s — the admin rung, which already spans them — or
    an installed plug-in's whose token is not narrowed to one initiative. A plug-in sees and changes only the
    subscriptions it registered (the ``plugin_scope_*`` policies), and what one
    delivers is capped by where the plug-in is placed and the scopes it holds.
    """
    return InitiativePath(
        predicate=lambda t, w: (
            f"(CASE WHEN {t}.initiative_id IS NULL "
            f"THEN ({_P.system} OR {_P.holds(AdminSurface.webhooks)}"
            f" OR {_UNNARROWED_INSTALL}) "
            f"ELSE {_access(f'{t}.initiative_id', w)} END)"
        ),
        initiative_expr=lambda r: f"{r}.initiative_id",
    )


def _named_tool_gate(t: str, write: bool) -> str:
    """Gates 3 and 4 for a row that names its governing tool: a search entry,
    a change in the change log.

    Every other table has one governing tool rendered into its policy. These
    rows name their own in ``dac_tool``, so the switch and the role key are a
    lookup over that column, and rows naming none (the guild's vocabulary)
    answer to no role. The CASE picks only the key; the role check is one call,
    since a call per arm is what a parsed policy pays for, on every connection.

    A row outlives the content it describes by as long as the sweep takes, so
    it answers the same three questions the source does rather than trusting
    that it was right when it was written.
    """
    # The switch no longer needs an arm per tool: the pair the standing carries
    # is ``<initiative>:<tool>``, and the row names its own tool in a column.
    switch = (
        f"({_GUILD_ADMIN} OR {_PAM_ANY} OR {t}.initiative_id IS NULL"
        f" OR {t}.dac_tool IS NULL"
        f" OR ({_P.this_guild}"
        f" AND ({t}.initiative_id::text || ':' || {t}.dac_tool)"
        f" = ANY ({_P.field('enabled_tools')})))"
    )
    key_arms = " ".join(
        f"WHEN '{tool.value}' THEN '{tool.view_permission}'" for tool in Tool
    )
    key = f"(CASE {t}.dac_tool {key_arms} END)"
    defaults = sql_values(tool.value for tool in Tool if tool in DEFAULT_ENABLED_TOOLS)
    role = (
        f"({key} IS NULL OR initiative_role_permits({t}.initiative_id, "
        f"{gucs.USER_ID}, {key}, {t}.dac_tool IN ({defaults}), {STANDING}))"
    )
    return (
        f"({switch}"
        f" AND {role}"
        f" AND {_resource_call(f'{t}.dac_tool', f'{t}.dac_id', f'{t}.initiative_id', write)})"
    )


def _unstamped_leg(t: str, kind_column: str, id_column: str) -> str:
    """An entry that stamps no sharing, about a kind no sharing governs (a
    collection) or a comment on one, is reached as the row it describes is:
    that row's own policy decides."""
    tables = {k.value: k.table for k in KINDS.values() if k.standalone}
    tables["comment"] = "comments"
    arms = " ".join(
        f"WHEN '{kind}' THEN EXISTS (SELECT 1 FROM {table} sk"  # noqa: S608
        f" WHERE sk.id = {t}.{id_column})"
        for kind, table in tables.items()
    )
    return (
        f"({t}.dac_tool IS NOT NULL OR (CASE {t}.{kind_column} {arms} ELSE true END))"
    )


def named_tool_path(entity: tuple[str, str] | None = None) -> InitiativePath:
    """A row about content, reached exactly like the content it describes: the
    search index, and the change log.

    It stores ``initiative_id`` and its governing ``dac_tool``/``dac_id``
    directly, so unlike ``personal_items`` this needs no per-type EXISTS join —
    the row was stamped by the same registries that render the source's own
    policies.

    A NULL initiative is the guild-level case (a tag, a guild calendar): the
    initiative gate has nothing to decide, and these are rows every member
    already sees everywhere else in the app. It is not an ungated leg — a row
    carrying a ``dac_tool`` still answers to sharing, and reaching this schema
    at all is the guild gate.

    ``entity`` names the columns an entry names its thing by, for the index:
    an entry about a kind no sharing governs, or a comment on one, is reached
    as that row is.
    """

    def predicate(t: str, w: bool) -> str:
        gate = (
            f"(CASE WHEN {t}.initiative_id IS NULL "
            f"THEN true "
            f"ELSE {_access(f'{t}.initiative_id', w)} END)"
        )
        if entity is None:
            return gate
        return f"({gate} AND {_unstamped_leg(t, *entity)})"

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: f"{r}.initiative_id",
        # The index stores the governing pair, so the legs need no join. Which
        # tool governs an entry differs per row, so the two that name a tool are
        # a CASE over it rather than a rendered constant.
        dac=DacPath(predicate=lambda t, c, w: _named_tool_gate(t, w)),
    )


def uploads_path() -> InitiativePath:
    """A stored file is reached through the initiative whose content shows it.

    Until it is saved into something (``claimed_at`` NULL) only its uploader
    reaches it. Once claimed, its ``initiative_id`` is gated like any
    :func:`direct` row, and a NULL there is content belonging to the whole
    guild — a guild calendar and what hangs off it — which every member reads.
    """
    return InitiativePath(
        predicate=lambda t, w: (
            f"(CASE WHEN {t}.claimed_at IS NULL"
            f" THEN ({t}.created_by = {gucs.USER_ID.once} OR {_P.system})"
            f" ELSE {_access(f'{t}.initiative_id', w)} END)"
        ),
        initiative_expr=lambda r: f"{r}.initiative_id",
    )


def evidence_path() -> InitiativePath:
    """A stored object is reached exactly as the one parent it names is: a
    community report by those who settle it, an operations case by those in
    the initiative its task is in.

    Reading walks to the parent, whose own policy answers. Writing asks the
    parent's own write question: full access for a report, the case task's
    initiative for a case.
    """
    report_walk = (
        "EXISTS (SELECT 1 FROM moderation_reports mr WHERE mr.id = {t}.report_id"
    )
    case_walk = "EXISTS (SELECT 1 FROM intake_cases ic WHERE ic.id = {t}.case_id"

    def predicate(t: str, w: bool) -> str:
        if not w:
            report = report_walk.format(t=t) + ")"
            case = case_walk.format(t=t) + ")"
        else:
            report = (
                report_walk.format(t=t) + f" AND {_full_access('mr.initiative_id', w)})"
            )
            case = (
                "EXISTS (SELECT 1 FROM intake_cases ic JOIN tasks tk ON tk.id = ic.task_id"
                f" JOIN projects pr ON pr.id = tk.project_id WHERE ic.id = {t}.case_id"
                f" AND {_access('pr.initiative_id', w)})"
            )
        return f"(CASE WHEN {t}.report_id IS NOT NULL THEN {report} ELSE {case} END)"

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: (
            f"COALESCE((SELECT mr.initiative_id FROM moderation_reports mr "  # noqa: S608
            f"WHERE mr.id = {r}.report_id), (SELECT pr.initiative_id FROM intake_cases ic "
            f"JOIN tasks tk ON tk.id = ic.task_id JOIN projects pr ON pr.id = tk.project_id "
            f"WHERE ic.id = {r}.case_id))"
        ),
    )


def _collection_writer(initiative: str) -> str:
    """Changing a collection: the Files switch on in its initiative, and a role
    there that creates files. Its own sharing is none, so nothing else."""
    return (
        f"({_switch_leg(Tool.file, initiative)}"
        f" AND initiative_role_permits({initiative}, {gucs.USER_ID}, "
        f"'{Tool.file.create_permission}', false, {STANDING}))"
    )


def metadata_definitions_path() -> InitiativePath:
    """Who may read and define metadata, by the definition's owner.

    * The initiative's property: read and written by its members.
    * A collection's: also read only by whoever sees the collection — one
      ``EXISTS`` into it, whose own policy answers — and written only by
      whoever may change it (:func:`_collection_writer`).
    * A project's: read by whoever reads the project, and written, as the
      project's tasks are, by whoever may write the project: its sharing at
      write, the same leg every write of a project's content takes.
    * A plug-in's: declared by its manifest and kept by its install, which
      alone writes it besides the system engine. It belongs to no
      initiative, and anybody in the community reads it, as they read which
      plug-ins are installed.
    """
    project = via("projects", "project_id")
    sharing = _dac_via("projects", "project_id")

    def project_sharing(t: str, c: str, w: bool) -> str | None:
        # Reading is the project's own SELECT policy, reached by the walk
        # above; only a write asks the project's sharing.
        if c == "SELECT":
            return None
        return f"({t}.project_id IS NULL OR {sharing.predicate(t, c, w)})"

    def predicate(t: str, w: bool) -> str:
        seen = f"EXISTS (SELECT 1 FROM collections c WHERE c.id = {t}.collection_id)"  # noqa: S608
        if w:
            seen = f"({seen} AND {_collection_writer(f'{t}.initiative_id')})"
        plugin = (
            f"({_P.system} OR ({t}.install_id = {_P.install_id} AND {_P.this_guild}"
            f" AND {_P.auth_ok}))"
            if w
            else "true"
        )
        return (
            f"(CASE WHEN {t}.install_id IS NOT NULL THEN {plugin}"
            f" WHEN {t}.project_id IS NOT NULL THEN {project.predicate(t, w)}"
            f" ELSE ({_access(f'{t}.initiative_id', w)}"
            f" AND ({t}.collection_id IS NULL OR {seen})) END)"
        )

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: f"{r}.initiative_id",
        parents=_no_parents,
        dac=DacPath(predicate=project_sharing),
    )


def collections_path() -> InitiativePath:
    """A collection is seen through its files and changed by the initiative's
    file makers.

    Reading is one ``EXISTS`` into its entries joined to their files, whose
    own read policy answers: whoever can open a file in it sees it, and
    nobody else but the community's administration and the system engine. The
    join is what asks it, since an entry alone reads for every member of the
    initiative (:func:`collection_files_path`). Writing asks membership
    at write level, and, in the slot a tool's sharing takes, the writer rule
    (:func:`_collection_writer`) — on INSERT too, since there is no sharing
    for a new one to lack.
    """

    def predicate(t: str, w: bool) -> str:
        if w:
            return _access(f"{t}.initiative_id", True)
        return (
            f"({_P.system_or_admin} OR EXISTS (SELECT 1 FROM collection_files cf "
            f"JOIN files f ON f.id = cf.file_id WHERE cf.collection_id = {t}.id))"
        )

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: f"{r}.initiative_id",
        parents=_no_parents,
        dac=DacPath(
            predicate=lambda t, c, w: (
                None if c == "SELECT" else _collection_writer(f"{t}.initiative_id")
            )
        ),
    )


def collection_files_path() -> InitiativePath:
    """A collection's entry reads as its file — one ``EXISTS`` into ``files``,
    whose own policy answers — and to every member of its initiative besides,
    who may know a file is there without opening it (``app.db.presence``):
    an entry is two ids. Adding or taking one out is changing the collection,
    in the entry's own initiative — which the keys hold to be the
    collection's and the file's — with the file in sight.
    """

    def predicate(t: str, w: bool) -> str:
        walk = f"EXISTS (SELECT 1 FROM files WHERE files.id = {t}.file_id)"
        if not w:
            return f"({walk} OR {present_to_member(f'{t}.initiative_id')})"
        return (
            f"({_access(f'{t}.initiative_id', True)} AND {walk}"
            f" AND {_collection_writer(f'{t}.initiative_id')})"
        )

    return InitiativePath(
        predicate=predicate,
        initiative_expr=lambda r: f"{r}.initiative_id",
        parents=lambda r: _one_parent("collections", f"{r}.collection_id"),
    )


def content_kind_path() -> InitiativePath:
    """A row about one piece of content, reached exactly like the content
    itself: ``(entity_type, entity_id)`` is the pair the entity function takes,
    and every content kind is one of its arms. Writing the row asks nothing of
    sharing beyond reading."""

    def folded(t: str, w: WriteFlag, sw: WriteFlag) -> str:
        return _entity_call(f"{t}.entity_type", f"{t}.entity_id", w, sw)

    def locate(r: str) -> str:
        arms = " ".join(
            f"WHEN '{etype}' THEN "
            f"(SELECT {initiative_of(tbl, 're')} FROM {tbl} re WHERE re.id = {r}.entity_id)"  # noqa: S608
            for etype, tbl in CONTENT_KIND_TABLES.items()
        )
        return f"(CASE {r}.entity_type {arms} END)"

    return InitiativePath(
        predicate=lambda t, w: folded(t, w, False),
        initiative_expr=locate,
        folded=folded,
    )


# table -> how its rows resolve an initiative for initiative_access(...). THE
# source of truth: INITIATIVE_SCOPED_TABLES and the rendered RLS DDL (app.db.guild_ddl) both derive from
# this dict, so a new initiative-scoped table is declared here exactly once.
INITIATIVE_PATHS: dict[str, InitiativePath] = {
    # Every tool's table: its own initiative_id column. A calendar may name no
    # initiative, being made for the whole guild.
    **{
        tool.plural: direct_or_guild() if tool is Tool.calendar else direct()
        for tool in Tool
    },
    "metadata_definitions": metadata_definitions_path(),
    # Sharing itself. It carries no sharing leg of its own: resource_access
    # reads this table, so a policy here that called it would not resolve.
    # ``direct()`` derives none, because the table is no tool's own.
    "resource_grants": direct(),
    # Who asked for a resource, and the answer: the initiative's gate, with
    # who reads and writes which rows narrowed in ``app.db.guild_ddl``.
    "share_requests": direct(),
    # The change log itself, read like the content each change describes: a
    # person reads a change only where they can open the tool instance that
    # governs it (``dac_tool``/``dac_id``, stamped by the capture trigger), as
    # with the search index. The poller and the levels pass read it as the
    # system, so a subscription's reach is still the scope it names (see
    # outbox_poller's module docstring). Writing is the capture trigger's alone
    # (app.db.guild_ddl._WRITTEN_BY).
    "event_outbox": named_tool_path(),
    # The events installed plug-ins emit, scoped by the initiative an event names
    # like the change log beside it. Written by the system engine alone
    # (app.db.guild_ddl._WRITTEN_BY) and read by the poller.
    "plugin_event_outbox": direct(),
    # The search index. Derived from the content tables, and gated like them.
    "search_entries": named_tool_path(entity=("entity_type", "entity_id")),
    # Integration config, reached by whoever can reach what it watches.
    "webhook_subscriptions": webhook_subscription_path(),
    "guest_invite_grants": administration_path(),
    # Stored files, reached through the initiative whose content shows them.
    "uploads": uploads_path(),
    # Reports a community settles. Reached by whoever already sees everything
    # in the initiative, plus the guild admin — see direct_full_access.
    "moderation_reports": direct_full_access(),
    "moderation_report_reporters": via_full_access("moderation_reports", "report_id"),
    "moderation_actions": direct_full_access(),
    # Where a stream of operations work lands. Reached by whoever can reach the
    # project it names, which is the initiative that does the work.
    "intake_bindings": via("projects", "project_id"),
    # One hop -> projects
    "tasks": via("projects", "project_id"),
    "task_statuses": via("projects", "project_id"),
    "task_types": via("projects", "project_id"),
    # One hop -> files
    "file_versions": via("files", "file_id"),
    # One hop -> queues
    "queue_items": via("queues", "queue_id"),
    # One hop -> counter_groups
    "counters": via("counter_groups", "counter_group_id"),
    # One hop -> wikis. The page tree is a column on this table, not a
    # second path: every page of a wiki is reached exactly as hard as the
    # wiki, however deep it sits.
    "wiki_pages": via("wikis", "wiki_id"),
    # One hop -> calendars
    "calendar_events": via("calendars", "calendar_id"),
    # One hop -> dashboards
    # One hop -> posts
    "post_reads": via("posts", "post_id"),
    # Seen through their files, changed by the initiative's file makers.
    "collections": collections_path(),
    "collection_files": collection_files_path(),
    "post_polls": via("posts", "post_id"),
    # Two hops -> tasks -> projects
    "task_assignees": via_task_project("task_id"),
    # A case is read exactly as hard as the task it describes, so it hangs off
    # the task rather than off the project column it is keyed by.
    "intake_cases": via_task_project("task_id"),
    # What a person attached: reached as its report or its case is.
    "evidence": evidence_path(),
    # Two hops -> queue_items -> queues
    # Two hops -> post_polls -> posts
    "post_poll_options": via_post_poll("poll_id"),
    "post_poll_votes": via_post_poll("poll_id"),
    # Two hops -> calendar_events -> calendars
    "calendar_event_attendees": via_event_calendar("calendar_event_id"),
    "calendar_event_answers": via_event_calendar("calendar_event_id"),
    # Every metadata value, properties included, on any tool and sub-tool and
    # on an install, by (entity_type, entity_id).
    "metadata_values": metadata_values_path(),
    # An initiative's views of one tool instance, or of a shared page.
    "tool_layouts": tool_layouts_path(),
    "comments": comments_path(),
    # Polymorphic over what it is on; gated by that thing's own path.
    "reactions": reactions_path(),
    "relationships": relationships_path(),
    # Per-user state, scoped via the entity it points at: a queued line is
    # gated like the task or the reacted-to thing it describes.
    "batched_notices": batched_notices_path(),
    "event_reminder_dispatches": via_event_calendar("event_id"),
    "personal_items": content_kind_path(),
    "engagement_levels": content_kind_path(),
}

# Derived — the classification follows the registry, never duplicates it.
INITIATIVE_SCOPED_TABLES: frozenset[str] = frozenset(INITIATIVE_PATHS)


@dataclass(frozen=True)
class NamedPerson:
    """A column on content that names a person. When the person leaves the
    initiative the content belongs to, or the community, they are taken off
    it (the departure section in ``guild_ddl``)."""

    table: str
    column: str
    #: The row stays and the column is emptied, rather than the row deleted.
    clear: bool = False


NAMED_PEOPLE: tuple[NamedPerson, ...] = (
    NamedPerson("task_assignees", "user_id"),
    NamedPerson("calendar_event_attendees", "user_id"),
    NamedPerson("calendar_event_answers", "user_id"),
    NamedPerson("metadata_values", "value_user_id", clear=True),
    NamedPerson("queue_items", "user_id", clear=True),
    # What somebody asked for goes with them: nobody is left to answer for.
    NamedPerson("share_requests", "user_id"),
)


def initiative_of(table: str, row: str, *, qualify: str = "") -> str:
    """The initiative a row of ``table`` belongs to, as a sub-select, walked
    through the hops its policies declare. ``qualify`` goes before each table
    name (a schema). A table that names its subject as a ``(kind, id)`` pair,
    or holds its own ``initiative_id``, has no hops to walk, and answers
    through its own ``initiative_expr``."""
    path = INITIATIVE_PATHS[table]
    if path.dac is None or not path.dac.via:
        return path.initiative_expr(row)
    hops = path.dac.via
    joins = f"{qualify}{hops[0][1]} h1"
    for i, (fk, parent) in enumerate(hops[1:], start=2):
        joins += f" JOIN {qualify}{parent} h{i} ON h{i}.id = h{i - 1}.{fk}"
    return (
        f"(SELECT h{len(hops)}.initiative_id FROM {joins}"
        f" WHERE h1.id = {row}.{hops[0][0]})"
    )


#: Which commands ask the sharing gate at WRITE level, for the tables that
#: deviate from the default — where every writing command does.
#:
#: An entry states what the table's own endpoints state, so the policy and the
#: service ask the same question of the same row:
#:
#: - **Nothing** for a reader's own record OF a resource — a bookmark, a view,
#:   a read receipt, a poll answer, an RSVP. Reordering and bookmarking a
#:   project, recording a view, marking a notice read, answering a poll and
#:   answering an invitation are all endpoints that take read access; the RSVP
#:   one says so in as many words ("RSVPing is answering an invitation, not
#:   editing the event").
#: - **Nothing** for comments and reactions. Responding to something is not
#:   editing it: you may answer a notice you cannot rewrite. What gates a
#:   response is whether you can reach the thing at all, plus the thread's own
#:   switch — so every command here asks at read, and the switch is the
#:   endpoint's to apply.
#:
#: Membership is a statement about the table, not about the gate: initiative
#: membership and the schema boundary still apply in full.
#: Responding to something asks nothing of write — named, so the tables that
#: are one gesture and its bookkeeping cannot drift apart.
_RESPONDING: frozenset[str] = frozenset()

DAC_WRITE_COMMANDS: dict[str, frozenset[str]] = {
    "personal_items": frozenset(),
    "post_reads": frozenset(),
    "post_poll_votes": frozenset(),
    "calendar_event_attendees": frozenset(),
    # One occurrence's answer, the same gesture as the attendee row's.
    "calendar_event_answers": frozenset(),
    # A record that this reader was reminded, written where the reminder is
    # sent. Being told about an event is a reader's business, not a change to
    # the calendar.
    "event_reminder_dispatches": _RESPONDING,
    "comments": _RESPONDING,
    "reactions": _RESPONDING,
    # A queued line is written in the same request as what it describes. An
    # assignment's asks write of the task's sharing when it is queued
    # (``batched_notices_path`` narrows this to those rows); taking or clearing
    # it is the recipient's own business, done as them.
    "batched_notices": frozenset({"INSERT"}),
}

#: The default: a command that writes asks at write level.
ALL_WRITE_COMMANDS: frozenset[str] = frozenset({"INSERT", "UPDATE", "DELETE"})

assert DAC_WRITE_COMMANDS.keys() <= INITIATIVE_SCOPED_TABLES, (
    "DAC_WRITE_COMMANDS names a table that is not initiative-scoped: "
    f"{sorted(DAC_WRITE_COMMANDS.keys() - INITIATIVE_SCOPED_TABLES)}"
)
assert all(
    commands <= ALL_WRITE_COMMANDS for commands in DAC_WRITE_COMMANDS.values()
), "DAC_WRITE_COMMANDS names a command that does not write"


def governing_path(table: str) -> tuple[Tool, tuple[tuple[str, str], ...]] | None:
    """The tool that governs ``table``'s rows and the join chain that reaches it.

    The app-layer half of the sharing leg the policies are rendered from — one
    declaration, read two ways, so an endpoint resolving "which project does
    this task belong to, and is it shared with me" cannot answer differently
    from the policy that already decided it.

    ``()`` as the chain means the row IS the resource (``projects`` → project).
    ``None`` means no single tool governs the table: a polymorphic one, where
    the answer is a property of the row, or a configuration table that no
    tool's sharing governs.
    """
    path = INITIATIVE_PATHS.get(table)
    if path is None or path.dac is None:
        return None
    tool = path.dac.tool
    if tool is None:
        # _dac_self reads it off the table name at render time rather than
        # storing it; a table that is no tool's own has no answer here.
        tool = _TOOL_BY_TABLE.get(table)
        if tool is None:
            return None
        return tool, ()
    return tool, path.dac.via


def dac_asks_at_write(table: str, command: str) -> bool:
    """Whether ``table``'s sharing leg asks at write level for ``command``."""
    return command in DAC_WRITE_COMMANDS.get(table, ALL_WRITE_COMMANDS)


# ---------------------------------------------------------------------------
# Change capture: what emits, and as what
# ---------------------------------------------------------------------------
#
# One registry, holding only DEVIATIONS from the default. The default is derived:
# a table in INITIATIVE_PATHS emits, scoped by that same path, naming itself.
# So an ordinary new content table needs no entry here at all — which is the
# whole point, and why the deviations are stated rather than the members.


@dataclass(frozen=True)
class ReportsAs:
    """Report a table's changes as an update to a DIFFERENT resource.

    Some tables have an id of their own without being something a subscriber
    fetches on its own: a project's statuses, a file's version history, an
    initiative's roles, a resource's sharing. Each is a facet of the thing it
    belongs to, and saying so is what keeps every event's id resolvable — the
    parent already has a detail route, so adding one of these owes no new API
    surface.

    Junctions get this shape for free (``task_tags`` -> ``tasks.updated`` with
    ``changed = ['tags']``, derived from the composite key). This is the explicit
    form, for tables whose own primary key would otherwise make them look
    independently addressable.
    """

    #: Resource types an event from this table can name. Usually one; a grant
    #: names whichever tool it is on, so the vocabulary needs the whole set.
    resource_types: frozenset[str]
    #: Row expression yielding that resource's id.
    id_expr: RowLocator
    #: Label reported in ``changed``.
    facet: str
    #: Row expression yielding the resource TYPE, for the polymorphic case.
    #: ``None`` when ``resource_types`` holds the single constant answer.
    type_expr: RowLocator | None = None
    #: Distinguishes this report from the others a table declares, in the
    #: trigger's name. ``None`` for the ordinary one-report table, which keeps
    #: every existing trigger named exactly as it is today.
    label: str | None = None
    #: Row expression yielding the label for ``changed``, where the answer
    #: depends on the row rather than on the table. ``facet`` stays the constant
    #: the rest of the registry reads; this is what the trigger evaluates.
    facet_expr: RowLocator | None = None
    #: Every label ``facet_expr`` can yield. The static counterpart to the
    #: expression, the way ``resource_types`` is to ``type_expr`` — a subscriber
    #: names a field before any row exists, so the vocabulary has to be known without
    #: evaluating anything. Empty where ``facet`` is the whole answer.
    facet_values: frozenset[str] = frozenset()
    #: Row expression yielding the initiative THIS report is scoped to, where
    #: the table's own answer is not the one this report wants. A table
    #: reporting against two different resources answers this twice. The parent
    #: chain needs no counterpart — it already resolves from the resource the
    #: report names.
    initiative_expr: RowLocator | None = None
    #: The label a row going away reports under, where it differs from the one
    #: a row arriving reports under (``facet``): a junction whose direction is
    #: the news. ``None`` where one label says both.
    facet_on_delete: str | None = None
    #: The chain this report carries, read off the row, where the resource it
    #: names is not where the row hangs: a file reported as added to a
    #: collection names that collection. ``None`` borrows the resource's own.
    parents: ParentsLocator | None = None


def reports_as(parent: str, fk: str, facet: str) -> ReportsAs:
    """Facet of one fixed parent, reached by a foreign key on the row."""
    return ReportsAs(
        resource_types=frozenset({parent}),
        id_expr=lambda r: f'{r}."{fk}"',
        facet=facet,
    )


def grants_report_on_their_resource() -> ReportsAs:
    """A grant is sharing ON something — report it against that something.

    ``resource_type`` holds the Tool value and ``resource_id`` its id, so the
    event lands on the project (or file, queue, …) whose access changed.
    That is both what a subscriber wants to hear and already resolvable, where
    the grant row's own id resolves nowhere.

    An unrecognized ``resource_type`` yields NULL from the CASE and the row is
    skipped, so the vocabulary below and what the trigger can emit stay the same
    set.
    """
    arms = " ".join(f"WHEN '{t.value}' THEN '{t.plural}'" for t in Tool)
    return ReportsAs(
        resource_types=frozenset(t.plural for t in Tool),
        id_expr=lambda r: f"{r}.resource_id",
        facet="sharing",
        type_expr=lambda r: f"(CASE {r}.resource_type {arms} END)",
    )


def reactions_report_on_their_target() -> ReportsAs:
    """A reaction is a facet OF what it is on — report it there.

    The reaction row's own id resolves to no route (there is no
    ``/reactions/{id}`` to re-read), where the comment it lands on already has
    one. So the event says "this comment changed, facet: reactions" and the
    subscriber re-reads the comment, whose read carries the current counts.
    """
    arms = " ".join(
        f"WHEN '{target.value}' THEN '{target.table}'" for target in ReactionTarget
    )
    return ReportsAs(
        resource_types=frozenset(target.table for target in ReactionTarget),
        id_expr=lambda r: f"{r}.target_id",
        facet="reactions",
        type_expr=lambda r: f"(CASE {r}.target_type {arms} END)",
    )


def _reported_as(table: str) -> tuple[str, Callable[[str], str]]:
    """The resource an event about a row of ``table`` names, and how to reach
    its id.

    A row is not always a thing a subscriber fetches: a file's version has no
    route of its own, and its own table says so by reporting against its file. A row
    naming one (an edge end, a property value) has to name what that table
    names, or the event would carry an id nothing can re-read — so the answer
    comes from the table's own registry entry rather than from a second
    decision here.
    """
    declared = event_source(table).reports_as
    if declared is None:
        return table, lambda alias: f"{alias}.id"
    report = declared[0] if isinstance(declared, tuple) else declared
    (parent,) = report.resource_types
    return parent, report.id_expr


def relationships_report_on_both_ends() -> tuple[ReportsAs, ...]:
    """An edge is a facet of BOTH things it connects, so it reports twice.

    One event would leave the other end's watchers unaware — and for a symmetric
    type there is no "main" end to pick, because the stored source is whichever
    node id sorted lower. Each event names only its own end and is scoped to
    that end's own initiative, so a subscriber is told that something it can see
    changed and re-reads it through RLS, which ANDs both ends and hands back
    only what that reader may have.

    An end that belongs to no initiative — a tag — resolves NULL, and the
    capture function writes no event it cannot scope. The other end still
    reports, so the change is heard once, by the initiative it happened in.

    **The label comes from the primitive**, read per row: a ``tagged_with`` edge
    reports ``changed = ['tags']`` whatever the two things are, which is what a
    junction named ``task_tags`` derived from its own name. Storage moves; a
    subscriber's field filter does not.
    """
    facet_arms = " ".join(
        f"WHEN '{t.value}' THEN '{FACETS[t]}'" for t in RelationshipType
    )
    reports = {kind: _reported_as(ep.table) for kind, ep in ENDPOINT_KINDS.items()}

    def one(side: str) -> ReportsAs:
        type_arms = " ".join(
            f"WHEN '{kind.value}' THEN '{resource}'"
            for kind, (resource, _) in reports.items()
        )

        def id_of(r: str) -> str:
            arms = " ".join(
                f"WHEN '{kind.value}' THEN (SELECT {id_expr('rl')} "  # noqa: S608
                f"FROM {ENDPOINT_KINDS[kind].table} rl WHERE rl.id = {r}.{side}_id)"
                for kind, (_, id_expr) in reports.items()
            )
            return f"(CASE {r}.{side}_type {arms} END)"

        def init(path: InitiativePath, alias: str) -> str:
            return path.initiative_expr(alias)

        return ReportsAs(
            resource_types=frozenset(resource for resource, _ in reports.values()),
            id_expr=id_of,
            # The constant the registry reads when it needs one name for the
            # table; what the trigger evaluates is the expression below.
            facet=FACETS[RelationshipType.related_to],
            facet_expr=lambda r: f"(CASE {r}.relationship_type {facet_arms} END)",
            facet_values=frozenset(FACETS.values()),
            type_expr=lambda r: f"(CASE {r}.{side}_type {type_arms} END)",
            initiative_expr=lambda r: _relationship_end(r, side, init),
            label=side,
        )

    return (one("source"), one("target"))


def values_report_on_their_target(kinds: Iterable[str], facet: str) -> ReportsAs:
    """A value kept on a ``(entity_type, entity_id)`` pair — a property value,
    a plug-in's value — is a facet OF what it is on: report it there.

    Whatever that thing itself reports as: a task's values as the task, a
    property definition's as its initiative. The subscriber re-reads it, and its read carries
    the current values. A pair naming none of ``kinds`` resolves to nothing,
    and the row is skipped.
    """
    tables = {target: entity_tables()[target] for target in kinds}
    reports = {target: _reported_as(table) for target, table in tables.items()}
    type_arms = " ".join(
        f"WHEN '{target}' THEN '{resource}'"
        for target, (resource, _) in reports.items()
    )

    def id_of(r: str) -> str:
        arms = " ".join(
            f"WHEN '{target}' THEN (SELECT {id_expr('pv')} "  # noqa: S608
            f"FROM {tables[target]} pv WHERE pv.id = {r}.entity_id)"
            for target, (_, id_expr) in reports.items()
        )
        return f"(CASE {r}.entity_type {arms} END)"

    return ReportsAs(
        resource_types=frozenset(resource for resource, _ in reports.values()),
        id_expr=id_of,
        facet=facet,
        type_expr=lambda r: f"(CASE {r}.entity_type {type_arms} END)",
    )


def layouts_report_on_their_target() -> ReportsAs:
    """A layout is a facet of the instance it is for, or of its initiative when
    it is for a shared tool. Whoever shows the set re-reads it."""
    arms = " ".join(
        f"WHEN '{target}' THEN '{table}'"
        for target, table in LAYOUT_INSTANCE_TABLES.items()
    )
    return ReportsAs(
        resource_types=frozenset(LAYOUT_INSTANCE_TABLES.values()) | {"initiatives"},
        id_expr=lambda r: f"COALESCE({r}.tool_id, {r}.initiative_id)",
        facet="layouts",
        type_expr=lambda r: (
            f"(CASE WHEN {r}.tool_id IS NULL THEN 'initiatives'"
            f" ELSE (CASE {r}.tool {arms} END) END)"
        ),
    )


def poll_options_report_on_their_post() -> ReportsAs:
    """A poll option is a facet of the notice that asks the question.

    Its own id resolves to no route — there is no ``/poll-options/{id}`` to
    re-read — where the post already has one, and re-reading the post carries
    the whole poll back. The poll itself reports the same way through its own
    ``post_id``; this is the one hop further out.
    """
    return ReportsAs(
        resource_types=frozenset({"posts"}),
        id_expr=lambda r: (
            f"(SELECT post_polls.post_id FROM post_polls "  # noqa: S608
            f"WHERE post_polls.id = {r}.poll_id)"
        ),
        facet="poll",
    )


@dataclass(frozen=True)
class Silent:
    """This table gets no capture trigger, and why not."""

    reason: str


@dataclass(frozen=True)
class Emit:
    """This table emits, deviating from the derived default in some respect."""

    #: How a row resolves its initiative, when INITIATIVE_PATHS has no entry —
    #: i.e. the table emits but carries no initiative-member RLS.
    initiative: RowLocator | None = None
    #: The row belongs to no initiative at all and a NULL is EXPECTED. Only ever
    #: correct for a table every guild member can already read.
    guild_wide: bool = False
    #: Report against a parent resource instead of naming this table. A tuple
    #: emits one event per entry — for a row that is a facet of more than one
    #: thing, so every surface it shows on is told to re-read.
    reports_as: ReportsAs | tuple[ReportsAs, ...] | None = None
    #: Publish this table's own events under this resource type instead of the
    #: table's name, for a table whose API segment differs from it. Keeps the
    #: readback rule (``resource_type`` -> the detail route that serves the id)
    #: derivable without a second route. Meaningless beside ``reports_as``,
    #: which names its parent instead.
    resource_type: str | None = None
    #: While this row expression holds, the row is not news: it emits nothing,
    #: and the moment it stops holding is reported as a create (the moment it
    #: starts, as a delete). For content that exists before it is anybody
    #: else's business — a notice still being drafted, which its author can
    #: reach and nobody else can. The same shape as the soft-delete rule the
    #: trigger already applies, read from the other end.
    quiet_when: RowLocator | None = None
    #: This table's events name no actor. For a gesture whose author is the
    #: private part of it: an event still says the thing moved, which is what a
    #: reader needs to re-read it, and says nothing about who moved it.
    anonymous: bool = False
    #: Only a row this row expression holds for is news: a change emits when
    #: it holds for the row before or after it, and a row it never holds for
    #: emits nothing. Rendered as the capture triggers' ``WHEN``, so the rest
    #: of the table's writes never call the capture function. For a table
    #: whose rows only some readers are shown.
    when: RowLocator | None = None


#: table -> how it deviates. Anything absent takes the derived default.
EVENT_SOURCES: dict[str, Emit | Silent] = {
    # -- Silent ------------------------------------------------------------
    "event_outbox": Silent("the log cannot log itself"),
    "plugin_event_outbox": Silent("delivered by the poller as events of its own"),
    # What one member did with their own UI, not a change to the initiative's
    # content, so every subscription would pay for pure noise.
    "search_entries": Silent("derived index, rebuilt from the content it mirrors"),
    "engagement_levels": Silent("derived ranking, rewritten by the hourly pass"),
    "personal_items": Silent(
        "one member's own opens, bookmarks, subscriptions and order"
    ),
    "batched_notices": Silent("internal batching bookkeeping"),
    "event_reminder_dispatches": Silent("internal reminder bookkeeping"),
    "webhook_subscriptions": Silent(
        "integration config; it reports on content, not on itself"
    ),
    "intake_bindings": Silent("routing config; it reports on no content"),
    "guest_invite_grants": Silent("an invite's terms; redeeming it is recorded"),
    "share_requests": Silent(
        "a person asking; the sharing an answer writes is what changes"
    ),
    "moderation_reports": Silent("who reported whom is not an automation signal"),
    "moderation_report_reporters": Silent("the reporters behind one report"),
    "moderation_actions": Silent("the moderation log, read on its own surface"),
    "intake_cases": Silent("the key -> task map; the task is what a subscriber hears"),
    "uploads": Silent("a stored file; the content showing it is what changed"),
    "evidence": Silent("an attached file; its case or report is what changed"),
    # -- Guild-level tables that emit ---------------------------------------
    # The structural initiative tables are deliberately exempt from
    # initiative-member RLS (a membership table gated by the membership check it
    # backs would recurse), and that exemption must not also mean "invisible to
    # every automation" — creating an initiative, adding a member, changing a
    # role are all things a subscriber acts on. They get a capture trigger and
    # nothing else; no policy is rendered from this registry. The outbox row
    # carries a real initiative_id, so RLS scopes the EVENT normally.
    "initiatives": Emit(initiative=lambda r: f"{r}.id"),
    "initiative_members": Emit(initiative=lambda r: f"{r}.initiative_id"),
    "initiative_roles": Emit(
        initiative=lambda r: f"{r}.initiative_id",
        reports_as=reports_as("initiatives", "initiative_id", "roles"),
    ),
    "initiative_rules": Emit(
        initiative=lambda r: f"{r}.initiative_id",
        reports_as=reports_as("initiatives", "initiative_id", "roles"),
    ),
    # -- Guild-wide: no initiative at all -----------------------------------
    # The row carries a NULL initiative_id, which the access function reads as
    # "the initiative gate has nothing to decide" and admits for any guild
    # member. Correct here rather than weakening: tags are already readable by
    # every member of the guild, run through most flows, and an automation that
    # cannot see them is missing an ordinary trigger. The envelope carries ids
    # and column names only, never values.
    #
    # The trigger is told a NULL is expected here specifically, so an
    # initiative-scoped row whose lookup fails still means "skip".
    "tags": Emit(guild_wide=True),
    # -- Not news yet -------------------------------------------------------
    # A draft is reachable by the people who could edit it and nobody else, and
    # the board it will appear on has not changed. Publication is the event,
    # from whichever of the two places does it — posted outright, or stamped by
    # the scheduler.
    # ``published_at`` is the fact, where ``scheduled_for`` is only the
    # intention — the same column ``is_published_clause`` reads.
    "posts": Emit(quiet_when=lambda r: f"{r}.published_at IS NULL"),
    # Installed plug-ins, same reasoning: the install row is guild-wide knowledge
    # (every member's sidebar lists it), so its lifecycle emits guild-wide too.
    # A subscriber hears an install appear, change (``config_state`` moving is
    # the moment a plug-in becomes usable), or go away, and re-reads current state
    # through the API like any other event. Published as ``plugins`` because that
    # is the segment the install's detail route lives at (``/plugins/{id}``).
    "guild_plugins": Emit(guild_wide=True, resource_type="plugins"),
    # -- Facets of their parent ---------------------------------------------
    "task_statuses": Emit(reports_as=reports_as("projects", "project_id", "statuses")),
    "task_types": Emit(reports_as=reports_as("projects", "project_id", "types")),
    # A property definition is read in its initiative's list, not at an
    # address of its own, so a change to one reports as that initiative; a
    # project's or a collection's metadata is read with its owner, and
    # reports as it. A plug-in's is its manifest's, and reports as nothing.
    "metadata_definitions": Emit(
        reports_as=ReportsAs(
            resource_types=frozenset({"initiatives", "projects", "collections"}),
            id_expr=lambda r: (
                f"COALESCE({r}.project_id, {r}.collection_id, {r}.initiative_id)"
            ),
            facet="properties",
            type_expr=lambda r: (
                f"(CASE WHEN {r}.project_id IS NOT NULL THEN 'projects'"
                f" WHEN {r}.collection_id IS NOT NULL THEN 'collections'"
                " ELSE 'initiatives' END)"
            ),
        )
    ),
    # A layout is read in its instance's set, or its initiative's for a shared
    # tool, so a change reports as that.
    "tool_layouts": Emit(reports_as=layouts_report_on_their_target()),
    # An answer is read with the event it answers, as its attendees are.
    "calendar_event_answers": Emit(
        reports_as=reports_as("calendar_events", "calendar_event_id", "answers")
    ),
    "file_versions": Emit(reports_as=reports_as("files", "file_id", "versions")),
    # A file going into a collection or out of one changes the collection's
    # list, and is news about the file too: which file, which collection, and
    # which way, the collection in the file's chain.
    "collection_files": Emit(
        reports_as=(
            reports_as("collections", "collection_id", "files"),
            ReportsAs(
                resource_types=frozenset({"files"}),
                id_expr=lambda r: f"{r}.file_id",
                facet="added_to_collection",
                facet_on_delete="removed_from_collection",
                parents=lambda r: _one_parent("collections", f"{r}.collection_id"),
                label="file",
            ),
        )
    ),
    # A draft page is read only by the wiki's writers, so like an unpublished
    # notice it is not news until it is finished.
    "wiki_pages": Emit(quiet_when=lambda r: f"{r}.is_draft"),
    "resource_grants": Emit(reports_as=grants_report_on_their_resource()),
    "post_polls": Emit(reports_as=reports_as("posts", "post_id", "poll")),
    "post_poll_options": Emit(reports_as=poll_options_report_on_their_post()),
    # A vote is the one gesture whose author is the private half of it — a poll
    # may be anonymous. So it reports as the notice being answered, like the
    # poll and its options do, and names nobody: a reader hears the tallies
    # moved and re-reads the post, which is where the results live anyway. One
    # rule for every poll, rather than a flag that can be got wrong per poll.
    "post_poll_votes": Emit(
        reports_as=poll_options_report_on_their_post(), anonymous=True
    ),
    "reactions": Emit(reports_as=reactions_report_on_their_target()),
}

_SILENT: frozenset[str] = frozenset(
    t for t, source in EVENT_SOURCES.items() if isinstance(source, Silent)
)

# The tables the capture trigger is installed on: initiative-scoped content,
# plus the guild-level tables that declared themselves emitters, minus whatever
# declared itself silent.
EVENTED_TABLES: frozenset[str] = (
    INITIATIVE_SCOPED_TABLES
    | frozenset(t for t, source in EVENT_SOURCES.items() if isinstance(source, Emit))
) - _SILENT


def event_source(table: str) -> Emit:
    """How ``table`` emits — its declared deviations, or the derived default."""
    source = EVENT_SOURCES.get(table)
    return source if isinstance(source, Emit) else Emit()


# Registered after the registry it reads: an edge reports against whatever its
# endpoints report against, so it can only be built once every endpoint's own
# entry above exists.
EVENT_SOURCES["relationships"] = Emit(reports_as=relationships_report_on_both_ends())
# The same, for whatever a metadata value is on; an install's values on itself
# name no item, and are skipped. A plug-in's values report as ``plugin_values``,
# which is no news about the item (``activity_feed.QUIET_FACETS``), and one no
# reader is shown is the plug-in's own and changes nothing a reader sees.
EVENT_SOURCES["metadata_values"] = Emit(
    quiet_when=lambda r: (
        "EXISTS (SELECT 1 FROM metadata_definitions md "  # noqa: S608
        f"WHERE md.id = {r}.property_id AND md.install_id IS NOT NULL"
        f" AND NOT {r}.entity_type = ANY (md.shown_on))"
    ),
    reports_as=replace(
        values_report_on_their_target(PROPERTY_TARGETS, "properties"),
        facet_expr=lambda r: (
            "(CASE WHEN EXISTS (SELECT 1 FROM metadata_definitions md "  # noqa: S608
            f"WHERE md.id = {r}.property_id AND md.install_id IS NOT NULL)"
            " THEN 'plugin_values' ELSE 'properties' END)"
        ),
        facet_values=frozenset({"properties", "plugin_values"}),
    ),
)


def initiative_locator(table: str) -> RowLocator:
    """Row expression yielding the initiative an event about ``table`` belongs to.

    One question, answered from the registry that already knows: an
    initiative-scoped table reuses the very path that renders its RLS, so a row
    can never be gated by one initiative and have its events attributed to
    another. Guild-level emitters say so themselves.
    """
    source = event_source(table)
    if source.guild_wide:
        return lambda _row: "NULL::integer"
    if source.initiative is not None:
        return source.initiative
    path = INITIATIVE_PATHS.get(table)
    if path is None:
        raise RuntimeError(
            f"{table} emits events but nothing resolves the initiative they "
            "belong to — add an INITIATIVE_PATHS entry, or an Emit(initiative=…)"
        )
    return path.initiative_expr
