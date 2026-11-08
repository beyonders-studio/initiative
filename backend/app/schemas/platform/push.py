from pydantic import ConfigDict, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class PushTokenRegisterRequest(SanitizedBaseModel):
    """Request body for registering a push notification token."""

    push_token: str = Field(min_length=1, max_length=512)
    platform: str = Field(pattern="^(android|ios)$")


class PushTokenUnregisterRequest(SanitizedBaseModel):
    """Request body for unregistering a push notification token."""

    push_token: str = Field(min_length=1, max_length=512)


class PushTokenResponse(SanitizedBaseModel):
    """Generic response for push token operations."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


class FCMConfigResponse(SanitizedBaseModel):
    """Public FCM configuration for mobile app initialization.

    Only exposes public fields (API key, project ID, sender ID).
    Does NOT expose service account credentials.

    ``push_relay_server_id`` is this server's id at the push relay, under
    which the app registers its device token with the relay for a handle;
    null while push is off or the server could not register.
    ``android_via_relay`` says Android pushes go through the relay too (no
    service account is configured), so the Android app registers a handle
    rather than its FCM token. iPhone pushes always go through the relay.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
    project_id: str | None = None
    application_id: str | None = None
    api_key: RawTextStr | None = None
    sender_id: str | None = None
    push_relay_server_id: str | None = None
    android_via_relay: bool = False
