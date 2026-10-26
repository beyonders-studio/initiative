"""Wiki endpoints — a body of linked pages in an initiative.

Creation is gated at the initiative level (wikis_enabled + create_wikis);
everything after that flows from the wiki's resource-grant DAC
(``resource_grants`` + ``PUT /{id}/grants``), like every other tool.

Three things here are the wiki's own rather than the generic tool shape:

* **Pages are content, not tools.** A page is added under its wiki —
  ``/wikis/{id}/pages`` — and addressed after that by its own id at
  ``/wiki-pages/{id}``. Adding, editing or moving one asks for **write** access
  on the wiki, the way editing a task asks for write on its project.
* **The tree comes back whole.** ``GET /{id}/pages`` returns every page of a
  wiki, flat and in reading order, because the navigation draws all of it at
  once. The rows carry no bodies, so the payload grows with the number of
  pages rather than with what has been written on them.
* **A page knows what points at it.** Saving a body records the ``[[ ]]``
  links it makes in ``relationships``, beside the connections people drew by
  hand, so ``GET /relationships/?entity=wiki_page:{id}`` reads a page's links
  both ways — which is what makes a wiki a web rather than a folder.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access, tool_copy
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    RLSSessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.messages import CommonMessages, WikiMessages
from app.core.body_limit import max_document_body
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import KINDS, Tool
from app.models.platform.user import User
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.ai_generation import AIStreamEvent
from app.schemas.tenant.wiki import (
    WikiCreate,
    WikiPageCreate,
    WikiPageMove,
    WikiPageRead,
    WikiPageTree,
    WikiPageUpdate,
    WikiRead,
    WikiUpdate,
    serialize_wiki_page,
    serialize_file_as_page,
    serialize_wiki_page_summary,
)
from app.schemas.tenant.tool import serialize_tool
from app.services import ai_generation
from app.services.tenant import attachments as attachments_service
from app.services.tenant import body_states
from app.services.tenant.collaboration import (
    collaboration_manager,
    content_version,
    current_content,
    versioned,
    written_into,
)
from app.services.tenant import content_references
from app.services.tenant import relationships as relationships_service
from app.services.tenant import soft_delete as soft_delete_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import wikis as wikis_service

router = APIRouter(route_class=ActorRoute)
#: A page addressed by its own id, mounted at the guild root the way a queue
#: item is. Only adding one names its wiki.
pages_router = APIRouter(route_class=ActorRoute)

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
#: The routes an installed plug-in may call, under the wikis scopes.
WikisRead = Annotated[ActorContext, Depends(plugin_scope("wikis:read"))]
WikisWrite = Annotated[ActorContext, Depends(plugin_scope("wikis:write"))]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _serialized_page(
    session: AsyncSession, page: WikiPage, guild_context: ActorContext
) -> WikiPageRead:
    """A page as every page route answers with it: its tags and properties,
    and the body it reads as now with that body's version."""
    await tags_service.annotate_tags(session, [page])
    await properties_service.annotate_properties(session, [page])
    return await versioned(
        serialize_wiki_page(page, context=guild_context),
        guild_context.guild_id,
        SearchEntityType.wiki_page.value,
    )


# ---------------------------------------------------------------------------
# Wikis
# ---------------------------------------------------------------------------


@router.get("/{wiki_id}", response_model=WikiRead)
async def read_wiki(
    wiki_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisRead,
) -> WikiRead:
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, hydrated=True
    )
    return serialize_tool(
        WikiRead, wiki, user_id=guild_context.user_id, context=guild_context
    )


