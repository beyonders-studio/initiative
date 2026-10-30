"""A community's custom roles: defining them (``roles``) and giving them
(``members``).

Each write is refused here with the reason, and by the policies on
``custom_roles`` and ``custom_role_members`` whatever the route says
(``app.db.guild_ddl``): nobody writes or gives a role holding a surface they do
not hold, a role on the admin rung takes an admin, and taking one off an admin
takes somebody who holds every surface. While the deployment has closed
``surface.custom_roles`` nothing here changes, and the roles the community has
keep applying.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.api.deps import (
    CurrentUser,
    GuildContext,
    GuildContextDep,
    RLSSessionDep,
    SettingsRLSSessionDep,
    require_surface,
)
from app.core.audit_events import AuditEventType
from app.core.messages import CustomRoleMessages, GuildMessages
from app.core.rules import SURFACE_CUSTOM_ROLES
from app.models.platform.guild import (
    MEMBER_ROLE_SURFACES,
    AdminSurface,
    CommunityRole,
    GuildMembership,
)
from app.models.tenant.custom_role import CustomRole
from app.schemas.tenant.custom_role import (
    CustomRoleAssignment,
    CustomRoleCreate,
    CustomRoleHolder,
    CustomRoleRead,
    CustomRoleUpdate,
    HeldSurfacesRead,
)
from app.services import audit as audit_service
from app.services.tenant import custom_roles as custom_roles_service

router = APIRouter()


def _writes(surface: AdminSurface):
    """A write to the roles, by a holder of ``surface``, while the deployment
    leaves ``surface.custom_roles`` open."""
    guard = require_surface(surface, settings=True, write=True)

    async def dependency(
        context: Annotated[GuildContext, Depends(guard)],
    ) -> GuildContext:
        if SURFACE_CUSTOM_ROLES in context.closed_surfaces:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.COMMUNITY_SURFACE_CLOSED,
            )
        return context

    return dependency


RolesWriteContext = Annotated[GuildContext, Depends(_writes(AdminSurface.roles))]
MembersWriteContext = Annotated[GuildContext, Depends(_writes(AdminSurface.members))]


def _refused(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _require_gives(
    context: GuildContext, base_rung: CommunityRole, surfaces: set[AdminSurface]
) -> None:
    """The writer may make or give a role on ``base_rung`` holding
    ``surfaces``. A settings grant answers for the community it is lent."""
    if base_rung is CommunityRole.member and not surfaces <= MEMBER_ROLE_SURFACES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CustomRoleMessages.CUSTOM_ROLE_SURFACE_NOT_FOR_MEMBERS,
        )
    if context.settings_rung is not None:
        return
    if not all(context.holds_surface(s) for s in surfaces) or (
        base_rung is CommunityRole.admin and not context.is_admin
    ):
        raise _refused(CustomRoleMessages.CUSTOM_ROLE_BEYOND_YOURS)


def _require_takes_off(context: GuildContext, role: CustomRole) -> None:
    """The writer may take ``role`` off its holders: as giving it, and an
    admin's only while holding every surface, since it widens them."""
    rung = CommunityRole(role.base_rung)
    _require_gives(context, rung, {AdminSurface(s) for s in role.surfaces})
    if rung is CommunityRole.admin and not context.manages_admins:
        raise _refused(CustomRoleMessages.CUSTOM_ROLE_WIDENS_AN_ADMIN)


def _read(role: CustomRole) -> CustomRoleRead:
    return CustomRoleRead.model_validate(role, from_attributes=True)


async def _role_or_404(session, role_id: int) -> CustomRole:
    role = await custom_roles_service.get_role(session, role_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CustomRoleMessages.CUSTOM_ROLE_NOT_FOUND,
        )
    return role


async def _record(
    session, context: GuildContext, actor: int, role: CustomRole, action: str
) -> None:
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_CUSTOM_ROLE_CHANGED,
        actor_user_id=actor,
        guild_id=context.guild_id,
        target_type="custom_role",
        target_id=role.id,
        detail={
            "action": action,
            "name": role.name,
            "base_rung": role.base_rung,
            "surfaces": sorted(role.surfaces),
        },
    )


async def _commit_named(session) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CustomRoleMessages.CUSTOM_ROLE_NAME_TAKEN,
        ) from None


