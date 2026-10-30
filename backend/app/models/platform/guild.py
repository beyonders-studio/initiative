from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import text
from sqlmodel import Field, Index, SQLModel, Enum as SQLEnum, Relationship
from pydantic import ConfigDict

from app.core.encryption import FERNET_SALT, SALT_EMAIL, decrypt_field

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.platform.guild_administration import GuildAdministration


#: The longest name a member may give themselves in one community.
MEMBER_DISPLAY_NAME_MAX_LENGTH = 64


class CommunityStatus(str, Enum):
    """Lifecycle status of a guild.

    The first four are operator-set from the platform Guilds tab (platform
    `communities.manage`) and are freely interchangeable:

    - ``active``: normal operation.
    - ``read_only``: members keep read access to content but writes are denied
      at the Postgres role level (routed into ``guild_<id>_ro``).
    - ``suspended``: the guild is in time out. Nobody in it reaches anything
      in it — content or settings, members and admins alike — and only the
      platform lifts it. It vanishes from members' guild lists; its admins
      keep a closed entry, so they can tell a time out from a loss. Set by
      the platform operator alone; the billing service cannot.
    - ``on_hold``: the guild is held for a significantly late payment. Nobody
      in it reaches it, its admins included, and it is absent from every
      member's guild list. Its superadmins are told once, on the way in, whom
      to contact. Set by the billing service, or by the operator.

    Guild admins keep the settings surface (billing / data ownership / danger
    zone) under ``active`` and ``read_only`` only.

    The fifth is not:

    - ``deleted``: the guild has been deleted and is being retained for
      :data:`~app.services.platform.retention.COMMUNITY_DELETION` before
      it is destroyed. Nobody in the guild reaches it, its admins included,
      and it is absent from every member's guild list.

      Reached only through deletion and left only through restore, both of
      which do more than move a column, so it is deliberately not offered in
      the operator's status control and a PATCH that names it is refused.

    PAM/break-glass grants deliberately override all of this: a grantee
    behaves exactly as against an active guild (the resolver's grant branch
    never consults the status), so no status can lock the platform operators
    out — which is what lets an operator look inside a deleted guild before
    deciding whether to bring it back. The status is not serialized to guild
    members.
    """

    active = "active"
    read_only = "read_only"
    suspended = "suspended"
    on_hold = "on_hold"
    deleted = "deleted"


#: The statuses from which a member reaches the guild at all — its content or
#: its settings. Everything else is refused by the guild-access resolver.
#:
#: Stated once, as a set, because the question is asked in a dozen places and
#: every one of them should have the same answer.
#: ``guild_soft_delete_test`` holds the set and the resolver together.
LIVE_STATUSES: frozenset[CommunityStatus] = frozenset(
    {CommunityStatus.active, CommunityStatus.read_only}
)

#: The statuses an operator may set from the Guilds tab, in the order the
#: control lists them (least → most restrictive). ``deleted`` is absent by
#: derivation rather than by a second hand-written list.
OPERATOR_SETTABLE_STATUSES: tuple[CommunityStatus, ...] = (
    CommunityStatus.active,
    CommunityStatus.read_only,
    CommunityStatus.on_hold,
    CommunityStatus.suspended,
)

#: The statuses the billing service may write. ``suspended`` is the platform
#: operator's time out and ``deleted`` belongs to deletion, so neither is here —
#: and a guild already in either takes no status write from billing at all.
BILLING_SETTABLE_STATUSES: frozenset[CommunityStatus] = frozenset(
    {CommunityStatus.active, CommunityStatus.read_only, CommunityStatus.on_hold}
)


def operator_status_choices(
    status: CommunityStatus,
    *,
    billing_status: CommunityStatus | None,
    billing_managed: bool,
) -> tuple[CommunityStatus, ...]:
    """The statuses the operator may move a guild at ``status`` to.

    Where billing sets plans, the operator's one status is the time out: into
    ``suspended``, and out of it to the status billing last wrote. Everywhere
    else, any of :data:`OPERATOR_SETTABLE_STATUSES`. A deleted guild has none;
    restoring it is not a status change. The triggers of migration 0364 hold
    the database to the same rule.
    """
    if status is CommunityStatus.deleted:
        return ()
    if not billing_managed:
        return OPERATOR_SETTABLE_STATUSES
    if status is CommunityStatus.suspended:
        return (billing_status or CommunityStatus.active, CommunityStatus.suspended)
    return (status, CommunityStatus.suspended)


