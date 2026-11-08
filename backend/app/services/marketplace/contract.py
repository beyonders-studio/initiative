"""The plug-in contract, as this build reads it.

The vocabulary a plug-in manifest draws on — every enum, cap and character set —
and the shape it takes are declared once, in the ``initiative-plugin-sdk``
repository, in ``manifest.contract.json``. That file is vendored here under
``backend/vendor/plugin-kit`` at a pinned kit version and read at import.

**Why the kit owns it.** A plug-in author writes against the kit: its types, its
offline validator, its published JSON Schema. When the vocabulary lived here and
the kit's types were written by hand beside a schema fetched from this
repository, the two drifted — the kit could not declare a block this build
accepts. One document, generated into both representations, is what removes
that.

**Why this build still pins it.** ``normalize_service_plugin_definition`` is
admission control: it decides what a publisher may install. A deployment
therefore reads a copy it shipped with, never one fetched at run time, and a new
contract reaches it when it next releases. So the direction is asymmetric on
purpose — a kit release reaches plug-in authors immediately and this build at its
next release — and a term the vendored contract declares that this build does
not act on is a failing test (:mod:`contract_coverage_test`), not a value
quietly dropped.

The kit's version is also the plug-in API contract this build serves
(:mod:`app.services.marketplace.plugin_api`).

Refresh the vendored copy with ``python scripts/refresh_plugin_kit.py``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "KIT_REVISION",
    "KIT_VERSION",
    "PLUGIN_API_PATH",
    "SCHEMA_PATH",
    "cap",
    "charset",
    "discarded_terms",
    "enum",
    "fields",
    "int_enum",
    "ladder",
    "manifest_schema",
    "objects",
]

#: Where the vendored kit lives, relative to the backend package root.
_VENDOR = Path(__file__).resolve().parents[3] / "vendor" / "plugin-kit"

#: The JSON Schema the kit generates from the same contract. Not read by the
#: validator — it is what the conformance tests measure this build against.
SCHEMA_PATH = _VENDOR / "plugin-manifest.json"

#: The plug-in API's OpenAPI document as the kit publishes it, at the kit
#: version above. Absent until a kit release that ships it is vendored. Not
#: read at run time: the test that holds this build's plug-in API to it is.
PLUGIN_API_PATH = _VENDOR / "plugin-api.json"


def _read(name: str) -> str:
    return (_VENDOR / name).read_text(encoding="utf-8").strip()


#: Which kit release this build speaks, recorded so a reviewer can see it move.
KIT_VERSION = _read("KIT_VERSION")
KIT_REVISION = _read("KIT_REVISION")


@lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    """The vendored contract, parsed once per process."""
    with (_VENDOR / "manifest.contract.json").open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def manifest_schema() -> dict[str, Any]:
    """The generated JSON Schema, for tests that measure the two against it."""
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def enum(name: str) -> frozenset[str]:
    """One closed vocabulary, as a set.

    A set rather than a sequence because every use here is a membership test.
    Where the order carries meaning — a ladder — use :func:`ladder`.
    """
    values = _contract()["enums"].get(name)
    if values is None:
        raise KeyError(f"the contract declares no enum {name!r}")
    return frozenset(values)


def int_enum(name: str) -> frozenset[int]:
    """A closed vocabulary of numbers rather than strings.

    Separate from :func:`enum` so each keeps a real element type; the protocol
    version is the one numeric vocabulary the contract carries.
    """
    values = _contract()["enums"].get(name)
    if values is None:
        raise KeyError(f"the contract declares no enum {name!r}")
    return frozenset(int(value) for value in values)


def ladder(name: str) -> tuple[str, ...]:
    """An ordered vocabulary: a value names the floor an audience must clear."""
    rungs = _contract()["ladders"].get(name)
    if rungs is None:
        raise KeyError(f"the contract declares no ladder {name!r}")
    return tuple(rungs)


def cap(name: str) -> int:
    """One upper bound, by the name the contract gives it."""
    value = _contract()["caps"].get(name)
    if value is None:
        raise KeyError(f"the contract declares no cap {name!r}")
    return int(value)


def charset(name: str) -> frozenset[str]:
    """The characters a class of id or path may use.

    A set, not a pattern: the checks in :mod:`manifest_values` are explicit
    membership tests, and the contract carries the characters themselves so the
    schema's pattern and this set cannot describe different things.
    """
    value = _contract()["charsets"].get(name)
    if value is None:
        raise KeyError(f"the contract declares no character set {name!r}")
    return frozenset(value)


def objects() -> dict[str, Any]:
    """Every object the contract defines, including the manifest itself."""
    contract = _contract()
    return {**contract["defs"], "manifest": contract["manifest"]}


def fields(owner: str) -> tuple[str, ...]:
    """Every field the contract declares on one object, in declaration order.

    The inventory the normalizer is held to. A field here that nothing reads is
    a restriction an author asked for and this build would silently discard.
    """
    node = objects().get(owner)
    if node is None:
        raise KeyError(f"the contract declares no object {owner!r}")
    return tuple(node.get("properties", {}))


def _shape(node: Any) -> dict[str, Any] | None:
    """The object a contract node describes, following a ``ref`` to its def."""
    if not isinstance(node, dict):
        return None
    if "ref" in node:
        return _contract()["defs"].get(node["ref"])
    return node


def _undeclared(value: Any, node: Any) -> list[str]:
    """Keys in ``value`` that ``node`` does not describe, depth first.

    Walks the contract's own structure rather than a second list of where
    things nest: a node either names a ``ref``, carries ``items``, or carries
    ``properties``, and each is followed the same way at every depth. An object
    the contract leaves open — ``additionalProperties`` for a binding's
    parameters — or opaque — a widget's ``meta`` — declares no properties, and
    nothing inside it is anyone's to name.
    """
    shape = _shape(node)
    if shape is None:
        return []

    if "items" in shape:
        if not isinstance(value, list):
            return []
        found: list[str] = []
        for index, item in enumerate(value):
            found += [f"{index}.{term}" for term in _undeclared(item, shape["items"])]
        return found

    properties = shape.get("properties")
    if properties is None or not isinstance(value, dict):
        return []

    found = []
    for key, child in value.items():
        if key not in properties:
            found.append(key)
            continue
        found += [f"{key}.{term}" for term in _undeclared(child, properties[key])]
    return found


def discarded_terms(definition: Any) -> list[str]:
    """Every key in a served definition that this build's contract does not name.

    A deployment reads the contract it shipped with, so a plug-in written against a
    newer one can send terms this build has no meaning for. They are dropped
    rather than refused — that is what lets a plug-in target a newer platform and
    still install on an older one — which leaves the author with nothing to see.
    This is what the registrar reports back so the skew is visible at
    verification instead of never.

    Paths are dotted and indexed (``endpoints.0.rate_limit``,
    ``dashboards.0.widgets.0.binding.timeout``) so a report names the exact
    term rather than the object it sat on.
    """
    return sorted(_undeclared(definition, _contract()["manifest"]))
