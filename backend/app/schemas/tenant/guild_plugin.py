"""What an installed plug-in looks like over the wire.

One rule shapes every payload here: **a stored secret never appears in a
response.** A connection reports which of its fields hold a value and nothing
about what those values are — to the member who typed them, and to the guild
admin who governs the install alike. Ending access is the useful power; reading
a live credential is not part of it.

The connection blocks are read off the *pinned* definition rather than the
catalog, so an install describes the form it was actually configured against.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
)

from pydantic import AliasChoices, ConfigDict, Field

from app.models.tenant.plugin_member_consent import ConsentAccess, ConsentStatus
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.marketplace import ListingSource
from app.schemas.query import PageMeta
from app.services.marketplace.definitions import published_by_us
from app.services.marketplace.registration_lookup import InstallState
from app.services.tenant import plugin_age
from app.services.tenant import plugin_config as plugin_config_service
from app.services.tenant.guild_plugins import (
    grantable_scopes,
    item_openability,
    offered_scopes,
    surface_openability,
)
from app.services.tenant.plugin_age import AgeViewer

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import GuildContext


class CommunityPluginInstall(SanitizedBaseModel):
    """Install a listing into this guild, with the seat's consent.

    The definition comes from the catalog, and the content the install creates
    is made server-side. What the request adds is the seat's answer to the
    install dialog: what the plug-in may reach, where it appears, and who opens it
    there. The install, its grant and its placements are one transaction.
    """

    listing_uid: str = Field(max_length=14)
    #: Overrides the listing's own default for the content this creates.
    name: str | None = Field(default=None, min_length=1, max_length=255)
    #: The scopes the seat grants. Each must be one the manifest requests and
    #: one the registration's ceiling allows, as for ``PUT …/scopes``. Left
    #: out, nothing is granted.
    granted_scopes: list[str] = Field(default_factory=list, max_length=64)
    #: The installs here the seat lets use this plug-in, from the listing's
    #: ``callers``. One it leaves out may not.
    callers: list[int] = Field(default_factory=list, max_length=64)
    #: Where the plug-in's initiative surfaces appear: ``"all"`` for every
    #: initiative that exists now, or a list of this guild's initiative ids.
    #: Left out, the plug-in is placed nowhere.
    placements: Literal["all"] | Annotated[list[int], Field(max_length=1000)] = Field(
        default_factory=list
    )
    #: The built-in initiative roles that may open the plug-in in each placement,
    #: by name (``moderator``, ``project_manager``, ``member``), resolved to
    #: each initiative's own role of that name.
    role_kinds: list[str] = Field(default_factory=lambda: ["moderator"], max_length=10)


class CommunityPluginUpdate(SanitizedBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    #: Turning a plug-in off hides it without touching what it created.
    enabled: bool | None = None
    #: Whether published versions are applied on their own. On until a guild
    #: admin turns it off, after which the Update button is how they land.
    auto_update: bool | None = None
    #: The initiatives this plug-in's initiative-scoped surfaces appear in, as the
    #: whole set: an initiative left out is no longer placed. An empty list
    #: places the plug-in in none. Left out entirely, placement is untouched.
    placed_initiative_ids: list[int] | None = None


class CommunityPluginConfigUpdate(SanitizedBaseModel):
    """Guild-scoped connection values, keyed by connection then field.

    A key sent as ``null`` clears that value; a key left out is untouched, so a
    form rendering part of a connection cannot wipe the rest.

    Deliberately untyped at this layer. A credential is opaque bytes to us, so
    sanitizing one would corrupt it, and the declared field types live in the
    pinned definition rather than in this schema — the service checks each value
    against the type its own connection declared, which coercion here would
    quietly defeat (a ``true`` arriving at an ``int`` field must be refused, not
    turned into ``1``).
    """

    values: dict[str, dict[str, Any]] = {}


class CommunityPluginSettingUpdate(SanitizedBaseModel):
    """A value for one of the install's settings.

    ``null`` clears a setting that is not unique. A unique one always holds a
    value: a lowercase letter, then lowercase letters and digits, which no other
    community on this server holds.
    """

    value: str | None = None


class CommunityPluginArtifact(SanitizedBaseModel):
    """One thing an install produced."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: str
    id: int


