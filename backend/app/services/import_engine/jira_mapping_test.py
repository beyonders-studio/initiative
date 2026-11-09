"""Jira's JSON as this app's project envelope.

The load-bearing test here is the last one: whatever the mapping produces has
to validate as a real ``ProjectExportEnvelope``, because the apply path is
the one that has existed for months and knows nothing about Jira. A mapping
that produces something almost-right would fail at apply time, inside a
worker, long after the person who started the import went away.
"""

import pytest

from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.services.import_engine import jira_mapping as jm


def _status(name, category_key, status_id=None):
    out = {"name": name, "statusCategory": {"key": category_key}}
    if status_id is not None:
        out["id"] = str(status_id)
    return out


def _issue(key, summary, *, status="To Do", **fields):
    return {
        "key": key,
        "fields": {"summary": summary, "status": {"name": status}, **fields},
    }


# --- priority --------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Highest", TaskPriority.urgent),
        ("High", TaskPriority.high),
        ("Medium", TaskPriority.medium),
        ("Low", TaskPriority.low),
        # Jira has five, we have four: the bottom two collapse.
        ("Lowest", TaskPriority.low),
        ("  hIgH  ", TaskPriority.high),
    ],
)
def test_priority_is_matched_by_name(name, expected):
    """By name, not id — ids are per-site, the five names are Jira's own."""
    assert jm.map_priority({"name": name}) is expected


@pytest.mark.parametrize("field", [None, {}, {"name": "Blocker"}, "High", 7])
def test_an_unreadable_priority_is_medium(field):
    assert jm.map_priority(field) is TaskPriority.medium


# --- statuses --------------------------------------------------------------


@pytest.mark.parametrize(
    "jira_status,expected",
    [
        (_status("To Do", "new"), TaskStatusCategory.todo),
        (_status("In Progress", "indeterminate"), TaskStatusCategory.in_progress),
        (_status("Done", "done"), TaskStatusCategory.done),
        # The one status name worth reading: we have a category for it and
        # Jira does not.
        (_status("Backlog", "new"), TaskStatusCategory.backlog),
        (_status("backlog", "new"), TaskStatusCategory.backlog),
        # A "Backlog" that Jira says is in flight is in flight.
        (_status("Backlog", "indeterminate"), TaskStatusCategory.in_progress),
    ],
)
def test_a_status_lands_by_jira_category(jira_status, expected):
    assert jm.map_status_category(jira_status) is expected


def test_statuses_are_the_union_over_issue_types():
    """Jira reports statuses per issue type, so the same one arrives twice."""
    statuses = jm.collect_statuses(
        [
            {
                "name": "Story",
                "statuses": [_status("To Do", "new"), _status("Done", "done")],
            },
            {
                "name": "Bug",
                "statuses": [_status("To Do", "new"), _status("Triage", "new")],
            },
        ]
    )
    assert [s["name"] for s in statuses] == ["To Do", "Done", "Triage"]


def test_the_board_decides_the_order_and_strays_follow():
    """The board is the order a team arranged; the workflow is the order Jira
    happens to list. A status the board does not show still has to exist, or
    the issues in it would have nowhere to land."""
    statuses = jm.collect_statuses(
        [
            {
                "statuses": [
                    _status("Done", "done"),
                    _status("To Do", "new"),
                    _status("In Progress", "indeterminate"),
                    _status("Archived", "done"),
                ]
            }
        ],
        board_column_order=["To Do", "In Progress", "Done"],
    )
    assert [s["name"] for s in statuses] == [
        "To Do",
        "In Progress",
        "Done",
        "Archived",
    ]
    assert [s["position"] for s in statuses] == [0, 1, 2, 3]


def test_the_default_is_the_first_not_started_column():
    statuses = jm.collect_statuses(
        [
            {
                "statuses": [
                    _status("In Progress", "indeterminate"),
                    _status("Backlog", "new"),
                    _status("Done", "done"),
                ]
            }
        ]
    )
    defaults = [s["name"] for s in statuses if s["is_default"]]
    assert defaults == ["Backlog"]


