"""The canonical ``Tool`` enum — the app-wide set of shareable tool kinds.

A tool is a first-class thing an initiative offers. Every tool is the same shape:
a soft-deletable content table under initiative-member RLS, shared via
``resource_grants`` (its string value IS the ``resource_type``). The single source
of truth for that set — the DAC registries and every tool endpoint reference it
rather than repeating string literals. Kept free of app imports beyond the leaf
``errors`` and ``messages`` modules, so it can be imported anywhere. ``tools_test.py`` asserts every per-tool surface covers
this enum, so a new member that forgets to wire one fails CI.

What is a fact about one tool rather than a rule every tool follows is its
record (:class:`ToolSpec`, in :data:`TOOL_SPECS`): adding a tool is its tables
plus one record. The frontend reads the records from the file
``scripts/build_tool_records.py`` writes beside its API types.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from app.core.errors import CodedError
from app.core.messages import KindMessages


def kind_refusal(kind: str, code: str, status_code: int) -> CodedError:
    """A ``KindMessages`` refusal about ``kind``, which its wording names."""
    return CodedError(code, status_code, params={"kind": kind})


def plural_of(stem: str) -> str:
    """The plural spelling of a tool stem — ``post`` → ``posts``,
    ``counter_group`` → ``counter_groups``. The frontend's ``toolPlural``
    applies the same rule."""
    if len(stem) > 1 and stem.endswith("y") and stem[-2] not in "aeiou":
        return stem[:-1] + "ies"
    return stem + "s"


class Tool(str, Enum):
    project = "project"
    file = "file"
    counter_group = "counter_group"
    calendar = "calendar"
    dashboard = "dashboard"
    post = "post"
    wiki = "wiki"
    contact = "contact"

    @property
    def plural(self) -> str:
        """Pluralized stem — the table-ish spelling every derived name uses
        (``counter_group`` → ``counter_groups``).

        One rule, mirrored by the frontend's ``toolPlural``: a trailing ``y``
        after a consonant becomes ``ies``, and everything else takes an ``s``.
        """
        return plural_of(self.value)

    @property
    def spec(self) -> ToolSpec:
        """This tool's record."""
        return TOOL_SPECS[self]

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
class Layouts:
    """How a tool lays out what it holds (``tool_layouts``)."""

    #: Each instance keeps layouts of its own (a project's, a counter
    #: group's). Otherwise the tool is one page per initiative (its calendar,
    #: its posts feed), so its layouts are the initiative's and name no
    #: instance.
    per_instance: bool
    #: How it lists what it holds, in the order offered.
    lists: tuple[str, ...] = ()
    #: The item it shows on its own (a project's task), if it lays one out.
    detail: str | None = None
    #: The detail is laid out once per type of item rather than once per
    #: instance: a project's task page is one per task type
    #: (``tool_layouts.task_type_id``).
    typed: bool = False


@dataclass(frozen=True)
class CommunityRows:
    """A tool whose rows may belong to the whole community (``initiative_id``
    NULL), each held by the community plug-in that mounts it. Such a row is
    made and changed by the holders of the tool's ``community_<plural>`` admin
    surface (``authorization.community_surface``)."""

    #: Whether a write grant on such a row changes it too. A contact holds
    #: nothing but itself, so writing one is changing it; a write grant on a
    #: calendar writes its events, and the calendar is the surface's.
    granted_writes_row: bool = False


