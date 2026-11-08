from pydantic import ConfigDict, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class ChangelogEntry(SanitizedBaseModel):
    """One parsed ``## [version] - date`` section of CHANGELOG.md."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    date: str
    # Server-controlled markdown read from CHANGELOG.md and rendered as markdown
    # client-side — not user input. RawTextStr keeps it verbatim and, crucially,
    # skips the plain-text length cap: a single version's section routinely
    # exceeds it (some are >12k chars), and the default sanitizer would reject it.
    changes: RawTextStr


class ChangelogResponse(SanitizedBaseModel):
    """The `/changelog` payload: the most recent N entries (or a single
    requested version)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entries: list[ChangelogEntry] = Field(default_factory=list)