def test_a_workflow_with_nothing_unstarted_still_has_a_default():
    """Something has to be default, and the first column is the least
    surprising answer."""
    statuses = jm.collect_statuses(
        [
            {
                "statuses": [
                    _status("In Progress", "indeterminate"),
                    _status("Done", "done"),
                ]
            }
        ]
    )
    assert statuses[0]["is_default"] is True
    assert sum(s["is_default"] for s in statuses) == 1


def test_board_columns_flatten_to_their_status_ids():
    """A column can hold several statuses; the flattened sequence is the
    board's reading order."""
    configuration = {
        "columnConfig": {
            "columns": [
                {"name": "To Do", "statuses": [{"id": "1"}]},
                {"name": "Doing", "statuses": [{"id": "2"}, {"id": "3"}]},
            ]
        }
    }
    assert jm.board_column_statuses(configuration) == ["1", "2", "3"]


@pytest.mark.parametrize("bad", [None, {}, {"columnConfig": None}, "nope"])
def test_a_board_we_cannot_read_just_has_no_opinion(bad):
    assert jm.board_column_statuses(bad) == []


# --- issues ----------------------------------------------------------------


def _map(issue, **kw):
    """The task alone. ``map_issue`` also reports what the description lost,
    which only the fetch's plan cares about."""
    mapped = jm.map_issue(
        issue,
        position=kw.pop("position", 1000.0),
        status_names=kw.pop("status_names", {"To Do", "Done"}),
        default_status_name=kw.pop("default_status_name", "To Do"),
    )
    return None if mapped is None else mapped[0]


def test_an_issue_becomes_a_task():
    task = _map(
        _issue(
            "ACME-1",
            "Fit the door",
            status="Done",
            priority={"name": "High"},
            labels=["joinery", "urgent"],
            assignee={"displayName": "Alice Chen"},
            duedate="2026-03-04",
            created="2024-03-04T09:30:00.000+0000",
        )
    )
    assert task["title"] == "Fit the door"
    assert task["status_name"] == "Done"
    assert task["priority"] == "high"
    assert [t["name"] for t in task["tags"]] == ["joinery", "urgent"]
    assert task["assignee_handles"] == ["Alice Chen"]
    assert task["due_date"].startswith("2026-03-04")
    assert task["created_at"].startswith("2024-03-04")
    assert task["external_ref"] == "jira:ACME-1"


def test_an_issue_in_an_unknown_status_lands_in_the_default():
    """A workflow can change mid-fetch. Inventing a column would be worse."""
    task = _map(_issue("ACME-2", "Stray", status="Somewhere Else"))
    assert task["status_name"] == "To Do"


def test_a_description_becomes_markdown_and_gives_up_its_checkboxes():
    task = _map(
        _issue(
            "ACME-3",
            "With a body",
            description={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Do it"}],
                    },
                    {
                        "type": "taskList",
                        "content": [
                            {
                                "type": "taskItem",
                                "attrs": {"state": "DONE"},
                                "content": [{"type": "text", "text": "measured"}],
                            }
                        ],
                    },
                ],
            },
        )
    )
    assert task["description"] == "Do it"
    assert task["checklist"] == [{"text": "measured", "done": True}]


def test_labels_are_deduplicated_case_insensitively():
    task = _map(_issue("ACME-4", "Tagged", labels=["Bug", "bug", " ", "ui"]))
    assert [t["name"] for t in task["tags"]] == ["Bug", "ui"]


def test_an_assignee_travels_as_a_name_never_an_address():
    """Jira nulls emailAddress under the account's own privacy settings, and
    who somebody is here is the wizard's question anyway."""
    task = _map(
        _issue(
            "ACME-5",
            "Assigned",
            assignee={
                "displayName": "Alice Chen",
                "emailAddress": "alice@example.com",
            },
        )
    )
    assert task["assignee_handles"] == ["Alice Chen"]
    assert "alice@example.com" not in str(task)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "not an issue",
        {"key": "ACME-9"},
        {"key": "ACME-9", "fields": {"summary": "   "}},
        {"key": "ACME-9", "fields": "nope"},
    ],
)
def test_a_malformed_issue_is_skipped_not_fatal(bad):
    """The search API is somebody else's. One bad row must not take the
    fetch down with it."""
    assert _map(bad) is None


# --- the whole envelope ----------------------------------------------------


