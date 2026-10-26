"""Markdown → export blocks.

Task (and project/initiative) descriptions are Markdown — the web UI renders
them with react-markdown + GFM — so a PDF that prints the raw source shows
``**bold**`` literally. This module parses that Markdown (CommonMark plus the
GFM strikethrough/table extensions markdown-it ships) into the same JSON-safe
blocks/runs intermediate the Lexical converter emits, so the Typst templates
render both through one vocabulary:

* ``paragraph``/``heading``/``quote`` — ``runs`` of ``{text, bold, italic,
  strike, code, link}``; hard breaks are ``{"text": "\\n"}`` runs (softbreaks
  collapse to a space, matching react-markdown's default). A picture's run
  carries ``picture``, and a mention reads as the app shows it: a person's as
  ``@Name`` carrying ``mention``, their id; a thing's as its name.
* ``list`` — ``ordered`` flag and ``items`` of ``{runs, children}`` (nested
  lists recurse). A list whose every item opens with a GFM task box is a
  ``checklist``, each item ``checked`` or not.
* ``code`` — fenced/indented blocks with the info string as ``language``.
* ``table`` — rows of cells, each cell a runs list.
* ``hr``.

Unknown/unsupported nodes degrade to their text content — never dropped,
never markup."""

from __future__ import annotations

from typing import Any

from collections.abc import Iterator

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.tree import SyntaxTreeNode

from app.core.references import kind_for_trigger

_parser = MarkdownIt("commonmark").enable(["strikethrough", "table"])


def _newlines_break(state: StateCore) -> None:
    for token in state.tokens:
        for child in token.children or ():
            if child.type == "softbreak":
                child.type = "hardbreak"


#: Prose typed in a box — a comment — where a newline is a line break, as the
#: app shows it.
_line_parser = MarkdownIt("commonmark").enable(["strikethrough", "table"])
_line_parser.core.ruler.push("newlines_break", _newlines_break)

_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def blocks_from_markdown(
    text: str | None, *, line_breaks: bool = False
) -> list[dict[str, Any]]:
    """Parse Markdown into export blocks; empty/whitespace input → [].
    ``line_breaks`` reads every newline as a line break, as a comment's is."""
    if not text or not text.strip():
        return []
    parser = _line_parser if line_breaks else _parser
    return _blocks(SyntaxTreeNode(parser.parse(text)))


