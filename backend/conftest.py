"""
Pytest configuration and fixtures for backend tests.

This module provides the core testing infrastructure including:
- Test database setup and teardown
- Session fixtures for database access
- Authentication helpers and fixtures
- Test client for API integration tests
"""

import asyncio
import functools
import hashlib
import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives import serialization as _serialization
from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed25519
from httpx import ASGITransport, AsyncClient
from starlette.requests import HTTPConnection
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.api import content_socket
from app.core.rate_limit import limiter
from app.db import cohorts, post_commit
from app.db.advisory_locks import LockNamespace
from app.db.session import (
    clear_rls_context,
    get_system_session,
    get_session,
    prepare_query_engine,
    served_guild_id,
)
from app.testing import guild_pool
from app.testing.schema_harness import clear_search_path_pin
from app.testing.server import in_request_tasks
from app.db.guild_ddl import render_guild_schema_ddl
from app.db.guild_migrations import GUILD_SCHEMA_REGEX
from app.db.schema_provisioning import guild_schema_name
from app.db.tenancy import SHARED_TABLES
from app.main import app

# Quarantined tests and a shuffled order (the nightly run).
pytest_plugins = ["app.testing.run_options", "pytester"]

# --- Per-run isolation (checkout + pytest-xdist worker) -------------------------
# xdist runs each worker as its own OS process, so all Python state in this module
# is already per-worker. The shared resources are the Postgres DATABASE and the
# cluster-global ROLES; isolate both per run so the suite is parallel-safe.
#
# The key has two parts, because a run is identified by two things:
#
#   WORKER_ID  — xdist's value used VERBATIM ("gw0"/"gw1"/... distributed,
#                "master" standalone). xdist exports PYTEST_XDIST_WORKER into each
#                worker process before this module is imported; we don't rename it.
#                Separates the workers WITHIN one run.
#   CHECKOUT_ID — a digest of this checkout's path. Separates CONCURRENT RUNS from
#                different worktrees, which are all "master" (or all "gw0", …) and
#                would otherwise share one database and one set of cluster-global
#                roles. The path is used rather than the branch so the key survives
#                a rename or a branch switch mid-run.
WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER", "master")
# parents[1] is the repo root — backend/conftest.py. scripts/dev-ports.sh keys
# the dev ports off the same directory, so one id names a checkout everywhere.
CHECKOUT_ID = hashlib.sha256(
    str(Path(__file__).resolve().parents[1]).encode()
).hexdigest()[:8]
RUN_ID = f"{CHECKOUT_ID}_{WORKER_ID}"

# Per-run, cluster-global role prefix so runs and workers never collide on, or
# drop, each other's roles (test_<checkout>_gw0_guild_<id>,
# test_<checkout>_gw0_platform_<tier>). Set BEFORE any migration/provisioning: the
# platform-role migration and the routing helpers read these at apply time, and
# guild provisioning is already prefix-aware.
settings.GUILD_ROLE_PREFIX = f"test_{RUN_ID}_"
settings.PLATFORM_ROLE_PREFIX = f"test_{RUN_ID}_"

# Handoff tokens are EdDSA and need a real signing key, which a test that mints
# one asks for through ``handoff_signing_key``. Everywhere else the deployment
# default holds: no key.
settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM = None

# Pin the dev-only webhook/AI target escape hatch OFF so the suite asserts
# production target policy (https + public addresses) regardless of a local
# ``.env`` that enables it. Tests exercising the flag-on path re-set it via
# ``monkeypatch`` for their own scope.
settings.WEBHOOK_ALLOW_PRIVATE_TARGETS = False

# --- Test-infrastructure superuser ---------------------------------------------
# The suite needs cluster-superuser powers the APP must never hold: CREATE
# DATABASE per worker, raw setup/assertion writes on FORCE-RLS tables (the
# ``session`` fixture), and session_replication_role truncation. That is test
# infrastructure, so it is deliberately NOT a Settings field — the app's
# DATABASE_URL stays the least-privilege app_provisioner role. Host/port come
# from DATABASE_URL (same cluster); credentials are the dev-compose/CI
# bootstrap superuser, overridable via the standard postgres-image variables.
_su_user = os.environ.get("POSTGRES_USER", "initiative")
_su_password = os.environ.get("POSTGRES_PASSWORD", "initiative")
_app_db = make_url(settings.DATABASE_URL)
_su_netloc = f"{_app_db.host}:{_app_db.port or 5432}"
_base_url = (
    f"postgresql+asyncpg://{quote(_su_user, safe='')}:"
    f"{quote(_su_password, safe='')}@{_su_netloc}"
)

#: Shared tables the migrations fill with catalog data and no test writes, so
#: the reset between tests leaves them alone (``rule_choices``: the values each
#: ``choice`` rule may take).
_CATALOG_TABLES = frozenset({"rule_choices"})

# Per-run database so a worker's TRUNCATE/DROP never clobbers another worker's —
# or another checkout's — data.
TEST_DB_NAME = f"initiative_test_{RUN_ID}"
TEST_DATABASE_URL = f"{_base_url}/{TEST_DB_NAME}"

# Bound any single statement against the test DB so a cross-connection deadlock
# (real-role request connection vs the privileged setup/provisioning connection —
# a wait Postgres can't detect) fails fast and visibly instead of hanging the
# suite. Applied at the DATABASE level so EVERY connection inherits it; set after
# migrations so a slow migration isn't bounded.
TEST_STATEMENT_TIMEOUT = "30s"

BACKEND_DIR = Path(__file__).resolve().parent


# --- `-n auto` is bounded by MEMORY, not just cores --------------------------
# A worker is not a thread: it imports the whole app and opens its own engines
# and pools, and was measured at ~500MB resident, with its Postgres backends and
# the WAL its writes generate on top of that. So on a 16-core machine plain
# `-n auto` asks for ~8GB of workers before Postgres or an editor gets a byte,
# and a fixed-ceiling host (a WSL2 VM is the one that bites here) dies partway
# through the suite instead of finishing it.
#
# Cores stay the upper bound; memory becomes the second one. Budget half of
# MemTotal for workers -- the other half is Postgres, its page cache, and
# whatever else is running -- and divide by the per-worker cost. Set
# PYTEST_XDIST_AUTO_NUM_WORKERS to override on a host that knows better: xdist
# reads that variable in its own implementation of this hook, so returning None
# here hands the decision straight back to it.
_WORKER_MEMORY_BUDGET_MB = 900


