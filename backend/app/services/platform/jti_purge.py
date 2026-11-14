"""One periodic worker that prunes every one-shot replay-guard table, and
the billing change log past its retention.

The guards — the billing service JWT blocklist and the client assertions spent
at the plug-in token endpoint — are the same maintenance concern: shared ``public``
tables of spent one-shot values that grow forever unless swept. They run on one
hourly cadence, so one worker sweeps them all rather than a near-identical
janitor per table (the per-table DELETE lives
in :func:`app.db.jti_blocklist.purge_expired_jtis`).

Each entry is gated by whether its integration is configured: on a self-host
with none of them wired, the worker is a strict no-op (no session opened). The
sweep runs on the system engine (``app_admin`` holds DELETE on each table); the
request path never deletes. Pruning is always safe — a value that old is already
refused at verification, by its own ``exp`` or by the signing freshness window,
before its guard table is consulted, so removing the spent row never re-opens a
replay window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import SQLModel

from app.core.security import plugin_platform_signing_enabled
from app.db.jti_blocklist import purge_expired_jtis
from app.models.platform.billing import BillingJti
from app.models.platform.plugin_assertion_jti import PluginAssertionJti
from app.services.platform import billing_changes
from app.services.platform.billing import billing_inbound_enabled

logger = logging.getLogger(__name__)

# Same cadence as the token purge; each table is cheap to sweep.
JTI_PURGE_POLL_SECONDS = 3600


@dataclass(frozen=True)
class _Blocklist:
    model: type[SQLModel]
    enabled: Callable[[], bool]
    label: str


# One entry per replay guard. Add a table here and it is swept automatically.
# Each entry asks the peer's own module whether it is configured, so a guard and
# its janitor can never disagree about whether that peer exists here.
_BLOCKLISTS: tuple[_Blocklist, ...] = (
    _Blocklist(BillingJti, billing_inbound_enabled, "billing"),
    # A registration exists only where the plug-in platform can sign, so that is
    # also where a plug-in can have presented a client assertion.
    _Blocklist(PluginAssertionJti, plugin_platform_signing_enabled, "plugin-assertion"),
)


async def process_jti_blocklist_purges() -> None:
    active = [b for b in _BLOCKLISTS if b.enabled()]
    if not active:
        return  # self-host default: nothing wired, nothing can have filled
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        for entry in active:
            # Independent per table: one failing sweep must not skip the rest.
            # purge_expired_jtis rolls back its own aborted transaction before
            # raising, so the shared session stays usable for the next entry.
            try:
                purged = await purge_expired_jtis(session, entry.model)
            except Exception:
                logger.exception("jti-purge: %s sweep failed", entry.label)
                continue
            if purged:
                logger.info(
                    "jti-purge: removed %s expired %s rows", purged, entry.label
                )
        if billing_inbound_enabled():
            # The billing change log's retention rides the same pass.
            try:
                pruned = await billing_changes.prune(session)
            except Exception:
                logger.exception("jti-purge: billing change log prune failed")
                await session.rollback()
            else:
                if pruned:
                    logger.info("jti-purge: removed %s old billing changes", pruned)
