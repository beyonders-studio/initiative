"""Which of the platform's providers a community signs its members in through.

Managed here: a community's ``guild_provider_connections`` rows, and the rules
riding them. A community does not register a provider — the operator holds
every one of those — so nothing on this surface takes an issuer, a client id or
a secret. What it takes is which provider, the claim that narrows it to this
community's own tenant, and where the groups that provider asserts land.

Those are one sentence said in one breath, which is why they share a router and
a gate: *our people come in through this, and these of them belong here.*

Exists only where the operator has granted the community that option (404
otherwise, like the rest of the guild auth surface).

Reading is a guild admin's; changing is the superadmin's, the seat that
holds a community's sign-in configuration.

Reading runs on the request-path session; changing runs on the seat's, which
is routed into ``guild_<id>_superadmin``. The connections themselves are read
and written on the system engine (``guild_provider_connections`` and
``auth_providers`` carry no request-path grants).
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    CommunityIdPath,
    SeatSessionDep,
    SeatWriteSessionDep,
    get_guild_seat_write_session,
    require_surface_open,
    GuildContext,
    require_surface,
    get_current_active_user,
    SystemSessionDep,
)
from app.core.audit_events import AuditEventType
from app.core.guild_auth_options import CommunityAuthOption
from app.core.messages import AuthProviderMessages, CustomRoleMessages
from app.core.rules import SURFACE_CUSTOM_ROLES
from app.models.tenant.custom_role import CustomRole, CustomRoleClaimRule
from app.models.platform.guild import AdminSurface
from app.models.platform.user import User
from app.schemas.platform.settings import (
    ConnectableProviderRead,
    CommunityClaimRuleCreate,
    CommunityClaimRuleRead,
    CommunityClaimRulesResponse,
    CommunityProviderConnectionCreate,
    CommunityProviderConnectionRead,
    CommunityProviderConnectionUpdate,
)
from app.schemas.tenant.custom_role import (
    CustomRoleClaimRuleCreate,
    CustomRoleClaimRuleOrder,
    CustomRoleClaimRuleRead,
)
from app.services import audit as audit_service
from app.services.auth import guild_claim_rules as claim_rules
from app.services.auth import guild_provider_connections as connections
from app.services.platform import guild_entitlements
from app.services.platform import guilds as guilds_service
from app.services.tenant import custom_roles as custom_roles_service

#: How people sign in to join is read by whoever administers the roster;
#: changing it is the seat's.
MembersContext = Annotated[
    GuildContext, Depends(require_surface(AdminSurface.members, settings=True))
]

router = APIRouter()
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


async def _require_connection_option(
    system_session: AsyncSession, guild_id: int
) -> None:
    """Changing it: the operator's grant of the option. The seat itself is
    :data:`~app.api.deps.SeatWriteSessionDep`, which routed the request here — who
    may enter a community is that seat's to decide."""
    await guild_entitlements.require_auth_option(
        system_session, guild_id, CommunityAuthOption.providers
    )


@router.get(
    "/{community_id}/auth/connections",
    response_model=List[CommunityProviderConnectionRead],
)
async def list_community_provider_connections(
    guild_id: CommunityIdPath,
    _guild_context: MembersContext,
    system_session: SystemSessionDep,
) -> List[CommunityProviderConnectionRead]:
    await guild_entitlements.require_auth_option(
        system_session, guild_id, CommunityAuthOption.providers
    )
    return await connections.list_connections(system_session, guild_id=guild_id)


@router.get(
    "/{community_id}/auth/connections/available",
    response_model=List[ConnectableProviderRead],
)
async def list_connectable_providers(
    guild_id: CommunityIdPath,
    _guild_context: MembersContext,
    system_session: SystemSessionDep,
) -> List[ConnectableProviderRead]:
    """The providers this community may choose from: the ones on offer, plus
    the ones it already connects to. Names only — a community picks a provider
    by name, and one registered for a single customer is nobody else's to
    see."""
    await guild_entitlements.require_auth_option(
        system_session, guild_id, CommunityAuthOption.providers
    )
    return await connections.list_connectable(system_session, guild_id=guild_id)


