"""A dashboard's statements, brought in by an import, name the rows the import
made rather than the ids they had where they were exported."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.references import format_ref
from app.core.search import SearchEntityType
from app.models.tenant.dashboard import Dashboard
from app.schemas.tenant.import_envelopes import DashboardEnvelope
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers.dashboard import DashboardImporter
from app.services.import_engine.references import resolve_references
from app.testing import create_guild, create_initiative, create_project, create_user
from app.testing.routing import route_as

_STATEMENTS = (
    "SELECT title FROM tasks WHERE project_id IN (12, 13) AND created_by = 12 -- by id",
    "SELECT count(*) AS n FROM sheet(42, 'Q3!A1:D')",
)


async def _imported(
    session: AsyncSession, context: ImportContext, initiative, owner
) -> list[str]:
    envelope = DashboardEnvelope(
        type="initiative-dashboard",
        name="Canvas",
        definition={
            "widgets": [
                {
                    "id": f"w{n}",
                    "type": "table",
                    "binding": {"source": "query", "sql": sql},
                }
                for n, sql in enumerate(_STATEMENTS)
            ]
        },
    )
    result = await DashboardImporter().apply(
        session,
        envelope=envelope,
        target_initiative=initiative,
        importer=owner,
        context=context,
    )
    await resolve_references(session, context, author_id=owner.id)
    dashboard = await session.get(Dashboard, result.entity_id)
    return [widget["binding"]["sql"] for widget in dashboard.definition["widgets"]]


async def test_a_statement_names_the_rows_the_import_made(session: AsyncSession):
    """A row the import made takes its new id, a person keeps theirs, and a row
    it did not carry is named only where it still is: in the community it
    was exported from. Anywhere else it names nothing (``0``)."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    await route_as(session, user_id=owner.id, guild_id=guild.id)

    elsewhere = ImportContext()
    elsewhere.links.register(
        format_ref(SearchEntityType.project, 12), SearchEntityType.project, project.id
    )
    assert await _imported(session, elsewhere, initiative, owner) == [
        (
            f"SELECT title FROM tasks WHERE project_id IN ({project.id}, 0) "
            "AND created_by = 12 -- by id"
        ),
        "SELECT count(*) AS n FROM sheet(0, 'Q3!A1:D')",
    ]

    here = ImportContext(same_community=True)
    assert (await _imported(session, here, initiative, owner))[1] == _STATEMENTS[1]
