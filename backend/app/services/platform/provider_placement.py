"""The platform's placement rules: a provider's own answer to where its
arrivals land.

A community writes rules for itself (``app.services.auth.guild_claim_rules``).
The platform writes these, on a provider, for whichever community they name:
*on this provider, group ``eng`` lands in Engineering as a member*. Both kinds
are rows of ``oidc_claim_mappings``, told apart by ``author``, and the sign-in
sync reads them together.

A provider rule places people in a community when that community accepts the
provider's rules on its connection, or when the deployment applies them to
every community (the rule ``provider_placement_everywhere``, recorded on
every change). Rules for a community that does neither are kept and shown, and
place nobody.

A provider rule may also name a directory — a verified claim and value, such
as the upstream a bridge stamps on its tokens — so a provider that signs in
people from several directories can say which one a rule is about. A rule
naming a directory and no group places everybody arriving from it.

Initiatives and their roles are read from the community's own schema, one
community at a time and only for a community the rule may place into, by
:func:`_initiatives_in`. The initiative a rule of either kind places into is
kept there too, under the rule's id and the version the rule names
(``claim_rule_initiatives``), written by :func:`set_rule_initiative` and read
by :func:`rule_initiatives`.
"""

import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import asdict, dataclass

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, exists, func, or_, tuple_
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import AuthProviderMessages, GuildMessages, SettingsMessages
from app.db import cohorts
from app.db.session import set_rls_context
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild import GUILD_ASSIGNABLE_ROLES, Guild, CommunityStatus
from app.models.platform.guild_provider_connection import (
    GuildProviderConnection,
    narrowing_admits,
)
from app.models.platform.oidc_claim_mapping import (
    ClaimRuleAuthor,
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.models.tenant.claim_rule_initiative import ClaimRuleInitiative
from app.models.tenant.initiative import Initiative, InitiativeRoleModel
from app.schemas.platform.settings import (
    PlacementCommunityRead,
    PlacementInitiativeRead,
    PlacementInitiativeRoleRead,
    PlacementProviderRead,
    ProviderPlacementResponse,
    ProviderPlacementRuleCreate,
    ProviderPlacementRuleRead,
    ProviderPlacementRuleUpdate,
)
from app.services import audit as audit_service
from app.services.platform import rules
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)

#: What a provider rule places somebody by, for the record, besides its
#: initiative (:func:`audited`).
AUDITED_FIELDS: tuple[str, ...] = (
    "provider_id",
    "claim_value",
    "scope_claim",
    "scope_value",
    "guild_id",
    "guild_role",
)

#: The standings a provider rule may hand out: the ones a community's own
#: rule may, and never the seat.
MAPPABLE_GUILD_ROLES: frozenset[str] = frozenset(
    role.value for role in GUILD_ASSIGNABLE_ROLES
)

#: How many communities one search of the picker returns.
COMMUNITY_SEARCH_LIMIT = 25


# ── Where a provider rule applies ─────────────────────────────────────────


async def placement_everywhere(session: AsyncSession) -> bool:
    """Whether the deployment applies provider rules to every community."""
    return (await rules.platform_values(session))["provider_placement_everywhere"]


async def set_placement_everywhere(
    session: AsyncSession, *, enabled: bool, actor_user_id: int | None
) -> bool:
    """Apply provider rules everywhere, or only where a community accepted.

    Nobody is signed out and no membership moves now: the next sync through
    each provider reconciles against what applies then.
    """
    was = await placement_everywhere(session)
    if was != enabled:
        await rules.put(session, "provider_placement_everywhere", enabled)
        await audit_service.record(
            session,
            event_type=AuditEventType.PROVIDER_PLACEMENT_EVERYWHERE_CHANGED,
            actor_user_id=actor_user_id,
            detail={"from": was, "to": enabled},
        )
        await session.commit()
        logger.info("provider placement everywhere: %s -> %s", was, enabled)
    return enabled


async def placeable_communities(
    session: AsyncSession, *, provider_id: int, guild_ids: set[int]
) -> set[int]:
    """Which of these communities this provider's rules place people in.

    All of them where the deployment applies provider rules everywhere;
    otherwise the ones whose own enabled connection to the provider accepts
    them.
    """
    if not guild_ids:
        return set()
    if await placement_everywhere(session):
        return set(guild_ids)
    rows = (
        await session.exec(
            select(GuildProviderConnection.guild_id).where(
                GuildProviderConnection.provider_id == provider_id,
                GuildProviderConnection.guild_id.in_(guild_ids),
                GuildProviderConnection.enabled.is_(True),
                GuildProviderConnection.accepts_provider_placement.is_(True),
            )
        )
    ).all()
    return set(rows)


