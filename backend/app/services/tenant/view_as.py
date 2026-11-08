"""A dashboard that runs as its initiative.

A tile ordinarily answers from whoever is looking at it. A dashboard can
instead run as its initiative (``Dashboard.view_mode == "initiative"``): its
query widgets then read with full read access to the dashboard's initiative,
the same for everybody who can open it. It is the dashboard's access, not any
one person's, so it does not change with who turned it on.

What that access is, precisely: the reader's own routed context with two
things added for that one initiative — "Full access" (the sharing override a
role can hold) and every tool's view permission. Everything else still holds:

* the dashboard's own gates decide who can open it at all, before this runs;
* the statement runs on the query role, which holds ``SELECT`` and nothing
  more, in a read-only transaction;
* it is narrowed to the dashboard's initiative, and a tool the initiative has
  switched off stays off;
* what runs is the statement stored on the widget, never one a reader sends.

Who may turn it on, and who may change the widgets while it is on, is an
initiative role permission (``dashboards_run_as_initiative``) that managers
always hold: :func:`may_run_as_initiative`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.core.tools import Tool
from app.db.guild_standing import GuildContext
from app.db.request_context import QUERYABLE
from app.models.tenant.dashboard import Dashboard, DashboardViewMode

#: The role key that lets a role set a dashboard to run as its initiative.
PERMISSION_KEY = "dashboards_run_as_initiative"


def runs_as_initiative(dashboard: Dashboard) -> bool:
    return dashboard.view_mode == DashboardViewMode.initiative.value


def may_run_as_initiative(context: GuildContext, initiative_id: int) -> bool:
    """Whether this reader may set a dashboard in *initiative_id* to run as
    the initiative, or change one that does. A community admin and the
    initiative's managers always may; anyone else needs the role permission."""
    return bool(
        context.is_admin
        or initiative_id in context.manager_initiatives
        or f"{initiative_id}:{PERMISSION_KEY}" in context.role_grants
    )


def initiative_context(dashboard: Dashboard, routed: Any) -> Any | None:
    """The context this dashboard's statements run as, or ``None`` to run as
    the reader.

    *routed* is the reader's own context, as the request established it.
    """
    if not runs_as_initiative(dashboard):
        return None
    if not isinstance(routed, QUERYABLE):
        return None
    standing = routed.standing
    if standing is None:
        return None
    initiative_id = dashboard.initiative_id
    widened = replace(
        standing,
        override_initiatives=tuple(
            sorted({*standing.override_initiatives, initiative_id})
        ),
        role_grants=tuple(
            sorted(
                {
                    *standing.role_grants,
                    *(f"{initiative_id}:{tool.view_permission}" for tool in Tool),
                }
            )
        ),
    )
    return replace(routed, standing=widened)
