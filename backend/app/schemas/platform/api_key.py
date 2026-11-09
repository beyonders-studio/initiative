from datetime import datetime

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from app.core.messages import UserMessages
from app.core.tools import FEED_TOOLS, Tool
from app.schemas.base import RawTextStr, SanitizedBaseModel


class ApiKeyMetadata(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    token_prefix: str
    is_active: bool
    read_only: bool = False
    community_id: int | None = Field(
        default=None, validation_alias=AliasChoices("community_id", "guild_id")
    )
    resource_type: Tool | None = None
    resource_id: int | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class ApiKeyListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    keys: list[ApiKeyMetadata] = Field(default_factory=list)


class ApiKeyCreateRequest(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None
    # Least-privilege scoping. ``read_only`` blocks all writes; ``guild_id`` pins
    # the key to a single guild. Recommended for machine credentials (MCP, CI).
    read_only: bool = False
    community_id: int | None = None
    # One tool resource the key reads, for a tool in ``FEED_TOOLS``: its feed
    # and nothing else. Needs ``community_id``; such a key is read-only.
    resource_type: Tool | None = None
    resource_id: int | None = None

    @model_validator(mode="after")
    def _one_resource(self) -> ApiKeyCreateRequest:
        if self.resource_type is None and self.resource_id is None:
            return self
        if (
            self.resource_type not in FEED_TOOLS
            or self.resource_id is None
            or self.community_id is None
        ):
            raise ValueError(UserMessages.API_KEY_RESOURCE_INVALID)
        self.read_only = True
        return self


class ApiKeyCreateResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    api_key: ApiKeyMetadata
    secret: RawTextStr
