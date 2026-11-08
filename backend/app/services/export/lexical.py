"""Lexical editor-state conversion for document exports (md / pdf / docx).

One tree walk (``blocks_from_editor_state``) turns the serialized editor
state into a JSON-safe intermediate — a flat list of typed blocks with
inline "runs" — that all three renderers consume: the Markdown emitter
(zipped with an ``assets/`` folder when images are referenced), the DOCX
emitter (python-docx, images embedded), and the ``document`` Typst template
(images staged into the compile root by the backend).

Degradation contract: any unknown node with ``text`` renders as text (this
covers mentions, references, hashtags, emojis, keywords — all TextNode
subclasses); unknown containers recurse into their children; embeds
(YouTube/Tweet) degrade to a link; a reference embed (``![[ ]]``) to a note
callout holding its name; anything else is dropped silently. A new
editor node can never break an export, it just exports as its text.

Images: only same-guild uploads (``/uploads/{community_id}/…``) are collected as
assets and embedded — an external URL is never fetched; it renders as a plain
link instead.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Callable

from app.services.export.stamp import markdown_stamp, stamp_docx
from app.services.platform.csv_export import safe_filename_component

# Lexical TextNode format bitmask.
_BOLD = 1
_ITALIC = 2
_STRIKE = 4
_UNDERLINE = 8
_CODE = 16

ReadBlob = Callable[[str], bytes]

# ---------------------------------------------------------------------------
# Parse: editor state -> blocks + referenced assets
# ---------------------------------------------------------------------------


def blocks_from_editor_state(
    content: dict, *, guild_id: int
) -> tuple[list[dict], list[dict]]:
    """Walk the serialized editor state into (blocks, assets).

    ``assets`` lists the same-guild upload blobs the document references:
    ``{"key": <storage key>, "name": <archive-safe file name>}``.
    """
    parser = _Parser(guild_id)
    root = (content or {}).get("root") or {}
    parser.walk_children(root.get("children") or [])
    parser.flush_paragraph()
    return parser.blocks, list(parser.assets.values())


class _Parser:
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.blocks: list[dict] = []
        self.assets: dict[str, dict] = {}
        self._pending_runs: list[dict] = []

    # -- inline ------------------------------------------------------------

    def collect_runs(self, children: list, link: str | None = None) -> list[dict]:
        runs: list[dict] = []
        for node in children or []:
            ntype = node.get("type")
            if ntype in ("link", "autolink"):
                runs.extend(
                    self.collect_runs(
                        node.get("children") or [], link=node.get("url") or link
                    )
                )
                continue
            if ntype == "linebreak":
                runs.append({"text": "\n"})
                continue
            if ntype == "status":
                # A status reads as its word, set apart the way the pill is.
                label = str(node.get("text") or "").strip()
                if label:
                    runs.append({"text": label.upper(), "bold": True})
                continue
            if ntype == "image":
                # An inline image splits the paragraph: emit what we have,
                # then the image as its own block.
                self._pending_runs.extend(runs)
                runs = []
                self.flush_paragraph()
                self.image_block(node)
                continue
            if ntype == "excalidraw":
                # A drawing splits it the same way. Its scene travels as it
                # is: markdown keeps it, and a format that cannot draw it
                # leaves it out.
                self._pending_runs.extend(runs)
                runs = []
                self.flush_paragraph()
                self.blocks.append(
                    {"type": "drawing", "data": str(node.get("data") or "")}
                )
                continue
            text = node.get("text")
            if isinstance(text, str) and text:
                fmt = int(node.get("format") or 0)
                run: dict[str, Any] = {"text": text}
                if fmt & _BOLD:
                    run["bold"] = True
                if fmt & _ITALIC:
                    run["italic"] = True
                if fmt & _STRIKE:
                    run["strike"] = True
                if fmt & _UNDERLINE:
                    run["underline"] = True
                if fmt & _CODE:
                    run["code"] = True
                if link:
                    run["link"] = link
                runs.append(run)
                continue
            # Unknown node: recurse if it has children, else drop.
            if node.get("children"):
                runs.extend(self.collect_runs(node["children"], link=link))
        return runs

    def flush_paragraph(self) -> None:
        if self._pending_runs:
            self.blocks.append({"type": "paragraph", "runs": self._pending_runs})
            self._pending_runs = []

    # -- blocks ------------------------------------------------------------

    def walk_children(self, children: list) -> None:
        for node in children or []:
            self.block(node)

    def block(self, node: dict) -> None:
        ntype = node.get("type")
        children = node.get("children") or []
        if ntype == "paragraph":
            runs = self.collect_runs(children)
            runs = self._pending_runs + runs
            self._pending_runs = []
            if runs:
                self.blocks.append({"type": "paragraph", "runs": runs})
        elif ntype == "heading":
            tag = str(node.get("tag") or "h1")
            level = int(tag[1]) if len(tag) == 2 and tag[1].isdigit() else 1
            self.blocks.append(
                {"type": "heading", "level": level, "runs": self.collect_runs(children)}
            )
            self.flush_paragraph()
        elif ntype == "quote":
            self.blocks.append({"type": "quote", "runs": self.collect_runs(children)})
            self.flush_paragraph()
        elif ntype == "code":
            self.blocks.append(
                {
                    "type": "code",
                    "language": str(node.get("language") or ""),
                    "text": _code_text(children),
                }
            )
        elif ntype == "list":
            self.blocks.append(self.list_block(node))
        elif ntype == "horizontalrule":
            self.blocks.append({"type": "hr"})
        elif ntype == "table":
            self.blocks.append(self.table_block(node))
        elif ntype == "callout":
            self.flush_paragraph()
            self.blocks.append(
                {
                    "type": "callout",
                    "variant": str(node.get("variant") or "note"),
                    "collapsed": node.get("collapsed") is True,
                    "blocks": self.nested(children),
                }
            )
        elif ntype == "reference-embed":
            # A thing shown in full. The export cannot read it live, so it keeps
            # the panel and the name the page had for it.
            self.flush_paragraph()
            name = str(node.get("text") or "")
            if name:
                self.blocks.append(
                    {
                        "type": "callout",
                        "variant": "note",
                        "blocks": [{"type": "paragraph", "runs": [{"text": name}]}],
                    }
                )
        elif ntype == "layout-container":
            self.flush_paragraph()
            items = [c for c in children if c.get("type") == "layout-item"]
            self.blocks.append(
                {
                    "type": "columns",
                    "widths": _column_widths(
                        str(node.get("templateColumns") or ""), len(items)
                    ),
                    "columns": [
                        self.nested(item.get("children") or []) for item in items
                    ],
                }
            )
        elif ntype == "image":
            self.image_block(node)
        elif ntype in ("youtube", "tweet"):
            url = _embed_url(node)
            if url:
                self.blocks.append(
                    {"type": "paragraph", "runs": [{"text": url, "link": url}]}
                )
        elif children:
            # Unknown container (layout containers/items, future nodes):
            # its children still export.
            self.walk_children(children)

    def nested(self, children: list) -> list[dict]:
        """Blocks inside a block — a callout's, a column's — sharing this
        document's one asset list, however deep an image sits."""
        inner = _Parser(self.guild_id)
        inner.assets = self.assets
        inner.walk_children(children)
        inner.flush_paragraph()
        return inner.blocks

    def list_block(self, node: dict) -> dict:
        list_type = node.get("listType")  # "bullet" | "number" | "check"
        items: list[dict] = []
        for child in node.get("children") or []:
            if child.get("type") != "listitem":
                continue
            nested = [
                gc for gc in (child.get("children") or []) if gc.get("type") == "list"
            ]
            inline = [
                gc for gc in (child.get("children") or []) if gc.get("type") != "list"
            ]
            item: dict[str, Any] = {"runs": self.collect_runs(inline)}
            if list_type == "check":
                item["checked"] = bool(child.get("checked"))
            if nested:
                item["children"] = [self.list_block(n) for n in nested]
            items.append(item)
        return {
            "type": "list",
            "ordered": list_type == "number",
            "checklist": list_type == "check",
            "items": items,
        }

    def table_block(self, node: dict) -> dict:
        """A table as rows of cells' runs.

        A table with merged cells also carries ``spans`` — each cell's
        ``[colspan, rowspan]``, row by row — and ``width``, the columns of
        the grid those spans sit in. A table without merges carries neither,
        and renders exactly as it always has.
        """
        rows: list[list[list[dict]]] = []
        spans: list[list[list[int]]] = []
        for row in node.get("children") or []:
            if row.get("type") != "tablerow":
                continue
            cells: list[list[dict]] = []
            row_spans: list[list[int]] = []
            for cell in row.get("children") or []:
                if cell.get("type") != "tablecell":
                    continue
                cell_runs: list[dict] = []
                for para in cell.get("children") or []:
                    if cell_runs:
                        cell_runs.append({"text": "\n"})
                    cell_runs.extend(self.collect_runs(para.get("children") or []))
                cells.append(cell_runs)
                row_spans.append(
                    [_span(cell.get("colSpan")), _span(cell.get("rowSpan"))]
                )
            if cells:
                rows.append(cells)
                spans.append(row_spans)
        block: dict[str, Any] = {"type": "table", "rows": rows}
        if any(span != [1, 1] for row in spans for span in row):
            block["spans"] = spans
            block["width"] = _grid_width(spans)
        return block

    def image_block(self, node: dict) -> None:
        src = str(node.get("src") or "")
        alt = str(node.get("altText") or "")
        prefix = f"/uploads/{self.guild_id}/"
        if src.startswith(prefix):
            key = src.removeprefix(prefix).split("?")[0]
            existing = self.assets.get(key)
            if existing is None:
                # Distinct keys can sanitize to the same name ("a img.png" /
                # "a_img.png") — suffix until unique so one archive entry
                # can't silently overwrite another.
                name = safe_filename_component(key)
                taken = {a["name"] for a in self.assets.values()}
                if name in taken:
                    stem, dot, ext = name.rpartition(".")
                    base = stem if dot else name
                    n = 2
                    while name in taken:
                        name = f"{base}-{n}{dot}{ext}" if dot else f"{base}-{n}"
                        n += 1
                existing = {"key": key, "name": name}
                self.assets[key] = existing
            block = {"type": "image", "asset": existing["name"], "alt": alt}
            block.update(_image_size(node))
            self.blocks.append(block)
        elif src:
            # External (or cross-guild) image: never fetched — link only.
            self.blocks.append({"type": "image", "asset": None, "url": src, "alt": alt})