def _mem_total_mb() -> int | None:
    """Total RAM in MB, or None where /proc/meminfo isn't readable."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_xdist_auto_num_workers(config: "pytest.Config") -> int | None:
    if os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return None  # explicit override; let xdist's own hook answer
    if hasattr(os, "sched_getaffinity"):
        cores = len(os.sched_getaffinity(0))
    else:
        cores = os.cpu_count() or 1
    mem_total = _mem_total_mb()
    if mem_total is None:
        return None  # unknown host; xdist's core count is as good a guess as any
    return max(1, min(cores, (mem_total // 2) // _WORKER_MEMORY_BUDGET_MB))


async def connect_su_postgres() -> asyncpg.Connection:
    """Test-infra superuser connection to the always-present ``postgres`` DB.

    Public because ``alembic/migrations_test.py`` creates its own database and
    needs the same credentials — one definition of "the test-infra superuser",
    not a second parse of ``DATABASE_URL`` that assumes the app's role is one.
    """
    return await asyncpg.connect(
        user=_su_user,
        password=_su_password,
        host=_app_db.host,
        port=_app_db.port or 5432,
        database="postgres",
    )


async def _ensure_test_database() -> None:
    """Create this worker's test database if it doesn't exist.

    Concurrent xdist workers each ``CREATE DATABASE`` at once; Postgres serializes
    these on a template lock and the losers raise (duplicate / "source database is
    being accessed"), so retry. ``CREATE DATABASE`` can't run inside a transaction,
    hence the autocommit asyncpg connection.
    """
    conn = await connect_su_postgres()
    try:
        for _attempt in range(12):
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
            )
            if exists:
                return
            try:
                await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
                return
            except asyncpg.DuplicateDatabaseError:
                return  # another worker won the race; that's fine
            except asyncpg.ObjectInUseError:
                # The ONLY expected transient error: template1 is momentarily
                # locked by a peer's CREATE DATABASE. Retry. Any other PostgresError
                # (auth, permissions, bad config) is real — let it propagate rather
                # than spin 12x and mask it behind a generic RuntimeError.
                await asyncio.sleep(0.5)
        raise RuntimeError(f"could not create test database {TEST_DB_NAME!r}")
    finally:
        await conn.close()


async def _bootstrap_test_database() -> None:
    """Apply the privileged prerequisites to this worker's test database.

    A deployment gets these from ``app.db.bootstrap`` at startup, over
    ``DATABASE_URL_BOOTSTRAP``; the suite is that infrastructure for its own
    database, the same way it sources its own superuser, and runs the same
    module so the tests exercise what ships. It covers both halves: the three
    login roles the app connects as, and the search match operator (without
    which the index falls back to the stock operator — a different plan than
    production runs).
    """
    from app.db.bootstrap import ensure_database_bootstrap

    await ensure_database_bootstrap(bootstrap_url=TEST_DATABASE_URL)


async def _grant_test_temporary() -> None:
    """Hand back the database's default TEMPORARY grant on this worker's own DB.

    A deployment creates no temporary objects, so the bootstrap revokes that
    grant; the suite does create them (fixtures that stand up a shape to query
    build it as a TEMP table). Runs on every session rather than only when the
    database is migrated, because the revoke outlives the run that applied it.
    """
    conn = await connect_su_postgres()
    try:
        await conn.execute(f'GRANT TEMPORARY ON DATABASE "{TEST_DB_NAME}" TO PUBLIC')
    finally:
        await conn.close()


async def _set_db_statement_timeout() -> None:
    """Apply a DB-level statement_timeout to the worker's test DB (catch-all net
    for cross-connection deadlocks). Affects connections opened afterward."""
    conn = await connect_su_postgres()
    try:
        await conn.execute(
            f'ALTER DATABASE "{TEST_DB_NAME}" SET statement_timeout = '
            f"'{TEST_STATEMENT_TIMEOUT}'"
        )
    finally:
        await conn.close()


# Cross-worker serialization for the migrations' SHARED cluster-global role DDL
# (app_user/app_admin/app_guild_base/platform_* + GRANTs) — concurrent xdist
# workers otherwise collide with "tuple concurrently updated" on the shared
# catalog. A PostgreSQL ADVISORY LOCK does this PORTABLY: unlike a POSIX file lock
# it needs no fcntl (so it works on Windows) and no extra dependency, it
# auto-releases if a worker dies (its connection drops), and advisory locks share
# ONE cluster-wide key space across the per-worker databases, so every worker
# serializes on the same key. Each worker still migrates its OWN DB; only the
# shared role operations are serialized.
# ``LockNamespace.TEST_SUITE_MIGRATION``, apart from the app's own migration
# lock: this one is taken on the ``postgres`` database, across workers, for DDL
# that is cluster-global.


def _alembic_config() -> Config:
    """Alembic config pointed at this worker's test database."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    config.attributes["url_configured"] = True
    return config


def _alembic_upgrade_head() -> None:
    """Run ``alembic upgrade head`` synchronously. Alembic's env.py drives its own
    event loop (``asyncio.run``), so this must run OUTSIDE a running loop — call it
    via ``asyncio.to_thread`` from async code."""
    command.upgrade(_alembic_config(), "head")


async def _migrate_under_lock() -> None:
    """Ensure the worker's DB exists and migrate it while holding the cross-worker
    advisory lock. The lock rides a dedicated connection to the always-present
    ``postgres`` DB for the whole migration; ``command.upgrade`` runs in a worker
    thread (where it can spin its own loop) while THIS loop keeps the lock
    connection — and thus the lock — alive."""
    lock_conn = await connect_su_postgres()
    try:
        await lock_conn.execute(
            "SELECT pg_advisory_lock($1)", int(LockNamespace.TEST_SUITE_MIGRATION)
        )
        await _ensure_test_database()
        await asyncio.to_thread(_alembic_upgrade_head)
    finally:
        await lock_conn.close()  # closing the connection releases the advisory lock


