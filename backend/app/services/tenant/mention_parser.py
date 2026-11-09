"""Mention syntax: parsing and anonymization.

Mention patterns in markdown — comments, task descriptions, any description:
- Users: @[](id) - e.g., @[](42), stored by id alone
  (``app.core.identity_boundary.without_mention_names``)
- Anything else: #kind[Title](id) - e.g., #task[Fix bug](123). That half is the
  reference vocabulary, read by ``app.core.references``.

An editor-state body (a file, a post, a wiki page) embeds a mention as a
Lexical ``mention`` node carrying ``mentionUserId``, with ``mentionName`` and
``text`` empty, in its content and its collaboration state alike.

Neither therefore holds a name for ``anonymize_user_mentions`` to take out.
"""

from sqlmodel import col, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import STORED_MENTION
from app.core.references import references_in_text
from app.core.search import SearchEntityType
from app.models.tenant.batched_notice import BatchedNotice

# Placeholder written over an anonymized user's name in a digest row.
# Matches the frontend's rendering of anonymized users
# (``getUserDisplayName`` → "Deleted user").
ANONYMIZED_MENTION_NAME = "Deleted user"


def extract_mentioned_user_ids(content: str) -> set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(user_id) for _, user_id in STORED_MENTION.findall(content)}


def extract_mentioned_task_ids(content: str) -> set[int]:
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


async def anonymize_user_mentions(session: AsyncSession, *, user_id: int) -> None:
    """Take ``user_id``'s name out of the CURRENTLY ROUTED guild schema.

    Content and collaboration state hold none to take out: a mention is
    stored by id alone. Pending digest rows lose the ``actor_name`` snapshot
    of the assigner or reactor.

    Caller owns routing (guild-admin context), flushing order, and the commit —
    everything here rides the caller's transaction.
    """
    await session.exec(
        update(BatchedNotice)
        .where(col(BatchedNotice.actor_id) == user_id)
        .values(actor_name=ANONYMIZED_MENTION_NAME)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
