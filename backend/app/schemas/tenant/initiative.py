from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, TYPE_CHECKING

from pydantic import AliasChoices, ConfigDict, Field, create_model

from app.core.identity_boundary import GuildId
from app.core.tools import DEFAULT_ENABLED_TOOLS, Tool
from app.schemas.base import (
    RichMentionStr,
    SanitizedBaseModel,
    TitleStr,
    reject_null,
)

from app.models.tenant.initiative import (
    BUILTIN_MEMBER_ROLE,
    DEFAULT_PERMISSION_VALUES,
    InitiativeJoinPolicy,
    JoinRequestStatus,
    PermissionKey,
)
from app.models.platform.user import Presence
from app.schemas.platform.user import UserSummary
from app.schemas.query import PageMeta

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.initiative import (
        Initiative,
        InitiativeMember,
        InitiativeRoleModel,
    )


HEX_COLOR_PATTERN = r"^#(?:[0-9a-fA-F]{3}){1,2}$"

#: A join request's note is a sentence or two for the managers reading the
#: queue, not a file — so it is capped well below the 8 KB plain-text
#: ceiling every ``SanitizedBaseModel`` string already carries.
JOIN_REQUEST_MESSAGE_MAX_LENGTH = 1000


class InitiativeListScope(str, Enum):
    """Which initiatives ``GET /initiatives/`` should return.

    ``member`` — the caller's own workspace: the initiatives they hold a
    membership in. This is what the sidebar and every initiative picker show.

    ``community`` — every initiative in the community, for the guild-settings
    management table. Guild admins only.
    """

    member = "member"
    community = "community"


# Derived bases: one `{tool.plural}_enabled` master-switch field per Tool. A new
# Tool member grows these schemas automatically (the SQLModel column itself is
# still declared on the Initiative model — real DDL stays explicit, pinned by
# its migration and the drift test).
#
# The field default matches the column default, so a create that names no tools
# gets projects and files rather than an initiative with nothing in it.
_InitiativeToolSwitches = create_model(
    "_InitiativeToolSwitches",
    __base__=SanitizedBaseModel,
    **{t.view_permission: (bool, t in DEFAULT_ENABLED_TOOLS) for t in Tool},
)
_InitiativeToolSwitchesPatch = create_model(
    "_InitiativeToolSwitchesPatch",
    __base__=SanitizedBaseModel,
    **{t.view_permission: (Optional[bool], None) for t in Tool},
)


class InitiativeBase(_InitiativeToolSwitches):
    name: str
    description: Optional[RichMentionStr] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)


class InitiativeCreate(InitiativeBase):
    name: TitleStr
    # Creation is guild-admin only, so the policy is theirs to set from the
    # start; defaulting private keeps "open" an explicit choice.
    join_policy: InitiativeJoinPolicy = InitiativeJoinPolicy.private


class InitiativeUpdate(_InitiativeToolSwitchesPatch):
    name: Optional[TitleStr] = None
    description: Optional[RichMentionStr] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)
    # Settable by whoever may already update the initiative (managers, guild
    # admins).
    join_policy: Optional[InitiativeJoinPolicy] = None
    # Guild admins only — enforced in the endpoint, and only valid alongside a
    # resulting join_policy of 'open'.
    auto_join: Optional[bool] = None
    # Settable by whoever may already update the initiative.
    keep_content_in: Optional[bool] = None

    _required = reject_null(
        "name",
        "join_policy",
        "auto_join",
        "keep_content_in",
        *(t.view_permission for t in Tool),
    )


# Role schemas
class InitiativeRoleRead(SanitizedBaseModel):
    """Role definition with permissions."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    display_name: str
    is_builtin: bool
    is_manager: bool
    # "Full access": this role views/edits all initiative content regardless of
    # sharing and may manage sharing. Carried by the built-in moderator role.
    override_share_restrictions: bool = False
    position: int
    permissions: Dict[PermissionKey, bool] = Field(default_factory=dict)
    member_count: int = 0


class InitiativeRoleCreate(SanitizedBaseModel):
    """Create a new custom role."""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)
    is_manager: bool = False
    permissions: Optional[Dict[PermissionKey, bool]] = None


class InitiativeRoleUpdate(SanitizedBaseModel):
    """Update a role's display name and/or permissions."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_manager: Optional[bool] = None
    permissions: Optional[Dict[PermissionKey, bool]] = None


