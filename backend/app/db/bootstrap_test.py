"""The privileged bootstrap declares what the app's own logins cannot create.

The module is the single source for two things a deployment needs before the
app can connect as its least-privilege roles: the login roles themselves, and
the guild-search match operator. These cover what that SQL must contain and how
the roles are read from the connection URLs; ``search_operator_test`` covers the
objects actually landing in a database.
"""

from __future__ import annotations

import pytest

from app.db.bootstrap import (
    _SEARCH_OPERATOR_STEPS,
    LoginRole,
    bootstrap_sql,
    login_roles,
)


def _search_operator_statements() -> tuple[str, ...]:
    """The statements that install the guild-search match operator, in order."""
    return tuple(statement for _label, statement in _SEARCH_OPERATOR_STEPS)


def test_roles_come_from_the_connection_urls(monkeypatch):
    """A deployment is free to name its logins; the bootstrap maintains
    whichever ones the URLs actually connect as."""
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://prov:pw1@h:5432/d"
    )
    monkeypatch.setattr(
        settings, "DATABASE_URL_APP", "postgresql+asyncpg://req:pw2@h:5432/d"
    )
    monkeypatch.setattr(
        settings, "DATABASE_URL_ADMIN", "postgresql+asyncpg://sys:pw3@h:5432/d"
    )
    provisioner, app_login, system = login_roles()
    assert (provisioner.name, provisioner.password) == ("prov", "pw1")
    assert (app_login.name, app_login.password) == ("req", "pw2")
    assert (system.name, system.password) == ("sys", "pw3")


def test_an_owner_database_url_gives_the_bootstrap_the_derived_logins(monkeypatch):
    """With DATABASE_URL as the owner, the bootstrap runs as that owner and
    maintains the canonical logins under their derived passwords."""
    from pydantic_settings import SettingsConfigDict

    from app.core.config import Settings, derive_database_password
    from app.db import bootstrap

    class _Hermetic(Settings):
        model_config = SettingsConfigDict(env_file=None)

    key = "f2d8a1c4b7e90365d4a2f8c1b6e3079a5c8d2e4f6a1b3c5d7e9f0a2b4c6d8e1f"
    owner = "postgresql+asyncpg://owner:pw@h:5432/d"
    resolved = _Hermetic(
        SECRET_KEY=key,
        DATABASE_URL=owner,
        DATABASE_URL_APP="",
        DATABASE_URL_ADMIN="",
    )
    monkeypatch.setattr(bootstrap, "settings", resolved)

    assert resolved.DATABASE_URL_BOOTSTRAP == owner
    assert bootstrap.owner_setting() == "DATABASE_URL"
    provisioner, app_login, system = login_roles()
    for role, name in (
        (provisioner, "app_provisioner"),
        (app_login, "app_user"),
        (system, "app_admin"),
    ):
        assert (role.name, role.password) == (name, derive_database_password(key, name))


def test_role_attributes_are_the_documented_ones():
    provisioner, app_login, system = login_roles()
    assert "CREATEROLE" in provisioner.attributes
    assert "NOSUPERUSER" in provisioner.attributes
    assert "NOBYPASSRLS" in provisioner.attributes
    assert "NOINHERIT" in app_login.attributes
    assert "BYPASSRLS" in system.attributes


