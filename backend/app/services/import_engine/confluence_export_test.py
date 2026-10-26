"""A Confluence space's HTML export: the tree, the bodies translated back to
storage format, and the files beside them."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.services.import_engine import confluence_export as ce
from app.services.import_engine.confluence_storage import storage_to_lexical
from app.services.import_engine.jira_attachments import AssetBudget


PNG = b"\x89PNG\r\n\x1a\nchart"
PDF = b"%PDF-spec"


def _page(title, main, *, crumbs=(), attachments=""):
    trail = "".join(
        f'<li><span><a href="{href}">{text}</a></span></li>' for href, text in crumbs
    )
    return f"""<!DOCTYPE html>
<html><head><title>Team Docs : {title}</title></head><body>
<div id="page"><div id="main" class="aui-page-panel">
<div id="main-header">
<div id="breadcrumb-section"><ol id="breadcrumbs">
<li class="first"><span><a href="index.html">Team Docs</a></span></li>{trail}
</ol></div>
<h1 id="title-heading" class="pagetitle"><span id="title-text"> Team Docs : {title} </span></h1>
</div>
<div id="content" class="view">
<div class="page-metadata">Created by <span class='author'> Robin Ade</span>, last modified on Sep 20, 2026</div>
<div id="main-content" class="wiki-content group">{main}</div>
{attachments}
</div></div></div></body></html>"""


INDEX = """<html><head><title>DOCS (Team Docs)</title></head><body>
<h1 id="title-heading"><span id="title-text">Space Details:</span></h1>
<div id="main-content" class="pageSection"><table class="confluenceTable">
<tr><th class="confluenceTh">Key</th><td class="confluenceTd">DOCS</td></tr>
<tr><th class="confluenceTh">Name</th><td class="confluenceTd">Team Docs</td></tr>
</table></div>
<div class="pageSection"><div class="pageSectionHeader">
<h2 class="pageSectionTitle">Available Pages:</h2></div>
<ul>
  <li><a href="Home_100.html">Home</a>
    <ul><li><a href="Guide_200.html">Guide</a></li></ul>
    <ul><li><a href="Runbook_300.html">Runbook</a></li></ul>
  </li>
</ul></div></body></html>"""

HOME = _page(
    "Home",
    """<p>Welcome, see <a href="Guide_200.html">the guide</a> and
<a class="confluence-userlink user-mention" href="/wiki/people/abc">Sam Bee</a>.</p>
<p><span class="status-macro aui-lozenge aui-lozenge-success">DONE</span>
<span class="jira-issue" data-jira-key="SCRUM-1"><a href="https://acme.atlassian.net/browse/SCRUM-1" class="jira-issue-key">SCRUM-1</a> - Fix it</span></p>
<div class="confluence-information-macro confluence-information-macro-warning">
<span class="aui-icon confluence-information-macro-icon"></span>
<div class="confluence-information-macro-body"><p>Mind the gap</p></div></div>
<div class="code panel pdl"><div class="codeHeader panelHeader pdl"><b>setup.sh</b></div>
<div class="codeContent panelContent pdl"><pre class="syntaxhighlighter-pre" data-syntaxhighlighter-params="brush: bash; gutter: false">echo "&lt;hi&gt;"</pre></div></div>
<ul class="inline-task-list"><li class="checked">Ship it</li><li>Tell people</li></ul>
<p><span class="confluence-embedded-file-wrapper"><img class="confluence-embedded-image" src="attachments/100/501.png" data-image-src="attachments/100/501.png" data-linked-resource-default-alias="chart.png" alt="chart"></span></p>
<p><a href="attachments/100/502.pdf">the spec</a></p>""",
    attachments="""<div class="pageSection group"><div class="pageSectionHeader">
<h2 id="attachments" class="pageSectionTitle">Attachments:</h2></div>
<div class="greybox" align="left">
<img src="images/icons/bullet_blue.gif" height="8" width="8" alt=""/>
<a href="attachments/100/501.png">chart.png</a> (image/png)<br/>
<img src="images/icons/bullet_blue.gif" height="8" width="8" alt=""/>
<a href="attachments/100/502.pdf">spec.pdf</a> (application/pdf)<br/>
</div></div>""",
)

GUIDE = _page(
    "Guide",
    "<h2>Steps</h2><p>Do the thing.</p>",
    crumbs=[("Home_100.html", "Home")],
)

RUNBOOK = _page("Runbook", "<p>Break glass.</p>", crumbs=[("Home_100.html", "Home")])
# Not in the index, so its place comes from its breadcrumbs.
ORPHAN = _page(
    "Loose Notes",
    "<p>Somewhere</p>",
    crumbs=[("Home_100.html", "Home"), ("Guide_200.html", "Guide")],
)


def export_bytes(**extra) -> bytes:
    """A space export, laid out the way Confluence writes one."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        files = {
            "DOCS/index.html": INDEX,
            "DOCS/Home_100.html": HOME,
            "DOCS/Guide_200.html": GUIDE,
            "DOCS/Runbook_300.html": RUNBOOK,
            "DOCS/Loose-Notes_400.html": ORPHAN,
            "DOCS/attachments/100/501.png": PNG,
            "DOCS/attachments/100/502.pdf": PDF,
            "DOCS/styles/site.css": "body {}",
            **extra,
        }
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def export_zip(**extra) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(export_bytes(**extra)))