def runs_of(blocks: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """The runs of each paragraph, heading, quote, list item and table cell in
    ``blocks``, in reading order. A code block has none."""
    for block in blocks:
        if block["type"] == "list":
            for item in block["items"]:
                yield item["runs"]
                yield from runs_of(item.get("children", []))
        elif block["type"] == "table":
            for row in block["rows"]:
                yield from row
        elif "runs" in block:
            yield block["runs"]


def _blocks(parent: SyntaxTreeNode) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in parent.children:
        kind = node.type
        if kind == "paragraph":
            runs = _inline_runs(node)
            if runs:
                out.append({"type": "paragraph", "runs": runs})
        elif kind == "heading":
            out.append(
                {
                    "type": "heading",
                    "level": _HEADING_LEVELS.get(node.tag, 1),
                    "runs": _inline_runs(node),
                }
            )
        elif kind in ("bullet_list", "ordered_list"):
            out.append(_list_block(node))
        elif kind == "blockquote":
            # Flatten the quote's inner blocks into one runs stream (paragraph
            # boundaries become hard breaks) — the templates render quotes as
            # a single styled block, mirroring the Lexical converter.
            runs: list[dict[str, Any]] = []
            for i, inner in enumerate(_blocks(node)):
                if i > 0:
                    runs.append({"text": "\n"})
                runs.extend(inner.get("runs") or [{"text": inner.get("text", "")}])
            out.append({"type": "quote", "runs": runs})
        elif kind in ("fence", "code_block"):
            out.append(
                {
                    "type": "code",
                    "language": (node.info or "").strip().split(" ")[0]
                    if kind == "fence"
                    else "",
                    "text": node.content.rstrip("\n"),
                }
            )
        elif kind == "hr":
            out.append({"type": "hr"})
        elif kind == "table":
            out.append({"type": "table", "rows": _table_rows(node)})
        elif kind == "html_block":
            # Block HTML degrades to its literal text (never markup, never
            # dropped) — a leaf token, so the recursive fallback can't see it.
            content = node.content.strip()
            if content:
                out.append({"type": "paragraph", "runs": [{"text": content}]})
        elif node.children:
            # Unknown container: recurse so its content still exports.
            out.extend(_blocks(node))
        elif node.content.strip():
            # Unknown leaf: degrade to its literal text.
            out.append({"type": "paragraph", "runs": [{"text": node.content.strip()}]})
    return out


def _list_block(node: SyntaxTreeNode) -> dict[str, Any]:
    items = []
    for item in node.children:  # list_item nodes
        runs: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []
        for part in item.children:
            if part.type in ("bullet_list", "ordered_list"):
                children.append(_list_block(part))
            elif part.type in ("paragraph", "inline"):
                if runs:
                    runs.append({"text": "\n"})
                runs.extend(_inline_runs(part))
            else:
                # Block content inside an item (code, quote…): degrade to text.
                if runs:
                    runs.append({"text": "\n"})
                runs.append({"text": part.content})
        entry: dict[str, Any] = {"runs": runs}
        if children:
            entry["children"] = children
        items.append(entry)
    boxes = [_task_box(item["runs"]) for item in items]
    checklist = all(box is not None for box in boxes)
    if checklist:
        for item, box in zip(items, boxes):
            item["checked"] = box
            rest = item["runs"][0]["text"][4:]
            if rest:
                item["runs"][0]["text"] = rest
            else:
                del item["runs"][0]
    return {
        "type": "list",
        "ordered": node.type == "ordered_list",
        "checklist": checklist,
        "items": items,
    }


def _task_box(runs: list[dict[str, Any]]) -> bool | None:
    """Whether a list item opens with a GFM task box, ``[ ]`` or ``[x]`` and a
    space, and the box is ticked; ``None`` where it does not."""
    first = runs[0] if runs else {}
    text = first.get("text", "") if first.keys() == {"text"} else ""
    if text[:1] == "[" and text[2:3] == "]" and text[1:2] in (" ", "x", "X"):
        if text[3:4] in (" ", "\t"):
            return text[1:2] != " "
    return None


def _table_rows(node: SyntaxTreeNode) -> list[list[list[dict[str, Any]]]]:
    rows: list[list[list[dict[str, Any]]]] = []
    for section in node.children:  # thead / tbody
        for tr in section.children:
            rows.append([_inline_runs(cell) for cell in tr.children])
    return rows


def _inline_runs(node: SyntaxTreeNode) -> list[dict[str, Any]]:
    """Collect a block node's inline content as runs."""
    inline = next((c for c in node.children if c.type == "inline"), None)
    target = inline if inline is not None else node
    return _runs(target, frozenset(), None)


def _runs(
    node: SyntaxTreeNode, flags: frozenset[str], link: str | None
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    children = node.children
    folded = -1
    for index, child in enumerate(children):
        if index == folded:
            continue
        kind = child.type
        following = children[index + 1] if index + 1 < len(children) else None
        mention = _mention(child.content, following) if kind == "text" else None
        if mention is not None:
            before, label, person = mention
            if before:
                runs.append(_run(before, flags, link))
            if person is None:
                runs.append(_run(label, flags, link))
            else:
                runs.append(_run(f"@{label}", flags, link) | person)
            folded = index + 1
        elif kind == "text":
            if child.content:
                runs.append(_run(child.content, flags, link))
        elif kind == "code_inline":
            runs.append(_run(child.content, flags | {"code"}, link))
        elif kind == "strong":
            runs.extend(_runs(child, flags | {"bold"}, link))
        elif kind == "em":
            runs.extend(_runs(child, flags | {"italic"}, link))
        elif kind == "s":
            runs.extend(_runs(child, flags | {"strike"}, link))
        elif kind == "link":
            href = str(child.attrs.get("href") or "") or link
            runs.extend(_runs(child, flags, href))
        elif kind == "softbreak":
            # react-markdown's default: a soft break renders as a space.
            runs.append(_run(" ", flags, link))
        elif kind == "hardbreak":
            runs.append({"text": "\n"})
        elif kind == "image":
            # No fetching in a description render: degrade to the alt text
            # linked to the source URL.
            alt = child.content or str(child.attrs.get("alt") or "") or "[image]"
            src = str(child.attrs.get("src") or "")
            runs.append(_run(alt, flags, src or link) | {"picture": True})
        elif kind == "html_inline":
            runs.append(_run(child.content, flags, link))  # literal, not markup
        elif child.children:
            runs.extend(_runs(child, flags, link))
        elif child.content:
            runs.append(_run(child.content, flags, link))
    return runs


def _mention(
    text: str, following: SyntaxTreeNode | None
) -> tuple[str, str, dict[str, Any] | None] | None:
    """A text ending in a trigger and the link after it, read as the app reads
    a mention: ``@[Ada](42)`` a person, ``#task[Fix it](12)`` a thing. The
    trigger counts at a word's start, so ``email@[x](1)`` stays a link.

    The text before the trigger, the mention's name, and for a person what
    their run carries (their id, where the mention has one); ``None`` where
    the two are no mention.
    """
    if following is None or following.type != "link":
        return None
    href = str(following.attrs.get("href") or "")
    label = "".join(node.content for node in following.walk() if not node.children)
    if text.endswith("@"):
        if href and not (href.isascii() and href.isdigit()):
            return None
        trigger, person = "@", {"mention": int(href)} if href else {}
    else:
        _, sign, word = text.rpartition("#")
        if not (sign and kind_for_trigger(word) and label):
            return None
        if not (href.isascii() and href.isdigit()):
            return None
        trigger, person = sign + word, None
    before = text[: -len(trigger)]
    if before and not (before[-1].isspace() or before[-1] in "([{"):
        return None
    return before, label, person


def _run(text: str, flags: frozenset[str], link: str | None) -> dict[str, Any]:
    run: dict[str, Any] = {"text": text}
    for flag in flags:
        run[flag] = True
    if link:
        run["link"] = link
    return run
