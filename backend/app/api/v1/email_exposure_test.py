"""Which response shapes may carry an address, and which may not.

Two shapes carry a stored address in full: ``UserRead`` on the ``/me``
routes, and ``UserEmailRead`` on the routes listing the addresses an account
holds. Both are served only to the address's owner. Every other route that
returns an account returns ``OperatorUserRead``, which masks it, and the shapes
that carry an address field alongside other data — the guild invite, the
access grant — mask it too. A deployment's contact address is not an account's
and is served in full wherever it is shown.

These tests read the OpenAPI schema and hold the app to that split, so a new
route or a new shape has to be a deliberate addition to the lists below rather
than something nobody noticed.
"""

import json
from collections.abc import Iterable
from typing import Any

from app.main import app

#: Shapes that carry a stored address in full, each mapped to the routes that
#: serve it — every one of them returning the caller their own account.
SELF_SHAPES = {
    "UserRead": {
        "/api/v1/auth/register",
        "/api/v1/me",
        "/api/v1/me/username",
        "/api/v1/me/age-confirmation",
        "/api/v1/me/avatar",
        "/api/v1/me/legal-acceptance",
    },
    "UserEmailRead": {
        "/api/v1/me/emails",
        "/api/v1/me/emails/{address_id}/primary",
    },
}

#: Shapes that carry an address field and mask it. Each has a validator
#: applying ``app.core.email_masking.mask_email``; adding a name here means
#: having added that validator.
MASKED_SHAPES = {
    "OperatorUserRead",
    "AccessGrantRead",
    "CommunityInviteRead",
    # A new invite with its code; it masks as CommunityInviteRead, which it is.
    "CommunityInviteCreated",
}

#: Shapes that carry a deployment's contact address: one an operator published
#: so people can write to it, not an account's stored address. It is served in
#: full, because a masked contact cannot be written to.
CONTACT_SHAPES = {"AccountTimeOutRead", "CommunityRead", "IntakeSettingsRead"}


def _operations() -> Iterable[tuple[str, str, dict]]:
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if isinstance(operation, dict):
                yield path, method, operation


def _referenced_names(node: Any) -> Iterable[str]:
    """Every ``#/components/schemas/<name>`` appearing anywhere under ``node``."""
    text = json.dumps(node)
    prefix = '"#/components/schemas/'
    start = 0
    while (found := text.find(prefix, start)) != -1:
        end = text.find('"', found + len(prefix))
        yield text[found + len(prefix) : end]
        start = end


def _reachable(node: Any, schemas: dict[str, Any]) -> set[str]:
    """Schemas reachable from ``node``, following references transitively.

    A response usually names one shape, but that shape can hold others — a
    paged envelope whose ``items`` are accounts names only the envelope at the
    top level. Walking the whole graph is what makes the two tests below cover
    those as well as the direct case.
    """
    seen: set[str] = set()
    queue = list(_referenced_names(node))
    while queue:
        name = queue.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        queue.extend(_referenced_names(schemas[name]))
    return seen


def _is_address(node: Any) -> bool:
    """Whether a property holds an address rather than merely being named for
    one.

    An address is text. A field called ``email`` that carries a shape — the
    account's mail schedule, say — or a flag is something else entirely, and
    the name alone cannot tell them apart.
    """
    branches = [
        node,
        *(node.get("anyOf") or node.get("oneOf") or node.get("allOf") or ()),
    ]
    return any(branch.get("type") == "string" for branch in branches)


def test_a_shape_is_not_an_address() -> None:
    """The narrowing above is what keeps the sweep on addresses.

    A field named for one but holding a shape, or a flag, is not an address;
    text is, however it is wrapped.
    """
    assert _is_address({"type": "string"})
    assert _is_address({"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert not _is_address({"$ref": "#/components/schemas/EmailSchedule"})
    assert not _is_address({"type": "boolean"})


def test_the_walk_reaches_a_nested_shape() -> None:
    """The reachability walk is what the two tests below rest on.

    Without this, a walk that silently found nothing would make both of them
    pass by vacuum rather than by being satisfied.
    """
    schemas = {
        "Envelope": {"properties": {"items": {"$ref": "#/components/schemas/Inner"}}},
        "Inner": {"properties": {"email": {"type": "string"}}},
    }
    node = {"200": {"schema": {"$ref": "#/components/schemas/Envelope"}}}
    assert _reachable(node, schemas) == {"Envelope", "Inner"}


def test_the_unmasked_shapes_are_served_only_on_their_own_routes() -> None:
    """An unmasked shape reaches a response only where the caller owns it.

    A route serving somebody else's account uses ``OperatorUserRead`` instead; one
    that genuinely belongs on a list is added to it explicitly.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    leaked = {
        (name, path)
        for path, _method, operation in _operations()
        for name, own_routes in SELF_SHAPES.items()
        if name in _reachable(operation.get("responses") or {}, schemas)
        and path not in own_routes
    }
    assert not leaked, (
        f"{sorted(leaked)} — these routes return a shape carrying the stored "
        "address. Serve somebody else's account as OperatorUserRead."
    )


def test_every_other_address_field_comes_from_a_masking_shape() -> None:
    """Any other address-shaped response field belongs to a shape that masks.

    Covers what the route check cannot: a new shape with an ``…_email`` field,
    reached directly or nested inside another. A field is judged by what it
    holds, so one named for an address without being one does not count.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    returned: set[str] = set()
    for _path, _method, operation in _operations():
        returned |= _reachable(operation.get("responses") or {}, schemas)

    carrying = {
        name
        for name in returned
        for field, node in (schemas[name].get("properties") or {}).items()
        if "email" in field.lower() and _is_address(node)
    }

    unaccounted = carrying - MASKED_SHAPES - CONTACT_SHAPES - set(SELF_SHAPES)
    assert not unaccounted, (
        f"{sorted(unaccounted)} carry an address field in a response without "
        "masking it."
    )
