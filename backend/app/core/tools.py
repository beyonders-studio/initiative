"""The canonical ``Tool`` enum — the app-wide set of shareable tool kinds.

A tool is a first-class thing an initiative offers. Every tool is the same shape:
a soft-deletable content table under initiative-member RLS, shared via
``resource_grants`` (its string value IS the ``resource_type``). The single source
of truth for that set — the DAC registries and every tool endpoint reference it
rather than repeating string literals. Kept free of app imports beyond the leaf
``errors`` and ``messages`` modules, so it can be imported anywhere. ``tools_test.py`` asserts every per-tool surface covers
this enum, so a new member that forgets to wire one fails CI.
"""

from dataclasses import dataclass
from enum import Enum

from app.core.errors import CodedError
from app.core.messages import KindMessages


def kind_refusal(kind: str, code: str, status_code: int) -> CodedError:
    """A ``KindMessages`` refusal about ``kind``, which its wording names."""
    return CodedError(code, status_code, params={"kind": kind})


def plural_of(stem: str) -> str:
    """The plural spelling of a tool stem — ``post`` → ``posts``, ``library`` →
    ``libraries``. The frontend's ``toolPlural`` applies the same rule."""
    if len(stem) > 1 and stem.endswith("y") and stem[-2] not in "aeiou":
        return stem[:-1] + "ies"
    return stem + "s"


class Tool(str, Enum):
    project = "project"
    file = "file"
    queue = "queue"
    counter_group = "counter_group"
    calendar = "calendar"
    dashboard = "dashboard"
    post = "post"
    library = "library"
    wiki = "wiki"

    @property
    def plural(self) -> str:
        """Pluralized stem — the table-ish spelling every derived name uses
        (``counter_group`` → ``counter_groups``, ``library`` → ``libraries``).

        One rule, mirrored by the frontend's ``toolPlural``: a trailing ``y``
        after a consonant becomes ``ies``, and everything else takes an ``s``.
        """
        return plural_of(self.value)

    @property
    def route_segment(self) -> str:
        """The kebab plural every route for this tool is served under
        (``counter_group`` → ``counter-groups``). The frontend's
        ``toolRouteSegment`` applies the same rule."""
        return self.plural.replace("_", "-")

    @property
    def view_permission(self) -> str:
        """The role ``PermissionKey`` value gating viewing this tool. For
        toggleable tools it is also the initiative master-switch column."""
        return f"{self.plural}_enabled"

    @property
    def create_permission(self) -> str:
        """The role ``PermissionKey`` value gating creating this tool."""
        return f"create_{self.plural}"

    # The refusals every tool answers alike, each naming the tool. A method
    # rather than a constant: each call is a fresh exception to raise.

    def not_found(self, status_code: int = 404) -> CodedError:
        """No such <tool>, or not one this reader can see."""
        return kind_refusal(self.value, KindMessages.NOT_FOUND, status_code)

    def no_access(self) -> CodedError:
        """This <tool> is not shared with you."""
        return kind_refusal(self.value, KindMessages.NO_ACCESS, 403)

    def owner_required(self) -> CodedError:
        """Only the <tool>'s owner may do that."""
        return kind_refusal(self.value, KindMessages.OWNER_REQUIRED, 403)

    def write_required(self) -> CodedError:
        """You may read this <tool> but not change it."""
        return kind_refusal(self.value, KindMessages.WRITE_ACCESS_REQUIRED, 403)

    def create_denied(self) -> CodedError:
        """Your initiative role may not create <tool>s."""
        return kind_refusal(self.value, KindMessages.CREATE_PERMISSION_REQUIRED, 403)

    def disabled(self) -> CodedError:
        """This initiative has <tool>s switched off."""
        return kind_refusal(self.value, KindMessages.TOOL_NOT_ENABLED, 403)

    def grant_cannot_manage_members(self) -> CodedError:
        """A temporary grant reaches this <tool>'s content, not who may see it."""
        return kind_refusal(self.value, KindMessages.GRANT_CANNOT_MANAGE_MEMBERS, 403)

    def grantee_lacks_access(self) -> CodedError:
        """Sharing was addressed to somebody whose role does not reach <tool>s."""
        return kind_refusal(self.value, KindMessages.GRANTEE_LACKS_ACCESS, 422)


