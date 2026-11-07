import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import AliasChoices, ConfigDict, EmailStr, Field, field_validator

from app.core.user_agents import ClientKind
from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.services.auth.native_handoff import is_verifier


class LoginProviderEntry(SanitizedBaseModel):
    """One sign-in provider offered on the login page (non-secret metadata)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    # Registry row id — what the guild auth-policy endpoints identify a
    # provider by. None only for a platform entry not yet reconciled to a row.
    id: Optional[int] = None
    slug: str
    display_name: str
    kind: str
    login_url: str
    icon: Optional[str] = None
    button_style: Optional[str] = None


class LoginProvidersResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    providers: List[LoginProviderEntry]
    # Guild-addressed listings only: the guild's display name for its login
    # page. Set exactly when the listing is non-empty, so a guild without
    # login-ready providers stays indistinguishable from an unknown id.
    community_name: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("community_name", "guild_name")
    )


class VerificationSendResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


class AccountChangeDone(VerificationSendResponse):
    """What answering a "This wasn't me" link did."""

    #: Whether the people who run this server were told, as a security case.
    platform_told: bool = False
    #: Who to tell where they weren't, if anybody is named.
    contact: Optional[str] = None


class VerificationConfirmRequest(SanitizedBaseModel):
    token: str = Field(min_length=10)


class AccountChangeToken(SanitizedBaseModel):
    """The token from the "This wasn't me" link in an account letter."""

    token: str = Field(min_length=10)


class AccountChangeRead(SanitizedBaseModel):
    """What a "This wasn't me" link answers and what it may do."""

    #: The account notice it came in, such as ``address.removed``.
    notice: str
    #: Whether it may sign the account out everywhere.
    sign_out: bool
    #: What it may undo (``proved``, ``primary``, ``removed`` or ``passkey``),
    #: or ``None``.
    undo: Optional[str] = None
    #: What the undo acts on, as the notice named it: an address or a
    #: passkey's name.
    subject: Optional[str] = None


class PasswordResetRequest(SanitizedBaseModel):
    email: EmailStr


class PasswordResetSubmit(SanitizedBaseModel):
    token: str = Field(min_length=10)
    # ``max_length`` is a cheap bound so we don't argon2-hash a
    # multi-megabyte payload. The min length and breach checks live in
    # ``app.core.password_policy`` and are invoked from the endpoint,
    # so all policy failures surface with a flat error code from
    # ``PasswordMessages`` that ``errors.json`` can map.
    password: RawTextStr = Field(max_length=256)


class NativeSignInRedeem(SanitizedBaseModel):
    """The code a sign-in in the phone's browser came back with, and the PKCE
    verifier the app began it with."""

    code: str = Field(max_length=4096)
    code_verifier: str = Field(min_length=43, max_length=128)

    @field_validator("code_verifier")
    @classmethod
    def _unreserved(cls, value: str) -> str:
        if not is_verifier(value):
            raise ValueError("code_verifier holds a character RFC 7636 does not allow")
        return value


class RefreshRequest(SanitizedBaseModel):
    """How a caller with no cookie presents its refresh token.

    The browser sends nothing here — its refresh token is a cookie it cannot
    read. A native client keeps its own in secure storage, so it has to hand it
    over explicitly.
    """

    refresh_token: Optional[str] = None
    #: How long ago the person last did something here. The idle window runs
    #: from then; absent, from now.
    idle_seconds: Optional[int] = Field(default=None, ge=0, le=1_000_000_000)


class SignedInSessionInfo(SanitizedBaseModel):
    """One place the account is signed in — a browser, the phone app or the
    desktop app — or one of its message devices that is not signed in, as its
    own "where you're signed in" list shows it. ``started_at`` is the sign-in,
    not the last renewal, so a browser left open for a month reads as a month
    old.

    ``id`` is the session, ``None`` for a message device with no live sign-in;
    ``message_device_id`` is the key store, where there is one. ``device`` marks
    a session the phone or desktop app opened. ``label`` is the name a device
    signed in with, or else derived from the user agent (``core.user_agents``). ``is_current`` marks the
    session doing the asking, which the list shows rather than offers to end.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: Optional[uuid.UUID]
    message_device_id: Optional[uuid.UUID]
    device: bool
    label: Optional[str]
    kind: ClientKind
    ip: Optional[str]
    started_at: datetime
    last_used_at: Optional[datetime]
    is_current: bool


class UploadTokenResponse(SanitizedBaseModel):
    """Short-lived, uploads-scoped credential for native media loads.

    Native (Capacitor) <img>/<iframe> tags can't send the Authorization header
    or the HttpOnly session cookie, so they carry auth as a ``?token=`` query
    param. This token is accepted only by the /uploads + file-download
    routes and expires quickly; the 7-day session JWT never goes in a URL.
    ``expires_in`` is the lifetime in seconds so the SPA can refresh before it
    lapses.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    upload_token: str
    token_type: str = "upload_token"
    expires_in: int


class UsernameSuggestionsResponse(SanitizedBaseModel):
    """Name parts nobody holds yet, best first."""

    suggestions: list[str]


class UsernameAvailabilityResponse(SanitizedBaseModel):
    """Whether a name part can still be handed out.

    Almost always ``true``: the number behind a name is what resolves
    contention, so this answers about the two cases that survive — a reserved
    or malformed name, and one whose ten thousand numbers are all taken.
    ``reason`` carries the flat code for those.
    """

    available: bool
    reason: Optional[str] = None
    #: The number this name would get, and the signed offer that keeps it.
    discriminator: Optional[int] = None
    offer: Optional[str] = None
