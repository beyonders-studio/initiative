"""A Confluence space's HTML export, read into the same bundle a site fetch
writes (design §6.2, P3).

Space settings → Export space → HTML gives a zip anybody can download, with
no token and from a site this server cannot reach — a Data Center install on
a private network included. It holds one HTML file per page, the page tree in
``index.html``, and every attachment under ``attachments/<page id>/``.

The pages are rendered HTML, not the storage format a site hands the API, so
each body is translated back into the storage constructs it was rendered
from — a status pill, a panel, a code block, an issue, a link to another page
or to a file — and then goes through the one walker the site fetch uses.
From there it is the same mapping, the same attachments, the same bundle.
"""

from __future__ import annotations

import asyncio
import html
import logging
import mimetypes
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

from app.core.messages import ImportEngineMessages
from app.services.import_engine import confluence_attachments, confluence_mapping
from app.services.import_engine.confluence_fetch import (
    _ENVELOPE_RESERVE_BYTES,
    ConfluenceFetched,
    Gathered,
)
from app.services.import_engine.confluence_storage import _Element, _parse, _text_of
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.jira_attachments import AssetBudget, AssetSink
from app.services.import_engine import limits as import_limits
from app.services.import_engine.zip_bounds import read_member

logger = logging.getLogger(__name__)

#: A page file names its page id: ``Page-Title_123456.html`` from a cloud
#: site, ``123456.html`` from an older one.
_PAGE_ID = re.compile(r"(?:^|_)(\d+)\.html$")

#: A lozenge's colour, by the class the export draws it with.
_LOZENGE_COLOURS = {
    "aui-lozenge-success": "Green",
    "aui-lozenge-error": "Red",
    "aui-lozenge-current": "Yellow",
    "aui-lozenge-moved": "Yellow",
    "aui-lozenge-complete": "Blue",
    "aui-lozenge-progress": "Purple",
}

#: A panel's macro, by the class the export draws it with.
_PANELS = {
    "confluence-information-macro-information": "info",
    "confluence-information-macro-note": "note",
    "confluence-information-macro-warning": "warning",
    "confluence-information-macro-tip": "tip",
}

_BRUSH = re.compile(r"brush:\s*([\w+#-]+)")
_MIME_NOTE = re.compile(r"\(([\w.+-]+/[\w.+-]+)\)")
_DATE = re.compile(r"on ([A-Z][a-z]{2} \d{1,2}, \d{4})")

#: Pages synthesised an id when their file does not carry one, far from any
#: real Confluence id so the two cannot meet.
_SYNTHETIC_ID_BASE = 9_000_000_000

_VOID = frozenset({"br", "hr", "img", "col", "input", "meta", "link"})


@dataclass(frozen=True)
class ExportAttachment:
    """A file in the export, by where it sits in the zip."""

    path: str
    filename: str
    media_type: str
    size: int


@dataclass
class ExportPage:
    id: str
    title: str
    file: str
    parent_file: Optional[str]
    position: Optional[int]
    #: The body, translated to storage format.
    body: str
    author: Optional[str] = None
    created_at: Optional[str] = None
    attachments: list[ExportAttachment] = field(default_factory=list)


@dataclass
class ExportSpace:
    key: str
    name: str
    pages: list[ExportPage]
    #: Everybody the pages name, by the synthetic account id given them.
    users: dict[str, str]
    #: The site the pages link issues to, when one of them does.
    site_url: str
    #: Pages past what may be held at once, and so left out.
    left_behind: int = 0


def _classes(element: _Element) -> set[str]:
    return set(element.attr("class").split())


def _walk(element: _Element):
    yield element
    for child in element.elements():
        yield from _walk(child)


def _find(element: _Element, predicate) -> Optional[_Element]:
    return next((e for e in _walk(element) if predicate(e)), None)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _user_ref(name: str) -> str:
    """The account id a person is given, since an export names people by
    their display name alone."""
    return f"name:{name}"


# --- Reading the zip ---------------------------------------------------------