class InitiativeDefaultsRead(SanitizedBaseModel):
    """What the community sets for every initiative in it. A tool or a member
    permission absent here is each initiative's own to set."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Each tool's switch the community set, by tool.
    tools: Dict[Tool, bool] = Field(default_factory=dict)
    #: What the built-in member role may do, by permission, where it set it.
    member_permissions: Dict[PermissionKey, bool] = Field(default_factory=dict)
    #: Whether managers may add roles of their own.
    custom_roles: bool = True


class InitiativeDefaultsUpdate(SanitizedBaseModel):
    """The defaults to change. A ``null`` hands that tool or permission back
    to each initiative; an omitted one is left as it is."""

    tools: Dict[Tool, Optional[bool]] = Field(default_factory=dict)
    member_permissions: Dict[PermissionKey, Optional[bool]] = Field(
        default_factory=dict
    )
    custom_roles: Optional[bool] = None


class ToolCountsByInitiativeResponse(SanitizedBaseModel):
    """Each tool's visible-row counts, by initiative (tool -> initiative_id ->
    count) — what the sidebar and the initiative directory badge."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: Dict[Tool, Dict[int, int]] = Field(default_factory=dict)


class ToolCountsResponse(SanitizedBaseModel):
    """One tool's page: how many rows sit in each of its views, and the tag
    tree beside the view being shown."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: View name -> rows. ``active`` and ``archived`` for every tool, and
    #: ``templates`` for a tool that keeps them.
    views: Dict[str, int]
    #: The tag tree beside the view asked for; ``None`` unless it was.
    tag_counts: Optional[Dict[int, int]] = None
    untagged_count: Optional[int] = None


# Member schemas - updated to work with role_id
class InitiativeMemberAdd(SanitizedBaseModel):
    """Add a member to an initiative."""

    user_id: int
    role_id: Optional[int] = None


class InitiativeMemberUpdate(SanitizedBaseModel):
    """Update a member's role."""

    role_id: int


class InitiativeMemberRead(SanitizedBaseModel):
    """Member info including their role."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    #: With what they have put around their picture, which a roster draws.
    user: UserSummary
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
    is_manager: bool = False
    #: Whether this member's role carries "Full access" — reaching every item
    #: in the initiative however it is shared, and managing that sharing. A
    #: guild admin clears it without holding it, so the client folds that in
    #: the way it already does for ``is_manager``.
    override_share_restrictions: bool = False
    joined_at: datetime
    oidc_managed: bool = False
    #: How they appear right now, public as it is on their profile.
    presence: Presence = Presence.offline
    #: When their time in the community ends, for a guest. ``None`` for a
    #: member.
    guest_until: Optional[datetime] = None


class InitiativeMemberListResponse(PageMeta):
    """One page of an initiative's roster, each member with their role."""

    items: List[InitiativeMemberRead]


class InitiativeCan(SanitizedBaseModel):
    """What the caller may do in an initiative (:func:`initiative_can`)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Run the initiative itself — its settings, roster and roles.
    manage: bool = False
    #: Act on its moderation reports ("Full access", or the community's admin).
    moderate: bool = False
    #: Read who is in it: its members, the community's admin and a grantee,
    #: not a guest given items in it.
    roster: bool = False
    #: The tools the caller may open here.
    view: List[Tool] = Field(default_factory=list)
    #: The tools the caller may make a new one of here.
    create: List[Tool] = Field(default_factory=list)


class InitiativeRead(InitiativeBase):
    """An initiative: the row, its headcount, what the caller may do in it and
    the role they hold there. Its roster is read a page at a time from
    ``GET /initiatives/{id}/members``."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    #: The community this initiative was read in. Set by
    #: :func:`serialize_initiative`; a payload pydantic builds while validating
    #: another carries none until that serializer replaces it.
    community_id: Optional[GuildId] = Field(
        default=None, validation_alias=AliasChoices("community_id", "guild_id")
    )
    # Hidden from the main sidebar once set (see Initiative.archived_at).
    archived_at: Optional[datetime] = None
    # How guild members may join (see InitiativeJoinPolicy). Never consulted by
    # RLS — it governs how a membership row comes to exist, nothing more.
    join_policy: InitiativeJoinPolicy = InitiativeJoinPolicy.private
    auto_join: bool = False
    #: Nothing in it is exported on its own or copied to another initiative.
    keep_content_in: bool = False
    created_at: datetime
    updated_at: datetime
    can: InitiativeCan = Field(default_factory=InitiativeCan)
    member_count: int = 0
    #: The caller's role here, when they are a member.
    role_display_name: Optional[str] = None


