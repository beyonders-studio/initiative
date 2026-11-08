"""The optional cookie categories Initiative knows about, and which of them a
given deployment actually uses.

Two separate questions, deliberately:

*What categories exist* is code. A category is here because Initiative has
something that would use it — an analytics integration compiled into the app,
say — not because an operator typed its name in. Nobody invents one.

*Which of them this deployment uses* is configuration, read at request time.
An integration that ships in the app is still off until the deployment
configures it, which is the normal state for somebody running this on their
own server, so most deployments use none of these.

Only the second list is offered to a visitor. A switch for something the
deployment does not do would collect an answer about nothing, and record a
refusal of something nobody was doing.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from app.core.config import Settings


class CookieCategory(str, Enum):
    """A kind of optional storage a visitor can be asked about.

    The vocabulary, not the offer — see the module docstring. Frontend labels
    are keyed on these values and a drift test keeps the two in step.
    """

    analytics = "analytics"
    marketing = "marketing"


#: How each category knows whether this deployment uses it.
#:
#: An entry says "we ship something in this category, and here is how to tell
#: whether it is switched on here". A category with no entry is never offered,
#: which is what every category looks like until the thing behind it exists.
#:
#: One line per integration, and the chooser grows a switch on the deployments
#: that configured it and nowhere else.
CATEGORY_IN_USE: dict[CookieCategory, Callable[[Settings], bool]] = {
    # Frontend measurement, sent to the collector the deployment names.
    CookieCategory.analytics: lambda settings: bool(settings.FARO_COLLECTOR_URL),
}


def active_cookie_categories(settings: Settings) -> list[CookieCategory]:
    """The optional categories this deployment actually uses.

    Ordered by the enum so the chooser lists them the same way every time.
    Empty on a deployment that has configured none, which is the default: the
    chooser then has nothing to ask and says so rather than offering switches
    that would do nothing.
    """
    return [
        category
        for category in CookieCategory
        if CATEGORY_IN_USE.get(category, lambda _: False)(settings)
    ]
