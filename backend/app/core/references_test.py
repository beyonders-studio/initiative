"""Reading a reference back.

``format_ref`` writes ``task:12``; this is the half that reads one. Every
trigger stores that shape, so one parser owning it is what keeps `#`, `[[ ]]`
and a smart chip agreeing about what a string names.
"""

from __future__ import annotations

from app.core.references import (
    MAX_ENTITY_ID,
    format_ref,
    parse_ref,
)
from app.core.search import SearchEntityType


def test_a_reference_reads_back_as_what_was_written():
    for entity_type in SearchEntityType:
        if entity_type is SearchEntityType.comment:
            continue
        assert parse_ref(format_ref(entity_type, 12)) == (entity_type, 12)


def test_a_comment_is_not_something_a_reference_names():
    """A comment is a remark ON something — the thing it is on is what a reader
    wants — so the vocabulary does not admit one."""
    assert parse_ref("comment:3") is None


def test_a_kind_this_build_does_not_know_names_nothing():
    assert parse_ref("sandwich:3") is None


def test_a_string_that_is_not_a_reference_names_nothing():
    for ref in ("", "task", "task:", ":12", "task:abc", "task:-1", "12:task"):
        assert parse_ref(ref) is None, ref


def test_an_id_is_written_in_plain_digits():
    """A reference also arrives from a client, so the id is read strictly: a
    superscript and a Devanagari numeral both pass ``str.isdigit``, and the
    first is not a number ``int`` will read at all."""
    for ref in ("task:²", "task:१२", "task:1½", "task: 12", "task:1_2"):
        assert parse_ref(ref) is None, ref


def test_an_id_no_column_could_hold_names_nothing():
    """Past what an id column holds there is nothing to find, and nothing worth
    asking the database about."""
    assert parse_ref(f"task:{MAX_ENTITY_ID}") == (SearchEntityType.task, MAX_ENTITY_ID)
    assert parse_ref(f"task:{MAX_ENTITY_ID + 1}") is None
    assert parse_ref("task:" + "9" * 40) is None


def test_an_aspect_is_not_part_of_the_bare_form():
    """``task:12:status`` names a fact about a thing. That is the smart-chip
    shape, read by the parser that knows which facts exist."""
    assert parse_ref("task:12:status") is None