@router.post("/", response_model=WikiRead, status_code=status.HTTP_201_CREATED)
async def create_wiki(
    wiki_in: WikiCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisWrite,
) -> WikiRead:
    """Create a wiki. Requires create_wikis permission on the initiative (or
    guild admin); the creator gets the owner grant."""
    resource_access.refuse_plugin_sharing(guild_context, wiki_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.wiki, wiki_in.initiative_id, current_user, guild_context
    )

    wiki = Wiki(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=wiki_in.name.strip(),
        description=(wiki_in.description or "").strip() or None,
    )
    session.add(wiki)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.wiki,
        user=current_user,
        resource_id=wiki.id,
        initiative_id=initiative.id,
        payload=wiki_in,
        grants=wiki_in.grants,
    )
    if wiki_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.wiki],
            guild_id=guild_context.guild_id,
            entity_id=wiki.id,
            tag_ids=wiki_in.tag_ids,
        )
    await attachments_service.claim_uploads(session, wiki)
    await properties_service.write_on_create(session, wiki, wiki_in.properties)
    await session.commit()
    return await read_after_write(session, wiki.id, current_user, guild_context)


@router.patch("/{wiki_id}", response_model=WikiRead)
async def update_wiki(
    wiki_id: int,
    wiki_in: WikiUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisWrite,
) -> WikiRead:
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    data = wiki_in.model_dump(exclude_unset=True)

    if "name" in data and data["name"] is not None:
        wiki.name = data["name"].strip()
    if "description" in data:
        wiki.description = (data["description"] or "").strip() or None
    # Both of these name one of the wiki's own pages, and neither is believed
    # without checking — a page id from another wiki would otherwise point this
    # wiki at somebody else's words.
    for field, refusal in (
        ("home_page_id", WikiMessages.HOME_NOT_IN_WIKI),
        ("template_page_id", WikiMessages.TEMPLATE_NOT_IN_WIKI),
    ):
        if field not in data:
            continue
        page_id = data[field]
        if page_id is not None:
            page = await wikis_service.get_page(session, page_id, wiki_id=wiki.id)
            if page is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=refusal
                )
        setattr(wiki, field, page_id)

    # The settings proper: each is written exactly when it was sent.
    for field in (
        "page_order",
        "contents_depth",
        "show_connections",
        "show_updated_at",
        "reading_width",
    ):
        if field in data and data[field] is not None:
            setattr(wiki, field, data[field])
    if "accent_color" in data:
        setattr(wiki, "accent_color", (data["accent_color"] or "").strip() or None)

    if data:
        wiki.updated_at = datetime.now(timezone.utc)
    session.add(wiki)
    await attachments_service.claim_uploads(session, wiki)
    await session.commit()
    return await read_after_write(session, wiki.id, current_user, guild_context)


async def read_after_write(
    session: RLSSessionDep,
    wiki_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> WikiRead:
    """The wiki a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await wikis_service.get_wiki_hydrated(
        session, wiki_id, populate_existing=True
    )
    if hydrated is None:
        raise Tool.wiki.not_found()
    return serialize_tool(
        WikiRead, hydrated, user_id=guild_context.user_id, context=guild_context
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@router.get("/{wiki_id}/pages", response_model=WikiPageTree)
async def list_wiki_pages(
    wiki_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisRead,
) -> WikiPageTree:
    """Every page of a wiki, in reading order.

    The whole list in one response: the navigation draws all of it, and these
    rows carry no bodies.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context
    )
    rows = await wikis_service.load_list(session, wiki)
    pages = [row for row, _ in rows if isinstance(row, WikiPage)]
    await tags_service.annotate_tags(session, pages)
    await properties_service.annotate_properties(session, pages)
    # The position each row is SERVED with is its place in the list as drawn —
    # a file's is kept on the wiki and a page's in its own column, and
    # neither is what a client counts with.
    known = {page.id for page in pages}
    items = [
        serialize_wiki_page_summary(row, context=guild_context, heading_nodes=nodes)
        if isinstance(row, WikiPage)
        else serialize_file_as_page(
            row,
            wiki_id=wiki.id,
            position=spot,
            heading_nodes=nodes,
            parent_page_id=wikis_service.visible_file_parent(wiki, row.id, known),
            context=guild_context,
        )
        for spot, (row, nodes) in enumerate(rows)
    ]
    return WikiPageTree(items=items)


