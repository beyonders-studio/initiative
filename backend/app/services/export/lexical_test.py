"""Unit tests for the Lexical editor-state converters."""

import io
import zipfile

from app.services.export.lexical import (
    blocks_from_editor_state,
    editor_markdown,
    render_docx,
    render_markdown,
)

GUILD = 7


def _text(text, fmt=0):
    return {"type": "text", "text": text, "format": fmt}


def _state(children):
    return {"root": {"type": "root", "children": children}}


FIXTURE = _state(
    [
        {"type": "heading", "tag": "h2", "children": [_text("Overview")]},
        {
            "type": "paragraph",
            "children": [
                _text("plain "),
                _text("bold", 1),
                _text(" italic", 2),
                _text(" code", 16),
                {
                    "type": "link",
                    "url": "https://example.com",
                    "children": [_text("a link")],
                },
                {"type": "mention", "text": "@alice", "mentionName": "alice"},
            ],
        },
        {"type": "quote", "children": [_text("wisdom")]},
        {
            "type": "code",
            "language": "python",
            "children": [_text("x = 1"), {"type": "linebreak"}, _text("y = 2")],
        },
        {
            "type": "list",
            "listType": "check",
            "children": [
                {"type": "listitem", "checked": True, "children": [_text("done")]},
                {
                    "type": "listitem",
                    "checked": False,
                    "children": [
                        _text("todo"),
                        {
                            "type": "list",
                            "listType": "bullet",
                            "children": [
                                {"type": "listitem", "children": [_text("nested")]}
                            ],
                        },
                    ],
                },
            ],
        },
        {"type": "image", "src": f"/uploads/{GUILD}/img-abc.png", "altText": "our pic"},
        {"type": "image", "src": "https://elsewhere.example/x.png", "altText": "ext"},
        {"type": "horizontalrule"},
        {"type": "youtube", "videoID": "dQw4w9WgXcQ"},
        {
            "type": "unknown-future-node",
            "children": [{"type": "paragraph", "children": [_text("still exported")]}],
        },
    ]
)


def test_parser_blocks_and_assets():
    blocks, assets = blocks_from_editor_state(FIXTURE, guild_id=GUILD)
    types = [b["type"] for b in blocks]
    assert types == [
        "heading",
        "paragraph",
        "quote",
        "code",
        "list",
        "image",
        "image",
        "hr",
        "paragraph",  # youtube degrades to a link paragraph
        "paragraph",  # unknown container's child
    ]
    # Same-guild upload collected as an asset; external stays a URL.
    assert assets == [{"key": "img-abc.png", "name": "img-abc.png"}]
    assert blocks[5]["asset"] == "img-abc.png"
    assert blocks[6]["asset"] is None
    assert blocks[6]["url"] == "https://elsewhere.example/x.png"
    # Format bitmask decoded; mention degraded to its text.
    para = blocks[1]["runs"]
    assert {"text": "bold", "bold": True} in para
    assert {"text": " code", "code": True} in para
    assert {"text": "a link", "link": "https://example.com"} in para
    assert {"text": "@alice"} in para
    # Code block joins its lines.
    assert blocks[3]["text"] == "x = 1\ny = 2"
    # Checklist with nesting.
    items = blocks[4]["items"]
    assert items[0]["checked"] is True
    assert items[1]["children"][0]["items"][0]["runs"] == [{"text": "nested"}]


def test_markdown_zips_when_assets_present():
    blocks, assets = blocks_from_editor_state(FIXTURE, guild_id=GUILD)
    data = {"title": "Notes", "stem": "notes", "blocks": blocks, "assets": assets}
    content, content_type, filename = render_markdown(
        data, lambda key: b"png-bytes-" + key.encode()
    )
    assert content_type == "application/zip"
    assert filename == "notes.zip"
    archive = zipfile.ZipFile(io.BytesIO(content))
    assert set(archive.namelist()) == {"notes.md", "assets/img-abc.png"}
    assert archive.read("assets/img-abc.png") == b"png-bytes-img-abc.png"
    md = archive.read("notes.md").decode("utf-8")
    assert "# Notes" in md
    assert "### Overview" in md  # content h2 shifted below the title
    assert "**bold**" in md and "` code`" in md
    assert "[a link](<https://example.com>)" in md
    assert "> wisdom" in md
    assert "```python" in md
    assert "- [x] done" in md and "- [ ] todo" in md
    assert "  - nested" in md
    assert "![our pic](assets/img-abc.png)" in md
    assert "![ext](<https://elsewhere.example/x.png>)" in md
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in md
    assert "still exported" in md