async def _bootstrap_under_lock() -> None:
    """Create the database and apply the privileged prerequisites to it.

    Runs on EVERY session, not only when the database needs migrating — a
    deployment applies these on every start, and the state they converge
    (role attributes, default privileges, the search operator) outlives the run
    that set it, so a database kept warm between runs would otherwise keep
    whatever an older build left. Shares the migration lock because the role
    DDL is cluster-global.
    """
    lock_conn = await connect_su_postgres()
    try:
        await lock_conn.execute(
            "SELECT pg_advisory_lock($1)", int(LockNamespace.TEST_SUITE_MIGRATION)
        )
        await _ensure_test_database()
        await _bootstrap_test_database()
    finally:
        await lock_conn.close()


async def _apply_public_rls() -> None:
    """Put the registry's policies on the shared tables, as boot does.

    A shared table's policies come from ``app.db.public_rls`` rather than its
    migration, and a deployment applies them in ``ensure_public_rls`` moments
    after migrating. This is that step for the worker's own database, run on
    every session so a registry edit reaches a database that was migrated
    before it. The shared trigger functions the guild back-fill re-renders
    come along for the same reason."""
    from app.db.public_rls import apply_public_rls_if_changed
    from app.db.schema_provisioning import apply_guild_trigger_functions

    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await apply_public_rls_if_changed(conn)
            await apply_guild_trigger_functions(conn)
    finally:
        await engine.dispose()


async def _narrow_set_config() -> None:
    """Take ``set_config`` from ``PUBLIC``, as boot does after migrating."""
    from app.db.bootstrap import ensure_set_config_narrowed

    assert await ensure_set_config_narrowed(bootstrap_url=TEST_DATABASE_URL)


async def _retire_public_authorization_copies() -> None:
    """Drop the ``public`` copies of the guild functions, as boot does after
    the back-fill. The migrations create them; a provisioned schema binds its
    own; a fresh database has nothing bound to them, so the drop goes through
    here. A copy something still binds is left, as boot leaves it."""
    from app.db.authorization import drop_public_copies
    from app.db.schema_provisioning import strip_template_registry_objects

    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        # As the boot back-fill does first: a template that earlier runs
        # rendered the registries into still binds the public copies.
        async with engine.begin() as conn:
            await strip_template_registry_objects(conn)
        await drop_public_copies(engine)
    finally:
        await engine.dispose()


async def _install_guild_pool() -> None:
    """Set up the guild schema pool on the worker's database (see
    ``app/testing/guild_pool.py``). After the migrations, whose own DDL is
    not a test's."""
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        await guild_pool.install(engine)
    finally:
        await engine.dispose()


async def _create_runtime_tables() -> None:
    """Create, as a deployment does, the tables a service makes on first use.

    A deployment creates them on the provisioning login, which owns them. The
    suite points the provisioning engine at its superuser, so whichever test got
    there first would leave one owned by a login the app never connects as.
    Made here, before any test, each belongs to the provisioner.
    """
    import app.db.session as db_session
    from app.services import storage_backfill

    engine = create_async_engine(
        settings.DATABASE_URL.rsplit("/", 1)[0] + "/" + TEST_DB_NAME
    )
    bound = db_session.provisioning_engine
    db_session.provisioning_engine = engine
    try:
        storage_backfill.reset_for_tests()
        await storage_backfill._ensure_table()
    finally:
        db_session.provisioning_engine = bound
        storage_backfill.reset_for_tests()
        await engine.dispose()


async def _test_db_is_at_head() -> bool:
    """True when this worker's database already exists and is stamped at head.

    A warm run is the common case: the per-worker databases persist, so every
    worker's ``alembic upgrade head`` finds nothing to do. It still pays a
    connection, an env.py import and — because the shared role DDL forces it —
    the cross-worker lock, which makes that no-op SERIAL: N workers pay it one
    after another before any test starts. Asking the version table first turns
    that into one cheap query per worker, taken in parallel.

    Anything unexpected (no database, no ``alembic_version``, more than one head)
    returns False and takes the full locked path, which is idempotent."""
    heads = set(ScriptDirectory.from_config(_alembic_config()).get_heads())
    if len(heads) != 1:
        return False
    try:
        conn = await asyncpg.connect(
            user=_su_user,
            password=_su_password,
            host=_app_db.host,
            port=_app_db.port or 5432,
            database=TEST_DB_NAME,
        )
    except (asyncpg.InvalidCatalogNameError, OSError):
        return False
    try:
        rows = await conn.fetch("SELECT version_num FROM alembic_version")
    except asyncpg.PostgresError:
        return False
    finally:
        await conn.close()
    return {r["version_num"] for r in rows} == heads


def _run_test_migrations() -> None:
    """Ensure the worker's test database exists, apply the privileged bootstrap
    and migrate it (serialized across workers by the advisory lock), then arm the
    statement_timeout net.

    The migration is skipped outright when the database is already at head — see
    ``_test_db_is_at_head``; the two steps after it run against this worker's OWN
    database, so they need no shared lock and stay parallel.

    ``_set_db_statement_timeout`` is a per-worker ``ALTER DATABASE`` on this
    worker's OWN DB — no shared catalog — so it runs OUTSIDE the cross-worker lock,
    and after migrations so a slow migration isn't bounded by it."""
    asyncio.run(_bootstrap_under_lock())
    if not asyncio.run(_test_db_is_at_head()):
        asyncio.run(_migrate_under_lock())
        # A deployment migrates as the provisioning role, so its objects belong
        # to that role the moment they are created. The suite migrates as its
        # own superuser instead, which leaves every table the migration made
        # owned by that login -- so the bootstrap runs a second time, and its
        # handover moves them. Without it a freshly created database is shaped
        # unlike any real one, with the app's tables owned by a login the app
        # never connects as.
        asyncio.run(_bootstrap_under_lock())
    asyncio.run(_create_runtime_tables())
    asyncio.run(_apply_public_rls())
    asyncio.run(_narrow_set_config())
    asyncio.run(_retire_public_authorization_copies())
    asyncio.run(_grant_test_temporary())
    asyncio.run(_set_db_statement_timeout())
    asyncio.run(_install_guild_pool())


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations():
    """Automatically create test database and run migrations once per session."""
    _run_test_migrations()


