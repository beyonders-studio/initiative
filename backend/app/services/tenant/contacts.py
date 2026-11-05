"""Contacts — loaders for the address book tool.

A contact is its own item with its own sharing, as a file is, so the loaders
here eager-load its grants and the actions the request may take on it. One
with no initiative belongs to the whole community, held by the community
contacts plug-in (``authorization.COMMUNITY_ROWS``).
"""

from __future__ import annotations

from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.contact import Contact
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service


def list_loader_options() -> list:
    """Eager-load what authorizing and serializing a contact read: its
    sharing, its initiative, and the actions the request may take on it."""
    return [
        selectinload(Contact.grants),
        selectinload(Contact.initiative),
        undefer(Contact.actions),
    ]


async def get_contact(
    session: AsyncSession, contact_id: int, *, populate_existing: bool = False
) -> Contact | None:
    """A contact as authorizing it reads it. RLS scopes the row to the
    request's guild."""
    statement = (
        select(Contact)
        .where(Contact.id == contact_id)
        .options(*list_loader_options())
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(statement)).one_or_none()


async def get_contact_hydrated(
    session: AsyncSession, contact_id: int, *, populate_existing: bool = False
) -> Contact | None:
    """:func:`get_contact` plus the tags and properties a ``ContactRead``
    carries."""
    contact = await get_contact(
        session, contact_id, populate_existing=populate_existing
    )
    if contact is not None:
        await tags_service.annotate_tags(session, [contact])
        await metadata_service.annotate_properties(session, [contact])
    return contact
