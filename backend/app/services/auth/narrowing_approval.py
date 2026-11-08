"""Agreeing that a community's claim values are its to claim.

A community says which arrivals on a provider are its own by naming a claim
and the values that count — a Google Workspace domain, an Entra tenant. It
names them itself, and nothing here can tell whether it holds the one it
wrote, so somebody outside the community answers that: support, through a case
raised when the values are written, or the operator on the community's own
page where the deployment runs no intake.

What waits for the answer is ``auto_join`` and nothing else. A connection
still decides who may use its button the moment it is saved, so a community
narrowing its own sign-in is not held up; what it cannot do unanswered is
place somebody in itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.intake import IntakeStream
from app.models.platform.guild import Guild
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.services import audit as audit_service
from app.services.platform.intake import CaseRefs, open_case


def _case_key(connection: GuildProviderConnection) -> str:
    """One case per connection per set of values.

    Keyed on what is being asked about, so saving the same values twice finds
    the case already open rather than raising a second one, and changing them
    asks a new question.
    """
    values = ",".join(sorted(connection.claim_values or ()))
    return f"narrowing:{connection.id}:{connection.claim}:{values}"


async def ask_for_agreement(
    session: AsyncSession, connection: GuildProviderConnection
) -> None:
    """Raise the case that asks whether these values are this community's.

    A no-op on a deployment that has bound no support stream: the operator's
    own page carries the same question there, and a case with nowhere to land
    is not one.
    """
    if connection.claim is None or not connection.claim_values:
        return
    guild = await session.get(Guild, connection.guild_id)
    name = guild.name if guild is not None else f"Community #{connection.guild_id}"
    values = ", ".join(connection.claim_values)
    await open_case(
        IntakeStream.support,
        title=f"{name} claims {values}",
        body=(
            f"{name} says arrivals whose {connection.claim} is one of "
            f"{values} are its own members, and asks that they join on "
            f"arrival. Agreeing places those accounts in this community when "
            f"they sign in; declining leaves the connection working for the "
            f"people already in it.\n\n"
            f"Operator dashboard › Communities › {name} › Manage holds the "
            f"answer."
        ),
        refs=CaseRefs(
            subject_guild=connection.guild_id,
            resource_type="guild_provider_connection",
            resource_id=connection.id,
        ),
        dedupe_key=_case_key(connection),
    )


async def agree(
    session: AsyncSession,
    connection_id: int,
    *,
    agreed: bool,
    actor_user_id: int,
    now: datetime | None = None,
) -> GuildProviderConnection:
    """Record the answer on the connection.

    Withdrawing one leaves the connection and its values exactly as they are;
    what stops is joining people on arrival.
    """
    connection = (
        await session.exec(
            select(GuildProviderConnection).where(
                GuildProviderConnection.id == connection_id
            )
        )
    ).one()
    connection.narrowing_approved_at = (now or datetime.now(UTC)) if agreed else None
    connection.narrowing_approved_by = actor_user_id if agreed else None
    session.add(connection)
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED,
        actor_user_id=actor_user_id,
        guild_id=connection.guild_id,
        target_type="guild_provider_connection",
        target_id=connection.id,
        detail={
            "provider_id": connection.provider_id,
            "narrowing_agreed": agreed,
            "claim": connection.claim,
        },
    )
    await session.commit()
    await session.refresh(connection)
    return connection
