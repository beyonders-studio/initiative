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

from app.db.guild_ddl import render_guild_rls_ddl
from app.db.initiative_rls import INITIATIVE_PATHS, parent_answers_for_reads

pytestmark = pytest.mark.always


_SELECT_POLICY = re.compile(
    r"^CREATE POLICY (\w+) ON (\w+) AS (PERMISSIVE|RESTRICTIVE) FOR SELECT$",
    re.MULTILINE,
)


def _permissive_select_policies() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, table, kind in _SELECT_POLICY.findall(render_guild_rls_ddl()):
        if kind == "PERMISSIVE":
            out.setdefault(table, []).append(name)
    return out


def _parents_walked_for_reads() -> set[str]:
    """Every table some child's read leg walks to."""
    walked: set[str] = set()
    for table, path in INITIATIVE_PATHS.items():
        read_leg = path.predicate(table, False)
        for candidate in INITIATIVE_PATHS:
            if candidate == table:
                continue
            if re.search(rf"\bFROM {candidate}\b", read_leg):
                walked.add(candidate)
    return walked


def test_every_parent_a_read_walks_to_gates_its_own_reads():
    """The assumption the shortcut rests on, stated as a test.

    One permissive ``SELECT`` policy per parent, and it is
    ``initiative_member_select`` — so "this row is visible to me" is the whole
    of what reaching it through a child can mean.
    """
    policies = _permissive_select_policies()
    walked = _parents_walked_for_reads()
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


def test_a_write_still_states_its_own_standing():
    """Only the read collapses. Changing a child asks for write on the parent,
    which being able to see it does not give."""
    tasks = INITIATIVE_PATHS["tasks"]
    assert "initiative_access" not in tasks.predicate("tasks", False)
    assert "initiative_access" in tasks.predicate("tasks", True)
