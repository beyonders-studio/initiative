"""Calendar container service — loaders and helpers for the calendar tool.

A calendar is the shareable DAC anchor for its events (``resource_type=
'calendar'``); events inherit access from it the way tasks inherit from their
project, so the loaders here eager-load ``grants`` and the level the request
holds on the calendar.

Two kinds of calendar live here. Nearly all of them belong to an initiative. A
**guild calendar** — the one the calendar plug-in installs — belongs to none, and
that is the whole of what it is: a set of its own events, holding nothing from
any initiative and reaching into none. Its ``initiative_id`` is NULL, so
anything derived from an initiative has nothing to derive from and refuses.
"""

from typing import Any, Sequence

from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
)
from app.services import permissions as permissions_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant.tool_listing import initiative_switch_clause


def calendar_loader_options() -> list:
    """Eager-load everything calendar serialization + authorization needs."""
    return [
        selectinload(Calendar.grants),
        selectinload(Calendar.initiative),
        undefer(Calendar.actions),
    ]


async def get_calendar(
    session: AsyncSession,
    calendar_id: int,
    *,
    populate_existing: bool = False,
    with_events: bool = False,
) -> Calendar | None:
    """Fetch a calendar with the relationships authorization + serialization
    need, and with ``with_events`` its events as an export serializes them.
    RLS scopes the row to the request's guild."""
    stmt = (
        select(Calendar)
        .where(Calendar.id == calendar_id)
        .options(
            *calendar_loader_options(),
            *(_event_export_loader_options() if with_events else ()),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    calendar = result.one_or_none()
    if calendar is not None:
        await tags_service.annotate_tags(session, [calendar])
        await metadata_service.annotate_properties(session, [calendar])
        if with_events:
            await tags_service.annotate_tags(session, calendar.events or [])
            await metadata_service.annotate_properties(session, calendar.events or [])
    return calendar


def _event_export_loader_options() -> list:
    """Eager-load each event's relationships that export serialization reads —
    ``event_export_dict`` walks attendees, tags, linked files, and property
    values, and async SQLAlchemy forbids the lazy loads those would otherwise
    trigger on the worker's render-time replay."""
    return [
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.attendees)
        .selectinload(CalendarEventAttendee.user),
    ]


async def list_calendar_ids_for_export(
    session: AsyncSession, *, initiative_id: int | None = None
) -> list[int]:
    """Ids of every calendar the user may export — the enumeration behind
    "export my calendars": calendars whose tool is on, DAC-visible to the user
    (a request that reaches the whole guild sees all), optionally narrowed to one
    initiative. Deterministic order for stable output.

    Narrowed to an initiative, a guild calendar is not among them: it belongs to
    no initiative, so it is in no initiative's export either. The tool switch
    applies in both shapes — the narrowing composes with it rather than
    replacing it, so a disabled initiative exports nothing here just as it
    lists nothing everywhere else."""

    conditions = [
        initiative_switch_clause(Tool.calendar, Calendar, guild_level_rows=True)
    ]
    if initiative_id is not None:
        conditions.append(Calendar.initiative_id == initiative_id)

    statement = (
        select(Calendar.id)
        .where(*conditions)
        .order_by(Calendar.name.asc(), Calendar.id.asc())
    )
    return list(await session.exec(statement))


async def give_to_install(
    session: AsyncSession,
    calendar: Calendar,
    *,
    install_id: int,
    guild_id: int,
    grants: Sequence[Any],
    actor_user_id: int | None = None,
) -> None:
    """Make a guild calendar the install's, shared by ``grants``. Uninstalling
    trashes what the install owns; the owner grant names the install row, so
    an uninstall holding that row finishes first and this write fails. At
    guild scope an everyone grant reads as every member of the guild."""
    await ownership_service.set_resource_owner(
        session,
        tool=Tool.calendar,
        row=calendar,
        new_owner=ownership_service.Owner(plugin_install_id=install_id),
    )
    await permissions_service.replace_resource_grants(
        session,
        resource_type=Tool.calendar.value,
        resource_id=calendar.id,
        guild_id=guild_id,
        initiative_id=None,
        owner_id=None,
        grants=grants,
        actor_user_id=actor_user_id,
    )
