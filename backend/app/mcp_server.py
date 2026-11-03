"""In-app MCP server.

Mounted at ``/api/v1/mcp/`` only when ``settings.ENABLE_MCP`` is set. Tools are
*route-backed*: each call flows through the real FastAPI route, so the PAT
authentication and the six RLS gates apply by reuse — never re-implemented.

The surface is curated and default-deny, so a newly added route can't silently
become a tool:
  * **Reads** — every ``GET`` route for initiatives and for the tools they hold
    (projects and tasks, files, queues, counters, calendars and their
    events, wikis and their pages, notices, dashboards), plus the two comment
    reads that pair with the comment write (a parent's thread and a single
    comment by id), plus the one relationships read, which answers what a thing
    is linked to, plus the guild's general search, which finds a thing by name,
    plus the caller's list of communities, which says what ``community_id``
    every other tool takes. A handful are carved back out: file downloads, who
    voted and who has read, and the dashboard editor's own palette.
  * **Writes** — an explicit allow-list, matched by path shape: create and edit
    every tool (projects, files, queues, counters, calendars, wikis,
    notices, dashboards) and the things they hold (tasks, queue items, counters,
    calendar events, wiki pages, comments), plus the two writes that shape alone
    doesn't reach — moving a task, and moving a counter's count — plus drawing
    one relationship between two of them. Each is gated client-side by Claude Code's
    per-write permission prompt. Destructive (delete, archive, reset), bulk
    (reorder, batch, archive-all, replacing a thing's links wholesale),
    AI-generation, sharing (grants), and property/tag routes are deliberately
    excluded. A tool's create still takes its initial ``grants``, as it does in
    the app: who a new thing is shared with is part of making it.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Iterator

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.openapi.models import HTTPRoute

from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.config import PROJECT_NAME
from app.mcp_descriptions import describe as describe_tool
from app.models.tenant.task import TaskStatusCategory
from app.core.tools import Tool
from app.services import fields as fields_registry
from app.services.compact import trim

if TYPE_CHECKING:
    import mcp.types as mt
    from fastapi import FastAPI

# Read surface: every GET route carrying these FastAPI tags becomes a tool.
# ``task-statuses`` and ``task-types`` expose only their GETs (list a
# project's statuses, or its types) — their other routes aren't in the write
# allow-list, so they stay excluded — giving a caller the ids needed to place,
# type or move a task.
#
# Every tool an initiative holds is readable, not only the two it starts with.
# An agent asked "how is this going" was previously answering from tasks alone,
# which is the shape of the question rather than the shape of the work: the
# rota is a queue, the write-up is a file, the numbers are counters, and
# what somebody would actually look at first is a dashboard. The write surface
# in ``_WRITE_ROUTE_MAPS`` covers the same set, so what an agent can read it can
# also author and edit.
READ_TAGS = (
    # Every tool's own tag, as its list is published under.
    *(TOOL_LISTS[tool].tag or tool.plural for tool in Tool),
    "tasks",
    "initiatives",
    "task-statuses",
    "task-types",
    "calendar-events",
    # A window of a calendar: its events, a repeating one expanded into its
    # occurrences, beside the tasks due in it. The events have no list of
    # their own; this is what "what's on this week" reads.
    "calendar-entries",
    # How many of each a page holds, and its tag tree: counted from the lists
    # above, for every tool at once.
    "tools",
)

# Curated writes: author and edit, across every tool.
#
# Matched by exact path *shape*, so only the pairs named here are exposed and
# everything else falls through to the default-deny catch-all below — delete,
# archive, reorder, duplicate, batch, AI generation, grants, properties/tags,
# uploads and imports are all outside it.
#
# The tool half is derived from the ``Tool`` enum rather than listed, for the
# same reason the read surface is: an eighth tool should arrive writable rather
# than wait for somebody to remember this list. ``counter_group`` is the only
# member whose path segment isn't already its plural spelling.
_ID = r"\{[^}]+\}"


def _create_and_edit(created_at: str, edited_at: str) -> list[RouteMap]:
    """The two route shapes that author and edit one kind of thing.

    ``POST /<created_at>`` creates and ``PATCH /<edited_at>/{id}`` edits. Both
    are anchored at the end, so a suffixed route on the same collection — an
    ``/archive``, a ``/grants``, a ``/properties``, a ``/reorder`` — matches
    neither and stays excluded.
    """
    return [
        RouteMap(
            methods=["POST"],
            pattern=r".*/" + created_at + r"/?$",
            mcp_type=MCPType.TOOL,
        ),
        RouteMap(
            methods=["PATCH"],
            pattern=r".*/" + edited_at + "/" + _ID + "$",
            mcp_type=MCPType.TOOL,
        ),
    ]


_WRITABLE_SEGMENTS = (
    # Every tool an initiative holds, addressed by its own path segment.
    *((tool.route_segment, tool.route_segment) for tool in Tool),
    # And what those tools hold in turn: a project's tasks, a calendar's
    # events, a queue's items, a counter group's counters, a wiki's pages. Not
    # derivable from the enum — each names its parent differently — so each is
    # spelled out. Tasks and events name their parent in the body; the other
    # three are added under it, and edited at their own id like the rest.
    ("tasks", "tasks"),
    ("calendar-events", "calendar-events"),
    ("queues/" + _ID + "/items", "queue-items"),
    ("counter-groups/" + _ID + "/counters", "counters"),
    ("wikis/" + _ID + "/pages", "wiki-pages"),
    # The comment surface every tool shares.
    ("comments", "comments"),
)

# Two writes that ``create``/``edit`` doesn't reach, added by hand:
#
#   * Moving a task to another status or project is its own route because it is
#     its own action, taking a destination rather than a field.
#   * A counter's count is the one thing about it ``PATCH`` cannot set — the
#     update schema shapes the counter (name, bounds, step, initial count) and
#     the count itself moves through these two. Without them, writing a
#     counter would mean renaming it. ``reset`` and ``reset-all`` are not here:
#     they discard counts rather than record one.
#   * Ticking one checklist item. ``PATCH /tasks/{id}`` rewrites the list's
#     lines but deliberately never its ``done`` flags, so without this an agent
#     that finished a piece of a task could say so only in a comment. It names
#     one item and touches only that one, the same write the app's checkbox
#     makes.
_EXTRA_WRITE_ROUTE_MAPS = [
    RouteMap(
        methods=["POST"], pattern=r".*/tasks/" + _ID + "/move$", mcp_type=MCPType.TOOL
    ),
    RouteMap(
        methods=["PATCH"],
        pattern=r".*/tasks/" + _ID + "/checklist/" + _ID + "$",
        mcp_type=MCPType.TOOL,
    ),
    *(
        RouteMap(
            methods=["POST"],
            pattern=r".*/counters/" + _ID + "/" + verb + "$",
            mcp_type=MCPType.TOOL,
        )
        for verb in ("set", "step")
    ),
]

_WRITE_ROUTE_MAPS = [
    *(m for segments in _WRITABLE_SEGMENTS for m in _create_and_edit(*segments)),
    *_EXTRA_WRITE_ROUTE_MAPS,
]

# Comment reads, matched by exact path shape rather than by adding ``comments``
# to ``READ_TAGS``, so only these two of the router's four GETs are exposed:
# list a parent's thread (``GET /comments/``) and read one comment back by id
# (``GET /comments/{id}``). Together they close the loop on the comment write —
# an agent can see the discussion on the task it is working and read back what
# it posted in a later session.
#
# The other two stay behind the default-deny catch-all. ``GET /comments/recent``
# is a guild-wide activity feed rather than a working surface — the same reason
# ``join-requests`` is carved out of the ``initiatives`` tag — and it reaches
# comments on parents (files, queues, counters, calendars, dashboards) that
# the tool surface otherwise doesn't cover, undirected by any task at hand.
# ``GET /comments/mentions/search`` backs the editor's @-mention picker; the
# member and task lookups an agent needs are already tools of their own.
_COMMENT_READ_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/comments/$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["GET"], pattern=r".*/comments/\{[^}]+\}$", mcp_type=MCPType.TOOL),
]

# The guild's general search: how a caller reaches a thing it knows the name of
# rather than the id of. Matched by path shape rather than by adding ``search``
# to ``READ_TAGS``, for the same reason the comment reads are — the router's
# other two GETs answer for a *picker* rather than for a question. ``recent``
# is what a field offers before anything is typed and ``suggest`` is titles to
# jump to while it is being typed; both describe a text input's behaviour. The
# search proper is the one an agent wants: ranked, narrowable by entity type
# and initiative, and carrying a ``total``, so "find the task called X" is one
# call instead of a guess at a filter.
_SEARCH_READ_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/search/$", mcp_type=MCPType.TOOL),
]

# The edges between the things above: read them, and draw one.
#
# Matched by path shape rather than by a tag or a ``_WRITABLE_SEGMENTS`` entry,
# for the same reason the comment reads are — a relationship is not a tool an
# initiative holds, and the router's four routes divide two and two, so each
# side is named rather than opted into wholesale.
#
# ``GET /relationships/`` answers what no tool read can: a task's payload
# carries its status, its people and its tags, but nothing about the task it
# blocks, the file it was written from, or the queue item it came out of —
# and that wiring is most of what "what is the state of this" means once a piece
# of work touches more than one tool. It answers for one thing at a time
# (``entity=task:12``), from that thing's side.
#
# ``POST /relationships/`` is the same create-and-edit reasoning the tool writes
# follow: what an agent can read it can also author, and an agent that files a
# task and writes the file behind it should be able to say so. There is no
# PATCH to pair with it — an edge has no fields to edit, only ends and a type,
# which are what it *is* — so the create stands alone. The endpoint refuses the
# links that aren't anybody's to assert by hand (a ``references`` edge is read
# out of a body when it is saved), ends in different initiatives, archived ends,
# and a source the caller can't write; none of that is re-implemented here.
#
# The router's other two stay behind the default-deny catch-all, on the grounds
# every other write is weighed against: ``PUT /relationships/`` replaces a whole
# slice of one thing's links, which is bulk *and* removes what it doesn't
# mention, and ``DELETE /relationships/{id}`` is a delete. An agent can wire two
# things together; unwiring them is done in the app.
_RELATIONSHIP_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/relationships/$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["POST"], pattern=r".*/relationships/$", mcp_type=MCPType.TOOL),
]

# The caller's communities: the one way to learn the ``community_id`` every
# other tool takes. Without it a session began by guessing an id and reading
# the refusal. Matched by path shape, as the reads above are — the router's
# other GETs are one community's administration (its members, its invites, its
# settings) rather than a list to start from. The route itself narrows what a
# key is shown to the communities it can address.
_COMMUNITY_READ_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/communities/$", mcp_type=MCPType.TOOL),
]

# Carved out of the tag rules below, each for a reason the tag itself cannot
# express. Ordered ahead of them so the exclusion wins.
_TOOL_READ_EXCLUSIONS = [
    # Bytes rather than an answer. A download hands back a file — an uploaded file's
    # contents, or one of its versions — and an export hands back a calendar
    # file. Neither is something a tool result can carry usefully, and a large
    # one would fill a caller's context with an attachment it cannot open.
    RouteMap(pattern=r".*/download$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r".*/export\.ics$", mcp_type=MCPType.EXCLUDE),
    # Who voted which way, and who has read a notice. Both are about people
    # rather than about the work, and neither is answerable from the thing an
    # agent was asked to do — the same reason join requests are carved out of
    # the initiatives tag.
    RouteMap(pattern=r".*/poll/voters$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r".*/reads$", mcp_type=MCPType.EXCLUDE),
    # The editor's own vocabulary. ``widget-catalog`` is the palette a person
    # arranges a dashboard from and ``installed-listings`` is what the
    # marketplace has put in this guild; both describe the authoring surface
    # rather than anything a dashboard is showing.
    RouteMap(pattern=r".*/widget-catalog$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r".*/installed-listings$", mcp_type=MCPType.EXCLUDE),
]

_ROUTE_MAPS = [
    # A collection's own writes are not on the write surface, and adding files
    # to one would otherwise read as creating a file.
    RouteMap(
        methods=["POST", "PATCH", "DELETE"],
        pattern=r".*/collections/.*",
        mcp_type=MCPType.EXCLUDE,
    ),
    *_WRITE_ROUTE_MAPS,
    *_COMMENT_READ_ROUTE_MAPS,
    *_SEARCH_READ_ROUTE_MAPS,
    *_RELATIONSHIP_ROUTE_MAPS,
    *_COMMUNITY_READ_ROUTE_MAPS,
    *_TOOL_READ_EXCLUSIONS,
    # Carved out of the ``initiatives`` read surface below: a join request names
    # who asked to be let in and carries their free-text note, which is
    # membership administration for a manager to answer rather than part of the
    # project/task surface these tools serve. Ordered ahead of the tag rule so
    # the exclusion wins.
    RouteMap(pattern=r".*/join-requests.*", mcp_type=MCPType.EXCLUDE),
    *(
        RouteMap(methods=["GET"], tags={tag}, mcp_type=MCPType.TOOL)
        for tag in READ_TAGS
    ),
    # Default-deny: anything not opted in above is excluded.
    RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
]


class TrimResultMiddleware(Middleware):
    """Trim every tool result to what a caller acts on (see
    :func:`app.services.compact.trim`).

    Route-backed tools return the raw route JSON. Trimming here — after the
    route (and its RLS gates) have run — only removes fields from the payload;
    it never adds, changes or reorders anything. Which fields are free-form is
    read off each tool's response schema when the server is built (see
    ``_free_form_keys``), so a new one is left alone by construction.

    Removing keys is possible because the tools publish no output schema (see
    ``_drop_output_schema``); against one, a missing key fails the client's
    validation.
    """

    def __init__(self, free_form_keys: dict[str, frozenset[str]] | None = None):
        self._free_form_keys = free_form_keys or {}

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        if result.structured_content is None:
            # Not a JSON body (route-backed tools only answer JSON or plain
            # text); there's nothing to trim.
            return result

        free_form = self._free_form_keys.get(context.message.name, frozenset())
        # The text block is serialized from the trimmed structure, so the two
        # always say the same thing.
        return ToolResult(
            structured_content=trim(result.structured_content, free_form),
            meta=result.meta,
            is_error=result.is_error,
        )


async def _forward_authorization(request: httpx.Request) -> None:
    """Forward the caller's PAT to the in-process upstream route call.

    FastMCP strips ``authorization`` from forwarded headers by default; re-add it
    explicitly so the FastAPI route authenticates the caller and RLS scopes the
    request to *their* identity — never a shared or static token.
    """
    auth = get_http_headers(include={"authorization"}).get("authorization")
    if auth:
        request.headers["authorization"] = auth


# The list endpoints take ``conditions``/``sorting`` as a JSON *string* query
# param, which ``main._inject_query_schemas`` publishes as its decoded array
# type under ``content: application/json``. The MCP request builder reads that
# type but doesn't JSON-encode the value: handed an array argument it
# serializes each item with Python ``str()`` (single-quoted, e.g.
# ``{'field': 'due_date'}``), which the backend's ``json.loads`` rejects — every
# filtered/sorted list call 400s. Presenting the param to the model as a plain
# JSON string instead makes it send a string the builder forwards verbatim (valid
# JSON the backend parses). This touches only the MCP tool surface; the REST +
# Orval types keep the rich array schema.
#
# The string's description names the fields the list filters and sorts on, read
# from the field registry (``app.services.fields``) — the same declaration the
# list compiles its filters through — so a model is not left guessing at
# ``<column>`` and reading the 400. Which dataset a tool's ``conditions`` filter
# is not something its route says, so the tools that take one are named here;
# ``mcp_server_test`` fails for one that is not.
_FILTER_DATASETS: dict[str, str] = {
    "list_tasks": "tasks",
    "list_task_groups": "tasks",
    "list_my_tasks": "tasks",
    "list_calendar_entries": "tasks",
    "list_my_calendar_entries": "tasks",
}

# Fields the app's filter controls don't offer but a caller of these tools
# needs: the task lists have no ``initiative_id`` argument, so narrowing one to
# an initiative is this condition.
_EXTRA_FILTER_FIELDS: dict[str, tuple[str, ...]] = {"tasks": ("initiative_ids",)}

_CONDITIONS_SHAPE = (
    "JSON-encoded array of filter conditions, AND-ed together. Each item: "
    '{"field": ..., "op": ..., "value": ...}; "negate": true inverts it. An '
    'item with a "conditions" key is a group: '
    '{"logic": "and"|"or", "conditions": [...]}.'
)
_SORTING_SHAPE = (
    'JSON-encoded array of sort fields. Each item: {"field": ..., "dir": "asc"|"desc"}.'
)


def _field_line(name: str, ops: list[str], options: list[str]) -> str:
    line = f"{name} ({'/'.join(ops)}"
    if options:
        line += ": " + ", ".join(options)
    return line + ")"


def _conditions_description(dataset_name: str | None) -> str:
    """``conditions``, described for one dataset — or by shape alone."""
    if dataset_name is None:
        return _CONDITIONS_SHAPE
    lines = [
        _field_line(field["name"], field["ops"], field["options"])
        for field in fields_registry.describe(dataset_name)
    ]
    spec = fields_registry.dataset(dataset_name)
    for name in _EXTRA_FILTER_FIELDS.get(dataset_name, ()):
        lines.append(
            _field_line(name, sorted(op.value for op in spec.by_name[name].ops), [])
        )
    text = f"{_CONDITIONS_SHAPE} Fields: {'; '.join(lines)}."
    if "property_values" in spec.by_name:
        text += (
            " A property or metadata: "
            '{"field": "property_values", "op": "eq", "value": '
            '{"property_id": <id>, "value": <value>}}.'
        )
    return text + ' Example: [{"field": "project_id", "op": "eq", "value": 12}]'


def _sorting_description(dataset_name: str | None) -> str:
    if dataset_name is None:
        return _SORTING_SHAPE
    # The fields a client offers that also sort, and the ones declared only to
    # be sorted on (a date window, a board column, a tag), which the offered
    # set — a set of filters — never holds.
    names = [f["name"] for f in fields_registry.describe(dataset_name) if f["sortable"]]
    names += [
        spec.name
        for spec in fields_registry.dataset(dataset_name).fields
        if spec.sortable and not spec.filterable
    ]
    return (
        f"{_SORTING_SHAPE} Fields: {', '.join(names)}. "
        'Example: [{"field": "due_date", "dir": "asc"}]'
    )


def _stringify_json_query_params(route: object, component: object) -> None:
    """Retype array ``conditions``/``sorting`` tool params to JSON strings.

    A FastMCP ``mcp_component_fn`` (build-time): mutates each tool's input schema
    in place so the model passes a JSON string the request builder forwards as
    valid JSON, rather than an array it would mis-serialize. See the note on
    ``_FILTER_DATASETS``.
    """
    params = getattr(component, "parameters", None)
    if not isinstance(params, dict):
        return
    props = params.get("properties")
    if not isinstance(props, dict):
        return
    dataset_name = _FILTER_DATASETS.get(getattr(component, "name", ""))
    for name, describe in (
        ("conditions", _conditions_description),
        ("sorting", _sorting_description),
    ):
        schema = props.get(name)
        if isinstance(schema, dict) and schema.get("type") == "array":
            props[name] = {"type": "string", "description": describe(dataset_name)}


# A tool's input schema is what a model reads to call it, so it carries only
# what a caller supplies. Three things the OpenAPI document holds for other
# readers are taken out:
#
#   * cookie parameters. The browser's session cookie is declared on every
#     route's auth dependency, which made it an argument on every tool; an MCP
#     caller authenticates with its key in the ``Authorization`` header.
#   * ``title`` annotations. Pydantic titles every field after its own name
#     ("Task Id" on ``task_id``), which tells a model nothing the name doesn't.
#   * ``$defs`` nothing references any more — the filter and sort models that
#     ``_stringify_json_query_params`` replaced with a string.
_SUBSCHEMA_KEYS = ("items", "additionalProperties", "not")
_SUBSCHEMA_LIST_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")


def _subschemas(schema: Any) -> Iterator[dict[str, Any]]:
    """``schema`` and every schema nested in it.

    Walks schema positions only, so a *property* called ``title`` (a task's) is
    never mistaken for an annotation: ``properties`` maps names to schemas, and
    only the schemas are visited.
    """
    if not isinstance(schema, dict):
        return
    yield schema
    for sub in (schema.get("properties") or {}).values():
        yield from _subschemas(sub)
    for sub in (schema.get("$defs") or {}).values():
        yield from _subschemas(sub)
    for key in _SUBSCHEMA_KEYS:
        yield from _subschemas(schema.get(key))
    for key in _SUBSCHEMA_LIST_KEYS:
        for sub in schema.get(key) or ():
            yield from _subschemas(sub)


def _strip_titles(schema: Any) -> None:
    """Remove ``title`` annotations from ``schema`` and its subschemas, in place."""
    for sub in _subschemas(schema):
        if isinstance(sub.get("title"), str):
            del sub["title"]


_DEF_REF = re.compile(r'"#/\$defs/([^"]+)"')


def _prune_unused_defs(schema: dict[str, Any]) -> None:
    """Drop the ``$defs`` entries nothing outside them reaches, in place."""
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return
    body = {k: v for k, v in schema.items() if k != "$defs"}
    reached: set[str] = set()
    pending = set(_DEF_REF.findall(json.dumps(body)))
    while pending:
        name = pending.pop()
        if name in reached or name not in defs:
            continue
        reached.add(name)
        pending |= set(_DEF_REF.findall(json.dumps(defs[name])))
    kept = {k: v for k, v in defs.items() if k in reached}
    if kept:
        schema["$defs"] = kept
    else:
        del schema["$defs"]


def _clean_parameters(route: HTTPRoute, component: object) -> None:
    """Take out of a tool's input schema what a caller never supplies."""
    params = getattr(component, "parameters", None)
    if not isinstance(params, dict):
        return
    cookies = {p.name for p in route.parameters if p.location == "cookie"}
    props = params.get("properties")
    if isinstance(props, dict):
        for name in cookies:
            props.pop(name, None)
    if isinstance(params.get("required"), list):
        params["required"] = [n for n in params["required"] if n not in cookies]
    _strip_titles(params)
    _prune_unused_defs(params)


def _free_form_keys(schema: dict[str, Any] | None) -> frozenset[str]:
    """The property names whose value ``schema`` leaves free-form.

    A free-form value is one the schema gives no shape to — no type, or an
    object with no properties: a document's content, a dashboard's config, a
    property's value. ``trim`` passes these through verbatim.
    """
    if not schema:
        return frozenset()
    defs = schema.get("$defs") or {}
    found: set[str] = set()
    visited: set[str] = set()

    def resolve(node: Any) -> Any:
        while isinstance(node, dict) and "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            node = defs.get(name)
        return node

    def is_free_form(node: Any) -> bool:
        node = resolve(node)
        if not isinstance(node, dict):
            return False
        if "anyOf" in node:
            return any(
                is_free_form(n) for n in node["anyOf"] if n.get("type") != "null"
            )
        shaped = ("properties", "items", "enum", "const", "allOf", "oneOf", "$ref")
        if "type" not in node:
            return not any(k in node for k in shaped)
        return node["type"] == "object" and "properties" not in node

    def walk(node: Any) -> None:
        if isinstance(node, dict) and "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in visited:
                return
            visited.add(name)
        node = resolve(node)
        if not isinstance(node, dict):
            return
        for key, sub in (node.get("properties") or {}).items():
            if is_free_form(sub):
                found.add(key)
            walk(sub)
        for key in _SUBSCHEMA_KEYS:
            walk(node.get(key))
        for key in _SUBSCHEMA_LIST_KEYS:
            for sub in node.get(key) or ():
                walk(sub)

    walk(schema)
    return frozenset(found)


def _drop_output_schema(component: object) -> None:
    """Publish the tool without an output schema.

    A route's response schema is most of what ``tools/list`` sends — four
    fifths of it, in one measurement — and is there for a client to validate
    the structured result against, not for a model to read. Without it the
    result is still structured, and ``trim`` may leave out keys the schema
    would have required.
    """
    if getattr(component, "output_schema", None) is not None:
        component.output_schema = None


# A description is read by a model, so it is written for one. The tool's own
# comes from ``app.mcp_descriptions``. Inside its input schema, a nested model
# carries its class docstring, which is written for whoever maintains the class
# — the grant row's alone ran to 800 characters, in nine tools — so it is cut to
# its first paragraph, which is the summary. An enum's is kept whole: it is
# where each value is explained. Sphinx markup (``x``, :func:`x`) is reduced to
# plain backticks everywhere.
_SPHINX_ROLE = re.compile(r":(?:func|class|data|meth|attr|mod):`([^`]+)`")
_DOUBLE_BACKTICKS = re.compile(r"``([^`]+)``")


def _plain(text: str) -> str:
    return _DOUBLE_BACKTICKS.sub(r"`\1`", _SPHINX_ROLE.sub(r"`\1`", text))


def _model_summaries(openapi: dict[str, Any]) -> dict[str, str]:
    """Each object model's docstring, mapped to its first paragraph.

    Only the docstrings with more than one paragraph are listed; a field's own
    description never matches one, so only the class docstrings are cut.
    """
    summaries: dict[str, str] = {}
    for schema in openapi.get("components", {}).get("schemas", {}).values():
        doc = schema.get("description")
        if not isinstance(doc, str) or "enum" in schema:
            continue
        first, _, rest = doc.partition("\n\n")
        if rest:
            summaries[doc] = " ".join(first.split())
    return summaries


def _describe_tool(component: object, model_summaries: dict[str, str]) -> None:
    """Publish the tool's MCP description, and plain ones inside its schema."""
    name = getattr(component, "name", None)
    description = describe_tool(name) if name else None
    if description is None:
        description = _plain(getattr(component, "description", None) or "")
    component.description = description
    for sub in _subschemas(getattr(component, "parameters", None)):
        text = sub.get("description")
        if isinstance(text, str):
            sub["description"] = _plain(model_summaries.get(text, text))


# Arguments a caller is given when it leaves them out, where the route's own
# default suits the app rather than a model.
#
# A page of results is what a call returns, so it is sized for a model's
# context rather than for a screen: twenty rows unless asked, and never more
# than fifty — a hundred trimmed tasks is past the 25k tokens Claude Code
# accepts from one call. A route whose default is "everything" (a
# ``page_size`` of 0) pages like the rest.
_MCP_PAGE_SIZE = 20
_MCP_MAX_PAGE_SIZE = 50

# "My tasks", asked by an assistant, means the work still to do — as it does on
# the app's own Home — not every task the caller was ever on; a caller after
# finished work says so.
_OPEN_TASKS = json.dumps(
    [
        {
            "field": "status_category",
            "op": "in_",
            "value": [
                c.value for c in TaskStatusCategory if c is not TaskStatusCategory.done
            ],
        }
    ]
)
_ARGUMENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "list_my_tasks": {"conditions": _OPEN_TASKS},
}


