"""Reading and writing what an account wants to be told about.

Everything here is about the signed-in account and nobody else, so both routes
resolve their subject from the credential rather than a path parameter.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api.deps import UserSessionDep, get_current_active_user
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_system_session
from app.core.notification_categories import (
    CATEGORY_SPECS,
    ALL_CHANNELS,
    DIGEST_CATEGORIES,
    NotificationCategory,
)
from app.models.platform.guild import Guild, GuildMembership
from app.models.platform.user import User
from app.schemas.platform.notification_prefs import (
    DigestSchedule,
    EmailSchedule,
    CommunityNotificationSettings,
    NotificationCategoryRead,
    NotificationPreferencesRead,
    NotificationPreferencesUpdate,
    PauseRead,
    QuietHours,
)
from app.services import notifications as notifications_service
from app.services import sweep_timers
from app.services.cross_guild import member_guild_ids
from app.services.platform import case_notices, email_outbox
from app.services.platform import notification_prefs as prefs_service

me_router = APIRouter()


def _registry(
    hidden: frozenset[NotificationCategory] = frozenset(),
) -> list[NotificationCategoryRead]:
    return [
        NotificationCategoryRead(
            category=category,
            group=spec.group,
            personal=spec.personal,
            community_scoped=spec.guild_scoped,
            per_community=spec.per_community,
            mutable_channels=[c for c in ALL_CHANNELS if c in spec.mutable_channels],
            defaults={channel: spec.defaults[channel] for channel in ALL_CHANNELS},
        )
        for category, spec in CATEGORY_SPECS.items()
        if category not in hidden
    ]


async def _hidden_for(user: User) -> frozenset[NotificationCategory]:
    """The categories nothing would ever reach ``user`` in, left off their
    page: cases, for somebody who works none."""
    if await case_notices.works_cases(user):
        return frozenset()
    return frozenset({NotificationCategory.cases})


def _section(doc: dict[str, Any], key: str) -> dict[str, Any]:
    value = doc.get(key)
    return value if isinstance(value, dict) else {}


def _retimes(payload: NotificationPreferencesUpdate) -> bool:
    """Whether this write changes *when* mail may go, as against whether."""
    return any(
        (
            payload.email is not None,
            payload.pause_until is not None,
            payload.pause_from is not None,
            payload.clear_pause,
            payload.quiet_hours is not None,
            payload.clear_quiet_hours,
            payload.respect_presence is not None,
        )
    )


def _prune(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop empty branches so the document stays sparse.

    Sparseness is what makes "everything on by default" true by construction,
    so a switch turned off and back on must leave no trace behind.
    """

    def _walk(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        out = {k: _walk(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in ({}, None)}

    return _walk(doc)


@me_router.get("/notification-preferences", response_model=NotificationPreferencesRead)
async def read_my_notification_preferences(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NotificationPreferencesRead:
    """The registry, this account's overrides, and each community's mute and
    rows.

    The registry travels with the response so the settings page renders the
    categories this build has rather than a copy of the list.
    """
    doc = await prefs_service.load_prefs(session, current_user.id)
    rows = (
        await session.exec(
            select(Guild, GuildMembership)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(GuildMembership.user_id == current_user.id)
            .order_by(GuildMembership.position, Guild.name)
        )
    ).all()
    guilds = [
        CommunityNotificationSettings(
            community_id=guild.id,
            community_name=guild.name,
            muted=prefs_service.is_muted(doc, guild.id),
            off=[
                category
                for category, spec in CATEGORY_SPECS.items()
                if spec.per_community
                and prefs_service.row_is_off(doc, guild.id, category)
            ],
        )
        for guild, _membership in rows
    ]
    window = prefs_service.quiet_hours(doc)
    schedule = prefs_service.email_schedule(doc)
    return NotificationPreferencesRead(
        categories=_registry(await _hidden_for(current_user)),
        settings=_section(doc, "categories"),
        quiet_hours=(
            QuietHours(
                start=window[0].strftime("%H:%M"), end=window[1].strftime("%H:%M")
            )
            if window
            else None
        ),
        email=EmailSchedule(
            cadence=schedule.cadence,
            at=schedule.at,
            weekday=schedule.weekday,
            personal_instant=schedule.personal_instant,
        ),
        digests={
            category: DigestSchedule(
                **asdict(prefs_service.digest_schedule(doc, category))
            )
            for category in DIGEST_CATEGORIES
        },
        # A lapsed pause reads as no pause. The sweep that summarises a lift
        # clears the key, but a deployment with nothing to summarise should not
        # show somebody a stand-down that ended last week either.
        # A stand-down that has not started yet is still one to show: it is
        # what somebody booked, and the page says so rather than looking as
        # though the booking did not take.
        pause=(
            PauseRead(since=paused[0], until=paused[1])
            if (paused := prefs_service.pause_window(doc)) is not None
            and paused[1] > datetime.now(timezone.utc)
            else None
        ),
        respect_presence=prefs_service.respects_presence(doc),
        communities=guilds,
    )


@me_router.put("/notification-preferences", response_model=NotificationPreferencesRead)
async def update_my_notification_preferences(
    payload: NotificationPreferencesUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    system_session: Annotated[AsyncSession, Depends(get_system_session)],
) -> NotificationPreferencesRead:
    """Move some switches.

    A partial write, because that is what a settings page sends and because two
    open tabs must not overwrite each other's unrelated rows.
    """
    doc = await prefs_service.load_prefs(session, current_user.id)

    for change in payload.channels:
        spec = CATEGORY_SPECS[change.category]
        if not spec.is_mutable(change.channel):
            # A channel that cannot be switched off is not an error to ask
            # about — it simply does not move.
            continue
        categories = doc.setdefault("categories", {})
        row = categories.setdefault(change.category.value, {})
        if change.enabled == spec.defaults[change.channel]:
            # Back to the default: forget it rather than storing the default,
            # so the document only ever holds real exceptions.
            row.pop(change.channel.value, None)
        else:
            row[change.channel.value] = change.enabled

    for row_change in payload.rows:
        spec = CATEGORY_SPECS[row_change.category]
        if not spec.per_community:
            continue
        # Off is every channel off in that community; on is the account's own
        # settings again, so nothing is kept.
        categories = (
            doc.setdefault("guilds", {})
            .setdefault(str(row_change.community_id), {})
            .setdefault("categories", {})
        )
        if row_change.enabled:
            categories.pop(row_change.category.value, None)
        else:
            categories[row_change.category.value] = {
                channel.value: False for channel in spec.mutable_channels
            }

    for mute in payload.mutes:
        branch = doc.setdefault("guilds", {}).setdefault(str(mute.community_id), {})
        if mute.muted:
            branch["muted"] = True
        else:
            branch.pop("muted", None)

    if payload.clear_quiet_hours:
        doc.pop("quiet_hours", None)
    elif payload.quiet_hours is not None:
        doc["quiet_hours"] = {
            "start": payload.quiet_hours.start,
            "end": payload.quiet_hours.end,
        }

    if payload.email is not None:
        # Stored whole rather than as a partial: the four fields are one
        # answer to one question, and the page sends them together.
        doc["email"] = {
            "cadence": payload.email.cadence.value,
            "at": payload.email.at,
            "weekday": payload.email.weekday,
            "personal_instant": payload.email.personal_instant,
        }

    for category, digest in payload.digests.items():
        if category not in DIGEST_CATEGORIES:
            continue
        doc.setdefault("digests", {})[category.value] = {
            "cadence": digest.cadence.value,
            "at": digest.at,
            "weekday": digest.weekday,
        }

    if payload.clear_pause:
        doc.pop("pause", None)
    elif payload.pause_until is not None:
        doc["pause"] = {
            "since": (payload.pause_from or datetime.now(timezone.utc)).isoformat(),
            "until": payload.pause_until.isoformat(),
        }

    if payload.respect_presence is not None:
        doc["away"] = {"respect": payload.respect_presence}

    doc = _prune(doc)
    await prefs_service.save_prefs(session, current_user.id, doc)

    # Anything already waiting is re-timed against what they just chose, so
    # Resume releases what a pause was holding and a cadence changed at noon
    # applies from noon. The outbox is the worker's table — the request path
    # only ever appends to it — so the re-timing runs on the system engine.
    if _retimes(payload):
        await email_outbox.recompute_pending(
            system_session,
            user_id=current_user.id,
            prefs=doc,
            tz_name=current_user.timezone,
            last_active_at=current_user.last_active_at,
        )
        await system_session.commit()

    # The choice is saved before any queue is emptied, so a queue is only ever
    # discarded for a choice that stuck.
    await session.commit()

    # Each digest goes out on its own schedule, to those who want it.
    moved = {*payload.digests, *(change.category for change in payload.channels)}
    armed = [category.value for category in DIGEST_CATEGORIES if category in moved]
    if armed:
        communities = await member_guild_ids(session, current_user.id)
        for kind in armed:
            await sweep_timers.arm_in(kind, communities)

    # A batch nobody will ever be sent is discarded, not kept: it is guild
    # scoped, so this reaches into each of the account's guild schemas.
    emptied = [
        batch.kind
        for batch in notifications_service.BATCHES
        if not notifications_service.wants_digest(doc, batch.category)
    ]
    if emptied:
        user_id = current_user.id
        await notifications_service.clear_batches_across_guilds(
            session, user_id, emptied
        )

    await session.commit()
    return await read_my_notification_preferences(session, current_user)
