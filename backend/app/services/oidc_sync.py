from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import partial

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db import post_commit
from app.models.platform.guild import GUILD_ADMIN_ROLES, GuildMembership, CommunityRole
from app.services import audit as audit_service
from app.services.auth import guild_provider_connections as guild_connections
from app.services.guild_sweeps import Scope, each_guild
from app.services.platform import provider_placement
from app.services.platform import account_stream
from app.services.platform import guilds as guilds_service
from app.services.tenant import custom_roles as custom_roles_service
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
)
from app.models.platform.oidc_claim_mapping import (
    ClaimRuleAuthor,
    OIDCClaimMapping,
    OIDCMappingTargetType,
)

logger = logging.getLogger(__name__)

# Role priority for conflict resolution: higher wins
_GUILD_ROLE_PRIORITY = {
    CommunityRole.member.value: 0,
    CommunityRole.admin.value: 1,
}

#: How every membership this module moves came to move. A reconciliation runs
#: off what a provider asserted, with nobody at a keyboard, so the records it
#: writes name this and no actor.
_VIA = "claim_sync"


async def _record(session: AsyncSession, **fields) -> None:
    """Write one record out where it is made, in the transaction ``session``
    commits. The actor is always absent, because the sync runs off asserted
    claims rather than a request."""
    await audit_service.record(session, actor_user_id=None, **fields)
    await session.flush()


async def _role_name(session: AsyncSession, role_id: int | None) -> str | None:
    """An initiative role's own name, for the record. ``None`` where the
    membership carries no role."""
    if role_id is None:
        return None
    return (
        await session.exec(
            select(InitiativeRoleModel.name).where(InitiativeRoleModel.id == role_id)
        )
    ).one_or_none()


@dataclass
class OIDCSyncResult:
    guilds_added: list[int] = field(default_factory=list)
    guilds_updated: list[int] = field(default_factory=list)
    guilds_removed: list[int] = field(default_factory=list)
    initiatives_added: list[int] = field(default_factory=list)
    initiatives_updated: list[int] = field(default_factory=list)
    initiatives_removed: list[int] = field(default_factory=list)


def extract_claim_values(
    profile: dict,
    id_token_claims: dict | None,
    claim_path: str,
) -> set[str]:
    """Extract claim values from userinfo or id_token using dot-notation path."""

    def _traverse(data: dict, path_parts: list[str]) -> list | str | dict | None:
        current = data
        for part in path_parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return current

    parts = claim_path.strip().split(".")
    if not parts or not parts[0]:
        return set()

    # Try userinfo first, then id_token
    raw = _traverse(profile, parts)
    if raw is None and id_token_claims:
        raw = _traverse(id_token_claims, parts)

    if raw is None:
        return set()

    if isinstance(raw, str):
        return {raw.lower()}
    if isinstance(raw, list):
        return {str(v).lower() for v in raw if v is not None}
    return set()


async def placement_claims(session: AsyncSession, *, provider_id: int) -> set[str]:
    """The verified claims this provider's rules are decided by: the narrowing
    each community that wrote a rule has for the provider, and the directory a
    provider rule names. What :func:`sync_oidc_assignments` reads from
    ``claims`` besides the groups."""
    rules = (
        await session.exec(
            select(OIDCClaimMapping).where(OIDCClaimMapping.provider_id == provider_id)
        )
    ).all()
    names = {
        rule.scope_claim
        for rule in rules
        if rule.author == ClaimRuleAuthor.provider
        and rule.scope_claim
        and rule.scope_value
    }
    return names | await guild_connections.narrowing_claims(
        session,
        provider_id=provider_id,
        guild_ids={
            rule.guild_id for rule in rules if rule.author == ClaimRuleAuthor.community
        },
    )


