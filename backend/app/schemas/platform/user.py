from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import (
    AliasChoices,
    ConfigDict,
    EmailStr,
    Field,
    SerializerFunctionWrapHandler,
    computed_field,
    field_validator,
    model_serializer,
    model_validator,
)

from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.schemas.platform.guild import NewCommunity
from app.schemas.query import PageMeta

from app.core.capabilities import Capability, standing_capabilities
from app.core.cookie_categories import CookieCategory
from app.core.email_masking import mask_email
from app.core.messages import UserMessages
from app.core.emoji import validate_emoji
from app.models.platform.account_change_hold import HeldChangeKind
from app.core.profile_decorations import (
    DATED_DECORATIONS,
    MAX_FRAME_TINTS,
    MIN_GRAD_YEAR,
    TINTABLE_FRAMES,
    TROPHY,
    BANNER,
    FRAME,
    max_grad_year,
    validate_decoration_id,
    validate_tint,
)
from app.core.identity_boundary import (
    PersonId,
    names_withheld,
    responding_to_install,
)
from app.models.platform.user import Presence, UserRole, UserStatus
from app.services.platform import user_avatars
from app.core.config import settings

# ``avatar_url`` is where a user's picture is: either a path this API serves
# (``/api/v1/users/{id}/avatar/{sha256}`` — the bytes live in ``user_avatars``
# and are uploaded through ``PUT /me/avatar``) or a URL somewhere else,
# from an OIDC ``picture`` claim. The two are alternatives, and one field holds
# whichever applies.
#
# There is deliberately no schema by which one account edits another's profile.
# A guild admin manages *membership* — who is in the guild — not the person's
# record, which spans every guild they belong to.
#
# Two identity rules are enforced here rather than per endpoint, so the shapes
# themselves are the proof:
#
# * An address never reaches a guild. ``email`` is absent from every
#   guild-scoped shape — roster, picker and member management alike — and kept
#   in full only on ``UserRead``, which is served for your own account.
# * An address is read back in full only by its owner. Staff reads use
#   ``OperatorUserRead``, which is ``UserRead`` with the address
#   shortened (``app.core.email_masking``) — enough to recognise one you
#   already have.
# * An account has no name. In a guild, ``display_name`` is the name the
#   member set there (``guild_memberships.display_name``, read through the
#   guild projection). Only the shapes that draw a person carry it;
#   ``UserIdentity`` — what everything else is built from — has no name field.
#
# What is always present is the handle: ``username`` plus ``discriminator``,
# rendered ``foobar#1234`` with the number muted. They are two fields rather
# than one string because the client styles them differently.


class UserBase(SanitizedBaseModel):
    email: EmailStr
    role: UserRole = UserRole.member


class UserCreate(SanitizedBaseModel):
    # Deliberately does NOT inherit ``UserBase.role``. Platform role must
    # never be settable from a create payload: this schema backs both
    # self-registration (``/auth/register``) and guild-admin user creation
    # (``POST /users/``), and neither caller is authorized to grant a
    # platform role from the request body. Registration computes the role
    # itself (first user = owner, everyone else = member) and the guild-admin
    # endpoint forces ``member``; standing platform roles change only via
    # ``/operator/users/{id}/platform-role`` (capability-gated, bounded
    # delegation).
    email: EmailStr
    # The name part of the handle. The number behind it is drawn server-side —
    # it is never anyone's to choose.
    username: str = Field(max_length=64)
    # ``max_length`` is a cheap bound so we don't argon2-hash a
    # multi-megabyte payload. The min length and breach checks live in
    # ``app.core.password_policy`` and are invoked from the endpoint,
    # so all policy failures surface with a flat error code from
    # ``PasswordMessages`` that ``errors.json`` can map.
    password: RawTextStr = Field(max_length=256)
    # Optional IANA timezone forwarded by the SPA on registration so a
    # new account starts at the user's wall clock instead of the model
    # default ``"UTC"``. Validated server-side by ``normalize_timezone``;
    # omitted by non-SPA callers, in which case the model default applies.
    timezone: Optional[str] = None
    # Optional captcha token supplied by the SPA's widget when the
    # deployment has ``CAPTCHA_PROVIDER`` configured. Verified
    # server-side via ``app.services.captcha`` before the row is
    # written. Ignored when captcha isn't configured.
    captcha_token: Optional[str] = None
    # The community this account is made with, when it is made to start one
    # rather than to join one.
    community: Optional[NewCommunity] = None
    # The signed number the name check showed beside the handle, kept if
    # still free.
    username_offer: Optional[str] = Field(default=None, max_length=1024)
    # Answers the directory's age question at sign-up; the date is not kept.
    birthdate: Optional[date] = None