@pytest.fixture(scope="session", autouse=True)
def _install_soft_delete_filter():
    """Install the SQLAlchemy session-wide filter that hides soft-deleted rows
    by default. Mirrors the production startup hook in app/main.py so tests
    see the same query semantics as live requests."""
    from app.db.soft_delete_filter import install_soft_delete_filter

    install_soft_delete_filter()


@pytest.fixture(autouse=True)
def _isolated_uploads_dir(monkeypatch, tmp_path):
    """Every test gets its own uploads directory.

    The default (repo-relative ``uploads/``) is shared state three ways over:
    across consecutive tests (guild ids RESTART IDENTITY every test, so
    ``guild_1/`` accumulates and any deprovision purges another test's
    blobs), across xdist workers (per-worker DATABASES, one shared
    filesystem), and — worst — with a locally running dev server, whose
    background workers (import/export GC, guild purges) sweep the very tree
    a test just staged a payload into. Storage resolves ``UPLOADS_DIR``
    lazily per call, so a per-test tmp dir isolates all of it."""
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))


@pytest.fixture(autouse=True)
def _reset_app_caches():
    """Start and end every test with no cached plug-in service registrations and
    no cached install references.

    The request path reads both through in-process caches (see
    ``registration_lookup`` and ``plugin_refs``). Test databases are rebuilt per
    test while those caches are module state, so without this a row created in
    one test would still be answering reads in the next.
    """
    from app.services.marketplace.plugin_refs import forget_cached_install_refs
    from app.services.marketplace.registration_lookup import invalidate_registrations

    invalidate_registrations()
    forget_cached_install_refs()
    yield
    invalidate_registrations()
    forget_cached_install_refs()


@pytest.fixture(autouse=True)
def _reset_presence_roll():
    """Start and end every test with nobody online.

    How a person appears is answered from a process-global roll fed by the
    sockets this process holds (see ``app.services.platform.presence``). Test
    databases RESTART IDENTITY per test, so user ids repeat — and a test that
    leaves a socket registered would hand its user id to whoever gets that id
    next, which reads as a stranger being online.
    """
    from app.services.platform import presence

    presence.online = presence.OnlineRoll()
    yield
    presence.online = presence.OnlineRoll()


@pytest.fixture(autouse=True)
def _reset_timer_wakes():
    """Start and end every test with no community waiting to be woken.

    ``sweep_timers.wake`` notes a community in a process-global set that the
    next ``process_due_timers`` arms timers for. Test databases RESTART
    IDENTITY per test, so a wake one test left behind would arm a timer in the
    next for a community that test never made, or for whoever has its id now.
    """
    from app.services import sweep_timers

    sweep_timers._woken.clear()
    yield
    sweep_timers._woken.clear()


@functools.cache
def _handoff_keypair() -> tuple[str, str]:
    """One Ed25519 keypair per process, built the first time a test asks for it."""
    key = _ed25519.Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=_serialization.Encoding.PEM,
        format=_serialization.PrivateFormat.PKCS8,
        encryption_algorithm=_serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=_serialization.Encoding.PEM,
            format=_serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return private_pem, public_pem


@pytest.fixture
def handoff_signing_key(monkeypatch) -> str:
    """Configure a handoff signing key for this test; returns its public PEM
    for tests that verify a minted token's signature."""
    private_pem, public_pem = _handoff_keypair()
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", private_pem)
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_KEY_ID", "test-handoff-key")
    return public_pem


@pytest.fixture(autouse=True)
def _disable_hibp_check(monkeypatch):
    """Disable the HaveIBeenPwned breach lookup for all tests by default.

    Without this, every registration / password change test would make
    a real outbound HTTPS call to the HIBP API — flaky and slow.
    Tests that explicitly exercise the breach path opt back in via
    their own monkeypatch + ``hibp.is_password_breached`` stub.
    """
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "HIBP_CHECK_ENABLED", False)


@pytest.fixture(scope="function")
async def engine(_worker_engines):
    """The test database engine, as the superuser."""
    yield _worker_engines.superuser
    await _worker_engines.superuser.dispose()


def _test_url_for_role(role: str) -> str:
    """Test-DB connection URL for a given Postgres login role.

    The default ``engine``/``session`` fixtures connect as the SUPERUSER, which
    bypasses table/schema GRANTs and BYPASSRLS — so they silently mask
    permission bugs that bite the real ``app_admin``/``app_user`` roles in
    production (e.g. a cross-schema ``SELECT`` without ``SET ROLE``). This maps a
    role name onto a test-DB URL using that role's real credentials so a test can
    exercise the production privilege boundary.
    """
    if role in ("superuser", "su"):
        return TEST_DATABASE_URL
    base = {
        "app_admin": settings.DATABASE_URL_ADMIN,
        "app_user": settings.DATABASE_URL_APP,
    }.get(role)
    if base is None:
        raise ValueError(f"unknown test role: {role!r}")
    return base.rsplit("/", 1)[0] + "/" + TEST_DB_NAME


@pytest.fixture
async def role_session():
    """Factory yielding a DB session connected AS a given role (default
    ``app_admin``), against the test database.

    Use this to verify behaviour under the REAL production privilege boundary —
    the superuser-backed ``session`` fixture would let a missing ``SET ROLE`` or
    a cross-schema grant gap pass silently. Set up data with the normal
    ``session`` fixture (factories commit, so the rows are visible to this
    separate connection), then assert via ``await role_session("app_admin")``.

    Set any request context on it the way production does — ``set_config(...,
    true)``, transaction-scoped, with the statements it applies to in the same
    transaction. These engines reach Postgres the way the app does, through a
    pooler in transaction mode, so a connection belongs to one caller only for
    as long as a transaction lasts; session-level state written on it outlives
    the test and is handed to whoever gets that connection next. CI runs the
    whole suite through the pooler for this reason.

    Example:
        s = await role_session("app_admin")
        # raises asyncpg InsufficientPrivilege if the code reads a guild schema
        # without SET ROLE — exactly the bug the superuser session hides.
    """
    created: list = []

    async def _make(role: str = "app_admin") -> AsyncSession:
        eng = create_async_engine(
            _test_url_for_role(role), echo=False, pool_pre_ping=True
        )
        maker = async_sessionmaker(
            bind=eng, class_=AsyncSession, expire_on_commit=False
        )
        sess = maker()
        created.append((eng, sess))
        return sess

    yield _make

    for eng, sess in created:
        await sess.close()
        await eng.dispose()


