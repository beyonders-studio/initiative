"""Calendar endpoints — the shareable container for events.

A calendar is to events what a project is to tasks: creation is gated at the
initiative level (calendars_enabled + create_calendars), and everything inside
the calendar flows from its resource-grant DAC (``resource_grants`` +
``PUT /{id}/grants``). Events themselves carry no grants.

A calendar with no initiative is a **guild calendar** — it belongs to the guild
itself, and lives inside the calendar plug-in, whose install owns it. Guild admins
make one and decide its sharing; a member with a write grant on it writes its
events.
"""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    CommunityIdPath,
    GuildAccessError,
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    authenticate_feed,
    establish_guild_access,
    plugin_scope,
    raise_for_guild_access,
)
from app.core.rate_limit import limiter
from app.core.messages import CalendarMessages, GuildMessages
from app.core.tools import Tool
from app.core.user_input_validators import resolve_zone
from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.platform.user import User
from app.schemas.tenant.calendar import (
    CalendarCreate,
    CalendarRead,
    CalendarUpdate,
)
from app.schemas.tenant.tool import serialize_tool
from app.services.export.adapters.calendar_events import event_dicts
from app.services.export.engine import count_within_bound, get_adapter
from app.services.tenant import metadata as metadata_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import tags as tags_service
from app.services.tenant.ical_service import ical_from_export_dicts

router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the calendars scopes.
CalendarsRead = Annotated[ActorContext, Depends(plugin_scope("calendars:read"))]
CalendarsWrite = Annotated[ActorContext, Depends(plugin_scope("calendars:write"))]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/{calendar_id}", response_model=CalendarRead)
async def read_calendar(
    calendar_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CalendarRead:
    calendar = await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, current_user, guild_context
    )
    return serialize_tool(
        CalendarRead, calendar, user_id=guild_context.user_id, context=guild_context
    )


async def _feed_user(
    request: Request, session: SessionDep, guild_id: CommunityIdPath, calendar_id: int
) -> User:
    """The person a calendar's subscription link names. A dependency, so the
    feed's rate limit counts them rather than the address fetching for them."""
    return await authenticate_feed(
        request, session, (guild_id, Tool.calendar, calendar_id)
    )


def _unchanged(if_none_match: Optional[str], etag: str) -> bool:
    """Whether ``If-None-Match`` names ``etag``: any tag in its list, weak or
    strong, or ``*``."""
    if if_none_match is None:
        return False
    tags = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return "*" in tags or etag in tags


@router.get("/{calendar_id}/feed.ics", include_in_schema=False)
@limiter.limit("30/minute")
async def calendar_feed(
    request: Request,
    guild_id: CommunityIdPath,
    calendar_id: int,
    session: SessionDep,
    user: Annotated[User, Depends(_feed_user)],
    if_none_match: Annotated[Optional[str], Header(alias="If-None-Match")] = None,
) -> Response:
    """The calendar as an iCalendar feed, for another app to subscribe to.

    Signed in by a personal API key in ``?token=`` that names this calendar,
    and answered as the calendar page's events export of it: the same reader,
    the same events, the same row bound, and refused while its initiative
    keeps its content in. Every fetch is authorized afresh.
    """
    # SessionDep, routed here: the guild comes from the path and access is
    # established for the person the link names, as a file download does. The
    # dependency has already put the deployment's second-factor question.
    try:
        context = await establish_guild_access(
            session, user, guild_id, factor_asked=True
        )
    except GuildAccessError as exc:
        raise_for_guild_access(exc)
    calendar = await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, user, context
    )
    params = {"calendar_ids": [calendar_id]}
    await count_within_bound(
        session,
        get_adapter("events", "ics"),
        user=user,
        guild_id=guild_id,
        params=params,
        format="ics",
    )
    dicts, _ = await event_dicts(session, user, params)
    # Named with where it lives, so two communities' "Events" stay apart in
    # the subscriber's app, and listed in the subscriber's own zone.
    home = calendar.initiative.name if calendar.initiative else context.guild.name
    body = ical_from_export_dicts(
        dicts,
        name=f"{calendar.name} · {home}",
        tz=resolve_zone(user.timezone).key,
    )
    headers = {
        "ETag": f'"{sha256(body).hexdigest()}"',
        "Cache-Control": "private, no-cache",
    }
    if _unchanged(if_none_match, headers["ETag"]):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(body, media_type="text/calendar; charset=utf-8", headers=headers)