def in_scope(rule: OIDCClaimMapping, claims: dict) -> bool:
    """Whether an arrival is from the directory a rule names, if it names one."""
    if rule.scope_claim is None or rule.scope_value is None:
        return True
    return narrowing_admits(rule.scope_claim, [rule.scope_value], claims)


def syncs_placement() -> ColumnElement[bool]:
    """Whether a provider's arrivals are reconciled against its rules, as a
    condition on ``auth_providers``: it reports groups, or it has a rule that
    places by directory alone, which applies whatever groups it reports.

    Sign-in and the background sweep both ask this, so a provider is
    reconciled by one on exactly the terms it is by the other.
    """
    return or_(
        func.coalesce(AuthProvider.role_claim_path, "") != "",
        exists().where(
            OIDCClaimMapping.provider_id == AuthProvider.id,
            OIDCClaimMapping.author == ClaimRuleAuthor.provider,
            OIDCClaimMapping.claim_value.is_(None),
        ),
    )


async def provider_syncs_placement(session: AsyncSession, *, provider_id: int) -> bool:
    """:func:`syncs_placement` for one provider."""
    row = (
        await session.exec(
            select(AuthProvider.id)
            .where(AuthProvider.id == provider_id, syncs_placement())
            .limit(1)
        )
    ).first()
    return row is not None


# ── What a rule may name ──────────────────────────────────────────────────


