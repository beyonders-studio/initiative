"""The ready-made shapes a new collection can start as: which of its lists it
shows and opens on, the fields it brings, and what its cards and its table
show of each file.

"Add to new collection" offers these, grouped, beside starting blank (a
collection shows its grid and table, as shipped, and has no fields) or copying
the shape of another collection in the initiative. Each is a suggestion:
everything about the collection can be changed afterwards. Its words (name,
hint, field names) are in the backend ``files`` catalogue under
``collections.shapes``, because they are chrome until the collection is made,
and then written in the language of whoever made it. So is the currency a
money field starts in, which follows the maker's language too.

Unlike a task type's, a shape's fields are the collection's own
(``property_definitions.collection_id``), not properties of the initiative, so
two collections never share a field by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union

#: How a list shows a rating.
RatingDisplay = Literal["number", "stars", "bar"]

#: The groups shapes are offered in, in order.
SHAPE_GROUPS: tuple[str, ...] = ("starters",)


@dataclass(frozen=True)
class ShapeField:
    """A field a shape brings: one of the collection's own."""

    #: Its name's key (``collections.shapes.fields.<key>``).
    key: str
    #: A ``PropertyType`` value.
    type: str
    #: For a rating, how the shape's lists show it.
    display: Optional[RatingDisplay] = None


#: What a card or a table column shows: a file's own field, by the id a
#: layout names it by (``FileFieldId``), or one of the shape's fields.
ShownField = Union[str, ShapeField]


@dataclass(frozen=True)
class CollectionShape:
    #: Its key, and its words' (``collections.shapes.shapes.<key>``).
    key: str
    group: str
    #: The lists it shows, in the order they are offered; it opens on the first.
    lists: tuple[str, ...]
    fields: tuple[ShapeField, ...] = ()
    #: What a card shows under the picture, in its masonry, grid and timeline.
    card: tuple[ShownField, ...] = ()
    #: Its table's columns.
    columns: tuple[ShownField, ...] = ()


_CAPTION = ShapeField("caption", "text")
_PRICE = ShapeField("price", "currency")
_RATING = ShapeField("rating", "rating", display="stars")
_DATE = ShapeField("date", "date")

#: Every ready-made shape, in the order a group lists them.
SHAPES: tuple[CollectionShape, ...] = (
    CollectionShape(
        "gallery",
        "starters",
        lists=("masonry", "grid", "timeline"),
        fields=(_CAPTION,),
        card=("name", _CAPTION),
        columns=("name", _CAPTION, "added"),
    ),
    CollectionShape(
        "catalog",
        "starters",
        lists=("grid", "table"),
        fields=(_PRICE, _RATING),
        card=("name", _PRICE, _RATING),
        columns=("name", _PRICE, _RATING, "added"),
    ),
    CollectionShape(
        "log",
        "starters",
        lists=("timeline", "table"),
        fields=(_DATE,),
        card=("name", _DATE),
        columns=("name", _DATE, "added"),
    ),
)

SHAPES_BY_KEY: dict[str, CollectionShape] = {shape.key: shape for shape in SHAPES}
