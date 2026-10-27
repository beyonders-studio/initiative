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
from datetime import datetime, timezone

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
        slug="0-65-admin-sidebar-lists-your-initiatives",
        title="Your sidebar now lists the initiatives you are in",
        category=AnnouncementCategory.breaking,
        published_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        # Only the people it changes anything for, and worth saying twice: an
        # admin who skims past it will conclude their initiatives are gone.
        guild_admins_only=True,
        dismissals_required=2,
        # Their sidebar is what changed, so this is for the people who had one
        # before the change — not for somebody signing up next month, and not
        # for a deployment that was never on the old behaviour.
        audience_accounts=AnnouncementAudienceAccounts.existing,
        only_upgrading_from_below="0.66.0",
        # Only inside a community. The notice is about the community sidebar,
        # and that sidebar is not on screen when someone lands on their own
        # task list at sign-in — a notice about a thing you cannot see is just
        # a thing in the way.
        trigger_route="/c/**",
        sections=(
            AnnouncementSection(
                heading="What changed",
                body=(
                    "Administering a community used to put **every** initiative in "
                    "it in your sidebar, whether you had anything to do with it or "
                    "not. Now your sidebar lists the initiatives you are actually a "
                    "member of, the same as everybody else's.\n\n"
                    "Nothing has been deleted, and nothing has been taken away from "
                    "you: as a community admin you can still reach and manage every "
                    "initiative in your community. The sidebar is a list of where "
                    "you work, not a list of what you are allowed to open."
                ),
                image_url="/announcement-images/admin-sidebar-initiatives.png",
                image_alt=(
                    "A community sidebar listing only the two initiatives this "
                    "admin belongs to"
                ),
            ),
            AnnouncementSection(
                starts_page=True,
                heading="Putting one back in your sidebar",
                body=(
                    "Open **Community settings → Initiatives**. Every initiative "
                    "in the community is listed there, whether you are in it or "
                    "not.\n\n"
                    "Set yourself as a **project manager** on the one you want, "
                    "and it appears in your sidebar with everything inside it."
                ),
                image_url="/announcement-images/admin-add-self-as-manager.png",
                image_alt=(
                    "The Initiatives tab of community settings, with the project "
                    "managers picker open on one initiative"
                ),
            ),
        ),
    ),
    BuiltinAnnouncement(
        slug="0-66-search-needs-bootstrap-connection",
        title="Search needs one line in your compose file",
        category=AnnouncementCategory.maintenance,
        published_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        # Only the people who can edit a deployment's environment, and only on
        # a deployment that upgraded into this: a fresh install came up with
        # the connection already wired, so there is nothing for it to add.
        min_platform_role=UserRole.operator,
        only_upgrading_from_below="0.66.0",
        # Missing it costs search on every query from here on, and the log line
        # that used to say so is the one operators were already skimming past.
        dismissals_required=2,
        sections=(
            AnnouncementSection(
                heading="What changed",
                body=(
                    "Initiative now creates its own database roles and installs "
                    "the search index's match operator at startup, over a fourth "
                    "connection, `DATABASE_URL_BOOTSTRAP`, made as the database "
                    "owner. Nothing has to be piped between containers any more.\n\n"
                    "An install that upgraded without that connection keeps running "
                    "exactly as before, but it can only check those prerequisites, "
                    "not apply them. If the search operator was never installed "
                    "here, search goes on reading more of its index than it should, "
                    "and the startup log goes on saying so."
                ),
            ),
            AnnouncementSection(
                starts_page=True,
                heading="What to do",
                body=(
                    "Add `DATABASE_URL_BOOTSTRAP` to the backend's environment, "
                    "pointing at this database as its owner, the way the example "
                    "compose file does:\n\n"
                    "```\n"
                    "DATABASE_URL_BOOTSTRAP: postgresql+asyncpg://<owner>:<password>@db:5432/<database>\n"
                    "```\n\n"
                    "Then restart. The log reports the roles and the search "
                    "operator as applied. You can leave the line in place, or "
                    "remove it once the stack is up: Initiative then verifies those "
                    "prerequisites instead of applying them, and names anything "
                    "missing.\n\n"
                    "If your database is provisioned elsewhere, print the SQL and "
                    "run it as the owner yourself:\n\n"
                    "```\n"
                    "docker compose exec -T initiative python -m app.db.bootstrap --print-sql\n"
                    "```"
                ),
            ),
        ),
    ),
    BuiltinAnnouncement(
        slug="0-66-my-pages-moved",
        title="Three sidebar pages became one",
        category=AnnouncementCategory.info,
        published_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        # For the people who had those pages in their sidebar last week. A new
        # account never saw them, and a fresh install never had them.
        audience_accounts=AnnouncementAudienceAccounts.existing,
        only_upgrading_from_below="0.66.0",
        sections=(
            AnnouncementSection(
                heading="Where they went",
                body=(
                    "**My Projects** and **My Documents** are now one page, "
                    "**My Tools**. Pick a tool at the top and see everything of "
                    "that kind that reaches you, across every community you are "
                    "in. A toggle narrows it to only what you made.\n\n"
                    "**Tasks I Created** is gone. **My Tasks** already answered "
                    "that question, and the toggle on My Tools has the same "
                    "reach.\n\n"
                    "**My Contacts** has folded into **My Messages**. The people "
                    "you can reach are the conversation list, requests either way "
                    "round sit above it, and the **+** finds anybody you have not "
                    "messaged yet. A community's own roster now lives on its "
                    "member count. Old links to My Contacts land on My Messages."
                ),
            ),
        ),
    ),
    BuiltinAnnouncement(
        slug="0-67-notifications",
        title="Notifications got a lot quieter",
        category=AnnouncementCategory.feature,
        published_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
        # For accounts that lived with the old, louder version.
        audience_accounts=AnnouncementAudienceAccounts.existing,
        only_upgrading_from_below="0.67.0",
        sections=(
            AnnouncementSection(
                heading="Four things, all of them quieter",
                body=(
                    "**Quiet hours.** Pick a window. Email and mobile hold off "
                    "inside it, and one message in the morning tells you what "
                    "you missed.\n\n"
                    "**A dial per community.** Everything, only what names you, "
                    "or nothing. Nothing means nothing.\n\n"
                    "**The bell is a setting now.** It used to be the one thing "
                    "you could not turn down. It has its own column in the "
                    "grid, per category.\n\n"
                    "**Twenty comments on your task are one line.** Not twenty. "
                    "Same for reactions.\n\n"
                    "All of it lives in **User settings → Notifications**."
                ),
            ),
        ),
    ),
    BuiltinAnnouncement(
        slug="0-76-comment-removal-moved-to-moderators",
        title="Taking down comments is for moderators now",
        category=AnnouncementCategory.breaking,
        published_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
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
        published_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
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
        slug="0-78-galleries-are-collections",
        title="Galleries are now collections",
        category=AnnouncementCategory.info,
        published_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
        # For the people who had galleries. A new account and a fresh install
        # start with collections and nothing to look for.
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
        ),
    ),
)


def builtin_by_key(key: str) -> BuiltinAnnouncement | None:
    """The builtin a read receipt's key names, if this version still has it."""
    for announcement in BUILTIN_ANNOUNCEMENTS:
        if announcement.key == key:
            return announcement
    return None