def restore_status_choices(
    *,
    billing_status: CommunityStatus | None,
    billing_managed: bool,
) -> tuple[CommunityStatus, ...]:
    """The statuses a deleted guild may be restored at.

    The choices that lift a suspension: where billing sets plans, the status
    billing last wrote or ``suspended``; everywhere else, any of
    :data:`OPERATOR_SETTABLE_STATUSES`. The status trigger of migration 0364
    holds the database to the same rule.
    """
    return operator_status_choices(
        CommunityStatus.suspended,
        billing_status=billing_status,
        billing_managed=billing_managed,
    )


#: The statuses whose guild is absent from every member's guild list, its
#: admins' included. A suspended guild is not here: its admins keep a closed
#: entry.
UNLISTED_STATUSES: frozenset[CommunityStatus] = frozenset(
    {CommunityStatus.on_hold, CommunityStatus.deleted}
)

#: :data:`LIVE_STATUSES` as the strings the column stores, so one set answers
#: the question in Python (``guild.status in LIVE_STATUS_VALUES``) and in SQL
#: (``Guild.status.in_(LIVE_STATUS_VALUES)``) rather than two.
LIVE_STATUS_VALUES: frozenset[str] = frozenset(s.value for s in LIVE_STATUSES)


class CommunityCategory(str, Enum):
    """A subject a guild can file itself under in the community directory.

    A closed vocabulary rather than free-form tags: the directory's job is to
    narrow a deployment's guilds down to a browsable shelf, and that only works
    if two guilds about the same thing pick the same word. Guilds choose their
    own (zero or more) from their settings page; the labels are localized
    client-side from these keys, so the stored value is never user-facing text.

    Stored as a ``text[]`` on ``guilds.categories`` with a CHECK that every
    element is one of these, mirroring how ``status`` is a CHECK-constrained
    string rather than a Postgres enum: adding a category is then an ordinary
    migration instead of an enum alteration.
    """

    art = "art"
    gaming = "gaming"
    ttrpg = "ttrpg"
    music = "music"
    writing = "writing"
    education = "education"
    technology = "technology"
    sports = "sports"
    business = "business"
    health = "health"
    social = "social"
    other = "other"


#: What a guild's banner is before anyone touches it: the app's own accent,
#: and white on it. Hard-coded rather than read from the operator's branding —
#: the accent differs between light and dark mode and a banner colour does not,
#: so a guild's banner is its own value from the moment it exists.
DEFAULT_BANNER_COLOR = "#2563eb"

#: Banner text is one of exactly two colours, never a free choice. A banner's
#: fill is the guild's to pick and its artwork can be anything, so the only way
#: the words on it stay readable is to keep them at one end of the scale or the
#: other. Anything in between is a contrast failure waiting for someone to pick
#: it.
BANNER_TEXT_COLORS: tuple[str, str] = ("#ffffff", "#000000")
DEFAULT_BANNER_TEXT_COLOR = BANNER_TEXT_COLORS[0]


class BannerTextAlign(str, Enum):
    """Where a banner's name and description sit across its width.

    Two answers, not a free position: centred reads as a masthead and is what a
    banner with artwork built around a middle wants, while left-aligned lines
    the copy up with the page's own content and is what a photograph with its
    subject on one side wants. Anything finer would be a design tool, and the
    guild is choosing between two looks rather than laying one out.
    """

    center = "center"
    left = "left"


class BannerFade(str, Enum):
    """How far a banner dissolves into the page beneath it.

    ``none`` ends the banner at an edge — a band with the page starting under
    it. The other two extend it past that edge and fade it out there, so the
    page's own content rides over the tail rather than starting below it: a
    ``weak`` fade is a soft join, a ``strong`` one lets the banner read as the
    page's background rather than as a strip on it.
    """

    none = "none"
    weak = "weak"
    strong = "strong"


#: What a banner is before anyone touches it.
DEFAULT_BANNER: dict[str, str] = {
    "color": DEFAULT_BANNER_COLOR,
    "text_color": DEFAULT_BANNER_TEXT_COLOR,
    "text_align": BannerTextAlign.center.value,
    "fade": BannerFade.strong.value,
}

