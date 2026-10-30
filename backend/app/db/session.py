import asyncio
import functools
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Sequence

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from asyncpg.exceptions import InvalidCatalogNameError
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import HTTPConnection

from app.core import metrics
from app.core.plugin_access_token import InstallAccessToken
from app.core.config import settings
from app.core.identify import bearer_plugin_token
from app.core.tools import Tool
from app.db import base  # noqa: F401  # ensure models are imported for Alembic
from app.db import cohorts, gucs, post_commit
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_standing import (
    GuildContext,
    InstallContext,
    compute_guild_standing,
    compute_install_standing,
)
from app.db.request_context import (
    ContentGrantee,
    ContextShapeError,
    Member,
    Platform,
    RequestContext,
    SettingsGrantee,
    SystemGuild,
    SystemMaintenance,
    Unattributed,
)
from app.models.tenant._mixins import tool_models

logger = logging.getLogger(__name__)

# Primary engine: non-superuser (DATABASE_URL_APP) for RLS-enforced queries.
# With DB_COHORTS above 1 this is the platform pool: requests that address no
# community. Each cohort's requests draw from a pool of their own
# (``app.db.cohorts``).
engine = create_async_engine(
    settings.DATABASE_URL_APP,
    echo=False,
    hide_parameters=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)

# System engine: background jobs, startup seeding, platform lifecycle.
# The textbook Postgres trusted-batch actor: BYPASSRLS, bounded by
# enumerated per-table GRANTs (migration 0129). Guild schemas still
# require SET ROLE guild_<id>, which drops the bypass. With DB_COHORTS above 1
# this is the platform system pool: system work in one community draws from
# that community's cohort (``app.db.cohorts.system_session``).
system_engine = create_async_engine(
    settings.DATABASE_URL_ADMIN,
    echo=False,
    hide_parameters=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)
_SYSTEM_LOGIN_ROLE, _ = settings.database_login("DATABASE_URL_ADMIN")

# Provisioning engine: superuser credentials (same as migrations) for privileged
# DDL — CREATE SCHEMA / CREATE ROLE — which app_user and app_admin can't do.
provisioning_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    hide_parameters=True,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)

#: Connections kept for reader-written SQL. Small on purpose: it is the bound
#: on how much of the database's attention those statements can hold.
QUERY_POOL_SIZE = 4
#: How long a query waits for one of them before giving up.
QUERY_POOL_TIMEOUT_SECONDS = 5

#: A pool of its own for reader-written SQL, so what those statements wait for
#: is each other rather than the requests serving every other page. Same login
#: as the request path — the difference is the role each statement assumes and
#: the transaction it runs in, not who connects. On a read replica when
#: DATABASE_URL_QUERY names one. With DB_COHORTS above 1 each cohort has a pool
#: of this size of its own (``app.db.cohorts.query_sessionmaker``).
query_engine = create_async_engine(
    settings.DATABASE_URL_QUERY or settings.DATABASE_URL_APP,
    echo=False,
    hide_parameters=True,
    pool_size=QUERY_POOL_SIZE,
    max_overflow=0,
    pool_timeout=QUERY_POOL_TIMEOUT_SECONDS,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)


def prepare_query_engine(target: AsyncEngine) -> AsyncEngine:
    """Ready a pool for reader-written SQL.

    Its statements run as the query role, which may not call ``set_config``
    (``app.db.bootstrap.ensure_set_config_narrowed``). asyncpg turns JIT off
    around its own type lookups with ``set_config`` whenever it believes the
    server has JIT; each connection here is told it has none, so a lookup made
    while the query role is current reads the catalog and nothing more. The
    executor turns JIT off for each transaction itself.
    """

    def no_jit(dbapi_connection, _record) -> None:
        raw = dbapi_connection.driver_connection
        raw._server_caps = raw._server_caps._replace(jit=False)

    event.listen(target.sync_engine, "connect", no_jit)
    return target


#: A statement that takes longer than this is logged with the request it served,
#: and counted. Half a second is also a common ``log_min_duration_statement``,
#: so this log and the database's own agree on what "slow" is.
SLOW_STATEMENT_SECONDS = 0.5

