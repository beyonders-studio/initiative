"""Atlassian Document Format → markdown.

The inbound twin of ``services.export.lexical``, and it keeps that module's
degradation contract pointing the other way: **an unknown node with text
renders its text, an unknown container recurses into its children, and
anything else is dropped and counted.** A node type Atlassian adds next year
can therefore never fail an import — at worst it arrives as its own words, or
as a number in the report saying something did not survive.

The count is the point of the "and counted" half. An import that silently
loses a macro is worse than one that says it lost three, because the second
can be checked. :class:`AdfResult` carries ``dropped_nodes`` so the plan can
say what will be lost *before* anything is written, and the report can say
what was.

Two things are not text and so are not the walker's to decide:

* **Media** — an ADF ``media`` node names a Media Services id, which is not
  the attachment id and which Jira exposes no mapping for. Matching is done
  by the node's ``alt`` (Jira sets it to the filename) by whoever fetched the
  attachments, so this module takes a resolver and falls back to the filename
  as plain text.
* **Mentions** — who an Atlassian account is *here* is the wizard's people
  step, not a guess. Same shape: a resolver, falling back to the display name.

Markdown is GFM, because that is what the app's own renderer reads
(``remark-gfm``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

# How deep a document may nest before the walker stops descending is the one
# limit every converter shares; content nested past it is left out.
from app.services.import_engine.limits import MAX_NESTING_DEPTH

#: A panel's kind to the line that opens the quote it becomes.
_PANEL_TITLES = {
    "info": "Info",
    "note": "Note",
    "warning": "Warning",
    "success": "Success",
    "error": "Error",
}

#: Marks that survive as markdown, innermost first — the order they wrap in.
_TEXT_MARKS = ("code", "strike", "em", "strong")

#: Marks that carry no markdown of their own. The text they cover is kept;
#: only the styling goes. Listed rather than defaulted so a new mark lands in
#: the "unknown" path and is counted instead of being silently ignored.
_STYLE_ONLY_MARKS = frozenset(
    {
        "underline",
        "textColor",
        "backgroundColor",
        "subsup",
        "alignment",
        "indentation",
        "breakout",
    }
)

MediaResolver = Callable[[str, str | None], str | None]
MentionResolver = Callable[[str, str | None], str | None]


@dataclass
class ChecklistLine:
    """One ADF task lifted out of a description into the task's own checklist."""

    text: str
    done: bool = False


@dataclass
class AdfResult:
    """What a document turned into, and what it cost.

    ``checklist`` is empty unless the document held a ``taskList`` *and* the
    caller asked for it to be lifted — a Jira description's checkboxes belong
    in the task's checklist, where they can be ticked, rather than frozen into
    its body. In a comment they stay inline, because a comment has no
    checklist to lift them into.
    """

    markdown: str = ""
    checklist: list[ChecklistLine] = field(default_factory=list)
    #: How many nodes were dropped entirely — neither rendered nor recursed.
    dropped_nodes: int = 0


def adf_to_markdown(
    doc: Any,
    *,
    lift_tasks: bool = False,
    media: MediaResolver | None = None,
    mention: MentionResolver | None = None,
) -> AdfResult:
    """Render one ADF document.

    ``lift_tasks`` pulls ``taskList`` items out of the body into
    :attr:`AdfResult.checklist` — what a task description wants. Left false
    (a comment) they render inline as ``- [ ]`` / ``- [x]``.

    ``media`` is called with ``(filename_or_id, alt)`` and returns the path to
    reference, or ``None`` to fall back to plain text. ``mention`` is called
    with ``(account_id, display_name)`` and returns a handle to link, or
    ``None`` for the plain name.
    """
    walker = _Walker(lift_tasks=lift_tasks, media=media, mention=mention)
    if not isinstance(doc, dict):
        return AdfResult()
    blocks = walker.blocks(doc.get("content") or [], depth=0)
    return AdfResult(
        markdown=_join(blocks),
        checklist=walker.checklist,
        dropped_nodes=walker.dropped,
    )


