"""What saving a description sets in motion.

A task's description and a catalog item's are written in the same composer as
a comment, so they carry the same mention syntax: ``@[Name](id)`` for a
person, ``#kind[Title](id)`` for a thing. Saving one does two things with
those:

* the ``#`` references become the thing's ``references`` edges, recomputed
  from the description and its comments together
  (:mod:`app.services.tenant.content_references`);
* each person the description names *for the first time* hears about it. A
  mention that was already there when the description was last saved is not
  news, so editing a sentence around it does not notify again.

Only people who can open the thing are told — a notice names it to whoever
gets it.
"""

from __future__ import annotations

from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.catalog import CatalogItem
from app.models.tenant.task import Task
from app.services import notifications as notifications_service
from app.services.tenant import content_references
from app.services.tenant.mention_parser import extract_mentioned_user_ids
from app.services.tenant.relationships import Endpoint

#: What carries a description, and the kind it is named by.
Described = Task | CatalogItem
_KINDS: dict[type, SearchEntityType] = {
    Task: SearchEntityType.task,
    CatalogItem: SearchEntityType.catalog_item,
}


def newly_mentioned(description: str | None, previous: str | None) -> set[int]:
    """The people ``description`` names that ``previous`` did not."""
    return extract_mentioned_user_ids(description or "") - extract_mentioned_user_ids(
        previous or ""
    )


def _endpoint(row: Described) -> Endpoint:
    return Endpoint(_KINDS[type(row)], cast(int, row.id))


async def record_references(
    session: AsyncSession, row: Described, *, author_id: int | None
) -> None:
    """Make the thing's ``references`` edges match its description and comments.

    On its own for a copy of text somebody already wrote — a duplicated task
    points at what its original did, and names nobody anew.
    """
    await content_references.sync_for_entity(
        session, _endpoint(row), body=row.description, author_id=author_id
    )


async def description_saved(
    session: AsyncSession,
    row: Described,
    *,
    previous: str | None,
    author: User | None,
) -> None:
    """Record what the description now points at, and tell whoever it newly
    names.

    ``previous`` is the description as it stood before this save — ``None`` for
    a thing that is new. ``author`` is ``None`` for an installed plug-in, whose
    save records references and tells nobody: a mention names a person by
    their row id, which a plug-in does not hold. Rides the caller's transaction;
    the caller commits.
    """
    await record_references(
        session, row, author_id=author.id if author is not None else None
    )
    if author is None:
        return

    endpoint = _endpoint(row)
    name = await notifications_service.actor_name(session, author)
    await notifications_service.notify(
        session,
        NotificationType.mention,
        sorted(newly_mentioned(row.description, previous)),
        about=(endpoint.kind.value, endpoint.id),
        key="mention.description",
        values={"actor": name, "title": getattr(row, row.display_field()) or ""},
        # The title is community content: the bell reads it back by kind and
        # id.
        data={
            "entity_type": endpoint.kind.value,
            "entity_id": endpoint.id,
            "mentioned_by_name": name,
            "mentioned_by_id": author.id,
        },
        actor=author,
    )
