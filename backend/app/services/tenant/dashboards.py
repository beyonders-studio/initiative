"""Dashboard service — loaders and helpers for the dashboard tool.

A dashboard is a shareable DAC resource (``resource_type='dashboard'``) whose
``definition`` is a validated presentation spec. It owns no child content: the
data it displays lives in other tools and is fetched per viewer through those
tools' own gated endpoints, so the loaders here only need what serialization
and the permission engine read.
"""

from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.dashboard import Dashboard
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service


def dashboard_loader_options() -> list:
    """Eager-load what a dashboard *list* row needs: its sharing, its
    initiative and the level the request holds on it."""
    return [
        selectinload(Dashboard.grants),
        selectinload(Dashboard.initiative),
        undefer(Dashboard.actions),
    ]


async def get_dashboard(
    session: AsyncSession,
    dashboard_id: int,
    *,
    populate_existing: bool = False,
) -> Dashboard | None:
    """Fetch a dashboard as a list row carries it: what authorizing it and the
    grant flow read. RLS scopes the row to the request's guild."""
    stmt = (
        select(Dashboard)
        .where(Dashboard.id == dashboard_id)
        .options(*dashboard_loader_options())
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(stmt)).one_or_none()


async def get_dashboard_hydrated(
    session: AsyncSession,
    dashboard_id: int,
    *,
    populate_existing: bool = False,
) -> Dashboard | None:
    """:func:`get_dashboard` plus the tags and properties a serialized
    ``DashboardRead`` carries."""
    dashboard = await get_dashboard(
        session, dashboard_id, populate_existing=populate_existing
    )
    if dashboard is not None:
        await tags_service.annotate_tags(session, [dashboard])
        await metadata_service.annotate_properties(session, [dashboard])
    return dashboard
