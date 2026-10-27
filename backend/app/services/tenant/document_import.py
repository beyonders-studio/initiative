"""Read a Word (``.docx``) or OpenDocument text (``.odt``) file into the XHTML
the wiki importer's walker reads (:func:`confluence_storage.storage_to_lexical`).

Both formats are a zip holding the body as XML: ``word/document.xml``, or
``content.xml``. Each is read here into plain XHTML, its headings, paragraphs
and their formatting, lists, tables, links and pictures, and the walker makes
that the editor's own document, so a converted file is built by the same rules
an imported page is. A picture is named by its path inside the zip, as an
attachment by its filename, and handed back with its bytes for the caller to
store. Page layout, headers and footers, footnotes, comments, text boxes and
embedded objects are not read. A tracked insertion reads as written and a
tracked deletion as gone.

The XML is read through defusedxml, one top-level block at a time, and
nothing is opened before the zip's declared sizes are checked.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import IO, Iterator, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import iterparse
from fastapi import status

from app.core.file_types import FileType
from app.core.messages import FileMessages
from app.services.tenant.attachments import MAX_IMAGE_BYTES
from app.services.tenant.files import FileContentError

#: The most a document's parts may add up to once decompressed, read from the
#: sizes its zip directory declares before anything is opened.
MAX_DOCUMENT_PACKAGE_BYTES = 100 * 1024 * 1024

#: The most table cells a document is read with once its repeated rows and
#: cells are counted. A document past it holds more than a document here can.
MAX_TABLE_CELLS = 100_000

#: How deep tables nest before an inner one is kept as its rows' text, as the
#: walker keeps any table inside a table.
_MAX_TABLE_DEPTH = 4

#: The walker's formatting tags, in the order they nest.
_FORMATS = _BOLD, _ITALIC, _UNDERLINE, _STRIKE, _SUB, _SUP = (
    "strong",
    "em",
    "u",
    "s",
    "sub",
    "sup",
)


@dataclass
class ReadDocument:
    xhtml: str
    #: Each picture the body shows, by its path in the zip.
    pictures: dict[str, bytes] = field(default_factory=dict)


def read_document(file_type: FileType, data: bytes) -> ReadDocument:
    """The body of a ``.docx`` or ``.odt`` file as XHTML, and its pictures.

    Raises :class:`FileContentError`: ``FILE_TOO_LARGE_TO_CONVERT`` for a
    package past :data:`MAX_DOCUMENT_PACKAGE_BYTES`, ``FILE_INVALID_FILE``
    for one that isn't a document this reads.
    """
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileContentError(FileMessages.INVALID_FILE) from exc
    with package:
        if sum(info.file_size for info in package.infolist()) > (
            MAX_DOCUMENT_PACKAGE_BYTES
        ):
            raise _too_large()
        reader = _Docx(package) if file_type == FileType.docx else _Odt(package)
        try:
            root = reader.read()
            pictures = {
                name: package.read(name)
                for name in reader.pictures
                if name in package.NameToInfo
                and package.NameToInfo[name].file_size <= MAX_IMAGE_BYTES
            }
        except (
            KeyError,
            EOFError,
            NotImplementedError,
            zipfile.BadZipFile,
            zlib.error,
            SyntaxError,
            DefusedXmlException,
            RecursionError,
        ) as exc:
            # A missing part, a damaged or unsupported zip, or XML that does
            # not parse, declares what defusedxml refuses, or nests past
            # what a walk can follow.
            raise FileContentError(FileMessages.INVALID_FILE) from exc
    return ReadDocument(tostring(root, encoding="unicode"), pictures)


def _too_large() -> FileContentError:
    return FileContentError(
        FileMessages.TOO_LARGE_TO_CONVERT, status.HTTP_413_CONTENT_TOO_LARGE
    )


def _part(package: zipfile.ZipFile, name: str) -> Optional[IO[bytes]]:
    """A part of the package, open, or ``None`` when it has none by that name."""
    try:
        return package.open(name)
    except KeyError:
        return None


def _elements(handle: IO[bytes], body: str = "") -> Iterator[Element]:
    """The children of the XML's root, and of its ``body`` element, each
    complete and cleared once the caller has it, so a body is held a block at
    a time. Callers tell the two apart by tag."""
    open_tags: list[str] = []
    for event, element in iterparse(handle, events=("start", "end")):
        if event == "start":
            open_tags.append(element.tag)
            continue
        open_tags.pop()
        if len(open_tags) == 1 or (body and open_tags and open_tags[-1] == body):
            yield element
            element.clear()


# ── The XHTML ────────────────────────────────────────────────────────────────


def _add_text(parent: Element, text: str) -> None:
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _formatted(parent: Element, formats: tuple[str, ...]) -> Element:
    """Where text with ``formats`` goes inside ``parent``: one element per
    format, nested."""
    for tag in formats:
        parent = SubElement(parent, tag)
    return parent


def _picture(parent: Element, name: str, alt: str, width: int, height: int) -> None:
    image = SubElement(parent, "ac:image")
    if alt:
        image.set("ac:alt", alt)
    if width > 0 and height > 0:
        image.set("ac:width", str(width))
        image.set("ac:height", str(height))
    SubElement(image, "ri:attachment", {"ri:filename": name})


class _Container:
    """Blocks written into one element — the body, or a table cell — with the
    lists open at its end."""

    def __init__(self, element: Element) -> None:
        self.element = element
        #: Open lists, outermost first: ``(level, which list, list, its last
        #: item)``.
        self.lists: list[tuple[int, object, Element, Optional[Element]]] = []

    def block(self, tag: str) -> Element:
        self.lists.clear()
        return SubElement(self.element, tag)

    def item(self, level: int, ordered: bool, key: object) -> Element:
        """A new list item at ``level`` (0 outermost) of the source list
        ``key`` names, in a list of the kind ``ordered`` says, nested under
        the last item of a shallower list. A different list at the same level
        starts a list of its own, so its numbering starts again."""
        tag = "ol" if ordered else "ul"
        while self.lists and (
            self.lists[-1][0] > level
            or (
                self.lists[-1][0] == level
                and (self.lists[-1][2].tag != tag or self.lists[-1][1] != key)
            )
        ):
            self.lists.pop()
        if not self.lists or self.lists[-1][0] < level:
            under = self.lists[-1][3] if self.lists else None
            if self.lists and under is None:
                under = SubElement(self.lists[-1][2], "li")
            listed = SubElement(under if under is not None else self.element, tag)
            self.lists.append((level, key, listed, None))
        current_level, _, listed, _ = self.lists[-1]
        entry = SubElement(listed, "li")
        self.lists[-1] = (current_level, key, listed, entry)
        return entry


def _rows_text_table(container: _Container, rows: list[list[str]]) -> None:
    """A table nested too deep, kept as one paragraph per row."""
    for cells in rows:
        line = " | ".join(text for text in cells if text)
        if line:
            _add_text(container.block("p"), line)


def _heading_tag(level: int) -> str:
    return f"h{min(max(level, 1), 6)}"


# ── Word ─────────────────────────────────────────────────────────────────────

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

#: English Metric Units to a pixel at 96 dpi.
_EMU_PER_PX = 9525
_HEADING_NAME = re.compile(r"^heading (\d)$")
#: Word's built-in list styles, whose number is the level they sit at.
_LIST_NAME = re.compile(r"^list (?:bullet|number) (\d)$")
#: Wrappers whose content reads as if they were not there.
_DOCX_WRAPPERS = frozenset(
    f"{_W}{tag}" for tag in ("ins", "moveTo", "smartTag", "customXml", "fldSimple")
)
_DOCX_RUN_FORMATS = (
    ("b", _BOLD),
    ("i", _ITALIC),
    ("u", _UNDERLINE),
    ("strike", _STRIKE),
    ("dstrike", _STRIKE),
)


def _on(element: Optional[Element]) -> Optional[bool]:
    """A run property: ``None`` when absent, else whether it is on."""
    if element is None:
        return None
    return element.get(f"{_W}val", "true").lower() not in ("0", "false", "off", "none")


@dataclass
class _WordStyle:
    name: str = ""
    based_on: str = ""
    outline: Optional[int] = None
    num_id: str = ""
    ilvl: int = 0
    run: Optional[Element] = None


class _Docx:
    def __init__(self, package: zipfile.ZipFile) -> None:
        self.package = package
        self.pictures: list[str] = []
        self.links: dict[str, str] = {}
        self.images: dict[str, str] = {}
        self.styles: dict[str, _WordStyle] = {}
        #: ``numId`` → ``ilvl`` → whether that level is numbered.
        self.numbering: dict[str, dict[int, bool]] = {}

    def read(self) -> Element:
        self.read_relationships()
        self.read_styles()
        self.read_numbering()
        root = Element("div")
        body = _Container(root)
        with self.package.open("word/document.xml") as handle:
            for element in _elements(handle, f"{_W}body"):
                for block in _unwrapped(element):
                    self.block(body, block, 0)
        return root

    # -- the package's other parts -------------------------------------------

    def read_relationships(self) -> None:
        handle = _part(self.package, "word/_rels/document.xml.rels")
        if handle is None:
            return
        with handle:
            for element in _elements(handle):
                if element.tag != f"{_RELS}Relationship":
                    continue
                target = element.get("Target") or ""
                kind = (element.get("Type") or "").rsplit("/", 1)[-1]
                if element.get("TargetMode") == "External":
                    if kind == "hyperlink":
                        self.links[element.get("Id") or ""] = target
                elif kind == "image":
                    self.images[element.get("Id") or ""] = posixpath.normpath(
                        posixpath.join("word", target)
                    ).lstrip("/")

    def read_styles(self) -> None:
        handle = _part(self.package, "word/styles.xml")
        if handle is None:
            return
        with handle:
            for element in _elements(handle):
                if element.tag != f"{_W}style":
                    continue
                style = _WordStyle(
                    name=_val(element.find(f"{_W}name")).lower(),
                    based_on=_val(element.find(f"{_W}basedOn")),
                    run=element.find(f"{_W}rPr"),
                )
                properties = element.find(f"{_W}pPr")
                if properties is not None:
                    outline = _val(properties.find(f"{_W}outlineLvl"))
                    style.outline = int(outline) if outline.isdigit() else None
                    numbered = properties.find(f"{_W}numPr")
                    if numbered is not None:
                        style.num_id = _val(numbered.find(f"{_W}numId"))
                        ilvl = _val(numbered.find(f"{_W}ilvl"))
                        style.ilvl = int(ilvl) if ilvl.isdigit() else 0
                self.styles[element.get(f"{_W}styleId") or ""] = style

    def read_numbering(self) -> None:
        handle = _part(self.package, "word/numbering.xml")
        if handle is None:
            return
        abstract: dict[str, dict[int, bool]] = {}
        nums: dict[str, str] = {}
        with handle:
            for element in _elements(handle):
                if element.tag == f"{_W}abstractNum":
                    levels: dict[int, bool] = {}
                    for lvl in element.findall(f"{_W}lvl"):
                        ilvl = lvl.get(f"{_W}ilvl") or ""
                        if ilvl.isdigit():
                            fmt = _val(lvl.find(f"{_W}numFmt"))
                            levels[int(ilvl)] = fmt not in ("", "bullet", "none")
                    abstract[element.get(f"{_W}abstractNumId") or ""] = levels
                elif element.tag == f"{_W}num":
                    nums[element.get(f"{_W}numId") or ""] = _val(
                        element.find(f"{_W}abstractNumId")
                    )
        self.numbering = {num: abstract.get(ref, {}) for num, ref in nums.items()}

    def chain(self, style_id: str) -> Iterator[_WordStyle]:
        """A style, then the styles it is based on."""
        seen: set[str] = set()
        while style_id and style_id not in seen and style_id in self.styles:
            seen.add(style_id)
            style = self.styles[style_id]
            yield style
            style_id = style.based_on

    # -- blocks ---------------------------------------------------------------

    def block(self, container: _Container, element: Element, depth: int) -> None:
        tag = element.tag
        if tag == f"{_W}p":
            self.paragraph(container, element)
        elif tag == f"{_W}tbl":
            self.table(container, element, depth + 1)

    def paragraph(self, container: _Container, paragraph: Element) -> None:
        properties = paragraph.find(f"{_W}pPr")
        style_id = (
            _val(properties.find(f"{_W}pStyle")) if properties is not None else ""
        )
        heading = self.heading_level(properties, style_id)
        # A heading's look is its level; a paragraph's style formats its text.
        base: list[Element] = []
        if heading is not None:
            target = container.block(_heading_tag(heading))
        else:
            base = [s.run for s in self.chain(style_id) if s.run is not None]
            base.reverse()
            numbered = self.list_level(properties, style_id)
            if numbered is None:
                target = container.block("p")
            else:
                level, ordered, num_id = numbered
                target = SubElement(container.item(level, ordered, num_id), "p")
        self.inline(target, paragraph, base)

    def heading_level(
        self, properties: Optional[Element], style_id: str
    ) -> Optional[int]:
        direct = (
            _val(properties.find(f"{_W}outlineLvl")) if properties is not None else ""
        )
        # Outline levels 0 to 8 are headings; 9 is body text.
        if direct.isdigit():
            return int(direct) + 1 if int(direct) < 9 else None
        for style in self.chain(style_id):
            if style.name == "title":
                return 1
            named = _HEADING_NAME.match(style.name)
            if named:
                return int(named.group(1))
            if style.outline is not None:
                return style.outline + 1 if style.outline < 9 else None
        return None

    def list_level(
        self, properties: Optional[Element], style_id: str
    ) -> Optional[tuple[int, bool, str]]:
        """The level a list paragraph sits at, whether it is numbered, and
        the list it belongs to."""
        num_id, ilvl = "", 0
        numbered = properties.find(f"{_W}numPr") if properties is not None else None
        if numbered is not None:
            num_id = _val(numbered.find(f"{_W}numId"))
            raw = _val(numbered.find(f"{_W}ilvl"))
            ilvl = int(raw) if raw.isdigit() else 0
        else:
            for style in self.chain(style_id):
                if style.num_id:
                    named = _LIST_NAME.match(style.name)
                    num_id = style.num_id
                    ilvl = int(named.group(1)) - 1 if named else style.ilvl
                    break
        if not num_id or num_id == "0":
            return None
        return ilvl, self.numbering.get(num_id, {}).get(ilvl, False), num_id

    def table(self, container: _Container, table: Element, depth: int) -> None:
        rows = [row for row in _children(table) if row.tag == f"{_W}tr"]
        if depth > _MAX_TABLE_DEPTH:
            _rows_text_table(
                container,
                [[_text_of(cell) for cell in _cells(row)] for row in rows],
            )
            return
        # Each row's cells with the grid column each starts at, so a cell
        # merged down can find the cells it covers in the rows below.
        grid: list[list[tuple[int, int, str, Element]]] = []
        for row in rows:
            column = _int(_val(row.find(f"{_W}trPr/{_W}gridBefore")))
            cells = []
            for cell in _cells(row):
                properties = cell.find(f"{_W}tcPr")
                span_raw = (
                    _val(properties.find(f"{_W}gridSpan"))
                    if properties is not None
                    else ""
                )
                span = int(span_raw) if span_raw.isdigit() and int(span_raw) > 0 else 1
                merge = (
                    properties.find(f"{_W}vMerge") if properties is not None else None
                )
                state = "" if merge is None else merge.get(f"{_W}val", "continue")
                cells.append((column, span, state, cell))
                column += span
            grid.append(cells)
        out = container.block("table")
        for index, (row, cells) in enumerate(zip(rows, grid)):
            header = row.find(f"{_W}trPr/{_W}tblHeader") is not None
            tr = SubElement(out, "tr")
            for column, span, state, cell in cells:
                if state == "continue":
                    continue
                td = SubElement(tr, "th" if header else "td")
                if span > 1:
                    td.set("colspan", str(span))
                if state == "restart":
                    down = 1
                    while index + down < len(grid) and any(
                        c == column and s == "continue"
                        for c, _, s, _ in grid[index + down]
                    ):
                        down += 1
                    if down > 1:
                        td.set("rowspan", str(down))
                inner = _Container(td)
                for child in _children(cell):
                    self.block(inner, child, depth)

    # -- inline ---------------------------------------------------------------

    def inline(self, target: Element, element: Element, base: list[Element]) -> None:
        """``element``'s runs, formatted over ``base``, its paragraph style's
        run properties."""
        for child in _children(element):
            if child.tag == f"{_W}r":
                self.run(target, child, base)
            elif child.tag == f"{_W}hyperlink":
                url = self.links.get(child.get(f"{_R}id") or "")
                self.inline(
                    SubElement(target, "a", href=url) if url else target, child, base
                )

    def run_formats(self, run: Element, base: list[Element]) -> tuple[str, ...]:
        """What a run looks like: its paragraph style's formats, then its
        character style's, then its own, each overriding the last."""
        properties = run.find(f"{_W}rPr")
        layers = list(base)
        if properties is not None:
            style_id = _val(properties.find(f"{_W}rStyle"))
            character = [s.run for s in self.chain(style_id) if s.run is not None]
            layers.extend(reversed(character))
            layers.append(properties)
        on: dict[str, bool] = {}
        for layer in layers:
            for name, tag in _DOCX_RUN_FORMATS:
                found = _on(layer.find(f"{_W}{name}"))
                if found is not None:
                    on[tag] = found
            align = _val(layer.find(f"{_W}vertAlign"))
            if align:
                on[_SUP] = align == "superscript"
                on[_SUB] = align == "subscript"
        return tuple(tag for tag in _FORMATS if on.get(tag))

    def run(self, target: Element, run: Element, base: list[Element]) -> None:
        formats = self.run_formats(run, base)
        for child in run:
            tag = child.tag
            if tag == f"{_W}t":
                _add_text(_formatted(target, formats), child.text or "")
            elif tag == f"{_W}tab":
                _add_text(target, "\t")
            elif tag == f"{_W}noBreakHyphen":
                _add_text(target, "-")
            elif tag == f"{_W}cr" or (
                tag == f"{_W}br" and child.get(f"{_W}type") in (None, "textWrapping")
            ):
                SubElement(target, "br")
            elif tag == f"{_W}drawing":
                self.drawing(target, child)
            elif tag == f"{_MC}AlternateContent":
                choice = child.find(f"{_MC}Choice")
                if choice is not None:
                    self.run(target, choice, base)

    def drawing(self, target: Element, drawing: Element) -> None:
        for frame in drawing:
            blip = frame.find(f".//{_A}blip")
            name = (
                self.images.get(blip.get(f"{_R}embed") or "")
                if blip is not None
                else None
            )
            if not name:
                continue
            properties = frame.find(f"{_WP}docPr")
            alt = ""
            if properties is not None:
                alt = properties.get("descr") or properties.get("title") or ""
            extent = frame.find(f"{_WP}extent")
            width = height = 0
            if extent is not None:
                width = _int(extent.get("cx")) // _EMU_PER_PX
                height = _int(extent.get("cy")) // _EMU_PER_PX
            if name not in self.pictures:
                self.pictures.append(name)
            _picture(target, name, alt.strip(), width, height)


