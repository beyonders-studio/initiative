"""Payloads for an account that signs in without a password."""

from pydantic import EmailStr, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class PasswordRemove(SanitizedBaseModel):
    """Giving up the password. It is asked for one last time, as a change asks
    for it; an account holding none has nothing to remove. Where the deployment
    signs nobody in with a password, a recent sign-in answers instead, and it
    is left out."""

    current_password: str | None = Field(default=None, max_length=256)


class PasswordRecover(SanitizedBaseModel):
    """Setting a password with a recovery code, for an account that holds none.

    The address names the account, the code proves it, and the password is what
    the account signs in with from now on."""

    email: EmailStr
    recovery_code: str = Field(min_length=1, max_length=64)
    #: ``max_length`` bounds what is hashed; the policy proper runs in the route.
    password: RawTextStr = Field(max_length=256)
