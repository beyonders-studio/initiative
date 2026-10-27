"""References as older builds wrote them, rewritten as this one writes them.

Before files were files a reference named a ``document``, a ``[[ ]]`` link was
a ``wikilink`` node of its own, and the composer wrote ``#doc``. A collection
was a gallery, and each of its pictures a ``gallery_image``. A body written
then, or a backup taken then, still says so. These functions rewrite one, in
either shape a body takes — a Lexical editor state or running text:

* ``document`` is ``file`` and ``gallery`` is ``collection``, under the same id;
* ``gallery_image`` is ``file``, under the id ``files`` maps the picture to. A
  picture with no file leaves the words the reference was written with;
* a ``wikilink`` is an ``entity-mention`` of its file, or its words when it
  never named one, as the browser's editor converted one on opening;
* ``#doc`` and ``#document`` are ``#file``, ``#gallery`` is ``#collection``,
  and ``#gallery-image`` is ``#file``.

The old spellings are stated here rather than read from the kinds: they are
what older builds wrote, which does not change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.core.references import (
    REF_SEPARATOR,
    REFERENCE_NODES,
    SOURCE_REF,
    reference_as_text,
    text_node,
)

#: Picture id -> the id of the file it became.
PictureFiles = Mapping[int, int]

#: Kinds that kept their ids under a new name.
_RENAMED = {"document": "file", "gallery": "collection"}
_PICTURE = "gallery_image"
_FILE = "file"
#: The words after ``#`` the composer wrote for those kinds.
_TRIGGERS = {"doc": _FILE, "document": _FILE, "gallery": "collection"}
_PICTURE_TRIGGERS = frozenset({"gallery-image", _PICTURE})

#: A reference in running text, by id (``#doc[Spec](7)``) or, in a backup, by
#: the ref it had (``#doc[Spec](document:7)``).
_TEXT_REFERENCE = re.compile(r"#([\w-]+)\[([^\]]*)\]\(((?:[a-z_]+:)?)(\d+)\)")


def _file_of(picture: Any, files: PictureFiles) -> int | None:
    if isinstance(picture, bool):
        return None
    try:
        return files.get(int(picture))
    except (TypeError, ValueError):
        return None


def rewrite_ref(ref: str, files: PictureFiles) -> str | None:
    """``kind:id`` as this build spells it, or ``None`` for a picture with no
    file."""
    kind, separator, rest = ref.partition(REF_SEPARATOR)
    if kind == _PICTURE:
        picture, aspect_separator, aspect = rest.partition(REF_SEPARATOR)
        file_id = _file_of(picture, files)
        if file_id is None:
            return None
        return f"{_FILE}{REF_SEPARATOR}{file_id}{aspect_separator}{aspect}"
    if kind in _RENAMED:
        return f"{_RENAMED[kind]}{separator}{rest}"
    return ref


def _wikilink(node: dict[str, Any]) -> dict[str, Any]:
    """A ``[[ ]]`` link as the reference it always was. One a backup carries
    still waits on the ref it had, and is placed like any other."""
    file_id = node.get("documentId")
    resolved = (
        isinstance(file_id, int) and not isinstance(file_id, bool) and file_id > 0
    )
    waiting = node.get(SOURCE_REF)
    title = node.get("documentTitle")
    if not resolved and not isinstance(waiting, str):
        return text_node(str(title or ""))
    mention: dict[str, Any] = {
        "type": "entity-mention",
        "version": 1,
        "entityType": _FILE,
        "entityId": file_id if resolved else 0,
        "text": next((v for v in (title, node.get("text")) if v is not None), ""),
    }
    if isinstance(waiting, str):
        mention[SOURCE_REF] = waiting
    return mention


def _reference(node: dict[str, Any], files: PictureFiles) -> dict[str, Any]:
    """A reference node naming what its old kind became."""
    key = "chipKind" if isinstance(node.get("chipKind"), str) else "entityType"
    value = node.get(key)
    if not isinstance(value, str):
        return node
    kind, separator, aspect = value.partition(REF_SEPARATOR)
    out = dict(node)
    if kind == _PICTURE:
        file_id = _file_of(node.get("entityId"), files)
        if file_id is None:
            return reference_as_text(node)
        out["entityId"] = file_id
        kind = _FILE
    out[key] = f"{_RENAMED.get(kind, kind)}{separator}{aspect}"
    waiting = node.get(SOURCE_REF)
    if isinstance(waiting, str):
        ref = rewrite_ref(waiting, files)
        if ref is None:
            return reference_as_text(node)
        out[SOURCE_REF] = ref
    return out


def rewrite_body(content: Any, files: PictureFiles) -> Any:
    """A Lexical editor state with every reference spelled as this build
    writes it. Returns new dicts and never edits ``content``."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if node.get("type") == "wikilink":
            node = _wikilink(node)
        if node.get("type") in REFERENCE_NODES:
            return _reference(node, files)
        children = node.get("children")
        if isinstance(children, list):
            return {**node, "children": [walk(child) for child in children]}
        return node

    return {**content, "root": walk(content["root"])}


def rewrite_text(text: str | None, files: PictureFiles) -> str | None:
    """Running text with every reference spelled as this build writes it."""
    if not text:
        return text

    def rewrite(match: re.Match[str]) -> str:
        word, label, prefix, number = match.groups()
        old_kind = prefix.removesuffix(REF_SEPARATOR)
        if word in _PICTURE_TRIGGERS or old_kind == _PICTURE:
            file_id = files.get(int(number))
            if file_id is None:
                return label
            ref = f"{_FILE}{REF_SEPARATOR}" if prefix else ""
            return f"#{_FILE}[{label}]({ref}{file_id})"
        if prefix:
            prefix = f"{_RENAMED.get(old_kind, old_kind)}{REF_SEPARATOR}"
        return f"#{_TRIGGERS.get(word, word)}[{label}]({prefix}{number})"

    return _TEXT_REFERENCE.sub(rewrite, text)
