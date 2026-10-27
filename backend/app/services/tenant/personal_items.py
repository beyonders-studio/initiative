"""What each member keeps about the items in a community: their opens, bookmarks,
subscriptions and their own order of projects, one ``personal_items`` row per item.

Opening any tool, or anything inside one, records a view; the tools' views are
the layout header's tabs. Every view is kept for :data:`WINDOW`; past it, a
tool is kept while it is among the person's newest tabs, and anything else goes.
A bookmark is on a tool, a subscription on anything, and both last until taken off.

Who is subscribed to an item is worked out, not only kept (:func:`subscribers_of`):
whoever made it or is named on it (an assignee, an attendee, :data:`NAMING`), and
whoever subscribed to it or to its tool by hand, less whoever unsubscribed from
it. The activity feed ranks by the same rule, and every notice about what
happens on an item goes to it.

A row holds at least one of these, which the table checks. So each path that
lets one go deletes the rows where it was the last, and empties it in the rest.

Everything here runs on the routed session, which already holds the reader to
their own rows (``PRIVATE_ROW_TABLES``). Letting go of a mark, and the purges,
run as the platform: the row may name something the reader can no longer open,
and whoever triggers a purge cannot reach rows that are someone else's alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import Table, and_, func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import SQLModel, col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import KINDS
from app.db.initiative_rls import CONTENT_KIND_TABLES, NAMED_PEOPLE
from app.models.tenant.calendar_event import RSVPStatus
from app.models.tenant.personal_item import TOOL_KINDS, PersonalItem, ViewSource
from app.services.tenant.change_log import RETENTION

if TYPE_CHECKING:
    from app.services.tenant.expiry import Expiring


class Mark(str, Enum):
    """What a member sets and clears on an item."""

    #: Opened it. Any kind; a tool's view is a tab.
    view = "view"
    #: Bookmarked it. Tools only.
    bookmark = "bookmark"
    #: Subscribed to it: it and what is inside it rise in their feed and notify
    #: them. Letting go of it is an unsubscription (:func:`unsubscribe`), not
    #: a clear: making something or being named on it subscribes too.
    subscribe = "subscribe"


#: The columns each mark sets, the first being its time.
MARK_COLUMNS: dict[Mark, tuple[str, ...]] = {
    Mark.view: ("viewed_at", "view_source"),
    Mark.bookmark: ("bookmarked_at",),
    Mark.subscribe: ("subscribed_at",),
}

#: Every column that keeps a row: each mark's time, an unsubscription, and the
#: project order.
_HOLDING = (
    "viewed_at",
    "bookmarked_at",
    "subscribed_at",
    "unsubscribed_at",
    "sort_order",
)

# Per-user cap on tabs kept and shown. The user's ``recent_tabs_limit``
# (Interface settings) picks the value within these bounds.
MIN_RECENT_VIEWS = 1
MAX_RECENT_VIEWS = 100
DEFAULT_RECENT_VIEWS = 20

#: How long every open is kept, tab or not: the span the change log keeps, so
#: what people opened and what they changed cover the same days.
WINDOW = RETENTION


def clamp_recent_limit(value: int | None) -> int:
    """A user's ``recent_tabs_limit`` within the allowed range, the default
    where they never set one."""
    if value is None:
        return DEFAULT_RECENT_VIEWS
    return max(MIN_RECENT_VIEWS, min(MAX_RECENT_VIEWS, value))


def _key(user_id: int, kind: str, entity_id: int) -> list[Any]:
    return [
        col(PersonalItem.user_id) == user_id,
        col(PersonalItem.entity_type) == kind,
        col(PersonalItem.entity_id) == entity_id,
    ]


async def _upsert(
    session: AsyncSession, user_id: int, kind: str, entity_id: int, **values: Any
) -> None:
    """Write these columns on the row, making it where there is none."""
    await session.exec(
        pg_insert(PersonalItem)
        .values(user_id=user_id, entity_type=kind, entity_id=entity_id, **values)
        .on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"], set_=values
        )
    )


async def record_view(
    session: AsyncSession,
    *,
    user_id: int,
    entity_type: str,
    entity_id: int,
    source: ViewSource = ViewSource.direct,
    persist: bool = True,
) -> datetime:
    """Record an open and where it came from, and return its time. What a
    person no longer keeps goes in the expiry sweep (:func:`expire`).

    ``persist=False`` writes nothing: a PAM grantee's browsing is transient.
    """
    now = datetime.now(timezone.utc)
    if persist:
        await _upsert(
            session,
            user_id,
            entity_type,
            entity_id,
            viewed_at=now,
            view_source=source.value,
        )
        await session.commit()
    return now


async def set_mark(
    session: AsyncSession, *, user_id: int, mark: Mark, kind: str, entity_id: int
) -> None:
    """Bookmark or subscribe to it. Setting one already set keeps the first
    time; subscribing takes back an unsubscription."""
    (column,) = MARK_COLUMNS[mark]
    insert = pg_insert(PersonalItem).values(
        user_id=user_id,
        entity_type=kind,
        entity_id=entity_id,
        **{column: datetime.now(timezone.utc)},
    )
    undone = {"unsubscribed_at": None} if mark is Mark.subscribe else {}
    await session.exec(
        insert.on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"],
            set_={
                column: func.coalesce(
                    PersonalItem.__table__.c[column], insert.excluded[column]
                ),
                **undone,
            },
        )
    )
    await session.commit()


async def unsubscribe(
    session: AsyncSession,
    *,
    user_id: int,
    kind: str,
    entity_id: int,
    new: bool = False,
) -> bool:
    """Hear nothing more about it, whatever ties the reader to it, until they
    subscribe again. Returns whether it is kept.

    On a row the reader already keeps about it, run as the platform and
    limited to that row, so a subscription comes off something they can no
    longer open, as any mark does (:func:`clear_mark`). Where they keep
    nothing, only with ``new``, on the reader's own session: for an item the
    caller loaded, since an unsubscription is kept only about what the reader
    can open."""
    from app.db.cohorts import as_system

    now = datetime.now(timezone.utc)
    async with as_system(session) as system:
        row = (
            await system.exec(
                select(PersonalItem)
                .where(*_key(user_id, kind, entity_id))
                .with_for_update()
            )
        ).one_or_none()
        if row is not None:
            row.subscribed_at = None
            row.unsubscribed_at = row.unsubscribed_at or now
            system.add(row)
            await system.flush()
    if row is None and new:
        await _upsert(
            session, user_id, kind, entity_id, subscribed_at=None, unsubscribed_at=now
        )
    await session.commit()
    return row is not None or new


async def clear_mark(
    session: AsyncSession, *, user_id: int, mark: Mark, kind: str, entity_id: int
) -> None:
    """Let go of a mark: close a tab, remove a bookmark.
    Idempotent, and whether or not the item can still be opened, so a mark on
    something the reader has lost can still come off. Run as the platform and
    limited to the reader's own row, which is locked while it is decided
    whether anything else keeps it, so two marks let go at once both go."""
    from app.db.cohorts import as_system

    async with as_system(session) as system:
        row = (
            await system.exec(
                select(PersonalItem)
                .where(*_key(user_id, kind, entity_id))
                .with_for_update()
            )
        ).one_or_none()
        if row is not None:
            for column in MARK_COLUMNS[mark]:
                setattr(row, column, None)
            if all(getattr(row, column) is None for column in _HOLDING):
                await system.delete(row)
            else:
                system.add(row)
            await system.flush()
    await session.commit()


async def item_state(
    session: AsyncSession, *, user_id: int, kind: str, entity_id: int
) -> Optional[PersonalItem]:
    """The reader's row on this item, if they keep anything about it."""
    return (
        await session.exec(select(PersonalItem).where(*_key(user_id, kind, entity_id)))
    ).one_or_none()