@router.get("/", response_model=List[CustomRoleRead])
async def list_custom_roles(
    session: RLSSessionDep, _context: GuildContextDep
) -> List[CustomRoleRead]:
    """The community's custom roles, for anybody in it: who holds what is
    shown beside each member."""
    return [_read(role) for role in await custom_roles_service.list_roles(session)]


@router.get("/held", response_model=HeldSurfacesRead)
async def read_held_surfaces(context: GuildContextDep) -> HeldSurfacesRead:
    """The admin surfaces the reader holds here: every one for an admin with
    no custom role, a role's otherwise, none for a member without one. What
    the community's settings pages are shown by."""
    return HeldSurfacesRead(
        surfaces=[s for s in AdminSurface if context.holds_surface(s)]
    )


@router.post("/", response_model=CustomRoleRead, status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    payload: CustomRoleCreate,
    session: SettingsRLSSessionDep,
    context: RolesWriteContext,
    current_user: CurrentUser,
) -> CustomRoleRead:
    surfaces = set(payload.surfaces)
    _require_gives(context, payload.base_rung, surfaces)
    role = CustomRole(
        name=payload.name,
        base_rung=payload.base_rung.value,
        surfaces=sorted(s.value for s in surfaces),
    )
    session.add(role)
    await session.flush()
    await _record(session, context, current_user.id, role, "created")
    await _commit_named(session)
    return _read(role)


@router.patch("/{role_id}", response_model=CustomRoleRead)
async def update_custom_role(
    role_id: int,
    payload: CustomRoleUpdate,
    session: SettingsRLSSessionDep,
    context: RolesWriteContext,
    current_user: CurrentUser,
) -> CustomRoleRead:
    """Rename a role, or change what it holds. Its rung stays the one it was
    made on."""
    role = await _role_or_404(session, role_id)
    rung = CommunityRole(role.base_rung)
    _require_gives(context, rung, {AdminSurface(s) for s in role.surfaces})
    if payload.name is not None:
        role.name = payload.name
    if payload.surfaces is not None:
        surfaces = set(payload.surfaces)
        _require_gives(context, rung, surfaces)
        role.surfaces = sorted(s.value for s in surfaces)
    session.add(role)
    await session.flush()
    await _record(session, context, current_user.id, role, "changed")
    await _commit_named(session)
    return _read(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_role(
    role_id: int,
    session: SettingsRLSSessionDep,
    context: RolesWriteContext,
    current_user: CurrentUser,
) -> Response:
    """Delete a role. Its holders stand on their plain rung again."""
    role = await _role_or_404(session, role_id)
    _require_takes_off(context, role)
    await _record(session, context, current_user.id, role, "deleted")
    await session.delete(role)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/holders", response_model=List[CustomRoleHolder])
async def list_custom_role_holders(
    session: RLSSessionDep, context: GuildContextDep
) -> List[CustomRoleHolder]:
    """Who holds which role, for anybody in the community."""
    return [
        CustomRoleHolder(user_id=user_id, role_id=role_id)
        for user_id, role_id in await custom_roles_service.holders(
            session, context.guild_id
        )
    ]


@router.put("/holders/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def assign_custom_role(
    user_id: int,
    payload: CustomRoleAssignment,
    session: SettingsRLSSessionDep,
    context: MembersWriteContext,
    current_user: CurrentUser,
) -> Response:
    """Give a member a custom role, in place of the one they hold, or take
    theirs off (``role_id`` null)."""
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == context.guild_id,
                GuildMembership.user_id == user_id,
            )
        )
    ).one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CustomRoleMessages.CUSTOM_ROLE_HOLDER_NOT_MEMBER,
        )
    held = await custom_roles_service.held_role(session, user_id)
    if held is not None:
        _require_takes_off(context, held)
    role = None
    if payload.role_id is not None:
        role = await _role_or_404(session, payload.role_id)
        _require_gives(
            context,
            CommunityRole(role.base_rung),
            {AdminSurface(s) for s in role.surfaces},
        )
    await custom_roles_service.assign(session, user_id=user_id, role_id=payload.role_id)
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_CUSTOM_ROLE_ASSIGNED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        guild_id=context.guild_id,
        target_type="custom_role",
        target_id=payload.role_id,
        detail={
            "from": held.name if held is not None else None,
            "to": role.name if role is not None else None,
        },
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
