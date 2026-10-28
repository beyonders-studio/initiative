"""The fields every tool's read carries, and the one way they are filled, and
the body every tool's duplicate takes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, TYPE_CHECKING, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.core.identity_boundary import GuildId, PersonId
from app.schemas.base import MAX_TITLE_LENGTH, SanitizedBaseModel
from app.schemas.tenant.archive import ToolState
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.property import PropertySummary, annotated_properties
from app.schemas.tenant.tag import TagSummary, annotated_tags

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext

Model = TypeVar("Model", bound=BaseModel)
Summary = TypeVar("Summary", bound="ToolSummaryBase")

_UNSET = object()


class ToolSummaryBase(ToolState):
    """What every tool's summary reports beside its own fields."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    created_by: PersonId | None = None
    created_at: datetime
    updated_at: datetime
    # When false this entity's comment thread is off — the UI renders none
    # and the API refuses to read or post one. Tasks are unaffected; their
    # thread belongs to the task, not to the tool.
    comments_enabled: bool = True
    tags: List[TagSummary] = Field(default_factory=list)
    # Every tool carries custom properties, filled by
    # ``metadata_service.annotate_properties`` beside the tags.
    properties: List[PropertySummary] = Field(default_factory=list)
    # The full sharing state — every resource_grants row for this tool. Exposed
    # on the summary so a list can manage sharing without a detail fetch.
    grants: List[ResourceGrantSchema] = Field(default_factory=list)

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        """The fields this tool works out from ``row`` rather than reading off
        it by name."""
        return {}


class ToolDuplicateRequest(SanitizedBaseModel):
    """What a duplicate of any tool may be told. Left out, the copy goes beside
    its source as "<name> (Copy)"; in another initiative it keeps the name."""

    #: Held to the rule its tool holds a name to (``tool_copy.duplicate``):
    #: free of reserved sigils except where the tool's names may carry them.
    name: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    target_initiative_id: Optional[int] = None


def from_row(schema: type[Model], row: Any, **fields: Any) -> Model:
    """``schema`` built from ``fields``, and from ``row``'s attribute of the same
    name for every other field it has one for.

    Built through the constructor rather than ``from_attributes``, so the
    schema's input validators run on what the row holds."""
    for name in schema.model_fields.keys() - fields.keys():
        value = getattr(row, name, _UNSET)
        if value is not _UNSET:
            fields[name] = value
    return schema(**fields)


def serialize_tool(
    schema: type[Summary],
    row: Any,
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    **fields: Any,
) -> Summary:
    """One tool row in ``schema``: its columns, the sharing state, tags,
    properties and affordances every tool reports alike, the schema's
    :meth:`~ToolSummaryBase.derived_fields`, and then ``fields``."""
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import client_access, serialize_grants

    return from_row(
        schema,
        row,
        **{
            "guild_id": context.guild_id,
            "can": client_access(row, user_id, context=context),
            "tags": annotated_tags(row),
            "properties": annotated_properties(row),
            "grants": serialize_grants(row, context=context),
            **schema.derived_fields(row, context=context, user_id=user_id),
            **fields,
        },
    )
