"""A reference to another thing, carried across an export by the ref it had.

Inside the app a reference names what it points at by id: ``#task[Fix the
bug](41)`` in markdown (a task's description, a comment), and an
``entity-mention``, ``wikilink``, ``smart-chip`` or ``reference-embed`` node in
an editor state (a file, a post, a wiki page). An id means nothing where an export is
restored — on another instance, or in a community where 41 is something else,
and even in the same community a restore makes new rows — so the export writes
each reference as the **ref** of what it named where it was written
(``task:41``), and the restore points it at whatever that ref became:

* markdown: ``#task[Fix the bug](41)`` becomes ``#task[Fix the bug](task:41)``,
  which no reader takes for a reference until the restore puts an id back.
* editor state: the node keeps its text, carries ``importSourceRef`` and holds
  no id (``0``, or ``None`` for a wikilink) until it is placed.

Every row a restore creates registers itself with the job's link collector
under the ref it had (``task:41``, ``file:7``), so once the last entry has
flushed :func:`resolve_references` reads each marked body again and places
every reference: on the row its ref became in this job; on the original, when
the export came from this same community and the thing did not come over with
it; and otherwise on nothing — the reference is its title again, never a link
to whatever holds that id here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import undefer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.references import (
    REFERENCE_NODES,
    TEXT_REFERENCE,
    format_ref,
    kind_for_trigger,
    parse_ref,
    reference_as_text,
    reference_node_kind,
)
from app.core.file_types import FileType
from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.import_engine.context import ImportContext

#: The placeholder an exported reference node carries in place of its id.
SOURCE_REF = "importSourceRef"

#: An exported reference in markdown: the id's place holds the ref instead.
_EXPORTED_TEXT_REFERENCE = re.compile(r"#([\w-]+)\[([^\]]*)\]\(([a-z_]+:\d+)\)")


def _waiting(node_type: str) -> int | None:
    """What a reference node's id field holds while it waits to be placed. A
    wikilink with no file is one the editor already draws as unlinked; the
    others keep a number, as a Confluence mention waiting on its page does."""
    return None if node_type == "wikilink" else 0


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


# -- export ------------------------------------------------------------------


def detach_markdown_references(text: str | None) -> str | None:
    """``text`` with each reference naming the ref it had rather than its id.

    A word after ``#`` that names no kind is not a reference, and is left as
    it was written."""
    if not text:
        return text

    def detach(match: re.Match[str]) -> str:
        kind = kind_for_trigger(match.group(1))
        if kind is None:
            return match.group(0)
        ref = format_ref(kind, int(match.group(3)))
        return f"#{match.group(1)}[{match.group(2)}]({ref})"

    return TEXT_REFERENCE.sub(detach, text)


def detach_editor_references(content: Any) -> Any:
    """``content`` with each reference node naming a ref instead of an id.

    Returns new dicts wherever something changed and never edits ``content``
    itself — it is usually a loaded row's column."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if node.get("query"):
            # An embed of a filter: its project, statuses, people and tags are
            # this community's ids, which mean nothing where it is going.
            return reference_as_text(node)
        field = REFERENCE_NODES.get(node.get("type"))
        if field is not None:
            kind = reference_node_kind(node)
            if kind is not None and _is_id(node.get(field)):
                return {
                    **node,
                    field: _waiting(node["type"]),
                    SOURCE_REF: format_ref(kind, node[field]),
                }
            return node
        children = node.get("children")
        if isinstance(children, list):
            return {**node, "children": [walk(child) for child in children]}
        return node

    return {**content, "root": walk(content["root"])}