class CommunityPluginConnectionRead(SanitizedBaseModel):
    """One connection of an install, as the current viewer sees it.

    ``has_value`` is the whole of what is disclosed about stored values. For a
    per-member connection the presence, status and account label are the
    *viewer's own* — a colleague who has connected and one who has not are both
    looking at a correct answer, because the underlying vendor access genuinely
    differs per person.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    scope: str
    label: dict[str, str] = {}
    #: The declared fields, verbatim from the pinned definition, so one generic
    #: form renderer can draw any plug-in's settings page.
    fields: list[dict[str, Any]] = []
    #: What the connection says it will use the credential for. Display-only.
    access_hint: dict[str, Any] | None = None
    #: The non-secret values, so a form can show what is currently set: a
    #: member's own on a per-member connection, and on a guild-wide one only
    #: for the seat, which sets them. Secret fields are absent from this by
    #: construction — they live in a column this never reads.
    values: dict[str, Any] = {}
    #: Which fields hold a value, secret ones included. Never the values.
    has_value: dict[str, bool] = {}
    #: Whether everything this connection declared it needs is present.
    satisfied: bool = False
    #: Whether the connection is established through the vendor's own flow,
    #: which Initiative runs: always on an interactive connection, and on a
    #: guild-wide one an admin connects rather than types.
    runs_flow: bool = False
    #: The viewer's own state on an interactive connection: ``pending``,
    #: ``connected``, ``expired`` (reconnect) or ``blocked``.
    status: str | None = None
    account_label: str | None = None
    blocked: bool = False


class CommunityPluginSettingRead(SanitizedBaseModel):
    """One setting the pinned definition declares, and what the install holds
    for it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    label: dict[str, str] = {}
    description: dict[str, str] = {}
    #: No two communities on this server hold the same value, and the values it
    #: held before stay this community's.
    unique: bool = False
    value: str | None = None
    #: A unique setting's earlier values, newest first, which the plug-in still
    #: reads.
    aliases: list[str] = []


class PluginPlacementRead(SanitizedBaseModel):
    """One initiative a plug-in is placed in, and who may open it there."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    initiative_id: int
    #: The initiative roles allowed to open the plug-in's surfaces here.
    role_ids: list[int] = []


class PluginPlacementUpdate(SanitizedBaseModel):
    """Who may open a plug-in's surfaces in one initiative.

    The whole set: a role left out is no longer allowed. Every id must be a
    role of that initiative. An empty list places the plug-in with no role, so
    only guild admins open it there.
    """

    role_ids: list[int] = Field(default_factory=list, max_length=200)


class CommunityPluginScopesUpdate(SanitizedBaseModel):
    """The scopes the seat grants an install, as the whole set.

    Each must be one the plug-in's manifest requests and one this deployment
    allows the plug-in. An empty list withdraws every grant.
    """

    granted: list[str] = Field(default_factory=list, max_length=64)


class PluginSurfaceAccessRead(SanitizedBaseModel):
    """Where the viewer may open one of a plug-in's surfaces.

    Computed on the server by the same decision the handoff makes, so the
    client offers exactly the doors that open.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    surface_id: str
    #: Whether the viewer may open it at the community level.
    openable_community_wide: bool = Field(
        default=False,
        validation_alias=AliasChoices("openable_community_wide", "openable_guild_wide"),
    )
    #: The initiatives the viewer may open it in.
    openable_initiatives: list[int] = []