@router.post("/", response_model=CalendarRead, status_code=status.HTTP_201_CREATED)
async def create_calendar(
    calendar_in: CalendarCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarRead:
    """Create a calendar.

    Two scopes, two gates. An **initiative** calendar needs that initiative's
    calendars switch on and the ``create_calendars`` permission (or guild
    admin), and its creator gets the owner grant. A **guild** calendar —
    ``initiative_id`` omitted — belongs to no initiative, so neither has
    anything to say about it: it is the guild admin's to make. It needs the
    calendar plug-in, whose install owns it and whose removal takes it along.

    An installed plug-in creates initiative calendars only: a guild calendar is
    owned by the calendar plug-in's install, which is community configuration.
    What it creates is owned by its install, whose owner row the table's
    trigger writes; it sets no initial sharing.
    """
    resource_access.refuse_plugin_sharing(guild_context, calendar_in, "grants")
    plugin: Optional[GuildPlugin] = None
    initiative_id = calendar_in.initiative_id

    if initiative_id is None and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarMessages.PLUGIN_INITIATIVE_REQUIRED,
        )
    if initiative_id is None:
        if not guild_context.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.COMMUNITY_ADMIN_REQUIRED,
            )
        plugin = await guild_plugins_service.find_mounting_plugin(
            session, tool=Tool.calendar.value
        )
        if plugin is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=CalendarMessages.GUILD_PLUGIN_REQUIRED,
            )
    else:
        await resource_access.prepare_create(
            session, Tool.calendar, initiative_id, current_user, guild_context
        )

    calendar = Calendar(
        initiative_id=initiative_id,
        created_by=guild_context.user_id,
        name=calendar_in.name.strip(),
        description=calendar_in.description,
        color=calendar_in.color,
    )
    session.add(calendar)
    await session.flush()

    if plugin is None:
        await resource_access.grant_initial_sharing(
            session,
            guild_context,
            Tool.calendar,
            user=current_user,
            resource_id=calendar.id,
            initiative_id=initiative_id,
            payload=calendar_in,
            grants=calendar_in.grants,
        )
    else:
        # The plug-in is the container, so it owns this.
        await calendars_service.give_to_install(
            session,
            calendar,
            install_id=plugin.id,
            guild_id=guild_context.guild_id,
            grants=calendar_in.grants,
            actor_user_id=guild_context.user_id,
        )

    if calendar_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.calendar],
            guild_id=guild_context.guild_id,
            entity_id=calendar.id,
            tag_ids=calendar_in.tag_ids,
        )

    await attachments_service.claim_uploads(session, calendar)
    await metadata_service.write_on_create(session, calendar, calendar_in.properties)
    await session.commit()
    return await read_after_write(session, calendar.id, current_user, guild_context)


@router.patch("/{calendar_id}", response_model=CalendarRead)
async def update_calendar(
    calendar_id: int,
    calendar_in: CalendarUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarRead:
    """Rename/update a calendar. Asks the edit action, which on a guild
    calendar is the guild admin's: a write grant on one writes its events."""
    calendar = await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        current_user,
        guild_context,
        access="write",
    )
    data = calendar_in.model_dump(exclude_unset=True)
    if data:
        for field, value in data.items():
            setattr(calendar, field, value)
        calendar.updated_at = datetime.now(timezone.utc)
        session.add(calendar)
        await attachments_service.claim_uploads(session, calendar)
        await session.commit()
    return await read_after_write(session, calendar_id, current_user, guild_context)


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    calendar_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> CalendarRead:
    """The calendar a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    calendar = await calendars_service.get_calendar(
        session, calendar_id, populate_existing=True
    )
    if not calendar:
        raise Tool.calendar.not_found()
    return serialize_tool(
        CalendarRead, calendar, user_id=guild_context.user_id, context=guild_context
    )
