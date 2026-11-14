"""Wire shapes of the plug-in platform's token endpoint, install listing and
consent requests.

The token endpoint speaks OAuth 2.0 (RFC 6749): its success and error bodies
are the ones that specification defines, and an error's ``error`` is a
protocol value rather than text for a person to read.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.platform.identity_ref import REF_MAX_LENGTH
from app.models.tenant.plugin_member_consent import (
    LABEL_MAX_LENGTH,
    PURPOSE_MAX_LENGTH,
    ConsentAccess,
    ConsentStatus,
    is_valid_purpose,
)
from app.schemas.base import TitleStr


class PluginAccessTokenResponse(BaseModel):
    """A successful token response (RFC 6749 §5.1)."""

    access_token: str
    token_type: str = "Bearer"
    #: Seconds until the token stops being accepted.
    expires_in: int
    #: The scopes the token carries, space-separated. Empty for a plug-in token.
    scope: str
    #: Sign in with Initiative: the ID token for the place the person chose.
    id_token: str | None = None
    #: Sign in with Initiative: what the plug-in renews with.
    refresh_token: str | None = None


class PluginOAuthErrorResponse(BaseModel):
    """An error response (RFC 6749 §5.2)."""

    error: str
    error_description: str


class PluginInstallationRead(BaseModel):
    """One install of the calling plug-in."""

    #: What the plug-in calls the community it is installed in. Passed back as
    #: ``installation`` to ask for a token there.
    installation: str
    #: Switched on, in a community in use: a token can be issued for it. An
    #: install that is off or whose community is paused is listed as inactive,
    #: and one that is gone is not listed.
    active: bool


class PluginConsentRequestCreate(BaseModel):
    """A plug-in asking one member to let it act as them, for one purpose."""

    model_config = ConfigDict(extra="forbid")

    #: The member, by the reference this install holds for them.
    member: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
    #: The plug-in's own id for what it wants to do as the member; absent for
    #: plug-in-wide consent.
    purpose: str | None = None
    #: What the purpose is, in the plug-in's own words. The member reads it as the
    #: plug-in's.
    label: TitleStr = Field(min_length=1, max_length=LABEL_MAX_LENGTH)
    #: The one initiative the purpose is bound to, when it is.
    initiative_id: int | None = Field(default=None, gt=0, le=2**31 - 1)
    access: ConsentAccess

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_purpose(value):
            raise ValueError(
                f"purpose is 1 to {PURPOSE_MAX_LENGTH} letters, digits or -_.:/@"
            )
        return value

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("label is printable text")
        return value


class PluginConsentRequestRead(BaseModel):
    """A request to act as a member, as it stands."""

    member: str
    purpose: str | None = None
    label: str
    initiative_id: int | None = None
    requested_access: ConsentAccess
    #: ``pending`` until the member answers; then ``granted``, ``declined``, or
    #: ``revoked`` when they withdrew what they allowed.
    status: ConsentStatus
    #: What the member allowed, while it stands.
    granted_access: ConsentAccess | None = None
    requested_at: datetime
