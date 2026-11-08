"""``initiative-dashboard`` importer: the presentation spec, its canvas, and
its tags.

A dashboard owns no child content — the data it shows is fetched per viewer
through the tools it points at — so applying one is creating a single row.
What it does need is the definition and config put back through
``normalize_dashboard_definition`` and ``normalize_dashboard_config``: an
envelope is a file, and a file is not a trusted source. Those are the same
validators the create endpoint runs, so an imported dashboard cannot describe a
widget the app has no renderer for.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import DashboardEnvelope
from app.services.import_engine.common import unique_name_in_initiative
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.import_engine.references import note_or_settle


class DashboardImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.dashboard)
    permission = PermissionKey(Tool.dashboard.create_permission)

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(DashboardEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: DashboardEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        widgets = (envelope.definition or {}).get("widgets")
        return 1 + (len(widgets) if isinstance(widgets, list) else 0)

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: DashboardEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model

        definition, config = _normalized_canvas(env.definition, env.config)
        listing_uid, listing_version = await _resolved_listing(
            session, env.listing_uid, env.listing_version
        )

        dashboard = Dashboard(
            name=await unique_name_in_initiative(
                session, Dashboard, target_initiative.id, env.name
            ),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
            definition=definition,
            config=config,
            listing_uid=listing_uid,
            listing_version=listing_version,
        )
        session.add(dashboard)
        await session.flush()
        # Its statements name rows as they were numbered where it was exported.
        dashboard.definition = note_or_settle(
            context, SearchEntityType.dashboard, dashboard.id, definition
        )

        await grant_ownership(
            session,
            tool=Tool.dashboard,
            entity_id=dashboard.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(dashboard, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(dashboard, env.properties)
        return EnvelopeImportResult(
            entity_id=dashboard.id,
            entity_title=dashboard.name,
            created={
                Tool.dashboard.plural: 1,
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            unmatched_handles=await props.settle(dashboard),
        )


def _normalized_canvas(
    raw_definition: dict[str, Any] | None, raw_config: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The envelope's definition and config, through the app's own validators.

    A definition naming a widget or binding this build has no renderer for —
    an archive from a newer version, or one that referenced a plug-in that is not
    installed here — yields an empty canvas rather than failing the whole
    import: the dashboard arrives, empty, for somebody to rebuild, which is
    more use than losing it and everything queued behind it. A widget's config
    the definition does not accept is dropped the same way, one widget at a
    time.
    """
    from app.services.tenant.dashboard_definition import (
        DashboardDefinitionError,
        normalize_dashboard_config,
        normalize_dashboard_definition,
    )

    try:
        definition = normalize_dashboard_definition(raw_definition or {})
    except DashboardDefinitionError:
        definition = normalize_dashboard_definition({})
    # Each widget's settings stand alone: one the definition refuses is
    # dropped without taking the other widgets' settings with it.
    raw_widgets = (raw_config or {}).get("widgets")
    widgets: dict[str, Any] = {}
    for widget_id, values in (
        raw_widgets.items() if isinstance(raw_widgets, dict) else ()
    ):
        try:
            widgets.update(
                normalize_dashboard_config(
                    {"widgets": {widget_id: values}}, definition
                )["widgets"]
            )
        except DashboardDefinitionError:
            continue
    return definition, {"widgets": widgets}


async def _resolved_listing(
    session: AsyncSession, listing_uid: str | None, listing_version: str | None
) -> tuple[str | None, str | None]:
    """Keep the plug-in reference only when this deployment ships that listing;
    otherwise the dashboard arrives as an ordinary one rather than pointing at
    a listing that is not here."""
    if not listing_uid:
        return None, None
    from app.services.export.provenance import builtin_listing_uids

    if listing_uid in await builtin_listing_uids(session, [listing_uid]):
        return listing_uid, listing_version
    return None, None
