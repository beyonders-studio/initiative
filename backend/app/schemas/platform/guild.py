from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import (
    AliasChoices,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.core.guild_auth_options import CommunityAuthOption
from app.core.login_methods import LoginMethod
from app.core.tools import Tool
from app.core.messages import GuildMessages
from app.schemas.base import RawTextStr, RichTextStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta

from app.core.email_masking import mask_email
from app.models.platform.guild import (
    DEFAULT_BANNER,
    MEMBER_DISPLAY_NAME_MAX_LENGTH,
    BannerFade,
    BannerTextAlign,
    CommunityCategory,
    CommunityRole,
    CommunityStatus,
)


class CommunityBannerRead(SanitizedBaseModel):
    """A guild's banner, whole — the picture and the look around it.

    ``image_url`` is where to fetch the artwork, never the bytes: a banner is
    ~350 KB and this rides in payloads that list every guild the caller is in.
    Which rendition it names is the surface's business — a guild's own front
    page gets the full one, a directory card the card one. ``None`` means no
    artwork, not no banner: the fill is what shows then.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    image_url: Optional[str] = None
    color: str = DEFAULT_BANNER["color"]
    text_color: str = DEFAULT_BANNER["text_color"]
    text_align: BannerTextAlign = BannerTextAlign(DEFAULT_BANNER["text_align"])
    fade: BannerFade = BannerFade(DEFAULT_BANNER["fade"])


class CommunityBannerWrite(SanitizedBaseModel):
    """The banner a guild admin sets, whole.

    Every field is required: the banner is one value and this replaces it, so a
    body naming two of the four would have to mean "leave the rest" — a merge
    the caller cannot see the result of. Sending ``null`` for the whole object
    is how you go back to the default. The artwork is set through its own
    endpoint; it is bytes, not a look.

    The layout fields are typed as their enums, so anything outside the
    vocabulary is a 422 rather than a rule the service restates; the colours
    are text here and normalized in the service.
    """

    color: RawTextStr
    text_color: RawTextStr
    text_align: BannerTextAlign
    fade: BannerFade


class CommunityLocation(SanitizedBaseModel):
    """Where a community is, in its admin's own words.

    ``text`` is the place as it was typed and as it is shown: a country alone
    ("Japan"), a city ("Lyon, France") or a full street address. ``label`` is
    the community's own name for the place ("Queen Anne Neighborhood"), shown
    ahead of it. ``country``
    (ISO 3166-1 alpha-2) and the coordinates are the place it was pinned to,
    for putting the communities near a reader first: a country alone pins no
    point, and text that was never pinned leaves all three out.

    The same shape is read and written: the whole location is one value, and a
    PATCH replaces it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    text: str = Field(max_length=200)
    #: Short, because it shares one line of a card with the place itself.
    label: Optional[TitleStr] = Field(default=None, max_length=60)
    country: Optional[str] = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @field_validator("text", mode="after")
    @classmethod
    def _tidy_text(cls, value: str) -> str:
        tidied = " ".join(value.split())
        if not tidied:
            raise ValueError("A location says where.")
        return tidied

    @field_validator("label", mode="after")
    @classmethod
    def _tidy_label(cls, value: Optional[str]) -> Optional[str]:
        return " ".join(value.split()) if value else None

    @field_validator("country", mode="after")
    @classmethod
    def _upper_country(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else None

    @model_validator(mode="after")
    def _point_within_country(self) -> CommunityLocation:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("A point has both coordinates.")
        if self.latitude is not None and not self.country:
            raise ValueError("A point belongs to a country.")
        return self


class CommunityBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None


class NewCommunity(CommunityBase):
    """A community, as somebody names it when they make one."""

    name: TitleStr


class CommunityCreate(NewCommunity):
    #: Make another account the guild's admin instead of the caller.
    #:
    #: Honoured only for a caller holding ``communities.manage``; anyone else
    #: sending it is refused rather than quietly ignored, so a request that
    #: names an owner never succeeds under a different one. The account must
    #: already exist — this never creates one.
    owner_user_id: Optional[int] = Field(default=None, ge=1)


class CommunityCan(SanitizedBaseModel):
    """What the caller may do in a community, as the server answers it.

    Each flag is the check the routes that do the thing run, so a client reads
    its affordances here rather than working them out from a rung."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Open it at all. False for a community in time out, which its
    #: administrators still see listed; the flags below say what the rung
    #: carries once it is lifted.
    enter: bool = False
    #: Reach its work. A settings grant reaches the configuration alone.
    content: bool = False
    #: Run its configuration, roster and invites: its administrator, or a
    #: settings grant at either rung.
    administer: bool = False
    #: Change that configuration: its administrator, or a settings grant
    #: beside a ``read_write`` content grant.
    configure: bool = False
    #: Administer its work — create and delete initiatives, add the
    #: community's own calendars. The membership row's administrator; no
    #: grant makes one.
    administer_content: bool = False
    #: Hold its top seat: sign-in, billing, AI, plug-ins, data and deletion.
    seat: bool = False
    #: Reach the community beyond what was shared with them: its initiative
    #: directory, its people, its plug-ins, its imports and exports. False for
    #: a guest.
    community_wide: bool = False
    #: Reach it with a personal API key, a subscription link included: false
    #: where its superadmin turned this member's API access off, and for a
    #: grant, which is never reached with one.
    use_api: bool = False


class CommunityRead(CommunityBase):
    """A guild as its own members see it (``GET /communities/`` and friends).

    The payload has two tiers, decided in one place — ``_serialize_guild`` in
    the guilds router:

    - The fields below with no note are for **every member**: guild identity,
      the caller's own rung, the roster size, ``content_read_only``.
    - The ones marked ADMIN-ONLY are guild administration — caps, plan label,
      retention window, lifecycle status, sign-in entitlement. They back
      admin-gated surfaces, so a regular member's payload leaves them ``None``.
      (Operators read the same underlying columns through
      :class:`PlatformCommunityStorageRead` instead, which is capability-gated.)
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    #: The rung this caller holds in the community: the membership row's own,
    #: or the one a live settings grant confers for its window. Shown as it
    #: stands; what it lets them do is ``can``.
    role: CommunityRole
    can: CommunityCan = Field(default_factory=CommunityCan)
    position: int
    #: What the caller has asked to be called here, as they set it; ``None``
    #: when they have not, which is most people.
    display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # ADMIN-ONLY. Trash retention window, set from the guild's trash settings tab.
    retention_days: Optional[int] = None
    # ADMIN-ONLY. Operator-set caps, rendered against usage on the settings page
    # (the usage half, /c/{id}/storage/usage, is guild-admin only too).
    max_storage_bytes: Optional[int] = None
    max_users: Optional[int] = None
    member_count: int = 0
    max_guests: Optional[int] = None
    # ADMIN-ONLY. Display/audit label of the paid tier (NULL = none /
    # self-hosted). Shown by the plan panel only when a billing portal is
    # configured; it is DISPLAY metadata and is never read in an enforcement
    # path (billing_foss_test scans for that). Enforcement reads
    # max_storage_bytes / max_users / max_guests / status.
    tier_name: Optional[str] = None
    # ADMIN-ONLY. Lifecycle status, so the app can show an admin a suspended
    # community as closed and a read-only one with its notice. ``None`` for
    # non-admin members — the moderation hold is never disclosed to them
    # (suspended guilds are also filtered from their guild list entirely).
    status: Optional[CommunityStatus] = None
    # True when content writes are frozen (read_only lifecycle status). Unlike
    # ``status`` this IS serialized to every member: writes fail at the
    # database role level regardless, so the UI must be able to drop its write
    # affordances — the flag discloses the effect, not the reason.
    content_read_only: bool = False
    # ADMIN-ONLY, and only for a suspended guild: who the closed entry tells
    # them to contact — the deployment's moderation contact, else its general
    # one (``app.services.platform.intake.contact_for``). ``None`` when neither
    # is set, or for any other guild.
    contact_email: Optional[str] = None
    # ADMIN-ONLY. What this guild may do about its own sign-in (operator
    # entitlement), so their settings UI knows which surfaces to offer;
    # ``None`` for non-admin members (they never configure auth).
    auth_options: Optional[List[CommunityAuthOption]] = None
    # Community directory opt-in and its subject tags. Guild identity, not
    # administration: every member sees them (they are published to strangers
    # anyway), and the settings page shows the controls to admins.
    is_community: bool = False
    categories: List[CommunityCategory] = []
    # The 18+ declaration. ``None`` — unanswered — is the normal state for a
    # guild that has never been listed; listing requires an explicit ``False``.
    has_adult_content: Optional[bool] = None
    # The guild's banner, at full size. Never absent — every guild has one, so
    # nothing downstream renders a guild that has none.
    banner: CommunityBannerRead = CommunityBannerRead()
    # Where the community is, or ``None`` for one that has not said. Identity,
    # like the banner: every member sees it, and a listed community publishes it.
    location: Optional[CommunityLocation] = None
    # How many of this guild's members have it open right now. A live reading
    # taken from the process answering the request rather than a stored
    # column — the same figure the directory card shows, and the same caveat: a
    # sense of how busy the guild is, not a number to reconcile against
    # anything. Zero is also what a request served by a process holding none of
    # the guild's sockets answers.
    online_count: int = 0
    # Where to fetch the guild's icon, or ``None`` when it has none. A URL like
    # the banner's: this payload lists every guild the caller is in, and the
    # icon used to be a data URI inlined into all of them.
    icon_url: Optional[str] = None
    # The banner's card rendition, for the guild's card in the switcher — the
    # strip its directory card shows. ``None`` when the banner has no artwork.
    banner_card_url: Optional[str] = None


class CommunityPaymentIssueRead(SanitizedBaseModel):
    payment_failed: bool = False


class CommunityBillingChargeRead(SanitizedBaseModel):
    # Minor units of ``currency`` (cents for USD).
    total: int
    currency: str


class CommunityBillingChangeRead(SanitizedBaseModel):
    action: Literal["cancel", "pause", "resume"]
    on: date


class CommunityBillingSummaryRead(SanitizedBaseModel):
    """The guild's plan as billing told it, fetched for this response alone.

    ``available`` is False when billing could not be asked or did not answer
    sensibly, and every other field is then empty — not a free plan, an
    unknown one.
    """

    available: bool = False
    tier_name: Optional[str] = None
    trial_ends_on: Optional[date] = None
    renews_on: Optional[date] = None
    next_charge: Optional[CommunityBillingChargeRead] = None
    scheduled_change: Optional[CommunityBillingChangeRead] = None
    payment_failed: bool = False


class CommunityInviteGrant(SanitizedBaseModel):
    """What a guest invite gives: an initiative to join, or one item in it at
    ``read`` or ``write``."""

    model_config = ConfigDict(from_attributes=True)

    initiative_id: int
    #: The item and its level, all three or none.
    resource_type: Optional[Tool] = None
    resource_id: Optional[int] = None
    level: Optional[Literal["read", "write"]] = None

    @model_validator(mode="after")
    def _item_whole(self) -> "CommunityInviteGrant":
        named = {
            self.resource_type is None,
            self.resource_id is None,
            self.level is None,
        }
        if len(named) != 1:
            raise ValueError(GuildMessages.GUEST_GRANT_NOT_FOUND)
        return self


class CommunityInviteCreate(SanitizedBaseModel):
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=1, ge=1)
    invitee_email: Optional[EmailStr] = None
    #: Makes a guest invite: whoever redeems it is a guest for this many days,
    #: or the community's or the deployment's longest stay if that is shorter.
    guest_days: Optional[int] = Field(default=None, ge=1)
    #: What a guest invite gives. Only a guest invite gives anything.
    grants: List[CommunityInviteGrant] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _grants_need_a_guest(self) -> "CommunityInviteCreate":
        if self.grants and self.guest_days is None:
            raise ValueError(GuildMessages.GUEST_GRANT_NOT_FOUND)
        return self


class CommunityInviteRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    created_by: Optional[int]
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    uses: int
    # Masked (``j***n@e***m``). Whoever typed the address already has it,
    # and a guild's other admins never did — the invite still matches the whole
    # address on redemption, from the ciphertext.
    invitee_email: Optional[str]
    created_at: datetime
    #: Set on a guest invite: how many days its guest stays, and what it
    #: gives them.
    guest_days: Optional[int] = None
    grants: List[CommunityInviteGrant] = Field(default_factory=list)

    @field_validator("invitee_email", mode="after")
    @classmethod
    def _mask_invitee_email(cls, value: Optional[str]) -> Optional[str]:
        return mask_email(value)


class CommunityInviteCreated(CommunityInviteRead):
    """A new invite, with its code: the one time the code is shown."""

    code: str


class CommunityInviteAcceptRequest(SanitizedBaseModel):
    code: str


class CommunityInviteStatus(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    code: str
    community_id: Optional[int] = Field(
        default=None, validation_alias=AliasChoices("community_id", "guild_id")
    )
    community_name: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("community_name", "guild_name")
    )
    is_valid: bool
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    uses: Optional[int] = None
    #: Set on a guest invite: how many days its guest stays.
    guest_days: Optional[int] = None


class CommunityGuestExtend(SanitizedBaseModel):
    #: The guest's time ends this many days from now, or at the community's
    #: or the deployment's longest stay if that is shorter.
    days: int = Field(ge=1)


class CommunityUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = None
    description: Optional[RichTextStr] = None
    # Trash retention period in days. None means "never auto-purge".
    # Sentinel "unset" semantics: explicitly omit the field to leave the
    # current setting untouched; set null to switch to never-purge.
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    # Community directory opt-in and subject tags. Omit-to-skip, like the
    # fields above: the endpoint inspects ``model_fields_set``, so a PATCH that
    # only renames a guild never disturbs its listing. A null ``categories``
    # is read as "no categories" — the empty list means the same thing and the
    # UI sends that — while a null ``is_community`` is a no-op (a boolean
    # opt-in has no third state).
    is_community: Optional[bool] = None
    categories: Optional[List[CommunityCategory]] = None
    # The whole banner, replaced. Omit-to-skip like the fields above; an
    # explicit null puts it back to the default rather than clearing it, since
    # a banner is never colourless and never without a layout.
    banner: Optional[CommunityBannerWrite] = None
    # The whole location, replaced. Omit-to-skip; an explicit null clears it,
    # since having no location is the default rather than a fallback.
    location: Optional[CommunityLocation] = None
    # The 18+ declaration, and the one field here where null is an ANSWER
    # rather than a skip — it puts the guild back to undeclared. Omitting the
    # field is how you leave it alone, so this is read from
    # ``model_fields_set`` rather than from the value being non-null.
    has_adult_content: Optional[bool] = None
    # NOTE: deliberately no cap/status/tier fields here. Those are
    # operator/billing enforcement inputs (the platform Guilds tab or the
    # verified billing path) — a guild's own admins must never set them, and
    # the column-scoped UPDATE grant on public.guilds (migration 0138) makes
    # the database enforce that even if a field regressed into this schema.


class CommunityAction(str, Enum):
    """What the reader may do to one community on the staff list. Worked out
    by the server per row, so a control the reader would be refused is never
    drawn."""

    #: The Manage sheet: caps, entitlements, sign-in, restoring a deletion.
    manage = "manage"
    #: The status control.
    set_status = "set_status"
    #: Suspend it, under a live ``moderate`` grant on it.
    suspend = "suspend"
    #: Lift its suspension, under the same.
    lift = "lift"
    #: The billing service's support console.
    billing_support = "billing_support"
    #: The billing service's operator console.
    billing_operator = "billing_operator"
    #: Ask for access to it.
    request_access = "request_access"
    #: Grant oneself access to it.
    break_glass = "break_glass"


class PlatformCommunityStorageRead(SanitizedBaseModel):
    """Operator view of a guild's storage cap (platform settings → Guilds tab).

    Unlike :class:`CommunityRead`, this carries no per-user membership fields
    (``role``/``position``): the platform operator lists every guild regardless
    of whether they belong to it, so only platform-wide attributes apply.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    member_count: int = 0
    # Plan label exactly as the billing service last set it — display/audit
    # metadata, never an enforcement input (the caps below are what enforce).
    # Echoed verbatim; this app neither invents nor interprets a plan name, and
    # None means no billing service has named one for this guild.
    tier_name: Optional[str] = None
    # Max total stored blob bytes for this guild. None means "unlimited".
    max_storage_bytes: Optional[int] = None
    # Max number of members for this guild. None means "unlimited".
    max_users: Optional[int] = None
    # Max number of guests at once. None means "unlimited"; 0 takes no new
    # guests.
    max_guests: Optional[int] = None
    # Lifecycle status (active / read_only / suspended / deleted). Surfaced
    # only to platform operators here — never to guild members (CommunityRead omits it).
    status: CommunityStatus = CommunityStatus.active
    status_changed_at: Optional[datetime] = None
    # The statuses the operator may move this guild to, the current one
    # included where it is one of them (``operator_status_choices``). Empty
    # for a deleted guild.
    status_choices: List[CommunityStatus] = Field(default_factory=list)
    # When a deleted guild is destroyed: its deletion time plus the retention
    # window. Null unless ``status`` is ``deleted``. Computed from the two
    # columns beside it rather than stored, so the window is stated in one
    # place (``retention.COMMUNITY_DELETION``).
    purge_at: Optional[datetime] = None
    # Whether anybody left in the guild can still run it — a ``superadmin``
    # seat. False after a deletion that cleared the roster, which is what makes
    # a restore ask the operator to seat somebody.
    has_seat: bool = True
    # Per-guild sign-in entitlements, set from the platform Guilds dashboard.
    auth_options: List[CommunityAuthOption] = Field(default_factory=list)
    # Whether this guild may upload banner artwork (operator toggle). On by
    # default; a guild without it picks a banner colour instead.
    banner_image_enabled: bool = True
    # Whether this guild's members may send a help request (operator toggle).
    # Off by default: the deployment that receives them is the one that decides
    # it is staffing them.
    support_enabled: bool = False
    # Where lifting its suspension returns it, while it is suspended. ``deleted``
    # where it was suspended out of deletion.
    lifts_to: Optional[CommunityStatus] = None
    # What the reader may do to it, worked out for them.
    allowed_actions: List[CommunityAction] = Field(default_factory=list)


class CommunitySuspensionUpdate(SanitizedBaseModel):
    """Suspend a community, or lift its suspension."""

    suspended: bool


class PlatformCommunityStorageListResponse(PageMeta):
    """One page of the operator's community list."""

    items: List[PlatformCommunityStorageRead]
    #: Whether the deployment has somewhere to send help requests. A
    #: community's help requests can only be switched on while it does.
    support_bound: bool = False


class PlatformCommunityRestore(SanitizedBaseModel):
    """Bring a deleted guild back (platform ``communities.manage``).

    ``status`` is what it returns at — the operator decides, because a
    community suspended for nonpayment and then deleted should not come back
    trading, and a column remembering what it used to be would be one more
    thing to keep correct for a decision somebody is making anyway.

    ``seat_user_id`` names the account that will run it, and is required only
    when the guild's roster no longer holds a ``superadmin`` — which is what a
    deletion that cleared the roster leaves behind. The endpoint re-checks
    that rather than trusting the client's reading of it.
    """

    status: CommunityStatus = CommunityStatus.active
    seat_user_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("status")
    @classmethod
    def _not_deleted(cls, value: CommunityStatus) -> CommunityStatus:
        if value == CommunityStatus.deleted:
            raise ValueError(GuildMessages.COMMUNITY_RESTORE_STATUS_INVALID)
        return value


class PlatformCommunityStorageUpdate(SanitizedBaseModel):
    """Set a guild's storage caps and/or lifecycle status from the Guilds tab.

    The cap fields use omit-to-skip sentinel semantics (the endpoint inspects
    ``model_fields_set``): omit a field to leave it untouched, send ``null`` to
    reset that cap to unlimited, or send a number to set it. ``status`` is
    omit-to-skip too (a lifecycle status is never null), validated against
    :class:`CommunityStatus`. A PATCH may carry any subset.
    """

    max_storage_bytes: Optional[int] = Field(default=None, ge=0)
    max_users: Optional[int] = Field(default=None, ge=1)
    max_guests: Optional[int] = Field(default=None, ge=0)
    status: Optional[CommunityStatus] = None

    @field_validator("status")
    @classmethod
    def _status_is_settable(
        cls, value: CommunityStatus | None
    ) -> CommunityStatus | None:
        """``deleted`` is not an operator setting.

        It is reached by deleting a guild and left by restoring one, both of
        which do a good deal more than move this column: clearing the guild's
        plug-in grants as it goes, seating somebody who can run it as it returns.
        Those two endpoints own the transition; this field does not.
        """
        if value == CommunityStatus.deleted:
            raise ValueError(GuildMessages.COMMUNITY_STATUS_NOT_SETTABLE)
        return value

    # Per-guild sign-in entitlements. Omit-to-skip; a sent list replaces the
    # set outright, and an empty one grants nothing.
    auth_options: Optional[List[CommunityAuthOption]] = None
    # Banner-artwork entitlement. Omit-to-skip, same as the one above.
    banner_image_enabled: Optional[bool] = None
    # Help-request entitlement. Omit-to-skip, same as the one above.
    support_enabled: Optional[bool] = None


#: What a community may require, beyond naming one provider. ``sso`` means its
#: own single sign-on, whichever of its providers serves it — the deployment's
#: providers are not its own. ``totp`` means the session carried the account's
#: second factor; ``passkey`` that it was opened, or stepped up, with one. The
#: platform's ``login_method`` vocabulary minus ``password`` and ``email_otp``,
#: which only the deployment decides about: a community's rule is about what a
#: session has proved, and those two are about whether the deployment offers
#: them at all. The same asymmetry the database holds as CHECKs on
#: ``require_methods``.
GuildRequirableMethod = Literal[LoginMethod.sso, LoginMethod.totp, LoginMethod.passkey]


class CommunityAuthPolicyRead(SanitizedBaseModel):
    """The guild's sign-in requirement. ``open`` is the default (no stored
    row). ``required`` names a provider a session must have satisfied, asks for
    the guild's own single sign-on without naming which provider serves it, or
    both."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    policy: Literal["open", "required"]
    provider_id: Optional[int] = None
    provider_slug: Optional[str] = None
    provider_display_name: Optional[str] = None
    require_methods: list[GuildRequirableMethod] = Field(default_factory=list)
    #: Whether the deployment already asks every account for a second factor.
    #: The community's own box for it is not offered while this is true —
    #: there is nothing left for it to add — and a rule already written stays
    #: on the row, in force again if the deployment lowers its answer.
    factor_required_by_platform: bool = False


class CommunityAuthPolicyUpdate(SanitizedBaseModel):
    policy: Literal["open", "required"]
    provider_id: Optional[int] = None
    #: ``["sso"]`` asks for the community's own single sign-on and ``["totp"]``
    #: for the account's second factor; both may be asked for at once.
    #: ``password`` is absent from the type on purpose: whether passwords exist
    #: at all is the deployment's question.
    require_methods: list[GuildRequirableMethod] = Field(default_factory=list)


class CommunityAuthSettingsRead(SanitizedBaseModel):
    """Every control on the superadmin seat's Security page, and what the
    deployment already asks beside them."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    auth_options: List[CommunityAuthOption] = Field(default_factory=list)
    auth_policy: CommunityAuthPolicyRead
    #: What it asks of its guests instead. Open unless it says otherwise.
    guest_auth_policy: CommunityAuthPolicyRead
    #: Whether its members sign in again every twelve hours, whatever the
    #: deployment's own limit says.
    enforce_compliance_session: bool
    #: Whether reaching it asks for a second factor. Which kinds count is the
    #: deployment's answer.
    require_second_factor: bool = False
    #: What its notifications may leave the app carrying. Each is also asked of
    #: the deployment and the stricter of the pair applies.
    allow_push_notifications: bool = True
    allow_email_notifications: bool = True
    redact_notification_content: bool = False
    #: The deployment's answers to the same three, so the page can say that a
    #: switch has nothing to add rather than offering the same answer twice.
    push_allowed_by_platform: bool = True
    email_allowed_by_platform: bool = True
    redacted_by_platform: bool = False
    #: Whether search orders its content by how many members engaged with it
    #: lately, and whether the deployment allows that at all.
    allow_engagement_ranking: bool = True
    engagement_ranking_allowed_by_platform: bool = True
    #: Whether AI features may send its content to a provider, and whether the
    #: deployment offers AI at all.
    allow_ai: bool = True
    ai_offered_by_platform: bool = True
    #: The longest a guest may stay, in days, and the deployment's ceiling,
    #: which applies when it is ``None`` or longer.
    guest_max_days: Optional[int] = None
    guest_max_days_by_platform: int


class CommunityAuthSettingsUpdate(SanitizedBaseModel):
    """The rules to change. An omitted field is left as it is.

    The whole request is one change: it is applied together or refused
    together, and a rule it loosens is loosened before one it tightens is
    checked. Tightening a rule needs the option it belongs to; loosening one
    never does.
    """

    #: The sign-in requirement, replaced as a whole.
    auth_policy: Optional[CommunityAuthPolicyUpdate] = None
    #: The guests' sign-in requirement, replaced as a whole.
    guest_auth_policy: Optional[CommunityAuthPolicyUpdate] = None
    enforce_compliance_session: Optional[bool] = None
    require_second_factor: Optional[bool] = None
    allow_push_notifications: Optional[bool] = None
    allow_email_notifications: Optional[bool] = None
    redact_notification_content: Optional[bool] = None
    allow_engagement_ranking: Optional[bool] = None
    allow_ai: Optional[bool] = None
    #: ``null`` leaves only the deployment's ceiling.
    guest_max_days: Optional[int] = Field(default=None, ge=1)


class CommunityDeletionRequest(SanitizedBaseModel):
    """Body for ``DELETE /communities/{id}``.

    Deleting a guild cascades through every initiative, project, task,
    file, membership, invite, and settings row it owns, so the
    endpoint gates on two confirmations:

    - ``confirmation_text`` must equal ``DELETE COMMUNITY <NAME>`` (the whole
      phrase uppercased) so the action can't be triggered by a stray click.
    - ``password`` is the current user's password. An account that holds
      none — one that signs in with a passkey or through an identity
      provider — has nothing to confirm with and answers with the phrase
      alone, mirroring the account-deletion endpoint, which is why it
      defaults to empty.
    """

    password: RawTextStr = ""
    confirmation_text: str


class CommunityOrderUpdate(SanitizedBaseModel):
    community_ids: list[int] = Field(min_length=1)


class CommunityEntitlementsRead(SanitizedBaseModel):
    """What an operator has turned on for one guild, for its own admins.

    Deliberately its own read rather than fields on :class:`CommunityRead`: these
    are the operator's decisions about a guild, they live on the separate
    ``guild_administration`` row, and only a guild admin has any use for them —
    a member's guild payload should not be carrying them at all.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    # Whether this guild may upload banner artwork. Off means the settings page
    # offers the banner colour alone; a banner already uploaded keeps showing.
    banner_image_enabled: bool = True


class CommunityMembershipUpdate(SanitizedBaseModel):
    """Schema for updating a user's guild membership role."""

    role: CommunityRole


class MemberDisplayNameUpdate(SanitizedBaseModel):
    """What a member is called in one community. ``None`` or blank clears it,
    and their handle shows again."""

    display_name: Optional[TitleStr] = Field(
        default=None, max_length=MEMBER_DISPLAY_NAME_MAX_LENGTH
    )

    @model_validator(mode="before")
    @classmethod
    def _blank_is_none(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("display_name"), str):
            if not data["display_name"].strip():
                data = {**data, "display_name": None}
        return data


class MemberApiAccessUpdate(SanitizedBaseModel):
    """Whether one member's personal API keys reach this community."""

    api_keys_allowed: bool


class LeaveCommunityEligibilityResponse(SanitizedBaseModel):
    """Response for checking if a user can leave a guild.

    Two things stop them, and the caller is told which. Being the guild's last
    admin is one. Holding its only superadmin seat while the guild requires
    a sign-in is the other — the requirement is lifted from the surface that
    seat holds, so the seat stays for as long as the requirement does.

    Content they own is released on the way out and left unowned for a guild
    admin to claim, so there is nothing to hand over first.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_leave: bool
    is_last_superadmin: bool = False


class DirectoryCommunityRead(SanitizedBaseModel):
    """One card in the community directory.

    Deliberately not a :class:`CommunityRead`: the reader is a stranger, so this
    carries only what the guild published by opting in — its identity, its
    shelves, and how many people are already there. No membership fields (they
    have none), no lifecycle status, no administration. ``already_member`` is
    about the *caller*, and only says whether the Join button applies to them.

    ``online_count`` is how many of those people have the guild open right now.
    It is a live reading rather than a stored one, taken from the process
    answering the request, so it is a sense of how busy a guild is rather than a
    figure to reconcile against anything.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    description: Optional[RichTextStr] = None
    icon_url: Optional[str] = None
    categories: List[CommunityCategory] = []
    member_count: int = 0
    online_count: int = 0
    already_member: bool = False
    # The guild's banner, its ``image_url`` naming the card rendition rather
    # than the full one: a directory page is up to sixty of these, so the bytes
    # stay out of the payload and are fetched (and then cached) per card. The
    # rest of it needs no fetch at all.
    banner: CommunityBannerRead = CommunityBannerRead()
    # Where the community is, if it said. Published like the rest of the card.
    location: Optional[CommunityLocation] = None


class DirectoryCommunityPage(PageMeta):
    """A page of directory results."""

    items: List[DirectoryCommunityRead]
