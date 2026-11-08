"""Every repeat a task's title can say is one the server takes.

``frontend/src/lib/smartTitle.repeats.json`` lists the phrases and the RRULE the
title reader writes for each. The frontend's ``smartTitle.test.ts`` holds the
reader to that list; this holds every rule on it to what creating a task runs:
the task rule's validation, its strategy and due date together, and storing it
with the zone it was picked in.
"""

import json
import pathlib
from datetime import datetime, timezone

import pytest

from app.core import recurrence
from app.schemas.recurrence import validate_task_recurrence

pytestmark = pytest.mark.always

_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "smartTitle.repeats.json"
)
_CASES = [case for case in json.loads(_FIXTURE.read_text())["cases"] if case["rrule"]]

#: The end of Thursday 22 October 2026 in Los Angeles, already the 23rd in UTC:
#: the case where the days a rule was picked on and its UTC days differ.
_DUE = datetime(2026, 10, 23, 6, 59, tzinfo=timezone.utc)
_ZONE = "America/Los_Angeles"


def test_the_list_has_cases():
    assert len(_CASES) >= 20


@pytest.mark.parametrize("case", _CASES, ids=[case["text"] for case in _CASES])
def test_a_title_repeat_is_a_task_rule(case):
    rule = recurrence.normalize(case["rrule"], kind="task")
    # Normalizing what normalizing wrote changes nothing.
    assert recurrence.normalize(rule, kind="task") == rule
    validate_task_recurrence(rule=rule, strategy=case["strategy"], limit=None, due=_DUE)
    stored, shift = recurrence.stored(rule, _DUE, _ZONE, kind="task")
    assert stored == rule
    # The shift the title reader shows the rule with (``shiftFor``).
    hourly = recurrence.parse(rule).rule["FREQ"] == ["HOURLY"]
    assert shift == (-7 * 60 if hourly else -1440)


def test_an_hourly_title_repeat_is_counted_from_completion():
    hourly = [case for case in _CASES if "FREQ=HOURLY" in case["rrule"]]
    assert hourly
    for case in hourly:
        assert case["strategy"] == "rolling"
        with pytest.raises(ValueError):
            validate_task_recurrence(
                rule=case["rrule"], strategy="fixed", limit=None, due=_DUE
            )


def test_an_interval_from_completion_runs_from_the_day_it_was_done():
    """ "every! 2 weeks" is two weeks after each one is finished, whatever
    weekday that was: the rule carries no day of its own to fall back to."""
    (case,) = [case for case in _CASES if case["text"] == "Mow the lawn every! 2 weeks"]
    assert case["strategy"] == "rolling"
    finished = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)  # a Monday
    assert recurrence.next_start(case["rrule"], finished, 0, count=False) == datetime(
        2026, 11, 9, 17, 0, tzinfo=timezone.utc
    )
