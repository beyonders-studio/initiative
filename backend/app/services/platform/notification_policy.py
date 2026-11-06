"""What a notification may leave the app carrying.

Three answers, each asked once of the deployment and once of the community the
notification belongs to, and resolved by taking the stricter of the pair:

``push``
    May it reach a phone. Off, nothing is sent to the device estate at all.

``email``
    May it reach a mailbox. The *notification* half of email only — a sign-in
    code, an address to confirm, a password reset and the notices an account
    gets about itself are not notifications and are unaffected.

``redact``
    May what it says name the thing it is about. Set, a notification that leaves
    the app reduces to the kind of thing that happened, and the app is where the
    rest of it is. The bell inside the app says everything either way.

Two levels because two parties know the answer. A deployment that is one
organisation is configured by its operator, once, for everybody on it; a
community sharing a deployment with others answers for itself. Either may
restrict; neither may relax what the other restricted.

A notification that belongs to no community — a direct message, a connection
request, a notice about an account — is answered by the deployment alone.

Read on the system engine, like the recipient's own settings next door: what
may leave is the deployment's answer and the community's, not a question for
whichever session happens to be sending.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Iterable, Mapping, TypeVar, cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.notification_categories import NotificationCategory
from app.services.platform import rules

if TYPE_CHECKING:
    from app.services.email import EmailPieces


@dataclass(frozen=True)
class NotificationPolicy:
    """The three answers, already resolved across both levels."""

    push: bool
    email: bool
    redact: bool

    def stricter_than(self, other: "NotificationPolicy") -> "NotificationPolicy":
        return NotificationPolicy(
            push=self.push and other.push,
            email=self.email and other.email,
            redact=self.redact or other.redact,
        )


#: What every deployment and community says until one of them says otherwise:
#: notifications reach both channels and name what they are about.
UNRESTRICTED = NotificationPolicy(push=True, email=True, redact=False)


def _platform_policy(values: Mapping[str, object]) -> NotificationPolicy:
    return NotificationPolicy(
        push=bool(values["push_notifications_enabled"]),
        email=bool(values["email_notifications_enabled"]),
        redact=bool(values["redact_notification_content"]),
    )


def _guild_policy(values: Mapping[str, object]) -> NotificationPolicy:
    """A community's own answers, each while it holds the option it needs."""
    return NotificationPolicy(
        push=bool(values["allow_push_notifications"]),
        email=bool(values["allow_email_notifications"]),
        redact=bool(values["redact_notification_content"]),
    )


async def resolve(session: AsyncSession, guild_id: int | None) -> NotificationPolicy:
    """Both levels, on a session that can read them, as one answer."""
    return (await resolve_many(session, [guild_id]))[guild_id]


async def resolve_many(
    session: AsyncSession, guild_ids: Iterable[int | None]
) -> Mapping[int | None, NotificationPolicy]:
    """The same answer for a set of communities, in one pass.

    What a digest needs: it gathers from every community an account is in, so
    each item it carries is answered by its own.
    """
    wanted = set(guild_ids)
    platform = _platform_policy(await rules.platform_values(session))
    by_id = {
        gid: _guild_policy(values)
        for gid, values in (
            await rules.community_values(
                session, {gid for gid in wanted if gid is not None}
            )
        ).items()
    }
    return {
        gid: platform if gid is None else platform.stricter_than(by_id[gid])
        for gid in wanted
    }


async def load(guild_id: int | None) -> NotificationPolicy:
    """The answer for one community, read on the system engine."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await resolve(system_session, guild_id)


async def load_many(
    guild_ids: Iterable[int | None],
) -> Mapping[int | None, NotificationPolicy]:
    """The answer for a set of communities, read on the system engine."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await resolve_many(system_session, guild_ids)


# --- One answer per send ------------------------------------------------------

#: Answers already read during the sender's current transaction, with that
#: transaction. Kept on ``Session.info`` so concurrent senders never share one.
_ANSWERS = "notification_policy_answers"


