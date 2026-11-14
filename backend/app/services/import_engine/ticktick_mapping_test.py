"""TickTick's CSV backup as this app's project envelope.

As with every mapper here, the last test is the load-bearing one: the result
has to validate as a real ``ProjectExportEnvelope``, because the apply path
knows nothing about TickTick.
"""

import pytest

from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.import_engine import ticktick_mapping as tm

PREAMBLE = (
    "Date: 2026-03-09+0000\nVersion: 7.1\nStatus: 0 Normal 1 Completed 2 Archived\n\n"
)
HEADER = (
    '"Folder Name","List Name","Title","Tags","Content","Is Check list",'
    '"Start Date","Due Date","Reminder","Repeat","Priority","Status",'
    '"Created Time","Completed Time","Order","Timezone","Is All Day",'
    '"Is Floating","Column Name","Column Order","View Mode","taskId","parentId"\n'
)


def _row(**over):
    values = {
        "Folder Name": "",
        "List Name": "Work",
        "Title": "A task",
        "Tags": "",
        "Content": "",
        "Is Check list": "N",
        "Start Date": "",
        "Due Date": "",
        "Reminder": "",
        "Repeat": "",
        "Priority": "0",
        "Status": "0",
        "Created Time": "",
        "Completed Time": "",
        "Order": "0",
        "Timezone": "UTC",
        "Is All Day": "false",
        "Is Floating": "false",
        "Column Name": "",
        "Column Order": "0",
        "View Mode": "list",
        "taskId": "",
        "parentId": "",
    }
    values.update(over)
    order = [h.strip('"') for h in HEADER.strip().split(",")]
    return ",".join(f'"{values[key]}"' for key in order) + "\n"


def _csv(*rows: str) -> str:
    return PREAMBLE + HEADER + "".join(rows)


def _build(content, selection="Work"):
    return tm.build_project_envelope(content, selection=selection, app_version="1.2.3")


# --- finding the real header ----------------------------------------------


_WEEKLY = "RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"


@pytest.mark.parametrize(
    ("repeat", "status", "fields"),
    [
        (
            _WEEKLY,
            "0",
            {
                "recurrence": _WEEKLY,
                "recurrence_shift": 1440,
                "recurrence_strategy": "fixed",
            },
        ),
        ("RRULE:FREQ=DAILY;TT_SKIP=HOLIDAY", "0", {}),
        ("RRULE:FREQ=HOURLY;INTERVAL=4", "0", {}),
        (_WEEKLY, "2", {}),
    ],
    ids=[
        "picked in the task's zone",
        "a rule a task cannot repeat by",
        "a fixed hourly rule is kept as a one-off",
        "a finished task holds no repeat",
    ],
)
def test_a_repeat_is_read_in_the_tasks_zone(repeat, status, fields):
    """Mondays at midnight in Berlin are Sundays in UTC, which the shift
    keeps; a rule with TickTick's own parts, or a finished task, leaves the
    task a one-off."""
    row = _row(
        Status=status,
        Repeat=repeat,
        Timezone="Europe/Berlin",
        **{"Due Date": "2026-03-08T23:00:00+0000"},
    )
    task = _build(_csv(row)).envelope["tasks"][0]
    assert {key: task[key] for key in fields} == fields
    assert ("recurrence" in task) == bool(fields)


def test_the_preamble_is_skipped_however_long_it_is():
    content = "one\ntwo\nthree\nfour\nfive\nsix\nseven\n" + HEADER + _row()
    assert [o.name for o in tm.preview(content)] == ["Work"]


def test_a_file_that_is_not_a_ticktick_backup_yields_nothing():
    assert tm.preview("just,some,columns\n1,2,3\n") == []


# --- which list -----------------------------------------------------------


def test_preview_lists_each_list_largest_first():
    content = _csv(
        _row(**{"List Name": "Work", "Title": "a"}),
        _row(**{"List Name": "Home", "Title": "b"}),
        _row(**{"List Name": "Work", "Title": "c"}),
    )
    options = tm.preview(content)
    assert [(o.name, o.task_count) for o in options] == [("Work", 2), ("Home", 1)]


def test_a_list_is_qualified_by_its_folder():
    """Two lists can share a name in different folders; merging them would be
    an import nobody asked for."""
    content = _csv(
        _row(**{"Folder Name": "Personal", "List Name": "Notes", "Title": "a"}),
        _row(**{"Folder Name": "Team", "List Name": "Notes", "Title": "b"}),
    )
    assert sorted(o.key for o in tm.preview(content)) == [
        "Personal / Notes",
        "Team / Notes",
    ]
    mapped = _build(content, selection="Team / Notes")
    assert mapped.envelope["project"]["name"] == "Notes"
    assert [t["title"] for t in mapped.envelope["tasks"]] == ["b"]


