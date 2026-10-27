"""What a body says it is about.

A ``#`` link or a ``[[ ]]`` link in something somebody wrote is an assertion
that the thing being written about and the thing being named belong together.
This module keeps that assertion in ``relationships`` as a ``references`` edge,
recomputed from the content every time the content is saved.

Three rules shape everything here:

**Recompute, never patch.** The edges a thing has are a function of what its
body and its comments say right now, so every sync reads all of them and makes
the table match. Nothing tracks what changed between two saves.

**A comment's ``#`` belongs to what the comment is about.** A comment is not
something a reference can name, and the conversation about a task is part of
that task — so a mention in a comment on task 5 is recorded as *task 5
references it*. That is why the recompute reads the body and every comment
together: dropping one comment must not drop an edge another still supports.

**A withdrawn edge is deleted, not remembered.** A person unlinking two things
means something; a sentence being rewritten does not. ``relationships.remove``
already reads provenance to decide that, so it is stated once, there.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Awaitable, Callable, Sequence

from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.references import (
    references_in_body,
    references_in_text,
    unresolve_missing_wikilinks,
)
from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.db import reference_targets
from app.db.initiative_rls import COMMENT_PARENT_COLUMNS
from app.models.tenant.comment import Comment
from app.models.tenant.file import File
from app.models.tenant.post import Post
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task
from app.models.tenant.wiki import WikiPage
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint

#: Kinds that carry a body of their own, and the column holding it. A body is
#: a Lexical editor state or markdown text — a task's description is written in
#: the same composer as a comment, with the same ``#`` syntax — and
#: :func:`references_in` reads either. A kind absent from this map contributes
#: nothing but its comments.
BODY_COLUMNS: dict[SearchEntityType, tuple[type, str]] = {
    SearchEntityType.file: (File, "content"),
    SearchEntityType.post: (Post, "body"),
    SearchEntityType.task: (Task, "description"),
    SearchEntityType.wiki_page: (WikiPage, "content"),
}

#: Kind -> the comment column naming a parent of that kind. Derived from the
#: registry the comment policies are rendered from, so a new commentable tool is
#: declared once and picked up here without an edit.
_COMMENT_COLUMNS: dict[SearchEntityType, str] = {
    SearchEntityType(column.removesuffix("_id")): column
    for column in COMMENT_PARENT_COLUMNS
}


async def sync_for_entity(
    session: AsyncSession,
    entity: Endpoint,
    *,
    body: Any = None,
    author_id: int | None = None,
    fix_content: bool = False,
) -> dict[str, Any] | None:
    """Make this thing's ``references`` edges match what is written about it.

    ``body`` is the entity's own content as it now stands — the caller passes it
    because the caller is mid-save and holds the new version, which is not yet
    what a query would return.

    ``fix_content`` additionally blanks any ``[[ ]]`` whose target is gone and
    returns the repaired body, which is the one thing a save wants done to the
    content itself. It returns None when nothing needed repairing, so a caller
    can write back ``fixed or original``.
    """
    wanted = references_in(body)
    for text in await _comment_bodies(session, entity):
        wanted |= references_in_text(text)
    # Nothing in this vocabulary means anything from a thing to itself, and a
    # body naming its own page is ordinary rather than an error.
    wanted.discard((entity.kind, entity.id))

    live = await _live_targets(session, wanted)
    if relationships_service.records_edges(session):
        await _reconcile(session, entity, live, author_id=author_id)

    if not fix_content or not isinstance(body, dict):
        return None
    live_files = {
        entity_id for kind, entity_id in live if kind is SearchEntityType.file
    }
    repaired = deepcopy(body)
    if not unresolve_missing_wikilinks(repaired, live_files):
        return None
    return repaired


def references_in(body: Any) -> set[tuple[SearchEntityType, int]]:
    """Every thing a body points at, whichever of the two shapes it is in."""
    if isinstance(body, str):
        return references_in_text(body)
    return references_in_body(body)


async def sync_for_comment(
    session: AsyncSession, comment: Comment, *, author_id: int | None = None
) -> None:
    """Recompute the edges of whatever a comment is about.

    Called when a comment is written, edited, trashed or restored — all four
    change what the conversation says, and none of them is a change to the
    comment's own edges, because a comment has none.
    """
    parent = comment_parent(comment)
    if parent is None:
        return
    await sync_for_entity(
        session,
        parent,
        body=await own_body(session, parent),
        author_id=author_id,
    )


async def referencing_files(session: AsyncSession, file_id: int) -> list[File]:
    """Files whose content points at this one, trashed ones included.

    The purge path asks this: a ``[[ ]]`` in a file that is only in the
    trash still has to be blanked, or restoring it later brings a dangling link
    back with it.
    """
    from app.db.soft_delete_filter import select_including_deleted

    target = Endpoint(SearchEntityType.file, file_id)
    sources = select(EntityRelationship.source_id).where(
        EntityRelationship.target_node == target.node,
        EntityRelationship.source_type == SearchEntityType.file.value,
        EntityRelationship.relationship_type == RelationshipType.references.value,
        EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
    )
    rows = await session.exec(
        select_including_deleted(File)
        .where(File.id.in_(sources))  # type: ignore[attr-defined]
        .options(undefer(File.content))
    )
    return list(rows.all())


def comment_parent(comment: Comment) -> Endpoint | None:
    """The thing a comment is about, as an edge would name it."""
    for kind, column in _COMMENT_COLUMNS.items():
        entity_id = getattr(comment, column, None)
        if entity_id is not None:
            return Endpoint(kind, entity_id)
    return None


async def own_body(session: AsyncSession, entity: Endpoint) -> Any:
    """A thing's stored body, or None if its kind has none."""
    source = BODY_COLUMNS.get(entity.kind)
    if source is None:
        return None
    model, column = source
    return (
        await session.exec(
            select(getattr(model, column)).where(model.id == entity.id)  # type: ignore[attr-defined]
        )
    ).first()


