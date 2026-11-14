"""Notices that ship in the app's own source rather than being written in it.

Some things have to be said by the release that changes them: a breaking
change, a migration someone has to run, a setting that moved. Those cannot wait
for an operator to notice and type them out — every deployment that upgrades
needs to see them, and a fresh install that starts on the new version needs to
not. So they are declared here, compiled into the image, and merged with the
authored ones by ``app.services.platform.announcements``.

They differ from authored announcements in three ways, all of them
consequences of living in source control:

* their key is ``builtin:<slug>`` rather than ``db:<id>``, so a read receipt
  survives a database that never held the announcement in the first place;
* they can be conditioned on the upgrade that brought them
  (``only_upgrading_from_below``), which an authored notice has no use for —
  it is written on a deployment that is already running;
* they cannot be edited or deleted from the operator surface — the way to retire
  one is to remove it here and ship that;
* their pictures are static assets shipped with the SPA
  (``frontend/public/announcement-images/…``, served at
  ``/announcement-images/…``) rather than uploads, because at build time there
  is no database to upload one to.

Adding one:

.. code-block:: python

    BUILTIN_ANNOUNCEMENTS = (
        BuiltinAnnouncement(
            slug="0-65-guild-admin-settings-moved",
            title="Guild settings have moved",
            category=AnnouncementCategory.breaking,
            published_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            guild_admins_only=True,
            dismissals_required=2,
            sections=(
                AnnouncementSection(
                    heading="Where they went",
                    body="Access and members now live under **Settings → Users**.",
                    image_url="/announcement-images/0-65-settings.png",
                    image_alt="The relocated settings page",
                ),
                # ``starts_page`` breaks the notice into pages the reader
                # steps through — the wizard shape.
                AnnouncementSection(
                    starts_page=True,
                    heading="What you have to do",
                    body="Re-check who can reach the community's data.",
                ),
            ),
        ),
    )

The slug is permanent: it is what a reader's dismissal is recorded against, so
changing it re-shows the notice to everyone who had already dealt with it.
Removing an entry is how a notice retires — the stale receipts it leaves behind
are harmless and cost one short row each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models.platform.announcement import (
    AnnouncementAudienceAccounts,
    AnnouncementCategory,
    builtin_announcement_key,
)
from app.models.platform.user import UserRole
from app.schemas.platform.announcement import AnnouncementRead, AnnouncementSection


@dataclass(frozen=True)
class BuiltinAnnouncement:
    """One notice declared in source. Mirrors the authored row's fields."""

    slug: str
    title: str
    category: AnnouncementCategory
    published_at: datetime
    sections: tuple[AnnouncementSection, ...] = field(default_factory=tuple)
    #: Audience, read exactly as the authored table's two columns are.
    min_platform_role: UserRole = UserRole.member
    guild_admins_only: bool = False
    expires_at: datetime | None = None
    #: How many times it has to be acknowledged before it stops coming back.
    #: A breaking change nobody can afford to miss is the reason this exists.
    dismissals_required: int = 1
    #: Hold it until the reader opens a matching page, instead of queueing it
    #: on sight — in-context help rather than news.
    trigger_route: str | None = None
    #: Which accounts it is for, measured against ``published_at``.
    audience_accounts: AnnouncementAudienceAccounts = (
        AnnouncementAudienceAccounts.everyone
    )
    #: Only tell a deployment that upgraded *into* this from below the given
    #: version. A fresh install has no previous version and so is never told:
    #: it was never on the behaviour the notice is about.
    only_upgrading_from_below: str | None = None

    @property
    def key(self) -> str:
        return builtin_announcement_key(self.slug)

    def to_read(self) -> AnnouncementRead:
        return AnnouncementRead(
            key=self.key,
            title=self.title,
            category=self.category,
            sections=list(self.sections),
            published_at=self.published_at,
            is_builtin=True,
            dismissals_required=self.dismissals_required,
            trigger_route=self.trigger_route,
        )


