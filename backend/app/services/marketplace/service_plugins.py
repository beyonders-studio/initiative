"""Service plug-ins: what a manifest may declare, and nothing else.

A ``service`` plug-in is a container the operator runs, or declarative: one with no
``service`` block, whose calls Initiative makes itself from requests and JSONata
expressions in the manifest. One plug-in is never both. Its definition is the
widest thing this build accepts from a publisher, so it is also the strictest:
a closed vocabulary, an explicit cap on every string, list and opaque body, and
unknown keys dropped rather than stored (an endpoint's and a part's nodes are
refused).

Three properties hold by construction, and they are why a definition is safe to
keep and later hand to a guild:

* **It names capabilities, not its own address.** Every route a container
  offers is a *path*; the base URL comes from a deployment-level registration.
  The hosts a declarative plug-in names are its vendor's, which every request it
  renders is held to.
* **No code in it runs here.** ``module_source`` is a widget's browser-side
  module: it is measured and stored as an opaque string, and this build has no
  path that parses, compiles, imports, or evaluates it. The browser's sandbox is
  the only thing that ever executes it. A declarative plug-in's expressions are
  standard JSONata, evaluated with bounds in worker processes
  (:mod:`app.services.marketplace.expressions`).
* **Blocks this build assigns no meaning to stay opaque.** The ``automation``
  body belongs to the automation service; it is checked for shape and size and
  passed through verbatim, with no vocabulary here describing its contents.

Features are the plug-in's own statement of what it contributes, and they are
cross-checked against the blocks present in both directions so the statement
cannot drift from the manifest. They inform install dialogs, deployment-fit
messaging, and review — they never gate installation. A plug-in may declare no
local features at all: an integration that exists to give an external system a
foothold in a guild is a legitimate install with nothing to render.
"""

from __future__ import annotations

import re
import string
from typing import Any, Mapping, Optional

from app.core.currencies import CURRENCY_CODES
from app.core.plugin_scopes import ALL_SCOPES, plugin_scope_target
from app.services.marketplace import contract, expressions, plugin_api
from app.services.marketplace.manifest_values import (
    MAX_HINT_LENGTH,
    MAX_IDENTIFIER_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PATH_LENGTH,
    check_identifier,
    check_json_size,
    check_metadata_key,
    check_path,
    check_public_id,
    check_single_line,
    check_uid,
    check_url,
    clean_text,
    fail,
    require_list,
    require_mapping,
    utf8_bytes,
)
from app.services.marketplace.widget_meta import (
    MAX_TEXT_LENGTH,
    localized_text,
    validate_widget_meta,
)
from app.services.tenant.plugin_config import RESERVED_TOKEN_KEYS

__all__ = [
    "ACTOR_KINDS",
    "PLUGIN_PROTOCOL_VERSIONS",
    "PLUGIN_WIDGET_TYPE_PREFIX",
    "WIDGET_BINDABLE_DIRECTIONS",
    "CONNECTION_SCOPES",
    "DIRECTIONS",
    "PAGE_CAPABILITIES",
    "FEATURES",
    "FEATURE_BLOCKS",
    "FIELD_KINDS",
    "FIELD_TYPES",
    "ITEM_KINDS",
    "PARAM_TYPES",
    "PART_NODES",
    "SURFACE_SCOPES",
    "TONES",
    "plugin_widget_type",
    "is_admin_only",
    "normalize_service_plugin_definition",
    "schedule_minutes",
]

# --- vocabulary -------------------------------------------------------------

#: Capability classes a plug-in can contribute. Closed: a manifest naming anything
#: else is refused rather than stored as a claim nothing can act on.
FEATURES: frozenset[str] = contract.enum("feature")

#: Which block backs each feature. The single source for the cross-check that
#: keeps a declaration and a manifest body from disagreeing.
#:
#: Derived rather than restated: a feature and its block share a name, so a
#: second list could only ever be missing one — and was, until a feature was
#: added to one of them.
FEATURE_BLOCKS: dict[str, str] = {feature: feature for feature in sorted(FEATURES)}

#: Whose credential a connection holds — not how it is obtained.
#:
#: ``static`` — one credential the whole guild uses.
#: ``interactive`` — each member's own account at a vendor that authorizes
#: people, and never anybody else's.
#:
#: A ``flow`` is the second question, asked of either: with one, Initiative
#: runs the vendor's OAuth flow, and the scope decides who is sent — every
#: member for their own account, or a guild admin once, for the guild. Without
#: one, a static connection is a form an admin types into. Some vendors leave
#: no choice: an organization-wide install is a page at the vendor with a
#: button on it, and no string an admin retypes here is the same thing.
CONNECTION_SCOPES: frozenset[str] = contract.enum("connectionScope")

#: What a vendor field may hold, what a flow is, how a token is minted, how a
#: grant is ended, and what a minted token's JWT is signed with.
VENDOR_FIELD_TYPES: frozenset[str] = contract.enum("vendorFieldType")
FLOW_TYPES: frozenset[str] = contract.enum("flowType")
TOKEN_TYPES: frozenset[str] = contract.enum("tokenType")
REVOKE_METHODS: frozenset[str] = contract.enum("revokeMethod")
JWT_ALGORITHMS: frozenset[str] = contract.enum("jwtAlgorithm")

#: A vendor's own setup flow (``vendor.setup``): the flows this build runs, a
#: GitHub App's permission levels, and the values GitHub answers a manifest
#: conversion with. The three secret ones are written only to a secret field.
GITHUB_APP_MANIFEST: str = contract.objects()["githubAppManifestSetup"]["properties"][
    "kind"
]["const"]
GITHUB_PERMISSION_LEVELS: frozenset[str] = contract.enum("githubPermissionLevel")
GITHUB_APP_VALUES: frozenset[str] = contract.enum("githubAppValue")
GITHUB_SECRET_VALUES: frozenset[str] = frozenset(
    {"client_secret", "pem", "webhook_secret"}
)

#: How a vendor webhook's signature is checked, and the characters a header
#: name and a body path are written in.
WEBHOOK_SCHEMES: frozenset[str] = contract.enum("webhookScheme")
WEBHOOK_ENCODINGS: frozenset[str] = contract.enum("webhookEncoding")
HEADER_NAME_CHARS = contract.charset("headerName")
FIELD_PATH_CHARS = contract.charset("fieldPath")

#: Field kinds a connection form can render. The same closed enum the automation
#: service's node contract settled on, so one generic form renderer draws every
#: plug-in's settings page.
FIELD_TYPES: frozenset[str] = contract.enum("fieldType")

#: What a data source may take as a query parameter. ``secret`` is absent: a
#: parameter travels with a request, and credentials are supplied once, held in
#: custody, and never restated per call.
PARAM_TYPES: frozenset[str] = contract.enum("paramType")

#: Where a surface renders. Not a choice between the two: a surface may declare
#: either, or both, and one that declares both gets a community-wide entry *and* an
#: entry inside each initiative — the same page, told which initiative it was
#: opened in. Closed, and defaulting to ``["community"]``, so a plug-in that says
#: nothing keeps the placement it already had.
SURFACE_SCOPES: frozenset[str] = contract.enum("surfaceScope")

#: How many ``plugins:<public_id>`` scopes a service may ask for beside the fixed
#: ones: one per plug-in it calls through Initiative.
MAX_PLUGIN_SCOPES = contract.cap("pluginScopes")

#: A term an earlier contract used to say who opens a surface or reads an
#: endpoint. Who opens a surface is now the community's to choose, per
#: initiative and role. A manifest still naming it is refused with a reason,
#: unlike other unknown terms, so its author moves to what replaced it rather
#: than finding the term quietly gone.
RETIRED_AUDIENCE_TERM = "visibility"


def is_admin_only(declared: Any) -> bool:
    """Whether a stored surface or endpoint is for the community's admins alone.

    Read off a *pinned* definition, which may predate ``admin_only``: one
    normalized under the earlier contract says ``visibility: "guild_admin"``
    instead, and it means the same thing until the install moves to a version
    published under this one.
    """
    if not isinstance(declared, dict):
        return False
    if declared.get("admin_only") is True:
        return True
    return declared.get(RETIRED_AUDIENCE_TERM) == "guild_admin"


#: Browser features a page may ask its frame for.
#:
#: A frame is granted nothing it did not name here, so a plug-in that says nothing
#: gets a frame with every one of these denied. The vocabulary is closed for the
#: same reason every other one in this module is: a value outside it is refused
#: with a reason rather than stored as a request nothing resolves.
#:
#: These are Permissions-Policy feature names, and what a manifest asks for is
#: what a guild admin is shown at install. ``payment`` is deliberately not
#: namable — a page takes no money, and the platform processes
#: payments on its own screens.
PAGE_CAPABILITIES: frozenset[str] = contract.enum("pageCapability")

#: No page has a use for the whole vocabulary at once; a manifest reaching
#: this many is describing something other than a page.
MAX_PAGE_CAPABILITIES = contract.cap("pageCapabilities")

#: Protocol versions this build speaks to a plug-in service. A manifest naming a
#: newer one is refused by name — the version floor (`min_app_version`) is how a
#: publisher says "this needs a newer Initiative".
PLUGIN_PROTOCOL_VERSIONS: frozenset[int] = contract.int_enum("protocol")

#: Widget type ids from a plug-in are namespaced, so a plug-in's widget can never
#: resolve to a built-in renderer (or the other way round). ``:`` is outside the
#: identifier character set, so the three parts stay separable.
PLUGIN_WIDGET_TYPE_PREFIX = "plugin:"

#: Every endpoint a plug-in declares is namespaced under its own service id.
ENDPOINT_ID_PREFIX = "plugin."
ENDPOINT_ID_CHARS = contract.charset("namespacedId")

#: Which way a call across an endpoint travels.
#:
#: ``read`` and ``write`` are both request/response and differ only in whether
#: the caller expects the plug-in to change something at its vendor — which decides
#: whether an answer may be cached. ``emit`` is the other direction: a
#: subscriber registers a URL and the plug-in posts to it, so there is nothing to
#: call and nothing to cache.
#:
#: An endpoint belongs to no particular consumer. A widget reads one, an
#: automation reads or calls the same one, and a subscriber waits on a third —
#: they are peers, and the direction describes the endpoint rather than who is
#: allowed to want it.
DIRECTIONS: frozenset[str] = contract.enum("direction")

#: Which of those a **widget** may bind — a rule about the tile, not about the
#: endpoint. A widget draws what it is given, so it can only bind one that
#: answers; nothing constrains an automation the same way.
WIDGET_BINDABLE_DIRECTIONS: frozenset[str] = frozenset({"read"})

#: Whose credential an endpoint runs on. The plug-in resolves it; this is the
#: vocabulary it states its preference in, best first.
ACTOR_KINDS: frozenset[str] = contract.enum("actorKind")

#: What an endpoint may say it hands BACK — the param vocabulary minus
#: ``select``, because a select is a *control* and the value behind one is a
#: string. Nothing here is a credential for the same reason a param is not.
#:
#: A caller reads these to know what it can do with an answer before it has
#: one: the automation service offers them as values a later step may bind, and
#: it has to be able to refuse a bad binding when somebody SAVES rather than
#: when the thing eventually runs.
RETURN_TYPES: frozenset[str] = contract.enum("returnValueType")