def _mapped(**kw):
    return jm.build_project_envelope(
        project=kw.pop("project", {"key": "ACME", "name": "Acme Board"}),
        issue_type_statuses=kw.pop(
            "issue_type_statuses",
            [{"statuses": [_status("To Do", "new"), _status("Done", "done")]}],
        ),
        issues=kw.pop("issues", [_issue("ACME-1", "One"), _issue("ACME-2", "Two")]),
        app_version="0.78.0-test",
        **kw,
    )


def _envelope(**kw):
    return _mapped(**kw).envelope


def test_rank_order_becomes_position_order():
    """Jira's rank is an opaque LexoRank string that means nothing here, so
    the sequence it arrives in is the thing that carries the order."""
    envelope = _envelope()
    positions = [t["position"] for t in envelope["tasks"]]
    assert positions == sorted(positions)
    assert positions[0] < positions[1]


def test_the_project_declares_every_tag_its_tasks_use():
    envelope = _envelope(
        issues=[
            _issue("ACME-1", "One", labels=["ui"]),
            _issue("ACME-2", "Two", labels=["ui", "api"]),
        ]
    )
    assert [t["name"] for t in envelope["tags"]] == ["ui", "api"]


def test_a_project_with_no_workflow_still_produces_something_applyable():
    """The importer refuses an envelope with no statuses, so the fetch must
    never produce one — even from a site that answers oddly."""
    envelope = _envelope(issue_type_statuses=[])
    assert len(envelope["task_statuses"]) == 1
    assert envelope["task_statuses"][0]["is_default"] is True


def test_malformed_issues_are_dropped_from_the_envelope():
    envelope = _envelope(issues=[_issue("ACME-1", "Good"), None, {"nope": True}])
    assert [t["title"] for t in envelope["tasks"]] == ["Good"]


def test_what_the_mapping_produces_is_a_real_envelope():
    """The one that matters. The apply path predates Jira by months and will
    not bend to it — whatever comes out of here has to validate as the same
    envelope a project export writes, or the import fails inside a worker
    long after anybody is watching.
    """
    from app.schemas.tenant.project_export import ProjectExportEnvelope

    envelope = _envelope(
        issues=[
            _issue(
                "ACME-1",
                "Fit the door",
                status="Done",
                priority={"name": "Highest"},
                labels=["joinery"],
                assignee={"displayName": "Alice Chen"},
                duedate="2026-03-04",
                created="2024-03-04T09:30:00.000+0000",
                updated="2024-05-01T12:00:00.000+0000",
                description={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Body"}],
                        }
                    ],
                },
            )
        ],
        board_column_order=["To Do", "Done"],
        site_url="https://acme.atlassian.net",
    )

    parsed = ProjectExportEnvelope.model_validate(envelope)
    assert parsed.project.name == "Acme Board"
    assert parsed.tasks[0].title == "Fit the door"
    assert parsed.tasks[0].priority is TaskPriority.urgent
    assert parsed.tasks[0].external_ref == "jira:ACME-1"
    assert parsed.task_statuses[0].name == "To Do"


# --- links and parents -------------------------------------------------------


def _blocks(*, inward=None, outward=None, link_id="10"):
    link = {
        "id": link_id,
        "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
    }
    if inward:
        link["inwardIssue"] = {"key": inward}
    if outward:
        link["outwardIssue"] = {"key": outward}
    return link


def _relates(*, inward=None, outward=None, link_id="20", name="Relates"):
    link = {
        "id": link_id,
        "type": {"name": name, "inward": "relates to", "outward": "relates to"},
    }
    if inward:
        link["inwardIssue"] = {"key": inward}
    if outward:
        link["outwardIssue"] = {"key": outward}
    return link


def test_the_blocked_issue_depends_on_its_blocker():
    """Jira shows a Blocks link on both issues. The blocked one — which sees
    its blocker as "is blocked by" — says it; the blocker says nothing, or
    the edge would be written twice."""
    blocked = _map(_issue("ACME-2", "Hang it", issuelinks=[_blocks(inward="ACME-1")]))
    blocker = _map(_issue("ACME-1", "Fit it", issuelinks=[_blocks(outward="ACME-2")]))
    assert blocked["links"] == [
        {"type": "depends_on", "target_external_ref": "jira:ACME-1"}
    ]
    assert blocker["links"] == []


