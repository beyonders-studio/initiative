"""How many people engaged with each item lately, as a coarse level.

Search orders by the level, read through :func:`level_of` beside the item and
gated like the item itself; it only reorders what a search already found. The hourly pass works it out in each active community from two records
the community already keeps, and writes nothing else:

- **Views**: each person's latest open of each item, from ``personal_items``.
- **Contributions**: each change a person made, from the change log. A change to
  something that has no level of its own (a comment, a reaction) counts for the
  innermost item it sits in (``content_item_of``, which the feed asks too).

Each person counts once per item, at their weightiest engagement, decayed by
age, so opening something forty times is opening it once. Somebody who turned
``count_toward_engagement_ranking`` off is not counted at all. An item gets a level
only once :data:`MIN_PEOPLE` different people engaged with it, and only the
level is kept: no person, no count.

A community that turned ranking off (while it holds the ``restrictions``
option), or a deployment that did, holds no levels: the pass clears them.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    Text,
    bindparam,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.dialects.postgresql import ARRAY

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.request_context import Unattributed
from app.db.session import routed_guild_id, set_rls_context
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild
from app.models.platform.user import User
from app.models.tenant.engagement_level import LEVEL_MAX, EngagementLevel
from app.models.tenant.personal_item import ViewSource
from app.services.guild_sweeps import Visit
from app.services.platform import rules
from app.services.tenant.personal_items import WINDOW

#: How fast an engagement fades: one this old counts half as much.
HALF_LIFE = timedelta(days=2)
#: What opening an item counts for.
VIEW_WEIGHT = 1.0
#: Where an open came from a surface that orders by the level, so it says less
#: about the item: search and the activity feed.
ORDERED_SOURCES = (ViewSource.search, ViewSource.feed)
#: What such an open counts for.
ORDERED_VIEW_WEIGHT = 0.5
#: What changing it counts for: acting on something says more than opening it.
CONTRIBUTION_WEIGHT = 2.0
#: The fewest different people an item needs before it has a level.
MIN_PEOPLE = 3
#: How much each level lifts a match: its rank times ``1 + BOOST × level``.
BOOST = 0.1


def level_of(entity_type: Any, entity_id: Any) -> ColumnElement[int]:
    """An item's level, 0 where it has none, read under the reader's own
    policies: a level is seen only beside an item the reader can read."""
    return func.coalesce(
        select(EngagementLevel.level)
        .where(
            EngagementLevel.entity_type == entity_type,
            EngagementLevel.entity_id == entity_id,
        )
        .scalar_subquery(),
        0,
    )


def boosted(rank: Any, level: Any) -> ColumnElement[float]:
    """A match's rank, lifted by its level. It reorders matches and never adds
    one."""
    return rank * (1 + BOOST * level)


#: One statement per community: score every item engaged with inside
#: :data:`WINDOW`, write the levels that changed and drop the ones that went.
#: An item counts only while it exists, which the schema's own per-kind gate
#: answers for the system engine.
_LEVELS = text(
    """
    WITH engaged AS (
        SELECT v.user_id, v.entity_type AS kind, v.entity_id AS id,
               v.viewed_at AS at,
               CASE WHEN v.view_source = ANY (:ordered) THEN :ordered_view_weight
                   ELSE :view_weight END AS weight
        FROM personal_items v
        WHERE v.viewed_at > :since
          AND v.user_id <> ALL (:uncounted)
      UNION ALL
        SELECT o.actor_user_id, t.kind, t.id, o.occurred_at, :contribution_weight
        FROM event_outbox o
        CROSS JOIN LATERAL content_item_of(o.resource_type, o.resource_id, o.parents) t
        WHERE o.occurred_at > :since
          AND o.actor_user_id IS NOT NULL
          AND o.actor_install_id IS NULL
          AND o.actor_user_id <> ALL (:uncounted)
    ),
    per_person AS (
        SELECT kind, id,
               max(weight * power(2.0, -extract(epoch FROM (:now - at)) / :half_life))
                   AS c
        FROM engaged
        GROUP BY kind, id, user_id
    ),
    scored AS (
        SELECT kind AS entity_type, id AS entity_id,
               least(:level_max, floor(ln(1 + sum(c)) / ln(2)))::smallint AS level
        FROM per_person
        GROUP BY kind, id
        HAVING count(*) >= :min_people
    ),
    levelled AS (
        SELECT s.entity_type, s.entity_id, s.level
        FROM scored s
        WHERE s.level >= 1
          AND entity_access(
              s.entity_type, s.entity_id, false, false, (SELECT current_standing())
          )
    ),
    written AS (
        INSERT INTO engagement_levels (entity_type, entity_id, level, computed_at)
        SELECT entity_type, entity_id, level, :now FROM levelled
        ON CONFLICT (entity_type, entity_id) DO UPDATE
            SET level = EXCLUDED.level, computed_at = EXCLUDED.computed_at
            WHERE engagement_levels.level IS DISTINCT FROM EXCLUDED.level
    )
    DELETE FROM engagement_levels e
    WHERE NOT EXISTS (
        SELECT 1 FROM levelled l
        WHERE l.entity_type = e.entity_type AND l.entity_id = e.entity_id
    )
    """
).bindparams(
    bindparam("uncounted", type_=ARRAY(Integer)),
    bindparam("now", type_=DateTime(timezone=True)),
    bindparam("since", type_=DateTime(timezone=True)),
    bindparam("view_weight", type_=Float),
    bindparam("ordered_view_weight", type_=Float),
    bindparam("ordered", type_=ARRAY(Text)),
    bindparam("contribution_weight", type_=Float),
    bindparam("half_life", type_=Float),
    bindparam("level_max", type_=Integer),
    bindparam("min_people", type_=Integer),
)


async def _community(session: AsyncSession, guild_id: int) -> tuple[bool, bool]:
    """Whether the community leaves ranking on (its own answer, which applies
    while it holds the option it needs), and whether its members can read it."""
    live = (
        await session.exec(
            select(Guild.status.in_(LIVE_STATUS_VALUES)).where(  # type: ignore[attr-defined]
                Guild.id == guild_id
            )
        )
    ).one_or_none()
    if live is None:
        return False, False
    allowed = await rules.community_value(session, guild_id, "allow_engagement_ranking")
    return bool(allowed), bool(live)


async def prepare() -> Visit:
    """The visit that works out one community's levels, with the deployment's
    answer and the accounts that asked not to be counted read once for the
    pass. It runs wherever the community's schema exists: levels are cleared
    wherever ranking is off, and worked out where members can read."""
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        enabled = (await rules.platform_values(session))["engagement_ranking_enabled"]
        uncounted = list(
            (
                await session.exec(
                    select(User.id).where(
                        User.count_toward_engagement_ranking.is_(False)  # type: ignore[attr-defined]
                    )
                )
            )
            .scalars()
            .all()
        )

    async def visit(session: AsyncSession, guild_id: int) -> None:
        if not await advisory_lock(
            session, LockNamespace.ENGAGEMENT_LEVELS, guild_id, wait=False
        ):
            return
        allowed, live = await _community(session, guild_id)
        if not (enabled and allowed):
            await session.exec(delete(EngagementLevel))  # type: ignore[arg-type]
            return
        if not live:
            return
        now = datetime.now(timezone.utc)
        await session.exec(
            _LEVELS,  # type: ignore[arg-type]
            params={
                "uncounted": uncounted,
                "now": now,
                "since": now - WINDOW,
                "view_weight": VIEW_WEIGHT,
                "ordered_view_weight": ORDERED_VIEW_WEIGHT,
                "ordered": [source.value for source in ORDERED_SOURCES],
                "contribution_weight": CONTRIBUTION_WEIGHT,
                "half_life": HALF_LIFE.total_seconds(),
                "level_max": LEVEL_MAX,
                "min_people": MIN_PEOPLE,
            },
        )

    return visit


async def purge_for_entities(
    session: AsyncSession, entity_type: str, entity_ids: Iterable[int]
) -> None:
    """Drop the levels of these, for a purge: ``entity_id`` is a weak
    reference, so nothing carries the rows out with the entity.

    The rows go in a transaction of their own, so the pass's lock is taken in
    the purge's first and held until it commits: no pass works out a level for
    something while it is being purged."""
    ids = tuple(entity_ids)
    if not ids:
        return
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        await advisory_lock(session, LockNamespace.ENGAGEMENT_LEVELS, guild_id)
    await cohorts.exec_as_system(
        session,
        delete(EngagementLevel).where(  # type: ignore[arg-type]
            EngagementLevel.entity_type == entity_type,
            EngagementLevel.entity_id.in_(ids),  # type: ignore[attr-defined]
        ),
    )