@dataclass(frozen=True)
class Kind:
    """A kind of thing a guild holds that can be addressed as ``(kind, id)``:
    every tool, the things that live inside one, and the guild's tags.

    ``code`` is **permanent**. It is the high bits of every node id derived from
    this kind (``app.core.relationships.node_id``), so changing one silently
    re-encodes every stored row of that kind while leaving the old rows behind:
    no error, no drift test in the database, just two encodings of the same
    thing. Codes are assigned once, never reordered, never reused — the
    discipline an announcement slug takes, for the same reason.
    """

    value: str
    code: int
    #: The tool this lives inside, for a kind that is not a tool itself.
    parent: Tool | None = None

    @property
    def table(self) -> str:
        """The guild-schema table ids of this kind point at."""
        return plural_of(self.value)

    @property
    def parent_column(self) -> str | None:
        """The column naming the tool this lives inside."""
        return f"{self.parent.value}_id" if self.parent else None

    def not_found(self, status_code: int = 404) -> CodedError:
        """No such <kind>, or not one this reader can see."""
        return kind_refusal(self.value, KindMessages.NOT_FOUND, status_code)


#: Every kind, keyed by its wire name. Append-only: a new kind takes the next
#: unused code, and no existing code ever moves. The initial set was assigned in
#: alphabetical order, which is where the resemblance ends — a derived ordinal
#: changes under you the first time a member is added in the middle. Declared
#: tools first, then what lives inside them, then the guild's vocabulary; the
#: lists below derived from it keep that order.
KINDS: dict[str, Kind] = {
    kind.value: kind
    for kind in (
        Kind(Tool.project.value, 10),
        Kind(Tool.file.value, 6),
        Kind(Tool.queue.value, 11),
        Kind(Tool.counter_group.value, 4),
        Kind(Tool.calendar.value, 1),
        Kind(Tool.dashboard.value, 5),
        Kind(Tool.post.value, 9),
        Kind(Tool.library.value, 7),
        Kind(Tool.wiki.value, 15),
        Kind("task", 14, parent=Tool.project),
        Kind("queue_item", 12, parent=Tool.queue),
        Kind("calendar_event", 2, parent=Tool.calendar),
        Kind("counter", 3, parent=Tool.counter_group),
        Kind("library_item", 8, parent=Tool.library),
        Kind("wiki_page", 16, parent=Tool.wiki),
        Kind("tag", 13),
    )
}

#: Every kind, keyed by the table its rows live in.
KIND_BY_TABLE: dict[str, Kind] = {kind.table: kind for kind in KINDS.values()}

#: The kinds that live inside a tool.
CHILD_KINDS: tuple[str, ...] = tuple(k.value for k in KINDS.values() if k.parent)

#: Every tool, then everything that lives inside one: every kind but the
#: community's vocabulary (tags).
CONTENT_KINDS: tuple[str, ...] = tuple(t.value for t in Tool) + CHILD_KINDS


# EVERY tool is toggleable: each carries a ``{plural}_enabled`` master switch on
# the initiative. Projects and files used to be exempt — always on, with no
# column at all — because they were the only places content could live and the
# other tools hung off them. Relationships ended that: anything links to
# anything, so an initiative that is only a calendar, or only a library, is a
# coherent thing to want rather than a half-built one.
#
# They keep the *default*, which is the part that was ever load-bearing. An
# initiative that says nothing about its tools still arrives with projects and
# files on, so nothing about making one changes; the switch is simply there
# to turn off now.
DEFAULT_ENABLED_TOOLS = frozenset({Tool.project, Tool.file})

# Tools WITHOUT an export-engine source, and why. Stated as an exclusion so the
# default is "a new tool is exportable": the adapter-coverage test then fails
# until the tool either has an adapter or is listed here deliberately. An
# inclusion list would instead let a new tool silently ship with no export.
#
# Empty, and that is the point: every tool has an export source. What used to
# sit here (``Tool.dashboard``) is now handled where it belongs — an entity
# built on a plug-in this build does not ship is filtered by provenance in
# ``services.export.provenance``, which is a property of the ROW, not of the
# tool. A whole tool is the wrong unit for that rule: most dashboards are
# hand-built here and are ordinary content.
NON_EXPORTABLE_TOOLS: frozenset[Tool] = frozenset()