class CommunityPluginUninstallNotice(SanitizedBaseModel):
    """What to tell somebody about to remove a plug-in, beyond what removing
    any plug-in does.

    ``managed`` is whether this deployment's entitlement issuer has a say about
    this plug-in at all: false, and nothing else, for every plug-in whose
    listing carries no package terms. When it does, ``message`` is the
    issuer's own sentence in the reader's language, shown as it is, or null
    when it could not say in time, in which case the client shows its own
    neutral text. ``action_url`` is where to go about it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    managed: bool = False
    message: str | None = None
    action_url: str | None = None


class CommunityPluginRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    listing_uid: str
    listing_version: str
    plugin_kind: str
    name: str
    enabled: bool
    #: Whether this install tracks its listing. True unless a guild admin chose
    #: to apply versions by hand.
    auto_update: bool = True
    #: A version that asks for more than the install holds, waiting for the
    #: seat to accept or decline it.
    pending_version: str | None = None
    #: What the install produced — for a tool instance, the row it created, so
    #: the sidebar can link straight to it.
    artifacts: list[CommunityPluginArtifact] = []
    #: Whether a guild admin still has a guild-scoped connection to fill in.
    needs_config: bool = False
    #: What the plug-in reported about the configuration it was given.
    config_state: str = "unverified"
    config_state_detail: str | None = None
    #: Which tool this plug-in mounts, when it mounts one. Read off the pinned
    #: definition so the client need not fetch the catalog to render an entry.
    tool: str | None = None
    #: The listing's artwork, so the sidebar can draw this install. Looked up
    #: from the catalog rather than pinned: a publisher who changes their
    #: picture changes it everywhere the plug-in is shown.
    avatar_url: str | None = None
    #: What a service plug-in contributes, from its pinned definition.
    features: list[str] = []
    #: The pinned definition itself, verbatim.
    #:
    #: A passthrough rather than a read: this build gives meaning to parts of it
    #: (``connections``, ``plugin_kind``) and none at all to others — the
    #: ``automation`` block belongs to the automation service, which parses it
    #: against its own schema off this same payload rather than through an
    #: endpoint that would have to understand it. Serving the snapshot the guild
    #: pinned, not whatever the catalog holds today, is what lets a reader say
    #: what *this* install actually is. It never carries a stored value: the
    #: definition describes the form, and what was typed into it lives in
    #: columns nothing here reads.
    definition: dict[str, Any] = {}
    #: The initiatives this plug-in's initiative-scoped surfaces appear in, as the
    #: seat set them, each with the roles allowed to open it there. An
    #: initiative not listed is one the plug-in does not appear in. Placement
    #: rather than permission: it is the community's own answer to where an
    #: plug-in belongs, so it reads the same for everyone.
    placements: list[PluginPlacementRead] = []
    #: Each page the pinned definition declares, with where the
    #: viewer may open it.
    surface_access: list[PluginSurfaceAccessRead] = []
    #: The initiatives whose items show the viewer this plug-in's values and
    #: parts.
    item_initiatives: list[int] = []
    #: The declared fields and parts offered there: those whose connections
    #: hold what they require.
    item_fields: list[str] = []
    item_parts: list[str] = []
    #: The declared actions the viewer may run on those items.
    item_actions: list[str] = []
    #: The install's settings' values by key, which its parts' text names.
    setting_values: dict[str, Any] = {}
    #: The scopes the community's seat granted this install: empty until the
    #: seat grants some, and never wider than what the manifest requests or
    #: the registration allows.
    granted_scopes: list[str] = []
    #: The deployment provides this plug-in to every guild, and a guild admin
    #: neither removes nor disables it. The affordances are absent rather than
    #: erroring, so the client is told which installs those are.
    mandatory: bool = False
    #: Whether what this plug-in offers can be reached right now. False for a
    #: service plug-in whose registration is missing or switched off — the install
    #: stays where it is and says why it is doing nothing.
    available: bool = True
    created_by: int
    created_at: datetime
    updated_at: datetime


class CommunityPluginConsentRead(SanitizedBaseModel):
    """One request from this plug-in to act as the viewer, and their answer.

    ``label`` is the plug-in's own description of what it wants to do, shown as
    the plug-in's words. ``purpose`` is the plug-in's id for it; absent for plug-in-wide
    consent.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    purpose: str | None = None
    label: str
    #: The one initiative the purpose is bound to, when it is.
    initiative_id: int | None = None
    requested_access: ConsentAccess
    granted_access: ConsentAccess | None = None
    status: ConsentStatus
    requested_at: datetime
    granted_at: datetime | None = None
    revoked_at: datetime | None = None


class CommunityPluginConsentAnswer(SanitizedBaseModel):
    """Allow a request, at ``access``: never more than the plug-in asked for.
    Declining is withdrawing a request that was never granted."""

    access: ConsentAccess


class CommunityPluginMemberConsent(CommunityPluginConsentRead):
    """One member's answer to one of the plug-in's requests, in the seat's Members
    view."""

    user_id: int