class PluginPerson(SanitizedBaseModel):
    """A person, as an installed plug-in receives them wherever one appears.

    ``id`` is the install's own reference for them. Their handle (``username``
    and ``discriminator``), the name they set in the community
    (``display_name``) and the picture they uploaded (``avatar_url``) come only
    to an install holding ``members:read``. A field without a value is left
    out, so without that scope a person is their ``id`` alone.
    """

    id: PersonId
    username: Optional[str] = None
    discriminator: Optional[int] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = Field(
        default=None,
        description=(
            "Where the plug-in reads the picture this member uploaded: "
            "`/api/v1/c/0/members/{id}/avatar/{sha256}`, a path on Initiative "
            "served under `members:read`. Absent when they have not uploaded one."
        ),
    )

    def for_install(self) -> dict[str, Any]:
        """This person, as the installed plug-in being answered may know them."""
        if names_withheld():
            return self.model_dump(mode="json", include={"id"})
        person = self.model_dump(mode="json", exclude={"avatar_url"}, exclude_none=True)
        digest = user_avatars.uploaded_digest(self.id, self.avatar_url)
        if digest is not None:
            # ``id`` is the response's marker for the person by now, which the
            # route class writes the reference over, in the path as well.
            person["avatar_url"] = user_avatars.member_avatar_url(person["id"], digest)
        return person


class PersonShape(SanitizedBaseModel):
    """A shape that draws a person.

    Served as itself to a person. To an installed plug-in it is the
    :class:`PluginPerson` it names, which is how the plug-in API's document types it
    (``x-person``, read by ``app.api.plugin_openapi``).
    """

    model_config = ConfigDict(json_schema_extra={"x-person": True})

    def plugin_person(self) -> PluginPerson:
        """Who this shape draws, read off its own fields. A shape that names
        the person under other fields says so."""
        return PluginPerson.model_validate(self, from_attributes=True)

    # Left unannotated, so the shape's published schema stays its own.
    @model_serializer(mode="wrap")
    def _as_plugin_person(self, handler: SerializerFunctionWrapHandler):
        if responding_to_install():
            return self.plugin_person().for_install()
        return handler(self)


class UserIdentity(SanitizedBaseModel):
    """A person, minus their name.

    The handle (``username`` + ``discriminator``) is always here and is what
    renders when there is no name to show. ``status`` comes along so the
    frontend can mark an account that is no longer in use without replacing the
    identifier that keeps an old thread legible.

    Every shape below is this plus something, and the name is never part of the
    "this": a shape that draws a person in a guild declares ``display_name``
    itself.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: PersonId
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active


class UserPublic(UserIdentity, PersonShape):
    """A person, as everyone else sees them — the handle, and the name they
    set in the guild being read."""

    display_name: Optional[str] = None


class UserCommunityRead(UserIdentity):
    """One account, as the guild administering its membership reads it back.

    The membership surfaces ask one thing about somebody and this is the
    answer: the handle, the picture, the standing, when the account started,
    and where the person sits in the guild's initiatives. None of the account's
    own business comes with it — no address, no platform tier, no word on
    whether the address was ever confirmed, no preferences.

    Nor does the member's name: that belongs to the surfaces that draw people
    — a roster, a picker, a byline — and reading back an account is not one.
    """

    status: UserStatus
    created_at: datetime
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)


class UserCommunityMember(UserCommunityRead):
    """A member, for the guild's own member-management surface.

    :class:`UserCommunityRead` plus the membership facts a guild admin manages —
    guild role, whether the membership is OIDC-managed — and the name they go
    by here. Two members are told apart by their handle, which is unique.
    """

    #: The rung this member holds in the guild, set by the endpoint. Shown as
    #: it stands, and asked of the ladder where a surface needs to know
    #: whether it administers the place.
    community_role: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("community_role", "guild_role")
    )
    oidc_managed: bool = False  # Whether membership is managed via OIDC claim mappings
    #: The name set for this member in this guild. ``None`` when nobody set
    #: one, and the handle renders.
    display_name: Optional[str] = None
    #: SEAT-ONLY. Whether this member's personal API keys reach the guild.
    #: ``None`` for anyone who does not hold the superadmin seat.
    api_keys_allowed: Optional[bool] = None


class UserCommunityMemberListResponse(PageMeta):
    """One page of the guild's roster."""

    items: List[UserCommunityMember]