def test_a_renamed_blocking_type_still_blocks():
    """A site can rename the type; the verb is what says it blocks."""
    link = _blocks(inward="ACME-1")
    link["type"]["name"] = "Prerequisite"
    task = _map(_issue("ACME-2", "Hang it", issuelinks=[link]))
    assert task["links"] == [
        {"type": "depends_on", "target_external_ref": "jira:ACME-1"}
    ]


@pytest.mark.parametrize("name", ["Relates", "Duplicate", "Cloners", "Causes"])
def test_every_other_link_is_related_and_said_once(name):
    """The finer words have no home here, so each is a plain relation — from
    the outward side only, since the inward side reports the same link."""
    outward_side = _map(
        _issue("ACME-1", "One", issuelinks=[_relates(outward="ACME-2", name=name)])
    )
    inward_side = _map(
        _issue("ACME-2", "Two", issuelinks=[_relates(inward="ACME-1", name=name)])
    )
    assert outward_side["links"] == [
        {"type": "related_to", "target_external_ref": "jira:ACME-2"}
    ]
    assert inward_side["links"] == []


def test_a_sub_task_or_story_is_part_of_its_parent():
    """A sub-task's parent and a story's epic arrive the same way: only the
    child names its parent."""
    task = _map(_issue("ACME-3", "A step", parent={"key": "ACME-1"}))
    assert task["links"] == [{"type": "part_of", "target_external_ref": "jira:ACME-1"}]


def test_the_same_link_twice_is_one_link():
    task = _map(
        _issue(
            "ACME-2",
            "Hang it",
            issuelinks=[
                _blocks(inward="ACME-1", link_id="10"),
                _blocks(inward="ACME-1", link_id="11"),
            ],
        )
    )
    assert len(task["links"]) == 1


@pytest.mark.parametrize(
    "bad",
    [None, "nope", [None], [{"type": None}], [{"type": {"name": "Blocks"}}]],
)
def test_links_that_name_nothing_are_ignored(bad):
    task = _map(_issue("ACME-2", "Hang it", issuelinks=bad, parent="ACME-1"))
    assert task["links"] == []


def test_link_ends_name_each_link_once_by_id():
    """For counting: both sides report a link, and the id is what makes them
    one. The parent is keyed by its child, since only the child names it."""
    issue = _issue(
        "ACME-2",
        "Hang it",
        parent={"key": "ACME-1"},
        issuelinks=[_blocks(inward="ACME-1", link_id="10"), _relates(outward="OPS-9")],
    )
    assert jm.link_far_ends(issue) == [
        ("parent:ACME-2", "ACME-1"),
        ("link:10", "ACME-1"),
        ("link:20", "OPS-9"),
    ]


def test_links_survive_into_a_real_envelope():
    """The link shape has to validate as the envelope's own, or the apply
    refuses the whole project."""
    from app.schemas.tenant.project_export import ProjectExportEnvelope

    envelope = _envelope(
        issues=[
            _issue("ACME-1", "Fit it"),
            _issue(
                "ACME-2",
                "Hang it",
                parent={"key": "ACME-1"},
                issuelinks=[_blocks(inward="ACME-1")],
            ),
        ]
    )
    parsed = ProjectExportEnvelope.model_validate(envelope)
    assert [
        (link.type.value, link.target_external_ref) for link in parsed.tasks[1].links
    ] == [
        ("part_of", "jira:ACME-1"),
        ("depends_on", "jira:ACME-1"),
    ]


# --- comments ------------------------------------------------------------------


def _adf_text(text):
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _jira_comment(author, text, created, **extra):
    return {
        "author": {"displayName": author, "emailAddress": "hidden@example.com"},
        "body": _adf_text(text),
        "created": created,
        **extra,
    }


def test_comments_arrive_oldest_first_with_their_author_and_date():
    mapped = jm.map_comments(
        {
            "comment": {
                "comments": [
                    _jira_comment("Sam", "Second", "2024-03-05T09:00:00.000+0000"),
                    _jira_comment("Robin", "First", "2024-03-04T09:00:00.000+0000"),
                ]
            }
        }
    )
    assert [c["body"] for c in mapped.comments] == ["First", "Second"]
    first = mapped.comments[0]
    assert first["author_handle"] == "Robin" and first["author_name"] == "Robin"
    assert first["created_at"].startswith("2024-03-04")
    # A display name, never an address.
    assert "hidden@example.com" not in str(mapped.comments)