class PluginSurfaceSummary(SanitizedBaseModel):
    """One of a plug-in's pages, by id and by its localized name."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    name: dict[str, str] = {}


class CommunityPluginUpgradeAsks(SanitizedBaseModel):
    """A version that asks for more than the install holds.

    ``added_scopes`` are grantable scopes neither the grant nor the pinned
    version names; ``added_surfaces`` are surfaces inside initiatives the
    pinned version does not have. ``declined`` says the seat declined this
    version: the install stays where it is and the sweep does not ask again.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    added_scopes: list[str] = []
    added_surfaces: list[PluginSurfaceSummary] = []
    declined: bool = False


class CommunityPluginUpdateRefused(SanitizedBaseModel):
    """A newer version than the install's that this server cannot run.
    ``reason`` is the ``messages.py`` code of the refusal."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    reason: str


class CommunityPluginUpgrade(SanitizedBaseModel):
    """The seat's consent to a version that asks for more.

    ``version`` is the version the seat was shown; if the catalog offers a
    different one now, nothing is applied. ``add_scopes`` are the scopes the
    seat grants with it, each requested by that version and within the
    ceiling. Consenting to a version's new surfaces alone sends none.
    """

    version: str = Field(max_length=32)
    add_scopes: list[str] = Field(default_factory=list, max_length=64)


class CommunityPluginDecline(SanitizedBaseModel):
    """Keep the pinned version, and stop being asked about this one."""

    version: str = Field(max_length=32)


class CommunityPluginListingRef(SanitizedBaseModel):
    """Where an install came from in the catalog, as the plug-in's page shows it.

    Read from the catalog rather than pinned, like the artwork: who publishes a
    listing is the catalog's to say.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The listing's row id, which a report names it by.
    id: int
    source: ListingSource  # type: ignore[valid-type]
    publisher: str
    #: Whether this project publishes it, so it is neither reported nor
    #: introduced as somebody else's.
    first_party: bool


class CommunityPluginEntitlementRead(SanitizedBaseModel):
    """What the entitlement statement held for an install's listing says, as
    the plug-in's page reads it: whether it entitles the community, and why
    not when it says (``term_full``: the deployment's term has no seat free)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    active: bool
    reason: str | None = None


class CommunityPluginDetail(CommunityPluginRead):
    """An install plus its connections, for the settings page.

    Separate from the list payload because the connection blocks carry the whole
    pinned form and the sidebar has no use for it.
    """

    connections: list[CommunityPluginConnectionRead] = []
    #: Each setting the pinned definition declares, with its value.
    settings: list[CommunityPluginSettingRead] = []
    #: The viewer's own answers to this plug-in's requests to act as them, one per
    #: purpose, the plug-in-wide one first. Nobody else's.
    consents: list[CommunityPluginConsentRead] = []
    #: The version this install would move to if it updated now, and absent
    #: when there is none: the install is on the newest, or the listing is gone
    #: or withdrawn, or its newest is one this server cannot run
    #: (``update_refused``). Only the detail read carries it: it costs a catalog
    #: lookup, and it is the page offering the Update button that needs it.
    update_version: str | None = None
    #: A newer version this server cannot run, and why, so the page can say
    #: so rather than "Up to date".
    update_refused: CommunityPluginUpdateRefused | None = None
    #: The scopes the pinned manifest asks for, in vocabulary order. Using a
    #: plug-in the community does not have is left out until it does.
    requested_scopes: list[str] = []
    #: The requested scopes this deployment allows the seat to grant. A
    #: requested scope missing here is one the server would refuse.
    grantable_scopes: list[str] = []
    #: What ``update_version`` asks for beyond what the install holds, when it
    #: asks for anything. Absent for a version that asks nothing new, which
    #: applies without consent.
    pending_update: CommunityPluginUpgradeAsks | None = None
    #: For each ``plugins:`` scope above, the requested ones and those the pending
    #: version adds: the name the plug-in it lets this one use goes by, keyed by
    #: that plug-in's public id. Its public id when the catalog has no name for it.
    plugin_names: dict[str, str] = {}
    #: The catalog listing behind this install. Absent when the catalog no
    #: longer holds it.
    listing: CommunityPluginListingRef | None = None
    #: The entitlement statement held for the install's listing, when one is.
    entitlement: CommunityPluginEntitlementRead | None = None


class CommunityPluginListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[CommunityPluginRead]


class CommunityPluginConnectStart(SanitizedBaseModel):
    """Where to send the person connecting: the vendor's authorization page,
    or its install page for a connection an organization installs.

    Initiative runs the flow, and the vendor returns the person to Initiative's
    own callback. Nothing is stored until it does.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connect_url: str
    #: The viewer's current state on this connection, before the flow runs.
    status: str


