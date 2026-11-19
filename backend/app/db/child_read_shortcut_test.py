"""What a child table's read policy rests on.

A child's read leg is an ``EXISTS`` into its parent, and nothing more: the
inner scan runs the parent's own ``SELECT`` policy, which asks membership and
sharing already, so the child restating them would be the same answer a second
time. That shortcut is only sound while each parent a child walks to carries
**one** permissive ``SELECT`` policy and it is the one the registry renders.

These read the rendered DDL rather than a live catalog, because the render is
what provisioning applies and what a new community gets.
"""

from __future__ import annotations

import re

import pytest

from app.core.tool_set import BUILTIN_TOOLS, ToolSet
from app.db.guild_ddl import render_guild_rls_ddl
from app.db.initiative_rls import parent_answers_for_reads, paths_for
from app.db.plugin_tools import InstalledTool, community_tool_set
from app.services.marketplace.tool_plugins import normalize_tool_plugin_definition
from app.testing.tool_plugins import COUNTERS_UID, counters_tool_manifest

pytestmark = pytest.mark.always


def _with_counters() -> ToolSet:
    """The built-in tools and Counters as a tool plug-in, with an item under
    its item, so a two-hop item's read is walked too."""
    definition = normalize_tool_plugin_definition(counters_tool_manifest())
    definition["tool"]["items"].append(
        {"key": "tally", "name": {"en": "Tally"}, "parent": "counter", "fields": []}
    )
    keys = ["counter_group", "counter", "tally"]
    codes = {f"{key}.{COUNTERS_UID.lower()}": 1024 + i for i, key in enumerate(keys)}
    return community_tool_set([InstalledTool(COUNTERS_UID, definition)], codes)


_SETS = pytest.mark.parametrize(
    "tools", [BUILTIN_TOOLS, _with_counters()], ids=["built-in", "with-a-tool-plugin"]
)


_SELECT_POLICY = re.compile(
    r"^CREATE POLICY (\w+) ON (\w+) AS (PERMISSIVE|RESTRICTIVE) FOR SELECT$",
    re.MULTILINE,
)


def _permissive_select_policies(tools: ToolSet) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, table, kind in _SELECT_POLICY.findall(render_guild_rls_ddl(tools)):
        if kind == "PERMISSIVE":
            out.setdefault(table, []).append(name)
    return out


def _parents_walked_for_reads(tools: ToolSet) -> set[str]:
    """Every table some child's read leg walks to."""
    walked: set[str] = set()
    paths = paths_for(tools)
    for table, path in paths.items():
        read_leg = path.predicate(table, False)
        for candidate in paths:
            if candidate == table:
                continue
            if re.search(rf"\bFROM {candidate}\b", read_leg):
                walked.add(candidate)
    return walked


@_SETS
def test_every_parent_a_read_walks_to_gates_its_own_reads(tools: ToolSet):
    """The assumption the shortcut rests on, stated as a test, in a community
    with a tool plug-in too.

    One permissive ``SELECT`` policy per parent, and it is
    ``initiative_member_select`` — so "this row is visible to me" is the whole
    of what reaching it through a child can mean.
    """
    policies = _permissive_select_policies(tools)
    walked = _parents_walked_for_reads(tools)
    assert walked, "found no parents — the walk is looking at the wrong render"
    wrong = {
        parent: policies.get(parent, [])
        for parent in sorted(walked)
        if policies.get(parent) != ["initiative_member_select"]
    }
    assert wrong == {}, (
        "a child's read leg is an EXISTS into its parent and nothing more, "
        "which is only the same answer while the parent carries exactly one "
        "permissive SELECT policy: " + repr(wrong)
    )


def test_a_parent_that_gates_nothing_is_not_shortcut_through():
    """The structural initiative tables carry no membership policy, so a child
    of one keeps asking for itself."""
    assert not parent_answers_for_reads("initiatives")
    assert not parent_answers_for_reads("initiative_members")
    assert parent_answers_for_reads("projects")


@pytest.mark.parametrize(
    "table", ["tasks", "p_tsjvtcm0s7gv2x_counter", "p_tsjvtcm0s7gv2x_tally"]
)
def test_a_write_still_states_its_own_standing(table: str):
    """Only the read collapses, for a tool plug-in's items as for a task.
    Changing a child asks for write on the parent, which being able to see it
    does not give."""
    path = paths_for(_with_counters())[table]
    assert "initiative_access" not in path.predicate(table, False)
    assert "initiative_access" in path.predicate(table, True)
