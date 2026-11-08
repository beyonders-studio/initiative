"""The published ideas, as anybody reads them, and the team's Idea panel."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from app.schemas.base import SanitizedBaseModel


class IdeaStatusRead(SanitizedBaseModel):
    """A status of the Ideas board, under the name the team gave it."""

    id: int
    name: str
    color: Optional[str] = None
    #: ``todo``, ``in_progress`` or ``done``; a ``done`` idea is closed.
    category: str


class IdeaRead(SanitizedBaseModel):
    """One published idea."""

    task_id: int
    title: str
    status: IdeaStatusRead
    votes: int
    #: Whether the reader voted for it; false for somebody signed out.
    voted: bool
    #: A closed idea keeps its votes and takes no change to them.
    closed: bool
    published_at: datetime
    updated_at: Optional[datetime] = None
    #: Only on one idea's own page.
    description: Optional[str] = None


class IdeaListRead(SanitizedBaseModel):
    """A page of the published ideas, and every status of the board."""

    items: List[IdeaRead]
    total: int
    statuses: List[IdeaStatusRead]


class IdeaPanelRead(SanitizedBaseModel):
    """What the team sees of an Ideas-board task."""

    published_at: Optional[datetime] = None
    votes: int
