"""Payloads for the plug-in service registry and its publishers.

A registration's listing, addresses and the public half of its keys are shown
as they are. Its vendor values are the one thing it holds that is secret: a
secret one is written and never read back, and the screen is told only that it
is set. A request writes deployment facts only; what the plug-in is and may do
comes from its listing.
"""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from app.core.messages import PluginServiceMessages
from app.models.platform.plugin_service_registration import LISTING_STATED_FIELDS
from app.schemas.base import RawTextStr, SanitizedBaseModel

__all__ = [
    "PluginPublisherCreate",
    "PluginPublisherRead",
    "PluginPublisherUpdate",
    "PluginServiceConnect",
    "PluginServicePublishedKey",
    "PluginServiceRegistrationCreate",
    "PluginServiceRegistrationRead",
    "PluginServiceRegistrationUpdate",
    "PluginServiceVendorSetup",
    "PluginServiceVendorSetupComplete",
    "PluginServiceVendorSetupStart",
    "PluginVendorFieldRead",
]


class PluginVendorFieldRead(SanitizedBaseModel):
    """One value an operator supplies for the plug-in's vendor client, as the
    listing's manifest declares it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    #: ``string``, ``secret`` or ``url``. A secret is write-only.
    type: str
    required: bool = False
    label: dict[str, str] = {}


class PluginServiceRegistrationRead(SanitizedBaseModel):
    """A registration as the owner's settings see it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    public_id: str
    #: The catalog listing its plug-in facts come from. Null until it arrives.
    listing_uid: str | None = None
    #: ``container``, or ``declarative`` for a plug-in whose calls Initiative
    #: makes itself: it has no address, origins or keys.
    kind: str = "container"
    #: The publisher the public_id's prefix names.
    publisher_id: int
    publisher_prefix: str
    publisher_name: str
    publisher_enabled: bool
    #: Where this deployment's server calls the plug-in. Null until the operator
    #: gives its address.
    base_url: str | None = None
    #: Where a browser loads its surfaces. Null when that is ``base_url`` too.
    page_origin: str | None = None
    allowed_origins: list[str] = []
    #: Public keys this plug-in signs with. Shown in full — the
    #: public half is meant to be read, and an operator provisioning it needs
    #: to see which ``kid`` landed.
    jwks: dict[str, Any] | None = None
    #: Where the plug-in publishes its key set, on its own origin.
    jwks_uri: str | None = None
    #: The most an install of this plug-in may be granted, from its listing.
    #: Empty means no scope may be granted.
    scope_ceiling: list[str] = []
    #: Installed into every guild and not removable by guild admins.
    mandatory: bool = False
    #: Offered to, installed in and live in the operations community alone.
    operations_only: bool = False
    #: One vendor installation may connect to several communities.
    shared_routes: bool = False
    enabled: bool = True
    #: ``registry`` when its plug-in facts come from a listing the registry signed,
    #: ``operator`` otherwise.
    source: str = "operator"
    #: The container image its listing names, pinned by digest.
    image_digest: str | None = None
    #: The Compose service its listing's publisher wrote, with the image and
    #: this deployment's public address filled in, for the operator to copy.
    #: YAML text, shown as text.
    compose_service: RawTextStr | None = None
    #: Where that service answers on the Compose network: the base URL to give
    #: it.
    compose_base_url: str | None = None
    #: The values the listing's manifest asks the operator for, in order.
    vendor_fields: list[PluginVendorFieldRead] = []
    #: The plain values of the non-secret vendor fields that hold one.
    vendor_values: dict[str, str] = {}
    #: Every vendor field that holds a value, secret or not.
    vendor_set: list[str] = []
    #: Whether every required vendor value is set.
    vendor_ready: bool = True
    #: The flow at the vendor that can create its client and fill in the
    #: vendor values (``github_app_manifest``), when the listing declares one.
    vendor_setup: str | None = None
    #: The two addresses to register with the vendor's client: where it
    #: returns a person with a code, and where its install page returns them.
    connection_callback_url: str
    connection_setup_url: str
    #: The address to give the vendor for this plug-in's webhooks.
    webhook_url: str
    #: Enabled, its publisher enabled, every required vendor value set and,
    #: for a container, an address and a key set to verify against.
    live: bool
    created_at: datetime
    updated_at: datetime


