"""What a listing is allowed to publish, per kind.

A listing arriving from anywhere — a shipped data file today, an operator upload
or a signed remote manifest later — carries a definition, and that definition is
stored and later copied into a guild's schema. This module is the one place that
decides whether a body is acceptable, and for a tool's listing it does so by
handing off to *that tool's importer*: a listing is the tool's export envelope,
held to the same checks as importing the same file (``tool_listings``), and a
dashboard's canvas to the same widget validator the guild-scoped API uses.

That reuse is the point: catalog content is held to the same vocabulary as
anything authored or imported in the app, by the same code.

The pieces this file leans on live beside it, because a service plug-in's manifest is
too large a vocabulary to read in one sitting:

* ``manifest_values`` — the bounded primitives every value goes through.
* ``widget_meta`` — the server-side reading of the rules the browser applies to
  a widget's own strings.
* ``service_plugins`` — the ``plugin_kind: "service"`` manifest.

Two rules span all of them. **Attribution is required**: a listing states who
wrote it or it is not published. And **``core.*`` belongs to this repository**:
an id in that namespace is only ever claimed by a listing shipped in this build.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.tools import BULK_EXPORT_TOOLS, Tool
from app.models.platform.publisher import FIRST_PARTY_PUBLISHER_PREFIX, publisher_prefix
from app.services.marketplace.manifest_values import (
    MAX_PUBLISHER_NAME_LENGTH,
    MAX_NAME_LENGTH,
    ListingDefinitionError,
    check_single_line,
    clean_text,
    fail,
)
from app.services.marketplace.home_layouts import normalize_home_layout_definition
from app.services.marketplace.profile_packs import (
    normalize_profile_pack_definition,
)
from app.services.marketplace.service_plugins import (
    plugin_widget_type,
    normalize_service_plugin_definition,
)
from app.services.marketplace.tool_listings import (
    normalize_tool_example,
    normalize_tool_listing,
)

__all__ = [
    "ListingDefinitionError",
    "LISTING_KINDS",
    "TOOL_LISTING_KINDS",
    "LISTING_AUDIENCES",
    "KIND_AUDIENCE",
    "kinds_for_audience",
    "LISTING_SOURCES",
    "LOCAL_SOURCE",
    "PLUGIN_KINDS",
    "GUILD_INSTALLABLE_PLUGIN_KINDS",
    "MOUNTABLE_TOOLS",
    "RESERVED_PUBLIC_ID_PREFIX",
    "published_by_us",
    "plugin_widget_type",
    "normalize_publisher",
    "normalize_listing_definition",
    "normalize_listing_example",
    "reserved_prefix_problem",
]


#: The tool marketplaces: one per tool that exports and imports, keyed by the
#: tool's own value. A listing of one of these kinds is that tool's export
#: envelope, and installing it is that tool's import, so a tool gets a
#: marketplace by having an exporter and an importer, which it needs anyway
#: (``tools_test`` holds the two together).
TOOL_LISTING_KINDS: dict[str, Tool] = {tool.value: tool for tool in BULK_EXPORT_TOOLS}

#: Kinds the catalog can hold: the tool marketplaces, plus the three that are
#: not a tool's content.
#:
#: ``auto`` is declared here so the vocabulary is complete — the marketplace can
#: name and filter by it — while nothing installs one yet: a manifest carrying
#: one is refused with a reason rather than stored as something no code can
#: resolve.
#:
#: ``profile_pack`` and ``home_layout`` install to a *person* rather than a
#: guild — a pack's decorations land in an account's own library, a layout
#: becomes a view on their own home page. The catalog does not need to know:
#: publishing, browsing and versioning are the same for them as for anything
#: else, and only the install path differs.
LISTING_KINDS: frozenset[str] = frozenset(
    {"plugin", "auto", "profile_pack", "home_layout", *TOOL_LISTING_KINDS}
)

#: Who a listing installs to.
#:
#: Most kinds install to a **guild** — a tool's content lands in an
#: initiative, a plug-in mounts in a community. A profile pack and a home
#: layout install to a **user**: they land in one account's own library or home
#: page and belong to that person across every community they are in.
#:
#: The distinction is not cosmetic. It decides which marketplace offers a
#: listing, who is allowed to install it, and what "installed" is even recorded
#: against — so it is declared once, here, beside the kinds themselves.
LISTING_AUDIENCES: frozenset[str] = frozenset({"guild", "user"})

KIND_AUDIENCE: dict[str, str] = {
    "plugin": "guild",
    "auto": "guild",
    "profile_pack": "user",
    "home_layout": "user",
    **{kind: "guild" for kind in TOOL_LISTING_KINDS},
}


def kinds_for_audience(audience: str) -> frozenset[str]:
    """The listing kinds a given marketplace offers."""
    if audience not in LISTING_AUDIENCES:
        raise ValueError(f"unknown listing audience {audience!r}")
    return frozenset(kind for kind, who in KIND_AUDIENCE.items() if who == audience)


#: How a listing reached this deployment. Not a trust ranking shown to a reader
#: — every listing is here because whoever runs this server put it here — but the reason
#: a listing shipped in this build is credited to us rather than to whatever its
#: manifest claims.
#:
#: ``builtin`` shipped in this build. ``operator`` was read from the catalog
#: directory whoever runs the deployment mounts. ``registry`` arrived from a
#: remote index this deployment trusts. ``local`` was added here and nowhere
#: else — shared by a member, or uploaded by the operator — and has no file or
#: index behind it, so no sweep of those sources ever retires it.
LISTING_SOURCES: frozenset[str] = frozenset(
    {"builtin", "local", "operator", "registry"}
)

#: The source a deployment's own additions publish under.
LOCAL_SOURCE = "local"

#: How a plug-in presents itself.
#:
#: ``tool_instance`` mounts one of the plug-in's own tools at guild scope — the plug-in
#: creates an ordinary row in an ordinary table and the existing UI renders it.
#: ``service`` declares features a container the operator runs will
#: serve.
PLUGIN_KINDS: frozenset[str] = frozenset({"tool_instance", "service"})

#: The plug-in kinds the guild install path can mount.
#:
#: All three, now that a ``service`` plug-in has somewhere to land: the deployment's
#: registration supplies the address, the secret and the powers, and the install
#: is the pinned definition plus whatever the guild configures against it. A
#: service plug-in creates no local content, so installing one is the row and
#: nothing else.
#:
#: The set is still separate from :data:`PLUGIN_KINDS` because the two answer
#: different questions — what a listing may *declare* versus what this build can
#: *mount* — and a kind added to the vocabulary ahead of its machinery is
#: refused by name rather than half-mounted.
GUILD_INSTALLABLE_PLUGIN_KINDS: frozenset[str] = frozenset({"tool_instance", "service"})

#: Tools a plug-in may mount at guild scope. A tool qualifies when its content is
#: meaningful without an initiative — a calendar of the guild's own events is,
#: and so is the guild's address book; a dashboard, which binds to one
#: initiative's data, is not (and is not planned to be).
MOUNTABLE_TOOLS: frozenset[str] = frozenset({"calendar", "contact"})

#: The namespace this repository's own listings publish under.
RESERVED_PUBLIC_ID_PREFIX = "core."

#: Sources allowed to claim it.
RESERVED_PREFIX_SOURCES: frozenset[str] = frozenset({"builtin"})


def published_by_us(source: str, public_id: str) -> bool:
    """Whether this project publishes a listing: shipped in this build, or
    from the registry under this project's own publisher prefix, which the
    registry's signature binds to it."""
    return source in RESERVED_PREFIX_SOURCES or (
        source == "registry"
        and publisher_prefix(public_id) == FIRST_PARTY_PUBLISHER_PREFIX
    )


