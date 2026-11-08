"""An editor state written as a comment's text."""

from __future__ import annotations

from app.services.import_engine.comment_markdown import comment_markdown


def doc(*blocks):
    return {"root": {"type": "root", "children": list(blocks)}}


def paragraph(*children):
    return {"type": "paragraph", "children": list(children)}


def text(value, fmt=0):
    return {"type": "text", "text": value, "format": fmt}


def test_people_and_things_are_written_the_way_a_comment_names_them():
    body = comment_markdown(
        doc(
            paragraph(
                {"type": "mention", "mentionName": "Sam Bee", "mentionUserId": 42},
                text(" and "),
                {
                    "type": "mention",
                    "mentionName": "Nobody Here",
                    "mentionUserId": None,
                },
                text(" see "),
                {
                    "type": "entity-mention",
                    "entityType": "wiki_page",
                    "entityId": 9,
                    "text": "The [Guide]",
                },
                text(" "),
                {"type": "smart-chip", "entityId": 9},
                {
                    "type": "entity-mention",
                    "entityType": "task",
                    "entityId": 0,
                    "text": "SCRUM-1",
                },
            )
        )
    )
    assert body == ("@[](42) and @Nobody Here see #wiki_page[The Guide](9) SCRUM-1")


def test_structure_reads_as_markdown_and_a_picture_keeps_its_address():
    body = comment_markdown(
        doc(
            paragraph(text("bold", fmt=1), text(" words")),
            {
                "type": "list",
                "listType": "bullet",
                "children": [{"type": "listitem", "children": [text("one")]}],
            },
            {"type": "image", "src": "/uploads/5/abc.png", "altText": "chart"},
        )
    )
    assert body == "**bold** words\n\n- one\n\n![chart](</uploads/5/abc.png>)"


def test_nothing_in_it_is_nothing():
    assert comment_markdown(doc()) == ""
    assert comment_markdown("nonsense") == ""