def _page_size_bounds(component: object) -> tuple[int, int] | None:
    """Publish the MCP page size on a tool that pages, and return
    ``(default, maximum)``; ``None`` for a tool that doesn't page."""
    params = getattr(component, "parameters", None)
    props = params.get("properties") if isinstance(params, dict) else None
    schema = props.get("page_size") if isinstance(props, dict) else None
    if not isinstance(schema, dict):
        return None
    route_default = schema.get("default") or 0
    default = min(int(route_default), _MCP_PAGE_SIZE) or _MCP_PAGE_SIZE
    maximum = min(int(schema.get("maximum", _MCP_MAX_PAGE_SIZE)), _MCP_MAX_PAGE_SIZE)
    schema.update(default=default, minimum=1, maximum=maximum)
    return default, maximum


def _publish_defaults(component: object, defaults: dict[str, Any]) -> None:
    """Say on each defaulted argument what it is left out as."""
    params = getattr(component, "parameters", None)
    props = params.get("properties") if isinstance(params, dict) else None
    if not isinstance(props, dict):
        return
    for name, value in defaults.items():
        schema = props.get(name)
        if isinstance(schema, dict):
            schema["description"] = (
                f"{schema.get('description', '')} Left out: {value}"
            ).strip()


class ArgumentDefaultsMiddleware(Middleware):
    """Fill in the MCP defaults a call left out, and hold a page size to its
    bounds, before the call reaches the route."""

    def __init__(
        self,
        defaults: dict[str, dict[str, Any]],
        page_sizes: dict[str, tuple[int, int]],
    ):
        self._defaults = defaults
        self._page_sizes = page_sizes

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        arguments = dict(context.message.arguments or {})
        for key, value in self._defaults.get(name, {}).items():
            if arguments.get(key) is None:
                arguments[key] = value
        if name in self._page_sizes:
            default, maximum = self._page_sizes[name]
            size = arguments.get("page_size")
            if not isinstance(size, int) or size < 1:
                arguments["page_size"] = default
            elif size > maximum:
                arguments["page_size"] = maximum
        message = context.message.model_copy(update={"arguments": arguments})
        return await call_next(context.copy(message=message))


