"""The privileged database bootstrap, in one place.

Two things have to exist in the cluster before the app can run as its own
least-privilege logins, and neither can be created *by* those logins:

* **The three login roles** — the provisioning role that owns the app's objects
  and runs migrations, the RLS-enforced request login, and the system-engine
  login — plus the database grants and ``public`` ownership they need.
* **The guild-search match operator** — a ``LEAKPROOF`` function, an operator
  over it, and a GIN operator class. Postgres accepts ``LEAKPROOF`` only from a
  superuser (``only superuser can define a leakproof function``), so this stays
  a privileged step no matter how the roles are arranged.

Both are declared here and applied from a connection opened as the database
owner, which is disposed before the app serves anything —
the request path keeps running on the three logins above. Every statement is
idempotent and re-applied on each boot, so rotating a role password, upgrading
into a release that adds a privileged object, and restoring a dump that carried
no role attributes all converge without hand-run SQL.

When ``DATABASE_URL_BOOTSTRAP`` is unset the same invariants are *verified*
instead: a deployment that provisions its database out of band (managed
Postgres, a Kubernetes operator, a DBA) boots normally when they hold, and
stops with the exact SQL when they do not. ``--print-sql`` emits that SQL.

That owner connection is ``DATABASE_URL`` when the deployment gives only that
one URL (the app then names its logins and derives their passwords, see
``app.core.config``), and ``DATABASE_URL_BOOTSTRAP`` when it names the three
logins itself.

Run standalone with ``python -m app.db.bootstrap``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import stringprep
import unicodedata
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import DATABASE_LOGINS, settings
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_migrations import GUILD_OR_TEMPLATE_SCHEMA_REGEX
from app.db.public_rls import (
    PLATFORM_ROUTES,
    SHARED_ROLES,
    SHARED_TABLE_REGISTRY,
    platform_tier,
    role_name,
)

logger = logging.getLogger(__name__)

#: Tried in order for the cluster-wide bootstrap lock. Both are conventionally
#: present; a provider that exposes neither falls back to the per-database lock.
#:
#: Role DDL writes shared catalogs, so two starts at once can collide there.
#: An advisory lock's key space is per-database, which is enough for replicas of
#: one deployment (they share a database) but not for two deployments on one
#: cluster. So the lock is taken on the cluster's maintenance database when that
#: is reachable, and on the app's own database otherwise — the latter still
#: covers the replica case, which is the one a deployment creates for itself.
#:
#: Two deployments sharing a cluster should not share login-role names; the
#: names come from the connection URLs precisely so they need not.
_MAINTENANCE_DATABASES = ("postgres", "template1")

#: Clauses that take a privilege away from a role that already holds it. The
#: bootstrap creates the logins the app needs; a role the deployment already
#: runs as a superuser keeps the attributes it has. Postgres refuses to remove
#: SUPERUSER from the cluster's own bootstrap role at all, and that is the role
#: an install predating ``app_provisioner`` names in both ``DATABASE_URL`` and
#: ``DATABASE_URL_BOOTSTRAP``.
_DEMOTING_CLAUSES = frozenset({"NOSUPERUSER", "NOBYPASSRLS"})


@dataclass(frozen=True)
class LoginRole:
    """One login the bootstrap maintains, as named by its connection URL."""

    name: str
    password: str | None
    attributes: str

    @property
    def attributes_if_superuser(self) -> str:
        """The same shape, minus the clauses that would demote the role."""
        return " ".join(
            word for word in self.attributes.split() if word not in _DEMOTING_CLAUSES
        )


@dataclass(frozen=True)
class BootstrapResult:
    applied: bool
    roles: tuple[str, ...]
    search_operator_installed: bool
    notes: tuple[str, ...] = ()


def owner_setting() -> str:
    """The setting an operator edits to change the owner connection."""
    return (
        "DATABASE_URL" if settings.database_logins_derived else "DATABASE_URL_BOOTSTRAP"
    )


#: The attributes each login is held to, keyed by the setting that names it.
_LOGIN_ATTRIBUTES = {
    "DATABASE_URL": "LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS",
    "DATABASE_URL_APP": "LOGIN NOINHERIT",
    "DATABASE_URL_ADMIN": "LOGIN BYPASSRLS",
}


def login_roles() -> tuple[LoginRole, LoginRole, LoginRole]:
    """The three logins to maintain: provisioner, request login, system engine.

    Deployments are free to name their logins something other than the
    canonical names; the bootstrap maintains whatever the URLs actually
    connect as, the same way the system-engine check reads ``current_user``.
    """
    provisioner, app_login, system = (
        LoginRole(*settings.database_login(setting), _LOGIN_ATTRIBUTES[setting])
        for setting, _name in DATABASE_LOGINS
    )
    return provisioner, app_login, system


# --- Role and database statements ------------------------------------------
#
# Role DDL takes no bind parameters, so the name and password travel as
# transaction-local GUCs and are quoted server-side with format(%I) / format(%L)
# — the same shape the baseline migration's role DDL uses. The password goes as
# the SCRAM-SHA-256 verifier Postgres stores (:func:`scram_verifier`), as
# psql's ``\password`` sends it.

#: The iteration count of a verifier, Postgres's own ``scram_iterations``
#: default.
SCRAM_ITERATIONS = 4096

#: The characters RFC 4013 refuses in a prepared password.
_SASLPREP_PROHIBITED = (
    stringprep.in_table_c12,
    stringprep.in_table_c21,
    stringprep.in_table_c22,
    stringprep.in_table_c3,
    stringprep.in_table_c4,
    stringprep.in_table_c5,
    stringprep.in_table_c6,
    stringprep.in_table_c7,
    stringprep.in_table_c8,
    stringprep.in_table_c9,
    stringprep.in_table_a1,
)


def _saslprep(password: str) -> str:
    """``password`` as Postgres prepares it before hashing (``pg_saslprep``,
    RFC 4013): an ASCII password as it is, and one the profile refuses as
    given."""
    if password.isascii():
        return password
    mapped = "".join(
        " " if stringprep.in_table_c12(char) else char
        for char in password
        if not stringprep.in_table_b1(char)
    )
    prepared = unicodedata.normalize("NFKC", mapped)
    if any(test(char) for char in prepared for test in _SASLPREP_PROHIBITED):
        return password
    right_to_left = [stringprep.in_table_d1(char) for char in prepared]
    if any(right_to_left) and (
        any(stringprep.in_table_d2(char) for char in prepared)
        or not (right_to_left[0] and right_to_left[-1])
    ):
        return password
    return prepared


def scram_verifier(password: str) -> str:
    """``password`` as the SCRAM-SHA-256 verifier Postgres keeps for it
    (RFC 5802, RFC 7677), with a fresh salt. Postgres stores a password given
    in this form as it is."""
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac(
        "sha256", _saslprep(password).encode(), salt, SCRAM_ITERATIONS
    )
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    encoded = [base64.b64encode(raw).decode() for raw in (salt, stored_key, server_key)]
    return f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{encoded[0]}${encoded[1]}:{encoded[2]}"


_ENSURE_ROLE = """
DO $$
DECLARE
    role_name text := current_setting('app._bootstrap_role');
    role_attrs text := current_setting('app._bootstrap_attrs');
    role_pw text := nullif(current_setting('app._bootstrap_pw'), '');
    already_superuser boolean;
    verb text;
