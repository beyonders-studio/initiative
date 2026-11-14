"""The published ideas, as anybody reads them."""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import SanitizedBaseModel
from app.schemas.query import PageMeta


class IdeaStatusRead(SanitizedBaseModel):
    """A status of the Ideas board, under the name the team gave it."""

    id: int
    name: str
    color: str | None = None
    #: The status's icon, by name.
    icon: str | None = None
    #: ``todo``, ``in_progress`` or ``done``; a ``done`` idea is closed.
    category: str


class IdeaRead(SanitizedBaseModel):
    """One published idea."""

    task_id: int
    title: str
    #: The status it reads as: a shipped idea reads as shipped once the
    #: release it shipped in is this server's, and as the board's last
    #: in-progress status before then.
    status: IdeaStatusRead
    votes: int
    #: Whether the reader voted for it; false for somebody signed out.
    voted: bool
    #: A closed idea keeps its votes and takes no change to them.
    closed: bool
    created_at: datetime
    updated_at: datetime | None = None
    #: Its category's name, where it has one.
    category: str | None = None
    #: The release it shipped in, where it reads as shipped.
    release: str | None = None
    #: The first paragraph of its description, as plain text; in a list.
    summary: str | None = None
    #: Only on one idea's own page.
    description: str | None = None


class IdeaCategoryCount(SanitizedBaseModel):
    """One category, and how many of the ideas the list can show are in it."""

    name: str
    count: int


class IdeaListRead(PageMeta):
    """A page of the published ideas, the statuses they read as, and the
    categories they are in."""

    items: list[IdeaRead]
    statuses: list[IdeaStatusRead]
    #: Each category with an idea the list can show, the category filter
    #: aside, in the field's order.
    categories: list[IdeaCategoryCount]


class IdeaRoadmapColumn(SanitizedBaseModel):
    """One status on the roadmap, and the ideas that read as it."""

    status: IdeaStatusRead
    items: list[IdeaRead]


class IdeaRoadmapRead(SanitizedBaseModel):
    """The board's in-progress statuses in its order, then its shipped
    status."""

    columns: list[IdeaRoadmapColumn]
