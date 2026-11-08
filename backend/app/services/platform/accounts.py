"""Reading an account, where an account may be read.

``public.users`` holds two different kinds of thing: a few columns that say who
somebody is, and the account itself — credentials, address, notification
preferences, locale, interface settings. A guild-routed session reads the first
kind through ``public.guild_member_profiles`` and cannot reach the second at
all, which is the point.

Some work on the request path legitimately needs the second kind about somebody
else. Addressing a notification is the main one: whether they asked to hear
about this, which language to write it in, what clock to render a time against,
and the address itself, which is stored encrypted and decrypted in Python. The
export worker is another — it re-runs a job as the person who asked for it, and
needs their account to do so.

Those reads happen here, on the system engine, the way
``authenticate_api_key`` resolves a credential before a session exists.

It is also where a recipient stops being one. An account that ignores the actor
does not hear from them — no notification row, so no email, no push, no unread
count and no realtime frame — and because that is decided here, no fan-out
carries a rule of its own.

The rows come back **detached**. Every column is loaded, so callers read them
exactly as they read a request-loaded row; what a detached row cannot do is
lazy-load a relationship or be written back, which is right for something the
caller is only reading facts off.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from datetime import timedelta

from sqlmodel import col, select

from app.models.platform.user import User

__all__ = ["load", "load_all", "load_event_reminder_leads", "load_one"]


async def load(
    user_ids: Iterable[int | None],
    *,
    excluding_ignorers_of: int | None = None,
) -> dict[int, User]:
    """The accounts behind ``user_ids``, keyed by id, detached.

    Ids with no account behind them are simply absent — an account can be
    erased between the content write and the notification, and having nobody to
    tell is not an error.

    ``excluding_ignorers_of`` drops the accounts that ignore that actor. It
    belongs here because this is the one place a *recipient* is resolved, so a
    person who has stopped hearing from somebody is not a recipient of theirs —
    and every caller already handles an id coming back empty, for the erasure
    case above. Left out, nothing is filtered: the export worker re-runs a job
    as the person who asked for it and is not telling anybody anything.
    """
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}

    # Imported here: this module is pulled in by request-path services, and the
    # session module reaches back into configuration at import time.
    from app.db.session import SystemSessionLocal
    from app.models.platform.user_ignore import UserIgnore

    statement = select(User).where(User.id.in_(tuple(wanted)))
    if excluding_ignorers_of is not None:
        statement = statement.where(
            ~select(UserIgnore.user_id)
            .where(
                UserIgnore.user_id == User.id,
                UserIgnore.ignored_user_id == excluding_ignorers_of,
            )
            .exists()
        )

    async with SystemSessionLocal() as system_session:
        rows = list((await system_session.exec(statement)).all())
        for row in rows:
            system_session.expunge(row)
    return {row.id: row for row in rows if row.id is not None}


async def load_one(
    user_id: int | None, *, excluding_ignorers_of: int | None = None
) -> User | None:
    """One recipient, or ``None`` if there is nobody to tell."""
    if user_id is None:
        return None
    return (await load([user_id], excluding_ignorers_of=excluding_ignorers_of)).get(
        user_id
    )


async def load_all(
    user_ids: Sequence[int | None], *, excluding_ignorers_of: int | None = None
) -> list[User]:
    """Recipients in the order asked for, skipping any that are gone."""
    targets = await load(user_ids, excluding_ignorers_of=excluding_ignorers_of)
    seen: set[int] = set()
    ordered: list[User] = []
    for user_id in user_ids:
        if user_id is None or user_id in seen:
            continue
        target = targets.get(user_id)
        if target is not None:
            seen.add(user_id)
            ordered.append(target)
    return ordered


async def load_event_reminder_leads(user_ids: Collection[int]) -> dict[int, timedelta]:
    """How long before an event each of ``user_ids`` asked to be reminded,
    for those who asked.

    The reminder sweep holds a session routed into a guild's schema, and a
    routed session has no business reading an account's preferences. The
    question is about accounts rather than any guild, so it is asked here, on
    the system engine, for the attendees a visit found.
    """
    from app.db.session import SystemSessionLocal

    if not user_ids:
        return {}
    async with SystemSessionLocal() as system_session:
        rows = (
            await system_session.exec(
                select(User.id, User.event_reminder_minutes_before).where(
                    col(User.id).in_(sorted(user_ids)),
                    User.event_reminder_minutes_before.is_not(None),
                )
            )
        ).all()
    return {user_id: timedelta(minutes=minutes) for user_id, minutes in rows}
