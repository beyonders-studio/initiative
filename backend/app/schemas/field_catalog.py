"""What the field registry tells a client.

A description, never a resolver: what a field compiles to is the server's, and
what it is called, what it holds, and what picks it are the client's. Nothing
here is tenant data — the same answer for every guild on a deployment — so it is
served off the platform path rather than a guild one.

Every field is typed as the enum it actually is, so the generated client gets
real unions rather than bare strings and a client cannot name a control or an
operator this build does not have.
"""

from typing import Any

from app.schemas.base import SanitizedBaseModel
from app.schemas.query import FilterOp
from app.services.fields.spec import ControlKind, FieldType


class FieldDescription(SanitizedBaseModel):
    """One field a client may offer for filtering."""

    #: The name a stored condition uses.
    name: str
    #: What the value is, for comparison and formatting.
    type: FieldType
    #: Which control picks a value — a member picker, a date picker, a tag
    #: picker. The client maps this to a component; the server never names one.
    kind: ControlKind
    #: The operators this control offers. Already narrowed to what the engine
    #: accepts, so anything here compiles.
    ops: list[FilterOp]
    #: Whether the control picks several values at once.
    multiple: bool
    #: Whether a list may be ordered by this field.
    sortable: bool
    #: The values this field accepts, when it accepts a closed set of them —
    #: read off the column that stores them. A client offers these rather than
    #: keeping its own copy, so a value added by a migration shows up on its
    #: own. Empty for a field whose values a lookup has to enumerate.
    options: list[str] = []


class RelationDescription(SanitizedBaseModel):
    """Another dataset this one can be read alongside.

    What a client needs to offer a related field is the name to prefix it with
    and the dataset to read that field's own description from — the hops in
    between are the server's business, and a client that knew them could write
    a join the server did not declare.
    """

    #: What a column of it is prefixed with: ``assignee.display_name``.
    name: str
    #: The dataset it arrives at, whose fields describe what may be named.
    dataset: str


class DefaultFilter(SanitizedBaseModel):
    """One condition a new statement about this dataset starts with.

    Shaped as the builder's own condition so a client seeds its filter rows
    with it rather than translating: what comes back is an ordinary filter,
    shown like every other and removed the same way.
    """

    field: str
    op: FilterOp
    value: Any = None


class GroupingDescription(SanitizedBaseModel):
    """A field a list of the dataset can be grouped by."""

    name: str
    kind: str
    #: Whether it groups by a bucket of the calendar, which the grouping names.
    bucket: bool = False


class FieldCatalogResponse(SanitizedBaseModel):
    """Every field a dataset offers, in the order a client lists them."""

    dataset: str
    fields: list[FieldDescription]
    #: What else it can be read alongside. A client offering a related field
    #: reads that dataset's own description for what may be named.
    relations: list[RelationDescription] = []
    #: What a new statement leaves out until its author says otherwise —
    #: archived rows and templates. A starting point rather than a rule: the
    #: conditions arrive as ordinary filter rows, and deleting one asks the
    #: question it was keeping out. The trash is NOT here; the query surface
    #: removes it in the database, and nothing can ask for it back.
    default_filters: list[DefaultFilter] = []
    #: The fields a list of it can be grouped by, beside the custom
    #: properties that group (``property:<id>``).
    groupings: list[GroupingDescription] = []