#: The keys a banner has, and the only ones it may have.
BANNER_KEYS: tuple[str, ...] = tuple(DEFAULT_BANNER)


class Guild(SQLModel, table=True):
    __tablename__ = "guilds"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        # The community directory's only query shape: listed guilds, optionally
        # narrowed to one category. Partial on the opt-in so the index stays
        # the size of the directory rather than the size of the deployment.
        Index(
            "ix_guilds_community_categories",
            "categories",
            postgresql_using="gin",
            postgresql_where=text("is_community"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    banner: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_BANNER),
        sa_column=Column(
            MutableDict.as_mutable(JSONB),
            nullable=False,
            server_default=json.dumps(DEFAULT_BANNER),
        ),
    )
    # Where the community is (see ``GuildLocation`` in the guild schemas for the
    # parts), or NULL for one that has not said — the default, and the answer
    # for most guilds. One value, replaced whole, like the banner.
    location: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Lifecycle status (see CommunityStatus). Stored as a plain string with a CHECK
    # constraint (the access_grants pattern) rather than a Postgres enum.
    #
    # Alone among the operator-set fields it lives here rather than on
    # ``GuildAdministration``: every guild request reads it (suspended -> 403,
    # read_only -> frozen writes) off a guild row the request already loads, so
    # moving it would buy a join on the hottest path in the app.
    status: str = Field(
        default=CommunityStatus.active.value,
        sa_column=Column(
            String(16), nullable=False, server_default=CommunityStatus.active.value
        ),
    )
    # When the status last changed; NULL until the first operator change.
    status_changed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # When a purge asked the community's plug-ins to erase what they hold. The
    # row is deleted once each has answered or been given up on
    # (``guild_purge``); until then the community cannot be restored or moved,
    # and no plug-in is given a new name in it. NULL while no purge has begun.
    purge_started_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # Where a suspended guild was before it was suspended, so lifting the
    # suspension puts it back there — ``deleted`` included, which a suspension
    # pulls out of its purge countdown. NULL while it is not suspended, and for
    # a suspension made before this was recorded.
    status_before_suspension: Optional[str] = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    # Community directory opt-in. False means the guild is reachable only by
    # invite; True publishes its name, description, icon, categories, and roster
    # size to the signed-in directory and lets anyone join without one. Set by
    # the guild's own admins, alongside the identity columns above.
    is_community: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Which shelves the guild files itself under (see CommunityCategory). A listed
    # guild must be on at least one — a card nobody can find by browsing is not
    # a listing — which the ck_guilds_community_categories CHECK enforces.
    categories: List[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
        ),
    )
    # Whether this guild is 18+. NULL is the default and stays the answer for
    # almost every guild: it is a question only the directory needs answered,
    # and a guild that never lists itself is never asked it.
    #
    # Listing requires an explicit False — the admin certifies it as part of
    # publishing. True and an unanswered NULL both keep the guild out, which is
    # one CHECK (ck_guilds_community_adult_content) rather than an app rule,
    # because ``IS FALSE`` is false for NULL too.
    has_adult_content: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    # The operator-set caps, plan label, and sign-in entitlement — everything
    # this row is NOT. See GuildAdministration for why they live apart.
    administration: Optional["GuildAdministration"] = Relationship(
        back_populates="guild",
        sa_relationship_kwargs={
            "uselist": False,
            "cascade": "all, delete-orphan",
        },
    )

    members: List["GuildMembership"] = Relationship(
        back_populates="guild",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class CommunityRole(str, Enum):
    admin = "admin"
    member = "member"
    # Above ``admin``: everything an admin reaches, plus the guild's sign-in
    # configuration — its identity providers and the requirement for entering
    # it. Separated because running a community and holding the keys to who may
    # enter it are different jobs, and most guilds have nobody in this seat.
    #
    # A superadmin seats another — one by membership, or one holding the seat
    # through a settings grant. An ordinary guild admin cannot — the hand that
    # administers a community is not the hand that decides who may enter it.
    superadmin = "superadmin"
    # An outside person in the community for a set time: a membership row
    # with ``guest_until`` set, which no seat count or member list includes.
    # Below ``member``: what a guest reaches is what they were given, not
    # what the community's members see.
    guest = "guest"
    # A time-bound PAM/support access grantee acting inside a guild they are
    # NOT a member of. Synthesized for the request only — never a persisted
    # ``guild_memberships`` row (the member-role endpoint rejects assigning
    # it). Unlike
    # ``admin``, ``support`` is bound by its grant's read/write level, enforced
    # at the Postgres role level — a read grant assumes ``guild_<id>_ro``. It
    # is the content axis only: what of the community's configuration a
    # grantee may work is a settings grant, held at its own rung beside this.
    # A break-glass grantee holds this too: its content grant is one of these,
    # and the ``superadmin`` settings grant beside it is read separately.
    support = "support"

    def reaches(self, rung: "CommunityRole") -> bool:
        """Whether this rung carries what ``rung`` carries.

        The community's ladder asked as a comparison rather than as a set per
        question: ``admin`` reaches ``member``, ``superadmin`` reaches both,
        and a rung added between them needs no list updated. ``support`` is
        below every rung — granted access is its own identity, and what it
        reaches is its grant, not a place on this ladder.
        """
        return GUILD_LADDER.index(self) >= GUILD_LADDER.index(rung)


#: The community's ladder, lowest rung first. ``support`` is the identity
#: granted access carries and sits below a member: it is not a rung of the
#: community, and nothing it holds comes from being on this list.
#:
#: One ordering, in one place. Asking whether a rung carries another's
#: authority is :meth:`CommunityRole.reaches`, and every set below derives from it
#: rather than restating which rungs are which.
GUILD_LADDER: tuple[CommunityRole, ...] = (
    CommunityRole.support,
    CommunityRole.guest,
    CommunityRole.member,
    CommunityRole.admin,
    CommunityRole.superadmin,
)

#: Roles that carry a guild admin's authority — the ladder from ``admin`` up.
#: Kept as a set because that is how most callers ask; it is derived, so the
#: day a rung is added between them there is nothing here to remember.
GUILD_ADMIN_ROLES: frozenset[CommunityRole] = frozenset(
    role for role in CommunityRole if role.reaches(CommunityRole.admin)
)


class AdminSurface(str, Enum):
    """A part of administering a community, held as a whole.

    The admin rung holds every one. What the rung holds beyond them, the reach
    into all of the community's content (``initiative_access``, "Full access",
    the trash's reads), is not one of these: it is the rung's own. Each admin
    route names the surface it guards, and so does each policy leg that guards
    one, reading the request's ``held_surfaces``.
    """

    #: The community's name, pictures, listing and retention.
    profile = "profile"
    #: Invites to the community, and what a guest invite gives.
    invites = "invites"
    #: The roster: rungs, guests, display names, removal, a departing
    #: member's content, and how people sign in to join.
    members = "members"
    #: Creating, archiving and deleting initiatives, every initiative's setup,
    #: and what every initiative uses.
    initiatives = "initiatives"
    #: Calendars that belong to the whole community.
    community_calendars = "community_calendars"
    #: Webhook subscriptions that report on the whole community.
    webhooks = "webhooks"
    #: Restoring anybody's deletions, and purging.
    trash = "trash"
    #: Storage used, and what installed plug-ins report.
    usage = "usage"
    #: The community's custom roles: defining them. Assigning one is
    #: ``members``.
    roles = "roles"


#: What a custom role on the member rung may hold. The rest reach the
#: community's content (``initiatives`` writes every roster, ``webhooks``
#: report across initiatives, ``trash`` reads the trash) or define roles, so
#: they are for a role on the admin rung.
MEMBER_ROLE_SURFACES: frozenset[AdminSurface] = frozenset(
    {
        AdminSurface.profile,
        AdminSurface.invites,
        AdminSurface.members,
        AdminSurface.community_calendars,
        AdminSurface.usage,
    }
)


#: What an ordinary guild admin may hand out. ``support`` is never persisted at
#: all, and ``superadmin`` is passed on only by somebody already holding it.
GUILD_ASSIGNABLE_ROLES: frozenset[CommunityRole] = frozenset(
    {CommunityRole.admin, CommunityRole.member}
)


#: Roles that exist as ``guild_memberships`` rows. ``support`` is synthesized
#: for the length of a PAM request and never stored, so it is the one value
#: that is not here — derived rather than listed, so a role added to the enum
#: is a stored role unless it is deliberately excluded.
GUILD_STORED_ROLES: frozenset[CommunityRole] = frozenset(CommunityRole) - {
    CommunityRole.support
}


def assignable_roles(by: CommunityRole) -> frozenset[CommunityRole]:
    """Which roles ``by`` may set on somebody else inside the guild.

    A superadmin passes the seat on; an ordinary admin cannot, and cannot
    take it away either. ``by`` is the rung the request stands on, so a
    superadmin settings grant seats somebody the same way a superadmin
    membership does.
    """
    if by == CommunityRole.superadmin:
        return GUILD_ASSIGNABLE_ROLES | {CommunityRole.superadmin}
    return GUILD_ASSIGNABLE_ROLES


class GuildMembership(SQLModel, table=True):
    __tablename__ = "guild_memberships"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        # The primary key is (guild_id, user_id); this is the other direction,
        # for "which guilds is this user in".
        Index("idx_guild_memberships_user_guild", "user_id", "guild_id"),
        CheckConstraint(
            "role <> 'guest' OR guest_until IS NOT NULL",
            name="ck_guild_memberships_guest_ends",
        ),
    )

    guild_id: int = Field(foreign_key="guilds.id", ondelete="CASCADE", primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE", primary_key=True)
    role: CommunityRole = Field(
        default=CommunityRole.member,
        sa_column=Column(
            SQLEnum(CommunityRole, name="guild_role"),
            nullable=False,
            server_default=CommunityRole.member.value,
        ),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    #: What this person is called in this community, set by them or by its
    #: administrators. NULL — the usual case — leaves their handle.
    #: ``guild_member_profiles`` answers with it (0438).
    display_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(MEMBER_DISPLAY_NAME_MAX_LENGTH), nullable=True),
    )
    #: The provider whose claims put this person here, and the only one whose
    #: sign-in may take it away again. NULL is a membership nobody manages —
    #: an invite, a join request, an admin adding somebody — which group sync
    #: neither grants nor reclaims. ``ON DELETE SET NULL``: removing a provider
    #: ends its claim on the row, it does not end the membership.
    oidc_provider_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )

    #: When a guest's membership ends; ``NULL`` for a member. A row with it
    #: set is a guest's: it admits them only until then, and no seat count or
    #: member list includes it.
    guest_until: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    guild: Optional[Guild] = Relationship(back_populates="members")
    user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(GuildMembership.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )


class GuildInvite(SQLModel, table=True):
    __tablename__ = "guild_invites"
    __table_args__ = (
        CheckConstraint("guest_days >= 1", name="ck_guild_invites_guest_days"),
        CheckConstraint(
            "(guest_days IS NULL) = (guest_role IS NULL)",
            name="ck_guild_invites_guest_terms",
        ),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # SHA-256 of the code, in hex. The code itself is shown once, when the
    # invite is made.
    code_hash: str = Field(index=True, unique=True, nullable=False, max_length=64)
    guild_id: int = Field(foreign_key="guilds.id", ondelete="CASCADE", nullable=False)
    # The invite outlives the admin who issued it.
    created_by: Optional[int] = Field(
        foreign_key="users.id", ondelete="SET NULL", nullable=True
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: ``None`` for no limit.
    max_uses: Optional[int] = Field(default=1, sa_column=Column(Integer, nullable=True))
    uses: int = Field(default=0, nullable=False)
    invitee_email_encrypted: Optional[str] = Field(
        default=None,
        sa_column=Column(String(2000), nullable=True, info={FERNET_SALT: SALT_EMAIL}),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # A guest invite: redeeming it makes a guest with ``guest_role`` for
    # ``guest_days``. Both are NULL on a member invite.
    guest_days: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    guest_role: Optional[CommunityRole] = Field(
        default=None,
        sa_column=Column(SQLEnum(CommunityRole, name="guild_role"), nullable=True),
    )

    @property
    def invitee_email(self) -> Optional[str]:
        """Return the decrypted invitee email, or None if not set."""
        if not self.invitee_email_encrypted:
            return None
        return decrypt_field(self.invitee_email_encrypted, SALT_EMAIL)

    guild: Optional[Guild] = Relationship()
