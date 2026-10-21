"""Copies of pitches: the pool, opening a link, expiry and the daily cleanup.

The pool loop keeps empty communities built ahead of time, so opening a link
builds nothing while the visitor waits. Opening one claims a pooled community,
names it after the pitch, makes the visitor an account and seats it as the
copy's guest on the link's terms, and queues an import of the pitch's newest
export into it. Once no guest's time is left, the copy's guest accounts and
the community are deleted. Copies are destroyed and rebuilt, never reused.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import exists, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import webhook_events
from app.core.image_headers import validate_image
from app.db import cohorts, post_commit
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.demo import accounts, pitches, sales
from app.models.platform.demo import DemoSandbox, DemoSandboxState
from app.models.platform.guild import (
    CommunityRole,
    CommunityStatus,
    Guild,
    GuildInvite,
    GuildMembership,
)
from app.models.platform.guild_image import IMAGE_SPECS, GuildImage, GuildImageVariant
from app.models.platform.user import User, UserRole, UserStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services.import_engine import backup as backup_service
from app.services.import_engine import engine as import_engine
from app.services.platform import guild_images, guild_purge
from app.services.platform import guilds as guilds_service
from app.services.platform import legal as legal_service
from app.services.platform import users as users_service

logger = logging.getLogger(__name__)

#: How many built communities wait for visitors.
POOL_SIZE = 20
#: The most pool communities and copies there may be at once.
CEILING = 200
#: How long the daily cleanup keeps an ended link, and an idle pitch.
CLEANUP_AFTER = timedelta(days=30)
#: How often the pool loop runs the cleanup.
CLEANUP_EVERY_SECONDS = 24 * 60 * 60
#: What a pool community is called until a link names it after its pitch.
_POOLED_NAME = "Demo"


#: The import job states a copy's import ends in.
class LinkNotLive(Exception):
    """The link is unknown, revoked, expired or used up, or its pitch has
    nothing published."""


class PoolBusy(Exception):
    """No copy can be handed out right now."""


@dataclass(frozen=True)
class Redemption:
    """What opening a link made: the visitor's account, their copy, and the
    import filling it."""

    user_id: int
    token_version: int
    guild_id: int
    import_job_id: int
    expires_at: datetime


async def redeem(
    session: AsyncSession, token: str, email: str | None = None
) -> Redemption:
    """Open the link ``token`` names: claim a pooled community as the visitor's
    copy, seat their account in it as a guest on the link's terms (its rung,
    for its days), keep ``email`` as a lead on the link when one is given, and
    queue the import of the pitch's newest export, its dates moved from the
    pitch's creation to now. The sales plug-in hears of the link's first
    opening and of a new lead. ``session`` is a platform system session."""
    await set_rls_context(session, Unattributed())
    source_id = (await _live(session, await _link(session, token))).guild_id
    if not await _count(session, DemoSandbox.state == DemoSandboxState.pooled):
        raise PoolBusy
    newest = await pitches.newest_export(source_id)
    if newest is None:
        raise LinkNotLive
    async with import_engine.open_payload(source_id, newest[0]) as bundle:
        if bundle is None:
            raise LinkNotLive
        plan = await asyncio.to_thread(
            backup_service.plan_backup, bundle, existing_initiative_names=set()
        )
        # Checked again once the link is locked.
        link = await _live(session, await _link(session, token, lock=True))
        now = datetime.now(timezone.utc)
        role = CommunityRole(link.guest_role)
        expires_at = now + timedelta(days=link.guest_days or 1)
        sandbox = (
            await session.exec(
                select(DemoSandbox)
                .where(DemoSandbox.state == DemoSandboxState.pooled)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).first()
        if sandbox is None:
            raise PoolBusy
        guild_id = sandbox.guild_id
        source = await session.get(Guild, source_id)
        copy = await session.get(Guild, guild_id)
        if source is None or copy is None:
            raise LinkNotLive
        anchor = source.created_at
        copy.name = source.name
        session.add(copy)
        await _copy_icon(session, source_id=source_id, guild_id=guild_id)

        host = await accounts.demo_host(session)
        visitor = await _visitor(session)
        await guilds_service.ensure_membership(
            session,
            guild_id=guild_id,
            user_id=visitor.id,
            role=role,
            actor_user_id=host.id,
            via="demo",
            invite_id=link.id,
            guest_until=expires_at,
        )
        seated = await pitches.seat_cast(
            session, guild_id=guild_id, people=plan.people, actor_id=host.id
        )
        host_id, visitor_id = host.id, visitor.id
        token_version = visitor.token_version
        async with cohorts.system_session(guild_id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild_id))
            # The import runs as the copy's seat holder, which creating its
            # initiatives asks for.
            job = await backup_service.stage_backup_job(
                guild_session,
                guild_id=guild_id,
                user=visitor if role is CommunityRole.superadmin else host,
                payload=bundle,
                status=ImportJobStatus.queued,
                anchor=anchor,
                people_map=seated,
                join=[visitor_id] if role is not CommunityRole.superadmin else None,
            )
            await guild_session.flush()
            job_id = cast(int, job.id)
            sandbox.state = DemoSandboxState.live
            sandbox.invite_id = link.id
            sandbox.claimed_at = now
            sandbox.import_job_id = job_id
            sandbox.visitor_id = visitor_id
            session.add(sandbox)
            first_open = link.uses == 0
            link.uses += 1
            if link.max_uses is not None and link.uses >= link.max_uses:
                # Used up, it ends now: the cleanup counts from when it did.
                link.expires_at = min(link.expires_at or now, now)
            session.add(link)
            new_lead = email is not None and await sales.keep_lead(
                session, link.id, email
            )
            invite_id = cast(int, link.id)
            # The job is committed only once the claim is.
            await session.commit()
            await guild_session.commit()
        await post_commit.settle(session)

        if role is CommunityRole.superadmin:
            await _hand_over_seat(session, guild_id, host_id)
    if first_open:
        await sales.announce(webhook_events.DEMO_LINK_OPENED, invite_id)
    if new_lead:
        await sales.announce(webhook_events.DEMO_LEAD_LEFT, invite_id)
    return Redemption(
        user_id=visitor_id,
        token_version=token_version,
        guild_id=guild_id,
        import_job_id=job_id,
        expires_at=expires_at,
    )


async def _live(session: AsyncSession, link: GuildInvite | None) -> GuildInvite:
    if (
        link is None
        or link.guest_role is None
        or not guilds_service.invite_is_active(link)
        or not await pitches.is_pitch(session, link.guild_id)
    ):
        raise LinkNotLive
    pitch = await session.get(Guild, link.guild_id)
    if pitch is None or pitch.status != CommunityStatus.active.value:
        raise LinkNotLive
    return link


async def _link(
    session: AsyncSession, token: str, *, lock: bool = False
) -> GuildInvite | None:
    link = await guilds_service.get_invite_by_code(session, code=token, lock=lock)
    if lock and link is not None:
        await session.refresh(link)
    return link


async def _count(session: AsyncSession, *where) -> int:
    return (
        await session.exec(select(func.count()).select_from(DemoSandbox).where(*where))
    ).one()


async def _copy_icon(session: AsyncSession, *, source_id: int, guild_id: int) -> None:
    icon = (
        await session.exec(
            select(GuildImage).where(
                GuildImage.guild_id == source_id,
                GuildImage.variant == GuildImageVariant.icon.value,
            )
        )
    ).first()
    if icon is not None:
        await guild_images.set_images(
            session,
            guild_id=guild_id,
            renditions={
                GuildImageVariant.icon: validate_image(
                    IMAGE_SPECS[GuildImageVariant.icon], icon.data
                )
            },
        )


async def _visitor(session: AsyncSession) -> User:
    """A visitor's account, with a generated handle."""
    user = await accounts.create(session)
    # The demo page carries the notice the Create account button does.
    await legal_service.record_acceptance(session, user_id=user.id)
    return user


