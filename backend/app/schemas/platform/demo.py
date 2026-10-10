from datetime import datetime
from typing import Literal, Optional

from pydantic import AwareDatetime, EmailStr, Field, field_validator

from app.core import usernames
from app.models.platform.demo import LinkState
from app.models.platform.guild import MEMBER_DISPLAY_NAME_MAX_LENGTH, CommunityCategory
from app.models.tenant.initiative import InitiativeJoinPolicy
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.platform.token import Token


class DemoRedeem(SanitizedBaseModel):
    """A demo link's token, read from the link's fragment."""

    token: str = Field(min_length=1, max_length=128)
    captcha_token: Optional[str] = None
    #: An address to leave for a follow-up, kept apart from the account.
    email: Optional[EmailStr] = None


class DemoRedemption(Token):
    """A visitor signed in to their own copy of the pitch.

    The copy is filled in the background by the import ``import_job_id``
    names; the account and its session end when the copy does.
    """

    community_id: int
    import_job_id: int


class DemoLeadCreate(SanitizedBaseModel):
    """An address a demo visitor leaves for a follow-up."""

    email: EmailStr


class DemoCopyRead(SanitizedBaseModel):
    """A demo visitor's own copy, and whether its import has finished."""

    community_id: int
    ready: bool
    expires_at: Optional[datetime] = None


class DemoPitchRead(SanitizedBaseModel):
    """Whether a community is a pitch, and when it was last published: the
    version visitors get."""

    is_pitch: bool
    last_published_at: Optional[datetime] = None


# --- the sales plug-in's API ---------------------------------------------------


class DemoPersona(SanitizedBaseModel):
    """An account the demo's communities cast, nobody signs in to."""

    #: The whole handle, ``name#1234``, as the plug-in's bundles name it.
    handle: str = Field(min_length=1, max_length=40)
    display_name: TitleStr = Field(max_length=MEMBER_DISPLAY_NAME_MAX_LENGTH)

    @field_validator("handle")
    @classmethod
    def _whole_handle(cls, value: str) -> str:
        name, digits = usernames.parse_handle(value)
        if digits is None or len(digits) != usernames.DISCRIMINATOR_DIGITS:
            raise ValueError("a handle is name#1234")
        return usernames.format_handle(usernames.validate(name), int(digits))


class DemoPersonasEnsure(SanitizedBaseModel):
    personas: list[DemoPersona] = Field(min_length=1, max_length=200)


class DemoPersonasEnsured(SanitizedBaseModel):
    #: The handles ensured, as stored.
    handles: list[str]


class DemoDirectoryCard(SanitizedBaseModel):
    """How a pitch shows in the community directory, which lists it."""

    categories: list[CommunityCategory] = Field(min_length=1)
    #: How a member who joined from the card comes into its initiatives.
    join_policy: InitiativeJoinPolicy = InitiativeJoinPolicy.open


class DemoPitchesFind(SanitizedBaseModel):
    names: list[str] = Field(min_length=1, max_length=100)


class DemoPitchFound(SanitizedBaseModel):
    pitch_ref: str
    name: str
    #: When its community was made.
    created_at: datetime


class DemoPitchesFound(SanitizedBaseModel):
    #: The pitches still kept whose name is exactly one of those asked for.
    pitches: list[DemoPitchFound]


class DemoPitchDelete(SanitizedBaseModel):
    pitch_ref: str = Field(min_length=1, max_length=64)


class DemoPitchCreated(SanitizedBaseModel):
    pitch_ref: str


class DemoLinkCreate(SanitizedBaseModel):
    pitch_ref: str = Field(min_length=1, max_length=64)
    role: Literal["member", "admin", "superadmin"] = "admin"
    label: TitleStr = Field(min_length=1, max_length=200)
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    #: When the link stops opening copies, with its zone; 30 days from now
    #: when omitted.
    expires_at: Optional[AwareDatetime] = None


class DemoLinkCreated(SanitizedBaseModel):
    link_ref: str
    #: The link to hand out. Shown once: only its token's hash is kept.
    url: str


class DemoLinksRead(SanitizedBaseModel):
    link_refs: list[str] = Field(min_length=1, max_length=100)


class DemoLeadRead(SanitizedBaseModel):
    #: The same on every read, so the plug-in can keep each lead once.
    id: int
    email: str
    created_at: datetime


class DemoLinkReport(SanitizedBaseModel):
    link_ref: str
    state: LinkState
    redemption_count: int
    last_redeemed_at: Optional[datetime] = None
    #: The addresses left on the link in the last 30 days, oldest first.
    leads: list[DemoLeadRead]


class DemoLinkReports(SanitizedBaseModel):
    #: One per reference that names a link this install knows.
    links: list[DemoLinkReport]


class DemoLinkRevoke(SanitizedBaseModel):
    link_ref: str = Field(min_length=1, max_length=64)
