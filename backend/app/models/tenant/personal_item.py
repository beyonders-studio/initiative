"""What one member keeps about one item: their last open, a bookmark, a
subscription or an unsubscription, a reminder, and where they put a project in
their own list.

One row per ``(user_id, entity_type, entity_id)``, in the item's community's
schema, its initiative resolved through the item it names. ``entity_id`` is a
weak reference, so purging the item purges its rows (``soft_delete``) rather
than a foreign key doing it. A row holds at least one of them: whatever clears
the last one deletes the row (``app.services.tenant.personal_items``).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Float, Index, Text, text
from sqlmodel import Field, SQLModel

from app.core.tools import CONTENT_KINDS, Tool
from app.db.registry_checks import FROM_REGISTRY


class ViewSource(str, Enum):
    """Where an open came from."""

    #: A link, an address, a tab, or moving around inside the app.
    direct = "direct"
    #: A search result or the command palette.
    search = "search"
    #: An entry in an activity feed.
    feed = "feed"


#: The kinds whose opens become tabs, and which can be bookmarked: every tool.
TOOL_KINDS: tuple[str, ...] = tuple(t.value for t in Tool)

_KINDS = ", ".join(f"'{kind}'" for kind in CONTENT_KINDS)
_TOOLS = ", ".join(f"'{kind}'" for kind in TOOL_KINDS)
_SOURCES = ", ".join(f"'{source.value}'" for source in ViewSource)


class PersonalItem(SQLModel, table=True):
    """One member's own state about one tool, or one thing inside a tool.

    Only that member reaches the row (``PRIVATE_ROW_TABLES``). Opening any
    content kind records a view; only a tool is bookmarked, and only a project is
    ordered, since only projects have a list of the reader's own to order.
    """

    __tablename__ = "personal_items"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_KINDS})",
            name="ck_personal_items_entity_type",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            f"view_source IN ({_SOURCES})",
            name="ck_personal_items_view_source",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            f"bookmarked_at IS NULL OR entity_type IN ({_TOOLS})",
            name="ck_personal_items_bookmarked_tool",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            f"sort_order IS NULL OR entity_type = '{Tool.project.value}'",
            name="ck_personal_items_sort_order_project",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            "(viewed_at IS NULL) = (view_source IS NULL)",
            name="ck_personal_items_view_source_with_view",
        ),
        CheckConstraint(
            "num_nonnulls(viewed_at, bookmarked_at, subscribed_at,"
            " unsubscribed_at, sort_order, remind_at) > 0",
            name="ck_personal_items_holds_something",
        ),
        CheckConstraint(
            "subscribed_at IS NULL OR unsubscribed_at IS NULL",
            name="ck_personal_items_subscribed_or_not",
        ),
        CheckConstraint(
            "remind_at IS NULL OR entity_type = 'task'",
            name="ck_personal_items_remind_at_task",
        ),
        CheckConstraint(
            "reminded_at IS NULL OR remind_at IS NOT NULL",
            name="ck_personal_items_reminded_with_reminder",
        ),
        # A purge drops everyone's rows on an item.
        Index("ix_personal_items_entity", "entity_type", "entity_id"),
        # The tabs bar reads a person's newest opens.
        Index("ix_personal_items_user_viewed_at", "user_id", "viewed_at"),
        # The reminder sweep reads the reminders not yet sent.
        Index(
            "ix_personal_items_remind_at",
            "remind_at",
            postgresql_where=text("remind_at IS NOT NULL AND reminded_at IS NULL"),
        ),
    )

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    #: The last open, and where it came from: a :class:`ViewSource` value.
    viewed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    view_source: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    bookmarked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Subscribed by hand, beyond what making it or being named on it does.
    subscribed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Unsubscribed: nothing about it reaches them, whatever ties them to it.
    unsubscribed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: When to remind the member of this task. A repeating task's next one
    #: takes it at the same distance from its due date
    #: (``task_series.next_reminders``).
    remind_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: When that reminder went out; setting another clears it.
    reminded_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Where the member put this project in their own list.
    sort_order: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
