"""A Confluence space's pages as a wiki envelope."""

from __future__ import annotations

from app.schemas.tenant.import_envelopes import WikiEnvelope
from app.services.import_engine import confluence_mapping as cm
from app.services.import_engine.confluence_attachments import PageMedia
from app.services.import_engine.jira_attachments import StoredImage

SITE = "https://acme.atlassian.net"
SPACE = {
    "id": "9",
    "key": "DOCS",
    "name": "Team Docs",
    "homepageId": "1",
    "description": {"plain": {"value": "Where we write things down"}},
}


def page(page_id, title, parent=None, position=None, body="<p>words</p>", **kw):
    return cm.SourcePage(
        id=str(page_id),
        title=title,
        parent_id=str(parent) if parent is not None else None,
        position=position,
        body=body,
        **kw,
    )


def build(pages, users=None, **kw):
    return cm.build_wiki_envelope(
        space=kw.pop("space", SPACE),
        pages=pages,
        users=users or {},
        site_url=SITE,
        app_version="0.78.0-test",
        **kw,
    )


def by_title(mapped):
    return {p["title"]: p for p in mapped.envelope["pages"]}


def test_a_space_is_one_wiki_with_its_home_page():
    mapped = build([page(1, "Home"), page(2, "Guide", parent=1)])
    envelope = mapped.envelope
    assert envelope["name"] == "Team Docs"
    assert envelope["description"] == "Where we write things down"
    assert envelope["home_page"] == "home"
    # The importer's own model reads it.
    WikiEnvelope.model_validate(envelope)


def test_the_tree_keeps_its_parents_and_sibling_order():
    mapped = build(
        [
            page(1, "Home"),
            page(3, "Second", parent=1, position=20),
            page(2, "First", parent=1, position=10),
            page(4, "Deep", parent=3),
        ]
    )
    # Navigation order: each page, then what is under it.
    assert [p["title"] for p in mapped.envelope["pages"]] == [
        "Home",
        "First",
        "Second",
        "Deep",
    ]
    pages = by_title(mapped)
    assert pages["First"]["parent"] == "home" and pages["First"]["position"] == 0
    assert pages["Second"]["position"] == 1
    assert pages["Deep"]["parent"] == "second"
    assert pages["Home"]["parent"] is None


def test_a_page_whose_parent_did_not_come_sits_at_the_top():
    mapped = build([page(5, "Orphan", parent=999)])
    assert by_title(mapped)["Orphan"]["parent"] is None


def test_a_loop_in_the_tree_still_brings_every_page():
    mapped = build([page(1, "A", parent=2), page(2, "B", parent=1)])
    assert {p["title"] for p in mapped.envelope["pages"]} == {"A", "B"}


def test_titles_that_slug_alike_get_their_own_addresses():
    mapped = build([page(1, "Notes"), page(2, "notes!"), page(3, "Notes")])
    assert [p["slug"] for p in mapped.envelope["pages"]] == [
        "notes",
        "notes-2",
        "notes-3",
    ]


def mentions_of(content):
    found = []

    def walk(node):
        if node.get("type") == "entity-mention":
            found.append((node["text"], node["importSlug"]))
        for child in node.get("children") or []:
            walk(child)

    walk(content["root"])
    return found


def test_a_folder_becomes_a_page_listing_what_is_in_it():
    mapped = build(
        [
            page(1, "Home"),
            page(50, "Designs", parent=1, body=None),
            page(2, "Login", parent=50, position=1),
            page(3, "Signup", parent=50, position=2),
        ]
    )
    folder = by_title(mapped)["Designs"]
    assert mentions_of(folder["content"]) == [("Login", "login"), ("Signup", "signup")]
    assert mapped.containers == 1


def test_a_parent_with_nothing_to_say_lists_its_children():
    mapped = build(
        [
            page(1, "Section", body="<p> </p>"),
            page(2, "Child", parent=1),
            page(3, "Blank leaf", body=""),
        ]
    )
    pages = by_title(mapped)
    assert mentions_of(pages["Section"]["content"]) == [("Child", "child")]
    # A blank page with nothing under it stays blank rather than growing a list.
    assert mentions_of(pages["Blank leaf"]["content"]) == []
    assert mapped.containers == 1


