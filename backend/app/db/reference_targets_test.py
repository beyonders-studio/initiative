"""What a reference resolves to, and that the registry saying so is not stale.

:data:`~app.db.reference_targets.VISUALS` names columns as strings, which is the
only way a table-keyed registry can name them — and a string survives a rename
that would have broken an attribute. These are the checks that fail instead of a
request failing at runtime.
"""

from sqlmodel import SQLModel

import app.db.base  # noqa: F401 — registers every model
from app.core.relationships import ENDPOINT_KINDS
from app.db.reference_targets import VISUALS, Visual, _column, _table_for
from app.db.search_index import SEARCH_SOURCES


def _tables():
    """Every table, keyed by bare name."""
    return {
        key.split(".")[-1]: table for key, table in SQLModel.metadata.tables.items()
    }


def _names_a_column(table, name: str) -> bool:
    """Whether ``name`` is a column of ``table``, or one through a pointer."""
    try:
        _column(table, name)
    except (KeyError, ValueError):
        return False
    return True


def test_every_visual_names_columns_that_exist():
    tables = _tables()
    for table_name, visual in VISUALS.items():
        assert table_name in tables, f"{table_name} is not a table"
        table = tables[table_name]
        named = [
            *visual.image,
            *(name for name in (visual.icon, visual.color) if name),
            *(
                name
                for name in (visual.file_type, visual.mime, visual.filename)
                if name
            ),
        ]
        if visual.link_in_json is not None:
            named.append(visual.link_in_json[0])
        missing = [name for name in named if not _names_a_column(table, name)]
        assert not missing, f"{table_name} has no column {missing}"


def test_a_kind_declares_at_most_one_look():
    """The card tries picture, emoji, colour in that order and draws the first,
    so a kind declaring two would silently never show the second."""
    for table_name, visual in VISUALS.items():
        looks = [
            bool(visual.image),
            bool(visual.icon),
            bool(visual.color),
        ]
        assert sum(looks) == 1, f"{table_name} declares more than one look"


def test_visuals_only_describe_kinds_an_edge_can_name():
    """A look nothing reads is a look nobody maintains."""
    linkable = {_table_for(kind) for kind in ENDPOINT_KINDS}
    assert set(VISUALS) <= linkable


def test_a_kind_with_no_entry_still_resolves_to_nothing():
    """`VISUALS.get` is what makes most kinds free, so the default has to be the
    empty one rather than a KeyError."""
    assert VISUALS.get("tasks", Visual()) == Visual()
    assert "tasks" in SEARCH_SOURCES