async def sync_oidc_assignments(
    session: AsyncSession,
    *,
    user_id: int,
    provider_id: int,
    claim_values: set[str],
    claims: dict,
) -> OIDCSyncResult:
    """Reconcile guild/initiative memberships against one provider's claims.

    Scoped to ``provider_id`` on both halves, because this both grants and
    takes away: it reads the rules belonging to that provider, and the
    memberships it may reclaim are the ones that provider's own sync granted.
    Another provider's rules and another provider's memberships are not this
    sign-in's business.

    ``claim_values`` are the groups the provider asserted; ``claims`` is the
    whole verified set, which says whose tenant the arrival belongs to. A rule
    applies only where its community counts the arrival as one of its own.

    Must be called with a system session.
    """
    result = OIDCSyncResult()

    # This provider's rules. Two providers spell their groups their own way, so
    # a claim value means nothing until you know who asserted it. Each rule
    # names the guild it grants in and is written by that guild's superadmin,
    # so it speaks for the arrivals that guild's connection admits.
    stmt = select(OIDCClaimMapping).where(OIDCClaimMapping.provider_id == provider_id)
    rules = (await session.exec(stmt)).all()
    community_rules = [r for r in rules if r.author == ClaimRuleAuthor.community]
    provider_rules = [r for r in rules if r.author == ClaimRuleAuthor.provider]
    admitted = await guild_connections.communities_admitting(
        session,
        provider_id=provider_id,
        claims=claims,
        guild_ids={rule.guild_id for rule in community_rules},
    )
    # The platform's rules for this provider place people where the community
    # accepts them, or everywhere where the deployment says so, and only
    # arrivals from the directory a rule names, if it names one. A community's
    # own narrowing governs the rules it wrote, not these: who a provider rule
    # places is the operator's to say.
    placeable = await provider_placement.placeable_communities(
        session,
        provider_id=provider_id,
        guild_ids={rule.guild_id for rule in provider_rules},
    )
    mappings = [rule for rule in community_rules if rule.guild_id in admitted] + [
        rule
        for rule in provider_rules
        if rule.guild_id in placeable and provider_placement.in_scope(rule, claims)
    ]
    # No early return on an empty set. A provider whose last rule was deleted
    # grants nothing, which is not the same as having nothing to take back —
    # the sweeps below are what hand those memberships over.

    # Partition into matched and unmatched
    matched: list[OIDCClaimMapping] = []
    matched_guild_ids: set[int] = set()
    matched_initiative_ids: set[int] = set()

    for mapping in mappings:
        # A rule naming no group places everybody its directory matched.
        if mapping.claim_value is None or mapping.claim_value.lower() in claim_values:
            matched.append(mapping)
            if mapping.target_type == OIDCMappingTargetType.guild:
                matched_guild_ids.add(mapping.guild_id)
            elif mapping.target_type == OIDCMappingTargetType.initiative:
                matched_guild_ids.add(mapping.guild_id)
                if mapping.initiative_id is not None:
                    matched_initiative_ids.add(mapping.initiative_id)

    # Resolve guild role conflicts: highest role wins per guild
    guild_roles: dict[int, str] = {}
    for mapping in matched:
        gid = mapping.guild_id
        role = mapping.guild_role
        if gid not in guild_roles:
            guild_roles[gid] = role
        elif _GUILD_ROLE_PRIORITY.get(role, 0) > _GUILD_ROLE_PRIORITY.get(
            guild_roles[gid], 0
        ):
            guild_roles[gid] = role

    # Resolve initiative mappings: collect candidate role_ids per initiative,
    # then pick the highest-privilege role (is_manager wins, then lowest position).
    # Also track which guild each initiative mapping belongs to.
    initiative_guild: dict[int, int] = {}  # initiative_id -> guild_id
    initiative_role_candidates: dict[int, list[int]] = {}  # initiative_id -> role_ids
    for mapping in matched:
        if (
            mapping.target_type == OIDCMappingTargetType.initiative
            and mapping.initiative_id is not None
        ):
            initiative_guild[mapping.initiative_id] = mapping.guild_id
            if mapping.initiative_role_id is not None:
                initiative_role_candidates.setdefault(mapping.initiative_id, []).append(
                    mapping.initiative_role_id
                )
            else:
                initiative_role_candidates.setdefault(mapping.initiative_id, [])

    # ``oidc_claim_mappings`` and guild memberships are shared; initiatives,
    # their roles and members live in each guild's schema. The shared half runs
    # on ``session``, and each guild's half on a system session from that
    # guild's cohort.

    # --- Stale guild memberships ---
    # An oidc-managed membership the claims no longer grant, removed in each
    # guild's own transaction the way leaving is, so a guild whose half fails
    # keeps the member for the next sync to finish.
    from app.services.content_sockets import sockets as content_sockets
    from app.services.tenant.initiatives import enroll_in_auto_join_initiatives

    async def drop_stale_initiatives(guild_session: AsyncSession, gid: int) -> None:
        """Remove the oidc-managed initiative memberships in this guild that
        the claims no longer grant, recording each."""
        stale_inits = (
            await guild_session.exec(
                select(InitiativeMember).where(
                    InitiativeMember.user_id == user_id,
                    InitiativeMember.oidc_provider_id == provider_id,
                )
            )
        ).all()
        for im in stale_inits:
            if im.initiative_id not in matched_initiative_ids:
                await _record(
                    guild_session,
                    event_type=AuditEventType.INITIATIVE_MEMBER_REMOVED,
                    target_user_id=user_id,
                    guild_id=gid,
                    target_type="initiative",
                    target_id=im.initiative_id,
                    detail={"via": _VIA},
                )
                await guild_session.delete(im)
                result.initiatives_removed.append(im.initiative_id)

    stale_guild_ids = (
        set(
            (
                await session.exec(
                    select(GuildMembership.guild_id).where(
                        GuildMembership.user_id == user_id,
                        GuildMembership.oidc_provider_id == provider_id,
                        GuildMembership.role != CommunityRole.superadmin,
                    )
                )
            ).all()
        )
        - matched_guild_ids
    )
    left: set[int] = set()

    async def leave(guild_session: AsyncSession, gid: int) -> None:
        await drop_stale_initiatives(guild_session, gid)
        await guild_session.flush()
        await guilds_service.remove_user_from_guild(
            guild_session,
            guild_id=gid,
            user_id=user_id,
            actor_user_id=None,
            via=_VIA,
        )
        post_commit.after_commit(
            guild_session, partial(content_sockets.revoke_user, gid, user_id)
        )
        await guild_session.commit()
        left.add(gid)

    if stale_guild_ids:
        await each_guild(
            [(Scope.LIVE, leave)], name="oidc-sync-leave", only=stale_guild_ids
        )
    result.guilds_removed.extend(sorted(left))

    # --- Guild memberships (shared) ---
    # Apply matched guild roles, and ensure a membership exists for every guild
    # that has a matched initiative so the initiative member can be added below.
    ensure_member_guilds = set(guild_roles) | set(initiative_guild.values())
    # Guilds this sync admits the user to for the first time, as a plain member.
    # They are as new to the guild as an invite redeemer, so the guild's
    # auto-join initiatives take them in the same way (below, in each guild's
    # half). Admins are left out for the same reason the invite path leaves
    # them out — standing access already, and no member role to hold.
    newly_admitted_guilds: set[int] = set()
    for guild_id in sorted(ensure_member_guilds):
        desired = guild_roles.get(guild_id)
        membership = await _get_guild_membership(
            session, user_id=user_id, guild_id=guild_id
        )
        if membership:
            # Only a row this provider manages. One somebody joined by
            # hand, or another provider's, is not this sync's to move — and
            # neither is a superadmin: that seat is passed on by somebody
            # holding it, never by a rule matching a claim value.
            if (
                desired is not None
                and membership.oidc_provider_id == provider_id
                and membership.role != CommunityRole.superadmin
            ):
                role = CommunityRole(desired)
                if membership.role != role:
                    membership.role = role
                    session.add(membership)
                    result.guilds_updated.append(guild_id)
        else:
            # A listed community is open to anyone signed in, so the age rule
            # holds however somebody arrived — and this is the way in with
            # nobody at a keyboard to be asked, so what counts is the answer
            # already on the record. An account that has never been asked is
            # admitted: not knowing is not the same as knowing they are too
            # young, and a private guild never puts the question at all.
            #
            # The guild is asked first, so a private one — which is most of
            # them, and which the rule does not touch — costs no lookup of
            # the account.
            if await guilds_service.is_listed_in_directory(
                session, guild_id=guild_id
            ) and await guilds_service.is_known_under_age(session, user_id=user_id):
                logger.info(
                    "guild %s is listed; the age answer on record keeps this "
                    "account out of it",
                    guild_id,
                )
                continue
            role = (
                CommunityRole(desired) if desired is not None else CommunityRole.member
            )
            await _create_guild_membership(
                session,
                user_id=user_id,
                guild_id=guild_id,
                role=role,
                provider_id=provider_id,
            )
            result.guilds_added.append(guild_id)
            # Nobody was at a keyboard for this one — it is the case the
            # standing checks exist for. Their tabs re-read the account.
            account_stream.queue_account_signal(session, user_id, "membership")
            if role not in GUILD_ADMIN_ROLES:
                newly_admitted_guilds.add(guild_id)
    await session.flush()

    # Guilds to visit for guild-scoped work: those the claims map to, plus every
    # guild the user still belongs to (so stale oidc-managed initiative
    # memberships get cleaned up).
    existing_guild_ids = set(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )
    relevant_guilds = (
        existing_guild_ids | set(initiative_guild.values()) | set(guild_roles)
    )
    # Where the community's own custom-role rules (in its schema) may speak for
    # this arrival: the communities that count it as one of their own, as for
    # the rules above.
    role_admitted = await guild_connections.communities_admitting(
        session, provider_id=provider_id, claims=claims, guild_ids=relevant_guilds
    )
    await session.commit()

    # --- Initiative resolution + membership (each guild's half) ---
    async def sync_initiatives(guild_session: AsyncSession, gid: int) -> None:
        guild_inits = {iid for iid, g in initiative_guild.items() if g == gid}
        # Drop references to initiatives that no longer exist in this schema
        # (oidc_claim_mappings has no cross-schema FK, so a purged initiative can
        # leave a dangling mapping).
        if guild_inits:
            present = set(
                (
                    await guild_session.exec(
                        select(Initiative.id).where(Initiative.id.in_(guild_inits))
                    )
                ).all()
            )
            guild_inits &= present

        # Resolve each initiative to a single role_id (manager first, then lowest
        # position), validating the role still exists in this schema.
        guild_init_roles: dict[int, int | None] = {}
        for iid in guild_inits:
            unique_ids = list(
                {c for c in initiative_role_candidates.get(iid, []) if c is not None}
            )
            role_id: int | None = None
            if unique_ids:
                roles = (
                    await guild_session.exec(
                        select(InitiativeRoleModel).where(
                            InitiativeRoleModel.id.in_(unique_ids)
                        )
                    )
                ).all()
                if roles:
                    roles.sort(key=lambda r: (not r.is_manager, r.position))
                    role_id = roles[0].id
            guild_init_roles[iid] = role_id

        for iid, role_id in guild_init_roles.items():
            im = await _get_initiative_membership(
                guild_session, user_id=user_id, initiative_id=iid
            )
            if im:
                if im.oidc_provider_id != provider_id:
                    continue
                if role_id is not None and im.role_id != role_id:
                    previous_role_id = im.role_id
                    im.role_id = role_id
                    guild_session.add(im)
                    result.initiatives_updated.append(iid)
                    await _record(
                        guild_session,
                        event_type=AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED,
                        target_user_id=user_id,
                        guild_id=gid,
                        target_type="initiative",
                        target_id=iid,
                        detail={
                            "from_role_id": previous_role_id,
                            "from": await _role_name(guild_session, previous_role_id),
                            "to_role_id": role_id,
                            "to": await _role_name(guild_session, role_id),
                        },
                    )
            else:
                await _create_initiative_membership(
                    guild_session,
                    user_id=user_id,
                    initiative_id=iid,
                    guild_id=gid,
                    role_id=role_id,
                    provider_id=provider_id,
                )
                result.initiatives_added.append(iid)

        await drop_stale_initiatives(guild_session, gid)

        # Onboarding for a first-time arrival, once the claims have had their
        # say. It runs last because the claims are authoritative about role:
        # enrolment would otherwise write a plain member row that the mapping
        # loop above then declines to touch (it leaves non-oidc-managed rows
        # alone by design), and a user mapped to a manager role would silently
        # land as a member. Enrolling afterwards is a no-op for any initiative
        # the claims already placed them in, so this only fills the gaps.
        #
        # The rows are ordinary (no managing provider), so the sweep above
        # leaves them alone and a later sync neither reaps nor fights them.
        if gid in newly_admitted_guilds:
            await enroll_in_auto_join_initiatives(
                guild_session, guild_id=gid, user_id=user_id
            )

        # The custom role the community's rules give for these groups.
        changed = await custom_roles_service.apply_claims(
            guild_session,
            guild_id=gid,
            user_id=user_id,
            provider_id=provider_id,
            claim_values=claim_values,
            admitted=gid in role_admitted,
        )
        if changed is not None:
            await _record(
                guild_session,
                event_type=AuditEventType.GUILD_CUSTOM_ROLE_ASSIGNED,
                target_user_id=user_id,
                guild_id=gid,
                target_type="custom_role",
                target_id=changed[1],
                detail={
                    "from_role_id": changed[0],
                    "to_role_id": changed[1],
                    "via": _VIA,
                },
            )

    if relevant_guilds:
        await each_guild(
            [(Scope.LIVE, sync_initiatives)], name="oidc-sync", only=relevant_guilds
        )
    return result


