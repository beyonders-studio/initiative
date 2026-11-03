"""Unit tests for the Markdown → export-blocks converter."""

from app.services.export.markdown import blocks_from_markdown


def test_empty_and_whitespace_input():
    assert blocks_from_markdown(None) == []
    assert blocks_from_markdown("") == []
    assert blocks_from_markdown("   \n  ") == []


def test_inline_formatting_runs():
    (para,) = blocks_from_markdown(
        "plain **bold** *italic* ~~strike~~ `code` [text](https://x.example)"
    )
    assert para["type"] == "paragraph"
    runs = para["runs"]
    assert {"text": "bold", "bold": True} in runs
    assert {"text": "italic", "italic": True} in runs
    assert {"text": "strike", "strike": True} in runs
    assert {"text": "code", "code": True} in runs
    assert {"text": "text", "link": "https://x.example"} in runs


def test_nested_emphasis_composes_flags():
    (para,) = blocks_from_markdown("**bold *and italic***")
    assert {"text": "and italic", "bold": True, "italic": True} in para["runs"]


def test_headings_carry_level():
    blocks = blocks_from_markdown("# One\n\n### Three")
    assert [(b["type"], b["level"]) for b in blocks] == [("heading", 1), ("heading", 3)]


def test_nested_list_structure():
    blocks = blocks_from_markdown("1. first\n2. second\n   - nested\n")
    (lst,) = blocks
    assert lst["type"] == "list" and lst["ordered"] is True
    assert lst["items"][0]["runs"] == [{"text": "first"}]
    nested = lst["items"][1]["children"][0]
    assert nested["ordered"] is False
    assert nested["items"][0]["runs"] == [{"text": "nested"}]


def test_code_block_keeps_language_and_text():
    (code,) = blocks_from_markdown("```python\nx = 1\ny = 2\n```")
    assert code == {"type": "code", "language": "python", "text": "x = 1\ny = 2"}


def test_quote_flattens_to_runs():
    (quote,) = blocks_from_markdown("> wise words\n> more words")
    assert quote["type"] == "quote"
    text = "".join(r["text"] for r in quote["runs"])
    assert "wise words" in text and "more words" in text
    # A list in a quote keeps its items' words.
    (listed,) = blocks_from_markdown("> - Bring passport\n> - Bring ticket")
    text = "".join(r["text"] for r in listed["runs"])
    assert text == "Bring passport\nBring ticket"


def test_table_rows_of_run_cells():
    (table,) = blocks_from_markdown("| A | B |\n|---|---|\n| **1** | 2 |")
    assert table["type"] == "table"
    assert table["rows"][0][0] == [{"text": "A"}]
    assert table["rows"][1][0] == [{"text": "1", "bold": True}]


def test_soft_break_is_space_and_hard_break_is_newline_run():
    """Matches the app's react-markdown defaults: a single newline renders as
    a space; a trailing-double-space hard break renders as a line break."""
    (soft,) = blocks_from_markdown("line one\nline two")
    assert {"text": "\n"} not in soft["runs"]
    (hard,) = blocks_from_markdown("line one  \nline two")
    assert {"text": "\n"} in hard["runs"]
    # A comment is typed in a box, where a newline is a line break.
    (typed,) = blocks_from_markdown("line one\nline two", line_breaks=True)
    assert {"text": "\n"} in typed["runs"]


def test_image_degrades_to_linked_alt_text():
    (para,) = blocks_from_markdown("![alt text](https://img.example/x.png)")
    assert {
        "text": "alt text",
        "link": "https://img.example/x.png",
        "picture": True,
    } in para["runs"]


def test_task_list_is_a_checklist():
    (lst,) = blocks_from_markdown("- [ ] one\n- [x] **two**\n  - [X] nested")
    assert lst["checklist"] is True
    assert [(i["checked"], i["runs"]) for i in lst["items"]] == [
        (False, [{"text": "one"}]),
        (True, [{"text": "two", "bold": True}]),
    ]
    assert lst["items"][1]["children"][0]["items"][0]["checked"] is True
    # A list with an item that has no box keeps its brackets as text.
    (mixed,) = blocks_from_markdown("- [ ] one\n- two\n- **[x] three**")
    assert mixed["checklist"] is False
    assert mixed["items"][0]["runs"] == [{"text": "[ ] one"}]


def test_mentions_read_as_the_app_shows_them():
    (para,) = blocks_from_markdown(
        "Ask @[Ada](42) about #task[Fix it](12), not @[Bo]() or"
        " mail@[x](1) or #nothing[y](2) or `@[](3)`"
    )
    runs = para["runs"]
    assert {"text": "@Ada", "mention": 42} in runs
    assert {"text": "Fix it"} in runs
    # Every kind the app can mention.
    (kinds,) = blocks_from_markdown(
        "#counter-group[Q1](9), #wiki-page[Home](2), #file[Map](3)"
    )
    assert "".join(r["text"] for r in kinds["runs"]) == "Q1, Home, Map"
    assert {"text": "@Bo"} in runs
    assert {"text": "x", "link": "1"} in runs
    assert {"text": "y", "link": "2"} in runs
    assert {"text": "@[](3)", "code": True} in runs


def test_html_stays_literal_text():
    """Raw HTML must never become markup — it degrades to its literal text."""
    (para,) = blocks_from_markdown('hello <b onmouseover="x">world</b>')
    texts = "".join(r["text"] for r in para["runs"])
    assert "<b" in texts  # literal, unparsed
    assert not any(r.get("bold") for r in para["runs"])


def test_html_block_degrades_to_literal_text():
    """Block-level HTML is a leaf token — it must degrade to its literal text
    (the "never dropped" contract), not vanish because it has no children."""
    blocks = blocks_from_markdown("<details>hidden text</details>")
    assert blocks == [
        {
            "type": "paragraph",
            "runs": [{"text": "<details>hidden text</details>"}],
        }
    ]