#: A declarative plug-in's requests: the methods, how paging ends, what an error
#: rule matches, the states a connection is in, and the codes Initiative itself
#: answers ``unavailable`` with. ``transient`` is an error rule's word for a
#: passing failure, which is answered as one to retry.
HTTP_METHODS: frozenset[str] = contract.enum("httpMethod")
PAGE_LIMITS: frozenset[str] = contract.enum("pageLimit")
STATUS_RANGES: frozenset[str] = contract.enum("statusRange")
CONNECTION_STATES: frozenset[str] = contract.enum("connectionState")
PLATFORM_CODES: frozenset[str] = contract.enum("platformCode")
TRANSIENT_CODE = "transient"
PAGING_KINDS: frozenset[str] = frozenset(
    contract.objects()[name]["properties"]["kind"]["const"]
    for name in ("pageNumberPaging", "linkHeaderPaging", "cursorPaging")
)
QUERY_NAME_CHARS = contract.charset("queryName")
HOST_LABEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
GRAPHQL_NAME_CHARS = frozenset(
    "_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
#: The header and prefix a credential is sent with when ``auth`` says nothing.
DEFAULT_AUTH_HEADER: str = contract.objects()["vendorAuth"]["properties"]["header"][
    "default"
]
DEFAULT_AUTH_PREFIX: str = contract.objects()["vendorAuth"]["properties"]["prefix"][
    "default"
]
#: Every term an endpoint may carry. The contract closes the object, so a
#: misspelt term is refused rather than dropped.
ENDPOINT_TERMS: frozenset[str] = frozenset(contract.fields("endpoint"))
#: The endpoint terms that make it declarative.
DECLARATIVE_ENDPOINT_TERMS = ("request", "steps", "map", "errors")

#: What a plug-in adds to items: the item kinds a field, part or action is
#: offered on, what a field's value is and so how it is drawn, and the tones a
#: badge or a part's text may take.
ITEM_KINDS: frozenset[str] = contract.enum("itemKind")
FIELD_KINDS: frozenset[str] = contract.enum("fieldKind")
TONES: frozenset[str] = contract.enum("tone")


def _node_props(name: str) -> dict[str, Any]:
    return contract.objects()[name]["properties"]["props"]["properties"]


#: The components a part is built from, by the ``type`` each node names, and
#: the contract object that describes it.
PART_NODES: dict[str, str] = {
    contract.objects()[entry["ref"]]["properties"]["type"]["const"]: entry["ref"]
    for entry in contract.objects()["partNode"]["oneOf"]
}
#: Every term a node may carry, and every prop. The contract closes both, so
#: a misspelt term is refused rather than dropped.
PART_NODE_TERMS: dict[str, frozenset[str]] = {
    node_type: frozenset(contract.fields(name))
    for node_type, name in PART_NODES.items()
}
PART_NODE_PROPS: dict[str, frozenset[str]] = {
    node_type: frozenset(_node_props(name)) for node_type, name in PART_NODES.items()
}
#: The nodes that hold others.
PART_CONTAINERS: frozenset[str] = frozenset(
    node_type for node_type, terms in PART_NODE_TERMS.items() if "children" in terms
)
STACK_DIRECTIONS: frozenset[str] = frozenset(
    _node_props(PART_NODES["stack"])["direction"]["enum"]
)
STACK_GAPS: frozenset[str] = frozenset(_node_props(PART_NODES["stack"])["gap"]["enum"])
BUTTON_VARIANTS: frozenset[str] = frozenset(
    _node_props(PART_NODES["button"])["variant"]["enum"]
)

# --- caps -------------------------------------------------------------------
#
# Counts first, then bodies. Together they bound what one published version can
# weigh: the per-item caps bound a single widget or blob, and the whole-document
# cap bounds the sum, so no combination of legal parts adds up to an illegal
# document.

MAX_CONNECTIONS = contract.cap("connections")
MAX_FIELDS_PER_CONNECTION = contract.cap("fieldsPerConnection")
MAX_VENDOR_FIELDS = contract.cap("vendorFields")
MAX_GITHUB_APP_PERMISSIONS = contract.cap("githubAppPermissions")
MAX_GITHUB_APP_EVENTS = contract.cap("githubAppEvents")
MAX_FLOW_SCOPES = contract.cap("flowScopes")
MAX_AUTHORIZE_PARAMS = contract.cap("authorizeParams")
MAX_TOKEN_LIFETIME_SECONDS = contract.cap("tokenLifetimeSeconds")
MAX_TEMPLATE_LENGTH = contract.cap("urlLength")
MAX_SELECT_OPTIONS = contract.cap("selectOptions")
MAX_ACCESS_HINT_SCOPES = contract.cap("accessHintScopes")
#: How many schedules a plug-in may declare, and the bounds of each interval.
MAX_SCHEDULES = contract.cap("schedules")
SCHEDULE_MIN_MINUTES = contract.cap("scheduleMinMinutes")
SCHEDULE_MAX_MINUTES = contract.cap("scheduleMaxMinutes")
MAX_SCHEDULE_EVERY_LENGTH = contract.cap("scheduleEveryLength")
MAX_REQUIRES_TERMS = contract.cap("requiresTerms")
MAX_WIDGETS = contract.cap("widgets")
MAX_WIDGET_ENDPOINTS = contract.cap("widgetEndpoints")
#: Reads, writes and emissions share one list, so this bounds all three
#: together rather than each separately.
MAX_ENDPOINTS = contract.cap("endpoints")
MAX_PARAMS_PER_ENDPOINT = contract.cap("paramsPerEndpoint")
#: What one endpoint may name as coming back. Higher than the param cap on
#: purpose: describing an answer is cheaper than asking for one, and a plug-in
#: that returns a dozen fields is ordinary where one taking a dozen is not.
MAX_RETURNS_PER_ENDPOINT = contract.cap("returnsPerEndpoint")
MAX_PAGES = contract.cap("pages")
MAX_FIELDS = contract.cap("fields")
MAX_PARTS = contract.cap("parts")
MAX_ACTIONS = contract.cap("actions")
#: How many facets a field's states may have, and how many keys each.
MAX_FACETS = contract.cap("facetsPerField")
MAX_FACET_VALUES = contract.cap("valuesPerFacet")
#: How large one part's tree may be: its nodes, and how deep they nest.
MAX_PART_NODES = contract.cap("partNodes")
MAX_PART_DEPTH = contract.cap("partDepth")
#: How many settings a plug-in may declare, what each holds and how its value
#: is given, and how long its help may be in each language.
MAX_SETTINGS = contract.cap("settings")
SETTING_TYPES: frozenset[str] = contract.enum("settingType")
SETTING_ASSIGNMENTS: frozenset[str] = contract.enum("settingAssignment")
MAX_HELP_LENGTH = contract.cap("helpLength")
#: How many countries a minimum age may name, and the oldest it may ask for.
MAX_MINIMUM_AGE_REGIONS = contract.cap("minimumAgeRegions")
MAX_MINIMUM_AGE_YEARS = contract.cap("minimumAgeYears")
#: The youngest a minimum age may be: the youngest age of digital consent any
#: regime sets. The contract's lower bound, which it states literally.
MIN_MINIMUM_AGE_YEARS = 13
#: A plug-in ships a handful of arrangements of its own widgets, not a library of
#: them. Each becomes a catalog row, so this is also how many listings a single
#: publish can create.
MAX_BUNDLED_DASHBOARDS = contract.cap("bundledDashboards")
#: The dashboard tool's own limits, restated rather than imported: this is the
#: manifest vocabulary, and the tool validates the derived definition again on
#: its own terms when an instance is created from it.
MAX_DASHBOARD_WIDGETS = contract.cap("dashboardWidgets")
MAX_DASHBOARD_GRID_COLUMNS = contract.cap("dashboardGridColumns")
MAX_DASHBOARD_BINDING_PARAMS = contract.cap("dashboardBindingParams")
#: How many values one binding parameter may fix, where the endpoint declared
#: it takes several.
MAX_BINDING_PARAM_VALUES = 64
#: One line under a bundled dashboard's name. Matches the catalog column it
#: becomes, so a description that publishes here fits the row it derives.
MAX_DESCRIPTION_LENGTH = contract.cap("descriptionLength")
#: A fixed parameter value on a tile's binding.
MAX_PARAM_VALUE_LENGTH = contract.cap("paramValueLength")
MAX_ENDPOINT_ID_LENGTH = contract.cap("endpointIdLength")
#: A day. A read that wants a longer memory than that is asking for a stale
#: dashboard rather than a cheaper one.
MAX_CACHE_TTL_SECONDS = contract.cap("cacheTtlSeconds")
#: Returns that may be joined into one address. An address, not a record.
MAX_IDENTITY_KEY_PARTS = contract.cap("identityKeyParts")
#: A declarative plug-in's requests.
MAX_HOSTS = contract.cap("hosts")
MAX_HOST_LENGTH = contract.cap("hostLength")
MAX_STEPS = contract.cap("steps")
MAX_PAGES_READ = contract.cap("maxPages")
MAX_PER_PAGE = contract.cap("perPage")
MAX_REQUEST_QUERY = contract.cap("requestQuery")
MAX_REQUEST_HEADERS = contract.cap("requestHeaders")
MAX_ERROR_RULES = contract.cap("errorRules")
MAX_UNAVAILABLE_CODES = contract.cap("unavailableCodes")
MAX_WEBHOOK_EVENTS = contract.cap("webhookEvents")
MAX_WEBHOOK_STATUSES = contract.cap("webhookStatuses")
MAX_HEALTH_STATES = contract.cap("healthStates")
MAX_STATUS = contract.cap("statusCode")
MAX_EXPRESSION_LENGTH = contract.cap("expressionLength")
MAX_GRAPHQL_LENGTH = contract.cap("graphqlLength")

#: A widget's browser-side module. Never parsed here — only measured.
MAX_MODULE_SOURCE_BYTES = contract.cap("moduleSourceBytes")
#: Rows powering a preview with no network call.
MAX_SAMPLE_DATA_BYTES = contract.cap("sampleDataBytes")
#: The canonical definition, after normalization. Checked last, so a publisher
#: is told the document is too large rather than which cap they happened to hit
#: first.
MAX_SERVICE_DEFINITION_BYTES = contract.cap("serviceDefinitionBytes")


# --- shared pieces ----------------------------------------------------------


def _label(raw: Any, *, what: str, max_length: int = MAX_TEXT_LENGTH) -> dict[str, str]:
    """A localized label, read by the same rules a widget's own strings are.

    One rule for every human-readable string a plug-in supplies, so a plug-in names
    its connections in as many languages as it names its widgets.
    """
    label = localized_text(raw, max_length)
    if label is None:
        fail(f"{what} must carry a label with at least one language")
    return label


def _requires(
    raw: Any, *, connection_ids: set[str], what: str
) -> dict[str, Any] | None:
    """Which connections satisfy an item.

    One level, one operator: ``all_of`` or ``any_of`` over connection ids, or
    absent for "always available". Satisfaction is later evaluated from the
    presence of values alone — this build never inspects a credential — so the
    only thing checkable here is that every id names a connection the manifest
    actually declares.
    """
    if raw is None:
        return None
    requires = require_mapping(raw, f"{what} requires")
    named = [key for key in ("all_of", "any_of") if key in requires]
    if len(named) != 1:
        fail(f"{what}: requires must name exactly one of 'all_of' or 'any_of'")
    key = named[0]
    terms = require_list(requires[key], f"{what} requires.{key}", MAX_REQUIRES_TERMS)
    cleaned: list[str] = []
    for term in terms:
        connection_id = check_identifier(term, what=f"{what} requires.{key} entry")
        if connection_id not in connection_ids:
            fail(f"{what}: requires names unknown connection {connection_id!r}")
        if connection_id not in cleaned:
            cleaned.append(connection_id)
    if not cleaned:
        fail(f"{what}: requires.{key} names no connection")
    return {key: cleaned}


def _admin_only(raw: dict[str, Any], *, what: str) -> bool:
    """``admin_only``, defaulting to false; absent and null read the same."""
    value = raw.get("admin_only")
    if value is None:
        return False
    if not isinstance(value, bool):
        fail(f"{what}: admin_only must be true or false")
    return value


def _refuse_retired_audience(raw: dict[str, Any], *, what: str) -> None:
    """Refuse the audience term an earlier contract used.

    Every other unknown term is dropped and reported. This one narrowed who
    could reach something, so it is refused by name and the author is told
    what replaced it.
    """
    if RETIRED_AUDIENCE_TERM in raw:
        fail(
            f"{what}: {RETIRED_AUDIENCE_TERM!r} is not a term this contract "
            "declares; who opens a surface is chosen by the community, and "
            "'admin_only' limits one to its admins"
        )


def _field(
    raw: Any,
    *,
    types: frozenset[str],
    allow_managed: bool,
    what: str,
    allow_list: bool = False,
) -> dict[str, Any]:
    """One typed input, in a connection form or an endpoint's parameters.

    ``allow_list`` is what separates the two. A connection's field is a single
    credential an admin types; an endpoint's parameter may take several values,
    and the caller has to be told which.
    """
    field = require_mapping(raw, what)
    key = check_identifier(field.get("key"), what=f"{what} key")
    field_type = field.get("type")
    if field_type not in types:
        fail(f"{what} {key!r}: unknown field type {field_type!r}")

    cleaned: dict[str, Any] = {
        "key": key,
        "type": field_type,
        "required": field.get("required") is True,
        "label": _label(field.get("label"), what=f"{what} {key!r}"),
    }
    if field_type == "select":
        options = require_list(
            field.get("options"), f"{what} {key!r} options", MAX_SELECT_OPTIONS
        )
        values = [
            clean_text(option, what=f"{what} {key!r} option", limit=MAX_LABEL_LENGTH)
            for option in options
        ]
        if not values:
            fail(f"{what} {key!r}: a select field must offer at least one option")
        cleaned["options"] = values
    # Cardinality is a fact about the value rather than about a control, so it
    # is the plug-in's to state and a caller has to know it: whether to send one
    # value or an array is not something a consumer can infer.
    if allow_list and field.get("list") is True:
        cleaned["list"] = True

    # Where the permitted values come from, when only the plug-in can know them.
    # `options` is the other case: a set that is the same on every deployment.
    if allow_list:
        source = _options_from(field.get("options_from"), what=f"{what} {key!r}")
        if source is not None:
            cleaned["options_from"] = source
    # Keys the plug-in writes back itself, rather than the admin typing them: a
    # vendor flow returns its result through the plug-in's own write path.
    if allow_managed and field.get("managed") is True:
        cleaned["managed"] = True
    return cleaned


def _options_from(raw: Any, *, what: str) -> dict[str, Any] | None:
    """Where a parameter's values come from, as a reference and nothing more.

    A repository, a channel, a board, a project: values that differ per install,
    change after it, and can only be enumerated by the plug-in holding that
    install's credential. None of them can be written into a manifest, which is
    published once and is identical on every deployment — so a parameter names
    the read endpoint that answers instead.

    Shape only here. That the endpoint exists, reads rather than writes, and
    returns the keys named is checked where every endpoint is known, the same
    way a widget's binding is.
    """
    if raw is None:
        return None

    source = require_mapping(raw, f"{what} options_from")
    named = source.get("endpoint")
    if not isinstance(named, str) or not named:
        fail(f"{what} options_from endpoint is required")
    if len(named) > MAX_ENDPOINT_ID_LENGTH:
        fail(f"{what} options_from endpoint {named[:40]!r}… is too long")
    for character in named:
        if character not in ENDPOINT_ID_CHARS:
            fail(f"{what} options_from endpoint {named!r} contains {character!r}")

    cleaned: dict[str, Any] = {
        "endpoint": named,
        "key": check_identifier(source.get("key"), what=f"{what} options_from key"),
    }

    label_key = source.get("label_key")
    if label_key is not None:
        cleaned["label_key"] = check_identifier(
            label_key, what=f"{what} options_from label_key"
        )

    needs = source.get("needs")
    if needs is not None:
        cleaned["needs"] = _option_source_needs(needs, what=what)
    return cleaned


def _option_source_needs(raw: Any, *, what: str) -> dict[str, str]:
    """What to send that endpoint, in its parameter names and this one's.

    Past the first source in a form, most of them answer differently depending
    on what has been chosen already — a repository's labels, a board's fields, a
    field's values — so a source names the sibling answers it needs.

    Shape only here. That each side names a real parameter is checked where
    every endpoint is known, the same way the endpoint itself is.
    """
    supplied = require_mapping(raw, f"{what} options_from needs")
    if len(supplied) > MAX_PARAMS_PER_ENDPOINT:
        fail(
            f"{what} options_from names more than "
            f"{MAX_PARAMS_PER_ENDPOINT} parameters to send"
        )
    needs: dict[str, str] = {}
    for theirs, ours in supplied.items():
        key = check_identifier(theirs, what=f"{what} options_from needs key")
        needs[key] = check_identifier(ours, what=f"{what} options_from needs {key!r}")
    return needs


# --- connections ------------------------------------------------------------


def _access_hint(raw: Any, *, what: str) -> dict[str, Any] | None:
    """What a connection says it will use the credential for.

    Display-only truth in advertising: the settings form names the API and the
    permissions the plug-in wants, so an admin can mint a minimal credential. No
    other system's permissions can be enforced from here, and none is claimed
    to be — this only makes least privilege the visible default.
    """
    if raw is None:
        return None
    hint = require_mapping(raw, f"{what} access_hint")
    cleaned: dict[str, Any] = {}
    api = clean_text(
        hint.get("api"),
        what=f"{what} access_hint.api",
        limit=MAX_HINT_LENGTH,
        required=False,
    )
    if api is not None:
        cleaned["api"] = api
    scopes = require_list(
        hint.get("scopes"), f"{what} access_hint.scopes", MAX_ACCESS_HINT_SCOPES
    )
    named = [
        clean_text(scope, what=f"{what} access_hint.scope", limit=MAX_HINT_LENGTH)
        for scope in scopes
    ]
    if named:
        cleaned["scopes"] = named
    return cleaned or None


def _vendor(raw: Any) -> dict[str, Any] | None:
    """What an operator supplies for the plug-in's vendor client, declared and
    never valued: every value is entered on the deployment."""
    if raw is None:
        return None
    vendor = require_mapping(raw, "service plug-in: vendor")
    entries = require_list(
        vendor.get("fields"), "service plug-in: vendor fields", MAX_VENDOR_FIELDS
    )
    if not entries:
        fail("service plug-in: vendor must declare at least one field")
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        field = require_mapping(entry, "service plug-in: vendor field")
        key = check_identifier(
            field.get("key"), what="service plug-in: vendor field key"
        )
        if key in seen:
            fail(f"service plug-in: two vendor fields share the key {key!r}")
        seen.add(key)
        field_type = field.get("type")
        if field_type not in VENDOR_FIELD_TYPES:
            fail(f"service plug-in: vendor field {key!r}: unknown type {field_type!r}")
        fields.append(
            {
                "key": key,
                "type": field_type,
                "required": field.get("required") is True,
                "label": _label(
                    field.get("label"), what=f"service plug-in: vendor field {key!r}"
                ),
            }
        )
    cleaned: dict[str, Any] = {"fields": fields}
    label = localized_text(vendor.get("label"), MAX_TEXT_LENGTH)
    if label is not None:
        cleaned["label"] = label
    if vendor.get("setup") is not None:
        cleaned["setup"] = _vendor_setup(vendor["setup"], fields=fields)
    return cleaned


def check_setup_values(values: Any, *, fields: list[dict[str, Any]]) -> None:
    """Hold a GitHub App setup's ``values`` to the vendor fields: each key a
    declared field, each answer GitHub gives written at most once, and the
    secret ones only to a secret field. Read when a manifest is published and
    again when a setup finishes against the manifest current then."""
    what = "service plug-in: vendor.setup.values"
    if not isinstance(values, dict) or not values:
        fail(f"{what} must name at least one value")
    types = {field["key"]: field.get("type") for field in fields}
    written: set[str] = set()
    for key, answer in values.items():
        if key not in types:
            fail(f"{what} names {key!r}, which the vendor block does not declare")
        if answer not in GITHUB_APP_VALUES:
            fail(f"{what} {key!r}: unknown value {answer!r}")
        if answer in written:
            fail(f"{what} writes {answer!r} twice")
        written.add(answer)
        if answer in GITHUB_SECRET_VALUES and types[key] != "secret":
            fail(f"{what} {key!r}: {answer!r} is written only to a secret field")


def _vendor_setup(raw: Any, *, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """The vendor's own flow for making its client, and which vendor field
    each value it answers with is written to."""
    what = "service plug-in: vendor.setup"
    setup = require_mapping(raw, what)
    if setup.get("kind") != GITHUB_APP_MANIFEST:
        fail(f"{what}: unknown kind {setup.get('kind')!r}")
    app = require_mapping(setup.get("app"), f"{what}.app")
    name = check_single_line(
        clean_text(app.get("name"), what=f"{what}.app.name", limit=MAX_LABEL_LENGTH)
        or "",
        what=f"{what}.app.name",
    )
    url = check_url(app.get("url"), what=f"{what}.app.url")
    if not url.startswith("https://"):
        fail(f"{what}.app.url must be an https address")
    public = app.get("public", False)
    if not isinstance(public, bool):
        fail(f"{what}.app.public must be true or false")
    permissions = require_mapping(
        app.get("default_permissions") or {}, f"{what}.app.default_permissions"
    )
    if len(permissions) > MAX_GITHUB_APP_PERMISSIONS:
        fail(
            f"{what}.app.default_permissions holds more than "
            f"{MAX_GITHUB_APP_PERMISSIONS} entries"
        )
    for permission, level in permissions.items():
        check_identifier(permission, what=f"{what}.app permission")
        if level not in GITHUB_PERMISSION_LEVELS:
            fail(f"{what}.app permission {permission!r}: unknown level {level!r}")
    events = [
        check_identifier(event, what=f"{what}.app event")
        for event in require_list(
            app.get("default_events"),
            f"{what}.app.default_events",
            MAX_GITHUB_APP_EVENTS,
        )
    ]
    if len(set(events)) != len(events):
        fail(f"{what}.app.default_events names an event twice")

    values = require_mapping(setup.get("values"), f"{what}.values")
    check_setup_values(values, fields=fields)

    cleaned_app: dict[str, Any] = {
        "name": name,
        "url": url,
        "public": public,
        "default_permissions": dict(sorted(permissions.items())),
        "default_events": events,
    }
    return {"kind": setup["kind"], "app": cleaned_app, "values": dict(values)}


def _template(
    raw: Any,
    *,
    what: str,
    vendor_keys: set[str],
    field_keys: set[str],
    required: bool = True,
    https: bool = False,
) -> str | None:
    """A declared value that may name ``{vendor.<key>}`` or ``{<key>}``, each
    of which must be declared: a vendor field, or one of the connection's own
    fields."""
    text = clean_text(raw, what=what, limit=MAX_TEMPLATE_LENGTH, required=required)
    if text is None:
        return None
    check_single_line(text, what=what)
    if https:
        if not text.startswith("https://"):
            fail(f"{what} must be an https address")
        # The host is the plug-in's to state; a value is filled in after it.
        if "{" in re.split(r"[/?#]", text[len("https://") :], maxsplit=1)[0]:
            fail(f"{what} fills a value into its host")
    _check_placeholders(text, what=what, vendor_keys=vendor_keys, field_keys=field_keys)
    return text


def _check_placeholders(
    text: str, *, what: str, vendor_keys: set[str], field_keys: set[str]
) -> None:
    """Every ``{vendor.<key>}`` and ``{<key>}`` ``text`` names is declared: a
    vendor field, or one of the connection's own fields."""
    position = 0
    while True:
        start = text.find("{", position)
        if start == -1:
            break
        end = text.find("}", start + 1)
        if end == -1:
            fail(f"{what} opens a '{{' it does not close")
        name = text[start + 1 : end]
        if name.startswith("vendor."):
            if name[len("vendor.") :] not in vendor_keys:
                fail(
                    f"{what} names {{{name}}}, which the vendor block does not declare"
                )
        elif name not in field_keys:
            fail(f"{what} names {{{name}}}, which is not a field of this connection")
        position = end + 1


def _exchange_body(
    raw: Any, *, what: str, vendor_keys: set[str], field_keys: set[str]
) -> dict[str, Any] | str:
    """The JSON object a minted token's assertion is posted with, or an
    expression answering it from the connection's own fields. A string in the
    object, at any depth, may name a vendor value and the connection's own
    fields, as the token's other values do."""
    if isinstance(raw, str):
        return _checked(raw, what=what)
    body = require_mapping(raw, what)
    pending: list[tuple[Any, str]] = [(body, what)]
    while pending:
        value, at = pending.pop()
        if isinstance(value, str):
            _check_placeholders(
                value, what=at, vendor_keys=vendor_keys, field_keys=field_keys
            )
        elif isinstance(value, dict):
            pending.extend((child, f"{at}.{key}") for key, child in value.items())
        elif isinstance(value, list):
            pending.extend(
                (child, f"{at}.{index}") for index, child in enumerate(value)
            )
    return body


def _flow(
    raw: Any,
    *,
    what: str,
    scope: str,
    field_keys: set[str],
    vendor_keys: set[str],
    declarative: bool,
    auth_header: str,
) -> dict[str, Any]:
    """How Initiative establishes a connection: an OAuth 2.0 authorization code
    flow, with the vendor client's values named from the vendor block."""
    flow = require_mapping(raw, f"{what} flow")
    flow_type = flow.get("type")
    if flow_type not in FLOW_TYPES:
        fail(f"{what} flow: unknown type {flow_type!r}")

    def template(key: str, **kwargs: Any) -> str | None:
        return _template(
            flow.get(key),
            what=f"{what} flow.{key}",
            vendor_keys=vendor_keys,
            field_keys=field_keys,
            **kwargs,
        )

    cleaned: dict[str, Any] = {
        "type": flow_type,
        "authorize_url": template("authorize_url", https=True),
        "token_url": template("token_url", https=True),
        "client_id": template("client_id"),
        "pkce": flow.get("pkce") is not False,
        "after_connect": _after_connect(
            flow.get("after_connect"),
            what=f"{what} flow.after_connect",
            auth_header=auth_header,
        ),
    }
    if declarative and cleaned["after_connect"] is True:
        fail(
            f"{what}: a declarative plug-in gives after_connect's request and map; "
            "there is no hook to call"
        )
    if not declarative and isinstance(cleaned["after_connect"], dict):
        fail(f"{what}: a container plug-in sets after_connect true and answers it")
    secret = template("client_secret", required=False)
    if secret is not None:
        cleaned["client_secret"] = secret
    scopes = require_list(flow.get("scopes"), f"{what} flow.scopes", MAX_FLOW_SCOPES)
    cleaned["scopes"] = [
        check_single_line(
            clean_text(item, what=f"{what} flow.scopes entry", limit=MAX_HINT_LENGTH)
            or "",
            what=f"{what} flow.scopes entry",
        )
        for item in scopes
    ]
    params_raw = flow.get("authorize_params")
    params: dict[str, str] = {}
    if params_raw is not None:
        mapping = require_mapping(params_raw, f"{what} flow.authorize_params")
        if len(mapping) > MAX_AUTHORIZE_PARAMS:
            fail(
                f"{what} flow.authorize_params holds more than "
                f"{MAX_AUTHORIZE_PARAMS} entries"
            )
        for name, value in mapping.items():
            key = check_identifier(name, what=f"{what} flow.authorize_params key")
            params[key] = (
                _template(
                    value,
                    what=f"{what} flow.authorize_params.{key}",
                    vendor_keys=vendor_keys,
                    field_keys=field_keys,
                )
                or ""
            )
    cleaned["authorize_params"] = params

    install = template("install_url", required=False, https=True)
    if install is not None:
        if scope != "static":
            fail(f"{what}: an install page is for a static connection")
        if not cleaned["after_connect"]:
            fail(
                f"{what}: an installation-style flow calls after_connect, which "
                "checks who installed it"
            )
        cleaned["install_url"] = install

    revoke = flow.get("revoke")
    if revoke is not None:
        if revoke not in REVOKE_METHODS:
            fail(f"{what} flow: unknown revoke {revoke!r}")
        if declarative and revoke == "hook":
            fail(f"{what} flow: a declarative plug-in has no revoke hook")
        cleaned["revoke"] = revoke
    revoke_url = template("revoke_url", required=False, https=True)
    if revoke_url is not None:
        cleaned["revoke_url"] = revoke_url
    if revoke in ("rfc7009", "github_grant") and revoke_url is None:
        fail(f"{what}: {revoke} revocation is sent to revoke_url, which is missing")
    return cleaned


def _token(
    raw: Any, *, what: str, field_keys: set[str], vendor_keys: set[str]
) -> dict[str, Any]:
    """An access token Initiative mints on demand with a vendor key."""
    token = require_mapping(raw, f"{what} token")
    token_type = token.get("type")
    if token_type not in TOKEN_TYPES:
        fail(f"{what} token: unknown type {token_type!r}")

    def template(key: str, **kwargs: Any) -> str | None:
        return _template(
            token.get(key),
            what=f"{what} token.{key}",
            vendor_keys=vendor_keys,
            field_keys=field_keys,
            **kwargs,
        )

    alg = token.get("alg", "RS256")
    if alg not in JWT_ALGORITHMS:
        fail(f"{what} token: unknown alg {alg!r}")
    lifetime = token.get("lifetime", 540)
    if (
        isinstance(lifetime, bool)
        or not isinstance(lifetime, int)
        or not 1 <= lifetime <= MAX_TOKEN_LIFETIME_SECONDS
    ):
        fail(f"{what} token.lifetime must be 1..{MAX_TOKEN_LIFETIME_SECONDS} seconds")
    cleaned: dict[str, Any] = {
        "type": token_type,
        "exchange_url": template("exchange_url", https=True),
        "iss": template("iss"),
        "key": template("key"),
        "alg": alg,
        "lifetime": lifetime,
    }
    if token.get("exchange_body") is not None:
        cleaned["exchange_body"] = _exchange_body(
            token["exchange_body"],
            what=f"{what} token.exchange_body",
            vendor_keys=vendor_keys,
            field_keys=field_keys,
        )
    return cleaned


def _connection(
    raw: Any, *, vendor_keys: set[str], declarative: bool, auth_header: str
) -> dict[str, Any]:
    connection = require_mapping(raw, "connection")
    connection_id = check_identifier(connection.get("id"), what="connection id")
    what = f"connection {connection_id!r}"

    scope = connection.get("scope")
    if scope not in CONNECTION_SCOPES:
        fail(f"{what}: unknown scope {scope!r}")

    fields_raw = require_list(
        connection.get("fields"), f"{what} fields", MAX_FIELDS_PER_CONNECTION
    )
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in fields_raw:
        field = _field(
            entry, types=FIELD_TYPES, allow_managed=True, what=f"{what} field"
        )
        if field["key"] in seen:
            fail(f"{what}: two fields share the key {field['key']!r}")
        if field["key"] in RESERVED_TOKEN_KEYS:
            fail(
                f"{what}: {field['key']!r} is reserved for a flow's tokens and"
                " the vendor's report that the connection was removed"
            )
        seen.add(field["key"])
        fields.append(field)

    cleaned: dict[str, Any] = {
        "id": connection_id,
        "scope": scope,
        "label": _label(connection.get("label"), what=what),
        "fields": fields,
    }

    flow_raw = connection.get("flow")
    if flow_raw is None:
        if scope == "interactive":
            # A member's own account is authorized at the vendor; there is
            # nothing for them to type.
            fail(f"{what}: an interactive connection declares a flow")
        if not fields:
            # Nothing for the admin to supply, so nothing this connection could be.
            fail(f"{what}: a static connection must declare at least one field")
    else:
        flow = _flow(
            flow_raw,
            what=what,
            scope=scope,
            field_keys=seen,
            vendor_keys=vendor_keys,
            declarative=declarative,
            auth_header=auth_header,
        )
        for field in fields:
            if field.get("managed") is not True:
                fail(
                    f"{what}: field {field['key']!r} — a connection with a flow "
                    "holds only managed values"
                )
        if fields and not flow["after_connect"]:
            fail(
                f"{what}: its managed values come from the after_connect hook, "
                "which the flow does not call"
            )
        cleaned["flow"] = flow

    token_raw = connection.get("token")
    if token_raw is not None:
        if scope != "static":
            fail(f"{what}: a minted token belongs to a static connection")
        cleaned["token"] = _token(
            token_raw, what=what, field_keys=seen, vendor_keys=vendor_keys
        )

    hint = _access_hint(connection.get("access_hint"), what=what)
    if hint is not None:
        cleaned["access_hint"] = hint
    if connection.get("health") is not None:
        if not declarative:
            fail(
                f"{what}: health is a declarative plug-in's; a container checks its own"
            )
        cleaned["health"] = _health(
            connection["health"], what=f"{what} health", auth_header=auth_header
        )
    return cleaned


def _drawn_from(value: Any, *, what: str, chars: frozenset[str], limit: int) -> str:
    """A required string written in ``chars`` alone."""
    if not isinstance(value, str) or not value:
        fail(f"{what} is required")
    if len(value) > limit:
        fail(f"{what} is longer than {limit} characters")
    for character in value:
        if character not in chars:
            fail(f"{what} contains {character!r}, which is not allowed")
    return value


def _webhooks(
    raw: Any,
    *,
    vendor_keys: set[str],
    connections: list[dict[str, Any]],
    declarative: bool,
) -> dict[str, Any] | None:
    """How Initiative receives the vendor's webhooks for the plug-in: the signature
    it checks, the header naming a delivery, and the static connection field a
    delivery is routed by."""
    if raw is None:
        return None
    hooks = require_mapping(raw, "service plug-in: webhooks")
    verify = require_mapping(hooks.get("verify"), "service plug-in: webhooks.verify")
    scheme = verify.get("scheme")
    if scheme not in WEBHOOK_SCHEMES:
        fail(f"service plug-in: webhooks.verify: unknown scheme {scheme!r}")
    encoding = verify.get("encoding")
    if encoding not in WEBHOOK_ENCODINGS:
        fail(f"service plug-in: webhooks.verify: unknown encoding {encoding!r}")
    secret = verify.get("secret")
    key = (
        secret[len("{vendor.") : -1]
        if isinstance(secret, str)
        and secret.startswith("{vendor.")
        and secret.endswith("}")
        else None
    )
    if key not in vendor_keys:
        fail(
            "service plug-in: webhooks.verify.secret must be one value the vendor "
            "block declares, written '{vendor.<key>}'"
        )

    def header(value: Any, what: str) -> str:
        return _drawn_from(
            value, what=what, chars=HEADER_NAME_CHARS, limit=MAX_IDENTIFIER_LENGTH
        )

    cleaned_verify: dict[str, Any] = {
        "scheme": scheme,
        "header": header(
            verify.get("header"), "service plug-in: webhooks.verify.header"
        ),
        "encoding": encoding,
        "secret": secret,
    }
    prefix = clean_text(
        verify.get("prefix"),
        what="service plug-in: webhooks.verify.prefix",
        limit=MAX_IDENTIFIER_LENGTH,
        required=False,
    )
    if prefix is not None:
        cleaned_verify["prefix"] = check_single_line(
            prefix, what="service plug-in: webhooks.verify.prefix"
        )

    route = require_mapping(hooks.get("route"), "service plug-in: webhooks.route")
    connection_id = check_identifier(
        route.get("connection"), what="service plug-in: webhooks.route.connection"
    )
    field = check_identifier(
        route.get("field"), what="service plug-in: webhooks.route.field"
    )
    connection = next((c for c in connections if c["id"] == connection_id), None)
    if connection is None or connection["scope"] != "static":
        fail(
            f"service plug-in: webhooks.route names {connection_id!r}, which is not a "
            "static connection this plug-in declares"
        )
    if field not in {entry["key"] for entry in connection["fields"]}:
        fail(
            f"service plug-in: webhooks.route names {field!r}, which is not a field of "
            f"the connection {connection_id!r}"
        )
    # Exactly one of a body path and a header carries the routed value.
    if (route.get("path") is None) == (route.get("header") is None):
        fail("service plug-in: webhooks.route names exactly one of 'path' and 'header'")
    cleaned_route: dict[str, Any] = (
        {
            "path": _drawn_from(
                route["path"],
                what="service plug-in: webhooks.route.path",
                chars=FIELD_PATH_CHARS,
                limit=MAX_PATH_LENGTH,
            )
        }
        if route.get("path") is not None
        else {
            "header": header(route["header"], "service plug-in: webhooks.route.header")
        }
    )
    cleaned: dict[str, Any] = {
        "verify": cleaned_verify,
        "dedup": header(hooks.get("dedup"), "service plug-in: webhooks.dedup"),
        "route": {**cleaned_route, "connection": connection_id, "field": field},
    }

    events = require_list(
        hooks.get("events"), "service plug-in: webhooks.events", MAX_WEBHOOK_EVENTS
    )
    statuses = require_list(
        hooks.get("status"), "service plug-in: webhooks.status", MAX_WEBHOOK_STATUSES
    )
    if not declarative:
        if events or statuses:
            fail(
                "service plug-in: a container plug-in's webhook hook receives each delivery"
            )
        return cleaned
    if not events and not statuses:
        fail(
            "service plug-in: a declarative plug-in maps deliveries with 'events' or "
            "'status'; there is no hook to forward them to"
        )
    if events:
        cleaned["events"] = []
        for index, entry in enumerate(events):
            what = f"service plug-in: webhooks.events.{index}"
            row = require_mapping(entry, what)
            # A row emits an event, changes the plug-in's values, or both, and
            # an event's payload is its map.
            if row.get("emit") is None and row.get("write") is None:
                fail(f"{what}: an event row emits, writes, or both")
            if (row.get("emit") is None) != (row.get("map") is None):
                fail(
                    f"{what}: an event row gives both 'emit' and the 'map' of its payload"
                )
            event: dict[str, Any] = {
                "when": _checked(row.get("when"), what=f"{what}.when")
            }
            if row.get("emit") is not None:
                event["emit"] = _endpoint_id_chars(row["emit"], what=f"{what}.emit")
                event["map"] = _checked(row["map"], what=f"{what}.map")
            if row.get("write") is not None:
                event["write"] = _checked(row["write"], what=f"{what}.write")
            cleaned["events"].append(event)
    if statuses:
        declared = {entry["id"] for entry in connections}
        cleaned["status"] = []
        for index, entry in enumerate(statuses):
            what = f"service plug-in: webhooks.status.{index}"
            row = require_mapping(entry, what)
            named = check_identifier(row.get("connection"), what=f"{what}.connection")
            if named not in declared:
                fail(f"{what}: {named!r} is not a connection this plug-in declares")
            state = row.get("state")
            if state not in CONNECTION_STATES - {"unavailable"}:
                fail(
                    f"{what}: a delivery says a connection is ok, suspended or removed"
                )
            cleaned["status"].append(
                {
                    "when": _checked(row.get("when"), what=f"{what}.when"),
                    "connection": named,
                    "state": state,
                }
            )
    return cleaned


def _endpoint_id_chars(raw: Any, *, what: str) -> str:
    """An endpoint id's shape, before what it names is known."""
    return _drawn_from(
        raw, what=what, chars=ENDPOINT_ID_CHARS, limit=MAX_ENDPOINT_ID_LENGTH
    )


def schedule_minutes(every: str) -> int:
    """A schedule's interval in minutes: ``15m`` is 15, ``6h`` is 360."""
    count = int(every[:-1])
    return count * 60 if every.endswith("h") else count


def _schedules(
    raw: Any,
    *,
    declarative: bool,
    service_public_id: str,
    endpoints: dict[str, dict[str, Any]],
    connection_ids: set[str],
) -> list[dict[str, str]]:
    """What Initiative runs on an interval for each community: each a unique id
    and a whole number of minutes or hours, within the bounds.

    A container's schedule calls its ``schedule`` hook and names nothing more.
    A declarative plug-in's makes one of its reads as the installation, so the
    read's ``actors`` take it, and its ``write`` answers the changes made from
    what the read answered. Its id is no connection's: a connection's health
    check runs under the connection's id.
    """
    schedules: list[dict[str, str]] = []
    for entry in require_list(raw, "service plug-in: schedules", MAX_SCHEDULES):
        schedule = require_mapping(entry, "service plug-in: schedule")
        schedule_id = check_identifier(
            schedule.get("id"), what="service plug-in: schedule id"
        )
        what = f"service plug-in: schedule {schedule_id!r}"
        if any(kept["id"] == schedule_id for kept in schedules):
            fail(f"service plug-in: two schedules share the id {schedule_id!r}")
        cleaned = {
            "id": schedule_id,
            "every": _every(schedule.get("every"), what=f"{what} every"),
        }
        if not declarative:
            if any(
                schedule.get(term) is not None
                for term in ("endpoint", "params", "write")
            ):
                fail(f"{what}: a container plug-in's schedule calls its schedule hook")
            schedules.append(cleaned)
            continue
        if schedule_id in connection_ids:
            fail(
                f"{what} has a connection's id, and Initiative keys connection "
                "health checks by connection id"
            )
        if schedule.get("endpoint") is None or schedule.get("write") is None:
            fail(
                f"{what}: a declarative plug-in's schedule names the read it makes "
                "and the write it makes from the answer; there is no hook to call"
            )
        endpoint = _endpoint_id(
            schedule["endpoint"],
            service_public_id=service_public_id,
            what=f"{what} endpoint",
        )
        named = endpoints.get(endpoint)
        if named is None:
            fail(f"{what}: names {endpoint!r}, which this manifest does not declare")
        if named["direction"] != "read":
            fail(
                f"{what}: names {endpoint!r}, which is a {named['direction']} endpoint"
            )
        if "installation" not in named.get("actors", ()):
            fail(
                f"{what}: {endpoint!r} does not take the installation as its actor, "
                "and no person is present when a schedule runs"
            )
        cleaned["endpoint"] = endpoint
        if schedule.get("params") is not None:
            cleaned["params"] = _checked(schedule["params"], what=f"{what} params")
        cleaned["write"] = _checked(schedule["write"], what=f"{what} write")
        schedules.append(cleaned)
    return schedules


def _every(every: Any, *, what: str) -> str:
    """An interval, a schedule's or a health check's: a whole number of minutes
    or hours, within the schedule bounds."""
    if not (
        isinstance(every, str)
        and 2 <= len(every) <= MAX_SCHEDULE_EVERY_LENGTH
        and every[-1] in "mh"
        and all(character in "0123456789" for character in every[:-1])
    ):
        fail(f"{what} is a whole number of minutes or hours, like '15m'")
    if not SCHEDULE_MIN_MINUTES <= schedule_minutes(every) <= SCHEDULE_MAX_MINUTES:
        fail(
            f"{what} is at least {SCHEDULE_MIN_MINUTES}m and at most "
            f"{SCHEDULE_MAX_MINUTES // 60}h"
        )
    return every


# --- what a declarative plug-in calls -------------------------------------------
#
# A declarative plug-in has no container: Initiative makes its calls itself, from
# requests and JSONata expressions written here. Shape and parsing are checked
# on publish; what an expression answers is the executor's to read.


def _expression(raw: Any, *, what: str) -> Any:
    """A JSONata expression that parses, and its syntax tree."""
    if not isinstance(raw, str) or not raw:
        fail(f"{what} is required")
    if len(raw) > MAX_EXPRESSION_LENGTH:
        fail(f"{what} is longer than {MAX_EXPRESSION_LENGTH} characters")
    try:
        return expressions.parse(raw)
    except expressions.ExpressionError as exc:
        where = "" if exc.position is None else f" (at character {exc.position})"
        fail(f"{what} does not parse: {exc}{where}")


def _reads_only(tree: Any, *, steps: set[str] | None, what: str) -> None:
    """With ``steps`` given, an expression reads only those steps."""
    if steps is None:
        return
    for name in sorted(expressions.step_reads(tree) - steps):
        fail(f"{what} reads steps.{name}, which is not a step before it")


def _checked(raw: Any, *, what: str, steps: set[str] | None = None) -> str:
    _reads_only(_expression(raw, what=what), steps=steps, what=what)
    return raw


def _host(raw: Any) -> str:
    """A host, exact or with one leading ``*.`` label: lowercase labels of 1
    to 63 characters, not edged with '-', and a name rather than an address."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_HOST_LENGTH:
        fail(f"service plug-in: host {raw!r} is not a host name")
    labels = (raw[2:] if raw.startswith("*.") else raw).split(".")
    if (
        len(labels) < 2
        or any(
            not 1 <= len(label) <= 63
            or label.startswith("-")
            or label.endswith("-")
            or any(character not in HOST_LABEL_CHARS for character in label)
            for label in labels
        )
        or all(character in "0123456789" for character in labels[-1])
    ):
        fail(f"service plug-in: {raw!r} is not a host name")
    return raw


def _hosts(raw: Any) -> list[str]:
    hosts = [
        _host(entry) for entry in require_list(raw, "service plug-in: hosts", MAX_HOSTS)
    ]
    if len(set(hosts)) != len(hosts):
        fail("service plug-in: hosts names a host twice")
    return hosts


def _auth(raw: Any) -> dict[str, str]:
    """How the credential is put on a request; absent, ``Authorization: Bearer``."""
    auth = require_mapping(raw, "service plug-in: auth")
    prefix = auth.get("prefix", DEFAULT_AUTH_PREFIX)
    if not isinstance(prefix, str) or len(prefix) > MAX_IDENTIFIER_LENGTH:
        fail(
            f"service plug-in: auth.prefix is at most {MAX_IDENTIFIER_LENGTH} characters"
        )
    return {
        "header": _drawn_from(
            auth.get("header", DEFAULT_AUTH_HEADER),
            what="service plug-in: auth.header",
            chars=HEADER_NAME_CHARS,
            limit=MAX_IDENTIFIER_LENGTH,
        ),
        "prefix": check_single_line(prefix, what="service plug-in: auth.prefix"),
    }


def _named_expressions(
    raw: Any, *, what: str, chars: frozenset[str], limit: int, steps: set[str] | None
) -> dict[str, str]:
    """Query parameters or headers: names in ``chars``, each an expression."""
    named = require_mapping(raw, what)
    if len(named) > limit:
        fail(f"{what} holds more than {limit} entries")
    return {
        _drawn_from(
            name, what=f"{what} name", chars=chars, limit=MAX_IDENTIFIER_LENGTH
        ): _checked(value, what=f"{what}.{name}", steps=steps)
        for name, value in named.items()
    }


def _page_count(raw: Any, *, what: str, low: int, high: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
        fail(f"{what} must be a whole number from {low} to {high}")
    return raw


def _paging(
    raw: Any, *, what: str, graphql: bool, steps: set[str] | None
) -> dict[str, Any]:
    """One of the three ways a request reads more than one page."""
    paging = require_mapping(raw, what)
    kind = paging.get("kind")
    if kind not in PAGING_KINDS:
        fail(f"{what}: unknown kind {kind!r}")
    on_limit = paging.get("on_limit")
    if on_limit not in PAGE_LIMITS:
        fail(f"{what}: on_limit must be one of {sorted(PAGE_LIMITS)}")
    cleaned: dict[str, Any] = {
        "kind": kind,
        "max_pages": _page_count(
            paging.get("max_pages"),
            what=f"{what}.max_pages",
            low=1,
            high=MAX_PAGES_READ,
        ),
        "on_limit": on_limit,
    }
    if paging.get("items") is not None:
        cleaned["items"] = _checked(paging["items"], what=f"{what}.items", steps=steps)

    def query_name(key: str) -> str:
        return _drawn_from(
            paging.get(key),
            what=f"{what}.{key}",
            chars=QUERY_NAME_CHARS,
            limit=MAX_IDENTIFIER_LENGTH,
        )

    if kind == "page_number":
        cleaned["page_param"] = query_name("page_param")
        if paging.get("per_page_param") is not None:
            cleaned["per_page_param"] = query_name("per_page_param")
        cleaned["per_page"] = _page_count(
            paging.get("per_page"), what=f"{what}.per_page", low=1, high=MAX_PER_PAGE
        )
    elif kind == "cursor":
        for key in ("next", "more"):
            cleaned[key] = _checked(paging.get(key), what=f"{what}.{key}", steps=steps)
        param, variable = paging.get("param"), paging.get("variable")
        if (param is None) == (variable is None):
            fail(f"{what}: a cursor is sent in exactly one of 'param' and 'variable'")
        if param is not None:
            cleaned["param"] = query_name("param")
        else:
            if not graphql:
                fail(
                    f"{what}: a cursor is sent in a variable only of a GraphQL request"
                )
            name = _drawn_from(
                variable,
                what=f"{what}.variable",
                chars=GRAPHQL_NAME_CHARS,
                limit=MAX_IDENTIFIER_LENGTH,
            )
            if name[0] in "0123456789":
                fail(f"{what}.variable is not a GraphQL name")
            cleaned["variable"] = name
    return cleaned


def _vendor_request(
    raw: Any,
    *,
    what: str,
    auth_header: str,
    connection_ids: set[str] | None,
    steps: set[str] | None = None,
) -> dict[str, Any]:
    """One call to the vendor, rendered from expressions.

    ``connection_ids`` is the connections an endpoint's request may name, and
    it must name one, or one per actor; ``None`` is a connection's own request
    (``after_connect`` and ``health``), which carries that connection's
    credential and names none.
    """
    request = require_mapping(raw, what)
    method = request.get("method")
    if method not in HTTP_METHODS:
        fail(f"{what}: method must be one of {sorted(HTTP_METHODS)}")
    cleaned: dict[str, Any] = {
        "method": method,
        "url": _checked(request.get("url"), what=f"{what}.url", steps=steps),
    }
    if request.get("query") is not None:
        cleaned["query"] = _named_expressions(
            request["query"],
            what=f"{what}.query",
            chars=QUERY_NAME_CHARS,
            limit=MAX_REQUEST_QUERY,
            steps=steps,
        )
    if request.get("headers") is not None:
        headers = _named_expressions(
            request["headers"],
            what=f"{what}.headers",
            chars=HEADER_NAME_CHARS,
            limit=MAX_REQUEST_HEADERS,
            steps=steps,
        )
        if any(name.lower() == auth_header.lower() for name in headers):
            fail(f"{what}.headers: the credential's header is Initiative's to set")
        cleaned["headers"] = headers
    graphql = request.get("graphql")
    if request.get("body") is not None:
        if graphql is not None:
            fail(f"{what}: a request sends a body or a GraphQL query, not both")
        cleaned["body"] = _checked(request["body"], what=f"{what}.body", steps=steps)
    if graphql is not None:
        if method != "POST":
            fail(f"{what}: a GraphQL request is sent by POST")
        document = require_mapping(graphql, f"{what}.graphql")
        cleaned["graphql"] = {
            "query": clean_text(
                document.get("query"),
                what=f"{what}.graphql.query",
                limit=MAX_GRAPHQL_LENGTH,
            )
        }
        if document.get("variables") is not None:
            cleaned["graphql"]["variables"] = _checked(
                document["variables"], what=f"{what}.graphql.variables", steps=steps
            )
    connection = request.get("connection")
    if connection_ids is None:
        if connection is not None:
            fail(f"{what}: carries the credential of the connection it belongs to")
    elif isinstance(connection, dict):
        # One per actor: which actors, and each connection's scope, are held
        # to the endpoint's actors (``_endpoint``).
        if not connection or not set(connection) <= ACTOR_KINDS:
            fail(
                f"{what}.connection: names one connection per actor, drawn from "
                f"{sorted(ACTOR_KINDS)}"
            )
        cleaned["connection"] = {
            actor: _declared_connection(
                named, what=f"{what}.connection.{actor}", connection_ids=connection_ids
            )
            for actor, named in connection.items()
        }
    else:
        cleaned["connection"] = _declared_connection(
            connection, what=f"{what}.connection", connection_ids=connection_ids
        )
    if request.get("paging") is not None:
        cleaned["paging"] = _paging(
            request["paging"],
            what=f"{what}.paging",
            graphql=graphql is not None,
            steps=steps,
        )
    return cleaned


def _declared_connection(raw: Any, *, what: str, connection_ids: set[str]) -> str:
    """A connection a request names, which the plug-in declares."""
    connection = check_identifier(raw, what=what)
    if connection not in connection_ids:
        fail(f"{what}: {connection!r} is not a connection this plug-in declares")
    return connection


def _request_or_steps(
    raw: dict[str, Any],
    cleaned: dict[str, Any],
    *,
    what: str,
    auth_header: str,
    connection_ids: set[str] | None,
) -> set[str]:
    """A declarative endpoint's or ``after_connect``'s one request, or its
    steps, each reading only the steps before it, written onto ``cleaned``.
    Answers the step names, which its map and predicates may read."""
    request, steps_raw = raw.get("request"), raw.get("steps")
    if (request is None) == (steps_raw is None):
        fail(f"{what}: gives exactly one of 'request' and 'steps'")
    names: set[str] = set()
    if request is not None:
        cleaned["request"] = _vendor_request(
            request,
            what=f"{what} request",
            auth_header=auth_header,
            connection_ids=connection_ids,
            steps=names,
        )
        return names
    rows = require_list(steps_raw, f"{what} steps", MAX_STEPS)
    if not rows:
        fail(f"{what} steps names at least one step")
    steps: list[dict[str, Any]] = []
    for index, entry in enumerate(rows):
        step = require_mapping(entry, f"{what} steps.{index}")
        name = check_identifier(step.get("name"), what=f"{what} steps.{index}.name")
        if name in names:
            fail(f"{what}: {name!r} names two steps")
        steps.append(
            {
                "name": name,
                "request": _vendor_request(
                    step.get("request"),
                    what=f"{what} steps.{index}.request",
                    auth_header=auth_header,
                    connection_ids=connection_ids,
                    steps=set(names),
                ),
            }
        )
        names.add(name)
    cleaned["steps"] = steps
    return names


def _status_match(raw: Any, *, what: str) -> int | str:
    """One HTTP status, or a range of a hundred (``"4xx"``)."""
    if raw in STATUS_RANGES:
        return raw
    if (
        isinstance(raw, bool)
        or not isinstance(raw, int)
        or not 100 <= raw <= MAX_STATUS
    ):
        fail(
            f"{what} must be a status from 100 to {MAX_STATUS} or one of {sorted(STATUS_RANGES)}"
        )
    return raw


def _after_connect(raw: Any, *, what: str, auth_header: str) -> bool | dict[str, Any]:
    """``true`` (a container's hook), or a declarative plug-in's request and map."""
    if raw is None or isinstance(raw, bool):
        return raw is True
    after = require_mapping(raw, what)
    cleaned: dict[str, Any] = {}
    names = _request_or_steps(
        after,
        cleaned,
        what=what,
        auth_header=auth_header,
        connection_ids=None,
    )
    cleaned["map"] = _checked(after.get("map"), what=f"{what}.map", steps=names)
    refuse_when, code = after.get("refuse_when"), after.get("code")
    if (refuse_when is None) != (code is None):
        fail(f"{what}: a refusal gives both 'refuse_when' and the 'code' it answers")
    if refuse_when is not None:
        cleaned["refuse_when"] = _checked(
            refuse_when, what=f"{what}.refuse_when", steps=names
        )
        cleaned["code"] = check_identifier(code, what=f"{what}.code")
    return cleaned


def _health(raw: Any, *, what: str, auth_header: str) -> dict[str, Any]:
    """A connection's health check: its request, how often, and the states."""
    health = require_mapping(raw, what)
    every = _every(health.get("every"), what=f"{what}.every")
    states: list[dict[str, Any]] = []
    rows = require_list(health.get("states"), f"{what}.states", MAX_HEALTH_STATES)
    if not rows:
        fail(f"{what}.states names at least one state")
    for index, entry in enumerate(rows):
        row = require_mapping(entry, f"{what}.states.{index}")
        state = row.get("state")
        if state not in CONNECTION_STATES:
            fail(f"{what}.states.{index}: unknown state {state!r}")
        cleaned: dict[str, Any] = {"state": state}
        if row.get("status") is not None:
            cleaned["status"] = _status_match(
                row["status"], what=f"{what}.states.{index}.status"
            )
        if row.get("when") is not None:
            cleaned["when"] = _checked(row["when"], what=f"{what}.states.{index}.when")
        states.append(cleaned)
    return {
        "request": _vendor_request(
            health.get("request"),
            what=f"{what}.request",
            auth_header=auth_header,
            connection_ids=None,
        ),
        "every": every,
        "states": states,
    }


def _declarative_endpoint(
    endpoint: dict[str, Any],
    cleaned: dict[str, Any],
    *,
    what: str,
    auth_header: str,
    connection_ids: set[str],
) -> None:
    """A declarative read or write: its request or steps, its map and its
    error rules, written onto ``cleaned``."""
    names = _request_or_steps(
        endpoint,
        cleaned,
        what=what,
        auth_header=auth_header,
        connection_ids=connection_ids,
    )
    cleaned["map"] = _checked(endpoint.get("map"), what=f"{what} map", steps=names)

    known = {*cleaned.get("unavailable", []), *PLATFORM_CODES, TRANSIENT_CODE}
    rules: list[dict[str, Any]] = []
    for index, entry in enumerate(
        require_list(endpoint.get("errors"), f"{what} errors", MAX_ERROR_RULES)
    ):
        rule = require_mapping(entry, f"{what} errors.{index}")
        code = check_identifier(rule.get("code"), what=f"{what} errors.{index}.code")
        if code not in known:
            fail(f"{what} errors.{index}: {code!r} is not one of this endpoint's codes")
        cleaned_rule: dict[str, Any] = {
            "status": _status_match(
                rule.get("status"), what=f"{what} errors.{index}.status"
            ),
            "code": code,
        }
        if rule.get("when") is not None:
            cleaned_rule["when"] = _checked(
                rule["when"], what=f"{what} errors.{index}.when", steps=names
            )
        rules.append(cleaned_rule)
    if rules:
        cleaned["errors"] = rules


def _unavailable_codes(endpoint: dict[str, Any], *, what: str) -> list[str]:
    """The codes a read or write may answer ``unavailable`` with, beyond
    Initiative's own."""
    codes = [
        check_identifier(code, what=f"{what} unavailable entry")
        for code in require_list(
            endpoint.get("unavailable"), f"{what} unavailable", MAX_UNAVAILABLE_CODES
        )
    ]
    if len(set(codes)) != len(codes):
        fail(f"{what}: unavailable names a code twice")
    return codes


# --- what a plug-in offers -----------------------------------------------------


def _endpoint_identity(raw: Any, *, what: str) -> dict[str, Any] | None:
    """Which of an endpoint's returns identify the thing it touched.

    Shape only; that each part names a single-valued return of this endpoint is
    checked where the returns are known.
    """
    if raw is None:
        return None
    identity = require_mapping(raw, f"{what} identity")
    parts = require_list(
        identity.get("key"), f"{what} identity.key", MAX_IDENTITY_KEY_PARTS
    )
    if not parts:
        fail(f"{what} identity.key: name at least one return")
    return {
        "kind": check_identifier(identity.get("kind"), what=f"{what} identity.kind"),
        "key": [
            check_identifier(part, what=f"{what} identity.key entry") for part in parts
        ],
    }


def _check_identity_returns(
    identity: dict[str, Any], *, returns: list[dict[str, Any]], what: str
) -> None:
    """Every part of an address names a single value this endpoint hands back.

    Nothing downstream refuses a bad one — it simply resolves to nothing, and a
    fire somebody was waiting on is dropped without a word — so a part naming a
    return this endpoint does not declare, or one that is a list, is refused
    here. Half an address matches nothing, and one built from whichever parts
    happened to be present matches the wrong thing.
    """
    single = {value["key"] for value in returns if not value.get("list")}
    declared = {value["key"] for value in returns}
    for part in identity["key"]:
        if part not in declared:
            fail(f"{what} identity.key names {part!r}, which it does not return")
        if part not in single:
            fail(
                f"{what} identity.key names {part!r}, which is a list — "
                "an address is built from single values"
            )


def _endpoint_id(raw: Any, *, service_public_id: str, what: str) -> str:
    """One endpoint id, namespaced under the plug-in's own service id.

    The prefix is checked here and again at ingress against the declaring
    registration, so a plug-in can answer and announce only under its own name. Two
    plug-ins offering ``create-issue`` would be two different things under one name,
    and a caller that resolved the wrong one would do the wrong thing
    successfully — which is worse than an error.
    """
    prefix = f"{ENDPOINT_ID_PREFIX}{service_public_id}."
    if not isinstance(raw, str) or not raw:
        fail(f"{what} is required")
    if len(raw) > MAX_ENDPOINT_ID_LENGTH:
        fail(f"{what} {raw[:40]!r}… is too long")
    for character in raw:
        if character not in ENDPOINT_ID_CHARS:
            fail(f"{what} {raw!r} contains {character!r}")
    if not raw.startswith(prefix) or len(raw) == len(prefix):
        fail(f"{what} {raw!r} must start with {prefix!r}")
    return raw


def _endpoint(
    raw: Any,
    *,
    connection_ids: set[str],
    service_public_id: str,
    declarative: bool,
    auth_header: str,
    interactive_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """One thing the plug-in will do when something connects to it.

    A single vocabulary for every caller and every direction. A widget filling a
    tile, an automation service asking the plug-in to act, and a subscriber waiting
    to be told all name an id from this list, and what separates them is which
    token they prove themselves with rather than which route they found.

    The id is the address. There is no path to choose, so two plug-ins cannot answer
    the same question at different URLs and a caller that knows the id needs
    nothing else to make the call.
    """
    endpoint = require_mapping(raw, "endpoint")
    endpoint_id = _endpoint_id(
        endpoint.get("id"), service_public_id=service_public_id, what="endpoint id"
    )
    what = f"endpoint {endpoint_id!r}"
    _refuse_retired_audience(endpoint, what=what)
    unknown = sorted(set(endpoint) - ENDPOINT_TERMS)
    if unknown:
        fail(f"{what}: {', '.join(map(repr, unknown))} is not a term of the contract")

    direction = endpoint.get("direction")
    if direction not in DIRECTIONS:
        fail(f"{what}: direction must be one of {sorted(DIRECTIONS)}")

    params_raw = require_list(
        endpoint.get("params"), f"{what} params", MAX_PARAMS_PER_ENDPOINT
    )
    params: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in params_raw:
        param = _field(
            entry,
            types=PARAM_TYPES,
            allow_managed=False,
            what=f"{what} param",
            allow_list=True,
        )
        if param["key"] in seen:
            fail(f"{what}: two parameters share the key {param['key']!r}")
        seen.add(param["key"])
        params.append(param)

    cleaned: dict[str, Any] = {"id": endpoint_id, "direction": direction}

    # What this endpoint IS, in words, and what it hands back. Both belong to
    # every direction: an emission is the one thing here a person picks out of a
    # list without ever calling it, so it needs a name more than the others do,
    # and its payload is exactly as worth describing as a response.
    #
    # Stored and never read here. A label is somebody else's to render and a
    # return is somebody else's to bind, and this build assigns meaning to
    # neither — it bounds them, which is the whole of what a store owes a
    # document it passes on.
    label = localized_text(endpoint.get("label"), MAX_TEXT_LENGTH)
    if label is not None:
        cleaned["label"] = label
    description = localized_text(endpoint.get("description"), MAX_TEXT_LENGTH)
    if description is not None:
        cleaned["description"] = description
    returns = _returns(endpoint.get("returns"), what=what)
    if returns:
        cleaned["returns"] = returns

    # Where a consumer that groups a plug-in's endpoints should file this one, and
    # what it needs to already have in hand. Both are opaque identifiers: the
    # vocabularies belong to whoever consumes them — the automation service
    # names the subjects a run can be about — and a second reading of a list
    # this build does not own would only ever drift from it.
    group = endpoint.get("group")
    if group is not None:
        cleaned["group"] = check_identifier(group, what=f"{what} group")
    needs = endpoint.get("needs_subject")
    if needs is not None:
        cleaned["needs_subject"] = check_identifier(needs, what=f"{what} needs_subject")

    # What this touched, or what it is about — the one thing here only the plug-in
    # can know. A read has none: it touched nothing. Declaring the same kind and
    # key on a write and on the emission about it is what lets a consumer
    # recognise the change an automation made as its own, rather than firing
    # that automation again on it.
    identity = _endpoint_identity(endpoint.get("identity"), what=what)
    if identity is not None:
        if direction == "read":
            fail(f"{what}: a read endpoint has no identity — it touched nothing")
        _check_identity_returns(identity, returns=returns, what=what)
        cleaned["identity"] = identity

    # An emission travels the other way: nobody calls it, so there is nothing
    # for a caller to send, nothing to cache and nobody to gate. Carrying any of
    # it would describe a call that never happens.
    if direction == "emit":
        for absent in (
            "params",
            "requires",
            "cache_ttl_seconds",
            "actors",
            "admin_only",
            "public",
            "unavailable",
            *DECLARATIVE_ENDPOINT_TERMS,
        ):
            if endpoint.get(absent) is not None:
                fail(f"{what}: an emit endpoint has no {absent}")
        return cleaned

    codes = _unavailable_codes(endpoint, what=what)
    if codes:
        cleaned["unavailable"] = codes
    # A declarative plug-in's reads and writes are a request and a map; a
    # container's are its handler, and carry neither.
    if declarative:
        _declarative_endpoint(
            endpoint,
            cleaned,
            what=what,
            auth_header=auth_header,
            connection_ids=connection_ids,
        )
    else:
        for term in DECLARATIVE_ENDPOINT_TERMS:
            if endpoint.get(term) is not None:
                fail(
                    f"{what}: a container plug-in's endpoint is answered by its handler"
                )

    # Whoever the call is for, stored whichever way it was declared so every
    # pinned endpoint answers the question the same way.
    cleaned["admin_only"] = _admin_only(endpoint, what=what)
    # Whether other plug-ins may call it through Initiative. Stored only when it
    # is, so an endpoint published before the term reads the same as one that
    # left it out.
    if _public(endpoint, what=what):
        cleaned["public"] = True

    if params:
        cleaned["params"] = params

    actors = _actors(endpoint.get("actors"), what=what)
    if actors:
        cleaned["actors"] = actors

    # Only a read is answered from cache.
    if direction == "read":
        cleaned["cache_ttl_seconds"] = _cache_ttl(
            endpoint.get("cache_ttl_seconds"), what=what
        )
    elif endpoint.get("cache_ttl_seconds") is not None:
        fail(f"{what}: only a read endpoint has cache_ttl_seconds")

    requires = _requires(
        endpoint.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    # A member's own connection is resolved for the caller by ``requires``, so
    # a request carrying one on every call names it there too, and is not one
    # the installation, which has no member, can make. A write's request may
    # name one connection per actor instead, for exactly its actors: the
    # member's own for the member, and the community's for the installation.
    required = {term for terms in (requires or {}).values() for term in terms}
    for request in _requests(cleaned):
        named = request.get("connection")
        if isinstance(named, dict):
            if direction != "write":
                fail(f"{what}: only a write's request names a connection per actor")
            if set(named) != set(actors):
                fail(
                    f"{what}: its request names a connection per actor, one for "
                    "each of the endpoint's actors and no other"
                )
            for actor, connection_id in named.items():
                if (connection_id in interactive_ids) != (actor == "member"):
                    scope = "an interactive" if actor == "member" else "a static"
                    fail(
                        f"{what}: its request names {connection_id!r} for the "
                        f"{actor}, which is not {scope} connection"
                    )
        elif named in interactive_ids:
            if named not in required:
                fail(
                    f"{what}: its request uses the member connection {named!r}, "
                    "which requires does not name"
                )
            if "installation" in actors:
                fail(
                    f"{what}: its request uses the member connection {named!r}, "
                    "which a call made as the installation does not have"
                )
    return cleaned


def _requests(endpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A declarative endpoint's requests, its one or each step's."""
    if "request" in endpoint:
        return [endpoint["request"]]
    return [step["request"] for step in endpoint.get("steps") or []]


def _public(raw: dict[str, Any], *, what: str) -> bool:
    """``public``, defaulting to false; absent and null read the same."""
    value = raw.get("public")
    if value is None:
        return False
    if not isinstance(value, bool):
        fail(f"{what}: public must be true or false")
    return value


def _returns(raw: Any, *, what: str) -> list[dict[str, Any]]:
    """What an endpoint hands back, by name and type.

    Declared rather than discovered, because the consumer needs it before the
    endpoint has ever run: a widget binds a column and an automation offers a
    value for a later step to read, and both have to be refusable at the moment
    somebody arranges them rather than the first time one fires.

    ``list`` says several rather than one. It matters to a caller that has
    somewhere to put exactly one value — a form field, a tile's number — which
    is why it is a flag here rather than a second set of types.
    """
    if raw is None:
        return []
    declared = require_list(raw, f"{what} returns", MAX_RETURNS_PER_ENDPOINT)
    returns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in declared:
        value = require_mapping(entry, f"{what} return")
        key = check_identifier(value.get("key"), what=f"{what} return key")
        if key in seen:
            fail(f"{what}: two returns share the key {key!r}")
        seen.add(key)
        value_type = value.get("type")
        if value_type not in RETURN_TYPES:
            fail(f"{what} return {key!r}: unknown type {value_type!r}")
        cleaned: dict[str, Any] = {"key": key, "type": value_type}
        # Optional, unlike a param's: a param is a control somebody fills in and
        # needs a word on it, while a return is read by name and is often shown
        # under one the consumer supplies.
        label = localized_text(value.get("label"), MAX_TEXT_LENGTH)
        if label is not None:
            cleaned["label"] = label
        if value.get("list") is True:
            cleaned["list"] = True
        if value.get("of") is not None:
            cleaned["of"] = check_identifier(
                value.get("of"), what=f"{what} return {key!r} of"
            )
        returns.append(cleaned)
    _check_measures(returns, what=what)
    return returns


def _minimum_age(raw: Any) -> dict[str, int] | None:
    """How old somebody must be to use the plug-in, by country.

    Keys are ISO 3166-1 alpha-2 codes and ``default``. Refused rather than
    trimmed when any entry is wrong: an age the publisher declared for
    compliance and this build quietly dropped is the one mistake here nobody
    would notice. Stored as declared; nothing here enforces it.
    """
    if raw is None:
        return None
    declared = require_mapping(raw, "service plug-in: minimum_age")
    if not declared:
        fail("service plug-in: minimum_age names no region")
    if len(declared) > MAX_MINIMUM_AGE_REGIONS:
        fail(
            "service plug-in: minimum_age names more than "
            f"{MAX_MINIMUM_AGE_REGIONS} regions"
        )
    cleaned: dict[str, int] = {}
    for region, age in declared.items():
        if region != "default" and not (
            isinstance(region, str)
            and len(region) == 2
            and region.isascii()
            and region.isalpha()
            and region.isupper()
        ):
            fail(
                f"service plug-in: minimum_age region {region!r} is not an "
                "ISO 3166-1 alpha-2 code or 'default'"
            )
        if (
            not isinstance(age, int)
            or isinstance(age, bool)
            or not MIN_MINIMUM_AGE_YEARS <= age <= MAX_MINIMUM_AGE_YEARS
        ):
            fail(
                f"service plug-in: minimum_age for {region!r} must be a whole "
                f"number from {MIN_MINIMUM_AGE_YEARS} to {MAX_MINIMUM_AGE_YEARS}"
            )
        cleaned[region] = age
    return cleaned


def _check_measures(returns: list[dict[str, Any]], *, what: str) -> None:
    """Every ``of`` names a sibling the pair can be drawn with.

    ``of`` counts one return against another — used of allowed — so a summary
    can be drawn as one measure. That only means something between two single
    whole numbers: a list has no one figure, and a date has no proportion.
    """
    by_key = {value["key"]: value for value in returns}
    for value in returns:
        ceiling_key = value.get("of")
        if ceiling_key is None:
            continue
        if ceiling_key == value["key"]:
            fail(f"{what} return {value['key']!r} is counted against itself")
        ceiling = by_key.get(ceiling_key)
        if ceiling is None:
            fail(
                f"{what} return {value['key']!r} is counted against "
                f"{ceiling_key!r}, which is not a return of this endpoint"
            )
        for half in (value, ceiling):
            if half["type"] != "int" or half.get("list"):
                fail(
                    f"{what} return {half['key']!r} is not a single 'int', so "
                    f"{value['key']!r} of {ceiling_key!r} cannot be drawn"
                )


def _actors(raw: Any, *, what: str) -> list[str]:
    """Whose credential the plug-in will run this on, best first.

    A list rather than a set because the order is the plug-in's preference, and a
    caller reads it to know what it is asking for: an endpoint offering only
    ``member`` refuses when the member has connected nothing, rather than
    quietly acting as the plug-in instead.
    """
    if raw is None:
        return []
    declared = require_list(raw, f"{what} actors", len(ACTOR_KINDS))
    actors: list[str] = []
    for entry in declared:
        if entry not in ACTOR_KINDS:
            fail(f"{what}: actors must be drawn from {sorted(ACTOR_KINDS)}")
        if entry not in actors:
            actors.append(entry)
    if not actors:
        fail(f"{what}: names no actor it could run as")
    return actors


def _cache_ttl(raw: Any, *, what: str) -> int:
    """How long a response may be reused. Clamped rather than refused: a number
    out of range is a judgement about freshness, not a vocabulary this build
    cannot resolve."""
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, int):
        fail(f"{what}: cache_ttl_seconds must be a whole number of seconds")
    return max(0, min(raw, MAX_CACHE_TTL_SECONDS))


def _widget(
    raw: Any, *, readable_ids: set[str], connection_ids: set[str]
) -> dict[str, Any]:
    widget = require_mapping(raw, "widget")
    widget_id = check_identifier(widget.get("id"), what="widget id")
    what = f"widget {widget_id!r}"

    meta = validate_widget_meta(widget.get("meta"))
    if meta is None:
        fail(f"{what}: meta must name the widget in at least one language")

    module_source = widget.get("module_source")
    if not isinstance(module_source, str) or not module_source.strip():
        fail(f"{what}: module_source is required")
    # Measured, never read: the module is a string to this build, and the
    # browser's sandbox is the only thing that evaluates it.
    encoded = utf8_bytes(module_source, what=f"{what} module_source")
    if len(encoded) > MAX_MODULE_SOURCE_BYTES:
        fail(f"{what}: module_source is larger than {MAX_MODULE_SOURCE_BYTES} bytes")

    bound = require_list(
        widget.get("endpoints"), f"{what} endpoints", MAX_WIDGET_ENDPOINTS
    )
    endpoints: list[str] = []
    for entry in bound:
        if not isinstance(entry, str) or entry not in readable_ids:
            # Named rather than described: a write and an emission are both real
            # endpoints, and neither fills a tile, so "unknown" would be the
            # wrong word for the mistake somebody is most likely making.
            fail(f"{what}: binds {entry!r}, which is not a declared read endpoint")
        if entry not in endpoints:
            endpoints.append(entry)

    cleaned: dict[str, Any] = {
        "id": widget_id,
        "meta": meta,
        "module_source": module_source,
    }
    if endpoints:
        cleaned["endpoints"] = endpoints

    sample = _sample_data(widget.get("sample_data"), sources=endpoints, what=what)
    if sample:
        cleaned["sample_data"] = sample
    requires = _requires(
        widget.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _bundled_dashboard(
    raw: Any, *, widget_ids: set[str], readable_ids: set[str]
) -> dict[str, Any]:
    """One dashboard a plug-in ships with itself.

    A publisher who declares widgets otherwise leaves every guild to arrange
    them. This is a ready-made arrangement of *this plug-in's own* widgets, which
    becomes an ordinary ``dashboard`` catalog listing when the plug-in is published —
    so a guild installs it the same way it installs any other dashboard, and
    what it gets afterwards is an ordinary dashboard of its own.

    Two things make it different from a dashboard published on its own, and both
    are why it can be checked here at all:

    * **It names widgets by bare id.** A manifest has no uid inside it — the uid
      lives in the document envelope — so widget types are resolved to
      ``plugin:<uid>:<widget id>`` at publish, exactly as
      :func:`plugin_widget_type` already does for the palette. The publisher never
      writes a uid into a widget type, so the two cannot disagree.
    * **It can only reference this manifest.** Every widget and every bound
      source is checked against what the same document declares, so a bundled
      dashboard cannot name a widget the plug-in does not have — the failure a
      separately published dashboard can only hit at install, and silently.

    The ``uid`` and ``public_id`` are the publisher's own, and are what make the
    derived row a real catalog identity rather than something invented here.
    """
    entry = require_mapping(raw, "bundled dashboard")
    uid = check_uid(entry.get("uid"), what="bundled dashboard uid")
    public_id = check_public_id(
        entry.get("public_id"), what=f"bundled dashboard {uid} public_id"
    )
    what = f"bundled dashboard {public_id!r}"

    name = clean_text(entry.get("name"), what=f"{what} name", limit=MAX_NAME_LENGTH)
    if not name:
        fail(f"{what}: name is required")
    description = clean_text(
        entry.get("description"),
        what=f"{what} description",
        limit=MAX_DESCRIPTION_LENGTH,
        required=False,
    )

    widgets = [
        _bundled_dashboard_widget(
            widget, widget_ids=widget_ids, readable_ids=readable_ids, what=what
        )
        for widget in require_list(
            entry.get("widgets"), f"{what} widgets", MAX_DASHBOARD_WIDGETS
        )
    ]
    if not widgets:
        fail(f"{what}: a dashboard with no widgets shows nothing")

    seen: set[str] = set()
    for widget in widgets:
        if widget["id"] in seen:
            fail(f"{what}: two widgets share the id {widget['id']!r}")
        seen.add(widget["id"])

    cleaned: dict[str, Any] = {
        "uid": uid,
        "public_id": public_id,
        "name": name,
        "widgets": widgets,
    }
    if description is not None:
        cleaned["description"] = description

    columns = _grid_int(
        (entry.get("layout") or {}).get("columns")
        if isinstance(entry.get("layout"), dict)
        else None,
        low=1,
        high=MAX_DASHBOARD_GRID_COLUMNS,
        what=f"{what} layout.columns",
    )
    if columns is not None:
        cleaned["layout"] = {"columns": columns}
    return cleaned


def _bundled_dashboard_widget(
    raw: Any, *, widget_ids: set[str], readable_ids: set[str], what: str
) -> dict[str, Any]:
    """One tile, naming one of this plug-in's widgets and one of its sources."""
    widget = require_mapping(raw, f"{what} widget")
    widget_type = check_identifier(widget.get("type"), what=f"{what} widget type")
    if widget_type not in widget_ids:
        fail(f"{what}: names unknown widget {widget_type!r}")

    binding = require_mapping(widget.get("binding"), f"{what} widget binding")
    endpoint_id = binding.get("endpoint_id")
    if not isinstance(endpoint_id, str) or endpoint_id not in readable_ids:
        fail(f"{what}: binds {endpoint_id!r}, which is not a declared read endpoint")

    bound: dict[str, Any] = {"endpoint_id": endpoint_id}
    params = binding.get("params")
    if params is not None:
        bound["params"] = _bundled_binding_params(params, what=what)

    cleaned: dict[str, Any] = {
        # Defaulted from the widget it draws, so a publisher who ships one tile
        # per widget writes no ids at all.
        "id": check_identifier(
            widget.get("id") or widget_type, what=f"{what} widget id"
        ),
        "type": widget_type,
        "binding": bound,
    }

    title = clean_text(
        widget.get("title"),
        what=f"{what} widget title",
        limit=MAX_NAME_LENGTH,
        required=False,
    )
    if title is not None:
        cleaned["title"] = title

    grid = widget.get("grid")
    if isinstance(grid, dict):
        placed = {
            key: _grid_int(
                grid.get(key),
                low=0 if key in ("x", "y") else 1,
                high=MAX_DASHBOARD_GRID_COLUMNS if key in ("x", "w") else None,
                what=f"{what} widget grid.{key}",
            )
            for key in ("x", "y", "w", "h")
        }
        kept = {key: value for key, value in placed.items() if value is not None}
        if kept:
            cleaned["grid"] = kept
    return cleaned


def _bundled_binding_params(raw: Any, *, what: str) -> dict[str, Any]:
    """Fixed parameter values for a tile's source, kept as they are.

    Deliberately not coerced: the source's ``params_schema`` declares the type,
    and turning a ``true`` into a ``1`` here would satisfy a check the fetch path
    is meant to make.

    An array is one of the shapes, because an endpoint may declare a parameter
    ``list`` and a bundled tile is entitled to fix several values for it — the
    same shape a guild's own binding may hold, so a dashboard shipped with a
    plug-in and one built by hand can express the same things.
    """
    params = require_mapping(raw, f"{what} widget binding params")
    if len(params) > MAX_DASHBOARD_BINDING_PARAMS:
        fail(f"{what}: a binding carries at most {MAX_DASHBOARD_BINDING_PARAMS} params")

    def scalar(value: Any, *, named: str) -> Any:
        if isinstance(value, bool) or isinstance(value, int):
            return value
        if isinstance(value, str):
            return clean_text(
                value,
                what=f"{what} binding param {named}",
                limit=MAX_PARAM_VALUE_LENGTH,
            )
        fail(f"{what}: binding param {named!r} must be a string, integer or boolean")

    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        name = check_identifier(key, what=f"{what} binding param")
        if isinstance(value, list):
            if len(value) > MAX_BINDING_PARAM_VALUES:
                fail(
                    f"{what}: binding param {name!r} carries more than "
                    f"{MAX_BINDING_PARAM_VALUES} values"
                )
            cleaned[name] = [scalar(entry, named=name) for entry in value]
        else:
            cleaned[name] = scalar(value, named=name)
    return cleaned


def _grid_int(raw: Any, *, low: int, high: Optional[int], what: str) -> Optional[int]:
    """A grid coordinate, or ``None`` when the publisher left it to the canvas."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        fail(f"{what} must be a whole number")
    if raw < low or (high is not None and raw > high):
        bound = f"{low}..{high}" if high is not None else f"at least {low}"
        fail(f"{what} must be {bound}")
    return raw


def _sample_data(raw: Any, *, sources: list[str], what: str) -> dict[str, Any]:
    """What each source would answer with, so a preview renders with no call.

    Keyed by the sources the widget declared; anything else is dropped, so a
    sample cannot describe data the widget could never be handed.

    Each one is an endpoint's *result* — the same keys that endpoint declares it
    returns — because a preview is read through those returns exactly as a live
    answer is. Checked here rather than left opaque: a sample in any other shape
    projects to nothing, and an empty preview at a listing is a long way from
    the manifest that caused it.
    """
    if raw is None:
        return {}
    supplied = require_mapping(raw, f"{what} sample_data")
    allowed = set(sources)
    sample = {
        key: require_mapping(value, f"{what} sample_data for {key!r}")
        for key, value in supplied.items()
        if key in allowed
    }
    check_json_size(sample, what=f"{what} sample_data", limit=MAX_SAMPLE_DATA_BYTES)
    return sample


def _scopes(raw: Any, *, what: str) -> list[str]:
    """Where a surface asked to render, canonically.

    Absent means ``["community"]`` — the placement every page had before there was
    anywhere else to put one. Sorted and de-duplicated, so re-publishing the
    same manifest produces the same document.
    """
    if raw is None:
        return ["community"]
    declared = require_list(raw, f"{what} scopes", len(SURFACE_SCOPES))
    scopes: set[str] = set()
    for entry in declared:
        if entry not in SURFACE_SCOPES:
            fail(f"{what}: unknown scope {entry!r}")
        scopes.add(entry)
    if not scopes:
        fail(f"{what}: scopes names nowhere to render")
    return sorted(scopes)


def _capabilities(raw: Any, *, what: str) -> list[str]:
    """The browser features a surface asks its frame for.

    Absent means none, which is also what a frame gets when the manifest names
    nothing. Sorted and de-duplicated, so re-publishing the same manifest
    produces the same document.
    """
    if raw is None:
        return []
    declared = require_list(raw, f"{what} capabilities", MAX_PAGE_CAPABILITIES)
    capabilities: set[str] = set()
    for entry in declared:
        # Typed before it is looked up: set membership is defined only for a
        # hashable value, so a name is what this compares.
        if not isinstance(entry, str) or entry not in PAGE_CAPABILITIES:
            fail(
                f"{what}: {entry!r} is not a capability a page may request "
                f"(one of {', '.join(sorted(PAGE_CAPABILITIES))})"
            )
        capabilities.add(entry)
    return sorted(capabilities)


def _page(raw: Any, *, connection_ids: set[str]) -> dict[str, Any]:
    page = require_mapping(raw, "page")
    page_id = check_identifier(page.get("id"), what="page id")
    what = f"page {page_id!r}"

    _refuse_retired_audience(page, what=what)

    admin_only = _admin_only(page, what=what)

    cleaned: dict[str, Any] = {
        "id": page_id,
        "path": check_path(page.get("path"), what=f"{what} path"),
        "scopes": _scopes(page.get("scopes"), what=what),
        # Stored whichever way it was declared, so every pinned surface answers
        # the question the same way.
        "admin_only": admin_only,
        "name": _label(page.get("name"), what=what),
    }
    capabilities = _capabilities(page.get("capabilities"), what=what)
    if capabilities:
        cleaned["capabilities"] = capabilities
    requires = _requires(page.get("requires"), connection_ids=connection_ids, what=what)
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


# --- what a plug-in adds to items -------------------------------------------


def _item_kinds(raw: Any, *, what: str) -> list[str]:
    """The item kinds something is offered on, canonically: at least one, each
    named once, stored sorted."""
    declared = require_list(raw, f"{what} on", len(ITEM_KINDS))
    kinds: set[str] = set()
    for entry in declared:
        if not isinstance(entry, str) or entry not in ITEM_KINDS:
            fail(
                f"{what}: {entry!r} is not an item kind "
                f"(one of {', '.join(sorted(ITEM_KINDS))})"
            )
        if entry in kinds:
            fail(f"{what}: on names {entry!r} twice")
        kinds.add(entry)
    if not kinds:
        fail(f"{what}: on names no item kind")
    return sorted(kinds)


def _choice(raw: Any, allowed: frozenset[str], *, what: str) -> str:
    if not isinstance(raw, str) or raw not in allowed:
        fail(f"{what} must be one of {', '.join(sorted(allowed))}")
    return raw


def _flag(raw: Any, *, what: str) -> bool:
    if not isinstance(raw, bool):
        fail(f"{what} must be true or false")
    return raw


def _item_field(
    raw: Any,
    *,
    connection_ids: set[str],
    action_kinds: dict[str, list[str]],
    declarative: bool,
) -> dict[str, Any]:
    field = require_mapping(raw, "field")
    key = check_metadata_key(field.get("key"), what="field key")
    what = f"field {key!r}"
    kind = field.get("kind")
    if not isinstance(kind, str) or kind not in FIELD_KINDS:
        fail(f"{what}: kind must be one of {', '.join(sorted(FIELD_KINDS))}")
    cleaned: dict[str, Any] = {
        "key": key,
        "name": _label(field.get("name"), what=what),
        "kind": kind,
        "on": _item_kinds(field.get("on"), what=what),
    }
    # Stored only when it is, as admin_only is.
    if field.get("list") is not None and _flag(field["list"], what=f"{what} list"):
        if kind == "multi_select":
            fail(f"{what}: a multi_select field is several values already")
        cleaned["list"] = True
    if kind == "currency":
        cleaned["currency"] = _choice(
            field.get("currency"), _CURRENCIES, what=f"{what} currency"
        )
    if kind in ("select", "multi_select"):
        cleaned["options"] = _field_options(field.get("options"), what=what)
    description = localized_text(field.get("description"), MAX_TEXT_LENGTH)
    if description is not None:
        cleaned["description"] = description
    if field.get("tone") is not None:
        cleaned["tone"] = _choice(field["tone"], TONES, what=f"{what} tone")
    if field.get("states") is not None:
        cleaned["states"] = _states(field["states"], what=what)
    if field.get("actions") is not None:
        cleaned["actions"] = _element_actions(
            field["actions"],
            on=cleaned["on"],
            listed="list" in cleaned,
            action_kinds=action_kinds,
            declarative=declarative,
            what=what,
        )
    requires = _requires(
        field.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


#: The currencies a currency field may name.
_CURRENCIES = frozenset(CURRENCY_CODES)
#: What an option's value is written in: a letter or a digit, then those, ``_``
#: and ``-`` (``fieldOption``).
_OPTION_START = frozenset(string.ascii_letters + string.digits)
_OPTION_CHARS = _OPTION_START | {"_", "-"}
MAX_OPTION_VALUE_LENGTH = contract.cap("optionValueLength")


def _field_options(raw: Any, *, what: str) -> list[dict[str, Any]]:
    """A select or multi_select field's options: at least one and at most
    :data:`MAX_SELECT_OPTIONS`, each a value written in :data:`_OPTION_CHARS`
    at most once, its label, and a ``#rrggbb`` colour if it has one."""
    options = require_list(raw, f"{what} options", MAX_SELECT_OPTIONS)
    if not options:
        fail(f"{what}: a select field offers at least one option")
    cleaned: list[dict[str, Any]] = []
    for raw_option in options:
        option = require_mapping(raw_option, f"{what} option")
        value = option.get("value")
        if not (
            isinstance(value, str)
            and 0 < len(value) <= MAX_OPTION_VALUE_LENGTH
            and value[0] in _OPTION_START
            and set(value) <= _OPTION_CHARS
        ):
            fail(
                f"{what}: an option's value is a letter or a digit, then those, _ and -"
            )
        if any(kept["value"] == value for kept in cleaned):
            fail(f"{what}: two options share the value {value!r}")
        kept: dict[str, Any] = {
            "value": value,
            "label": _label(option.get("label"), what=f"{what} option {value!r}"),
        }
        color = option.get("color")
        if color is not None:
            if not (
                isinstance(color, str)
                and len(color) == 7
                and color[0] == "#"
                and set(color[1:]) <= set(string.hexdigits)
            ):
                fail(f"{what} option {value!r}: color must be #rrggbb")
            kept["color"] = color
        cleaned.append(kept)
    return cleaned


def _states(raw: Any, *, what: str) -> dict[str, Any]:
    """A field's states: at most :data:`MAX_FACETS` facets by id, each named,
    with at most :data:`MAX_FACET_VALUES` keys, each with its badge's words and
    tone."""
    facets = require_mapping(raw, f"{what} states")
    if not facets:
        fail(f"{what}: states names no facet")
    if len(facets) > MAX_FACETS:
        fail(f"{what}: states holds more than {MAX_FACETS} facets")
    cleaned: dict[str, Any] = {}
    for facet_id, raw_facet in facets.items():
        check_identifier(facet_id, what=f"{what} state")
        at = f"{what} state {facet_id!r}"
        facet = require_mapping(raw_facet, at)
        values = require_mapping(facet.get("values"), f"{at} values")
        if not values:
            fail(f"{at}: values names no key")
        if len(values) > MAX_FACET_VALUES:
            fail(f"{at}: values holds more than {MAX_FACET_VALUES} keys")
        kept: dict[str, Any] = {}
        for value_key, raw_value in values.items():
            check_identifier(value_key, what=f"{at} value")
            named = f"{at} value {value_key!r}"
            value = require_mapping(raw_value, named)
            kept[value_key] = {"label": _label(value.get("label"), what=named)}
            if value.get("tone") is not None:
                kept[value_key]["tone"] = _choice(
                    value["tone"], TONES, what=f"{named} tone"
                )
        cleaned[facet_id] = {"name": _label(facet.get("name"), what=at), "values": kept}
    return cleaned


def _element_actions(
    raw: Any,
    *,
    on: list[str],
    listed: bool,
    action_kinds: dict[str, list[str]],
    declarative: bool,
    what: str,
) -> list[str]:
    """The actions a list field offers on each of its elements: a declarative
    plug-in's, each declared and offered on every item kind the field is."""
    if not declarative:
        fail(
            f"{what}: a container plug-in's action is not told which element it "
            "was run from: its handler is handed the item alone"
        )
    if not listed:
        fail(
            f"{what}: actions are offered on a list's elements, and this field "
            "is not a list"
        )
    cleaned: list[str] = []
    for entry in require_list(raw, f"{what} actions", MAX_ACTIONS):
        action_id = check_identifier(entry, what=f"{what} action")
        kinds = action_kinds.get(action_id)
        if kinds is None:
            fail(f"{what}: {action_id!r} is not declared by this manifest")
        missing = [kind for kind in on if kind not in kinds]
        if missing:
            fail(
                f"{what}: {action_id!r} is not offered on {', '.join(missing)}, "
                "where this field is"
            )
        if action_id in cleaned:
            fail(f"{what}: actions names {action_id!r} twice")
        cleaned.append(action_id)
    if not cleaned:
        fail(f"{what}: actions names no action")
    return cleaned


def _action(
    raw: Any,
    *,
    service_public_id: str,
    endpoints: dict[str, dict[str, Any]],
    connection_ids: set[str],
    declarative: bool,
) -> dict[str, Any]:
    """One thing a reader runs on an item. A container's names the write
    endpoint its handler answers. A declarative plug-in's names an endpoint
    whose call Initiative makes (a read that fetches what its ``write`` keeps,
    or a write that changes something at the vendor), a ``write`` answering
    the change Initiative makes to the plug-in's values on the item, or
    both."""
    action = require_mapping(raw, "action")
    action_id = check_identifier(action.get("id"), what="action id")
    what = f"action {action_id!r}"
    if declarative:
        if action.get("endpoint") is None and action.get("write") is None:
            fail(
                f"{what}: a declarative plug-in's action names an endpoint, a write, or both"
            )
    else:
        if action.get("endpoint") is None:
            fail(
                f"{what}: a container plug-in's action names the write endpoint "
                "its handler answers"
            )
        if action.get("write") is not None:
            fail(f"{what}: a container plug-in's action is answered by its handler")
    cleaned: dict[str, Any] = {
        "id": action_id,
        "name": _label(action.get("name"), what=what),
    }
    if action.get("endpoint") is not None:
        endpoint = _endpoint_id(
            action["endpoint"],
            service_public_id=service_public_id,
            what=f"{what} endpoint",
        )
        # Initiative calls the endpoint for the reader. A container's does the
        # work, so it is a write; a declarative plug-in's ``write`` does the
        # work, so its endpoint may also be a read that fetches what the write
        # keeps. A run sends what the reader answered for the params the
        # action asks for, and nothing else, so a param the endpoint requires
        # is one the action asks for.
        declared = endpoints.get(endpoint)
        if declared is None:
            fail(f"{what}: names {endpoint!r}, which this manifest does not declare")
        if declared["direction"] not in (
            ("read", "write") if declarative else ("write",)
        ):
            fail(
                f"{what}: names {endpoint!r}, which is a {declared['direction']} endpoint"
            )
        cleaned["endpoint"] = endpoint
        asked: list[str] = []
        if action.get("params") is not None:
            # The endpoint's params the reader is asked for, each once.
            takes = {param["key"] for param in declared.get("params") or ()}
            for entry in require_list(
                action["params"], f"{what} params", MAX_PARAMS_PER_ENDPOINT
            ):
                key = check_identifier(entry, what=f"{what} param")
                if key not in takes:
                    fail(f"{what}: {key!r} is not a parameter of {endpoint!r}")
                if key in asked:
                    fail(f"{what}: params names {key!r} twice")
                asked.append(key)
            if not asked:
                fail(f"{what}: params names no parameter")
            cleaned["params"] = asked
        unasked = [
            param["key"]
            for param in declared.get("params") or ()
            if param.get("required") is True and param["key"] not in asked
        ]
        if unasked:
            fail(
                f"{what}: names {endpoint!r}, which requires "
                f"{', '.join(map(repr, unasked))}, which the action does not ask "
                "the reader for"
            )
    elif action.get("params") is not None:
        fail(
            f"{what}: an action asks for its endpoint's parameters, and names no "
            "endpoint"
        )
    if action.get("write") is not None:
        cleaned["write"] = _checked(action["write"], what=f"{what} write")
    cleaned["on"] = _item_kinds(action.get("on"), what=what)
    # Stored whichever way it was declared, so every pinned action answers
    # where it is offered the same way.
    cleaned["menu"] = (
        False
        if action.get("menu") is None
        else _flag(action["menu"], what=f"{what} menu")
    )
    # Stored only when it is, so an action published before the term reads the
    # same as one that left it out.
    if _admin_only(action, what=what):
        cleaned["admin_only"] = True
    if action.get("confirm") is not None:
        cleaned["confirm"] = _label(action["confirm"], what=f"{what} confirm")
    requires = _requires(
        action.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _part(
    raw: Any,
    *,
    field_kinds: dict[str, list[str]],
    action_kinds: dict[str, list[str]],
    connection_ids: set[str],
) -> dict[str, Any]:
    part = require_mapping(raw, "part")
    part_id = check_identifier(part.get("id"), what="part id")
    what = f"part {part_id!r}"
    on = _item_kinds(part.get("on"), what=what)
    cleaned: dict[str, Any] = {
        "id": part_id,
        "name": _label(part.get("name"), what=what),
        "on": on,
        "tree": _part_tree(
            part.get("tree"),
            on=on,
            field_kinds=field_kinds,
            action_kinds=action_kinds,
            what=what,
        ),
    }
    description = localized_text(part.get("description"), MAX_TEXT_LENGTH)
    if description is not None:
        cleaned["description"] = description
    requires = _requires(part.get("requires"), connection_ids=connection_ids, what=what)
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _part_tree(
    raw: Any,
    *,
    on: list[str],
    field_kinds: dict[str, list[str]],
    action_kinds: dict[str, list[str]],
    what: str,
) -> dict[str, Any]:
    """A part's tree of Initiative's components, each node closed, at most
    :data:`MAX_PART_NODES` of them and :data:`MAX_PART_DEPTH` deep.

    A field or a button names something this manifest declares, offered on
    every item kind the part is: one that is not would draw nothing there.
    """
    count = 0

    def offered(name: str, kinds: list[str] | None, *, block: str, at: str) -> None:
        if kinds is None:
            fail(f"{at}: names {name!r}, which is not one of this manifest's {block}")
        missing = [kind for kind in on if kind not in kinds]
        if missing:
            fail(
                f"{at}: {name!r} is not offered on {', '.join(missing)}, "
                "where this part is"
            )

    def node(raw: Any, depth: int, at: str) -> dict[str, Any]:
        nonlocal count
        count += 1
        if count > MAX_PART_NODES:
            fail(f"{what}: tree holds more than {MAX_PART_NODES} nodes")
        if depth > MAX_PART_DEPTH:
            fail(f"{at}: nested deeper than {MAX_PART_DEPTH}")
        entry = require_mapping(raw, at)
        node_type = entry.get("type")
        if not isinstance(node_type, str) or node_type not in PART_NODES:
            fail(f"{at}: type must be one of {', '.join(sorted(PART_NODES))}")
        unknown = sorted(set(entry) - PART_NODE_TERMS[node_type])
        if unknown:
            fail(f"{at}: {', '.join(map(repr, unknown))} is not a term of the contract")
        props = require_mapping(entry.get("props", {}), f"{at} props")
        unknown = sorted(set(props) - PART_NODE_PROPS[node_type])
        if unknown:
            fail(
                f"{at}: {', '.join(map(repr, unknown))} is not a prop of a {node_type}"
            )

        kept: dict[str, Any] = {}
        if node_type == "section":
            if props.get("title") is not None:
                kept["title"] = _label(props["title"], what=f"{at} title")
            if props.get("collapsed") is not None:
                kept["collapsed"] = _flag(props["collapsed"], what=f"{at} collapsed")
        elif node_type == "stack":
            if props.get("direction") is not None:
                kept["direction"] = _choice(
                    props["direction"], STACK_DIRECTIONS, what=f"{at} direction"
                )
            if props.get("gap") is not None:
                kept["gap"] = _choice(props["gap"], STACK_GAPS, what=f"{at} gap")
            if props.get("wrap") is not None:
                kept["wrap"] = _flag(props["wrap"], what=f"{at} wrap")
        elif node_type in ("field", "value"):
            key = check_metadata_key(props.get("field"), what=f"{at} field")
            offered(key, field_kinds.get(key), block="fields", at=at)
            kept["field"] = key
        elif node_type == "text":
            kept["text"] = _label(props.get("text"), what=f"{at} text")
            if props.get("tone") is not None:
                kept["tone"] = _choice(props["tone"], TONES, what=f"{at} tone")
        elif node_type == "button":
            action_id = check_identifier(props.get("action"), what=f"{at} action")
            offered(action_id, action_kinds.get(action_id), block="actions", at=at)
            kept["action"] = action_id
            if props.get("variant") is not None:
                kept["variant"] = _choice(
                    props["variant"], BUTTON_VARIANTS, what=f"{at} variant"
                )

        cleaned: dict[str, Any] = {"type": node_type}
        if kept:
            cleaned["props"] = kept
        if node_type in PART_CONTAINERS:
            children = [
                node(child, depth + 1, f"{at}.children.{index}")
                for index, child in enumerate(
                    require_list(
                        entry.get("children"), f"{at} children", MAX_PART_NODES
                    )
                )
            ]
            if children:
                cleaned["children"] = children
        return cleaned

    return node(raw, 1, f"{what} tree")


# --- the definition ---------------------------------------------------------


def plugin_widget_type(listing_uid: str, widget_id: str) -> str:
    """The type id a listing's widget is offered under.

    Namespaced with the catalog uid, so two plug-ins can both ship a ``summary``
    widget and neither can shadow a built-in type. ``:`` is outside the
    identifier character set, so the parts stay unambiguous — and the id is
    re-checked here, so that stays true wherever this is called from.
    """
    check_identifier(widget_id, what="widget id")
    return f"{PLUGIN_WIDGET_TYPE_PREFIX}{listing_uid}:{widget_id}"


def _service_block(raw: Any) -> dict[str, Any]:
    service = require_mapping(raw, "service plug-in: service")
    public_id = check_public_id(
        service.get("public_id"), what="service plug-in: service.public_id"
    )
    protocol = service.get("protocol", 1)
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        fail("service plug-in: service.protocol must be a whole number")
    if protocol not in PLUGIN_PROTOCOL_VERSIONS:
        fail(
            f"service plug-in: protocol {protocol} is not one this build speaks "
            f"({sorted(PLUGIN_PROTOCOL_VERSIONS)})"
        )
    cleaned: dict[str, Any] = {"public_id": public_id, "protocol": protocol}
    scopes = _requested_scopes(service.get("scopes"), where="service.scopes")
    if scopes:
        cleaned["scopes"] = scopes
    if service.get("calls_plugins") is not None and _flag(
        service["calls_plugins"], what="service plug-in: service.calls_plugins"
    ):
        cleaned["calls_plugins"] = True
    return cleaned


def _setting(raw: Any) -> dict[str, Any]:
    """A value the community's admins set on the install."""
    setting = require_mapping(raw, "setting")
    key = check_identifier(setting.get("key"), what="setting key")
    what = f"setting {key!r}"
    cleaned: dict[str, Any] = {
        "key": key,
        "type": _choice(setting.get("type"), SETTING_TYPES, what=f"{what} type"),
        "label": _label(setting.get("label"), what=what),
    }
    description = localized_text(setting.get("description"), MAX_TEXT_LENGTH)
    if description is not None:
        cleaned["description"] = description
    if setting.get("unique") is not None and _flag(
        setting["unique"], what=f"{what} unique"
    ):
        cleaned["unique"] = True
    if setting.get("assigned") is not None:
        if "unique" not in cleaned:
            fail(f"{what}: only a unique setting's value is assigned")
        cleaned["assigned"] = _choice(
            setting["assigned"], SETTING_ASSIGNMENTS, what=f"{what} assigned"
        )
    return cleaned


def _help(raw: Any) -> dict[str, str]:
    """Help with the plug-in, in markdown, by language: at most
    :data:`MAX_HELP_LENGTH` characters in each."""
    for language, text in require_mapping(raw, "service plug-in: help").items():
        if isinstance(text, str) and len(text.strip()) > MAX_HELP_LENGTH:
            fail(
                f"service plug-in: help in {language!r} is longer than "
                f"{MAX_HELP_LENGTH} characters"
            )
    text = localized_text(raw, MAX_HELP_LENGTH)
    if text is None:
        fail("service plug-in: help says nothing in any language")
    return text


def _requested_scopes(raw: Any, *, where: str) -> list[str]:
    """The scopes a plug-in asks a community to grant, canonically: a
    container's ``service.scopes``, or a declarative plug-in's ``scopes``.

    Absent means none. Each must be in the vocabulary, or a ``plugins:`` scope
    naming another plug-in's public id, and named once; stored sorted, so
    re-publishing the same manifest produces the same document.
    """
    if raw is None:
        return []
    declared = require_list(
        raw, f"service plug-in: {where}", len(ALL_SCOPES) + MAX_PLUGIN_SCOPES
    )
    scopes: set[str] = set()
    plugin_scopes = 0
    for entry in declared:
        # Typed before it is looked up: set membership is defined only for a
        # hashable value.
        if not isinstance(entry, str):
            fail(f"service plug-in: {entry!r} is not a scope a plug-in may request")
        if plugin_scope_target(entry) is not None:
            plugin_scopes += 1
        elif entry not in ALL_SCOPES:
            fail(f"service plug-in: {entry!r} is not a scope a plug-in may request")
        if entry in scopes:
            fail(f"service plug-in: {where} names {entry!r} twice")
        scopes.add(entry)
    if plugin_scopes > MAX_PLUGIN_SCOPES:
        fail(f"service plug-in: {where} names more than {MAX_PLUGIN_SCOPES} plug-ins")
    return sorted(scopes)


def _features(raw: Any) -> list[str]:
    declared = require_list(raw, "service plug-in: features", len(FEATURES))
    features: set[str] = set()
    for entry in declared:
        if entry not in FEATURES:
            fail(f"service plug-in: unknown feature {entry!r}")
        features.add(entry)
    # Sorted, so a re-publish of the same manifest produces the same document.
    return sorted(features)


def _check_features(features: list[str], cleaned: dict[str, Any]) -> None:
    """Both directions, because either mismatch is a manifest that lies.

    A feature declared with no block behind it would advertise something the plug-in
    cannot do; a block with no feature declared would ship a capability the
    install dialog never disclosed and review never looked at.
    """
    declared = set(features)
    for feature, block in FEATURE_BLOCKS.items():
        # Membership, not truthiness: whether a block was stored is the question,
        # and reading it as a value would let a stored-but-empty block count as
        # absent here while still being persisted.
        present = block in cleaned
        if feature in declared and not present:
            fail(
                f"service plug-in: the {feature!r} feature is declared but "
                f"{block} is missing"
            )
        if present and feature not in declared:
            fail(
                f"service plug-in: {block} is present but the {feature!r} feature "
                "is not declared"
            )


def _check_option_sources(
    endpoints: list[dict[str, Any]], *, readable_ids: set[str]
) -> None:
    """Every ``options_from`` against the endpoint it names.

    Three things have to hold, and each of them fails silently downstream:

    * the endpoint is one this manifest declares — an id from another plug-in is a
      cross-plugin read with no consent story behind it;
    * it *reads*, because filling in a form must not write anything;
    * the keys it names are returns of that endpoint, and are lists. One value
      cannot be a menu, and a caller asking for options would get a scalar it
      has nowhere to put;
    * every ``needs`` entry joins a parameter that endpoint takes to one this
      endpoint declares — and never to this parameter itself, which would ask
      for the answer being filled in.
    """
    returns_by_id = {
        endpoint["id"]: {value["key"]: value for value in endpoint.get("returns") or []}
        for endpoint in endpoints
    }
    params_by_id = {
        endpoint["id"]: {param["key"] for param in endpoint.get("params") or []}
        for endpoint in endpoints
    }

    for endpoint in endpoints:
        for param in endpoint.get("params") or []:
            source = param.get("options_from")
            if not source:
                continue
            what = f"service plug-in: endpoint {endpoint['id']!r} parameter {param['key']!r}"
            named = source["endpoint"]

            if named not in returns_by_id:
                fail(
                    f"{what}: options_from names {named!r}, which is not declared here"
                )
            if named not in readable_ids:
                fail(f"{what}: options_from names {named!r}, which does not read")

            for field in ("key", "label_key"):
                key = source.get(field)
                if key is None:
                    continue
                value = returns_by_id[named].get(key)
                if value is None:
                    fail(
                        f"{what}: options_from {field} {key!r} is not returned by {named!r}"
                    )
                if value.get("list") is not True:
                    fail(
                        f"{what}: options_from {field} {key!r} is a single value — "
                        "options come from a list"
                    )

            for theirs, ours in (source.get("needs") or {}).items():
                if theirs not in params_by_id.get(named, set()):
                    fail(
                        f"{what}: options_from needs {theirs!r}, "
                        f"which {named!r} does not take"
                    )
                if ours == param["key"]:
                    fail(
                        f"{what}: options_from needs {ours!r}, "
                        "which is the parameter being filled in"
                    )
                if ours not in params_by_id.get(endpoint["id"], set()):
                    fail(
                        f"{what}: options_from needs {ours!r}, "
                        "which this endpoint does not declare"
                    )


def normalize_service_plugin_definition(
    definition: Any, *, public_id: Optional[str] = None
) -> dict[str, Any]:
    """Validate and canonicalize a service plug-in's definition.

    A container plug-in names itself in its ``service`` block, and the scopes it
    asks for there. A declarative plug-in has none, and is named by its
    listing's ``public_id``, which its endpoints are namespaced under; it asks
    for read scopes, at the top of its manifest. One plug-in is never both.
    """
    body = require_mapping(definition, "service plug-in definition")

    declarative = body.get("service") is None
    service: dict[str, Any] | None = None
    hosts: list[str] = []
    auth: dict[str, str] | None = None
    scopes: list[str] = []
    if declarative:
        if public_id is None:
            fail("service plug-in: a declarative plug-in is named by its listing")
        plugin_public_id = check_public_id(public_id, what="service plug-in: public_id")
        hosts = _hosts(body.get("hosts"))
        if not hosts:
            fail("service plug-in: a declarative plug-in names the hosts it calls")
        if body.get("auth") is not None:
            auth = _auth(body["auth"])
        if body.get("pages") is not None:
            fail(
                "service plug-in: a declarative plug-in has no pages; a page is "
                "served by a container"
            )
        scopes = _requested_scopes(body.get("scopes"), where="scopes")
        if any(not scope.endswith(":read") for scope in scopes):
            fail(
                "service plug-in: a declarative plug-in asks only for read scopes: "
                "it keeps its own values on items it can read, and does not call "
                "Initiative"
            )
    else:
        service = _service_block(body.get("service"))
        plugin_public_id = service["public_id"]
        for term in ("hosts", "auth"):
            if body.get(term) is not None:
                fail(
                    f"service plug-in: {term!r} is a declarative plug-in's term; a "
                    "container plug-in makes its own calls"
                )
        if body.get("scopes") is not None:
            fail(
                "service plug-in: a container plug-in declares its scopes in its "
                "service block"
            )
    auth_header = (auth or {}).get("header", DEFAULT_AUTH_HEADER)
    vendor = _vendor(body.get("vendor"))
    vendor_keys = {field["key"] for field in (vendor or {}).get("fields", [])}

    connections = [
        _connection(
            entry,
            vendor_keys=vendor_keys,
            declarative=declarative,
            auth_header=auth_header,
        )
        for entry in require_list(
            body.get("connections"), "service plug-in: connections", MAX_CONNECTIONS
        )
    ]
    connection_ids: set[str] = set()
    for connection in connections:
        if connection["id"] in connection_ids:
            fail(f"service plug-in: two connections share the id {connection['id']!r}")
        connection_ids.add(connection["id"])
    webhooks = _webhooks(
        body.get("webhooks"),
        vendor_keys=vendor_keys,
        connections=connections,
        declarative=declarative,
    )

    # One list for every direction, so a caller resolves an id without being
    # told which kind of thing it is first.
    endpoints = [
        _endpoint(
            entry,
            connection_ids=connection_ids,
            service_public_id=plugin_public_id,
            declarative=declarative,
            auth_header=auth_header,
            interactive_ids=frozenset(
                entry["id"] for entry in connections if entry["scope"] == "interactive"
            ),
        )
        for entry in require_list(
            body.get("endpoints"), "service plug-in: endpoints", MAX_ENDPOINTS
        )
    ]
    endpoint_ids: set[str] = set()
    readable_ids: set[str] = set()
    for endpoint in endpoints:
        if endpoint["id"] in endpoint_ids:
            fail(f"service plug-in: two endpoints share the id {endpoint['id']!r}")
        endpoint_ids.add(endpoint["id"])
        if endpoint["direction"] in WIDGET_BINDABLE_DIRECTIONS:
            readable_ids.add(endpoint["id"])
    emits = {
        endpoint["id"] for endpoint in endpoints if endpoint["direction"] == "emit"
    }
    for index, event in enumerate((webhooks or {}).get("events", [])):
        if "emit" in event and event["emit"] not in emits:
            fail(
                f"service plug-in: webhooks.events.{index} emits {event['emit']!r}, "
                "which is not an emit endpoint this plug-in declares"
            )
    by_id = {endpoint["id"]: endpoint for endpoint in endpoints}
    # After the endpoints, because a declarative plug-in's schedule names one.
    schedules = _schedules(
        body.get("schedules"),
        declarative=declarative,
        service_public_id=plugin_public_id,
        endpoints=by_id,
        connection_ids=connection_ids,
    )

    # A parameter naming where its values come from, checked once every endpoint
    # is known. Nothing downstream refuses a bad one: a form asks this
    # deployment to resolve it, no such return is found, and the form offers
    # nothing — which is indistinguishable from a vendor being slow.
    _check_option_sources(endpoints, readable_ids=readable_ids)

    widgets = [
        _widget(entry, readable_ids=readable_ids, connection_ids=connection_ids)
        for entry in require_list(
            body.get("widgets"), "service plug-in: widgets", MAX_WIDGETS
        )
    ]
    widget_ids: set[str] = set()
    for widget in widgets:
        if widget["id"] in widget_ids:
            fail(f"service plug-in: two widgets share the id {widget['id']!r}")
        widget_ids.add(widget["id"])

    pages = [
        _page(entry, connection_ids=connection_ids)
        for entry in require_list(
            body.get("pages"), "service plug-in: pages", MAX_PAGES
        )
    ]
    page_ids: set[str] = set()
    for page in pages:
        if page["id"] in page_ids:
            fail(f"service plug-in: two pages share the id {page['id']!r}")
        page_ids.add(page["id"])

    actions = [
        _action(
            entry,
            service_public_id=plugin_public_id,
            endpoints=by_id,
            connection_ids=connection_ids,
            declarative=declarative,
        )
        for entry in require_list(
            body.get("actions"), "service plug-in: actions", MAX_ACTIONS
        )
    ]
    action_kinds: dict[str, list[str]] = {}
    for action in actions:
        if action["id"] in action_kinds:
            fail(f"service plug-in: two actions share the id {action['id']!r}")
        action_kinds[action["id"]] = action["on"]

    # After the actions, because a list field's elements offer them.
    fields = [
        _item_field(
            entry,
            connection_ids=connection_ids,
            action_kinds=action_kinds,
            declarative=declarative,
        )
        for entry in require_list(
            body.get("fields"), "service plug-in: fields", MAX_FIELDS
        )
    ]
    field_kinds: dict[str, list[str]] = {}
    for field in fields:
        if field["key"] in field_kinds:
            fail(f"service plug-in: two fields share the key {field['key']!r}")
        field_kinds[field["key"]] = field["on"]

    settings = [
        _setting(entry)
        for entry in require_list(
            body.get("settings"), "service plug-in: settings", MAX_SETTINGS
        )
    ]
    setting_keys: set[str] = set()
    for setting in settings:
        if setting["key"] in setting_keys:
            fail(f"service plug-in: two settings share the key {setting['key']!r}")
        setting_keys.add(setting["key"])

    # After the fields and actions, because a part's nodes name them.
    parts = [
        _part(
            entry,
            field_kinds=field_kinds,
            action_kinds=action_kinds,
            connection_ids=connection_ids,
        )
        for entry in require_list(
            body.get("parts"), "service plug-in: parts", MAX_PARTS
        )
    ]
    part_ids: set[str] = set()
    for part in parts:
        if part["id"] in part_ids:
            fail(f"service plug-in: two parts share the id {part['id']!r}")
        part_ids.add(part["id"])

    cleaned: dict[str, Any] = {
        "plugin_kind": "service",
        "features": _features(body.get("features")),
    }
    if service is not None:
        cleaned["service"] = service
    else:
        cleaned["hosts"] = hosts
        if auth is not None:
            cleaned["auth"] = auth
        if scopes:
            cleaned["scopes"] = scopes
    # Empty blocks are left out entirely, so "does this plug-in offer widgets?" has
    # one answer rather than two shapes that mean the same thing.
    if vendor is not None:
        cleaned["vendor"] = vendor
    if connections:
        cleaned["connections"] = connections
    if webhooks is not None:
        cleaned["webhooks"] = webhooks
    if schedules:
        cleaned["schedules"] = schedules
    if endpoints:
        cleaned["endpoints"] = endpoints
    if widgets:
        cleaned["widgets"] = widgets
    if pages:
        cleaned["pages"] = pages
    if fields:
        cleaned["fields"] = fields
    if parts:
        cleaned["parts"] = parts
    if actions:
        cleaned["actions"] = actions
    if settings:
        cleaned["settings"] = settings
    if body.get("help") is not None:
        cleaned["help"] = _help(body["help"])

    # After the widgets and endpoints it can name, because every tile is checked
    # against them — the whole point of bundling rather than publishing
    # separately is that this cross-check is possible at all.
    dashboards = [
        _bundled_dashboard(entry, widget_ids=widget_ids, readable_ids=readable_ids)
        for entry in require_list(
            body.get("dashboards"),
            "service plug-in: dashboards",
            MAX_BUNDLED_DASHBOARDS,
        )
    ]
    if dashboards:
        seen_uids: set[str] = set()
        seen_public_ids: set[str] = set()
        for dashboard in dashboards:
            # Checked here as well as by the catalog: these become listing rows
            # whose identities are unique, and a manifest that collides with
            # itself would fail halfway through a publish.
            if dashboard["uid"] in seen_uids:
                fail(
                    f"service plug-in: two dashboards share the uid {dashboard['uid']}"
                )
            if dashboard["public_id"] in seen_public_ids:
                fail(
                    "service plug-in: two dashboards share the public_id "
                    f"{dashboard['public_id']!r}"
                )
            if dashboard["public_id"] == plugin_public_id:
                fail(
                    f"service plug-in: dashboard {dashboard['uid']} uses the plug-in's own "
                    "public_id; a bundled dashboard is its own listing"
                )
            seen_uids.add(dashboard["uid"])
            seen_public_ids.add(dashboard["public_id"])
        cleaned["dashboards"] = dashboards

    # After the endpoints, because it names one of them. A summary is a read:
    # it reports where this community stands, and a deployment that renders it is
    # drawing an answer, not asking the plug-in to do anything.
    summary = body.get("community_summary")
    if summary is not None:
        summary_id = _endpoint_id(
            summary,
            service_public_id=plugin_public_id,
            what="service plug-in: community_summary",
        )
        if summary_id not in readable_ids:
            fail(
                f"service plug-in: community_summary names {summary_id!r}, which is not "
                "an endpoint this plug-in answers reads on"
            )
        cleaned["community_summary"] = summary_id

    default_name = clean_text(
        body.get("default_name"),
        what="service plug-in: default_name",
        limit=MAX_NAME_LENGTH,
        required=False,
    )
    if default_name is not None:
        cleaned["default_name"] = default_name

    minimum_age = _minimum_age(body.get("minimum_age"))
    if minimum_age is not None:
        cleaned["minimum_age"] = minimum_age

    # The oldest plug-in API contract the plug-in calls. The catalog decides from
    # it whether this deployment serves the version; kept here so the stored
    # definition still says what its author asked for.
    try:
        min_plugin_api = plugin_api.check_min_plugin_api(body.get("min_plugin_api"))
    except ValueError as exc:
        fail(f"service plug-in: {exc}")
    if min_plugin_api is not None:
        cleaned["min_plugin_api"] = min_plugin_api

    _check_features(cleaned["features"], cleaned)
    check_json_size(
        cleaned,
        what="service plug-in definition",
        limit=MAX_SERVICE_DEFINITION_BYTES,
    )
    return cleaned