def _column_widths(template: str, count: int) -> list[int]:
    """A column template (``1fr 3fr``) as whole percentages, one per
    column; a template that does not say is shared out evenly."""
    parts: list[float] = []
    for part in template.split():
        try:
            value = float(part.removesuffix("fr"))
        except ValueError:
            value = 1.0
        parts.append(value if value > 0 else 1.0)
    if len(parts) != count:
        parts = [1.0] * count
    total = sum(parts) or 1.0
    return [round(part / total * 100) for part in parts]


def _span(value: Any) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else 1
    )


def _grid_width(spans: list[list[list[int]]]) -> int:
    """How many columns a table's grid has, once merged cells take theirs."""
    return max((len(row) for row in _grid(spans)), default=0)


def _grid(spans: list[list[list[int]]]) -> list[list[tuple[int, int] | None]]:
    """Each grid position's owner as ``(row, cell)``, or ``None`` for a hole.

    A cell spanning columns owns every position it covers in its row; one
    spanning rows owns its column in the rows below, which is where a later
    row's cells skip past it.
    """
    grid: list[list[tuple[int, int] | None]] = []
    for r, row in enumerate(spans):
        while len(grid) <= r:
            grid.append([])
        column = 0
        for c, (colspan, rowspan) in enumerate(row):
            while column < len(grid[r]) and grid[r][column] is not None:
                column += 1
            for dr in range(rowspan):
                while len(grid) <= r + dr:
                    grid.append([])
                line = grid[r + dr]
                while len(line) < column + colspan:
                    line.append(None)
                for dc in range(colspan):
                    line[column + dc] = (r, c)
            column += colspan
    return grid[: len(spans)]


def _image_size(node: dict) -> dict:
    """The editor stores a resize as width/height px on the node ("inherit"
    when untouched). Width alone is carried — the renderers derive height
    from the aspect ratio, so a stale stored height can't distort."""
    for field in ("width", "height"):
        value = node.get(field)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ):
            return {field: int(value)}
    return {}


def _code_text(children: list) -> str:
    parts: list[str] = []
    for node in children or []:
        if node.get("type") == "linebreak":
            parts.append("\n")
        else:
            text = node.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _embed_url(node: dict) -> str | None:
    if node.get("type") == "youtube" and node.get("videoID"):
        return f"https://www.youtube.com/watch?v={node['videoID']}"
    if node.get("type") == "tweet" and node.get("tweetID"):
        return f"https://x.com/i/status/{node['tweetID']}"
    return None


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

#: No guild's uploads are this one's, so every picture keeps its own address
#: rather than being rewritten as a file inside an export archive.
_NO_ARCHIVE = -1


def editor_markdown(content: Any, *, reading: bool = False) -> str:
    """An editor state as Markdown text alone: no title, no stamp, no archive.

    ``reading`` lays columns out one after another and leaves drawings out,
    for a reader that wants the words in order rather than the page.
    """
    blocks, _assets = blocks_from_editor_state(content, guild_id=_NO_ARCHIVE)
    if reading:
        blocks = _in_line(blocks, callouts=False)
    if not blocks:
        return ""
    return _markdown_text({"blocks": blocks}).strip()