# --- attribution ------------------------------------------------------------


def normalize_publisher(raw: Any) -> str:
    """The name a listing publishes under, required on every ingestion path.

    One name, not a person and a distributor kept apart: whoever publishes is
    who a reader is trusting, whether that is the individual who wrote it or an
    organisation shipping someone else's work. A listing that states none is
    refused rather than published as anonymous.

    What the publisher *claims* is bounded here; the catalog separately records
    how the listing arrived.
    """
    if raw is None:
        fail("publisher is required: a listing states who publishes it")
    name = clean_text(raw, what="publisher", limit=MAX_PUBLISHER_NAME_LENGTH)
    check_single_line(name or "", what="publisher")
    return name or ""


def reserved_prefix_problem(public_id: str, *, source: str) -> Optional[str]:
    """Why this source may not publish under this id, or ``None``.

    ``core.*`` names listings shipped in this repository, so the id itself
    carries the same answer the provenance badge does. Anything arriving from an
    operator upload or a registry publishes under its own publisher prefix.
    """
    if not public_id.startswith(RESERVED_PUBLIC_ID_PREFIX):
        return None
    if source in RESERVED_PREFIX_SOURCES:
        return None
    return (
        f"the {RESERVED_PUBLIC_ID_PREFIX!r} prefix is reserved for listings "
        f"shipped with this build; a {source!r} listing publishes under its "
        "own publisher prefix"
    )