def _root(names: list[str]) -> str:
    """The folder the space was exported into — the one holding the
    shallowest ``index.html``, or wherever the pages are."""
    indexes = sorted(
        (n for n in names if posixpath.basename(n) == "index.html"),
        key=lambda n: n.count("/"),
    )
    if indexes:
        return posixpath.dirname(indexes[0])
    pages = sorted(
        (n for n in names if n.endswith(".html")), key=lambda n: n.count("/")
    )
    if not pages:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)
    return posixpath.dirname(pages[0])


def _read(archive: zipfile.ZipFile, name: str) -> str:
    """One HTML file of the export, read up to the envelope cap: a page is
    held to what one envelope may carry."""
    data = read_member(archive, name, max_bytes=import_limits.IMPORT_MAX_ENVELOPE_BYTES)
    return data.decode("utf-8", errors="replace")


def read_export(archive: zipfile.ZipFile) -> ExportSpace:
    """The space an HTML export holds: its pages in tree order, each with its
    parent, its body in storage format, and the files attached to it.

    A page at a time: every page is parsed once for its title, which a link
    from any other page may need, and again when its body is translated, so
    no more than one page's tree is held at once. The translated bodies are
    held within the size a zip's whole content may declare
    (``IMPORT_MAX_ZIP_UNCOMPRESSED_BYTES``); the pages past it are left out
    and counted, as the pages past a space's budget are. Blocking; run it in
    a thread from async code."""
    names = [info.filename for info in archive.infolist() if not info.is_dir()]
    root = _root(names)
    prefix = f"{root}/" if root else ""
    page_files = sorted(
        posixpath.basename(n)
        for n in names
        if n.startswith(prefix)
        and n.endswith(".html")
        and "/" not in n[len(prefix) :]
        and posixpath.basename(n) != "index.html"
    )
    if not page_files:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)
    sizes = {info.filename: info.file_size for info in archive.infolist()}

    index_name = f"{prefix}index.html"
    index = _parse(_read(archive, index_name)) if index_name in sizes else None
    details = _space_details(index) if index is not None else {}
    key = details.get("key") or posixpath.basename(root) or "SPACE"
    name = details.get("name") or key
    tree = _index_tree(index, set(page_files)) if index is not None else {}
    del index

    titles = {
        file: _page_title(_parse(_read(archive, prefix + file)), name, key) or file
        for file in page_files
    }

    ids: dict[str, str] = {}
    for offset, file in enumerate(page_files):
        match = _PAGE_ID.search(file)
        ids[file] = match.group(1) if match else str(_SYNTHETIC_ID_BASE + offset)
    titles_by_id = {ids[file]: titles[file] for file in page_files}

    users: dict[str, str] = {}
    site = ""
    pages: list[ExportPage] = []
    held = 0
    for file in page_files:
        doc = _parse(_read(archive, prefix + file))
        attachments = _listed_attachments(doc, prefix, sizes)
        translator = _Translator(
            page_titles=titles,
            titles_by_id=titles_by_id,
            attachments={a.path[len(prefix) :]: a for a in attachments},
            prefix=prefix,
            sizes=sizes,
        )
        main = _find(doc, lambda e: e.attr("id") == "main-content")
        body = translator.markup(main.children) if main is not None else ""
        held += len(body)
        if held > import_limits.IMPORT_MAX_ZIP_UNCOMPRESSED_BYTES:
            break
        for extra in translator.found_attachments:
            if extra.path not in {a.path for a in attachments}:
                attachments.append(extra)
        users.update({_user_ref(n): n for n in translator.people})
        site = site or translator.site_url
        author, created = _metadata(doc)
        if author:
            users[_user_ref(author)] = author
        parent, position = tree.get(file, (None, None))
        if file not in tree:
            parent = _breadcrumb_parent(doc, set(page_files))
        pages.append(
            ExportPage(
                id=ids[file],
                title=titles[file],
                file=file,
                parent_file=parent,
                position=position,
                body=body,
                author=author,
                created_at=created,
                attachments=attachments,
            )
        )
    return ExportSpace(
        key=key,
        name=name,
        pages=pages,
        users=users,
        site_url=site,
        left_behind=len(page_files) - len(pages),
    )


