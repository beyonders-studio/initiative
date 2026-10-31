"""What a community makes of the groups its provider asserts.

The other half of a connection. A connection says which arrivals count as this
community's; a rule says where one of them lands — as a member or an admin of
the community, and in an initiative if the community says so. Both are one
sentence a community says in one breath: *our people come in through this, and
these of them belong here.*

The rows are ``oidc_claim_mappings``, named by ``guild_id``. A community reads
and writes only the ones naming it, and this surface is the only one that
writes them; the sign-in that evaluates them reads every rule for the provider
it came through. The initiative a rule names is the community's own, kept in
its schema under the rule's id (``claim_rule_initiatives``).

Which claim carries groups stays the operator's, per provider
(``auth_providers.role_claim_path``) — it is a fact about the provider, not a
decision about a community, and a community that has to know it would be
configuring somebody else's provider.
"""

import logging
from dataclasses import asdict

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import AuthProviderMessages, SettingsMessages
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild import GUILD_ASSIGNABLE_ROLES, Guild
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.models.platform.oidc_claim_mapping import (
    ClaimRuleAuthor,
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.schemas.platform.settings import (
    ProviderPlacementRuleRead,
    CommunityClaimRuleCreate,
    CommunityClaimRuleRead,
    CommunityClaimRulesResponse,
)
from app.services import audit as audit_service
from app.services.platform import provider_placement

logger = logging.getLogger(__name__)

#: The standings a rule may hand out, from the one set that says so — a group
#: grants an ordinary standing, never the seat that decides who may enter.
MAPPABLE_GUILD_ROLES: frozenset[str] = frozenset(
    role.value for role in GUILD_ASSIGNABLE_ROLES
)

#: What a rule places somebody by, for the record, besides its initiative
#: (:func:`~app.services.platform.provider_placement.audited`).
AUDITED_FIELDS: tuple[str, ...] = (
    "provider_id",
    "claim_value",
    "target_type",
    "guild_role",
)


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


def _require_mappable_role(guild_role: str) -> None:
    if guild_role not in MAPPABLE_GUILD_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.INVALID_GUILD_ROLE,
        )


def _rule_read(
    row: OIDCClaimMapping,
    *,
    providers: dict[int, AuthProvider],
    initiative: provider_placement.RuleInitiative | None,
) -> CommunityClaimRuleRead:
    provider = providers.get(row.provider_id)
    return CommunityClaimRuleRead(
        id=row.id,
        provider_id=row.provider_id,
        provider_display_name=provider.display_name if provider else "",
        provider_icon=provider.icon if provider else None,
        claim_value=row.claim_value or "",
        community_role=row.guild_role,
        **(asdict(initiative) if initiative else {}),
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
    initiatives = await provider_placement.rule_initiatives(
        guild_id,
        [
            row.id
            for row in rows
            if row.target_type == OIDCMappingTargetType.initiative
            and row.id is not None
        ],
    )
    return CommunityClaimRulesResponse(
        rules=[
            _rule_read(
                row,
                providers=providers,
                initiative=initiatives.get(row.id) if row.id is not None else None,
            )
            for row in rows
            if row.author == ClaimRuleAuthor.community
        ],
        reporting_provider_ids=sorted(
            pid for pid, row in providers.items() if row.role_claim_path
        ),
        provider_rules=await _provider_rules_here(
            session,
            guild_id=guild_id,
            rows=[row for row in rows if row.author == ClaimRuleAuthor.provider],
            initiatives=initiatives,
        ),
        placement_everywhere=await provider_placement.placement_everywhere(session),
    )


async def _provider_rules_here(
    session: AsyncSession,
    *,
    guild_id: int,
    rows: list[OIDCClaimMapping],
    initiatives: dict[int, provider_placement.RuleInitiative],
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
        reads.append(
            provider_placement.rule_read(
                row,
                provider=provider,
                guild_name=guild.name if guild else "",
                applies=applies,
                initiative=initiatives.get(row.id) if row.id is not None else None,
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
    row = OIDCClaimMapping(
        provider_id=payload.provider_id,
        claim_value=payload.claim_value.strip(),
        target_type=provider_placement.destination_type(
            payload.initiative_id, payload.initiative_role_id
        ),
        guild_id=guild_id,
        guild_role=payload.community_role,
    )
    initiative = await provider_placement.place_rule(
        session,
        row,
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
                {}, provider_placement.audited(row, AUDITED_FIELDS, initiative)
            ),
        },
    )
    await session.commit()
    await session.refresh(row)
    return _rule_read(row, providers={provider.id: provider}, initiative=initiative)


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
    placed = row.target_type == OIDCMappingTargetType.initiative
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
    if placed:
        await provider_placement.drop_rule_initiative(guild_id, rule_id)
