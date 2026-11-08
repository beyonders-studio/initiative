"""Tests for monthly_report.py. Run: python3 scripts/ci/monthly_report_test.py"""

import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import monthly_report
from monthly_report import Release, Run

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


class ReleasesTest(unittest.TestCase):
    def test_a_patch_soon_after_or_a_regression_is_a_fix(self):
        releases = [
            Release("v0.71.0", at(0)),
            Release("v0.71.1", at(8)),  # the fix for 0.71.0
            Release("v0.72.0", at(100)),
            Release("v0.72.1", at(300)),  # outside the window: not a fix
            Release("v0.73.0", at(400)),  # another minor: not a patch of 0.72
        ]

        fixes = monthly_report.needed_a_fix(releases, regressions={"0.72.1"})

        self.assertEqual(
            fixes,
            {
                "v0.71.0": "v0.71.1 8 h later",
                "v0.72.1": "a regression was reported against it",
            },
        )


class MergeToGreenTest(unittest.TestCase):
    def test_a_push_waits_for_the_next_green_run(self):
        runs = [
            Run(at(0), at(0.5), "success"),
            Run(at(1), at(1.2), "cancelled"),  # replaced by the next push
            Run(at(1.1), at(1.6), "failure"),
            Run(at(2), at(2.5), "success"),
            Run(at(3), at(3.4), None),  # still running: no green after it yet
        ]

        waits = monthly_report.merge_to_green(runs, at(0), at(3))

        self.assertEqual(
            [wait.total_seconds() / 3600 for wait in waits],
            [0.5, 1.5, 1.4, 0.5],
        )


class MonthTest(unittest.TestCase):
    def test_a_month_is_read_a_week_at_a_time(self):
        start, end = monthly_report.month_bounds("2026-09")
        self.assertEqual(
            monthly_report.weeks(start, end),
            [
                "2026-09-01..2026-09-07",
                "2026-09-08..2026-09-14",
                "2026-09-15..2026-09-21",
                "2026-09-22..2026-09-28",
                "2026-09-29..2026-09-30",
            ],
        )

    def test_the_previous_month_and_its_bounds(self):
        self.assertEqual(monthly_report.previous_month(date(2026, 1, 1)), "2025-12")
        self.assertEqual(
            monthly_report.month_bounds("2026-12"),
            (
                datetime(2026, 12, 1, tzinfo=UTC),
                datetime(2027, 1, 1, tzinfo=UTC),
            ),
        )


def run(id_, event, branch, created, minutes, conclusion="success", attempt=1):
    started = T0 + timedelta(days=created)
    return {
        "id": id_,
        "run_number": id_,
        "html_url": f"https://example.test/runs/{id_}",
        "event": event,
        "head_branch": branch,
        "created_at": started.isoformat(),
        "run_started_at": started.isoformat(),
        "updated_at": (started + timedelta(minutes=minutes)).isoformat(),
        "conclusion": conclusion,
        "run_attempt": attempt,
    }


class ReportTest(unittest.TestCase):
    """The whole report, on API answers made up for September 2026."""

    ci_runs: ClassVar[list[dict]] = [
        run(1, "pull_request", "fix/x", 1, 30),
        run(2, "push", "dev", 2, 40),
        run(3, "push", "main", 3, 90),  # not dev's gate
        run(4, "pull_request", "fix/y", 4, 20, attempt=2),  # green on a re-run
        run(5, "push", "dev", 29.9, 40, conclusion="failure"),
        run(6, "push", "dev", 30.1, 40),  # October: what turns dev green
    ]

    def answer(self, path, params=None):
        if path.endswith("/releases"):
            return [
                {"tag_name": "v1.0.0", "published_at": "2026-09-10T00:00:00Z"},
                {"tag_name": "v1.0.1", "published_at": "2026-09-10T05:00:00Z"},
            ]
        if path.endswith("/issues"):
            return []
        if path.endswith("/attempts/1"):
            return {"conclusion": "failure"}
        if "release-candidate.yml" in path:
            raise monthly_report.urllib.error.HTTPError(path, 404, "", {}, None)
        if "ci.yml" in path:
            assert params is not None
            first, last = (date.fromisoformat(d) for d in params["created"].split(".."))
            return [
                r
                for r in self.ci_runs
                if first <= date.fromisoformat(r["created_at"][:10]) <= last
            ]
        return []

    def test_it_reads_each_gate_and_looks_past_the_month(self):
        with mock.patch.object(monthly_report, "get", self.answer):
            text = monthly_report.report("o/r", "2026-09")

        self.assertIn("2 shipped, 1 needed a fix (50%", text)
        self.assertIn("- v1.0.0: v1.0.1 5 h later", text)
        # Two pushes to dev in September; the late one waits into October.
        self.assertIn("over 2 pushes", text)
        self.assertIn("longest 5.5 h", text)
        self.assertIn("1 of 5 finished runs", text)
        self.assertIn("https://example.test/runs/4", text)
        self.assertIn("| Integration (dev) | 2 | 40 min | 40 min |", text)
        self.assertIn("| Pull request | 2 |", text)
        self.assertIn("| Release candidate | 0 |", text)


if __name__ == "__main__":
    unittest.main()