def _space_details(index: _Element) -> dict[str, str]:
    """The space's key and name, from the table the export opens
    ``index.html`` with."""
    details: dict[str, str] = {}
    for row in (e for e in _walk(index) if e.tag == "tr"):
        header = next((c for c in row.elements() if c.tag == "th"), None)
        value = next((c for c in row.elements() if c.tag == "td"), None)
        if header is None or value is None:
            continue
        label = _clean(_text_of(header)).lower()
        if label in ("key", "name"):
            details[label] = _clean(_text_of(value))
    return details


def _page_title(doc: _Element, space_name: str, key: str) -> str:
    heading = _find(doc, lambda e: e.attr("id") == "title-text")
    element = heading or _find(doc, lambda e: e.tag == "title")
    text = _clean(_text_of(element)) if element is not None else ""
    # Rendered as "<space> : <page>".
    for lead in (space_name, key):
        if lead and text.startswith(f"{lead} : "):
            return text[len(lead) + 3 :].strip()
    return text


def _index_tree(
    index: _Element, page_files: set[str]
) -> dict[str, tuple[Optional[str], int]]:
    """Each page's parent and place among its siblings, from the list of
    pages the export draws in ``index.html`` — where each child is a list of
    its own, so siblings are counted across every list under one parent."""
    tree: dict[str, tuple[Optional[str], int]] = {}
    counts: dict[Optional[str], int] = {}

    def page_of(item: _Element) -> Optional[str]:
        link = next((e for e in item.elements() if e.tag == "a"), None)
        href = link.attr("href") if link is not None else ""
        return href if href in page_files else None

    def walk(container: _Element, parent: Optional[str]) -> None:
        for listing in container.elements():
            if listing.tag not in ("ul", "ol"):
                continue
            for item in listing.elements():
                if item.tag != "li":
                    continue
                file = page_of(item)
                if file is None or file in tree:
                    continue
                tree[file] = (parent, counts.get(parent, 0))
                counts[parent] = counts.get(parent, 0) + 1
                walk(item, file)

    listing = next(
        (
            e
            for e in _walk(index)
            if e.tag == "ul"
            and any(page_of(item) for item in e.elements() if item.tag == "li")
        ),
        None,
    )
    if listing is not None:
        # The lists sit side by side in one section; walk the section.
        section = _parent_of(index, listing) or listing
        walk(section, None)
    return tree


def _parent_of(root: _Element, target: _Element) -> Optional[_Element]:
    for element in _walk(root):
        if any(child is target for child in element.elements()):
            return element
    return None


def _breadcrumb_parent(doc: _Element, page_files: set[str]) -> Optional[str]:
    crumbs = _find(doc, lambda e: e.attr("id") == "breadcrumbs")
    if crumbs is None:
        return None
    links = [e.attr("href") for e in _walk(crumbs) if e.tag == "a"]
    parents = [href for href in links if href in page_files]
    return parents[-1] if parents else None


def _metadata(doc: _Element) -> tuple[Optional[str], Optional[str]]:
    """Who wrote the page and when, from the line the export prints under
    its title."""
    line = _find(doc, lambda e: "page-metadata" in _classes(e))
    if line is None:
        return None, None
    author_span = _find(line, lambda e: "author" in _classes(e))
    author = _clean(_text_of(author_span)) if author_span is not None else None
    created = None
    match = _DATE.search(_clean(_text_of(line)))
    if match:
        try:
            created = datetime.strptime(match.group(1), "%b %d, %Y").date().isoformat()
        except ValueError:
            created = None
    return author or None, created


def _listed_attachments(
    doc: _Element, prefix: str, sizes: dict[str, int]
) -> list[ExportAttachment]:
    """The files the page's "Attachments" section lists, with the names and
    types it gives them."""
    heading = _find(doc, lambda e: e.attr("id") == "attachments")
    if heading is None:
        return []
    section = _section_of(doc, heading)
    found: list[ExportAttachment] = []
    children = list(section.children) if section is not None else []
    flat: list[Union[_Element, str]] = []

    def flatten(nodes: list[Union[_Element, str]]) -> None:
        for node in nodes:
            flat.append(node)
            if isinstance(node, _Element) and node.tag != "a":
                flatten(node.children)

    flatten(children)
    for index, node in enumerate(flat):
        if not isinstance(node, _Element) or node.tag != "a":
            continue
        href = html.unescape(node.attr("href")).split("?")[0]
        path = prefix + href
        if not href.startswith("attachments/") or path not in sizes:
            continue
        after = next((n for n in flat[index + 1 :] if isinstance(n, str)), "")
        mime = _MIME_NOTE.search(after)
        filename = _clean(_text_of(node)) or posixpath.basename(href)
        found.append(
            ExportAttachment(
                path=path,
                filename=filename,
                media_type=(mime.group(1) if mime else _guess(filename)).lower(),
                size=sizes[path],
            )
        )
    return found