async def _hand_over_seat(session: AsyncSession, guild_id: int, host_id: int) -> None:
    """Take the demo host out of the copy, leaving the visitor its seat."""
    await guilds_service.lock_guild_seats(session, guild_id)
    if await guilds_service.must_keep_superadmin(
        session, guild_id=guild_id, user_id=host_id
    ):
        raise RuntimeError(f"community {guild_id} has no other seat holder")
    async with cohorts.system_session(guild_id) as guild_session:
        await set_rls_context(guild_session, SystemGuild(guild_id))
        await guilds_service.remove_user_from_guild(
            guild_session,
            guild_id=guild_id,
            user_id=host_id,
            actor_user_id=None,
            via="demo",
        )
        await guild_session.commit()
        await post_commit.settle(guild_session)
    await session.commit()


@dataclass(frozen=True)
class AccountCopy:
    """The copy a visitor's account is a guest of."""

    guild_id: int
    #: When the visitor's time ends, and the copy and the account with it.
    expires_at: datetime | None
    #: The link, an invite into the pitch, it was opened from, while kept.
    invite_id: int | None
    #: The import filling it, in its own schema.
    import_job_id: int | None


async def account_copy(user_id: int) -> AccountCopy | None:
    """The copy made for this account, or ``None`` for an account no copy was
    made for, a guest someone invited into one included."""
    async with cohorts.system_session(None) as session:
        row = (
            await session.exec(
                select(
                    DemoSandbox.guild_id,
                    GuildMembership.guest_until,
                    DemoSandbox.invite_id,
                    DemoSandbox.import_job_id,
                )
                .join(DemoSandbox, DemoSandbox.guild_id == GuildMembership.guild_id)
                .where(
                    GuildMembership.user_id == user_id,
                    DemoSandbox.visitor_id == user_id,
                    GuildMembership.guest_until.is_not(None),
                )
            )
        ).first()
    return None if row is None else AccountCopy(*row)


