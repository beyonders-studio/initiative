"""The wiki importer's placing of what a page names."""

from __future__ import annotations

from app.services.import_engine.importers.wiki import WikiImporter, _place_references


def _doc(*inline):
    return {
        "root": {
            "type": "root",
            "children": [{"type": "paragraph", "children": list(inline)}],
        }
    }


def _page_mention(slug, text="Target"):
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": "wiki_page",
        "entityId": 0,
        "text": text,
        "importSlug": slug,
    }


def _person(name, user_id=None):
    return {
        "type": "mention",
        "version": 1,
        "mentionName": name,
        "mentionUserId": user_id,
        "text": name,
    }


def test_a_page_mention_points_at_the_page_its_slug_became():
    placed = _place_references(
        _doc(_page_mention("guide")), page_ids={"guide": 12}, mentioned={}
    )
    assert placed is not None
    (node,) = placed["root"]["children"][0]["children"]
    assert node["entityId"] == 12 and "importSlug" not in node


def test_a_mention_of_a_page_that_did_not_arrive_is_its_words_again():
    placed = _place_references(
        _doc(_page_mention("gone", "The old page")), page_ids={}, mentioned={}
    )
    assert placed is not None
    (node,) = placed["root"]["children"][0]["children"]
    assert node["type"] == "text" and node["text"] == "The old page"


def test_a_person_placed_by_the_people_step_is_linked_and_nobody_else_is():
    placed = _place_references(
        _doc(_person("Sam Bee"), _person("Nobody"), _person("Already", 3)),
        page_ids={},
        mentioned={"Sam Bee": 7, "Already": 9},
    )
    assert placed is not None
    sam, nobody, already = placed["root"]["children"][0]["children"]
    assert sam["mentionUserId"] == 7
    assert nobody["mentionUserId"] is None
    # A mention that already names an account is somebody else's to change.
    assert already["mentionUserId"] == 3


def test_content_with_nothing_to_place_is_left_as_it_was():
    assert (
        _place_references(
            _doc({"type": "text", "text": "x"}), page_ids={}, mentioned={}
        )
        is None
    )
    assert _place_references("not a file", page_ids={}, mentioned={}) is None


def test_the_people_a_wiki_names_are_asked_about_most_named_first():
    importer = WikiImporter()
    envelope = importer.validate(
        {
            "type": "initiative-wiki",
            "name": "Docs",
            "pages": [
                {
                    "title": "A",
                    "slug": "a",
                    "author_handle": "Robin",
                    "author_name": "Robin Ade",
                    "mention_handles": ["Sam"],
                },
                {
                    "title": "B",
                    "slug": "b",
                    "author_handle": "robin",
                    "mention_handles": [],
                },
                {"title": "C", "slug": "c"},
            ],
        }
    )
    people = importer.people(envelope)
    assert [(p.handle, p.name) for p in people] == [
        ("Robin", "Robin Ade"),
        ("Sam", None),
    ]


def _jira_mention(key):
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": "task",
        "entityId": 0,
        "text": key,
        "importJiraKey": key,
        "importUrl": f"https://acme.atlassian.net/browse/{key}",
    }


def _jira_chip(key):
    return {
        "type": "smart-chip",
        "version": 1,
        "chipKind": "task:status",
        "entityId": 0,
        "text": key,
        "importJiraKey": key,
    }


def _jira_link(key, words):
    return {
        "type": "link",
        "url": f"https://acme.atlassian.net/browse/{key}",
        "children": [{"type": "text", "text": words}],
        "importJiraKey": key,
    }


def test_a_jira_issue_that_came_over_is_its_task_and_its_live_status():
    placed = _place_references(
        _doc(
            _jira_mention("SCRUM-1"),
            _jira_chip("SCRUM-1"),
            _jira_link("SCRUM-1", "see it"),
        ),
        page_ids={},
        mentioned={},
        jira_tasks={"SCRUM-1": 41},
    )
    assert placed is not None
    mention, chip, link = placed["root"]["children"][0]["children"]
    assert mention == {
        "type": "entity-mention",
        "version": 1,
        "entityType": "task",
        "entityId": 41,
        "text": "SCRUM-1",
    }
    assert chip["entityId"] == 41 and "importJiraKey" not in chip
    assert link == {
        "type": "entity-mention",
        "version": 1,
        "entityType": "task",
        "entityId": 41,
        "text": "see it",
    }


def test_a_jira_issue_that_did_not_come_over_links_back_to_jira():
    placed = _place_references(
        _doc(
            _jira_mention("SCRUM-9"),
            _jira_chip("SCRUM-9"),
            _jira_link("SCRUM-9", "see it"),
        ),
        page_ids={},
        mentioned={},
        jira_tasks={},
    )
    assert placed is not None
    link, kept = placed["root"]["children"][0]["children"]
    # The mention is a link to the issue again, and the chip — with nothing to
    # read — is gone.
    assert link["type"] == "link"
    assert link["url"] == "https://acme.atlassian.net/browse/SCRUM-9"
    assert link["children"][0]["text"] == "SCRUM-9"
    assert kept["type"] == "link" and "importJiraKey" not in kept


def _file_mention(ref, text="spec.pdf"):
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": "file",
        "entityId": 0,
        "text": text,
        "importRef": ref,
    }


def test_a_file_the_page_links_to_is_the_file_it_became():
    placed = _place_references(
        _doc(_file_mention("entry:assets/a.pdf"), _file_mention("entry:assets/b.pdf")),
        page_ids={},
        mentioned={},
        file_ids={"entry:assets/a.pdf": 31},
    )
    assert placed is not None
    found, missing = placed["root"]["children"][0]["children"]
    assert found["entityId"] == 31 and "importRef" not in found
    # One that did not arrive is its name again.
    assert missing["type"] == "text" and missing["text"] == "spec.pdf"