async def list_marked(
    session: AsyncSession, *, user_id: int, mark: Mark, limit: Optional[int] = None
) -> Sequence[PersonalItem]:
    """The tools the reader marked this way in this community, newest first:
    the tabs for views, the sidebar's bookmarks for bookmarks. Bookmarks are listed
    whole: the list is also what lights each bookmark on a page."""
    column = PersonalItem.__table__.c[MARK_COLUMNS[mark][0]]
    statement = (
        select(PersonalItem)
        .where(
            col(PersonalItem.user_id) == user_id,
            col(PersonalItem.entity_type).in_(TOOL_KINDS),
            column.is_not(None),
        )
        .order_by(column.desc())
    )
    if limit is not None:
        statement = statement.limit(limit)
    return (await session.exec(statement)).all()


class Tie(str, Enum):
    """Why somebody is subscribed to an item, the strongest first."""

    #: Named on it: assigned to it, going to it.
    named = "named"
    #: Made it.
    made = "made"
    #: Subscribed to it or to its tool by hand, or made or is named on its tool.
    subscribed = "subscribed"


_STRENGTH = {tie: rank for rank, tie in enumerate(Tie)}


@dataclass(frozen=True)
class Subscriber:
    #: Everything that ties them to it.
    ties: frozenset[Tie]
    #: When they first subscribed by hand, where that is all that ties them:
    #: what happened before it is not news to them.
    since: Optional[datetime] = None

    @property
    def tie(self) -> Tie:
        """The strongest of their ties."""
        return min(self.ties, key=_STRENGTH.__getitem__)

    @property
    def follows(self) -> bool:
        """Made it or follows it, beyond being named on it."""
        return bool(self.ties - {Tie.named})

    def joined(self, other: "Subscriber") -> "Subscriber":
        """Both ties at once. A date holds only while every tie has one."""
        since = (
            None
            if self.since is None or other.since is None
            else min(self.since, other.since)
        )
        return Subscriber(self.ties | other.ties, since)


