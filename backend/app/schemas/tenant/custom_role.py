"""A community's custom roles, as its settings read and write them."""

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.core.rules import SetBy
from app.models.platform.guild import AdminSurface, CommunityRole
from app.models.tenant.custom_role import (
    CUSTOM_ROLE_NAME_MAX_LENGTH,
    CUSTOM_ROLE_RUNGS,
)
from app.schemas.base import SanitizedBaseModel, TitleStr


class PluginPermissionRef(SanitizedBaseModel):
    """One installed plug-in's community permission."""

    install_id: int
    permission: str = Field(min_length=1, max_length=64)


class CustomRoleRead(SanitizedBaseModel):
    id: int
    name: str
    #: The rung the role applies on: ``member`` or ``admin``.
    base_rung: CommunityRole
    surfaces: list[AdminSurface]
    #: The plug-ins' community permissions a role on the admin rung keeps, as
    #: ``surfaces`` keeps parts of administering the community.
    plugin_permissions: list[PluginPermissionRef] = []
    #: Who defined the role. The community gives a role the deployment
    #: defined, and does not change or delete it.
    set_by: SetBy


class CustomRoleCreate(SanitizedBaseModel):
    name: TitleStr = Field(min_length=1, max_length=CUSTOM_ROLE_NAME_MAX_LENGTH)
    #: ``member`` or ``admin`` (``CUSTOM_ROLE_RUNGS``).
    base_rung: CommunityRole
    surfaces: list[AdminSurface] = Field(default_factory=list)
    plugin_permissions: list[PluginPermissionRef] = Field(
        default_factory=list, max_length=1000
    )

    @field_validator("base_rung")
    @classmethod
    def _anchorable(cls, rung: CommunityRole) -> CommunityRole:
        if rung not in CUSTOM_ROLE_RUNGS:
            raise ValueError("a custom role is on the member or the admin rung")
        return rung


class CustomRoleUpdate(SanitizedBaseModel):
    name: TitleStr | None = Field(
        default=None, min_length=1, max_length=CUSTOM_ROLE_NAME_MAX_LENGTH
    )
    surfaces: list[AdminSurface] | None = None
    #: The whole set of plug-ins' community permissions the role keeps.
    plugin_permissions: list[PluginPermissionRef] | None = Field(
        default=None, max_length=1000
    )


class CustomRoleAssignment(SanitizedBaseModel):
    #: The role to give, or ``None`` to take the person's role off.
    role_id: int | None = None


class CustomRoleHolder(SanitizedBaseModel):
    user_id: int
    role_id: int


class HeldSurfacesRead(SanitizedBaseModel):
    #: The admin surfaces the reader holds in the community, as the request's
    #: standing computed them.
    surfaces: list[AdminSurface]
    #: The installed plug-ins' community permissions they hold, likewise.
    plugin_permissions: list[PluginPermissionRef] = []


#: A group as a provider spells it, without the spaces around it.
GroupName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class CustomRoleClaimRuleCreate(SanitizedBaseModel):
    #: One of the community's connected sign-in providers.
    provider_id: int
    #: The group the provider asserts, as the community's other claim rules
    #: name it.
    claim_value: GroupName
    role_id: int


class CustomRoleClaimRuleUpdate(SanitizedBaseModel):
    """Change the group a rule reads or the role it gives. Its provider and
    its place in the order are not changed here."""

    claim_value: GroupName | None = None
    role_id: int | None = None


class CustomRoleClaimRuleRead(SanitizedBaseModel):
    id: int
    provider_id: int
    claim_value: str
    role_id: int
    #: Earlier first; the first matching rule decides the role.
    position: int


class CustomRoleClaimRuleOrder(SanitizedBaseModel):
    #: Every rule's id, once, in the order a sign-in should read them.
    rule_ids: list[int]