async def _initiatives_in(guild_id: int) -> list[PlacementInitiativeRead]:
    """One community's initiatives and their roles, read in its schema on a
    system session from its own cohort."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        initiatives = (
            await session.exec(select(Initiative).order_by(Initiative.name))
        ).all()
        roles = (
            await session.exec(
                select(InitiativeRoleModel).order_by(InitiativeRoleModel.position)
            )
        ).all()
    by_initiative: dict[int, list[PlacementInitiativeRoleRead]] = {}
    for role in roles:
        if role.id is None:
            continue
        by_initiative.setdefault(role.initiative_id, []).append(
            PlacementInitiativeRoleRead(
                id=role.id, name=role.display_name, is_manager=role.is_manager
            )
        )
    return [
        PlacementInitiativeRead(
            id=initiative.id,
            name=initiative.name,
            roles=by_initiative.get(initiative.id, []),
        )
        for initiative in initiatives
        if initiative.id is not None
    ]


async def _require_provider(session: AsyncSession, provider_id: int) -> AuthProvider:
    provider = await session.get(AuthProvider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.NOT_FOUND,
        )
    return provider


async def _require_guild(session: AsyncSession, guild_id: int) -> Guild:
    guild = await session.get(Guild, guild_id)
    if guild is None or guild.status == CommunityStatus.deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_NOT_FOUND,
        )
    return guild


async def _require_placeable(
    session: AsyncSession, *, provider_id: int, guild_id: int
) -> None:
    placeable = await placeable_communities(
        session, provider_id=provider_id, guild_ids={guild_id}
    )
    if guild_id not in placeable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthProviderMessages.PLACEMENT_NOT_ACCEPTED,
        )


async def list_communities(
    session: AsyncSession, *, provider_id: int, query: str | None
) -> list[PlacementCommunityRead]:
    """Communities matching a search, and whether a rule naming one applies."""
    await _require_provider(session, provider_id)
    stmt = (
        select(Guild.id, Guild.name)
        .where(Guild.status != CommunityStatus.deleted)
        .order_by(Guild.name)
        .limit(COMMUNITY_SEARCH_LIMIT)
    )
    needle = (query or "").strip()
    if needle:
        stmt = stmt.where(Guild.name.ilike(f"%{needle}%"))
    rows = (await session.exec(stmt)).all()
    placeable = await placeable_communities(
        session, provider_id=provider_id, guild_ids={gid for gid, _ in rows}
    )
    return [
        PlacementCommunityRead(id=gid, name=name, placeable=gid in placeable)
        for gid, name in rows
    ]


async def list_targets(
    session: AsyncSession, *, provider_id: int, guild_id: int
) -> list[PlacementInitiativeRead]:
    """The initiatives a rule for this community may place people in."""
    await _require_provider(session, provider_id)
    await _require_guild(session, guild_id)
    placeable = await placeable_communities(
        session, provider_id=provider_id, guild_ids={guild_id}
    )
    if guild_id not in placeable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.PLACEMENT_NOT_ACCEPTED,
        )
    return await _initiatives_in(guild_id)


# ── The rules ─────────────────────────────────────────────────────────────


def _clean_match(
    claim_value: str | None, scope_claim: str | None, scope_value: str | None
) -> tuple[str | None, str | None, str | None]:
    """A rule matches a group, a directory, or both. A directory is a claim
    and a value together."""
    group = (claim_value or "").strip() or None
    claim = (scope_claim or "").strip() or None
    value = (scope_value or "").strip() or None
    if (claim is None) != (value is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AuthProviderMessages.RULE_SCOPE_HALF_SET,
        )
    if group is None and claim is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AuthProviderMessages.RULE_NEEDS_A_MATCH,
        )
    return group, claim, value


def _require_mappable_role(guild_role: str) -> None:
    if guild_role not in MAPPABLE_GUILD_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.INVALID_GUILD_ROLE,
        )


@dataclass(frozen=True)
class RuleInitiative:
    """The initiative a rule places people in, and the role they hold there,
    spelled as both rule reads spell them. The names are ``None`` where they
    were not read."""

    initiative_id: int
    initiative_role_id: int
    initiative_name: str | None = None
    initiative_role_name: str | None = None


def audited(
    row: OIDCClaimMapping, fields: Collection[str], initiative: RuleInitiative | None
) -> dict[str, object]:
    """What a rule places somebody by, for the record: ``fields`` of the rule,
    and the initiative and role it places them in."""
    return {
        **audit_service.snapshot(row, fields),
        "initiative_id": initiative.initiative_id if initiative else None,
        "initiative_role_id": initiative.initiative_role_id if initiative else None,
    }


def destination_type(
    initiative_id: int | None, initiative_role_id: int | None
) -> OIDCMappingTargetType:
    """Which kind of rule a destination makes: naming neither lands somebody
    in the community alone, and an initiative needs the role to go with it."""
    if initiative_id is None and initiative_role_id is None:
        return OIDCMappingTargetType.guild
    if initiative_id is None or initiative_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.INITIATIVE_FIELDS_REQUIRED,
        )
    return OIDCMappingTargetType.initiative


def placed(rules: Iterable[OIDCClaimMapping]) -> list[tuple[int, int]]:
    """The ``claim_rule_initiatives`` key of each of these rules that places
    people in an initiative: its id and the version it names."""
    return [
        (rule.id, rule.placement_version)
        for rule in rules
        if rule.target_type == OIDCMappingTargetType.initiative and rule.id is not None
    ]


async def rule_initiatives(
    guild_id: int, rules: Iterable[OIDCClaimMapping], *, named: bool = True
) -> dict[int, RuleInitiative]:
    """The initiative each of these rules places people in, by rule id, read
    in the community's schema; a rule placing into none is left out. Unnamed
    where ``named`` is false: the platform reads no initiative's name in a
    community its rules do not apply in."""
    keys = placed(rules)
    if not keys:
        return {}
    stmt = select(
        ClaimRuleInitiative.rule_id,
        ClaimRuleInitiative.initiative_id,
        ClaimRuleInitiative.initiative_role_id,
    ).where(tuple_(ClaimRuleInitiative.rule_id, ClaimRuleInitiative.version).in_(keys))
    if named:
        stmt = (
            stmt.add_columns(Initiative.name, InitiativeRoleModel.display_name)
            .join(Initiative, Initiative.id == ClaimRuleInitiative.initiative_id)
            .join(
                InitiativeRoleModel,
                InitiativeRoleModel.id == ClaimRuleInitiative.initiative_role_id,
            )
        )
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        rows = (await session.exec(stmt)).all()
    return {row[0]: RuleInitiative(*row[1:]) for row in rows}


async def placements_stand(versions: Mapping[int, int]) -> bool:
    """Whether each of these rules, by id, still names the version given:
    False where one has moved or gone since it was read."""
    if not versions:
        return True
    async with cohorts.system_session(None) as session:
        now = dict(
            (
                await session.exec(
                    select(
                        OIDCClaimMapping.id, OIDCClaimMapping.placement_version
                    ).where(
                        OIDCClaimMapping.id.in_(versions)  # type: ignore[union-attr]
                    )
                )
            ).all()
        )
    return all(now.get(rule_id) == version for rule_id, version in versions.items())


async def set_rule_initiative(
    guild_id: int,
    rule_id: int,
    *,
    version: int,
    initiative_id: int,
    initiative_role_id: int,
    alike: Collection[tuple[int, int]],
) -> RuleInitiative:
    """Place a rule's people in one of the community's initiatives, at one of
    that initiative's roles, written and committed in the community's schema
    under the rule's ``version``. ``alike`` are the rules, by id and version,
    none of which may place the same people in the same initiative already."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        names = (
            await session.exec(
                select(Initiative.name, InitiativeRoleModel.display_name)
                .join(
                    InitiativeRoleModel,
                    InitiativeRoleModel.initiative_id == Initiative.id,
                )
                .where(
                    Initiative.id == initiative_id,
                    InitiativeRoleModel.id == initiative_role_id,
                )
            )
        ).one_or_none()
        if names is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=SettingsMessages.INITIATIVE_WRONG_GUILD,
            )
        if alike:
            taken = (
                await session.exec(
                    select(ClaimRuleInitiative.rule_id)
                    .where(
                        tuple_(
                            ClaimRuleInitiative.rule_id, ClaimRuleInitiative.version
                        ).in_(alike),
                        ClaimRuleInitiative.initiative_id == initiative_id,
                    )
                    .limit(1)
                )
            ).first()
            if taken is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=AuthProviderMessages.RULE_EXISTS,
                )
        row = await session.get(ClaimRuleInitiative, (rule_id, version))
        if row is None:
            row = ClaimRuleInitiative(
                rule_id=rule_id,
                version=version,
                initiative_id=initiative_id,
                initiative_role_id=initiative_role_id,
            )
        row.initiative_id = initiative_id
        row.initiative_role_id = initiative_role_id
        session.add(row)
        await session.commit()
    return RuleInitiative(initiative_id, initiative_role_id, *names)