def build_mcp_server(app: "FastAPI") -> FastMCP:
    """Build the route-backed MCP server from the FastAPI ``app``.

    The app must already have its routers included so the RouteMap can see them.
    """
    free_form_keys: dict[str, frozenset[str]] = {}
    page_sizes: dict[str, tuple[int, int]] = {}
    model_summaries = _model_summaries(app.openapi())

    def shape_tool(route: HTTPRoute, component: object) -> None:
        _stringify_json_query_params(route, component)
        _clean_parameters(route, component)
        _describe_tool(component, model_summaries)
        name = getattr(component, "name", None)
        if name is not None:
            free_form_keys[name] = _free_form_keys(
                getattr(component, "output_schema", None)
            )
            bounds = _page_size_bounds(component)
            if bounds is not None:
                page_sizes[name] = bounds
            _publish_defaults(component, _ARGUMENT_DEFAULTS.get(name, {}))
        _drop_output_schema(component)

    server = FastMCP.from_fastapi(
        app=app,
        name=PROJECT_NAME,
        route_maps=_ROUTE_MAPS,
        mcp_component_fn=shape_tool,
        httpx_client_kwargs={"event_hooks": {"request": [_forward_authorization]}},
    )
    server.add_middleware(ArgumentDefaultsMiddleware(_ARGUMENT_DEFAULTS, page_sizes))
    server.add_middleware(TrimResultMiddleware(free_form_keys))
    return server
