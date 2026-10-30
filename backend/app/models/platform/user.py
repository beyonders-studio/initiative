from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, SQLModel, Relationship
from pydantic import ConfigDict


if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.guild import GuildMembership


class UserRole(str, Enum):
    """Platform-level (app-wide) user role.

    Ordered from least to most privileged. Authorization checks should
    generally go through the capability model (``app.core.capabilities``)
    rather than comparing roles directly, so that the privilege ladder can
    evolve without touching every call site.
    """

    member = "member"
    moderator = "moderator"
    support = "support"
    operator = "operator"
    owner = "owner"


class UserStatus(str, Enum):
    active = "active"
    #: Frozen by a platform moderator. Distinct from ``deactivated``, which
    #: drops every guild and initiative membership — suspension writes this one
    #: column and nothing else, so lifting it restores the account whole. The
    #: holder still signs in and reaches their own account; what they lose is
    #: every guild.
    suspended = "suspended"
    #: The holder closed their account. Memberships are dropped; the row and
    #: its personal data remain so an operator can reactivate it.
    deactivated = "deactivated"
    #: Erased. The row is a husk kept only so the work it touched still says
    #: who did it.
    anonymized = "anonymized"
    #: The holder asked for the account to go, and it is being kept for the
    #: deployment's window before it is erased. Distinct from ``deactivated``,
    #: which is somebody taking a break and must never be erased by a timer:
    #: this one has a date on it.
    #:
    #: Memberships, initiative roles and owned files are all kept, so
    #: coming back restores the account whole rather than to an empty one —
    #: which is what ``deactivated`` gives, its memberships having been
    #: dropped. What the account loses meanwhile is everybody else: it is
    #: absent from rosters, pickers and search for as long as it sits here.
    deleted = "deleted"


class Presence(str, Enum):
    """How a person appears to everyone else.

    Both halves of one idea, which is why it is one enum: what a person picks
    for themselves, and what a reader of their name is shown. The picked value
    is a standing preference on the account; the shown value is that preference
    narrowed by what the process can see — whether they have Initiative open at
    all, and whether anyone has touched it lately — which is decided in one
    place (``app.services.platform.presence``).

    ``idle`` is the one a person may either pick or be given: left on
    ``online``, an account that goes quiet is shown it anyway, and picking it
    outright is how someone says they would rather look that way regardless.

    Not to be confused with ``UserStatus`` (the account's standing, which is not
    the account holder's to write) or ``custom_status`` (the line they wrote).
    """

    #: Follow the connection: shown while a tab is open, and not otherwise.
    online = "online"
    #: Open, but with no sign of anyone at the keyboard for a while — the
    #: state for stepping away, whether or not you said so. The one that is
    #: inferred as well as picked: it is what ``online`` becomes on its own
    #: after a long enough quiet, and what someone picks to look that way
    #: whether or not they are.
    idle = "idle"
    #: Here, and would rather not be interrupted.
    busy = "busy"
    #: Shown to nobody, whether or not a tab is open. Also what a reader is
    #: told about anyone who has nothing open.
    offline = "offline"


#: The statuses that may hold a session. A suspended account signs in — that is
#: how its holder is told they are in time out — and reaches only the time-out
#: allow-list (``app.api.deps.AccountHolder``); every other route refuses it.
LOGIN_STATUSES: frozenset[UserStatus] = frozenset(
    {UserStatus.active, UserStatus.suspended}
)

#: The statuses a sign-in may be completed against.
#:
#: ``deleted`` is here on purpose: signing in is how somebody calls off the
#: deletion of their own account, so the sign-in has to be allowed to happen
#: before there is anything to call off. The account is restored at the moment
#: the session is opened (``sessions.create_session``), so nothing ever holds a
#: live session while still deleted.
#:
#: ``suspended`` is here so its holder can be told they are in time out; see
#: :data:`LOGIN_STATUSES` for what the session then reaches.
SIGN_IN_STATUSES: frozenset[UserStatus] = frozenset(
    {UserStatus.active, UserStatus.suspended, UserStatus.deleted}
)


def may_sign_in(user: "User") -> bool:
    """Whether a sign-in may be completed against this account.

    Its status is one of :data:`SIGN_IN_STATUSES`, and its own age answer has
    not closed it. An account refused for being under the minimum age for one
    where it was (``age_below_account_minimum_at``) sits in the erasure window
    like any deleted account, but the holder coming back is not what calls
    that off: the answer stands until somebody with ``users.age_unblock``
    clears it, and only then does a sign-in restore the account. Every way in
    asks this rather than the set, so the exception has one home.
    """
    return user.status in SIGN_IN_STATUSES and user.age_below_account_minimum_at is None


