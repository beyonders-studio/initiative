"""One walk over the communities, for every background sweep that visits them.

A sweep that works community by community (publishing scheduled posts, purging
trash, delivering webhooks, claiming data jobs) hands its per-community function
to :func:`each_guild`, which reads the communities once and visits each on a
system session from that community's cohort. Each visit is routed into the
community, run and committed on its own, so one that fails is rolled back and
logged and the rest carry on.

A cohort's communities are visited one after another on one session, and the
cohorts side by side, a few at a time, so a pass holds at most one connection
per cohort.

Work armed by a timer (``app.services.sweep_timers``) is handed in as each
community's own visits, and visits just those.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from enum import Enum
from typing import NamedTuple

from sqlalchemy import text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import audit_context, metrics
from app.db import cohorts
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import LIVE_STATUS_VALUES, CommunityStatus, Guild

logger = logging.getLogger(__name__)

#: How many cohorts a pass visits at once. Each holds one system connection
#: while its communities are visited.
COHORTS_AT_ONCE = 4


class Scope(Enum):
    """Which communities a visit is for."""

    #: Communities taking writes.
    ACTIVE = "active"
    #: Communities their members can still read: active and read-only.
    LIVE = "live"
    #: Every community whose schema exists, whatever its status. A read-only,
    #: suspended, held or deleted-but-retained community keeps its schema, and
    #: what its jobs left behind, until it is purged.
    PROVISIONED = "provisioned"
    #: The operations community while it takes writes: the one active
    #: community whose schema has the operations tables
    #: (``app.db.tenancy.OPERATIONS_TABLES``).
    OPERATIONS = "operations"

    def admits(self, status: str, *, provisioned: bool, operations: bool) -> bool:
        if self is Scope.ACTIVE:
            return status == CommunityStatus.active.value
        if self is Scope.LIVE:
            return status in LIVE_STATUS_VALUES
        if self is Scope.OPERATIONS:
            return operations and status == CommunityStatus.active.value
        return provisioned


#: ``(session, guild_id)``: one sweep's work in one community, on a session
#: routed into it. What it returns is ignored.
Visit = Callable[[AsyncSession, int], Awaitable[object]]


class Scan(NamedTuple):
    """A sweep in two halves: a visit to each community it admits, and what it
    does with what the visits found once the pass has been everywhere."""

    scope: Scope
    visit: Visit
    finish: Callable[[], Awaitable[None]]


async def each_guild(
    visits: Sequence[tuple[Scope, Visit]],
    *,
    name: str,
    only: Iterable[int] | None = None,
    scans: Sequence[Scan] = (),
    planned: Mapping[int, Sequence[tuple[Scope, Visit]]] | None = None,
) -> None:
    """Run every visit in every community its scope admits, then finish each
    scan.

    ``planned`` adds each community's own visits, and restricts the pass to
    those communities. ``only`` restricts the pass to those communities.
    ``name`` labels the log lines and the pass-duration metric."""
    started = time.monotonic()
    every = [*visits, *((scan.scope, scan.visit) for scan in scans)]
    plan = planned or {}
    if planned is not None:
        only = list(planned)
    all_visits = [*every, *(pair for own in plan.values() for pair in own)]
    by_cohort: dict[int, list[tuple[int, str, bool, bool]]] = {}
    for community in await _communities(all_visits, only):
        by_cohort.setdefault(cohorts.cohort_of(community[0]), []).append(community)
    limit = asyncio.Semaphore(COHORTS_AT_ONCE)

    async def visit_cohort(communities: list[tuple[int, str, bool, bool]]) -> None:
        try:
            async with limit, cohorts.system_session(communities[0][0]) as session:
                for guild_id, status, provisioned, operations in communities:
                    # Ids repeat across schemas.
                    session.expunge_all()
                    for scope, visit in [*plan.get(guild_id, ()), *every]:
                        if scope.admits(
                            status, provisioned=provisioned, operations=operations
                        ):
                            await _visit(session, visit, guild_id, name=name)
        except Exception:
            logger.exception(
                "%s: cohort %s failed", name, cohorts.cohort_of(communities[0][0])
            )

    await asyncio.gather(*(visit_cohort(c) for c in by_cohort.values()))
    for scan in scans:
        try:
            await scan.finish()
        except Exception:
            logger.exception("%s: finishing a scan failed", name)
    metrics.sweep_pass_duration.labels(name).observe(time.monotonic() - started)


async def _communities(
    visits: Sequence[tuple[Scope, Visit]], only: Iterable[int] | None
) -> list[tuple[int, str, bool, bool]]:
    """Each community in the pass, with its status, whether its schema
    exists, and whether that schema has the operations tables."""
    from app.db.operations_schema import operations_schemas
    from app.db.schema_provisioning import guild_schema_name

    statement = select(Guild.id, Guild.status).order_by(col(Guild.id).asc())
    if only is not None:
        statement = statement.where(col(Guild.id).in_(list(only)))
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        rows = (await session.exec(statement)).all()
        schemas: set[str] = set()
        if any(scope is Scope.PROVISIONED for scope, _visit in visits):
            schemas = set(
                (await session.exec(text("SELECT nspname FROM pg_namespace"))).scalars()
            )
        operations: set[str] = set()
        if any(scope is Scope.OPERATIONS for scope, _visit in visits):
            operations = await operations_schemas(await session.connection())
    return [
        (
            guild_id,
            status,
            guild_schema_name(guild_id) in schemas,
            guild_schema_name(guild_id) in operations,
        )
        for guild_id, status in rows
        if guild_id is not None
    ]


async def _visit(
    session: AsyncSession, visit: Visit, guild_id: int, *, name: str
) -> None:
    with audit_context.visiting(guild_id):
        try:
            await set_rls_context(session, SystemGuild(guild_id))
            await visit(session, guild_id)
            await session.commit()
        except Exception:
            logger.exception("%s: visit failed", name)
            await session.rollback()