def test_the_tree_comes_from_the_index_and_the_breadcrumbs():
    space = ce.read_export(export_zip())
    assert (space.key, space.name) == ("DOCS", "Team Docs")
    by_title = {page.title: page for page in space.pages}
    assert set(by_title) == {"Home", "Guide", "Runbook", "Loose Notes"}
    assert by_title["Home"].parent_file is None and by_title["Home"].id == "100"
    assert (by_title["Guide"].parent_file, by_title["Guide"].position) == (
        "Home_100.html",
        0,
    )
    assert (by_title["Runbook"].parent_file, by_title["Runbook"].position) == (
        "Home_100.html",
        1,
    )
    assert by_title["Loose Notes"].parent_file == "Guide_200.html"
    assert by_title["Home"].author == "Robin Ade"
    assert by_title["Home"].created_at == "2026-09-20"
    assert space.users == {"name:Robin Ade": "Robin Ade", "name:Sam Bee": "Sam Bee"}
    assert space.site_url == "https://acme.atlassian.net"


def test_the_attachments_section_names_each_file():
    space = ce.read_export(export_zip())
    home = next(page for page in space.pages if page.title == "Home")
    assert [(a.filename, a.media_type) for a in home.attachments] == [
        ("chart.png", "image/png"),
        ("spec.pdf", "application/pdf"),
    ]


def _children(node):
    return node.get("children") or []


def test_a_rendered_body_converts_like_the_page_it_was_rendered_from():
    space = ce.read_export(export_zip())
    home = next(page for page in space.pages if page.title == "Home")
    result = storage_to_lexical(
        home.body,
        page=lambda title, key: ce.confluence_mapping.PageTarget(slug=title.lower()),
        user=lambda account: space.users.get(account),
        image=lambda name: f"/uploads/1/{name}",
        file=lambda name: f"entry:assets/{name}",
        site_url=space.site_url,
    )
    blocks = result.content["root"]["children"]
    kinds = [block["type"] for block in blocks]
    assert "callout" in kinds and "code" in kinds and "list" in kinds

    flat: list[dict] = []

    def walk(node):
        flat.append(node)
        for child in _children(node):
            walk(child)

    for block in blocks:
        walk(block)
    mention = next(n for n in flat if n.get("importSlug"))
    assert mention["importSlug"] == "guide" and mention["text"] == "the guide"
    assert any(
        n.get("type") == "mention" and n["mentionName"] == "Sam Bee" for n in flat
    )
    status = next(n for n in flat if n.get("type") == "status")
    assert (status["text"], status["color"]) == ("DONE", "green")
    assert any(n.get("importJiraKey") == "SCRUM-1" for n in flat)
    image = next(n for n in flat if n.get("type") == "image")
    assert image["src"] == "/uploads/1/chart.png"
    file_mention = next(n for n in flat if n.get("importRef"))
    assert file_mention["importRef"] == "entry:assets/spec.pdf"
    code = next(block for block in blocks if block["type"] == "code")
    assert code["language"] == "bash"
    assert "".join(n.get("text", "") for n in _children(code)) == 'echo "<hi>"'
    checklist = next(
        block
        for block in blocks
        if block["type"] == "list" and block["listType"] == "check"
    )
    assert [item["checked"] for item in _children(checklist)] == [True, False]
    assert result.mentions == ["Sam Bee"]


async def _discard(stored, data):
    pass


async def test_the_export_maps_to_a_wiki_with_its_files():
    fetched, site = await ce.export_to_fetched(
        export_zip(),
        guild_id=1,
        app_version="0.0.0-test",
        asset_budget=AssetBudget(bytes_left=10_000_000, files_left=100),
        store=_discard,
        files_allowed=True,
    )
    ((key, wiki),) = fetched.envelopes
    assert key == "DOCS" and wiki["name"] == "Team Docs"
    assert wiki["home_page"] == "home"
    pages = {page["title"]: page for page in wiki["pages"]}
    assert pages["Guide"]["parent"] == "home"
    assert pages["Home"]["author_handle"] == "Robin Ade"
    assert [image.filename for image in fetched.images] == ["chart.png"]
    ((page_file),) = fetched.files["DOCS"]
    assert page_file.stored.filename == "spec.pdf" and page_file.page_slug == "home"
    assert fetched.report.pages == 4
    assert site == "https://acme.atlassian.net"