def _mention(name, account="acc-1"):
    return {"type": "mention", "attrs": {"id": account, "text": f"@{name}"}}


def test_a_reply_names_the_comment_it_answers():
    """Jira's threaded replies carry ``parentId``; the reply arrives under
    its comment rather than beside it."""
    mapped = jm.map_comments(
        {
            "comment": {
                "comments": [
                    _jira_comment(
                        "Robin", "Question", "2024-03-04T09:00:00.000+0000", id="10"
                    ),
                    _jira_comment(
                        "Sam",
                        "Answer",
                        "2024-03-05T09:00:00.000+0000",
                        id="11",
                        parentId=10,
                    ),
                    _jira_comment(
                        "Sam", "Aside", "2024-03-06T09:00:00.000+0000", parentId="x"
                    ),
                ]
            }
        }
    )
    question, answer, aside = mapped.comments
    assert question["external_ref"] == "jira-comment:10"
    assert "reply_to_ref" not in question
    assert answer["reply_to_ref"] == "jira-comment:10"
    # An id that is not one is no thread.
    assert "external_ref" not in aside and "reply_to_ref" not in aside


def test_a_mention_is_rendered_as_the_name_and_listed():
    """Who a mention is here is the people step's answer, so the fetch
    writes the name and lists it for the apply to link."""
    body = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    _mention("Jordan Janzen"),
                    {"type": "text", "text": " thoughts? cc "},
                    _mention("Mel", "acc-2"),
                    {"type": "text", "text": " and "},
                    _mention("Jordan Janzen"),
                ],
            }
        ],
    }
    mapped = jm.map_comments(
        {
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Robin"},
                        "body": body,
                        "created": "2024-03-04T09:00:00.000+0000",
                    }
                ]
            }
        }
    )
    (comment,) = mapped.comments
    assert comment["body"] == "@Jordan Janzen thoughts? cc @Mel and @Jordan Janzen"
    assert comment["mention_handles"] == ["Jordan Janzen", "Mel"]

    issue = _issue(
        "ACME-1",
        "One",
        description={
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Ask "}, _mention("Mel")],
                }
            ],
        },
    )
    task = _map(issue)
    assert task["description"] == "Ask @Mel"
    assert task["mention_handles"] == ["Mel"]


def test_a_restricted_comment_stays_behind_and_is_counted():
    """Visible to one role at the source; bringing it over would show it to
    everybody in the initiative."""
    fields = {
        "comment": {
            "comments": [
                _jira_comment("Robin", "Open", "2024-03-04T09:00:00.000+0000"),
                _jira_comment(
                    "Sam",
                    "Admins only",
                    "2024-03-05T09:00:00.000+0000",
                    visibility={"type": "role", "value": "Administrators"},
                ),
            ]
        }
    }
    mapped = jm.map_comments(fields)
    assert [c["body"] for c in mapped.comments] == ["Open"]
    assert mapped.restricted == 1
    assert jm.restricted_comment_count(fields) == 1


def test_an_empty_comment_is_skipped_and_plain_text_is_kept():
    mapped = jm.map_comments(
        {
            "comment": {
                "comments": [
                    {"author": {"displayName": "A"}, "body": _adf_text("   ")},
                    {"author": {"displayName": "B"}, "body": "plain words"},
                    "nonsense",
                ]
            }
        }
    )
    assert [c["body"] for c in mapped.comments] == ["plain words"]


def test_comments_ride_on_the_task_only_when_asked_for():
    issue = _issue(
        "ACME-1",
        "One",
        comment={
            "comments": [_jira_comment("Robin", "Hi", "2024-03-04T09:00:00.000+0000")]
        },
    )
    assert _map(issue)["comments"] == []
    with_comments = jm.map_issue(
        issue,
        position=1.0,
        status_names={"To Do"},
        default_status_name="To Do",
        include_comments=True,
    )
    assert with_comments is not None
    assert [c["body"] for c in with_comments[0]["comments"]] == ["Hi"]


