"""The endpoint the router will run for a request, resolved once.

Middleware that acts per route — the body bound, the default rate limit — asks
here rather than matching paths of its own. The answer is kept on the scope,
so a request is resolved once however many layers ask.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from starlette.routing import Match

#: Stands in for a request that lands on a mounted sub-app. A mount has no
#: endpoint to read a marker off, which is a different answer from "no route
#: matched".
MOUNTED = object()

_RESOLVED = "initiative.route_endpoint"


def route_endpoint(scope: MutableMapping[str, Any]) -> object | None:
    """The endpoint the router will run for this request, :data:`MOUNTED`
    for a mounted sub-app, or ``None`` when no route fully matches.

    Starlette dispatches to the FIRST route that fully matches, so this stops
    there rather than reading on.
    """
    if _RESOLVED in scope:
        return scope[_RESOLVED]
    resolved: object | None = None
    for route in getattr(scope.get("app"), "routes", ()):
        match, _ = route.matches(scope)
        if match == Match.FULL:
            endpoint = getattr(route, "endpoint", None)
            resolved = MOUNTED if endpoint is None else endpoint
            break
    scope[_RESOLVED] = resolved
    return resolved
