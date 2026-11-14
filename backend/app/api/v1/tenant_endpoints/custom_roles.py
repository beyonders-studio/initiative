"""A community's custom roles: defining them (``roles``) and giving them
(``members``).

Each write is refused here with the reason, and by the policies on
``custom_roles`` and ``custom_role_members`` whatever the route says
(``app.db.guild_ddl``): nobody writes or gives a role holding a surface or a
plug-in permission they do not hold, a role on the admin rung takes an admin,
only a role on the admin rung keeps plug-in permissions, and taking one off an
admin takes somebody who holds every surface and plug-in permission. While the deployment has closed
``surface.custom_roles`` nothing here changes, and the roles the community has
keep applying. A role the deployment defined is given here and changed only by
billing's sync, and its name is the deployment's.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    CurrentUser,
    GuildContext,
    GuildContextDep,
    RLSSessionDep,
    SettingsContextDep,
    SettingsRLSSessionDep,
    require_surface,
)
from app.core.audit_events import AuditEventType
from app.core.messages import CustomRoleMessages, GuildMessages, GuildPluginMessages
from app.core.rules import SURFACE_CUSTOM_ROLES, SetBy
from app.models.platform.guild import (
    MEMBER_ROLE_SURFACES,
    AdminSurface,
    CommunityRole,
    GuildMembership,
)
from app.models.tenant.custom_role import CustomRole, CustomRolePluginPermission
from app.schemas.tenant.custom_role import (
    CustomRoleAssignment,
    CustomRoleCreate,
    CustomRoleHolder,
    CustomRoleRead,
    CustomRoleUpdate,
    HeldSurfacesRead,
    PluginPermissionRef,
)
from app.services import audit as audit_service
from app.services.tenant import custom_roles as custom_roles_service
from app.services.tenant import guild_plugins as guild_plugins_service

router = APIRouter()


def _writes(surface: AdminSurface) -> Callable[..., Awaitable[GuildContext]]:
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


#: The plug-ins' community permissions a role keeps, as ``(install id,
#: permission id)``.
Kept = frozenset[tuple[int, str]]


def _require_gives(
    context: GuildContext,
    base_rung: CommunityRole,
    surfaces: set[AdminSurface],
    kept: Kept = frozenset(),
) -> None:
    """The writer may make or give a role on ``base_rung`` holding
    ``surfaces`` and keeping ``kept``. A settings grant answers for the
    community it is lent."""
    if base_rung is CommunityRole.member and (
        not surfaces <= MEMBER_ROLE_SURFACES or kept
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CustomRoleMessages.CUSTOM_ROLE_SURFACE_NOT_FOR_MEMBERS,
        )
    if context.settings_rung is not None:
        return
    if (
        not all(context.holds_surface(s) for s in surfaces)
        or not all(
            context.holds_plugin_permission(install_id, permission, initiative_id=None)
            for install_id, permission in kept
        )
        or (base_rung is CommunityRole.admin and not context.is_admin)
    ):
        raise _refused(CustomRoleMessages.CUSTOM_ROLE_BEYOND_YOURS)


async def _kept(session: AsyncSession, *role_ids: int) -> dict[int, Kept]:
    """What each of these roles keeps of the plug-ins' permissions."""
    rows = await session.exec(
        select(CustomRolePluginPermission).where(
            col(CustomRolePluginPermission.role_id).in_(role_ids)
        )
    )
    kept: dict[int, set[tuple[int, str]]] = {role_id: set() for role_id in role_ids}
    for row in rows.all():
        kept[row.role_id].add((row.install_id, row.permission))
    return {role_id: frozenset(pairs) for role_id, pairs in kept.items()}


async def _require_gives_role(
    session: AsyncSession, context: GuildContext, role: CustomRole
) -> Kept:
    """:func:`_require_gives` for a role as it stands; answers what it keeps."""
    kept = (await _kept(session, int(role.id or 0)))[int(role.id or 0)]
    _require_gives(
        context,
        CommunityRole(role.base_rung),
        {AdminSurface(s) for s in role.surfaces},
        kept,
    )
    return kept


async def _require_takes_off(
    session: AsyncSession, context: GuildContext, role: CustomRole
) -> None:
    """The writer may take ``role`` off its holders: as giving it, and an
    admin's only while holding everything the admin rung holds, since it
    widens them to all of it."""
    await _require_gives_role(session, context, role)
    if (
        CommunityRole(role.base_rung) is CommunityRole.admin
        and not context.manages_admins
    ):
        raise _refused(CustomRoleMessages.CUSTOM_ROLE_WIDENS_AN_ADMIN)


async def _requested(session: AsyncSession, refs: list[PluginPermissionRef]) -> Kept:
    """The plug-in permissions a request names, each a community permission
    an installed plug-in declares."""
    wanted = frozenset((ref.install_id, ref.permission) for ref in refs)
    if wanted - await guild_plugins_service.declared_permission_ids(
        session, "community"
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.PERMISSION_UNKNOWN,
        )
    return wanted


async def _keep(
    session: AsyncSession, role: CustomRole, before: Kept, after: Kept
) -> None:
    """Make the role keep ``after`` in place of ``before``."""
    for install_id, permission in before - after:
        await session.exec(
            delete(CustomRolePluginPermission).where(
                CustomRolePluginPermission.role_id == role.id,
                CustomRolePluginPermission.install_id == install_id,
                CustomRolePluginPermission.permission == permission,
            )
        )
    for install_id, permission in sorted(after - before):
        session.add(
            CustomRolePluginPermission(
                role_id=int(role.id or 0), install_id=install_id, permission=permission
            )
        )
    await session.flush()


