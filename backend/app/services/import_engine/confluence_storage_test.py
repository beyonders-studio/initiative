"""The storage-format walker: what each piece of a Confluence page becomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.import_engine.confluence_storage import (
    BOLD,
    CODE,
    ITALIC,
    PageTarget,
    StorageResult,
    storage_to_lexical,
)


def blocks(xhtml: str, **kw):
    return storage_to_lexical(xhtml, **kw).content["root"]["children"]


def texts(node) -> str:
    """Everything a node says, as one string, line breaks as newlines."""
    if node.get("type") == "linebreak":
        return "\n"
    if "children" in node:
        return "".join(texts(child) for child in node["children"])
    return node.get("text", "")


def runs(block):
    return [(n["text"], n["format"]) for n in block["children"] if n["type"] == "text"]


# --- the basics ------------------------------------------------------------------


def test_an_empty_body_is_one_empty_paragraph():
    for body in ("", None, "   \n "):
        (only,) = blocks(body)
        assert only["type"] == "paragraph" and only["children"] == []


def test_paragraphs_and_headings_keep_their_order_and_level():
    out = blocks("<h1>Title</h1><p>First</p><h3>Sub</h3><p>Second</p>")
    assert [(b["type"], b.get("tag"), texts(b)) for b in out] == [
        ("heading", "h1", "Title"),
        ("paragraph", None, "First"),
        ("heading", "h3", "Sub"),
        ("paragraph", None, "Second"),
    ]


def test_formatting_is_a_bitmask_and_neighbours_merge():
    (p,) = blocks("<p>plain <strong>bold <em>both</em></strong> <code>x()</code></p>")
    assert runs(p) == [
        ("plain ", 0),
        ("bold ", BOLD),
        ("both", BOLD | ITALIC),
        (" ", 0),
        ("x()", CODE),
    ]


def test_markup_whitespace_is_not_content_but_a_non_breaking_space_is():
    (p,) = blocks("<p>\n   spaced\n   out&nbsp;here  </p>")
    assert texts(p) == "spaced out\xa0here"


def test_a_line_break_stays_a_line_break():
    (p,) = blocks("<p>one<br/>two</p>")
    assert [n["type"] for n in p["children"]] == ["text", "linebreak", "text"]


def test_loose_text_between_blocks_becomes_a_paragraph():
    out = blocks("before<h2>Heading</h2>after")
    assert [b["type"] for b in out] == ["paragraph", "heading", "paragraph"]


def test_entities_are_decoded():
    (p,) = blocks("<p>Fish &amp; chips &lt;3 &mdash; &#169;</p>")
    assert texts(p) == "Fish & chips <3 \u2014 \u00a9"


def test_unclosed_and_stray_tags_do_not_lose_the_rest():
    out = blocks("<p>open <strong>never closed</p></em><p>next</p>")
    assert [texts(b) for b in out] == ["open never closed", "next"]


# --- lists -----------------------------------------------------------------------


def test_lists_nest_the_way_the_editor_stores_them():
    (listed,) = blocks("<ol><li>one<ul><li>inner</li></ul></li><li>two</li></ol>")
    assert listed["type"] == "list" and listed["listType"] == "number"
    first, holder, second = listed["children"]
    assert texts(first) == "one"
    # A nested list sits in a sibling item of its own.
    (inner,) = holder["children"]
    assert inner["type"] == "list" and inner["listType"] == "bullet"
    assert texts(inner) == "inner"
    assert texts(second) == "two"


def test_a_paragraph_inside_a_list_item_is_its_line():
    (listed,) = blocks("<ul><li><p>a</p><p>b</p></li></ul>")
    (item,) = listed["children"]
    assert texts(item) == "a\nb"


def test_a_task_list_becomes_a_check_list():
    (listed,) = blocks(
        "<ac:task-list>"
        "<ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete</ac:task-status>"
        "<ac:task-body>Done thing</ac:task-body></ac:task>"
        "<ac:task><ac:task-id>2</ac:task-id><ac:task-status>incomplete</ac:task-status>"
        "<ac:task-body><span>Open <strong>thing</strong></span></ac:task-body></ac:task>"
        "</ac:task-list>"
    )
    assert listed["listType"] == "check"
    done, open_ = listed["children"]
    assert (texts(done), done["checked"]) == ("Done thing", True)
    assert (texts(open_), open_["checked"]) == ("Open thing", False)


# --- tables ----------------------------------------------------------------------


def test_a_table_keeps_its_header_row_and_spans():
    (table,) = blocks(
        "<table><colgroup><col/><col/></colgroup><tbody>"
        "<tr><th><p>Name</p></th><th><p>What</p></th></tr>"
        '<tr><td colspan="2"><p>Wide</p></td></tr>'
        "<tr><th>Row head</th><td></td></tr>"
        "</tbody></table>"
    )
    header, wide, last = table["children"]
    assert [c["headerState"] for c in header["children"]] == [1, 1]
    (cell,) = wide["children"]
    assert cell["colSpan"] == 2 and texts(cell) == "Wide"
    # A header cell below the first row heads its row, not a column.
    assert [c["headerState"] for c in last["children"]] == [2, 0]
    # An empty cell still holds a paragraph for the cursor to land in.
    assert last["children"][1]["children"][0]["type"] == "paragraph"


def test_a_table_inside_a_table_is_kept_as_its_text():
    result = storage_to_lexical(
        "<table><tr><td><table><tr><td>a</td><td>b</td></tr></table></td></tr></table>"
    )
    (table,) = result.content["root"]["children"]
    assert texts(table) == "a | b"
    assert result.dropped["nested-table"] == 1


# --- macros ----------------------------------------------------------------------


def test_a_code_macro_keeps_its_language_and_its_text_verbatim():
    (code,) = blocks(
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[if a < b:\n    print('&amp;')]]>"
        "</ac:plain-text-body></ac:structured-macro>"
    )
    assert code["type"] == "code" and code["language"] == "python"
    assert [n["type"] for n in code["children"]] == [
        "code-highlight",
        "linebreak",
        "code-highlight",
    ]
    assert texts(code) == "if a < b:\n    print('&amp;')"


def test_an_escaped_cdata_end_survives():
    (code,) = blocks(
        '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
        "<![CDATA[a]]]]><![CDATA[>b]]></ac:plain-text-body></ac:structured-macro>"
    )
    assert texts(code) == "a]]>b"


def test_a_panel_is_a_callout_led_by_its_title():
    (callout,) = blocks(
        '<ac:structured-macro ac:name="warning">'
        '<ac:parameter ac:name="title">Careful</ac:parameter>'
        "<ac:rich-text-body><p>First</p><ul><li>one</li></ul></ac:rich-text-body>"
        "</ac:structured-macro>"
    )
    assert callout["type"] == "callout"
    # Confluence's "warning" is its red panel.
    assert callout["variant"] == "error"
    title, first, listed = callout["children"]
    assert runs(title) == [("Careful", BOLD)]
    assert texts(first) == "First"
    # Unlike a quote, a callout holds a list as a list.
    assert listed["type"] == "list"


@pytest.mark.parametrize(
    "macro,variant",
    [
        ("info", "info"),
        ("note", "warning"),
        ("tip", "tip"),
        ("success", "success"),
        ("error", "error"),
        ("panel", "note"),
    ],
)
def test_each_panel_keeps_its_colour(macro, variant):
    (callout,) = blocks(
        f'<ac:structured-macro ac:name="{macro}"><ac:rich-text-body><p>x</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert callout["variant"] == variant


def test_an_empty_panel_is_still_somewhere_to_type():
    (callout,) = blocks('<ac:structured-macro ac:name="info"/>')
    assert [child["type"] for child in callout["children"]] == ["paragraph"]


def test_an_expand_is_its_title_then_its_body():
    out = blocks(
        '<ac:structured-macro ac:name="expand">'
        '<ac:parameter ac:name="title">More</ac:parameter>'
        "<ac:rich-text-body><p>Hidden</p></ac:rich-text-body></ac:structured-macro>"
    )
    assert [(b["type"], b.get("tag"), texts(b)) for b in out] == [
        ("heading", "h3", "More"),
        ("paragraph", None, "Hidden"),
    ]


def test_generated_and_embedded_macros_are_dropped_and_counted():
    result = storage_to_lexical(
        '<ac:structured-macro ac:name="toc"/>'
        "<p>kept</p>"
        '<ac:structured-macro ac:name="children"/>'
        '<ac:structured-macro ac:name="drawio"><ac:parameter ac:name="diagramName">'
        "x</ac:parameter></ac:structured-macro>"
    )
    assert [texts(b) for b in result.content["root"]["children"]] == ["kept"]
    assert result.dropped == {"toc": 1, "children": 1, "drawio": 1}


def test_an_unknown_macro_keeps_its_body():
    out = blocks(
        '<ac:structured-macro ac:name="excerpt"><ac:rich-text-body>'
        "<p>The gist</p></ac:rich-text-body></ac:structured-macro>"
        '<ac:structured-macro ac:name="custom-thing"><ac:plain-text-body>'
        "<![CDATA[raw words]]></ac:plain-text-body></ac:structured-macro>"
    )
    assert [texts(b) for b in out] == ["The gist", "raw words"]


def test_a_status_lozenge_is_a_status_in_its_colour():
    (p,) = blocks(
        '<p>State: <ac:structured-macro ac:name="status">'
        '<ac:parameter ac:name="colour">Green</ac:parameter>'
        '<ac:parameter ac:name="title">On track</ac:parameter>'
        '</ac:structured-macro> and <ac:structured-macro ac:name="status">'
        '<ac:parameter ac:name="title">Later</ac:parameter></ac:structured-macro></p>'
    )
    _state, green, _and, grey = p["children"]
    assert green == {
        "type": "status",
        "version": 1,
        "text": "On track",
        "color": "green",
    }
    # No colour set is Confluence's grey.
    assert grey["color"] == "neutral"


def test_a_jira_issue_macro_is_the_task_and_its_status_once_placed():
    (p,) = blocks(
        '<p><ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="key">SCRUM-2</ac:parameter></ac:structured-macro></p>',
        site_url="https://acme.atlassian.net/",
    )
    mention, space, chip = p["children"]
    assert mention["type"] == "entity-mention" and mention["entityType"] == "task"
    assert mention["importJiraKey"] == "SCRUM-2"
    assert mention["importUrl"] == "https://acme.atlassian.net/browse/SCRUM-2"
    assert space["text"] == " "
    assert chip["type"] == "smart-chip" and chip["chipKind"] == "task:status"
    assert chip["importJiraKey"] == "SCRUM-2"


def test_a_jira_macro_with_no_key_is_dropped_and_counted():
    result = storage_to_lexical(
        '<p><ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="jqlQuery">project = X</ac:parameter>'
        "</ac:structured-macro></p>"
    )
    assert result.dropped["jira"] == 1


def test_a_link_to_an_issue_on_the_site_is_marked_for_the_apply():
    (p,) = blocks(
        '<p><a href="https://acme.atlassian.net/browse/SCRUM-3?focus=1">SCRUM-3</a> '
        '<a href="https://elsewhere.example/browse/SCRUM-4">other</a></p>',
        site_url="https://acme.atlassian.net",
    )
    ours, _space, theirs = p["children"]
    assert ours["type"] == "link" and ours["importJiraKey"] == "SCRUM-3"
    assert "importJiraKey" not in theirs


def test_a_layout_becomes_the_editors_columns():
    out = blocks(
        "<ac:layout>"
        '<ac:layout-section ac:type="two_left_sidebar">'
        "<ac:layout-cell><p>side</p></ac:layout-cell>"
        "<ac:layout-cell><p>main</p></ac:layout-cell>"
        "</ac:layout-section>"
        '<ac:layout-section ac:type="single"><ac:layout-cell><p>full</p>'
        "</ac:layout-cell></ac:layout-section>"
        "</ac:layout>"
    )
    container, full = out
    assert container["type"] == "layout-container"
    assert container["templateColumns"] == "1fr 3fr"
    assert [texts(item) for item in container["children"]] == ["side", "main"]
    # One column is no layout at all.
    assert full["type"] == "paragraph" and texts(full) == "full"


def test_an_adf_extension_it_does_not_know_falls_back_to_its_rendering():
    out = blocks(
        '<ac:adf-extension><ac:adf-node type="something-new">'
        '<ac:adf-attribute key="setting">not words</ac:adf-attribute>'
        "<ac:adf-content><p>new</p></ac:adf-content></ac:adf-node><ac:adf-fallback>"
        "<p>fallback</p></ac:adf-fallback></ac:adf-extension>"
    )
    assert [texts(b) for b in out] == ["fallback"]


def test_an_adf_extension_with_no_fallback_keeps_its_words_not_its_settings():
    out = blocks(
        '<ac:adf-extension><ac:adf-node type="something-new">'
        '<ac:adf-attribute key="setting">not words</ac:adf-attribute>'
        "<ac:adf-content><p>kept</p></ac:adf-content></ac:adf-node></ac:adf-extension>"
    )
    assert [texts(b) for b in out] == ["kept"]


# --- links, people, pictures ---------------------------------------------------


def test_a_link_keeps_its_url_and_an_unsafe_one_keeps_only_its_words():
    (p,) = blocks(
        '<p><a href="https://example.com/x">site</a> and '
        '<a href="javascript:alert(1)">this</a></p>'
    )
    link, rest = p["children"]
    assert link["type"] == "link" and link["url"] == "https://example.com/x"
    assert texts(link) == "site"
    assert rest == {**rest, "text": " and this"}


def test_a_link_to_a_page_in_the_import_is_a_page_mention():
    def page(title, space):
        return (
            PageTarget(slug="database-design") if title == "Database Design" else None
        )

    (p,) = blocks(
        '<p>See <ac:link><ri:page ri:content-title="Database Design"/>'
        "<ac:plain-text-link-body><![CDATA[the design]]></ac:plain-text-link-body>"
        "</ac:link></p>",
        page=page,
    )
    _see, mention = p["children"]
    assert mention == {
        "type": "entity-mention",
        "version": 1,
        "entityType": "wiki_page",
        "entityId": 0,
        "text": "the design",
        "importSlug": "database-design",
    }


def test_a_link_to_a_page_outside_the_import_goes_back_to_the_source():
    def page(title, space):
        return PageTarget(url=f"https://acme.atlassian.net/wiki/display/{space}/X")

    (p,) = blocks(
        '<p><ac:link><ri:page ri:space-key="OTHER" ri:content-title="Elsewhere"/>'
        "</ac:link></p>",
        page=page,
    )
    (link,) = p["children"]
    assert link["type"] == "link" and link["url"].endswith("/OTHER/X")
    assert texts(link) == "Elsewhere"


def test_a_page_link_nobody_can_place_keeps_its_words():
    (p,) = blocks('<p><ac:link><ri:page ri:content-title="Gone"/></ac:link></p>')
    assert texts(p) == "Gone"


def test_a_mention_names_the_person_and_is_listed_for_the_people_step():
    result = storage_to_lexical(
        '<p><ac:link><ri:user ri:account-id="abc"/></ac:link> and '
        '<ac:link><ri:user ri:account-id="abc"/></ac:link> and '
        '<ac:link><ri:user ri:account-id="nobody"/></ac:link></p>',
        user=lambda account: {"abc": "Jordan Janzen"}.get(account),
    )
    (p,) = result.content["root"]["children"]
    first = p["children"][0]
    assert first["type"] == "mention"
    assert first["mentionName"] == "Jordan Janzen"
    assert first["mentionUserId"] is None
    assert result.mentions == ["Jordan Janzen"]
    assert result.dropped["user"] == 1


def test_an_attached_image_renders_from_where_the_fetch_put_it():
    result = storage_to_lexical(
        '<p><ac:image ac:width="320" ac:alt="The chart">'
        '<ri:attachment ri:filename="chart.png"/></ac:image></p>'
        '<ac:image><ri:attachment ri:filename="missing.png"/></ac:image>'
        '<p><ac:image><ri:url ri:value="https://cdn.example.com/a.gif"/></ac:image></p>',
        image=lambda name: "/uploads/7/abc.png" if name == "chart.png" else None,
    )
    placed, missing, remote = result.content["root"]["children"]
    (image,) = placed["children"]
    assert image["type"] == "image"
    assert (image["src"], image["altText"], image["width"]) == (
        "/uploads/7/abc.png",
        "The chart",
        320,
    )
    # Nobody could place it: its name, where it stood, and counted.
    assert texts(missing) == "[missing.png]"
    assert result.dropped["image"] == 1
    # A picture from the web is linked as it is, never fetched.
    assert remote["children"][0]["src"] == "https://cdn.example.com/a.gif"
    assert result.attachments == ["chart.png", "missing.png"]


def test_a_link_to_an_attachment_goes_where_the_file_went():
    (p,) = blocks(
        '<p><ac:link><ri:attachment ri:filename="spec.pdf"/>'
        "<ac:plain-text-link-body><![CDATA[the spec]]></ac:plain-text-link-body>"
        "</ac:link></p>",
        attachment=lambda name: "/files/12",
    )
    (link,) = p["children"]
    assert link["type"] == "link" and link["url"] == "/files/12"
    assert texts(link) == "the spec"


def test_a_link_to_a_file_that_became_a_file_mentions_it():
    (p,) = blocks(
        '<p><ac:link><ri:attachment ri:filename="spec.pdf"/>'
        "<ac:plain-text-link-body><![CDATA[the spec]]></ac:plain-text-link-body>"
        '</ac:link> and <ac:link><ri:attachment ri:filename="other.pdf"/></ac:link>'
        '<a href="https://example.com"><ac:link><ri:attachment ri:filename="spec.pdf"/>'
        "</ac:link></a></p>",
        file=lambda name: "entry:assets/abc.pdf" if name == "spec.pdf" else None,
        attachment=lambda name: None,
    )
    mention, words, inside = p["children"]
    assert mention == {
        "type": "entity-mention",
        "version": 1,
        "entityType": "file",
        "entityId": 0,
        "text": "the spec",
        "importRef": "entry:assets/abc.pdf",
    }
    # A file that did not become one keeps its name.
    assert (words["type"], words["text"]) == ("text", " and other.pdf")
    # A mention cannot sit inside a link, so there it is words.
    assert inside["type"] == "link" and texts(inside) == "spec.pdf"


def test_a_file_card_mentions_its_file_too():
    (p,) = blocks(
        '<p><ac:structured-macro ac:name="view-file"><ac:parameter ac:name="name">'
        '<ri:attachment ri:filename="deck.pptx"/></ac:parameter>'
        "</ac:structured-macro></p>",
        file=lambda name: f"entry:assets/{name}",
    )
    (mention,) = p["children"]
    assert mention["importRef"] == "entry:assets/deck.pptx"
    assert mention["text"] == "deck.pptx"


def test_the_pictures_a_page_shows_are_told_apart_from_those_it_links():
    result = storage_to_lexical(
        '<p><ac:image><ri:attachment ri:filename="shown.png"/></ac:image>'
        '<ac:link><ri:attachment ri:filename="linked.png"/></ac:link></p>'
    )
    assert result.attachments == ["shown.png", "linked.png"]
    assert result.shown == ["shown.png"]


def test_an_emoticon_and_a_date_are_text():
    (p,) = blocks(
        '<p><ac:emoticon ac:name="smile" ac:emoji-fallback="\U0001f642"/> on '
        '<time datetime="2024-03-04"/></p>'
    )
    assert texts(p) == "\U0001f642 on 2024-03-04"


def test_an_inline_comment_marker_is_just_its_text():
    (p,) = blocks(
        '<p>Some <ac:inline-comment-marker ac:ref="x">marked</ac:inline-comment-marker>'
        " words</p>"
    )
    assert texts(p) == "Some marked words"


def test_a_block_inside_a_line_is_laid_on_the_line():
    (p,) = blocks("<p>before<div>inside</div>after</p>")
    assert texts(p) == "before\ninside\nafter"


# --- real pages ------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "confluence"

_INLINE = {
    "text",
    "linebreak",
    "link",
    "mention",
    "entity-mention",
    "image",
    "status",
    "smart-chip",
}
_BLOCK = {
    "paragraph",
    "heading",
    "list",
    "quote",
    "code",
    "table",
    "horizontalrule",
    "layout-container",
    "callout",
    "youtube",
}
_CHILDREN: dict[str, set[str]] = {
    "root": _BLOCK,
    "paragraph": _INLINE,
    "heading": _INLINE,
    "quote": _INLINE,
    "link": {"text", "linebreak"},
    "list": {"listitem"},
    "listitem": _INLINE | {"list"},
    "code": {"code-highlight", "linebreak"},
    "table": {"tablerow"},
    "tablerow": {"tablecell"},
    "tablecell": _BLOCK - {"table", "layout-container"},
    "layout-container": {"layout-item"},
    "layout-item": _BLOCK - {"layout-container"},
    "callout": _BLOCK - {"layout-container"},
}


def assert_loadable(node: dict, path: str = "root") -> None:
    """Every node is one the editor registers, where the editor allows it."""
    node_type = node["type"]
    assert node.get("version") == 1, path
    if node_type in ("text", "code-highlight"):
        assert isinstance(node["text"], str) and node["text"], path
        assert isinstance(node["format"], int), path
        return
    if node_type not in _CHILDREN:
        assert "children" not in node, path
        return
    for index, child in enumerate(node["children"]):
        where = f"{path}/{index}:{child['type']}"
        assert child["type"] in _CHILDREN[node_type], where
        assert_loadable(child, where)


def _real_pages():
    pages = sorted(FIXTURES.glob("*.xml"))
    if not pages:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no pages captured"))]
    return [pytest.param(page, id=page.stem) for page in pages]


@pytest.mark.parametrize("page", _real_pages())
def test_every_real_page_converts_to_a_state_the_editor_can_load(page):
    result = storage_to_lexical(
        page.read_text(encoding="utf-8"),
        page=lambda title, space: PageTarget(slug="x"),
        user=lambda account: "Somebody",
        image=lambda name: f"/uploads/1/{name}",
        attachment=lambda name: "/files/1",
        site_url="https://example.atlassian.net",
    )
    root = result.content["root"]
    assert root["children"], page.name
    assert_loadable(root)
    # And it survives the trip to the database as JSON.
    json.loads(json.dumps(result.content))


def test_everything_above_together_is_a_state_the_editor_can_load():
    result = storage_to_lexical(
        "<h2>Kitchen sink</h2><p>A <strong>bold</strong> "
        '<a href="https://example.com">link</a> and '
        '<ac:link><ri:user ri:account-id="a"/></ac:link><br/>'
        '<ac:image><ri:attachment ri:filename="x.png"/></ac:image></p>'
        "<ul><li>one<ol><li>deep</li></ol></li></ul>"
        "<ac:task-list><ac:task><ac:task-status>complete</ac:task-status>"
        "<ac:task-body>done</ac:task-body></ac:task></ac:task-list>"
        "<table><tr><th>h</th></tr><tr><td><ul><li>in cell</li></ul></td></tr></table>"
        '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>note</p>'
        "</ac:rich-text-body></ac:structured-macro>"
        '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[x = 1]]>'
        "</ac:plain-text-body></ac:structured-macro><hr/>"
        '<ac:layout><ac:layout-section ac:type="three_equal">'
        "<ac:layout-cell><p>a</p></ac:layout-cell><ac:layout-cell/>"
        "<ac:layout-cell><table><tr><td>t</td></tr></table></ac:layout-cell>"
        "</ac:layout-section></ac:layout><blockquote><p>q</p></blockquote>",
        user=lambda account: "Somebody",
        image=lambda name: f"/uploads/1/{name}",
    )
    assert_loadable(result.content["root"])


# --- what the real pages turned up -------------------------------------------------


def real(stem: str) -> StorageResult:
    (path,) = FIXTURES.glob(f"{stem}-*.xml")
    return storage_to_lexical(
        path.read_text(encoding="utf-8"),
        page=lambda title, space: PageTarget(slug=title.lower().replace(" ", "-")),
        user=lambda account: "Somebody",
        image=lambda name: f"/uploads/1/{name}",
        attachment=lambda name: f"/files/{name}",
        site_url="https://morels.atlassian.net",
        children=lambda: {"type": "list", "listType": "bullet", "children": []},
    )


def outline(result: StorageResult) -> list[tuple[str, str]]:
    return [
        (block["type"], texts(block)) for block in result.content["root"]["children"]
    ]


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_a_new_editor_panel_is_a_callout_of_its_kind():
    result = real("26247169")
    callouts = [b for b in result.content["root"]["children"] if b["type"] == "callout"]
    assert ("note", "A note panel.") in [(c["variant"], texts(c)) for c in callouts]


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_a_decision_log_is_a_checklist_ticked_where_decided():
    result = real("26279956")
    decisions = [
        b
        for b in result.content["root"]["children"]
        if b["type"] == "list" and "prod read access" in texts(b)
    ]
    (listed,) = decisions
    assert listed["listType"] == "check"
    assert [item["checked"] for item in listed["children"]] == [True, False]


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_tabs_are_a_heading_over_each_body_and_carry_no_settings():
    result = real("26509330")
    pairs = outline(result)
    assert ("heading", "macOS") in pairs and ("heading", "Linux") in pairs
    assert ("paragraph", "brew install thing") in pairs
    assert not any("native-tabs" in text for _type, text in pairs)


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_an_embedded_video_is_the_editors_embed_and_mermaid_stays_mermaid():
    result = real("26509330")
    roots = result.content["root"]["children"]
    (video,) = [b for b in roots if b["type"] == "youtube"]
    assert video["videoID"] == "dQw4w9WgXcQ"
    (mermaid,) = [b for b in roots if b["type"] == "code" and "flowchart" in texts(b)]
    assert mermaid["language"] == "mermaid"


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_an_included_page_is_a_link_to_it():
    result = real("26509330")
    mentions = [
        node
        for block in result.content["root"]["children"]
        for node in block.get("children") or []
        if node.get("type") == "entity-mention"
    ]
    assert "Database Design" in [m["text"] for m in mentions]
    assert "include" not in result.dropped


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_the_children_macro_is_the_list_of_pages_beneath():
    result = real("26116204")
    assert "children" not in result.dropped
    assert any(b["type"] == "list" for b in result.content["root"]["children"])


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_an_emoticon_stored_by_name_is_its_glyph():
    result = real("26476563")
    line = next(t for kind, t in outline(result) if t.startswith("Emoji nodes"))
    assert ":warning:" not in line and "\u26a0" in line


@pytest.mark.skipif(not FIXTURES.exists(), reason="no pages captured")
def test_file_cards_and_captions_on_the_attachments_page():
    result = real("26378256")
    assert "view-file" not in result.dropped and "viewpdf" not in result.dropped
    assert {"design-spec.pdf", "roadmap-export.csv"} <= set(result.attachments)
    captioned = [
        block
        for block in result.content["root"]["children"]
        if any(n.get("type") == "image" for n in block.get("children") or [])
        and "Architecture diagram (a blue rectangle)" in texts(block)
    ]
    assert captioned, "the caption reads under its picture"


def test_a_jira_issue_list_is_a_link_to_the_same_search():
    (p,) = blocks(
        '<p><ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="jqlQuery">project = SCRUM AND status = Done</ac:parameter>'
        "</ac:structured-macro></p>",
        site_url="https://acme.atlassian.net",
    )
    (link,) = p["children"]
    assert link["type"] == "link"
    assert link["url"] == (
        "https://acme.atlassian.net/issues/?jql=project%20%3D%20SCRUM%20AND%20status%20%3D%20Done"
    )


def test_an_emoticon_is_its_glyph_however_it_was_stored():
    (p,) = blocks(
        '<p><ac:emoticon ac:name="tada" ac:emoji-id="1f389" ac:emoji-fallback=":tada:"/>'
        '<ac:emoticon ac:name="warning" ac:emoji-id="atlassian-warning" '
        'ac:emoji-fallback=":warning:"/><ac:emoticon ac:name="thumbs-up"/></p>'
    )
    assert texts(p) == "\U0001f389⚠️\U0001f44d"