def _section_of(doc: _Element, heading: _Element) -> Optional[_Element]:
    """The ``pageSection`` block a heading sits in."""
    for element in _walk(doc):
        if "pageSection" in _classes(element) and any(
            e is heading for e in _walk(element)
        ):
            return element
    return None


def _guess(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


# --- Translating a rendered body back to storage format ---------------------


class _Translator:
    """A rendered page body as the storage format it was rendered from."""

    def __init__(
        self,
        *,
        page_titles: dict[str, str],
        titles_by_id: dict[str, str],
        attachments: dict[str, ExportAttachment],
        prefix: str,
        sizes: dict[str, int],
    ) -> None:
        self.page_titles = page_titles
        self.titles_by_id = titles_by_id
        self.attachments = attachments
        self.prefix = prefix
        self.sizes = sizes
        self.people: set[str] = set()
        self.found_attachments: list[ExportAttachment] = []
        self.site_url = ""

    def markup(self, nodes: list[Union[_Element, str]]) -> str:
        return "".join(self.node(node) for node in nodes)

    def node(self, node: Union[_Element, str]) -> str:
        if isinstance(node, str):
            return html.escape(node, quote=False)
        tag = node.tag
        classes = _classes(node)
        if tag in _DROPPED_TAGS or classes & _DROPPED_CLASSES:
            return ""
        if tag == "img":
            return self.image(node)
        if tag == "a":
            return self.anchor(node)
        if tag == "span" and "status-macro" in classes:
            return self.status(node, classes)
        if tag == "span" and "jira-issue" in classes:
            return self.jira(node)
        if tag == "div" and "confluence-information-macro" in classes:
            return self.panel(node, classes)
        if tag == "div" and "code" in classes and "panel" in classes:
            return self.code(node)
        if tag == "div" and "expand-container" in classes:
            return self.expand(node)
        if tag == "ul" and "inline-task-list" in classes:
            return self.task_list(node)
        if tag == "ul" and "content-by-label" in classes:
            return self.page_list(node)
        if tag == "p" and "media-group" in classes:
            # File cards side by side: one to a line.
            cards = [self.node(child) for child in node.elements()]
            return f"<p>{'<br/>'.join(card for card in cards if card)}</p>"
        if tag == "ul" and "decision-list" in classes:
            # What was decided: each one ticked, as a decision log reads.
            return self.task_list(node, all_done=True)
        if tag == "div" and "contentLayout2" in classes:
            return f"<ac:layout>{self.markup(node.children)}</ac:layout>"
        if tag == "div" and "columnLayout" in classes:
            return self.layout_section(node)
        if tag == "div" and "cell" in classes:
            return f"<ac:layout-cell>{self.markup(node.children)}</ac:layout-cell>"
        if tag == "div" and "panel" in classes:
            content = _find(node, lambda e: "panelContent" in _classes(e))
            inner = self.markup(
                content.children if content is not None else node.children
            )
            return _macro("panel", {}, rich_body=inner)
        return self.element(tag, node.attrs, node.children)

    def element(
        self, tag: str, attrs: dict[str, str], children: list[Union[_Element, str]]
    ) -> str:
        kept = {k: v for k, v in attrs.items() if k in _KEPT_ATTRS}
        rendered = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in kept.items()
        )
        if tag in _VOID:
            return f"<{tag}{rendered}/>"
        return f"<{tag}{rendered}>{self.markup(children)}</{tag}>"

    def attachment_at(self, src: str, alias: str = "") -> Optional[ExportAttachment]:
        href = html.unescape(src).split("?")[0]
        if not href.startswith("attachments/"):
            return None
        known = self.attachments.get(href)
        if known is not None:
            return known
        path = self.prefix + href
        if path not in self.sizes:
            return None
        filename = alias or posixpath.basename(href)
        found = ExportAttachment(
            path=path,
            filename=filename,
            media_type=_guess(filename),
            size=self.sizes[path],
        )
        self.attachments[href] = found
        self.found_attachments.append(found)
        return found

    def image(self, node: _Element) -> str:
        if "emoticon" in _classes(node):
            return html.escape(node.attr("data-emoji-fallback"), quote=False)
        self.note_base(node)
        src = node.attr("data-image-src") or node.attr("src")
        found = self.attachment_at(src, node.attr("data-linked-resource-default-alias"))
        if found is not None:
            width = node.attr("width") or node.attr("data-width")
            return (
                f'<ac:image ac:alt="{html.escape(node.attr("alt"), quote=True)}"'
                + (f' ac:width="{html.escape(width, quote=True)}"' if width else "")
                + f'><ri:attachment ri:filename="{html.escape(found.filename, quote=True)}"/>'
                "</ac:image>"
            )
        if src.startswith(("http://", "https://")) and not _signed(src):
            return self.element("img", node.attrs, [])
        # The export's own icons and emoticons: what they meant, if anything.
        alt = node.attr("alt")
        return html.escape(alt, quote=False) if alt and not alt.startswith("(") else ""

    def note_base(self, node: _Element) -> None:
        """The site the export came from, where an element names it."""
        base = node.attr("data-base-url")
        if base and not self.site_url:
            self.site_url = base.removesuffix("/wiki").rstrip("/")

    def anchor(self, node: _Element) -> str:
        href = html.unescape(node.attr("href"))
        classes = _classes(node)
        text = _clean(_text_of(node))
        self.note_base(node)
        # A page named by id, wherever the link points: another page of this
        # space, even when the export wrote the site's address for it.
        if node.attr("data-linked-resource-type") == "page":
            title = self.titles_by_id.get(node.attr("data-linked-resource-id"))
            if title is not None:
                return (
                    f'<ac:link><ri:page ri:content-title="{html.escape(title, quote=True)}"/>'
                    f"<ac:link-body>{self.markup(node.children)}</ac:link-body></ac:link>"
                )
        if "confluence-embedded-file" in classes:
            # A file card: its name, not the preview drawn inside it.
            found = self.attachment_at(
                href, node.attr("data-linked-resource-default-alias")
            )
            if found is not None:
                return (
                    f'<ac:link><ri:attachment ri:filename="{html.escape(found.filename, quote=True)}"/>'
                    "</ac:link>"
                )
        if classes & {"user-mention", "confluence-userlink"} and text:
            name = text.lstrip("@")
            self.people.add(name)
            return (
                f'<ac:link><ri:user ri:account-id="{html.escape(_user_ref(name), quote=True)}"/>'
                "</ac:link>"
            )
        page_file = href.split("#")[0]
        if page_file in self.page_titles:
            title = self.page_titles[page_file]
            return (
                f'<ac:link><ri:page ri:content-title="{html.escape(title, quote=True)}"/>'
                f"<ac:link-body>{self.markup(node.children)}</ac:link-body></ac:link>"
            )
        found = self.attachment_at(href)
        if found is not None:
            return (
                f'<ac:link><ri:attachment ri:filename="{html.escape(found.filename, quote=True)}"/>'
                f"<ac:link-body>{self.markup(node.children)}</ac:link-body></ac:link>"
            )
        match = re.match(r"(https?://[^/]+)/browse/", href)
        if match and not self.site_url:
            self.site_url = match.group(1)
        return self.element("a", node.attrs, node.children)

    def status(self, node: _Element, classes: set[str]) -> str:
        colour = next(
            (_LOZENGE_COLOURS[c] for c in classes if c in _LOZENGE_COLOURS), "Grey"
        )
        return _macro(
            "status", {"title": _clean(_text_of(node)), "colour": colour}, inline=True
        )

    def jira(self, node: _Element) -> str:
        key = node.attr("data-jira-key")
        link = _find(node, lambda e: e.tag == "a" and "/browse/" in e.attr("href"))
        if link is not None and not self.site_url:
            match = re.match(
                r"(https?://[^/]+)/browse/", html.unescape(link.attr("href"))
            )
            if match:
                self.site_url = match.group(1)
        if not key:
            return self.markup(node.children)
        return _macro("jira", {"key": key}, inline=True)

    def panel(self, node: _Element, classes: set[str]) -> str:
        name = next((_PANELS[c] for c in classes if c in _PANELS), "info")
        body = _find(node, lambda e: "confluence-information-macro-body" in _classes(e))
        title = _find(node, lambda e: "title" in _classes(e) and e.tag == "p")
        params = {"title": _clean(_text_of(title))} if title is not None else {}
        inner = self.markup(body.children if body is not None else node.children)
        return _macro(name, params, rich_body=inner)

    def code(self, node: _Element) -> str:
        pre = _find(node, lambda e: e.tag == "pre")
        source = _text_of(pre) if pre is not None else _text_of(node)
        params: dict[str, str] = {}
        brush = (
            _BRUSH.search(pre.attr("data-syntaxhighlighter-params")) if pre else None
        )
        if brush:
            params["language"] = brush.group(1)
        header = _find(node, lambda e: "codeHeader" in _classes(e))
        if header is not None and _clean(_text_of(header)):
            params["title"] = _clean(_text_of(header))
        return _macro("code", params, plain_body=source)

    def expand(self, node: _Element) -> str:
        title = _find(node, lambda e: "expand-control-text" in _classes(e))
        content = _find(node, lambda e: "expand-content" in _classes(e))
        params = {"title": _clean(_text_of(title))} if title is not None else {}
        inner = self.markup(content.children if content is not None else [])
        return _macro("expand", params, rich_body=inner)

    def page_list(self, node: _Element) -> str:
        """A list of pages a macro gathered: each page's link, and nothing of
        the icons and labels drawn around it."""
        items = []
        for item in node.elements():
            if item.tag != "li":
                continue
            link = _find(
                item, lambda e: e.tag == "a" and e.attr("data-linked-resource-id")
            )
            if link is not None:
                items.append(f"<li>{self.anchor(link)}</li>")
        return f"<ul>{''.join(items)}</ul>" if items else ""

    def layout_section(self, node: _Element) -> str:
        kind = node.attr("data-layout") or next(
            (c for c in _classes(node) if c in _LAYOUTS), "single"
        )
        return (
            f'<ac:layout-section ac:type="{_LAYOUTS.get(kind, "single")}">'
            f"{self.markup(node.children)}</ac:layout-section>"
        )

    def task_list(self, node: _Element, *, all_done: bool = False) -> str:
        tasks = []
        for item in node.elements():
            if item.tag != "li":
                continue
            done = all_done or "checked" in _classes(item)
            tasks.append(
                "<ac:task><ac:task-status>"
                + ("complete" if done else "incomplete")
                + f"</ac:task-status><ac:task-body>{self.markup(item.children)}"
                "</ac:task-body></ac:task>"
            )
        return f"<ac:task-list>{''.join(tasks)}</ac:task-list>"