def _editor_holders(data: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Where a tool envelope keeps its editor-state bodies."""
    kind = data.get("type")
    if (
        kind == tool_envelope_type(Tool.file)
        and data.get("file_type") == FileType.lexical
    ):
        return [(data, "content")]
    if kind == tool_envelope_type(Tool.post):
        return [(data, "body")]
    if kind == tool_envelope_type(Tool.wiki):
        return [
            *(
                (page, "content")
                for page in data.get("pages") or []
                if isinstance(page, dict)
            ),
            # The files filed in it, carried whole inside it.
            *(
                holder
                for filed in data.get("files") or []
                if isinstance(filed, dict)
                for holder in _editor_holders(filed.get("envelope") or {})
            ),
        ]
    return []


def detach_envelope_references(data: Any, *, guild_id: int) -> None:
    """Rewrite the references in one tool envelope, in place on
    ``data`` (a freshly built envelope dict — the content inside it is never
    edited, only replaced), and say where it was taken.

    A project envelope's references are markdown and are written by
    ``build_project_export`` itself, which is where the text is read.
    """
    from app.core.config import settings

    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        # Not an envelope: a blob riding beside one, say.
        return
    for holder, key in _editor_holders(data):
        holder[key] = detach_editor_references(holder.get(key))
    if data.get("source_instance_url") is None:
        data["source_instance_url"] = settings.APP_URL
    if data.get("source_guild_id") is None:
        data["source_guild_id"] = guild_id


# -- import ------------------------------------------------------------------


def has_source_references(content: Any) -> bool:
    """Whether a body holds a reference still waiting to be placed."""
    if isinstance(content, str):
        return _EXPORTED_TEXT_REFERENCE.search(content) is not None
    found = False

    def walk(node: Any) -> None:
        nonlocal found
        if found or not isinstance(node, dict):
            return
        if isinstance(node.get(SOURCE_REF), str):
            found = True
            return
        for child in node.get("children") or []:
            walk(child)

    walk(content.get("root") if isinstance(content, dict) else None)
    return found


def place_markdown_references(
    text: str | None, resolve: Callable[[str], int | None]
) -> str | None:
    """``text`` with each exported reference pointing at ``resolve(ref)``, or
    reduced to its label when that is nothing."""
    if not text:
        return text

    def place(match: re.Match[str]) -> str:
        target = resolve(match.group(3))
        if target is None:
            return match.group(2)
        return f"#{match.group(1)}[{match.group(2)}]({target})"

    return _EXPORTED_TEXT_REFERENCE.sub(place, text)


def place_editor_references(content: Any, resolve: Callable[[str], int | None]) -> Any:
    """``content`` with each exported reference node placed through
    ``resolve``. One that resolves to nothing is its text again; a wikilink
    stays a wikilink with no file, which is how the editor draws one
    whose file is gone."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        ref = node.get(SOURCE_REF)
        field = REFERENCE_NODES.get(node.get("type"))
        if isinstance(ref, str) and field is not None:
            placed = {k: v for k, v in node.items() if k != SOURCE_REF}
            target = resolve(ref)
            if target is not None:
                placed[field] = target
                return placed
            if node.get("type") == "wikilink":
                placed[field] = None
                return placed
            return reference_as_text(node)
        children = node.get("children")
        if isinstance(children, list):
            return {**node, "children": [walk(child) for child in children]}
        return node

    return {**content, "root": walk(content["root"])}


def note_or_settle(
    context: "ImportContext | None",
    kind: SearchEntityType,
    entity_id: int | None,
    content: Any,
) -> Any:
    """Hand a freshly written body with exported references to the job, which
    places them once every entry has been applied. With no job to come back to
    — an import run outside the engine — the body is settled now, which is
    the answer the job would give for a reference to nothing it carried.

    Returns the content to store."""
    if not has_source_references(content):
        return content
    if context is None or entity_id is None:
        return _settle(content, lambda _ref: None)
    context.links.note_references(kind, entity_id)
    return content


def _settle(content: Any, resolve: Callable[[str], int | None]) -> Any:
    if isinstance(content, str):
        return place_markdown_references(content, resolve)
    return place_editor_references(content, resolve)


def _body_column(kind: SearchEntityType) -> tuple[type, str] | None:
    """The model and column a noted row keeps its body in."""
    from app.models.tenant.comment import Comment
    from app.services.tenant.content_references import BODY_COLUMNS

    if kind == SearchEntityType.comment:
        return Comment, "content"
    return BODY_COLUMNS.get(kind)


async def resolve_references(
    session: AsyncSession, context: "ImportContext", *, author_id: int | None
) -> int:
    """Place the exported references in every body the job noted, now that
    everything the job carries exists, and record the ``references`` edges
    those bodies now make. Returns how many bodies changed.

    Runs on the caller's routed session after the last entry has flushed,
    like :meth:`LinkCollector.resolve`: a row the importer cannot read is not
    rewritten.
    """
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint

    noted = context.links.take_references()
    if not noted:
        return 0

    def resolve(ref: str) -> int | None:
        parsed = parse_ref(ref)
        if parsed is None:
            return None
        kind, source_id = parsed
        endpoint = context.links.lookup(ref)
        if endpoint is not None and endpoint.kind == kind:
            return endpoint.id
        # The export came from this community, so the id still names the
        # thing it named; it just was not part of what was carried.
        return source_id if context.same_community else None

    changed = 0
    # What each rewritten body is about: a comment's edges belong to the thing
    # it is on, which is why a sync reads a body and its comments together.
    owners: dict[int, Endpoint] = {}
    for kind, entity_id in noted:
        column = _body_column(kind)
        if column is None:
            continue
        model, field = column
        row = await session.get(
            model, entity_id, options=[undefer(getattr(model, field))]
        )
        if row is None:
            continue
        before = getattr(row, field)
        after = _settle(before, resolve)
        if after != before:
            setattr(row, field, after)
            session.add(row)
            changed += 1
        # What an edit of just this task kept back names things the same way.
        carry = (
            getattr(row, "recurrence_carry", None)
            if kind == SearchEntityType.task
            else None
        )
        if carry and has_source_references(carry.get("description")):
            setattr(
                row,
                "recurrence_carry",
                {**carry, "description": _settle(carry["description"], resolve)},
            )
            session.add(row)
        owner = (
            content_references.comment_parent(row)
            if kind == SearchEntityType.comment
            else Endpoint(kind, entity_id)
        )
        if owner is not None:
            owners[owner.node] = owner
    await session.flush()

    # An import writes a body without the edges a save derives from it, and
    # these are bodies whose references now name something here.
    for owner in owners.values():
        await content_references.sync_for_entity(
            session,
            owner,
            body=await content_references.own_body(session, owner),
            author_id=author_id,
        )
    return changed