@router.put("/{wiki_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_file_to_wiki(
    wiki_id: int,
    file_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Put an existing file in this wiki.

    Two gates, because two things are involved: write on the wiki, because the
    wiki is what gains a page, and read on the file, because you cannot put
    something in front of people that you cannot see yourself.

    The file is not moved or copied. It joins by an edge — ``file
    part_of wiki`` — so it keeps its address, its sharing and its history, and
    goes on belonging to whatever else it already belonged to.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context
    )

    await relationships_service.create(
        session,
        source=relationships_service.Endpoint(SearchEntityType.file, file.id),
        relationship_type=RelationshipType.part_of,
        target=relationships_service.Endpoint(SearchEntityType.wiki, wiki.id),
        created_by=current_user.id,
    )
    await session.commit()


@router.post("/{wiki_id}/files/{file_id}/move", status_code=status.HTTP_204_NO_CONTENT)
async def move_wiki_file(
    wiki_id: int,
    file_id: int,
    move: WikiPageMove,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """File a borrowed file under a page of this wiki, or at its top, and
    put it in order there.

    Where it sits is recorded on the wiki, not on the file: the same
    file can sit somewhere else entirely in another wiki.

    Write on the wiki is the whole gate, and read on the file is implied by
    it already being in a wiki this person may write: where it sits is a
    decision about the wiki, not a change to the file — which is why the
    file itself is never written.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    files = await wikis_service.linked_files(session, wiki.id)
    file = next((d for d in files if d.id == file_id), None)
    if file is None:
        raise KINDS["wiki_page"].not_found()

    if move.parent_page_id is not None and (
        await wikis_service.get_page(session, move.parent_page_id, wiki_id=wiki.id)
        is None
    ):
        raise KINDS["wiki_page"].not_found()
    await wikis_service.place_in_list(
        session, wiki, file, move.position, move.parent_page_id
    )
    await session.commit()


@router.delete("/{wiki_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_file_from_wiki(
    wiki_id: int,
    file_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Take a file back out of this wiki.

    The wiki loses a page; the file loses nothing. Write on the wiki is the
    only gate — this is a decision about what the wiki contains.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    edge = await relationships_service.find(
        session,
        source=relationships_service.Endpoint(SearchEntityType.file, file_id),
        relationship_type=RelationshipType.part_of,
        target=relationships_service.Endpoint(SearchEntityType.wiki, wiki.id),
    )
    if edge is not None:
        await relationships_service.remove(session, edge, removed_by=current_user.id)
        wikis_service.forget_file_placement(wiki, file_id)
        session.add(wiki)
        await session.commit()


@router.post(
    "/{wiki_id}/pages",
    response_model=WikiPageRead,
    status_code=status.HTTP_201_CREATED,
)
@max_document_body
async def create_wiki_page(
    wiki_id: int,
    page_in: WikiPageCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisWrite,
) -> WikiPageRead:
    """Add a page. Write access on the wiki is the whole gate — a page is the
    wiki's content.

    It arrives as a draft unless the request says otherwise: for as long as it
    takes to write one, a new page is empty and unnamed, and the people who
    only read this wiki have no use for that.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    title = (page_in.title or "").strip()

    if page_in.parent_page_id is not None:
        parent = await wikis_service.get_page(
            session, page_in.parent_page_id, wiki_id=wiki.id
        )
        if parent is None:
            raise KINDS["wiki_page"].not_found()

    # A new page starts as a copy of the wiki's template, where it has one and
    # the request did not bring a body of its own. That is what keeps two
    # hundred character pages the same shape without anybody policing it.
    content = page_in.content
    if content is None and wiki.template_page_id is not None:
        template = await wikis_service.get_page(
            session, wiki.template_page_id, wiki_id=wiki.id
        )
        if template is not None:
            content = deepcopy(template.content or {})

    page = WikiPage(
        wiki_id=wiki.id,
        created_by=guild_context.user_id,
        parent_page_id=page_in.parent_page_id,
        position=await wikis_service.next_position(
            session, wiki, page_in.parent_page_id
        ),
        is_draft=page_in.is_draft,
        title=title,
        slug=await wikis_service.unique_page_slug(session, wiki.id, title),
        content=content or {},
    )
    session.add(page)
    await session.flush()

    if page_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["wiki_page"],
            guild_id=guild_context.guild_id,
            entity_id=page.id,
            tag_ids=page_in.tag_ids,
        )

    # What the body names becomes `references` edges, the same way a file's
    # does — which is what makes the backlinks below say anything.
    await content_references.sync_for_entity(
        session,
        relationships_service.Endpoint(SearchEntityType.wiki_page, page.id),
        body=page.content,
        author_id=guild_context.user_id,
    )
    await attachments_service.claim_uploads(session, page)
    await properties_service.write_on_create(session, page, page_in.properties)
    await session.commit()
    hydrated = await resource_access.reload_child(session, WikiPage, page.id)
    return await _serialized_page(session, hydrated, guild_context)