def _val(element: Optional[Element]) -> str:
    return (element.get(f"{_W}val") or "") if element is not None else ""


def _int(raw: Optional[str]) -> int:
    return int(raw) if raw and raw.isdigit() else 0


def _unwrapped(element: Element) -> list[Element]:
    """``element``, or what it holds when it is a wrapper Word puts around
    content: a content control, a tracked insertion. A contents table, which
    whatever opens the document makes again, is left out."""
    if element.tag == f"{_W}sdt":
        gallery = element.find(f"{_W}sdtPr/{_W}docPartObj/{_W}docPartGallery")
        if _val(gallery) == "Table of Contents":
            return []
        return _children(element.find(f"{_W}sdtContent"))
    if element.tag in _DOCX_WRAPPERS:
        return _children(element)
    return [element]


def _children(element: Optional[Element]) -> list[Element]:
    """An element's children, with Word's wrappers opened up."""
    if element is None:
        return []
    return [inner for child in element for inner in _unwrapped(child)]


def _cells(row: Element) -> list[Element]:
    return [cell for cell in _children(row) if cell.tag == f"{_W}tc"]


def _text_of(element: Element) -> str:
    return "".join(t.text or "" for t in element.iter(f"{_W}t")).strip()


# ── OpenDocument ─────────────────────────────────────────────────────────────

