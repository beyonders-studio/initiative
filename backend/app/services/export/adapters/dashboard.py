"""Dashboard source adapter: the envelope (json) every tool writes, of the
dashboards this build may put in a file.

A dashboard owns no child content — its ``definition`` is a presentation spec
naming where data lives, and the data itself belongs to the tools it points
at. So the envelope is the spec plus the canvas config, and nothing else: a
restored dashboard finds its data through the tools around it, exactly as the
original did. A dashboard installed from a built-in plug-in carries its
listing too, so a restore can re-resolve the definition from the catalog
instead of pinning the copy in the file.

Dashboards were excluded from export while the marketplace's definition format
was the only one in play. The rule that replaced the exclusion is narrower and
lives in ``export.provenance``: a dashboard built on a plug-in this build does
not ship is not ours to put in a file, while a hand-built one — the common
case — is ordinary content.

Access rule: READ on the dashboard (exporting is a formatted read), enforced
by the ``ToolExportAdapter.fetch`` seam at both count and build time, under
the caller's RLS session.

A dashboard built on a plug-in this build does not ship is refused: its
definition belongs to its publisher, and the way to have it somewhere else is
to install the plug-in there. ``adapters/backup`` leaves those out before they are
fetched, so a community's backup is not failed by one of them.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.dashboard import Dashboard
from app.services.export.adapters._common import ToolExportAdapter
from app.services.permissions import EXPORT_ACCESS


class DashboardAdapter(ToolExportAdapter):
    tool = Tool.dashboard
    # A dashboard is queries over the community it sits in, so a listing of one
    # previews on generated sample data rather than on anybody's results.
    example_is_generated = True

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        dashboard_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Dashboard:
        from app.services.export.provenance import builtin_listing_uids, is_exportable

        dashboard = await super().fetch(
            session, user, guild_id, dashboard_id, access=access
        )
        builtin = await builtin_listing_uids(session, [dashboard.listing_uid])
        if not is_exportable(dashboard.listing_uid, builtin):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ExportMessages.EXPORT_THIRD_PARTY_PLUGIN,
            )
        return dashboard

    async def initiative_ids(
        self, session: AsyncSession, initiative_id: int, /
    ) -> list[int]:
        """Only the dashboards built on this build's own plug-ins — the rest are
        left out by provenance."""
        from app.services.export.provenance import builtin_listing_uids, is_exportable

        rows = list(
            await session.exec(
                select(Dashboard.id, Dashboard.listing_uid)
                .where(*self.in_initiative(initiative_id))
                .order_by(Dashboard.id.asc())
            )
        )
        builtin = await builtin_listing_uids(session, [uid for _, uid in rows])
        return [did for did, uid in rows if is_exportable(uid, builtin)]

    def rows(self, dashboard: Dashboard, /) -> int:
        """A dashboard is worth its widgets: the definition is the size, and a
        canvas of eighty widgets is not the same export as a canvas of one."""
        widgets = (dashboard.definition or {}).get("widgets")
        return max(1, len(widgets) if isinstance(widgets, list) else 1)