#: The statuses whose holder does not appear where people are listed as
#: somebody to work with — rosters, pickers, search, mention candidates,
#: presence. Read through ``users.visible_to_other_people()``, which is the
#: one place the rule is applied.
#:
#: Neither is a removal. A suspension is reversible and a deletion is
#: reversible for its window, so in both cases the work the account already
#: touched keeps saying who did it.
ABSENT_STATUSES: frozenset[UserStatus] = frozenset(
    {UserStatus.suspended, UserStatus.deleted}
)


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        # A handle is unique as a pair, and case-insensitively on the name
        # part: one never differs from another by case alone.
        Index(
            "ix_users_handle",
            text("lower(username)"),
            "discriminator",
            unique=True,
        ),
        # The bound on the status line, held where the line is stored as well
        # as where it is parsed — see
        # ``app.schemas.platform.user.STATUS_TEXT_MAX_LENGTH``.
        CheckConstraint(
            "char_length(custom_status->>'text') <= 40",
            name="ck_users_custom_status_text_length",
        ),
        # One question, two answers, never both. An account that confirmed is
        # not also blocked, and one that is blocked never got to confirm.
        CheckConstraint(
            "age_confirmed_at IS NULL OR age_below_minimum_at IS NULL",
            name="ck_users_age_answer",
        ),
        # Under the minimum for an account is under the directory's minimum
        # too: the second mark never stands without the first.
        CheckConstraint(
            "age_below_account_minimum_at IS NULL OR age_below_minimum_at IS NOT NULL",
            name="ck_users_age_account_answer",
        ),
    )
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    __allow_unmapped__ = True

    id: Optional[int] = Field(default=None, primary_key=True)
    #: The name part of this account's handle — what a person picks and reads.
    #: Unique with ``discriminator``, case-insensitively (``ix_users_handle``);
    #: the vocabulary lives in ``app.core.usernames``.
    username: str = Field(sa_column=Column(String(32), nullable=False))
    #: The number behind the name, 0000-9999, drawn at random and rendered
    #: zero-padded beside it. Never chosen by anyone.
    discriminator: int = Field(sa_column=Column(SmallInteger, nullable=False))
    #: Whether the handle was picked rather than assigned. False on a row the
    #: backfill seeded and on an account provisioned from SSO claims, which is
    #: what routes its owner to the pick screen on their next sign-in.
    username_chosen: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # NULL = no password set (SSO-only account) — password verification treats
    # a missing hash as "never a match", so such an account can only sign in
    # through its identity provider until it explicitly sets a password.
    hashed_password: Optional[str] = Field(default=None)
    #: When this account's password was last set, as far as the record goes.
    #: NULL means one of two things a stored hash cannot tell apart: no
    #: password at all, or one set before this column existed — an account
    #: provisioned through an identity provider before ``20260720_0152`` carries
    #: a throwaway argon2 hash indistinguishable from a chosen one. Every place
    #: that sets a password stamps this, so the unknown set only shrinks.
    password_set_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    role: UserRole = Field(
        default=UserRole.member,
        sa_column=Column(
            SQLEnum(UserRole, name="user_role"),
            nullable=False,
            server_default=UserRole.member.value,
        ),
    )
    status: UserStatus = Field(
        default=UserStatus.active,
        sa_column=Column(
            SQLEnum(UserStatus, name="user_status"),
            nullable=False,
            server_default=UserStatus.active.value,
        ),
    )
    # When ``status`` last changed; NULL until the first change. For a
    # ``deleted`` account this is when the deletion was asked for, and so what
    # the erasure date is counted from — the same column, doing the same job,
    # as ``guilds.status_changed_at``.
    status_changed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Why the account was suspended, when whoever suspended it said; the
    #: time-out screen shows it. Cleared when the suspension is lifted.
    status_reason: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Where this user's picture is: a path this API serves
    #: (``/api/v1/users/{id}/avatar/{sha256}``, bytes in ``user_avatars``) or a
    #: URL somewhere else, from an OIDC ``picture`` claim. One or the other,
    #: never both — see ``app.services.platform.user_avatars``.
    avatar_url: Optional[str] = Field(default=None, nullable=True)
    token_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    #: What this person is up to, in their own words: an emoji, a short line,
    #: or both, as ``{"emoji": ..., "text": ...}``. One column rather than two,
    #: because it is one thing a person sets and one thing every surface that
    #: names them renders. Distinct from ``status`` above, which is the
    #: account's standing and is not theirs to write. The shape is
    #: ``app.schemas.platform.user.CustomStatus``.
    custom_status: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    #: How this person wants to appear to everyone else — see ``Presence``.
    #: A standing preference rather than live state: the live half is which
    #: sockets are open, which no column could hold.
    presence: Presence = Field(
        default=Presence.online,
        sa_column=Column(
            SQLEnum(Presence, name="user_presence"),
            nullable=False,
            server_default=Presence.online.value,
        ),
    )
    #: How this person's profile is dressed: a banner, a frame around the
    #: picture, trophies under it. Each is an id naming a catalog entry
    #: the client resolves to artwork it already ships — never an upload, so a
    #: decorated profile costs a guild none of its storage. The shape is
    #: ``app.schemas.platform.user.ProfileDecorations``.
    profile_decorations: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    week_starts_on: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    #: Whether clock times read as "1:30 PM" or "13:30". ``system`` — the
    #: default — names no convention and leaves the choice to the browser's
    #: locale, which is what every account had before the setting existed.
    #: See ``app.core.user_input_validators.TIME_FORMATS``.
    time_format: str = Field(
        default="system",
        sa_column=Column(String(16), nullable=False, server_default="system"),
    )
    # How many recently-opened items the header tabs bar keeps and shows for
    # this user, across all entity types and guilds. Drives both the display
    # count and how many each guild keeps (app.services.tenant.personal_items).
    # Clamped to [1, 100] on write; default 20 preserves the historic behavior.
    recent_tabs_limit: int = Field(
        default=20,
        sa_column=Column(Integer, nullable=False, server_default="20"),
    )
    #: Whether what this person opens and changes counts toward the engagement
    #: levels search orders by (app.services.tenant.engagement_levels). Theirs
    #: to turn off, and on until they do.
    count_toward_engagement_ranking: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    #: When this account said it belongs to somebody old enough to join a
    #: community the whole deployment can browse. NULL means it never has,
    #: which costs it nothing outside the directory. A timestamp rather than a
    #: flag because the record of *when* is the point: it is what a deployment
    #: running a community directory keeps for the accounts that joined one.
    #: Whether it is asked for at all is the platform owner's switch
    #: (the rule ``community_age_gate_enabled``).
    age_confirmed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    #: When this account answered the age question as being under the minimum.
    #: NULL means it never has. The date it gave is not kept — this records
    #: only that the answer was given, which is what stops the question being
    #: asked again until somebody with the standing to put it right lifts it.
    #: Never set at the same time as ``age_confirmed_at``; the two are the two
    #: answers to one question (``ck_users_age_answer``).
    age_below_minimum_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    #: When this account answered the age question as being under the minimum
    #: for an account at all where it was (``users.ACCOUNT_MINIMUM_AGE``: 13 in
    #: the US, 16 in Germany), which closes the account rather than the
    #: directory. Set beside ``age_below_minimum_at`` and never without it
    #: (``ck_users_age_account_answer``). While it stands the account is
    #: scheduled for erasure and no sign-in calls that off (:func:`may_sign_in`);
    #: ``users.age_unblock`` is what clears it.
    age_below_account_minimum_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    timezone: str = Field(
        default="UTC",
        sa_column=Column(String(64), nullable=False, server_default="UTC"),
    )
    # Lead time (minutes) for the scheduled event reminder. NULL = reminders off.
    event_reminder_minutes_before: Optional[int] = Field(
        default=15,
        sa_column=Column(Integer, nullable=True, server_default="15"),
    )
    #: When this account was last doing something, to within a few minutes.
    #: One mutable stamp rather than a history: it answers "were they here
    #: recently", which is what decides whether to interrupt somebody who is
    #: already reading the same news in the app. Never serialized to any
    #: response: it belongs to no profile family, which is what decides where a
    #: column goes (see ``app.db.user_columns``).
    last_active_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_overdue_notification_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_task_assignment_digest_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_coming_up_digest_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Locale
    locale: str = Field(
        default="en",
        sa_column=Column(String(10), nullable=False, server_default="en"),
    )

    # UI Preferences
    color_theme: str = Field(
        default="kobold",
        sa_column=Column(String(50), nullable=False, server_default="kobold"),
    )
    # Stored as a free-form short string; the frontend interprets the value
    # against a fixed enum (none | confetti | heart | d20 | gold_coin | random)
    # and falls back to "none" if it doesn't recognise the value. Scoped to
    # "visual" so audio / haptic siblings can be added later as their own
    # columns without renaming this one.
    task_completion_visual_feedback: str = Field(
        default="none",
        sa_column=Column(String(32), nullable=False, server_default="none"),
    )
    # Subtler siblings to the visual effect — these fire on any task the
    # current user marks done (assignee check is dropped because they're
    # less obtrusive). Default on so existing users discover them.
    task_completion_audio_feedback: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    task_completion_haptic_feedback: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    #: Whether a task being added reads its due date, priority, repeat, tags
    #: and assignees out of the words typed into its title. On until the
    #: account turns it off; what it reads is shown before the task is added.
    smart_task_titles: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # An account has no standing view of guild content. What refers to a person
    # from inside a guild schema — an assignment, a membership, an ordering, a
    # bookmark — is reached from that content, through ``MemberProfile``, on a
    # session routed into the guild that holds it. ``hard_delete_user`` clears
    # those rows itself, guild by guild.
    #
    # ``guild_memberships`` is the exception, and stays: it is a ``public``
    # table, and the cascade here goes with the row it names.
    guild_memberships: List["GuildMembership"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    api_keys: List["UserApiKey"] = Relationship(back_populates="user")


from app.models.platform.api_key import UserApiKey  # noqa: E402  # isort:skip
