"""Payloads for who may ask to message an account.

The policy and its per-community toggles are one screen and travel as one
object, so a write carries whichever halves changed and the pair stays in a
state the screen can render.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import AliasChoices, ConfigDict, Field

from app.models.platform.user import Presence, UserStatus
from app.models.platform.user_dm_settings import DmPolicy
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import PageMeta
from app.schemas.platform.user import ProfileDecorations


class CommunityDmToggle(SanitizedBaseModel):
    """One of the reader's communities, and whether it counts.

    Only consulted while the policy is ``community``; the list is returned
    whatever the policy is, so switching to it does not arrive on an empty
    screen.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    name: str
    icon_url: Optional[str] = None
    enabled: bool


class DirectMessageSettingsRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    dm_policy: DmPolicy
    #: In the reader's own rail order, the same rule the people roster uses.
    communities: List[CommunityDmToggle]
    #: NULL while the account has not answered the age question.
    age_confirmed_at: Optional[datetime] = None
    #: Whether the age question is still owed: unanswered, on a deployment
    #: that checks age. True holds the policy at ``private`` whatever it says.
    age_answer_required: bool = False
    #: Whether this account's clients report a message as delivered and read.
    send_receipts: bool = True


class CommunityDmToggleUpdate(SanitizedBaseModel):
    community_id: int
    enabled: bool


class DirectMessageSettingsUpdate(SanitizedBaseModel):
    """Both halves optional, and omitting one leaves it alone.

    A toggle list is a set of changes rather than the whole list: a client that
    knows about three communities should not be able to silently switch on a
    fourth it has never rendered.
    """

    dm_policy: Optional[DmPolicy] = None
    communities: Optional[List[CommunityDmToggleUpdate]] = None
    send_receipts: Optional[bool] = None


class IgnoredAccountRead(SanitizedBaseModel):
    """One row of the holder's own list."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    user_id: int
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    created_at: datetime


class IgnoredAccountsResponse(PageMeta):
    items: List[IgnoredAccountRead]


class DirectMessagePermissionRead(SanitizedBaseModel):
    """What this reader may do about that account, right now.

    ``denied`` covers every refusal with no distinguishing field: a policy that
    does not admit them, an account that cannot be reached, and being ignored
    all answer the same way.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Whether a connection request would be taken. A separate answer from
    #: ``permission``, because connecting and messaging are separate rules --
    #: an account that takes no messages may still take a connection, and the
    #: other way round. Without it a surface listing people can only guess,
    #: and offer a button that is refused.
    may_connect: bool = False

    permission: str


class DirectMessagePermissionsRequest(SanitizedBaseModel):
    """Which accounts a surface is about to draw controls for."""

    user_ids: List[int] = Field(min_length=1, max_length=100)


class DirectMessagePermissionsResponse(SanitizedBaseModel):
    """One answer per account asked about, keyed by id as a string.

    Accounts the caller may not see are simply absent rather than refused: the
    reader is drawing a list, and a page that fails because one row is gone is
    worse than one that offers nothing for that row.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    permissions: Dict[str, DirectMessagePermissionRead]


class ContactGrantRead(SanitizedBaseModel):
    """One connection or message request, from the reader's side of it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    user_id: int
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    #: Carried so a grant renders as an ordinary person row wherever one is
    #: listed. No ``display_name``: that name belongs to one community, and a
    #: grant may name somebody the reader shares no community with.
    status: UserStatus = UserStatus.active
    presence: Presence = Presence.offline
    #: What they wear around their picture, for the same reason: a grant row is
    #: a person row, and a person looks the same wherever they are listed.
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    state: str
    #: True when the reader is the one who asked, which is what tells a
    #: cancellable request from one waiting on them.
    outgoing: bool
    created_at: datetime
    responded_at: Optional[datetime] = None


class ContactGrantsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    accepted: List[ContactGrantRead]
    incoming: List[ContactGrantRead]
    outgoing: List[ContactGrantRead]


class ConnectionRequestCreate(SanitizedBaseModel):
    """A connection is addressed by handle, never by id.

    One shape whatever the target's policy, and the shape the app-wide people
    search will use: an account on ``private`` is reached by somebody typing
    its handle rather than by being offered from a list.
    """

    username: str
    discriminator: int


class IgnoreAccountCreate(SanitizedBaseModel):
    """Ignoring by handle, the same address a connection request takes."""

    username: str
    discriminator: int


class MessageRequestCreate(SanitizedBaseModel):
    """A message request is addressed by id: everyone you may ask is somebody
    you can already see."""

    user_id: int
