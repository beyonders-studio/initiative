"""What the widget data plane sends back.

Two payloads, and the difference between them is the point.

:class:`PluginDataResponse` is the plug-in's own answer, read through the returns its
endpoint declares: the ones holding several become rows, the ones holding a
single value stay whole beside them. The projection is by name alone — nothing
here interprets a value, and the manifest is the only thing that says what the
names are.

:class:`PluginWidgetCatalogResponse` is what a dashboard needs before it can bind
anything: which installed plug-ins offer widgets, which sources each widget draws,
and the module the browser will run in its sandbox. It is read off each
install's **pinned** definition, so a canvas is authored against the version the
guild chose rather than whatever the catalog says today.

:class:`PluginActionRun` runs one of a plug-in's
actions on an item, and :class:`PluginActionResult` is the item's values for
that plug-in afterwards.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


from pydantic import Field

from app.core.tools import ITEM_KINDS
from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.schemas.sql_query import QueryColumnDescription


class PluginDataTable(SanitizedBaseModel):
    """Rows a statement produced, and what they hold.

    Positional against ``columns`` rather than keyed by name, for the reason
    every other read of this surface is: a statement may name two outputs the
    same thing, and a mapping would keep one of the two.
    """

    columns: List[QueryColumnDescription] = []
    rows: List[List[Any]] = []


class PluginSummaryReturn(SanitizedBaseModel):
    """One figure a plug-in's community summary declares: its key, its type,
    the plug-in's own label for it, and what it is counted against."""

    key: str
    type: str
    label: Optional[Dict[str, str]] = None
    list: bool = False
    of: Optional[str] = None


class PluginSummaryRead(SanitizedBaseModel):
    """An installed plug-in that says where the community stands with it."""

    plugin_id: int
    #: The install's name, which the community chose.
    name: str
    returns: List[PluginSummaryReturn] = []


class PluginSummaryListResponse(SanitizedBaseModel):
    items: List[PluginSummaryRead] = []


class PluginDataResponse(SanitizedBaseModel):
    """One data source's answer, in the two shapes its endpoint declared."""

    #: One entry per index across the endpoint's ``list`` returns, read side by
    #: side. Values are carried as the plug-in sent them — the widget sandbox
    #: receives them as data, never as markup.
    rows: List[Dict[str, Any]] = []
    #: The endpoint's single-valued returns: what the answer says about itself
    #: rather than about any one item in it, and still there when there are no
    #: items at all.
    #: What a statement made of those rows, where the binding carried one.
    #: Absent otherwise: a plug-in's own rows are read by the names its manifest
    #: declared, and its widget module already knows them.
    table: Optional["PluginDataTable"] = None
    values: Dict[str, Any] = {}
    #: When the *upstream* call happened. A cached body keeps the time it was
    #: actually obtained, so a viewer can tell how fresh the answer is rather
    #: than how recently they asked.
    fetched_at: datetime
    #: True when this body came from the response cache.
    cached: bool = False


class PluginParamOptionSource(SanitizedBaseModel):
    """Where a parameter's permitted values come from, when only the plug-in knows.

    A repository, a label, a board: every one of them differs per install,
    changes after it, and can be enumerated only by the plug-in holding that
    install's credential — so none can be written into a manifest, which is
    published once and identical on every deployment. The manifest names a read
    of the plug-in's own instead, and this is that naming, carried through to
    whoever draws the control.
    """

    #: A ``read`` endpoint the same plug-in declares.
    endpoint: str
    #: Which of its returns holds the values. Always one of its ``list``
    #: returns — a menu comes from a column, not from a single value.
    key: str
    #: A second return holding what a person reads, where the value is opaque.
    label_key: Optional[str] = None
    #: What to send that endpoint, as one of ITS parameter names to one of the
    #: parameters this same form collects. A repository's labels are that
    #: repository's, so the source has to be told which one was chosen.
    needs: Dict[str, str] = {}


class PluginDataParam(SanitizedBaseModel):
    """One parameter an endpoint accepts, from its ``params``."""

    key: str
    type: str
    label: Dict[str, str] = {}
    required: bool = False
    options: Optional[List[str]] = None
    #: Where to fill a menu from, for the values only the plug-in can enumerate.
    #: A control is still the consumer's to draw — this says what the values
    #: are, not what to draw for them.
    options_from: Optional[PluginParamOptionSource] = None
    #: Whether the parameter takes several values. A fact about the value
    #: rather than about a control, and not inferable: whether to send one
    #: value or an array is the plug-in's to state.
    list: bool = False