def test_comments_survive_into_a_real_envelope():
    from app.schemas.tenant.project_export import ProjectExportEnvelope

    envelope = jm.build_project_envelope(
        project={"key": "ACME", "name": "Acme"},
        issue_type_statuses=[{"statuses": [_status("To Do", "new")]}],
        issues=[
            _issue(
                "ACME-1",
                "One",
                comment={
                    "comments": [
                        _jira_comment("Robin", "Hi", "2024-03-04T09:00:00.000+0000")
                    ]
                },
            )
        ],
        app_version="0.78.0-test",
        include_comments=True,
    ).envelope
    parsed = ProjectExportEnvelope.model_validate(envelope)
    assert parsed.tasks[0].comments[0].author_handle == "Robin"


# --- images --------------------------------------------------------------------


def _media_doc(filename, text="See"):
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            {
                "type": "mediaSingle",
                "content": [
                    {
                        "type": "media",
                        "attrs": {"id": "media-uuid", "type": "file", "alt": filename},
                    }
                ],
            },
        ],
    }


def _stored(filename, key):
    from app.services.import_engine.jira_attachments import StoredImage

    return StoredImage(filename, key, "image/png", 0)


def test_an_embedded_image_renders_from_its_upload_where_it_sat():
    """Found by the filename Jira puts on the media node's alt — its id is a
    Media Services id with no way back to the attachment."""
    mapped = jm.map_issue(
        _issue("ACME-1", "One", description=_media_doc("door.png")),
        position=1.0,
        status_names={"To Do"},
        default_status_name="To Do",
        images=[_stored("door.png", "k1.png")],
        guild_id=5,
    )
    assert mapped is not None
    description = mapped[0]["description"]
    assert "![door.png](/uploads/5/k1.png)" in description
    # Placed where it was embedded, and not listed again at the foot.
    assert "Attachments" not in description


def test_an_image_nobody_embedded_is_listed_at_the_foot():
    mapped = jm.map_issue(
        _issue("ACME-1", "One", description=_adf_text("Body")),
        position=1.0,
        status_names={"To Do"},
        default_status_name="To Do",
        images=[_stored("hinge.png", "k2.png")],
        guild_id=5,
    )
    assert mapped is not None
    description = mapped[0]["description"]
    assert description.startswith("Body")
    assert description.endswith("![hinge.png](/uploads/5/k2.png)")


def test_an_image_embedded_in_a_comment_renders_there_too():
    mapped = jm.map_issue(
        _issue(
            "ACME-1",
            "One",
            comment={
                "comments": [
                    {
                        "author": {"displayName": "Robin"},
                        "body": _media_doc("proof.png", text="Done"),
                        "created": "2024-03-04T09:00:00.000+0000",
                    }
                ]
            },
        ),
        position=1.0,
        status_names={"To Do"},
        default_status_name="To Do",
        include_comments=True,
        images=[_stored("proof.png", "k3.png")],
        guild_id=5,
    )
    assert mapped is not None
    task = mapped[0]
    assert "![proof.png](/uploads/5/k3.png)" in task["comments"][0]["body"]
    # Embedded in a comment counts as placed: not repeated in the description.
    assert not task["description"]


def test_without_images_a_media_node_is_its_filename():
    task = _map(_issue("ACME-1", "One", description=_media_doc("door.png")))
    assert "door.png" in task["description"] and "/uploads/" not in task["description"]


