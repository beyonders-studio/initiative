"""What changed lately in a community that this reader would want to know.

One entry per item: the items people changed in the last week, read from the
change log on the reader's own session, so its read policy (the initiative and
the sharing of the tool a change names) decides which changes are seen at all.
Each change counts for the item ``content_item_of`` names, the same item the
engagement levels count it for, and an item is shown only where its search
entry is readable too, which is also where its title comes from.

An entry is ordered by how recent its latest change is, the item's engagement
level, and how involved the reader is with it: made it or named on it,
changed it, subscribed to it or its tool, opened it, bookmarked its tool.

    2^(−age / HALF_LIFE) × boosted(1, level) × relevance

Only people's changes make entries, never a plug-in's, and never the reader's
own: what the reader did says the item is theirs, which lifts it, and nothing
more. Some changes are not activity at all (a reaction, a read, a vote): they
count toward the level and make no entry.

The newest :data:`CANDIDATE_CHANGES` changes are the candidates, read through
the change log's index on time, so a busy community's request reads a bounded
slice of the week. Older changes have faded by then anyway. The scan is held
to the tools the reader can open, read first from the search index under their
own policies, so a change in a tool they cannot open is passed over by a
comparison of ids rather than a sharing check: a reader who can open little of
a busy community does not pay for the rest of it.

Whether the reader made an item or is assigned to it is asked of each kind's
own table (``personal_items.NAMING``, the rule subscriptions are worked out by),
once per kind among the candidates, and the candidates are scored here: asked
inside the statement, every kind's table and its policies would be planned on
every request whichever kinds were there. Unsubscribing from an item takes back
what made it theirs.

The same statement, over a batch of transactions rather than a window, is what
subscribers are told from (``subscription_notices``), read as each of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Integer, Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.initiative_rls import CONTENT_KIND_TABLES
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.search_entry import SearchEntry
from app.services.tenant.change_log import RETENTION
from app.services.tenant.engagement_levels import boosted
from app.services.tenant.personal_items import NAMING

#: How far back the feed reads: the change log's own retention.
WINDOW = RETENTION
#: How fast an entry fades: one this old is ordered as if half as recent.
HALF_LIFE = timedelta(days=1)
#: The newest changes a request reads. Everything else in the window has faded.
CANDIDATE_CHANGES = 2000
#: Entries one page holds.
PAGE_SIZE = 20
#: The people an entry names; the rest are a count.
ACTORS_SHOWN = 3

#: What the reader's own involvement adds to an item's relevance.
#: Made it, or named on it (assigned, attending).
INVOLVED_WEIGHT = 2.0
CHANGED_WEIGHT = 1.0
#: Subscribed to it, or the tool it is in: the reader asked to hear of it.
SUBSCRIBED_WEIGHT = 2.0
OPENED_WEIGHT = 0.5
#: Bookmarked the tool it is in.
BOOKMARKED_WEIGHT = 0.5


class FeedView(str, Enum):
    """What an entry has to be, to be in a view."""

    #: Everything.
    all = "all"
    #: What the reader is assigned to, made, or changed this week.
    yours = "yours"
    #: What somebody commented on.
    comments = "comments"


class Verb(str, Enum):
    """What happened to an item, as an entry says it."""

    created = "created"
    completed = "completed"
    commented = "commented"
    edited = "edited"
    moved = "moved"
    scheduled = "scheduled"
    published = "published"


#: Facets whose changes are not activity: they move an item's level and make no
#: entry. A reaction ranks an item rather than being news about it; a read and
#: an answer or a vote are a person's own business; sharing, layouts, a
#: project's statuses and plug-in values are configuration.
QUIET_FACETS: tuple[str, ...] = (
    "reactions",
    "reads",
    "poll",
    "answers",
    "sharing",
    "layouts",
    "statuses",
    "plugin_values",
)

#: The columns that say a task or an event was rescheduled.
_SCHEDULE_COLUMNS = ("start_date", "due_date", "start_at")


def _verb() -> str:
    """One change as a verb, or NULL for a change that makes no entry."""
    return f"""
        CASE
            WHEN o.resource_type = 'comments' THEN
                CASE WHEN o.action = 'created' THEN '{Verb.commented.value}' END
            -- The item itself arriving: a facet is always reported as updated.
            WHEN o.action = 'created' AND o.resource_type = ANY (:item_tables)
                THEN '{Verb.created.value}'
            WHEN o.action <> 'updated' THEN NULL
            -- The log says only that completed_at changed. The latest such
            -- change completed the task if it is done now; any earlier one
            -- could have gone either way, and moved its status regardless.
            WHEN o.resource_type = 'tasks' AND 'completed_at' = ANY (o.changed) THEN
                CASE WHEN EXISTS (SELECT 1 FROM tasks t WHERE t.id = o.resource_id
                                  AND t.completed_at IS NOT NULL)
                      AND NOT EXISTS (SELECT 1 FROM changes later
                                       WHERE later.resource_type = 'tasks'
                                         AND later.resource_id = o.resource_id
                                         AND 'completed_at' = ANY (later.changed)
                                         AND later.occurred_at > o.occurred_at)
                     THEN '{Verb.completed.value}' ELSE '{Verb.moved.value}' END
            WHEN o.resource_type = 'tasks' AND 'task_status_id' = ANY (o.changed)
                THEN '{Verb.moved.value}'
            WHEN o.resource_type = 'posts' AND 'published_at' = ANY (o.changed)
                THEN '{Verb.published.value}'
            WHEN o.resource_type IN ('tasks', 'calendar_events')
                 AND o.changed && :schedule_columns
                THEN '{Verb.scheduled.value}'
            ELSE '{Verb.edited.value}'
        END"""


def _statement(tools: list[str] | None) -> Any:
    """The candidates as one statement: each item people changed among the
    changes in ``tools`` the reader can open (``:ids_<tool>`` each), with what
    the log, the index and the levels say about it. With ``tools`` ``None``,
    the changes of the transactions ``:txns`` instead, however long ago, for
    telling subscribers what one batch of the log did: plug-ins' changes
    included, which the feed leaves out, and comments left out, which are told
    where they are made."""
    if tools is None:
        scope = (
            "o.txn_id = ANY (:txns) AND o.resource_type <> 'comments'"
            " AND (o.actor_user_id IS NOT NULL OR o.actor_install_id IS NOT NULL)"
        )
        window = ""
    else:
        readable = " OR ".join(
            f"(o.dac_tool = '{tool}' AND o.dac_id = ANY (:ids_{tool}))"
            for tool in tools
        )
        scope = (
            f"o.occurred_at > :since AND ({readable})"
            " AND o.actor_user_id IS NOT NULL AND o.actor_install_id IS NULL"
        )
        window = "ORDER BY o.occurred_at DESC LIMIT :candidates"
    sql = f"""
    WITH changes AS (
        SELECT o.resource_type, o.resource_id, o.parents, o.action,
               o.changed::text[] AS changed,
               o.actor_user_id, o.actor_install_id, o.occurred_at
        FROM event_outbox o
        WHERE {scope}
          AND NOT (o.action = 'updated' AND o.changed::text[] <@ :quiet)
        {window}
    ),
    attributed AS (
        SELECT item.kind, item.id, o.actor_user_id AS actor,
               o.actor_install_id AS install, o.occurred_at,
               {_verb()} AS verb
        FROM changes o
        CROSS JOIN LATERAL content_item_of(o.resource_type, o.resource_id, o.parents)
            AS item
    ),
    per_actor AS (
        SELECT kind, id, actor, install, max(occurred_at) AS last
        FROM attributed
        WHERE actor IS DISTINCT FROM :reader AND verb IS NOT NULL
        GROUP BY kind, id, actor, install
    ),
    items AS (
        SELECT p.kind, p.id, max(p.last) AS latest,
               (array_agg(p.actor ORDER BY p.last DESC, p.actor, p.install))
                   [1:{ACTORS_SHOWN}] AS actors,
               (array_agg(p.install ORDER BY p.last DESC, p.actor, p.install))
                   [1:{ACTORS_SHOWN}] AS installs,
               bool_or(p.install IS NULL) AS by_people,
               count(*) AS actor_count
        FROM per_actor p
        GROUP BY p.kind, p.id
    )
    SELECT i.kind AS entity_type, i.id AS entity_id, i.latest, i.actors,
           i.installs, i.by_people, i.actor_count,
           (SELECT array_agg(DISTINCT a.verb ORDER BY a.verb) FROM attributed a
             WHERE a.kind = i.kind AND a.id = i.id
               AND a.actor IS DISTINCT FROM :reader AND a.verb IS NOT NULL)
               AS verbs,
           (SELECT array_agg(a.verb || ':' || coalesce(a.actor::text, '')
                             || ':' || coalesce(a.install::text, '')
                             ORDER BY a.occurred_at DESC)
              FROM attributed a
             WHERE a.kind = i.kind AND a.id = i.id
               AND a.actor IS DISTINCT FROM :reader AND a.verb IS NOT NULL)
               AS done,
           EXISTS (SELECT 1 FROM attributed a
                    WHERE a.kind = i.kind AND a.id = i.id AND a.actor = :reader)
               AS changed,
           coalesce(mine.viewed_at > :since, false) AS opened,
           mine_tool.bookmarked_at IS NOT NULL AS bookmarked,
           (mine.subscribed_at IS NOT NULL OR mine_tool.subscribed_at IS NOT NULL)
               AS subscribed,
           mine.unsubscribed_at IS NOT NULL AS unsubscribed,
           coalesce(l.level, 0) AS level,
           se.title, se.initiative_id, se.dac_tool AS tool, se.dac_id AS tool_id,
           container.title AS tool_title, ini.name AS initiative_name
    FROM items i
    JOIN search_entries se
      ON se.entity_type = i.kind AND se.entity_id = i.id AND se.chunk_ix = 0
     AND NOT se.archived AND NOT se.template
    LEFT JOIN engagement_levels l ON l.entity_type = i.kind AND l.entity_id = i.id
    LEFT JOIN personal_items mine
      ON mine.user_id = :reader AND mine.entity_type = i.kind AND mine.entity_id = i.id
    LEFT JOIN personal_items mine_tool
      ON mine_tool.user_id = :reader AND mine_tool.entity_type = se.dac_tool
     AND mine_tool.entity_id = se.dac_id
    LEFT JOIN search_entries container
      ON container.entity_type = se.dac_tool AND container.entity_id = se.dac_id
     AND container.chunk_ix = 0
     AND NOT (container.entity_type = i.kind AND container.entity_id = i.id)
    LEFT JOIN initiatives ini ON ini.id = se.initiative_id
    """
    shared = (
        bindparam("reader", type_=Integer),
        bindparam("since", type_=DateTime(timezone=True)),
        bindparam("quiet", type_=ARRAY(Text)),
        bindparam("schedule_columns", type_=ARRAY(Text)),
        bindparam("item_tables", type_=ARRAY(Text)),
    )
    if tools is None:
        return text(sql).bindparams(*shared, bindparam("txns", type_=ARRAY(BigInteger)))
    return text(sql).bindparams(
        *shared,
        bindparam("candidates", type_=Integer),
        *(bindparam(f"ids_{tool}", type_=ARRAY(Integer)) for tool in tools),
    )


@dataclass(frozen=True)
class FeedEntry:
    """One item, as the feed shows it."""

    entity_type: str
    entity_id: int
    title: str
    initiative_id: Optional[int]
    initiative_name: Optional[str]
    tool: Optional[str]
    tool_id: Optional[int]
    tool_title: Optional[str]
    latest: datetime
    verbs: list[str]
    actors: list[MemberProfile]
    actor_count: int


async def readable_tools(
    session: AsyncSession,
    *,
    initiative_id: Optional[int] = None,
    tool: Optional[Tool] = None,
    tool_id: Optional[int] = None,
) -> dict[str, list[int]]:
    """The tools the reader can open, by kind, narrowed to one initiative or one
    tool where those are given: what the feed's scan is held to."""
    rows = select(SearchEntry.entity_type, SearchEntry.entity_id).where(
        SearchEntry.chunk_ix == 0,
        col(SearchEntry.entity_type).in_([t.value for t in Tool]),
    )
    if initiative_id is not None:
        rows = rows.where(SearchEntry.initiative_id == initiative_id)
    if tool is not None and tool_id is not None:
        rows = rows.where(
            SearchEntry.entity_type == tool.value, SearchEntry.entity_id == tool_id
        )
    tools: dict[str, list[int]] = {}
    for kind, entity_id in (await session.exec(rows)).all():
        tools.setdefault(kind, []).append(entity_id)
    return tools


