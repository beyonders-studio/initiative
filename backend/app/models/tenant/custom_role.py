"""A community's custom roles: named sets of admin surfaces, on a rung.

A custom role holds some of the parts of administering the community
(``app.models.platform.guild.AdminSurface``) and is anchored to a rung: on the
admin rung it narrows what an admin holds, on the member rung it gives a member
a few surfaces. It applies only while its holder's rung, which
``public.guild_memberships`` keeps, is the role's ``base_rung``, and only to an
assignment made during the membership the holder has now. Otherwise the holder
stands on their plain rung. Both tables are the community's own: nothing outside
it reads them.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlmodel import Field, SQLModel

from app.db.registry_checks import FROM_REGISTRY
from app.models.platform.guild import MEMBER_ROLE_SURFACES, AdminSurface, CommunityRole
from app.models.tenant._mixins import CreatedByMixin

#: The rungs a custom role may be anchored to.
CUSTOM_ROLE_RUNGS: tuple[CommunityRole, ...] = (
    CommunityRole.member,
    CommunityRole.admin,
)

#: The longest name a custom role may have.
CUSTOM_ROLE_NAME_MAX_LENGTH = 64


def _listed(values: Iterable[Enum]) -> str:
    return ", ".join(f"'{value.value}'" for value in values)


def _surfaces(values: Iterable[AdminSurface]) -> str:
    return f"ARRAY[{_listed(values)}]::text[]"


class CustomRole(CreatedByMixin, table=True):
    """A named set of admin surfaces, on the rung it applies to."""

    __tablename__ = "custom_roles"
    __table_args__ = (
        CheckConstraint(
            f"base_rung IN ({_listed(CUSTOM_ROLE_RUNGS)})",
            name="ck_custom_roles_base_rung",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            f"surfaces <@ {_surfaces(AdminSurface)}"
            f" AND (base_rung <> '{CommunityRole.member.value}'"
            f" OR surfaces <@ {_surfaces(sorted(MEMBER_ROLE_SURFACES))})",
            name="ck_custom_roles_surfaces",
            info={FROM_REGISTRY: True},
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(
        sa_column=Column(
            String(length=CUSTOM_ROLE_NAME_MAX_LENGTH), nullable=False, unique=True
        )
    )
    base_rung: str = Field(sa_column=Column(String(length=16), nullable=False))
    surfaces: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CustomRoleMember(SQLModel, table=True):
    """Who holds a custom role: one per person, from ``assigned_at``."""

    __tablename__ = "custom_role_members"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("custom_roles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: When the role was given, by the database. The standing applies it only
    #: from the holder's ``guild_memberships.joined_at`` on, so leaving and
    #: coming back does not bring an old role back.
    assigned_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
