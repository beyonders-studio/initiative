"""The published ideas, readable by anybody, and votes for them.

Only Initiative Cloud has an Ideas board; everywhere else every route answers
404. Reading needs nobody signed in. Voting needs an account here, and is
paced per account.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user, get_current_user_optional
from app.core.messages import AuthMessages, IdeaMessages
from app.models.platform.user import User
from app.schemas.platform.idea import IdeaListRead, IdeaRead, IdeaStatusRead
from app.services.platform import ideas as ideas_service

router = APIRouter()

OptionalReader = Annotated[Optional[User], Depends(get_current_user_optional)]
Voter = Annotated[User, Depends(get_current_active_user)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=IdeaMessages.NOT_FOUND
    )


def _status_read(found: ideas_service.IdeaStatus) -> IdeaStatusRead:
    return IdeaStatusRead(
        id=found.id, name=found.name, color=found.color, category=found.category
    )


def _read(idea: ideas_service.IdeaRead) -> IdeaRead:
    return IdeaRead(
        task_id=idea.task_id,
        title=idea.title,
        status=_status_read(idea.status),
        votes=idea.votes,
        voted=idea.voted,
        closed=idea.closed,
        created_at=idea.created_at,
        updated_at=idea.updated_at,
        description=idea.description,
    )


@router.get("", response_model=IdeaListRead)
async def list_ideas(
    reader: OptionalReader,
    q: Annotated[Optional[str], Query(max_length=200)] = None,
    status_id: Optional[int] = None,
    voted: bool = False,
    sort: ideas_service.IdeaSort = ideas_service.IdeaSort.votes,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IdeaListRead:
    """The published ideas: those whose title holds ``q``, in ``status_id``,
    or that the reader voted for, as asked; most voted or newest first."""
    try:
        found = await ideas_service.list_ideas(
            reader,
            q=q,
            status_id=status_id,
            voted_only=voted and reader is not None,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except ideas_service.IdeaNotFound:
        raise _not_found() from None
    return IdeaListRead(
        items=[_read(idea) for idea in found.items],
        total=found.total,
        statuses=[_status_read(s) for s in found.statuses],
    )


@router.get("/{task_id}", response_model=IdeaRead)
async def read_idea(task_id: int, reader: OptionalReader) -> IdeaRead:
    """One published idea, with its description."""
    try:
        _, idea = await ideas_service.read_idea(reader, task_id)
    except ideas_service.IdeaNotFound:
        raise _not_found() from None
    return _read(idea)


async def _vote(voter: User, task_id: int, *, on: bool) -> IdeaRead:
    try:
        return _read(await ideas_service.vote(voter, task_id, on=on))
    except ideas_service.IdeaNotFound:
        raise _not_found() from None
    except ideas_service.VoteRefused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=IdeaMessages.CLOSED
        ) from None
    except ideas_service.VotingTooFast:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.RATE_LIMITED,
        ) from None


@router.put("/{task_id}/vote", response_model=IdeaRead)
async def vote_for_idea(task_id: int, voter: Voter) -> IdeaRead:
    """Vote for an open idea. Voting twice is one vote."""
    return await _vote(voter, task_id, on=True)


@router.delete("/{task_id}/vote", response_model=IdeaRead)
async def take_vote_back(task_id: int, voter: Voter) -> IdeaRead:
    """Take a vote back from an open idea."""
    return await _vote(voter, task_id, on=False)
