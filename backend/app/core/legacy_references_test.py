"""Links written by older builds, rewritten as this one writes them."""

from __future__ import annotations

from app.core.legacy_references import rewrite_body, rewrite_text
from app.core.references import SOURCE_REF, text_node

#: Picture 12 became file 40; picture 13 had no file.
FILES = {12: 40}


def _mention(kind: str, entity_id: int, text: str = "x") -> dict:
    return {
        "type": "entity-mention",
        "entityType": kind,
        "entityId": entity_id,
        "text": text,
    }


def test_a_body_names_what_each_old_kind_became():
    body = {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        _mention("gallery_image", 12),
                        _mention("gallery_image", 13, "Lost"),
                        _mention("gallery", 3),
                        _mention("document", 5),
                        {
                            "type": "smart-chip",
                            "chipKind": "document:status",
                            "entityId": 6,
                        },
                        {
                            "type": "wikilink",
                            "documentId": 7,
                            "documentTitle": "Spec",
                            "text": "Spec",
                        },
                        {
                            "type": "wikilink",
                            "documentId": None,
                            "documentTitle": "Nowhere",
                        },
                        # From a backup: no id yet, the ref it had instead.
                        {
                            "type": "wikilink",
                            "documentId": None,
                            "documentTitle": "Plan",
                            SOURCE_REF: "document:8",
                        },
                    ],
                },
                {
                    "type": "reference-embed",
                    "entityType": "gallery_image",
                    "entityId": 13,
                    "text": "Lost",
                },
            ]
        }
    }

    inline, embed = rewrite_body(body, FILES)["root"]["children"]

    assert inline["children"] == [
        _mention("file", 40),
        text_node("Lost"),
        _mention("collection", 3),
        _mention("file", 5),
        {"type": "smart-chip", "chipKind": "file:status", "entityId": 6},
        {
            "type": "entity-mention",
            "version": 1,
            "entityType": "file",
            "entityId": 7,
            "text": "Spec",
        },
        text_node("Nowhere"),
        {
            "type": "entity-mention",
            "version": 1,
            "entityType": "file",
            "entityId": 0,
            "text": "Plan",
            SOURCE_REF: "file:8",
        },
    ]
    # A block of its own keeps a paragraph for its words.
    assert embed["type"] == "paragraph" and embed["children"] == [text_node("Lost")]


def test_running_text_names_what_each_old_kind_became():
    assert (
        rewrite_text(
            "#doc[Spec](5) #document[Plan](6) #gallery[Wall](3) #gallery-image[Sunset](12) "
            "#gallery_image[Lost](13) #task[Keep](9)",
            FILES,
        )
        == "#file[Spec](5) #file[Plan](6) #collection[Wall](3) #file[Sunset](40) Lost #task[Keep](9)"
    )
    # A backup's text names the ref it had.
    assert (
        rewrite_text(
            "#doc[Spec](document:5) #gallery-image[Lost](gallery_image:13)", {}
        )
        == "#file[Spec](file:5) Lost"
    )
