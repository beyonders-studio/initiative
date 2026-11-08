"""A read, trimmed for a model to read.

A model pays for every field it is given, and the app's reads are shaped for
the app. The MCP server trims every tool result with :func:`trim`, and the AI
features trim the reads they put in a prompt the same way, so both send one
shape.

What is left out:

* an absent value — a ``null``, an empty list, an empty object. Most of a
  task row's fields are unset most of the time; leaving the key out says the
  same thing.
* pictures — any ``*_base64`` data URI (a single avatar is often larger than
  the rest of a task read combined) and any ``avatar_url``. Neither is
  anything a model can open or act on.
* a property's option list after the first row that carried it. A task list
  repeats each property's whole definition — every option, label and colour —
  on every row, which was nearly a quarter of a page of tasks. The first row
  keeps it, so the model still learns what the property accepts. A repeat is
  the same id *and* the same options: ids are numbered per community, and a
  cross-community list can hold two properties that share one.

Colours, icons and positions stay: the MCP write tools set them, so a model
can be asked about them.

A free-form field — a file's content, a dashboard's config, a property's
value — passes through verbatim: what is inside it is the document's own, and
a ``null`` there can mean something. The caller names which fields those are.
"""

from __future__ import annotations

import json
from typing import Any

_BASE64_SUFFIX = "_base64"
_UNREAD_KEYS = frozenset({"avatar_url"})


def _is_absent(value: Any) -> bool:
    return value is None or value == [] or value == {}


def trim(
    value: Any,
    free_form: frozenset[str] = frozenset(),
    seen_properties: set[Any] | None = None,
) -> Any:
    """Return ``value`` without the fields a model never acts on.

    Returns a new structure; the input is left untouched. ``free_form`` names
    the keys whose values pass through as they are; ``seen_properties`` carries
    the (property id, options) pairs a row earlier in the same result has
    already shown.
    """
    if seen_properties is None:
        seen_properties = set()
    if isinstance(value, list):
        return [trim(v, free_form, seen_properties) for v in value]
    if not isinstance(value, dict):
        return value

    trimmed: dict[str, Any] = {}
    repeats_options = False
    if "options" in value and value.get("property_id") is not None:
        shown = (value["property_id"], json.dumps(value["options"], sort_keys=True))
        repeats_options = shown in seen_properties
        seen_properties.add(shown)
    for key, v in value.items():
        if key in _UNREAD_KEYS or key.endswith(_BASE64_SUFFIX):
            continue
        if key == "options" and repeats_options:
            continue
        if key not in free_form:
            v = trim(v, free_form, seen_properties)
        if not _is_absent(v):
            trimmed[key] = v
    return trimmed