class CommunityPluginHandoff(SanitizedBaseModel):
    """A short-lived credential for one of a plug-in's pages.

    The token reaches the iframe by ``postMessage`` and never a query string,
    and it is worth a minute. ``allowed_origins`` is what the SPA posts to and
    accepts messages from — the registration's own list, not a client guess.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    handoff_token: str
    expires_in_seconds: int
    page_url: str
    allowed_origins: list[str] = []
    audience: str
    surface_id: str


class CommunityPluginMemberConnection(SanitizedBaseModel):
    """One member's connection, in the admin's Members view.

    Who connected, as which vendor account, when, and whether they are blocked.
    No values, and no ``connection_ref`` — the handle is between the platform
    and the plug-in, and putting it in an admin screen would make it something
    people copy around.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    user_id: int
    status: str
    account_label: str | None = None
    blocked: bool = False
    blocked_by_id: int | None = None
    created_at: datetime
    updated_at: datetime


class CommunityPluginConnectionSummary(SanitizedBaseModel):
    """The aggregate an admin actually wants: how many of the guild connected."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    label: dict[str, str] = {}
    connected_count: int = 0
    blocked_count: int = 0
    member_count: int = 0


class CommunityPluginConsentSummary(SanitizedBaseModel):
    """Every member's answers to this plug-in's requests, counted."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Members who were asked anything.
    member_count: int = 0
    #: Members who allowed at least one request.
    allowed_count: int = 0
    #: Answers that still stand or still wait: the ones an admin can end.
    open_count: int = 0


class CommunityPluginMembersResponse(PageMeta):
    """One page of the members who connected to this plug-in or answered it.

    ``summary`` and ``consent_summary`` count across every member; ``items``
    and ``consents`` are the rows of the members on this page.
    """

    summary: list[CommunityPluginConnectionSummary] = []
    items: list[CommunityPluginMemberConnection] = []
    #: The page's members' answers to this plug-in's requests to act as them.
    #: Beside the connections rather than in a view of its own: both answer
    #: "what does this plug-in have of this member's", and an admin governing one
    #: wants the other in the same place.
    consents: list[CommunityPluginMemberConsent] = []
    consent_summary: CommunityPluginConsentSummary = CommunityPluginConsentSummary()


# --- serialization ----------------------------------------------------------


