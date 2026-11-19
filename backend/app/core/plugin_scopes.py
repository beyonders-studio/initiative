"""The scopes a plug-in can be granted in a community — the one vocabulary.

A scope is ``<resource>:<access>``: ``projects:write``, ``comments:read``. The
resources are derived from the registries that already define the things they
name, so a new tool is a new scope the moment it joins ``Tool``:

- one resource per tool, spelled as the tool's plural;
- ``comments``, ``relationships`` and ``tags``, the surfaces that span tools;
- ``properties``, an initiative's custom property definitions. A project's or
  a collection's metadata is defined with the scope of its tool (``projects``,
  ``files``), and a value set on an item answers to the scope of the tool
  that governs the item instead;
- ``sharing``, a resource's grants: reading who has access, and changing it
  where the plug-in's own rung on the resource would let a person;
- ``members`` and ``initiatives``, which are read-only.

Writing implies reading. :func:`expand` applies that once, so no later check
has to ask twice.

Two more name a **standing** rather than a resource: ``initiatives:moderate``
(acting as a moderator in an initiative the plug-in is placed in) and
``community:admin`` (acting with a community admin's standing). A grant holds them by
exact name, :func:`expand` gives them nothing, and no token carries one unless
it asks for it by its level (:class:`InstallLevel`); see
``app.services.marketplace.plugin_oauth``.

Beside that fixed vocabulary sits one open family: ``plugins:<public_id>``, which
lets a plug-in call another plug-in's public endpoints through Initiative. It names
no resource of the community's, so :func:`expand` gives it nothing; it is
parsed by its prefix and the public-id characters (:func:`plugin_scope_target`)
rather than listed, and a grant holds it by exact name.

Beside them sits a second open family, one per installed tool plug-in: its
tool's kind (``app.db.plugin_tools``) as the resource, ``<kind>:read`` and
``<kind>:write``, which reach the tool's rows and its items as a built-in
tool's scopes reach its own (:func:`tool_scope_target`). It names a tool only
a community that installed it has; elsewhere it reaches nothing.

Dependency-free apart from ``Tool`` at import, so ``app.db``'s registry layer
can import it.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from app.core.tools import Tool

#: The resources that span tools, and the read-only ones. Everything else is a
#: tool.
_SHARED_RESOURCES: tuple[str, ...] = (
    "comments",
    "relationships",
    "tags",
    "properties",
    "sharing",
)
_READ_ONLY_RESOURCES: tuple[str, ...] = ("members", "initiatives")

# What a scope names: one member per tool, plus the surfaces that span tools.
PluginScopeResource = Enum(
    "PluginScopeResource",
    [
        (name, name)
        for name in (
            *(tool.plural for tool in Tool),
            *_SHARED_RESOURCES,
            *_READ_ONLY_RESOURCES,
        )
    ],
    type=str,
)


class PluginScopeAccess(str, Enum):
    read = "read"
    write = "write"


#: Resources a scope may only read.
READ_ONLY_RESOURCES: frozenset[PluginScopeResource] = frozenset(
    PluginScopeResource(name) for name in _READ_ONLY_RESOURCES
)


def tool_resource(tool: Tool) -> PluginScopeResource:
    """The resource a tool's scopes name."""
    return PluginScopeResource(tool.plural)


def scope_name(resource: PluginScopeResource, access: PluginScopeAccess) -> str:
    """The scope string for ``resource`` at ``access``."""
    return f"{resource.value}:{access.value}"


class InstallLevel(str, Enum):
    """A standing an installation token may ask for, above what its scopes
    alone give it."""

    moderator = "moderator"
    community_admin = "community_admin"


#: The scope a community grants for each level.
LEVEL_SCOPES: dict[InstallLevel, str] = {
    InstallLevel.moderator: "initiatives:moderate",
    InstallLevel.community_admin: "community:admin",
}
STANDING_SCOPES: frozenset[str] = frozenset(LEVEL_SCOPES.values())

#: The resource scopes, in a stable order.
_RESOURCE_SCOPES: tuple[str, ...] = tuple(
    scope_name(resource, access)
    for resource in PluginScopeResource
    for access in PluginScopeAccess
    if not (access is PluginScopeAccess.write and resource in READ_ONLY_RESOURCES)
)

#: Every scope a plug-in can be granted, in a stable order: the resource scopes,
#: then the standings.
ALL_SCOPES: tuple[str, ...] = _RESOURCE_SCOPES + tuple(LEVEL_SCOPES.values())
_ALL_SCOPES = frozenset(ALL_SCOPES)
_PARSEABLE = frozenset(_RESOURCE_SCOPES)


