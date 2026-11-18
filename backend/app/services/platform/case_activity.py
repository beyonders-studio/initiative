"""What the platform writes on an operations case, as the case goes on.

A case is a task, and its comments are its history. Most of that history is
people working it; the rest is the platform noting what happened around it — a
report seen again, and in later phases a reply from whoever filed it, a grant
issued against it, a rule tripping again. This module is the one writer of
those notes, so every kind is worded in one place and every note looks alike.

A note is an ordinary comment with no author and a ``system_kind`` naming what
wrote it. That is what tells it from a comment an installed plug-in wrote, which
names no author either. Notes are said to the case's members only: nothing the
platform notes reaches the person who filed the case.

Notes carry ids, counts and what somebody typed into the filing itself —
never content read out of another community.
"""

from __future__ import annotations

from enum import Enum

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.comment import Comment, CommentAudience


class ActivityKind(str, Enum):
    """What a note on a case is about."""

    #: The source of an open case was seen again.
    repeat = "repeat"
    #: Content was held for the platform on this case.
    hold_placed = "hold_placed"
    #: A hold on this case was released.
    hold_released = "hold_released"
    #: A hold on this case is still in place.
    hold_reminder = "hold_reminder"
    #: The community settled its own report of what this case is about.
    community_settled = "community_settled"
    #: What this case is about should be held, and nothing has held it yet.
    hold_requested = "hold_requested"
    #: Somebody asked for access to a community for this case.
    grant_requested = "grant_requested"
    #: An access request for this case was approved, denied or revoked.
    grant_decided = "grant_decided"
    #: What a grant for this case did, so far or in all.
    grant_digest = "grant_digest"
    #: A moderation act taken under a grant for this case.
    moderation_act = "moderation_act"
    #: A community's status changed under a grant for this case.
    guild_act = "guild_act"
    #: Staff acted on an account for this case.
    account_act = "account_act"


def repeat_text(*, occurrences: int, detail: str | None) -> str:
    """The note for a source seen again, with whatever the new filing said."""
    seen = f"Seen again ({occurrences} times in all)."
    if not detail:
        return seen
    return f"{seen} New detail:\n\n{detail}"


async def post(
    session: AsyncSession, *, task_id: int, kind: ActivityKind, text: str
) -> Comment:
    """Note ``text`` on the case task ``task_id``, as the platform.

    ``session`` must already be routed into the operations guild by
    ``guild_id`` alone, as the intake writer's is: with no user in the
    routing, the ``created_by`` trigger leaves the author empty, which is the
    truthful answer for a note nobody signed in wrote.
    """
    note = Comment(
        subject_type="task",
        subject_id=task_id,
        content=text,
        audience=CommentAudience.members,
        system_kind=kind.value,
    )
    session.add(note)
    await session.flush()
    return note