async def copy_import(copy: AccountCopy) -> ImportJobStatus:
    """Where the import filling the copy stands; one that is missing counts as
    failed. Read on the system engine routed into the copy: a member visitor
    does not read import jobs."""
    async with cohorts.system_session(copy.guild_id) as session:
        await set_rls_context(session, SystemGuild(copy.guild_id))
        status = (
            await session.exec(
                select(ImportJob.status).where(ImportJob.id == copy.import_job_id)
            )
        ).first()
    return ImportJobStatus.failed if status is None else ImportJobStatus(status)


# --- the pool loop -----------------------------------------------------------


#: When this process last ran the cleanup, on the monotonic clock.
_cleaned_at: float | None = None


async def pool_pass() -> None:
    """One pass of the pool loop: delete the copies whose time is up and the
    leads left too long ago, then build pool communities one at a time while
    the pool is short and the ceiling allows, and once a day run the cleanup.
    One process runs it at a time."""
    global _cleaned_at
    async with cohorts.system_session(None) as lock:
        if not await advisory_lock(lock, LockNamespace.DEMO_POOL, wait=False):
            return
        now = datetime.now(timezone.utc)
        await expire_copies(now)
        await sales.forget_leads(now - sales.LEAD_LIFETIME)
        while await _pool_short():
            await build_copy()
        if _cleaned_at is None or time.monotonic() - _cleaned_at >= (
            CLEANUP_EVERY_SECONDS
        ):
            await clean_up()
            _cleaned_at = time.monotonic()


async def expire_copies(now: datetime) -> None:
    """Delete every copy claimed :data:`pitches.COPY_DAYS` ago, or with no
    guest whose time is left, and then its guests' accounts, with no retention
    window."""
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        due = (
            await session.exec(
                select(DemoSandbox.guild_id).where(
                    DemoSandbox.state == DemoSandboxState.live,
                    or_(
                        DemoSandbox.claimed_at
                        <= now - timedelta(days=pitches.COPY_DAYS),
                        ~exists().where(
                            GuildMembership.guild_id == DemoSandbox.guild_id,
                            GuildMembership.guest_until > now,
                        ),
                    ),
                )
            )
        ).all()
        for guild_id in due:
            try:
                await _destroy_copy(session, guild_id)
            except Exception:
                logger.exception("demo: deleting copy %s failed", guild_id)
                await session.rollback()


