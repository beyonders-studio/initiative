"""AI settings & connections schemas (mode-based, schema-per-guild).

AI config ownership is a single global mode (``platform`` or ``guild``, never
both — like the auth posture). The mode's owner defines *connections* (the
destination: provider, base_url, model, and its key). Members configure nothing.
"""

from datetime import datetime
from enum import Enum

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel


class AIProvider(str, Enum):
    """Where a connection sends its requests. ``ollama`` and ``custom`` are
    servers somebody runs, at the address the connection gives; the rest are
    hosted services at their own (``app.services.ai_provider.PRESETS``)."""

    openai = "openai"
    anthropic = "anthropic"
    gemini = "gemini"
    deepseek = "deepseek"
    groq = "groq"
    xai = "xai"
    together = "together"
    openrouter = "openrouter"
    ollama = "ollama"
    custom = "custom"


class AIConfigMode(str, Enum):
    """Who owns AI config, app-wide. ``platform`` = the operator's connections
    apply to every guild; ``community`` = each community admin configures its own;
    ``disabled`` = AI off."""

    disabled = "disabled"
    platform = "platform"
    community = "community"


class ConnectionScope(str, Enum):
    """Which table a connection lives in — ``platform`` = the shared
    ``platform_ai_connections`` row, ``community`` = a ``guild_ai_connections`` row."""

    platform = "platform"
    community = "community"


# --- Connections (owner-controlled destination) ------------------------------
class AIConnectionCommunity(SanitizedBaseModel):
    """A community an operator's connection serves. No name when the
    community no longer exists."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str | None = None


class AIConnectionResponse(SanitizedBaseModel):
    """A connection as seen by its owning admin. Never carries the key itself —
    only whether one is set."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    scope: ConnectionScope
    label: str
    provider: AIProvider
    base_url: str | None = None
    model: str | None = None
    has_api_key: bool = False
    enabled: bool = True
    is_default: bool = False
    #: An operator's connection given to these communities serves only them;
    #: with none, it serves every community no other connection is given to.
    communities: list[AIConnectionCommunity] = []
    #: The message code its last request failed with, and since when; none
    #: once one succeeds.
    last_error: str | None = None
    last_error_at: datetime | None = None


class AIConnectionCreate(SanitizedBaseModel):
    label: str
    provider: AIProvider
    base_url: str | None = None
    model: str | None = None
    api_key: RawTextStr | None = None
    enabled: bool = True
    is_default: bool = False
    #: An operator's connection only. Giving it a community takes that
    #: community from any other connection it was given to.
    community_ids: list[int] = []


class AIConnectionUpdate(SanitizedBaseModel):
    label: str | None = None
    provider: AIProvider | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: RawTextStr | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    community_ids: list[int] | None = None


# --- Platform mode (operator-set, on app_settings) ---------------------------
class PlatformAIModeResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    mode: AIConfigMode = AIConfigMode.disabled


class PlatformAIModeUpdate(SanitizedBaseModel):
    mode: AIConfigMode


# --- Resolved (final computed, used internally) ------------------------------
class ResolvedAISettings(SanitizedBaseModel):
    enabled: bool = False
    provider: AIProvider | None = None
    api_key: RawTextStr | None = None
    has_api_key: bool = False
    base_url: str | None = None
    model: str | None = None
    # ``allow_private`` is server-computed as (provider == ollama and the chosen
    # connection is a platform connection); never influenced by request input.
    allow_private: bool = False
    scope: ConnectionScope | None = None
    connection_id: int | None = None
    source: str = "disabled"  # "platform" | "community" | "disabled"


class ResolvedAISettingsResponse(SanitizedBaseModel):
    """Resolved settings for the frontend — never exposes the API key."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool = False
    provider: AIProvider | None = None
    has_api_key: bool = False
    base_url: str | None = None
    model: str | None = None
    source: str = "disabled"


# --- Connection probe (test / list models on a STORED connection) ------------
class AIConnectionTestResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    #: The failure's message code; none on success.
    message: str | None = None
    available_models: list[str] | None = None


class AIModelsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    models: list[str]
    error: str | None = None
