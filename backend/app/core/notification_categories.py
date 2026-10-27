"""The canonical notification **category** registry.

Every ``NotificationType`` belongs to exactly one category, and the category —
not a hand-written list anywhere else — is what the preference storage, the
settings grid, each community's rows and mute and the "addressed to me" filter
all read.

The rows for a community's content are by how the reader relates to what
happened, not by what kind of thing it was: named or answered (``mentions``),
given it or on it (``assignments``), following it, which includes having made
it (``subscriptions``), and what arrived for them to see (``news``).
``notification_categories_test.py`` asserts the mapping is exhaustive over
``NotificationType``, so a new type cannot ship without a category decision.

Two axes separate categories that otherwise look adjacent, and they are the
axes to apply when a new one is proposed:

``personal``
    The notification is addressed to this account **by another person**. This is
    what email sends straight away when the rest waits for its schedule, and
    what the inbox's "Mentions" filter shows.

``mutable_channels``
    Which channels the account may switch off. ``account``, ``approvals`` and
    ``moderation`` keep the in-app channel on: being told your account was
    suspended, or that somebody is waiting on your decision, is not a
    preference. ``cases`` keeps every channel on.

The difference between ``jobs`` and ``account`` is who started it. A job is your
own request finishing — you asked for the export, so being pinged about it is
entirely yours to switch off, and the file is in the jobs table either way. An
account notice is somebody else acting on your account, which is why it is not
optional. The same asymmetry puts ``access_grant_requested`` in ``approvals``
(waiting on your decision) and its resolutions in ``account`` (somebody else's
decision landing on you).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from app.models.platform.notification import NotificationType


class Channel(str, Enum):
    """How a notification reaches somebody.

    ``in_app`` is a real channel, not an always-on floor. Before it existed the
    bell was written unconditionally and only email and push could be turned
    down, which is the whole reason the surface felt loud.
    """

    in_app = "in_app"
    email = "email"
    push = "push"
    #: A system notification from the desktop app, carried on its own
    #: connection rather than through a push service, so it needs no Firebase.
    desktop = "desktop"


ALL_CHANNELS: tuple[Channel, ...] = tuple(Channel)


class NotificationCategory(str, Enum):
    mentions = "mentions"
    assignments = "assignments"
    subscriptions = "subscriptions"
    news = "news"
    approvals = "approvals"
    moderation = "moderation"
    cases = "cases"
    direct_messages = "direct_messages"
    jobs = "jobs"
    account = "account"


#: How the settings page groups the rows. Presentation only — nothing resolves
#: through it.
class CategoryGroup(str, Enum):
    #: What a community's content says to you, by how you relate to it. The
    #: rows each community can switch on its own.
    your_communities = "your_communities"
    #: What a community needs of you, or did about you.
    community = "community"
    #: Yours alone, outside any community's content.
    account = "account"


_ON = {
    Channel.in_app: True,
    Channel.email: True,
    Channel.push: True,
    Channel.desktop: True,
}


@dataclass(frozen=True)
class CategorySpec:
    """One category, described once."""

    types: frozenset[NotificationType]
    group: CategoryGroup
    #: Addressed to this account by another person.
    personal: bool
    #: Belongs to a community, so muting the community reaches it, and, where
    #: it is in :attr:`CategoryGroup.your_communities`, the community's own row
    #: switch. False for direct messages and account notices, which exist
    #: outside any guild.
    guild_scoped: bool
    #: Channels the account may switch off. None at all means it is not a
    #: preference: nothing turns it down, a muted community included.
    mutable_channels: frozenset[Channel]
    #: Every channel is on until the account switches it off.
    defaults: Mapping[Channel, bool] = field(default_factory=lambda: _ON)

    def is_mutable(self, channel: Channel) -> bool:
        return channel in self.mutable_channels

    @property
    def per_community(self) -> bool:
        """Whether each community can switch this row off on its own."""
        return self.group is CategoryGroup.your_communities


_ALL_MUTABLE = frozenset(ALL_CHANNELS)
#: In-app stays on; the reachable channels are still the account's own choice.
_KEEP_IN_APP = frozenset({Channel.email, Channel.push, Channel.desktop})


CATEGORY_SPECS: Mapping[NotificationCategory, CategorySpec] = {
    # Somebody named you, or answered something you said: a reply to your
    # comment, or a reaction to it.
    NotificationCategory.mentions: CategorySpec(
        types=frozenset(
            {
                NotificationType.mention,
                NotificationType.comment_reply,
                NotificationType.comment_reaction,
            }
        ),
        group=CategoryGroup.your_communities,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
    ),
    # You were given something, and what you are on: assigned, invited, due,
    # changed, cancelled, about to start.
    NotificationCategory.assignments: CategorySpec(
        types=frozenset(
            {
                NotificationType.task_assignment,
                NotificationType.overdue_tasks,
                NotificationType.event_invitation,
                NotificationType.event_cancelled,
                NotificationType.event_reminder,
                NotificationType.assigned_activity,
            }
        ),
        group=CategoryGroup.your_communities,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
    ),
    # What you follow, which includes what you made
    # (``personal_items.subscribers_of``): changes, comments, reactions to a
    # post and answers to an event. Ambient: it scales with how busy the
    # thing is.
    NotificationCategory.subscriptions: CategorySpec(
        types=frozenset(
            {
                NotificationType.subscription_activity,
                NotificationType.comment_on_task,
                NotificationType.comment_on_resource,
                NotificationType.event_rsvp,
            }
        ),
        group=CategoryGroup.your_communities,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
    ),
    # What arrived in a community for you to see: a post went up, you were
    # added to an initiative or a project, your request to join or to see
    # something was answered.
    NotificationCategory.news: CategorySpec(
        types=frozenset(
            {
                NotificationType.post_published,
                NotificationType.project_added,
                NotificationType.initiative_added,
                NotificationType.initiative_join_approved,
                NotificationType.initiative_join_denied,
                NotificationType.share_granted,
                NotificationType.share_declined,
            }
        ),
        group=CategoryGroup.your_communities,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
    ),
    # Something is waiting on this account's decision, so the bell keeps it:
    # a queue nobody is told about is a queue nobody works.
    NotificationCategory.approvals: CategorySpec(
        types=frozenset(
            {
                NotificationType.initiative_join_requested,
                NotificationType.share_requested,
                NotificationType.access_grant_requested,
                NotificationType.plugin_consent_requested,
                NotificationType.plugin_update_pending,
            }
        ),
        group=CategoryGroup.community,
        personal=True,
        guild_scoped=True,
        mutable_channels=_KEEP_IN_APP,
    ),
    # A community's moderators acted on something this account wrote. Like an
    # account notice, being told is not a preference; unlike one, it belongs
    # to a community.
    NotificationCategory.moderation: CategorySpec(
        types=frozenset(
            {
                NotificationType.moderation_removal,
                NotificationType.moderation_warning,
            }
        ),
        group=CategoryGroup.community,
        personal=True,
        guild_scoped=True,
        mutable_channels=_KEEP_IN_APP,
    ),
    # Work arriving for the people who answer the operations community's
    # cases: a new one, and a requester's answer on one nobody has taken.
    # Answering cases is a platform role rather than something anybody opted
    # into, so nothing switches it off.
    NotificationCategory.cases: CategorySpec(
        types=frozenset(
            {
                NotificationType.case_opened,
                NotificationType.case_replied,
            }
        ),
        group=CategoryGroup.community,
        personal=False,
        guild_scoped=True,
        mutable_channels=frozenset(),
    ),
    NotificationCategory.direct_messages: CategorySpec(
        types=frozenset(
            {
                NotificationType.direct_message,
                NotificationType.message_request_received,
                NotificationType.message_request_accepted,
                NotificationType.connection_requested,
                NotificationType.connection_accepted,
            }
        ),
        group=CategoryGroup.account,
        personal=True,
        guild_scoped=False,
        mutable_channels=_ALL_MUTABLE,
    ),
    # Work this account asked for, finished. Entirely theirs to switch off —
    # the export is in the jobs table whether or not they were pinged.
    NotificationCategory.jobs: CategorySpec(
        types=frozenset(
            {
                NotificationType.export_ready,
                NotificationType.export_failed,
                NotificationType.import_ready,
                NotificationType.import_failed,
            }
        ),
        group=CategoryGroup.account,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
    ),
    # Somebody else acted on this account. Being told is not a preference.
    NotificationCategory.account: CategorySpec(
        types=frozenset(
            {
                NotificationType.avatar_removed,
                NotificationType.username_changed,
                NotificationType.profile_field_cleared,
                NotificationType.account_suspended,
                NotificationType.account_unsuspended,
                NotificationType.community_on_hold,
                NotificationType.community_trial_ending,
                NotificationType.community_trial_ended,
                NotificationType.community_pause_reminder,
                NotificationType.community_welcome,
                NotificationType.access_grant_approved,
                NotificationType.access_grant_denied,
                NotificationType.access_grant_revoked,
                NotificationType.ticket_updated,
            }
        ),
        group=CategoryGroup.account,
        personal=True,
        guild_scoped=False,
        mutable_channels=_KEEP_IN_APP,
    ),
}


#: Type -> category, built from the registry so the two can never disagree.
CATEGORY_OF: Mapping[NotificationType, NotificationCategory] = {
    notification_type: category
    for category, spec in CATEGORY_SPECS.items()
    for notification_type in spec.types
}

#: The types the inbox's Mentions filter keeps, and email sends at once.
PERSONAL_TYPES: frozenset[NotificationType] = frozenset(
    notification_type
    for category, spec in CATEGORY_SPECS.items()
    if spec.personal
    for notification_type in spec.types
)


def sample_type(category: NotificationCategory) -> NotificationType:
    """Any one type from a category, for a push that covers a whole category
    but is sent and stored by type — the summary when a hold lifts. Sorted so
    the choice is stable rather than dependent on set ordering.
    """
    return sorted(CATEGORY_SPECS[category].types, key=lambda t: t.value)[0]


def category_of(notification_type: NotificationType) -> NotificationCategory:
    """The category a type belongs to. Total over ``NotificationType`` — the
    drift test is what keeps it that way."""
    return CATEGORY_OF[notification_type]


def spec_of(notification_type: NotificationType) -> CategorySpec:
    return CATEGORY_SPECS[CATEGORY_OF[notification_type]]


def is_personal(notification_type: NotificationType) -> bool:
    return notification_type in PERSONAL_TYPES
