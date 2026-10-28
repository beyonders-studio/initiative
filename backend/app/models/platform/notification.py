from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, text
from sqlmodel import Field, Index, SQLModel


class NotificationType(str, Enum):
    task_assignment = "task_assignment"
    #: The overdue digest: every task still overdue, on the account's schedule.
    overdue_tasks = "overdue_tasks"
    #: The coming-up digest: tasks due and events starting before the next one.
    coming_up = "coming_up"
    initiative_added = "initiative_added"
    initiative_join_requested = "initiative_join_requested"
    initiative_join_approved = "initiative_join_approved"
    initiative_join_denied = "initiative_join_denied"
    share_requested = "share_requested"
    share_granted = "share_granted"
    share_declined = "share_declined"
    project_added = "project_added"
    mention = "mention"
    comment_on_task = "comment_on_task"
    comment_on_resource = "comment_on_resource"
    comment_reply = "comment_reply"
    #: Somebody reacted to the recipient's comment.
    comment_reaction = "comment_reaction"
    #: Somebody changed or commented on something the recipient is subscribed
    #: to, or on something inside a tool they are subscribed to.
    subscription_activity = "subscription_activity"
    #: Somebody changed something the recipient is named on: a task they are
    #: assigned, an event they are going to.
    assigned_activity = "assigned_activity"
    #: A notice went up on a bulletin board the recipient can see.
    post_published = "post_published"
    access_grant_requested = "access_grant_requested"
    access_grant_approved = "access_grant_approved"
    access_grant_denied = "access_grant_denied"
    access_grant_revoked = "access_grant_revoked"
    event_invitation = "event_invitation"
    event_cancelled = "event_cancelled"
    event_rsvp = "event_rsvp"
    event_reminder = "event_reminder"
    export_ready = "export_ready"
    export_failed = "export_failed"
    import_ready = "import_ready"
    import_failed = "import_failed"
    avatar_removed = "avatar_removed"
    username_changed = "username_changed"
    #: Staff cleared part of the recipient's profile: names in communities,
    #: status line or decorations. Names which, never who.
    profile_field_cleared = "profile_field_cleared"
    account_suspended = "account_suspended"
    account_unsuspended = "account_unsuspended"
    #: A community this account holds the seat of was put on hold. Written once,
    #: on the way in, naming whom to contact.
    community_on_hold = "community_on_hold"
    #: A community this account holds the seat of — or owns, by billing's
    #: account — is near the end of its trial, or past it. Written once per
    #: notice billing sends.
    community_trial_ending = "community_trial_ending"
    community_trial_ended = "community_trial_ended"
    #: A community this account holds the seat of — or owns, by billing's
    #: account — has had its plan paused by its admin, and goes on hold on the
    #: day the notice names unless it is resumed. Written once per reminder
    #: billing sends.
    community_pause_reminder = "community_pause_reminder"
    #: A community made for this account, by them or by staff on their behalf.
    #: Written once, where billing sets plans, inviting them to set up its plan.
    community_welcome = "community_welcome"
    connection_requested = "connection_requested"
    connection_accepted = "connection_accepted"
    message_request_received = "message_request_received"
    message_request_accepted = "message_request_accepted"
    #: One rolled-up line per conversation with unread activity. It names the
    #: sender and counts the messages; it never carries one.
    direct_message = "direct_message"
    #: An installed plug-in asks to act as the recipient, for one purpose. Written
    #: once per request; it links to where the recipient answers.
    plugin_consent_requested = "plugin_consent_requested"
    #: A newer version of an installed plug-in asks for more than the install
    #: holds, and waits for the community's seat. Written once per version to
    #: each seat holder; it links to where they accept or decline it.
    plugin_update_pending = "plugin_update_pending"
    #: A case this account filed moved: somebody answered it, or it is now
    #: waiting on them, in progress or closed. Names the case and its state,
    #: never what was said.
    ticket_updated = "ticket_updated"
    #: A community's moderators took down something the recipient wrote.
    #: Names the kind and the reason, never what it said or who reported it.
    moderation_removal = "moderation_removal"
    #: A community's moderators warned the recipient about something they
    #: wrote, in the moderator's own words. Never names or counts reporters.
    moderation_warning = "moderation_warning"
    #: A case opened in the operations community, told to everyone who can
    #: read it. Names the stream; the title is read when the line is.
    case_opened = "case_opened"
    #: Whoever filed a case answered on it, and nobody has taken it, so the
    #: people who can read it hear instead of nobody.
    case_replied = "case_replied"


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (
        # The inbox query is always "my notifications, unread first", so the
        # composite carries it; a bare ``user_id`` index would be a prefix of
        # this one.
        Index("ix_notifications_user_read", "user_id", "read_at"),
        # Where there is unread activity, for the dots that run down the
        # navigation. Partial on unread because that is the only thing this
        # question is ever asked about, which keeps the index small enough to
        # answer it with an index-only scan.
        Index(
            "ix_notifications_unread_place",
            "user_id",
            "guild_id",
            "initiative_id",
            "tool",
            "resource_id",
            "subject_type",
            "subject_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        # What the retention sweep asks for: read rows by when they were read.
        # Partial, so the unread rows it never touches stay out of it.
        Index(
            "ix_notifications_read_at",
            "read_at",
            postgresql_where=text("read_at IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE", nullable=False)
    type: NotificationType = Field(
        sa_column=Column(String(64), nullable=False),
        default=NotificationType.task_assignment,
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    #: Where this happened, as three independently-optional levels. A direct
    #: message has none of them, a membership notice has only a guild, and a
    #: comment on a task has all three — so a parent lights whenever anything
    #: beneath it is unread, with nothing to sum and no special case for the
    #: rows that stop short.
    #:
    #: All three are already carried in ``data``; as columns they are indexable,
    #: which is the whole difference.
    guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    #: Weak reference: initiatives live in ``guild_<id>``, and provisioning omits
    #: cross-schema foreign keys.
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    #: A ``Tool`` value, or NULL where the notification is not about one.
    tool: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    #: The row of that tool: the project a task is in, the calendar of an
    #: event, the wiki of a page. Weak, like ``initiative_id``.
    resource_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    #: What the notification is about, as an ``entity_tables`` kind and its id
    #: — the task, the event, the page. Opening it marks the line read.
    subject_type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    subject_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    read_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