def test_a_link_to_a_page_goes_to_the_imported_page_or_back_to_the_source():
    mapped = build(
        [
            page(1, "Home", body=""),
            page(
                2,
                "Links",
                body=(
                    '<p><ac:link><ri:page ri:content-title="database design"/></ac:link>'
                    '<ac:link><ri:page ri:content-title="Not fetched"/></ac:link>'
                    '<ac:link><ri:page ri:space-key="OPS" ri:content-title="Runbook"/>'
                    "</ac:link></p>"
                ),
            ),
            page(3, "Database Design"),
        ]
    )
    (paragraph,) = by_title(mapped)["Links"]["content"]["root"]["children"]
    same, missing, other = paragraph["children"]
    # Titles match however they were capitalised.
    assert same["type"] == "entity-mention" and same["importSlug"] == "database-design"
    assert missing["url"] == f"{SITE}/wiki/display/DOCS/Not+fetched"
    assert other["url"] == f"{SITE}/wiki/display/OPS/Runbook"


def test_authors_and_mentions_are_named_and_counted_for_the_people_step():
    users = {"a1": "Robin Ade", "b2": "Sam Bee"}
    mapped = build(
        [
            page(
                1,
                "One",
                author_id="a1",
                body='<p><ac:link><ri:user ri:account-id="b2"/></ac:link></p>',
            ),
            page(2, "Two", author_id="a1"),
            page(3, "Three", author_id="zz"),
        ],
        users=users,
    )
    pages = by_title(mapped)
    assert pages["One"]["author_handle"] == "Robin Ade"
    assert pages["One"]["mention_handles"] == ["Sam Bee"]
    # An account the site would not name: no author claimed.
    assert "author_handle" not in pages["Three"]
    assert mapped.people == {"Robin Ade": 2, "Sam Bee": 1}


def test_labels_become_tags_and_times_come_along():
    mapped = build(
        [
            page(
                1,
                "Tagged",
                labels=("howto", "ops"),
                created_at="2024-03-04T09:00:00.000Z",
                updated_at="2024-05-01T10:00:00.000Z",
            )
        ]
    )
    tagged = by_title(mapped)["Tagged"]
    assert tagged["tags"] == ["howto", "ops"]
    assert tagged["created_at"] == "2024-03-04T09:00:00.000Z"
    assert tagged["updated_at"] == "2024-05-01T10:00:00.000Z"


def test_what_the_converter_drops_is_summed_over_the_space():
    mapped = build(
        [
            page(1, "A", body='<ac:structured-macro ac:name="toc"/><p>x</p>'),
            page(2, "B", body='<ac:structured-macro ac:name="toc"/><p>y</p>'),
        ]
    )
    assert mapped.dropped == {"toc": 2}


def test_pages_past_the_envelope_budget_are_left_out_whole_and_counted():
    big = "<p>" + "x" * 5000 + "</p>"
    mapped = build(
        [page(1, "One", body=big), page(2, "Two", body=big), page(3, "Three")],
        max_bytes=8000,
    )
    assert [p["title"] for p in mapped.envelope["pages"]] == ["One", "Three"]
    assert mapped.over_limit == 1
    assert mapped.pages == 2


def test_the_home_page_is_dropped_from_the_envelope_if_it_did_not_fit():
    mapped = build([page(1, "Home", body="<p>" + "x" * 5000 + "</p>")], max_bytes=100)
    assert mapped.envelope["home_page"] is None


def test_a_malformed_page_is_skipped():
    assert cm.read_page({"id": "abc", "title": "X"}) is None
    assert cm.read_page({"id": "1", "title": "  "}) is None
    assert cm.read_page("nonsense") is None
    read = cm.read_page(
        {
            "id": "7",
            "title": "Real",
            "parentId": "3",
            "position": 12,
            "authorId": "a1",
            "createdAt": "2024-03-04T09:00:00.000Z",
            "version": {"createdAt": "2024-05-01T10:00:00.000Z"},
            "body": {"storage": {"value": "<p>hi</p>"}},
        },
        ("tag",),
    )
    assert read == cm.SourcePage(
        id="7",
        title="Real",
        parent_id="3",
        position=12,
        body="<p>hi</p>",
        author_id="a1",
        created_at="2024-03-04T09:00:00.000Z",
        updated_at="2024-05-01T10:00:00.000Z",
        labels=("tag",),
    )
    folder = cm.read_folder({"id": "50", "title": "Designs", "parentId": "1"})
    assert folder is not None and folder.is_folder


def test_labels_are_read_once_each():
    assert cm.page_labels(
        {"results": [{"name": "a"}, {"name": "b"}, {"name": "a"}, {"x": 1}]}
    ) == ("a", "b")
    assert cm.page_labels("nope") == ()


def stored(name, content_type="application/pdf"):
    return StoredImage(
        filename=name,
        storage_key=f"key-{name}",
        content_type=content_type,
        size_bytes=5,
    )


def media_of(*files, images=()):
    media = PageMedia()
    for name in files:
        media.files[name] = stored(name)
    for name in images:
        media.stored_images[name] = stored(name, "image/png")
        media.images[name] = f"/uploads/1/key-{name}"
    return media


