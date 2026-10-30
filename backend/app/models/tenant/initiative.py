from datetime import datetime, timezone
from enum import Enum
from typing import List, NamedTuple, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.orm import column_property
from sqlmodel import Field, Relationship, SQLModel

from app.core.tools import DEFAULT_ENABLED_TOOLS, Tool
from app.db.registry_checks import FROM_REGISTRY
from app.models.platform.user import ABSENT_STATUSES
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant._mixins import (
    ArchiveMixin,
    CreatedByMixin,
    SoftDeleteMixin,
    _reader,
    attach_initiative_actions,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.project import Project
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.file import File
    from app.models.tenant.queue import Queue
    from app.models.tenant.calendar import Calendar
    from app.models.tenant.counter import CounterGroup


class InitiativeJoinPolicy(str, Enum):
    """How a guild member may come to hold a membership row in an initiative.

    The policy governs *how a membership row comes to exist* — it is never
    consulted by RLS. ``initiative_access`` still answers every access
    question from ``initiative_members`` exactly as it did before.

    - ``private``: invisible outside its membership; a manager adds people by
      hand. The default, so nothing opens on upgrade.
    - ``request``: listed in the guild's initiative directory; members ask and a
      manager resolves the request.
    - ``open``: listed in the directory; any guild member self-joins and
      receives the built-in ``member`` role.

    Stored as a plain string with a table CHECK (the ``guilds.status`` pattern)
    rather than a Postgres enum, so adding a policy is an ordinary migration.
    """

    private = "private"
    request = "request"
    open = "open"


class JoinRequestStatus(str, Enum):
    """Lifecycle of a row in ``initiative_join_requests``."""

    pending = "pending"
    approved = "approved"
    denied = "denied"


# Permission keys for role-based access control — derived from the Tool enum,
# one `{plural}_enabled` + `create_{plural}` pair per tool (projects_enabled,
# create_projects, …), plus the few EXTRA_PERMISSION_KEYS that are not a tool of
# their own. A new Tool member gets its keys automatically, and the CHECK on
# initiative_rules is rendered from them at boot
# (``app.db.registry_checks``).
#: Role keys that are not a tool's pair. Each is a capability inside a tool
#: rather than the tool itself, defaults to off for an ordinary role, and is
#: held by every manager role.
EXTRA_PERMISSION_KEYS: tuple[str, ...] = (
    # Set a dashboard to run as the initiative: everyone who opens it sees
    # every row in the initiative, whatever their own access.
    "dashboards_run_as_initiative",
)

PermissionKey = Enum(
    "PermissionKey",
    [(name, name) for t in Tool for name in (t.view_permission, t.create_permission)]
    + [(name, name) for name in EXTRA_PERMISSION_KEYS],
    type=str,
)


# Fallback values when a permission is not explicitly set on a role, derived
# from the tool classification: viewing a tool an initiative starts with
# defaults to True, viewing one it does not defaults to False (its initiative
# master switch gates availability, and within that only managers see it unless
# a custom role grants it), and creation is always False (restrictive).
#
# This is the ROLE default, and it is a separate question from the initiative's
# master switch: the switch says whether a tool exists here at all, and this
# says what an ordinary member may do with one that does.
DEFAULT_PERMISSION_VALUES: dict["PermissionKey", bool] = {
    **{PermissionKey(t.view_permission): t in DEFAULT_ENABLED_TOOLS for t in Tool},
    **{PermissionKey(t.create_permission): False for t in Tool},
    **{PermissionKey(name): False for name in EXTRA_PERMISSION_KEYS},
}


class BuiltinRole(NamedTuple):
    """One of the roles every initiative is created with.

    The whole definition of a built-in lives here — its name, how it is
    labelled, whether it manages the initiative, whether it carries "Full
    access", and what it may do with each tool. ``create_builtin_roles`` walks
    this tuple in order, and each role's ``position`` is its index, so the
    order below is the order the settings screen lists them in.
    """

    name: str
    display_name: str
    is_manager: bool
    override_share_restrictions: bool
    permissions: dict["PermissionKey", bool]


# The built-in roles, ordered. Moderator and project manager get every tool
# permission; members get view-only on the core (always-on) tools.
BUILTIN_ROLES: tuple[BuiltinRole, ...] = (
    BuiltinRole(
        name="moderator",
        display_name="Moderator",
        is_manager=True,
        override_share_restrictions=True,
        permissions={key: True for key in PermissionKey},
    ),
    BuiltinRole(
        name="project_manager",
        display_name="Project Manager",
        is_manager=True,
        override_share_restrictions=False,
        permissions={key: True for key in PermissionKey},
    ),
    BuiltinRole(
        name="member",
        display_name="Member",
        is_manager=False,
        override_share_restrictions=False,
        permissions=dict(DEFAULT_PERMISSION_VALUES),
    ),
)

BUILTIN_ROLE_PERMISSIONS = {role.name: role.permissions for role in BUILTIN_ROLES}

# The built-ins whose tool permissions are fixed: they already hold every key,
# so there is nothing to configure and a screen that offered the switches would
# only offer a way to lock somebody out.
LOCKED_PERMISSION_ROLE_NAMES = frozenset(
    role.name for role in BUILTIN_ROLES if all(role.permissions.values())
)


class InitiativeRoleModel(CreatedByMixin, table=True):
    """Defines roles available per initiative."""

    __tablename__ = "initiative_roles"
    __table_args__ = (
        UniqueConstraint("initiative_id", "name", name="uq_initiative_role_name"),
        # What an initiative's rule names a role by: the role and the
        # initiative it belongs to, so a rule never reaches another's role.
        UniqueConstraint("id", "initiative_id", name="uq_initiative_roles_initiative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    name: str = Field(max_length=100)  # e.g., "project_manager", "viewer"
    display_name: str = Field(max_length=100)  # e.g., "Project Manager"
    is_builtin: bool = Field(default=False)  # true for the BUILTIN_ROLES
    is_manager: bool = Field(default=False)  # counts toward manager constraint
    # "Full access": members with this role view/edit ALL content in the
    # initiative regardless of how each item is shared, and may manage sharing
    # (the gate-4 / DAC override, scoped to this one initiative). Off by
    # default; the built-in moderator role is the one that carries it, and a
    # guild admin joining an initiative lands on that role.
    override_share_restrictions: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    position: int = Field(default=0)  # for ordering in UI

    initiative: Optional["Initiative"] = Relationship(back_populates="roles")
    permissions: List["InitiativeRule"] = Relationship(
        back_populates="role",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    members: List["InitiativeMember"] = Relationship(back_populates="role_ref")


class InitiativeRule(SQLModel, table=True):
    """One of an initiative's rules: what one of its roles may do with a tool
    (``PermissionKey``). Kept in the community's own schema beside the
    initiative, and gone with it; a role's rules go with the role."""

    __tablename__ = "initiative_rules"
    __table_args__ = (
        CheckConstraint(
            "key IN (" + ", ".join(f"'{key.value}'" for key in PermissionKey) + ")",
            name="ck_initiative_rules_key",
            info={FROM_REGISTRY: True},
        ),
        ForeignKeyConstraint(
            ["initiative_role_id", "initiative_id"],
            ["initiative_roles.id", "initiative_roles.initiative_id"],
            ondelete="CASCADE",
            name="fk_initiative_rules_role",
        ),
        UniqueConstraint(
            "initiative_id",
            "key",
            "initiative_role_id",
            name="uq_initiative_rules_subject",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: The role the rule is about.
    initiative_role_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    key: str = Field(sa_column=Column(String(64), nullable=False))
    enabled: bool = Field(sa_column=Column(Boolean, nullable=False))

    role: Optional["InitiativeRoleModel"] = Relationship(back_populates="permissions")


class InitiativeMember(SQLModel, table=True):
    __tablename__ = "initiative_members"

    initiative_id: int = Field(
        foreign_key="initiatives.id", ondelete="CASCADE", primary_key=True
    )
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    role_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: The provider whose claims put this person here — see
    #: ``GuildMembership.oidc_provider_id``, which this mirrors. A plain
    #: integer and no foreign key: this table lives in a guild schema and
    #: ``auth_providers`` does not, the same arrangement every other reference
    #: across that line uses. A provider that has been deleted therefore leaves
    #: an id that matches nothing, which reads as unmanaged and is the outcome
    #: the shared table's ``SET NULL`` produces.
    oidc_provider_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="memberships")
    user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(InitiativeMember.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )
    role_ref: Optional["InitiativeRoleModel"] = Relationship(back_populates="members")


class InitiativeJoinRequest(SQLModel, table=True):
    """A guild member knocking on a ``request``-policy initiative.

    Deliberately guild-level rather than initiative-scoped (see
    ``app.db.tenancy.GUILD_LEVEL_TABLES``): a requester is by definition not yet
    a member, so an initiative-membership row gate would hide their own request
    from them. Who may read which rows is decided in the service layer instead —
    requesters see their own, managers see their initiative's.
    """

    __tablename__ = "initiative_join_requests"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_initiative_join_requests_status",
        ),
        # One live request per user per initiative; resolved rows stay as history.
        Index(
            "uq_initiative_join_requests_pending",
            "initiative_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )
    )
    status: str = Field(
        default=JoinRequestStatus.pending.value,
        sa_column=Column(
            String(length=20),
            nullable=False,
            server_default=JoinRequestStatus.pending.value,
        ),
    )
    # Optional note from the requester to the initiative's managers.
    message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    resolved_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # The manager who approved or denied; NULL while pending.
    resolved_by: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id"),
            nullable=True,
        ),
    )


# One `{tool.plural}_enabled` master-switch column per Tool — derived from the
# enum, so a new tool grows its column here automatically. The actual DDL still
# ships as a guild migration (and the provisioning drift tests catch a
# model/schema mismatch).
#
# Only the default varies: the tools in DEFAULT_ENABLED_TOOLS start on, so an
# initiative created without an opinion is the one people already had.
_InitiativeToolSwitchColumns = type(
    "_InitiativeToolSwitchColumns",
    (SQLModel,),
    {
        "__module__": __name__,
        "__annotations__": {t.view_permission: bool for t in Tool},
        **{
            t.view_permission: Field(
                default=t in DEFAULT_ENABLED_TOOLS,
                nullable=False,
                sa_column_kwargs={
                    "server_default": str(t in DEFAULT_ENABLED_TOOLS).lower()
                },
            )
            for t in Tool
        },
    },
)


class Initiative(
    _InitiativeToolSwitchColumns,
    CreatedByMixin,
    ArchiveMixin,
    SoftDeleteMixin,
    table=True,
):
    __tablename__ = "initiatives"

    __table_args__ = (
        # Literal SQL, mirroring the migration that creates them: the vocabulary
        # is InitiativeJoinPolicy, and widening it is a migration either way.
        CheckConstraint(
            "join_policy IN ('private', 'request', 'open')",
            name="ck_initiatives_join_policy",
        ),
        # Auto-join enrols arrivals automatically, so the initiative must also be
        # one they could have found and joined themselves.
        CheckConstraint(
            "(NOT auto_join) OR join_policy = 'open'",
            name="ck_initiatives_auto_join_open",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, nullable=False)
    description: Optional[str] = Field(default=None)
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    # See InitiativeJoinPolicy. Guarded by ck_initiatives_join_policy.
    join_policy: str = Field(
        default=InitiativeJoinPolicy.private.value,
        sa_column=Column(
            String(length=20),
            nullable=False,
            server_default=InitiativeJoinPolicy.private.value,
        ),
    )
    # New guild members are enrolled in this initiative automatically. Guild-admin
    # settable, and only on an `open` initiative (ck_initiatives_auto_join_open).
    auto_join: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Nothing in it is exported on its own or copied to another initiative,
    # by anyone. The initiative and community backups still take it.
    keep_content_in: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    memberships: List["InitiativeMember"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    roles: List["InitiativeRoleModel"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    projects: List["Project"] = Relationship(back_populates="initiative")
    files: List["File"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    queues: List["Queue"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    calendars: List["Calendar"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    counter_groups: List["CounterGroup"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


attach_initiative_actions(Initiative)

# How many people the initiative holds, and the role the request's user holds
# in it. Deferred like ``actions``; the loaders that serialize an initiative ask
# for them with ``undefer``. The count is of the people its roster lists: an
# account that is suspended or awaiting erasure is absent from both.
Initiative.__mapper__.add_property(  # type: ignore[attr-defined]
    "member_count",
    column_property(
        select(func.count())
        .select_from(InitiativeMember)
        .join(MemberProfile, MemberProfile.id == InitiativeMember.user_id)
        .where(
            InitiativeMember.initiative_id == Initiative.id,
            MemberProfile.status.notin_(sorted(ABSENT_STATUSES, key=lambda s: s.value)),
        )
        .correlate_except(InitiativeMember, MemberProfile)
        .scalar_subquery(),
        deferred=True,
    ),
)
Initiative.__mapper__.add_property(  # type: ignore[attr-defined]
    "role_display_name",
    column_property(
        select(InitiativeRoleModel.display_name)
        .join(InitiativeMember, InitiativeMember.role_id == InitiativeRoleModel.id)
        .where(
            InitiativeMember.initiative_id == Initiative.id,
            InitiativeMember.user_id == _reader(),
        )
        .correlate_except(InitiativeMember, InitiativeRoleModel)
        .scalar_subquery(),
        deferred=True,
    ),
)
