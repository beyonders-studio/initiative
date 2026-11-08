"""`/api/v1/c/{community_id}/search` — one query across everything in a guild.

Guild-scoped like any other content endpoint: the guild comes from the path and
``RLSSessionDep`` routes into its schema, so the index answers under the same
gates as the content it mirrors.

An installed plug-in may call ``/suggest``.
The scope it needs depends on the ``types`` it asks for, so the route takes
:func:`app.api.deps.plugin_scope_checked` and the service narrows ``types`` to the
kinds the install may read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
    plugin_scope_checked,
)
from app.core.references import parse_ref
from app.core.search import SearchEntityType
from app.db.guild_standing import InstallContext
from app.db.plugin_rls import SEARCH_ENTRY_READ_SCOPE
from app.db.search_index import entity_types
from app.models.platform.user import User
from app.schemas.tenant.search import SearchResults, SearchSuggestion
from app.services.tenant import search as search_service

router = APIRouter(route_class=ActorRoute)

#: ``/suggest`` for a person or an installed plug-in. A plug-in needs the read scope
#: of each kind it asks for, which the service checks once it has ``types``.
SuggestByEntityType = Annotated[
    ActorContext,
    Depends(
        plugin_scope_checked(
            {f"{resource.value}:read" for resource in SEARCH_ENTRY_READ_SCOPE.values()},
            per="entity type",
        )
    ),
]

_ARCHIVED_DESCRIPTION = (
    "Include archived work. Left out by default, so a search answers with what "
    "is in play."
)
_TEMPLATE_DESCRIPTION = (
    "Omit for both. ``true`` returns only templates (a template picker), "
    "``false`` only real content (a picker choosing where content goes)."
)
_SUBJECT_DESCRIPTION = (
    "The thing being written in, as a reference (``file:12``). It is left "
    "out of the answer: a thing does not point at itself. A reference that "
    "names nothing narrows nothing."
)
_TYPE_DESCRIPTION = (
    "Restrict to these entity types. Omit for the default scope "
    f"({', '.join(t.value for t in entity_types(default_scope_only=True))}); "
    "naming a type "
    "reaches it explicitly."
)


@router.get("/", response_model=SearchResults)
async def search_community(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    search: str = Query(description="What to search for.", max_length=1000),
    types: list[SearchEntityType] | None = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    initiative_id: int | None = Query(
        default=None, description="Restrict to one initiative."
    ),
    include_archived: bool = Query(default=False, description=_ARCHIVED_DESCRIPTION),
    is_template: bool | None = Query(default=None, description=_TEMPLATE_DESCRIPTION),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=search_service.MAX_PAGE_SIZE),
) -> SearchResults:
    """Ranked matches across the guild's tools, comments and tags.

    ``total_count`` counts entities the caller may see, so it is what a pager
    should show rather than an estimate to correct later.
    """
    return await search_service.search(
        session,
        query=search,
        filters=search_service.Filters(
            types=types,
            initiative_id=initiative_id,
            include_archived=include_archived,
            template=is_template,
        ),
        page=page,
        page_size=page_size,
    )


@router.get("/recent", response_model=list[SearchSuggestion])
async def recent_community(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    types: list[SearchEntityType] | None = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    initiative_id: int | None = Query(
        default=None, description="Restrict to one initiative."
    ),
    is_template: bool | None = Query(default=None, description=_TEMPLATE_DESCRIPTION),
    subject: str | None = Query(default=None, description=_SUBJECT_DESCRIPTION),
    limit: int = Query(default=search_service.SUGGEST_LIMIT, ge=1),
) -> list[SearchSuggestion]:
    """What a picker offers before anything has been typed.

    The most recently changed things the caller could name, taking the same
    ``types``, ``initiative_id`` and ``is_template`` narrowing as the search — so
    what a picker suggests and what it finds are the same set of things.
    """
    return await search_service.recent(
        session,
        user_id=current_user.id,
        filters=search_service.Filters(
            types=types,
            initiative_id=initiative_id,
            template=is_template,
            subject=parse_ref(subject) if subject else None,
        ),
        limit=limit,
    )


@router.get("/suggest", response_model=list[SearchSuggestion])
async def suggest_community(
    session: ActorSessionDep,
    guild_context: SuggestByEntityType,
    search: str = Query(description="What to jump to.", max_length=200),
    types: list[SearchEntityType] | None = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    initiative_id: int | None = Query(
        default=None, description="Restrict to one initiative."
    ),
    is_template: bool | None = Query(default=None, description=_TEMPLATE_DESCRIPTION),
    subject: str | None = Query(default=None, description=_SUBJECT_DESCRIPTION),
    limit: int = Query(default=search_service.SUGGEST_LIMIT, ge=1),
) -> list[SearchSuggestion]:
    """Titles for the command palette — a way to reach one thing quickly.

    Takes the same ``types`` as the search itself, so the palette and the
    results page can be narrowed to the same slice of the guild.

    An installed plug-in is answered the kinds among ``types`` (the default scope
    when omitted) whose read scope it holds, in the initiatives it is placed
    in, and only what it could read through the tools themselves. Asking only
    for kinds it holds no read scope for is 403 (``PLUGIN_SCOPE_REQUIRED``).
    """
    install = guild_context if isinstance(guild_context, InstallContext) else None
    return await search_service.suggest(
        session,
        query=search,
        user_id=guild_context.user_id,
        filters=search_service.Filters(
            types=types,
            initiative_id=initiative_id,
            template=is_template,
            subject=parse_ref(subject) if subject else None,
        ),
        limit=limit,
        install=install,
    )