def serialize_guild_plugin(
    plugin: Any,
    *,
    context: "GuildContext",
    install_state: InstallState | None = None,
    avatar_url: str | None = None,
    placements: Sequence[Any] = (),
    artifacts: Sequence[dict[str, Any]] = (),
    viewer: AgeViewer,
) -> CommunityPluginRead:
    """One install as the client sees it.

    ``install_state`` is what this deployment's registration says about the plug-in
    (§7.7): whether the platform provides it, and whether it can be reached at
    all. It is passed in rather than looked up here so a list of installs
    resolves it once. ``placements`` are the install's ``plugin_placements`` rows,
    and ``artifacts`` what it owns at guild scope, loaded by the caller for the
    same reason. ``viewer`` is the person reading, so a surface they are too
    young for is not offered to them.
    """
    definition = plugin.definition or {}
    state = plugin_config_service.config_state(plugin)
    age_allows = plugin_age.age_allows(definition, viewer)
    openability = surface_openability(
        definition,
        placements=placements,
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
        age_allows=age_allows,
    )
    on_items = item_openability(
        plugin,
        placements=placements,
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
        age_allows=age_allows,
        frozen=context.content_read_only,
    )
    features = definition.get("features")
    service_state = install_state or InstallState()
    return CommunityPluginRead(
        id=plugin.id,
        community_id=context.guild_id,
        listing_uid=plugin.listing_uid,
        listing_version=plugin.listing_version,
        plugin_kind=plugin.plugin_kind,
        name=plugin.name,
        enabled=plugin.enabled,
        auto_update=plugin.auto_update,
        pending_version=plugin.pending_version,
        artifacts=[CommunityPluginArtifact(**artifact) for artifact in artifacts],
        needs_config=state.needs_config,
        config_state=state.state,
        config_state_detail=state.detail,
        tool=definition.get("tool"),
        avatar_url=avatar_url,
        features=list(features) if isinstance(features, list) else [],
        definition=definition,
        placements=[
            PluginPlacementRead(
                initiative_id=row.initiative_id, role_ids=list(row.role_ids or [])
            )
            for row in sorted(placements, key=lambda row: row.initiative_id)
        ],
        surface_access=[
            PluginSurfaceAccessRead(
                surface_id=one.surface_id,
                openable_community_wide=one.openable_guild_wide,
                openable_initiatives=list(one.openable_initiatives),
            )
            for one in openability
        ],
        item_initiatives=list(on_items.initiatives),
        item_fields=list(on_items.fields),
        item_parts=list(on_items.parts),
        item_actions=list(on_items.actions),
        setting_values=dict(plugin.settings or {}),
        granted_scopes=sorted(plugin.granted_scopes or []),
        mandatory=service_state.mandatory,
        available=service_state.available,
        created_by=plugin.created_by,
        created_at=plugin.created_at,
        updated_at=plugin.updated_at,
    )


def serialize_connection(
    plugin: Any,
    connection: dict[str, Any],
    *,
    member_row: Any = None,
    holds_seat: bool = False,
) -> CommunityPluginConnectionRead:
    """One connection block for the viewer looking at it.

    A guild-scoped connection reads its presence off the install row; a
    per-member one reads it off the viewer's own row, so the payload carries
    only the viewer's own state — there is no branch that could reach another
    row.

    A guild-scoped connection's values go to ``holds_seat`` alone: the seat is
    who sets them, and everybody else is told only whether they are there.
    """
    connection_id = connection.get("id") or ""
    scope = connection.get("scope") or "static"

    if scope == "static":
        stored_config = (plugin.config or {}).get(connection_id) or {}
        stored_secrets = (plugin.secret_fields or {}).get(connection_id) or {}
    else:
        stored_config = (member_row.config or {}) if member_row is not None else {}
        stored_secrets = (
            (member_row.secret_fields or {}) if member_row is not None else {}
        )

    declared = {
        field.get("key")
        for field in connection.get("fields") or []
        if isinstance(field, dict)
    }
    readable = scope != "static" or holds_seat
    return CommunityPluginConnectionRead(
        id=connection_id,
        scope=scope,
        label=connection.get("label") or {},
        fields=connection.get("fields") or [],
        access_hint=connection.get("access_hint"),
        # Declared fields only: a flow's tokens and their expiry sit beside
        # them under reserved keys, and are nobody's to read here.
        values=(
            {key: value for key, value in stored_config.items() if key in declared}
            if readable
            else {}
        ),
        has_value=plugin_config_service.has_value_map(
            connection, stored_config, stored_secrets
        ),
        satisfied=plugin_config_service.is_satisfied(
            connection, stored_config, stored_secrets
        ),
        runs_flow=plugin_config_service.runs_vendor_flow(connection),
        status=member_row.status if member_row is not None else None,
        account_label=member_row.account_label if member_row is not None else None,
        blocked=member_row is not None and member_row.blocked_at is not None,
    )


