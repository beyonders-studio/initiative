"""What a body says it is about.

A ``#`` link or a ``[[ ]]`` link in something somebody wrote is an assertion
that the thing being written about and the thing being named belong together,
and an ``@`` mention in it says the same of a person. This module keeps that
assertion in ``relationships`` as a ``references`` edge, recomputed from the
content every time the content is saved.

Three rules shape everything here:

**Recompute, never patch.** The edges a thing has are a function of what its
body and its comments say right now, so every sync reads all of them and makes
the table match. Nothing tracks what changed between two saves.

**A comment's ``#`` belongs to what the comment is about.** A comment is not
something a reference can name, and the conversation about a task is part of
that task — so a mention in a comment on task 5 is recorded as *task 5
references it*. That is why the recompute reads the body and every comment
together: dropping one comment must not drop an edge another still supports.
A comment's ``@`` is a remark to somebody rather than the thing's own words
about them, so only the body's mentions of people are kept.

**A withdrawn edge is deleted, not remembered.** A person unlinking two things
means something; a sentence being rewritten does not. ``relationships.remove``
already reads provenance to decide that, so it is stated once, there.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.references import references_in_body, references_in_text
from app.core.relationships import PERSON, Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.core.tool_set import ToolSet
from app.db import reference_targets
from app.db.session import session_tools
from app.db.tool_rows import locate, text_columns
from app.models.tenant.comment import Comment, said_on
from app.models.tenant.file import File
from app.models.tenant.post import Post
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task
from app.models.tenant.wiki import WikiPage
from app.services.import_engine.mentions import (
    editor_mention_ids,
    markdown_mention_ids,
)
from app.services.tenant import named_people
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


async def sync_for_entity(
    session: AsyncSession,
    entity: Endpoint,
    *,
    body: Any = None,
    author_id: int | None = None,
) -> None:
    """Make this thing's ``references`` edges match what is written about it.

    ``body`` is the entity's own content as it now stands — the caller passes it
    because the caller is mid-save and holds the new version, which is not yet
    what a query would return.
    """
    wanted = references_in(body)
    for text in await _comment_bodies(session, entity):
        wanted |= references_in_text(text)
    # Nothing in this vocabulary means anything from a thing to itself, and a
    # body naming its own page is ordinary rather than an error.
    wanted.discard((entity.kind, entity.id))

    tools = await session_tools(session)
    live = await _by_kind(session, wanted, reference_targets.live_ids, tools)
    if relationships_service.records_edges(session):
        people = (
            markdown_mention_ids(body)
            if isinstance(body, str)
            else editor_mention_ids(body)
        )
        live |= {(PERSON.value, user_id) for user_id in people}
        await _reconcile(session, entity, live, tools, author_id=author_id)


def references_in(body: Any) -> set[tuple[str, int]]:
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
    comment's own edges, because a comment has none. The thing it is about is
    named in the community's tool set: the request's, or, where the system
    routed this session itself, the one its installs make.
    """
    parent = comment_parent(comment, await session_tools(session))
    await sync_for_entity(
        session,
        parent,
        body=await own_body(session, parent),
        author_id=author_id,
    )


async def referencing_files(session: AsyncSession, file_id: int) -> list[File]:
    """Files whose content points at this one, trashed ones included.

    The purge path asks this: a reference in a file that is only in the
    trash still has to be unlinked, or restoring it later brings a dangling
    link back with it.
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


def comment_parent(comment: Comment, tools: ToolSet) -> Endpoint:
    """The thing a comment is about, as an edge would name it, in the
    community with ``tools``."""
    return Endpoint.of(tools, comment.subject_type, comment.subject_id)


def texts_body(texts: Iterable[Any]) -> str | None:
    """A tool plug-in's row's body: its declared text fields, as one text."""
    return "\n\n".join(text for text in texts if text) or None


async def own_body(session: AsyncSession, entity: Endpoint) -> Any:
    """A thing's stored body, or None if its kind has none (:func:`texts_body`
    for a tool plug-in's row)."""
    source = BODY_COLUMNS.get(entity.kind)
    if source is None:
        located = locate(await session_tools(session), entity.kind)
        texts = text_columns(located.table) if located is not None else []
        if not texts:
            return None
        row = (
            await session.exec(
                sa.select(*texts).where(located.table.c.id == entity.id)  # type: ignore[union-attr]
            )
        ).first()
        return texts_body(row or ())
    model, column = source
    return (
        await session.exec(
            select(getattr(model, column)).where(model.id == entity.id)  # type: ignore[attr-defined]
        )
    ).first()


async def _comment_bodies(session: AsyncSession, entity: Endpoint) -> Sequence[str]:
    """Every live comment written about this thing."""
    rows = await session.exec(
        select(Comment.content).where(said_on(entity.kind, entity.id))
    )
    return list(rows.all())


async def _by_kind(
    session: AsyncSession,
    wanted: set[tuple[str, int]],
    ask: Callable[..., Awaitable[set[int]]],
    tools: ToolSet,
) -> set[tuple[str, int]]:
    """Run one id question per kind in the community with ``tools``, and put
    the pairs back together.

    Asked through the saving session, so a reference resolves to exactly what
    the person writing the content can point at: what still exists and this
    session may read (``live_ids``), or, of the edges about to be MADE, what is
    still taking writes (``unfrozen_ids``). An archived or trashed thing takes
    no new links, so a mention of one records nothing until it comes back; an
    edge already there stands on the mention that made it, which is still
    there."""
    by_kind: dict[str, list[int]] = {}
    for kind, entity_id in wanted:
        by_kind.setdefault(kind, []).append(entity_id)

    found: set[tuple[str, int]] = set()
    for kind, ids in by_kind.items():
        for entity_id in await ask(session, kind, ids, tools=tools):
            found.add((kind, entity_id))
    return found


async def _reconcile(
    session: AsyncSession,
    entity: Endpoint,
    wanted: set[tuple[str, int]],
    tools: ToolSet,
    *,
    author_id: int | None,
) -> None:
    """Add what the content now names, drop what it no longer does.

    Only the additions ask whether the far end is still taking writes, or, for a
    person, whether they are in the community, as a link to one asks. What
    removes an edge here is the sentence going, and a far end being archived,
    or a person leaving, afterwards is not that.
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

    have = {(row.target_type, row.target_id): row for row in existing}

    for key, row in have.items():
        if key not in wanted:
            await relationships_service.remove(
                session, row, removed_by=author_id, tombstone=False
            )

    adding = wanted - set(have)
    people = {pair for pair in adding if pair[0] == PERSON.value}
    members = await named_people.members(session, (pair[1] for pair in people))
    await relationships_service.create_many(
        session,
        source=entity,
        relationship_type=RelationshipType.references,
        targets=[
            Endpoint.of(tools, kind, entity_id)
            for kind, entity_id in sorted(
                await _by_kind(
                    session, adding - people, reference_targets.unfrozen_ids, tools
                )
                | {pair for pair in people if pair[1] in members},
                key=lambda pair: (pair[0], pair[1]),
            )
        ],
        provenance=Provenance.content,
        created_by=author_id,
    )
