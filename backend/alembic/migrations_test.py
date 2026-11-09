"""Database tests for Alembic migrations.

These tests actually exercise every migration on a dedicated Postgres
database to confirm:

* a fresh database can be migrated up to ``head`` end-to-end
* each revision can be applied step-by-step from base to head (so a
  silent failure inside one migration can't be papered over by alembic
  collapsing several into a single transaction)
* the chain can be walked downward from head back to the first
  reversible boundary, then re-applied forward again — this is the
  high-value test for release rollbacks
* the alembic_version stamp matches the script directory's head
* the *most-recent* revision (head) specifically can be applied,
  rolled back, and re-applied — this is the test that fires when
  you just wrote a broken migration

These tests use a separate ``initiative_migrations_test`` database so
they don't disturb the schema-stamped ``initiative_test`` database used
by the rest of the suite. Roles (``app_user`` / ``app_admin``) are
PostgreSQL cluster-global and reused — the baseline migration's role
helpers are idempotent.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from app.core.config import settings
from app.db.advisory_locks import LockNamespace
from app.db.tenancy import GUILD_SCOPED_TABLES
from conftest import CHECKOUT_ID, connect_su_postgres

ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parent
BACKEND_DIR = ALEMBIC_SCRIPT_LOCATION.parent
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"

# The baseline is the root: everything before it was collapsed into it
# (scripts/collapse_migrations.py) and cannot be reached, so its
# ``downgrade()`` is a permanent ``NotImplementedError``.
BASELINE_REVISION = ScriptDirectory(str(ALEMBIC_SCRIPT_LOCATION)).get_base()

# Migrations whose ``downgrade()`` intentionally raises
# ``NotImplementedError`` and which therefore have to be skipped when
# walking the chain backwards. Add new entries (with a justification
# comment) when introducing other irreversible migrations.
INTENTIONALLY_IRREVERSIBLE = frozenset(
    {
        BASELINE_REVISION,
    }
)

# Per-run so neither parallel xdist workers nor concurrent runs from other
# checkouts drop/recreate the same DB — these tests DROP their database, so a
# shared name is destructive rather than merely flaky. Same key as conftest's
# TEST_DB_NAME: xdist's worker id verbatim ("gw0"/… distributed, "master"
# standalone), plus conftest's digest of this checkout's path.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "master")
MIGRATIONS_DB_NAME = f"initiative_migrations_test_{CHECKOUT_ID}_{_WORKER}"
_BASE_DB_URL = settings.DATABASE_URL.rsplit("/", 1)[0]
MIGRATIONS_TEST_DATABASE_URL = f"{_BASE_DB_URL}/{MIGRATIONS_DB_NAME}"

# These tests exercise migration up *and down*, so they CREATE and DROP the
# cluster-global app roles. Use a role prefix distinct from the main suite's
# (conftest sets ``test_{checkout}_{worker}_``) so this file's downgrades never
# drop the roles the rest of the suite depends on. Keyed on (checkout, worker)
# for the same reason the database is: the teardown drops every role matching
# this prefix, so a prefix shared with another checkout would take that
# checkout's roles with it.
_MIGRATIONS_ROLE_PREFIX = f"migtest_{CHECKOUT_ID}_{_WORKER}_"

# The suite's migration lock (``LockNamespace.TEST_SUITE_MIGRATION``, as in
# conftest) — a cluster-wide pg_advisory_lock serializes ALL migration runs
# across xdist workers (and across both files) so the shared cluster-global role
# DDL never races. (Portable; replaces a POSIX file lock.)


# ---------------------------------------------------------------------------
# Alembic plumbing
# ---------------------------------------------------------------------------


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["url_configured"] = True
    config.attributes["configure_logger"] = False
    return config


def _script_directory() -> ScriptDirectory:
    """Inspect-only ScriptDirectory; uses the test DB url as a placeholder
    because we never actually connect through it."""
    return ScriptDirectory.from_config(_alembic_config(MIGRATIONS_TEST_DATABASE_URL))


def _run_alembic(action: str, revision: str) -> None:
    """Run ``alembic upgrade <revision>`` or ``alembic downgrade <revision>``.

    A fresh Config is built every call so we never reuse a closed engine
    after a previous step.

    The app role prefixes are swapped to this file's dedicated namespace for the
    duration of the migration (the platform-role migration reads them at apply
    time), then restored — so up/down here churns ``migtest_*`` roles, never the
    main suite's ``test_*`` roles.
    """
    asyncio.run(_run_alembic_async(action, revision))


def _alembic_command(action: str, revision: str) -> None:
    """Run the (synchronous) alembic command. Alembic's env.py spins its own event
    loop, so this must run OUTSIDE a running loop — invoked via asyncio.to_thread."""
    config = _alembic_config(MIGRATIONS_TEST_DATABASE_URL)
    if action == "upgrade":
        command.upgrade(config, revision)
    elif action == "downgrade":
        command.downgrade(config, revision)
    else:  # pragma: no cover — guard against typos in test bodies
        raise ValueError(f"Unknown alembic action: {action!r}")


async def _run_alembic_async(action: str, revision: str) -> None:
    # Serialize with the suite's migration advisory lock: even with a distinct role
    # prefix, the baseline still touches SHARED cluster-global roles (e.g. ALTER
    # ROLE app_user), which races ("tuple concurrently updated") against a
    # concurrent worker's migration. The lock rides a dedicated 'postgres'
    # connection (held for the whole migration); the alembic command runs in a
    # worker thread (where it can spin its own loop). Same key as conftest.
    lock_conn = await asyncpg.connect(**_parse_admin_url(), database="postgres")
    try:
        await lock_conn.execute(
            "SELECT pg_advisory_lock($1)", int(LockNamespace.TEST_SUITE_MIGRATION)
        )
        await _administer_shared_roles()
        saved = (settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX)
        settings.GUILD_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        settings.PLATFORM_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        try:
            await asyncio.to_thread(_alembic_command, action, revision)
        finally:
            settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX = saved
    finally:
        await lock_conn.close()  # closing the connection releases the advisory lock


async def _run_upgrade_chain_locked_async(revisions: list[str]) -> None:
    """Apply ``revisions`` in order while holding the migration lock for the WHOLE
    chain, asserting the stamp after each step.

    Stepping that releases the lock between revisions (the obvious loop of
    ``_run_alembic`` calls) leaves this worker mid-chain after 0068 created the
    cluster-global ``automation_engine`` role + tables but before 0077 drops them.
    A concurrent worker that grabs the lock and runs ``upgrade head`` then hits
    0077's ``DROP ROLE``, which fails because this DB still has automation tables
    depending on the shared role (``DROP ROLE`` consults the cluster-wide
    ``pg_shdepend``). Holding the lock across the chain keeps that transient window
    invisible to other workers — the only place the suite walks *through* the
    0068→0077 window one step at a time.
    """
    lock_conn = await asyncpg.connect(**_parse_admin_url(), database="postgres")
    try:
        await lock_conn.execute(
            "SELECT pg_advisory_lock($1)", int(LockNamespace.TEST_SUITE_MIGRATION)
        )
        await _administer_shared_roles()
        saved = (settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX)
        settings.GUILD_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        settings.PLATFORM_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        try:
            for rev in revisions:
                await asyncio.to_thread(_alembic_command, "upgrade", rev)
                stamp = await _fetch_current_revision_async()
                assert stamp == rev, (
                    f"After upgrading to {rev}, alembic_version is {stamp!r}. "
                    "A migration likely failed silently or skipped a step."
                )
        finally:
            settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX = saved
    finally:
        await lock_conn.close()  # closing the connection releases the advisory lock


def _ordered_revisions_base_to_head() -> list[str]:
    """Return every revision id in apply order (base first, head last)."""
    script = _script_directory()
    return [r.revision for r in list(script.walk_revisions())[::-1]]


# ---------------------------------------------------------------------------
# Direct asyncpg helpers (no sync postgres driver is installed in this repo)
# ---------------------------------------------------------------------------


def _parse_admin_url() -> dict:
    """Connection kwargs for the app's provisioning role (``DATABASE_URL``).

    Everything these tests do *inside* the database runs as this role, exactly
    as migrations do in production. Creating and dropping the database itself
    does not: that is cluster-level, and the provisioning role is deliberately
    ``NOCREATEDB``. ``connect_su_postgres`` covers those two statements.
    """
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    return {
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
    }


async def _administer_shared_roles() -> None:
    """Let the provisioning role hand out the cluster-global roles it shares.

    The suite migrates two sets of databases with two different logins: the
    main suite's ``conftest`` runs as the test-infra superuser, this file as
    ``app_provisioner``. A prefixed role belongs to whichever of them made it,
    but the handful of unprefixed ones is created once for the whole cluster,
    by whichever got there first, and a ``CREATEROLE`` login holds ADMIN only
    on the roles it created itself.

    A deployment settles that in ``app.db.bootstrap``, which grants the
    provisioner ADMIN OPTION over those roles on every start; the suite is that
    infrastructure for its own databases, so it runs the same statement over
    the same role set — no second list — on the superuser connection. Called
    while holding the migration lock, which is also what every other worker
    creates roles under.
    """
    from app.db.bootstrap import _administer_existing_roles

    conn = await connect_su_postgres()
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app._bootstrap_role', $1, true)",
                _parse_admin_url()["user"],
            )
            await conn.execute(_administer_existing_roles())
    finally:
        await conn.close()


async def _drop_prefixed_roles(conn: asyncpg.Connection) -> None:
    """Drop this worker's cluster-global roles.

    Roles outlive the database that used them, so a crashed run leaves them
    behind — and a CREATEROLE role holds ADMIN OPTION only on roles it created
    itself, so the provisioning role cannot re-grant a leftover it did not
    make. Clearing them alongside the database keeps each run creating its own.
    Safe to run before the database exists; call it *after* dropping the
    database so no privileges still depend on them.
    """
    rows = await conn.fetch(
        "SELECT rolname FROM pg_roles WHERE rolname LIKE $1",
        f"{_MIGRATIONS_ROLE_PREFIX}%",
    )
    if rows:
        names = ", ".join(f'"{row["rolname"]}"' for row in rows)
        await conn.execute(f"DROP ROLE IF EXISTS {names}")


async def _drop_db() -> None:
    """Drop the dedicated migrations test database and this worker's roles.

    ``DROP DATABASE`` requires no other sessions to be connected. We use
    ``WITH (FORCE)`` (PG 13+) to evict any leftover connections from a
    crashed prior run.
    """
    conn = await connect_su_postgres()
    try:
        await conn.execute(
            f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)'
        )
        await _drop_prefixed_roles(conn)
    finally:
        await conn.close()


async def _drop_and_create_db() -> None:
    """Drop+recreate the dedicated migrations test database.

    Owned by the provisioning role so the migration chain runs against objects
    it owns, the way a real deployment does.
    """
    owner = _parse_admin_url()["user"]
    conn = await connect_su_postgres()
    try:
        await conn.execute(
            f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)'
        )
        await _drop_prefixed_roles(conn)
        await conn.execute(f'CREATE DATABASE "{MIGRATIONS_DB_NAME}" OWNER "{owner}"')
    finally:
        await conn.close()


async def _connect_test_db() -> asyncpg.Connection:
    return await asyncpg.connect(database=MIGRATIONS_DB_NAME, **_parse_admin_url())


async def _fetch_current_revision_async() -> str | None:
    conn = await _connect_test_db()
    try:
        exists = await conn.fetchval(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )
        if not exists:
            return None
        return await conn.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await conn.close()


def _current_alembic_revision() -> str | None:
    return asyncio.run(_fetch_current_revision_async())


async def _table_exists_async(table_name: str, schema: str = "public") -> bool:
    conn = await _connect_test_db()
    try:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = $2 AND table_name = $1"
                ")",
                table_name,
                schema,
            )
        )
    finally:
        await conn.close()


def _table_exists(table_name: str, schema: str = "public") -> bool:
    return asyncio.run(_table_exists_async(table_name, schema))


async def _alembic_version_row_count_async() -> int:
    conn = await _connect_test_db()
    try:
        return await conn.fetchval("SELECT count(*) FROM alembic_version")
    finally:
        await conn.close()


def _alembic_version_row_count() -> int:
    return asyncio.run(_alembic_version_row_count_async())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def migrations_db() -> Iterator[str]:
    """Module-scoped fixture: create a clean Postgres database for the
    migration round-trip tests and drop it at teardown."""
    asyncio.run(_drop_and_create_db())
    yield MIGRATIONS_TEST_DATABASE_URL
    try:
        asyncio.run(_drop_db())
    except Exception:
        pass


@pytest.fixture
def fresh_migrations_db(migrations_db: str) -> Iterator[str]:
    """Function-scoped fixture: each test gets a freshly recreated DB so
    state from other tests can never leak in."""
    asyncio.run(_drop_and_create_db())
    yield migrations_db


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------


class TestMigrationsAgainstDatabase:
    """End-to-end migration runs against a real Postgres instance."""

    def test_upgrade_to_head_on_fresh_database(self, fresh_migrations_db: str) -> None:
        """The full chain applies cleanly from an empty database."""
        _run_alembic("upgrade", "head")

        head = _script_directory().get_current_head()
        assert _current_alembic_revision() == head, (
            "alembic_version stamp must equal script_directory().get_current_head() "
            "after a successful upgrade"
        )

        # Sanity-check the layout: shared tables in public, tenant content in
        # guild_template — and no tenant table anywhere in public. The whole
        # set, not a sample: public holding one is the bug 20260811_0163 ended.
        for table in ("users", "guilds", "access_grants", "alembic_version"):
            assert _table_exists(table), f"expected table {table!r} after upgrade head"
        for table in ("initiatives", "projects", "tasks", "files"):
            assert _table_exists(table, schema="guild_template"), (
                f"expected table {table!r} in guild_template after upgrade head"
            )
        for table in sorted(GUILD_SCOPED_TABLES):
            assert not _table_exists(table), (
                f"tenant table {table!r} must not exist in public — guild "
                "content lives only in guild schemas"
            )

    def test_upgrade_head_is_idempotent(self, fresh_migrations_db: str) -> None:
        """Running ``upgrade head`` twice must not raise. Catches
        accidental non-idempotent DDL."""
        _run_alembic("upgrade", "head")
        rev_after_first = _current_alembic_revision()
        _run_alembic("upgrade", "head")
        rev_after_second = _current_alembic_revision()
        assert rev_after_first == rev_after_second, (
            "Repeated `alembic upgrade head` changed the version stamp — "
            "a migration is not idempotent."
        )

    def test_step_by_step_upgrade_from_base_to_head(
        self, fresh_migrations_db: str
    ) -> None:
        """Apply each revision one at a time and check the stamp after
        every step. Catches partial failures that ``upgrade head``
        might paper over."""
        revisions = _ordered_revisions_base_to_head()
        # Make the chain-order invariant explicit: revisions[0] must be
        # the baseline. Without this, a misconfigured chain that placed
        # something before the baseline would cause the slice below to
        # silently skip a real migration.
        assert revisions[0] == BASELINE_REVISION, (
            f"Expected first revision to be the baseline {BASELINE_REVISION!r}, "
            f"got {revisions[0]!r}. The migration chain is misconfigured."
        )

        # Hold the migration lock across the whole chain (not per step) so the
        # transient cluster-global automation_engine role (0068→0077) is never
        # exposed to a concurrent worker's DROP ROLE. See the helper's docstring.
        asyncio.run(_run_upgrade_chain_locked_async(revisions))

    def test_full_round_trip_down_to_first_reversible_then_back(
        self, fresh_migrations_db: str
    ) -> None:
        """Walks: base → head → (down across every reversible migration) → head.

        Stops the downgrade at the first migration above an irreversible
        boundary. Every reversible downgrade actually runs; missing or
        broken downgrades are the main cause of broken release
        rollbacks, so this is the single highest-value DB test here.
        """
        script = _script_directory()
        head = script.get_current_head()

        # The reversible walk normally starts at the head. But when the head
        # (or a run of revisions below it) is intentionally irreversible — its
        # own ``downgrade()`` raises — we can't descend through it, so anchor
        # the walk at the highest reversible revision by stepping down past
        # every irreversible one at the top. Every reachable reversible
        # downgrade below the boundary still runs; the irreversible heads' own
        # upgrades are covered by the TestMostRecentRevision tests.
        anchor = head
        while anchor in INTENTIONALLY_IRREVERSIBLE:
            parent = script.get_revision(anchor).down_revision
            if parent is None:
                # Walked off the base: the entire chain is irreversible (e.g.
                # right after a squash — only the baseline + reconciler exist,
                # both roll-forward-only). Nothing reversible to round-trip;
                # TestMostRecentRevision covers the head's own upgrade.
                pytest.skip("no reversible migration above the irreversible baseline")
            assert isinstance(parent, str), (
                f"Irreversible revision {anchor!r} has multiple parents "
                f"{parent!r}; the round-trip walk only handles linear chains."
            )
            anchor = parent

        _run_alembic("upgrade", anchor)
        assert _current_alembic_revision() == anchor

        steps_taken = 0
        while True:
            current = _current_alembic_revision()
            assert current is not None
            if current in INTENTIONALLY_IRREVERSIBLE:
                # We're now at an irreversible revision — its own
                # ``downgrade()`` would raise. Stop here.
                break
            rev_obj = script.get_revision(current)
            parent = rev_obj.down_revision
            if parent is None:
                break  # at base
            # Fail loud on merge revisions (down_revision is a tuple) — the
            # stamp-equality check below would silently false-fail otherwise.
            assert isinstance(parent, str), (
                f"Revision {current} has multiple parents {parent!r}; the "
                "round-trip walk only handles linear chains. If a merge "
                "migration is intentional, extend this loop to handle it."
            )
            _run_alembic("downgrade", "-1")
            steps_taken += 1
            stamp = _current_alembic_revision()
            assert stamp == parent, (
                f"downgrade -1 from {current} should land on {parent}, got {stamp!r}"
            )

        assert steps_taken > 0, (
            "Expected at least one reversible migration above the "
            "irreversible boundary; took zero steps. Check "
            "INTENTIONALLY_IRREVERSIBLE."
        )

        _run_alembic("upgrade", anchor)
        assert _current_alembic_revision() == anchor

    def test_baseline_downgrade_raises(self, fresh_migrations_db: str) -> None:
        """The baseline cannot be downgraded — verify it actually raises
        rather than silently succeeding."""
        _run_alembic("upgrade", BASELINE_REVISION)
        with pytest.raises(NotImplementedError):
            _run_alembic("downgrade", "base")

    def test_alembic_version_table_has_single_row_after_upgrade(
        self, fresh_migrations_db: str
    ) -> None:
        """A common corruption mode is multiple rows in
        ``alembic_version`` after a botched merge. ``upgrade head`` must
        keep the table at exactly one row."""
        _run_alembic("upgrade", "head")
        assert _alembic_version_row_count() == 1


class TestMostRecentRevision:
    """Targeted tests against the most-recent (head) revision.

    These give a tight signal when *the migration you just wrote* is
    broken. They run faster than the full chain walk because they only
    exercise the head revision in isolation: bring the database to
    head's parent, then upgrade by one step and (if the head is
    reversible) downgrade and re-upgrade.

    Failures here mean the newest migration on the chain — the one
    most likely to be wrong because it's the one you just changed —
    cannot be applied, cannot be rolled back, or cannot be re-applied
    after a rollback.
    """

    def test_head_upgrade_from_parent(self, fresh_migrations_db: str) -> None:
        """Upgrade to the head's parent, then apply the head. Isolates
        failures in the newest migration from failures earlier in the
        chain."""
        script = _script_directory()
        head = script.get_current_head()
        assert head is not None, "alembic could not determine a head revision"

        head_rev = script.get_revision(head)
        parent = head_rev.down_revision
        assert isinstance(parent, str) and parent, (
            f"Head revision {head!r} has no single parent (down_revision={parent!r}); "
            "the chain may have branched."
        )

        _run_alembic("upgrade", parent)
        assert _current_alembic_revision() == parent, (
            f"Could not stage the database at head's parent {parent!r}"
        )

        _run_alembic("upgrade", head)
        assert _current_alembic_revision() == head, (
            f"Applying the head revision {head!r} did not advance the stamp "
            "as expected — the newest migration's upgrade() is broken."
        )

    def test_head_downgrade_then_reapply(self, fresh_migrations_db: str) -> None:
        """If the head is reversible, downgrading by one step from head
        and re-applying must round-trip cleanly. Exercises the newest
        migration's downgrade() and proves a release rollback would
        work right now."""
        script = _script_directory()
        head = script.get_current_head()
        assert head is not None

        if head in INTENTIONALLY_IRREVERSIBLE:
            pytest.skip(
                f"Head revision {head} is intentionally irreversible; "
                "cannot test downgrade round-trip."
            )

        head_rev = script.get_revision(head)
        parent = head_rev.down_revision
        assert isinstance(parent, str) and parent

        _run_alembic("upgrade", "head")
        assert _current_alembic_revision() == head

        _run_alembic("downgrade", "-1")
        assert _current_alembic_revision() == parent, (
            f"Downgrading from head {head!r} should land on {parent!r}, "
            f"got {_current_alembic_revision()!r}. The newest migration's "
            "downgrade() is broken or incomplete."
        )

        _run_alembic("upgrade", head)
        assert _current_alembic_revision() == head, (
            f"Re-upgrading to head {head!r} after downgrade failed. The "
            "newest migration is not reversible end-to-end (downgrade may "
            "leave behind state that the upgrade does not expect)."
        )

    def test_head_upgrade_is_idempotent(self, fresh_migrations_db: str) -> None:
        """Re-running the head migration after it's already applied
        must be a no-op. Catches accidental ``CREATE`` / ``ADD COLUMN``
        without ``IF NOT EXISTS`` guards on the newest migration."""
        _run_alembic("upgrade", "head")
        head_first = _current_alembic_revision()
        _run_alembic("upgrade", "head")
        head_second = _current_alembic_revision()
        assert head_first == head_second
        assert head_second == _script_directory().get_current_head()
