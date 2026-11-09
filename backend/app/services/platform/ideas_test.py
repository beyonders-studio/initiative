"""An idea's category, read from its words."""

from __future__ import annotations

import json

import pytest

from app.blueprints.intake import BLUEPRINT_DIR, CATEGORY_FIELD
from app.services.platform.ideas import category_named

#: The Ideas blueprint's categories, in its order.
LABELS = next(
    [option["label"] for option in field["options"]]
    for field in json.loads((BLUEPRINT_DIR / "ideas.json").read_text())[
        "property_definitions"
    ]
    if field["name"] == CATEGORY_FIELD
)


@pytest.mark.parametrize(
    ("title", "description", "named"),
    [
        # The label, either case, or its singular.
        ("Archive a project", None, "Projects"),
        ("PROJECTS that repeat", None, "Projects"),
        ("Snooze a notification", None, "Notifications"),
        # A label that is a single word takes its plural too.
        ("Merge two accounts", None, "Account"),
        # A hyphen joins the words either side of it, in the text and the
        # label alike.
        ("A plugin for invoices", None, "Plug-ins"),
        ("A plug-in for invoices", None, "Plug-ins"),
        ("More Plug-ins", None, "Plug-ins"),
        # Whole words only.
        ("Projection of costs", None, None),
        ("Profiles everywhere", None, None),
        # The title first, then the description.
        ("Dark mode", "Starts with the calendar and its files.", "Calendars"),
        ("Share a wiki", "Like a file is shared.", "Wikis"),
        # Two in the same text: the one mentioned first.
        ("Attach files to a post", None, "Files"),
        ("Post a file", None, "Posts"),
        ("Nothing named", "Nor here.", None),
        ("", None, None),
    ],
)
def test_an_idea_is_filed_under_the_category_its_words_name(
    title: str, description: str | None, named: str | None
) -> None:
    assert category_named(title, description, LABELS) == named


def test_the_categories_are_the_tools_then_the_rest() -> None:
    assert LABELS == [
        "Projects",
        "Files",
        "Counters",
        "Calendars",
        "Dashboards",
        "Posts",
        "Wikis",
        "Contacts",
        "Notifications",
        "Account",
        "Plug-ins",
    ]


def test_a_label_of_several_words_is_named_by_them_all() -> None:
    labels = ["Mobile app", "Apps"]
    assert category_named("The mobile apps crash", None, labels) == "Mobile app"
    assert category_named("An app for my phone", None, labels) == "Apps"