def _answers_for_this_transaction(
    session: AsyncSession,
) -> dict[int | None, NotificationPolicy] | None:
    """The answers read so far in ``session``'s open transaction, or ``None``
    when it has none open to hold them to."""
    txn = session.sync_session.get_transaction()
    if txn is None:
        return None
    held = session.info.get(_ANSWERS)
    if held is None or held[0] is not txn:
        held = (txn, {})
        session.info[_ANSWERS] = held
    return held[1]


async def for_send(session: AsyncSession, guild_id: int | None) -> NotificationPolicy:
    """The answer for one community, read once per transaction of ``session``.

    ``session`` is the sender's, and only carries the answer: it is still read
    on the system engine. A fan-out that writes to fifty people in one
    transaction asks once rather than twice per recipient, and the next
    transaction reads again, so a switch changed in between applies to it.
    """
    answers = _answers_for_this_transaction(session)
    if answers is None:
        return await load(guild_id)
    if guild_id not in answers:
        answers[guild_id] = await load(guild_id)
    return answers[guild_id]


async def for_send_many(
    session: AsyncSession, guild_ids: Iterable[int | None]
) -> Mapping[int | None, NotificationPolicy]:
    """:func:`for_send` for a set of communities, in one pass.

    Also holds the deployment's own answer, which the pass reads anyway, for
    the sends that belong to no community.
    """
    wanted = set(guild_ids) | {None}
    answers = _answers_for_this_transaction(session)
    if answers is None:
        return await load_many(wanted)
    missing = wanted - answers.keys()
    if missing:
        answers.update(await load_many(missing))
    return {gid: answers[gid] for gid in wanted}


# --- What a notification says as it leaves ----------------------------------

#: What a channel carries: a push's ``(title, body)``, or a notification email.
Pieces = TypeVar("Pieces", tuple[str, str], "EmailPieces")


def redacted_line(category: NotificationCategory, locale: str) -> tuple[str, str]:
    """The title and body a redacted notification carries, as ``(title, body)``.

    Written per category rather than per type: the category is what the app
    already groups a notification under everywhere else, and the point of a
    redacted line is that it says the kind of thing and stops.
    """
    key = f"redacted.{category.value}"
    return (
        translate(f"{key}.title", locale, namespace="notifications"),
        translate(f"{key}.body", locale, namespace="notifications"),
    )


def apply(
    policy: NotificationPolicy,
    pieces: Pieces,
    *,
    category: NotificationCategory,
    locale: str,
) -> Pieces | None:
    """What ``pieces`` may carry out of the app under ``policy``.

    The channel is the shape of ``pieces``: a ``(title, body)`` pair is a push,
    anything else a notification email. Returns ``None`` where that channel is
    switched off; where content is redacted, the kind of thing that happened in
    ``locale`` — an email keeps its link, which is the way back rather than the
    content; and ``pieces`` as given otherwise.

    Every push and notification email is put through this as it is sent,
    under the switches as they stand then; a writer may also call it earlier to
    store no more than will be sent.
    """
    if isinstance(pieces, tuple):
        if not policy.push:
            return None
        return (
            cast(Pieces, redacted_line(category, locale)) if policy.redact else pieces
        )
    if not policy.email:
        return None
    if not policy.redact:
        return pieces
    title, body = redacted_line(category, locale)
    return replace(pieces, subject=title, headline=title, body=body, link_label=None)


#: What a redacted push's data keeps: where tapping it opens.
_ROUTING_KEYS = frozenset({"type", "community_id", "target_path"})


def push_data(
    policy: NotificationPolicy, data: Mapping[str, object] | None
) -> dict[str, object]:
    """What a push's data payload may carry under ``policy``: all of it, or
    where it is redacted, only where tapping it opens, as an email keeps its
    link."""
    return {
        name: value
        for name, value in (data or {}).items()
        if not policy.redact or name in _ROUTING_KEYS
    }