async def _destroy_copy(session: AsyncSession, guild_id: int) -> None:
    """Delete the visitor's account, taking its record with it, and then the
    community. Marked deleted first, which closes it to its visitors
    and lets its seat holder go. A step that fails leaves the copy recorded for
    the next pass. The visitor's account is the one the copy recorded, so one
    the guest sweep has already taken out of it is found too."""
    guild = await session.get(Guild, guild_id)
    if guild is None:
        return
    if guild.status != CommunityStatus.deleted.value:
        guild.status = CommunityStatus.deleted.value
        guild.status_changed_at = datetime.now(timezone.utc)
        session.add(guild)
        await session.commit()
    # Only the account the copy was made for: anyone else its guest was
    # invited, and leaves with the community.
    sandbox = await session.get(DemoSandbox, guild_id)
    visitors = [sandbox.visitor_id] if sandbox and sandbox.visitor_id else []
    for user_id in visitors:
        await users_service.hard_delete_user(session, user_id, actor_user_id=None)
    await session.refresh(guild)
    await guild_purge.destroy_now(session, guild)


async def _pool_short() -> bool:
    async with cohorts.system_session(None) as session:
        pooled, total = (
            await session.exec(
                select(
                    func.count().filter(DemoSandbox.state == DemoSandboxState.pooled),
                    func.count(),
                ).select_from(DemoSandbox)
            )
        ).one()
    return pooled < POOL_SIZE and total < CEILING


async def build_copy() -> int:
    """Build one empty pool community with the create sequence, created by
    the demo host. Returns its id."""
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        host = await accounts.demo_host(session)
        guild = await guilds_service.provision_new_guild(
            session, name=_POOLED_NAME, creator=host
        )
        guild_id, host_id = cast(int, guild.id), host.id
        session.add(DemoSandbox(guild_id=guild_id))
        await session.commit()
    await guilds_service.welcome_new_guild(guild_id, owner_user_id=host_id)
    return guild_id


# --- the daily cleanup -------------------------------------------------------


async def clean_up() -> None:
    """Delete each pitch whose links have all been dead, with no live copy,
    for :data:`CLEANUP_AFTER`, with its links (a community nobody ever made a
    link to, such as a seeded one, is left alone), and every account left over
    from an invite: one on the bottom rung that is in no
    community and that somebody can sign in to, other than a sample."""
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        cutoff = datetime.now(timezone.utc) - CLEANUP_AFTER
        host = await accounts.demo_host(session)
        in_use = exists().where(
            GuildInvite.guild_id == Guild.id,
            or_(GuildInvite.expires_at.is_(None), GuildInvite.expires_at > cutoff),
        )
        idle = await session.exec(
            select(Guild.id).where(
                Guild.created_by == host.id,
                Guild.created_at < cutoff,
                ~exists().where(DemoSandbox.guild_id == Guild.id),
                exists().where(GuildInvite.guild_id == Guild.id),
                ~in_use,
            )
        )
        for pitch_id in idle.all():
            try:
                pitch = await session.get(Guild, pitch_id)
                if pitch is not None:
                    await guild_purge.destroy_now(session, pitch)
            except Exception:
                logger.exception("demo: deleting pitch %s failed", pitch_id)
                await session.rollback()
        await session.commit()

        leftovers = (
            await session.exec(
                select(User.id).where(
                    User.role == UserRole.member,
                    User.status != UserStatus.anonymized,
                    ~accounts.unloginable(),
                    ~accounts.sample(),
                    ~exists().where(GuildMembership.user_id == User.id),
                )
            )
        ).all()
        for user_id in leftovers:
            await users_service.hard_delete_user(session, user_id, actor_user_id=None)