#: Every notice this version of the app carries. Empty is the normal state —
#: an entry is added by the release that needs one and removed once it is old
#: news.
BUILTIN_ANNOUNCEMENTS: tuple[BuiltinAnnouncement, ...] = (
    BuiltinAnnouncement(
        slug="0-76-comment-removal-moved-to-moderators",
        title="Taking down comments is for moderators now",
        category=AnnouncementCategory.breaking,
        published_at=datetime(2026, 10, 9, tzinfo=UTC),
        audience_accounts=AnnouncementAudienceAccounts.existing,
        only_upgrading_from_below="0.76.0",
        guild_admins_only=True,
        sections=(
            AnnouncementSection(
                heading="What changed",
                body=(
                    "**Delete is for your own comments.** Project managers "
                    "could delete anybody's comment in their initiative. They "
                    "can't any more.\n\n"
                    "**Moderators take comments down instead.** Community "
                    "admins, and anyone whose initiative role has **Full "
                    "access**, can remove a comment with a reason. It leaves a "
                    "tombstone where it was, its replies stay, and it can be "
                    "put back from the moderation page's **Log**."
                ),
            ),
            AnnouncementSection(
                heading="What to do",
                body=(
                    "If a manager should keep taking comments down, give their "
                    "role **Full access** in the initiative's settings, or "
                    "move them to the built-in **Moderator** role."
                ),
            ),
        ),
    ),
    BuiltinAnnouncement(
        slug="0-76-intake-status-roles",
        title="Tell requesters when you're waiting on them",
        category=AnnouncementCategory.feature,
        published_at=datetime(2026, 10, 11, tzinfo=UTC),
        audience_accounts=AnnouncementAudienceAccounts.existing,
        only_upgrading_from_below="0.76.0",
        min_platform_role=UserRole.owner,
        trigger_route="/settings/platform/intake",
        sections=(
            AnnouncementSection(
                heading="What changed",
                body=(
                    "People who file a ticket follow it under **My Tickets**, "
                    "and see whether it's received, being worked, waiting on "
                    "them or closed.\n\n"
                    "**Waiting on them needs a status.** A stream set up "
                    "before 0.75 has none picked, so its requesters see "
                    'Received, In progress and Closed, and never "Waiting '
                    'on you".'
                ),
            ),
            AnnouncementSection(
                heading="What to do",
                body=(
                    "For each stream below, pick the status that means "
                    "**Waiting on the requester**, and the one their answer "
                    "moves a case to (**When they answer, move to**). A "
                    "stream set up with **Set this up for me** has both "
                    "picked already."
                ),
            ),
        ),
    ),
    BuiltinAnnouncement(
        slug="0-78-galleries-and-queues",
        title="Galleries are now collections, and queues projects",
        category=AnnouncementCategory.info,
        published_at=datetime(2026, 10, 27, tzinfo=UTC),
        # For the people who had galleries or queues. A new account and a fresh
        # install start with neither and have nothing to look for.
        audience_accounts=AnnouncementAudienceAccounts.existing,
        only_upgrading_from_below="0.78.0",
        trigger_route="/c/**",
        sections=(
            AnnouncementSection(
                heading="Why",
                body=(
                    "Files started out as documents. Over time they grew to hold "
                    "every kind of file, and once all of them lived in one place, "
                    "keeping pictures in a separate container stopped making "
                    "sense.\n\n"
                    "So each gallery is now a **collection**, in **Files**, with "
                    "its comments, tags and links. Each picture is a file, shared "
                    "as its gallery was, and its caption is in the collection's "
                    "**Caption** field."
                ),
            ),
            AnnouncementSection(
                heading="What a collection is",
                body=(
                    "Add any files to it and lay it out however suits you: a "
                    "gallery, a library, a catalog, whatever makes the most sense. "
                    "A file can be in several collections and stays in the Files "
                    "list, and a collection can have fields of its own, such as a "
                    "price or a rating."
                ),
                image_url="/announcement-images/collections.png",
                image_alt=(
                    "A collection of maps and handouts in Files, laid out as a "
                    "masonry gallery"
                ),
            ),
            AnnouncementSection(
                starts_page=True,
                heading="Upload almost anything",
                body=(
                    "Audio, video, archives, OpenDocument, design files, 3D "
                    "models, fonts, e-books and more upload as files, each with "
                    "its category's icon. Videos and recordings play in the app, "
                    "and a Word or OpenDocument file can be turned into a "
                    "document you edit here.\n\n"
                    "Programs and scripts are the one thing refused."
                ),
            ),
            AnnouncementSection(
                starts_page=True,
                heading="Queues are now projects",
                body=(
                    "We want Initiative to stay focused on project management. "
                    "Projects now have task types, statuses, properties and "
                    "board, table, Gantt and calendar views, so most of what we "
                    "built queues for is done better in a project.\n\n"
                    "Each queue is now a **project** in the same initiative, and "
                    "each of its items a task, in the order the queue showed "
                    "them. The item it was on is **Up now**, held items are "
                    "**Held**, hidden ones **Sitting out** and the rest "
                    "**Waiting**. An item's member is linked to its task, and its "
                    "comments, sharing, tags and links came with it."
                ),
            ),
            AnnouncementSection(
                heading="Taking turns",
                body=(
                    "A project has no **Next** button or rounds. Move a task to "
                    "**Up now** when it's someone's turn, and to **Done** once "
                    "it's finished."
                ),
            ),
        ),
    ),
)