def test_a_page_shows_its_pictures_and_mentions_its_files():
    mapped = build(
        [
            page(
                1,
                "Home",
                body=(
                    '<p><ac:image><ri:attachment ri:filename="chart.png"/></ac:image>'
                    '<ac:link><ri:attachment ri:filename="spec.pdf"/></ac:link></p>'
                ),
            )
        ],
        media={"1": media_of("spec.pdf", images=("chart.png", "hidden.png"))},
    )
    (paragraph,) = by_title(mapped)["Home"]["content"]["root"]["children"]
    image, mention = paragraph["children"]
    assert image["src"] == "/uploads/1/key-chart.png"
    assert mention["importRef"] == "entry:assets/key-spec.pdf"
    assert [s.filename for s in mapped.uploads] == ["chart.png"]
    # The picture the page never shows comes over as a file too.
    assert [f.stored.filename for f in mapped.files] == ["spec.pdf", "hidden.png"]
    # Each is filed under the page it was attached to.
    assert {f.page_slug for f in mapped.files} == {"home"}


def test_without_files_a_picture_nobody_shows_is_counted():
    mapped = build(
        [page(1, "Home", body="<p>nothing shown</p>")],
        media={"1": media_of(images=("hidden.png",))},
        files_allowed=False,
    )
    assert mapped.files == [] and mapped.uploads == []
    assert mapped.files_blocked == 1


def test_a_page_left_out_for_size_leaves_its_attachments_too():
    big = "<p>" + "x" * 5000 + "</p>"
    mapped = build(
        [page(1, "One", body=big), page(2, "Two", body=big)],
        media={"2": media_of("spec.pdf")},
        max_bytes=8000,
    )
    assert mapped.over_limit == 1
    assert mapped.files == []


def comment(
    comment_id, body, parent=None, author="a1", at="2024-05-01T10:00:00Z", **kw
):
    return cm.SourceComment(
        id=str(comment_id),
        body=body,
        parent_id=str(parent) if parent else None,
        author_id=author,
        created_at=at,
        **kw,
    )


def test_what_was_said_on_a_page_arrives_on_it_as_a_thread():
    users = {"a1": "Robin Ade", "b2": "Sam Bee"}
    mapped = build(
        [page(1, "Home"), page(2, "Guide", parent=1)],
        users=users,
        comments={
            "1": [
                # Out of order, as the site may send them: a reply first.
                comment(
                    12,
                    "<p>Agreed</p>",
                    parent=11,
                    author="b2",
                    at="2024-05-02T00:00:00Z",
                ),
                comment(
                    11,
                    '<p>See <ac:link><ri:page ri:content-title="Guide"/></ac:link>, '
                    '<ac:link><ri:user ri:account-id="b2"/></ac:link></p>',
                ),
                comment(
                    13,
                    "<p>Typo here</p>",
                    at="2024-05-03T00:00:00Z",
                    selection="teh word",
                ),
            ]
        },
    )
    home = by_title(mapped)["Home"]
    first, reply, inline = home["comments"]
    assert first["external_ref"] == "confluence-comment:11"
    assert first["author_handle"] == "Robin Ade"
    assert first["mention_handles"] == ["Sam Bee"]
    (paragraph,) = first["content"]["root"]["children"]
    assert paragraph["children"][1]["importSlug"] == "guide"
    # The reply follows what it answers.
    assert reply["reply_to_ref"] == "confluence-comment:11"
    # An inline comment quotes what it was anchored to.
    quote = inline["content"]["root"]["children"][0]
    assert quote["type"] == "quote" and quote["children"][0]["text"] == "teh word"
    assert mapped.comments == 3
    assert mapped.people == {"Robin Ade": 2, "Sam Bee": 2}
    WikiEnvelope.model_validate(mapped.envelope)


def test_a_comment_is_read_from_the_sites_answer():
    read = cm.read_comment(
        {
            "id": "501",
            "parentCommentId": "500",
            "version": {"authorId": "a1", "createdAt": "2024-05-01T10:00:00.000Z"},
            "properties": {"inlineOriginalSelection": "the words"},
            "body": {"storage": {"value": "<p>hello</p>"}},
        }
    )
    assert read == cm.SourceComment(
        id="501",
        body="<p>hello</p>",
        parent_id="500",
        author_id="a1",
        created_at="2024-05-01T10:00:00.000Z",
        selection="the words",
    )
    # A reply read under its parent names that parent.
    assert (
        cm.read_comment(
            {"id": "7", "body": {"storage": {"value": "<p>x</p>"}}}, parent_id="3"
        ).parent_id
        == "3"
    )
    assert cm.read_comment({"id": "8", "body": {"storage": {"value": "  "}}}) is None
    assert cm.read_comment({"id": "abc"}) is None
