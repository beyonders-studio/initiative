"""The wire shape of an edge.

An endpoint is named the way a ``#`` link names one — ``task:12``, the string
``core.references.format_ref`` produces — so one spelling addresses a thing
across references, search and this. Node ids are an internal addressing detail
and never appear here.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator

from app.core.references import REF_SEPARATOR
from app.core.relationships import ENDPOINT_KINDS, RelationshipType
from app.core.tools import Tool
from app.core.search import SearchEntityType
from app.schemas.base import SanitizedBaseModel


class EndpointRef(SanitizedBaseModel):
    """One end of an edge: what kind of thing, and which one."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: SearchEntityType
    id: int

    @field_validator("type")
    @classmethod
    def _must_be_an_endpoint(cls, value: SearchEntityType) -> SearchEntityType:
        if value not in ENDPOINT_KINDS:
            raise ValueError(f"{value.value} cannot sit on a relationship")
        return value

    @property
    def ref(self) -> str:
        return f"{self.type.value}{REF_SEPARATOR}{self.id}"


class RelationshipCreate(SanitizedBaseModel):
    """Make one edge. Provenance is not here — it is the code path's to state,
    never a request's, because it is the weight any later scoring reads."""

    source: EndpointRef
    relationship_type: RelationshipType
    target: EndpointRef


class RelatedEnd(SanitizedBaseModel):
    """The far end of an edge, as the caller's side sees it.

    Enough to draw the thing and link to it, because a list of edges is a list of
    mixed kinds and a reader should not have to fetch each one to find out what it
    is called, what it looks like or where it lives.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: SearchEntityType
    id: int
    title: Optional[str] = None
    initiative_id: Optional[int] = None
    #: When the far end last changed, for the surfaces that order by recency.
    #: None for a kind that records no such moment.
    updated_at: Optional[datetime] = None
    #: The tool this thing is addressed inside, and which one. A task is
    #: addressed in its project and an event in its calendar, so these are what
    #: an address is built from for the kinds that have no page of their own.
    #: The same pair a search hit carries, from the same declaration.
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None
    #: What that tool is called. A list of links is a list of mixed things, and
    #: a name is often not enough to tell two of them apart — six projects run
    #: from one template hold six tasks called "Do a thing". None for a far end
    #: that IS a tool.
    tool_title: Optional[str] = None
    #: What it shows of itself besides its name: a picture, an emoji, or a
    #: colour. At most one is set, and most kinds set none — those draw as their
    #: kind's own icon. A picture URL has already fallen back from a thumbnail to
    #: the full image, so a caller renders what it is given.
    #: Pictures to draw, newest first. A file has its featured image at
    #: most; a library has the cover somebody chose, or the newest few when
    #: nobody did — which is what a library shows of itself everywhere else.
    image_urls: List[str] = Field(default_factory=list)
    icon: Optional[str] = None
    color: Optional[str] = None
    #: What sort of thing it is within its kind, for the kinds whose icon is not
    #: fixed: a spreadsheet, a whiteboard and a PDF are all files, and none
    #: of them should be drawn as a scroll. The same three facts a recent item
    #: carries, plus where a smart link points, so a client picks the icon with
    #: the helper it already has. Only files set any of these.
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
    smart_link_url: Optional[str] = None
    #: Whether the far end is still outstanding — whether, were this a
    #: ``depends_on`` edge, it would still be holding the anchor up. None for a
    #: kind that has no notion of finishing, which is most of them: a file
    #: is never "done". See :mod:`app.db.blocking`.
    is_open: Optional[bool] = None


class RelationshipRead(SanitizedBaseModel):
    """One edge, rendered from the asking entity's side.

    ``direction`` is which way it runs relative to the entity asked about, so a
    caller never has to know that a symmetric edge is stored in node-id order.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    relationship_type: RelationshipType
    direction: str
    other: RelatedEnd
    provenance: str
    confidence: Optional[float] = None
    created_by: Optional[int] = None
    created_at: datetime


class TaskEdgeRead(SanitizedBaseModel):
    """One edge from or to a task of a project, as it is stored: the source
    depends on, is part of, or is related to the target."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    source_id: int
    target_id: int
    relationship_type: RelationshipType


class LinkedTaskRead(SanitizedBaseModel):
    """A task of another project at the far end of one of those edges, as a
    Gantt draws it beside the project's own."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    title: str
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    project_id: int
    project_name: str
    initiative_id: int
    done: bool


class TaskEdgesRead(SanitizedBaseModel):
    """A project's task edges, and the other projects' tasks they reach."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    edges: List[TaskEdgeRead]
    others: List[LinkedTaskRead]


class NeighbourhoodNode(SanitizedBaseModel):
    """One thing in a neighbourhood, and how many hops out it was found."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    end: RelatedEnd
    depth: int


class NeighbourhoodEdge(SanitizedBaseModel):
    """One link in a neighbourhood, from the side the walk reached it on.

    ``direction`` is relative to ``anchor``, as a :class:`RelationshipRead`'s is
    to the entity asked about.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    relationship_type: RelationshipType
    anchor: EndpointRef
    other: EndpointRef
    direction: str
    provenance: str


class NeighbourhoodRead(SanitizedBaseModel):
    """Everything within some hops of one thing, in one answer."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    nodes: List[NeighbourhoodNode]
    edges: List[NeighbourhoodEdge]