BEGIN
    -- NULL when the role does not exist yet, which is what selects CREATE.
    SELECT rolsuper INTO already_superuser FROM pg_roles WHERE rolname = role_name;
    verb := CASE WHEN already_superuser IS NULL THEN 'CREATE' ELSE 'ALTER' END;
    IF already_superuser THEN
        role_attrs := current_setting('app._bootstrap_attrs_superuser');
    END IF;
    IF role_pw IS NULL THEN
        EXECUTE format('%s ROLE %I WITH %s', verb, role_name, role_attrs);
    ELSE
        EXECUTE format('%s ROLE %I WITH %s PASSWORD %L',
                       verb, role_name, role_attrs, role_pw);
    END IF;
EXCEPTION WHEN duplicate_object THEN
    -- Another process created it between the check and the CREATE; ALTER to
    -- the same shape instead.
    IF role_pw IS NULL THEN
        EXECUTE format('ALTER ROLE %I WITH %s', role_name, role_attrs);
    ELSE
        EXECUTE format('ALTER ROLE %I WITH %s PASSWORD %L',
                       role_name, role_attrs, role_pw);
    END IF;
END
$$;
"""

#: Every database privilege the provisioning role holds, whoever owns the
#: database: migrations run as that role, so they run with the same rights
#: whether the deployment gave one owner URL or named its logins.
PROVISIONER_DATABASE_PRIVILEGES = ("CREATE", "CONNECT", "TEMPORARY")

_GRANT_DATABASE = f"""
DO $$ BEGIN
    EXECUTE format('GRANT {", ".join(PROVISIONER_DATABASE_PRIVILEGES)} ON DATABASE %I TO %I',
                   current_database(), current_setting('app._bootstrap_role'));
END $$;
"""

# The request path creates no temporary objects, so it does not use the
# TEMPORARY grant PUBLIC carries by default on a new database.
_REVOKE_TEMPORARY = """
DO $$ BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC',
                   current_database());
END $$;
"""

# Only a database's owner can change its ACL; a REVOKE from any other role
# reports success and changes nothing, so read the ACL back rather than trust
# the command's exit.
_VERIFY_TEMPORARY_REVOKED = """
DO $$
DECLARE db_owner text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_database d,
             aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
        WHERE d.datname = current_database()
          AND a.grantee = 0
          AND a.privilege_type = 'TEMPORARY'
    ) THEN
        SELECT pg_get_userbyid(datdba) INTO db_owner
          FROM pg_database WHERE datname = current_database();
        RAISE EXCEPTION
            'REVOKE TEMPORARY did not take effect on database %. The '
            'bootstrap connection must be its owner (%).',
            current_database(), db_owner;
    END IF;
END
$$;
"""

# Postgres 15+ made CREATE on the public schema owner-only, and the baseline
# migration builds the shared schema there as the provisioning role.
_OWN_PUBLIC_SCHEMA = """
DO $$ BEGIN
    EXECUTE format('ALTER SCHEMA public OWNER TO %I',
                   current_setting('app._bootstrap_role'));
