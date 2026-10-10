"""What an item leaves behind when it is shared, and how its dates travel."""

from app.core.tools import Tool
from app.services.marketplace.publish_profile import (
    DATE_ANCHOR,
    anchor_dates,
    shift_dates,
    strip_for_listing,
)
from app.services.marketplace.tool_listings import normalize_tool_listing


def _editor(*children: dict) -> dict:
    return {
        "root": {
            "type": "root",
            "children": [{"type": "paragraph", "children": list(children)}],
        }
    }


def _project(**task_overrides) -> dict:
    task = {
        "title": "Kick-off",
        "description": "Ask @alice#1234 about #task[Budget](task:41)",
        "status_name": "To Do",
        "start_date": "2026-03-10T09:00:00+00:00",
        "due_date": "2026-03-12T17:00:00+00:00",
        "external_ref": "task:1",
        "tags": [],
        "assignee_handles": ["alice#1234"],
        "mention_handles": ["alice#1234"],
        "checklist": [],
        "property_values": [
            {
                "property_name": "Owner",
                "property_type": "user_reference",
                "value_handle": "alice#1234",
            },
            {
                "property_name": "Review",
                "property_type": "date",
                "value_text": "2026-03-11",
            },
        ],
        "links": [
            {"type": "depends_on", "target_external_ref": "task:2"},
            {"type": "depends_on", "target_external_ref": "task:999"},
        ],
        "comments": [
            {"author_handle": "alice#1234", "author_name": "Alice", "body": "hi"}
        ],
        "created_at": "2026-02-01T00:00:00+00:00",
        "archived_at": "2026-04-01T00:00:00+00:00",
        **task_overrides,
    }
    second = {
        "title": "Wrap-up",
        "status_name": "To Do",
        "external_ref": "task:2",
        "due_date": "2026-03-20T17:00:00+00:00",
        "tags": [],
        "assignee_handles": [],
        "checklist": [],
        "property_values": [],
    }
    return {
        "type": "initiative-project",
        "schema_version": 1,
        "app_version": "0.70.0",
        "exported_at": "2026-03-01T00:00:00+00:00",
        "exported_by_handle": "alice#1234",
        "project": {
            "name": "Launch",
            "description": "Plan with @bob#9",
            "archived_at": None,
        },
        "tags": [],
        "task_statuses": [{"name": "To Do", "category": "todo", "is_default": True}],
        "property_definitions": [],
        "tasks": [task, second],
    }


class TestNobodyIsCarried:
    def test_a_project_names_nobody(self):
        stripped = strip_for_listing(Tool.project, _project())
        task = stripped["tasks"][0]
        assert stripped["exported_by_handle"] is None
        assert task["assignee_handles"] == []
        assert task["comments"] == []
        assert task["mention_handles"] == []
        assert [value["property_name"] for value in task["property_values"]] == [
            "Review"
        ]

    def test_a_mention_keeps_its_words_but_names_no_account(self):
        task = strip_for_listing(Tool.project, _project())["tasks"][0]
        assert task["description"] == "Ask @alice about Budget"

    def test_a_body_mention_and_reference_become_text_and_uploads_go(self):
        file = {
            "type": "initiative-file",
            "file_type": "native",
            "name": "Notes",
            "mention_handles": ["alice#1234"],
            "content": _editor(
                {
                    "type": "mention",
                    "mentionName": "Alice",
                    "mentionHandle": "alice#1234",
                    "text": "@Alice",
                },
                {
                    "type": "entity-mention",
                    "entityId": 0,
                    "text": "Budget",
                    "importSourceRef": "task:41",
                },
                {"type": "image", "src": "/uploads/3/abc.png"},
            ),
        }
        file["content"]["root"]["children"].append(
            {
                "type": "reference-embed",
                "entityType": "task",
                "entityId": 41,
                "text": "Budget",
            }
        )
        stripped = strip_for_listing(Tool.file, file)
        paragraph, embed = stripped["content"]["root"]["children"]
        assert [node["type"] for node in paragraph["children"]] == ["text", "text"]
        assert [node["text"] for node in paragraph["children"]] == ["@Alice", "Budget"]
        assert embed["type"] == "paragraph"
        assert [node["text"] for node in embed["children"]] == ["Budget"]
        assert stripped["mention_handles"] == []

    def test_a_calendar_invites_nobody(self):
        calendar = {
            "type": "initiative-calendar",
            "name": "Rota",
            "events": [
                {
                    "title": "Shift",
                    "start_at": "2026-03-10T09:00:00+00:00",
                    "end_at": "2026-03-10T17:00:00+00:00",
                    "attendees": [{"handle": "alice#1234"}],
                }
            ],
        }
        assert (
            strip_for_listing(Tool.calendar, calendar)["events"][0]["attendees"] == []
        )

    def test_the_argument_is_left_alone(self):
        original = _project()
        strip_for_listing(Tool.project, original)
        assert original["tasks"][0]["assignee_handles"] == ["alice#1234"]


class TestLinks:
    def test_a_link_inside_the_item_survives_and_one_out_of_it_does_not(self):
        task = strip_for_listing(Tool.project, _project())["tasks"][0]
        assert task["links"] == [
            {"type": "depends_on", "target_external_ref": "task:2"}
        ]