def serialize_guild_plugin_detail(
    plugin: Any,
    *,
    context: "GuildContext",
    member_rows: dict[str, Any],
    install_state: InstallState | None = None,
    avatar_url: str | None = None,
    update_offer: Any = None,
    update_refused: Any = None,
    installed: Collection[str] = (),
    placements: Sequence[Any] = (),
    artifacts: Sequence[dict[str, Any]] = (),
    consent_rows: Sequence[Any] = (),
    plugin_names: dict[str, str] | None = None,
    viewer: AgeViewer,
    listing: Any = None,
    entitlement: CommunityPluginEntitlementRead | None = None,
) -> CommunityPluginDetail:
    """The install and its connections, from the viewer's own perspective.

    ``update_offer`` (a ``plugin_updates.UpdateOffer``) and ``update_refused``
    (a ``plugin_updates.RefusedUpdate``) are resolved by the caller, which is
    the layer holding a session that can read the catalog, and so are
    ``listing`` (the install's ``MarketplaceListing``, if any) and
    ``installed``, the public ids of the plug-ins the community has.
    """
    base = serialize_guild_plugin(
        plugin,
        context=context,
        install_state=install_state,
        avatar_url=avatar_url,
        placements=placements,
        artifacts=artifacts,
        viewer=viewer,
    )
    connections = [
        serialize_connection(
            plugin,
            connection,
            member_row=member_rows.get(connection.get("id") or ""),
            holds_seat=context.guild_seat,
        )
        for connection in plugin_config_service.definition_connections(
            plugin.definition
        )
    ]
    held = plugin.settings or {}
    aliases = plugin.setting_aliases or {}
    return CommunityPluginDetail(
        **base.model_dump(),
        connections=connections,
        settings=[
            CommunityPluginSettingRead(
                key=setting["key"],
                label=setting.get("label") or {},
                description=setting.get("description") or {},
                unique=setting.get("unique") is True,
                value=held.get(setting["key"]),
                aliases=list(aliases.get(setting["key"]) or []),
            )
            for setting in plugin_config_service.definition_settings(plugin.definition)
        ],
        consents=[serialize_consent(row) for row in consent_rows],
        update_version=update_offer.version if update_offer is not None else None,
        update_refused=(
            CommunityPluginUpdateRefused(
                version=update_refused.version, reason=update_refused.reason
            )
            if update_refused is not None
            else None
        ),
        pending_update=serialize_upgrade_asks(plugin, update_offer),
        requested_scopes=offered_scopes(plugin.definition, installed),
        grantable_scopes=grantable_scopes(
            plugin.definition,
            (install_state or InstallState()).scope_ceiling,
            installed,
        ),
        plugin_names=dict(plugin_names or {}),
        listing=(
            CommunityPluginListingRef(
                id=listing.id,
                source=listing.source,
                publisher=listing.publisher,
                first_party=published_by_us(listing.source, listing.public_id),
            )
            if listing is not None and listing.id is not None
            else None
        ),
        entitlement=entitlement,
    )


def upgrade_asks_read(version: str, asks: Any, *, declined: bool = False):
    """What a version asks for, as the client reads it."""
    return CommunityPluginUpgradeAsks(
        version=version,
        added_scopes=list(asks.added_scopes),
        added_surfaces=[
            PluginSurfaceSummary(
                id=surface["id"],
                name={
                    str(key): str(value)
                    for key, value in (surface.get("name") or {}).items()
                },
            )
            for surface in asks.added_surfaces
        ],
        declined=declined,
    )


def serialize_upgrade_asks(
    plugin: Any, offer: Any
) -> CommunityPluginUpgradeAsks | None:
    """The offered version's asks, or ``None`` when it asks nothing new."""
    if offer is None or not offer.asks.asks_more:
        return None
    return upgrade_asks_read(
        offer.version, offer.asks, declined=plugin.declined_version == offer.version
    )


def serialize_member_connection(row: Any) -> CommunityPluginMemberConnection:
    return CommunityPluginMemberConnection(
        connection_id=row.connection_id,
        user_id=row.user_id,
        status=row.status,
        account_label=row.account_label,
        blocked=row.blocked_at is not None,
        blocked_by_id=row.blocked_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_consent(row: Any) -> CommunityPluginConsentRead:
    return CommunityPluginConsentRead(
        id=row.id,
        purpose=row.purpose,
        label=row.label,
        initiative_id=row.initiative_id,
        requested_access=ConsentAccess(row.requested_access),
        granted_access=(
            ConsentAccess(row.granted_access) if row.granted_access else None
        ),
        status=row.status,
        requested_at=row.requested_at,
        granted_at=row.granted_at,
        revoked_at=row.revoked_at,
    )


def serialize_member_consent(row: Any) -> CommunityPluginMemberConsent:
    return CommunityPluginMemberConsent(
        **serialize_consent(row).model_dump(), user_id=row.user_id
    )
