"""Confluence storage format → the editor's Lexical state (design §7.2).

A Confluence page body, fetched as ``body-format=storage``, is XHTML with the
product's own ``ac:`` and ``ri:`` elements mixed in: macros, task lists, links
to pages and people, images by attachment filename, column layouts. This walks
it into the same shape the editor saves — ``root`` → blocks → text with a
format bitmask — so an imported page opens, searches and exports like one
written here.

Pure, like the ADF walker: no network, no database. What a body names that
only the fetch can answer — which page a title is, who an account is, where an
attachment went — is asked through the resolvers the caller passes in, and
anything no rule can place degrades by rule and is counted, so the plan can say
what did not come across.

Parsed with the standard library's tolerant HTML parser: no entity or external
resolution, and ``ac:`` tags arrive as ordinary tag names. CDATA — the body of
a code macro — is lifted out before parsing and put back verbatim.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlsplit

from app.core.search import SearchEntityType
from app.services.import_engine.limits import MAX_NESTING_DEPTH

# --- Lexical text format bits, as the editor defines them ---------------------

BOLD = 1
ITALIC = 2
STRIKETHROUGH = 4
UNDERLINE = 8
CODE = 16
SUBSCRIPT = 32
SUPERSCRIPT = 64

_FORMAT_TAGS: dict[str, int] = {
    "strong": BOLD,
    "b": BOLD,
    "em": ITALIC,
    "i": ITALIC,
    "u": UNDERLINE,
    "s": STRIKETHROUGH,
    "del": STRIKETHROUGH,
    "strike": STRIKETHROUGH,
    "code": CODE,
    "sub": SUBSCRIPT,
    "sup": SUPERSCRIPT,
}

#: Tables' ``headerState``: a header row, and a header column.
_HEADER_ROW = 1
_HEADER_COLUMN = 2

#: Elements with no end tag, so the parser never waits for one.
_VOID = frozenset(
    {
        "br",
        "hr",
        "img",
        "col",
        "wbr",
        "ac:emoticon",
        "ac:task-id",
        "ri:page",
        "ri:user",
        "ri:attachment",
        "ri:url",
        "ri:space",
        "ri:blog-post",
        "ri:content-entity",
    }
)

_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "table",
        "blockquote",
        "pre",
        "hr",
        "ac:task-list",
        "ac:layout",
        "ac:layout-section",
        "ac:layout-cell",
        "ac:adf-extension",
    }
)

#: Macros that sit inside a line of text rather than making a block of their
#: own. Everything else a macro can be is a block.
_INLINE_MACROS = frozenset({"status", "jira", "anchor", "mention"})

#: Confluence's panels, as the editor's callout kinds — matched by how they
#: look, since that is what a reader took from them: Confluence's "note" is
#: its amber one and its "warning" its red.
_CALLOUT_MACROS: dict[str, str] = {
    "info": "info",
    "note": "warning",
    "warning": "error",
    "tip": "tip",
    "success": "success",
    "error": "error",
    "panel": "note",
}

#: Macros whose output is generated from elsewhere — navigation the wiki draws
#: for itself, or content that belongs to another page. Nothing of theirs is
#: in this body to keep.
_GENERATED_MACROS = frozenset(
    {
        "toc",
        "toc-zone",
        "children",
        "pagetree",
        "pagetreesearch",
        "include",
        "excerpt-include",
        "recently-updated",
        "contentbylabel",
        "content-report-table",
        "livesearch",
        "attachments",
        "anchor",
        "blog-posts",
        "page-index",
        "create-from-template",
    }
)

#: Embeds of another product's content, which cannot be carried.
_EMBED_MACROS = frozenset(
    {"drawio", "drawio-sketch", "gliffy", "widget", "html", "iframe", "roadmap"}
)

#: Confluence's layout section types, as the editor's column templates.
_LAYOUT_COLUMNS: dict[str, str] = {
    "two_equal": "1fr 1fr",
    "two_left_sidebar": "1fr 3fr",
    "two_right_sidebar": "3fr 1fr",
    "three_equal": "1fr 1fr 1fr",
    "three_with_sidebars": "1fr 2fr 1fr",
    "four_equal": "1fr 1fr 1fr 1fr",
}

#: Confluence's status colours, as the editor's status colours.
_STATUS_COLOURS: dict[str, str] = {
    "grey": "neutral",
    "gray": "neutral",
    "red": "red",
    "yellow": "yellow",
    "green": "green",
    "blue": "blue",
    "purple": "purple",
}

#: Confluence's own emoticons, for the ones it stores by name alone.
_EMOTICONS: dict[str, str] = {
    "smile": "\U0001f642",
    "sad": "\U0001f641",
    "cheeky": "\U0001f61b",
    "laugh": "\U0001f604",
    "wink": "\U0001f609",
    "thumbs-up": "\U0001f44d",
    "thumbs-down": "\U0001f44e",
    "information": "\u2139\ufe0f",
    "tick": "\u2705",
    "cross": "\u274c",
    "warning": "\u26a0\ufe0f",
    "plus": "\u2795",
    "minus": "\u2796",
    "question": "\u2753",
    "light-on": "\U0001f4a1",
    "light-off": "\U0001f4a1",
    "yellow-star": "\u2b50",
    "red-star": "\u2b50",
    "green-star": "\u2b50",
    "blue-star": "\u2b50",
    "heart": "\u2764\ufe0f",
    "broken-heart": "\U0001f494",
}

#: Macros that show one attached file.
_FILE_MACROS = frozenset({"view-file", "viewpdf", "view-doc", "view-ppt", "view-xls"})

#: The newer editor's panel types, as callout kinds.
_ADF_PANELS: dict[str, str] = {
    "info": "info",
    "note": "note",
    "tip": "tip",
    "success": "success",
    "warning": "warning",
    "error": "error",
    "custom": "note",
}

#: A YouTube video's id, from any of the addresses YouTube hands out.
_YOUTUBE = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)

#: A Jira issue key, as it appears in a link to the issue.
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
_WHITESPACE = re.compile(r"[ \t\n\r\f]+")
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_CDATA_TAG = "x-cdata"

# --- What the caller answers ---------------------------------------------------


@dataclass(frozen=True)
class PageTarget:
    """Where a link to another Confluence page goes.

    ``slug`` for a page in the same import: the walker writes a wiki-page
    mention the apply resolves once the page exists. ``url`` for one outside
    it: an ordinary link back to the source.
    """

    slug: str | None = None
    url: str | None = None


#: ``(content_title, space_key)`` → where a page link goes, or ``None``.
PageResolver = Callable[[str, str | None], PageTarget | None]
#: ``account_id`` → the person's display name, or ``None``.
UserResolver = Callable[[str], str | None]
#: ``filename`` → the URL it is served from here, or ``None``.
UploadResolver = Callable[[str], str | None]
#: ``filename`` → the ref of the file the attachment became, or ``None``.
FileResolver = Callable[[str], str | None]
#: The block listing the pages beneath this one, or ``None`` when it has none.
ChildrenResolver = Callable[[], dict[str, Any] | None]


@dataclass
class StorageResult:
    """One page body, converted, and what converting it cost."""

    content: dict[str, Any]
    #: What was left out, by kind — a macro's name, or ``image`` for a picture
    #: nobody could place.
    dropped: Counter[str] = field(default_factory=Counter)
    #: Everybody the body mentions, by display name, in order of first
    #: mention: the people step's to place, and the apply's to link.
    mentions: list[str] = field(default_factory=list)
    #: Attachment filenames the body shows or links to, in order of first use.
    attachments: list[str] = field(default_factory=list)
    #: The attachments among those it shows as pictures.
    shown: list[str] = field(default_factory=list)

    @property
    def dropped_nodes(self) -> int:
        return sum(self.dropped.values())


# --- Parsing -------------------------------------------------------------------


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str]
    children: list[_Element | str] = field(default_factory=list)

    def attr(self, name: str) -> str:
        return self.attrs.get(name) or ""

    def elements(self) -> list[_Element]:
        return [child for child in self.children if isinstance(child, _Element)]

    def first(self, tag: str) -> _Element | None:
        return next((child for child in self.elements() if child.tag == tag), None)


class _TreeBuilder(HTMLParser):
    """The body as a tree, at most :data:`MAX_NESTING_DEPTH` elements deep.

    An element that opens past the limit is kept where it sits, but nothing
    nests inside it: what it holds joins its parent's children instead, so
    the text survives and every walk over the tree stays within the limit.
    """

    def __init__(self, cdata: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("root", {})
        self.stack = [self.root]
        #: Tags opened past the depth limit and not yet closed.
        self.overflow: list[str] = []
        self.cdata = cdata

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == _CDATA_TAG:
            index = dict(attrs).get("n") or ""
            if index.isdigit() and int(index) < len(self.cdata):
                self.stack[-1].children.append(self.cdata[int(index)])
            return
        element = _Element(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(element)
        if tag in _VOID:
            return
        if len(self.stack) > MAX_NESTING_DEPTH:
            self.overflow.append(tag)
        else:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == _CDATA_TAG:
            self.handle_starttag(tag, attrs)
            return
        self.stack[-1].children.append(
            _Element(tag, {name: value or "" for name, value in attrs})
        )

    def handle_endtag(self, tag: str) -> None:
        # Close back to the matching element; a stray end tag closes nothing.
        for depth in range(len(self.overflow) - 1, -1, -1):
            if self.overflow[depth] == tag:
                del self.overflow[depth:]
                return
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                self.overflow.clear()
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _parse(xhtml: str) -> _Element:
    cdata: list[str] = []

    def lift(match: re.Match[str]) -> str:
        cdata.append(match.group(1))
        return f'<{_CDATA_TAG} n="{len(cdata) - 1}"/>'

    builder = _TreeBuilder(cdata)
    builder.feed(_CDATA.sub(lift, xhtml))
    builder.close()
    return builder.root


def _text_of(element: _Element | str) -> str:
    if isinstance(element, str):
        return element
    return "".join(_text_of(child) for child in element.children)


# --- Lexical node builders -----------------------------------------------------


def _element(node_type: str, children: list[dict], **extra: Any) -> dict[str, Any]:
    return {
        "type": node_type,
        "version": 1,
        "direction": "ltr",
        "format": "",
        "indent": 0,
        "children": children,
        **extra,
    }


def _text(text: str, fmt: int = 0) -> dict[str, Any]:
    return {
        "type": "text",
        "version": 1,
        "text": text,
        "format": fmt,
        "style": "",
        "mode": "normal",
        "detail": 0,
    }


def _linebreak() -> dict[str, Any]:
    return {"type": "linebreak", "version": 1}


def _paragraph(children: list[dict]) -> dict[str, Any]:
    return _element("paragraph", children, textFormat=0, textStyle="")


def _is_text(node: dict) -> bool:
    return node.get("type") == "text"


def _tidy_inline(nodes: list[dict]) -> list[dict]:
    """Trim a line's edges, drop empty text, and join neighbours that share a
    format — what the editor itself would have saved."""
    out: list[dict] = []
    for node in nodes:
        if _is_text(node):
            if not node["text"]:
                continue
            if out and _is_text(out[-1]) and out[-1]["format"] == node["format"]:
                out[-1] = {**out[-1], "text": out[-1]["text"] + node["text"]}
                continue
        out.append(node)
    # Leading and trailing spaces are the markup's indentation, not content.
    while out and _is_text(out[0]) and not out[0]["text"].strip(" "):
        out.pop(0)
    while out and _is_text(out[-1]) and not out[-1]["text"].strip(" "):
        out.pop()
    while out and out[0].get("type") == "linebreak":
        out.pop(0)
    while out and out[-1].get("type") == "linebreak":
        out.pop()
    if out and _is_text(out[0]):
        out[0] = {**out[0], "text": out[0]["text"].lstrip(" ")}
    if out and _is_text(out[-1]):
        out[-1] = {**out[-1], "text": out[-1]["text"].rstrip(" ")}
    return out


def _safe_url(url: str) -> str | None:
    """``url`` if it is one a link may carry: the web, mail, or a path on
    this app (where the fetch put an attachment)."""
    url = url.strip()
    if not url:
        return None
    if url.startswith("/") and not url.startswith("//"):
        return url
    scheme = urlsplit(url).scheme.lower()
    return url if scheme in _LINK_SCHEMES else None


def _parameters(macro: _Element) -> dict[str, str]:
    return {
        child.attr("ac:name"): _text_of(child).strip()
        for child in macro.elements()
        if child.tag == "ac:parameter" and child.attr("ac:name")
    }


def _dimension(raw: str) -> int:
    digits = raw.strip().removesuffix("px")
    return int(digits) if digits.isdigit() else 0


# --- The walker ----------------------------------------------------------------


class _Walker:
    def __init__(
        self,
        *,
        page: PageResolver | None,
        user: UserResolver | None,
        image: UploadResolver | None,
        attachment: UploadResolver | None,
        site_url: str | None,
        children: ChildrenResolver | None = None,
        file: FileResolver | None = None,
    ) -> None:
        self.children = children
        self.file = file
        self.page = page
        self.user = user
        self.image = image
        self.attachment = attachment
        self.site_url = (site_url or "").rstrip("/")
        self.result = StorageResult(content={})

    # -- bookkeeping --------------------------------------------------------

    def drop(self, kind: str) -> None:
        self.result.dropped[kind] += 1

    def note_attachment(self, filename: str) -> None:
        if filename and filename not in self.result.attachments:
            self.result.attachments.append(filename)

    def file_link(
        self, filename: str, text: list[dict], *, in_link: bool
    ) -> list[dict]:
        """A link to an attached file: a mention of the file it became,
        a link to where it is served, or its words."""
        self.note_attachment(filename)
        ref = self.file(filename) if (self.file and filename) else None
        if ref and not in_link:
            return [
                {
                    "type": "entity-mention",
                    "version": 1,
                    "entityType": SearchEntityType.file.value,
                    "entityId": 0,
                    "text": "".join(n.get("text", "") for n in text) or filename,
                    # Resolved to the imported file's id on apply.
                    "importRef": ref,
                }
            ]
        url = self.attachment(filename) if (self.attachment and filename) else None
        return self.link(url, text, in_link) if url else text

    def note_mention(self, name: str) -> None:
        if name and name not in self.result.mentions:
            self.result.mentions.append(name)

    # -- blocks -------------------------------------------------------------

    def blocks(self, nodes: list[_Element | str], *, fmt: int = 0) -> list[dict]:
        """A run of siblings as blocks: loose text and inline elements are
        gathered into paragraphs, and each block element stands alone."""
        out: list[dict] = []
        pending: list[dict] = []

        def flush() -> None:
            line = _tidy_inline(pending)
            pending.clear()
            if line:
                out.append(_paragraph(line))

        for node in nodes:
            if isinstance(node, _Element) and self.is_block(node):
                flush()
                out.extend(self.block(node, fmt=fmt))
            else:
                pending.extend(self.inline([node], fmt=fmt))
        flush()
        return out

    def is_block(self, element: _Element) -> bool:
        if element.tag in _BLOCK_TAGS:
            return True
        if element.tag == "ac:structured-macro":
            return element.attr("ac:name") not in _INLINE_MACROS
        if element.tag == "a" and element.attr("data-card-appearance") == "embed":
            return _YOUTUBE.match(element.attr("href")) is not None
        return False

    def block(self, element: _Element, *, fmt: int = 0) -> list[dict]:
        tag = element.tag
        if tag == "p":
            line = _tidy_inline(self.inline(element.children, fmt=fmt))
            return [_paragraph(line)] if line else []
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            line = _tidy_inline(self.inline(element.children, fmt=fmt))
            return [_element("heading", line, tag=tag)] if line else []
        if tag in ("ul", "ol"):
            listed = self.list_node(element, "number" if tag == "ol" else "bullet")
            return [listed] if listed else []
        if tag == "ac:task-list":
            listed = self.task_list(element)
            return [listed] if listed else []
        if tag == "table":
            return self.table(element)
        if tag == "blockquote":
            return self.quote(self.blocks(element.children, fmt=fmt))
        if tag == "pre":
            return [self.code(_text_of(element), "")]
        if tag == "hr":
            return [{"type": "horizontalrule", "version": 1}]
        if tag == "ac:layout":
            return [
                block
                for section in element.elements()
                if section.tag == "ac:layout-section"
                for block in self.layout_section(section)
            ]
        if tag == "ac:layout-section":
            return self.layout_section(element)
        if tag == "ac:structured-macro":
            return self.macro(element)
        if tag == "ac:adf-extension":
            return self.adf_extension(element, fmt=fmt)
        if tag == "a":
            # A video Confluence embeds, as the editor's own embed.
            match = _YOUTUBE.match(element.attr("href"))
            if match:
                return [
                    {
                        "type": "youtube",
                        "version": 1,
                        "format": "",
                        "videoID": match.group(1),
                    }
                ]
        # div, section, a layout cell met out of place: its content counts.
        return self.blocks(element.children, fmt=fmt)

    def file_card(self, macro: _Element, *, in_link: bool) -> list[dict] | None:
        """A file Confluence shows as a card or a viewer: a link to where the
        file went, or its name. Counted among the page's attachments rather
        than as a loss. ``None`` for a macro that is not one."""
        if macro.attr("ac:name") not in _FILE_MACROS:
            return None
        attachment = next(
            (e for e in _descendants(macro) if e.tag == "ri:attachment"), None
        )
        filename = attachment.attr("ri:filename") if attachment is not None else ""
        if not filename:
            return None
        return self.file_link(filename, [_text(filename)], in_link=in_link)

    def adf_extension(self, element: _Element, *, fmt: int) -> list[dict]:
        """A node the newer editor stores natively, carried with a fallback
        rendering for readers that do not know it.

        The ones worth reading natively are: a panel, which is a callout; a
        decision log, which is a checklist ticked where decided; and tabs,
        each a heading over its body. Anything else takes its fallback, or
        failing that its content — never its attributes, which are settings
        and not words.
        """
        node = element.first("ac:adf-node")
        kind = node.attr("type") if node is not None else ""
        attrs = _adf_attributes(node) if node is not None else {}
        content = node.first("ac:adf-content") if node is not None else None
        if node is not None and kind == "panel":
            body = self.blocks(content.children, fmt=fmt) if content else []
            return [
                _element(
                    "callout",
                    [b for b in body if b.get("type") != "layout-container"]
                    or [_paragraph([])],
                    variant=_ADF_PANELS.get(attrs.get("panel-type", ""), "note"),
                )
            ]
        if node is not None and kind == "decision-list":
            items = [
                child
                for child in node.elements()
                if child.tag == "ac:adf-node" and child.attr("type") == "decision-item"
            ]
            listed: list[dict] = []
            for index, item in enumerate(items, start=1):
                body = item.first("ac:adf-content")
                listed.extend(
                    self.list_items(
                        body.children if body else [],
                        [],
                        index,
                        checked=_adf_attributes(item).get("state") == "DECIDED",
                    )
                )
            return [self.list_wrapper("check", listed)] if listed else []
        if (
            node is not None
            and kind == "multi-bodied-extension"
            and content is not None
        ):
            titles = _adf_tab_titles(node)
            out: list[dict] = []
            frames = [
                f for f in content.elements() if f.tag == "ac:adf-extension-frame"
            ]
            for index, frame in enumerate(frames):
                title = titles[index] if index < len(titles) else ""
                if title:
                    out.append(_element("heading", [_text(title)], tag="h3"))
                out.extend(self.blocks(frame.children, fmt=fmt))
            return out
        fallback = element.first("ac:adf-fallback")
        if fallback is not None:
            return self.blocks(fallback.children, fmt=fmt)
        return self.blocks(content.children, fmt=fmt) if content is not None else []

    def list_node(self, element: _Element, list_type: str) -> dict | None:
        items: list[dict] = []
        for child in element.elements():
            if child.tag != "li":
                continue
            inline: list[_Element | str] = []
            nested: list[dict] = []
            for grandchild in child.children:
                if isinstance(grandchild, _Element) and grandchild.tag in ("ul", "ol"):
                    sub = self.list_node(
                        grandchild, "number" if grandchild.tag == "ol" else "bullet"
                    )
                    if sub:
                        nested.append(sub)
                else:
                    inline.append(grandchild)
            items.extend(self.list_items(inline, nested, len(items) + 1))
        if not items:
            return None
        return self.list_wrapper(list_type, items)

    def list_items(
        self,
        inline: list[_Element | str],
        nested: list[dict],
        value: int,
        *,
        checked: bool | None = None,
    ) -> list[dict]:
        """One source list item: its line, then — as the editor stores
        nesting — a sibling item holding each list beneath it."""
        line = self.flat_line(inline)
        extra: dict[str, Any] = {"value": value}
        if checked is not None:
            extra["checked"] = checked
        items = [_element("listitem", line, **extra)]
        for sub in nested:
            items.append(_element("listitem", [sub], value=value))
        return items

    def list_wrapper(self, list_type: str, items: list[dict]) -> dict:
        return _element(
            "list",
            items,
            listType=list_type,
            start=1,
            tag="ol" if list_type == "number" else "ul",
        )

    def task_list(self, element: _Element) -> dict | None:
        items: list[dict] = []
        for task in element.elements():
            if task.tag != "ac:task":
                continue
            status = task.first("ac:task-status")
            body = task.first("ac:task-body")
            done = status is not None and _text_of(status).strip() == "complete"
            inline: list[_Element | str] = []
            nested: list[dict] = []
            for child in body.children if body else []:
                if isinstance(child, _Element) and child.tag == "ac:task-list":
                    sub = self.task_list(child)
                    if sub:
                        nested.append(sub)
                else:
                    inline.append(child)
            items.extend(self.list_items(inline, nested, len(items) + 1, checked=done))
        if not items:
            return None
        return self.list_wrapper("check", items)

    def flat_line(self, nodes: list[_Element | str]) -> list[dict]:
        """Content that must be one line — a list item — with any blocks
        inside it laid end to end on line breaks."""
        out: list[dict] = []
        for block in self.blocks(nodes):
            line = self.inline_of(block)
            if not line:
                continue
            if out:
                out.append(_linebreak())
            out.extend(line)
        return out

    def inline_of(self, block: dict) -> list[dict]:
        """A block's inline content, for a place that can only hold a line."""
        node_type = block.get("type")
        if node_type in ("paragraph", "heading", "quote"):
            return list(block["children"])
        if node_type == "code":
            text = "".join(
                "\n" if child.get("type") == "linebreak" else child.get("text", "")
                for child in block["children"]
            )
            return [_text(text, CODE)] if text else []
        if node_type == "horizontalrule":
            return []
        # A list, a table or a layout inside a line: its text, line by line.
        out: list[dict] = []
        for child in block.get("children") or []:
            line = self.inline_of(child) if isinstance(child, dict) else []
            if not line:
                continue
            if out:
                out.append(_linebreak())
            out.extend(line)
        return out

    def quote(self, blocks: list[dict]) -> list[dict]:
        """Blocks as one quote. The editor's quote holds a single run of
        text, so paragraphs inside it are joined by line breaks; a list or a
        table that cannot be flattened without losing its shape follows the
        quote instead."""
        line: list[dict] = []
        after: list[dict] = []
        for block in blocks:
            if block.get("type") in ("list", "table", "layout-container", "code"):
                after.append(block)
                continue
            content = self.inline_of(block)
            if not content:
                continue
            if line:
                line.append(_linebreak())
            line.extend(content)
        out = [_element("quote", line)] if line else []
        return out + after

    def code(self, text: str, language: str) -> dict:
        children: list[dict] = []
        lines = text.replace("\r\n", "\n").strip("\n").split("\n")
        for index, line in enumerate(lines):
            if index:
                children.append(_linebreak())
            if line:
                children.append(
                    {
                        "type": "code-highlight",
                        "version": 1,
                        "text": line,
                        "format": 0,
                        "style": "",
                        "mode": "normal",
                        "detail": 0,
                    }
                )
        extra: dict[str, Any] = {}
        if language:
            extra["language"] = language
        return _element("code", children, **extra)

    def table(self, element: _Element) -> list[dict]:
        rows: list[dict] = []
        for row in self.table_rows(element):
            cells: list[dict] = []
            for cell in row.elements():
                if cell.tag not in ("td", "th"):
                    continue
                header = 0
                if cell.tag == "th":
                    header = _HEADER_ROW if not rows else _HEADER_COLUMN
                content = self.cell_blocks(cell)
                extra: dict[str, Any] = {
                    "headerState": header,
                    "colSpan": _span(cell.attr("colspan")),
                    "rowSpan": _span(cell.attr("rowspan")),
                    "backgroundColor": None,
                }
                cells.append(_element("tablecell", content, **extra))
            if cells:
                rows.append(_element("tablerow", cells))
        if not rows:
            return []
        return [_element("table", rows)]

    def table_rows(self, element: _Element) -> list[_Element]:
        rows: list[_Element] = []
        for child in element.elements():
            if child.tag == "tr":
                rows.append(child)
            elif child.tag in ("thead", "tbody", "tfoot"):
                rows.extend(r for r in child.elements() if r.tag == "tr")
        return rows

    def cell_blocks(self, cell: _Element) -> list[dict]:
        blocks: list[dict] = []
        for block in self.blocks(cell.children):
            if block.get("type") == "table":
                # The editor has no table inside a table: the inner one is
                # kept as its rows' text.
                self.drop("nested-table")
                for row in block["children"]:
                    texts = [
                        "".join(n.get("text", "") for n in self.inline_of(c))
                        for c in row["children"]
                    ]
                    line = " | ".join(t for t in texts if t)
                    if line:
                        blocks.append(_paragraph([_text(line)]))
                continue
            if block.get("type") == "layout-container":
                blocks.extend(b for item in block["children"] for b in item["children"])
                continue
            blocks.append(block)
        return blocks or [_paragraph([])]

    def layout_section(self, section: _Element) -> list[dict]:
        cells = [c for c in section.elements() if c.tag == "ac:layout-cell"]
        if len(cells) <= 1:
            return [b for cell in cells for b in self.blocks(cell.children)]
        items = []
        for cell in cells:
            content = [
                b
                for b in self.blocks(cell.children)
                if b.get("type") != "layout-container"
            ]
            items.append(_element("layout-item", content or [_paragraph([])]))
        columns = _LAYOUT_COLUMNS.get(section.attr("ac:type")) or " ".join(
            ["1fr"] * len(cells)
        )
        return [_element("layout-container", items, templateColumns=columns)]

    def macro(self, macro: _Element) -> list[dict]:
        name = macro.attr("ac:name")
        params = _parameters(macro)
        rich = macro.first("ac:rich-text-body")
        plain = macro.first("ac:plain-text-body")
        if name in ("code", "noformat"):
            return [
                self.code(
                    _text_of(plain) if plain else "",
                    params.get("language", "") if name == "code" else "",
                )
            ]
        if name in _CALLOUT_MACROS:
            body = self.blocks(rich.children) if rich else []
            title = params.get("title", "")
            if title:
                body = [_paragraph([_text(title, BOLD)]), *body]
            return [
                _element(
                    "callout",
                    [block for block in body if block.get("type") != "layout-container"]
                    or [_paragraph([])],
                    variant=_CALLOUT_MACROS[name],
                )
            ]
        if name == "expand":
            body = self.blocks(rich.children) if rich else []
            title = params.get("title", "")
            heading = [_element("heading", [_text(title)], tag="h3")] if title else []
            return heading + body
        if name == "children":
            # The list of the pages beneath this one, which is what the macro
            # draws — when the page has any here.
            listed = self.children() if self.children else None
            if listed is not None:
                return [listed]
        if name in ("include", "excerpt-include"):
            # Another page's words, drawn in: kept as a link to that page.
            link = next((e for e in _descendants(macro) if e.tag == "ac:link"), None)
            line = self.ac_link(link, fmt=0, in_link=False) if link is not None else []
            if line:
                return [_paragraph(line)]
        card = self.file_card(macro, in_link=False)
        if card is not None:
            return [_paragraph(card)]
        if name in _GENERATED_MACROS or name in _EMBED_MACROS:
            self.drop(name)
            return []
        if rich is not None:
            return self.blocks(rich.children)
        if plain is not None:
            text = _text_of(plain).strip()
            return [_paragraph([_text(text)])] if text else []
        self.drop(name or "macro")
        return []

    # -- inline -------------------------------------------------------------

    def inline(
        self,
        nodes: list[_Element | str],
        *,
        fmt: int = 0,
        in_link: bool = False,
    ) -> list[dict]:
        out: list[dict] = []
        for node in nodes:
            if isinstance(node, str):
                text = _WHITESPACE.sub(" ", node)
                if text:
                    out.append(_text(text, fmt))
                continue
            out.extend(self.inline_element(node, fmt=fmt, in_link=in_link))
        return out

    def inline_element(
        self, element: _Element, *, fmt: int, in_link: bool
    ) -> list[dict]:
        tag = element.tag
        if tag in _FORMAT_TAGS:
            return self.inline(
                element.children, fmt=fmt | _FORMAT_TAGS[tag], in_link=in_link
            )
        if tag == "br":
            return [_linebreak()]
        if tag == "a":
            return self.anchor(element, fmt=fmt, in_link=in_link)
        if tag == "ac:link":
            return self.ac_link(element, fmt=fmt, in_link=in_link)
        if tag in ("ac:image", "img"):
            return self.image_node(element)
        if tag == "ac:emoticon":
            glyph = _emoticon(element)
            return [_text(glyph, fmt)] if glyph else []
        if tag == "time":
            stamp = element.attr("datetime") or _text_of(element).strip()
            return [_text(stamp, fmt)] if stamp else []
        if tag == "ac:structured-macro":
            return self.inline_macro(element, fmt=fmt, in_link=in_link)
        if tag in ("ac:placeholder", "ac:task-id", "x-cdata", "colgroup", "col"):
            return []
        if self.is_block(element):
            # A block where only a line can go: its text, on a line of its own.
            line: list[dict] = []
            for block in self.block(element, fmt=fmt):
                content = self.inline_of(block)
                if content:
                    line.append(_linebreak())
                    line.extend(content)
            return [*line, _linebreak()] if line else []
        # span, ac:inline-comment-marker, anything unknown: its content.
        return self.inline(element.children, fmt=fmt, in_link=in_link)

    def link(self, url: str, children: list[dict], in_link: bool) -> list[dict]:
        safe = _safe_url(url)
        if not children:
            return []
        if safe is None or in_link:
            return children
        return [
            _element(
                "link",
                children,
                url=safe,
                rel="noopener noreferrer",
                target="_blank",
                title=None,
            )
        ]

    def anchor(self, element: _Element, *, fmt: int, in_link: bool) -> list[dict]:
        children = self.inline(element.children, fmt=fmt, in_link=True)
        href = element.attr("href")
        linked = self.link(href, children, in_link)
        key = self.jira_key_of(href)
        if key and len(linked) == 1 and linked[0].get("type") == "link":
            # A link to an issue on this site: the apply points it at the task
            # the issue became, if it came over, and leaves the link if not.
            linked[0]["importJiraKey"] = key
        return linked

    def jira_key_of(self, url: str) -> str | None:
        """The issue key a URL names, when it is an issue on this site."""
        if not self.site_url:
            return None
        prefix = f"{self.site_url}/browse/"
        if not url.startswith(prefix):
            return None
        key = url.removeprefix(prefix).split("?")[0].split("#")[0].strip("/")
        return key if _JIRA_KEY.match(key) else None

    def link_body(self, element: _Element, fmt: int) -> list[dict]:
        rich = element.first("ac:link-body")
        if rich is not None:
            return self.inline(rich.children, fmt=fmt, in_link=True)
        plain = element.first("ac:plain-text-link-body")
        if plain is not None:
            text = _text_of(plain).strip()
            return [_text(text, fmt)] if text else []
        return []

    def ac_link(self, element: _Element, *, fmt: int, in_link: bool) -> list[dict]:
        body = self.link_body(element, fmt)

        user = element.first("ri:user")
        if user is not None:
            account = user.attr("ri:account-id") or user.attr("ri:userkey")
            name = self.user(account) if (self.user and account) else None
            if name:
                self.note_mention(name)
                return [
                    {
                        "type": "mention",
                        "version": 1,
                        "mentionName": name,
                        "mentionUserId": None,
                        "text": name,
                    }
                ]
            if body:
                return body
            self.drop("user")
            return []

        page = element.first("ri:page") or element.first("ri:blog-post")
        if page is not None:
            title = page.attr("ri:content-title")
            space = page.attr("ri:space-key") or None
            target = self.page(title, space) if (self.page and title) else None
            text = body or ([_text(title, fmt)] if title else [])
            if target is not None and target.slug and not in_link:
                return [
                    {
                        "type": "entity-mention",
                        "version": 1,
                        "entityType": "wiki_page",
                        "entityId": 0,
                        "text": "".join(n.get("text", "") for n in text) or title,
                        # Resolved to the imported page's id on apply.
                        "importSlug": target.slug,
                    }
                ]
            if target is not None and target.url:
                return self.link(target.url, text, in_link)
            return text

        attachment = element.first("ri:attachment")
        if attachment is not None:
            filename = attachment.attr("ri:filename")
            text = body or ([_text(filename, fmt)] if filename else [])
            return self.file_link(filename, text, in_link=in_link)

        url_ref = element.first("ri:url")
        if url_ref is not None:
            url = url_ref.attr("ri:value")
            return self.link(url, body or [_text(url, fmt)], in_link)

        anchor = element.attr("ac:anchor")
        if body:
            return body
        return [_text(anchor, fmt)] if anchor else []

    def image_node(self, element: _Element) -> list[dict]:
        alt = element.attr("ac:alt") or element.attr("alt") or element.attr("title")
        src: str | None = None
        if element.tag == "img":
            src = _safe_url(element.attr("src"))
        else:
            attachment = element.first("ri:attachment")
            remote = element.first("ri:url")
            if attachment is not None:
                filename = attachment.attr("ri:filename")
                self.note_attachment(filename)
                if filename and filename not in self.result.shown:
                    self.result.shown.append(filename)
                alt = alt or filename
                src = self.image(filename) if (self.image and filename) else None
            elif remote is not None:
                src = _safe_url(remote.attr("ri:value"))
        caption_element = element.first("ac:caption")
        caption = (
            _WHITESPACE.sub(" ", _text_of(caption_element)).strip()
            if caption_element
            else ""
        )
        if not src:
            self.drop("image")
            return [_text(f"[{alt}]")] if alt else []
        # A caption reads under its picture, in italics.
        after = [_linebreak(), _text(caption, ITALIC)] if caption else []
        return [
            {
                "type": "image",
                "version": 1,
                "src": src,
                "altText": alt,
                "width": _dimension(element.attr("ac:width") or element.attr("width")),
                "height": _dimension(
                    element.attr("ac:height") or element.attr("height")
                ),
                "maxWidth": 800,
                "showCaption": False,
            },
            *after,
        ]

    def inline_macro(self, macro: _Element, *, fmt: int, in_link: bool) -> list[dict]:
        name = macro.attr("ac:name")
        params = _parameters(macro)
        if name == "status":
            title = params.get("title", "").strip()
            if not title:
                return []
            return [
                {
                    "type": "status",
                    "version": 1,
                    "text": title,
                    "color": _STATUS_COLOURS.get(
                        params.get("colour", "").strip().lower(), "neutral"
                    ),
                }
            ]
        if name == "jira":
            key = params.get("key", "").strip()
            query = params.get("jqlQuery", "").strip()
            if not key and query and self.site_url:
                # A list of issues, drawn live in Confluence: kept as a link
                # to the same search.
                return self.link(
                    f"{self.site_url}/issues/?jql={quote(query)}",
                    [_text(query, fmt)],
                    in_link,
                )
            if not key:
                self.drop("jira")
                return []
            url = f"{self.site_url}/browse/{key}" if self.site_url else None
            if in_link or not _JIRA_KEY.match(key):
                return (
                    self.link(url, [_text(key, fmt)], in_link)
                    if url
                    else [_text(key, fmt)]
                )
            # The issue, and its live status beside it — as the macro shows
            # them — once the apply has found the task the issue became. One
            # that was not imported goes back to being a link to Jira.
            return [
                {
                    "type": "entity-mention",
                    "version": 1,
                    "entityType": "task",
                    "entityId": 0,
                    "text": key,
                    "importJiraKey": key,
                    **({"importUrl": url} if url else {}),
                },
                _text(" "),
                {
                    "type": "smart-chip",
                    "version": 1,
                    "chipKind": "task:status",
                    "entityId": 0,
                    "text": key,
                    "importJiraKey": key,
                },
            ]
        if name == "anchor":
            return []
        card = self.file_card(macro, in_link=in_link)
        if card is not None:
            return card
        rich = macro.first("ac:rich-text-body")
        if rich is not None:
            return self.inline(rich.children, fmt=fmt, in_link=in_link)
        self.drop(name or "macro")
        return []


