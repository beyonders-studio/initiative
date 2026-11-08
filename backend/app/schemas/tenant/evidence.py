"""How an attached file, and what a stream takes, are described."""

from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict

from app.core.intake import EvidencePolicy
from app.schemas.base import SanitizedBaseModel


class EvidenceRead(SanitizedBaseModel):
    """One attached file: what it is called and what it is. Fetched by its
    own route, never by a link that outlives the reader's access."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    #: What its bytes say it is.
    content_type: str
    size_bytes: int
    created_at: datetime


class EvidencePolicyRead(SanitizedBaseModel):
    """What may be attached: how many files, how large, of which types."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    max_files: int
    max_bytes: int
    types: list[str]

    @classmethod
    def of(cls, policy: EvidencePolicy) -> EvidencePolicyRead:
        return cls(
            max_files=policy.max_files,
            max_bytes=policy.max_bytes,
            types=sorted(policy.types),
        )
