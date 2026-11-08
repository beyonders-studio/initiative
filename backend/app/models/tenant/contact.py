from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, text
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
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant


#: A contact's fixed fields, in the order a card shows them.
DETAILS: tuple[str, ...] = ("emails", "phones", "addresses", "websites")


def _details() -> Column:
    """One of a contact's fixed fields: its values, in order, as ``{label,
    value}``. A column of its own per field, since one Column cannot be shared
    across attributes."""
    return Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class Contact(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """Somebody an initiative, or the whole community, deals with: a person or
    an organization, and how to reach them.

    Each contact is an item of its own with its own sharing, as a file is. One
    with no initiative belongs to the whole community, and the community
    contacts plug-in's install owns it (``authorization.COMMUNITY_ROWS``).

    Its fixed fields are lists of ``{label, value}``, several of each in the
    order they were written; the first is the one a table shows. An address is
    one block of text, as it is written on an envelope. Anything else about a
    contact is an initiative property, and a person's organization is a
    ``part_of`` link to an organization contact.
    """

    __tablename__ = "contacts"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__: ClassVar[dict[str, bool]] = {"implicit_returning": False}

    id: int | None = Field(default=None, primary_key=True)
    #: NULL for a community contact.
    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    name: str = Field(nullable=False, index=True, max_length=255)
    is_organization: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    emails: list[dict[str, str]] = Field(default_factory=list, sa_column=_details())
    phones: list[dict[str, str]] = Field(default_factory=list, sa_column=_details())
    addresses: list[dict[str, str]] = Field(default_factory=list, sa_column=_details())
    websites: list[dict[str, str]] = Field(default_factory=list, sa_column=_details())
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
                "and_(foreign(ResourceGrant.resource_id) == Contact.id, "
                "ResourceGrant.resource_type == 'contact')"
            ),
            "viewonly": True,
        }
    )


attach_actions(Contact, Tool.contact)
