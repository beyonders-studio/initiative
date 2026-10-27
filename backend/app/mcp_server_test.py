"""The in-app MCP server exposes only a curated surface.

Builds the route-backed server from the real app (no DB/network needed) and
asserts the RouteMap curation holds: tools cover initiatives and the tools they
hold (+ the shared comment surface, + the edges between them), and the *write*
surface is exactly the allow-list — create and edit each of those, draw one
edge, and nothing destructive, bulk, AI-generating, sharing, or property/tag.
"""

import json
from types import SimpleNamespace

import httpx
from fastmcp import Client
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams, TextContent

from app.core.tools import Tool
from app.main import app
from app.mcp_descriptions import TOOL_DESCRIPTIONS, described_names
from app.mcp_server import (
    _FILTER_DATASETS,
    _MCP_MAX_PAGE_SIZE,
    _MCP_PAGE_SIZE,
    _OPEN_TASKS,
    ArgumentDefaultsMiddleware,
    TrimResultMiddleware,
    _free_form_keys,
    build_mcp_server,
)

# A tool is a "write" if its operationId begins with one of these verbs.
_WRITE_PREFIXES = (
    "create_",
    "update_",
    "move_",
    "delete_",
    "archive_",
    "duplicate_",
    "reorder_",
    "set_",
    "batch_",
    "generate_",
    "put_",
    "replace_",
    "patch_",
    "post_",
    "remove_",
    "add_",
    "step_",
    "reset_",
    "upload_",
    "import_",
    "copy_",
    "vote_",
    "toggle_",
    "start_",
    "stop_",
    "sort_",
    "advance_",
    "hold_",
    "release_",
    "upgrade_",
)

# The only mutations the MCP server is allowed to expose (handler names).
_SAFE_WRITES = {
    # Every tool an initiative holds: author it and edit it.
    "create_project",
    "update_project",
    "create_file",
    "update_file",
    "create_queue",
    "update_queue",
    "create_counter_group",
    "update_counter_group",
    "create_calendar",
    "update_calendar",
    "create_dashboard",
    "update_dashboard",
    "create_post",
    "update_post",
    # A library is authored and renamed here, and filled elsewhere: putting a
    # picture in one is a multipart upload, which no RouteMap matches, so the
    # write surface stops at the wall itself.
    "create_library",
    "update_library",
    "create_wiki",
    "update_wiki",
    # And what those tools hold: a project's tasks, a queue's items, a counter
    # group's counters, a calendar's events, a wiki's pages, and the comments on
    # any of them.
    "create_task",
    "update_task",
    "move_task",
    # One checklist tick. The task update rewrites the list's lines but never
    # its done flags, so this is the only way to mark a piece of a task done.
    "toggle_checklist_item",
    "add_queue_item",
    "update_queue_item",
    "add_counter",
    "update_counter",
    "create_calendar_event",
    "update_calendar_event",
    # A page is authored and edited, not dragged: where it sits in the tree is
    # `move`, which takes a parent and a position, so it sits with the reorders.
    "create_wiki_page",
    "update_wiki_page",
    "create_comment",
    "update_comment",
    # A counter's count, which its update schema doesn't carry.
    "set_counter_count",
    "step_counter",
    # One edge between two of them. No ``update_`` pair: an edge has no fields
    # to edit, only ends and a type, which are what it is.
    "create_relationship",
}


async def test_mcp_tools_are_curated():
    tools = await build_mcp_server(app).list_tools()
    names = [t.name.lower() for t in tools]

    assert names, "expected the curated tools to be present"

    # Every tool is for an initiative, one of the tools an initiative holds, or
    # the comment surface they share. Everything else (admin, auth, settings,
    # users, uploads, grants, …) carries none of these words, so this also
    # proves none of them are exposed.
    allowed = (
        "initiative",
        "comment",
        # The things a tool holds, which the enum names only their parent of:
        # a task belongs to a project, a counter to a counter group.
        "task",
        # A task's checklist, ticked one item at a time.
        "checklist",
        # How full each of a project's status columns is, where a move into a
        # full one is refused.
        "column_limits",
        "counter",
        "backlink",
        # The edges between them, which belong to no one tool.
        "relationship",
        "widget",
        # And the way in when a caller knows a name rather than an id.
        "search",
        # How many of each, for every tool at once.
        "tool_counts",
        # The caller's communities: where a session learns its community_id.
        "list_communities",
        *(tool.value for tool in Tool),
        *(tool.plural for tool in Tool),
    )
    off_list = [n for n in names if not any(a in n for a in allowed)]
    assert not off_list, f"tools outside the allow-list: {off_list}"

    # And every tool an initiative holds is readable. Derived from the enum
    # rather than listed, so a seventh kind arrives here as a failure rather
    # than as a surface nobody remembered to open.
    for tool in Tool:
        stem = tool.value.replace("_", "")
        assert any(stem in n.replace("_", "") for n in names), (
            f"no MCP tool reads {tool.value}"
        )
    # And what those tools hold reads back by its own id.
    assert {"read_queue_item", "read_counter", "read_wiki_page"} <= set(names)

    # Join requests sit on the initiatives router and would otherwise ride in on
    # its tag, but they name who asked to be let in and quote their note — a
    # manager's queue, not a working surface. Carved out explicitly.
    assert not [n for n in names if "join_request" in n]