class UserSummary(UserIdentity, PersonShape):
    """Slim user projection for typeahead and picker surfaces.

    What it keeps is what it takes to *draw* a person and say where they stand
    in the guild being read: the handle, the avatar, what they have put around
    it, and their guild role. A decoration is an id naming a catalog entry and
    a role is one word, so all of it is short, and none of it costs a query
    beyond the one already being run.

    What it drops is the account's own business and anything that would cost
    another round trip: no address, no platform tier, no ``initiative_roles``
    (an N+1 enrichment on the full roster), no timestamps. The payload is
    bounded by pagination on the endpoints that serve it.

    ``profile_decorations`` is quoted and the model rebuilt below, because the
    catalog shape it names is declared further down this file.
    """

    display_name: Optional[str] = None
    profile_decorations: Optional["ProfileDecorations"] = None
    #: The rung this member holds in the guild this was read under. Absent
    #: where the caller asked outside a guild, which is why it is optional
    #: rather than defaulted to the quietest of them.
    community_role: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("community_role", "guild_role")
    )


class UserSummaryListResponse(PageMeta):
    """Paginated envelope for the slim user search/typeahead endpoints."""

    items: List[UserSummary]


#: How long the line beside the emoji may run. Short on purpose: the bubble is
#: read in a sidebar column and over a picture, so a status is a line, not a
#: paragraph. Mirrored by the CHECK constraint in migration 20260902_0212 and
#: by ``STATUS_MAX_LENGTH`` in ``frontend/src/components/user/ProfileStatus``.
STATUS_TEXT_MAX_LENGTH = 40


