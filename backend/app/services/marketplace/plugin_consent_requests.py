"""Recording an installed plug-in's request to act as a member, and telling them.

The plug-in's own request is routed and stood up by the install seam, which also
resolves the member it names in the install's own sector. What it then writes —
the request row in the community's schema, and the member's notification in
``public`` — is written here on a system session from the community's
cohort: the plug-in's role holds nothing
on either table, and neither write decides what anybody may reach. The row is a
question for the member, and only the member's answer makes it count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select

from app.db import cohorts
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership
from app.models.platform.notification import NotificationType
from app.models.platform.user import User, UserStatus
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.plugin_member_consent import ConsentAccess, ConsentStatus
from app.services.platform import notice_outbox
from app.services.tenant import plugin_member_consents

__all__ = [
    "ConsentMemberNotInInitiative",
    "ConsentRequestLimited",
    "RecordedRequest",
    "consent_target_path",
    "record_request",
]


class ConsentMemberNotInInitiative(Exception):
    """The request names an initiative the member is not in."""


class ConsentRequestLimited(Exception):
    """The request would be a new one, and the install may make no more of
    this member for now."""


@dataclass(frozen=True)
class RecordedRequest:
    """The request as it stands, and whether this call made it."""

    purpose: str | None
    label: str
    initiative_id: int | None
    requested_access: ConsentAccess
    granted_access: ConsentAccess | None
    status: ConsentStatus
    requested_at: datetime
    created: bool


def consent_target_path(install_id: int) -> str:
    """Where the member answers, inside the community: its front page with the
    plug-in's settings open."""
    return f"/?plugin={int(install_id)}"


async def record_request(
    *,
    guild_id: int,
    install_id: int,
    user_id: int,
    purpose: str | None,
    label: str,
    initiative_id: int | None,
    access: ConsentAccess,
    may_create: bool = True,
) -> RecordedRequest | None:
    """Record the request, or find the one already made, and notify the member
    the first time.

    Returns ``None`` when the member no longer belongs to the community or
    their account is not active: there is nobody to ask. A request bound to an
    initiative the member is not in raises :class:`ConsentMemberNotInInitiative`,
    since they could never act there. With ``may_create`` false only a request
    already made is returned, and a new one raises
    :class:`ConsentRequestLimited`.
    """
    async with cohorts.system_session(guild_id) as session:
        belongs = (
            await session.exec(
                select(GuildMembership.user_id)
                .join(User, User.id == GuildMembership.user_id)  # type: ignore[arg-type]
                .where(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.user_id == user_id,
                    User.status == UserStatus.active,
                )
            )
        ).first()
        await session.rollback()
        if belongs is None:
            return None

        await set_rls_context(session, SystemGuild(guild_id))
        if initiative_id is not None:
            in_initiative = (
                await session.exec(
                    select(InitiativeMember.user_id).where(
                        InitiativeMember.initiative_id == initiative_id,
                        InitiativeMember.user_id == user_id,
                    )
                )
            ).first()
            if in_initiative is None:
                await session.rollback()
                raise ConsentMemberNotInInitiative()
        if may_create:
            row, created = await plugin_member_consents.request_consent(
                session,
                plugin_member_consents.ConsentRequest(
                    install_id=install_id,
                    user_id=user_id,
                    purpose=purpose,
                    label=label,
                    initiative_id=initiative_id,
                    access=access,
                ),
            )
        else:
            existing = await plugin_member_consents.find_consent(
                session, install_id=install_id, user_id=user_id, purpose=purpose
            )
            if existing is None:
                raise ConsentRequestLimited()
            row, created = existing, False
        plugin_name = (
            await session.exec(
                select(GuildPlugin.name).where(GuildPlugin.id == install_id)
            )
        ).first()
        recorded = RecordedRequest(
            purpose=row.purpose,
            label=row.label,
            initiative_id=row.initiative_id,
            requested_access=ConsentAccess(row.requested_access),
            granted_access=(
                ConsentAccess(row.granted_access) if row.granted_access else None
            ),
            status=row.status,
            requested_at=row.requested_at,
            created=created,
        )
        consent_id = row.id
        await session.commit()

        if created:
            # Out of the community's schema: the notification is the member's
            # own row in ``public``.
            await set_rls_context(session, Unattributed())
            await notice_outbox.enqueue(
                session,
                [
                    notice_outbox.row(
                        user_id,
                        guild_id,
                        NotificationType.plugin_consent_requested,
                        {
                            "community_id": guild_id,
                            "plugin_id": install_id,
                            "plugin_name": plugin_name or "",
                            "consent_id": consent_id,
                            "label": recorded.label,
                            "access": recorded.requested_access.value,
                            "target_path": consent_target_path(install_id),
                        },
                    )
                ],
            )
            await session.commit()
    return recorded
