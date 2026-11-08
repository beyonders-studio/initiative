"""What the sales plug-in reaches on the demo, and the addresses visitors leave.

The plug-in is an install in the operations community whose token holds the
community-admin standing there (``InstallLevel.community_admin``). It names pitches and links by the references the plug-in
holds for them (``identity_refs``, purpose ``plugin``, the plug-in as sector):
a pitch is its community's reference, a link a ``demo_link`` one. Nothing here
names a person.

A visitor may leave an address on the link they opened. It is kept as a lead,
apart from any account, for 30 days, and every read of the link hands out the
leads it holds. The plug-in hears of a link's first opening and of each new lead by the demo's
events (``webhook_events.DEMO_EVENT_TYPES``), each carrying only the link's
reference, delivered through the community's plug-in outbox to the
subscriptions of every install there whose grant holds that standing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import (
    SALT_EMAIL,
    decrypt_field,
    encrypt_field,
    hash_email,
    normalize_email,
)
from app.core.plugin_scopes import LEVEL_SCOPES, InstallLevel
from app.db import cohorts
from app.db.guild_standing import ISSUABLE_SCOPES_SQL
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.demo import pitches
from app.models.platform.demo import DemoLead, LinkState
from app.models.platform.guild import GuildInvite
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.marketplace import plugin_refs
from app.services.platform import identity_refs
from app.services.platform.intake import configured_operations_guild_id
from app.services.tenant import plugin_channels

logger = logging.getLogger(__name__)

#: How long a lead is kept.
LEAD_LIFETIME = timedelta(days=30)

#: The installs in the routed community whose grant issues ``:scope``.
_SCOPED_INSTALLS_SQL_TEXT = (
    f"SELECT a.id, a.definition -> 'service' ->> 'public_id' AS public_id "
    f"FROM guild_plugins a "
    f"WHERE a.enabled AND :scope = ANY ({ISSUABLE_SCOPES_SQL}) "
    f"AND a.definition -> 'service' ->> 'public_id' IS NOT NULL ORDER BY a.id"
)
_SCOPED_INSTALLS_SQL = text(_SCOPED_INSTALLS_SQL_TEXT)
#: The community-admin standing, which the demo's events need.
_ADMIN_SCOPE = LEVEL_SCOPES[InstallLevel.community_admin]


@dataclass(frozen=True)
class SalesInstall:
    """The install a request comes from, in the operations community."""

    guild_id: int
    install_id: int
    #: The plug-in, whose sector the install's references are in.
    public_id: str

    async def name(self, entity: IdentityEntity, entity_id: int) -> str:
        """What this install's plug-in calls the entity, minting it on first
        use."""
        return await plugin_refs.ensure_plugin_entity_ref(
            guild_id=self.guild_id,
            public_id=self.public_id,
            entity=entity,
            entity_id=entity_id,
        )

    async def resolve(
        self, session: AsyncSession, entity: IdentityEntity, refs: Sequence[str]
    ) -> dict[str, int]:
        """The entities of kind ``entity`` that ``refs`` name in this install's
        sector, by reference. A reference that names nothing here is left
        out."""
        return {
            row.ref: row.entity_id
            for row in await identity_refs.resolve_refs(session, refs=refs)
            if row.purpose == IdentityPurpose.plugin
            and row.entity_type == entity
            and row.sector_guild_id == self.guild_id
            and row.sector_plugin == self.public_id
        }


@dataclass(frozen=True)
class LeadRead:
    id: int
    email: str
    created_at: datetime


@dataclass(frozen=True)
class LinkReport:
    """What happened on one link, and the leads left on it."""

    invite_id: int
    state: LinkState
    redemption_count: int
    leads: list[LeadRead]


async def admin_installs(guild_id: int) -> list[tuple[int, str]]:
    """The installs in the community whose grant issues the community-admin
    standing now, each with its plug-in's ``public_id``, read on the system
    engine routed into it."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id, read_only=True))
        return [
            (int(row.id), str(row.public_id))
            for row in await session.exec(
                _SCOPED_INSTALLS_SQL, params={"scope": _ADMIN_SCOPE}
            )
        ]


async def keep_lead(session: AsyncSession, invite_id: int, email: str) -> bool:
    """Keep ``email`` as a lead on the link ``invite_id``, staged. ``False`` when this
    address was already left on it. ``session`` is a platform system
    session."""
    stored = await session.exec(
        pg_insert(DemoLead.__table__)
        .values(
            invite_id=invite_id,
            email_hash=hash_email(email),
            email_encrypted=encrypt_field(normalize_email(email), SALT_EMAIL),
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_demo_leads_invite_email")
        .returning(DemoLead.__table__.c.id)
    )
    return stored.first() is not None


async def read_links(
    session: AsyncSession, invite_ids: Sequence[int]
) -> list[LinkReport]:
    """What happened on each link, with the leads left on it, oldest first.
    ``session`` is a platform system session."""
    now = datetime.now(UTC)
    links = (
        await session.exec(
            select(GuildInvite)
            .where(GuildInvite.id.in_(invite_ids))
            .order_by(GuildInvite.id)
        )
    ).all()
    leads = (
        await session.exec(
            select(DemoLead)
            .where(DemoLead.invite_id.in_([link.id for link in links]))
            .order_by(DemoLead.created_at, DemoLead.id)
        )
    ).all()
    return [
        LinkReport(
            invite_id=cast(int, link.id),
            state=pitches.link_state(link, now),
            redemption_count=link.uses,
            leads=[
                LeadRead(
                    id=cast(int, lead.id),
                    email=decrypt_field(lead.email_encrypted, SALT_EMAIL),
                    created_at=lead.created_at,
                )
                for lead in leads
                if lead.invite_id == link.id
            ],
        )
        for link in links
    ]


async def forget_leads(before: datetime) -> None:
    """Delete the leads left before ``before``."""
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        await session.exec(delete(DemoLead).where(DemoLead.created_at < before))
        await session.commit()


async def announce(event_type: str, invite_id: int) -> None:
    """Tell every install in the operations community whose grant holds the
    community-admin standing that ``event_type`` happened on the link, naming the link
    by that install's reference for it. Reports rather than raises: what
    happened on the link is kept either way, and the plug-in reads it with
    the link."""
    try:
        guild_id = await configured_operations_guild_id()
        if guild_id is None:
            return
        installs = await admin_installs(guild_id)
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            for install_id, public_id in installs:
                ref = await SalesInstall(guild_id, install_id, public_id).name(
                    IdentityEntity.demo_link, invite_id
                )
                await plugin_channels.stage_event(
                    session,
                    install_id=install_id,
                    event_type=event_type,
                    payload={"link_ref": ref},
                )
            await session.commit()
    except Exception:
        logger.exception("demo: announcing %s failed", event_type)
