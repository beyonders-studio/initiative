"""What a reader sends the query surface, and what comes back.

Rows are positional against ``columns`` rather than keyed by name, because a
query may name two columns the same thing — ``SELECT t.id, p.id`` is legal and
gives both the name ``id``. A mapping would keep one of the two.
"""

from typing import Any, List, Literal, Optional, Union

from pydantic import Field

from app.schemas.base import SanitizedBaseModel
from app.schemas.field_catalog import FieldDescription
from app.schemas.query import FilterOp
from app.services.fields.spec import FieldType


class QueryRequest(SanitizedBaseModel):
    """One statement to read."""

    #: The statement. Bounded so that reading it is bounded: everything this
    #: surface accepts fits comfortably, and a payload past it is not a query
    #: anybody wrote by hand.
    sql: str = Field(min_length=1, max_length=20_000)
    #: Which initiative the answer is about. A statement names datasets, not a
    #: scope, so a surface that belongs to one initiative says so and the rows
    #: come back narrowed to it. Omitted means the whole guild the reader
    #: reaches.
    initiative_id: Optional[int] = Field(default=None, gt=0)


class QueryColumnDescription(SanitizedBaseModel):
    """One output column, as the database describes it before running."""

    name: str
    #: The same vocabulary the field registry uses, so a client reading a
    #: query's shape and a client reading a dataset's fields read one thing.
    type: FieldType
    #: For a date rounded with ``date_trunc``, the unit it is rounded to —
    #: ``day``, ``week``, ``month``, ``quarter`` or ``year``. A chart labels
    #: its points by this rather than by guessing from the dates.
    grain: Optional[str] = None
    #: A SQL DATE is a calendar label, encoded at UTC midnight rather than a
    #: timestamp to convert into the viewer's timezone.
    date_only: bool = False


class QuerySheetDescription(SanitizedBaseModel):
    """A range a statement reads with ``sheet()``, as the file holds it now."""

    #: The name the statement reads it under.
    alias: str
    #: The workbook's visible sheets, for picking one.
    sheets: List[str]
    #: Its columns, described as a dataset's fields are.
    fields: List[FieldDescription]


class QueryShapeResponse(SanitizedBaseModel):
    """What a statement would return, without returning it."""

    columns: List[QueryColumnDescription]
    #: The datasets the statement reads.
    relations: List[str]
    #: The ranges of spreadsheets it reads.
    sheets: List[QuerySheetDescription] = []


class QueryResponse(SanitizedBaseModel):
    """What the statement returned."""

    #: The output columns, in order, named and typed. Names are not necessarily
    #: distinct; the statement is prepared to run either way, so saying what it
    #: returns costs nothing extra here.
    columns: List[QueryColumnDescription]
    #: One list per row, positional against ``columns``.
    rows: List[List[Any]]
    #: Whether there were more rows than one query returns.
    truncated: bool
    #: The datasets the statement read.
    relations: List[str]


class QueryColumnSpec(SanitizedBaseModel):
    """One thing a built query returns."""

    field: str = Field(min_length=1, max_length=100)
    #: Reduce the column across the group rather than returning it as it is.
    aggregate: Optional[str] = Field(default=None, max_length=20)
    #: Round a date down before grouping by it.
    bucket: Optional[str] = Field(default=None, max_length=20)
    alias: Optional[str] = Field(default=None, max_length=100)
    #: Add a count or a total up along the grouping: a running total.
    running: bool = False


class QueryConditionSpec(SanitizedBaseModel):
    """One comparison, in the vocabulary the filter DSL already uses."""

    field: str = Field(min_length=1, max_length=100)
    op: FilterOp = FilterOp.eq
    value: Any = None
    #: The same comparison, answered the other way.
    negate: bool = False


class QueryFilterGroupSpec(SanitizedBaseModel):
    """Comparisons held together by one word.

    ``conditions`` is required rather than defaulted, so a comparison cannot
    read as an empty group: the two shapes are told apart by which key they
    carry.
    """

    logic: Literal["and", "or"] = "and"
    conditions: List["QueryFilterNode"] = Field(max_length=20)


#: One line of a filter: a comparison, or a bracket around more of them. The
#: group comes first so a bracket is read as one.
QueryFilterNode = Union[QueryFilterGroupSpec, QueryConditionSpec]

QueryFilterGroupSpec.model_rebuild()


class QuerySortSpec(SanitizedBaseModel):
    field: str = Field(min_length=1, max_length=100)
    descending: bool = False


class QuerySheetSpec(SanitizedBaseModel):
    """A range of a spreadsheet a built query reads."""

    #: The spreadsheet's id.
    file: int = Field(gt=0)
    #: The range in A1 notation, its sheet before the last ``!``. Omitted
    #: reads the first visible sheet's filled area.
    range: Optional[str] = Field(default=None, min_length=1, max_length=200)


class QueryBuildRequest(SanitizedBaseModel):
    """What somebody clicked, before it is a statement.

    The builder describes; the server writes the SQL. A statement built by
    clicking is therefore always one this surface will run, because it is built
    in the parse tree rather than assembled as text. It reads one dataset or
    one range of a spreadsheet.
    """

    dataset: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sheet: Optional[QuerySheetSpec] = None
    columns: List[QueryColumnSpec] = Field(min_length=1, max_length=20)
    where: List[QueryFilterNode] = Field(default_factory=list, max_length=20)
    # As many as there are columns: what a statement is grouped by is drawn
    # from what it shows.
    group_by: List[str] = Field(default_factory=list, max_length=20)
    order_by: Optional[QuerySortSpec] = None
    limit: Optional[int] = Field(default=None, gt=0, le=10_000)
    #: Which initiative the answer is about. A statement names datasets, not a
    #: scope, so a surface that belongs to one initiative says so and the rows
    #: come back narrowed to it. Omitted means the whole guild the reader
    #: reaches.
    initiative_id: Optional[int] = Field(default=None, gt=0)


class QueryVocabulary(SanitizedBaseModel):
    """The words a statement may contain, beside the fields of a dataset.

    A statement is checked against an allow-list, so what may be written is a
    closed set and a client that has to help somebody write one needs to know
    it. Served rather than restated on the client, so the surface cannot offer
    a name the validator would refuse — nor stop offering one it accepts.
    """

    #: The relations a statement may name. The registry's own datasets.
    datasets: List[str]
    #: The functions it may call, spelled as they are written.
    functions: List[str]
    #: The names that are not columns and are resolved from the request rather
    #: than from the statement. ``me`` is the reader, so a saved statement that
    #: uses it answers per person without holding anybody's id.
    tokens: List[str] = []


class QueryBuildResponse(SanitizedBaseModel):
    """The statement, and what it would return."""

    sql: str
    columns: List[QueryColumnDescription]
    relations: List[str]
    #: The range it reads, when it reads one.
    sheets: List[QuerySheetDescription] = []