class PluginDataReturn(SanitizedBaseModel):
    """One thing an endpoint hands back, from its ``returns``.

    Declared rather than discovered, because a consumer binds one of these
    before the endpoint has ever run. The ones marked ``list`` are what become
    the rows — so they are also the columns a statement over those rows may
    name.
    """

    key: str
    type: str
    label: Dict[str, str] = {}
    #: Whether it holds several. The ones that do are read side by side into
    #: rows; the ones that do not describe the answer rather than any item in
    #: it, and stay whole beside them.
    list: bool = False


class PluginEndpointRead(SanitizedBaseModel):
    """A read endpoint a widget may bind to.

    Reads only. A write and an emission are both real endpoints and neither
    fills a tile, so neither belongs in a widget picker.
    """

    id: str
    #: Read by the community's admins alone — enforced again on every fetch
    #: under the caller's own session, so this is what the picker shows rather
    #: than what protects the data.
    admin_only: bool = False
    #: What the manifest asks for, already clamped at publish time. The proxy
    #: applies the deployment's own ceiling on top.
    cache_ttl_seconds: int = 0
    params: List[PluginDataParam] = []
    #: What it hands back. A widget binds against this, and a statement over
    #: its rows is checked against it.
    returns: List[PluginDataReturn] = []


class PluginWidgetRead(SanitizedBaseModel):
    """One widget an installed plug-in contributes."""

    #: Namespaced ``plugin:<listing_uid>:<widget_id>``, so a plug-in's widget can
    #: never resolve to a built-in renderer or the other way round.
    type: str
    id: str
    #: The widget's own strings, in every language its author supplied.
    meta: Dict[str, Any] = {}
    #: The browser-side module. Opaque and carried verbatim: it is JavaScript,
    #: already size-capped by the manifest validator, and passing it through the
    #: plain-text sanitizer would rewrite operators like ``a < b`` into
    #: something that no longer parses. Nothing on this side reads, compiles, or
    #: evaluates it — the browser's sandbox is the only thing that runs it.
    module_source: RawTextStr
    #: Which of the plug-in's read endpoints this widget draws.
    endpoints: List[str] = []
    #: What a preview draws instead of calling anything, keyed by endpoint id
    #: and projected through that endpoint's returns exactly as a live answer
    #: is — so a listing's tile and an installed one are the same widget.
    sample_data: Dict[str, Any] = {}


class PluginWidgetCatalogEntry(SanitizedBaseModel):
    """One installed plug-in's contribution to the widget palette."""

    plugin_id: int
    plugin_uid: str = Field(max_length=14)
    name: str
    enabled: bool = True
    widgets: List[PluginWidgetRead] = []
    endpoints: List[PluginEndpointRead] = []


class PluginWidgetCatalogResponse(SanitizedBaseModel):
    items: List[PluginWidgetCatalogEntry] = []


class PluginParamOption(SanitizedBaseModel):
    """One value a parameter permits."""

    value: str
    #: What a person reads, when the value itself is opaque. Absent means the
    #: value is its own label.
    label: Optional[str] = None


class PluginParamOptionsResponse(SanitizedBaseModel):
    """The menu for one parameter, or why there is not one.

    ``unavailable`` is never an error. A source that will not resolve — the plug-in
    is down, a credential nobody has connected, a sibling not yet chosen — must
    leave the parameter **enterable**, because a control disabled on those
    grounds has made a valid configuration unreachable. A consumer draws a menu
    when there is one and a text field when there is not.
    """

    options: List[PluginParamOption] = []
    #: ``no-source``, ``needs-sibling`` or ``unresolved``.
    unavailable: Optional[str] = None


ItemKind = Enum("ItemKind", {name: name for name in ITEM_KINDS}, type=str)
ItemKind.__doc__ = "A kind of item a plug-in's fields and actions are offered on."


class PluginActionRun(SanitizedBaseModel):
    """The item to run an action on, and what the reader gave the action."""

    entity_type: ItemKind
    entity_id: int
    #: What the reader answered, by key, for the parameters the action asks
    #: for; nothing else is taken.
    params: Optional[Dict[str, Any]] = None
    #: The ``ref`` of the list element the action was run from, when it was.
    element: Optional[str] = None


class PluginActionResult(SanitizedBaseModel):
    """The values the plug-in shows on the item after its action, by key."""

    values: Dict[str, Any]