async def test_the_tool_reads_stop_short_of_these():
    """What riding in on a tag would have brought, and why each stays out.

    Opening a tool's tag exposes every GET it carries, and a few of those are
    not the working surface the rest are. Named here so removing one is a
    decision somebody makes rather than a line that quietly stops matching.
    """
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]

    # Bytes rather than an answer: a file, one of its versions, a calendar
    # file. None is something a tool result carries usefully.
    assert not [n for n in names if "download" in n or "export" in n]
    # People rather than work: who voted which way, who has read a notice.
    assert not [n for n in names if "voter" in n or n.endswith("_reads")]
    # The dashboard editor's own vocabulary, not anything a dashboard shows.
    assert not [n for n in names if "widget_catalog" in n or "installed_listing" in n]

    # The one that has to be present, because it is the whole point of reading
    # a dashboard: what its tiles currently say.
    assert any("load_dashboard_data" in n for n in names)


async def test_comment_reads_are_exposed():
    """The two reads that pair with the comment write, and only those.

    ``comments`` is deliberately not a READ_TAG: the router's other two GETs
    (the guild-wide ``recent`` activity feed and the @-mention picker's search)
    are matched by no RouteMap and fall through the default-deny catch-all.
    """
    names = {t.name.lower() for t in await build_mcp_server(app).list_tools()}

    assert "list_comments" in names
    assert "read_comment" in names
    assert "recent_comments" not in names
    assert "search_mentionables" not in names


async def test_search_is_exposed_without_the_picker_routes():
    """The general search, and only it, out of the search router's three GETs.

    ``search`` is deliberately not a READ_TAG: ``recent`` and ``suggest`` both
    describe a text field's behaviour — what to offer before anything is typed,
    and titles to jump to while it is — rather than answering a question, so
    they fall through the default-deny catch-all.
    """
    names = {t.name.lower() for t in await build_mcp_server(app).list_tools()}

    assert "search_community" in names
    assert "recent_community" not in names
    assert "suggest_community" not in names


async def test_relationship_tools_are_read_and_draw_one():
    """List one thing's edges and draw one, and nothing that unwires them.

    ``relationships`` is deliberately neither a READ_TAG nor a writable segment:
    the router's four routes divide two and two, so each side is named by path
    shape. Replacing a thing's links wholesale is bulk and removes what it
    doesn't mention; deleting one is a delete. Both fall through the
    default-deny catch-all.
    """
    names = {t.name.lower() for t in await build_mcp_server(app).list_tools()}

    assert "list_relationships" in names
    assert "create_relationship" in names
    assert "replace_relationship_slice" not in names
    assert "remove_relationship" not in names


async def test_mcp_write_tools_are_the_curated_safe_set():
    # Lowercase consistently so a differently-cased operationId can't dodge the
    # write-prefix check.
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]

    writes = {n for n in names if n.startswith(_WRITE_PREFIXES)}
    # Exactly the allow-list — no delete/archive/reset/reorder/duplicate/batch,
    # no AI generation, no grants, no property or tag mutation.
    assert writes == _SAFE_WRITES, f"write surface changed: {sorted(writes)}"

    # Every tool is writable, derived from the enum rather than read back off
    # the set above, so an eighth tool arrives here as a failure rather than as
    # a tool nobody remembered to make writable.
    for tool in Tool:
        assert f"create_{tool.value}" in writes, f"no MCP tool creates {tool.value}"
        assert f"update_{tool.value}" in writes, f"no MCP tool edits {tool.value}"