def _descendants(element: _Element):
    for child in element.elements():
        yield child
        yield from _descendants(child)


def _adf_attributes(node: _Element) -> dict[str, str]:
    return {
        child.attr("key"): _text_of(child).strip()
        for child in node.elements()
        if child.tag == "ac:adf-attribute" and child.attr("key")
    }


def _adf_tab_titles(node: _Element) -> list[str]:
    """The tabs' titles, in order, from a tabs node's parameters."""
    titles: list[str] = []
    for value in _descendants(node):
        if value.tag != "ac:adf-parameter-value":
            continue
        for parameter in value.elements():
            if parameter.tag == "ac:adf-parameter" and parameter.attr("key") == "title":
                titles.append(_text_of(parameter).strip())
    return titles


def _emoticon(element: _Element) -> str:
    """An emoticon's glyph: the one Confluence stored with it, else the
    character its id names, else Confluence's own for its name."""
    fallback = element.attr("ac:emoji-fallback")
    if fallback and not (fallback.startswith(":") and fallback.endswith(":")):
        return fallback
    emoji_id = element.attr("ac:emoji-id")
    try:
        glyph = "".join(chr(int(part, 16)) for part in emoji_id.split("-") if part)
    except ValueError:
        glyph = ""
    if glyph:
        return glyph
    name = element.attr("ac:name")
    return _EMOTICONS.get(name, fallback or (f":{name}:" if name else ""))