async def _comment_bodies(session: AsyncSession, entity: Endpoint) -> Sequence[str]:
    """Every live comment written about this thing."""
    column = _COMMENT_COLUMNS.get(entity.kind)
    if column is None:
        return ()
    rows = await session.exec(
        select(Comment.content).where(getattr(Comment, column) == entity.id)
    )
    return list(rows.all())


async def _live_targets(
    session: AsyncSession, wanted: set[tuple[SearchEntityType, int]]
) -> set[tuple[SearchEntityType, int]]:
    """The subset that still exists and this session may read.

    Asked through the saving session, so a reference resolves to exactly what
    the person writing the content can point at.
    """
    return await _by_kind(session, wanted, reference_targets.live_ids)


async def _accepting_links(
    session: AsyncSession, wanted: set[tuple[SearchEntityType, int]]
) -> set[tuple[SearchEntityType, int]]:
    """The subset that is still taking writes.

    Asked only of the edges about to be MADE. An archived or trashed thing takes
    no new links, so a mention of one records nothing until it comes back; an
    edge already there stands on the mention that made it, which is still there.
    """
    return await _by_kind(session, wanted, reference_targets.unfrozen_ids)


async def _by_kind(
    session: AsyncSession,
    wanted: set[tuple[SearchEntityType, int]],
    ask: Callable[[AsyncSession, SearchEntityType, list[int]], Awaitable[set[int]]],
) -> set[tuple[SearchEntityType, int]]:
    """Run one id question per kind, and put the pairs back together."""
    by_kind: dict[SearchEntityType, list[int]] = {}
    for kind, entity_id in wanted:
        by_kind.setdefault(kind, []).append(entity_id)

    found: set[tuple[SearchEntityType, int]] = set()
    for kind, ids in by_kind.items():
        for entity_id in await ask(session, kind, ids):
            found.add((kind, entity_id))
    return found


async def _reconcile(
    session: AsyncSession,
    entity: Endpoint,
    wanted: set[tuple[SearchEntityType, int]],
    *,
    author_id: int | None,
) -> None:
    """Add what the content now names, drop what it no longer does.

    Only the additions ask whether the far end is still taking writes. What
    removes an edge here is the sentence going, and a far end being archived
    afterwards is not that.
    """
    existing = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node == entity.node,
                EntityRelationship.relationship_type
                == RelationshipType.references.value,
                EntityRelationship.provenance == Provenance.content.value,
                EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()

    have = {(SearchEntityType(row.target_type), row.target_id): row for row in existing}

    for key, row in have.items():
        if key not in wanted:
            await relationships_service.remove(
                session, row, removed_by=author_id, tombstone=False
            )

    await relationships_service.create_many(
        session,
        source=entity,
        relationship_type=RelationshipType.references,
        targets=[
            Endpoint(kind, entity_id)
            for kind, entity_id in sorted(
                await _accepting_links(session, wanted - set(have)),
                key=lambda pair: (pair[0].value, pair[1]),
            )
        ],
        provenance=Provenance.content,
        created_by=author_id,
    )
