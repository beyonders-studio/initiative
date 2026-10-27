"""What each MCP tool says it does, written for the model that calls it.

A route's own description is its handler's docstring, written for whoever
maintains the handler: why a path is declared where it is, which surface of the
app calls it, how a gate is put together. A model choosing a tool needs
something else — what the tool answers, which arguments matter, and what to
call next — and a tool with no docstring was described by its name alone
("List Tasks"), which is also all a tool search had to go on.

So the MCP surface describes its tools here, and nothing here reaches the REST
API or the generated client.

  * The four tools every kind of tool has — list, read, create, edit — are
    described from the ``Tool`` enum, so a new tool arrives described.
  * Every other tool, and any of those four that has more to say, is written
    out in :data:`TOOL_DESCRIPTIONS`, which wins over the template.

``mcp_server_test`` fails for an exposed tool this module cannot describe, and
for an entry here that names no tool.
"""

from __future__ import annotations

from app.core.tools import Tool

#: What a tool is called in prose, where its enum value isn't the word a
#: person uses: a post is a notice on its initiative's board.
_NOUNS: dict[Tool, tuple[str, str]] = {
    Tool.post: ("notice", "notices"),
}


def _nouns(tool: Tool) -> tuple[str, str]:
    return _NOUNS.get(
        tool, (tool.value.replace("_", " "), tool.plural.replace("_", " "))
    )


def _templated(tool: Tool) -> dict[str, str]:
    one, many = _nouns(tool)
    return {
        f"list_{tool.plural}": (
            f"List the {many} in a community that the caller can see. Narrow "
            "with `initiative_id`, `search`, `tag_ids` or `property_filters`; "
            "follow `has_next` for more pages."
        ),
        f"read_{tool.value}": f"Read one {one} by id.",
        f"create_{tool.value}": (
            f"Create a {one} in an initiative (`initiative_id`). The caller owns "
            "it; `grants` says who else it is shared with."
        ),
        f"update_{tool.value}": f"Change a {one}. Only the fields sent change.",
    }


