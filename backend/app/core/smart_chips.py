"""Smart chips — the facts a chip can show about a thing it references.

A reference (:mod:`app.core.references`) names something and resolves to what
it is called. A chip goes one step further and shows a fact ABOUT it that
changes on its own: the column a task sits in, a counter's reading, when an
event is.

Only the facts live here. Which kinds can be referred to at all is a reference
question, not a chip one.
"""

from enum import Enum

from app.core.references import REF_SEPARATOR
from app.core.search import SearchEntityType


class SmartChipAspect(str, Enum):
    """The fact a chip is about."""

    #: A task's column — the one that answers "where is this".
    status = "status"
    #: Who is holding it.
    assignee = "assignee"
    #: When it is due, and whether that has passed.
    due = "due"
    #: How urgent it was said to be.
    priority = "priority"
    #: A counter's current reading.
    value = "value"
    #: When something happens, and whether it has.
    when = "when"
    #: How much of the work in something is finished.
    progress = "progress"
    #: Whether a task is finished, as a box to tick.
    checklist = "checklist"
    #: How to call somebody: a contact's first phone number.
    phone = "phone"
    #: How to write to somebody: a contact's first email address.
    email = "email"


class SmartChipTone(str, Enum):
    """How a chip is coloured when nothing more specific applies.

    The server decides this rather than the client, because what counts as
    finished, late or urgent is a product rule and not a rendering detail. A
    chip with its own colour — a task status carries one — sends that instead.
    """

    neutral = "neutral"
    #: Nothing there yet: unassigned, no date.
    muted = "muted"
    #: Finished, or otherwise where you want it to be.
    good = "good"
    #: Worth noticing.
    warn = "warn"
    #: Late, or urgent.
    danger = "danger"


#: Every chip there is: a thing, and the changing fact about it.
#:
#: One entry is one reader in ``app.services.tenant.smart_chips``;
#: ``smart_chips_test`` fails until a pair added here has one.
SMART_CHIP_KINDS: tuple[tuple[SearchEntityType, SmartChipAspect], ...] = (
    (SearchEntityType.calendar_event, SmartChipAspect.when),
    (SearchEntityType.contact, SmartChipAspect.email),
    (SearchEntityType.contact, SmartChipAspect.phone),
    (SearchEntityType.counter, SmartChipAspect.value),
    (SearchEntityType.project, SmartChipAspect.progress),
    (SearchEntityType.task, SmartChipAspect.assignee),
    (SearchEntityType.task, SmartChipAspect.due),
    (SearchEntityType.task, SmartChipAspect.priority),
    (SearchEntityType.task, SmartChipAspect.status),
    (SearchEntityType.task, SmartChipAspect.checklist),
)

#: Chips a reader can act on from the page — a box ticked in a file ticks
#: the task. Each answer says whether this reader may, so the chip offers only
#: what the request would allow.
ACTIONABLE_CHIP_KINDS: frozenset[tuple[SearchEntityType, SmartChipAspect]] = frozenset(
    {(SearchEntityType.task, SmartChipAspect.checklist)}
)


def kind_value(entity_type: SearchEntityType, aspect: SmartChipAspect) -> str:
    """The pair as the API spells it: ``task:status``."""
    return f"{entity_type.value}{REF_SEPARATOR}{aspect.value}"


#: The pairs as a closed set the generated client reads, so an editor's insert
#: menu is built from what this server actually answers.
SmartChipKind = Enum(
    "SmartChipKind",
    {
        f"{kind.value}_{aspect.value}": kind_value(kind, aspect)
        for kind, aspect in SMART_CHIP_KINDS
    },
    type=str,
    module=__name__,
)