def verb_params() -> dict[str, Any]:
    """What :func:`_verb` and the quiet filter read: the facets that are no
    news, the columns that reschedule, the tables an item is."""
    return {
        "quiet": list(QUIET_FACETS),
        "schedule_columns": list(_SCHEDULE_COLUMNS),
        "item_tables": sorted(CONTENT_KIND_TABLES.values()),
    }


def query(
    tools: dict[str, list[int]], *, reader_id: int, since: Optional[datetime] = None
) -> tuple[Any, dict]:
    """The candidates' statement over ``tools``, from ``since`` where that is
    inside the :data:`WINDOW`, and its parameters."""
    start = datetime.now(timezone.utc) - WINDOW
    params: dict[str, Any] = {
        "reader": reader_id,
        "since": max(since, start) if since else start,
        "candidates": CANDIDATE_CHANGES,
        **verb_params(),
        **{f"ids_{tool}": ids for tool, ids in tools.items()},
    }
    return _statement(sorted(tools)), params


def batch_query(txns: list[int], *, reader_id: int) -> tuple[Any, dict]:
    """The same statement over the changes of the transactions ``txns``, and
    its parameters: what those transactions did that the reader can see,
    people's and plug-ins' changes, never the reader's own. ``by_people`` says
    whether a person made any of an item's, and ``done`` pairs each verb with
    who did it (``verb:person:install``), newest first."""
    return _statement(None), {
        "reader": reader_id,
        "since": datetime.now(timezone.utc) - WINDOW,
        "txns": txns,
        **verb_params(),
    }


