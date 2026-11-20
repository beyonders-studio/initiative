"""The completed_at rule's one case no endpoint reaches.

Every path that moves a task across the done boundary is covered in
``app/api/v1/tenant_endpoints/task_completion_test.py``.
"""

from datetime import UTC, datetime

from app.models.tenant.task import Task
from app.services.tenant.task_completion import sync_completed_at


def test_an_unresolved_status_counts_as_incomplete():
    """A caller that cannot resolve a status (a bulk creator whose mapping
    missed) must not leave a stale completion behind."""
    task = Task(
        project_id=1,
        task_status_id=1,
        title="t",
        completed_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
    )

    sync_completed_at(task, None, now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC))

    assert task.completed_at is None