def test_markdown_table_escapes_pipes():
    state = _state(
        [
            {
                "type": "table",
                "children": [
                    {
                        "type": "tablerow",
                        "children": [
                            {
                                "type": "tablecell",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [_text("a | b")],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    )
    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)
    content, _, _ = render_markdown(
        {"title": "", "blocks": blocks, "assets": assets}, lambda key: b""
    )
    md = content.decode("utf-8")
    assert "| a \\| b |" in md  # a raw pipe would split the column


def test_asset_names_deduped_on_sanitize_collision():
    """Two distinct storage keys can sanitize to one archive name — each must
    keep its own entry or one image silently replaces the other."""
    state = _state(
        [
            {"type": "image", "src": f"/uploads/{GUILD}/a img.png", "altText": "one"},
            {"type": "image", "src": f"/uploads/{GUILD}/a_img.png", "altText": "two"},
        ]
    )
    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)
    names = [a["name"] for a in assets]
    assert len(assets) == 2
    assert len(set(names)) == 2  # unique archive names
    # Blocks reference their own (deduped) names.
    assert {b["asset"] for b in blocks} == set(names)
    content, _content_type, _ = render_markdown(
        {"title": "", "stem": "d", "blocks": blocks, "assets": assets},
        lambda key: key.encode(),
    )
    archive = zipfile.ZipFile(io.BytesIO(content))
    stored = {n: archive.read(n) for n in archive.namelist() if n.startswith("assets/")}
    assert len(stored) == 2
    assert set(stored.values()) == {b"a img.png", b"a_img.png"}  # both survive


def test_markdown_zip_survives_missing_asset():
    """An image gone from storage skips its archive entry; the export (and
    the other assets) still ship."""
    state = _state(
        [
            {"type": "image", "src": f"/uploads/{GUILD}/gone.png", "altText": "gone"},
            {"type": "image", "src": f"/uploads/{GUILD}/here.png", "altText": "here"},
        ]
    )
    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)

    def read(key: str) -> bytes:
        if key == "gone.png":
            raise FileNotFoundError(key)
        return b"bytes"

    content, content_type, _ = render_markdown(
        {"title": "", "stem": "d", "blocks": blocks, "assets": assets}, read
    )
    assert content_type == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(content))
    assert "assets/here.png" in archive.namelist()
    assert "assets/gone.png" not in archive.namelist()


def test_markdown_inline_code_with_backticks():
    state = _state(
        [
            {
                "type": "paragraph",
                "children": [_text("use `backticks` here", 16)],  # code format
            }
        ]
    )
    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)
    content, _, _ = render_markdown(
        {"title": "", "blocks": blocks, "assets": assets}, lambda key: b""
    )
    # Double-backtick spaced form keeps the inner backticks literal.
    assert "`` use `backticks` here ``" in content.decode("utf-8")


def test_markdown_plain_without_assets():
    state = _state([{"type": "paragraph", "children": [_text("hello")]}])
    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)
    content, content_type, filename = render_markdown(
        {"title": "T", "stem": "t", "blocks": blocks, "assets": assets},
        lambda key: b"",
    )
    assert content_type.startswith("text/markdown")
    assert filename is None
    assert "hello" in content.decode("utf-8")


