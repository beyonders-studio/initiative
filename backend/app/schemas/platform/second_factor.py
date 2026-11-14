"""Payloads for the account's own second factor."""

from pydantic import Field

from app.schemas.base import SanitizedBaseModel


class SecondFactorStatus(SanitizedBaseModel):
    """What the account holds, for the settings surface."""

    #: An enrolment that has been proved. A started-and-abandoned one reads as
    #: False here, because it is not asked for at sign-in either.
    enrolled: bool = False
    confirmed_at: str | None = None
    last_used_at: str | None = None
    recovery_codes_remaining: int = 0
    #: Whether this account holds a password the factor routes will re-check.
    #: The form asks for one only when there is one to give: an account
    #: provisioned through an identity provider has no hash, and holding a
    #: federated identity is a different question — an account can have both.
    password_required: bool = True
    #: Whether this deployment offers the authenticator app at all. Withdrawn,
    #: an enrolment already made is left alone and simply stops being asked
    #: for, so the surface stops offering it rather than pretending it is off.
    offered: bool = True
    #: Whether the account signs in without a password. The recovery set then
    #: serves the account itself rather than a factor, and is reported here
    #: whether or not the authenticator is enrolled.
    passwordless: bool = False


class SecondFactorEnrolStart(SanitizedBaseModel):
    """Beginning an enrolment. The password is re-checked here, as it is for a
    password change; an account with no usable password sends nothing."""

    current_password: str | None = None


class SecondFactorEnrolment(SanitizedBaseModel):
    """The seed, once. There is no path that reads it back."""

    secret: str
    #: What an authenticator app scans. The client renders the QR code; the
    #: server draws nothing.
    otpauth_uri: str


class SecondFactorConfirm(SanitizedBaseModel):
    code: str = Field(min_length=1, max_length=16)


class RecoveryCodes(SanitizedBaseModel):
    """A set of codes, handed over once."""

    codes: list[str]


class SecondFactorDisable(SanitizedBaseModel):
    """Removing the factor asks for the password and for the factor itself —
    either a live code or one of the recovery codes."""

    current_password: str | None = None
    code: str | None = Field(default=None, max_length=64)
    recovery_code: str | None = Field(default=None, max_length=64)


class RecoveryCodesRegenerate(SanitizedBaseModel):
    current_password: str | None = None


class SecondFactorChallengeAnswer(SanitizedBaseModel):
    """The second leg of a sign-in: the challenge, and the thing it asked for."""

    challenge: str = Field(min_length=1, max_length=512)
    code: str | None = Field(default=None, max_length=64)
    recovery_code: str | None = Field(default=None, max_length=64)


class SecondFactorStepUpAnswer(SanitizedBaseModel):
    """The factor, presented against a session that is already signed in.

    No challenge: the session the request is authenticated by is what names
    the account, so there is nothing for the client to carry between two legs
    of a sign-in that is not happening.
    """

    code: str | None = Field(default=None, max_length=64)
    recovery_code: str | None = Field(default=None, max_length=64)
