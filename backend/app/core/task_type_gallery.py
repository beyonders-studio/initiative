"""The ready-made task types a project can add: what each is called, how its
page is shaped, the fields it brings and what a new task of it starts with.

"Add type" offers these, grouped by what they are for, beside starting blank
or from one of the project's own. Each is a suggestion: the person adding it
names it ("Event", or "Gig", or "Session"), and everything about it can be
changed afterwards. Its words (name, hint, field names, a description outline)
are in the ``projects`` catalogue under ``taskTypes.gallery``, because they are
chrome until the type is added — and then written in the language of whoever
added it, as a project's starting types are.

Its fields are properties of the project's initiative. Adding the type creates
the ones the initiative lacks and reuses one of the same name and kind, so two
types that each want a Location share one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: The groups the gallery is shown in, in order.
GALLERY_GROUPS: tuple[str, ...] = ("planning", "home", "groups", "making", "learning")


@dataclass(frozen=True)
class GalleryField:
    """A field a type brings: a property of the initiative."""

    #: Its name's key (``taskTypes.gallery.fields.<key>``).
    key: str
    #: A ``MetadataType`` value.
    type: str


@dataclass(frozen=True)
class GalleryStart:
    """What a new task of the type starts with. ``outline`` names a
    description in the catalogue (``taskTypes.gallery.outlines.<key>``)."""

    outline: Optional[str] = None
    priority: Optional[str] = None
    recurrence: Optional[str] = None
    recurrence_strategy: Optional[str] = None


@dataclass(frozen=True)
class GalleryType:
    #: Its key, and its words' (``taskTypes.gallery.types.<key>``).
    key: str
    group: str
    shape: str
    color: str
    icon: str
    fields: tuple[GalleryField, ...] = ()
    start: GalleryStart = field(default_factory=GalleryStart)


_LOCATION = GalleryField("location", "text")
_LINK = GalleryField("link", "url")

#: Every ready-made type, in the order the gallery lists them within a group.
GALLERY: tuple[GalleryType, ...] = (
    # Planning: something with a date.
    GalleryType("milestone", "planning", "dates", "#A78BFA", "flag"),
    GalleryType(
        "event", "planning", "dates", "#60A5FA", "calendar-days", fields=(_LOCATION,)
    ),
    GalleryType(
        "appointment", "planning", "dates", "#22D3EE", "clock", fields=(_LOCATION,)
    ),
    # Around the house: what comes round again, and what needs fetching.
    GalleryType(
        "chore",
        "home",
        "repeat",
        "#34D399",
        "repeat",
        start=GalleryStart(recurrence="RRULE:FREQ=WEEKLY"),
    ),
    GalleryType("errand", "home", "checklist", "#FB923C", "shopping-cart"),
    GalleryType(
        "bill",
        "home",
        "repeat",
        "#F472B6",
        "receipt",
        fields=(GalleryField("amount", "number"),),
        start=GalleryStart(recurrence="RRULE:FREQ=MONTHLY"),
    ),
    # Groups and volunteers.
    GalleryType(
        "shift", "groups", "dates", "#F59E0B", "hand-helping", fields=(_LOCATION,)
    ),
    GalleryType(
        "purchase",
        "groups",
        "plain",
        "#10B981",
        "shopping-bag",
        fields=(GalleryField("cost", "number"), _LINK),
    ),
    GalleryType("question", "groups", "discussion", "#FBBF24", "circle-help"),
    GalleryType("idea", "groups", "discussion", "#FBBF24", "lightbulb"),
    GalleryType("request", "groups", "plain", "#94A3B8", "inbox"),
    # Making things.
    GalleryType(
        "bug",
        "making",
        "fix",
        "#F87171",
        "bug",
        start=GalleryStart(outline="bug"),
    ),
    GalleryType("feature", "making", "plain", "#60A5FA", "sparkles"),
    GalleryType("art", "making", "plain", "#F472B6", "palette"),
    GalleryType(
        "playtest",
        "making",
        "discussion",
        "#A78BFA",
        "gamepad-2",
        start=GalleryStart(outline="playtest"),
    ),
    # Learning.
    GalleryType("assignment", "learning", "dates", "#F87171", "notebook-pen"),
    GalleryType(
        "reading", "learning", "plain", "#34D399", "book-open", fields=(_LINK,)
    ),
)

GALLERY_BY_KEY: dict[str, GalleryType] = {entry.key: entry for entry in GALLERY}
