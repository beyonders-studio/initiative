"""A kind a universal route takes, published as a string.

The universal routes (archive, trash, comments, tags, links, sharing,
properties, personal items, search, export) each take a kind: one of the
built-in kinds the route serves, or a kind of a tool plug-in the community has
installed (``<key>.<uid>``, ``app.db.plugin_tools``), its tool's or an item's.
Which kinds a community has is its tool set's, read at request time, so the
parameter is a string and :func:`require_kind` asks the tool set: a kind the
community does not have is not found.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from app.core.messages import KindMessages
from app.core.tool_set import ToolSet
from app.core.tools import kind_refusal


def installed_kinds(tools: ToolSet, *, items: bool = True) -> frozenset[str]:
    """The kinds ``tools``' installed tool plug-ins bring: each tool's, and,
    with ``items``, each of its items'."""
    return frozenset(
        kind
        for record in tools.installed
        for kind in (
            record.kind,
            *((child.value for child in record.children) if items else ()),
        )
    )


def require_kind(
    tools: ToolSet,
    kind: str,
    builtin: type[Enum] | Iterable[str] = (),
    *,
    items: bool = True,
) -> str:
    """``kind`` where the community with ``tools`` has it for this route: one
    of ``builtin`` (the built-in kinds the route serves), or a kind of an
    installed tool plug-in (with ``items``, an item's too). Anything else is
    not found."""
    values = (
        builtin._value2member_map_
        if isinstance(builtin, type) and issubclass(builtin, Enum)
        else frozenset(builtin)
    )
    if kind in values or kind in installed_kinds(tools, items=items):
        return kind
    raise kind_refusal(kind, KindMessages.NOT_FOUND, 404)
