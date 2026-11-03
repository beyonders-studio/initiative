from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, Relationship, SQLModel

from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    HoldMixin,
    SoftDeleteMixin,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative


class Collection(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    SoftDeleteMixin,
    table=True,
):
    """A group of files in an initiative's Files.

    A file can be in any number of collections and stays in its initiative's
    Files list. A collection has no sharing of its own: it is seen by whoever
    can open a file in it, and changed by whoever's role creates files in its
    initiative (``app.db.initiative_rls``).

    ``cover_file_id`` is the file that stands for it on a card. Nullable: a
    card falls back to the newest file its reader can open.
    """

    __tablename__ = "collections"
    # A collection is written before any file is in it, when its reader cannot
    # see it yet, so it is read back by no RETURNING clause.
    __table_args__ = (
        UniqueConstraint("id", "initiative_id", name="uq_collections_id_initiative"),
        {"implicit_returning": False},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    cover_file_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship()


class CollectionFile(SQLModel, table=True):
    """One file in one collection.

    ``initiative_id`` is the collection's and the file's alike, which the two
    keys hold: a collection holds only its own initiative's files.
    ``added_at`` is when the file arrived, which a collection's timeline goes
    by. ``added_by`` is who added it, and null where a plug-in acting as its
    community did.
    """

    __tablename__ = "collection_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "initiative_id"],
            ["collections.id", "collections.initiative_id"],
            ondelete="CASCADE",
            name="fk_collection_files_collection",
        ),
        ForeignKeyConstraint(
            ["file_id", "initiative_id"],
            ["files.id", "files.initiative_id"],
            ondelete="CASCADE",
            name="fk_collection_files_file",
        ),
    )

    collection_id: int = Field(primary_key=True)
    file_id: int = Field(primary_key=True, index=True)
    initiative_id: int = Field(nullable=False)
    added_by: Optional[int] = Field(default=None, foreign_key="users.id")
    added_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
