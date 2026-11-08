"""What the deployment has to tell the people using it.

An announcement is a short, illustrated notice shown once and then remembered:
a new feature to look at, a setting that moved, a breaking change to act on.
It is deployment-wide rather than guild content — the same notice reaches every
guild, and it is written by whoever runs the platform — so it lives in
``public`` beside the other operator-owned tables.

Three tables, one idea:

* ``announcements`` — the notices an operator wrote, each an ordered list of
  **sections** (heading, prose, picture). A release note is rarely one
  paragraph; it is "here is the new board view" with a screenshot, then "here
  is where the old filter went" with another, which is why the body is a list
  rather than a single markdown blob.
* ``announcement_reads`` — one row per (person, announcement) recording that
  they saw it and, separately, that they acknowledged it. Keyed by an opaque
  string rather than a foreign key so the *same* table also remembers the
  notices that ship in the app's own source
  (``app.core.builtin_announcements``), which have no row to point at.
* ``announcement_images`` — the pictures those sections show, stored as bytes
  here for the reason guild images are: the public plane has no object store,
  every S3 key being namespaced under a guild, and an announcement crosses
  exactly that boundary.

Who *sees* a given announcement is two independent filters on the row —
a minimum platform rung (``min_platform_role``) and "is a guild admin
somewhere" (``guild_admins_only``) — evaluated in
``app.services.platform.announcements``. They are audience selection, not a
confidentiality boundary: what RLS enforces here is that an unpublished draft
is nobody's business but the author's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlmodel import Field, Index, SQLModel

from app.core.image_headers import RASTER_CONTENT_TYPES, ImageSpec


class AnnouncementAudienceAccounts(str, Enum):
    """Which accounts a notice is for, measured against its publication.

    A breaking change is about a *transition*: somebody who signed up
    afterwards never lived on the old behaviour and has nothing to act on.
    The inverse is just as useful — an onboarding tip is for the people who
    have just arrived, and stale for everyone else.
    """

    everyone = "everyone"
    #: Accounts that already existed when it was published.
    existing = "existing"
    #: Accounts made since.
    new = "new"


class AnnouncementCategory(str, Enum):
    """What kind of news this is — drives the icon and accent, nothing else."""

    release = "release"
    feature = "feature"
    breaking = "breaking"
    maintenance = "maintenance"
    security = "security"
    info = "info"


#: A screenshot: full-width captures of a feature, so generous next to a guild
#: icon at 2 MB, and mean next to a photo library, because they are pasted into
#: a table row that every reader loads. Any shape up to 4096px on its longest
#: side; anything larger is a screenshot nobody resized.
ANNOUNCEMENT_IMAGE_SPEC = ImageSpec(
    4096, 4096, 2 * 1024 * 1024, RASTER_CONTENT_TYPES, keep_aspect=False
)

#: How ``announcement_reads`` names what was read. DB rows are ``db:<id>``;
#: notices compiled into the app are ``builtin:<slug>``.
DB_KEY_PREFIX = "db:"
BUILTIN_KEY_PREFIX = "builtin:"


def db_announcement_key(announcement_id: int) -> str:
    return f"{DB_KEY_PREFIX}{announcement_id}"


def builtin_announcement_key(slug: str) -> str:
    return f"{BUILTIN_KEY_PREFIX}{slug}"


class Announcement(SQLModel, table=True):
    __tablename__ = "announcements"
    __table_args__ = (
        # Every read is "what is live now, newest first"; the operator list is the
        # same query with the published filter dropped.
        Index("ix_announcements_published_at", "published_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(200), nullable=False))
    category: str = Field(
        sa_column=Column(String(16), nullable=False, server_default="info"),
        default=AnnouncementCategory.info.value,
    )
    #: Ordered ``AnnouncementSection`` objects (heading / body / image), stored
    #: as one document because they are only ever written and read whole —
    #: the editor submits the full list on every save.
    sections: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    #: Lowest platform rung this is meant for — "member" reaches everyone.
    min_platform_role: str = Field(
        sa_column=Column(String(16), nullable=False, server_default="member"),
        default="member",
    )
    #: When set, only people who administer at least one guild see it.
    guild_admins_only: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    #: Whether the notice is for accounts that predate it, accounts made since,
    #: or everyone. Measured against ``published_at``.
    audience_accounts: str = Field(
        sa_column=Column(String(16), nullable=False, server_default="everyone"),
        default=AnnouncementAudienceAccounts.everyone.value,
    )
    #: NULL is a draft. A future timestamp is scheduled; both are invisible to
    #: everyone but the authors, and RLS is what makes that true.
    published_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Past this, the notice stops being shown. Old news is worse than none.
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: How many times a person has to acknowledge this before it stops coming
    #: back. One is the normal case — say it, they dealt with it, done. A
    #: breaking change that costs someone their evening if they miss it is
    #: worth two or three: the notice returns on their next session until they
    #: have dismissed it that many times.
    dismissals_required: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )
    #: When set, the notice is not queued on sight — it waits until the reader
    #: opens a matching page, and is then shown there. That is what turns an
    #: announcement into in-context help: "here is what this screen does", on
    #: the screen it is about. Matched client-side against the route path
    #: (``*`` one segment, ``**`` the rest), because the server has no idea
    #: what the SPA's routes are.
    trigger_route: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnnouncementReadReceipt(SQLModel, table=True):
    """That one person has seen — and separately, acknowledged — one notice.

    The halves answer different questions: ``seen_at`` is how the dialog stops
    re-queueing something already on screen, and the dismissal pair is the
    person saying they are done with it. Only dismissal takes a notice out of
    the queue — and only once ``dismiss_count`` reaches the announcement's
    ``dismissals_required``, which is how a notice can insist on being
    acknowledged more than once.
    """

    __tablename__ = "announcement_reads"

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    #: ``db:<id>`` or ``builtin:<slug>`` — see the module docstring.
    announcement_key: str = Field(
        sa_column=Column(String(120), primary_key=True, nullable=False)
    )
    seen_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: The most recent dismissal, or None if they have never dismissed it.
    dismissed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: How many times they have dismissed it. Compared against the
    #: announcement's ``dismissals_required`` to decide whether it is finished.
    dismiss_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )


class AnnouncementImage(SQLModel, table=True):
    """One picture an announcement section shows, addressed by its digest.

    The digest is the URL's last segment, so the bytes behind a URL never
    change and the response can be cached forever. Uploading the same
    screenshot twice stores it once.
    """

    __tablename__ = "announcement_images"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sha256: str = Field(sa_column=Column(String(64), primary_key=True, nullable=False))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    width: int = Field(sa_column=Column(Integer, nullable=False))
    height: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: When these bytes were last put here. Uploading the same picture twice
    #: keeps one row and moves this, because it is what the orphan sweep reads
    #: to decide whether nobody wants it — and a re-upload is somebody
    #: wanting it.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
