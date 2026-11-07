from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from app.models.tenant.dashboard import DashboardViewMode
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.query import PageMeta

from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.services.fields.spec import FieldType
from app.schemas.tenant.tool import ToolSummaryBase
from app.services.tenant.dashboard_definition import (
    TABULAR_SOURCES,
    WIDGET_PRESETS,
    WIDGET_SPECS,
    OptionKind,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


# Derived from the widget registry rather than restated, the way TagTarget
# derives from TAG_TARGETS: a new primitive reaches the API — and, through the
# generated types, the frontend's drift test — without an edit here.
WidgetType = Enum("WidgetType", {name: name for name in sorted(WIDGET_SPECS)}, type=str)
WidgetType.__doc__ = "Widget primitives this build has renderers for."

BindingSource = Enum(
    "BindingSource", {name: name for name in sorted(TABULAR_SOURCES)}, type=str
)
BindingSource.__doc__ = "Data sources a widget binding may name."


class DashboardBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class DashboardCreate(DashboardBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    tag_ids: Optional[List[int]] = None
    # Install from the marketplace instead of authoring: name a catalog listing
    # by its uid and the server resolves it, taking the definition from the
    # catalog row and pinning the version. Nothing about the body below is read
    # when this is set — an installed definition is never client-supplied.
    listing_uid: Optional[str] = Field(default=None, max_length=14)
    # The canvas body. Validated + canonicalized by
    # ``dashboard_definition.normalize_dashboard_definition`` before it is
    # stored, so only known widget/binding vocabulary ever lands in the row.
    # Defaults to an empty canvas the author fills in.
    definition: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class DashboardInstalledListings(SanitizedBaseModel):
    """How many dashboards in this guild came from each marketplace listing.

    Keyed by listing uid, because that is what an install pins. Answered here
    rather than by the catalog: which listings a guild has is guild data, and the
    catalog holds none of it. Small and unpaginated by construction — one entry
    per distinct listing, not per dashboard — so a browse surface can mark what
    is already installed without walking the dashboard list.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: Dict[str, int] = Field(default_factory=dict)


class DashboardUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    # Absent = unchanged. Sending either re-runs validation over the pair, so
    # config can never outlive the widgets it configures.
    definition: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class DashboardPreview(SanitizedBaseModel):
    """A dashboard as a list's card draws it: its canvas alone. Every widget
    draws from sample data there, so a list runs none of their queries."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    definition: Dict[str, Any]
    config: Dict[str, Any]


class DashboardSummary(DashboardBase, ToolSummaryBase):
    # Marketplace provenance; both null for a dashboard authored from scratch.
    listing_uid: Optional[str] = None
    listing_version: Optional[str] = None
    #: Whose access the query widgets answer from: each viewer's own, or full
    #: read access to the initiative, the same for everyone.
    view_mode: DashboardViewMode = DashboardViewMode.individual
    #: The canvas, when the list was asked for previews.
    preview: Optional[DashboardPreview] = None


class DashboardListResponse(PageMeta):
    items: List[DashboardSummary]


class DashboardRead(DashboardSummary):
    # The canvas body is only sent on the detail read — a list of dashboards
    # doesn't render widgets, and definitions are the largest field here.
    definition: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    #: Whether the reader may set this dashboard to run as its initiative, or
    #: change its widgets while it does: an initiative manager, a community
    #: admin, or a role holding ``dashboards_run_as_initiative``.
    can_run_as_initiative: bool = False

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        # Local imports avoid a schema -> service import cycle.
        from app.db.guild_standing import GuildContext
        from app.services.tenant import view_as

        return {
            **super().derived_fields(row, context=context, user_id=user_id),
            "can_run_as_initiative": isinstance(context, GuildContext)
            and view_as.may_run_as_initiative(context, row.initiative_id),
        }


class DashboardViewModeRequest(SanitizedBaseModel):
    mode: DashboardViewMode


class DashboardWidgetData(SanitizedBaseModel):
    """One widget's answer when its canvas is loaded: a statement's rows, a
    plug-in widget's rows and values, or the code it was refused with.
    Exactly one is set."""

    result: Optional["QueryResponse"] = None
    plugin: Optional["PluginDataResponse"] = None
    error: Optional[str] = None


class DashboardDataResponse(SanitizedBaseModel):
    """Every widget on a canvas that reads data, answered together, keyed by
    widget id."""

    #: The initiative the canvas reads, so a client knows which changes make
    #: these answers stale.
    initiative_id: int
    widgets: Dict[str, DashboardWidgetData]


from app.schemas.sql_query import QueryResponse  # noqa: E402
from app.schemas.tenant.plugin_data import PluginDataResponse  # noqa: E402

DashboardWidgetData.model_rebuild()


# --- widget catalog --------------------------------------------------------
#
# What the editor's palette needs to know about each widget: how small it may
# be placed, what it can bind to, and which display options it takes. It is a
# projection of WIDGET_SPECS, served rather than duplicated, so the frontend
# never carries a second copy of the vocabulary.


class WidgetOption(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    #: In the order the palette should offer them, not sorted — a time scale
    #: reads day → quarter, and alphabetical ordering would scatter it.
    values: List[str]
    #: What the widget draws when a definition names no value for this option.
    #: Served rather than guessed at, so the editor's pre-selected entry is the
    #: one that will actually be drawn.
    default: str
    #: ``choice`` picks one of ``values``; ``number`` and ``date`` take a value
    #: of their own (a target, its day) and are empty until one is given.
    kind: OptionKind = "choice"


class WidgetSlot(SanitizedBaseModel):
    """One column a widget needs, and what may fill it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    #: The field types this slot accepts, so a client can offer only the
    #: columns that fit it.
    types: List[FieldType]
    required: bool = True
    #: Whether several columns may fill it — a chart's measures are a series
    #: each.
    repeatable: bool = False


class WidgetCatalogEntry(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: WidgetType  # type: ignore[valid-type]
    min_w: int
    min_h: int
    default_w: int
    default_h: int
    #: The columns this widget draws, in the order it reads them. Empty means it
    #: draws whatever it is given. A client matches a query's described columns
    #: against these to decide which widgets can render it, and to fill the
    #: pickers that let an author override the match.
    shape: List[WidgetSlot] = Field(default_factory=list)
    options: List[WidgetOption] = Field(default_factory=list)


class WidgetPresetEntry(SanitizedBaseModel):
    """A named widget built from a primitive plus fixed options — the palette's
    ready-made entries ("Bar chart"), and later the shape a listing uses to
    contribute its own."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    primitive: WidgetType  # type: ignore[valid-type]
    options: Dict[str, str] = Field(default_factory=dict)


class WidgetCatalog(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    widgets: List[WidgetCatalogEntry]
    presets: List[WidgetPresetEntry]


def build_widget_catalog() -> WidgetCatalog:
    return WidgetCatalog(
        widgets=[
            WidgetCatalogEntry(
                type=name,
                min_w=spec.min_w,
                min_h=spec.min_h,
                default_w=spec.default_w,
                default_h=spec.default_h,
                shape=[
                    WidgetSlot(
                        name=slot.name,
                        types=sorted(slot.types, key=lambda kind: kind.value),
                        required=slot.required,
                        repeatable=slot.repeatable,
                    )
                    for slot in spec.shape
                ],
                options=[
                    WidgetOption(
                        key=key,
                        values=list(option.values),
                        default=option.default,
                        kind=option.kind,
                    )
                    for key, option in spec.options.items()
                ],
            )
            for name, spec in sorted(WIDGET_SPECS.items())
        ],
        presets=[
            WidgetPresetEntry(
                name=name,
                primitive=preset.primitive,
                options=dict(preset.options),
            )
            for name, preset in sorted(WIDGET_PRESETS.items())
        ],
    )
