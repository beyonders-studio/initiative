"""Guild search can use its index.

Search matches through ``public.@@@`` and an index built on its operator class.
Where those are absent it falls back to the stock operator: same rows, more of
the table read, and nothing else would report it.

These assert the pieces that keep that from happening unnoticed — the objects
exist, the guild index is built on the operator class, the query layer picks it,
and installing the objects late still reaches indexes built without them.
Infrastructure installs them (``app.db.bootstrap``); ``conftest`` runs that
same module for the suite.
"""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql

from app.db import schema_provisioning
from app.db.schema_provisioning import SEARCH_MATCH_FUNCTION, SEARCH_OPCLASS
from app.models.platform.guild import CommunityRole
from app.models.tenant.search_entry import SearchEntry
from app.services.tenant.search import search_match_clause


async def test_the_match_function_is_installed_and_marked(session):
    row = (
        await session.exec(
            text(
                "SELECT p.proleakproof, p.prolang::regprocedure IS NOT NULL AS ok "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname = :match_fn"
            ).bindparams(match_fn=SEARCH_MATCH_FUNCTION)
        )
    ).first()
    assert row is not None, (
        f"public.{SEARCH_MATCH_FUNCTION} is missing — the bootstrap did not install it"
    )
    assert row[0] is True, "the match function is not marked LEAKPROOF"


async def test_the_operator_class_is_installed(session):
    present = (
        await session.exec(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_opclass c "
                "JOIN pg_namespace n ON n.oid = c.opcnamespace "
                "WHERE n.nspname = 'public' AND c.opcname = :o)"
            ).bindparams(o=SEARCH_OPCLASS)
        )
    ).one()
    assert present[0], f"public.{SEARCH_OPCLASS} is missing"


async def test_the_stock_operator_is_left_alone(session):
    """Only our operator carries the marking; pg_catalog is untouched, so every
    other table and application on the cluster is unaffected."""
    leakproof = (
        await session.exec(
            text("SELECT proleakproof FROM pg_proc WHERE proname = 'ts_match_vq'")
        )
    ).one()
    assert leakproof[0] is False


async def test_the_guild_index_is_built_against_the_operator_class(
    session, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin)
    definition = (
        await session.exec(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s AND indexname = 'ix_search_entries_tsv'"
            ).bindparams(s=f"guild_{a.guild.id}")
        )
    ).one()
    assert SEARCH_OPCLASS in definition[0], (
        f"the search index is not using {SEARCH_OPCLASS}: {definition[0]}"
    )


async def test_readiness_is_detected(session):
    assert await schema_provisioning.search_operator_ready() is True
    assert schema_provisioning.search_operator_available() is True


def test_the_query_layer_picks_the_installed_operator(monkeypatch):
    """And falls back to the stock one rather than failing when it is absent."""
    query = func.websearch_to_tsquery("simple", "vendor")

    def rendered(available: bool) -> str:
        monkeypatch.setattr(
            schema_provisioning, "_search_operator_ready", available, raising=False
        )
        statement = select(SearchEntry.entity_id).where(search_match_clause(query))
        return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())

    assert "OPERATOR(public.@@@)" in rendered(True)
    assert "OPERATOR(public.@@@)" not in rendered(False)
    assert "tsv @@ websearch_to_tsquery" in rendered(False)


async def test_an_index_built_without_the_operator_is_rebuilt_later(
    session, acting_user
):
    """The supported upgrade order: install the app first, the operator after.

    The migration builds the index on the stock class when the objects are
    absent. Installing them later has to reach those existing indexes, or the
    query layer would switch operators while every guild kept an index that
    cannot serve them.
    """
    from sqlalchemy import text as sa_text

    from app.db.schema_provisioning import apply_guild_search

    a = await acting_user(guild_role=CommunityRole.admin)
    schema = f"guild_{a.guild.id}"

    async def index_def() -> str:
        return (
            await session.exec(
                sa_text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = :s AND indexname = 'ix_search_entries_tsv'"
                ).bindparams(s=schema)
            )
        ).one()[0]

    # Simulate the fallback path: an index on the stock operator class.
    await session.exec(
        sa_text(f'DROP INDEX IF EXISTS "{schema}".ix_search_entries_tsv')
    )
    await session.exec(
        sa_text(
            f'CREATE INDEX ix_search_entries_tsv ON "{schema}".search_entries '
            "USING gin (tsv)"
        )
    )
    await session.commit()
    assert SEARCH_OPCLASS not in await index_def()

    # Provisioning re-asserts it, which is what the stamp change triggers.
    schema_provisioning.reset_provisioning_bundle()
    async with schema_provisioning.db_session.provisioning_engine.begin() as conn:
        await apply_guild_search(conn, schema)

    assert SEARCH_OPCLASS in await index_def(), (
        "installing the operator did not reach an index built without it"
    )
