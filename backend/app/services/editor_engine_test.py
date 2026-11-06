"""The document editor on the server: a state read back is the document
written, and a room can hold it."""

import copy

import pytest
from pycrdt import Doc

from app.services import editor_engine
from app.services.editor_engine import EditorError

# The editor is built from frontend/, which test selection cannot see.
pytestmark = pytest.mark.always

_ELEMENT = {"direction": "ltr", "format": "", "indent": 0, "version": 1}


def _text(text: str, format: int = 0) -> dict:
    return {"type": "text", "text": text, "format": format, "version": 1}


def _paragraph(*children: dict) -> dict:
    return {"type": "paragraph", "children": list(children), **_ELEMENT}


def _document(*blocks: dict) -> dict:
    return {"root": {"type": "root", "children": list(blocks), **_ELEMENT}}


def _without_defaults(value):
    """A document as it reads, whichever way it spells a default."""
    if isinstance(value, dict):
        return {
            key: _without_defaults(item)
            for key, item in value.items()
            if item not in (0, "", None, False, "normal") or item is True
        }
    if isinstance(value, list):
        return [_without_defaults(item) for item in value]
    return value


DOCUMENT = _document(
    {"type": "heading", "tag": "h1", "children": [_text("Title")], **_ELEMENT},
    _paragraph(
        _text("Plain, "),
        _text("bold", 1),
        {
            "type": "link",
            "url": "https://example.com",
            "children": [_text("a link")],
            **_ELEMENT,
        },
    ),
    {
        "type": "list",
        "listType": "check",
        "start": 1,
        "tag": "ul",
        "children": [
            {
                "type": "listitem",
                "value": 1,
                "checked": True,
                "children": [_text("done")],
                **_ELEMENT,
            }
        ],
        **_ELEMENT,
    },
    {
        "type": "callout",
        "variant": "info",
        "collapsed": False,
        "children": [_paragraph(_text("Inside a callout"))],
        **_ELEMENT,
    },
    _paragraph({"type": "mention", "mentionUserId": 7, "version": 1}),
    {"type": "quote", "children": [_text("A quote")], **_ELEMENT},
    # Highlighted into tokens, as the browser stores it.
    {
        "type": "code",
        "language": "python",
        "children": [
            {**_text("print"), "type": "code-highlight", "highlightType": "keyword"},
            {**_text("("), "type": "code-highlight", "highlightType": "punctuation"},
            {**_text(")"), "type": "code-highlight", "highlightType": "punctuation"},
        ],
        **_ELEMENT,
    },
    {
        "type": "table",
        "children": [
            {
                "type": "tablerow",
                "children": [
                    {
                        "type": "tablecell",
                        "headerState": 1,
                        "colSpan": 1,
                        "rowSpan": 1,
                        "children": [_paragraph(_text("cell"))],
                        **_ELEMENT,
                    }
                ],
                **_ELEMENT,
            }
        ],
        **_ELEMENT,
    },
    {"type": "horizontalrule", "version": 1},
    _paragraph(
        {
            "type": "image",
            "src": "/uploads/picture.png",
            "altText": "a picture",
            "width": 0,
            "height": 0,
            "maxWidth": 500,
            "showCaption": True,
            "caption": {"editorState": _document(_paragraph(_text("A caption")))},
            "version": 1,
        },
        {"type": "excalidraw", "data": "[]", "width": 0, "version": 1},
    ),
    {"type": "youtube", "videoID": "dQw4w9WgXcQ", "format": "", "version": 1},
    {"type": "tweet", "id": "20", "format": "", "version": 1},
)


async def test_a_state_reads_back_as_the_document_it_was_made_from():
    state = await editor_engine.bootstrap(DOCUMENT)

    assert _without_defaults(await editor_engine.render(state)) == _without_defaults(
        DOCUMENT
    )


async def test_a_room_holds_the_state_as_the_browser_would_send_it():
    room = Doc()
    room.apply_update(await editor_engine.bootstrap(DOCUMENT))

    rendered = await editor_engine.render(bytes(room.get_update()))
    assert _without_defaults(rendered) == _without_defaults(DOCUMENT)


async def test_a_document_with_no_content_starts_with_an_empty_paragraph():
    rendered = await editor_engine.render(await editor_engine.bootstrap(None))

    assert [block["type"] for block in rendered["root"]["children"]] == ["paragraph"]
    assert rendered["root"]["children"][0]["children"] == []