async def _involved(
    session: AsyncSession, reader_id: int, items: dict[str, list[int]]
) -> set[tuple[str, int]]:
    """The items, of those given by kind, the reader made or is named on."""
    found: set[tuple[str, int]] = set()
    for kind, ids in items.items():
        for table, item_column, person_column, _tie in NAMING.get(kind, ()):
            rows = await session.exec(
                select(table.c[item_column]).where(  # type: ignore[call-overload]
                    table.c[item_column].in_(ids), table.c[person_column] == reader_id
                )
            )
            found.update((kind, item_id) for item_id in rows.all())
    return found


def _score(row: Any, now: datetime, involved: bool) -> float:
    age = (now - row["latest"]).total_seconds()
    # Unsubscribing from an item takes back what made it the reader's.
    kept = not row["unsubscribed"]
    relevance = (
        1
        + (INVOLVED_WEIGHT if involved and kept else 0)
        + (CHANGED_WEIGHT if row["changed"] else 0)
        + (SUBSCRIBED_WEIGHT if row["subscribed"] and kept else 0)
        + (OPENED_WEIGHT if row["opened"] else 0)
        + (BOOKMARKED_WEIGHT if row["bookmarked"] else 0)
    )
    return (
        2 ** (-age / HALF_LIFE.total_seconds()) * boosted(1, row["level"]) * relevance
    )