#: Elements an export draws that carry nothing a reader wrote: a form the
#: attachments macro renders, and the export's own scripts and styles.
_DROPPED_TAGS = frozenset(
    {"script", "style", "x-cdata", "form", "input", "fieldset", "iframe", "button"}
)

#: Blocks the export renders that are not the page's content: the table of
#: contents (the wiki draws its own), the attachments macro (the files come
#: anyway), and a preview of an attached file (the file comes itself).
_DROPPED_CLASSES = frozenset(
    {"toc-macro", "plugin_attachments_container", "office-container"}
)

#: A layout's columns, by the name the export gives them.
_LAYOUTS = {
    "single": "single",
    "fixed-width": "single",
    "full-width": "single",
    "two-equal": "two_equal",
    "two-left-sidebar": "two_left_sidebar",
    "two-right-sidebar": "two_right_sidebar",
    "three-equal": "three_equal",
    "three-with-sidebars": "three_with_sidebars",
    "four-equal": "four_equal",
}


def _signed(url: str) -> bool:
    """A preview on Atlassian's media host, whose address carries a
    short-lived grant — it stops loading within the hour, so it is not kept."""
    return "api.media.atlassian.com" in url


#: What an ordinary element keeps of its attributes: enough for a table's
#: spans, a link's address and a picture's size.
_KEPT_ATTRS = frozenset(
    {"href", "src", "alt", "title", "colspan", "rowspan", "width", "height", "start"}
)


