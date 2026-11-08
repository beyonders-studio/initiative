"""Rows a community's schema keeps for a while and then lets go.

Each record states its own rule beside its own code: how long the change log
keeps events, which delivery records go with them, which recent views a person
no longer keeps, which sent reminders are past their event. :func:`prepare`
runs every rule in order, in one visit per community and one transaction, when
the community's ``expiry`` timer comes due. Each rule is one statement. Most are a probe of an index when
nothing is due; the recent-views rule ranks the community's views every time,
which is one row per person per thing they opened.

Rules run wherever the community's schema exists, whatever its status: how long
something is kept does not wait for the community to be active again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.user import User
from app.services.guild_sweeps import Visit


@dataclass
class Expiring:
    """What one community's rules share in a pass."""

    now: datetime
    #: Each account whose recent-tabs limit is not the default, with its limit.
    tab_limits: dict[int, int]
    #: Transactions the change log let go in this visit.
    expired_txns: set[int] = field(default_factory=set)


Rule = Callable[[AsyncSession, Expiring], Awaitable[None]]


def _rules() -> tuple[Rule, ...]:
    """Every rule, in the order they run: a record that goes with another runs
    after it."""
    from app.services import notifications
    from app.services.tenant import (
        change_log,
        outbox_poller,
        personal_items,
        plugin_hooks,
    )

    return (
        change_log.expire,
        outbox_poller.expire_deliveries,
        plugin_hooks.expire_deliveries,
        personal_items.expire,
        notifications.expire_reminder_dispatches,
    )


async def _tab_limits() -> dict[int, int]:
    """Each account whose recent-tabs limit is not the default, read once for
    the pass: a community's own session reads no accounts."""
    from app.services.tenant.personal_items import (
        DEFAULT_RECENT_VIEWS,
        clamp_recent_limit,
    )

    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        rows = await session.exec(
            select(col(User.id), col(User.recent_tabs_limit)).where(
                col(User.recent_tabs_limit) != DEFAULT_RECENT_VIEWS
            )
        )
        return {
            user_id: clamp_recent_limit(limit)
            for user_id, limit in rows.all()
            if user_id is not None
        }


def _kept() -> list[Any]:
    """When each record but the recent views next has a row to let go."""
    from app.models.tenant.event_outbox import EventOutbox
    from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
    from app.models.tenant.plugin_event_outbox import PluginEventOutbox
    from app.models.tenant.plugin_hook_delivery import PluginHookDelivery
    from app.services import notifications
    from app.services.tenant import change_log

    return [
        *(
            select(func.min(log.occurred_at) + change_log.RETENTION)
            for log in (EventOutbox, PluginEventOutbox)
        ),
        select(func.min(PluginHookDelivery.expires_at)),
        select(
            func.min(EventReminderDispatch.event_start_at)
            + notifications.EVENT_REMINDER_DISPATCH_RETENTION
        ),
    ]


def next_due(_now: datetime) -> Any:
    """When the community next has something to let go, counting every
    recent view, tabs a person keeps included. Early for those: the visit
    answers exactly, with each person's tab limit."""
    from app.models.tenant.personal_item import PersonalItem
    from app.services.tenant.personal_items import WINDOW

    return select(
        func.least(
            *(part.scalar_subquery() for part in _kept()),
            select(func.min(PersonalItem.viewed_at) + WINDOW).scalar_subquery(),
        )
    )


async def prepare() -> Visit:
    """The visit that runs every rule in one community, with what the pass
    shares read once. It answers when the community next has something to
    let go."""
    from app.services.tenant import personal_items

    now = datetime.now(UTC)
    tab_limits = await _tab_limits()
    rules = _rules()

    async def visit(session: AsyncSession, guild_id: int) -> datetime | None:
        expiring = Expiring(now=now, tab_limits=tab_limits)
        for rule in rules:
            await rule(session, expiring)
        kept = (
            await session.exec(
                select(func.least(*(part.scalar_subquery() for part in _kept())))
            )
        ).first()
        views = await personal_items.next_due(session, expiring)
        return min((due for due in (kept, views) if due is not None), default=None)

    return visit