#: How much of a slow statement's text its log line keeps.
_SLOW_STATEMENT_TEXT_LIMIT = 2000

#: Where a statement's start time rides between the two cursor events.
_STARTED_AT = "_initiative_started_at"


def instrument_engine(
    target: AsyncEngine, label: str, *, flag_slow: bool = True, log_text: bool = True
) -> None:
    """Time every statement ``target`` runs, and report its pool.

    ``flag_slow`` logs and counts statements over :data:`SLOW_STATEMENT_SECONDS`;
    ``log_text`` puts the statement's text on that line. The text is the SQL
    as written, never the values bound into it.
    """
    metrics.watch_pool(label, target)
    duration = metrics.db_statement_duration.labels(engine=label)
    slow = metrics.db_slow_statements.labels(engine=label)

    def started(_conn, _cursor, _statement, _parameters, context, _executemany):
        setattr(context, _STARTED_AT, time.perf_counter())

    def finished(_conn, _cursor, statement, _parameters, context, _executemany):
        began = getattr(context, _STARTED_AT, None)
        if began is None:
            return
        elapsed = time.perf_counter() - began
        duration.observe(elapsed)
        if not flag_slow or elapsed < SLOW_STATEMENT_SECONDS:
            return
        slow.inc()
        written = ""
        if log_text:
            written = ": " + " ".join(statement.split())[:_SLOW_STATEMENT_TEXT_LIMIT]
        logger.warning(
            "Slow statement on the %s engine, %.0f ms%s",
            label,
            elapsed * 1000,
            written,
        )

    event.listen(target.sync_engine, "before_cursor_execute", started)
    event.listen(target.sync_engine, "after_cursor_execute", finished)


instrument_engine(engine, "request")
instrument_engine(system_engine, "system")
# Schema provisioning is DDL, which is expected to take its time.
instrument_engine(provisioning_engine, "provisioning", flag_slow=False)
# What a reader writes is theirs, so its text stays out of the log.
instrument_engine(query_engine, "query", log_text=False)
prepare_query_engine(query_engine)
if settings.DB_COHORTS > 1:
    cohorts.tag_engine(engine, cohorts.PLATFORM)
    cohorts.tag_engine(system_engine, cohorts.PLATFORM_SYSTEM)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