def is_standing_scope(scope: str) -> bool:
    """Whether ``scope`` names a standing (:data:`LEVEL_SCOPES`)."""
    return scope in STANDING_SCOPES


#: The prefix of the scope family that lets a plug-in call another plug-in.
PLUGIN_SCOPE_PREFIX = "plugins:"

#: What a public id is drawn from, and how long one may be: the contract's
#: ``publicId`` character set and ``publicIdLength`` cap, restated here so this
#: module stays free of the marketplace package (``plugin_scopes_test`` holds the
#: two equal).
PUBLIC_ID_CHARS: frozenset[str] = frozenset("-.0123456789_abcdefghijklmnopqrstuvwxyz")
MAX_PUBLIC_ID_LENGTH = 120


def plugin_scope(public_id: str) -> str:
    """The scope that lets a plug-in call the plug-in ``public_id``."""
    return f"{PLUGIN_SCOPE_PREFIX}{public_id}"


def plugin_scope_target(scope: str) -> str | None:
    """The public id a ``plugins:`` scope names, or ``None`` when ``scope`` is
    not one: the prefix, then a ``<publisher>.<slug>`` id of the public-id
    characters."""
    if not isinstance(scope, str) or not scope.startswith(PLUGIN_SCOPE_PREFIX):
        return None
    public_id = scope[len(PLUGIN_SCOPE_PREFIX) :]
    if not public_id or len(public_id) > MAX_PUBLIC_ID_LENGTH or "." not in public_id:
        return None
    for character in public_id:
        if character not in PUBLIC_ID_CHARS:
            return None
    return public_id


def tool_scope_target(scope: str) -> str | None:
    """The tool plug-in's kind a ``<kind>:read`` or ``<kind>:write`` scope
    names, or ``None`` when ``scope`` is not one."""
    from app.db.plugin_tools import is_plugin_kind

    if not isinstance(scope, str):
        return None
    kind, _, access = scope.rpartition(":")
    if access not in PluginScopeAccess._value2member_map_ or not is_plugin_kind(kind):
        return None
    return kind


def is_known_scope(scope: str) -> bool:
    """Whether ``scope`` is in the vocabulary, the ``plugins:`` family or a
    tool plug-in's."""
    return (
        scope in _ALL_SCOPES
        or plugin_scope_target(scope) is not None
        or tool_scope_target(scope) is not None
    )


def ordered_scopes(scopes: Iterable[str]) -> list[str]:
    """The known scopes among ``scopes``, each once: the vocabulary's in its
    order, then the open families' sorted."""
    asked = {scope for scope in scopes if isinstance(scope, str)}
    return [scope for scope in ALL_SCOPES if scope in asked] + sorted(
        scope for scope in asked - _ALL_SCOPES if is_known_scope(scope)
    )


class UnknownPluginScope(ValueError):
    """A string that is not a scope in this vocabulary."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


def parse_scope(scope: str) -> tuple[PluginScopeResource | str, PluginScopeAccess]:
    """Split a resource scope into its resource and access, or raise
    :class:`UnknownPluginScope`. A tool plug-in's resource is its kind. A
    standing scope names no resource and is not one."""
    kind = tool_scope_target(scope)
    if kind is not None:
        return kind, PluginScopeAccess(scope.rpartition(":")[2])
    if scope not in _PARSEABLE:
        raise UnknownPluginScope(scope)
    resource, _, access = scope.partition(":")
    return PluginScopeResource(resource), PluginScopeAccess(access)


def validate_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """``scopes`` as a set, raising :class:`UnknownPluginScope` on the first one
    that is neither in the vocabulary nor in the ``plugins:`` family."""
    checked = frozenset(scopes)
    for scope in sorted(checked):
        if not is_known_scope(scope):
            raise UnknownPluginScope(scope)
    return checked


def expand(
    scopes: Iterable[str],
) -> tuple[frozenset[PluginScopeResource | str], frozenset[PluginScopeResource | str]]:
    """The resources ``scopes`` let a plug-in read and write.

    Writing implies reading, so every written resource is in the read set too.
    A ``plugins:`` scope or a standing names no resource and adds nothing.
    """
    read: set[PluginScopeResource | str] = set()
    write: set[PluginScopeResource | str] = set()
    for scope in scopes:
        if plugin_scope_target(scope) is not None or is_standing_scope(scope):
            continue
        resource, access = parse_scope(scope)
        read.add(resource)
        if access is PluginScopeAccess.write:
            write.add(resource)
    return frozenset(read), frozenset(write)
