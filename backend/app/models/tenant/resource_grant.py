"""Polymorphic per-resource access grants — the single DAC table.

One row grants access to a resource at a level for exactly one of four grantee
kinds:

- a **user** (``user_id`` set),
- an **initiative role** (``role_id`` set),
- the **whole initiative** — a "general access" row with neither ``user_id`` nor
  ``role_id`` set and ``all_initiative_members`` true; ``level`` (read/write)
  gives the Viewer/Editor level. The backend aggregates every member of the
  row's ``initiative_id`` for it (see ``app.services.permissions``).
  ``all_initiative_members`` may only be set when there is no user/role grantee
  (enforced by the ``resource_grants_one_grantee`` check), or
- an **installed plug-in** (``plugin_install_id`` set), the install acting as its
  community.

Replaces the per-resource ``*_permissions`` / ``*_role_permissions`` tables.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, Relationship

from app.core.tools import Tool
from app.models.tenant._mixins import CreatedByMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile


class ResourceAccessLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"

    def reaches(self, level: "ResourceAccessLevel") -> bool:
        """Whether this level carries what ``level`` carries.

        The sharing ladder asked as a comparison rather than as a set per
        question: ``write`` reaches ``read``, ``owner`` reaches both.
        """
        return RESOURCE_LEVEL_LADDER.index(self) >= RESOURCE_LEVEL_LADDER.index(level)


#: The sharing ladder, lowest rung first — the one ordering, which the
#: policies' write leg and the app's level arithmetic both read.
RESOURCE_LEVEL_LADDER: tuple[ResourceAccessLevel, ...] = (
    ResourceAccessLevel.read,
    ResourceAccessLevel.write,
    ResourceAccessLevel.owner,
)

#: The levels that let somebody change a resource; ``read`` is the third.
WRITE_LEVELS: tuple[ResourceAccessLevel, ...] = tuple(
    level for level in RESOURCE_LEVEL_LADDER if level.reaches(ResourceAccessLevel.write)
)


class ResourceGrant(CreatedByMixin, table=True):
    __tablename__ = "resource_grants"

    __table_args__ = (
        # Exactly one grantee kind per row: a user, an initiative role, the
        # whole initiative (all_initiative_members), or a plug-in install. This keeps the old XOR (never user AND role) and forbids the
        # share boolean whenever another grantee is set.
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
            "+ (all_initiative_members)::int "
            "+ (plugin_install_id IS NOT NULL)::int = 1",
            name="resource_grants_one_grantee",
        ),
        # A resource has one owner or none. Nothing else in the schema said so,
        # and the re-homing paths that used to upgrade every initiative manager
        # at once left resources with several.
        Index(
            "ix_resource_grants_single_owner",
            "resource_type",
            "resource_id",
            unique=True,
            postgresql_where=text("level = 'owner'"),
        ),
        # NULLS NOT DISTINCT so the unused grantee column (NULL) compares equal —
        # otherwise two identical user grants (role_id NULL) wouldn't collide.
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "user_id",
            "role_id",
            "plugin_install_id",
            name="resource_grants_unique_grantee",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # Carried directly so RLS is a plain initiative_access(initiative_id) — no hop.
    #
    # NULL means the grant is on a guild-level resource: one that belongs to no
    # initiative, so its scope is the guild itself. The DAC semantics are
    # unchanged — a grant still names a user, a role, or everyone — and at guild
    # scope "everyone" reads as every guild member.
    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    # resource_id is polymorphic (keyed by resource_type) — no FK; cleaned up in the
    # resource's delete path, inert if orphaned.
    # Indexed by the COMPOSITE partial indexes below (ix_resource_grants_resource
    # etc.), owned by migration history — not per-column, so no index=True here.
    # Typed as the canonical Tool enum (stored as its string value).
    resource_type: Tool = Field(sa_column=Column(String(length=32), nullable=False))
    resource_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id"),
            nullable=True,
        ),  # indexed by composite partial ix_resource_grants_user
    )
    role_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="CASCADE"),
            nullable=True,
        ),  # indexed by composite partial ix_resource_grants_role
    )
    #: The installed plug-in this grant is made to. The row says what the install
    #: may reach when it acts as its community; uninstalling removes its
    #: grants with it.
    plugin_install_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            nullable=True,
        ),  # indexed by the partial ix_resource_grants_plugin_install
    )
    level: ResourceAccessLevel = Field(
        sa_column=Column(String(length=16), nullable=False)
    )
    # All-initiative-members grant — when true (and there is no user/role
    # grantee), the row grants every member of ``initiative_id`` access at
    # ``level`` (read = Viewer, write = Editor). The constraint forbids it being
    # set alongside a user/role.
    all_initiative_members: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(ResourceGrant.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )
