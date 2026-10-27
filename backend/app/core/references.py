"""What can be referred to, and how a reference is written down.

A reference names one thing: ``task:12``. Everything that points at work is
built on it — a `#` link, a `[[ ]]` link, an `@` mention, and the smart chips
that add a fact about the thing on top.

This module owns the vocabulary because it belongs to all of those shapes and
to none of them in particular — including how one is READ back out of something
somebody wrote, which is the same question whether the body is a Lexical editor
state or the running text of a comment.

What a reference RESOLVES to — the column holding the name, the resource whose
sharing gates it — is derived from the search registry in
:mod:`app.db.reference_targets`, which needs the models.
"""

import re
from enum import Enum
from typing import Any, Callable

from app.core.search import SearchEntityType

#: How the parts of a reference are joined: ``task:12``, ``task:12:status``.
REF_SEPARATOR = ":"

#: Indexed kinds that are not things you point at mid-sentence.
#:
#: A comment is a remark ON something — the thing it is on is what a reader
#: wants — and it has an opening line rather than a name. A decision about what
#: a reference means, rather than a fact about the database.
NOT_REFERENCEABLE: frozenset[SearchEntityType] = frozenset({SearchEntityType.comment})

#: Everything a reference can name. Derived, so a tool added to ``Tool`` can be
#: linked, mentioned and chipped without an edit here.
REFERENCEABLE_TYPES: tuple[SearchEntityType, ...] = tuple(
    entity_type
    for entity_type in SearchEntityType
    if entity_type not in NOT_REFERENCEABLE
)


def is_referenceable(entity_type: SearchEntityType) -> bool:
    """Whether a reference may name this kind."""
    return entity_type not in NOT_REFERENCEABLE


def format_ref(
    entity_type: SearchEntityType, entity_id: int, aspect: Enum | None = None
) -> str:
    """A reference as it is stored and asked for.

    ``task:12`` names the thing, which resolves to what it is called now.
    ``task:12:status`` names a fact about it.
    """
    parts = [entity_type.value, str(entity_id)]
    if aspect is not None:
        parts.append(aspect.value)
    return REF_SEPARATOR.join(parts)


#: The largest id a reference can name. Every id column here is a Postgres
#: ``integer``, so a number past this names nothing that exists — and it is a
#: number the database cannot be asked about, rather than one it answers "no"
#: to.
MAX_ENTITY_ID = 2_147_483_647

#: The characters an id is written with. Checked explicitly because
#: ``str.isdigit`` is true of more than these — a superscript is a digit by that
#: measure and not a number ``int`` will read.
_ID_DIGITS = frozenset("0123456789")


#: Kinds stored content still names by an older spelling. A body keeps what
#: was written into it, Yjs state included, so these are read for as long as
#: such content exists: a file was called a document before it was a file,
#: and a collection a gallery, under the same id.
_LEGACY_KINDS: dict[str, SearchEntityType] = {
    "document": SearchEntityType.file,
    "gallery": SearchEntityType.collection,
}


def _kind(value: str) -> SearchEntityType | None:
    """The kind a reference names, or None if nothing is called that."""
    legacy = _LEGACY_KINDS.get(value)
    if legacy is not None:
        return legacy
    try:
        return SearchEntityType(value)
    except ValueError:
        return None


def parse_ref(ref: str) -> tuple[SearchEntityType, int] | None:
    """The thing a bare reference names, or ``None`` for a string that names none.

    The inverse of :func:`format_ref` without an aspect. A reference that does
    not parse is dropped rather than refused: stored content outlives the build
    that wrote it, and a kind this build no longer offers should cost a reader
    the reference, not the page it is on. A reference arriving from a client is
    read the same way, so a malformed one narrows nothing instead of failing
    the request.
    """
    kind, separator, raw_id = ref.partition(REF_SEPARATOR)
    if not separator or not raw_id or not _ID_DIGITS.issuperset(raw_id):
        return None
    entity_id = int(raw_id)
    if entity_id > MAX_ENTITY_ID:
        return None
    entity_type = _kind(kind)
    if entity_type is None or not is_referenceable(entity_type):
        return None
    return entity_type, entity_id


#: Node types in a Lexical body that name another thing, and the field holding
#: its id.
#:
#: ``wikilink`` is what ``[[ ]]`` wrote before references were one thing;
#: ``entity-mention`` is what both triggers write now. Both count, which is what
#: stops "what links here" under-reporting the moment anyone uses ``#``. A
#: ``smart-chip`` and a ``reference-embed`` (``![[ ]]``) count too: a page
#: showing a task's status, or the task itself, is about that task.
REFERENCE_NODES: dict[str, str] = {
    "wikilink": "documentId",
    "entity-mention": "entityId",
    "smart-chip": "entityId",
    "reference-embed": "entityId",
}

