"""Contact endpoints — the address book tool.

Each contact is its own item with its own sharing, as a file is: creation is
gated at the initiative level (contacts_enabled + create_contacts), and
everything after that flows from the contact's resource grants
(``resource_grants`` + ``PUT /{id}/grants``).

A contact with no initiative is one of the **community's contacts**. It lives
inside the community contacts plug-in, whose install owns it, and is made by
holders of the ``community_contacts`` surface. Members read it through the
share with everyone; a guest reads one only where it is shared with them by
name. Holders of the surface edit it, and so does anyone given write on it.
An initiative's content may link to one.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
    plugin_scope,
)
from app.core.messages import ContactMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.models.tenant.contact import DETAILS, Contact
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.tenant.contact import ContactCreate, ContactRead, ContactUpdate
from app.schemas.tenant.resource_grant import initiative_readable
from app.schemas.tenant.tool import serialize_tool
from app.services.tenant import attachments as attachments_service
from app.services.tenant import contacts as contacts_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import tags as tags_service

router = APIRouter(route_class=ActorRoute)

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
#: The routes an installed plug-in may call, under the contacts scopes.
ContactsRead = Annotated[ActorContext, Depends(plugin_scope("contacts:read"))]
ContactsWrite = Annotated[ActorContext, Depends(plugin_scope("contacts:write"))]


@router.get("/{contact_id}", response_model=ContactRead)
async def read_contact(
    contact_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ContactsRead,
) -> ContactRead:
    contact = await resource_access.load_authorized(
        session, Tool.contact, contact_id, current_user, guild_context, hydrated=True
    )
    return serialize_tool(
        ContactRead, contact, user_id=guild_context.user_id, context=guild_context
    )


@router.post("/", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(
    contact_in: ContactCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ContactsWrite,
) -> ContactRead:
    """Create a contact.

    In an initiative it needs that initiative's contacts switch on and the
    ``create_contacts`` permission (or guild admin), and its maker owns it.
    With ``initiative_id`` omitted it is one of the community's contacts: it
    needs the ``community_contacts`` surface and the community contacts
    plug-in, whose install owns it. An installed plug-in creates initiative
    contacts only, owned by its install.
    """
    resource_access.refuse_plugin_sharing(guild_context, contact_in, "grants")
    initiative_id = contact_in.initiative_id
    plugin: Optional[GuildPlugin] = None
    if initiative_id is None:
        plugin = await contacts_service.community_holder(
            session, current_user, guild_context
        )
    else:
        await resource_access.prepare_create(
            session, Tool.contact, initiative_id, current_user, guild_context
        )

    contact = Contact(
        initiative_id=initiative_id,
        created_by=guild_context.user_id,
        **contact_in.model_dump(include={"name", "is_organization", *DETAILS}),
    )
    session.add(contact)
    await session.flush()

    if plugin is None:
        await resource_access.grant_initial_sharing(
            session,
            guild_context,
            Tool.contact,
            user=current_user,
            resource_id=contact.id,
            initiative_id=initiative_id,
            payload=contact_in,
            grants=contact_in.grants,
        )
    else:
        await ownership_service.give_to_install(
            session,
            Tool.contact,
            contact,
            install_id=plugin.id,
            guild_id=guild_context.guild_id,
            grants=contact_in.grants,
            actor_user_id=guild_context.user_id,
        )
    if contact_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.contact],
            guild_id=guild_context.guild_id,
            entity_id=contact.id,
            tag_ids=contact_in.tag_ids,
        )
    await metadata_service.write_on_create(session, contact, contact_in.properties)
    await session.commit()
    return await read_after_write(session, contact.id, current_user, guild_context)


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: int,
    contact_in: ContactUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ContactsWrite,
) -> ContactRead:
    """Change a contact. A list sent replaces the one there."""
    contact = await resource_access.load_authorized(
        session,
        Tool.contact,
        contact_id,
        current_user,
        guild_context,
        access="write",
    )
    data = contact_in.model_dump(exclude_unset=True)
    if data:
        for field, value in data.items():
            setattr(contact, field, value)
        contact.updated_at = datetime.now(timezone.utc)
        session.add(contact)
        await session.commit()
    return await read_after_write(session, contact_id, current_user, guild_context)


@router.post("/{contact_id}/move", response_model=ContactRead)
async def move_contact(
    contact_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> ContactRead:
    """Move an initiative's contact into the community's contacts.

    It needs write on the contact, the ``community_contacts`` surface and the
    community contacts plug-in, and is refused when its initiative keeps its
    content in. It is then the community's as a new one is: owned by the
    plug-in's install and shared with every member. Its initiative's property
    values are dropped, since their definitions are the initiative's, and the
    files its comments show are kept for the community. Its links stay,
    now running from the initiative's side to the community's.
    """
    contact = await resource_access.load_authorized(
        session,
        Tool.contact,
        contact_id,
        current_user,
        guild_context,
        access="write",
    )
    if contact.initiative_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ContactMessages.ALREADY_IN_COMMUNITY,
        )
    plugin = await contacts_service.community_holder(
        session, current_user, guild_context
    )
    await resource_access.require_stays_in(session, contact.initiative_id, None)

    await metadata_service.drop_values(
        session, Tool.contact.value, [contact.id], moved=True
    )
    contact.initiative = None
    contact.initiative_id = None
    contact.updated_at = datetime.now(timezone.utc)
    session.add(contact)
    await session.flush()
    await ownership_service.give_to_install(
        session,
        Tool.contact,
        contact,
        install_id=plugin.id,
        guild_id=guild_context.guild_id,
        grants=initiative_readable(),
        actor_user_id=current_user.id,
    )
    comments = await session.exec(
        select(Comment).where(Comment.contact_id == contact.id)
    )
    await attachments_service.claim_uploads(session, *comments.all(), carried=True)
    await session.commit()
    return await read_after_write(session, contact_id, current_user, guild_context)


async def read_after_write(
    session: RLSSessionDep,
    contact_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> ContactRead:
    """The contact a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    contact = await contacts_service.get_contact_hydrated(
        session, contact_id, populate_existing=True
    )
    if contact is None:
        raise Tool.contact.not_found()
    return serialize_tool(
        ContactRead, contact, user_id=guild_context.user_id, context=guild_context
    )
