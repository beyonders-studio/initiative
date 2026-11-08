from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlmodel import Field

from app.core.tools import Tool
from app.db.registry_checks import FROM_REGISTRY
from app.models.tenant._mixins import CreatedByMixin
from app.models.tenant.resource_grant import ResourceAccessLevel


class GuestInviteGrant(CreatedByMixin, table=True):
    """What a guest invite gives whoever redeems it: an initiative to join, or
    one item in it, at ``read`` or ``write``.

    Written with the invite by the community's administrators, and applied
    when the invite is redeemed (``app.services.platform.guilds``): an
    initiative becomes a membership with the role its standing earns, an item
    a sharing row naming the guest. ``invite_id`` names a ``public.guild_invites``
    row, which no key in a community's schema reaches; withdrawing the invite
    deletes these with it.
    """

    __tablename__ = "guest_invite_grants"
    __table_args__ = (
        CheckConstraint(
            "(resource_type IS NULL) = (resource_id IS NULL)"
            " AND (resource_type IS NULL) = (level IS NULL)",
            name="ck_guest_invite_grants_item",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            "level IN ('read', 'write')",
            name="ck_guest_invite_grants_level",
            info={FROM_REGISTRY: True},
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    invite_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: The item, with ``level``; all three NULL for the whole initiative.
    resource_type: Tool | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    resource_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    level: ResourceAccessLevel | None = Field(
        default=None, sa_column=Column(String(length=16), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
