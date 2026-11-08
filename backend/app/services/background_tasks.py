from __future__ import annotations

import asyncio
import logging
from functools import partial
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.core import audit_context

logger = logging.getLogger(__name__)

#: How often the hourly pass runs.
HOURLY_PASS_SECONDS = 3600


class Loop:
    """One background worker's loop.

    Runs its work every ``interval`` seconds, and soon after :meth:`wake` is
    called. A woken pass waits ``settle`` seconds first, so wakes arriving
    together are served by one pass. Without an ``interval`` it runs only when
    woken. A pass that fails is logged, and the loop carries on.
    """

    def __init__(
        self, name: str, *, interval: float | None = None, settle: float = 0.0
    ) -> None:
        self.name = name
        self.interval = interval
        self.settle = settle
        self._woken = asyncio.Event()

    def wake(self) -> None:
        """Ask for a pass. Returns at once."""
        self._woken.set()

    async def run(self, work: Callable[[], Awaitable[object]]) -> None:
        logger.info("%s worker started (interval=%ss)", self.name, self.interval)
        try:
            # A timed loop starts with a pass; one that is only woken waits.
            if self.interval is None:
                await self._wait()
            while True:
                self._woken.clear()
                with audit_context.job(self.name):
                    try:
                        await work()
                    except Exception:  # pragma: no cover
                        logger.exception("%s worker encountered an error", self.name)
                await self._wait()
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("%s worker cancelled", self.name)
            raise

    async def _wait(self) -> None:
        try:
            await asyncio.wait_for(self._woken.wait(), timeout=self.interval)
        except TimeoutError:
            return
        await asyncio.sleep(self.settle)


async def hourly_pass() -> None:
    """The settled mail and read notifications past their keeping, and the
    security-signal windows no rule can still read. Work in the communities
    runs on timers (``app.services.sweep_timers``)."""
    from app.services import notifications
    from app.services.platform import security_signals

    await notifications.drop_spent_notifications(now=datetime.now(timezone.utc))
    await security_signals.sweep()