#: Written out: everything the template does not cover, and the template's
#: tools where a field needs explaining.
TOOL_DESCRIPTIONS: dict[str, str] = {
    # --- Where to start -----------------------------------------------------
    "list_communities": (
        "The communities the caller belongs to, with each one's `id` and the "
        "caller's role there. Every other tool except `list_my_tasks` and "
        "`list_my_calendar_entries` takes one of these ids as `community_id`, "
        "so this is the first call when the community isn't known."
    ),
    "list_initiatives": (
        "The initiatives the caller belongs to in a community. An initiative "
        "holds the projects, files, queues and other tools; most lists narrow "
        "by its `id` as `initiative_id`. A community admin can pass "
        "`scope=community` for every initiative in the community."
    ),
    "list_initiative_directory": (
        "The initiatives in a community that any member may discover and join, "
        "with what each publishes about itself. None of their content."
    ),
    "get_initiative": "Read one initiative by id: its settings and which tools it has on.",
    "list_initiative_roles": "An initiative's roles and what each may do.",
    "get_initiative_members": (
        "One page of an initiative's members, each with their role. Narrow with "
        "`search`, or to managers with `is_manager`."
    ),
    "search_initiative_members": (
        "Find people in an initiative by name, for an id to assign or mention. "
        "Pass `user_id` (repeatable) to look up known ids instead."
    ),
    "search_community": (
        "Find anything in a community by name or text: tasks, files, wiki pages, "
        "events, comments, tags and the rest, ranked. The quickest way to an id "
        "when you know what a thing is called. Narrow with `types` or "
        "`initiative_id`."
    ),
    "get_tool_counts": (
        "How many of one kind of tool an initiative (or the community) holds in "
        "each view — active, archived and so on — and, with `include_tags`, "
        "how many per tag."
    ),
    "get_tool_counts_by_initiative": (
        "How many live items of every kind of tool each initiative holds, in one call."
    ),
    # --- Projects and tasks -------------------------------------------------
    "list_projects": (
        "List the projects in a community that the caller can see. Narrow with "
        "`initiative_id`, `search`, `tag_ids` or `property_filters`; `slim` "
        "returns only ids and names, and `writable` only the projects the "
        "caller may add tasks to. Follow `has_next` for more pages."
    ),
    "create_project": (
        "Create a project. `initiative_id` places it in an initiative; "
        "`template_id` starts it as a copy of a template project. "
        "The caller owns it; `grants` says who else it is shared with."
    ),
    "list_task_statuses": (
        "A project's status columns, in board order, with each one's category "
        "(backlog, todo, in_progress, done). Their ids are what `create_task` "
        "and `update_task` take as `task_status_id`."
    ),
    "list_task_type_gallery": (
        "Ready-made task types a project can add (Event, Chore, Bill, …), "
        "grouped by what they are for, in the caller's language, with the "
        "fields and starting values each brings."
    ),
    "list_task_types": (
        "A project's task types (Task, Bug, Idea, Milestone, or the project's "
        "own), in order, with which is the default. Their ids are what "
        "`create_task` and `update_task` take as `task_type_id`."
    ),
    "list_initiative_task_statuses": (
        "The status columns used across an initiative's projects, one per name "
        "and category, with how many projects use each."
    ),
    "list_column_limits": (
        "The board columns with a limit in each named project (`project_id`, "
        "repeatable), and how many open tasks each holds. A full column refuses "
        "new tasks and moves into it."
    ),
    "list_tasks": (
        "List tasks in a community, filtered with `conditions` — for one "
        "project, `project_id`; for one initiative, `initiative_ids`. Sort with "
        "`sorting`; follow `has_next` for more pages. Archived tasks are left "
        "out unless `include_archived`."
    ),
    "list_task_groups": (
        "The groups the tasks `conditions` match fall into, grouped by one "
        "field (`group_by`, or `property:<id>` for a custom property), in the "
        "order a grouped list shows them, and the groups each task id is in. "
        "A date groups by `bucket`."
    ),
    "list_my_tasks": (
        "Tasks assigned to the caller across every community they belong to, or "
        "with `created` the ones they created. Left without `conditions`, only "
        "open tasks (not done); send `conditions` — `[]` for every task — to "
        "choose. A `guild_ids` condition narrows to some communities."
    ),
    "read_task": (
        "Read one task by id: its status, people, dates, checklist, tags and "
        "properties."
    ),
    "create_task": (
        "Create a task in a project (`project_id`). Left without "
        "`task_status_id`, it goes in the project's default column, and "
        "without `task_type_id` it is the project's default type. "
        "`description` is markdown; `checklist` takes lines of text."
    ),
    "update_task": (
        "Change a task. Only the fields sent change. `status_category` (e.g. "
        "`done`) moves it to that category's column without knowing the column "
        "id. `add_assignee_ids`/`remove_assignee_ids` change people without "
        "replacing the list; `assignee_ids` and `tag_ids` replace it. "
        "`checklist` rewrites the lines but never their ticks — use "
        "`toggle_checklist_item`. `task_type_id` changes its type (see "
        "`list_task_types`) and keeps everything it holds. To move it to "
        "another project, `move_task`."
    ),
    "move_task": (
        "Move a task to another project (`target_project_id`), into that "
        "project's default column. It keeps a type of the same name there, or "
        "takes that project's default type."
    ),
    "toggle_checklist_item": (
        "Tick or untick one checklist item on a task, by the item's `id` from "
        "`read_task`."
    ),
    "read_task_case": (
        "For a task opened from an operations case: how the case was filed and "
        "by whom. 404 for an ordinary task."
    ),
    # --- Comments -----------------------------------------------------------
    "list_comments": (
        "The comment thread on one thing — name it with exactly one of the "
        "`*_id` arguments. Newest conversations first, each with its replies; "
        "follow `next_cursor` for older ones."
    ),
    "create_comment": (
        "Comment on one thing, named with exactly one of the `*_id` arguments. "
        "`content` is markdown; `parent_comment_id` makes it a reply."
    ),
    "read_comment": "Read one comment by id.",
    "update_comment": "Change the text of a comment the caller wrote.",
    # --- Files --------------------------------------------------------------
    "read_file": (
        "Read one file by id, with its body. A body can be large: pass "
        "`include_content=false` for the name, tags and properties alone."
    ),
    "update_file": (
        "Change a file. Only the fields sent change. To change its body, send "
        "the whole new `content` with the `content_version` of the read it was "
        "made from; if somebody changed the body since, the write is refused "
        "and the file should be read again."
    ),
    "list_file_versions": "The stored versions of an uploaded file, newest first.",
    # --- Queues -------------------------------------------------------------
    "add_queue_item": (
        "Add an item to a queue. `position` orders it among the others; "
        "`user_id` names who it is for."
    ),
    "read_queue_item": "Read one queue item by id.",
    "update_queue_item": "Change a queue item. Only the fields sent change.",
    # --- Counters -----------------------------------------------------------
    "add_counter": (
        "Add a counter to a counter group. `min`, `max` and `step` bound and "
        "size its moves; `count` is where it starts."
    ),
    "read_counter": "Read one counter by id, with its count.",
    "update_counter": (
        "Change a counter's name, bounds, step or look. Only the fields sent "
        "change. Its count moves with `set_counter_count` and `step_counter`."
    ),
    "set_counter_count": "Put a counter at a number, held within its bounds.",
    "step_counter": (
        "Move a counter `up` or `down` by `amount`, or by its own step, held "
        "within its bounds."
    ),
    # --- Calendars ----------------------------------------------------------
    "create_calendar": (
        "Create a calendar in an initiative (`initiative_id`). Without one it "
        "is a community calendar, which only a community admin may make. The "
        "caller owns it; `grants` says who else it is shared with."
    ),
    "list_calendar_entries": (
        "What is on in a community between `start_after` and `start_before`: "
        "events, with repeating ones expanded, beside the tasks due. Narrow "
        "with `initiative_id` or `calendar_ids`, filter the tasks with "
        "`conditions`, and add projects or poll closings with "
        "`include_projects`/`include_polls`."
    ),
    "list_my_calendar_entries": (
        "The caller's events and assigned tasks across every community between "
        "`start_after` and `start_before`. Narrow with `community_ids`."
    ),
    "read_calendar_event": (
        "Read one event by id. For one occurrence of a repeating event, pass "
        "its `occurrence`."
    ),
    "create_calendar_event": (
        "Create an event on a calendar (`calendar_id`). `recurrence` takes RFC "
        "5545 lines; `attendee_ids` invites people."
    ),
    "update_calendar_event": (
        "Change an event. Only the fields sent change. For a repeating event, "
        "`scope` says which occurrences: `this` one (named by `occurrence`), "
        "`following`, or `all`. `calendar_id` moves it to another calendar."
    ),
    # --- Dashboards ---------------------------------------------------------
    "read_dashboard": (
        "Read one dashboard by id: its layout and widgets. What the widgets "
        "currently show is `load_dashboard_data`."
    ),
    "update_dashboard": (
        "Change a dashboard's name or description, or replace its "
        "`definition`/`config`. Only the fields sent change."
    ),
    "load_dashboard_data": (
        "What every widget on a dashboard currently shows, in one call. A "
        "widget whose query is refused says so in its own entry."
    ),
    # --- Notices ------------------------------------------------------------
    "create_post": (
        "Post a notice to an initiative's board (`initiative_id`). "
        "`scheduled_for` holds it back until then; `poll` attaches a poll. The "
        "caller owns it; `grants` says who else it is shared with."
    ),
    "update_post": (
        "Edit a notice. Only the fields sent change. `scheduled_for` moves a "
        "schedule not yet reached; sending it as `null` publishes the notice "
        "now. A notice already up cannot be rescheduled."
    ),
    "get_post_timeline": (
        "The months a board has notices in, newest first, with how many in "
        "each. Takes the same filters as `list_posts`."
    ),
    # --- Libraries ----------------------------------------------------------
    "update_library": (
        "Change a library's name or description, or choose its cover (`cover_item_id`)."
    ),
    "list_library_items": (
        "One page of a library's pictures, newest first (`oldest_first` to "
        "reverse). Narrow with `search` or `tag_ids`."
    ),
    "get_library_item_timeline": (
        "The months a library has pictures in, newest first, with how many in each."
    ),
    "read_library_item": "Read one picture in a library by id.",
    "list_library_item_versions": "Every stored rendition of a picture, newest first.",
    # --- Wikis --------------------------------------------------------------
    "update_wiki": (
        "Change a wiki: its name and description, its home page, page order "
        "and display settings. Only the fields sent change."
    ),
    "list_wiki_pages": (
        "Every page of a wiki, in reading order, without their bodies. Read a "
        "page's body with `read_wiki_page`."
    ),
    "create_wiki_page": (
        "Add a page to a wiki, under `parent_page_id` if given. It is a draft, "
        "hidden from readers, unless `is_draft=false`."
    ),
    "read_wiki_page": "Read one wiki page by id, with its body.",
    "update_wiki_page": (
        "Change a wiki page. Only the fields sent change. `is_draft=false` "
        "publishes it. To change its body, send the whole new `content` with "
        "the `content_version` of the read it was made from."
    ),
    # --- Relationships ------------------------------------------------------
    "list_relationships": (
        "What one thing is linked to — what it depends on, is part of, is "
        "related to or mentions — named as `kind:id` (e.g. `task:12`). "
        "`direction=inbound` lists what links to it instead."
    ),
    "create_relationship": (
        "Link two things in the same initiative, each named as `{type, id}`. "
        "`depends_on`: the source cannot proceed until the target; `part_of`: "
        "the source is a piece of the target; `attached` and `related_to` "
        "belong together. 409 if the link is already there."
    ),
}


def describe(name: str) -> str | None:
    """The description an MCP tool publishes, or ``None`` for a tool this
    module does not know."""
    if name in TOOL_DESCRIPTIONS:
        return TOOL_DESCRIPTIONS[name]
    for tool in Tool:
        templated = _templated(tool)
        if name in templated:
            return templated[name]
    return None


def described_names() -> frozenset[str]:
    """Every tool name this module describes."""
    names = set(TOOL_DESCRIPTIONS)
    for tool in Tool:
        names |= set(_templated(tool))
    return frozenset(names)