def test_a_url_without_credentials_falls_back_to_the_canonical_name(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL_APP", "postgresql+asyncpg://h/d")
    _provisioner, app_login, _system = login_roles()
    assert app_login.name == "app_user"
    assert app_login.password is None


def test_printed_sql_covers_both_halves():
    body = bootstrap_sql()
    # Roles, database and schema ownership.
    assert "CREATE" in body and "ALTER" in body
    assert "GRANT CREATE, CONNECT, TEMPORARY ON DATABASE" in body
    assert "ALTER SCHEMA public OWNER TO" in body
    assert "WITH ADMIN OPTION" in body
    # The search operator.
    assert "LEAKPROOF" in body
    assert "tsvector_search_ops" in body


def test_printed_sql_is_wrapped_in_one_transaction():
    body = bootstrap_sql()
    assert body.startswith("--")
    assert "\nBEGIN;\n" in body
    assert body.rstrip().endswith("COMMIT;")


def test_the_match_function_is_declared_leakproof():
    """Postgres accepts the attribute only from a superuser, and the planner
    needs it to use the index here."""
    statements = _search_operator_statements()
    function = next(s for s in statements if "CREATE OR REPLACE FUNCTION" in s)
    assert "LEAKPROOF" in function
    assert "LANGUAGE plpgsql" in function


def test_the_stock_operator_is_not_touched():
    joined = "\n".join(_search_operator_statements())
    assert "public.@@@" in joined
    assert "CREATE OPERATOR pg_catalog" not in joined


def test_a_role_that_is_already_a_superuser_keeps_what_it_has():
    """The provisioner's shape is applied to an existing superuser without the
    clauses that would take privileges off it.

    An install predating ``app_provisioner`` names the same role in
    ``DATABASE_URL`` and ``DATABASE_URL_BOOTSTRAP`` — the cluster's own
    bootstrap role, which Postgres will not let anyone demote.
    """
    provisioner, _app_login, _system = login_roles()
    kept = provisioner.attributes_if_superuser.split()
    assert kept == ["LOGIN", "CREATEROLE"]


def test_the_printed_sql_carries_both_shapes():
    """``--print-sql`` runs the same statements, so it needs the same settings."""
    body = bootstrap_sql()
    assert body.count("set_config('app._bootstrap_attrs'") == 3
    assert body.count("set_config('app._bootstrap_attrs_superuser'") == 3


@pytest.mark.parametrize(
    ("created_with", "attribute", "expected"),
    [
        # An install predating app_provisioner names one role in both
        # DATABASE_URL and DATABASE_URL_BOOTSTRAP — the cluster's own bootstrap
        # role, which Postgres will not let anyone demote.
        ("SUPERUSER", "rolsuper", True),
        # The counterpart: an ordinary role still converges on the shape, so a
        # provisioner created with more than it needs gives it up.
        ("BYPASSRLS", "rolbypassrls", False),
    ],
)
async def test_the_provisioner_shape_on_an_existing_role(
    created_with, attribute, expected
):
    """What applying the provisioner's attributes does to a role that is
    already there, by what that role already holds."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.bootstrap import _ensure_role_steps, _run_steps
    from conftest import RUN_ID, TEST_DATABASE_URL

    # Roles are cluster-global; key the probe to this run so concurrent
    # checkouts and xdist workers never drop each other's.
    name = f"test_{RUN_ID}_probe_{created_with.lower()}"
    provisioner, _app_login, _system = login_roles()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
            await conn.execute(text(f'CREATE ROLE "{name}" {created_with}'))
        try:
            async with engine.begin() as conn:
                await _run_steps(
                    conn,
                    _ensure_role_steps(LoginRole(name, None, provisioner.attributes)),
                )
                held = await conn.scalar(
                    text(f"SELECT {attribute} FROM pg_roles WHERE rolname = :n"),
                    {"n": name},
                )
            assert held is expected
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
    finally:
        await engine.dispose()


@pytest.mark.parametrize("password", ["derived-0f3a9c", "pässwörd\u00a0\ufb01x"])
async def test_a_login_signs_in_with_the_password_its_verifier_was_made_from(
    password,
):
    """The bootstrap sets a login by its verifier, and the password itself
    signs in: Postgres prepares and hashes it the same way."""
    from sqlalchemy import make_url, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.bootstrap import _ensure_role_steps, _run_steps
    from conftest import RUN_ID, TEST_DATABASE_URL

    name = f"test_{RUN_ID}_probe_scram"
    steps = _ensure_role_steps(LoginRole(name, password, "LOGIN"))
    assert password not in repr(steps)
    owner = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    signed_in = create_async_engine(
        make_url(TEST_DATABASE_URL).set(username=name, password=password),
        poolclass=NullPool,
    )
    try:
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
            await _run_steps(conn, steps)
            await conn.execute(
                text(
                    f"DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO "
                    f'"{name}"\', current_database()); END $$'
                )
            )
        try:
            async with signed_in.connect() as conn:
                assert await conn.scalar(text("SELECT current_user")) == name
        finally:
            async with owner.begin() as conn:
                await conn.execute(
                    text(
                        f"DO $$ BEGIN EXECUTE format('REVOKE ALL ON DATABASE %I "
                        f'FROM "{name}"\', current_database()); END $$'
                    )
                )
                await conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
    finally:
        await signed_in.dispose()
        await owner.dispose()


def _guc_keys(sql: str, call: str) -> set[str]:
    """The ``app._bootstrap_*`` settings ``sql`` names in ``call('<key>'``."""
    keys: set[str] = set()
    marker = f"{call}('app._bootstrap"
    start = 0
    while (opened := sql.find(marker, start)) != -1:
        key_at = opened + len(call) + 2
        closed = sql.index("'", key_at)
        keys.add(sql[key_at:closed])
        start = closed
    return keys


def test_the_printed_sql_sets_every_setting_it_reads():
    """``--print-sql`` has to run unattended.

    Its statements read their inputs from session settings, so each one has to
    be emitted alongside them; a statement whose setting is missing stops the
    script on ``unrecognized configuration parameter``.
    """
    body = bootstrap_sql()
    read = _guc_keys(body, "current_setting")
    written = _guc_keys(body, "set_config")
    assert read <= written, f"read but never set: {sorted(read - written)}"


def test_the_printed_handover_runs_rather_than_prints():
    """The script is piped into psql unattended, so a step that only *displays*
    the work is a step nobody does.

    The ownership handover used to be emitted as the bare query plus a comment
    saying to run what it returned. A fresh install has nothing to hand over
    and never noticed; a database already running under another login — which
    is the only kind that reaches this step — was left with its objects still
    owned by the outgoing login, and the next boot failed on "must be owner
    of".
    """
    body = bootstrap_sql()
    assert "DO $handover$" in body
    assert "EXECUTE statements[i]" in body
    assert "run what it" not in body


def test_the_printed_handover_and_the_app_run_one_query():
    """Both forms are built from ``_TRANSFER_STATEMENTS``; a second copy is a
    second handover to keep in step."""
    from app.db.bootstrap import _TRANSFER_STATEMENTS

    assert _TRANSFER_STATEMENTS.strip() in bootstrap_sql()


async def test_the_wrapper_executes_every_statement_it_is_given(session):
    """Proved on a stub query, not the real one: the real one would move the
    ownership of every object in this worker's database."""
    from sqlalchemy import text

    from app.db.bootstrap import _executing

    block = _executing(
        "SELECT 'probe' AS label, "
        "$stmt$SELECT set_config('app._handover_probe', 'ran', true)$stmt$ AS stmt"
    )
    await session.exec(text(block))
    ran = (
        await session.exec(text("SELECT current_setting('app._handover_probe', true)"))
    ).one()
    assert ran[0] == "ran"


async def test_the_wrapper_is_a_no_op_when_there_is_nothing_to_move(session):
    """A fresh install renders the same block and must pass straight through
    it."""
    from sqlalchemy import text

    from app.db.bootstrap import _executing

    block = _executing("SELECT NULL::text AS label, NULL::text AS stmt WHERE false")
    await session.exec(text(block))


async def test_nothing_is_said_when_the_connecting_login_owns_its_objects(session):
    """The ordinary case, and the one a warning must not fire on: the test
    database was handed to the declared provisioner by conftest's bootstrap,
    so the handover would move nothing."""
    from app.db.bootstrap import owners_to_hand_over

    owners = await owners_to_hand_over(
        await session.connection(), login_roles()[0].name
    )
    assert not owners, f"the handover would still move objects owned by {owners}"


async def test_an_object_owned_elsewhere_is_seen(session):
    """A table in a guild schema owned by another login is what the warning is
    for; one owned by a role the handover keeps as an owner (a reader's view,
    such as ``entity_presence``) is not."""
    from sqlalchemy import text

    from app.db.bootstrap import owners_to_hand_over
    from conftest import RUN_ID

    other = f"owner_probe_{RUN_ID}"
    kept = "app_presence_reader"
    tables = (f"owner_probe_{RUN_ID}", f"kept_probe_{RUN_ID}")
    await session.exec(text(f'CREATE ROLE "{other}"'))
    try:
        await session.exec(text("CREATE SCHEMA IF NOT EXISTS guild_template"))
        for table, owner in zip(tables, (other, kept), strict=True):
            await session.exec(text(f"CREATE TABLE guild_template.{table} (id int)"))
            await session.exec(
                text(f'ALTER TABLE guild_template.{table} OWNER TO "{owner}"')
            )
        owners = await owners_to_hand_over(
            await session.connection(), login_roles()[0].name
        )
        assert other in owners
        assert kept not in owners
    finally:
        for table in tables:
            await session.exec(text(f"DROP TABLE IF EXISTS guild_template.{table}"))
        await session.exec(text(f'DROP ROLE IF EXISTS "{other}"'))


def test_the_bootstrap_keeps_the_functions_it_installs():
    """The handover's exclusion list names functions the bootstrap creates.

    The two have to agree: a function the bootstrap re-asserts on every boot
    but hands away can no longer be replaced by the login doing the asserting.
    """
    from app.db.bootstrap import BOOTSTRAP_OWNED_FUNCTIONS

    installed = "\n".join(_search_operator_statements())
    for name in BOOTSTRAP_OWNED_FUNCTIONS:
        assert f"public.{name}(" in installed, (
            f"{name} is excluded from the ownership handover but the bootstrap "
            f"does not install it"
        )


async def test_the_handover_claims_every_function_the_outgoing_login_owns(session):
    """A database moved to the provisioning role hands over all of its own
    ``public`` functions, not only the ones a trigger or policy points at.

    A plpgsql body records no dependency on what it calls, so a helper reached
    only from another function's body — ``search_entry_write``, called from
    inside ``refresh_search_entry`` — looks unreferenced in the catalog. The
    probe below stands for one. Left behind, it keeps the outgoing owner and
    the next boot cannot replace it.

    A fresh database has nothing to hand over, which is why the probe is
    created here rather than looked for: this is the case CI never builds.
    """
    from sqlalchemy import text

    from app.db.bootstrap import _TRANSFER_STATEMENTS, BOOTSTRAP_OWNED_FUNCTIONS
    from app.db.public_rls import SHARED_TABLE_REGISTRY
    from conftest import RUN_ID

    async def set_local(key: str, value: str) -> None:
        await session.exec(
            text("SELECT set_config(:k, :v, true)").bindparams(k=key, v=value)
        )

    probe = f"test_{RUN_ID}_unreferenced_helper"
    await session.exec(
        text(
            f"CREATE FUNCTION public.{probe}() RETURNS void "
            f"LANGUAGE plpgsql AS $probe$ BEGIN END $probe$"
        )
    )
    try:
        await set_local("app._bootstrap_role", "handover_target")
        await set_local(
            "app._bootstrap_tables", ",".join(sorted(SHARED_TABLE_REGISTRY))
        )
        await set_local(
            "app._bootstrap_functions", ",".join(sorted(BOOTSTRAP_OWNED_FUNCTIONS))
        )
        await set_local("app._bootstrap_kept_owners", "")

        claimed = {
            label.removeprefix("function ")
            for label, _stmt, _owner in (
                await session.exec(text(_TRANSFER_STATEMENTS))
            ).all()
            if label.startswith("function ")
        }
        owned = {
            row[0]
            for row in (
                await session.exec(
                    text(
                        "SELECT p.oid::regprocedure::text FROM pg_proc p "
                        " WHERE p.pronamespace = 'public'::regnamespace "
                        "   AND p.proowner = current_user::regrole "
                        "   AND NOT p.proname = ANY(:kept) "
                        "   AND NOT EXISTS (SELECT 1 FROM pg_depend d "
                        "                    WHERE d.objid = p.oid AND d.deptype = 'e')"
                    ).bindparams(kept=list(BOOTSTRAP_OWNED_FUNCTIONS))
                )
            ).all()
        }

        assert f"{probe}()" in owned, "the probe did not land where the query looks"
        assert owned - claimed == set(), f"left behind: {sorted(owned - claimed)}"
    finally:
        await session.exec(text(f"DROP FUNCTION IF EXISTS public.{probe}()"))


async def test_the_handover_leaves_alone_what_a_login_never_held(session):
    """The match function is installed over the bootstrap connection and
    re-asserted from it on every boot, so it stays with that login. A function
    a migration gave to one of the app's shared roles stays with that role."""
    from sqlalchemy import text

    from app.db.bootstrap import (
        _TRANSFER_STATEMENTS,
        BOOTSTRAP_OWNED_FUNCTIONS,
        SEARCH_MATCH_FUNCTION,
        _kept_owners,
    )
    from app.db.public_rls import SHARED_TABLE_REGISTRY
    from conftest import RUN_ID

    async def set_local(key: str, value: str) -> None:
        await session.exec(
            text("SELECT set_config(:k, :v, true)").bindparams(k=key, v=value)
        )

    await set_local("app._bootstrap_role", "handover_target")
    await set_local("app._bootstrap_tables", ",".join(sorted(SHARED_TABLE_REGISTRY)))
    await set_local(
        "app._bootstrap_functions", ",".join(sorted(BOOTSTRAP_OWNED_FUNCTIONS))
    )
    await set_local("app._bootstrap_kept_owners", _kept_owners())

    owner = (
        await session.exec(
            text(
                "SELECT pg_get_userbyid(p.proowner) = current_user FROM pg_proc p "
                " WHERE p.pronamespace = 'public'::regnamespace "
                "   AND p.proname = :match_fn"
            ).bindparams(match_fn=SEARCH_MATCH_FUNCTION)
        )
    ).first()
    assert owner is not None and owner[0], (
        f"{SEARCH_MATCH_FUNCTION} is not owned by this login, so this proves nothing"
    )

    definer = f"test_{RUN_ID}_reader_definer"
    await session.exec(
        text(
            f"CREATE FUNCTION public.{definer}() RETURNS boolean "
            f"LANGUAGE sql SECURITY DEFINER AS $probe$ SELECT true $probe$"
        )
    )
    try:
        await session.exec(
            text(f"ALTER FUNCTION public.{definer}() OWNER TO app_dm_reader")
        )
        labels = [
            label
            for label, _stmt, _owner in (
                await session.exec(text(_TRANSFER_STATEMENTS))
            ).all()
        ]
    finally:
        await session.exec(text(f"DROP FUNCTION IF EXISTS public.{definer}()"))
    assert not any(SEARCH_MATCH_FUNCTION in label for label in labels)
    assert not any(definer in label for label in labels), labels


async def test_the_handover_claims_an_object_owned_by_a_third_login(session):
    """The outgoing owner need not be the login running the handover.

    An install that has changed hands more than once holds objects belonging to
    a login the bootstrap connection is neither, and those are exactly the ones
    a migration's ``CREATE OR REPLACE`` then cannot touch. Read-only: the query
    is asked what it would move, not told to move it.
    """
    from sqlalchemy import text

    from app.db.bootstrap import _TRANSFER_STATEMENTS
    from app.db.public_rls import SHARED_TABLE_REGISTRY
    from conftest import RUN_ID

    provisioner = login_roles()[0].name
    other = f"third_owner_{RUN_ID}"
    table = f"third_owner_probe_{RUN_ID}"
    await session.exec(text(f'CREATE ROLE "{other}"'))
    try:
        await session.exec(text("CREATE SCHEMA IF NOT EXISTS guild_template"))
        await session.exec(text(f"CREATE TABLE guild_template.{table} (id int)"))
        await session.exec(
            text(f'ALTER TABLE guild_template.{table} OWNER TO "{other}"')
        )
        for key, value in (
            ("app._bootstrap_role", provisioner),
            ("app._bootstrap_tables", ",".join(sorted(SHARED_TABLE_REGISTRY))),
            ("app._bootstrap_functions", ""),
            ("app._bootstrap_kept_owners", ""),
        ):
            await session.exec(
                text("SELECT set_config(:key, :value, true)").bindparams(
                    key=key, value=value
                )
            )
        moves = {
            row[0]: row[1]
            for row in (await session.exec(text(_TRANSFER_STATEMENTS))).all()
        }
        label = f"table guild_template.{table}"
        assert label in moves, (
            f"a table owned by {other!r} was not claimed for {provisioner!r}: "
            f"{sorted(moves)}"
        )
        assert f'OWNER TO "{provisioner}"' in moves[label] or (
            f"OWNER TO {provisioner}" in moves[label]
        )
    finally:
        await session.exec(text(f"DROP TABLE IF EXISTS guild_template.{table}"))
        await session.exec(text(f'DROP ROLE IF EXISTS "{other}"'))


async def test_the_handover_leaves_alone_what_the_target_already_owns(session):
    """The provisioning login's own objects are not statements to run."""
    from sqlalchemy import text

    from app.db.bootstrap import _TRANSFER_STATEMENTS
    from app.db.public_rls import SHARED_TABLE_REGISTRY
    from conftest import RUN_ID

    provisioner = login_roles()[0].name
    table = f"own_owner_probe_{RUN_ID}"
    await session.exec(text("CREATE SCHEMA IF NOT EXISTS guild_template"))
    await session.exec(text(f"CREATE TABLE guild_template.{table} (id int)"))
    try:
        await session.exec(
            text(f'ALTER TABLE guild_template.{table} OWNER TO "{provisioner}"')
        )
        for key, value in (
            ("app._bootstrap_role", provisioner),
            ("app._bootstrap_tables", ",".join(sorted(SHARED_TABLE_REGISTRY))),
            ("app._bootstrap_functions", ""),
            ("app._bootstrap_kept_owners", ""),
        ):
            await session.exec(
                text("SELECT set_config(:key, :value, true)").bindparams(
                    key=key, value=value
                )
            )
        labels = [
            row[0] for row in (await session.exec(text(_TRANSFER_STATEMENTS))).all()
        ]
        assert f"table guild_template.{table}" not in labels
    finally:
        await session.exec(text(f"DROP TABLE IF EXISTS guild_template.{table}"))


async def test_a_shared_role_the_provisioner_administers_is_left_alone():
    """Granting the provisioner ADMIN again would lock the role, which a
    community being provisioned elsewhere may hold: one the provisioner
    already administers is skipped, so the start never waits on it."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.bootstrap import _administer_existing_roles
    from app.db.public_rls import role_name
    from conftest import RUN_ID, TEST_DATABASE_URL

    shared = role_name("app_billing_log")
    holder = f"test_{RUN_ID}_lock_holder"
    provisioner = login_roles()[0].name
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as other:
            # A grant of the shared role, left open, holds its lock.
            held = await other.begin()
            await other.execute(text(f'CREATE ROLE "{holder}"'))
            await other.execute(text(f'GRANT "{shared}" TO "{holder}"'))
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL lock_timeout = '2s'"))
                    await conn.execute(
                        text("SELECT set_config('app._bootstrap_role', :p, true)"),
                        {"p": provisioner},
                    )
                    await conn.execute(text(_administer_existing_roles()))
            finally:
                await held.rollback()
    finally:
        await engine.dispose()
