"""Communities divided into cohorts, and a request, a system and a query pool
for each.

A database connection keeps the catalog of every table it has opened for as
long as it lives, and each community is a schema of its own, so a connection
that has served every community holds every community's catalog. Dividing the
communities into ``DB_COHORTS`` cohorts, and serving each cohort from pools of
its own, means a connection only ever opens its own cohort's schemas.

:func:`cohort_of` is the one place that says which cohort a community is in.
Everything else asks it.

With one cohort (the default) there is nothing to divide: requests draw from
the one request pool, ``app.db.session.AsyncSessionLocal``, system work from
the one system pool, ``app.db.session.SystemSessionLocal``, and reader-written
SQL from ``app.db.session.query_engine``, as they always have, and nothing in
this module is built.

What a session routes into is noted on the connection it runs on
(:func:`note_route`), so a connection that serves a community outside its
cohort is counted, and in the test suite refused.

Work in a community that follows a write in ``public`` runs after that write
commits, on a session from the community's cohort, registered with
:func:`app.db.post_commit.after_commit`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import metrics
from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

#: The tag on a connection from the request pool that serves no community's
#: schema.
PLATFORM = "platform"

#: The tag on a connection from the system pool that names no community. Its
#: routes into a community are counted but never refused (see
#: :func:`note_route`).
PLATFORM_SYSTEM = "platform-system"

#: Where a pooled connection keeps its cohort, and the communities it has
#: served. On the pool's record, so both last as long as the connection does.
_COHORT_KEY = "initiative_cohort"
_SERVED_KEY = "initiative_cohort_served"

#: Marks a session handed out by the request path or by
#: :func:`system_session`, with which of the two it is. Work across communities
#: made on a marked session gives each community a session of the same kind
#: from its own cohort.
_KIND_KEY = "cohort_session_kind"
_REQUEST = "request"
_SYSTEM = "system"

#: Marks a session whose transactions are opened read-only.
READ_ONLY_INFO_KEY = "cohort_read_only"

#: The test suite sets this, so a route outside the connection's cohort raises
#: rather than being counted.
STRICT = False

#: Each cohort's request sessionmaker, built on first use.
_request_makers: list[async_sessionmaker[AsyncSession]] | None = None

#: Each cohort's system sessionmaker, built on first use.
_system_makers: list[async_sessionmaker[AsyncSession]] | None = None

#: Each cohort's sessionmaker on DATABASE_URL_QUERY, built on first use.
_read_makers: list[async_sessionmaker[AsyncSession]] | None = None

#: Each cohort's sessionmaker for reader-written SQL, built on first use.
_query_makers: list[async_sessionmaker[AsyncSession]] | None = None


class CrossCohortRoute(RuntimeError):
    """A connection was routed into a community outside its cohort."""


def cohort_count() -> int:
    return settings.DB_COHORTS


def cohort_of(guild_id: int) -> int:
    """The cohort ``guild_id`` belongs to."""
    return int(guild_id) % cohort_count()


def cohort_url(url: str, cohort: int) -> str:
    """``url`` with the database ``DB_COHORT_DATABASE`` names for ``cohort``."""
    template = settings.DB_COHORT_DATABASE
    if not template:
        return url
    return (
        make_url(url)
        .set(database=template.format(cohort=cohort))
        .render_as_string(hide_password=False)
    )


def _served(record_info: dict[str, Any]) -> set[int]:
    return record_info.setdefault(_SERVED_KEY, set())


def tag_engine(engine: AsyncEngine, tag: int | str) -> None:
    """Mark every connection ``engine`` opens as belonging to ``tag``, and
    report how many communities each one served when it closes."""
    label = str(tag)
    communities = metrics.db_connection_communities.labels(cohort=label)

    def connected(_dbapi_connection: Any, record: Any) -> None:
        record.info[_COHORT_KEY] = tag

    def closed(_dbapi_connection: Any, record: Any) -> None:
        served = record.info.get(_SERVED_KEY)
        if served:
            communities.observe(len(served))

    event.listen(engine.sync_engine, "connect", connected)
    event.listen(engine.sync_engine, "close", closed)


def _build_makers(
    url: str, label: str, *, log_text: bool = True, **pool: Any
) -> list[async_sessionmaker[AsyncSession]]:
    """A sessionmaker per cohort on ``url``. ``pool`` sizes each cohort's pool,
    ``DB_POOL_SIZE`` and ``DB_MAX_OVERFLOW`` unless it says otherwise."""
    from app.db.session import instrument_engine, prepare_query_engine

    pool.setdefault("pool_size", settings.DB_POOL_SIZE)
    pool.setdefault("max_overflow", settings.DB_MAX_OVERFLOW)
    makers = []
    divided = cohort_count() > 1
    for cohort in range(cohort_count()):
        engine = create_async_engine(
            cohort_url(url, cohort) if divided else url,
            echo=False,
            hide_parameters=True,
            pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
            **pool,
        )
        instrument_engine(
            engine, f"{label}/{cohort}" if divided else label, log_text=log_text
        )
        if label == "query":
            prepare_query_engine(engine)
        if divided:
            tag_engine(engine, cohort)
        makers.append(_sessionmaker(engine))
    return makers


def _sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )


def _cohort_makers(
    engines: list[AsyncEngine],
) -> list[async_sessionmaker[AsyncSession]]:
    for cohort, engine in enumerate(engines):
        tag_engine(engine, cohort)
    return [_sessionmaker(engine) for engine in engines]


def use_request_engines(engines: list[AsyncEngine]) -> None:
    """Serve the cohorts' requests from ``engines``, one per cohort in order.
    For the test suite, which points every pool at its own database."""
    global _request_makers
    _request_makers = _cohort_makers(engines)


def use_system_engines(engines: list[AsyncEngine]) -> None:
    """Serve the cohorts' system work from ``engines``, one per cohort in
    order. For the test suite, as :func:`use_request_engines`."""
    global _system_makers
    _system_makers = _cohort_makers(engines)


def use_query_engines(engines: list[AsyncEngine]) -> None:
    """Serve the cohorts' reader-written SQL from ``engines``, one per cohort
    in order. For the test suite, as :func:`use_request_engines`."""
    global _query_makers
    _query_makers = _cohort_makers(engines)


def request_sessionmaker(guild_id: int | None) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker for request-path work in ``guild_id``'s community, or
    for work that names no community when it is ``None``."""
    global _request_makers
    # Looked up on the module rather than bound at import, so the test
    # harness's binding of the request pool applies here too.
    from app.db import session as db_session

    if guild_id is None or cohort_count() == 1:
        return db_session.AsyncSessionLocal
    if _request_makers is None:
        _request_makers = _build_makers(settings.DATABASE_URL_APP, "request")
    return _request_makers[cohort_of(guild_id)]


