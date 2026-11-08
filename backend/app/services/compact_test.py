"""The trimming the MCP server and the AI features share."""

from app.services.compact import trim


def test_trim_leaves_out_what_a_caller_never_acts_on():
    payload = {
        "title": "t",
        "due_date": None,
        "tags": [],
        "can": {},
        "archived": False,
        "comment_count": 0,
        "guild": {"id": 3, "name": "g", "avatar_base64": "AAAA"},
        "assignees": [
            {"id": 1, "avatar_url": "https://example.com/a.png", "avatar_base64": None},
        ],
        "count_base64_ish": "kept",  # only an exact suffix match is left out
        "color": "#2563eb",
        "icon": "circle",
        "position": 2.5,
    }
    trimmed = trim(payload)

    assert trimmed == {
        "title": "t",
        # A false and a zero are answers, not absences.
        "archived": False,
        "comment_count": 0,
        "guild": {"id": 3, "name": "g"},
        "assignees": [{"id": 1}],
        "count_base64_ish": "kept",
        # The write tools set these, so they are kept.
        "color": "#2563eb",
        "icon": "circle",
        "position": 2.5,
    }
    # Input is not mutated.
    assert payload["guild"]["avatar_base64"] == "AAAA"
    assert payload["due_date"] is None


def test_trim_shows_a_property_s_options_once_per_result():
    options = [{"value": "bug", "label": "Bug", "color": "#DB0000"}]
    row = {"property_id": 2, "type": "multi_select", "options": options}
    other = {"property_id": 5, "type": "select", "options": options}
    payload = {
        "items": [
            {"id": 1, "properties": [{**row, "value": ["bug"]}]},
            {"id": 2, "properties": [{**row, "value": []}, {**other, "value": "bug"}]},
        ]
    }
    first, second = trim(payload, frozenset({"value"}))["items"]

    assert first["properties"][0]["options"] == options
    # Seen already: the second row carries the value without the definition.
    assert "options" not in second["properties"][0]
    # A different property's options are its own, shown the first time.
    assert second["properties"][1]["options"] == options


def test_trim_keeps_another_community_s_options_under_the_same_id():
    # Property ids are numbered per community, and ``list_my_tasks`` lists
    # tasks from all of them: the same id can be two different properties.
    ours = [{"value": "bug", "label": "Bug"}]
    theirs = [{"value": "low", "label": "Low"}]
    payload = {
        "items": [
            {"community_id": 1, "properties": [{"property_id": 1, "options": ours}]},
            {"community_id": 2, "properties": [{"property_id": 1, "options": theirs}]},
            {"community_id": 2, "properties": [{"property_id": 1, "options": theirs}]},
        ]
    }
    first, second, third = trim(payload)["items"]

    assert first["properties"][0]["options"] == ours
    assert second["properties"][0]["options"] == theirs
    # Once both have been shown, a repeat of either carries the value alone.
    assert "options" not in third["properties"][0]


def test_trim_passes_free_form_fields_through_verbatim():
    content = {"type": "doc", "attrs": {"level": None}, "content": []}
    payload = {"id": 1, "content": content, "description": None}

    trimmed = trim(payload, frozenset({"content"}))

    # Inside a document a null can mean something, so it is left alone.
    assert trimmed == {"id": 1, "content": content}