_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
_FO = "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}"
_SVG = "{urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0}"
_XLINK = "{http://www.w3.org/1999/xlink}"

#: Pixels at 96 dpi in one of each length unit OpenDocument writes.
_PX_PER_UNIT = {
    "in": 96.0,
    "cm": 96 / 2.54,
    "mm": 96 / 25.4,
    "pt": 96 / 72,
    "pc": 16.0,
    "px": 1.0,
}
_LENGTH = re.compile(r"^([0-9.]+)([a-z]+)$")
#: Inline content that isn't the text: notes, comments, tracked-change marks.
_ODT_SKIPPED_INLINE = frozenset(
    {
        f"{_TEXT}note",
        f"{_OFFICE}annotation",
        f"{_OFFICE}annotation-end",
        f"{_TEXT}change",
        f"{_TEXT}change-start",
        f"{_TEXT}change-end",
    }
)


@dataclass
class _OdtStyle:
    parent: str = ""
    #: Formats it sets: ``tag`` → on or off.
    formats: dict[str, bool] = field(default_factory=dict)
    #: ``text:level`` → numbered, for a list style.
    levels: dict[int, bool] = field(default_factory=dict)


class _Odt:
    def __init__(self, package: zipfile.ZipFile) -> None:
        self.package = package
        self.pictures: list[str] = []
        self.styles: dict[str, _OdtStyle] = {}
        #: How many separate lists the body has started.
        self.lists = 0
        #: How many more table cells may be written.
        self.cells_left = MAX_TABLE_CELLS

    def read(self) -> Element:
        handle = _part(self.package, "styles.xml")
        if handle is not None:
            with handle:
                for element in _elements(handle):
                    if element.tag in (
                        f"{_OFFICE}styles",
                        f"{_OFFICE}automatic-styles",
                    ):
                        self.read_styles(element)
        root = Element("div")
        body = _Container(root)
        with self.package.open("content.xml") as handle:
            for element in _elements(handle, f"{_OFFICE}text"):
                if element.tag == f"{_OFFICE}automatic-styles":
                    self.read_styles(element)
                else:
                    self.block(body, element, 0)
        return root

    def read_styles(self, styles: Element) -> None:
        for element in styles:
            name = element.get(f"{_STYLE}name") or ""
            if element.tag == f"{_STYLE}style":
                style = _OdtStyle(
                    parent=element.get(f"{_STYLE}parent-style-name") or ""
                )
                text = element.find(f"{_STYLE}text-properties")
                if text is not None:
                    style.formats = _odt_formats(text)
                self.styles[name] = style
            elif element.tag == f"{_TEXT}list-style":
                levels: dict[int, bool] = {}
                for level_style in element:
                    level = level_style.get(f"{_TEXT}level") or ""
                    if level.isdigit():
                        levels[int(level)] = (
                            level_style.tag == f"{_TEXT}list-level-style-number"
                            and bool(level_style.get(f"{_STYLE}num-format"))
                        )
                self.styles[name] = _OdtStyle(levels=levels)

    def chain(self, name: str) -> Iterator[tuple[str, _OdtStyle]]:
        seen: set[str] = set()
        while name and name not in seen and name in self.styles:
            seen.add(name)
            style = self.styles[name]
            yield name, style
            name = style.parent

    def formats(self, name: str, base: tuple[str, ...] = ()) -> tuple[str, ...]:
        """What text in style ``name`` looks like, inside text that looks
        like ``base``."""
        on = dict.fromkeys(base, True)
        for _, style in reversed(list(self.chain(name))):
            on.update(style.formats)
        return tuple(tag for tag in _FORMATS if on.get(tag))

    # -- blocks ---------------------------------------------------------------

    def block(self, container: _Container, element: Element, depth: int) -> None:
        tag = element.tag
        if tag == f"{_TEXT}h":
            outline = element.get(f"{_TEXT}outline-level") or "1"
            target = container.block(
                _heading_tag(int(outline) if outline.isdigit() else 1)
            )
            self.inline(target, element, ())
        elif tag == f"{_TEXT}p":
            style = element.get(f"{_TEXT}style-name") or ""
            if any(name == "Title" for name, _ in self.chain(style)):
                self.inline(container.block("h1"), element, ())
            else:
                self.inline(container.block("p"), element, self.formats(style))
        elif tag == f"{_TEXT}list":
            if element.get(f"{_TEXT}continue-numbering") != "true" and not (
                element.get(f"{_TEXT}continue-list")
            ):
                self.lists += 1
            self.read_list(container, element, 0, None, self.lists, depth)
        elif tag == f"{_TABLE}table":
            self.table(container, element, depth + 1)
        elif tag == f"{_DRAW}frame":
            self.frame(container.block("p"), element)
        elif tag == f"{_TEXT}section":
            for child in element:
                self.block(container, child, depth)

    def read_list(
        self,
        container: _Container,
        listed: Element,
        level: int,
        inherited: Optional[str],
        key: int,
        depth: int,
    ) -> None:
        """A list and the lists inside it, all part of the body's list
        ``key``. What an item holds besides lists is read as blocks into the
        item, which the walker lays on its line."""
        style_name = listed.get(f"{_TEXT}style-name") or inherited
        style = self.styles.get(style_name or "")
        ordered = bool(style and style.levels.get(level + 1))
        for item in listed:
            if item.tag not in (f"{_TEXT}list-item", f"{_TEXT}list-header"):
                continue
            entry: Optional[_Container] = None
            for child in item:
                if child.tag == f"{_TEXT}list":
                    self.read_list(container, child, level + 1, style_name, key, depth)
                    continue
                if entry is None:
                    entry = _Container(container.item(level, ordered, key))
                self.block(entry, child, depth)

    def table(self, container: _Container, table: Element, depth: int) -> None:
        rows: list[tuple[bool, Element]] = []
        for child in table:
            if child.tag == f"{_TABLE}table-row":
                rows.append((False, child))
            elif child.tag in (
                f"{_TABLE}table-header-rows",
                f"{_TABLE}table-rows",
                f"{_TABLE}table-row-group",
            ):
                header = child.tag == f"{_TABLE}table-header-rows"
                rows.extend(
                    (header, row) for row in child if row.tag == f"{_TABLE}table-row"
                )
        if depth > _MAX_TABLE_DEPTH:
            _rows_text_table(
                container,
                [
                    [
                        " ".join(
                            "".join(p.itertext()) for p in cell.iter(f"{_TEXT}p")
                        ).strip()
                        for cell in row
                        if cell.tag == f"{_TABLE}table-cell"
                    ]
                    for _, row in rows
                ],
            )
            return
        out = container.block("table")
        row_times = self.repeats([row for _, row in rows], "number-rows-repeated")
        for (header, row), times in zip(rows, row_times):
            cells = [cell for cell in row if cell.tag == f"{_TABLE}table-cell"]
            cell_times = self.repeats(cells, "number-columns-repeated")
            for _ in range(times):
                tr = SubElement(out, "tr")
                for cell, repeat in zip(cells, cell_times):
                    for _ in range(repeat):
                        self.cells_left -= 1
                        if self.cells_left < 0:
                            raise _too_large()
                        td = SubElement(tr, "th" if header else "td")
                        for attribute, name in (
                            ("number-columns-spanned", "colspan"),
                            ("number-rows-spanned", "rowspan"),
                        ):
                            span = cell.get(f"{_TABLE}{attribute}") or ""
                            if span.isdigit() and int(span) > 1:
                                td.set(name, span)
                        inner = _Container(td)
                        for child in cell:
                            self.block(inner, child, depth)

    def repeats(self, elements: list[Element], attribute: str) -> list[int]:
        """How many times each row or cell is written: as many as its
        ``table:<attribute>`` says, except an empty one with nothing filled
        after it, which pads the table to the page's edge and is written
        once. Refuses a repeat past the cells left to write."""
        filled = [i for i, element in enumerate(elements) if not _empty(element)]
        last = filled[-1] if filled else -1
        out: list[int] = []
        for index, element in enumerate(elements):
            raw = element.get(f"{_TABLE}{attribute}") or ""
            times = int(raw) if raw.isdigit() and int(raw) > 1 else 1
            if index > last:
                times = 1
            if times > self.cells_left:
                raise _too_large()
            out.append(times)
        return out

    # -- inline ---------------------------------------------------------------

    def inline(
        self, target: Element, element: Element, formats: tuple[str, ...]
    ) -> None:
        _add_text(_formatted(target, formats), element.text or "")
        for child in element:
            tag = child.tag
            if tag in _ODT_SKIPPED_INLINE:
                pass
            elif tag == f"{_TEXT}span":
                style = child.get(f"{_TEXT}style-name") or ""
                self.inline(target, child, self.formats(style, formats))
            elif tag == f"{_TEXT}a":
                href = child.get(f"{_XLINK}href") or ""
                self.inline(
                    SubElement(target, "a", href=href) if href else target,
                    child,
                    formats,
                )
            elif tag == f"{_TEXT}s":
                _add_text(target, " ")
            elif tag == f"{_TEXT}tab":
                _add_text(target, "\t")
            elif tag == f"{_TEXT}line-break":
                SubElement(target, "br")
            elif tag == f"{_DRAW}frame":
                self.frame(target, child)
            elif tag == f"{_DRAW}a":
                for frame in child.iter(f"{_DRAW}frame"):
                    self.frame(target, frame)
            else:
                # A field or a bookmark: what it shows, if anything.
                self.inline(target, child, formats)
            _add_text(_formatted(target, formats), child.tail or "")

    def frame(self, target: Element, frame: Element) -> None:
        image = frame.find(f"{_DRAW}image")
        href = (image.get(f"{_XLINK}href") or "") if image is not None else ""
        if not href or "://" in href or href.startswith("/"):
            return
        name = posixpath.normpath(href.removeprefix("./"))
        alt = (
            "".join(
                "".join(part.itertext())
                for part in (frame.find(f"{_SVG}desc"), frame.find(f"{_SVG}title"))
                if part is not None
            )
            or frame.get(f"{_DRAW}name")
            or ""
        )
        if name not in self.pictures:
            self.pictures.append(name)
        _picture(
            target,
            name,
            alt.strip(),
            _pixels(frame.get(f"{_SVG}width")),
            _pixels(frame.get(f"{_SVG}height")),
        )