# --- definitions ------------------------------------------------------------


def _normalize_plugin_definition(
    definition: Any, *, public_id: Optional[str]
) -> dict[str, Any]:
    """A plug-in's body: which kind it is, and what that kind needs.

    ``tool_instance`` is deliberately narrow — a kind and one thing, which of
    this build's tools to mount. It carries no code or URL.

    ``service`` is the wide one, and it keeps the same rule (see
    ``service_plugins``): paths, never addresses. Unknown keys are dropped rather
    than stored, so a definition always has canonical shape.
    """
    if not isinstance(definition, dict):
        raise ListingDefinitionError("plug-in definition must be an object")

    plugin_kind = definition.get("plugin_kind")
    if plugin_kind not in PLUGIN_KINDS:
        raise ListingDefinitionError(f"unknown plug-in kind {plugin_kind!r}")

    if plugin_kind == "service":
        return normalize_service_plugin_definition(definition, public_id=public_id)

    cleaned: dict[str, Any] = {"plugin_kind": plugin_kind}
    tool = definition.get("tool")
    if tool not in MOUNTABLE_TOOLS:
        raise ListingDefinitionError(f"{tool!r} cannot be mounted at guild scope")
    cleaned["tool"] = tool

    # A starting name for what the install produces; the guild renames it
    # afterwards like anything else.
    default_name = clean_text(
        definition.get("default_name"),
        what="default_name",
        limit=MAX_NAME_LENGTH,
        required=False,
    )
    if default_name is not None:
        cleaned["default_name"] = default_name
    return cleaned


def normalize_listing_definition(
    kind: str, definition: Any, *, public_id: Optional[str] = None
) -> dict[str, Any]:
    """Validate and canonicalize a listing's definition for its kind.

    A tool's listing is that tool's export envelope, held to the tool's own
    importer (``tool_listings``); the other kinds each have their own shape.
    ``public_id`` is the listing's, which names a declarative plug-in.
    """
    if kind not in LISTING_KINDS:
        raise ListingDefinitionError(f"unknown listing kind {kind!r}")
    if kind == "auto":
        raise ListingDefinitionError(
            "automation listings are not installable in this build yet"
        )
    if kind == "plugin":
        return _normalize_plugin_definition(definition, public_id=public_id)
    if kind == "profile_pack":
        return normalize_profile_pack_definition(definition)
    if kind == "home_layout":
        return normalize_home_layout_definition(definition)
    return normalize_tool_listing(TOOL_LISTING_KINDS[kind], definition)


def normalize_listing_example(
    kind: str, example: Any, definition: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Validate a listing's example, or ``None`` when it has none.

    Only a tool's listing carries one — the same envelope filled in, or for a
    tool made of queries the publisher's own sample data. ``definition`` is the
    listing's normalized definition, which a sample is checked against. Any
    other kind that states one is refused rather than having it silently
    dropped.
    """
    tool = TOOL_LISTING_KINDS.get(kind)
    if tool is None:
        if example is not None:
            raise ListingDefinitionError(f"a {kind} listing carries no example")
        return None
    return normalize_tool_example(tool, example, definition)
