"""The event vocabulary a subscription may name, derived not listed.

A subscription says which events it wants (``tasks.updated``) and optionally
which columns it cares about (``status_id``). Both are checked here so a typo is
a 400 at registration rather than a target that silently never fires — the
failure that started this whole line of work.

Nothing is enumerated by hand. Resources are what the capture specs name,
actions are what the capture trigger emits, and the field vocabulary comes from
the mapped columns plus the facet labels sub-resources report under. A new
content table therefore becomes subscribable the moment it joins the registry,
with no edit here.

Each is read for a community's tool set (``app.core.tool_set``): the built-in
tools', and an installed tool plug-in's tables beside them. A tool plug-in's
table is named by its kind (``counter_group.tsjvtcm0s7gv2x``), the name its
routes take (``/plugin-tools/{kind}``), so its events are
``<kind>.created`` and the rest, and the fields they report are its columns:
its declared fields and the ones every tool's rows have.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from app.core.plugin_scopes import PluginScopeResource
from app.core.tool_set import BUILTIN_TOOLS, KEPT_TOOL_SETS, ToolSet
from app.db.event_capture import (
    HOUSEKEEPING_COLUMNS,
    HOUSEKEEPING_SUFFIXES,
    build_specs,
)
from app.db.plugin_rls import PluginTableKind, plugin_table_access

#: What the capture trigger emits. A soft delete arrives as ``deleted`` and a
#: restore as ``created``, so this is the whole vocabulary.
ACTIONS: tuple[str, ...] = ("created", "updated", "deleted")

#: The demo deployment's events (``app.demo``): a link opened for the first
#: time, and an address left on one. Each names the link by the receiving
#: install's reference for it, and only an install in the operations community
#: whose grant holds the community-admin standing hears them.
DEMO_LINK_OPENED = "demo.link_opened"
DEMO_LEAD_LEFT = "demo.lead_left"
DEMO_EVENT_TYPES: frozenset[str] = frozenset({DEMO_LINK_OPENED, DEMO_LEAD_LEFT})


@lru_cache(maxsize=KEPT_TOOL_SETS)
def kinds_by_table(tools: ToolSet = BUILTIN_TOOLS) -> Mapping[str, str]:
    """Each installed tool's table and each of its items', to the kind its
    events name it by. None for the built-in tools, whose events name their
    tables."""
    return {
        table: kind
        for record in tools.installed
        for kind, table in (
            (record.kind, record.table.name),
            *((child.value, child.table) for child in record.children),
        )
    }


def resource_name(resource_type: str, tools: ToolSet = BUILTIN_TOOLS) -> str:
    """What an event names the resource the change log names
    ``resource_type``: an installed tool's table by its kind, everything else
    as it is."""
    return kinds_by_table(tools).get(resource_type, resource_type)


@lru_cache(maxsize=KEPT_TOOL_SETS)
def _vocabulary(tools: ToolSet = BUILTIN_TOOLS) -> dict[str, frozenset[str]]:
    """Resource -> the field names events for it can report, in a community
    with ``tools``.

    A resource's own columns, minus the housekeeping ones the trigger already
    excludes, plus the facet label of every sub-resource that reports against it
    — a row in ``task_tags`` arrives as ``tasks.updated`` with ``changed:
    ['tags']``, so ``tags`` has to be nameable even though no such column
    exists.
    """
    fields: dict[str, set[str]] = {}
    for spec in build_specs(tools):
        if spec.facet is not None:
            # A polymorphic facet reports against any of several parents, and
            # every one of them can name the label. A facet the ROW decides
            # brings its whole vocabulary: an edge says ``tags`` or
            # ``attachments`` depending on what it is, and both are nameable.
            labels = spec.facet_values or {spec.facet}
            for resource in spec.resource_types:
                fields.setdefault(resource_name(resource, tools), set()).update(labels)
            continue
        bucket = fields.setdefault(
            resource_name(spec.static_resource_type, tools), set()
        )
        bucket.update(
            column.name
            for column in tools.tables[spec.table].columns
            if column.name not in HOUSEKEEPING_COLUMNS
            and not column.name.endswith(HOUSEKEEPING_SUFFIXES)
        )
    return {resource: frozenset(names) for resource, names in fields.items()}


def resources(tools: ToolSet = BUILTIN_TOOLS) -> frozenset[str]:
    return frozenset(_vocabulary(tools))


def event_types(tools: ToolSet = BUILTIN_TOOLS) -> frozenset[str]:
    """Every ``resource.action`` a subscription may name in a community with
    ``tools``."""
    return frozenset(
        f"{resource}.{action}" for resource in _vocabulary(tools) for action in ACTIONS
    )


def fields_for(resource: str, tools: ToolSet = BUILTIN_TOOLS) -> frozenset[str]:
    return _vocabulary(tools).get(resource, frozenset())


def unknown_event_types(
    candidates: list[str], tools: ToolSet = BUILTIN_TOOLS
) -> list[str]:
    known = event_types(tools)
    return sorted({name for name in candidates if name not in known})


def unknown_fields(
    candidates: list[str],
    event_types_named: list[str],
    tools: ToolSet = BUILTIN_TOOLS,
) -> list[str]:
    """Field names none of the named events could ever report.

    Checked against the union across the subscription's resources rather than
    per event, so a subscription watching both tasks and files may name a
    field belonging to either.
    """
    allowed: set[str] = set()
    for event_type in event_types_named:
        resource, _, _action = event_type.rpartition(".")
        allowed |= fields_for(resource, tools)
    return sorted({name for name in candidates if name not in allowed})


def _scope_resource(resource: PluginScopeResource | str) -> str:
    """A scope's resource as its scope names it: a built-in one's value, an
    installed tool's kind."""
    return resource.value if isinstance(resource, PluginScopeResource) else resource


@lru_cache(maxsize=KEPT_TOOL_SETS)
def _read_scopes(tools: ToolSet = BUILTIN_TOOLS) -> dict[str, str | None]:
    """Resource -> the scope resource a plug-in must read to hear its events,
    in a community with ``tools``.

    A resource's events describe the rows of the table it is named after, so
    they answer to that table's scope (``app.db.plugin_rls``): ``tasks`` to
    ``projects``, ``calendar_events`` to ``calendars``, and an installed
    tool's item to its tool's kind. A resource whose table no scope names maps
    to ``None``, and no plug-in hears it.
    """
    tables: dict[str, str] = {}
    for spec in build_specs(tools):
        if spec.facet is None:
            tables.setdefault(
                resource_name(spec.static_resource_type, tools), spec.table
            )
    table_access = plugin_table_access(tools)
    scopes: dict[str, str | None] = {}
    for resource in _vocabulary(tools):
        access = table_access.get(tables.get(resource, resource))
        scopes[resource] = (
            _scope_resource(access.resource)
            if access is not None
            and access.kind is PluginTableKind.scoped
            and access.resource is not None
            else None
        )
    return scopes


def read_scope_for(event_type: str, tools: ToolSet = BUILTIN_TOOLS) -> str | None:
    """The scope resource whose read a plug-in holds to hear ``event_type`` in
    a community with ``tools``, or ``None`` when no scope reaches it (or it is
    not an event type at all)."""
    resource, _, _action = event_type.rpartition(".")
    return _read_scopes(tools).get(resource)


def event_read_scopes() -> frozenset[str]:
    """Every scope a plug-in may need to hear some built-in event type: the
    read scope of each resource whose events a plug-in can hear. A tool
    plug-in's events need its own tool's, ``<kind>:read``."""
    return frozenset(
        f"{resource}:read" for resource in _read_scopes().values() if resource
    )