# Tools with an export-engine source (single-entity + bulk selection export),
# all served by ``GET /exports/{tool}``. The engine's source name is the KEBAB
# SINGULAR of the tool ("counter_group" -> "counter-group"). The frontend
# mirrors this as TOOL_REGISTRY's ``bulkExport`` flag.
BULK_EXPORT_TOOLS = tuple(t for t in Tool if t not in NON_EXPORTABLE_TOOLS)

# Tools a person can subscribe to from another app: a personal API key limited
# to one of them (``user_api_keys.resource_type``/``resource_id``) reads that
# one's feed and nothing else. Each serves its feed from its own router.
FEED_TOOLS: frozenset[Tool] = frozenset({Tool.calendar})


# Comment surfaces: EVERY tool carries a thread, plus these content-level
# extras — sub-resources with a conversation of their own. A task holds one
# because a task is a piece of work people talk about; a wiki page holds one
# because a page is what somebody reads, and a note about the rota belongs on
# the rota rather than on the handbook it is filed in.
#
# An extra carries no ``comments_enabled`` column of its own; it is reached
# through the tool that owns it, and that tool's switch is what answers for it
# — a wiki's switch turns off the threads on its pages. The task is the one
# exception, and deliberately so: its thread predates the switch and belongs
# to the task rather than to the project's tool surface.
#
# Extras come first so the declaration order — and every derived column list —
# keeps reading task-first, as it always has.
COMMENTABLE_EXTRAS: tuple[str, ...] = ("task", "wiki_page")
COMMENT_TARGETS: tuple[str, ...] = COMMENTABLE_EXTRAS + tuple(t.value for t in Tool)


# Tag-assignment surfaces: EVERY tool is taggable, plus everything that lives
# inside one but a counter. The assignment registry (app.services.tenant.tags.TAG_LINKS) and
# the ``TagTarget`` schema enum both derive from TAG_TARGETS, so a new Tool is
# taggable across every surface with no per-surface edit; tags_test.py fails if
# any surface drifts.
TAGGABLE_EXTRAS: tuple[str, ...] = tuple(k for k in CHILD_KINDS if k != "counter")
TAG_TARGETS: tuple[str, ...] = tuple(t.value for t in Tool) + TAGGABLE_EXTRAS


# Trash surfaces: EVERY tool is trashable, plus everything that lives inside
# one, the comments on them, the initiative itself, and the guild-level content
# that isn't a tool (tags). Same shape as TAG_TARGETS above, for the same
# reason: the trash EntityType and its registry derive from this, so a new Tool
# reaches the trash can with no per-surface edit.
TRASHABLE_EXTRAS: tuple[str, ...] = ("comment", "initiative", "tag")
TRASH_TARGETS: tuple[str, ...] = CONTENT_KINDS + TRASHABLE_EXTRAS

#: Archivable things that are not tools. Archiving says "this is finished with",
#: which is true of anything an initiative offers — so every Tool is archivable,
#: with no exceptions — and of these two, which are worked through and put away
#: without being tools: a task, and an initiative itself.
ARCHIVABLE_EXTRAS: tuple[str, ...] = ("task", "initiative")
ARCHIVE_TARGETS: tuple[str, ...] = tuple(t.value for t in Tool) + ARCHIVABLE_EXTRAS

# Property surfaces: EVERY tool carries custom properties, plus every sub-tool —
# the rows inside a tool that are things in their own right. The properties
# seam (app.services.tenant.properties.PROPERTY_LINKS), the value table's
# CHECK, its policies and the ``PropertyTarget`` schema enum all derive from
# PROPERTY_TARGETS, so a new Tool carries properties with no per-surface edit.
PROPERTY_TARGETS: tuple[str, ...] = CONTENT_KINDS

# Items: the rows a tool lists one by one — every kind that lives inside a tool
# but the wiki page, which is a document — and the post, which is the feed's
# own item. The plug-in kit's contract names the same set (``itemKind``).
ITEM_KINDS: tuple[str, ...] = tuple(k for k in CHILD_KINDS if k != "wiki_page") + (
    Tool.post.value,
)