class _DeploymentFacts(SanitizedBaseModel):
    """A request naming what only the plug-in's listing states is refused."""

    @model_validator(mode="before")
    @classmethod
    def _no_listing_facts(cls, data: Any) -> Any:
        if isinstance(data, dict) and any(key in data for key in LISTING_STATED_FIELDS):
            raise ValueError(PluginServiceMessages.STATED_BY_LISTING)
        return data


class PluginServiceRegistrationCreate(_DeploymentFacts):
    """Set up a plug-in service's deployment facts before its listing arrives.

    ``public_id`` names the plug-in. ``page_origin`` is optional, and unset is the
    ordinary case: a plug-in reachable at one address needs only ``base_url``.
    Give one when the address a browser must use is not the address this
    deployment calls.

    Keys are a pasted ``jwks``, a ``jwks_uri`` on ``base_url``'s own origin
    over https, or both. A registration with neither is not live.
    """

    public_id: str = Field(max_length=120)
    base_url: str = Field(max_length=1000)
    page_origin: str | None = Field(default=None, max_length=1000)
    allowed_origins: list[str] | None = None
    #: JWKS holding the public half of the plug-in's signing keys.
    jwks: dict[str, Any] | None = None
    jwks_uri: str | None = Field(default=None, max_length=1000)
    mandatory: bool = False
    operations_only: bool = False
    enabled: bool = True
    #: Values for the vendor fields the listing's manifest declares, by key.
    vendor_values: dict[str, RawTextStr | None] | None = None


class PluginServiceRegistrationUpdate(_DeploymentFacts):
    """Partial edit.

    An empty ``page_origin`` clears it, putting both surfaces back on
    ``base_url``. An empty ``jwks_uri`` clears it, and an empty ``jwks``
    object clears the pasted set. In ``vendor_values`` a key sent empty or
    null clears that value, and a key left out keeps it, so a secret is kept
    by not sending it.
    """

    base_url: str | None = Field(default=None, max_length=1000)
    page_origin: str | None = Field(default=None, max_length=1000)
    allowed_origins: list[str] | None = None
    #: Replace the key set. An empty object clears it.
    jwks: dict[str, Any] | None = None
    jwks_uri: str | None = Field(default=None, max_length=1000)
    mandatory: bool | None = None
    operations_only: bool | None = None
    #: Let one vendor installation connect to several communities. Turning it
    #: off is refused while one is connected to more than one.
    shared_routes: bool | None = None
    enabled: bool | None = None
    #: Set or clear vendor values, by key.
    vendor_values: dict[str, RawTextStr | None] | None = None


class PluginServicePublishedKey(SanitizedBaseModel):
    """One key the plug-in serves under its base URL: what Connect shows, and what
    the operator confirms."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kid: str
    #: The key's RFC 7638 SHA-256 thumbprint, base64url without padding: the
    #: fingerprint the plug-in logs at start.
    fingerprint: str = Field(max_length=64)


class PluginServiceConnect(SanitizedBaseModel):
    """Pin the key set the plug-in serves, as the operator confirmed it."""

    #: The keys the operator was shown and confirmed.
    keys: list[PluginServicePublishedKey] = Field(min_length=1, max_length=20)


class PluginServiceVendorSetupStart(SanitizedBaseModel):
    """Start the vendor's own setup for the plug-in's client."""

    #: The GitHub organization to own the new app. Empty: the operator's own
    #: account.
    organization: str | None = Field(default=None, max_length=100)


class PluginServiceVendorSetup(SanitizedBaseModel):
    """What the operator's browser posts to the vendor: ``manifest`` as a form
    field, to ``action`` with ``state`` in its query."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    action: str
    #: The manifest, as JSON text.
    manifest: RawTextStr
    state: str


class PluginServiceVendorSetupComplete(SanitizedBaseModel):
    """What the vendor sent the operator back with."""

    code: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=4000)


class PluginPublisherRead(SanitizedBaseModel):
    """A publisher as the owner's settings see it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    #: The ``public_id`` prefix its plug-ins carry.
    prefix: str
    display_name: str
    #: Whether the deployment has confirmed who this publisher is.
    verified: bool
    #: Off makes every registration under this prefix not live.
    enabled: bool
    created_at: datetime


class PluginPublisherCreate(SanitizedBaseModel):
    """Add a publisher for a prefix, unverified."""

    prefix: str = Field(max_length=120)
    display_name: str = Field(max_length=200)
    enabled: bool = True


class PluginPublisherUpdate(SanitizedBaseModel):
    """Rename a publisher, or switch it on or off."""

    display_name: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