def _macro(
    name: str,
    params: dict[str, str],
    *,
    inline: bool = False,
    rich_body: Optional[str] = None,
    plain_body: Optional[str] = None,
) -> str:
    parts = [f'<ac:structured-macro ac:name="{name}">']
    for key, value in params.items():
        if value:
            parts.append(
                f'<ac:parameter ac:name="{key}">{html.escape(value, quote=False)}</ac:parameter>'
            )
    if rich_body is not None:
        parts.append(f"<ac:rich-text-body>{rich_body}</ac:rich-text-body>")
    if plain_body is not None:
        safe = plain_body.replace("]]>", "]]]]><![CDATA[>")
        parts.append(f"<ac:plain-text-body><![CDATA[{safe}]]></ac:plain-text-body>")
    parts.append("</ac:structured-macro>")
    return "".join(parts)


# --- Into a bundle -----------------------------------------------------------


async def export_to_fetched(
    archive: zipfile.ZipFile,
    *,
    guild_id: int,
    app_version: str,
    asset_budget: Optional[AssetBudget],
    files_allowed: bool,
    store: Optional[AssetSink] = None,
    max_rows: Optional[int] = None,
) -> tuple[ConfluenceFetched, str]:
    """The export as a site fetch would have read it, and the site its pages
    point issues at, when they do.

    ``asset_budget`` is what the bundle can hold for attachments, and
    ``store`` where each one goes; without a budget none are brought. ``files_allowed`` false is an initiative that cannot take
    uploaded files: only the pictures the pages show come.
    """
    space = await asyncio.to_thread(read_export, archive)
    budget_rows = import_limits.IMPORT_FETCH_MAX_ROWS if max_rows is None else max_rows
    by_file = {page.file: page for page in space.pages}
    pages = [
        confluence_mapping.SourcePage(
            id=page.id,
            title=page.title[: confluence_mapping.MAX_TITLE_LENGTH],
            parent_id=by_file[page.parent_file].id
            if page.parent_file in by_file
            else None,
            position=page.position,
            body=page.body,
            author_id=_user_ref(page.author) if page.author else None,
            created_at=page.created_at,
        )
        for page in space.pages[: max(0, budget_rows - 1)]
    ]

    if asset_budget is not None and store is None:
        raise ValueError("attachments need somewhere to be stored")
    gathered = Gathered()
    media: dict[str, confluence_attachments.PageMedia] = {}
    if asset_budget is not None and store is not None:

        async def read(item: Any, max_bytes: int) -> bytes:
            return await asyncio.to_thread(
                read_member, archive, item.id, max_bytes=max_bytes
            )

        for page in space.pages[: len(pages)]:
            media[page.id] = await confluence_attachments.download_page_attachments(
                [
                    confluence_attachments.PageAttachment(
                        id=a.path,
                        filename=a.filename,
                        media_type=a.media_type,
                        size=a.size,
                    )
                    for a in page.attachments
                ],
                guild_id=guild_id,
                download=read,
                store=store,
                budget=asset_budget,
                report=gathered.downloads,
                files_allowed=files_allowed,
            )

    # The first page at the top of the tree is where a reader starts.
    roots = sorted(
        (p for p in pages if p.parent_id is None),
        key=lambda p: (p.position is None, p.position or 0),
    )
    home = roots[0].id if roots and roots[0].id.isdigit() else None
    mapped = await asyncio.to_thread(
        confluence_mapping.build_wiki_envelope,
        space={"key": space.key, "name": space.name, "homepageId": home},
        pages=pages,
        users=space.users,
        site_url=space.site_url,
        app_version=app_version,
        max_bytes=max(
            0, import_limits.IMPORT_FETCH_MAX_SPACE_BYTES - _ENVELOPE_RESERVE_BYTES
        ),
        media=media,
        files_allowed=files_allowed,
    )
    gathered.add(space.key, mapped, counted_references=asset_budget is None)
    gathered.report.pages_over_limit += (
        max(0, len(space.pages) - len(pages)) + space.left_behind
    )
    gathered.settle()
    return gathered.fetched(), space.site_url