async def test_without_a_budget_no_file_is_read():
    fetched, _site = await ce.export_to_fetched(
        export_zip(),
        guild_id=1,
        app_version="0.0.0-test",
        asset_budget=None,
        files_allowed=True,
    )
    assert fetched.images == [] and fetched.files == {}
    assert fetched.report.attachments == 2


def test_a_zip_with_no_pages_is_not_an_export():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")
    with pytest.raises(ce.ImportEngineError):
        ce.read_export(zipfile.ZipFile(io.BytesIO(buffer.getvalue())))


# --- the real IMPTEST export -------------------------------------------------------

REAL = Path(__file__).parent / "fixtures" / "confluence_export"


def real_export_bytes() -> bytes:
    """The fixture space as Confluence zipped it — root directory entry and
    all."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("/"), "")
        for path in sorted(REAL.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(REAL).as_posix())
    return buffer.getvalue()


def _real_fetched():
    from app.services.import_engine.zip_bounds import open_zip
    from app.services.import_engine.jira_attachments import bundle_budget

    return ce.export_to_fetched(
        open_zip(real_export_bytes()),
        guild_id=1,
        app_version="0.0.0-test",
        asset_budget=bundle_budget(),
        store=_discard,
        files_allowed=True,
    )


def _texts(node) -> str:
    return (node.get("text") or "") + "".join(_texts(c) for c in _children(node))


def test_a_real_export_opens_despite_its_root_entry():
    space = ce.read_export(zipfile.ZipFile(io.BytesIO(real_export_bytes())))
    assert (space.key, space.name) == ("IMPTEST", "Initiative Import Test")
    assert space.site_url == "https://morels.atlassian.net"
    by_title = {page.title: page for page in space.pages}
    by_file = {page.file: page for page in space.pages}

    def parent(title):
        page = by_title[title]
        return by_file[page.parent_file].title if page.parent_file else None

    assert parent("Initiative Import Test Home") is None
    assert parent("Migrations Runbook") == "Database Design"
    # Siblings each sit in a list of their own in index.html, and are still
    # counted as one run.
    engineering = sorted(
        (p for p in space.pages if parent(p.title) == "Engineering"),
        key=lambda p: p.position,
    )
    assert [p.title for p in engineering] == [
        "Architecture Overview",
        "API Reference",
        "Onboarding Checklist",
        "Restricted: Incident Postmortem",
    ]
    assert by_title["Q&A: What / Why? <Special> \"Chars\" & 'Quotes' #1 %20"]


async def test_a_real_export_converts_its_macros():
    fetched, _site = await _real_fetched()
    ((_key, wiki),) = fetched.envelopes
    pages = {page["title"]: page for page in wiki["pages"]}
    assert wiki["home_page"] == "initiative-import-test-home"

    architecture = pages["Architecture Overview"]["content"]["root"]["children"]
    kinds = [block["type"] for block in architecture]
    assert "layout-container" in kinds and kinds.count("callout") >= 5
    # The table of contents is the wiki's to draw.
    assert "Summary" not in _texts(architecture[0])
    link = next(
        n
        for block in architecture
        for n in _flat(block)
        if n.get("importSlug") == "engineering"
    )
    assert link["type"] == "entity-mention"

    kickoff = pages["2026-09-01 Kickoff"]["content"]["root"]["children"]
    checklists = [
        b for b in kickoff if b["type"] == "list" and b["listType"] == "check"
    ]
    assert [item["checked"] for item in _children(checklists[-1])] == [True]

    gallery = _texts(pages["Macros Gallery"]["content"]["root"])
    # The attachments macro's upload form is not the page's content.
    assert "Drag and drop" not in gallery and "Upload file" not in gallery

    emoji = _texts(pages["Émojis & Ünïcode 🚀 日本語 العربية"]["content"]["root"])
    assert "🎉" in emoji and "content.emoticon" not in emoji

    label_list = pages["Meeting Notes"]["content"]["root"]["children"][-1]
    assert [_texts(item) for item in _children(label_list)] == [
        "2026-09-01 Kickoff",
        "2026-09-15 Sprint Review",
    ]


async def test_a_real_exports_files_come_under_their_pages():
    fetched, _site = await _real_fetched()
    assert sorted(image.filename for image in fetched.images) == [
        "architecture-diagram.png",
        "guepinia-helvelloides6.jpg",
        "team photo (2026).png",
    ]
    files = {f.stored.filename: f.page_slug for f in fetched.files["IMPTEST"]}
    assert files == {
        "design-spec.pdf": "attachments-images",
        "roadmap-export.csv": "attachments-images",
        "notes ünïcode.txt": "attachments-images",
        "16102826_25637542_proof.pdf": "inline-pdf-and-images",
    }


def _flat(node):
    yield node
    for child in _children(node):
        yield from _flat(child)
