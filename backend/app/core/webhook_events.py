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
"""

from __future__ import annotations

from functools import lru_cache

from sqlmodel import SQLModel

from app.core.plugin_scopes import PluginScopeAccess, PluginScopeResource, scope_name
from app.db.plugin_rls import PLUGIN_TABLE_ACCESS, PluginTableKind
from app.db.event_capture import (
    HOUSEKEEPING_COLUMNS,
    HOUSEKEEPING_SUFFIXES,
    build_specs,
)

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


@lru_cache(maxsize=1)
def _vocabulary() -> dict[str, frozenset[str]]:
    """Resource -> the field names events for it can report.

    A resource's own columns, minus the housekeeping ones the trigger already
    excludes, plus the facet label of every sub-resource that reports against it
    — a row in ``task_tags`` arrives as ``tasks.updated`` with ``changed:
    ['tags']``, so ``tags`` has to be nameable even though no such column
    exists.
    """
    fields: dict[str, set[str]] = {}
    for spec in build_specs():
        if spec.facet is not None:
            # A polymorphic facet reports against any of several parents, and
            # every one of them can name the label. A facet the ROW decides
            # brings its whole vocabulary: an edge says ``tags`` or
            # ``attachments`` depending on what it is, and both are nameable.
            labels = spec.facet_values or {spec.facet}
            for resource in spec.resource_types:
                fields.setdefault(resource, set()).update(labels)
            continue
        bucket = fields.setdefault(spec.static_resource_type, set())
        table = SQLModel.metadata.tables[spec.table]
        bucket.update(
            column.name
            for column in table.columns
            if column.name not in HOUSEKEEPING_COLUMNS
            and not column.name.endswith(HOUSEKEEPING_SUFFIXES)
        )
    return {resource: frozenset(names) for resource, names in fields.items()}


def resources() -> frozenset[str]:
    return frozenset(_vocabulary())


def event_types() -> frozenset[str]:
    """Every ``resource.action`` a subscription may name."""
    return frozenset(
        f"{resource}.{action}" for resource in _vocabulary() for action in ACTIONS
    )


def fields_for(resource: str) -> frozenset[str]:
    return _vocabulary().get(resource, frozenset())


def unknown_event_types(candidates: list[str]) -> list[str]:
    known = event_types()
    return sorted({name for name in candidates if name not in known})


def unknown_fields(candidates: list[str], event_types_named: list[str]) -> list[str]:
    """Field names none of the named events could ever report.

    Checked against the union across the subscription's resources rather than
    per event, so a subscription watching both tasks and files may name a
    field belonging to either.
    """
    allowed: set[str] = set()
    for event_type in event_types_named:
        resource, _, _action = event_type.rpartition(".")
        allowed |= fields_for(resource)
    return sorted({name for name in candidates if name not in allowed})


@lru_cache(maxsize=1)
def _read_scopes() -> dict[str, PluginScopeResource | None]:
    """Resource -> the scope resource a plug-in must read to hear its events.

    A resource's events describe the rows of the table it is named after, so
    they answer to that table's scope in ``PLUGIN_TABLE_ACCESS``: ``tasks`` to
    ``projects``, ``calendar_events`` to ``calendars``. A resource whose table
    no scope names maps to ``None``, and no plug-in hears it.
    """
    tables: dict[str, str] = {}
    for spec in build_specs():
        if spec.facet is None:
            tables.setdefault(spec.static_resource_type, spec.table)
    scopes: dict[str, PluginScopeResource | None] = {}
    for resource in _vocabulary():
        access = PLUGIN_TABLE_ACCESS.get(tables.get(resource, resource))
        scopes[resource] = (
            access.resource
            if access is not None and access.kind is PluginTableKind.scoped
            else None
        )
    return scopes


def read_scope_for(event_type: str) -> PluginScopeResource | None:
    """The scope resource whose read a plug-in holds to hear ``event_type``, or
    ``None`` when no scope reaches it (or it is not an event type at all)."""
    resource, _, _action = event_type.rpartition(".")
    return _read_scopes().get(resource)


def event_read_scopes() -> frozenset[str]:
    """Every scope a plug-in may need to hear some event type: the read scope of
    each resource whose events a plug-in can hear."""
    return frozenset(
        scope_name(resource, PluginScopeAccess.read)
        for resource in _read_scopes().values()
        if resource is not None
    )