def system_sessionmaker(guild_id: int | None) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker for system work in ``guild_id``'s community, or for
    system work that names no community when it is ``None``."""
    global _system_makers
    # Looked up on the module, as in ``request_sessionmaker``.
    from app.db import session as db_session

    if guild_id is None or cohort_count() == 1:
        return db_session.SystemSessionLocal
    if _system_makers is None:
        _system_makers = _build_makers(settings.DATABASE_URL_ADMIN, "system")
    return _system_makers[cohort_of(guild_id)]


@asynccontextmanager
async def system_session(guild_id: int | None) -> AsyncIterator[AsyncSession]:
    """A system session from ``guild_id``'s cohort, or from the platform system
    pool when it is ``None``. The caller routes it and commits. Work across
    communities made on it gives each community a system session from that
    community's cohort."""
    async with system_sessionmaker(guild_id)() as session:
        mark_system_session(session)
        yield session


@asynccontextmanager
async def as_system(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """``session`` when it already works in its community as the platform, else
    a session routed there as the platform, committed on the way out. For the
    cleanup a person's or an installed plug-in's request makes of rows that
    are other members' alone.

    The work is a transaction of its own, so it must not touch a row the
    caller's transaction has already written."""
    from app.db.request_context import SystemGuild
    from app.db.session import guild_context, install_context, set_rls_context

    context = guild_context(session) or install_context(session)
    if context is None:
        yield session
        return
    async with system_session(context.guild_id) as system:
        await set_rls_context(system, SystemGuild(context.guild_id))
        yield system
        await system.commit()


async def exec_as_system(session: AsyncSession, statement: Any) -> None:
    """Run ``statement`` in ``session``'s community as the platform
    (:func:`as_system`)."""
    async with as_system(session) as system:
        await system.exec(statement)


def read_sessionmaker(guild_id: int) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker for background reads in ``guild_id``'s community that
    may trail the primary by a moment: on DATABASE_URL_QUERY when it is set,
    from the community's cohort, and otherwise the community's system pool, so
    background work never draws on the request path's."""
    global _read_makers
    if not settings.DATABASE_URL_QUERY:
        return system_sessionmaker(guild_id)
    if _read_makers is None:
        _read_makers = _build_makers(settings.DATABASE_URL_QUERY, "read")
    return _read_makers[cohort_of(guild_id)]


@asynccontextmanager
async def read_session(guild_id: int) -> AsyncIterator[AsyncSession]:
    """A read-only session from :func:`read_sessionmaker`."""
    async with read_sessionmaker(guild_id)() as session:
        if not settings.DATABASE_URL_QUERY:
            mark_system_session(session)
        session.info[READ_ONLY_INFO_KEY] = True
        yield session


def query_sessionmaker(guild_id: int) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker for reader-written SQL in ``guild_id``'s community:
    each cohort has a pool of ``QUERY_POOL_SIZE`` of its own, on
    DATABASE_URL_QUERY when it is set."""
    global _query_makers
    # Looked up on the module, as in ``request_sessionmaker``.
    from app.db import session as db_session

    if cohort_count() == 1:
        return _sessionmaker(db_session.query_engine)
    if _query_makers is None:
        _query_makers = _build_makers(
            settings.DATABASE_URL_QUERY or settings.DATABASE_URL_APP,
            "query",
            # What a reader writes is theirs, so its text stays out of the log.
            log_text=False,
            pool_size=db_session.QUERY_POOL_SIZE,
            max_overflow=0,
            pool_timeout=db_session.QUERY_POOL_TIMEOUT_SECONDS,
        )
    return _query_makers[cohort_of(guild_id)]


def addressed_guild_id(path_params: Mapping[str, Any]) -> int | None:
    """The community a request's path addresses, if it addresses one."""
    raw = path_params.get("community_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def mark_request_session(session: AsyncSession) -> None:
    session.info[_KIND_KEY] = _REQUEST


def is_request_session(session: AsyncSession) -> bool:
    """Whether ``session`` was handed out by the request path."""
    return session.info.get(_KIND_KEY) == _REQUEST


def mark_system_session(session: AsyncSession) -> None:
    session.info[_KIND_KEY] = _SYSTEM


@asynccontextmanager
async def community_session(
    parent: AsyncSession, guild_id: int, *, read_only: bool = True
) -> AsyncIterator[AsyncSession]:
    """A session from ``guild_id``'s cohort of the same kind as ``parent``, for
    one community's part of work across several. ``parent`` is a request-path
    session or one from :func:`system_session`. Read-only unless ``read_only``
    is False, in which case the caller commits what it wrote."""
    kind = parent.info.get(_KIND_KEY)
    if kind is None:
        raise TypeError(
            "work across communities needs a request-path session or one from "
            "cohorts.system_session"
        )
    maker = system_sessionmaker if kind == _SYSTEM else request_sessionmaker
    async with maker(guild_id)() as session:
        session.info[_KIND_KEY] = kind
        if read_only:
            session.info[READ_ONLY_INFO_KEY] = True
        yield session


def note_route(connection: Connection | None, guild_id: int | None) -> None:
    """Record that ``connection`` is serving ``guild_id``'s community, and
    count it when that community is outside the connection's cohort.

    Every tagged pool is held to its cohort the same way, and the platform
    pools belong to none. Under :data:`STRICT` a route outside the cohort
    raises."""
    if connection is None or guild_id is None:
        return
    info = connection.info
    tag = info.get(_COHORT_KEY)
    if tag is None:
        return
    _served(info).add(guild_id)
    if tag == cohort_of(guild_id):
        return
    metrics.db_cross_cohort_routes.labels(cohort=str(tag)).inc()
    if STRICT:
        raise CrossCohortRoute(
            f"a connection from the {tag!s} pool was routed into community "
            f"{guild_id}, which is in cohort {cohort_of(guild_id)}"
        )
