"""What a plug-in service sees of its own installs.

These payloads serialize one install's state for the calls a plug-in makes about
its own installation (``/plugin-platform/installation/*``), so they are shaped by
two rules the browser-facing schemas in :mod:`app.schemas.tenant.guild_plugin` do
not share:

* **Credentials do appear here — in two payloads.**
  :class:`PluginInstallConfigRead` carries the values a community typed and the
  managed values a connection's ``after_connect`` hook returned, decrypted; a
  flow's tokens are never in it. :class:`PluginConnectionToken` is one usable
  access token, asked for by reference. Every other payload, the connections
  view included, carries state and never a value.
* **Members are references.** A per-member connection is addressed by its
  opaque ``connection_ref``; there is no user id, email, or display name in any
  shape below.

Values are typed ``Dict[str, Any]`` deliberately: a credential is opaque bytes
to this build, so declaring it as text would invite sanitization that corrupts
it, and the field types that *do* apply live in the pinned definition the
service layer validates against.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import AwareDatetime, ConfigDict, Field

from app.core.tools import METADATA_TARGETS
from app.schemas.base import RawTextStr, SanitizedBaseModel

__all__ = [
    "MetadataTarget",
    "PluginConnectionRead",
    "PluginConnectionToken",
    "PluginConnectionsResponse",
    "PluginInstallConfigRead",
    "PluginInstallationEvent",
    "PluginMemberConfigRead",
    "PluginMetadataItem",
    "PluginMetadataItems",
    "PluginMetadataValues",
    "PluginMetadataWrite",
    "PluginStatusRead",
    "PluginStatusReport",
]


class PluginMemberConfigRead(SanitizedBaseModel):
    """One member's stored values, addressed by the handle the plug-in knows."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connection_ref: str
    status: str
    values: dict[str, Any] = {}


class PluginInstallConfigRead(SanitizedBaseModel):
    """The decrypted configuration for one install — the custody channel.

    ``connections`` holds the guild-wide values, keyed by connection id;
    ``member_connections`` holds each member's managed values, keyed by
    reference. ``connection_refs`` names the handle of each guild-wide
    connection that has one, for asking for its token. A flow's tokens are in
    none of them.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_ref: str
    install_id: int
    listing_uid: str
    listing_version: str
    enabled: bool
    config_state: str = "unverified"
    config_state_detail: str | None = None
    needs_config: bool = False
    connections: dict[str, dict[str, Any]] = {}
    connection_refs: dict[str, str] = {}
    member_connections: list[PluginMemberConfigRead] = []


class PluginConnectionRead(SanitizedBaseModel):
    """One member's connection, as the plug-in reconciles it.

    Enough to know which handles are live and which an admin has stopped, and
    no more: a plug-in matching its stored credentials against this list never
    needs a value to do it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connection_ref: str
    status: str
    blocked: bool = False
    #: What the plug-in itself reported the member connected as. Display only.
    account_label: str | None = None
    created_at: datetime
    updated_at: datetime


class PluginConnectionsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[PluginConnectionRead] = []


class PluginConnectionToken(SanitizedBaseModel):
    """A usable access token for one connection.

    Refreshed first when it was close to expiring, or minted for a connection
    that declares a ``jwt_bearer`` token. ``expires_at`` is in epoch seconds,
    and absent when the vendor did not say.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    access_token: str
    expires_at: int | None = None


class PluginStatusReport(SanitizedBaseModel):
    """The plug-in's verdict on the configuration it was handed.

    ``unverified`` is absent by design: it is this build's resting value for an
    install nothing has reported on, not something a plug-in asserts.
    """

    state: Literal["ok", "invalid"]
    #: A short code shown beside an ``invalid`` state, e.g. ``missing_scope``.
    detail: str | None = Field(default=None, max_length=120)


class PluginStatusRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_ref: str
    install_id: int
    config_state: str
    config_state_detail: str | None = None


class PluginInstallationEvent(SanitizedBaseModel):
    """An event a plug-in emits in the community whose install its token names.

    ``event_type`` is checked against the pinned definition and against the
    caller's own namespace. ``initiative_id`` names the initiative the event
    is about, when it is about one.
    """

    event_type: str = Field(max_length=200)
    payload: dict[str, Any] = {}
    initiative_id: int | None = None


MetadataTarget = Enum(
    "MetadataTarget", {name: name for name in METADATA_TARGETS}, type=str
)
MetadataTarget.__doc__ = (
    "What a plug-in keeps values on: an item, or ``plugin``, its own install."
)


class PluginMetadataItem(SanitizedBaseModel):
    """The values one install keeps on one item, by key."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: str
    entity_id: int
    values: dict[str, Any] = {}


class PluginMetadataItems(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[PluginMetadataItem] = []


class PluginMetadataWrite(SanitizedBaseModel):
    """A change to one item's values, or to the install's own: ``values`` sets
    them by key, a ``null`` removing its key; ``upsert`` adds a list field's
    elements by key, or merges each into the element with its ``ref``; and
    ``remove`` takes the elements with these refs from a list field. At least
    one of the three, each key in one. ``entity_id`` names the item; the
    install's own values need none."""

    entity_type: MetadataTarget
    entity_id: int | None = None
    values: dict[str, Any] | None = None
    upsert: dict[str, Any] | None = None
    remove: dict[str, Any] | None = None


class PluginMetadataValues(SanitizedBaseModel):
    """Every value the install keeps on the item, after a write."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    values: dict[str, Any] = {}


class PluginEntitlementRead(SanitizedBaseModel):
    """The entitlement statement held for the install's community and
    listing: the compact JWS the issuer signed, exactly as it was sent. The
    plug-in verifies it with the issuer's key and reads ``version`` and
    ``values`` from its claims."""

    statement: RawTextStr


class PluginUsageReport(SanitizedBaseModel):
    """A period's cumulative total for one meter, as the plug-in counted it."""

    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=0, le=2**63 - 1, strict=True)
    #: When the total was counted.
    as_of: AwareDatetime


class PluginUsageRead(SanitizedBaseModel):
    """The total held for one meter and period after a report."""

    meter: str
    period: str
    quantity: int
