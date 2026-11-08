"""Calendar-entries aggregate — the dated things in a window, in one request.

The calendar surfaces (an initiative's Events page and the cross-guild My
Calendar) render events and task start/due markers together over one bounded date
window. Historically each fired two list requests (events + tasks) and merged
them client-side. These endpoints return the union in a single round trip.

This is a **union under the existing gates**, not a new authorization surface:
each leg delegates to the exact query path of
``calendar_events.query_guild_calendar_events`` / ``list_tasks`` (guild) and
``query_my_calendar_events`` / ``list_my_tasks`` (me), so RLS + per-resource
DAC are identical. The client keeps the merge, so the
response reuses the existing ``CalendarEventSummary`` and ``TaskListRead`` shapes.
A repeating event or task is expanded into its occurrences in the window here,
from rows those queries returned. Projects whose dates fall in the window and
polls that close in it are opt-in legs on the same terms: each takes its own
list's conditions and serializer (``visible_project_conditions``,
``board_conditions``).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlmodel import select

from app.api.deps import (
    GuildContextDep,
    RLSSessionDep,
    UserSessionDep,
    get_current_active_user,
)
from app.api.v1.tenant_endpoints import calendar_events as calendar_events_api
from app.api.v1.tenant_endpoints import posts as posts_api
from app.api.v1.tenant_endpoints import projects as projects_api
from app.core.user_input_validators import resolve_zone
from app.models.platform.user import User
from app.models.tenant.post import Post
from app.models.tenant.post_poll import PostPoll
from app.models.tenant.project import Project
from app.schemas.tenant.calendar_entry import CalendarEntriesResponse
from app.schemas.tenant.calendar_event import serialize_calendar_event_summary
from app.schemas.tenant.post import PostRead
from app.schemas.tenant.tool import serialize_tool
from app.services.tenant import calendar_events as events_service
from app.services.tenant import calendar_occurrences as occurrences_service
from app.services.tenant import posts as posts_service
from app.services.tenant import task_queries

router = APIRouter()
# Cross-guild "my calendar" aggregate. Mounted under /api/v1/me.
me_router = APIRouter()


@router.get("/", response_model=CalendarEntriesResponse)
async def list_calendar_entries(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    window: calendar_events_api.CalendarWindowDep,
    initiative_id: int | None = Query(default=None),
    scope: Literal["community"] | None = Query(default=None),
    calendar_ids: list[int] | None = Query(default=None),
    property_filters: str | None = Query(default=None),
    conditions: str | None = Query(
        default=None,
        description="Task filter conditions (same JSON shape as GET /tasks).",
    ),
    tz: str | None = Query(default=None),
    include_events: bool = Query(default=True),
    include_tasks: bool = Query(default=True),
    include_projects: bool = Query(default=False),
    include_polls: bool = Query(default=False),
) -> CalendarEntriesResponse:
    """Events + task markers for one guild's calendar over a date window.

    ``start_after``/``start_before`` are required and bound both legs; the
    window may span at most ``MAX_CALENDAR_WINDOW``.

    Skip a leg with ``include_events=false`` / ``include_tasks=false`` (e.g. when
    the calendar has that type toggled off), and ask for the projects whose start
    or end date is in the window with ``include_projects=true`` and the polls
    that close in it with ``include_polls=true``. ``calendar_ids`` narrows the event
    leg to named calendars — a surface showing a single calendar asks for
    exactly it rather than everything and filtering client-side.

    ``scope=community`` is the same question asked by kind rather than by name: every
    guild calendar, however many there are. The calendar plug-in shows all of them
    at once, and a list of ids it had to assemble first would be a page of them.

    ``initiative_id`` and ``scope`` bound every leg: an initiative's tasks are
    those of its projects, and the community as a whole holds no tasks,
    projects or posts, since each of those is an initiative's.
    """
    events_out = []
    if include_events:
        events = await events_service.query_guild_calendar_events(
            session,
            current_user,
            guild_context,
            initiative_id=initiative_id,
            guild_scope=scope == "community",
            calendar_ids=calendar_ids,
            start_after=window.start_after,
            start_before=window.start_before,
            tz=tz,
            property_filters=property_filters,
        )
        events_out = events_service.occurrences(
            [
                serialize_calendar_event_summary(
                    e, user_id=current_user.id, context=guild_context
                )
                for e in events
            ],
            window.start_after,
            window.start_before,
            tz,
            await occurrences_service.changed_starts(
                session, [e.id for e in events if e.recurrence]
            ),
        )

    tasks_out, task_occurrences = [], []
    if include_tasks and scope != "community":
        tasks_out, task_occurrences = task_queries.projected_occurrences(
            await task_queries.query_guild_tasks(
                session,
                current_user,
                guild_context,
                conditions=conditions,
                tz=tz,
                start_after=window.start_after,
                start_before=window.start_before,
                initiative_id=initiative_id,
            ),
            window.start_after,
            window.start_before,
        )

    projects_out = []
    if include_projects and scope != "community":
        # Whole days, so the window's bounds are read as the viewer's dates.
        zone = resolve_zone(tz)
        first = window.start_after.astimezone(zone).date()
        last = window.start_before.astimezone(zone).date()
        projects = (
            await session.exec(
                select(Project)
                .where(
                    *projects_api.visible_project_conditions(
                        current_user.id,
                        context=guild_context,
                        archived=False,
                        is_template=False,
                        initiative_id=initiative_id,
                    ),
                    or_(
                        Project.start_date.between(first, last),
                        Project.end_date.between(first, last),
                    ),
                )
                .options(*projects_api.project_load_options(slim=True))
                .order_by(Project.id)
            )
        ).all()
        projects_out = await projects_api.serialize_project_page(
            session, current_user.id, list(projects), slim=True
        )

    polls_out = []
    if include_polls and scope != "community":
        posts = list(
            (
                await session.exec(
                    select(Post)
                    .join(PostPoll, PostPoll.post_id == Post.id)
                    .where(
                        *posts_api.board_conditions(
                            current_user.id,
                            context=guild_context,
                            initiative_id=initiative_id,
                            archived=False,
                        ),
                        Post.published_at.is_not(None),
                        PostPoll.closes_at >= window.start_after,
                        PostPoll.closes_at < window.start_before,
                    )
                    .options(*posts_service.list_loader_options())
                    .order_by(PostPoll.closes_at, Post.id)
                )
            ).all()
        )
        await posts_api.annotate_post_rows(session, posts, user_id=current_user.id)
        polls_out = [
            serialize_tool(
                PostRead, post, context=guild_context, user_id=current_user.id
            )
            for post in posts
        ]

    return CalendarEntriesResponse(
        events=events_out,
        tasks=tasks_out,
        task_occurrences=task_occurrences,
        projects=projects_out,
        polls=polls_out,
    )


@me_router.get("/calendar-entries", response_model=CalendarEntriesResponse)
async def list_my_calendar_entries(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    window: calendar_events_api.CalendarWindowDep,
    guild_ids: list[int] | None = Query(default=None, alias="community_ids"),
    conditions: str | None = Query(
        default=None,
        description="Task filter conditions (same JSON shape as GET /me/tasks).",
    ),
    tz: str | None = Query(default=None),
    include_events: bool = Query(default=True),
    include_tasks: bool = Query(default=True),
) -> CalendarEntriesResponse:
    """Cross-guild events + assigned-task markers for the My Calendar page.

    Both legs run on the caller's own ``platform_<tier>`` session, as
    ``/me/tasks`` does: the event leg enters each
    member guild with the membership role held there (``gather_across_guilds``)
    and the task leg is the ``/me/tasks`` query, fetch-all over the window.
    """
    events_out = []
    if include_events:
        events = await events_service.query_my_calendar_events(
            session,
            current_user,
            guild_ids=guild_ids,
            start_after=window.start_after,
            start_before=window.start_before,
            tz=tz,
        )
        # Already serialized and expanded inside each guild's own routed fetch.
        events_out = events

    tasks_out, task_occurrences = [], []
    if include_tasks:
        tasks_out, task_occurrences = task_queries.projected_occurrences(
            await task_queries.query_my_tasks_list(
                session,
                current_user,
                conditions=conditions,
                tz=tz,
                start_after=window.start_after,
                start_before=window.start_before,
            ),
            window.start_after,
            window.start_before,
        )

    return CalendarEntriesResponse(
        events=events_out, tasks=tasks_out, task_occurrences=task_occurrences
    )
