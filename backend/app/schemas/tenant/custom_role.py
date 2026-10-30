"""A community's custom roles, as its settings read and write them."""

from typing import Optional

from pydantic import Field, field_validator

from app.models.platform.guild import AdminSurface, CommunityRole
from app.models.tenant.custom_role import (
    CUSTOM_ROLE_NAME_MAX_LENGTH,
    CUSTOM_ROLE_RUNGS,
)
from app.schemas.base import SanitizedBaseModel


class CustomRoleRead(SanitizedBaseModel):
    id: int
    name: str
    #: The rung the role applies on: ``member`` or ``admin``.
    base_rung: CommunityRole
    surfaces: list[AdminSurface]


class CustomRoleCreate(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=CUSTOM_ROLE_NAME_MAX_LENGTH)
    #: ``member`` or ``admin`` (``CUSTOM_ROLE_RUNGS``).
    base_rung: CommunityRole
    surfaces: list[AdminSurface] = Field(default_factory=list)

    @field_validator("base_rung")
    @classmethod
    def _anchorable(cls, rung: CommunityRole) -> CommunityRole:
        if rung not in CUSTOM_ROLE_RUNGS:
            raise ValueError("a custom role is on the member or the admin rung")
        return rung


class CustomRoleUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(
        default=None, min_length=1, max_length=CUSTOM_ROLE_NAME_MAX_LENGTH
    )
    surfaces: Optional[list[AdminSurface]] = None


class CustomRoleAssignment(SanitizedBaseModel):
    #: The role to give, or ``None`` to take the person's role off.
    role_id: Optional[int] = None


class CustomRoleHolder(SanitizedBaseModel):
    user_id: int
    role_id: int
