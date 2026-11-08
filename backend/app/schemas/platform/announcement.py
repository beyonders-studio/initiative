"""Request/response shapes for announcements.

One output shape, :class:`AnnouncementRead`, serves both the notices an
operator wrote and the ones compiled into the app — the client renders them
identically and only ever needs the ``key`` to say "I have read this". The
operator surface adds the fields a reader has no business with (draft state,
audience, authorship) in :class:`AnnouncementOperatorRead`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, Field, field_validator

from app.models.platform.announcement import (
    AnnouncementAudienceAccounts,
    AnnouncementCategory,
)
from app.models.platform.user import UserRole
from app.schemas.base import RichTextStr, SanitizedBaseModel

#: A body long enough for a paragraph or three of markdown per section, and
#: nowhere near long enough to be a document.
MAX_SECTION_BODY_LENGTH = 4000

#: Sections per announcement. A release note that needs more than this is a
#: changelog, which the app already has.
MAX_SECTIONS = 20

#: How many acknowledgements one announcement may demand. Three is already
#: nagging; ten is the outer bound so a typo cannot make a notice immortal.
MAX_DISMISSALS_REQUIRED = 10

#: Where a section's picture may point: an image uploaded here (addressed by
#: digest), any other path this deployment serves (a builtin notice ships its
#: screenshots as static assets), or an absolute http(s) URL for one hosted
#: elsewhere.
IMAGE_PATH_PREFIX = "/api/v1/announcements/images/"


class AnnouncementSection(SanitizedBaseModel):
    """One beat of an announcement: a heading, some prose, and a picture.

    Every part is optional on its own, but a section with none of them is
    nothing, so at least one must be present.
    """

    heading: str | None = Field(default=None, max_length=160)
    #: Start a new page here. Sections are one flowing list until a section
    #: says otherwise, and the reader pages through the groups that makes —
    #: which is all a "wizard" announcement is.
    starts_page: bool = False
    body: RichTextStr | None = Field(default=None, max_length=MAX_SECTION_BODY_LENGTH)
    image_url: str | None = Field(default=None, max_length=2048)
    #: What the picture shows, for anyone who cannot see it.
    image_alt: str | None = Field(default=None, max_length=200)

    @field_validator("image_url")
    @classmethod
    def _check_image_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        # A protocol-relative "//host/x" is a remote URL wearing a path's
        # clothes, so it goes through the scheme check like any other.
        if value.startswith("/") and not value.startswith("//"):
            return value
        if value.startswith(("https://", "http://")):
            return value
        raise ValueError("image_url must be a site-relative path or an http(s) URL")

    @field_validator("heading", "body", "image_alt")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def is_empty(self) -> bool:
        return not (self.heading or self.body or self.image_url)


def _validate_trigger_route(value: str | None) -> str | None:
    """A trigger is a path pattern, so it looks like one.

    Only the shape is checked here: whether it matches anything is the SPA's
    question, and it is the SPA that answers it.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if not trimmed.startswith("/") or trimmed.startswith("//"):
        raise ValueError("trigger_route must be a site-relative path pattern")
    return trimmed


class AnnouncementRead(SanitizedBaseModel):
    """An announcement as a reader receives it."""

    #: Stable identity across both sources — ``db:<id>`` or ``builtin:<slug>``.
    key: str
    title: str
    category: AnnouncementCategory
    sections: list[AnnouncementSection] = Field(default_factory=list)
    published_at: datetime | None = None
    #: True for notices shipped in the app's own source rather than authored
    #: in the operator surface; they cannot be edited from the UI.
    is_builtin: bool = False
    #: When this reader last acknowledged it, if they have.
    dismissed_at: datetime | None = None
    #: How many acknowledgements this notice asks for, and how many this
    #: reader has given — the client shows the remainder and stops queueing it
    #: once they match.
    dismissals_required: int = 1
    dismiss_count: int = 0
    #: Route pattern this notice waits for, or None to queue it on sight.
    trigger_route: str | None = None


class AnnouncementListResponse(SanitizedBaseModel):
    items: list[AnnouncementRead] = Field(default_factory=list)


class AnnouncementOperatorRead(AnnouncementRead):
    """Everything about an announcement, for the people who write them."""

    id: int | None = None
    min_platform_role: UserRole = UserRole.member
    community_admins_only: bool = Field(
        default=False,
        validation_alias=AliasChoices("community_admins_only", "guild_admins_only"),
    )
    audience_accounts: AnnouncementAudienceAccounts = (
        AnnouncementAudienceAccounts.everyone
    )
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnnouncementOperatorListResponse(SanitizedBaseModel):
    items: list[AnnouncementOperatorRead] = Field(default_factory=list)


class AnnouncementWrite(SanitizedBaseModel):
    """Body for creating an announcement, and the base for editing one."""

    title: str = Field(min_length=1, max_length=200)
    category: AnnouncementCategory = AnnouncementCategory.info
    sections: list[AnnouncementSection] = Field(default_factory=list)
    min_platform_role: UserRole = UserRole.member
    community_admins_only: bool = False
    audience_accounts: AnnouncementAudienceAccounts = (
        AnnouncementAudienceAccounts.everyone
    )
    published_at: datetime | None = None
    expires_at: datetime | None = None
    dismissals_required: int = Field(default=1, ge=1, le=MAX_DISMISSALS_REQUIRED)
    trigger_route: str | None = Field(default=None, max_length=200)

    @field_validator("trigger_route")
    @classmethod
    def _check_trigger_route(cls, value: str | None) -> str | None:
        return _validate_trigger_route(value)

    @field_validator("sections")
    @classmethod
    def _check_sections(
        cls, value: list[AnnouncementSection]
    ) -> list[AnnouncementSection]:
        if len(value) > MAX_SECTIONS:
            raise ValueError(
                f"an announcement may have at most {MAX_SECTIONS} sections"
            )
        kept = [section for section in value if not section.is_empty()]
        if not kept:
            raise ValueError("an announcement needs at least one non-empty section")
        return kept


class AnnouncementUpdate(SanitizedBaseModel):
    """Body for editing an announcement — every field optional."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: AnnouncementCategory | None = None
    sections: list[AnnouncementSection] | None = None
    min_platform_role: UserRole | None = None
    community_admins_only: bool | None = None
    audience_accounts: AnnouncementAudienceAccounts | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None
    dismissals_required: int | None = Field(
        default=None, ge=1, le=MAX_DISMISSALS_REQUIRED
    )
    trigger_route: str | None = Field(default=None, max_length=200)
    #: Explicit unsets, because ``None`` on the fields above means "leave as is".
    clear_published_at: bool = False
    clear_expires_at: bool = False
    clear_trigger_route: bool = False

    @field_validator("trigger_route")
    @classmethod
    def _check_trigger_route(cls, value: str | None) -> str | None:
        return _validate_trigger_route(value)

    @field_validator("sections")
    @classmethod
    def _check_sections(
        cls, value: list[AnnouncementSection] | None
    ) -> list[AnnouncementSection] | None:
        if value is None:
            return None
        return AnnouncementWrite._check_sections(value)


class AnnouncementImageRead(SanitizedBaseModel):
    """Where an uploaded picture now lives, and how big it is."""

    url: str
    sha256: str
    content_type: str
    byte_size: int
    width: int
    height: int
