"""Payloads for the account's passkeys."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, ConfigDict, EmailStr, Field

from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.platform.guild import NewCommunity
from app.services.auth.native_handoff import is_challenge, is_verifier

#: The longest name a passkey may be given. Mirrors the service's cap.
NAME_MAX_LENGTH = 64


def _challenge_shape(value: str) -> str:
    if value and not is_challenge(value):
        raise ValueError("code_challenge is not an S256 challenge")
    return value


def _verifier_shape(value: str) -> str:
    if value and not is_verifier(value):
        raise ValueError("code_verifier is not an RFC 7636 verifier")
    return value


#: The app's S256 challenge, which a sign-in or sign-up the app begins is
#: bound to: only the app holding the verifier behind it can finish it.
AppChallenge = Annotated[str, AfterValidator(_challenge_shape)]
#: The verifier behind the challenge the ceremony was begun with.
AppVerifier = Annotated[str, AfterValidator(_verifier_shape)]


class PasskeyRead(SanitizedBaseModel):
    """One credential, as its holder sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = None
    #: Whether the credential is synced by a password manager, so losing the
    #: device does not lose the key.
    backed_up: bool
    #: Whether the ceremony that made it proved the person as well as the
    #: device — a PIN, a fingerprint, a face.
    user_verified: bool
    #: How the authenticator can be reached — usb, nfc, ble, internal, hybrid.
    transports: list[str] = Field(default_factory=list)
    #: The authenticator model's identifier, when it reported one.
    aaguid: str | None = None


class PasskeyList(SanitizedBaseModel):
    """What the account holds, for the settings surface."""

    passkeys: list[PasskeyRead] = Field(default_factory=list)
    #: Whether this account holds a password the passkey routes will re-check.
    #: The form asks for one only when there is one to give.
    password_required: bool = True
    #: The most passkeys one account may hold.
    limit: int
    #: Whether this deployment's address can carry a passkey at all.
    site_supported: bool = True
    #: Whether this deployment offers passkeys at all. Withdrawn, the ones an
    #: account holds are left alone and simply stop being a way in, so the
    #: surface stops offering to add one rather than pretending they are gone.
    offered: bool = True


class PasskeyRegisterStart(SanitizedBaseModel):
    """Beginning a registration. The name is settled here, before the browser
    makes anything; the password is re-checked as it is for a password change,
    and an account with no usable password sends nothing."""

    name: TitleStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    current_password: str | None = None


class PasskeyRegistrationOptions(SanitizedBaseModel):
    """What the browser's credential API is handed, as the library renders it."""

    #: ``PublicKeyCredentialCreationOptionsJSON`` — passed to the browser as is.
    options: dict[str, Any]


class PasskeyRegisterFinish(SanitizedBaseModel):
    """The browser's answer, and the name the person gives the credential."""

    #: ``RegistrationResponseJSON`` — the credential as the browser returned it.
    credential: dict[str, Any]
    name: TitleStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class PasskeyRename(SanitizedBaseModel):
    name: TitleStr = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class PasskeyRemove(SanitizedBaseModel):
    """Removing a way in asks for the password, where there is one."""

    current_password: str | None = None


class PasskeySignInStart(SanitizedBaseModel):
    """Beginning a sign-in. No account is named: the authenticator offers what
    it holds for this domain, and the assertion names the credential."""

    #: From the app, which finishes the sign-in itself with the verifier.
    code_challenge: AppChallenge = ""


class _PasskeySignUpDetails(SanitizedBaseModel):
    """What a passkey registration says about the account, at both calls."""

    email: EmailStr
    # The name part of the handle. The number behind it is drawn server-side —
    # it is never anyone's to choose.
    username: str = Field(max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    captcha_token: str | None = Field(default=None, max_length=4096)
    community: NewCommunity | None = None
    # The signed number the name check showed beside the handle, kept if
    # still free.
    username_offer: str | None = Field(default=None, max_length=1024)
    # Answers the directory's age question at sign-up; the date is not kept.
    birthdate: date | None = None
    # The documents the form showed above its button, by slug: what pressing
    # it agreed to. Only these are recorded; any other required one is asked
    # for after sign-in.
    accepted_documents: list[str] = Field(default_factory=list, max_length=32)


class PasskeySignUpStart(_PasskeySignUpDetails):
    """Registering an account whose way in is a key rather than a password.

    The same things a password registration says about itself, minus the
    password. A deployment that has withdrawn passwords has no other door of
    its own; before this, it could only take a registration through an
    identity provider.
    """

    #: From the app, which finishes the registration itself with the verifier.
    code_challenge: AppChallenge = ""


class PasskeySignUpFinish(_PasskeySignUpDetails):
    """The browser's answer, with the same details it began with.

    Said again rather than kept: nothing about the account exists between the
    two calls, and everything here is checked again before one is made.
    """

    #: ``RegistrationResponseJSON`` — the credential as the browser returned it.
    credential: dict[str, Any]
    #: What to call the credential in the account's own list.
    name: TitleStr = Field(default="Passkey", min_length=1, max_length=NAME_MAX_LENGTH)
    #: The verifier behind ``code_challenge``, where the begin carried one.
    code_verifier: AppVerifier = ""


class PasskeySignUpResult(SanitizedBaseModel):
    """The account, signed in, and the codes that are now its way back.

    An account with no password cannot be sent a reset, so the recovery set is
    issued here and shown once — on a deployment with no mail configured,
    which is the self-hosted case, it is the only way back.
    """

    access_token: str
    token_type: str = "bearer"
    #: For the app, which keeps its own refresh token. A browser gets it as a
    #: cookie, and this stays absent.
    refresh_token: str | None = None
    codes: list[str] = Field(default_factory=list)


class PasskeyAuthenticationOptions(SanitizedBaseModel):
    """What the browser's credential API is handed, as the library renders it."""

    #: ``PublicKeyCredentialRequestOptionsJSON`` — passed to the browser as is.
    options: dict[str, Any]


class PasskeySignInFinish(SanitizedBaseModel):
    """The browser's answer."""

    #: ``AuthenticationResponseJSON`` — the assertion as the browser returned it.
    credential: dict[str, Any]
    #: What the app's device list calls the device signing in.
    device_name: str = Field(default="", max_length=255)
    #: The verifier behind ``code_challenge``, where the begin carried one.
    code_verifier: AppVerifier = ""


class PasskeyStepUpFinish(SanitizedBaseModel):
    """The browser's answer, presented against the session already open."""

    #: ``AuthenticationResponseJSON`` — the assertion as the browser returned it.
    credential: dict[str, Any]
