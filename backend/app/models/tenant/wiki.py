from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship

from app.core.tools import Tool
from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    HoldMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    attach_actions,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant


class WikiPageOrder(str, Enum):
    """How a wiki's page tree is sorted.

    ``manual`` is the spine — where somebody dragged each page. ``title`` sorts
    siblings alphabetically instead, which is what a reference wants: nobody
    arranges a glossary by hand, and a new entry should land where it belongs
    rather than at the end.
    """

    manual = "manual"
    title = "title"
    recently_updated = "recently_updated"


class WikiReadingWidth(str, Enum):
    """How wide a page's body runs.

    ``wide`` fills the screen, which is what a runbook full of tables and
    screenshots wants. ``comfortable`` holds prose to a measure you can read
    without losing your place, which is what a handbook wants.
    """

    wide = "wide"
    comfortable = "comfortable"


class Wiki(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """A body of linked pages in an initiative.

    A wiki is a whole tool entity — its own sharing, its own comment thread,
    tags, the trash can, a URL — and its pages are child rows the way a
    project's tasks are. The split is what the tool is for: a handbook is one
    thing to share and one thing to open, and then read a page at a time.

    ``home_page_id`` is the page a wiki opens on. Nullable, because a wiki has
    no pages the moment it is made and most never nominate one afterwards: a
    wiki without a home opens on its first top-level page, which is what a
    handbook someone is still writing looks like from outside. The foreign key
    is declared ``use_alter`` because the two tables point at each other — a
    wiki names its home, a page names its wiki — and one of the constraints has
    to be added after both exist. ``SET NULL`` so removing the nominated page
    leaves the wiki without a home rather than without a wiki.
    """

    __tablename__ = "wikis"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__: ClassVar[dict[str, bool]] = {"implicit_returning": False}

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    home_page_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "wiki_pages.id",
                ondelete="SET NULL",
                use_alter=True,
                name="wikis_home_page_id_fkey",
            ),
            nullable=True,
        ),
    )
    #: How siblings are ordered in the tree. ``manual`` reads ``position``.
    page_order: WikiPageOrder = Field(
        default=WikiPageOrder.manual,
        sa_column=Column(
            String(length=16), nullable=False, server_default=WikiPageOrder.manual.value
        ),
    )
    #: Where the files borrowed into this wiki sit in its list, as
    #: ``{"<file id>": position}`` on the same scale a page's ``position``
    #: uses. A file is not the wiki's to own — it belongs to whatever else
    #: it is in too — so where it sits is a fact about THIS wiki and is kept
    #: here, rather than on the file or on the edge that put it in. A
    #: file nobody has placed yet sorts to the end, which is where it
    #: arrived.
    file_positions: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    #: How deep the contents rail goes. A page with four heading levels makes a
    #: forty-row rail nobody can use; most wikis want the top one or two.
    contents_depth: int = Field(
        default=3,
        sa_column=Column(Integer, nullable=False, server_default=text("3")),
    )
    #: Whether a page shows what links to it. A world bible lives on that
    #: question; a handbook read front to back never asks it.
    show_connections: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    #: Whether a page says when it was last touched. A handbook people act on
    #: needs it — a rota nobody has revised since March is worth knowing about
    #: — and a world bible is timeless and does not.
    show_updated_at: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    reading_width: WikiReadingWidth = Field(
        default=WikiReadingWidth.wide,
        sa_column=Column(
            String(length=16),
            nullable=False,
            server_default=WikiReadingWidth.wide.value,
        ),
    )
    #: The wiki's own accent, used for its chrome so two wikis open side by side
    #: are told apart at a glance. NULL takes the app's.
    accent_color: str | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    #: A page whose body seeds every new page. Nullable, and declared
    #: ``use_alter`` for the same reason ``home_page_id`` is — the two tables
    #: point at each other. ``SET NULL`` so deleting the template leaves the
    #: wiki without one rather than without a wiki.
    template_page_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "wiki_pages.id",
                ondelete="SET NULL",
                use_alter=True,
                name="wikis_template_page_id_fkey",
            ),
            nullable=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship()
    grants: list["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Wiki.id, "
                "ResourceGrant.resource_type == 'wiki')"
            ),
            "viewonly": True,
        }
    )
    # The pages. Ordered by the tree's own spine here — siblings by position,
    # then by id so a tie is still a stable order — because that is the order
    # the navigation renders in and every other surface is a filter over it.
    pages: list["WikiPage"] = Relationship(
        back_populates="wiki",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "(WikiPage.position, WikiPage.id)",
            "foreign_keys": "WikiPage.wiki_id",
        },
    )
    home_page: Optional["WikiPage"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "Wiki.home_page_id == WikiPage.id",
            "foreign_keys": "Wiki.home_page_id",
            "viewonly": True,
        }
    )