def test_a_project_mapped_a_page_at_a_time_is_the_project_mapped_whole():
    """The fetch maps each page of issues as it arrives. The envelope has to
    come out the same as mapping every issue at once: positions keep
    counting across pages, and the property definitions still cover what any
    page filled in."""
    catalog = [
        {
            "id": "customfield_1",
            "name": "Team",
            "custom": True,
            "schema": {"type": "option", "custom": "select"},
        }
    ]
    issues = [
        _issue("ACME-1", "One", priority={"name": "High"}, labels=["ui"]),
        _issue("ACME-2", "Two", customfield_1={"value": "Core"}),
        {"key": "", "fields": "not an issue"},
        _issue("ACME-3", "Three", customfield_1={"value": "Web"}, labels=["api"]),
        _issue("ACME-4", "Four", priority={"name": "Lowest"}),
    ]
    files = {"ACME-3": [_stored("spec.pdf", "k-spec.pdf")]}
    shared = {
        "project": {"key": "ACME", "name": "Acme Board"},
        "issue_type_statuses": [
            {"statuses": [_status("To Do", "new"), _status("Done", "done")]}
        ],
        "app_version": "0.78.0-test",
        "field_catalog": catalog,
    }

    whole = jm.build_project_envelope(issues=issues, files_by_issue=files, **shared)
    mapper = jm.ProjectMapper(**shared)
    mapper.add(issues[:2])
    mapper.add(issues[2:4], files_by_issue=files)
    mapper.add(issues[4:])
    paged = mapper.finish()

    whole.envelope.pop("exported_at", None)
    paged.envelope.pop("exported_at", None)
    assert paged.envelope == whole.envelope
    assert (paged.skipped_rows, paged.properties) == (
        whole.skipped_rows,
        whole.properties,
    )
    assert "Team" in paged.properties


# --- issue types -------------------------------------------------------------


def test_each_issue_type_becomes_a_task_type_and_each_task_is_its_own():
    envelope = _envelope(
        issues=[
            _issue("ACME-1", "One", issuetype={"name": "Story"}),
            _issue("ACME-2", "Two", issuetype={"name": "Bug"}),
            _issue("ACME-3", "Three", issuetype={"name": "Task"}),
            _issue("ACME-4", "Four", issuetype={"name": "Bug"}),
        ]
    )
    assert [
        (t["name"], t["is_default"], t["layout_preset"], t["icon"])
        for t in envelope["task_types"]
    ] == [
        ("Story", False, "plain", "book-open"),
        ("Bug", False, "fix", "bug"),
        ("Task", True, "plain", "square-check"),
    ]
    assert [t["type_name"] for t in envelope["tasks"]] == [
        "Story",
        "Bug",
        "Task",
        "Bug",
    ]


def test_without_a_task_type_the_commonest_is_the_default():
    envelope = _envelope(
        issues=[
            _issue("ACME-1", "One", issuetype={"name": "Story"}),
            _issue("ACME-2", "Two", issuetype={"name": "Spike"}),
            _issue("ACME-3", "Three", issuetype={"name": "Story"}),
        ]
    )
    assert [(t["name"], t["is_default"]) for t in envelope["task_types"]] == [
        ("Story", True),
        ("Spike", False),
    ]


def test_more_issue_types_than_a_project_holds_keep_the_commonest_and_every_name():
    from app.core.task_types import MAX_TASK_TYPES

    rare = [f"Kind {n}" for n in range(MAX_TASK_TYPES)]
    mapped = _mapped(
        issues=[
            _issue("ACME-1", "One", issuetype={"name": "Bug"}),
            _issue("ACME-2", "Two", issuetype={"name": "Bug"}),
            *(
                _issue(f"ACME-{n + 3}", name, issuetype={"name": name})
                for n, name in enumerate(rare)
            ),
        ]
    )
    envelope = mapped.envelope

    names = [t["name"] for t in envelope["task_types"]]
    assert len(names) == MAX_TASK_TYPES
    assert names[0] == "Bug"
    # Every issue still says what it was, the left-out kinds included.
    [kept] = [d for d in envelope["property_definitions"] if d["name"] == "Issue type"]
    assert [o["value"] for o in kept["options"]] == ["Bug", *rare]
    values = {
        task["title"]: next(
            v["value_text"]
            for v in task["properties"]
            if v["property_name"] == "Issue type"
        )
        for task in envelope["tasks"]
    }
    assert values[rare[-1]] == rare[-1]
    # The review counts the tasks it fills, as any other property's.
    assert mapped.properties["Issue type"] == ("select", 2 + len(rare))


def test_issue_types_that_all_fit_need_no_property():
    envelope = _envelope(issues=[_issue("ACME-1", "One", issuetype={"name": "Bug"})])
    assert "Issue type" not in {d["name"] for d in envelope["property_definitions"]}


def test_issues_naming_no_type_leave_the_starting_types():
    assert "task_types" not in _envelope()