#: The reference nodes the editor draws as a block of their own rather than in
#: a line of text.
BLOCK_REFERENCE_NODES = frozenset({"reference-embed"})


def reference_node_kind(node: dict[str, Any]) -> SearchEntityType | None:
    """The kind a reference node names. A chip spells it as the first half of
    its ``task:status``; a legacy wikilink is a file by construction and
    carries none."""
    chip_kind = node.get("chipKind")
    if isinstance(chip_kind, str):
        return _kind(chip_kind.split(REF_SEPARATOR)[0])
    return _kind(node.get("entityType", SearchEntityType.file.value))


def text_node(text: str, fmt: int = 0) -> dict[str, Any]:
    """A plain Lexical text node."""
    return {
        "type": "text",
        "version": 1,
        "text": text,
        "format": fmt,
        "style": "",
        "mode": "normal",
        "detail": 0,
    }


def reference_as_text(node: dict[str, Any]) -> dict[str, Any]:
    """A reference node as the words it was written with: a text node, or a
    paragraph holding one when the reference is a block of its own."""
    words = text_node(str(node.get("text") or ""), node.get("format") or 0)
    if node.get("type") not in BLOCK_REFERENCE_NODES:
        return words
    return {
        "type": "paragraph",
        "version": 1,
        "children": [words],
        "direction": None,
        "format": "",
        "indent": 0,
        "textFormat": 0,
        "textStyle": "",
    }


#: A reference written into running text: ``#task[Fix the bug](12)``. The kind
#: is part of the syntax, so one pattern reads every kind rather than one
#: pattern per kind. The word after ``#`` is spelled the way the composer
#: writes it — see :func:`kind_for_trigger`.
TEXT_REFERENCE = re.compile(r"#([\w-]+)\[([^\]]*)\]\((\d+)\)")

#: What the composer wrote for a file before the trigger words were
#: derived from the kinds, and what stored comments still say.
_LEGACY_TRIGGERS: dict[str, SearchEntityType] = {"doc": SearchEntityType.file}


def kind_for_trigger(word: str) -> SearchEntityType | None:
    """The kind the word after a ``#`` names in running text.

    The composer writes a kind kebabed — ``#wiki-page``, ``#counter-group`` —
    and once wrote ``#doc``; the kind's own spelling reads too.
    """
    legacy = _LEGACY_TRIGGERS.get(word)
    if legacy is not None:
        return legacy
    return _kind(word.replace("-", "_"))


def references_in_body(content: Any) -> set[tuple[SearchEntityType, int]]:
    """Every thing a Lexical body points at.

    Walks the editor state for reference nodes, chips included.
    """
    if not isinstance(content, dict):
        return set()

    found: set[tuple[SearchEntityType, int]] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        field = REFERENCE_NODES.get(node.get("type"))
        if field is not None:
            kind = reference_node_kind(node)
            entity_id = node.get(field)
            if kind is not None and isinstance(entity_id, int) and entity_id > 0:
                found.add((kind, entity_id))
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    root = content.get("root")
    if isinstance(root, dict):
        walk(root)
    return found


def references_in_text(content: str | None) -> set[tuple[SearchEntityType, int]]:
    """Every thing a plain-text body points at — what a comment is written in."""
    if not content:
        return set()
    found: set[tuple[SearchEntityType, int]] = set()
    for raw_kind, _label, raw_id in TEXT_REFERENCE.findall(content):
        kind = kind_for_trigger(raw_kind)
        if kind is not None:
            found.add((kind, int(raw_id)))
    return found


def unresolve_missing_wikilinks(
    content: dict[str, Any], live_file_ids: set[int]
) -> bool:
    """Blank the target of every ``[[ ]]`` pointing at a file that is gone.

    The node stays and renders as unresolved, which is what the editor shows for
    a link whose target was never picked. Returns whether anything changed.
    """
    return _blank_wikilinks(content, lambda doc_id: doc_id not in live_file_ids)


def unresolve_wikilinks_to(content: dict[str, Any], file_id: int) -> bool:
    """:func:`unresolve_missing_wikilinks` for one file that is going away."""
    return _blank_wikilinks(content, lambda doc_id: doc_id == file_id)


def _blank_wikilinks(
    content: dict[str, Any], should_blank: Callable[[int], bool]
) -> bool:
    changed = False

    def walk(node: Any) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        if node.get("type") == "wikilink":
            doc_id = node.get("documentId")
            if isinstance(doc_id, int) and doc_id > 0 and should_blank(doc_id):
                node["documentId"] = None
                changed = True
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    root = content.get("root")
    if isinstance(root, dict):
        walk(root)
    return changed