def start_background_tasks() -> list[asyncio.Task]:
    from app.services import sweep_timers
    from app.services.notifications import (
        process_hold_summaries,
        HOLD_SUMMARY_POLL_SECONDS,
    )
    from app.services.platform import email_outbox, notice_outbox
    from app.services.platform import security_signals
    from app.services.platform.presence import (
        ACTIVITY_FLUSH_SECONDS,
        process_activity_flush,
    )
    from app.services.oidc_refresh import (
        process_oidc_refresh_sync,
        OIDC_SYNC_POLL_SECONDS,
    )
    from app.services.platform.announcements import (
        process_announcement_image_purge,
        IMAGE_PURGE_POLL_SECONDS,
    )
    from app.services.platform.guild_purge import (
        GUILD_PURGE_POLL_SECONDS,
        process_guild_purges,
    )
    from app.services.platform.account_purge import (
        ACCOUNT_PURGE_POLL_SECONDS,
        process_account_purges,
    )
    from app.services.platform.identity_refs import (
        IDENTITY_REF_SWEEP_POLL_SECONDS,
        process_identity_ref_sweep,
    )
    from app.services.tenant.room_sink import ROOM_SWEEP_SECONDS, process_room_sweep
    from app.services.platform.user_tokens import (
        process_expired_token_purge,
        TOKEN_PURGE_POLL_SECONDS,
    )
    from app.services.auth.sessions import (
        SESSION_PURGE_POLL_SECONDS,
        process_dead_session_purge,
    )
    from app.services.platform.jti_purge import (
        process_jti_blocklist_purges,
        JTI_PURGE_POLL_SECONDS,
    )
    from app.services.platform.access_grants import (
        GRANT_EXPIRY_POLL_SECONDS,
        process_grant_expiry,
    )
    from app.services.platform.guests import (
        GUEST_EXPIRY_POLL_SECONDS,
        end_expired_guests,
    )
    from app.services.auth.held_changes import (
        HOLD_SWEEP_POLL_SECONDS,
        process_due_holds,
    )
    from app.services.platform.ticket_notices import (
        TICKET_NOTICE_POLL_SECONDS,
        process_ticket_notices,
    )
    from app.services.marketplace.tuf_registry import (
        process_registry_refresh,
        registry_available,
    )

    tasks = [
        # Every sweep that works community by community, in only the
        # communities whose timers have come due.
        asyncio.create_task(sweep_timers.loop.run(sweep_timers.process_due_timers)),
        # The sweeps that call another server, so none of the above waits on one.
        asyncio.create_task(
            sweep_timers.outward_loop.run(
                partial(sweep_timers.process_due_timers, outward=True)
            )
        ),
        # A catalog change arms the communities with an install of it.
        asyncio.create_task(sweep_timers.catalog_loop.run(sweep_timers.watch_catalog)),
        asyncio.create_task(
            Loop("hourly", interval=HOURLY_PASS_SECONDS).run(hourly_pass)
        ),
        asyncio.create_task(
            Loop("hold-summary", interval=HOLD_SUMMARY_POLL_SECONDS).run(
                process_hold_summaries
            )
        ),
        # Notices, delivered as they are written.
        asyncio.create_task(
            notice_outbox.loop.run(notice_outbox.process_notice_outbox)
        ),
        # The one way notification email leaves the building.
        asyncio.create_task(email_outbox.loop.run(email_outbox.process_email_outbox)),
        # What the presence roll has seen, written where another process can
        # read it. The roll is this worker's own memory; delivery decides
        # elsewhere.
        asyncio.create_task(
            Loop("activity-flush", interval=ACTIVITY_FLUSH_SECONDS).run(
                process_activity_flush
            )
        ),
        # What the security rules counted in this process, added to the
        # deployment's totals, and a case opened for any key that crossed.
        asyncio.create_task(
            Loop(
                "security-signals",
                interval=security_signals.FLUSH_INTERVAL.total_seconds(),
            ).run(security_signals.process_flush)
        ),
        asyncio.create_task(
            Loop("oidc-refresh-sync", interval=OIDC_SYNC_POLL_SECONDS).run(
                process_oidc_refresh_sync
            )
        ),
        asyncio.create_task(
            Loop("guild-purge", interval=GUILD_PURGE_POLL_SECONDS).run(
                process_guild_purges
            )
        ),
        asyncio.create_task(
            Loop("account-purge", interval=ACCOUNT_PURGE_POLL_SECONDS).run(
                process_account_purges
            )
        ),
        asyncio.create_task(
            Loop("identity-ref-sweep", interval=IDENTITY_REF_SWEEP_POLL_SECONDS).run(
                process_identity_ref_sweep
            )
        ),
        asyncio.create_task(
            Loop("announcement-image-purge", interval=IMAGE_PURGE_POLL_SECONDS).run(
                process_announcement_image_purge
            )
        ),
        # The room sink's backstop. The prompt path is the capture's own
        # pg_notify; this covers the hints raised while a worker's bus
        # connection was rebuilding, and reads nothing for a guild this
        # process holds no socket for.
        asyncio.create_task(
            Loop("room-sweep", interval=ROOM_SWEEP_SECONDS).run(process_room_sweep)
        ),
        asyncio.create_task(
            Loop("token-purge", interval=TOKEN_PURGE_POLL_SECONDS).run(
                process_expired_token_purge
            )
        ),
        asyncio.create_task(
            Loop("jti-purge", interval=JTI_PURGE_POLL_SECONDS).run(
                process_jti_blocklist_purges
            )
        ),
        asyncio.create_task(
            Loop("session-purge", interval=SESSION_PURGE_POLL_SECONDS).run(
                process_dead_session_purge
            )
        ),
        asyncio.create_task(
            Loop("grant-expiry", interval=GRANT_EXPIRY_POLL_SECONDS).run(
                process_grant_expiry
            )
        ),
        asyncio.create_task(
            Loop("guest-expiry", interval=GUEST_EXPIRY_POLL_SECONDS).run(
                end_expired_guests
            )
        ),
        asyncio.create_task(
            Loop("held-changes", interval=HOLD_SWEEP_POLL_SECONDS).run(
                process_due_holds
            )
        ),
        asyncio.create_task(
            Loop("ticket-notices", interval=TICKET_NOTICE_POLL_SECONDS).run(
                process_ticket_notices
            )
        ),
    ]

    from app.core.config import settings

    if settings.DEMO_MODE:
        from app.demo.copies import pool_pass

        tasks.append(asyncio.create_task(Loop("demo-pool", interval=60).run(pool_pass)))

    # The marketplace registry needs a trusted root. A build without one runs
    # no worker at all. Each pass asks the platform switch first, so turning
    # the registry off stops the fetching without a restart. The loop runs its
    # first pass immediately, so boot is also the first refresh; the catalog
    # this build ships is already seeded by then and the registry adds to it
    # through the same writer.
    if registry_available():
        tasks.append(
            asyncio.create_task(
                Loop(
                    "marketplace-registry",
                    interval=settings.MARKETPLACE_REGISTRY_TTL_SECONDS,
                ).run(process_registry_refresh)
            )
        )

    # Encrypting what was stored before STORAGE_ENCRYPTION was set. A
    # deployment that leaves it unset runs no worker. The first pass is at
    # boot; once every community is caught up a pass is one query.
    if settings.STORAGE_ENCRYPTION:
        from app.services import storage_encryption

        tasks.append(
            asyncio.create_task(
                Loop(
                    "storage-encryption", interval=storage_encryption.PASS_SECONDS
                ).run(storage_encryption.encrypt_existing)
            )
        )

    return tasks
