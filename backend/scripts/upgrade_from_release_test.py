"""Holds upgrade_from_release.py's comparison to the communities it picks.

A community's schema carries the tables of the tool plug-ins it installed, so
each upgraded community is compared with the fresh community that installed the
same. These cases hold that choice to reporting every real difference.
Run, from ``backend/``: python scripts/upgrade_from_release_test.py
"""

from __future__ import annotations

import unittest

from upgrade_from_release import _divergence

SHARED = {"public": {}, "guild_template": {}, "roles": {}}
TASKS = {"relation tasks": "['r']", "column tasks.title": "['text']"}
NO_TOOLS = {**TASKS, "constraint comments.ck_comments_subject_type": "['task']"}
COUNTERS = {
    **TASKS,
    "relation p_tsjvtcm0s7gv2x_counter": "['r']",
    "relation p_tsjvtcm0s7gv2x_counter_id_seq": "['S']",
    "column p_tsjvtcm0s7gv2x_counter.step": "['numeric(20,10)']",
    "constraint comments.ck_comments_subject_type": "['task', 'counter']",
}


#: The fresh install: the Primary Community its first boot makes, which installs
#: nothing, and the seeded one, which installs Counters.
FRESH = {"guild_1": NO_TOOLS, "guild_2": COUNTERS}


def divergence(
    upgraded: dict[str, dict[str, str]], fresh: dict[str, dict[str, str]]
) -> list[str]:
    return _divergence({**SHARED, **upgraded}, {**SHARED, **fresh})


def report(upgraded: dict[str, dict[str, str]]) -> str:
    """What the check prints for ``upgraded`` against :data:`FRESH`."""
    return "\n".join(divergence(upgraded, FRESH))


class DivergenceTest(unittest.TestCase):
    def test_each_community_is_compared_with_one_of_its_tool_plug_ins(self) -> None:
        upgraded = {"guild_1": NO_TOOLS, "guild_2": COUNTERS, "guild_3": COUNTERS}
        self.assertEqual(divergence(upgraded, FRESH), [])

    def test_the_fresh_communities_order_does_not_matter(self) -> None:
        fresh = {"guild_1": COUNTERS, "guild_2": NO_TOOLS}
        upgraded = {"guild_1": NO_TOOLS, "guild_2": COUNTERS}
        self.assertEqual(divergence(upgraded, fresh), [])

    def test_a_changed_plug_in_column_is_reported(self) -> None:
        changed = {**COUNTERS, "column p_tsjvtcm0s7gv2x_counter.step": "['integer']"}
        self.assertEqual(
            report({"guild_2": changed}),
            (
                "guild_2: column p_tsjvtcm0s7gv2x_counter.step\n"
                "    upgraded: ['integer']\n"
                "    fresh: ['numeric(20,10)']"
            ),
        )

    def test_a_kind_check_without_the_plug_ins_kinds_is_reported(self) -> None:
        narrow = {
            **COUNTERS,
            "constraint comments.ck_comments_subject_type": "['task']",
        }
        self.assertEqual(
            report({"guild_2": narrow}),
            (
                "guild_2: constraint comments.ck_comments_subject_type\n"
                "    upgraded: ['task']\n"
                "    fresh: ['task', 'counter']"
            ),
        )

    def test_a_missing_plug_in_table_is_reported(self) -> None:
        partial = {
            key: value
            for key, value in COUNTERS.items()
            if key != "relation p_tsjvtcm0s7gv2x_counter_id_seq"
        }
        self.assertEqual(
            report({"guild_2": partial}),
            (
                "guild_2: upgraded lacks relation "
                "p_tsjvtcm0s7gv2x_counter_id_seq (fresh: ['S'])"
            ),
        )

    def test_a_plug_in_the_fresh_install_never_installed_is_reported(self) -> None:
        other = {
            **COUNTERS,
            "relation p_k3m9q2x7w1v4ab_board": "['r']",
            "column p_k3m9q2x7w1v4ab_board.title": "['text']",
        }
        self.assertEqual(
            report({"guild_2": other}),
            (
                "guild_2: fresh lacks column p_k3m9q2x7w1v4ab_board.title "
                "(upgraded: ['text'])\n"
                "guild_2: fresh lacks relation p_k3m9q2x7w1v4ab_board (upgraded: ['r'])"
            ),
        )

    def test_a_built_in_table_change_is_reported_beside_a_plug_in(self) -> None:
        changed = {**COUNTERS, "column tasks.title": "['varchar']"}
        self.assertEqual(
            report({"guild_2": changed}),
            (
                "guild_2: column tasks.title\n"
                "    upgraded: ['varchar']\n"
                "    fresh: ['text']"
            ),
        )


if __name__ == "__main__":
    unittest.main()
