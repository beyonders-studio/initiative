"""The endpoint the router will run for a request, resolved once.

Middleware that acts per route — the body bound, the default rate limit — asks
here rather than matching paths of its own. The answer is kept on the scope,
so a request is resolved once however many layers ask.
"""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any

from fastapi.routing import _IncludedRouter
from starlette.routing import BaseRoute, Match

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
    resolved = _first_match(getattr(scope.get("app"), "routes", ()), scope)
    scope[_RESOLVED] = resolved
    return resolved


def _first_match(routes: Iterable[BaseRoute], scope: MutableMapping[str, Any]):
    for route in routes:
        if isinstance(route, _IncludedRouter):
            # FastAPI keeps an included router whole rather than copying its
            # routes up, and only it knows which of them answers under its
            # prefix: a route of its own (with the prefixed context), or a
            # router included in it.
            match, _, inner, context = route._match(scope)
            if match != Match.FULL:
                continue
            if context is None:
                return _first_match((inner,), scope) if inner is not None else None
            return MOUNTED if context.endpoint is None else context.endpoint
        match, _ = route.matches(scope)
        if match == Match.FULL:
            endpoint = getattr(route, "endpoint", None)
            return MOUNTED if endpoint is None else endpoint
    return None