def _read(role: CustomRole, kept: Kept) -> CustomRoleRead:
    return CustomRoleRead.model_validate(role, from_attributes=True).model_copy(
        update={
            "plugin_permissions": [
                PluginPermissionRef(install_id=install_id, permission=permission)
                for install_id, permission in sorted(kept)
            ]
        }
    )


async def _role_or_404(session: AsyncSession, role_id: int) -> CustomRole:
    role = await custom_roles_service.get_role(session, role_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CustomRoleMessages.CUSTOM_ROLE_NOT_FOUND,
        )
    return role


async def _communitys_role(session: AsyncSession, role_id: int) -> CustomRole:
    """A role the community defined, which it may change or delete."""
    role = await _role_or_404(session, role_id)
    if role.set_by == SetBy.deployment.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CustomRoleMessages.CUSTOM_ROLE_SET_BY_DEPLOYMENT,
        )
    return role


async def _require_free(session: AsyncSession, name: str) -> None:
    """``name`` is not one the deployment's roles have."""
    if await custom_roles_service.reserved(session, name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CustomRoleMessages.CUSTOM_ROLE_NAME_RESERVED,
        )


async def _record(
    session: AsyncSession,
    context: GuildContext,
    actor: int,
    role: CustomRole,
    action: str,
    kept: Kept = frozenset(),
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
            "plugin_permissions": [f"{i}:{p}" for i, p in sorted(kept)],
        },
    )


async def _flush_named(session: AsyncSession) -> None:
    """Write the role, answering a name another role has with a conflict."""
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CustomRoleMessages.CUSTOM_ROLE_NAME_TAKEN,
        ) from None


@router.get("/", response_model=list[CustomRoleRead])
async def list_custom_roles(
    session: RLSSessionDep, _context: GuildContextDep
) -> list[CustomRoleRead]:
    """The community's custom roles, for anybody in it: who holds what is
    shown beside each member."""
    roles = await custom_roles_service.list_roles(session)
    kept = await _kept(session, *(int(role.id or 0) for role in roles))
    return [_read(role, kept[int(role.id or 0)]) for role in roles]


@router.get("/held", response_model=HeldSurfacesRead)
async def read_held_surfaces(
    session: SettingsRLSSessionDep, context: SettingsContextDep
) -> HeldSurfacesRead:
    """The admin surfaces and the plug-ins' community permissions the reader
    holds here: every one for an admin with no custom role, a role's
    otherwise, none for a member without one. What the community's settings
    pages are shown by, and a role's editor offers."""
    return HeldSurfacesRead(
        surfaces=[s for s in AdminSurface if context.holds_surface(s)],
        plugin_permissions=[
            PluginPermissionRef(install_id=install_id, permission=permission)
            for install_id, permission in sorted(
                await guild_plugins_service.declared_permission_ids(
                    session, "community"
                )
            )
            if context.holds_plugin_permission(
                install_id, permission, initiative_id=None
            )
        ],
    )


@router.post("/", response_model=CustomRoleRead, status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    payload: CustomRoleCreate,
    session: SettingsRLSSessionDep,
    context: RolesWriteContext,
    current_user: CurrentUser,
) -> CustomRoleRead:
    surfaces = set(payload.surfaces)
    kept = await _requested(session, payload.plugin_permissions)
    _require_gives(context, payload.base_rung, surfaces, kept)
    await _require_free(session, payload.name)
    role = CustomRole(
        name=payload.name,
        base_rung=payload.base_rung.value,
        surfaces=sorted(s.value for s in surfaces),
    )
    session.add(role)
    await _flush_named(session)
    await _keep(session, role, frozenset(), kept)
    await _record(session, context, current_user.id, role, "created", kept)
    await session.commit()
    return _read(role, kept)


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
    role = await _communitys_role(session, role_id)
    rung = CommunityRole(role.base_rung)
    before = kept = await _require_gives_role(session, context, role)
    if payload.name is not None:
        await _require_free(session, payload.name)
        role.name = payload.name
    surfaces = {AdminSurface(s) for s in role.surfaces}
    if payload.surfaces is not None:
        surfaces = set(payload.surfaces)
    if payload.plugin_permissions is not None:
        kept = await _requested(session, payload.plugin_permissions)
    _require_gives(context, rung, surfaces, kept)
    role.surfaces = sorted(s.value for s in surfaces)
    session.add(role)
    await _flush_named(session)
    await _keep(session, role, before, kept)
    await _record(session, context, current_user.id, role, "changed", kept)
    await session.commit()
    return _read(role, kept)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_role(
    role_id: int,
    session: SettingsRLSSessionDep,
    context: RolesWriteContext,
    current_user: CurrentUser,
) -> Response:
    """Delete a role. Its holders stand on their plain rung again."""
    role = await _communitys_role(session, role_id)
    await _require_takes_off(session, context, role)
    await _record(session, context, current_user.id, role, "deleted")
    await session.delete(role)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/holders", response_model=list[CustomRoleHolder])
async def list_custom_role_holders(
    session: RLSSessionDep, context: GuildContextDep
) -> list[CustomRoleHolder]:
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
        await _require_takes_off(session, context, held)
    role = None
    if payload.role_id is not None:
        role = await _role_or_404(session, payload.role_id)
        await _require_gives_role(session, context, role)
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
