"""Which pool a community's requests and system work draw from.

The suite runs with two cohorts (``conftest._TEST_COHORTS``), each with a
request and a system pool on the worker's database, and with a route outside a
connection's cohort refused rather than counted.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import HTTPConnection

from app.core.config import Settings, settings
from app.db import cohorts
from app.db import session as db_session
from app.db.request_context import SystemGuild
from app.db.session import get_session, set_rls_context
from app.services.cross_guild import gather_across_guilds
from app.testing import create_guild, create_user, platform_session


def _connection(path_params: dict[str, str]) -> HTTPConnection:
    return HTTPConnection({"type": "http", "path_params": path_params, "headers": []})


def test_a_community_is_in_the_cohort_its_id_leaves_over(monkeypatch):
    monkeypatch.setattr(settings, "DB_COHORTS", 3)
    assert [cohorts.cohort_of(g) for g in (3, 4, 5, 6)] == [0, 1, 2, 0]


def test_the_database_template_names_each_cohorts_database(monkeypatch):
    url = "postgresql+asyncpg://app_user:pw@db:6432/initiative"
    assert cohorts.cohort_url(url, 2) == url
    monkeypatch.setattr(settings, "DB_COHORT_DATABASE", "initiative_c{cohort}")
    assert cohorts.cohort_url(url, 2) == (
        "postgresql+asyncpg://app_user:pw@db:6432/initiative_c2"
    )


@pytest.mark.parametrize(
    "template", ["initiative", "initiative_{shard}", "initiative_{cohort}_{0}"]
)
def test_a_database_template_must_name_the_cohort_and_nothing_else(template):
    with pytest.raises(ValueError, match="DB_COHORT_DATABASE"):
        Settings.model_validate(
            {**settings.model_dump(), "DB_COHORT_DATABASE": template}
        )


def test_the_path_addresses_a_community_only_by_number():
    assert cohorts.addressed_guild_id({"community_id": "12"}) == 12
    assert cohorts.addressed_guild_id({"community_id": "a-reference"}) is None
    assert cohorts.addressed_guild_id({}) is None


def test_one_cohort_is_the_one_request_pool(monkeypatch):
    monkeypatch.setattr(settings, "DB_COHORTS", 1)
    assert cohorts.request_sessionmaker(7) is db_session.AsyncSessionLocal
    assert cohorts.request_sessionmaker(None) is db_session.AsyncSessionLocal


async def _bind_for(path_params: dict[str, str]):
    sessions = get_session(_connection(path_params))
    session = await anext(sessions)
    try:
        return session.bind, cohorts._KIND_KEY in session.info
    finally:
        await sessions.aclose()


async def test_a_request_draws_from_the_cohort_its_path_addresses():
    bind, marked = await _bind_for({"community_id": "5"})
    assert bind is cohorts.request_sessionmaker(5).kw["bind"]
    assert bind is not cohorts.request_sessionmaker(4).kw["bind"]
    assert marked

    bind, _ = await _bind_for({})
    assert bind is db_session.AsyncSessionLocal.kw["bind"]


async def test_a_route_outside_the_connections_cohort_is_refused(session):
    guild = await create_guild(session)
    other_cohort = guild.id + 1
    assert cohorts.cohort_of(other_cohort) != cohorts.cohort_of(guild.id)

    async with cohorts.request_sessionmaker(guild.id)() as own:
        await set_rls_context(own, SystemGuild(guild.id))
        assert (await own.exec(text("SELECT 1"))).one()[0] == 1

    async with cohorts.request_sessionmaker(other_cohort)() as elsewhere:
        await set_rls_context(elsewhere, SystemGuild(guild.id))
        with pytest.raises(cohorts.CrossCohortRoute):
            await elsewhere.exec(text("SELECT 1"))


async def test_a_system_session_routes_only_into_its_own_cohort(session):
    guild = await create_guild(session)
    other_cohort = guild.id + 1

    async with cohorts.system_session(guild.id) as own:
        assert own.bind is cohorts.system_sessionmaker(guild.id).kw["bind"]
        assert own.bind is not cohorts.request_sessionmaker(guild.id).kw["bind"]
        await set_rls_context(own, SystemGuild(guild.id))
        connection = await own.connection()
        assert connection.info["initiative_cohort"] == cohorts.cohort_of(guild.id)
        assert (await own.exec(text("SELECT 1"))).one()[0] == 1

    async with cohorts.system_session(other_cohort) as elsewhere:
        await set_rls_context(elsewhere, SystemGuild(guild.id))
        with pytest.raises(cohorts.CrossCohortRoute):
            await elsewhere.exec(text("SELECT 1"))


async def test_the_platform_system_pool_is_refused_in_a_community(session):
    guild = await create_guild(session)
    async with db_session.SystemSessionLocal() as system:
        with pytest.raises(cohorts.CrossCohortRoute):
            await set_rls_context(system, SystemGuild(guild.id))
            await system.exec(text("SELECT 1"))


async def test_a_community_session_only_reads(session):
    guild = await create_guild(session)
    async with (
        cohorts.system_session(None) as parent,
        cohorts.community_session(parent, guild.id) as routed,
    ):
        read_only = (await routed.exec(text("SHOW transaction_read_only"))).one()[0]
    assert read_only == "on"


@pytest.mark.parametrize("kind", ["request", "system"])
async def test_a_read_across_communities_reads_each_from_its_own_cohort(session, kind):
    user = await create_user(session)
    first = await create_guild(session, creator=user)
    second = await create_guild(session, creator=user)
    assert cohorts.cohort_of(first.id) != cohorts.cohort_of(second.id)
    if kind == "request":
        opened, maker = platform_session(user), cohorts.request_sessionmaker
    else:
        opened, maker = cohorts.system_session(None), cohorts.system_sessionmaker

    seen: list[tuple[int, object, bool]] = []

    async with opened as parent:

        async def fetch(routed: AsyncSession, guild_id: int) -> list[int]:
            assert routed.bind is maker(guild_id).kw["bind"]
            connection = await routed.connection()
            seen.append(
                (guild_id, connection.info.get("initiative_cohort"), routed is parent)
            )
            count = (await routed.exec(text("SELECT count(*) FROM initiatives"))).one()
            return [int(count[0])]

        results = await gather_across_guilds(
            parent, {user.id: [first.id, second.id]}, fetch
        )

    assert len(results) == 2
    assert seen == [
        (first.id, cohorts.cohort_of(first.id), False),
        (second.id, cohorts.cohort_of(second.id), False),
    ]


async def test_reads_that_may_trail_use_the_system_pool_without_a_replica():
    assert settings.DATABASE_URL_QUERY is None
    assert cohorts.read_sessionmaker(5) is cohorts.system_sessionmaker(5)
    async with cohorts.read_session(5) as reading:
        assert reading.info[cohorts.READ_ONLY_INFO_KEY] is True
        assert not cohorts.is_request_session(reading)


@pytest.mark.parametrize(
    ("makers", "sessionmaker", "pool_size"),
    [
        ("_read_makers", cohorts.read_sessionmaker, settings.DB_POOL_SIZE),
        ("_query_makers", cohorts.query_sessionmaker, db_session.QUERY_POOL_SIZE),
    ],
)
async def test_reads_that_may_trail_use_the_replica_when_there_is_one(
    monkeypatch, makers, sessionmaker, pool_size
):
    replica = "postgresql+asyncpg://app_user:pw@replica:5432/initiative"
    monkeypatch.setattr(settings, "DATABASE_URL_QUERY", replica)
    monkeypatch.setattr(settings, "DB_COHORT_DATABASE", "initiative_c{cohort}")
    monkeypatch.setattr(cohorts, makers, None)

    engines = [sessionmaker(g).kw["bind"] for g in (4, 5)]
    try:
        assert [e.url.host for e in engines] == ["replica", "replica"]
        assert [e.url.database for e in engines] == [
            f"initiative_c{cohorts.cohort_of(4)}",
            f"initiative_c{cohorts.cohort_of(5)}",
        ]
        assert [e.pool.size() for e in engines] == [pool_size, pool_size]
    finally:
        for engine in engines:
            await engine.dispose()