def test_docx_renders_and_embeds_image():
    import struct
    import zlib

    def make_png():
        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b"")
        )

    import docx

    blocks, assets = blocks_from_editor_state(FIXTURE, guild_id=GUILD)
    data = {"title": "Notes", "stem": "notes", "blocks": blocks, "assets": assets}
    content = render_docx(data, lambda key: make_png())
    assert content.startswith(b"PK")
    document = docx.Document(io.BytesIO(content))
    texts = [p.text for p in document.paragraphs]
    assert "Notes" in texts  # title
    assert any("wisdom" in t for t in texts)
    assert any("still exported" in t for t in texts)
    assert any("☑ done" in t for t in texts)
    assert len(document.inline_shapes) == 1  # the embedded upload image


def test_image_resize_carried_and_honored_in_docx():
    """The editor's resize (width px on the node) must survive into the
    block and set the DOCX picture width — not the fixed 6-inch default."""
    import struct
    import zlib

    import docx
    from docx.shared import Inches

    def make_png():
        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b"")
        )

    state = _state(
        [
            {
                "type": "image",
                "src": f"/uploads/{GUILD}/pic.png",
                "altText": "sized",
                "width": 192,  # 2 inches at 96 dpi
                "height": 120,
            },
            {
                "type": "image",
                "src": f"/uploads/{GUILD}/pic.png",
                "altText": "untouched",
                "width": "inherit",  # editor default: no resize stored
            },
        ]
    )
    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)
    assert blocks[0]["width"] == 192  # width wins; stale height not carried
    assert "height" not in blocks[0]
    assert "width" not in blocks[1]  # "inherit" ignored

    content = render_docx(
        {"title": "", "blocks": blocks, "assets": assets}, lambda key: make_png()
    )
    document = docx.Document(io.BytesIO(content))
    shapes = document.inline_shapes
    assert len(shapes) == 2
    assert shapes[0].width == Inches(2)  # resized: 192px / 96dpi
    assert shapes[1].width == Inches(6)  # untouched: the default cap


def test_docx_degrades_unreadable_image_to_alt_text():
    state = _state(
        [{"type": "image", "src": f"/uploads/{GUILD}/bad.png", "altText": "broken"}]
    )
    import docx

    blocks, assets = blocks_from_editor_state(state, guild_id=GUILD)
    content = render_docx(
        {"title": "", "blocks": blocks, "assets": assets},
        lambda key: b"not-an-image",
    )
    document = docx.Document(io.BytesIO(content))
    assert any("broken" in p.text for p in document.paragraphs)


def _cell(text, colspan=1, rowspan=1, header=0):
    return {
        "type": "tablecell",
        "colSpan": colspan,
        "rowSpan": rowspan,
        "headerState": header,
        "children": [{"type": "paragraph", "children": [_text(text)]}],
    }


def _row(*cells):
    return {"type": "tablerow", "children": list(cells)}


MERGED = _state(
    [
        {
            "type": "table",
            "children": [
                _row(_cell("Name", header=1), _cell("Detail", colspan=2, header=1)),
                _row(_cell("Tall", rowspan=2), _cell("a"), _cell("b")),
                _row(_cell("c"), _cell("d")),
            ],
        }
    ]
)


def test_a_table_with_merged_cells_carries_its_spans_and_grid():
    (table,) = blocks_from_editor_state(MERGED, guild_id=GUILD)[0]
    assert table["width"] == 3
    assert table["spans"] == [
        [[1, 1], [2, 1]],
        [[1, 2], [1, 1], [1, 1]],
        [[1, 1], [1, 1]],
    ]


def test_a_table_without_merges_is_unchanged():
    plain = _state([{"type": "table", "children": [_row(_cell("a"), _cell("b"))]}])
    (table,) = blocks_from_editor_state(plain, guild_id=GUILD)[0]
    assert "spans" not in table and "width" not in table


def test_merged_cells_export_as_multimarkdown():
    content, _ctype, _name = render_markdown(
        {"title": "", "blocks": blocks_from_editor_state(MERGED, guild_id=GUILD)[0]},
        lambda key: b"",
    )
    lines = content.decode().strip().splitlines()
    assert lines == [
        "| Name | Detail ||",
        "| --- | --- | --- |",
        "| Tall | a | b |",
        "| ^^ | c | d |",
    ]