def _join(blocks: list[str]) -> str:
    """Block bodies into one document: one blank line between them, no
    leading or trailing whitespace, and no run of three newlines."""
    text = "\n\n".join(block for block in blocks if block.strip())
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


class _Walker:
    def __init__(
        self,
        *,
        lift_tasks: bool,
        media: MediaResolver | None,
        mention: MentionResolver | None,
    ) -> None:
        self.lift_tasks = lift_tasks
        self.media = media
        self.mention = mention
        self.checklist: list[ChecklistLine] = []
        self.dropped = 0

    # --- blocks ------------------------------------------------------------

    def blocks(self, nodes: Any, *, depth: int) -> list[str]:
        if not isinstance(nodes, list) or depth > MAX_NESTING_DEPTH:
            return []
        out: list[str] = []
        for node in nodes:
            if isinstance(node, dict):
                out.extend(self.block(node, depth=depth))
        return out

    def block(self, node: dict, *, depth: int) -> list[str]:
        kind = node.get("type")
        children = node.get("content") or []
        attrs = node.get("attrs") or {}

        if kind == "paragraph":
            text = self.inline(children, depth=depth + 1)
            return [text] if text.strip() else []

        if kind == "heading":
            level = attrs.get("level")
            level = level if isinstance(level, int) and 1 <= level <= 6 else 1
            text = self.inline(children, depth=depth + 1)
            return [f"{'#' * level} {text}"] if text.strip() else []

        if kind in ("bulletList", "orderedList"):
            return [self.list_block(node, depth=depth, indent="")]

        if kind == "taskList":
            return self.task_list(node, depth=depth, indent="")

        if kind == "codeBlock":
            language = attrs.get("language") or ""
            body = self.plain(children, depth=depth + 1)
            return [f"```{language}\n{body}\n```"]

        if kind == "blockquote":
            return [_prefix(self.blocks(children, depth=depth + 1), "> ")]

        if kind == "panel":
            title = _PANEL_TITLES.get(str(attrs.get("panelType") or "").lower())
            body = self.blocks(children, depth=depth + 1)
            lines = [f"**{title}**"] if title else []
            return [_prefix(lines + body, "> ")]

        if kind in ("expand", "nestedExpand"):
            title = str(attrs.get("title") or "").strip()
            body = self.blocks(children, depth=depth + 1)
            return ([f"**{title}**"] if title else []) + body

        if kind == "table":
            return [self.table(node, depth=depth)]

        if kind == "rule":
            return ["---"]

        if kind in ("mediaSingle", "mediaGroup"):
            text = self.inline(children, depth=depth + 1)
            return [text] if text.strip() else []

        if kind == "decisionList":
            lines = []
            for item in children:
                if isinstance(item, dict) and item.get("type") == "decisionItem":
                    lines.append(
                        f"- ✅ {self.inline(item.get('content') or [], depth=depth + 1)}"
                    )
            return ["\n".join(lines)] if lines else []

        if kind in ("layoutSection", "layoutColumn"):
            # Columns in sequence: markdown has no columns, and the reading
            # order is the one thing that must survive.
            return self.blocks(children, depth=depth + 1)

        if kind in ("bodiedExtension", "extension", "inlineExtension"):
            body = self.blocks(children, depth=depth + 1)
            if body:
                return body
            self.dropped += 1
            return []

        # Unknown. A container recurses; a leaf with text renders it; anything
        # else is dropped and counted — by ``inline_node``, which is where the
        # leaf ends up either way. Counting again here would report one lost
        # node as two.
        if children:
            return self.blocks(children, depth=depth + 1)
        text = self.inline([node], depth=depth + 1)
        return [text] if text.strip() else []

    def list_block(self, node: dict, *, depth: int, indent: str) -> str:
        ordered = node.get("type") == "orderedList"
        start = (node.get("attrs") or {}).get("order")
        number = start if isinstance(start, int) and start > 0 else 1
        lines: list[str] = []
        for item in node.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "listItem":
                continue
            marker = f"{number}. " if ordered else "- "
            lines.append(
                self.list_item(item, depth=depth, indent=indent, marker=marker)
            )
            number += 1
        return "\n".join(line for line in lines if line.strip())

    def list_item(self, item: dict, *, depth: int, indent: str, marker: str) -> str:
        """One line, plus whatever hangs under it indented to match."""
        head: list[str] = []
        tail: list[str] = []
        # Continuation lines align under the marker, which is how a nested
        # list stays inside its parent item rather than starting a new one.
        child_indent = indent + " " * len(marker)
        for child in item.get("content") or []:
            if not isinstance(child, dict):
                continue
            if child.get("type") in ("bulletList", "orderedList"):
                tail.append(
                    self.list_block(child, depth=depth + 1, indent=child_indent)
                )
            elif child.get("type") == "taskList":
                tail.extend(self.task_list(child, depth=depth + 1, indent=child_indent))
            else:
                rendered = self.block(child, depth=depth + 1)
                if not head:
                    head.extend(rendered)
                else:
                    tail.extend(_prefix([b], child_indent) for b in rendered)
        first = head[0] if head else ""
        out = [f"{indent}{marker}{first}"]
        out.extend(t for t in tail if t.strip())
        return "\n".join(out)

    def task_list(self, node: dict, *, depth: int, indent: str) -> list[str]:
        """Checkboxes: lifted into the task's checklist, or rendered inline.

        Lifting is what a Jira description wants — the boxes become the task's
        own checklist, where somebody can tick them. A comment has no
        checklist, so there they stay in the body as GFM checkboxes.
        """
        lines: list[str] = []
        for item in node.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "taskItem":
                continue
            state = (item.get("attrs") or {}).get("state")
            done = str(state).upper() == "DONE"
            text = self.inline(item.get("content") or [], depth=depth + 1)
            if self.lift_tasks:
                if text.strip():
                    self.checklist.append(ChecklistLine(text=text.strip(), done=done))
            else:
                box = "x" if done else " "
                lines.append(f"{indent}- [{box}] {text}")
        return ["\n".join(lines)] if lines else []

    def table(self, node: dict, *, depth: int) -> str:
        """A GFM table. A cell holding blocks is flattened to one line, and
        rowspan/colspan are ignored — markdown has neither, and a lost merge
        is better than a broken grid."""
        rows: list[list[str]] = []
        for row in node.get("content") or []:
            if not isinstance(row, dict) or row.get("type") != "tableRow":
                continue
            cells: list[str] = []
            for cell in row.get("content") or []:
                if not isinstance(cell, dict):
                    continue
                if cell.get("type") not in ("tableHeader", "tableCell"):
                    continue
                body = " ".join(
                    line
                    for block in self.blocks(cell.get("content") or [], depth=depth + 1)
                    for line in block.splitlines()
                )
                cells.append(body.replace("|", "\\|").strip())
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        head, *body = rows
        out = ["| " + " | ".join(head) + " |"]
        out.append("| " + " | ".join(["---"] * width) + " |")
        out.extend("| " + " | ".join(r) + " |" for r in body)
        return "\n".join(out)

    # --- inline ------------------------------------------------------------

    def inline(self, nodes: Any, *, depth: int) -> str:
        if not isinstance(nodes, list) or depth > MAX_NESTING_DEPTH:
            return ""
        return "".join(
            self.inline_node(n, depth=depth) for n in nodes if isinstance(n, dict)
        )

    def inline_node(self, node: dict, *, depth: int) -> str:
        kind = node.get("type")
        attrs = node.get("attrs") or {}

        if kind == "text":
            return self.marked(str(node.get("text") or ""), node.get("marks") or [])

        if kind == "hardBreak":
            # Two spaces then a newline: a line break inside a paragraph.
            return "  \n"

        if kind in ("media", "mediaInline"):
            return self.media_node(attrs)

        if kind == "mention":
            name = str(attrs.get("text") or "").lstrip("@") or "unknown"
            account = str(attrs.get("id") or "")
            resolved = self.mention(account, name) if self.mention else None
            return f"@[{name}]({resolved})" if resolved else f"@{name}"

        if kind == "emoji":
            return str(attrs.get("text") or attrs.get("shortName") or "")

        if kind in ("inlineCard", "blockCard", "embedCard"):
            url = str(attrs.get("url") or "")
            return f"[{url}]({url})" if url else ""

        if kind == "status":
            text = str(attrs.get("text") or "").strip()
            return f"**[{text}]**" if text else ""

        if kind == "date":
            return _iso_date(attrs.get("timestamp"))

        # Unknown: recurse into a container, render a leaf's own text, else
        # drop and count.
        children = node.get("content")
        if isinstance(children, list) and children:
            return self.inline(children, depth=depth + 1)
        if node.get("text"):
            return str(node.get("text"))
        self.dropped += 1
        return ""

    def media_node(self, attrs: dict) -> str:
        """An image if we can name the file, its filename if we cannot.

        ``alt`` is what Jira sets to the filename, and it is the only reliable
        handle on a media node — the ``id`` is a Media Services id with no
        mapping back to the attachment.
        """
        alt = str(attrs.get("alt") or "").strip()
        identifier = str(attrs.get("id") or "").strip()
        path = self.media(identifier or alt, alt or None) if self.media else None
        if path:
            return f"![{alt}]({path})"
        label = alt or identifier
        return label

    def marked(self, text: str, marks: Any) -> str:
        if not text or not isinstance(marks, list):
            return text
        names = {
            m.get("type"): (m.get("attrs") or {})
            for m in marks
            if isinstance(m, dict) and m.get("type")
        }
        # A link wraps whatever the styling marks produced.
        for mark in _TEXT_MARKS:
            if mark not in names:
                continue
            if mark == "code":
                text = f"`{text}`"
            elif mark == "strike":
                text = f"~~{text}~~"
            elif mark == "em":
                text = f"_{text}_"
            elif mark == "strong":
                text = f"**{text}**"
        href = str(names.get("link", {}).get("href") or "")
        if href:
            text = f"[{text}]({href})"
        for name in names:
            if (
                name not in _TEXT_MARKS
                and name != "link"
                and name not in _STYLE_ONLY_MARKS
            ):
                # An unknown mark keeps its text and is counted, exactly as an
                # unknown node with text would be.
                self.dropped += 1
        return text

    def plain(self, nodes: Any, *, depth: int) -> str:
        """Text with no markdown applied — a code block's body, where a ``*``
        is a ``*``."""
        if not isinstance(nodes, list) or depth > MAX_NESTING_DEPTH:
            return ""
        out: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "hardBreak":
                out.append("\n")
            elif node.get("text"):
                out.append(str(node.get("text")))
            elif node.get("content"):
                out.append(self.plain(node.get("content"), depth=depth + 1))
        return "".join(out)


def _prefix(blocks: list[str], marker: str) -> str:
    """Put ``marker`` in front of every line, including the empty ones that
    separate blocks — a blockquote with an unprefixed blank line is two
    blockquotes."""
    lines: list[str] = []
    for index, block in enumerate(blocks):
        if index:
            lines.append(marker.rstrip())
        lines.extend(
            f"{marker}{line}" if line else marker.rstrip()
            for line in block.splitlines()
        )
    return "\n".join(lines)


def _iso_date(timestamp: Any) -> str:
    """An ADF date is milliseconds since the epoch, as a string."""
    from datetime import datetime

    try:
        millis = int(timestamp)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=UTC).date().isoformat()
