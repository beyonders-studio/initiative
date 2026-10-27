"""Asking for something you can't open or edit, and answering."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field, model_validator

from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.share_request import MAX_MESSAGE_LENGTH, ShareRequestScope
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import UserSummary


def _askable(level: ResourceAccessLevel | None) -> ResourceAccessLevel | None:
    if level is ResourceAccessLevel.owner:
        raise ValueError("owner is given, never asked for")
    return level


class ShareStanding(SanitizedBaseModel):
    """Where the reader stands on one thing they can open, or know is there:
    on the tool whose sharing decides it, which is what to ask for."""

    resource_type: Tool
    resource_id: int
    initiative_id: int
    #: The rung they hold, or ``None`` where they can't open it.
    level: Optional[ResourceAccessLevel] = None
    #: The rung they asked for and nobody has answered yet.
    pending: Optional[ResourceAccessLevel] = None


class HiddenFiles(SanitizedBaseModel):
    """The files of a collection or a wiki the reader knows are there and
    can't open, and how many of those they have asked for."""

    count: int = 0
    requested: int = 0


class ShareRequestCreate(SanitizedBaseModel):
    """Ask for one thing, or for the files of a collection or a wiki the
    reader can't open."""

    resource_type: Tool
    resource_id: Optional[int] = None
    collection_id: Optional[int] = None
    wiki_id: Optional[int] = None
    level: ResourceAccessLevel = ResourceAccessLevel.read
    message: Optional[str] = Field(default=None, max_length=MAX_MESSAGE_LENGTH)

    @model_validator(mode="after")
    def _one_target(self) -> "ShareRequestCreate":
        _askable(self.level)
        named = [x for x in (self.resource_id, self.collection_id, self.wiki_id) if x]
        if len(named) != 1:
            raise ValueError("name one thing, one collection or one wiki")
        if self.resource_id is None and self.resource_type is not Tool.file:
            raise ValueError("a collection or a wiki holds files")
        return self


class ShareRequestBatch(SanitizedBaseModel):
    """The requests one ask made."""

    batch_id: UUID
    count: int


class ShareRequestRead(SanitizedBaseModel):
    """One request waiting on the reader's answer."""

    id: int
    batch_id: UUID
    resource_type: Tool
    resource_id: int
    #: What the thing is called, as the reader reads it.
    resource_name: str
    initiative_id: int
    user: UserSummary
    #: When the requester's time as a guest ends; ``None`` for a member.
    guest_until: Optional[datetime] = None
    level: ResourceAccessLevel
    message: Optional[str] = None
    created_at: datetime


class ShareRequestAnswer(SanitizedBaseModel):
    """A yes or a no to some of the requests the reader may answer."""

    ids: list[int] = Field(min_length=1, max_length=500)
    approve: bool
    #: The rung a yes gives; the one asked for where it is left out.
    level: Optional[ResourceAccessLevel] = None
    #: Whether a yes reaches the requester or the whole initiative.
    scope: ShareRequestScope = ShareRequestScope.user
    #: Whether a no is told to the requester.
    tell: bool = False

    @model_validator(mode="after")
    def _level(self) -> "ShareRequestAnswer":
        _askable(self.level)
        return self
