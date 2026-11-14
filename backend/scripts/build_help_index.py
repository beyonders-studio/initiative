"""Build the Help panel's search index from a built help center.

``zensical build`` writes ``site/search.json``: every page and heading of the
help center, its text as HTML. This keeps what the panel searches and shows,
one entry per English page or heading down to level 3:

- ``title``: the heading, as plain text.
- ``section``: where it sits, the last two steps of its breadcrumb
  (``FAQ › Getting in``). A level-3 heading's breadcrumb ends in the level-2
  heading above it.
- ``location``: its address from the site's root
  (``en/faq/#my-invite-link-doesnt-work``).
- ``snippet``: the start of its text, as plain text, cut at a word.

The docs workflow (``.github/workflows/docs.yml``) publishes it beside the
pages as ``help-index.json``, and the app's Help panel reads it from there on
every server and every version since, so these four fields keep their names.

An input that is not the shape this reads stops with an error and a non-zero
exit, so a change to Zensical's format fails the deploy rather than publishing
an empty index. Standard library only: the workflow that runs it installs
Zensical and nothing of the backend's.
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

#: The pages the panel searches: the English ones, which are all there are.
LANGUAGE = "en/"
#: Pages (1), their sections (2) and the headings within those (3).
DEEPEST_LEVEL = 3
#: About how much of an entry's text the panel shows under its title.
SNIPPET_LENGTH = 200
SEPARATOR = " › "

#: Tags whose edges separate words, so the text either side is not run
#: together when the tags are dropped.
_BLOCK_TAGS = frozenset(
    {
        "blockquote",
        "br",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "summary",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)


class FormatError(Exception):
    """The input is not a Zensical search index this script can read."""


class _Text(HTMLParser):
    """The text of a piece of HTML, its entities decoded."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain(markup: str) -> str:
    """``markup`` as plain text, with its whitespace collapsed."""
    parser = _Text()
    parser.feed(markup)
    parser.close()
    return " ".join("".join(parser.parts).split())


def snippet(text: str) -> str:
    """The start of ``text``, about :data:`SNIPPET_LENGTH` characters, cut at
    a word."""
    if len(text) <= SNIPPET_LENGTH:
        return text
    cut = text[: SNIPPET_LENGTH + 1].rsplit(" ", 1)[0] or text[:SNIPPET_LENGTH]
    return cut.rstrip(" ,;:") + "…"


def _items(index: Any) -> list[dict[str, Any]]:
    """``index``'s items, each checked for the fields this reads."""
    if not isinstance(index, dict) or not isinstance(index.get("items"), list):
        raise FormatError("expected an object with an 'items' list")
    fields = {"location": str, "level": int, "title": str, "text": str, "path": list}
    for position, item in enumerate(index["items"]):
        if not isinstance(item, dict):
            raise FormatError(f"item {position} is not an object")
        for name, kind in fields.items():
            value = item.get(name)
            if not isinstance(value, kind) or isinstance(value, bool):
                raise FormatError(
                    f"item {position} has no {kind.__name__} '{name}': {item!r:.200}"
                )
        if not all(isinstance(step, str) for step in item["path"]):
            raise FormatError(f"item {position} has a 'path' that is not text")
    return index["items"]


def _section(trail: list[str], title: str) -> str:
    """The last two steps of ``trail``, with a step repeated after itself and
    the entry's own title left off the end."""
    steps: list[str] = []
    for step in trail:
        if step and (not steps or steps[-1] != step):
            steps.append(step)
    if steps and steps[-1] == title:
        steps.pop()
    return SEPARATOR.join(steps[-2:])


def build(index: Any) -> dict[str, list[dict[str, str]]]:
    """The panel's index, from a Zensical ``search.json``'s contents."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    shown: set[tuple[str, str]] = set()
    #: Each page's most recent level-2 heading, for the level-3 ones under it.
    heading: dict[str, str] = {}
    for item in _items(index):
        location, level = item["location"], item["level"]
        if not location.startswith(LANGUAGE) or level > DEEPEST_LEVEL:
            continue
        title = plain(item["title"])
        page = location.split("#", 1)[0]
        trail = [plain(step) for step in item["path"]]
        if level == 2:
            heading[page] = title
        elif level == 3 and page in heading:
            trail.append(heading[page])
        if not title or location in seen:
            continue
        section = _section(trail, title)
        if (title, section) in shown:
            continue
        seen.add(location)
        shown.add((title, section))
        entries.append(
            {
                "title": title,
                "section": section,
                "location": location,
                "snippet": snippet(plain(item["text"])),
            }
        )
    if not entries:
        raise FormatError(f"no entries under '{LANGUAGE}' up to level {DEEPEST_LEVEL}")
    return {"items": entries}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build_help_index.py SEARCH_JSON OUTPUT", file=sys.stderr)
        return 2
    source, target = Path(argv[0]), Path(argv[1])
    try:
        index = build(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, FormatError) as exc:
        print(f"build_help_index: {source}: {exc}", file=sys.stderr)
        return 1
    target.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"build_help_index: {len(index['items'])} entries written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
