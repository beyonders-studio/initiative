"""What a community makes of the groups its provider asserts.

The other half of a connection. A connection says which arrivals count as this
community's; a rule says where one of them lands — as a member or an admin of
the community, and in an initiative if the community says so. Both are one
sentence a community says in one breath: *our people come in through this, and
these of them belong here.*

The rows are ``oidc_claim_mappings``, named by ``guild_id``. A community reads
and writes only the ones naming it, and this surface is the only one that
writes them; the sign-in that evaluates them reads every rule for the provider
it came through.

Which claim carries groups stays the operator's, per provider
(``auth_providers.role_claim_path``) — it is a fact about the provider, not a
decision about a community, and a community that has to know it would be
configuring somebody else's provider.
"""

import logging

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import AuthProviderMessages, SettingsMessages
from app.db.session import set_rls_context
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild import GUILD_ASSIGNABLE_ROLES, Guild
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.models.platform.oidc_claim_mapping import (
    ClaimRuleAuthor,
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.models.tenant.initiative import Initiative, InitiativeRoleModel
from app.schemas.platform.settings import (
    PlacementInitiativeRead,
    PlacementInitiativeRoleRead,
    ProviderPlacementRuleRead,
    CommunityClaimRuleCreate,
    CommunityClaimRuleRead,
    CommunityClaimRulesResponse,
)
from app.services import audit as audit_service
from app.services.platform import provider_placement
from app.db.request_context import SystemGuild, Unattributed

logger = logging.getLogger(__name__)

#: The standings a rule may hand out, from the one set that says so — a group
#: grants an ordinary standing, never the seat that decides who may enter.
MAPPABLE_GUILD_ROLES: frozenset[str] = frozenset(
    role.value for role in GUILD_ASSIGNABLE_ROLES
)

#: What a rule places somebody by, for the record.
AUDITED_FIELDS: tuple[str, ...] = (
    "provider_id",
    "claim_value",
    "target_type",
    "guild_role",
    "initiative_id",
    "initiative_role_id",
)


async def reset_to_system_baseline(session: AsyncSession) -> None:
    """Return the system session to its neutral public / login-role baseline.

    After routing into a guild schema the session has assumed that guild's
    role, which has no write access to shared ``public`` config tables. Reset
    to the system login role before writing a rule back to ``public``.
    """
    await set_rls_context(session, Unattributed())


async def lookup_guild_initiative(
    session: AsyncSession,
    guild_id: int,
    initiative_id: int,
    initiative_role_id: int | None,
) -> tuple[Initiative | None, InitiativeRoleModel | None]:
    """Look up an initiative (and optional role) inside a guild's schema.

    Routes the session into ``guild_<id>`` for the read, then resets it.
    ``populate_existing`` keeps a colliding id from another guild
    already in the identity map from being returned stale — ids are unique only
    within a schema.
    """
    await set_rls_context(session, SystemGuild(guild_id))
    try:
        initiative = (
            await session.exec(
                select(Initiative)
                .where(Initiative.id == initiative_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        role: InitiativeRoleModel | None = None
        if initiative_role_id is not None:
            role = (
                await session.exec(
                    select(InitiativeRoleModel)
                    .where(InitiativeRoleModel.id == initiative_role_id)
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        return initiative, role
    finally:
        await reset_to_system_baseline(session)


async def connected_provider(
    session: AsyncSession, *, guild_id: int, provider_id: int
) -> AuthProvider:
    """The provider behind one of this community's connections.

    This is the tie between the two halves: a community says what a group
    means only for a provider it already counts as its own.
    """
    row = (
        await session.exec(
            select(AuthProvider)
            .join(
                GuildProviderConnection,
                GuildProviderConnection.provider_id == AuthProvider.id,
            )
            .where(
                GuildProviderConnection.guild_id == guild_id,
                GuildProviderConnection.provider_id == provider_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthProviderMessages.RULE_PROVIDER_NOT_CONNECTED,
        )
    return row


async def _editable_rule(
    session: AsyncSession, rule_id: int, *, guild_id: int
) -> OIDCClaimMapping:
    """This community's rule for one id, or a 404. One naming another
    community is indistinguishable from one that is not there."""
    row = (
        await session.exec(
            select(OIDCClaimMapping).where(
                OIDCClaimMapping.id == rule_id,
                OIDCClaimMapping.guild_id == guild_id,
                OIDCClaimMapping.author == ClaimRuleAuthor.community,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.RULE_NOT_FOUND,
        )
    return row


async def _resolve_destination(
    session: AsyncSession,
    *,
    guild_id: int,
    initiative_id: int | None,
    initiative_role_id: int | None,
) -> OIDCMappingTargetType:
    """Check an initiative destination and say which kind of rule results.

    Naming neither lands somebody in the community alone. Naming an initiative
    needs the role to go with it, and both have to be that community's own.
    """
    if initiative_id is None and initiative_role_id is None:
        return OIDCMappingTargetType.guild
    if initiative_id is None or initiative_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.INITIATIVE_FIELDS_REQUIRED,
        )
    initiative, role = await lookup_guild_initiative(
        session, guild_id, initiative_id, initiative_role_id
    )
    if initiative is None or role is None or role.initiative_id != initiative_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.INITIATIVE_WRONG_GUILD,
        )
    return OIDCMappingTargetType.initiative


def _require_mappable_role(guild_role: str) -> None:
    if guild_role not in MAPPABLE_GUILD_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.INVALID_GUILD_ROLE,
        )


async def _require_unique(
    session: AsyncSession,
    *,
    guild_id: int,
    provider_id: int,
    claim_value: str,
    initiative_id: int | None,
) -> None:
    stmt = select(OIDCClaimMapping.id).where(
        OIDCClaimMapping.author == ClaimRuleAuthor.community,
        OIDCClaimMapping.guild_id == guild_id,
        OIDCClaimMapping.provider_id == provider_id,
        OIDCClaimMapping.claim_value == claim_value,
    )
    if initiative_id is None:
        stmt = stmt.where(OIDCClaimMapping.initiative_id.is_(None))
    else:
        stmt = stmt.where(OIDCClaimMapping.initiative_id == initiative_id)
    if (await session.exec(stmt.limit(1))).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.RULE_EXISTS,
        )


async def _rule_read(
    session: AsyncSession, row: OIDCClaimMapping, *, providers: dict[int, AuthProvider]
) -> CommunityClaimRuleRead:
    initiative_name = None
    initiative_role_name = None
    if row.initiative_id is not None:
        initiative, role = await lookup_guild_initiative(
            session, row.guild_id, row.initiative_id, row.initiative_role_id
        )
        if initiative is not None:
            initiative_name = initiative.name
        if role is not None:
            initiative_role_name = role.display_name
    provider = providers.get(row.provider_id)
    return CommunityClaimRuleRead(
        id=row.id,
        provider_id=row.provider_id,
        provider_display_name=provider.display_name if provider else "",
        provider_icon=provider.icon if provider else None,
        claim_value=row.claim_value or "",
        community_role=row.guild_role,
        initiative_id=row.initiative_id,
        initiative_name=initiative_name,
        initiative_role_id=row.initiative_role_id,
        initiative_role_name=initiative_role_name,
    )


async def list_rules(
    session: AsyncSession, *, guild_id: int
) -> CommunityClaimRulesResponse:
    """This community's rules, newest last, with the providers named."""
    connected = (
        await session.exec(
            select(AuthProvider)
            .join(
                GuildProviderConnection,
                GuildProviderConnection.provider_id == AuthProvider.id,
            )
            .where(GuildProviderConnection.guild_id == guild_id)
        )
    ).all()
    providers = {row.id: row for row in connected if row.id is not None}
    rows = (
        await session.exec(
            select(OIDCClaimMapping)
            .where(OIDCClaimMapping.guild_id == guild_id)
            .order_by(OIDCClaimMapping.id)
        )
    ).all()
    own = [row for row in rows if row.author == ClaimRuleAuthor.community]
    return CommunityClaimRulesResponse(
        rules=[await _rule_read(session, row, providers=providers) for row in own],
        reporting_provider_ids=sorted(
            pid for pid, row in providers.items() if row.role_claim_path
        ),
        provider_rules=await _provider_rules_here(
            session,
            guild_id=guild_id,
            rows=[row for row in rows if row.author == ClaimRuleAuthor.provider],
        ),
        placement_everywhere=await provider_placement.placement_everywhere(session),
    )


async def _provider_rules_here(
    session: AsyncSession, *, guild_id: int, rows: list[OIDCClaimMapping]
) -> list[ProviderPlacementRuleRead]:
    """The platform's rules naming this community, as it sees them: which
    provider, what they match, where they land, and whether they apply."""
    if not rows:
        return []
    guild = await session.get(Guild, guild_id)
    reads: list[ProviderPlacementRuleRead] = []
    for row in rows:
        provider = await session.get(AuthProvider, row.provider_id)
        applies = guild_id in await provider_placement.placeable_communities(
            session, provider_id=row.provider_id, guild_ids={guild_id}
        )
        initiatives: list[PlacementInitiativeRead] = []
        if row.initiative_id is not None:
            initiative, role = await lookup_guild_initiative(
                session, guild_id, row.initiative_id, row.initiative_role_id
            )
            if initiative is not None and initiative.id is not None:
                initiatives = [
                    PlacementInitiativeRead(
                        id=initiative.id,
                        name=initiative.name,
                        roles=[
                            PlacementInitiativeRoleRead(
                                id=role.id,
                                name=role.display_name,
                                is_manager=role.is_manager,
                            )
                        ]
                        if role is not None and role.id is not None
                        else [],
                    )
                ]
        reads.append(
            provider_placement.rule_read(
                row,
                provider=provider,
                guild_name=guild.name if guild else "",
                applies=applies,
                initiatives=initiatives,
            )
        )
    return reads


async def create_rule(
    session: AsyncSession,
    *,
    guild_id: int,
    payload: CommunityClaimRuleCreate,
    actor_user_id: int | None = None,
) -> CommunityClaimRuleRead:
    provider = await connected_provider(
        session, guild_id=guild_id, provider_id=payload.provider_id
    )
    _require_mappable_role(payload.community_role)
    claim_value = payload.claim_value.strip()
    target_type = await _resolve_destination(
        session,
        guild_id=guild_id,
        initiative_id=payload.initiative_id,
        initiative_role_id=payload.initiative_role_id,
    )
    await _require_unique(
        session,
        guild_id=guild_id,
        provider_id=payload.provider_id,
        claim_value=claim_value,
        initiative_id=payload.initiative_id,
    )
    row = OIDCClaimMapping(
        provider_id=payload.provider_id,
        claim_value=claim_value,
        target_type=target_type,
        guild_id=guild_id,
        guild_role=payload.community_role,
        initiative_id=payload.initiative_id,
        initiative_role_id=payload.initiative_role_id,
    )
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.CLAIM_RULE_CREATED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="claim_rule",
        target_id=row.id,
        detail={
            "via": "guild",
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_FIELDS)
            ),
        },
    )
    await session.commit()
    await session.refresh(row)
    return await _rule_read(session, row, providers={provider.id: provider})


async def delete_rule(
    session: AsyncSession,
    *,
    guild_id: int,
    rule_id: int,
    actor_user_id: int | None = None,
) -> None:
    """Stop placing the people carrying one group.

    The memberships it already granted stay. A rule is how somebody arrives,
    not a lease on their standing, and the next sign-in through that provider
    reconciles what its rules say now.
    """
    row = await _editable_rule(session, rule_id, guild_id=guild_id)
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.CLAIM_RULE_DELETED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="claim_rule",
        target_id=rule_id,
        detail={"via": "guild"},
    )
    await session.commit()