def test_merged_cells_are_merged_in_word():
    import docx

    out = render_docx(
        {"title": "", "blocks": blocks_from_editor_state(MERGED, guild_id=GUILD)[0]},
        lambda key: b"",
    )
    table = docx.Document(io.BytesIO(out)).tables[0]
    # The merged header cell is one cell reached from both of its columns.
    assert table.cell(0, 1)._tc is table.cell(0, 2)._tc
    assert table.cell(1, 0)._tc is table.cell(2, 0)._tc
    assert table.cell(2, 1).text == "c"


CALLOUT = _state(
    [
        {
            "type": "callout",
            "variant": "warning",
            "children": [
                {"type": "paragraph", "children": [_text("Careful")]},
                {
                    "type": "list",
                    "listType": "bullet",
                    "children": [{"type": "listitem", "children": [_text("one")]}],
                },
                {
                    "type": "image",
                    "src": f"/uploads/{GUILD}/in-callout.png",
                    "altText": "pic",
                },
            ],
        },
        {"type": "paragraph", "children": [_text("after")]},
    ]
)


def test_a_callout_keeps_its_kind_and_blocks():
    blocks, assets = blocks_from_editor_state(CALLOUT, guild_id=GUILD)
    callout, after = blocks
    assert callout["type"] == "callout" and callout["variant"] == "warning"
    assert [b["type"] for b in callout["blocks"]] == ["paragraph", "list", "image"]
    # An image inside a callout still travels with the document.
    assert [a["key"] for a in assets] == ["in-callout.png"]
    assert after["runs"][0]["text"] == "after"


def test_a_callout_exports_as_obsidian_markdown():
    blocks, _assets = blocks_from_editor_state(CALLOUT, guild_id=GUILD)
    content, _ctype, _name = render_markdown(
        {"title": "", "blocks": blocks[:1]}, lambda key: b""
    )
    lines = content.decode().strip().splitlines()
    assert lines[:4] == ["> [!warning]", "> Careful", ">", "> - one"]


def test_a_folded_callout_exports_with_obsidians_fold_marker():
    folded = _state([{**CALLOUT["root"]["children"][0], "collapsed": True}])
    blocks, _assets = blocks_from_editor_state(folded, guild_id=GUILD)
    content, _ctype, _name = render_markdown(
        {"title": "", "blocks": blocks}, lambda key: b""
    )
    assert content.decode().strip().splitlines()[:2] == ["> [!warning]-", "> Careful"]


def test_an_embed_exports_as_a_callout_holding_its_name():
    state = _state(
        [
            {
                "type": "reference-embed",
                "entityType": "task",
                "entityId": 12,
                "text": "Roll call",
            }
        ]
    )
    blocks, _assets = blocks_from_editor_state(state, guild_id=GUILD)
    content, _ctype, _name = render_markdown(
        {"title": "", "blocks": blocks}, lambda key: b""
    )
    assert content.decode().strip().splitlines() == ["> [!note]", "> Roll call"]


def test_a_callout_in_word_is_its_label_then_its_blocks():
    import docx

    blocks, _assets = blocks_from_editor_state(CALLOUT, guild_id=GUILD)
    out = render_docx({"title": "", "blocks": blocks}, lambda key: b"")
    texts = [p.text for p in docx.Document(io.BytesIO(out)).paragraphs if p.text]
    assert texts[:3] == ["Warning", "Careful", "one"]


COLUMNS = _state(
    [
        {
            "type": "layout-container",
            "templateColumns": "1fr 3fr",
            "children": [
                {
                    "type": "layout-item",
                    "children": [{"type": "paragraph", "children": [_text("narrow")]}],
                },
                {
                    "type": "layout-item",
                    "children": [
                        {"type": "paragraph", "children": [_text("wide")]},
                        {"type": "paragraph", "children": [_text("more")]},
                    ],
                },
            ],
        }
    ]
)


def test_columns_keep_their_widths_and_blocks():
    (columns,) = blocks_from_editor_state(COLUMNS, guild_id=GUILD)[0]
    assert columns["type"] == "columns"
    assert columns["widths"] == [25, 75]
    assert [[b["runs"][0]["text"] for b in col] for col in columns["columns"]] == [
        ["narrow"],
        ["wide", "more"],
    ]


