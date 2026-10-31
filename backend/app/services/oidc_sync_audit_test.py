"""What a claim reconciliation writes down.

Nobody is at a keyboard for one of these: it runs off what a provider asserted,
so every record it writes names the community, the account it happened to, and
no actor at all. That is also what the guild-routed half of the sync can write —
the session carries no account while it is inside a guild's schema.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.session import set_rls_context
from app.models.tenant.claim_rule_initiative import ClaimRuleInitiative
from app.models.tenant.initiative import InitiativeRoleModel
from app.services.oidc_sync import sync_oidc_assignments
from app.services.tenant.initiatives import get_role_by_name
from app.testing import emitted, route_session_to_guild
from app.testing.factories import (
    NARROWED_CLAIM,
    NARROWED_VALUE,
    create_auth_provider,
    create_claim_rule,
    create_guild_provider_connection,
    create_guild,
    create_initiative,
    create_user,
)
from app.db.request_context import Unattributed


def _where(row) -> tuple:
    return (
        row["actor_user_id"],
        row["target_user_id"],
        row["guild_id"],
        row["target"],
    )


def _of_type(written: list[dict], event_type: AuditEventType) -> list[dict]:
    return [row for row in written if row["event_type"] == event_type.value]


async def _sync(session: AsyncSession, *, user_id: int, provider_id: int, claims):
    await set_rls_context(session, Unattributed())
    result = await sync_oidc_assignments(
        session,
        user_id=user_id,
        provider_id=provider_id,
        claim_values=claims,
        claims={NARROWED_CLAIM: NARROWED_VALUE},
    )
    await session.commit()
    return result


async def test_a_first_arrival_records_the_guild_and_the_initiative(
    session: AsyncSession, capfd
):
    provider = await create_auth_provider(session)
    provider_id = provider.id
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    guild_id = guild.id
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    initiative = await create_initiative(session, guild, owner, name="Ops")
    initiative_id = initiative.id
    pm_role = await get_role_by_name(
        session, initiative_id=initiative_id, role_name="project_manager"
    )
    pm_role_id, pm_role_name = pm_role.id, pm_role.name

    newcomer = await create_user(session)
    newcomer_id = newcomer.id
    await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        claim_value="engineering",
        initiative=initiative,
        initiative_role_id=pm_role_id,
    )
    capfd.readouterr()

    await _sync(
        session,
        user_id=newcomer_id,
        provider_id=provider_id,
        claims={"engineering"},
    )

    written = emitted(capfd)
    joined = _of_type(written, AuditEventType.GUILD_MEMBER_ADDED)
    # No actor: the session is inside the guild with no account behind it, and
    # that is the truthful reading of a sync besides.
    assert [_where(row) for row in joined] == [
        (None, newcomer_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert joined[0]["detail"] == {"role": "member", "via": "claim_sync"}

    placed = _of_type(written, AuditEventType.INITIATIVE_MEMBER_ADDED)
    assert [_where(row) for row in placed] == [
        (None, newcomer_id, guild_id, {"type": "initiative", "id": initiative_id})
    ]
    assert placed[0]["detail"] == {
        "via": "claim_sync",
        "role_id": pm_role_id,
        "role": pm_role_name,
    }

    # The same claims a second time move nothing, so they record nothing.
    await _sync(
        session,
        user_id=newcomer_id,
        provider_id=provider_id,
        claims={"engineering"},
    )
    again = emitted(capfd)
    assert _of_type(again, AuditEventType.GUILD_MEMBER_ADDED) == []
    assert _of_type(again, AuditEventType.INITIATIVE_MEMBER_ADDED) == []


async def test_a_moved_role_and_a_withdrawn_claim_are_both_recorded(
    session: AsyncSession, capfd
):
    provider = await create_auth_provider(session, slug="movers")
    provider_id = provider.id
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    guild_id = guild.id
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    initiative = await create_initiative(session, guild, owner, name="Moving")
    initiative_id = initiative.id
    pm_role = await get_role_by_name(
        session, initiative_id=initiative_id, role_name="project_manager"
    )
    pm_role_id, pm_role_name = pm_role.id, pm_role.name

    await route_session_to_guild(session, guild_id)
    other_role = (
        await session.exec(
            select(InitiativeRoleModel)
            .where(
                InitiativeRoleModel.initiative_id == initiative_id,
                InitiativeRoleModel.id != pm_role_id,
            )
            .order_by(InitiativeRoleModel.position)
        )
    ).first()
    assert other_role is not None and other_role.id is not None
    other_role_id, other_role_name = other_role.id, other_role.name

    newcomer = await create_user(session)
    newcomer_id = newcomer.id
    rule = await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        claim_value="engineering",
        initiative=initiative,
        initiative_role_id=pm_role_id,
    )
    rule_id = rule.id

    await _sync(
        session, user_id=newcomer_id, provider_id=provider_id, claims={"engineering"}
    )

    # The rule now names a different role for the same claim.
    await route_session_to_guild(session, guild_id)
    placed = await session.get(ClaimRuleInitiative, (rule_id, 0))
    assert placed is not None
    placed.initiative_role_id = other_role_id
    session.add(placed)
    await session.commit()
    capfd.readouterr()

    await _sync(
        session, user_id=newcomer_id, provider_id=provider_id, claims={"engineering"}
    )

    moved = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED)
    assert [_where(row) for row in moved] == [
        (None, newcomer_id, guild_id, {"type": "initiative", "id": initiative_id})
    ]
    assert moved[0]["detail"] == {
        "from_role_id": pm_role_id,
        "from": pm_role_name,
        "to_role_id": other_role_id,
        "to": other_role_name,
    }

    # The claim stops being asserted, and the sync takes both places back.
    await _sync(session, user_id=newcomer_id, provider_id=provider_id, claims=set())

    written = emitted(capfd)
    dropped = _of_type(written, AuditEventType.INITIATIVE_MEMBER_REMOVED)
    assert [_where(row) for row in dropped] == [
        (None, newcomer_id, guild_id, {"type": "initiative", "id": initiative_id})
    ]
    assert dropped[0]["detail"] == {"via": "claim_sync"}

    left = _of_type(written, AuditEventType.GUILD_MEMBER_REMOVED)
    assert [_where(row) for row in left] == [
        (None, newcomer_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert left[0]["detail"] == {"role": "member", "via": "claim_sync"}