class CustomStatus(SanitizedBaseModel):
    """What a person is up to, in their own words.

    One object, stored in one column, because it is one thing a person sets
    and one thing every surface that names them renders: splitting it in two
    would mean two reads and two writes for a single line of text.

    Not to be confused with ``UserStatus`` (``users.status``), which is the
    account's standing — suspended, deactivated — and is not the person's to
    write.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    emoji: Optional[str] = None
    text: Optional[str] = Field(default=None, max_length=STATUS_TEXT_MAX_LENGTH)

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, value: Optional[str]) -> Optional[str]:
        """Hold the status emoji to the same shape a reaction's is held to.

        An empty string means "take it off", which is how a picker sends a
        cleared selection.
        """
        if value is None or not value.strip():
            return None
        return validate_emoji(value)

    @field_validator("text")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else (value.strip() or None)


#: How many trophies one profile may wear. A rendering bound — a row of them
#: under a banner, not a wall.
MAX_PROFILE_TROPHIES = 6


class ProfileDecorations(SanitizedBaseModel):
    """How a profile is dressed: a banner, a frame, trophies under it.

    Every value is an **id naming a catalog entry**, never an image. The client
    resolves an id to artwork it already ships, so a decorated profile takes up
    none of a guild's upload allowance. An id this deployment's catalog doesn't
    know simply renders nothing, which is what lets a profile keep wearing
    something the store stopped offering.

    ``extra="forbid"``: the set of things a profile can wear is this list, and
    a client sending a key that isn't here is told so rather than having it
    quietly stored and never rendered.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    banner: Optional[str] = None
    frame: Optional[str] = None
    #: The colours the wearer picked for a frame that takes them. Kept beside
    #: the frame rather than folded into its id, because the id names a catalog
    #: entry and a colour is not part of what was granted. Ignored — and
    #: dropped on write — for any frame that is not tintable.
    frame_tint: List[str] = Field(default_factory=list, max_length=MAX_FRAME_TINTS)
    trophies: List[str] = Field(default_factory=list, max_length=MAX_PROFILE_TROPHIES)
    #: The year on a decoration that carries one. Kept beside them for the same
    #: reason a tint is kept beside its frame: the id names what was granted,
    #: and the year is the wearer's. The client draws it. Ignored — and dropped
    #: on write — unless something worn takes a year.
    grad_year: Optional[int] = None

    @field_validator("banner", "frame")
    @classmethod
    def _check_single(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else validate_decoration_id(value)

    @field_validator("frame_tint")
    @classmethod
    def _check_tints(cls, value: List[str]) -> List[str]:
        return [validate_tint(colour) for colour in value]

    @model_validator(mode="after")
    def _tint_only_what_takes_it(self) -> "ProfileDecorations":
        """Keep the stored colours honest about the frame they are for.

        A colour on a frame that cannot take one would be state nothing reads
        and nothing clears — so it is dropped here, and a frame that takes one
        colour never keeps two.
        """
        takes = TINTABLE_FRAMES.get(self.frame or "", 0)
        if len(self.frame_tint) > takes:
            object.__setattr__(self, "frame_tint", self.frame_tint[:takes])
        return self

    @field_validator("grad_year")
    @classmethod
    def _check_grad_year(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if not MIN_GRAD_YEAR <= value <= max_grad_year():
            raise ValueError(
                f"Year must be between {MIN_GRAD_YEAR} and {max_grad_year()}"
            )
        return value

    @model_validator(mode="after")
    def _year_only_what_takes_it(self) -> "ProfileDecorations":
        """Drop a year nothing worn would draw, the way a stray tint is dropped."""
        if self.grad_year is None:
            return self
        worn = {self.banner, self.frame, *self.trophies}
        if not (worn & DATED_DECORATIONS):
            object.__setattr__(self, "grad_year", None)
        return self

    @field_validator("trophies")
    @classmethod
    def _check_trophies(cls, value: List[str]) -> List[str]:
        seen: List[str] = []
        for trophy in value:
            identifier = validate_decoration_id(trophy)
            # Wearing the same one twice is a duplicate, not a second trophy.
            if identifier not in seen:
                seen.append(identifier)
        return seen

    def worn(self) -> List[tuple[str, str]]:
        """``(id, slot)`` for everything this profile is wearing.

        The one place a slot is paired with its id, so the check against a
        person's library and the shape they wrote it in cannot disagree about
        which is which.
        """
        pairs: List[tuple[str, str]] = []
        if self.banner:
            pairs.append((self.banner, BANNER))
        if self.frame:
            pairs.append((self.frame, FRAME))
        pairs.extend((trophy, TROPHY) for trophy in self.trophies)
        return pairs


# ``UserSummary`` names this shape before it is declared.
UserSummary.model_rebuild()


class OwnedDecoration(SanitizedBaseModel):
    """One decoration an account may wear, and where it came from.

    ``source`` names the marketplace pack that granted it, and is ``None`` for
    the ones that ship with the app. The client renders a picker per slot from
    these, drawing each id with the artwork it has for it and skipping the ones
    it doesn't.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    kind: str
    #: What its publisher called it. Absent for the set that ships with the
    #: app, whose names are translated in the client.
    name: Optional[str] = None
    #: The listing uid of the pack that granted it, or ``None`` for the set
    #: that ships with the app.
    source: Optional[str] = None
    #: The picture its pack carries for it, served by the marketplace. Absent
    #: where the client ships the art for the id itself.
    image_url: Optional[str] = None


class DecorationPack(SanitizedBaseModel):
    """One installable set of decorations, and whether this account has it.

    A marketplace listing, so the words are the listing's — its publisher named
    it, and nobody else can. ``uid`` is the identity: it means this pack on
    every deployment carrying the catalog, and it is what a granted row records.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    name: str
    publisher: str
    description: str
    #: Artwork for the pack itself, from the listing.
    avatar_url: Optional[str] = None
    contents: List[OwnedDecoration]
    installed: bool = False


class DecorationPackListResponse(SanitizedBaseModel):
    """Every pack this build ships. Small and read all at once — the store is
    one page."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[DecorationPack]


class OwnedDecorationsResponse(SanitizedBaseModel):
    """A person's whole library, in one read — it is small and it is all
    needed at once, because the profile form renders every slot together."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[OwnedDecoration]


class UserProfile(SanitizedBaseModel):
    """A person, as anyone can see them.

    A profile is public. It carries the handle — which is the name in this
    product, unique and never withheld — the face, the line they wrote, the
    look they picked, how they appear right now, and when they joined. The name
    a member goes by is a guild's business, and this shape has no guild in it.

    Nothing here is private to a guild, so nothing here is reached through
    one. What it does not carry is the whole point of it being its own shape:
    no address, no roles, no memberships, no preferences.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active
    custom_status: CustomStatus = Field(default_factory=CustomStatus)
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    #: How this person appears right now — the account, not a guild. What they
    #: picked, narrowed by whether they have anything open; set by the endpoint
    #: from the one roll that decides it.
    presence: Presence = Presence.offline
    #: When the account was made.
    joined_at: datetime


class CommunityRosterMember(UserSummary):
    """One person on a community's people roster.

    ``UserSummary`` plus what a roster row draws beside the name: how they
    appear right now and the line they wrote. Both are public, as they are on
    the profile.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    presence: Presence = Presence.offline
    custom_status: CustomStatus = Field(default_factory=CustomStatus)


class CommunityRosterResponse(PageMeta):
    """A page of the roster, and how many people are in each presence group
    across every page, so a group's heading can count people not yet loaded."""

    items: List[CommunityRosterMember]
    presence_counts: dict[Presence, int]


class UserEmailRead(SanitizedBaseModel):
    """One address on the account reading it.

    Served only to its owner, so the address is in full — every other shape
    that carries one either masks it or does not have it at all.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    verified: bool
    is_primary: bool
    #: signup | added | oidc — how the account came to hold it.
    source: str
    created_at: datetime
    last_login_at: Optional[datetime] = None


class UserEmailCreate(SanitizedBaseModel):
    """Adding an address asks for the password, where there is one."""

    email: EmailStr
    current_password: Optional[str] = None


class UserEmailChange(SanitizedBaseModel):
    """Removing an address or making one primary asks for the password, where
    there is one."""

    current_password: Optional[str] = None


class HeldChangeRead(SanitizedBaseModel):
    """A change to how the account is signed into that waits until
    ``applies_at``. ``subject`` is the address or passkey it acts on."""

    id: int
    kind: HeldChangeKind
    subject: Optional[str] = None
    requested_at: datetime
    applies_at: datetime


class HeldChangeOutcome(SanitizedBaseModel):
    """What a change that may be held answers, made or not: ``held`` is the
    change waiting (``202``), or null where it was made at once (``200``)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    held: Optional[HeldChangeRead] = None


class UserEmailListResponse(SanitizedBaseModel):
    items: List[UserEmailRead]
    #: Whether changing the list asks for the password. Where it does not, a
    #: recent sign-in answers instead.
    password_required: bool


class CookieConsentRead(SanitizedBaseModel):
    """What an account allows to be kept in a browser, and when it said so."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    granted: List[str]
    #: Which version of the question was answered. A client holding an answer
    #: to an older one treats it as unanswered and asks again.
    version: int
    #: The server's clock, not the client's, so two browsers comparing their
    #: answers compare one clock.
    decided_at: datetime


class CookieConsentUpdate(SanitizedBaseModel):
    """An answer given in one browser, for the account to carry to the rest."""

    granted: List[CookieCategory] = Field(default_factory=list)
    version: int


class AccountTimeOutRead(SanitizedBaseModel):
    """What a suspended account is told on its time-out screen."""

    #: Who to contact about it: the deployment's moderation contact, else its
    #: general one, else ``None``.
    contact_email: Optional[str] = None
    #: When the suspension began, where it was recorded.
    since: Optional[datetime] = None
    #: The reason the moderator gave, where one was given.
    reason: Optional[str] = None
    #: Whether an appeal can be filed here, rather than written to
    #: ``contact_email``.
    can_appeal: bool = False
    #: The account's most recent appeal, which it follows on this screen.
    appeal_task_id: Optional[int] = None


class UserRead(UserBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    username: str
    discriminator: int
    # Whether this account picked its handle. False routes the SPA to the
    # choose-your-handle screen before anything else.
    username_chosen: bool = False
    #: When this account said it belongs to somebody old enough for the
    #: community directory, ``None`` where it never has. Read by the
    #: directory's Join button, which asks before it joins rather than letting
    #: the server refuse.
    age_confirmed_at: Optional[datetime] = None
    #: When this account answered the age question as under the minimum,
    #: ``None`` where it has not. Turns the directory's dialog from a form into
    #: an explanation: the answer stands, and putting it right is somebody
    #: else's to do.
    age_below_minimum_at: Optional[datetime] = None
    #: Whether this account still owes its agreement to this deployment's
    #: terms and privacy policy. Always false where there are none to agree
    #: to, which is every self-hosted deployment. An account created through
    #: the signup form agreed there and never sees this; one provisioned by an
    #: identity provider met no form, so true blocks the app on the acceptance
    #: screen the way ``username_chosen`` false routes to the handle screen.
    #: Populated by ``/me``; defaults false elsewhere.
    legal_acceptance_required: bool = False
    #: Whether this account's date of birth is kept. The date itself is never
    #: sent, to its owner included; this is what says the question is answered.
    birthdate_on_file: bool = False
    #: Whether this account still owes its date of birth: none is kept, it has
    #: not answered as under age, and the deployment checks age. True blocks
    #: the app on the birthdate screen. Populated by ``/me``; false elsewhere.
    birthdate_required: bool = False
    #: This account's cookie answer, so a browser it has never been asked in
    #: can adopt it instead of asking again. Null where it has never answered,
    #: which is different from having answered and allowed nothing. Populated
    #: by ``/me``; null elsewhere.
    cookie_consent: Optional["CookieConsentRead"] = None
    status: UserStatus
    #: Both resolved from ``user_emails`` by whoever builds this shape (see
    #: ``services.platform.users.to_read``) — the ``users`` row carries neither.
    email: Optional[EmailStr] = None
    email_verified: bool = False
    created_at: datetime
    updated_at: datetime
    avatar_url: Optional[str] = None
    custom_status: CustomStatus = Field(default_factory=CustomStatus)
    #: What this account picked, not what a reader would be shown: on your own
    #: record this is the setting itself, and the control that writes it.
    presence: Presence = Presence.online
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    week_starts_on: int = 0
    #: "system" (follow the browser locale), "12", or "24".
    time_format: str = "system"
    recent_tabs_limit: int = 20
    timezone: str = "UTC"
    event_reminder_minutes_before: Optional[int] = 15
    last_overdue_notification_at: Optional[datetime] = None
    last_task_assignment_digest_at: Optional[datetime] = None
    color_theme: str = "kobold"
    task_completion_visual_feedback: str = "none"
    task_completion_audio_feedback: bool = True
    task_completion_haptic_feedback: bool = True
    locale: str = "en"
    # True when the account has a linked external identity (SSO). Consumed by
    # the profile/deletion UI to hide the password confirmation, since SSO-only
    # accounts have no usable password to type in. Populated wherever an
    # account is handed its own record (``users.to_self_read``); defaults False
    # elsewhere.
    has_federated_identity: bool = False
    # True when the account holds a password it can be asked for. Read from
    # the stored hash rather than from the identity link above: an account can
    # hold both, and one that gave its password up holds neither. Populated
    # with the field above.
    has_password: bool = False
    # True when confirming a change asks this account for its password: it
    # holds one and the deployment signs people in with passwords. Otherwise a
    # recent sign-in answers. Populated with the fields above.
    password_required: bool = False
    #: When the demo copy this account was made for is deleted, with the
    #: account; ``None`` for every other account. Populated with the fields
    #: above.
    demo_expires_at: Optional[datetime] = None
    #: The demo copy this account was made for; ``None`` for every other
    #: account. Populated with the fields above.
    demo_community_id: Optional[int] = None
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def can_create_communities(self) -> bool:
        if self.status == UserStatus.suspended or self.demo_expires_at is not None:
            return False
        if not settings.DISABLE_GUILD_CREATION:
            return True
        # When disabled, only platform roles that manage guilds can create them.
        return Capability.COMMUNITIES_MANAGE in standing_capabilities(
            self.role, self.status
        )

    @computed_field(return_type=List[Capability])  # type: ignore[misc]
    @property
    def capabilities(self) -> List[Capability]:
        """Platform capabilities granted by this user's standing role — none
        while the account is suspended.

        The frontend gates UI on these values (single source of truth);
        see ``app.core.capabilities``. Sorted by value.
        """
        return sorted(
            standing_capabilities(self.role, self.status), key=lambda c: c.value
        )


class OperatorUserRead(UserRead):
    """A staff view of somebody else's account: the address masked.

    Everything staff do to an account — reset its password, rename
    it, change its tier, suspend it, delete it — is addressed by id, and the
    roster is read and searched by handle, so none of it needs the address
    itself. What the mask leaves is enough to match a row against an address
    somebody has quoted at you, which is what the column is read for.

    Masking lives on the shape rather than in each operator route: subclassing
    keeps ``/me`` — where the reader is the address's owner — on plain
    ``UserRead``, while every operator route that returns an account gets the
    masked form without opting in.
    """

    #: ``validate_assignment`` so the mask below runs on assignment too, not
    #: only on validation. The address is resolved from ``user_emails`` after
    #: the shape is built, and an assignment that skipped the validator would
    #: put the stored address on the wire.
    model_config = ConfigDict(validate_assignment=True)

    #: Re-declared as a plain ``str``, widening ``UserBase.email``: a masked
    #: address is not a deliverable one, so typing it ``EmailStr`` would
    #: describe it wrongly in the OpenAPI schema and make this shape fail to
    #: re-validate its own output. Empty until the builder resolves it, for the
    #: reason ``UserRead`` gives.
    email: str = ""

    #: When a deleted account is erased: the moment the deletion was asked for
    #: plus the deployment's window. Null unless ``status`` is ``deleted``, and
    #: null for a deployment that keeps deleted accounts. Computed from the
    #: columns beside it rather than stored, so the window is stated once.
    purge_at: Optional[datetime] = None

    #: Set while wrong passwords or codes have turned the account's password
    #: and code sign-in off; it turns back on by itself at that time.
    sign_in_locked_until: Optional[datetime] = None

    #: Whether the account holds an authenticator it has proved — what the
    #: roster offers to clear when its holder has lost it.
    second_factor_enrolled: bool = False

    #: How many of the account's API keys still work — what the sheet offers
    #: to revoke.
    api_key_count: int = 0

    @field_validator("email", mode="after")
    @classmethod
    def _mask_email(cls, value: str) -> str:
        return mask_email(value) or value


class OperatorUserListResponse(PageMeta):
    """One page of the operator roster."""

    items: List[OperatorUserRead]


class UsernameClaim(SanitizedBaseModel):
    """The name part an account picks for itself.

    Available once, to an account whose handle was assigned rather than chosen
    (``username_chosen`` false) — every account created without a form gets one
    that way. The number behind the name is drawn server-side.
    """

    username: str = Field(max_length=64)
    #: The signed number the name check showed, kept if still free.
    offer: Optional[str] = Field(default=None, max_length=1024)


class AgeConfirmation(SanitizedBaseModel):
    """Someone saying when they were born, once.

    The date answers one question — are they old enough — and is then gone. It
    is never written to a column, never logged, and never put in an audit
    record; there is nowhere in the schema it could be kept. What the account
    keeps is that the question was answered and when
    (``users.age_confirmed_at``), which is what a deployment needs to show it
    asked.

    Asking for a date rather than offering a box to tick is the difference
    between a question and a formality: a box says what the answer should be
    before it is given.
    """

    birthdate: date


class UserInitiativeRole(SanitizedBaseModel):
    initiative_id: int
    initiative_name: str
    # The role's own name; ``None`` when the role it pointed at was deleted.
    role: Optional[str] = None


class UserSelfUpdate(SanitizedBaseModel):
    password: Optional[RawTextStr] = Field(default=None, max_length=256)
    # Required to set a new ``password`` (verified server-side). Exempt for
    # OIDC-only accounts, which have no local password to confirm.
    current_password: Optional[RawTextStr] = Field(default=None, max_length=256)
    # A picture hosted elsewhere, by an https address; empty takes it off.
    avatar_url: Optional[str] = Field(default=None, max_length=2000)
    # Sending ``null`` takes the status off; leaving it out leaves it alone.
    custom_status: Optional[CustomStatus] = None
    presence: Optional[Presence] = None
    # The whole set at once rather than one key at a time: a profile wears a
    # look, and a partial write would have no way to say "take the frame off".
    profile_decorations: Optional[ProfileDecorations] = None
    week_starts_on: Optional[int] = None
    time_format: Optional[str] = None
    recent_tabs_limit: Optional[int] = Field(default=None, ge=1, le=100)
    timezone: Optional[str] = None
    event_reminder_minutes_before: Optional[int] = None
    color_theme: Optional[str] = None
    task_completion_visual_feedback: Optional[str] = None
    task_completion_audio_feedback: Optional[bool] = None
    task_completion_haptic_feedback: Optional[bool] = None
    locale: Optional[str] = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")

    @field_validator("avatar_url")
    @classmethod
    def _https_picture(cls, value: Optional[str]) -> Optional[str]:
        if value and not (value.startswith("https://") and len(value) > 8):
            raise ValueError("avatar_url must be an https:// URL")
        return value

    @model_validator(mode="after")
    def _password_alone(self) -> "UserSelfUpdate":
        # A new password is written on a commit of its own, so it travels with
        # nothing but the one it replaces.
        if self.password and self.model_fields_set - {"password", "current_password"}:
            raise ValueError(UserMessages.PASSWORD_CHANGED_ALONE)
        return self


class AccountDeletionRequest(SanitizedBaseModel):
    """Request from a user to deactivate or anonymize (soft-delete) their own account.

    `hard_delete` is intentionally not allowed from this self-service endpoint;
    only an operator can purge a row, and they do so via the operator endpoint.
    """

    action: Literal["deactivate", "soft_delete"]
    password: RawTextStr
    confirmation_text: str


class DeletionEligibilityResponse(SanitizedBaseModel):
    """Response indicating whether user can be deleted and any blockers"""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    #: The account is the last active platform owner; another is promoted first.
    last_owner: bool = False
    #: Communities this account holds the only superadmin seat of, which the
    #: dialog offers to delete.
    sole_superadmin_communities: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "sole_superadmin_communities", "sole_superadmin_guilds"
        ),
    )


class AccountDeletionResponse(SanitizedBaseModel):
    """Response after a deactivate / anonymize / hard-delete action."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    action: str
    message: str