async def test_the_tool_writes_stop_short_of_these():
    """What create-and-edit deliberately doesn't reach.

    Named here so removing one is a decision somebody makes rather than a line
    that quietly stops matching. The equality assertion above covers all of it;
    these spell out the categories that were weighed.
    """
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]
    writes = {n for n in names if n.startswith(_WRITE_PREFIXES)}

    # Nothing that removes or empties: delete, trash, archive, reset a counter
    # or a queue, discard the done column.
    assert not [w for w in writes if w.startswith(("delete_", "archive_", "reset_"))]
    # Nothing that acts on a whole collection at once.
    assert not [
        w for w in writes if w.startswith(("reorder_", "batch_", "sort_", "duplicate_"))
    ]
    # Sharing is a decision about people, made in the app: no grants, no
    # publishing a dashboard figure, no pinning a notice guild-wide.
    assert not [w for w in writes if w.endswith("_grants")]
    assert "set_published_view" not in writes
    assert "set_post_pin" not in writes
    # Speaking for somebody: voting in a poll, marking a notice read, RSVPing.
    assert not [w for w in writes if w.startswith("vote_") or w.endswith("_rsvp")]
    assert "mark_posts_read" not in writes
    assert "set_attendees" not in writes
    # Whole-set replacements and generated prose stay out, as they were.
    assert not [w for w in writes if w.endswith(("_tags", "_properties"))]
    assert not [w for w in writes if w.startswith("generate_")]
    # A project's status columns are its shape, set up in the app; a task is
    # placed into one by reading them.
    assert "create_task_status" not in writes
    assert "update_task_status" not in writes
    # So are its task types; a task is given one by reading them.
    assert "list_task_types" in names
    assert not [w for w in writes if "task_type" in w]