async def test_legacy_nodes_come_back_as_the_browser_shows_them():
    hashtag = {**_text("#idea"), "type": "hashtag"}

    rendered = await editor_engine.render(
        await editor_engine.bootstrap(_document(_paragraph(_text("An "), hashtag)))
    )

    (paragraph,) = rendered["root"]["children"]
    assert [node["type"] for node in paragraph["children"]] == ["text"]
    assert paragraph["children"][0]["text"] == "An #idea"


def _merged(*updates: bytes) -> bytes:
    doc = Doc()
    for update in updates:
        doc.apply_update(update)
    return bytes(doc.get_update())


async def test_writing_what_a_state_already_reads_as_changes_nothing():
    state = await editor_engine.bootstrap(DOCUMENT)

    update = await editor_engine.apply(state, await editor_engine.render(state))

    assert update == bytes(Doc().get_update())


async def test_an_applied_edit_reads_back_as_written():
    state = await editor_engine.bootstrap(DOCUMENT)
    edited = await editor_engine.render(state)
    edited["root"]["children"][1] = _paragraph(_text("Rewritten"))

    update = await editor_engine.apply(state, edited)

    rendered = await editor_engine.render(_merged(state, update))
    assert _without_defaults(rendered) == _without_defaults(edited)


async def test_an_edited_caption_reads_back_as_written():
    """A caption is part of the image, not a document of its own: written into
    a state, it is there when the state is read."""
    state = await editor_engine.bootstrap(DOCUMENT)
    recaptioned = copy.deepcopy(DOCUMENT)
    image = recaptioned["root"]["children"][9]["children"][0]
    image["caption"] = {"editorState": _document(_paragraph(_text("Renamed")))}

    rendered = await editor_engine.render(
        _merged(state, await editor_engine.apply(state, recaptioned))
    )

    assert _without_defaults(rendered) == _without_defaults(recaptioned)


async def test_two_edits_to_one_paragraph_keep_each_others_words():
    """Each write changes only its own characters, so two made from the same
    state merge as two people typing would."""
    state = await editor_engine.bootstrap(_document(_paragraph(_text("hello world"))))

    async def written(words: str) -> bytes:
        return await editor_engine.apply(state, _document(_paragraph(_text(words))))

    merged = _merged(
        state, await written("hello brave world"), await written("hello world!")
    )

    rendered = await editor_engine.render(merged)
    (paragraph,) = rendered["root"]["children"]
    assert [node["text"] for node in paragraph["children"]] == ["hello brave world!"]


def _paragraphs(*words: str) -> dict:
    return _document(*(_paragraph(_text(w)) for w in words))


async def _words_of(state: bytes) -> list[str]:
    rendered = await editor_engine.render(state)
    return [
        "".join(node["text"] for node in block["children"])
        for block in rendered["root"]["children"]
    ]


async def test_blocks_written_before_the_first_keep_their_order():
    state = await editor_engine.bootstrap(_paragraphs("Z"))

    update = await editor_engine.apply(state, _paragraphs("A", "B", "Z"))

    assert await _words_of(_merged(state, update)) == ["A", "B", "Z"]


async def test_a_block_a_write_kept_takes_edits_made_to_it_elsewhere():
    """Removing B and adding D leaves C as it was, so an edit made to C from
    the same state still lands on C."""
    state = await editor_engine.bootstrap(_paragraphs("A", "B", "C"))

    rewritten = await editor_engine.apply(state, _paragraphs("A", "C", "D"))
    edited = await editor_engine.apply(state, _paragraphs("A", "B", "C!"))

    assert await _words_of(_merged(state, rewritten, edited)) == ["A", "C!", "D"]


async def test_a_long_document_keeps_its_blocks_when_one_is_added():
    """Past the size where moved blocks are searched for, the unchanged ends
    are still kept, so an edit made elsewhere to the first block lands."""
    words = [f"block {n}" for n in range(1200)]
    state = await editor_engine.bootstrap(_paragraphs(*words))

    appended = await editor_engine.apply(state, _paragraphs(*words, "the end"))
    edited = await editor_engine.apply(state, _paragraphs("block 0!", *words[1:]))

    merged = await _words_of(_merged(state, appended, edited))
    assert merged == ["block 0!", *words[1:], "the end"]


async def test_content_the_editor_refuses_is_an_error():
    # The error names what the editor refused, not something it lacked.
    with pytest.raises(EditorError, match="no-such-node"):
        await editor_engine.bootstrap(_document({"type": "no-such-node", "version": 1}))


async def test_an_edit_the_editor_refuses_is_an_error():
    state = await editor_engine.bootstrap(_paragraphs("A"))

    with pytest.raises(EditorError, match="no-such-node"):
        await editor_engine.apply(
            state, _document({"type": "no-such-node", "version": 1})
        )
