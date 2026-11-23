"""Schemas for the cross-guild tool views."""

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel


class MyToolCountsResponse(SanitizedBaseModel):
    """How much of each tool reaches the caller across their communities.

    Keyed by the tool's kind rather than fielded per tool: every built-in
    tool, and each tool plug-in installed in one of the caller's communities.
    A built-in tool the caller has nothing of is present with a zero, not
    absent — the difference between "none" and "not asked" matters to the
    page deciding which tabs to draw.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: dict[str, int] = Field(default_factory=dict)