Ref = tuple[str, int]


def _naming_tables() -> dict[str, list[tuple[Table, str, str, Tie]]]:
    """Per content kind, the tables whose rows tie a person to one: ``(table,
    column naming the item, column naming the person, tie)``. The item's own
    ``created_by``, and the kept :data:`NAMED_PEOPLE` rows (an assignee, an
    attendee) whose foreign key is the kind's. From the schema, so a new kind
    is asked the moment its table has either."""
    kind_of = {table: kind for kind, table in CONTENT_KIND_TABLES.items()}
    tables = SQLModel.metadata.tables
    naming: dict[str, list[tuple[Table, str, str, Tie]]] = {}
    for kind, name in CONTENT_KIND_TABLES.items():
        if "created_by" in tables[name].c:
            naming.setdefault(kind, []).append(
                (tables[name], "id", "created_by", Tie.made)
            )
    for named in NAMED_PEOPLE:
        if named.clear:
            continue
        for fk in tables[named.table].foreign_keys:
            kind = kind_of.get(fk.column.table.name)
            if kind is not None:
                naming.setdefault(kind, []).append(
                    (tables[named.table], fk.parent.name, named.column, Tie.named)
                )
    return naming


NAMING = _naming_tables()


async def _declined(session: AsyncSession, event_ids: set[int]) -> set[tuple[int, int]]:
    """``(event, person)`` for everyone who declined an event: they aren't
    going, so they are no longer named on it. Read as the event's own answers
    are (``calendar_occurrences.answers_of``), so an occurrence of a series is
    answered under the series and its start."""
    from app.models.tenant.calendar_event import CalendarEvent
    from app.services.tenant import calendar_occurrences

    if not event_ids:
        return set()
    events = (
        await session.exec(
            select(CalendarEvent).where(col(CalendarEvent.id).in_(event_ids))
        )
    ).all()
    answers = await calendar_occurrences.answers_of(session, events)
    return {
        (event_id, person)
        for event_id, by_person in answers.items()
        for person, status in by_person.items()
        if status == RSVPStatus.declined
    }