async def drop_rule_initiative(
    guild_id: int, rule_id: int, *, before: int | None = None
) -> None:
    """Drop a rule's rows in the community's schema: every one, or those of
    the versions ``before`` the one given."""
    stmt = delete(ClaimRuleInitiative).where(ClaimRuleInitiative.rule_id == rule_id)
    if before is not None:
        stmt = stmt.where(ClaimRuleInitiative.version < before)
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        await session.exec(stmt)
        await session.commit()


async def place_rule(
    session: AsyncSession,
    row: OIDCClaimMapping,
    *,
    initiative_id: int | None,
    initiative_role_id: int | None,
    excluding: int | None = None,
) -> RuleInitiative | None:
    """Check where ``row`` places people, refusing a place another rule by its
    author already gives the same arrivals in the same community, and write
    the initiative it names.

    ``row`` carries its :func:`destination_type` and the version to write
    under. It is flushed here for the id its initiative is kept under, which
    is committed in the community before the caller commits ``row``: a rule
    that is then not committed leaves a row under a version no rule names. A
    rule that names no initiative keeps whatever one it had until the caller
    drops it (:func:`drop_rule_initiative`), once ``row`` is committed.
    """
    stmt = select(OIDCClaimMapping.id, OIDCClaimMapping.placement_version).where(
        OIDCClaimMapping.author == row.author,
        OIDCClaimMapping.provider_id == row.provider_id,
        OIDCClaimMapping.guild_id == row.guild_id,
        OIDCClaimMapping.target_type == row.target_type,
    )
    for column, value in (
        (OIDCClaimMapping.claim_value, row.claim_value),
        (OIDCClaimMapping.scope_claim, row.scope_claim),
        (OIDCClaimMapping.scope_value, row.scope_value),
    ):
        stmt = stmt.where(column.is_(None) if value is None else column == value)
    if excluding is not None:
        stmt = stmt.where(OIDCClaimMapping.id != excluding)
    alike = (await session.exec(stmt)).all()
    if initiative_id is None or initiative_role_id is None:
        if alike:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=AuthProviderMessages.RULE_EXISTS,
            )
        return None
    session.add(row)
    await session.flush()
    assert row.id is not None
    return await set_rule_initiative(
        row.guild_id,
        row.id,
        version=row.placement_version,
        initiative_id=initiative_id,
        initiative_role_id=initiative_role_id,
        alike=[(rule_id, version) for rule_id, version in alike],
    )