@pytest.fixture
async def reading_as(role_session):
    """A session that reads a community the way a request reads it.

    The default ``session`` fixture connects as the test-infrastructure
    superuser, and a superuser cannot see a policy hide a row — even routed,
    its *login* is still one the database treats as trusted. A test that
    asserts what the policies allow therefore reads on the real request login,
    through the same seam a request goes through, and sets its data up on the
    ordinary session (the factories commit, so a separate connection sees it).

        s = await reading_as(member.id, guild.id)
        assert sorted(await s.exec(select(Queue.name))) == []
    """
    from app.testing import route_as

    async def _make(user_id: int, guild_id: int):
        session = await role_session("app_user")
        await route_as(session, user_id=user_id, guild_id=guild_id)
        return session

    return _make


# Guild ids whose schema was provisioned during the CURRENT test. Lets the
# session-teardown SKIP the pg_namespace / pg_roles cleanup scan for the (vast
# majority of) tests that never provision a guild — only a test that actually
# created a guild schema pays for the catalog scan + DROP SCHEMA/ROLE.
_provisioned_guild_ids: set[int] = set()

#: Whether the CURRENT test reuses pooled guild schemas (``guild_pool``).
_pooling = False

#: How many cohorts the suite divides communities into. More than one, so the
#: paths that give each community a session of its own are the ones exercised.
_TEST_COHORTS = 2

#: The provisioning render of this worker's migrated ``guild_template``, made
#: by the first test and handed to every test after it.
_template_bundle: Any = None


@dataclass(frozen=True)
class _WorkerEngines:
    """The engines app code reaches during a test, built once per worker.

    A test runs on an event loop of its own and a connection belongs to the
    loop that opened it, so the harness empties every pool when a test ends;
    the engines, and the dialect set-up their first connection paid for, are
    kept.
    """

    superuser: AsyncEngine
    system: AsyncEngine
    query: AsyncEngine
    app: AsyncEngine
    cohort_request: tuple[AsyncEngine, ...]
    cohort_system: tuple[AsyncEngine, ...]
    cohort_query: tuple[AsyncEngine, ...]

    def app_engines(self) -> tuple[AsyncEngine, ...]:
        """Every engine but the superuser's, which ``engine`` empties."""
        return (
            self.system,
            self.query,
            self.app,
            *self.cohort_request,
            *self.cohort_system,
            *self.cohort_query,
        )


@pytest.fixture(scope="session")
def _worker_engines() -> _WorkerEngines:
    def _make(role: str) -> AsyncEngine:
        return create_async_engine(
            _test_url_for_role(role), echo=False, pool_pre_ping=True
        )

    engines = _WorkerEngines(
        superuser=_make("superuser"),
        system=_make("app_admin"),
        query=prepare_query_engine(_make("app_user")),
        app=_make("app_user"),
        cohort_request=tuple(_make("app_user") for _ in range(_TEST_COHORTS)),
        cohort_system=tuple(_make("app_admin") for _ in range(_TEST_COHORTS)),
        cohort_query=tuple(
            prepare_query_engine(_make("app_user")) for _ in range(_TEST_COHORTS)
        ),
    )
    # Two cohorts, each with a request, a system and a query pool on this
    # worker's database, so every test that reaches a community through a
    # session of its own (the sockets, the cross-community reads, the sweeps,
    # the query surface) does so from that community's cohort — and a route
    # outside it raises. The platform
    # system pool is tagged as in production, so its routes are counted.
    # Tagging adds listeners, so it happens here, once per engine.
    cohorts.use_request_engines(list(engines.cohort_request))
    cohorts.use_system_engines(list(engines.cohort_system))
    cohorts.use_query_engines(list(engines.cohort_query))
    cohorts.tag_engine(engines.system, cohorts.PLATFORM_SYSTEM)
    return engines