async def _get_guild_membership(
    session: AsyncSession, *, user_id: int, guild_id: int
) -> GuildMembership | None:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    return (await session.exec(stmt)).one_or_none()


async def _create_guild_membership(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    role: CommunityRole,
    provider_id: int,
) -> GuildMembership:
    from sqlalchemy import func as sa_func

    # Calculate next position
    max_pos = (
        await session.exec(
            select(sa_func.max(GuildMembership.position)).where(
                GuildMembership.user_id == user_id
            )
        )
    ).one_or_none()
    next_pos = (max_pos if max_pos is not None else -1) + 1

    membership = GuildMembership(
        guild_id=guild_id,
        user_id=user_id,
        role=role,
        position=next_pos,
        oidc_provider_id=provider_id,
    )
    session.add(membership)
    await session.flush()
    await _record(
        session,
        event_type=AuditEventType.GUILD_MEMBER_ADDED,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"role": role.value, "via": _VIA},
    )
    return membership


async def _get_initiative_membership(
    session: AsyncSession, *, user_id: int, initiative_id: int
) -> InitiativeMember | None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    return (await session.exec(stmt)).one_or_none()


async def _create_initiative_membership(
    session: AsyncSession,
    *,
    user_id: int,
    initiative_id: int,
    guild_id: int,
    role_id: int | None,
    provider_id: int,
) -> InitiativeMember:
    im = InitiativeMember(
        initiative_id=initiative_id,
        user_id=user_id,
        role_id=role_id,
        oidc_provider_id=provider_id,
    )
    session.add(im)
    await session.flush()
    await _record(
        session,
        event_type=AuditEventType.INITIATIVE_MEMBER_ADDED,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="initiative",
        target_id=initiative_id,
        detail={
            "via": _VIA,
            "role_id": role_id,
            "role": await _role_name(session, role_id),
        },
    )
    return im
