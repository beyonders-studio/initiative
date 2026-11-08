from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
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


class DashboardViewMode(str, Enum):
    """Whose access a dashboard's query widgets answer from."""

    #: Each person sees what their own access reaches. The default.
    individual = "individual"
    #: Everyone who can open the dashboard sees everything in its initiative.
    initiative = "initiative"


class Dashboard(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """An initiative's dashboard: a canvas of widgets over existing data.

    ``definition`` is the validated, declarative body — layout plus widgets and
    their data bindings. It is a presentation spec only: it names *where* data
    comes from (a task filter, a counter, a file range) and never carries
    content, credentials, or actions. Every binding resolves per viewer through
    the normal gated endpoints, so a dashboard grants no access of its own and
    can never mutate what it displays.

    ``view_mode`` is the one exception to "per viewer": a dashboard set to run
    as its initiative answers its statements with full read access to that
    initiative, for everybody who can open it.

    ``config`` fills the binding slots a definition leaves open, so one shared
    definition can be pointed at this initiative's actual counters/files.

    Dashboards are initiative-scoped: there is no guild-wide (NULL initiative)
    form — a guild-level surface is a plug-in, which is a separate concept.
    """

    __tablename__ = "dashboards"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    #
    # Provenance (``listing_uid``/``listing_version``) is every tool's, from
    # ``ListingProvenanceMixin``. A dashboard is the one tool that reads it back
    # — the upgrade button re-pins an installed dashboard to its listing — so it
    # is the one that keeps an index on it.
    __table_args__ = (
        Index("ix_dashboards_listing_uid", "listing_uid"),
        CheckConstraint(
            "view_mode IN ('individual', 'initiative')", name="ck_dashboards_view_mode"
        ),
        {"implicit_returning": False},
    )

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
    description: str | None = Field(default=None, max_length=2000)
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    #: Whose access the query widgets answer from: ``individual`` (each
    #: viewer's own, the default) or ``initiative`` (full read access to this
    #: dashboard's initiative, the same for everyone who can open it). See
    #: ``app.services.tenant.view_as``.
    view_mode: str = Field(
        default=DashboardViewMode.individual.value,
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=DashboardViewMode.individual.value,
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
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(Dashboard.created_by) == MemberProfile.id,"
                " Dashboard.created_by_kind == 'member')"
            ),
            "viewonly": True,
        }
    )
    grants: list["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Dashboard.id, "
                "ResourceGrant.resource_type == 'dashboard')"
            ),
            "viewonly": True,
        }
    )


attach_actions(Dashboard, Tool.dashboard)