async def subscribers_of(
    session: AsyncSession,
    items: Mapping[Ref, Optional[Ref]],
    *,
    user_id: Optional[int] = None,
) -> dict[Ref, dict[int, Subscriber]]:
    """Who is subscribed to each item, given the tool it is in, and why.

    Subscribed to an item is: made it or named on it, or subscribed to it by
    hand; or made, is named on or subscribed to the tool it is in, unless
    unsubscribed from the tool. Unsubscribing from the item itself overrides
    all of it. ``user_id`` asks about one person.

    Identifiers only, read as the platform: rows here are each member's own,
    and this decides only whom to ask, never what anyone may see.
    """
    from app.db.cohorts import as_system

    if not items:
        return {}
    refs = set(items) | {tool for tool in items.values() if tool is not None}
    by_kind: dict[str, set[int]] = {}
    for kind, entity_id in refs:
        by_kind.setdefault(kind, set()).add(entity_id)
    tied: dict[Ref, dict[int, set[Tie]]] = {}
    explicit: dict[Ref, dict[int, datetime]] = {}
    unsubscribed: dict[Ref, set[int]] = {}
    async with as_system(session) as system:
        for kind, ids in by_kind.items():
            for table, item_column, person_column, tie in NAMING.get(kind, ()):
                statement = select(table.c[item_column], table.c[person_column]).where(
                    table.c[item_column].in_(ids), table.c[person_column].is_not(None)
                )
                if user_id is not None:
                    statement = statement.where(table.c[person_column] == user_id)
                for entity_id, person in (await system.exec(statement)).all():  # type: ignore[call-overload]
                    tied.setdefault((kind, entity_id), {}).setdefault(
                        person, set()
                    ).add(tie)
        declined = await _declined(system, by_kind.get("calendar_event", set()))
        for event_id, person in declined:
            tied.get(("calendar_event", event_id), {}).get(person, set()).discard(
                Tie.named
            )
        marks = select(PersonalItem).where(
            or_(
                *(
                    and_(
                        col(PersonalItem.entity_type) == kind,
                        col(PersonalItem.entity_id).in_(ids),
                    )
                    for kind, ids in by_kind.items()
                )
            ),
            or_(
                col(PersonalItem.subscribed_at).is_not(None),
                col(PersonalItem.unsubscribed_at).is_not(None),
            ),
        )
        if user_id is not None:
            marks = marks.where(col(PersonalItem.user_id) == user_id)
        for row in (await system.exec(marks)).all():
            ref = (row.entity_type, row.entity_id)
            if row.subscribed_at is not None:
                explicit.setdefault(ref, {})[row.user_id] = row.subscribed_at
            else:
                unsubscribed.setdefault(ref, set()).add(row.user_id)

    found: dict[Ref, dict[int, Subscriber]] = {}
    for item, tool in items.items():
        people: dict[int, Subscriber] = {}

        def tie(person: int, how: Tie, since: Optional[datetime] = None) -> None:
            subscriber = Subscriber(frozenset({how}), since)
            held = people.get(person)
            people[person] = subscriber if held is None else held.joined(subscriber)

        if tool is not None and tool != item:
            gone = unsubscribed.get(tool, set())
            for person, hows in tied.get(tool, {}).items():
                if hows and person not in gone:
                    tie(person, Tie.subscribed)
            for person, at in explicit.get(tool, {}).items():
                tie(person, Tie.subscribed, at)
        for person, at in explicit.get(item, {}).items():
            tie(person, Tie.subscribed, at)
        for person, hows in tied.get(item, {}).items():
            for how in hows:
                tie(person, how)
        for person in unsubscribed.get(item, set()):
            people.pop(person, None)
        found[item] = people
    return found


async def is_subscribed(
    session: AsyncSession, *, user_id: int, kind: str, entity_id: int
) -> bool:
    """Whether the reader is subscribed to one item, as :func:`subscribers_of`
    says, the tool it is in read on their own session."""
    from app.services.tenant.named_people import governing_of

    item = (kind, entity_id)
    # A kind in no one instance of its tool has no tool row to follow.
    governed = None if KINDS[kind].standalone else await governing_of(session, item)
    tool = None if governed is None else (governed[0].value, governed[1].id)
    found = await subscribers_of(session, {item: tool}, user_id=user_id)
    return user_id in found[item]


async def rows_for(
    session: AsyncSession, *, user_id: int, kind: str, ids: Iterable[int]
) -> dict[int, PersonalItem]:
    """The reader's rows on these items of one kind, by id, for a list that
    shows what they keep about each."""
    wanted = list(ids)
    if not wanted:
        return {}
    rows = await session.exec(
        select(PersonalItem).where(
            col(PersonalItem.user_id) == user_id,
            col(PersonalItem.entity_type) == kind,
            col(PersonalItem.entity_id).in_(wanted),
        )
    )
    return {row.entity_id: row for row in rows.all()}


async def place_projects(
    session: AsyncSession, *, user_id: int, order: Sequence[int]
) -> None:
    """Put these projects in the reader's own list in this order."""
    if not order:
        return
    insert = pg_insert(PersonalItem).values(
        [
            dict(
                user_id=user_id,
                entity_type="project",
                entity_id=project_id,
                sort_order=float(index),
            )
            for index, project_id in enumerate(order)
        ]
    )
    await session.exec(
        insert.on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"],
            set_={"sort_order": insert.excluded.sort_order},
        )
    )
    await session.commit()