# Metadata surfaces: what an installed plug-in keeps its own values on. Every
# item, and the install itself, whose values are on ``(plugin, <install id>)``.
# The value table's CHECK, its policies and the installation routes derive
# from METADATA_TARGETS.
INSTALL_METADATA_KIND = "plugin"
METADATA_TARGETS: tuple[str, ...] = ITEM_KINDS + (INSTALL_METADATA_KIND,)

# Layouts (``tool_layouts``): how an instance of a tool draws its items, and
# one of them. Each of these tools has its own layouts per instance (a
# project's, a queue's); the calendar and the posts feed are one page per
# initiative, so their layouts belong to the initiative and name no instance.
# The table's CHECKs, its policies, its events and its purge derive from these.
LAYOUTS_PER_INSTANCE: tuple[Tool, ...] = (
    Tool.project,
    Tool.queue,
    Tool.counter_group,
    Tool.library,
)
LAYOUTS_SHARED: tuple[Tool, ...] = (Tool.calendar, Tool.post)
LAYOUT_TOOLS: tuple[Tool, ...] = LAYOUTS_PER_INSTANCE + LAYOUTS_SHARED
# A target has one layout of each kind its tool draws: how it lists what it
# holds (``LIST_LAYOUTS``), and how it shows one of them on its own
# (``DETAIL_LAYOUTS``: a project's task, the calendar's event). A tool with none here yet stores
# none. The list a target opens on is one more row (``LAYOUT_DEFAULT``).
LIST_LAYOUTS: dict[Tool, tuple[str, ...]] = {
    Tool.project: ("table", "board", "gantt", "calendar"),
    Tool.calendar: ("calendar",),
}
DETAIL_LAYOUTS: dict[Tool, tuple[str, ...]] = {
    Tool.project: ("task",),
    Tool.calendar: ("calendar_event",),
    Tool.queue: ("queue_item",),
    Tool.library: ("library_item",),
    Tool.counter_group: ("counter",),
    Tool.post: ("post",),
}
#: The details laid out once per type of item rather than once per target: a
#: project's task page is one per task type (``tool_layouts.task_type_id``).
TYPED_DETAILS: dict[Tool, str] = {Tool.project: "task"}
#: The per-instance tools that lay out anything of their own, a list or an
#: item: those an initiative's settings list.
INSTANCE_LAYOUT_TOOLS: tuple[Tool, ...] = tuple(
    tool
    for tool in LAYOUTS_PER_INSTANCE
    if tool in LIST_LAYOUTS or tool in DETAIL_LAYOUTS
)
LAYOUT_DEFAULT = "default"
LAYOUT_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *(kind for kinds in LIST_LAYOUTS.values() for kind in kinds),
            *(kind for kinds in DETAIL_LAYOUTS.values() for kind in kinds),
            LAYOUT_DEFAULT,
        ]
    )
)


def tool_export_source(tool: Tool) -> str:
    """The export adapter registry key for a tool."""
    return tool.value.replace("_", "-")


def tool_envelope_type(tool: Tool) -> str:
    """The import/export envelope ``type`` discriminator for a tool.

    One rule, spelled once: a tool's envelope is ``initiative-<kebab
    singular>``. The importers and the export adapters read it from here; only
    the envelope schemas restate it, because a pydantic ``Literal`` cannot be
    computed, and ``tools_test.py`` holds the importer registry to this.
    """
    return f"initiative-{tool_export_source(tool)}"


def tool_for_create_permission(permission_value: str) -> Tool:
    """The Tool whose ``create_permission`` is ``permission_value`` — the
    inverse lookup the import engine uses to reach a tool's master switch
    without re-deriving column names by string surgery. Raises KeyError for
    a permission that gates no tool (callers validate at registry-build
    time, so a miss is a programming error, never a request error)."""
    return _TOOL_BY_CREATE_PERMISSION[permission_value]


_TOOL_BY_CREATE_PERMISSION: dict[str, Tool] = {t.create_permission: t for t in Tool}
