"""Mention syntax: parsing and anonymization.

Mention patterns in markdown — comments, task descriptions, any description:
- Users: @[](id) - e.g., @[](42), stored by id alone
  (``app.core.identity_boundary.without_mention_names``)
- Anything else: #kind[Title](id) - e.g., #task[Fix bug](123). That half is the
  reference vocabulary, read by ``app.core.references``.

An editor-state body (a file, a post, a wiki page) embeds a mention as a
Lexical ``mention`` node carrying ``mentionUserId``, with ``mentionName`` and
``text`` empty.

Content therefore holds no name for ``anonymize_user_mentions`` to take out;
it takes out what a collaboration state may still hold.
"""

from typing import Optional, Set

from pycrdt import Doc, Text, XmlElement, XmlText
from pycrdt._base import base_types
from sqlalchemy import Text as SqlText, cast
from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import STORED_MENTION
from app.core.references import references_in_text
from app.core.search import SearchEntityType
from app.db import gucs
from app.db.session import raise_flag
from app.models.tenant.batched_notice import BatchedNotice
from app.db.session import routed_guild_id

# Placeholder written over an anonymized user's name in a digest row.
# Matches the frontend's rendering of anonymized users
# (``getUserDisplayName`` → "Deleted user").
ANONYMIZED_MENTION_NAME = "Deleted user"


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(user_id) for _, user_id in STORED_MENTION.findall(content)}


def extract_mentioned_task_ids(content: str) -> Set[int]:
    """Extract all task IDs mentioned in the content.

    Read through the reference vocabulary rather than a pattern of its own: a
    ``#`` in a comment is the same syntax wherever it is read, and it is also
    what the content-reference sync records.
    """
    return {
        entity_id
        for kind, entity_id in references_in_text(content)
        if kind is SearchEntityType.task
    }


def nameless_state(state: bytes) -> Optional[bytes]:
    """A collaboration state with no mention of somebody by id holding a name,
    or ``None`` where none held one.

    The editor's binding keeps a document under the root ``root``: an element
    as an ``XmlText`` embedded in its parent, and a decorator, a mention among
    them, as an ``XmlElement`` whose attributes are its properties, the name in
    ``__mention`` and the id in ``__mentionUserId``. The name is cleared as an
    edit on top of the state, so nothing else written into it changes. A state
    that cannot be read is left as it is: collaboration never loads one, and
    starts from the content instead.
    """
    doc = Doc()
    changed = False

    def walk(text: Text) -> None:
        nonlocal changed
        for value, _ in text.diff():
            # An embedded type comes back unwrapped; pycrdt keeps the wrappers
            # by the type it returns.
            kind = base_types.get(type(value))
            node = kind(_doc=doc, _integrated=value) if kind else None
            if isinstance(node, XmlText):
                walk(node)
            elif (
                isinstance(node, XmlElement)
                and node.attributes.get("__type") == "mention"
                and node.attributes.get("__mentionUserId") is not None
                and node.attributes.get("__mention")
            ):
                node.attributes["__mention"] = ""
                changed = True

    try:
        doc.apply_update(state)
        walk(doc.get("root", type=Text))
    except Exception:
        return None
    return bytes(doc.get_update()) if changed else None


async def anonymize_user_mentions(session: AsyncSession, *, user_id: int) -> None:
    """Take ``user_id``'s name out of the CURRENTLY ROUTED guild schema.

    Content holds none to take out: a mention is stored by id alone. A
    collaboration state can, as an editor from before names were left out
    writes one into it, so every file or wiki page that mentions the user
    has its state's mentions made nameless (:func:`nameless_state`). Pending
    task-assignment digest rows lose the ``assigned_by_name`` snapshot too.

    Caller owns routing (guild-admin context), flushing order, and the commit —
    everything here rides the caller's transaction. Soft-deleted and archived
    rows are included: something restored later must not resurrect the name.
    """
    from app.services.tenant.collaboration import collaboration_manager
    from app.services.tenant.collaborative_resources import (
        YJS_STATE_COLUMN,
        registered_types,
        resource_for,
    )

    mentioned = rf'"mentionUserId":\s*{user_id}[^0-9]'

    # Finished work is included: an archived file keeps its state. Writing
    # to frozen content is the purge's kind of write, so this runs under the
    # purge flag and lowers it again before the rest of the erasure (see
    # ``app.db.gucs.PURGING``).
    await raise_flag(session, gucs.PURGING)
    rooms: list[tuple[str, int]] = []
    for kind in registered_types():
        resource = resource_for(kind)
        model = resource.model
        state = getattr(model, YJS_STATE_COLUMN)
        held = await session.exec(
            select(model.id, state)
            .where(
                state.is_not(None),
                cast(getattr(model, resource.content_column), SqlText).op("~")(
                    mentioned
                ),
            )
            .execution_options(include_deleted=True, include_archived=True)
        )
        for row_id, current in held.all():
            nameless = nameless_state(current)
            if nameless is None:
                continue
            await session.exec(
                update(model)
                .where(model.id == row_id)
                .values({YJS_STATE_COLUMN: nameless})
                .execution_options(synchronize_session=False)
            )
            rooms.append((kind, row_id))

    # Batched lines snapshot the assigner's or reactor's name for the email.
    await session.exec(
        update(BatchedNotice)
        .where(col(BatchedNotice.actor_id) == user_id)
        .values(actor_name=ANONYMIZED_MENTION_NAME)
        .execution_options(synchronize_session=False)
    )

    await session.flush()
    await raise_flag(session, gucs.PURGING, False)

    # Drop idle collaboration rooms so a room's save can't write a stale
    # in-memory state back on next disconnect. Rooms are keyed by (guild,
    # kind, id) and this runs once per guild, routed to it.
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        for kind, row_id in rooms:
            await collaboration_manager.invalidate_room_if_empty(guild_id, kind, row_id)
