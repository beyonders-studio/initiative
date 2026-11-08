"""What an operator sees of the marketplace registry client.

Deployment bookkeeping, not catalog content: whether the deployment follows a
registry, how the last refresh or bundle went, and what it did. No guild
appears here, and no key material.
"""

from datetime import datetime

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


class RegistrySkippedListing(SanitizedBaseModel):
    """A listing (or a publisher) the repository carried that did not land."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The listing's target path, or the publisher's role name.
    name: str
    #: A ``MarketplaceRegistryMessages`` code naming why.
    code: str


class RegistryRefreshRead(SanitizedBaseModel):
    """The outcome of one refresh or bundle upload."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The version of the newest trusted root the repository verified under.
    root_version: int | None = None
    upserted: int = 0
    withdrawn: int = 0
    #: True when the repository had not changed since the last clean refresh.
    unchanged: bool = False
    skipped: list[RegistrySkippedListing] = []


class RegistryStatusRead(SanitizedBaseModel):
    """Where this deployment stands with its registry."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The platform switch.
    enabled: bool = False
    #: False when this build ships no trusted root, so there is nothing to
    #: follow and nothing else here is filled in.
    configured: bool = False
    #: True when ``MARKETPLACE_REGISTRY_ROOT`` replaces the shipped root.
    custom_root: bool = False
    registry_url: str = ""
    root_version: int | None = None
    #: When the verified metadata expires. Past it the listings from the
    #: registry are stale until a refresh succeeds.
    expires_at: datetime | None = None
    #: Whether the last attempt read the network or an uploaded bundle.
    last_source: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    #: A ``MarketplaceRegistryMessages`` code, or null after a clean refresh.
    last_error: str | None = None
    listing_count: int = 0


class RegistrySettings(SanitizedBaseModel):
    """The platform switch for the marketplace registry."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