END $$;
"""


def _administer_existing_roles() -> str:
    """Grant the provisioner ADMIN on the roles it administers but did not
    create: the shared floors, the platform ladder and the two reader roles
    come from migrations, and per-guild roles from guild provisioning. A
    cluster-global role is created once, by whichever login got there first,
    and a ``CREATEROLE`` login holds ADMIN only on the roles it created itself
    (implicitly, PG16+), so the ones that already exist are granted here.
    A role it already administers is left alone: a grant locks the role, and
    a community being provisioned at the same moment locks the same shared
    roles in its own order. Rendered at call time, under the configured role
    prefixes.
    """
    from app.db.schema_provisioning import guild_role_regex

    names = sorted(
        {role_name(r) for r in SHARED_ROLES}
        | {role_name(platform_tier(r)) for r in PLATFORM_ROUTES}
    )
    listed = ", ".join(f"'{n}'" for n in names)
    return f"""
DO $$
DECLARE
    provisioner text := current_setting('app._bootstrap_role');
    r record;
BEGIN
    FOR r IN SELECT g.rolname FROM pg_roles g
              WHERE (g.rolname IN ({listed}) OR g.rolname ~ '{guild_role_regex()}')
                AND NOT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    JOIN pg_roles p ON p.oid = m.member
                    WHERE m.roleid = g.oid AND p.rolname = provisioner
                      AND m.admin_option)
    LOOP
        EXECUTE format('GRANT %I TO %I WITH ADMIN OPTION', r.rolname, provisioner);
    END LOOP;
END
$$;
"""


_ADMINISTER_LOGIN_ROLE = """
DO $$ BEGIN
    EXECUTE format('GRANT %I TO %I WITH ADMIN OPTION',
                   current_setting('app._bootstrap_grantee'),
                   current_setting('app._bootstrap_role'));
END $$;
"""

#: The names of the match function and operator class this module installs.
#: ``schema_provisioning`` reads them from here so each name has one home.
SEARCH_MATCH_FUNCTION = "search_tsmatch"
SEARCH_OPCLASS = "tsvector_search_ops"

#: Functions this module installs itself, over the bootstrap connection rather
#: than the provisioning one. Every boot re-asserts them with CREATE OR REPLACE
#: on that same connection, and replacing a function is an owner's right, so
#: the handover below leaves these with the login that has them.
BOOTSTRAP_OWNED_FUNCTIONS = (SEARCH_MATCH_FUNCTION,)


def _kept_owners() -> str:
    """The app's shared roles, as the handover's setting names them."""
    return ",".join(sorted(role_name(role) for role in SHARED_ROLES))


# Hand the app's objects to the provisioning role, for a database that has been
# running under another login. Postgres renders each statement so identifiers
# are quoted at the source; the caller executes what comes back and logs it.
#
# Scope is what the app can show is its own: the shared tables named in its own
# registry, the guild schemas and everything in them, the enums those tables
# use, and the functions in ``public`` the outgoing login created. Extension
# members, the bootstrap's own functions, and whatever the app's own shared
# roles own are never taken: a migration gave those to that role, and no login
# ever held them.
_TRANSFER_STATEMENTS = f"""
WITH app_tables AS (
    SELECT unnest(string_to_array(current_setting('app._bootstrap_tables'), ',')) AS name
), kept AS (
    SELECT unnest(string_to_array(current_setting('app._bootstrap_kept_owners'), ',')) AS role
), target AS (
    -- The login every statement below moves an object to. Each branch excludes
    -- what it already owns, so a re-run on a moved database returns no rows.
    SELECT current_setting('app._bootstrap_role') AS role
)
SELECT format('table %I.%I', n.nspname, c.relname) AS label,
       format('ALTER TABLE %I.%I OWNER TO %I', n.nspname, c.relname, target.role) AS stmt,
       pg_get_userbyid(c.relowner) AS owner
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace, target
 WHERE c.relkind IN ('r', 'v', 'm', 'p')
   AND pg_get_userbyid(c.relowner) <> target.role
   AND pg_get_userbyid(c.relowner) NOT IN (SELECT role FROM kept)
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')
   AND (n.nspname ~ '{GUILD_OR_TEMPLATE_SCHEMA_REGEX}'
        OR (n.nspname = 'public' AND c.relname IN (SELECT name FROM app_tables)))
UNION ALL
SELECT format('sequence %I.%I', n.nspname, c.relname),
       format('ALTER SEQUENCE %I.%I OWNER TO %I', n.nspname, c.relname, target.role),
       pg_get_userbyid(c.relowner)
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace, target
 WHERE c.relkind = 'S'
   AND pg_get_userbyid(c.relowner) <> target.role
   AND pg_get_userbyid(c.relowner) NOT IN (SELECT role FROM kept)
   AND n.nspname ~ '{GUILD_OR_TEMPLATE_SCHEMA_REGEX}'
   AND NOT EXISTS (
       SELECT 1 FROM pg_depend d
        WHERE d.objid = c.oid AND d.deptype IN ('a', 'e'))
