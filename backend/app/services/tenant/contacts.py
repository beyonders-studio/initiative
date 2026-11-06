"""Contacts — loaders for the address book tool, and who may put one in the
community's contacts.

A contact is its own item with its own sharing, as a file is, so the loaders
here eager-load its grants and the actions the request may take on it. One
with no initiative belongs to the whole community, held by the community
contacts plug-in (``authorization.COMMUNITY_ROWS``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ContactMessages, GuildMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.guild_standing import ActorContext
from app.models.platform.guild import AdminSurface
from app.models.platform.user import User
from app.models.tenant.contact import Contact
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import guild_plugins as guild_plugins_service
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


async def organizations_of(
    session: AsyncSession, person_ids: Iterable[int]
) -> dict[int, tuple[int, str, int | None]]:
    """The organization each person is ``part_of``, as ``(id, name, initiative_id)``, for a
    page of people at once. Read as the reader may see both the link and the
    organization; a person with several takes the one linked first."""
    ids = sorted(set(person_ids))
    if not ids:
        return {}
    kind = SearchEntityType.contact.value
    rows = await session.exec(
        select(
            EntityRelationship.source_id,
            Contact.id,
            Contact.name,
            Contact.initiative_id,
        )
        .join(Contact, col(Contact.id) == EntityRelationship.target_id)
        .where(
            EntityRelationship.source_type == kind,
            col(EntityRelationship.source_id).in_(ids),
            EntityRelationship.target_type == kind,
            EntityRelationship.relationship_type == RelationshipType.part_of.value,
            col(EntityRelationship.removed_at).is_(None),
            col(Contact.is_organization).is_(True),
        )
        .order_by(col(EntityRelationship.created_at), col(EntityRelationship.id))
    )
    found: dict[int, tuple[int, str, int | None]] = {}
    for person_id, org_id, name, initiative_id in rows.all():
        found.setdefault(person_id, (org_id, name, initiative_id))
    return found


async def community_holder(
    session: AsyncSession, user: Optional[User], guild_context: ActorContext
) -> GuildPlugin:
    """The install a community contact goes into, once the request may put one
    there: a person holding the ``community_contacts`` surface, in a community
    that has the plug-in."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ContactMessages.PLUGIN_INITIATIVE_REQUIRED,
        )
    if not guild_context.holds_surface(AdminSurface.community_contacts):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ADMIN_REQUIRED,
        )
    plugin = await guild_plugins_service.find_mounting_plugin(
        session, tool=Tool.contact.value
    )
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ContactMessages.PLUGIN_REQUIRED,
        )
    return plugin