def _empty(element: Element) -> bool:
    """Whether a row or cell shows nothing: no text and no picture."""
    return (
        not "".join(element.itertext()).strip()
        and element.find(f".//{_DRAW}frame") is None
    )


def _odt_formats(properties: Element) -> dict[str, bool]:
    formats: dict[str, bool] = {}
    weight = properties.get(f"{_FO}font-weight")
    if weight:
        formats[_BOLD] = weight == "bold" or (weight.isdigit() and int(weight) >= 600)
    style = properties.get(f"{_FO}font-style")
    if style:
        formats[_ITALIC] = style in ("italic", "oblique")
    for attribute, tag in (
        ("text-underline-style", _UNDERLINE),
        ("text-line-through-style", _STRIKE),
    ):
        value = properties.get(f"{_STYLE}{attribute}")
        if value:
            formats[tag] = value != "none"
    position = (properties.get(f"{_STYLE}text-position") or "").split()
    if position:
        first = position[0]
        formats[_SUP] = first == "super" or (
            first.endswith("%") and not first.startswith(("-", "0"))
        )
        formats[_SUB] = first == "sub" or first.startswith("-")
    return formats


def _pixels(raw: Optional[str]) -> int:
    match = _LENGTH.match((raw or "").strip())
    if not match or match.group(2) not in _PX_PER_UNIT:
        return 0
    try:
        return round(float(match.group(1)) * _PX_PER_UNIT[match.group(2)])
    except ValueError:
        return 0