def render_markdown(data: dict, read_blob: ReadBlob) -> tuple[bytes, str, str | None]:
    """Emit Markdown. With referenced assets: a zip of ``{stem}.md`` +
    ``assets/``, image refs rewritten to the relative paths. Returns
    (content, content_type, filename_override)."""
    stem = str(data.get("stem") or "document")
    md = _markdown_text(data)
    assets = data.get("assets") or []
    if not assets:
        return md.encode("utf-8"), "text/markdown; charset=utf-8", None

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{stem}.md", md)
        for asset in assets:
            try:
                content = read_blob(asset["key"])
            except Exception:
                # A referenced image that's gone from storage must not fail
                # the whole export — the .md keeps its (dangling) ref, same
                # as the document itself would show a broken image.
                continue
            archive.writestr(f"assets/{asset['name']}", content)
    return buffer.getvalue(), "application/zip", f"{stem}.zip"


def _markdown_text(data: dict) -> str:
    lines = markdown_stamp(data)
    title = str(data.get("title") or "").strip()
    if title:
        lines.append(f"# {title}")
        lines.append("")
    for block in data.get("blocks") or []:
        rendered = _md_block(block)
        if rendered:
            lines.extend(rendered)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _md_block(block: dict, indent: str = "") -> list[str]:
    btype = block.get("type")
    if btype == "heading":
        # Document title is H1; shift content headings down one level.
        level = min(int(block.get("level") or 1) + 1, 6)
        return [f"{'#' * level} {_md_runs(block.get('runs') or [])}"]
    if btype == "quote":
        return [f"> {_md_runs(block.get('runs') or [])}"]
    if btype == "callout":
        # Obsidian's callout, which GitHub reads as an alert. A folded one
        # carries Obsidian's fold marker; a page or a Word file shows it open.
        fold = "-" if block.get("collapsed") else ""
        lines = [f"> [!{block.get('variant') or 'note'}]{fold}"]
        for index, inner in enumerate(block.get("blocks") or []):
            if index:
                lines.append(">")
            lines.extend(f"> {line}" if line else ">" for line in _md_block(inner))
        return lines
    if btype == "columns":
        # Pandoc's fenced divs: plain markdown has no columns of its own.
        lines = [":::: {.columns}"]
        widths = block.get("widths") or []
        for index, column in enumerate(block.get("columns") or []):
            width = widths[index] if index < len(widths) else 0
            lines.append(f'::: {{.column width="{width}%"}}')
            for inner_index, inner in enumerate(column):
                if inner_index:
                    lines.append("")
                lines.extend(_md_block(inner))
            lines.append(":::")
        lines.append("::::")
        return lines
    if btype == "code":
        return [f"```{block.get('language') or ''}", block.get("text") or "", "```"]
    if btype == "drawing":
        # The editor's own form: the scene in a fence tagged ``excalidraw``,
        # longer than any run of backticks inside it.
        data = block.get("data") or ""
        longest = max((len(run) for run in re.findall(r"`+", data)), default=0)
        fence = "`" * max(3, longest + 1)
        return [f"{fence}excalidraw", data, fence]
    if btype == "hr":
        return ["---"]
    if btype == "pagebreak":
        # Markdown has no pages; the heading after it says where one began.
        return []
    if btype == "image":
        alt = _md_escape(block.get("alt") or "")
        if block.get("asset"):
            return [f"![{alt}](assets/{block['asset']})"]
        return [f"![{alt}](<{block.get('url') or ''}>)"]
    if btype == "list":
        return _md_list(block, indent)
    if btype == "table":
        return _md_table(block)
    return [f"{indent}{_md_runs(block.get('runs') or [])}"]


