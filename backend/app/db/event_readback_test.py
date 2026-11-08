"""Every resource the bus can name has to be fetchable by that name.

An event envelope carries ``resource: {type, id}`` and the same pair for each
of that resource's parents — identifiers, no paths and no values. That is what
lets it stay content-free: the subscriber reads the state back through the API,
where the gates decide. It only works if each id is a whole address, so the
route for a resource type is derivable from the type itself:

    resource_type -> /c/{community_id}/<kebab>/{id}

Which is not a convention invented here — it is what the resources that already
worked all do. Sub-resources with an id of their own (``comments``,
``counters``) are flat for exactly this reason; a nested path would demand a
parent the envelope never carries.

Anything that is a facet rather than a resource — a project's statuses, a
file's versions, a task's tags — reports against the parent instead (see
``ReportsAs``), so it needs no route of its own and never reaches this test.
Between the two, a new evented table owes no new API surface.
"""

from __future__ import annotations


import app.db.base  # noqa: F401 — register every model
from app.db.event_capture import build_specs
from app.db.initiative_rls import parent_types
from app.main import app


def _detail_paths() -> set[str]:
    """Guild-scoped detail GETs, as ``<segment>`` for ``/<segment>/{id}``."""
    found: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "GET" not in methods or "/c/{community_id}/" not in path:
            continue
        tail = path.split("/c/{community_id}/", 1)[1]
        parts = tail.split("/")
        # Exactly "<segment>/{param}" — one hop, then the id.
        if (
            len(parts) == 2
            and not parts[0].startswith("{")
            and parts[1].startswith("{")
        ):
            found.add(parts[0])
    return found


def _named_resources() -> set[str]:
    """Every type an event can put an id under — its resource, and its parents.

    A parent is addressed exactly like a resource, so the same rule covers
    both: a chain that names something unfetchable is as broken as a resource
    that does.
    """
    named: set[str] = set()
    for spec in build_specs():
        named |= spec.resource_types
        named |= parent_types(spec.parents_expr)
    return named


def test_every_evented_resource_resolves_by_its_own_id():
    paths = _detail_paths()
    missing = sorted(r for r in _named_resources() if r.replace("_", "-") not in paths)
    assert not missing, (
        f"{missing} emit events naming ids nothing can fetch. Either add "
        f"GET /c/{{guild_id}}/<kebab>/{{id}}, or report the table against a "
        "parent that has one (Emit(reports_as=...))."
    )