def _span(raw: str) -> int:
    return int(raw) if raw.strip().isdigit() and int(raw) > 0 else 1


def storage_to_lexical(
    xhtml: Any,
    *,
    page: PageResolver | None = None,
    user: UserResolver | None = None,
    image: UploadResolver | None = None,
    attachment: UploadResolver | None = None,
    site_url: str | None = None,
    children: ChildrenResolver | None = None,
    file: FileResolver | None = None,
) -> StorageResult:
    """Convert one page body.

    ``page`` answers where a link to another page goes (see
    :class:`PageTarget`); a link it cannot place keeps its words. ``user``
    names an account id, and a mention it cannot name keeps its link text.
    ``image`` and ``attachment`` give the URL an attachment is served from
    here, by filename; an image nobody can place becomes its alt text and is
    counted. ``file`` names the file an attachment became, and a link to
    one becomes a mention of it. ``site_url`` is where a Jira issue macro
    links to.

    A wiki-page mention is written with ``entityId`` 0 and an ``importSlug``:
    the apply swaps in the imported page's id, or turns it back into text if
    that page did not arrive. A file mention carries an ``importRef`` the
    same way.
    """
    walker = _Walker(
        page=page,
        user=user,
        image=image,
        attachment=attachment,
        site_url=site_url,
        children=children,
        file=file,
    )
    tree = _parse(xhtml if isinstance(xhtml, str) else "")
    body = walker.blocks(tree.children)
    walker.result.content = {
        "root": {
            "type": "root",
            "version": 1,
            "direction": "ltr",
            "format": "",
            "indent": 0,
            "children": body or [_paragraph([])],
        }
    }
    return walker.result