@pytest.fixture(autouse=True)
async def _schema_test_harness(engine, _worker_engines, monkeypatch, request):
    """Make every test schema-per-guild aware.

    - Installs the before_flush router so direct-session (factory) guild-scoped
      writes land in the guild's schema, mirroring what set_rls_context does for
      the request path.
    - Points the provisioning engine at the test DB so create_guild / the guilds
      endpoint provision schemas/roles on the test database.
    - Points the system (admin) engine at the test DB **as the real app_admin
      role**, so maintenance jobs that use ``db_session.system_engine`` /
      ``SystemSessionLocal`` directly (secret-key rotation, upload back-fills,
      workers) run against test data under the real policy-bound role instead
      of silently hitting the dev database.
    - Points the request-path engine at the test DB **as the real app_user
      role**, for the same reason: the sockets and the seams that open a
      session of their own (``db_session.AsyncSessionLocal``) rather than
      taking the request's run against test data under the RLS-enforced role.
    - Wraps ``provision_guild`` (the universal provisioning choke point — factory,
      guild endpoints, backfill, and conversion all route through it) to record
      which guilds got a schema this test, so teardown can skip its cleanup scan
      when none did, and to hand out a pooled schema where one is parked
      (``app/testing/guild_pool.py``).
    """
    import app.db.schema_provisioning as schema_provisioning
    import app.db.session as db_session
    from app.testing.schema_harness import install_guild_routing

    install_guild_routing()
    monkeypatch.setattr(db_session, "provisioning_engine", engine)

    # The provisioning bundle reflects the live guild_template. Tests leave
    # the template as they found it, so it is rendered once per worker, and
    # every test starts from that render whatever the one before it cached.
    global _template_bundle
    if _template_bundle is None:
        schema_provisioning.reset_provisioning_bundle()
        _template_bundle = await schema_provisioning.get_provisioning_bundle()
    monkeypatch.setattr(schema_provisioning, "_bundle", _template_bundle)

    engines = _worker_engines
    monkeypatch.setattr(db_session, "system_engine", engines.system)

    # The query surface keeps a pool of its own, so it needs pointing at this
    # worker's database like the others — it is created at import against the
    # configured one.
    monkeypatch.setattr(db_session, "query_engine", engines.query)
    monkeypatch.setattr(
        db_session,
        "SystemSessionLocal",
        async_sessionmaker(
            bind=engines.system,
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        ),
    )

    monkeypatch.setattr(db_session, "engine", engines.app)
    monkeypatch.setattr(
        db_session,
        "AsyncSessionLocal",
        async_sessionmaker(
            bind=engines.app,
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        ),
    )

    monkeypatch.setattr(settings, "DB_COHORTS", _TEST_COHORTS)
    monkeypatch.setattr(cohorts, "STRICT", True)

    global _pooling
    _pooling = (
        guild_pool.ENABLED
        and request.node.get_closest_marker("fresh_guild_schema") is None
    )
    _provisioned_guild_ids.clear()
    _orig_provision_guild = schema_provisioning.provision_guild

    async def _tracking_provision_guild(*args: Any, **kwargs: Any) -> str:
        gid = kwargs.get("guild_id", args[0] if args else None)
        if gid is None:
            return await _orig_provision_guild(*args, **kwargs)
        gid = int(gid)
        _provisioned_guild_ids.add(gid)
        # A pooled schema was built from the harness's render, so it serves
        # only a test provisioning from that same render.
        if not _pooling or schema_provisioning._bundle is not _template_bundle:
            return await _orig_provision_guild(*args, **kwargs)
        activated = await guild_pool.activate(engine, gid, _template_bundle.stamp)
        if activated:
            return guild_schema_name(gid)
        schema = await _orig_provision_guild(*args, **kwargs)
        if activated is False:
            await guild_pool.adopt(engine, gid)
        return schema

    monkeypatch.setattr(
        schema_provisioning, "provision_guild", _tracking_provision_guild
    )
    yield
    try:
        # Work a commit started, and every task spawned beside it, finishes
        # before the pools close.
        await post_commit.settle_all()
    finally:
        for worker_engine in engines.app_engines():
            await worker_engine.dispose()


