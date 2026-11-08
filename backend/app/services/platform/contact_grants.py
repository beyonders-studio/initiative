"""Connections and message requests — what two accounts have agreed.

Both live in ``contact_grants``, one row per unordered pair per kind, and they
do different jobs. A **connection** satisfies every ``DmPolicy`` and opens
nothing on its own; an accepted **message** grant is what opens the channel.
So a pair on ``private`` needs both.

Two rules here are worth finding when you come back to this module:

* ``initial_message_state`` — a message grant between connected accounts starts
  accepted. That is a statement about what a connection currently *means*, not
  about messaging, and it is the one place to delete when a connection carries
  anything else.
* ``revoke_stale_message_grants`` — a grant lives only while the pair could ask
  each other today. Five events take a leg of ``can_ask`` away, and all five
  run the same test rather than each carrying a rule of its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
import logging
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.errors import CodedError
from app.db import post_commit
from app.models.platform.contact_grant import (
    ContactGrant,
    ContactGrantKind,
    ContactGrantState,
    canonical_pair,
)
from app.models.platform.user_ignore import UserIgnore
from app.services.platform import contact_notifications
from app.services.platform import connections_stream, user_stream
from app.services.platform import presence as presence_service
from app.services.platform import user_ignores
from app.schemas.platform.dm import (
    ContactGrantRead,
    ContactGrantsResponse,
)


class ContactGrantError(CodedError):
    """A refused grant. Every refusal is a 409 with its code and nothing else:
    a handle nobody holds, an account that cannot be reached and a request that
    will never be surfaced all answer the same way, so the endpoint is not a
    way to learn which it was."""

    status_code = 409


def initial_message_state(connected: bool) -> ContactGrantState:
    """The state a message grant is born in.

    Connected accounts get an accepted one: asking somebody to connect and then
    asking them again for permission to say hello is a consent step with no
    decision in it. Not a rule about messaging — a rule about what a connection
    currently means. When a connection carries anything besides messaging, this
    returns ``pending`` again and nothing else moves.
    """
    return ContactGrantState.accepted if connected else ContactGrantState.pending


async def _get(
    session: AsyncSession, a: int, b: int, kind: ContactGrantKind
) -> ContactGrant | None:
    low, high = canonical_pair(a, b)
    return await session.get(ContactGrant, (low, high, kind))


async def are_connected(session: AsyncSession, a: int, b: int) -> bool:
    row = await _get(session, a, b, ContactGrantKind.connection)
    return row is not None and row.state is ContactGrantState.accepted


async def _may_connect(session: AsyncSession, target_id: int) -> bool:
    """Whether the caller may send this account a connection request.

    ``dm_may_connect`` reads the caller from the request context, so this asks
    about the caller and one other account and cannot be pointed elsewhere.
    """
    return (
        await session.exec(
            text("SELECT public.dm_may_connect(:t)").bindparams(t=target_id)
        )
    ).scalar_one()


async def _may_message(session: AsyncSession, target_id: int) -> bool:
    """Whether the caller and this account could open a channel today.

    The same answer the profile shows, from the same function — ``denied``
    covers every refusal, including being ignored, which the caller is not told
    apart from the rest.
    """
    permission = (
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=target_id)
        )
    ).scalar_one()
    return permission in ("may_request", "open")


async def _pair_still_allowed(session: AsyncSession, a: int, b: int) -> bool:
    """``public.dm_mutual_ask`` for a pair that need not involve the caller.

    Only the system engine may ask this, which is why the sweep runs there.
    """
    return (
        await session.exec(
            text("SELECT public.dm_mutual_ask(:a, :b)").bindparams(a=a, b=b)
        )
    ).scalar_one()


async def list_for(
    session: AsyncSession, *, user_id: int, kind: ContactGrantKind
) -> list[ContactGrant]:
    """Every grant of one kind this account is a party to.

    Rows whose other party the reader ignores are dropped, so a request from
    somebody they have stopped hearing from is not a way back to their
    attention. The row stays; it becomes visible again if the ignore is lifted.
    """
    rows = (
        await session.exec(
            select(ContactGrant)
            .where(
                ContactGrant.kind == kind,
                or_(
                    ContactGrant.user_id_low == user_id,
                    ContactGrant.user_id_high == user_id,
                ),
            )
            .order_by(col(ContactGrant.created_at).desc())
        )
    ).all()
    if not rows:
        return []

    ignored = set(
        (
            await session.exec(
                select(UserIgnore.ignored_user_id).where(UserIgnore.user_id == user_id)
            )
        ).all()
    )
    # One direction only, and deliberately: what is dropped is a row whose other
    # party *the reader* ignores. An account that ignores the reader has not
    # stopped itself reaching them — ignoring governs arrival at the person who
    # did it, so their request still lands, and their own inbox is where it goes
    # quiet.
    return [row for row in rows if other_party(row, user_id) not in ignored]


def other_party(grant: ContactGrant, user_id: int) -> int:
    return grant.user_id_high if grant.user_id_low == user_id else grant.user_id_low


async def request(
    session: AsyncSession,
    *,
    actor_id: int,
    target_id: int,
    kind: ContactGrantKind,
) -> ContactGrant:
    """Ask for a connection, or for permission to message.

    A crossing request — the other party asking while yours is pending — is a
    primary-key collision rather than a race, and it means both of them wanted
    it, so it is turned into an accept.

    An account that ignores the actor still gets the row: it is stored, never
    surfaced to them, and becomes acceptable if they ever stop. Refusing here
    would answer a question this feature does not answer.
    """
    from app.core.messages import ContactGrantMessages

    if actor_id == target_id:
        raise ContactGrantError(ContactGrantMessages.CANNOT_GRANT_SELF)

    existing = await _get(session, actor_id, target_id, kind)
    if existing is not None:
        if existing.state is ContactGrantState.accepted:
            return existing
        if existing.requested_by == actor_id:
            return existing
        return await accept(session, actor_id=actor_id, other_id=target_id, kind=kind)

    allowed = (
        await _may_connect(session, target_id)
        if kind is ContactGrantKind.connection
        else await _may_message(session, target_id)
    )
    if not allowed:
        raise ContactGrantError(ContactGrantMessages.CANNOT_REACH)

    low, high = canonical_pair(actor_id, target_id)
    state = (
        initial_message_state(await are_connected(session, actor_id, target_id))
        if kind is ContactGrantKind.message
        else ContactGrantState.pending
    )
    now = datetime.now(timezone.utc)
    grant = ContactGrant(
        user_id_low=low,
        user_id_high=high,
        kind=kind,
        state=state,
        requested_by=actor_id,
        created_at=now,
        responded_at=now if state is ContactGrantState.accepted else None,
    )
    session.add(grant)
    # The recipient hears about it unless they ignore the requester, in which
    # case the row is stored and stays out of their sight — a frame would say
    # what the hidden row does not.
    if not await user_ignores.ignores(
        session, user_id=target_id, other_user_id=actor_id
    ):
        connections_stream.queue_connections_signal(session, target_id)
    connections_stream.queue_connections_signal(session, actor_id)
    await session.commit()
    await session.refresh(grant)
    # A stream frame only reaches a client that is already open. The request is
    # waiting on a person, so the one holding a closed phone has to be told too.
    # An already-accepted message grant asked nobody anything, and announcing it
    # would be a notification about a decision that was never made.
    if grant.state is not ContactGrantState.accepted:
        await contact_notifications.notify(
            recipient_id=target_id, actor_id=actor_id, kind=kind, accepted=False
        )
    return grant


async def accept(
    session: AsyncSession,
    *,
    actor_id: int,
    other_id: int,
    kind: ContactGrantKind,
) -> ContactGrant:
    """Say yes to a request somebody else made.

    Accepting a connection also opens the pair's message grant, per
    ``initial_message_state`` — one act, one consent, and one notification.
    """
    from app.core.messages import ContactGrantMessages

    grant = await _get(session, actor_id, other_id, kind)
    if grant is None or grant.requested_by == actor_id:
        raise ContactGrantError(ContactGrantMessages.NO_REQUEST)
    if grant.state is ContactGrantState.accepted:
        return grant

    grant.state = ContactGrantState.accepted
    grant.responded_at = datetime.now(timezone.utc)
    session.add(grant)

    if kind is ContactGrantKind.connection:
        await _open_message_grant(session, actor_id, other_id, grant.requested_by)

    connections_stream.queue_connections_signal(session, actor_id)
    connections_stream.queue_connections_signal(session, other_id)
    await session.commit()
    await session.refresh(grant)
    # The one who asked is the one waiting for an answer, so they are the one
    # told. Whether they ignore the accepter is not consulted: they started this.
    await contact_notifications.notify(
        recipient_id=other_id, actor_id=actor_id, kind=kind, accepted=True
    )
    return grant


async def _open_message_grant(
    session: AsyncSession, a: int, b: int, requested_by: int
) -> None:
    """Give a newly connected pair their channel.

    Flips an in-flight pending request rather than colliding with it: the
    connection answers the same question it was asking.
    """
    existing = await _get(session, a, b, ContactGrantKind.message)
    now = datetime.now(timezone.utc)
    if existing is not None:
        if existing.state is not ContactGrantState.accepted:
            existing.state = ContactGrantState.accepted
            existing.responded_at = now
            session.add(existing)
        return
    low, high = canonical_pair(a, b)
    session.add(
        ContactGrant(
            user_id_low=low,
            user_id_high=high,
            kind=ContactGrantKind.message,
            state=ContactGrantState.accepted,
            requested_by=requested_by,
            created_at=now,
            responded_at=now,
        )
    )


async def remove(
    session: AsyncSession,
    *,
    actor_id: int,
    other_id: int,
    kind: ContactGrantKind,
) -> None:
    """Decline, cancel, disconnect or close — one verb, one delete.

    There is no ``declined`` state to store: the pair is back where it started
    and either may ask again. Removing a *connection* re-tests the pair's
    message grant rather than deleting it: a connection is a leg of ``can_ask``,
    not a rank above the others, so two co-members who un-connect keep talking.
    """
    grant = await _get(session, actor_id, other_id, kind)
    if grant is None:
        return
    await session.delete(grant)
    await session.flush()
    if kind is ContactGrantKind.connection:
        await _revoke_pair_if_stale(session, actor_id, other_id)
    connections_stream.queue_connections_signal(session, actor_id)
    connections_stream.queue_connections_signal(session, other_id)
    await session.commit()


async def _revoke_pair_if_stale(
    session: AsyncSession, caller_id: int, other_id: int
) -> None:
    """Re-test one pair after a connection between them went away.

    The caller is one of the two, so the question is theirs to ask and the row
    is theirs to delete.
    """
    grant = await _get(session, caller_id, other_id, ContactGrantKind.message)
    if grant is None:
        return
    if not await _may_message(session, other_id):
        await session.delete(grant)
        await session.flush()


async def revoke_stale_message_grants(
    session: AsyncSession | None, *, user_id: int
) -> int:
    """Drop every message grant this account could no longer form today.

    Called wherever a leg of ``can_ask`` goes away — a policy change, a
    community switched off, a membership dropped, a community suspended, a
    connection removed. All five ask the one question rather than each carrying
    a rule of its own, so a grant is revoked for the same reason it would be
    refused.

    Runs on the system engine, on its own session. The pairs need not involve
    whoever is making the request — removing somebody from a community re-tests
    *their* grants — and neither the pairwise test nor those rows are the
    request path's to reach.

    It must see the state the prompting change left behind, so callers reach it
    through ``queue_stale_grant_sweep`` rather than calling it mid-transaction.
    ``session`` is accepted and unused, so a test can drive it directly.

    Returns how many were dropped, so a caller can decide whether to signal.
    """
    from app.db.session import SystemSessionLocal

    dropped = 0
    async with SystemSessionLocal() as system_session:
        grants = (
            await system_session.exec(
                select(ContactGrant).where(
                    ContactGrant.kind == ContactGrantKind.message,
                    or_(
                        ContactGrant.user_id_low == user_id,
                        ContactGrant.user_id_high == user_id,
                    ),
                )
            )
        ).all()
        touched: set[int] = set()
        for grant in grants:
            if not await _pair_still_allowed(
                system_session, grant.user_id_low, grant.user_id_high
            ):
                await system_session.delete(grant)
                touched.update({grant.user_id_low, grant.user_id_high})
                dropped += 1
        if dropped:
            # Both sides of every pair that actually went — which is already
            # the bound worth having: a community's worth of revocations costs
            # the pairs revoked, not the size of the membership.
            user_stream.queue_signals(
                system_session, touched, connections_stream.RESOURCE
            )
            await system_session.commit()
    return dropped


async def resolve_handle(
    session: AsyncSession, *, username: str, discriminator: int
) -> int:
    """The account id behind a handle, for a connection request.

    One answer for every miss: a handle nobody holds and a handle belonging to
    somebody unreachable raise the same code, so the endpoint says only whether
    a connection can be made and never whether an account is there.
    """
    from app.core.messages import ContactGrantMessages

    row = (
        await session.exec(
            text(
                "SELECT id FROM public.user_profiles "
                "WHERE lower(username) = lower(:u) AND discriminator = :d"
            ).bindparams(u=username, d=discriminator)
        )
    ).first()
    if row is None:
        raise ContactGrantError(ContactGrantMessages.CANNOT_REACH)
    return row[0]


async def to_reads(
    session: AsyncSession, *, user_id: int, grants: list[ContactGrant]
) -> ContactGrantsResponse:
    """Group a reader's grants into accepted, incoming and outgoing."""
    if not grants:
        return ContactGrantsResponse(accepted=[], incoming=[], outgoing=[])

    others = {other_party(grant, user_id) for grant in grants}
    profiles = {
        row[0]: row
        for row in (
            await session.exec(
                text(
                    "SELECT id, username, discriminator, avatar_url, status, "
                    "profile_decorations "
                    "FROM public.user_profiles WHERE id = ANY(:ids)"
                ).bindparams(ids=list(others))
            )
        ).all()
    }

    accepted: list[ContactGrantRead] = []
    incoming: list[ContactGrantRead] = []
    outgoing: list[ContactGrantRead] = []
    for grant in grants:
        other = other_party(grant, user_id)
        profile = profiles.get(other)
        if profile is None:
            continue
        read = ContactGrantRead(
            user_id=other,
            username=profile[1],
            discriminator=profile[2],
            avatar_url=profile[3],
            status=profile[4],
            profile_decorations=profile[5] or {},
            presence=presence_service.online.presence_of(other),
            state=grant.state.value,
            outgoing=grant.requested_by == user_id,
            created_at=grant.created_at,
            responded_at=grant.responded_at,
        )
        if grant.state is ContactGrantState.accepted:
            accepted.append(read)
        elif read.outgoing:
            outgoing.append(read)
        else:
            incoming.append(read)
    return ContactGrantsResponse(
        accepted=accepted, incoming=incoming, outgoing=outgoing
    )


logger = logging.getLogger(__name__)

#: Keys a sweep per account per transaction.
_SWEEP_KEY = "contact_grants_sweep"


def queue_stale_grant_sweep(session: Any, user_id: int | None) -> None:
    """Re-test this account's channels once the transaction commits.

    The sweep reads the state the change left behind, so it cannot run while
    that change is still uncommitted — a membership deleted but not committed
    still answers ``dm_mutual_ask`` as present, and the channel that rested on
    it would be kept. Registered with ``post_commit.after_commit``, which
    ``user_stream.queue_frame`` uses for the same reason.

    A rollback discards the sweep, so nothing is revoked for a change that did
    not happen. And a sweep that never runs costs correctness nothing: rule 3
    recomputes ``mutual_ask`` on every call, so a row left behind grants no
    access — it is only tidier for it to be gone.
    """
    if user_id is None:
        return
    post_commit.after_commit(
        session, partial(_sweep_quietly, user_id), key=(_SWEEP_KEY, user_id)
    )


async def _sweep_quietly(user_id: int) -> None:
    try:
        await revoke_stale_message_grants(None, user_id=user_id)
    except Exception:  # pragma: no cover - best effort, the rule still holds
        logger.debug("contact_grants: stale sweep failed", exc_info=True)
