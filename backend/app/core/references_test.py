"""Reading a reference back.

``format_ref`` writes ``task:12``; this is the half that reads one. Every
trigger stores that shape, so one parser owning it is what keeps `#`, `[[ ]]`
and a smart chip agreeing about what a string names.
"""

from __future__ import annotations

import pytest

from app.core.references import (
    MAX_ENTITY_ID,
    format_ref,
    kind_for_trigger,
    parse_ref,
)
from app.core.search import SearchEntityType


def test_a_reference_reads_back_as_what_was_written():
    for entity_type in SearchEntityType:
        if entity_type is SearchEntityType.comment:
            continue
        assert parse_ref(format_ref(entity_type, 12)) == (entity_type, 12)
    assert parse_ref(f"task:{MAX_ENTITY_ID}") == (SearchEntityType.task, MAX_ENTITY_ID)


@pytest.mark.parametrize(
    "ref",
    [
        # A comment is a remark ON something, so the vocabulary has none.
        "comment:3",
        # A kind this build does not know.
        "sandwich:3",
        # Not a reference at all.
        "",
        "task",
        "task:",
        ":12",
        "task:abc",
        "task:-1",
        "12:task",
        # An id is read strictly, in plain ASCII digits.
        "task:²",
        "task:१२",
        "task:1½",
        "task: 12",
        "task:1_2",
        # Past what an id column holds.
        f"task:{MAX_ENTITY_ID + 1}",
        "task:" + "9" * 40,
        # An aspect is the smart-chip shape, not the bare form.
        "task:12:status",
        "counter.tsjvtcm0s7gv2x:12:value",
        # Not a kind a plug-in could have.
        "counter.TSJVTCM0S7GV2X:1",
        "Counter.abc:1",
        "1counter.abc:1",
        "counter.:1",
        ".abc:1",
        "counter.a.b:1",
        "counter.a_b:1",
        "counter-group.abc:1",
    ],
)
def test_what_is_not_a_reference_names_nothing(ref):
    assert parse_ref(ref) is None


def test_a_tool_plugins_kind_reads_back_as_written():
    """A tool plug-in's kind is its key, ``.`` and its plug-in's uid in lower
    case. Whether the community has it is asked where it is resolved."""
    for kind in ("counter.tsjvtcm0s7gv2x", "counter_group.tsjvtcm0s7gv2x"):
        assert parse_ref(format_ref(kind, 12)) == (kind, 12)


def test_the_word_after_a_hash_is_the_kind_kebabed():
    """``#counter-group.tsjvtcm0s7gv2x`` names ``counter_group.tsjvtcm0s7gv2x``:
    a key holds no ``-`` and a uid neither ``-`` nor ``_``."""
    assert kind_for_trigger("counter-group.tsjvtcm0s7gv2x") == (
        "counter_group.tsjvtcm0s7gv2x"
    )
    assert kind_for_trigger("calendar-event") is SearchEntityType.calendar_event
    assert kind_for_trigger("counter-group") is None
    assert kind_for_trigger("wiki-page") is SearchEntityType.wiki_page
