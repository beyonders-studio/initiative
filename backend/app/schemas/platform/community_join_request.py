"""Asking to join a ``request`` community, and the queue its admins answer."""

from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import UserIdentity
from app.schemas.tenant.initiative import JOIN_REQUEST_MESSAGE_MAX_LENGTH


class CommunityJoinRequestCreate(SanitizedBaseModel):
    """Asking a ``request`` community to let the caller in."""

    # Often the only way the asker can say who they are.
    message: str | None = Field(
        default=None, max_length=JOIN_REQUEST_MESSAGE_MAX_LENGTH
    )


class CommunityJoinRequestRead(SanitizedBaseModel):
    """One request in a community's queue: who is asking, what they wrote and
    when. The asker is not a member, so they are drawn from their public
    profile rather than the community's roster."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    user: UserIdentity
    message: str | None = None
    created_at: datetime