UNION ALL
SELECT format('type public.%I', t.typname),
       format('ALTER TYPE public.%I OWNER TO %I', t.typname, target.role),
       pg_get_userbyid(t.typowner)
  FROM pg_type t, target
 WHERE t.typnamespace = 'public'::regnamespace
   AND t.typtype = 'e'
   AND pg_get_userbyid(t.typowner) <> target.role
   AND pg_get_userbyid(t.typowner) NOT IN (SELECT role FROM kept)
   AND EXISTS (
       SELECT 1 FROM pg_attribute a
         JOIN pg_class c2 ON c2.oid = a.attrelid
         JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
        WHERE a.atttypid = t.oid AND NOT a.attisdropped
          AND (n2.nspname ~ '{GUILD_OR_TEMPLATE_SCHEMA_REGEX}'
               OR (n2.nspname = 'public'
                   AND c2.relname IN (SELECT name FROM app_tables))))
UNION ALL
SELECT format('function %s', p.oid::regprocedure),
       format('ALTER FUNCTION %s OWNER TO %I', p.oid::regprocedure, target.role),
       pg_get_userbyid(p.proowner)
  FROM pg_proc p, target
 WHERE p.pronamespace = 'public'::regnamespace
   AND pg_get_userbyid(p.proowner) <> target.role
   AND pg_get_userbyid(p.proowner) NOT IN (SELECT role FROM kept)
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
   -- Every function the outgoing login left in ``public``, less the ones the
   -- bootstrap keeps. What calls a function is not something the catalog can
   -- be asked: a plpgsql body records no dependency on what it PERFORMs, so a
   -- helper reached only from another function's body, or only from the app's
   -- own SQL, is indistinguishable from an unused one.
   AND p.proname <> ALL (
       string_to_array(current_setting('app._bootstrap_functions'), ','))
UNION ALL
SELECT format('schema %I', n.nspname),
       format('ALTER SCHEMA %I OWNER TO %I', n.nspname, target.role),
       pg_get_userbyid(n.nspowner)
  FROM pg_namespace n, target
 WHERE n.nspname ~ '{GUILD_OR_TEMPLATE_SCHEMA_REGEX}'
   AND pg_get_userbyid(n.nspowner) <> target.role
   AND pg_get_userbyid(n.nspowner) NOT IN (SELECT role FROM kept)
"""


# Tables created by future provisioner-run migrations reach the routed roles
# through the two shared floors. The login roles are deliberately absent: a new
# shared table grants them nothing until a migration decides, from the audited
# registry in app.db.system_grants. Skipped until the floors exist — the
# baseline migration creates them, and the next start asserts this.
#
# app_guild_base_ro takes no default privileges. A shared table added later is
# granted to it by the migration that adds it, once somebody has decided the
# read floor should have it; guild_base_ro_parity_test is what asks. Nor does
# app_superadmin, the seat floor: it holds the community's sign-in
# configuration and nothing else until the registry in system_grants.py says
# otherwise. Nor does plugin_install_base, the floor an installed plug-in's routed
# role inherits.
def _default_privileges() -> str:
    """Rendered at call time, under the configured role prefix."""
    guild_floor, platform_floor = (
        role_name(floor) for floor in ("app_guild_base", "platform_base")
    )
    return f"""
DO $$
DECLARE
    provisioner text := current_setting('app._bootstrap_role');
    guild_floor text := '{guild_floor}';
    platform_floor text := '{platform_floor}';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = guild_floor)
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = platform_floor) THEN
        RETURN;
    END IF;
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I, %I',
        provisioner, guild_floor, platform_floor);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT SELECT, USAGE ON SEQUENCES TO %I, %I',
        provisioner, guild_floor, platform_floor);
END
$$;
"""


# --- Search operator --------------------------------------------------------
#
# Guild search matches a tsvector against a tsquery. These objects give it its
# own match operator and GIN operator class so its index can serve that match.
# The stock `@@` operator is left exactly as Postgres ships it.

# PL/pgSQL rather than SQL on purpose: a SQL body is inlined into the calling
# query, which discards the attributes declared here.
_SEARCH_MATCH_FUNCTION = """
CREATE OR REPLACE FUNCTION public.search_tsmatch(tsvector, tsquery)
    RETURNS boolean
    LANGUAGE plpgsql
    IMMUTABLE STRICT PARALLEL SAFE LEAKPROOF
    AS $fn$ BEGIN RETURN $1 OPERATOR(pg_catalog.@@) $2; END $fn$;
"""

_SEARCH_FUNCTION_COMMENT = """
COMMENT ON FUNCTION public.search_tsmatch(tsvector, tsquery) IS
    'Guild search text match, behind the public.@@@ operator. Body is PL/pgSQL '
    'so the attributes declared here survive planning.';
"""

# Selectivity estimators are the stock full-text ones, so the planner costs
# this exactly as it costs `@@`.
_SEARCH_OPERATOR = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_operator o
        JOIN pg_namespace n ON n.oid = o.oprnamespace
        WHERE n.nspname = 'public' AND o.oprname = '@@@'
          AND o.oprleft = 'tsvector'::regtype AND o.oprright = 'tsquery'::regtype
    ) THEN
        CREATE OPERATOR public.@@@ (
            LEFTARG   = tsvector,
            RIGHTARG  = tsquery,
            PROCEDURE = public.search_tsmatch,
            RESTRICT  = tsmatchsel,
            JOIN      = tsmatchjoinsel
        );
    END IF;
END
$$;
"""