def _md_list(block: dict, indent: str = "") -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(block.get("items") or [], start=1):
        if block.get("checklist"):
            box = "x" if item.get("checked") else " "
            marker = f"- [{box}]"
        elif block.get("ordered"):
            marker = f"{index}."
        else:
            marker = "-"
        lines.append(f"{indent}{marker} {_md_runs(item.get('runs') or [])}")
        for nested in item.get("children") or []:
            lines.extend(_md_list(nested, indent + "  "))
    return lines


def _md_table(block: dict) -> list[str]:
    rows = block.get("rows") or []
    if not rows:
        return []
    if block.get("spans"):
        return _md_merged_table(block)
    width = max(len(r) for r in rows)

    def cells(row: list) -> str:
        padded = list(row) + [[]] * (width - len(row))
        # Escape pipes AFTER rendering (a raw | in cell text would split the
        # column); _md_escape would also mangle the link syntax just emitted.
        rendered = (_md_runs(c).replace("\n", " ").replace("|", "\\|") for c in padded)
        return "| " + " | ".join(rendered) + " |"

    lines = [cells(rows[0]), "|" + "|".join(" --- " for _ in range(width)) + "|"]
    lines.extend(cells(row) for row in rows[1:])
    return lines


def _md_merged_table(block: dict) -> list[str]:
    """A table with merged cells, in MultiMarkdown's table syntax.

    Plain markdown has no merged cell, so this uses the extension that does:
    a cell spanning columns is followed by one extra ``|`` per column it
    takes (``| wide ||``), and a position covered by the cell above holds
    ``^^``. A reader that does not know the syntax still sees every cell's
    words, in order.
    """
    rows = block.get("rows") or []
    grid = _grid(block["spans"])
    width = int(block.get("width") or 0)

    def text(r: int, c: int) -> str:
        return _md_runs(rows[r][c]).replace("\n", " ").replace("|", "\\|").strip()

    lines: list[str] = []
    for r, line in enumerate(grid):
        parts: list[str] = []
        column = 0
        while column < width:
            owner = line[column] if column < len(line) else None
            if owner is None:
                parts.append("| ")
                column += 1
                continue
            if owner[0] != r:
                parts.append("| ^^ ")
                column += 1
                continue
            colspan = block["spans"][owner[0]][owner[1]][0]
            parts.append(f"| {text(*owner)} " + "|" * (colspan - 1))
            column += colspan
        lines.append("".join(parts) + "|")
        if r == 0:
            lines.append("|" + "|".join(" --- " for _ in range(width)) + "|")
    return lines


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def _md_runs(runs: list[dict]) -> str:
    parts: list[str] = []
    for run in runs or []:
        text = run.get("text") or ""
        if text == "\n":
            parts.append("  \n")
            continue
        if run.get("code"):
            # A backtick inside code needs the double-backtick spaced form.
            text = f"`` {text} ``" if "`" in text else f"`{text}`"
        else:
            if run.get("bold") and run.get("italic"):
                text = f"***{text}***"
            elif run.get("bold"):
                text = f"**{text}**"
            elif run.get("italic"):
                text = f"*{text}*"
            if run.get("strike"):
                text = f"~~{text}~~"
        if run.get("link"):
            text = f"[{text}](<{run['link']}>)"
        parts.append(text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def render_docx(data: dict, read_blob: ReadBlob) -> bytes:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Inches, Pt

    document = docx.Document()
    stamp_docx(document, data)
    title = str(data.get("title") or "").strip()
    if title:
        document.add_heading(title, level=0)

    def add_runs(paragraph, runs: list[dict]) -> None:
        for run in runs or []:
            text = run.get("text") or ""
            if text == "\n":
                paragraph.add_run().add_break(WD_BREAK.LINE)
                continue
            r = paragraph.add_run(text)
            r.bold = bool(run.get("bold")) or None
            r.italic = bool(run.get("italic")) or None
            r.font.strike = bool(run.get("strike")) or None
            r.underline = bool(run.get("underline")) or None
            if run.get("code"):
                r.font.name = "Consolas"
            if run.get("link"):
                # python-docx has no first-class hyperlink on runs; keep the
                # text and append the target so it survives visibly.
                r.underline = True
                paragraph.add_run(f" ({run['link']})").font.size = Pt(8)

    def add_list(block: dict, level: int = 0) -> None:
        style = "List Number" if block.get("ordered") else "List Bullet"
        # python-docx built-in list styles support levels 1-3 via suffixes.
        if level:
            style = f"{style} {min(level + 1, 3)}"
        for item in block.get("items") or []:
            paragraph = document.add_paragraph(style=style)
            if block.get("checklist"):
                paragraph.add_run("☑ " if item.get("checked") else "☐ ")
            add_runs(paragraph, item.get("runs") or [])
            for nested in item.get("children") or []:
                add_list(nested, level + 1)

    name_to_key = {a["name"]: a["key"] for a in (data.get("assets") or [])}

    def set_columns(section, widths: list[int] | None) -> None:
        """Lay a section out in columns at these percentage widths, or back
        in one column with ``None``."""
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        sect_pr = section._sectPr
        for existing in sect_pr.findall(qn("w:cols")):
            sect_pr.remove(existing)
        cols = OxmlElement("w:cols")
        if not widths:
            cols.set(qn("w:num"), "1")
            sect_pr.append(cols)
            return
        gap = 360  # twips: a quarter inch between columns
        # Lengths are EMUs; a twip is 635 of them.
        page = int(section.page_width or 0) - int(section.left_margin or 0)
        page -= int(section.right_margin or 0)
        usable = max(1, page // 635 - gap * (len(widths) - 1))
        total = sum(widths) or 1
        cols.set(qn("w:num"), str(len(widths)))
        cols.set(qn("w:space"), str(gap))
        cols.set(qn("w:equalWidth"), "0")
        for width in widths:
            col = OxmlElement("w:col")
            col.set(qn("w:w"), str(max(1, int(usable * width / total))))
            col.set(qn("w:space"), str(gap))
            cols.append(col)
        sect_pr.append(cols)

    def add_columns(block: dict) -> None:
        """Columns as Word's own: a continuous section in as many columns as
        the page had, each column's blocks ended by a column break, then a
        section back in one column for what follows."""
        from docx.enum.section import WD_SECTION

        columns = block.get("columns") or []
        widths = list(block.get("widths") or [])
        if len(widths) != len(columns):
            widths = [1] * len(columns)
        set_columns(document.add_section(WD_SECTION.CONTINUOUS), widths)
        for index, column in enumerate(columns):
            for inner in _in_line(column):
                add_block(inner)
            if index < len(columns) - 1:
                document.add_paragraph().add_run().add_break(WD_BREAK.COLUMN)
        set_columns(document.add_section(WD_SECTION.CONTINUOUS), None)

    def add_table(block: dict) -> None:
        rows = block.get("rows") or []
        if not rows:
            return
        spans = block.get("spans")
        if not spans:
            width = max(len(r) for r in rows)
            table = document.add_table(rows=len(rows), cols=width)
            table.style = "Table Grid"
            for r_idx, row in enumerate(rows):
                for c_idx, cell_runs in enumerate(row):
                    add_runs(table.cell(r_idx, c_idx).paragraphs[0], cell_runs)
            return
        grid = _grid(spans)
        table = document.add_table(rows=len(grid), cols=int(block.get("width") or 1))
        table.style = "Table Grid"
        placed: set[tuple[int, int]] = set()
        for r_idx, line in enumerate(grid):
            for c_idx, owner in enumerate(line):
                if owner is None or owner in placed:
                    continue
                placed.add(owner)
                colspan, rowspan = spans[owner[0]][owner[1]]
                cell = table.cell(r_idx, c_idx)
                if colspan > 1 or rowspan > 1:
                    cell = cell.merge(
                        table.cell(
                            min(r_idx + rowspan, len(grid)) - 1,
                            min(c_idx + colspan, len(table.columns)) - 1,
                        )
                    )
                add_runs(cell.paragraphs[0], rows[owner[0]][owner[1]])

    def add_block(block: dict) -> None:
        btype = block.get("type")
        if btype == "heading":
            document.add_heading(
                _plain_text(block.get("runs") or []),
                level=min(int(block.get("level") or 1), 9),
            )
        elif btype == "quote":
            add_runs(
                document.add_paragraph(style="Intense Quote"), block.get("runs") or []
            )
        elif btype == "code":
            paragraph = document.add_paragraph()
            code_run = paragraph.add_run(block.get("text") or "")
            code_run.font.name = "Consolas"
            code_run.font.size = Pt(9)
        elif btype == "hr":
            separator = document.add_paragraph("· · ·")
            separator.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif btype == "pagebreak":
            document.add_page_break()
        elif btype == "list":
            add_list(block)
        elif btype == "table":
            add_table(block)
        elif btype == "image":
            if block.get("asset"):
                key = name_to_key.get(block["asset"])
                if key:
                    # Editor resize is CSS px; Word wants inches (96 dpi).
                    # Cap at the ~6.5" content width of the default page.
                    width_px = block.get("width")
                    height_px = block.get("height")
                    if width_px:
                        size = {"width": Inches(min(width_px / 96, 6.5))}
                    elif height_px:
                        size = {"height": Inches(min(height_px / 96, 9))}
                    else:
                        size = {"width": Inches(6)}
                    try:
                        document.add_picture(io.BytesIO(read_blob(key)), **size)
                    except Exception:
                        # Unreadable/unsupported image: degrade to alt text
                        # rather than failing the whole document.
                        document.add_paragraph(block.get("alt") or "[image]")
            else:
                paragraph = document.add_paragraph(block.get("alt") or "")
                paragraph.add_run(f" ({block.get('url') or ''})")
        else:  # paragraph
            add_runs(document.add_paragraph(), block.get("runs") or [])

    for top in data.get("blocks") or []:
        if top.get("type") == "columns" and top.get("columns"):
            add_columns(top)
            continue
        for block in _in_line([top]):
            add_block(block)

    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _in_line(blocks: list[dict], *, callouts: bool = True) -> list[dict]:
    """Blocks with each set of columns laid out one after another, drawings
    left out and, with ``callouts``, each callout as its kind in a bold label
    and then what it holds — for a renderer with no panel or grid of its own
    to draw."""
    out: list[dict] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "callout" and callouts:
            label = str(block.get("variant") or "note").capitalize()
            out.append({"type": "quote", "runs": [{"text": label, "bold": True}]})
            out.extend(_in_line(block.get("blocks") or []))
        elif btype == "callout":
            inner = _in_line(block.get("blocks") or [], callouts=False)
            out.append({**block, "blocks": inner})
        elif btype == "columns":
            for column in block.get("columns") or []:
                out.extend(_in_line(column, callouts=callouts))
        elif btype == "drawing":
            continue
        else:
            out.append(block)
    return out


def _plain_text(runs: list[dict]) -> str:
    return "".join(run.get("text") or "" for run in runs)
