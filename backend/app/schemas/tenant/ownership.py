"""Payloads for the guild-admin content-ownership screens, and the owning plug-in
a read model names."""

from typing import Any

from pydantic import ConfigDict, Field, model_validator

from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import UserPublic


class OwnerPluginSummary(SanitizedBaseModel):
    """An installed plug-in that owns a resource, or may be handed one: the
    install's id, its name in this community, and its listing's picture."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    avatar_url: str | None = None


def owner_profile(row: Any) -> UserPublic | None:
    """The person holding ``row``'s owner grant, or None when nobody does or a
    plug-in does. Read off the grants the loader brings with their users:
    ownership is recorded there and nowhere else."""
    for grant in getattr(row, "grants", None) or []:
        if (
            grant.user_id is not None
            and grant.level == ResourceAccessLevel.owner
            and grant.user is not None
        ):
            return UserPublic.model_validate(grant.user)
    return None


class OwnedContentItem(SanitizedBaseModel):
    """One thing someone owns, or that nobody does."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tool: Tool
    id: int
    name: str


class OwnedContentResponse(SanitizedBaseModel):
    """What a user owns in this guild, or what no current member owns.

    ``counts`` is per tool, keyed by the ``Tool`` value, so the dialog can say
    "3 projects, 1 calendar" without walking the list. ``eligible_plugins`` are the
    installed plug-ins that may own every item listed, which the dialog offers
    beside the community's admins.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[OwnedContentItem] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    eligible_plugins: list[OwnerPluginSummary] = Field(default_factory=list)


class OwnershipTransferRequest(SanitizedBaseModel):
    """Who should end up owning it: an active admin of this guild
    (``new_owner_id``), or an installed plug-in that may own all of it
    (``new_owner_plugin_id``). Exactly one is set."""

    new_owner_id: int | None = None
    new_owner_plugin_id: int | None = None

    @model_validator(mode="after")
    def exactly_one_recipient(self) -> OwnershipTransferRequest:
        if (self.new_owner_id is None) == (self.new_owner_plugin_id is None):
            raise ValueError("Exactly one of new_owner_id or new_owner_plugin_id")
        return self


class OwnershipTransferResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