SystemSessionLocal = async_sessionmaker(
    bind=system_engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


def served_guild_id(connection: HTTPConnection) -> int | None:
    """The community a request is served in: the one its installation token
    names, when it carries one, and otherwise the one its path addresses.

    An installed plug-in's calls are about the community its token names, whatever
    the path says, so that community's cohort serves them."""
    token = bearer_plugin_token(connection)
    if isinstance(token, InstallAccessToken):
        return token.guild_id
    return cohorts.addressed_guild_id(connection.path_params)


async def get_session(
    connection: HTTPConnection,
) -> AsyncGenerator[AsyncSession, None]:
    # No checkout reset: context is transaction-local (set_config is_local +
    # SET LOCAL semantics), so a pooled connection carries NO role/GUC/
    # search_path state between transactions — there is nothing to clear.
    # The pool's rollback-on-return is the only baseline needed.
    #
    # The pool is chosen here, before the first statement, from the community
    # the request is served in: by the time the seam routes the session, the
    # credential and membership lookups have already begun a transaction on it.
    async with cohorts.request_sessionmaker(served_guild_id(connection))() as session:
        cohorts.mark_request_session(session)
        yield session


async def get_system_session(
    connection: HTTPConnection,
) -> AsyncGenerator[AsyncSession, None]:
    """Get a session on the system engine (background jobs, bootstrapping,
    platform lifecycle). ``app_admin`` is the standard Postgres trusted-batch
    actor — BYPASSRLS, bounded by enumerated per-table GRANTs (0129); guild
    schemas require ``SET ROLE guild_<id>`` (dropping the bypass) via
    set_rls_context(). Context is transaction-local, so a recycled pooled
    connection starts every session at the login-role/public baseline with
    no reset round-trip.

    Like ``get_session``, the session is from the cohort of the community the
    request is served in, and from the platform system pool when it names
    none."""
    async with cohorts.system_session(served_guild_id(connection)) as session:
        yield session


def clear_rls_context(session: AsyncSession) -> None:
    """Drop the session's stored context so no replay occurs.

    Production sessions are per-request and die with their context; a
    long-lived session that is REUSED across logical request boundaries (the
    test harness's connection-bound sessions) calls this at each boundary so
    the next transaction begins unrouted — fresh-session equivalence.
    """
    session.info.pop(_RLS_CONTEXT_INFO_KEY, None)
    session.info.pop(_RLS_ESTABLISHED_INFO_KEY, None)


# --- Transaction-local RLS context -----------------------------------------
#
# All request context (assumed role, search_path, app.* GUCs) is applied with
# set_config(..., is_local => true) — the SET LOCAL equivalent — so it DIES
# WITH THE TRANSACTION. Nothing session-level is ever set: a forgotten reset
# is unrepresentable, and the connection carries zero cross-transaction state
# (the property a transaction-mode pooler requires).
#
# The parameters live in session.info; the _replay_rls_context after_begin
# hook re-applies them at the start of EVERY transaction (autobegin after a
# commit() included), on whatever pooled connection the transaction landed on.

# Maximum age of a *user-derived* authorization snapshot. The stored context
# capture membership / guild role / PAM state as validated by
# establish_guild_access, so a snapshot older than this is refused rather than
# replayed. The socket register re-validates sockets every
# REAUTH_INTERVAL_SECONDS (= half this bound; content_sockets derives it from
# this constant), so any properly registered consumer refreshes long before the
# floor; a consumer that holds a routed session without re-validating reaches
# it and fails. System contexts (no user_id: workers, seeding) are not
# user-authorization snapshots and are exempt.
RLS_CONTEXT_MAX_AGE_SECONDS = 60

#: Where a session keeps the shape it was routed with (``app.db.request_context``).
_RLS_CONTEXT_INFO_KEY = "rls_context"
_RLS_ESTABLISHED_INFO_KEY = "rls_established_at"

# The platform tier this REQUEST authenticated as, held in the SQLAlchemy
# session's Python state — never on the connection. It is read only by
# set_rls_context, which resolves it into the stored context below; from there it
# reaches Postgres the same way every other value does, as a transaction-local
# set_config replayed per transaction. Nothing here survives a request, and
# nothing here is session state at the database.
_RLS_TIER_INFO_KEY = "rls_platform_tier"


class StaleAuthorizationContext(RuntimeError):
    """A transaction tried to begin on an authorization snapshot older than
    RLS_CONTEXT_MAX_AGE_SECONDS. Re-validate via establish_guild_access (or
    re-call set_rls_context with freshly validated inputs) instead of holding
    a routed session past the bound."""


def _search_path(*schemas: str) -> str:
    """The schemas a request resolves unqualified names against, in priority order.

    ``pg_temp`` is named explicitly, and last. Postgres searches it FIRST for
    relation names when it is left off the path, and the shared functions in
    ``public`` (``initiative_access``, ``capture_change``) resolve guild tables
    through whatever path their caller carries — that is what lets one
    definition serve every guild schema. Naming every schema here keeps their
    resolution a property of the route rather than of the connection.
    """
    return ", ".join((*schemas, "pg_temp"))


#: The whole of a routing, in one statement. It returns to the login role
#: first and assumes the routed role last, so a statement that fails part-way
#: leaves the transaction aborted on the login role, never wearing a stale
#: guild role. It writes every variable in ``app.db.gucs.REQUEST_GUCS``, so a
#: routing always states the standing too: nothing, until the statement that
#: computes it has run (``app.db.guild_standing``).
_CONTEXT_SQL = (
    "SELECT set_config('role', 'none', true), "
    + "".join(
        f"set_config('{guc.name}', :{guc.bind}, true), " for guc in gucs.REQUEST_GUCS
    )
    + "set_config('search_path', :search_path, true), "
    "set_config('role', :role, true)"
)


def _binds(
    values: dict[gucs.Guc, Any], *, search_path: str, role: str
) -> dict[str, str]:
    """The bind parameters for :data:`_CONTEXT_SQL`: each variable's value as
    its text, and empty where ``values`` names none."""
    return {
        **{guc.bind: guc.encode(values.get(guc)) for guc in gucs.REQUEST_GUCS},
        "search_path": search_path,
        "role": role,
    }


def _bind_params(context: RequestContext) -> dict[str, str]:
    """The bind parameters for :data:`_CONTEXT_SQL` that route ``context``.

    Pure, and shared by the async apply path and the sync replay hook — one
    routing decision, two executors.
    """
    route = context.route()
    return _binds(
        route.values, search_path=_search_path(*route.schemas), role=route.role
    )


def _replay_rls_context(session: SyncSession, transaction, connection) -> None:
    """after_begin hook: re-apply the session's stored context at the start of
    every transaction, so no query ever runs without it — regardless of
    commits or which pooled connection the transaction landed on."""
    if transaction.nested:
        # SET LOCAL scopes to the top-level transaction; savepoints inherit.
        return
    if session.info.get(cohorts.READ_ONLY_INFO_KEY):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    context = session.info.get(_RLS_CONTEXT_INFO_KEY)
    if context is None:
        return
    if context.attributed:
        established = session.info.get(_RLS_ESTABLISHED_INFO_KEY)
        if (
            established is None
            or time.monotonic() - established > RLS_CONTEXT_MAX_AGE_SECONDS
        ):
            raise StaleAuthorizationContext(
                "Authorization snapshot exceeded "
                f"{RLS_CONTEXT_MAX_AGE_SECONDS}s; re-validate via "
                "establish_guild_access before further queries."
            )
    cohorts.note_route(connection, context.guild_id)
    connection.execute(text(_CONTEXT_SQL), _bind_params(context))


# propagate=True so the hook also fires for SQLModel's Session subclass (the
# sync session under AsyncSession). Sessions without a stored context are a
# no-op, so the global listener is effectively scoped to routed sessions.
event.listen(SyncSession, "after_begin", _replay_rls_context, propagate=True)


@functools.cache
def _tool_of_model() -> dict[type, Tool]:
    models = tool_models()
    return {models[tool.plural]: tool for tool in Tool}


def _note_created_tools(session: SyncSession, _flush_context: Any) -> None:
    # ``session.new`` still lists what this flush inserted. Counted once the
    # transaction commits, and not if the savepoint it was flushed in rolls back.
    tool_of = _tool_of_model()
    created = [tool_of[type(row)] for row in session.new if type(row) in tool_of]
    if created:
        post_commit.after_commit(session, functools.partial(_count_tools, created))


def _count_tools(tools: list[Tool]) -> None:
    for tool in tools:
        metrics.tools_created.labels(tool=tool.value).inc()


event.listen(SyncSession, "after_flush", _note_created_tools, propagate=True)

#: The shapes that name a person, and so carry the tier the request
#: authenticated as.
_TIERED = (Platform, Member, ContentGrantee, SettingsGrantee)


async def set_rls_context(session: AsyncSession, context: RequestContext) -> None:
    """Route ``session`` as ``context`` — transaction-local.

    The shape is stored on the session and applied with ``set_config(...,
    true)``: it dies at COMMIT/ROLLBACK, and the ``_replay_rls_context``
    after_begin hook re-applies it on every new transaction. No session-level
    state ever exists on the connection, so pooled-connection staleness is
    unrepresentable and transaction-mode poolers are safe.

    Every variable in ``app.db.gucs.REQUEST_GUCS`` is written, empty where the
    shape says nothing, so values from a previous request on the same pooled
    connection can never reach this one.

    **The tier.** A shape that names a person but not their tier is this
    request re-establishing its own context — returning from a guild excursion,
    or narrowing after a lookup — not becoming somebody else, and it is given
    back the tier the request authenticated as. A shape with no person forgets
    it. The tier lives in the SQLAlchemy session's Python state, never on the
    connection.

    **The system shapes** route only on the system engine: a request-path
    session refuses them, and :class:`SystemMaintenance` also checks the
    connection's login, since it keeps that login's own grants.

    **This routes a session; it does not establish a request.** Resolving who
    somebody is in a community, and computing what that gives them, is the
    establishment seam's job (``app.api.deps.establish_guild_access``); the
    person and install shapes carry what it found. It touches no task-scoped
    state, which is what makes it safe on a second session while a request is
    being served.
    """
    if isinstance(context, (SystemGuild, SystemMaintenance)):
        if cohorts.is_request_session(session):
            raise ContextShapeError(
                "a system routing runs on the system engine, not a request session"
            )
        if isinstance(context, SystemMaintenance):
            is_system_login = (
                await session.exec(
                    text("SELECT session_user = :role"),
                    params={"role": _SYSTEM_LOGIN_ROLE},
                )
            ).one()[0]
            if not is_system_login:
                raise PermissionError(
                    "system guild routing requires the configured system login"
                )

    if isinstance(context, _TIERED):
        if context.tier is not None:
            session.info[_RLS_TIER_INFO_KEY] = context.tier
        elif (tier := session.info.get(_RLS_TIER_INFO_KEY)) is not None:
            context = replace(context, tier=tier)
    else:
        session.info.pop(_RLS_TIER_INFO_KEY, None)

    # Stored with its freshness stamp BEFORE any execute: an execute may
    # autobegin a transaction, firing the replay hook, which must see the new
    # context. The stamp only refreshes here — on a routing that carries
    # freshly validated inputs — never on replay.
    session.info[_RLS_CONTEXT_INFO_KEY] = context
    session.info[_RLS_ESTABLISHED_INFO_KEY] = time.monotonic()

    # Applied now only when a transaction is already open (a re-route mid
    # transaction, e.g. a cross-guild gather): there the hook has already
    # fired. On a fresh session the first statement autobegins and the hook
    # applies it.
    if session.in_transaction():
        await _apply_stored_context(session)


def routed_context(session: AsyncSession) -> RequestContext:
    """The shape this session was routed with.

    For a caller that needs a second session to see what this one sees — the
    query surface runs on a pool of its own — so there is one decision about
    who the request is rather than a second reading of it somewhere else.
    """
    context = session.info.get(_RLS_CONTEXT_INFO_KEY)
    if context is None:
        raise RuntimeError("no RLS context has been established on this session")
    return context


def _record_standing(session: AsyncSession, completed: Any) -> None:
    """Store a completed standing on the shape it completes."""
    context = session.info.get(_RLS_CONTEXT_INFO_KEY)
    if (
        getattr(context, "standing", None) is not None
        and context.guild_id == completed.guild_id
    ):
        session.info[_RLS_CONTEXT_INFO_KEY] = replace(context, standing=completed)


async def apply_guild_standing(
    session: AsyncSession, context: GuildContext
) -> GuildContext:
    """Compute this request's standing and record it on the session.

    The second half of the establishment seam: the routing has just written the
    community context and cleared every standing key, so what
    :data:`app.db.guild_standing.STANDING_SQL` writes is the whole of it. Its
    returned row completes ``context``, which replaces the one the stored shape
    carries, so the replay hook re-applies routing and standing together.
    """
    completed = context.with_standing(await compute_guild_standing(session))
    _record_standing(session, completed)
    return completed


async def apply_install_standing(
    session: AsyncSession,
    context: InstallContext,
    named_refs: Sequence[str] = (),
) -> InstallContext:
    """Compute an installed plug-in's standing and record it on the session.

    The second half of the install seam, as :func:`apply_guild_standing` is of
    the person seam. ``named_refs`` are the references the request names; the
    same statement resolves them in the install's own sector.
    """
    completed = context.with_standing(
        await compute_install_standing(session, named_refs)
    )
    _record_standing(session, completed)
    return completed


def routed_guild_id(session: AsyncSession) -> int | None:
    """The guild this session is currently routed to, or ``None`` if it is not.

    Ids of things that live in a guild schema — files, initiatives — are
    per-schema sequences, so the same number names a different row in each
    guild. Anything keyed by one of them outside the database needs the guild
    beside it, and where the id was read through a routed session, that routing
    is the answer.
    """
    context = session.info.get(_RLS_CONTEXT_INFO_KEY)
    return None if context is None else context.guild_id


def _standing(session: AsyncSession, kind: type) -> Any:
    """The standing the stored shape carries, when it is a ``kind`` computed
    for the community the session is routed to."""
    context = session.info.get(_RLS_CONTEXT_INFO_KEY)
    standing = getattr(context, "standing", None)
    if not isinstance(standing, kind):
        return None
    return standing if standing.guild_id == context.guild_id else None


def guild_context(session: AsyncSession) -> GuildContext | None:
    """The standing this session was routed with, or ``None``.

    The standing *is* part of the stored shape, so reading it here and reading
    the routed community are one lookup rather than two that can disagree.
    """
    return _standing(session, GuildContext)


def require_guild_context(session: AsyncSession) -> GuildContext:
    """The standing this session was routed with, for a caller that needs one.

    Raising beats deciding on a standing nobody computed: every leg of one
    answers no when it is missing, which reads as a refusal rather than as the
    missing routing it is.
    """
    context = guild_context(session)
    if context is None:
        raise RuntimeError(
            "no standing is recorded on this session; establish_guild_access "
            "must run before a decision is made from one"
        )
    return context


def install_context(session: AsyncSession) -> InstallContext | None:
    """The installed plug-in's standing this session was routed with, or ``None``."""
    return _standing(session, InstallContext)


def actor_context(session: AsyncSession) -> GuildContext | InstallContext | None:
    """The standing this session was routed with, a person's or an installed
    plug-in's, or ``None`` for the system's own reads."""
    return guild_context(session) or install_context(session)


def require_actor_context(session: AsyncSession) -> GuildContext | InstallContext:
    """The standing this session was routed with, a person's or an installed
    plug-in's, for a caller on a route that serves either."""
    context = guild_context(session) or install_context(session)
    if context is None:
        raise RuntimeError(
            "no standing is recorded on this session; the route's seam must run "
            "before a decision is made from one"
        )
    return context


async def raise_flag(session: AsyncSession, flag: gucs.Guc, value: Any = True) -> None:
    """Set one of :data:`app.db.gucs.FLAGS` for the current transaction.

    A flag is not part of the routing: it is raised inside the transaction that
    does the work, lasts until that transaction ends, and is never replayed.
    """
    if flag not in gucs.FLAGS:
        raise ValueError(f"{flag.name} is not a transaction flag")
    await session.exec(
        text("SELECT set_config(:name, :value, true)").bindparams(
            name=flag.name, value=flag.encode(value)
        )
    )


async def _apply_stored_context(session: AsyncSession) -> None:
    """Apply the session's stored context to the CURRENT transaction.

    Uses set_config() (a regular SQL function) instead of SET commands —
    set_config() is a standard SQL query guaranteed to run on the same
    connection as other session queries. The statement resets to the login
    role first, NOT because switching requires it (SET ROLE checks the SESSION
    user's memberships, so guild A -> guild B directly is legal) but as a
    defensive baseline (see :data:`_CONTEXT_SQL`).
    """
    context = session.info[_RLS_CONTEXT_INFO_KEY]
    connection = await session.connection()
    cohorts.note_route(connection.sync_connection, context.guild_id)
    await session.exec(text(_CONTEXT_SQL), params=_bind_params(context))


@dataclass(frozen=True)
class SavedContext:
    """A session's stored context, as :func:`save_rls_context` found it."""

    context: Optional[RequestContext]
    established: Optional[float]
    #: The tier the request authenticated as. A routing records it, so it is
    #: put back with the rest: the caller on the other side is still the same
    #: request, and one that had recorded none has none again.
    tier: Optional[str]


def save_rls_context(session: AsyncSession) -> SavedContext:
    """What :func:`restore_rls_context` needs to put this session back."""
    return SavedContext(
        context=session.info.get(_RLS_CONTEXT_INFO_KEY),
        established=session.info.get(_RLS_ESTABLISHED_INFO_KEY),
        tier=session.info.get(_RLS_TIER_INFO_KEY),
    )


async def restore_rls_context(
    session: AsyncSession, saved: SavedContext, *, apply: bool = True
) -> None:
    """Put back the context ``saved`` recorded, including the freshness stamp,
    which a routing in between must not renew.

    A session that carried no context at all (the system engine on its login
    role) is returned to exactly that: the current transaction is neutralized
    and the stored context is dropped, so later transactions start pristine
    rather than replaying a context something else invented. ``apply`` false
    leaves the current transaction alone, for one that accepts no further
    statements.
    """
    # Restoring the stored context comes first and cannot fail, so the
    # caller's next transaction replays the caller's own context whatever
    # happened in between.
    session.info[_RLS_CONTEXT_INFO_KEY] = (
        saved.context if saved.context is not None else Unattributed()
    )
    if saved.established is not None:
        session.info[_RLS_ESTABLISHED_INFO_KEY] = saved.established
    if saved.tier is not None:
        session.info[_RLS_TIER_INFO_KEY] = saved.tier
    else:
        session.info.pop(_RLS_TIER_INFO_KEY, None)
    if apply and session.in_transaction():
        await _apply_stored_context(session)
    if saved.context is None:
        session.info.pop(_RLS_CONTEXT_INFO_KEY, None)
        session.info.pop(_RLS_ESTABLISHED_INFO_KEY, None)


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = BACKEND_DIR / "alembic"


def _get_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    # Use superuser URL for migrations (needs CREATE ROLE and DDL privileges)
    # Alembic uses ConfigParser interpolation; escape literal URL percent signs.
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    config.attributes["url_configured"] = True
    return config


def _database_name(url: str) -> str:
    return make_url(url).database or "?"


def migration_chain() -> tuple[frozenset[str], str | None]:
    """Every revision this image ships, and the newest of them.

    Read from the files in the image, without touching the database: it is what
    a stamped database is checked against before alembic is asked to upgrade it
    (see ``check_pre_baseline_db``). ``(frozenset(), None)`` if the chain cannot
    be read, so a caller diagnosing a database treats it as unknown rather than
    as empty.
    """
    try:
        chain = ScriptDirectory.from_config(_get_alembic_config())
        revisions = frozenset(step.revision for step in chain.walk_revisions())
        return revisions, chain.get_current_head()
    except Exception:
        return frozenset(), None


def _missing_database_error() -> RuntimeError:
    """What to raise when DATABASE_URL names a database that is not there.

    The database itself is infrastructure's to make, not the app's: the
    compose image creates it from POSTGRES_DB on first boot, and an existing
    install has one already. Say so, rather than let a connection error
    surface as forty frames of driver traceback — from whichever of the two
    startup connections reaches it first.
    """
    name = _database_name(settings.DATABASE_URL)
    return RuntimeError(
        f"Database {name!r} does not exist. The compose image creates it "
        f"from POSTGRES_DB the first time its volume is initialised, and "
        f"only then — on a server that already has a volume, make it by "
        f"hand as the superuser:\n"
        f"  docker exec -e PGPASSWORD=<pw> <container> \\\n"
        f"    psql -U <superuser> -d postgres -c 'CREATE DATABASE {name}'\n"
        f"The app does not create its own database; it takes ownership "
        f"of an existing one at startup."
    )


@asynccontextmanager
async def migration_lock() -> AsyncGenerator[AsyncConnection, None]:
    """Take the database's migration lock for the duration of the block.

    Alembic runs in-process at startup, so instances sharing a database take
    turns here rather than upgrading it at the same time. The lock rides a
    connection of its own — opened for this, closed after, which is what
    releases it — because the upgrade runs on connections alembic opens for
    itself. AUTOCOMMIT keeps that connection merely idle, rather than idle in
    a transaction, for however long the upgrade ahead of it takes. The block
    is given the connection, for the checks that run under the lock.
    """
    lock_engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    try:
        conn = await lock_engine.connect()
    except InvalidCatalogNameError as exc:
        await lock_engine.dispose()
        raise _missing_database_error() from exc
    try:
        if not await advisory_lock(
            conn, LockNamespace.MIGRATION, wait=False, xact=False
        ):
            logger.info(
                "Another instance is migrating this database; waiting for it to finish."
            )
            waited_from = time.monotonic()
            await advisory_lock(conn, LockNamespace.MIGRATION, xact=False)
            logger.info(
                "Migration lock acquired after %.0fs.", time.monotonic() - waited_from
            )
        yield conn
    finally:
        # Closing the connection is what gives the lock back.
        await conn.close()
        await lock_engine.dispose()


async def run_migrations() -> None:
    config = _get_alembic_config()
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
    except InvalidCatalogNameError as exc:
        raise _missing_database_error() from exc
