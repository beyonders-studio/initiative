from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, Relationship

from app.core.reactions import REACTION_TARGETS
from app.db.registry_checks import FROM_REGISTRY
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant._mixins import CreatedByMixin

#: The target vocabulary, frozen into the CHECK constraint from the registry so
#: the column can never hold a kind nothing knows how to authorize.
_TARGET_VALUES = ", ".join(f"'{target.value}'" for target in REACTION_TARGETS)


class Reaction(CreatedByMixin, table=True):
    """One person's one emoji on one thing.

    Polymorphic by ``(target_type, target_id)`` rather than a column per parent:
    a reaction says nothing about what it is on, so a new reactable kind costs a
    registry entry, not a schema change. The unique constraint is what makes the
    API a toggle — the same person cannot hold the same emoji on the same target
    twice.

    Reactions are NOT soft-deleted. Removing one is the author taking their own
    reaction back, which leaves nothing worth restoring; the trash can holds
    things that were authored, and a reaction is a gesture.
    """

    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "created_by",
            "emoji",
            name="uq_reactions_target_user_emoji",
        ),
        CheckConstraint(
            f"target_type IN ({_TARGET_VALUES})",
            name="ck_reactions_target_type",
            info={FROM_REGISTRY: True},
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    target_type: str = Field(sa_column=Column(String(32), nullable=False))
    target_id: int = Field(sa_column=Column(Integer, nullable=False))
    #: The emoji itself, as the grapheme cluster the client rendered. Stored
    #: rather than a shortcode so the display needs no lookup table, and
    #: validated on the way in (see ``app.schemas.tenant.reaction``).
    emoji: str = Field(sa_column=Column(Text, nullable=False))
    #: Who reacted. Part of the unique key, so it is set explicitly by the
    #: service rather than left to the ``created_by`` fill trigger.
    created_by: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # The API calls this the reactor; the column is the schema-wide
    # ``created_by``. The join is spelled out because the target is a view,
    # which carries no foreign key.
    reactor: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Reaction.created_by) == MemberProfile.id",
            "viewonly": True,
        },
    )