@pages_router.get("/wiki-pages/{page_id}", response_model=WikiPageRead)
async def read_wiki_page(
    page_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisRead,
) -> WikiPageRead:
    """One page by its own id, which is all a link to it, a mention or a
    stored notification names."""
    page = await resource_access.load_child(session, WikiPage, page_id)
    return await _serialized_page(session, page, guild_context)


@pages_router.post(
    "/wiki-pages/{page_id}/ai/summary",
    response_class=ai_generation.AIStreamResponse,
    responses={200: {"model": AIStreamEvent}},
)
async def summarize_wiki_page(
    page_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> ai_generation.AIStreamResponse:
    """A summary of a page, streamed as it is written. Requires read access
    to the page."""
    page = await resource_access.load_child(session, WikiPage, page_id)
    content = await current_content(
        guild_context.guild_id, SearchEntityType.wiki_page.value, page.id, page.content
    )
    await ai_generation.record_request(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        purpose="summary",
        target_type="wiki_page",
        target_id=page.id,
        initiative_id=page.wiki.initiative_id,
    )
    return ai_generation.AIStreamResponse(
        await ai_generation.summarize(
            session,
            current_user,
            guild_context.guild_id,
            title=page.title,
            content=content,
        )
    )


@pages_router.post(
    "/wiki-pages/{page_id}/duplicate",
    response_model=WikiPageRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_wiki_page(
    page_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisWrite,
) -> WikiPageRead:
    """Copy the page, without the pages under it, to the end of where it is
    filed, as "<title> (Copy)", with its tags, links and properties."""
    page = await resource_access.load_child(session, WikiPage, page_id, access="write")
    wiki = page.wiki
    copy = await tool_copy.duplicate_child(
        session,
        page,
        parent_page_id=page.parent_page_id,
        position=await wikis_service.next_position(session, wiki, page.parent_page_id),
        slug=await wikis_service.unique_page_slug(
            session, wiki.id, tool_copy.copied_name(page)
        ),
    )
    await session.commit()
    hydrated = await resource_access.reload_child(session, WikiPage, copy.id)
    return await _serialized_page(session, hydrated, guild_context)


@pages_router.patch("/wiki-pages/{page_id}", response_model=WikiPageRead)
@max_document_body
async def update_wiki_page(
    page_id: int,
    page_in: WikiPageUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisWrite,
) -> WikiPageRead:
    page = await resource_access.load_child(session, WikiPage, page_id, access="write")
    data = page_in.model_dump(exclude_unset=True)
    content_updated = "content" in data and data["content"] is not None
    room = (
        collaboration_manager.live_room(
            guild_context.guild_id, SearchEntityType.wiki_page.value, page.id
        )
        if content_updated
        else None
    )
    version = data.get("content_version")
    # A page with a live collaboration room has that room as the writer of its
    # content. A body naming no version may describe a page the session has
    # moved on from, so it is refused rather than saved over. A patch with no
    # body (a rename, a draft flag, tags) still applies.
    if room is not None and version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.LIVE_SESSION_OWNS_CONTENT,
        )
    if room is None and content_updated:
        # Locked until this write commits, so a write naming the same version
        # reads this one's content.
        await session.refresh(page, ["content"], with_for_update=True)
        # A page is written over whole, so a write naming the content it
        # changed is refused once that content has moved on: writing it would
        # undo whatever moved it.
        if version is not None and content_version(page.content) != version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CommonMessages.CONTENT_CHANGED,
            )

    if "is_draft" in data and data["is_draft"] is not None:
        page.is_draft = data["is_draft"]
    if "title" in data and data["title"] is not None:
        title = data["title"].strip()
        if title != page.title:
            page.title = title
            page.slug = await wikis_service.unique_page_slug(
                session, page.wiki_id, title, exclude_page_id=page.id
            )
    if room is not None:
        # The writer read what the session holds now: the change goes into
        # it, reaches the open editors, and is saved with their edits.
        if not await room.write(
            data["content"], version, user_id=guild_context.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CommonMessages.CONTENT_CHANGED,
            )
        content_updated = False
    elif content_updated:
        page.content = data["content"]
        # No room is live, so this edit is the newest thing about the page:
        # its stored Yjs state has it written in, and the next session opens
        # on it.
        page.yjs_state = await written_into(
            body_states.LEXICAL, page.yjs_state, page.content
        )

    if data:
        page.updated_at = datetime.now(timezone.utc)
    session.add(page)
    await session.flush()

    if "tag_ids" in data and data["tag_ids"] is not None:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["wiki_page"],
            guild_id=guild_context.guild_id,
            entity_id=page.id,
            tag_ids=data["tag_ids"],
        )
    await properties_service.write_on_update(session, page, page_in.properties)
    if "content" in data:
        await content_references.sync_for_entity(
            session,
            relationships_service.Endpoint(SearchEntityType.wiki_page, page.id),
            body=page.content,
            author_id=guild_context.user_id,
        )
    await attachments_service.claim_uploads(session, page)
    await session.commit()
    if content_updated:
        # A room left in memory would still hold the state from before this
        # edit; dropping it makes the next session load from the database.
        await collaboration_manager.invalidate_room_if_empty(
            guild_context.guild_id, SearchEntityType.wiki_page.value, page.id
        )
    hydrated = await resource_access.reload_child(session, WikiPage, page.id)
    return await _serialized_page(session, hydrated, guild_context)


@pages_router.post("/wiki-pages/{page_id}/move", response_model=WikiPageRead)
async def move_wiki_page(
    page_id: int,
    move: WikiPageMove,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: WikisWrite,
) -> WikiPageRead:
    """File a page and place it there in one request — what a drag is.

    Only the page's new neighbours are renumbered: a position means something
    among the pages filed together and nothing across the wiki.
    """
    page = await resource_access.load_child(session, WikiPage, page_id, access="write")
    wiki = page.wiki
    await wikis_service.validate_reparent(session, page, move.parent_page_id)
    await wikis_service.place_in_list(
        session, wiki, page, move.position, move.parent_page_id
    )
    await session.commit()
    hydrated = await resource_access.reload_child(session, WikiPage, page.id)
    return await _serialized_page(session, hydrated, guild_context)


@pages_router.delete("/wiki-pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wiki_page(
    page_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Send a page to the trash. Its children go with it — a section is put
    away whole."""
    page = await resource_access.load_child(session, WikiPage, page_id, access="write")
    # Sub-pages go with it through CASCADE_CHILDREN, the same way a comment
    # thread follows its root.
    await soft_delete_service.trash(
        session,
        page,
        deleted_by_user_id=guild_context.user_id,
    )
    await session.commit()