@dataclass(frozen=True)
class ToolSpec:
    """The facts about one tool that are not a rule every tool follows."""

    #: Its kind code: permanent, as every :attr:`Kind.code` is.
    code: int
    #: Switched on in an initiative that says nothing about its tools.
    #:
    #: Every tool carries a ``{plural}_enabled`` switch on the initiative.
    #: Projects and files used to be exempt — always on, with no column at all
    #: — because they were the only places content could live. Relationships
    #: ended that: anything links to anything, so an initiative that is only a
    #: calendar is a coherent thing to want. They keep the default, which is
    #: the part that was ever load-bearing.
    on_by_default: bool = False
    #: The formats a selection of it exports to, in the order they are
    #: offered, all served by ``GET /exports/{tool}``. ``None`` for a tool
    #: whose formats depend on each row (a file's, on its type). Every tool
    #: exports by default, so leaving one out has to be written down, as an
    #: empty tuple; whether a row was built on a plug-in this build does not
    #: ship is the row's question (``services.export.provenance``), not the
    #: tool's.
    export_formats: tuple[str, ...] | None = ("json",)
    #: The formats an initiative or community report may write it in, in the
    #: order offered. With none chosen — or none offered — it rides as its
    #: envelope.
    report_formats: tuple[str, ...] = ()
    #: Report formats per file type, for a tool whose formats depend on each
    #: row rather than the tool (a file's, on its type).
    type_report_formats: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: A person can subscribe to it from another app: a personal API key
    #: limited to one of them (``user_api_keys.resource_type``/``resource_id``)
    #: reads its feed and nothing else, served from the tool's own router.
    feed: bool = False
    #: Whether its rows may belong to the whole community, and how they are
    #: written.
    community_rows: CommunityRows | None = None
    #: How it lays out what it holds, if it does.
    layouts: Layouts | None = None


#: Every tool's record, in enum order.
TOOL_SPECS: dict[Tool, ToolSpec] = {
    Tool.project: ToolSpec(
        code=10,
        on_by_default=True,
        export_formats=("json", "pdf", "csv", "xlsx"),
        report_formats=("pdf", "csv", "xlsx"),
        layouts=Layouts(
            per_instance=True,
            lists=("table", "board", "gantt", "calendar"),
            detail="task",
            typed=True,
        ),
    ),
    Tool.file: ToolSpec(
        code=6,
        on_by_default=True,
        export_formats=None,
        type_report_formats={
            "lexical": ("pdf", "md", "docx"),
            "sheet": ("csv", "xlsx"),
        },
    ),
    Tool.counter_group: ToolSpec(
        code=4,
        export_formats=("pdf", "csv", "xlsx", "md", "json"),
        report_formats=("pdf", "csv", "xlsx", "md"),
        layouts=Layouts(per_instance=True, detail="counter"),
    ),
    Tool.calendar: ToolSpec(
        code=1,
        export_formats=("ics", "json"),
        report_formats=("ics", "json"),
        feed=True,
        community_rows=CommunityRows(),
        layouts=Layouts(
            per_instance=False, lists=("calendar",), detail="calendar_event"
        ),
    ),
    Tool.dashboard: ToolSpec(code=5),
    Tool.post: ToolSpec(code=9, layouts=Layouts(per_instance=False, detail="post")),
    Tool.wiki: ToolSpec(code=15, export_formats=("pdf", "md", "docx", "json")),
    Tool.contact: ToolSpec(
        code=19,
        export_formats=("json", "csv"),
        # One spreadsheet of each initiative's contacts.
        report_formats=("csv",),
        community_rows=CommunityRows(granted_writes_row=True),
    ),
}


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
    #: Inside its tool but in no one instance of it: no column names a parent
    #: row, and its own row security answers for it rather than a parent's
    #: sharing (a collection, in Files).
    standalone: bool = False
    #: Inside a tool, and holds a conversation of its own (every tool does):
    #: :data:`COMMENT_TARGETS`.
    commentable: bool = False
    #: Inside a tool, and is put away when finished with (every tool is):
    #: :data:`ARCHIVE_TARGETS`.
    archivable: bool = False

    @property
    def table(self) -> str:
        """The guild-schema table ids of this kind point at."""
        return plural_of(self.value)

    @property
    def parent_column(self) -> str | None:
        """The column naming the tool instance this lives inside."""
        if self.parent is None or self.standalone:
            return None
        return f"{self.parent.value}_id"

    @property
    def tool(self) -> Tool:
        """The tool this kind is or lives in. Raises for one that is neither
        (a tag)."""
        return self.parent or Tool(self.value)

    def not_found(self, status_code: int = 404) -> CodedError:
        """No such <kind>, or not one this reader can see."""
        return kind_refusal(self.value, KindMessages.NOT_FOUND, status_code)