@router.post(
    "/{community_id}/auth/connections",
    response_model=CommunityProviderConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_community_provider_connection(
    guild_id: CommunityIdPath,
    payload: CommunityProviderConnectionCreate,
    _session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> CommunityProviderConnectionRead:
    await _require_connection_option(system_session, guild_id)
    return await connections.create_connection(
        system_session, payload, guild_id=guild_id, actor_user_id=current_user.id
    )


@router.patch(
    "/{community_id}/auth/connections/{connection_id}",
    response_model=CommunityProviderConnectionRead,
)
async def update_community_provider_connection(
    guild_id: CommunityIdPath,
    connection_id: int,
    payload: CommunityProviderConnectionUpdate,
    session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> CommunityProviderConnectionRead:
    await _require_connection_option(system_session, guild_id)
    if payload.enabled is False:
        await guilds_service.lock_guild_seats(session, guild_id)
    return await connections.update_connection(
        system_session,
        connection_id,
        payload,
        guild_id=guild_id,
        actor_user_id=current_user.id,
    )


@router.delete(
    "/{community_id}/auth/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_community_provider_connection(
    guild_id: CommunityIdPath,
    connection_id: int,
    session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Disconnect. Nobody is signed out and no account changes — what goes is
    the button on this community's sign-in page, and its claim on who arrives
    through that provider. Lift any sign-in requirement that depends on this
    connection first: the gate reads the connections, so a requirement without
    one has nothing left to satisfy it."""
    await _require_connection_option(system_session, guild_id)
    # Setting a requirement takes the same lock. Whichever wins commits before
    # the other checks, so a provider cannot become required while its
    # connection is being removed through the separate system session.
    await guilds_service.lock_guild_seats(session, guild_id)
    await connections.delete_connection(
        system_session, connection_id, guild_id=guild_id, actor_user_id=current_user.id
    )


@router.get("/{community_id}/auth/rules", response_model=CommunityClaimRulesResponse)
async def list_community_claim_rules(
    guild_id: CommunityIdPath,
    _guild_context: MembersContext,
    system_session: SystemSessionDep,
) -> CommunityClaimRulesResponse:
    """Where this community places the people its providers vouch for."""
    await guild_entitlements.require_auth_option(
        system_session, guild_id, CommunityAuthOption.providers
    )
    return await claim_rules.list_rules(system_session, guild_id=guild_id)


@router.post(
    "/{community_id}/auth/rules",
    response_model=CommunityClaimRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_community_claim_rule(
    guild_id: CommunityIdPath,
    payload: CommunityClaimRuleCreate,
    _session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> CommunityClaimRuleRead:
    """Place the people carrying one group. The rule reads a provider this
    community already counts as its own — saying what a group means is the
    same sentence as saying whose people arrive through it."""
    await _require_connection_option(system_session, guild_id)
    return await claim_rules.create_rule(
        system_session,
        guild_id=guild_id,
        payload=payload,
        actor_user_id=current_user.id,
    )


@router.delete(
    "/{community_id}/auth/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_community_claim_rule(
    guild_id: CommunityIdPath,
    rule_id: int,
    _session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Stop placing the people carrying one group. Nobody loses a standing
    they already hold until their next sign-in through that provider, which
    reconciles against the rules as they stand then."""
    await _require_connection_option(system_session, guild_id)
    await claim_rules.delete_rule(
        system_session,
        guild_id=guild_id,
        rule_id=rule_id,
        actor_user_id=current_user.id,
    )


#: Changing which custom role a group gives, which the deployment may close
#: for one community with the rest of its custom roles.
_ROLE_RULES_OPEN = Depends(
    require_surface_open(SURFACE_CUSTOM_ROLES, get_guild_seat_write_session)
)


def _role_rule_read(rule: CustomRoleClaimRule) -> CustomRoleClaimRuleRead:
    return CustomRoleClaimRuleRead.model_validate(rule, from_attributes=True)


@router.get(
    "/{community_id}/auth/role-rules",
    response_model=List[CustomRoleClaimRuleRead],
)
async def list_custom_role_claim_rules(
    guild_id: CommunityIdPath,
    session: SeatSessionDep,
    system_session: SystemSessionDep,
) -> List[CustomRoleClaimRuleRead]:
    """Which custom role each group gives, in the order a sign-in reads them:
    the first rule whose group it carries decides. Kept in the community's own
    schema, beside the roles they name."""
    await _require_connection_option(system_session, guild_id)
    return [
        _role_rule_read(rule)
        for rule in await custom_roles_service.claim_rules(session)
    ]


@router.post(
    "/{community_id}/auth/role-rules",
    response_model=CustomRoleClaimRuleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_ROLE_RULES_OPEN],
)
async def create_custom_role_claim_rule(
    guild_id: CommunityIdPath,
    payload: CustomRoleClaimRuleCreate,
    session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> CustomRoleClaimRuleRead:
    """Give a custom role to whoever signs in through one of the community's
    providers carrying a group, after every rule already there."""
    await _require_connection_option(system_session, guild_id)
    await claim_rules.connected_provider(
        system_session, guild_id=guild_id, provider_id=payload.provider_id
    )
    if await session.get(CustomRole, payload.role_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CustomRoleMessages.CUSTOM_ROLE_NOT_FOUND,
        )
    try:
        rule = await custom_roles_service.add_claim_rule(
            session,
            provider_id=payload.provider_id,
            claim_value=payload.claim_value.strip(),
            role_id=payload.role_id,
        )
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.RULE_EXISTS,
        ) from None
    await audit_service.record(
        session,
        event_type=AuditEventType.CLAIM_RULE_CREATED,
        actor_user_id=current_user.id,
        guild_id=guild_id,
        target_type="custom_role_claim_rule",
        target_id=rule.id,
        detail={
            "provider_id": rule.provider_id,
            "claim_value": rule.claim_value,
            "role_id": rule.role_id,
        },
    )
    await session.commit()
    return _role_rule_read(rule)


@router.put(
    "/{community_id}/auth/role-rules/order",
    response_model=List[CustomRoleClaimRuleRead],
    dependencies=[_ROLE_RULES_OPEN],
)
async def order_custom_role_claim_rules(
    guild_id: CommunityIdPath,
    payload: CustomRoleClaimRuleOrder,
    session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> List[CustomRoleClaimRuleRead]:
    """Put the rules in a new order; it names every rule once."""
    await _require_connection_option(system_session, guild_id)
    if not await custom_roles_service.order_claim_rules(session, payload.rule_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthProviderMessages.RULE_NOT_FOUND,
        )
    await audit_service.record(
        session,
        event_type=AuditEventType.CLAIM_RULE_UPDATED,
        actor_user_id=current_user.id,
        guild_id=guild_id,
        target_type="custom_role_claim_rule",
        detail={"order": payload.rule_ids},
    )
    await session.commit()
    return [
        _role_rule_read(rule)
        for rule in await custom_roles_service.claim_rules(session)
    ]


@router.delete(
    "/{community_id}/auth/role-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_ROLE_RULES_OPEN],
)
async def delete_custom_role_claim_rule(
    guild_id: CommunityIdPath,
    rule_id: int,
    session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUserDep,
) -> Response:
    """Stop giving a role for a group. Whoever holds it by this rule keeps it
    until their next sign-in through that provider."""
    await _require_connection_option(system_session, guild_id)
    rule = await session.get(CustomRoleClaimRule, rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.RULE_NOT_FOUND,
        )
    await audit_service.record(
        session,
        event_type=AuditEventType.CLAIM_RULE_DELETED,
        actor_user_id=current_user.id,
        guild_id=guild_id,
        target_type="custom_role_claim_rule",
        target_id=rule.id,
        detail={"claim_value": rule.claim_value, "role_id": rule.role_id},
    )
    await session.delete(rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