def test_subtasks_are_not_counted_as_tasks():
    content = _csv(
        _row(taskId="1", Title="Parent"),
        _row(taskId="2", Title="Child", parentId="1"),
    )
    assert tm.preview(content)[0].task_count == 1


# --- the fields the old importer dropped -----------------------------------


def test_tags_come_across():
    mapped = _build(_csv(_row(Tags="urgent, backend, Urgent")))
    assert mapped.envelope["tasks"][0]["tags"] == [
        {"name": "urgent", "color": "#6366F1"},
        {"name": "backend", "color": "#6366F1"},
    ]
    assert [t["name"] for t in mapped.envelope["tags"]] == ["urgent", "backend"]


def test_the_four_date_columns_come_across():
    mapped = _build(
        _csv(
            _row(
                **{
                    "Due Date": "2026-03-09T15:02:00+0000",
                    "Start Date": "2026-03-01T09:00:00+0000",
                    "Created Time": "2026-02-01T08:00:00+0000",
                    "Completed Time": "2026-03-10T11:00:00+0000",
                }
            )
        )
    )
    task = mapped.envelope["tasks"][0]
    assert task["due_date"].startswith("2026-03-09")
    assert task["start_date"].startswith("2026-03-01")
    assert task["created_at"].startswith("2026-02-01")
    assert task["completed_at"].startswith("2026-03-10")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", TaskPriority.low),
        ("1", TaskPriority.low),
        ("3", TaskPriority.medium),
        ("5", TaskPriority.high),
        ("", TaskPriority.low),
    ],
)
def test_priority_skips_values(raw, expected):
    mapped = _build(_csv(_row(Priority=raw)))
    assert mapped.envelope["tasks"][0]["priority"] == expected.value


def test_columns_become_statuses():
    mapped = _build(
        _csv(
            _row(Title="a", **{"Column Name": "Backlog"}),
            _row(Title="b", **{"Column Name": "Done"}),
        )
    )
    statuses = mapped.envelope["task_statuses"]
    assert [s["name"] for s in statuses] == ["Backlog", "Done"]
    assert statuses[0]["category"] == TaskStatusCategory.backlog.value
    assert statuses[1]["category"] == TaskStatusCategory.done.value


def test_a_task_with_no_column_still_lands_somewhere():
    mapped = _build(_csv(_row()))
    assert mapped.envelope["tasks"][0]["status_name"] == tm.NO_COLUMN


def test_a_subtask_becomes_its_parents_checklist_line():
    mapped = _build(
        _csv(
            _row(taskId="1", Title="Parent"),
            _row(taskId="2", Title="Step", parentId="1", Status="2"),
        )
    )
    (task,) = mapped.envelope["tasks"]
    assert task["checklist"] == [{"text": "Step", "done": True}]


def test_a_subtask_whose_parent_is_in_another_list_is_counted_not_lost():
    mapped = _build(
        _csv(
            _row(taskId="1", Title="Here"),
            _row(taskId="2", Title="Stray", parentId="elsewhere"),
        )
    )
    assert mapped.skipped_rows == 1


def test_the_task_id_becomes_an_external_ref():
    mapped = _build(_csv(_row(taskId="abc123")))
    assert mapped.envelope["tasks"][0]["external_ref"] == "ticktick:abc123"


# --- the one that matters --------------------------------------------------


def test_the_envelope_validates_as_a_real_project_export():
    mapped = _build(
        _csv(
            _row(
                taskId="1",
                Title="Ship it",
                Content="Some detail",
                Tags="release",
                Priority="5",
                Status="0",
                **{
                    "Column Name": "In Progress",
                    "Due Date": "2026-03-09T15:02:00+0000",
                },
            ),
            _row(taskId="2", Title="A step", parentId="1", Status="1"),
        )
    )
    envelope = ProjectExportEnvelope.model_validate(mapped.envelope)
    assert envelope.project.name == "Work"
    (task,) = envelope.tasks
    assert task.title == "Ship it"
    assert task.priority == TaskPriority.high
    assert task.status_name == "In Progress"
    assert task.checklist[0].done is True
    assert task.tags[0].name == "release"
