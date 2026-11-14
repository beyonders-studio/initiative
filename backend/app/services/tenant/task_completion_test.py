"""Unit tests for the completed_at rule.

The endpoint-level coverage — every path that can move a task across the done
boundary — lives in
``app/api/v1/tenant_endpoints/task_completion_test.py``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.models.tenant.task import Task, TaskStatusCategory
from app.services.tenant.task_completion import sync_completed_at

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=3)


def _task(**overrides: Any) -> Task:
    return Task(project_id=1, task_status_id=1, title="t", **overrides)


@pytest.mark.parametrize(
    ("case", "was", "category", "expected"),
    [
        ("entering done stamps it", None, TaskStatusCategory.done, NOW),
        # Moving between two done statuses is not a re-completion.
        ("staying done keeps the original", EARLIER, TaskStatusCategory.done, EARLIER),
        *(
            ("leaving done clears it", EARLIER, c, None)
            for c in (
                TaskStatusCategory.backlog,
                TaskStatusCategory.todo,
                TaskStatusCategory.in_progress,
            )
        ),
        ("staying incomplete is a no-op", None, TaskStatusCategory.todo, None),
        # A caller that cannot resolve a status (a bulk creator whose mapping
        # missed) must not leave a stale completion behind.
        ("an unresolved status counts as incomplete", EARLIER, None, None),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
def test_completed_at_follows_the_done_boundary(case: str, was, category, expected):
    task = _task(completed_at=was)

    sync_completed_at(task, category, now=NOW)

    assert task.completed_at == expected


def test_rule_is_idempotent():
    task = _task()

    sync_completed_at(task, TaskStatusCategory.done, now=NOW)
    sync_completed_at(task, TaskStatusCategory.done, now=NOW + timedelta(hours=1))

    assert task.completed_at == NOW
