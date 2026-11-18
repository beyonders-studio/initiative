"""Sending somebody something: pointing them at it, in the app."""

from __future__ import annotations

from pydantic import Field, field_validator

from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.share_request import MAX_MESSAGE_LENGTH
from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.personal_item import ContentKind


class SendCreate(SanitizedBaseModel):
    """Point people at one thing, with a note if there is one.

    ``level`` lets those who can't open it in, at that rung, where the sender
    may share it; left out, they are told it is there and may ask for it."""

    kind: ContentKind
    entity_id: int
    user_ids: list[int] = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    level: ResourceAccessLevel | None = None

    @field_validator("level")
    @classmethod
    def _givable(cls, level: ResourceAccessLevel | None) -> ResourceAccessLevel | None:
        if level is ResourceAccessLevel.owner:
            raise ValueError("A send gives view or edit, never ownership")
        return level


class SendResult(SanitizedBaseModel):
    """Who heard, and how: sent what they can open, let in to it first, or
    told it is there to ask for."""

    sent: list[int]
    let_in: list[int]
    may_ask: list[int]