def test_columns_export_as_pandoc_fenced_divs():
    content, _ctype, _name = render_markdown(
        {"title": "", "blocks": blocks_from_editor_state(COLUMNS, guild_id=GUILD)[0]},
        lambda key: b"",
    )
    assert content.decode().strip().splitlines() == [
        ":::: {.columns}",
        '::: {.column width="25%"}',
        "narrow",
        ":::",
        '::: {.column width="75%"}',
        "wide",
        "",
        "more",
        ":::",
        "::::",
    ]


def test_columns_in_word_are_word_columns():
    import docx
    from docx.oxml.ns import qn

    out = render_docx(
        {"title": "", "blocks": blocks_from_editor_state(COLUMNS, guild_id=GUILD)[0]},
        lambda key: b"",
    )
    document = docx.Document(io.BytesIO(out))
    texts = [p.text for p in document.paragraphs if p.text]
    assert texts == ["narrow", "wide", "more"]
    # A section in two columns at the page's widths, then one column again.
    layouts = []
    for section in document.sections:
        (cols,) = section._sectPr.findall(qn("w:cols"))
        widths = [int(c.get(qn("w:w"))) for c in cols.findall(qn("w:col"))]
        layouts.append((cols.get(qn("w:num")), widths))
    two = [layout for layout in layouts if layout[0] == "2"]
    assert len(two) == 1
    narrow, wide = two[0][1]
    assert 2.9 < wide / narrow < 3.1
    assert layouts[-1][0] == "1"
    # Each column ends where the next begins.
    breaks = [
        br
        for p in document.paragraphs
        for br in p._p.iter(qn("w:br"))
        if br.get(qn("w:type")) == "column"
    ]
    assert len(breaks) == 1


DRAWING_DATA = (
    '{"elements":[{"id":"t","type":"text","text":"```"}],"appState":{},"files":{}}'
)
DRAWING = _state(
    [
        {
            "type": "paragraph",
            "children": [
                _text("before "),
                {"type": "excalidraw", "data": DRAWING_DATA, "width": 0},
                _text(" after"),
            ],
        }
    ]
)


def test_a_drawing_exports_to_markdown_as_its_fenced_scene():
    blocks, _assets = blocks_from_editor_state(DRAWING, guild_id=GUILD)
    assert [b["type"] for b in blocks] == ["paragraph", "drawing", "paragraph"]
    content, _ctype, _name = render_markdown(
        {"title": "", "blocks": blocks}, lambda k: b""
    )
    assert "````excalidraw\n" + DRAWING_DATA + "\n````" in content.decode()


def test_a_drawing_is_left_out_of_word():
    import docx

    blocks, _assets = blocks_from_editor_state(DRAWING, guild_id=GUILD)
    out = render_docx({"title": "", "blocks": blocks}, lambda key: b"")
    texts = [p.text for p in docx.Document(io.BytesIO(out)).paragraphs if p.text]
    assert [text.strip() for text in texts] == ["before", "after"]


def test_reading_order_keeps_callouts_and_reads_columns_in_line():
    assert editor_markdown(CALLOUT, reading=True).splitlines() == [
        "> [!warning]",
        "> Careful",
        ">",
        "> - one",
        ">",
        f"> ![pic](</uploads/{GUILD}/in-callout.png>)",
        "",
        "after",
    ]
    assert editor_markdown(COLUMNS, reading=True) == "narrow\n\nwide\n\nmore"
    assert editor_markdown(DRAWING, reading=True) == "before \n\n after"


def test_a_status_exports_as_its_word_set_apart():
    state = _state(
        [
            {
                "type": "paragraph",
                "children": [
                    _text("State: "),
                    {"type": "status", "text": "In progress", "color": "blue"},
                ],
            }
        ]
    )
    (paragraph,) = blocks_from_editor_state(state, guild_id=GUILD)[0]
    assert paragraph["runs"][-1] == {"text": "IN PROGRESS", "bold": True}
