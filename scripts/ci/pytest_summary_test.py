"""Tests for pytest_summary.py. Run: python3 scripts/ci/pytest_summary_test.py"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest_summary

LOG = """\
[gw1] [ 10%] PASSED app/a_test.py::test_ok
[gw2] [ 20%] \x1b[31mFAILED\x1b[0m app/b_test.py::test_one
[gw2] [ 30%] FAILED app/b_test.py::test_two
[gw2] [ 40%] ERROR app/c_test.py::test_three
============================= slowest 3 durations ==============================
2.50s call     app/a_test.py::test_ok
0.40s setup    app/b_test.py::test_one
9.10s call     alembic/migrations_test.py::test_round_trip
=========================== short test summary info ============================
FAILED app/b_test.py::test_one - asyncpg.exceptions.DeadlockDetectedError: deadlock detected
FAILED app/b_test.py::test_two - AssertionError: assert None
ERROR app/c_test.py::test_three
============ 9637 passed, 265 skipped, 2 failed, 1 error in 2659.65s (0:44:19) ============
"""


class SummaryTest(unittest.TestCase):
    def test_reads_the_result_failures_and_durations(self):
        run = pytest_summary.parse(LOG)
        self.assertEqual(
            run.result,
            "9637 passed, 265 skipped, 2 failed, 1 error in 2659.65s (0:44:19)",
        )
        self.assertEqual(run.workers, {"gw2": 3})
        self.assertEqual(
            run.failures,
            {
                "app/b_test.py::test_one": "asyncpg.exceptions.DeadlockDetectedError: deadlock detected",
                "app/b_test.py::test_two": "AssertionError: assert None",
                "app/c_test.py::test_three": "error",
            },
        )
        self.assertEqual(len(run.slowest), 3)

    def test_names_one_worker_holding_every_failure(self):
        text = pytest_summary.render(pytest_summary.parse(LOG))
        self.assertIn("All 3 failures are on gw2", text)
        # Slowest first.
        self.assertLess(text.index("migrations_test"), text.index("a_test.py::test_ok"))

    def test_a_reason_cannot_become_html(self):
        text = pytest_summary.render(
            pytest_summary.parse("FAILED app/x_test.py::test - <class 'X'>: boom\n")
        )
        self.assertIn("&lt;class 'X'>: boom", text)

    def test_a_clean_run_has_no_failure_sections(self):
        text = pytest_summary.render(
            pytest_summary.parse("==== 12 passed in 3.00s ====\n")
        )
        self.assertIn("12 passed in 3.00s", text)
        self.assertNotIn("Failures", text)

    def test_each_log_gets_its_own_heading(self):
        text = pytest_summary.render(
            pytest_summary.parse("==== 3 passed in 1.00s ====\n"),
            "Request-context seam",
        )
        self.assertTrue(text.startswith("### Request-context seam"))

    def test_a_missing_log_prints_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pytest_summary.main(["x", f"{tmp}/none.log"]), 0)


if __name__ == "__main__":
    unittest.main()