class WikiPage(
    HoldMixin, CommentLockMixin, CreatedByMixin, SoftDeleteMixin, table=True
):
    """One page of a wiki.

    A page is a Lexical body, the same editor a native file carries, and it
    is collaborative through the same Yjs room — ``yjs_state`` mirrors what the
    room holds so a page reopened after everyone has left reads back what was
    written.

    Two different structures meet on this row, and keeping them apart is the
    whole design of the tool:

    ``parent_page_id`` and ``position`` are the **spine** — the shape the
    navigation draws. Pages file under pages, and siblings hold an order; the
    headings inside a page are a third structure again, content rather than
    filing, and they live in the body. Both are columns because both are read
    on every draw of the sidebar and rewritten by a drag, which wants to be one
    statement and one transaction.

    Everything else a page connects to is an edge in ``relationships``: a page
    ``part_of`` a task, ``related_to`` another wiki's page, and the
    ``references`` edges read out of the ``[[ ]]`` links in this body whenever
    it is saved. That is the **web**, and it is deliberately not the spine: a
    task can belong to a page without appearing in the page tree.

    ``slug`` is the page's stable name in a URL, unique among the live pages of
    its wiki. Titles get rewritten; a link that survives the rewrite is the
    point of a wiki.
    """

    __tablename__ = "wiki_pages"
    __table_args__ = (
        # One page of a wiki per address, always — a page on its way to the bin
        # parks its slug out of the alphabet first (see RELEASED_NAMES in
        # app.db.frozen), so what is unique here in practice
        # is the set of addresses a reader can reach.
        UniqueConstraint("wiki_id", "slug", name="uq_wiki_pages_wiki_slug"),
    )
    # What labels a page in a bare list of mixed things (the trash can).
    _display_field: ClassVar[str] = "title"

    id: int | None = Field(default=None, primary_key=True)
    wiki_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("wikis.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    #: What this page is filed under, or nothing if it sits at the top of the
    #: wiki. ``CASCADE`` so a purge takes the branch with it; a soft-delete
    #: walks the same edge through ``CASCADE_CHILDREN``.
    parent_page_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("wiki_pages.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    # The spine. Sparse on purpose — pages are inserted between their
    # neighbours far more often than they are appended.
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    # A page somebody is still writing. Editors see it, greyed; everybody else
    # is not told it exists, which is what makes a draft safe to leave lying
    # around in a wiki people read.
    is_draft: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    title: str = Field(nullable=False, max_length=255)
    slug: str = Field(sa_column=Column(String(length=255), nullable=False))
    content: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    yjs_state: bytes | None = Field(
        default=None,
        sa_column=Column(LargeBinary, nullable=True),
    )
    yjs_updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    wiki: Wiki | None = Relationship(
        back_populates="pages",
        sa_relationship_kwargs={"foreign_keys": "WikiPage.wiki_id"},
    )
    author: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(WikiPage.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )


attach_actions(Wiki, Tool.wiki)