def test_free_form_keys_are_read_off_the_response_schema():
    schema = {
        "type": "object",
        "properties": {
            "result": {"type": "array", "items": {"$ref": "#/$defs/Read"}},
        },
        "$defs": {
            "Read": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "content": {"anyOf": [{"type": "object"}, {"type": "null"}]},
                    "value": {},
                    "owner": {"$ref": "#/$defs/Owner"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
            "Owner": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    }

    assert _free_form_keys(schema) == {"content", "value"}
    assert _free_form_keys(None) == frozenset()


async def test_the_server_records_each_tool_s_free_form_fields():
    server = build_mcp_server(app)
    (trim,) = [m for m in server.middleware if isinstance(m, TrimResultMiddleware)]

    # A document's body and a dashboard's config are the thing's own, and
    # reach the caller untouched.
    assert "content" in trim._free_form_keys["read_file"]
    assert "config" in trim._free_form_keys["read_dashboard"]
    # A task has none, so all of it is trimmed.
    assert not trim._free_form_keys["read_task"] - {"value"}


async def test_trim_middleware_trims_the_result_and_its_text():
    payload = {"guild": {"avatar_base64": "AAAA", "name": "g", "icon": None}}
    result = ToolResult(structured_content=payload)

    async def call_next(_context):
        return result

    context = SimpleNamespace(message=SimpleNamespace(name="read_guild"))
    out = await TrimResultMiddleware().on_call_tool(context, call_next)

    assert out.structured_content == {"guild": {"name": "g"}}
    # The text a client without structured content reads says the same, and
    # is serialized compactly.
    assert out.content[0].text == '{"guild":{"name":"g"}}'


async def test_trim_middleware_passes_through_non_json_text():
    result = ToolResult(content=[TextContent(type="text", text="plain not json")])

    async def call_next(_context):
        return result

    context = SimpleNamespace(message=SimpleNamespace(name="read_file"))
    out = await TrimResultMiddleware().on_call_tool(context, call_next)

    assert out.content[0].text == "plain not json"


async def test_list_tools_expose_conditions_and_sorting_as_json_strings():
    # main._inject_query_schemas retypes these to arrays for the REST/Orval
    # surface; the MCP tool must present them as JSON strings instead, or the
    # request builder serializes an array via Python str() (single-quoted) and
    # the backend's json.loads rejects it. Assert every tool that has them uses
    # a string schema.
    tools = await build_mcp_server(app).list_tools()
    seen = 0
    for tool in tools:
        props = (tool.parameters or {}).get("properties", {})
        for name in ("conditions", "sorting"):
            schema = props.get(name)
            if schema is not None:
                seen += 1
                assert schema.get("type") == "string", (
                    f"{tool.name}.{name} should be a JSON string, got {schema}"
                )
    assert seen, "expected at least one tool exposing conditions/sorting"


async def test_tools_publish_no_output_schema():
    """The response schema is for validating a result, not for a model to read.

    It was four fifths of ``tools/list``, and against it a trimmed result
    would fail validation for the keys it leaves out.
    """
    tools = await build_mcp_server(app).list_tools()

    assert [t.name for t in tools if t.output_schema is not None] == []


def _schema_titles(schema, path="$"):
    """Every ``title`` annotation in ``schema``, by where it sits."""
    found = []
    if isinstance(schema, dict):
        if isinstance(schema.get("title"), str):
            found.append(path)
        for name, sub in (schema.get("properties") or {}).items():
            found += _schema_titles(sub, f"{path}.{name}")
        for name, sub in (schema.get("$defs") or {}).items():
            found += _schema_titles(sub, f"{path}.$defs.{name}")
        for key in ("items", "additionalProperties", "not"):
            found += _schema_titles(schema.get(key), f"{path}.{key}")
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            for i, sub in enumerate(schema.get(key) or ()):
                found += _schema_titles(sub, f"{path}.{key}[{i}]")
    return found


async def test_tool_inputs_carry_only_what_a_caller_supplies():
    tools = await build_mcp_server(app).list_tools()

    for tool in tools:
        params = tool.parameters or {}
        props = params.get("properties", {})
        # The browser's session cookie: a caller authenticates with its key.
        assert "session_token" not in props, tool.name
        assert "session_token" not in params.get("required", []), tool.name
        # Titles that only restate a field's name.
        assert _schema_titles(params) == [], tool.name
        # Definitions nothing points at any more.
        body = json.dumps({k: v for k, v in params.items() if k != "$defs"})
        defs = params.get("$defs", {})
        for name in defs:
            reached = f'"#/$defs/{name}"' in body or any(
                f'"#/$defs/{name}"' in json.dumps(d) for d in defs.values()
            )
            assert reached, f"{tool.name} keeps unused $defs/{name}"

    # A *property* called ``title`` is not an annotation, and stays.
    (create_task,) = [t for t in tools if t.name == "create_task"]
    assert "title" in create_task.parameters["properties"]
    assert "title" in create_task.parameters["required"]


async def test_the_community_list_is_exposed_and_nothing_else_of_its_router():
    """Where a session learns the ``community_id`` every other tool takes. The
    router's other routes are one community's administration."""
    tools = await build_mcp_server(app).list_tools()
    community_routes = [
        t.name for t in tools if "/communities" in getattr(t, "_route").path
    ]

    assert community_routes == ["list_communities"]


async def test_every_tool_is_described_for_the_model_calling_it():
    """A tool says what it answers, not only its name — which was all a tool
    search had to go on for a third of them."""
    names = {t.name for t in await build_mcp_server(app).list_tools()}

    assert names - described_names() == set(), "tools with no MCP description"
    # And nothing here describes a tool that is not exposed.
    assert set(TOOL_DESCRIPTIONS) - names == set(), "descriptions for no tool"


async def test_the_templated_list_descriptions_name_real_arguments():
    tools = {t.name: t for t in await build_mcp_server(app).list_tools()}
    for tool in Tool:
        listed = tools[f"list_{tool.plural}"]
        props = listed.parameters["properties"]
        for name in ("initiative_id", "search", "tag_ids", "property_filters"):
            assert name in props, f"{listed.name} has no {name}"


async def test_descriptions_carry_no_sphinx_markup_or_class_essays():
    tools = await build_mcp_server(app).list_tools()

    for tool in tools:
        texts = [tool.description or ""] + [
            sub["description"]
            for sub in _subschemas_of(tool.parameters)
            if isinstance(sub.get("description"), str)
        ]
        for text in texts:
            assert "``" not in text, f"{tool.name}: {text[:80]}"
            assert ":func:" not in text and ":class:" not in text, tool.name

    # A nested model's docstring is cut to its summary: the grant row's ran on
    # for paragraphs about the sharing panel.
    (create_project,) = [t for t in tools if t.name == "create_project"]
    grant = create_project.parameters["properties"]["grants"]["items"]
    assert grant["description"].startswith("One `resource_grants` row")
    assert "\n\n" not in grant["description"]


def _subschemas_of(schema):
    if isinstance(schema, dict):
        yield schema
        for value in schema.values():
            if isinstance(value, dict):
                yield from _subschemas_of(value)
            elif isinstance(value, list):
                for item in value:
                    yield from _subschemas_of(item)


async def test_every_filtered_list_names_its_fields():
    """``conditions`` names the fields its list filters on, from the field
    registry, so a model doesn't guess at columns."""
    tools = await build_mcp_server(app).list_tools()
    filtered = {
        t.name: t.parameters["properties"]["conditions"]["description"]
        for t in tools
        if "conditions" in t.parameters.get("properties", {})
    }

    # A new list that takes conditions is told which dataset they filter.
    assert set(filtered) == set(_FILTER_DATASETS)
    for name, text in filtered.items():
        for field in ("project_id", "status_category", "assignee_ids", "due_date"):
            assert field in text, f"{name} conditions do not name {field}"
        # The task lists have no initiative argument, so it is a condition.
        assert "initiative_ids" in text, name


async def test_every_sorted_list_names_its_sorts():
    tools = await build_mcp_server(app).list_tools()
    sorted_lists = {
        t.name: t.parameters["properties"]["sorting"]["description"]
        for t in tools
        if "sorting" in t.parameters.get("properties", {})
    }

    assert sorted_lists
    for name, text in sorted_lists.items():
        # What the board and table sort by, including the fields declared only
        # to be sorted on.
        for field in ("due_date", "priority", "date_group", "status_position"):
            assert field in text, f"{name} sorting does not name {field}"
        # And not the lifecycle columns no client offers.
        assert "deleted_at" not in text and "hold_id" not in text, name


async def test_a_page_is_sized_for_a_model():
    tools = await build_mcp_server(app).list_tools()
    paged = [t for t in tools if "page_size" in t.parameters.get("properties", {})]

    assert paged
    for tool in paged:
        schema = tool.parameters["properties"]["page_size"]
        assert 1 <= schema["default"] <= _MCP_PAGE_SIZE, tool.name
        assert schema["maximum"] <= _MCP_MAX_PAGE_SIZE, tool.name
        assert schema["minimum"] == 1, tool.name


def _call(name: str, arguments: dict | None):
    return SimpleNamespace(
        message=CallToolRequestParams(name=name, arguments=arguments),
        copy=lambda message: SimpleNamespace(message=message),
    )


async def _arguments_after(middleware, name: str, arguments: dict | None) -> dict:
    seen = {}

    async def call_next(context):
        seen.update(context.message.arguments)
        return ToolResult(structured_content={})

    await middleware.on_call_tool(_call(name, arguments), call_next)
    return seen


async def test_my_tasks_left_unfiltered_are_the_open_ones():
    middleware = ArgumentDefaultsMiddleware(
        {"list_my_tasks": {"conditions": _OPEN_TASKS}}, {}
    )

    unfiltered = await _arguments_after(middleware, "list_my_tasks", {})
    open_categories = json.loads(unfiltered["conditions"])[0]["value"]
    assert set(open_categories) == {"backlog", "todo", "in_progress"}

    # Asked for, every task comes back, and a filter of the caller's own wins.
    everything = await _arguments_after(
        middleware, "list_my_tasks", {"conditions": "[]"}
    )
    assert everything["conditions"] == "[]"
    # Other tools are left alone.
    assert await _arguments_after(middleware, "list_tasks", None) == {}


async def test_a_page_size_is_held_to_its_bounds():
    middleware = ArgumentDefaultsMiddleware({}, {"list_files": (20, 50)})

    assert (await _arguments_after(middleware, "list_files", {}))["page_size"] == 20
    # Zero means "everything" to the route; here it means the default page.
    assert (await _arguments_after(middleware, "list_files", {"page_size": 0}))[
        "page_size"
    ] == 20
    assert (await _arguments_after(middleware, "list_files", {"page_size": 500}))[
        "page_size"
    ] == 50
    assert (await _arguments_after(middleware, "list_files", {"page_size": 7}))[
        "page_size"
    ] == 7


async def test_the_server_sends_the_defaults_to_the_route():
    """End to end through the built server: the request a call makes carries
    the MCP defaults it left out."""
    server = build_mcp_server(app)
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [], "has_next": False})

    for tool in await server.list_tools():
        if tool.name == "list_my_tasks":
            tool._client = httpx.AsyncClient(
                transport=httpx.MockTransport(answer), base_url="http://test"
            )

    async with Client(server) as client:
        await client.call_tool_mcp("list_my_tasks", {})

    (request,) = requests
    assert json.loads(request.url.params["conditions"]) == json.loads(_OPEN_TASKS)
    assert request.url.params["page_size"] == str(_MCP_PAGE_SIZE)
