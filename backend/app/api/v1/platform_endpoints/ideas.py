"""The published ideas, readable by anybody, and votes for them.

Only Initiative Cloud has an Ideas board; everywhere else every route answers
404. Reading needs nobody signed in. Voting needs an account here, and is
paced per account.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user, get_current_user_optional
from app.core.messages import AuthMessages, IdeaMessages
from app.db.query import build_paginated_response
from app.models.platform.user import User
from app.schemas.platform.idea import IdeaListRead, IdeaRead, IdeaStatusRead
from app.services.platform import ideas as ideas_service

router = APIRouter()

OptionalReader = Annotated[User | None, Depends(get_current_user_optional)]
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
    search: Annotated[str | None, Query(max_length=200)] = None,
    status_id: int | None = None,
    voted: bool = False,
    sort: ideas_service.IdeaSort = ideas_service.IdeaSort.votes,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IdeaListRead:
    """The published ideas: those whose title holds ``search``, in ``status_id``,
    or that the reader voted for, as asked; most voted or newest first."""
    try:
        found = await ideas_service.list_ideas(
            reader,
            search=search,
            status_id=status_id,
            voted_only=voted and reader is not None,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except ideas_service.IdeaNotFound:
        raise _not_found() from None
    return IdeaListRead(
        **build_paginated_response(
            [_read(idea) for idea in found.items],
            found.total,
            page,
            page_size,
            statuses=[_status_read(s) for s in found.statuses],
        )
    )


@router.get("/similar", response_model=list[IdeaRead])
async def similar_ideas(
    reader: OptionalReader,
    text: Annotated[str, Query(min_length=1, max_length=1000)],
) -> list[IdeaRead]:
    """The open published ideas whose title is close to ``text``, closest
    first: what somebody writing feedback may vote for instead."""
    try:
        found = await ideas_service.similar(reader, text)
    except ideas_service.IdeaNotFound:
        raise _not_found() from None
    return [_read(idea) for idea in found]


@router.get("/{task_id}", response_model=IdeaRead)
async def read_idea(task_id: int, reader: OptionalReader) -> IdeaRead:
    """One published idea, with its description. An idea joined into another
    answers with the one it joined, which has another ``task_id``."""
    try:
        _, idea = await ideas_service.read_idea(reader, task_id)
    except ideas_service.IdeaNotFound:
        target = await ideas_service.joined_into(task_id)
        if target is None:
            raise _not_found() from None
        try:
            _, idea = await ideas_service.read_idea(reader, target)
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