@pytest.fixture(scope="function")
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a fresh database session for each test.

    This fixture:
    - Provides a clean AsyncSession for the test
    - Truncates all tables after the test to ensure isolation

    This ensures test isolation by cleaning up all data after each test.

    The session is bound to a single dedicated connection (not the engine pool)
    so that the per-guild ``search_path`` the routing harness sets survives across
    commits — an engine-bound session checks out a fresh, unrouted connection per
    transaction, which is why a flush-then-refresh would otherwise lose the route.
    """
    async with engine.connect() as bound_conn:
        async_session = async_sessionmaker(
            bind=bound_conn,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with async_session() as test_session:
            # Force ``populate_existing`` on every top-level SELECT this setup
            # session runs. The request path now executes on a SEPARATE connection
            # (real app_user/app_admin), so a read-back assertion here would
            # otherwise return the stale, still-cached instance instead of what the
            # request committed. populate_existing refreshes matched objects' columns
            # from the row (unlike expire_all, it doesn't expire PKs, so building a
            # read-back query from a cached object's id stays a pure in-memory read).
            #
            # BUT only when the session has NO pending writes. The fixture is
            # ``autoflush=False`` (mirrors production), so a service test that mutates
            # in memory without committing — e.g. ``invite.uses += 1`` — and then
            # reads the row back would have its uncommitted change CLOBBERED by a
            # refresh from the (still-0) row. Refreshing is only safe-and-wanted when
            # there's no local pending state to lose; a dirty session keeps the
            # identity-map instance (today's pre-real-role behaviour).
            @event.listens_for(test_session.sync_session, "do_orm_execute")
            def _force_populate_existing(orm_execute_state):
                sess = orm_execute_state.session
                if (
                    orm_execute_state.is_select
                    and not orm_execute_state.is_column_load
                    and not orm_execute_state.is_relationship_load
                    and not (sess.new or sess.dirty or sess.deleted)
                ):
                    orm_execute_state.update_execution_options(populate_existing=True)

            yield test_session

            # Expire all objects to detach them from the session
            test_session.expire_all()

        # Roll back the bound connection explicitly: closing a session bound to an
        # external connection does NOT end that connection's transaction, so the
        # test's trailing reads would keep AccessShare locks on the guild-schema
        # tables — which the teardown's DROP SCHEMA (AccessExclusive) would block on.
        # The rollback also ends any assumed role / search_path routing: context
        # is transaction-local now, so no committed reset is needed for the
        # superuser cleanup below to run unrouted.
        await bound_conn.rollback()

    # Work a commit started on a session of its own (joining a community's
    # auto-join initiatives, say) finishes before the tables it reads are
    # emptied or dropped below. After the rollback, so that work is not left
    # waiting on a lock the test's own transaction held.
    await post_commit.settle_all()

    # Session is now closed (its rollback released any lock on public.guilds the
    # create-guild endpoint's trailing SELECT left held). Clean up on a fresh
    # connection: park the pooled guild schemas the test used and drop the rest,
    # with their roles (cluster-global roles must not leak between tests — guild
    # ids restart with the identity below), then truncate public. Only a test
    # that provisioned a guild schema (tracked in _provisioned_guild_ids) or ran
    # DDL on one pays for the catalog scan.
    changed = await guild_pool.take_changed(engine)
    guild_ids: list[int] = []
    if _provisioned_guild_ids or changed:
        async with engine.connect() as conn:
            guild_ids = [
                int(schema.removeprefix("guild_"))
                for (schema,) in (
                    await conn.execute(
                        text("SELECT nspname FROM pg_namespace WHERE nspname ~ :pat"),
                        {"pat": GUILD_SCHEMA_REGEX},
                    )
                ).all()
            ]

    # One guild per transaction. A guild schema holds ~60 tables and their
    # indexes, policies and triggers, and DROP ... CASCADE takes a lock on each;
    # dropping several alongside the TRUNCATE below put hundreds of locks in one
    # transaction, which several xdist workers doing it at once can exhaust
    # (``max_locks_per_transaction`` sizes one shared table for the cluster).
    for guild_id in guild_ids:
        if (
            _pooling
            and guild_schema_name(guild_id) not in changed
            and await guild_pool.park(engine, guild_id)
        ):
            continue
        await guild_pool.drop(engine, guild_id)
    template_changed = (
        guild_pool.TEMPLATE in changed
        and await render_guild_schema_ddl(engine) != _template_bundle.schema_ddl
    )

    # Truncate the SHARED (public-schema) tables to reset state — one
    # multi-table TRUNCATE (a single round-trip) instead of one statement
    # per table. Only shared tables exist in public since the v0.53.5
    # baseline squash; tenant content lives in the per-test guild schemas
    # dropped above.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("SET lock_timeout = '10s'")
        await conn.execute(text("SET session_replication_role = 'replica'"))
        shared_tables = ", ".join(
            f'"{table.name}"'
            for table in SQLModel.metadata.sorted_tables
            if table.name in SHARED_TABLES and table.name not in _CATALOG_TABLES
        )
        await conn.execute(
            text(f"TRUNCATE TABLE {shared_tables} RESTART IDENTITY CASCADE")
        )
        await conn.execute(text("SET session_replication_role = 'origin'"))

    if template_changed:
        pytest.fail(
            "This test changed guild_template and left it changed. Every guild "
            "this worker provisions is rendered from the template as it was "
            "when the run started, so later tests would not see the change.",
            pytrace=False,
        )


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client whose REQUEST path runs as the REAL ``app_user`` login
    role (RLS-enforced), not the Postgres superuser.

    This is the "no superuser in request execution" model: an authenticated request
    assumes its platform/guild role on top of ``app_user`` (so e.g. a ``member`` is
    bound by member-level RLS), and an unauthenticated request runs as ``app_user`` —
    exactly like production. The superuser-backed ``session`` fixture is still used
    for *data setup* (factories commit, so the request connection sees the rows) and
    for the privileged teardown (TRUNCATE / DROP SCHEMA / DROP ROLE).

    ``SystemSessionDep`` is overridden to a real ``app_admin`` (BYPASSRLS,
    grant-bounded) session,
    mirroring the production system engine, so bootstrapping endpoints (guild
    creation, background-job style ops) keep their intended RLS bypass instead of
    silently leaning on the superuser.

    Each request/system session is bound to a single connection so the per-request
    ``SET ROLE`` / ``search_path`` GUCs persist across the request's statements.
    """
    # One connection per (login, pool) a request can be served from: each
    # cohort, and the platform pool for a request that names no community.
    # Each is tagged like the production pool it stands in for, so a session
    # routed outside its cohort raises here as it would be counted there.
    # Opened on first use; a test pays only for the pools it reaches.
    #
    # NOTE on deadlocks: the request path (app_user) and system path (app_admin)
    # are SEPARATE connections, so an endpoint that locks a row on one and
    # waits on the other can app-level deadlock — a wait Postgres can't detect.
    # The net is the DATABASE-level statement_timeout armed in _run_test_migrations
    # (covers EVERY connection, incl. the privileged setup/provisioning conn that a
    # per-connection SET here would miss — which is what hung admin_test).
    served: dict[tuple[str, int | str], tuple[AsyncSession, Any, Any]] = {}

    async def _served_session(login: str, guild_id: int | None) -> AsyncSession:
        if guild_id is not None:
            tag: int | str = cohorts.cohort_of(guild_id)
        else:
            tag = cohorts.PLATFORM if login == "app_user" else cohorts.PLATFORM_SYSTEM
        key = (login, tag)
        if key not in served:
            pool_engine = create_async_engine(
                _test_url_for_role(login), echo=False, pool_pre_ping=True
            )
            cohorts.tag_engine(pool_engine, tag)
            conn = await pool_engine.connect()
            fresh = async_sessionmaker(
                bind=conn, class_=AsyncSession, expire_on_commit=False, autoflush=False
            )()
            if login == "app_user":
                cohorts.mark_request_session(fresh)
            else:
                cohorts.mark_system_session(fresh)
            served[key] = (fresh, conn, pool_engine)
        return served[key][0]

    async def _publish_setup_state() -> None:
        """Commit the setup ``session`` so the request — on its OWN real-role
        connection — sees data the test created but had not committed, and so any
        row lock the setup transaction holds is released.

        Before real-role execution, setup and request shared one connection, so
        uncommitted setup was visible to the request. They are now separate
        transactions: factories commit (visible), but a test that sets up via a
        service which defers its commit (e.g. ``ensure_default_statuses``) would
        otherwise leave its rows invisible to the request — or block the request
        on a lock it holds. Flushing+committing at each request boundary mirrors
        production (data must be committed to cross a connection). It is a cheap
        no-op when nothing is pending.
        """
        await session.commit()

    # Mirror production's per-request session lifecycle: ``get_session`` /
    # ``get_system_session`` yield from ``async with AsyncSessionLocal()``, which
    # rolls back and releases locks when the request ends. The test reuses ONE
    # persistent session per role (bound to a connection so SET ROLE / search_path
    # survive), so it must roll back per request itself — otherwise a handler that
    # leaves an open transaction (e.g. SELECT ... FOR UPDATE then a 4xx without
    # commit) leaks its row locks onto the next request, or onto a follow-up setup
    # write on the SAME row, which then blocks until statement_timeout.
    @asynccontextmanager
    async def _override(
        login: str, connection: HTTPConnection
    ) -> AsyncIterator[AsyncSession]:
        await _publish_setup_state()
        reused = await _served_session(login, served_guild_id(connection))
        # Production gets a FRESH session (empty info) per request; this reused
        # session must drop the previous request's stored context or the next
        # transaction would replay it (stale user/guild) — including any
        # harness pin the before_flush net recorded during the previous
        # request's tenant writes. The DB side needs no reset:
        # transaction-local context died with the request's rollback.
        clear_rls_context(reused)
        clear_search_path_pin(reused)
        # A fresh session also starts with an empty identity map: a row an
        # earlier request loaded would otherwise come back as that request saw
        # it, not as the database now holds it.
        reused.expunge_all()
        try:
            yield reused
        finally:
            await reused.rollback()

    # ``async with``, not ``async for``: closing the dependency must run the
    # rollback before the next request, rather than leave the inner generator
    # for the event loop to close later on the same connection.
    async def override_get_session(
        connection: HTTPConnection,
    ) -> AsyncGenerator[AsyncSession, None]:
        async with _override("app_user", connection) as reused:
            yield reused

    async def override_get_system_session(
        connection: HTTPConnection,
    ) -> AsyncGenerator[AsyncSession, None]:
        async with _override("app_admin", connection) as reused:
            yield reused

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_system_session] = override_get_system_session

    # Disable rate limiting in tests
    limiter.enabled = False

    try:
        async with AsyncClient(
            transport=ASGITransport(app=in_request_tasks(app)),
            base_url="http://test",
            # What a browser on this origin actually sends. Every unsafe method
            # from a page carries it, and CsrfOriginMiddleware requires it (or
            # an allowlisted Origin) before it will let a COOKIE-authenticated
            # write through -- so a client that omits it is not modelling the
            # SPA, it is modelling a script.
            #
            # Set here rather than per test so the fixture is faithful by
            # default. The middleware's own behaviour, including what it does
            # when this is absent or says cross-site, is covered directly in
            # app/core/csrf_test.py against a bare app.
            headers={"sec-fetch-site": "same-origin"},
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        # Release the request/system connections BEFORE the session-fixture teardown
        # runs its privileged TRUNCATE/DROP SCHEMA (which would block on any lock
        # these idle-in-transaction connections still hold, hanging the NEXT test
        # until its statement_timeout fires).
        #
        # Clean each pair INDEPENDENTLY and best-effort: a failure tearing down the
        # request pair must NOT skip the admin pair (or vice versa) and leak its
        # connection. ``engine.dispose()`` is the guaranteed backstop — it
        # force-closes the pooled connection even if the graceful role-reset above
        # it failed — so it runs for every engine regardless.
        for sess, conn, eng in served.values():
            with suppress(Exception):
                await sess.close()
            with suppress(Exception):
                # Rollback ends the transaction and, with it, any assumed role
                # (context is transaction-local — no committed reset needed).
                await conn.rollback()
            with suppress(Exception):
                await conn.close()
            with suppress(Exception):
                await eng.dispose()
        # The create-guild endpoint ends on a SELECT (no commit), so the privileged
        # setup session may hold a lock on public.guilds; release it too.
        with suppress(Exception):
            await session.rollback()


def _unpooled(bind: AsyncEngine) -> AsyncEngine:
    return create_async_engine(bind.url, poolclass=NullPool)


@pytest.fixture
def socket_client(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Starlette's ``TestClient``, which drives the app's sockets.

    It serves the app on an event loop of its own. The pools the socket
    endpoints draw from are swapped, for the test, for ones that open a
    connection per checkout, so a connection opened on one loop is never handed
    to the other. A quiet socket beats at once, so an admitted one says so
    without the test waiting out the interval.
    """
    import app.db.session as db_session

    monkeypatch.setattr(content_socket, "HEARTBEAT_SECONDS", 0.05)
    for name in ("_request_makers", "_system_makers"):
        makers = getattr(cohorts, name)
        monkeypatch.setattr(
            cohorts,
            name,
            cohorts._cohort_makers([_unpooled(m.kw["bind"]) for m in makers]),
        )
    monkeypatch.setattr(
        db_session,
        "AsyncSessionLocal",
        async_sessionmaker(
            bind=_unpooled(db_session.engine),
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        ),
    )
    return TestClient(app)


@pytest.fixture
async def acting_user(session):
    """Mint an authenticated test identity at explicit platform/guild roles —
    the single seam for "run this test AS role X". Returns an
    :class:`app.testing.Actor`; see ``app/testing/actor.py`` for the full
    semantics (role defaults, initiative/project scaffolding, ``a.g()`` URLs).

        a = await acting_user()                                  # platform owner
        a = await acting_user("support")                         # tier ceilings
        a = await acting_user(guild_role=CommunityRole.admin,
                              initiative=True, project=True)     # workspace
        b = await acting_user(guild_role=CommunityRole.member, guild=a.guild,
                              initiative=a.initiative, initiative_role="member")
        await client.get(a.g("/projects/"), headers=a.headers)

    With the real-role ``client`` fixture the request runs AS the actor's
    platform tier (public path) or guild role (``/c/{community_id}`` path) on a
    real ``app_user`` connection — RLS enforced, like production.
    """
    from app.testing.actor import make_actor

    return functools.partial(make_actor, session)


@pytest.fixture
async def account_socket():
    """Open a notification-stream socket for an account
    (``app.testing.sockets.open_account_socket``); each leaves the register at
    teardown."""
    from app.services.content_sockets import sockets
    from app.testing.sockets import open_account_socket

    opened: list = []

    def open_(user_id: int, websocket=None, **kwargs):
        opened.append(open_account_socket(user_id, websocket, **kwargs))
        return opened[-1]

    yield open_
    for websocket in opened:
        sockets.leave(websocket)


@pytest.fixture
def rate_limit_of_one_per_minute(client, monkeypatch):
    """Turn the global default rate limit on, at a rate a second request breaks.

    The suite runs with the limiter off, so anything asserting throttling has to
    switch it back on. It takes ``client`` rather than being requested beside it
    because that fixture disables the limiter during its own setup: requested the
    other way round, this is set up first and then quietly undone.
    """
    from slowapi.wrappers import LimitGroup

    from app.core.rate_limit import get_user_or_ip_key

    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(
        limiter,
        "_default_limits",
        [
            LimitGroup(
                limit_provider="1/minute",
                key_function=get_user_or_ip_key,
                scope=None,
                per_method=False,
                methods=None,
                error_message=None,
                exempt_when=None,
                cost=1,
                override_defaults=False,
            )
        ],
    )
    limiter.reset()
    yield
    limiter.reset()