async def feed(
    session: AsyncSession,
    *,
    reader_id: int,
    view: FeedView = FeedView.all,
    initiative_id: Optional[int] = None,
    tool: Optional[Tool] = None,
    tool_id: Optional[int] = None,
    since: Optional[datetime] = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> tuple[list[FeedEntry], bool]:
    """One page of the reader's feed, on their own routed session.

    Narrowed to one initiative, or to one tool (any :class:`Tool`, with the id
    of the instance), or to the changes since a moment, where those are given.
    Narrowing only removes changes. Returns the page's entries and whether
    another page follows.
    """
    tools = await readable_tools(
        session, initiative_id=initiative_id, tool=tool, tool_id=tool_id
    )
    if not tools:
        return [], False
    statement, params = query(tools, reader_id=reader_id, since=since)
    rows = (await session.exec(statement, params=params)).mappings().all()  # type: ignore[call-overload]

    by_kind: dict[str, list[int]] = {}
    for row in rows:
        by_kind.setdefault(row["entity_type"], []).append(row["entity_id"])
    involved = await _involved(session, reader_id, by_kind)

    def wanted(row: Any) -> bool:
        if view is FeedView.yours:
            return row["changed"] or (row["entity_type"], row["entity_id"]) in involved
        if view is FeedView.comments:
            return Verb.commented.value in (row["verbs"] or ())
        return True

    now = datetime.now(timezone.utc)
    ranked = sorted(
        (row for row in rows if wanted(row)),
        key=lambda row: (
            -_score(row, now, (row["entity_type"], row["entity_id"]) in involved),
            -row["latest"].timestamp(),
            row["entity_type"],
            row["entity_id"],
        ),
    )
    start = (page - 1) * page_size
    shown = ranked[start : start + page_size]

    people_ids = {actor for row in shown for actor in row["actors"]}
    people = (
        {
            person.id: person
            for person in (
                await session.exec(
                    select(MemberProfile).where(MemberProfile.id.in_(people_ids))  # type: ignore[attr-defined]
                )
            ).all()
        }
        if people_ids
        else {}
    )
    return [
        FeedEntry(
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            title=row["title"],
            initiative_id=row["initiative_id"],
            initiative_name=row["initiative_name"],
            tool=row["tool"],
            tool_id=row["tool_id"],
            tool_title=row["tool_title"],
            latest=row["latest"],
            verbs=list(row["verbs"] or []),
            actors=[people[a] for a in row["actors"] if a in people],
            actor_count=row["actor_count"],
        )
        for row in shown
    ], len(ranked) > start + page_size