async def _provider_rule(session: AsyncSession, rule_id: int) -> OIDCClaimMapping:
    row = (
        await session.exec(
            select(OIDCClaimMapping).where(
                OIDCClaimMapping.id == rule_id,
                OIDCClaimMapping.author == ClaimRuleAuthor.provider,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.RULE_NOT_FOUND,
        )
    return row


def rule_read(
    row: OIDCClaimMapping,
    *,
    provider: AuthProvider | None,
    guild_name: str,
    applies: bool,
    initiative: RuleInitiative | None,
) -> ProviderPlacementRuleRead:
    """One rule as either surface shows it, with the initiative it places
    people in where it names one."""
    assert row.id is not None
    return ProviderPlacementRuleRead(
        id=row.id,
        provider_id=row.provider_id,
        provider_display_name=provider.display_name if provider else "",
        provider_icon=provider.icon if provider else None,
        claim_value=row.claim_value,
        scope_claim=row.scope_claim,
        scope_value=row.scope_value,
        community_id=row.guild_id,
        community_name=guild_name,
        community_role=row.guild_role,
        applies=applies,
        **(asdict(initiative) if initiative else {}),
    )


async def list_rules(session: AsyncSession) -> ProviderPlacementResponse:
    """Every provider, every provider rule, and whether rules apply everywhere.

    Initiative names are read only for communities a rule places into.
    """
    providers = {
        row.id: row
        for row in (
            await session.exec(select(AuthProvider).order_by(AuthProvider.display_name))
        ).all()
        if row.id is not None
    }
    rows = (
        await session.exec(
            select(OIDCClaimMapping)
            .where(OIDCClaimMapping.author == ClaimRuleAuthor.provider)
            .order_by(OIDCClaimMapping.id)
        )
    ).all()
    guild_ids = {row.guild_id for row in rows}
    names = (
        dict(
            (
                await session.exec(
                    select(Guild.id, Guild.name).where(Guild.id.in_(guild_ids))
                )
            ).all()
        )
        if guild_ids
        else {}
    )
    placeable: set[tuple[int, int]] = set()
    for provider_id in {row.provider_id for row in rows}:
        for gid in await placeable_communities(
            session,
            provider_id=provider_id,
            guild_ids={row.guild_id for row in rows if row.provider_id == provider_id},
        ):
            placeable.add((provider_id, gid))
    placing: dict[tuple[int, int], list[OIDCClaimMapping]] = {}
    for row in rows:
        if row.target_type == OIDCMappingTargetType.initiative:
            placing.setdefault((row.provider_id, row.guild_id), []).append(row)
    initiatives: dict[int, RuleInitiative] = {}
    for (provider_id, gid), placing_rows in sorted(placing.items()):
        initiatives |= await rule_initiatives(
            gid, placing_rows, named=(provider_id, gid) in placeable
        )
    return ProviderPlacementResponse(
        placement_everywhere=await placement_everywhere(session),
        providers=[
            PlacementProviderRead(
                id=pid,
                display_name=row.display_name,
                icon=row.icon,
                reports_groups=bool(row.role_claim_path),
            )
            for pid, row in providers.items()
        ],
        rules=[
            rule_read(
                row,
                provider=providers.get(row.provider_id),
                guild_name=names.get(row.guild_id, ""),
                applies=(row.provider_id, row.guild_id) in placeable,
                initiative=initiatives.get(row.id) if row.id is not None else None,
            )
            for row in rows
        ],
    )


async def _read_one(
    session: AsyncSession, row: OIDCClaimMapping, initiative: RuleInitiative | None
) -> ProviderPlacementRuleRead:
    """A rule just written, which applies: its community accepted it."""
    provider = await session.get(AuthProvider, row.provider_id)
    guild = await session.get(Guild, row.guild_id)
    return rule_read(
        row,
        provider=provider,
        guild_name=guild.name if guild else "",
        applies=True,
        initiative=initiative,
    )


async def create_rule(
    session: AsyncSession,
    *,
    payload: ProviderPlacementRuleCreate,
    actor_user_id: int | None = None,
) -> ProviderPlacementRuleRead:
    await _require_provider(session, payload.provider_id)
    await _require_guild(session, payload.community_id)
    claim_value, scope_claim, scope_value = _clean_match(
        payload.claim_value, payload.scope_claim, payload.scope_value
    )
    _require_mappable_role(payload.community_role)
    await _require_placeable(
        session, provider_id=payload.provider_id, guild_id=payload.community_id
    )
    row = OIDCClaimMapping(
        author=ClaimRuleAuthor.provider,
        provider_id=payload.provider_id,
        claim_value=claim_value,
        scope_claim=scope_claim,
        scope_value=scope_value,
        target_type=destination_type(payload.initiative_id, payload.initiative_role_id),
        guild_id=payload.community_id,
        guild_role=payload.community_role,
    )
    initiative = await place_rule(
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
        guild_id=row.guild_id,
        target_type="claim_rule",
        target_id=row.id,
        detail={
            "via": "platform",
            "author": ClaimRuleAuthor.provider.value,
            **audit_service.changed_fields(
                {}, audited(row, AUDITED_FIELDS, initiative)
            ),
        },
    )
    await session.commit()
    await session.refresh(row)
    return await _read_one(session, row, initiative)


async def update_rule(
    session: AsyncSession,
    *,
    rule_id: int,
    payload: ProviderPlacementRuleUpdate,
    actor_user_id: int | None = None,
) -> ProviderPlacementRuleRead:
    row = await _provider_rule(session, rule_id)
    await _require_placeable(
        session, provider_id=row.provider_id, guild_id=row.guild_id
    )
    assert row.id is not None
    was = (await rule_initiatives(row.guild_id, [row], named=False)).get(row.id)
    before = audited(row, AUDITED_FIELDS, was)
    data = payload.model_dump(exclude_unset=True)

    row.claim_value, row.scope_claim, row.scope_value = _clean_match(
        data["claim_value"] if "claim_value" in data else row.claim_value,
        data["scope_claim"] if "scope_claim" in data else row.scope_claim,
        data["scope_value"] if "scope_value" in data else row.scope_value,
    )
    if data.get("community_role") is not None:
        _require_mappable_role(data["community_role"])
        row.guild_role = data["community_role"]
    initiative_id = (
        data["initiative_id"]
        if "initiative_id" in data
        else (was.initiative_id if was else None)
    )
    initiative_role_id = (
        data["initiative_role_id"]
        if "initiative_role_id" in data
        else (was.initiative_role_id if was else None)
    )
    row.target_type = destination_type(initiative_id, initiative_role_id)
    # Moving the rule writes its next version, which it names once committed
    # with its claims, so a sign-in reads the place that goes with them.
    moved = (was.initiative_id, was.initiative_role_id) if was else None
    if initiative_id is not None and moved != (initiative_id, initiative_role_id):
        row.placement_version += 1
    initiative = await place_rule(
        session,
        row,
        initiative_id=initiative_id,
        initiative_role_id=initiative_role_id,
        excluding=row.id,
    )
    session.add(row)
    changed = audit_service.changed_fields(
        before, audited(row, AUDITED_FIELDS, initiative)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.CLAIM_RULE_UPDATED,
            actor_user_id=actor_user_id,
            guild_id=row.guild_id,
            target_type="claim_rule",
            target_id=row.id,
            detail={
                "via": "platform",
                "author": ClaimRuleAuthor.provider.value,
                **changed,
            },
        )
    await session.commit()
    if initiative is None:
        if was is not None:
            await drop_rule_initiative(row.guild_id, row.id)
    else:
        # The version before stays for a sign-in that read the rule just
        # before this change.
        await drop_rule_initiative(
            row.guild_id, row.id, before=row.placement_version - 1
        )
    await session.refresh(row)
    return await _read_one(session, row, initiative)


async def delete_rule(
    session: AsyncSession, *, rule_id: int, actor_user_id: int | None = None
) -> None:
    """Stop placing the people a rule matched. What it granted is released by
    the next sign-in through the provider, as a community's own rule is."""
    row = await _provider_rule(session, rule_id)
    guild_id = row.guild_id
    placed = row.target_type == OIDCMappingTargetType.initiative
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.CLAIM_RULE_DELETED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="claim_rule",
        target_id=rule_id,
        detail={"via": "platform", "author": ClaimRuleAuthor.provider.value},
    )
    await session.commit()
    if placed:
        await drop_rule_initiative(guild_id, rule_id)
