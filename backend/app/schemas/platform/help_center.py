"""The help center's search index, as the app's Help panel reads it."""

from typing import List

from app.schemas.base import RawTextStr, SanitizedBaseModel


class HelpIndexEntry(SanitizedBaseModel):
    """One page or heading of the help center, as plain text."""

    # Written by the image build from the help center's own pages
    # (scripts/build_help_index.py) and kept verbatim: a snippet may quote a
    # placeholder such as ``<name>``, which the plain-text sanitizer would drop
    # as a tag.
    title: RawTextStr
    #: Where it sits, the last two steps of its breadcrumb:
    #: ``FAQ › Getting in``. Empty for a top-level section's own page.
    section: RawTextStr
    #: Its address from the help center's root, with its anchor:
    #: ``en/faq/#my-invite-link-doesnt-work``.
    location: RawTextStr
    #: The start of its text, about 200 characters, cut at a word.
    snippet: RawTextStr


class HelpIndex(SanitizedBaseModel):
    """Every English page and heading of the help center, down to level 3, in
    the order the help center has them."""

    items: List[HelpIndexEntry]