# Support functions are the stock ones — only the operator differs, so an index
# built on this behaves like any tsvector GIN index.
_SEARCH_OPERATOR_CLASS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_opclass c
        JOIN pg_namespace n ON n.oid = c.opcnamespace
        WHERE n.nspname = 'public' AND c.opcname = 'tsvector_search_ops'
    ) THEN
        CREATE OPERATOR CLASS public.tsvector_search_ops
            FOR TYPE tsvector USING gin AS
            OPERATOR 1 public.@@@ (tsvector, tsquery),
            FUNCTION 1 pg_catalog.gin_cmp_tslexeme(text, text),
            FUNCTION 2 pg_catalog.gin_extract_tsvector(tsvector, internal, internal),
            FUNCTION 3 pg_catalog.gin_extract_tsquery(tsvector, internal, smallint,
                           internal, internal, internal, internal),
            FUNCTION 4 pg_catalog.gin_tsquery_consistent(internal, smallint, tsvector,
                           integer, internal, internal, internal, internal),
            FUNCTION 5 pg_catalog.gin_cmp_prefix(text, text, smallint, internal),
            FUNCTION 6 pg_catalog.gin_tsquery_triconsistent(internal, smallint, tsvector,
                           integer, internal, internal, internal),
            STORAGE text;
    END IF;