#: Every kind, keyed by its wire name. Append-only: a new kind takes the next
#: unused code, and no existing code ever moves. 7 and 8 were the libraries',
#: 11 and 12 were the queues', and all four stay retired. 18 is the person's
#: (``app.core.relationships.PERSON``), an edge end that is not a kind, and is
#: never reused. The initial set was assigned in alphabetical order, which is
#: where the resemblance ends — a derived ordinal changes under you the first
#: time a member is added in the middle. The tools first, with the codes their
#: records hold, then what lives inside them, then the guild's vocabulary; the
#: lists below derived from it keep that order.
KINDS: dict[str, Kind] = {
    kind.value: kind
    for kind in (
        *(Kind(tool.value, tool.spec.code) for tool in Tool),
        Kind("task", 14, parent=Tool.project, commentable=True, archivable=True),
        Kind("calendar_event", 2, parent=Tool.calendar),
        Kind("counter", 3, parent=Tool.counter_group),
        Kind("wiki_page", 16, parent=Tool.wiki, commentable=True),
        Kind(
            "collection",
            17,
            parent=Tool.file,
            standalone=True,
            commentable=True,
            archivable=True,
        ),
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


# Tools with an export-engine source (single-entity + bulk selection export),
# all served by ``GET /exports/{tool}``: every tool whose record does not say it
# exports nothing. The engine's source name is the KEBAB SINGULAR of the tool
# ("counter_group" -> "counter-group").
BULK_EXPORT_TOOLS = tuple(t for t in Tool if t.spec.export_formats != ())


# Comment surfaces: EVERY tool carries a thread, plus the kinds inside one that
# say so — sub-resources with a conversation of their own. A task holds one
# because a task is a piece of work people talk about; a wiki page holds one
# because a page is what somebody reads, and a note about the rota belongs on
# the rota rather than on the handbook it is filed in; a collection holds one
# because it is a thing in Files people talk about apart from its files.
#
# Such a kind carries no ``comments_enabled`` column of its own; it is reached
# through the tool that owns it, and that tool's switch is what answers for it
# — a wiki's switch turns off the threads on its pages. The task is one
# exception, and deliberately so: its thread predates the switch and belongs
# to the task rather than to the project's tool surface. A collection is the
# other: it sits in no one instance of Files, so it carries its own switch.
#
# The kinds come first so every derived column list keeps reading task-first,
# as it always has.
COMMENT_TARGETS: tuple[str, ...] = tuple(
    k for k in CHILD_KINDS if KINDS[k].commentable
) + tuple(t.value for t in Tool)


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

#: Everything archivable. Archiving says "this is finished with", which is true
#: of anything an initiative offers — so every Tool is archivable, with no
#: exceptions — and of the kinds inside one that say so, which are worked
#: through and put away without being tools (a task, a collection), and of an
#: initiative itself.
ARCHIVE_TARGETS: tuple[str, ...] = (
    *(t.value for t in Tool),
    *(k for k in CHILD_KINDS if KINDS[k].archivable),
    "initiative",
)

# Property surfaces: EVERY tool carries custom properties, plus every sub-tool —
# the rows inside a tool that are things in their own right. The properties
# seam (app.services.tenant.metadata.PROPERTY_LINKS), the value table's
# CHECK, its policies and the ``PropertyTarget`` schema enum all derive from
# PROPERTY_TARGETS, so a new Tool carries properties with no per-surface edit.
PROPERTY_TARGETS: tuple[str, ...] = CONTENT_KINDS

# Items: the rows a tool lists one by one — every kind that lives inside a tool
# but the wiki page, which is a document, and the collection, which groups
# files — and the post, which is the feed's own item. The plug-in kit's
# contract names the same set (``itemKind``).
ITEM_KINDS: tuple[str, ...] = tuple(
    k for k in CHILD_KINDS if k not in ("wiki_page", "collection")
) + (Tool.post.value,)

# Metadata surfaces: what an installed plug-in keeps its own values on. Every
# item, and the install itself, whose values are on ``(plugin, <install id>)``.
# The value table's CHECK, its policies and the installation routes derive
# from METADATA_TARGETS.
INSTALL_METADATA_KIND = "plugin"
METADATA_TARGETS: tuple[str, ...] = ITEM_KINDS + (INSTALL_METADATA_KIND,)

# Layouts (``tool_layouts``): how an instance of a tool draws its items, and
# one of them, as each tool's record says (:class:`Layouts`). The table's
# CHECKs, its policies, its events and its purge derive from these.
LAYOUTS_PER_INSTANCE: tuple[Tool, ...] = tuple(
    t for t in Tool if t.spec.layouts is not None and t.spec.layouts.per_instance
)
LAYOUTS_SHARED: tuple[Tool, ...] = tuple(
    t for t in Tool if t.spec.layouts is not None and not t.spec.layouts.per_instance
)
LAYOUT_TOOLS: tuple[Tool, ...] = LAYOUTS_PER_INSTANCE + LAYOUTS_SHARED
#: Kinds inside a tool that lay out what they hold themselves, as an instance
#: does: a collection's files. ``tool_id`` is the row's own id.
LAYOUT_KIND_TARGETS: tuple[str, ...] = ("collection",)
#: Every value ``tool_layouts.tool`` takes.
LAYOUT_TARGETS: tuple[str, ...] = (
    *(tool.value for tool in LAYOUT_TOOLS),
    *LAYOUT_KIND_TARGETS,
)
# A target has one layout of each kind its tool draws: how it lists what it
# holds (``LIST_LAYOUTS``), and how it shows one of them on its own
# (``DETAIL_LAYOUTS``: a project's task, the calendar's event, a collection's
# file). A tool with none here yet stores none. The list a target opens on is
# one more row (``LAYOUT_DEFAULT``).
#: Every target that names an instance, and the table its ``tool_id`` points at.
LAYOUT_INSTANCE_TABLES: dict[str, str] = {
    **{tool.value: tool.plural for tool in LAYOUTS_PER_INSTANCE},
    **{kind: KINDS[kind].table for kind in LAYOUT_KIND_TARGETS},
}
LIST_LAYOUTS: dict[str, tuple[str, ...]] = {
    **{
        tool: layouts.lists
        for tool in LAYOUT_TOOLS
        if (layouts := tool.spec.layouts) is not None and layouts.lists
    },
    "collection": ("masonry", "grid", "timeline", "table"),
}
#: Lists a target draws hidden until it shows them; every other list shows as
#: shipped. A new collection shows its grid and its table.
LISTS_HIDDEN_AS_SHIPPED: dict[str, frozenset[str]] = {
    "collection": frozenset({"masonry", "timeline"}),
}
DETAIL_LAYOUTS: dict[str, tuple[str, ...]] = {
    **{
        tool: (layouts.detail,)
        for tool in LAYOUT_TOOLS
        if (layouts := tool.spec.layouts) is not None and layouts.detail
    },
    "collection": ("file",),
}
#: The details laid out once per type of item rather than once per target
#: (:attr:`Layouts.typed`).
TYPED_DETAILS: dict[Tool, str] = {
    tool: layouts.detail
    for tool in LAYOUT_TOOLS
    if (layouts := tool.spec.layouts) is not None
    and layouts.typed
    and layouts.detail is not None
}
#: The per-instance tools that lay out anything of their own, a list or an
#: item: those an initiative's settings list.
INSTANCE_LAYOUT_TOOLS: tuple[Tool, ...] = tuple(
    tool
    for tool in LAYOUTS_PER_INSTANCE
    if tool in LIST_LAYOUTS or tool in DETAIL_LAYOUTS
)
LAYOUT_DEFAULT = "default"
_DETAIL_KINDS = [kind for kinds in DETAIL_LAYOUTS.values() for kind in kinds]
#: Every value ``tool_layouts.kind`` takes: the lists, then the details — the
#: items in the order their kinds are declared, then what a kind target shows
#: (a collection's file) — then the default.
LAYOUT_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *(kind for kinds in LIST_LAYOUTS.values() for kind in kinds),
            *(kind for kind in ITEM_KINDS if kind in _DETAIL_KINDS),
            *_DETAIL_KINDS,
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
    singular>``. The importers, the export adapters and the envelope schemas'
    ``type`` fields read it from here, and ``tools_test.py`` holds the
    importer registry and the schemas to it.
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