class TestDates:
    def test_the_earliest_date_lands_on_the_anchor(self):
        anchored = anchor_dates(
            Tool.project, strip_for_listing(Tool.project, _project())
        )
        task = anchored["tasks"][0]
        # The earliest planning date was 2026-03-10; everything kept its distance.
        assert task["start_date"].startswith(DATE_ANCHOR.isoformat())
        assert task["due_date"].startswith("2000-01-05")
        assert task["property_values"][0]["value_text"] == "2000-01-04"
        assert anchored["tasks"][1]["due_date"].startswith("2000-01-13")

    def test_when_it_happened_is_not_carried(self):
        task = strip_for_listing(Tool.project, _project())["tasks"][0]
        assert task["created_at"] is None
        assert task["archived_at"] is None

    def test_shifting_moves_every_date_by_the_same_days(self):
        anchored = anchor_dates(Tool.project, _project())
        shifted = shift_dates(Tool.project, anchored, 7)
        assert shifted["tasks"][0]["start_date"].startswith("2000-01-10")
        assert shifted["tasks"][0]["property_values"][1]["value_text"] == "2000-01-11"

    def test_a_calendar_travels_the_same_way(self):
        calendar = {
            "type": "initiative-calendar",
            "name": "Rota",
            "events": [
                {
                    "title": "A",
                    "start_at": "2026-05-04T09:00:00+00:00",
                    "end_at": "2026-05-04T10:00:00+00:00",
                },
                {
                    "title": "B",
                    "start_at": "2026-05-06T09:00:00+00:00",
                    "end_at": "2026-05-06T10:00:00+00:00",
                },
            ],
        }
        anchored = anchor_dates(Tool.calendar, calendar)
        assert anchored["events"][0]["start_at"].startswith("2000-01-03")
        assert anchored["events"][1]["start_at"].startswith("2000-01-05")

    def test_a_repeat_keeps_its_weekday_and_its_edited_occurrence(self):
        """Mondays from 3 January moved five days: Mondays from the 10th, and
        the second Monday's edit, an hour later, on the new second Monday."""
        calendar = {
            "type": "initiative-calendar",
            "name": "Rota",
            "events": [
                {
                    "title": "Standup",
                    "start_at": "2000-01-03T09:00:00+00:00",
                    "end_at": "2000-01-03T09:15:00+00:00",
                    "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO",
                    "external_ref": "event:1",
                },
                {
                    "title": "Standup",
                    "start_at": "2000-01-10T10:00:00+00:00",
                    "end_at": "2000-01-10T10:15:00+00:00",
                    "series_ref": "event:1",
                    "original_start": "2000-01-10T09:00:00+00:00",
                },
                {
                    "title": "Retro",
                    "start_at": "2000-01-04T15:00:00+00:00",
                    "end_at": "2000-01-04T16:00:00+00:00",
                },
            ],
        }
        series, edit, once = shift_dates(Tool.calendar, calendar, 5)["events"]
        assert series["start_at"].startswith("2000-01-10T09:00")
        assert series["end_at"].startswith("2000-01-10T09:15")
        assert edit["original_start"].startswith("2000-01-17T09:00")
        assert edit["start_at"].startswith("2000-01-17T10:00")
        assert once["start_at"].startswith("2000-01-09T15:00")

    def test_an_item_with_no_dates_is_unchanged(self):
        counters = {"type": "initiative-counter-group", "name": "HP", "counters": []}
        assert anchor_dates(Tool.counter_group, counters) == counters


class TestEveryListingIsStripped:
    def test_a_listing_from_any_source_names_nobody(self):
        # Ingestion applies the profile, so a file that carried people — an
        # upload, a registry manifest — is stored without them.
        stored = normalize_tool_listing(Tool.project, _project())
        assert stored["tasks"][0]["assignee_handles"] == []
        assert stored["exported_by_handle"] is None

    def test_the_stored_form_is_a_fixed_point(self):
        once = normalize_tool_listing(Tool.project, _project())
        assert normalize_tool_listing(Tool.project, once) == once


class TestPictures:
    DIGEST = "a" * 64

    def test_a_picture_the_catalogue_keeps_stays(self):
        from app.services.marketplace.media import media_path

        kept = media_path(self.DIGEST)
        post = {
            "type": "initiative-post",
            "name": "News",
            "body": _editor(
                {"type": "image", "src": kept},
                {"type": "image", "src": "/uploads/3/elsewhere.png"},
            ),
        }
        paragraph = strip_for_listing(Tool.post, post)["body"]["root"]["children"][0]
        assert paragraph["children"] == [{"type": "image", "src": kept}]

    def test_a_gallery_keeps_only_what_travelled(self):
        from app.services.marketplace.media import media_path

        kept = media_path(self.DIGEST)
        gallery = {
            "type": "initiative-gallery",
            "name": "Moodboard",
            "cover": "abc.png",
            "images": [{"storage_key": kept}, {"storage_key": "abc.png"}],
        }
        stripped = strip_for_listing(Tool.gallery, gallery)
        assert stripped["images"] == [{"storage_key": kept}]
        assert stripped["cover"] is None