END
$$;
"""

_SEARCH_OPERATOR_STEPS = (
    ("search match function", _SEARCH_MATCH_FUNCTION),
    ("search match function comment", _SEARCH_FUNCTION_COMMENT),
    ("search match operator", _SEARCH_OPERATOR),
    ("search operator class", _SEARCH_OPERATOR_CLASS),
)


_SEARCH_OPERATOR_PRESENT = text(
    "SELECT "
    "  coalesce((SELECT p.proleakproof FROM pg_proc p"
    "            JOIN pg_namespace n ON n.oid = p.pronamespace"
    "            WHERE n.nspname = 'public' AND p.proname = :match_fn), false)"
    "  AND EXISTS (SELECT 1 FROM pg_opclass c"
    "              JOIN pg_namespace n ON n.oid = c.opcnamespace"
    "              WHERE n.nspname = 'public' AND c.opcname = :opclass)"
).bindparams(match_fn=SEARCH_MATCH_FUNCTION, opclass=SEARCH_OPCLASS)


async def search_operator_present(conn) -> bool:
    """Whether both objects are present, so guild search can use its index."""
    return bool(await conn.scalar(_SEARCH_OPERATOR_PRESENT))


_IS_SUPERUSER = text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")


async def _set_local(conn, key: str, value: str) -> None:
    await conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value})


#: One step of the bootstrap: a ``(key, value)`` session setting the next
#: statements read, or a statement to run.
_Step = tuple[str, str] | str


def _ensure_role_steps(role: LoginRole) -> list[_Step]:
    """Create the login, or bring an existing one to this shape."""
    return [
        ("app._bootstrap_role", role.name),
        ("app._bootstrap_attrs", role.attributes),
        ("app._bootstrap_attrs_superuser", role.attributes_if_superuser),
        ("app._bootstrap_pw", scram_verifier(role.password) if role.password else ""),
        _ENSURE_ROLE,
    ]


def _role_steps(roles: tuple[LoginRole, ...]) -> list[_Step]:
    """The logins, the database and the handover, in the order they apply.

    The app runs these over its owner connection (:func:`_run_steps`) and
    ``--print-sql`` prints them (:func:`bootstrap_sql`), so both do the same
    work in the same order.
    """
    provisioner = roles[0]
    steps: list[_Step] = [step for role in roles for step in _ensure_role_steps(role)]
    # Everything below acts for the provisioning role.
    steps += [
        ("app._bootstrap_pw", ""),
        ("app._bootstrap_role", provisioner.name),
        _GRANT_DATABASE,
        _REVOKE_TEMPORARY,
        _VERIFY_TEMPORARY_REVOKED,
        _OWN_PUBLIC_SCHEMA,
    ]
    for role in roles:
        if role.name == provisioner.name:
            continue
        steps += [
            ("app._bootstrap_grantee", role.name),
            _ADMINISTER_LOGIN_ROLE,
        ]
    steps += [
        _administer_existing_roles(),
        *_handover_settings(),
        _TRANSFER_STATEMENTS,
        _default_privileges(),
    ]
    return steps


async def _run_steps(conn, steps: list[_Step]) -> None:
    """Apply the steps over ``conn``. The handover query returns the statements
    to run, so it is run through :func:`_transfer_ownership`."""
    for step in steps:
        if isinstance(step, tuple):
            await _set_local(conn, *step)
        elif step is _TRANSFER_STATEMENTS:
            await _transfer_ownership(conn)
        else:
            await conn.execute(text(step))


@asynccontextmanager
async def _bootstrap_lock(url: str):
    """Hold the bootstrap lock for the block.

    Prefers a session lock on the cluster's maintenance database, so two
    deployments on one cluster serialize too. Falls back to the caller's own
    database, where the lock is still taken per transaction by the caller.
    """
    base = make_url(url)
    for database in _MAINTENANCE_DATABASES:
        engine = create_async_engine(
            base.set(database=database),
            poolclass=NullPool,
            echo=False,
            hide_parameters=True,
        )
        try:
            conn = await engine.connect()
        except Exception:
            await engine.dispose()
            continue
        try:
            await advisory_lock(conn, LockNamespace.DATABASE_BOOTSTRAP, xact=False)
            yield
            return
        finally:
            await conn.close()
            await engine.dispose()
    logger.debug(
        "database bootstrap: no maintenance database reachable for the "
        "cluster-wide lock; serializing on the app database only"
    )
    yield


async def _transfer_ownership(conn) -> None:
    """Hand the app's own objects to the provisioning role.

    Nothing to do on a fresh install, where the provisioning role creates them,
    or on any later start. A database that has been running under another login
    moves once, and what moved is logged.

    The move is described by who owns an object, not by who is asking: the
    bootstrap connection is whichever login the deployment named, and on an
    install that has changed hands more than once the objects can belong to a
    login it is neither. Claiming them needs rights over their current owner,
    which is why this runs from the bootstrap connection and not from the
    provisioning one.
    """
    rows = (await conn.execute(text(_TRANSFER_STATEMENTS))).all()
    if not rows:
        return
    for label, statement, _owner in rows:
        await conn.execute(text(statement))
    logger.info(
        "database bootstrap: took ownership of %d object(s): %s",
        len(rows),
        ", ".join(label for label, _stmt, _owner in rows),
    )


async def _apply_search_operator(conn) -> bool:
    """Install the match operator objects. Returns whether they are present
    afterwards — a non-superuser bootstrap connection cannot create them, and
    that is reported rather than raised: search works without them."""
    if not await conn.scalar(_IS_SUPERUSER):
        return await search_operator_present(conn)
    for label, statement in _SEARCH_OPERATOR_STEPS:
        try:
            await conn.execute(text(statement))
        except Exception:
            logger.exception("database bootstrap: %s failed", label)
            return False
    return await search_operator_present(conn)


def _handover_settings() -> list[tuple[str, str]]:
    """What :data:`_TRANSFER_STATEMENTS` reads besides the role taking the
    objects: the app's shared tables, the functions the bootstrap keeps, and
    the shared roles left owning what they own."""
    return [
        ("app._bootstrap_tables", ",".join(sorted(SHARED_TABLE_REGISTRY))),
        ("app._bootstrap_functions", ",".join(sorted(BOOTSTRAP_OWNED_FUNCTIONS))),
        ("app._bootstrap_kept_owners", _kept_owners()),
    ]


async def owners_to_hand_over(conn, role: str) -> list[str]:
    """Who owns what the handover would move to ``role``: the handover's own
    query, run without its statements, so the two cannot disagree about what
    belongs to the app."""
    for key, value in [("app._bootstrap_role", role), *_handover_settings()]:
        await _set_local(conn, key, value)
    rows = await conn.execute(
        text(
            f"SELECT DISTINCT owner FROM ({_TRANSFER_STATEMENTS}) AS pending ORDER BY 1"
        )
    )
    return [row[0] for row in rows.all()]


async def warn_if_ownership_was_never_handed_over() -> None:
    """Say so when the app's objects still belong to an earlier login.

    The handover runs as part of the bootstrap, so a deployment that gives the
    owner connection — as ``DATABASE_URL`` alone, or as
    ``DATABASE_URL_BOOTSTRAP`` beside its own three logins — has already had
    this done and reads nothing here. One that names its logins and gives no
    owner connection has no path that moves ownership: the app can ask for
    this repair but cannot make it, because taking an object from another login
    needs rights over that login which a least-privilege provisioner does not
    have.

    Untreated it is not fatal and not silent either: `CREATE OR REPLACE` on the
    app's functions and the per-community schema refresh both fail, once per
    community, on every start. This turns that into one line that names the
    remedy.
    """
    from app.db import session as db_session

    provisioner, _app_login, _system = login_roles()
    try:
        async with db_session.provisioning_engine.connect() as conn:
            owners = await owners_to_hand_over(conn, provisioner.name)
    except Exception:
        logger.debug("ownership check could not run", exc_info=True)
        return
    if not owners:
        return

    if settings.DATABASE_URL_BOOTSTRAP:
        named = " and ".join(repr(owner) for owner in owners)
        remedy = (
            f"{owner_setting()} is the owner connection, so the move was attempted and\n"
            "found nothing it could take. Point it at a login with rights\n"
            f"over {named} -- the owner of the database, or a superuser -- and\n"
            "start once.\n"
        )
    else:
        remedy = (
            "This deployment has no DATABASE_URL_BOOTSTRAP for the move to\n"
            "run under. Set it to a connection URL for the database owner and\n"
            "start once. It moves every object and logs what it moved; the\n"
            "line can come out again afterwards.\n"
        )
    logger.warning(
        "\n%s\n"
        "The app's objects still belong to %s, not to %r. Ownership moves as\n"
        "part of the bootstrap. Left alone, refreshing the app's functions and\n"
        "each community's schema fails on every start.\n\n"
        "%s"
        "%s",
        "=" * 70,
        " and ".join(repr(owner) for owner in owners),
        provisioner.name,
        remedy,
        "=" * 70,
    )


def _executing(query: str) -> str:
    """Wrap a ``(label, stmt)`` query in a block that RUNS what it returns.

    The app executes those rows itself (:func:`_transfer_ownership`). The
    printed script is piped into ``psql`` with nobody reading it, so it needs
    the same rows executed rather than displayed. Both forms are built from the
    one query, so they cannot come to describe different work.

    Every statement is collected before any of them runs: the query filters
    ``pg_class`` on who owns each object, and altering an owner part-way
    through a scan of the catalog it is filtering on is not something to leave
    to chance. That is also exactly what the app path does — fetch all, then
    execute.
    """
    return (
        "DO $handover$\n"
        "DECLARE\n"
        "    statements text[];\n"
        "    labels text[];\n"
        "    i int;\n"
        "BEGIN\n"
        "    SELECT array_agg(stmt ORDER BY label), array_agg(label ORDER BY label)\n"
        "      INTO statements, labels\n"
        "      FROM (\n"
        f"{query.strip()}\n"
        "      ) AS pending;\n"
        "    IF statements IS NULL THEN\n"
        "        RETURN;\n"
        "    END IF;\n"
        "    FOR i IN 1 .. array_length(statements, 1) LOOP\n"
        "        EXECUTE statements[i];\n"
        "        RAISE NOTICE 'ownership: %', labels[i];\n"
        "    END LOOP;\n"
        "END\n"
        "$handover$;"
    )


def bootstrap_sql() -> str:
    """The whole bootstrap as runnable SQL, for an operator applying it by hand.

    The settings the statements read are emitted as ``set_config`` calls ahead
    of them, so the output runs as-is under ``psql``.
    """
    out: list[str] = [
        "-- Initiative database bootstrap. Run as the database owner",
        "-- (a superuser, for the search operator's LEAKPROOF function).",
        "BEGIN;",
        "",
    ]
    for step in _role_steps(login_roles()):
        if isinstance(step, tuple):
            key, value = step
            out.append(f"SELECT set_config('{key}', {_sql_literal(value)}, true);")
        elif step is _TRANSFER_STATEMENTS:
            out.append(_executing(step))
        else:
            out.append(step.strip())
    out += ["", "-- Guild search match operator"]
    out += [statement.strip() for _label, statement in _SEARCH_OPERATOR_STEPS]
    out += ["", "COMMIT;"]
    return "\n".join(out) + "\n"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _repair_instructions(missing: list[str]) -> str:
    return (
        "The database is missing prerequisites the app cannot create as its "
        "own roles: " + ", ".join(missing) + ".\n"
        "Either point DATABASE_URL at the database owner and remove "
        "DATABASE_URL_APP and DATABASE_URL_ADMIN — the app then makes its "
        "logins and applies these itself — or apply them once by hand:\n"
        "  docker compose exec -T initiative python -m app.db.bootstrap "
        "--print-sql | psql -v ON_ERROR_STOP=1 -U <owner> -d <database>\n"
    )


async def _verify_only() -> BootstrapResult:
    """Check the invariants using the provisioning connection the app already
    has, for deployments that provision their database out of band."""
    from app.db import session as db_session

    provisioner, app_login, system = login_roles()
    missing: list[str] = []
    async with db_session.provisioning_engine.connect() as conn:
        present = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
                    {"names": [provisioner.name, app_login.name, system.name]},
                )
            ).all()
        }
        for role in (provisioner, app_login, system):
            if role.name not in present:
                missing.append(f"role {role.name}")
        if provisioner.name in present:
            for privilege in PROVISIONER_DATABASE_PRIVILEGES:
                held = await conn.scalar(
                    text(
                        "SELECT has_database_privilege("
                        "CAST(:role AS text), current_database(), CAST(:p AS text))"
                    ),
                    {"role": provisioner.name, "p": privilege},
                )
                if not held:
                    missing.append(
                        f"{privilege} on the database for {provisioner.name}"
                    )
        search_ready = await search_operator_present(conn)
    if missing:
        raise RuntimeError(_repair_instructions(missing))
    return BootstrapResult(
        applied=False,
        roles=(provisioner.name, app_login.name, system.name),
        search_operator_installed=search_ready,
        notes=("DATABASE_URL_BOOTSTRAP is not set; verified only",),
    )


async def ensure_database_bootstrap(
    bootstrap_url: str | None = None,
) -> BootstrapResult:
    """Apply the privileged prerequisites, or verify them when no bootstrap URL
    is configured. Called once at startup, before migrations.

    ``bootstrap_url`` overrides ``DATABASE_URL_BOOTSTRAP`` for callers that
    already know which connection to use — the test harness sources its own
    superuser and points this at the database under test.
    """
    url = bootstrap_url or settings.DATABASE_URL_BOOTSTRAP
    if not url:
        return await _verify_only()

    roles = login_roles()
    engine = create_async_engine(
        url, poolclass=NullPool, echo=False, hide_parameters=True
    )
    try:
        async with _bootstrap_lock(url), engine.begin() as conn:
            await advisory_lock(conn, LockNamespace.DATABASE_BOOTSTRAP)
            try:
                await _run_steps(conn, _role_steps(roles))
            except Exception as exc:
                raise RuntimeError(
                    f"{owner_setting()} could not apply the database "
                    "prerequisites. It must connect as the owner of the "
                    f"database (and, for the search operator, a superuser): "
                    f"{exc}"
                ) from exc
            search_ready = await _apply_search_operator(conn)
            await _revoke_former_set_config_holders(conn)
    finally:
        await engine.dispose()

    result = BootstrapResult(
        applied=True,
        roles=tuple(role.name for role in roles),
        search_operator_installed=search_ready,
    )
    logger.info(
        "database bootstrap applied as the database owner (%s): roles %s; "
        "search operator %s.",
        owner_setting(),
        ", ".join(result.roles),
        "present" if search_ready else "NOT installed",
    )
    return result


#: The function every routing and standing statement writes through. The
#: logins and every shared floor a routed role inherits hold it; ``PUBLIC``
#: does not, so a role that inherits no floor — the query surface's
#: ``guild_<id>_q``, which runs statements a reader wrote — cannot call it.
SET_CONFIG_FUNCTION = "pg_catalog.set_config(text, text, boolean)"

_SET_CONFIG_OPEN = text(
    "SELECT has_function_privilege('public', CAST(:function AS text), 'EXECUTE')"
).bindparams(function=SET_CONFIG_FUNCTION)

_ROLES_PRESENT = text("SELECT count(*) FROM pg_roles WHERE rolname = ANY(:names)")


def set_config_holders() -> tuple[str, ...]:
    """Who holds ``set_config``: the three logins, the shared floors, and the
    billing role, which inherits none."""
    return (
        *(role.name for role in login_roles()),
        *sorted(role_name(role) for role in SHARED_ROLES),
        role_name("initiative_billing"),
    )


def set_config_sql() -> tuple[str, str]:
    """The grant to its holders, then the revoke from ``PUBLIC``."""
    holders = ", ".join(
        '"' + name.replace('"', '""') + '"' for name in set_config_holders()
    )
    return (
        f"GRANT EXECUTE ON FUNCTION {SET_CONFIG_FUNCTION} TO {holders}",
        f"REVOKE EXECUTE ON FUNCTION {SET_CONFIG_FUNCTION} FROM PUBLIC",
    )


async def set_config_narrowed(conn) -> bool:
    """Whether ``PUBLIC`` no longer holds ``set_config`` on this database."""
    return not await conn.scalar(_SET_CONFIG_OPEN)


_FORMER_SET_CONFIG_HOLDERS = text(
    "SELECT r.rolname FROM pg_proc p "
    "CROSS JOIN LATERAL aclexplode(p.proacl) a "
    "JOIN pg_roles r ON r.oid = a.grantee "
    "WHERE p.oid = CAST(:function AS regprocedure) "
    "AND a.grantee <> p.proowner AND r.rolname <> ALL(:holders)"
).bindparams(function=SET_CONFIG_FUNCTION)


async def _revoke_former_set_config_holders(conn) -> None:
    """Take ``set_config`` from a role that is no longer one of its holders.

    A floor a migration retires still holds it, and only the function's owner
    can take it back, so the migration that drops the floor cannot. This runs
    from a superuser owner connection before the migrations, so the drop finds
    nothing holding the floor.
    """
    if not await conn.scalar(_IS_SUPERUSER):
        return
    former = await conn.scalars(
        _FORMER_SET_CONFIG_HOLDERS, {"holders": list(set_config_holders())}
    )
    for name in former.all():
        quoted = '"' + name.replace('"', '""') + '"'
        await conn.execute(
            text(f"REVOKE EXECUTE ON FUNCTION {SET_CONFIG_FUNCTION} FROM {quoted}")
        )


async def ensure_set_config_narrowed(bootstrap_url: str | None = None) -> bool:
    """Take ``set_config`` from ``PUBLIC`` once every holder exists.

    Called after migrations, which create the shared floors. Only the
    function's owner can change who may call it, so it is applied from the
    owner connection when that connection is a superuser, and otherwise said,
    with the SQL, for the operator to run. Returns whether it is in place.
    """
    url = bootstrap_url or settings.DATABASE_URL_BOOTSTRAP
    holders = set_config_holders()
    if url:
        engine = create_async_engine(
            url, poolclass=NullPool, echo=False, hide_parameters=True
        )
        try:
            async with _bootstrap_lock(url), engine.begin() as conn:
                if await conn.scalar(_IS_SUPERUSER) and await conn.scalar(
                    _ROLES_PRESENT, {"names": list(holders)}
                ) == len(holders):
                    for statement in set_config_sql():
                        await conn.execute(text(statement))
                narrowed = await set_config_narrowed(conn)
        finally:
            await engine.dispose()
    else:
        from app.db import session as db_session

        async with db_session.provisioning_engine.connect() as conn:
            narrowed = await set_config_narrowed(conn)
    if not narrowed:
        logger.warning(
            "\n%s\n"
            "Any database role may still call set_config on this database.\n"
            "The app takes it from the query surface's role once %s is a\n"
            "superuser connection. To apply it by hand instead, as a superuser:\n"
            "\n  %s;\n  %s;\n%s",
            "=" * 70,
            owner_setting(),
            *set_config_sql(),
            "=" * 70,
        )
    return narrowed


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = await ensure_database_bootstrap()
    print(
        f"roles: {', '.join(result.roles)}\n"
        f"search operator: "
        f"{'present' if result.search_operator_installed else 'missing'}"
    )
    return 0


if __name__ == "__main__":
    import sys

    if "--print-sql" in sys.argv:
        print(bootstrap_sql(), end="")
    else:
        raise SystemExit(asyncio.run(_main()))
