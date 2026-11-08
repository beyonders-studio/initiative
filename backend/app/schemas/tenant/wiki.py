from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import AliasChoices, ConfigDict, Field

from app.core.identity_boundary import GuildId, PersonId
from app.models.tenant.wiki import WikiPageOrder, WikiReadingWidth
from app.schemas.base import LexicalState, MentionStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.file import smart_link_url
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.share_request import HiddenFiles
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import ToolSummaryBase, from_row

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


class WikiBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[MentionStr] = Field(default=None, max_length=2000)


class WikiCreate(WikiBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes. A
    # wiki defaults to readable by the whole initiative: it is written to be
    # read.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class WikiSettings(SanitizedBaseModel):
    """What a wiki is *for*, as the handful of choices that differ.

    Every field is optional on the way in and only what is sent is written, so
    one switch is one request rather than a whole form.
    """

    #: How siblings are ordered in the tree.
    page_order: Optional[WikiPageOrder] = None
    #: How deep the contents rail goes — 2 to 4 heading levels.
    contents_depth: Optional[int] = Field(default=None, ge=2, le=4)
    #: Whether a page shows what links to it.
    show_connections: Optional[bool] = None
    show_updated_at: Optional[bool] = None
    #: Whether a page's body fills the screen or holds to a reading measure.
    reading_width: Optional[WikiReadingWidth] = None
    #: The wiki's own accent, as a CSS colour. ``null`` takes the app's.
    accent_color: Optional[str] = Field(default=None, max_length=32)
    #: A page whose body seeds every new one. ``null`` clears it; a set value
    #: has to be one of this wiki's own pages.
    template_page_id: Optional[int] = None


class WikiUpdate(WikiSettings):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[MentionStr] = Field(default=None, max_length=2000)
    #: The page the wiki opens on. ``null`` clears the choice and it opens on
    #: the first top-level page; a set value has to be one of its own pages.
    home_page_id: Optional[int] = None


class WikiSummary(WikiBase, ToolSummaryBase):
    #: The page it opens on, or ``null`` where none was chosen.
    home_page_id: Optional[int] = None
    #: What this wiki is for — see :class:`WikiSettings`.
    page_order: WikiPageOrder = WikiPageOrder.manual
    contents_depth: int = 3
    show_connections: bool = True
    show_updated_at: bool = True
    reading_width: WikiReadingWidth = WikiReadingWidth.wide
    accent_color: Optional[str] = None
    template_page_id: Optional[int] = None
    comment_count: int = 0


class WikiRead(WikiSummary):
    """A wiki on its own page: its summary, and the files filed in it the
    reader knows are there and can't open. The pages are fetched as a tree of
    their own, because a wiki is navigated rather than read end to end."""

    hidden_files: HiddenFiles = Field(default_factory=HiddenFiles)


class WikiListResponse(PageMeta):
    items: List[WikiSummary]


class WikiPageCreate(PropertiesOnCreate):
    #: Optional, and usually absent: a page is made before it is about
    #: anything, so it starts with no name rather than one somebody has to
    #: delete before typing their own. Every surface that draws a page falls
    #: back to "Untitled" for one that has not been named yet.
    title: Optional[TitleStr] = Field(default=None, max_length=255)
    #: What to file the new page under. Absent means the top of the wiki.
    parent_page_id: Optional[int] = None
    #: A page starts as a draft, and is published when somebody says so. A new
    #: page is empty and unnamed for as long as it takes to write it, and a
    #: wiki people read should not be showing them that — so the default is the
    #: safe half of the answer, and publishing is a decision.
    is_draft: bool = True
    content: Optional[LexicalState] = None
    tag_ids: Optional[List[int]] = None


class WikiPageUpdate(PropertiesOnUpdate):
    """A change to one page.

    Every field is optional and only what is sent is written, so renaming a
    page is the same request shape as editing its body.
    """

    title: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    is_draft: Optional[bool] = None
    content: Optional[LexicalState] = None
    #: The ``content_version`` of the read this ``content`` was made from.
    #: Given and still current, the write merges in, into a live editing
    #: session too; given and out of date, it is refused with
    #: ``*_CONTENT_CHANGED``. Left out, a live session refuses the write.
    content_version: Optional[str] = None
    tag_ids: Optional[List[int]] = None


class WikiPageMove(SanitizedBaseModel):
    """Where a page should sit after a drag — two facts, sent together.

    What it is filed under and where it sits among what else is filed there.
    One request, because a drag is one gesture and half of it landing is a
    tree nobody arranged.
    """

    #: What the page is now filed under. Absent — the default — is the top of
    #: the wiki, so a move that says nothing about filing unfiles the page.
    parent_page_id: Optional[int] = None
    #: Index among the pages filed in the same place, after the move.
    #: Out-of-range clamps.
    position: int = Field(default=0, ge=0)


class WikiPageKind(str, Enum):
    """What a row in a wiki's navigation actually is.

    A wiki holds pages of its own and files somebody put in it. The second
    kind is a file still — it is not copied in, it keeps its own address,
    its own sharing and its own history — so the navigation has to say which it
    is looking at rather than pretend they are the same row.
    """

    #: A page belonging to this wiki, written here.
    page = "page"
    #: A file placed in this wiki by a ``part_of`` edge.
    file = "file"


class WikiPageHeading(SanitizedBaseModel):
    """One heading written on a page.

    Carried with the page rather than read from an editor: the navigation draws
    the headings of every page in a wiki, and only one of them is ever open.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    text: str
    #: 1-6, from the heading tag.
    level: int
    #: What the rendered heading's ``id`` is, so a link from the navigation
    #: lands on it.
    anchor: str


class WikiPageSummary(SanitizedBaseModel):
    """One page as the navigation draws it — no body.

    The navigation renders every page of a wiki at once, so this carries what a
    row needs and nothing that would make the payload grow with what people
    have written.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    wiki_id: int
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    #: Which of the two things this row is. A file keeps its own id, so a
    #: client keys rows on the pair rather than on the number alone.
    kind: WikiPageKind = WikiPageKind.page
    #: What this row is filed under: a page, or ``None`` for the top. A
    #: file is filed like a page is, but never holds anything itself.
    parent_page_id: Optional[int] = None
    position: int = 0
    #: A file placed in a wiki is never a draft: it is not this wiki's to
    #: hold back, and it is readable wherever else it already lives.
    is_draft: bool = False
    title: str
    slug: str
    created_by: PersonId | None = None
    created_at: datetime
    updated_at: datetime
    #: What is written on the page, so the navigation can nest it without
    #: opening it.
    headings: List[WikiPageHeading] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    properties: List[PropertySummary] = Field(default_factory=list)
    #: A file row's kind of file and the facts its icon is drawn
    #: from — a PDF, a spreadsheet and a link to a design tool each look like
    #: what they are. ``None`` on a page.
    file_type: Optional[str] = None
    file_content_type: Optional[str] = None
    original_filename: Optional[str] = None
    smart_link_url: Optional[str] = None


class WikiPageRead(WikiPageSummary):
    """One page, opened."""

    content: LexicalState = Field(default_factory=dict)
    #: The version of ``content`` this read returns. Send it back with a
    #: ``PATCH`` of ``content`` so the write merges into the body only if
    #: nobody has changed it since. ``null`` when the body was left out.
    content_version: Optional[str] = None
    #: When a moderator closed its comments: they still read, and nothing is
    #: added or edited until it is reopened. Null while it is open.
    comments_locked_at: Optional[datetime] = None


class WikiPageTree(SanitizedBaseModel):
    """Every page of a wiki, in reading order — each page, then what is filed
    under it.

    Flat on the wire and a tree by ``parent_page_id``: the navigation draws all
    of it at once, and the order it arrives in is the order it reads in.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[WikiPageSummary]


def serialize_wiki_page_summary(
    page: "Any", *, context: ActorContext, heading_nodes: Optional[list] = None
) -> WikiPageSummary:
    """A page as a row. ``heading_nodes`` are its headings as the tree read
    them (``wikis.heading_nodes``), in place of its body."""
    from app.services.tenant.wikis import page_headings

    headings = page_headings(page.content if heading_nodes is None else heading_nodes)
    return from_row(
        WikiPageSummary,
        page,
        guild_id=context.guild_id,
        headings=[WikiPageHeading(**h) for h in headings],
        tags=annotated_tags(page),
        properties=annotated_properties(page),
    )


def serialize_file_as_page(
    file: "Any",
    *,
    context: ActorContext,
    wiki_id: int,
    position: int,
    heading_nodes: list,
    parent_page_id: Optional[int] = None,
) -> WikiPageSummary:
    """A file, as the wiki's navigation draws it.

    Everything a row needs, read off the file itself — including its
    headings (``heading_nodes``, as the tree read them), so a file in a
    wiki opens in the sidebar exactly as a page written here does.
    """
    from app.services.tenant.names import slugify
    from app.services.tenant.wikis import page_headings

    return WikiPageSummary(
        id=file.id,
        wiki_id=wiki_id,
        community_id=context.guild_id,
        kind=WikiPageKind.file,
        parent_page_id=parent_page_id,
        position=position,
        is_draft=False,
        title=file.name,
        slug=slugify(file.name, fallback=f"file-{file.id}"),
        created_by=file.created_by,
        created_at=file.created_at,
        updated_at=file.updated_at,
        headings=[WikiPageHeading(**h) for h in page_headings(heading_nodes)],
        file_type=getattr(file.file_type, "value", file.file_type),
        file_content_type=getattr(file.current_version, "file_content_type", None),
        original_filename=getattr(file.current_version, "original_filename", None),
        smart_link_url=smart_link_url(file),
    )


def serialize_wiki_page(page: "Any", *, context: ActorContext) -> WikiPageRead:
    return WikiPageRead(
        **serialize_wiki_page_summary(page, context=context).model_dump(),
        content=page.content or {},
    )
