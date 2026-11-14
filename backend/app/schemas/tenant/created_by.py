"""Who made a row, as a read reports it."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from app.core.identity_boundary import PersonId
from app.models.tenant._mixins import ActorKind
from app.schemas.base import SanitizedBaseModel


class CreatedByRead(SanitizedBaseModel):
    """``created_by_kind`` says who made the row. A member is ``created_by``
    (a person, as every person is read); a plug-in is ``created_by_install``;
    Initiative is neither. One column stores both ids, and the read parts them
    because only a person is a :data:`PersonId`."""

    created_by: PersonId | None = None
    created_by_kind: ActorKind
    created_by_install: int | None = None

    @model_validator(mode="after")
    def _install(self) -> Self:
        if self.created_by_kind is ActorKind.plugin and self.created_by is not None:
            self.created_by_install, self.created_by = self.created_by, None
        return self
