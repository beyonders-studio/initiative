"""The notices this build ships have to be usable notices.

Everything here is about the real registry rather than a fixture: a builtin is
edited by hand in source, is not validated by any endpoint on the way in, and
is wrong in ways nobody sees until it is in front of every admin on every
deployment. A screenshot that was never committed is the likeliest of those.
"""

from __future__ import annotations

import pathlib

import pytest


from app.core.builtin_announcements import BUILTIN_ANNOUNCEMENTS
from app.core.version import compare_versions
from app.schemas.platform.announcement import (
    IMAGE_PATH_PREFIX,
    MAX_DISMISSALS_REQUIRED,
    MAX_SECTIONS,
)

pytestmark = pytest.mark.always

#: Where a builtin's pictures are shipped: static assets in the SPA's public
#: directory, served at ``/announcement-images/…``.
_ASSET_ROOT = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "public"
_ASSET_URL_PREFIX = "/announcement-images/"


def test_slugs_are_unique():
    slugs = [announcement.slug for announcement in BUILTIN_ANNOUNCEMENTS]
    assert len(slugs) == len(set(slugs))


def test_every_entry_says_something():
    for announcement in BUILTIN_ANNOUNCEMENTS:
        assert announcement.title.strip()
        assert announcement.sections, announcement.slug
        assert len(announcement.sections) <= MAX_SECTIONS, announcement.slug
        assert 1 <= announcement.dismissals_required <= MAX_DISMISSALS_REQUIRED
        for section in announcement.sections:
            assert not section.is_empty(), announcement.slug


def test_every_picture_is_actually_shipped():
    """A builtin cannot upload its screenshots, so they have to be in the repo."""
    for announcement in BUILTIN_ANNOUNCEMENTS:
        for section in announcement.sections:
            url = section.image_url
            if not url or not url.startswith(_ASSET_URL_PREFIX):
                continue
            asset = _ASSET_ROOT / url.lstrip("/")
            assert asset.is_file(), f"{announcement.slug}: {url} is not in the repo"
            assert section.image_alt, f"{announcement.slug}: {url} has no alt text"


def test_every_upgrade_floor_reads_as_a_version():
    """A floor that does not parse silently becomes 0.0.0 and tells nobody."""
    for announcement in BUILTIN_ANNOUNCEMENTS:
        floor = announcement.only_upgrading_from_below
        if floor is None:
            continue
        assert compare_versions(floor, "0.0.0") > 0, announcement.slug


def test_no_entry_points_at_the_upload_endpoint():
    """Uploads belong to authored notices; a builtin predates any database."""
    for announcement in BUILTIN_ANNOUNCEMENTS:
        for section in announcement.sections:
            assert not (section.image_url or "").startswith(IMAGE_PATH_PREFIX)


def test_a_page_break_never_opens_the_notice():
    """The first section starts page one; a break on it would mean nothing."""
    for announcement in BUILTIN_ANNOUNCEMENTS:
        if announcement.sections:
            assert not announcement.sections[0].starts_page, announcement.slug