class InitiativeDirectoryEntry(SanitizedBaseModel):
    """One card in a guild's initiative directory.

    Only initiatives that chose to be listed (``request`` / ``open``) ever reach
    this shape; a ``private`` one is excluded in the service. The three caller-
    relative fields answer which call to action the card renders: already in it,
    knocked and waiting, or free to join.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    join_policy: InitiativeJoinPolicy
    # Whether new guild members are enrolled here on arrival. Discloses nothing
    # a card does not already: ``ck_initiatives_auto_join_open`` means only an
    # ``open`` initiative can carry it, and an open one is listed to every guild
    # member anyway. It is what lets a guild's admin see, from the list they
    # would pick from, whether arrivals currently land anywhere at all.
    auto_join: bool = False
    member_count: int = 0
    is_member: bool = False
    #: The caller's role here, when they are a member.
    role_display_name: Optional[str] = None
    has_pending_request: bool = False
    # How many people are waiting at this door — the badge on a manager's card.
    # Zero for everyone who could not act on the queue anyway (see
    # ``list_directory_entries``), so the directory never tells a bystander how
    # many of their peers asked to get in.
    pending_join_request_count: int = 0


class InitiativeJoinRequestCreate(SanitizedBaseModel):
    """A guild member knocking on a ``request``-policy initiative."""

    message: Optional[str] = Field(
        default=None, max_length=JOIN_REQUEST_MESSAGE_MAX_LENGTH
    )


class InitiativeJoinRequestRead(SanitizedBaseModel):
    """One row of an initiative's join-request queue.

    Carries everything the manager needs to decide without a second call: who
    is asking (the same slim user projection the member pickers use), what they
    said, when they asked, and how many times this initiative has turned them
    down before — a denied requester may ask again, so the history is what keeps
    the repeat visible.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    user: UserSummary
    status: JoinRequestStatus
    message: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    prior_denials: int = 0


def serialize_role(
    role: "InitiativeRoleModel",
    member_count: int = 0,
    *,
    defaults: InitiativeDefaultsRead | None = None,
) -> InitiativeRoleRead:
    """Serialize a role model to a read schema.

    Every permission key is answered for, not just the ones with a stored row:
    a role created before a tool shipped has no row for it, and a caller asking
    "who can see Posts" must not have to know that an absent key means the
    documented default. The stored row wins wherever there is one, and for the
    built-in member role what the community set (``defaults``) wins over it.
    """
    permissions = {
        **DEFAULT_PERMISSION_VALUES,
        **{perm.key: perm.enabled for perm in (role.permissions or [])},
    }
    if defaults is not None and role.is_builtin and role.name == BUILTIN_MEMBER_ROLE:
        permissions.update(defaults.member_permissions)
    return InitiativeRoleRead(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        is_builtin=role.is_builtin,
        is_manager=role.is_manager,
        override_share_restrictions=getattr(role, "override_share_restrictions", False),
        position=role.position,
        permissions=permissions,
        member_count=member_count,
    )


class InitiativeSummary(SanitizedBaseModel):
    """An initiative as something else names it: enough to label and link it.

    What a project, a file or a task carries about the initiative it is in.
    The initiative's own read is :class:`InitiativeRead`.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    color: Optional[str] = None


def initiative_can(initiative: "Initiative") -> InitiativeCan:
    """What the caller may do in ``initiative``, as the schema's
    ``initiative_actions`` answered it in the SELECT that loaded the row."""
    held = set(initiative.actions or ())
    return InitiativeCan(
        manage="manage" in held,
        moderate="moderate" in held,
        roster="roster" in held,
        view=[t for t in Tool if f"view:{t.value}" in held],
        create=[t for t in Tool if f"create:{t.value}" in held],
    )


def serialize_initiative(
    initiative: "Initiative", *, context: "ActorContext"
) -> InitiativeRead:
    """The initiative as a route answers with it. ``actions``, ``member_count``
    and ``role_display_name`` are deferred on the model, so whoever loads the
    row undefers them."""
    # Here rather than at the top: the switches read the standing's module,
    # which reads these schemas.
    from app.services.tenant.initiative_tools import tool_on

    return InitiativeRead(
        id=initiative.id,
        community_id=context.guild_id,
        name=initiative.name,
        description=initiative.description,
        color=initiative.color,
        archived_at=getattr(initiative, "archived_at", None),
        join_policy=getattr(
            initiative, "join_policy", InitiativeJoinPolicy.private.value
        ),
        auto_join=getattr(initiative, "auto_join", False),
        keep_content_in=initiative.keep_content_in,
        created_at=initiative.created_at,
        updated_at=initiative.updated_at,
        can=initiative_can(initiative),
        member_count=initiative.member_count,
        role_display_name=initiative.role_display_name,
        **{t.view_permission: tool_on(context, initiative, t) for t in Tool},
    )


def serialize_initiative_member(
    membership: "InitiativeMember",
    presence: Presence = Presence.offline,
    guest_until: Optional[datetime] = None,
) -> InitiativeMemberRead:
    """One roster row: the member, the role they hold, how they appear and,
    for a guest, when they go. Reads ``membership.user`` and
    ``membership.role_ref``, so the loader brings both."""
    role = membership.role_ref
    return InitiativeMemberRead(
        user=UserSummary.model_validate(membership.user),
        role_id=membership.role_id,
        role_name=role.name if role else None,
        role_display_name=role.display_name if role else None,
        is_manager=role.is_manager if role else False,
        override_share_restrictions=(
            role.override_share_restrictions if role else False
        ),
        joined_at=membership.joined_at,
        oidc_managed=membership.oidc_provider_id is not None,
        presence=presence,
        guest_until=guest_until,
    )