#: Each view, ranked among its person's tabs or other views, beside that
#: person's tab limit when it is not the default.
_RANKED = """
    (
        SELECT user_id, entity_type, entity_id, viewed_at,
               entity_type = ANY (CAST(:tabs AS text[])) AS is_tab,
               row_number() OVER (
                   PARTITION BY user_id,
                                entity_type = ANY (CAST(:tabs AS text[]))
                   ORDER BY viewed_at DESC
               ) AS n
          FROM personal_items
         WHERE viewed_at IS NOT NULL
    ) ranked
    LEFT JOIN unnest(CAST(:users AS integer[]), CAST(:limits AS integer[]))
           AS chosen(user_id, tab_limit)
           ON chosen.user_id = ranked.user_id
"""

#: The view goes once it is past the window: anything but a tab among its
#: person's newest ``recent_tabs_limit``.
_LETS_GO = (
    "(NOT ranked.is_tab OR ranked.n > COALESCE(chosen.tab_limit, :default_limit))"
)

#: Every view :func:`expire` lets go: past the window, and let go. A row the
#: view was all of goes; the rest keep what else they hold. A view reopened
#: while this runs is left: it no longer has the time it was ranked by.
_EXPIRE = f"""
    WITH doomed AS (
        SELECT ranked.user_id, ranked.entity_type, ranked.entity_id,
               ranked.viewed_at
          FROM {_RANKED}
         WHERE ranked.viewed_at < :cutoff AND {_LETS_GO}
    ),
    gone AS (
        DELETE FROM personal_items p USING doomed d
         WHERE (p.user_id, p.entity_type, p.entity_id, p.viewed_at)
             = (d.user_id, d.entity_type, d.entity_id, d.viewed_at)
           AND p.bookmarked_at IS NULL AND p.subscribed_at IS NULL
           AND p.unsubscribed_at IS NULL AND p.sort_order IS NULL
    )
    UPDATE personal_items p SET viewed_at = NULL, view_source = NULL
      FROM doomed d
     WHERE (p.user_id, p.entity_type, p.entity_id, p.viewed_at)
         = (d.user_id, d.entity_type, d.entity_id, d.viewed_at)
       AND num_nonnulls(
               p.bookmarked_at, p.subscribed_at, p.unsubscribed_at, p.sort_order
           ) > 0
"""

#: The oldest view :func:`expire` would let go once it passes the window.
_OLDEST_LET_GO = "SELECT min(ranked.viewed_at) FROM " + _RANKED + " WHERE " + _LETS_GO


def _ranking(expiring: Expiring) -> dict:
    users = list(expiring.tab_limits)
    return dict(
        tabs=list(TOOL_KINDS),
        users=users,
        limits=[expiring.tab_limits[user] for user in users],
        default_limit=DEFAULT_RECENT_VIEWS,
    )


async def expire(session: AsyncSession, expiring: Expiring) -> None:
    """Let go of each person's views past :data:`WINDOW`, except a tab among
    their newest ``recent_tabs_limit``."""
    await session.exec(
        text(_EXPIRE).bindparams(cutoff=expiring.now - WINDOW, **_ranking(expiring))
    )


async def next_due(session: AsyncSession, expiring: Expiring) -> datetime | None:
    """When the next view :func:`expire` would let go passes the window."""
    oldest = (
        await session.exec(text(_OLDEST_LET_GO).bindparams(**_ranking(expiring)))
    ).scalar_one()
    return None if oldest is None else oldest + WINDOW


async def purge_for_entities(
    session: AsyncSession, entity_type: str, entity_ids: Iterable[int]
) -> None:
    """Drop everyone's rows on these, for a purge: ``entity_id`` is a weak
    reference, so nothing carries the rows out with the item."""
    from app.db.cohorts import exec_as_system

    ids = tuple(entity_ids)
    if not ids:
        return
    await exec_as_system(
        session,
        delete(PersonalItem).where(  # type: ignore[arg-type]
            col(PersonalItem.entity_type) == entity_type,
            col(PersonalItem.entity_id).in_(ids),
        ),
    )


async def purge_for_user(session: AsyncSession, user_id: int) -> None:
    """Drop a person's rows in this community, for their leaving it."""
    from app.db.cohorts import exec_as_system

    await exec_as_system(
        session,
        delete(PersonalItem).where(col(PersonalItem.user_id) == user_id),  # type: ignore[arg-type]
    )
