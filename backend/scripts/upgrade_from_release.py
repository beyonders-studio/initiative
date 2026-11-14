"""Upgrade a database that a release wrote, and check what the upgrade did.

Every other migration check starts from an empty database, where a backfill
has nothing to move and a ``NOT NULL`` column has no rows to refuse it. This
one starts where a deployment does:

1. Boot the release's published image and fill the database with
   ``upgrade_seed.py`` under that release's code.
2. With ``--walk``, boot every later release's image in turn, as a deployment
   that takes each one does.
3. Boot ``--image``, this tree built as the image a release would publish,
   then seed it again with the current code: the upgraded database has to take
   new writes as well as keep old ones.
4. Build a fresh install with ``--image`` on a second server, seeded the same
   way.

A boot is the image's own start: its entrypoint runs the migrations and serves.
It has booted when it answers on its port; ``--image`` must then also report
every dependency ready and serve the web app, its version and the app-update
manifest.

``--image`` runs as each setup the documentation describes. With one
``DATABASE_URL``, it is reached over plain HTTP at an address other than
``APP_URL``. With explicit logins, it runs as a larger deployment does:
requests, system work and dashboard reads through PgBouncer in transaction
mode, communities in :data:`COHORTS` cohorts, uploads in Garage (S3), and
served over HTTPS by Caddy on :data:`HOSTNAME`, which must resolve to this
host. Releases boot with the logins alone.

and fails when:

* any boot or seed fails, or ``--image`` does not serve what it should;
* a table that held rows before a boot is empty after it;
* the upgraded database differs in structure from the fresh install —
  ``public``, ``guild_template``, and every community schema against a fresh
  one. That is the shape a revision edited after release leaves behind: fresh
  installs get the new body, and upgraded ones never do;
* a second start of the fresh install changes its structure. A start repairs
  what is out of date, so one that changes a current database undoes what the
  migrations set;
* with ``--same-as``, the fresh install differs from the one another run built
  in the other setup. One URL and explicit logins are two ways of giving the
  app the same database, and they must end up with the same one, roles and
  privileges included.

"Structure" is every schema's tables, columns, constraints, indexes, triggers,
policies, functions, grants and default privileges, and the app's roles: their
attributes and memberships.

Each database has its own Postgres server, because roles are cluster-wide and a
community's roles would otherwise be shared between the two.

The containers use the host's network, so the servers' URLs are the same for
them as for this script, and the ports they take (8173, and with explicit
logins 3900, 3901, 6432 and 8443) must be free.

Usage, from ``backend/`` with ``SECRET_KEY`` set, as each boot reads it::

    docker build -t initiative:local --build-arg VERSION=$(cat ../VERSION) ..
    python scripts/upgrade_from_release.py --image initiative:local \\
        --from v0.77.1 \\
        --server postgresql://initiative:initiative@localhost:5432 \\
        --fresh-server postgresql://initiative:initiative@localhost:5433

``--from`` defaults to the newest release tag. ``--walk`` starts at the release
the migration chain's baseline was cut at, the oldest a database may come from,
and boots every release after it, less :data:`WITHDRAWN`.

``--one-url`` runs every boot, of each release and of the current tree, with a
single ``DATABASE_URL`` naming the database owner, as ``docker-compose.example.yml``
does: the app derives its three logins from it. Without it, each boot is given
the three logins and the owner URL explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SEED = BACKEND / "scripts" / "upgrade_seed.py"
DATABASE = "initiative"

#: Where each release's image is published, tagged with its version.
RELEASE_IMAGE = "ghcr.io/beyonders-studio/initiative"

#: Where a booted image answers, and the address it is told it has: a
#: deployment reached at another one, over plain HTTP.
SERVED_AT = "http://127.0.0.1:8173"
APP_URL = "http://initiative.test:8173"

#: How long a boot may take to answer: a fresh install runs every migration.
BOOT_SECONDS = 600

#: The account ``--image`` runs as. CI denies it the network outside the host,
#: as an air-gapped install has none.
IMAGE_UID = "1999"

#: Where ``--image`` looks for the marketplace registry: nowhere it can reach,
#: as on an air-gapped install that has no mirror. Its refresh still runs, and
#: fails without leaving the host.
OFFLINE_REGISTRY = "http://127.0.0.1:9/"

#: What the explicit-logins deployment runs beside the image.
POOLER_IMAGE = "docker.io/edoburu/pgbouncer:v1.24.1-p1@sha256:3db3d7223e93af52b4116f642951a1a5fa44702a88c2a59cf7562cac19320c9e"
STORE_IMAGE = "docker.io/dxflrs/garage:v2.4.1@sha256:9c96caa2612d3411acc5b0e6701fb238dbfba33e533a6d7d3d811a4b12d0d020"
PROXY_IMAGE = "docker.io/library/caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b"
POOLER = "127.0.0.1:6432"
STORE = "http://127.0.0.1:3900"
HOSTNAME = "initiative.test"
PROXIED_AT = f"https://{HOSTNAME}:8443"
COHORTS = 3
STORE_KEY = "GK0123456789abcdef01234567"
STORE_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

# The login roles every release since the bootstrap module creates for itself,
# with the passwords CI gives them.
LOGINS = {
    "DATABASE_URL": "app_provisioner",
    "DATABASE_URL_APP": "app_user",
    "DATABASE_URL_ADMIN": "app_admin",
}


#: Releases withdrawn after they shipped, and the release that replaced them.
#: A walk steps over each one, as the deployments it stopped did: what it
#: shipped is fixed, so booting it would only fail again.
WITHDRAWN = {
    # Never published: its build walked from its own tag, whose image did not
    # exist yet.
    "v0.75.1": "v0.75.2",
}


#: Every database setting a boot may be given; each boot gets only its own.
_DATABASE_SETTINGS = (*LOGINS, "DATABASE_URL_BOOTSTRAP")


def _floor() -> str:
    """The release the migration chain starts at: the current tree refuses a
    database from before it, so nothing older is supported."""
    for path in (BACKEND / "alembic" / "versions").glob("*_baseline.py"):
        found = re.search(r'^release = "(v[\d.]+)"$', path.read_text(), re.MULTILINE)
        if found:
            return found.group(1)
    raise SystemExit("No baseline revision names the release it was cut at.")


def _environment(server: str, *, one_url: bool) -> dict[str, str]:
    """The app's database settings for ``server``: the owner's URL alone, or
    the three logins and the owner explicitly."""
    base = {k: v for k, v in os.environ.items() if k not in _DATABASE_SETTINGS}
    owner = server.replace("postgresql://", "postgresql+asyncpg://") + f"/{DATABASE}"
    if one_url:
        return {**base, "DATABASE_URL": owner}
    host = server.split("@", 1)[1]
    env = {
        name: f"postgresql+asyncpg://{role}:{role}@{host}/{DATABASE}"
        for name, role in LOGINS.items()
    }
    env["DATABASE_URL_BOOTSTRAP"] = owner
    return {**base, **env}


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(command)}  (in {cwd})", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _published(tag: str) -> bool:
    """Whether the registry holds ``tag``'s image."""
    result = subprocess.run(
        ["docker", "manifest", "inspect", f"{RELEASE_IMAGE}:{tag.removeprefix('v')}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if "manifest unknown" in result.stderr or "no such manifest" in result.stderr:
        return False
    raise RuntimeError(f"could not ask the registry for {tag}: {result.stderr.strip()}")


def _release_tags() -> list[str]:
    """Every release tag whose image is published, oldest first.

    A release is tagged before its image is published, and the build of that
    tag walks the releases before it, so the newest tags wait for their image.
    """
    output = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=v:refname"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tags = [tag for tag in output.split() if re.fullmatch(r"v\d+\.\d+\.\d+", tag)]
    while tags and not _published(tags[-1]):
        print(
            f"{tags[-1]} has no published image yet; walking the releases before it",
            flush=True,
        )
        tags.pop()
    return tags


async def _recreate_database(server: str) -> None:
    conn = await asyncpg.connect(f"{server}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{DATABASE}"')
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


async def _row_counts(server: str) -> dict[str, int]:
    """Rows in every table of ``public`` and of every community schema.

    Read as the owner, which row security does not bind here: the counts are of
    what is stored, not of what any request may see.
    """
    conn = await asyncpg.connect(f"{server}/{DATABASE}")
    try:
        tables = await conn.fetch(
            "SELECT n.nspname, c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition "
            "AND (n.nspname = 'public' OR n.nspname ~ '^guild_[0-9]+$')"
        )
        return {
            f"{schema}.{table}": await conn.fetchval(
                f'SELECT count(*) FROM "{schema}"."{table}"'
            )
            for schema, table in tables
        }
    finally:
        await conn.close()


def _lost(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Communities that are gone, and tables that held rows and still exist
    but hold none now.

    A table a revision drops or renames is not in ``after`` and is not listed:
    that is a decision the revision states. Emptying one it keeps is not, and
    no revision drops a community.
    """
    schemas_after = {table.split(".", 1)[0] for table in after}
    gone = {
        table.split(".", 1)[0]
        for table in before
        if _COMMUNITY.match(table) and table.split(".", 1)[0] not in schemas_after
    }
    return [f"{schema} (the whole community)" for schema in sorted(gone)] + sorted(
        f"{table} ({count} rows before)"
        for table, count in before.items()
        if count and after.get(table) == 0
    )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

# Everything is read with an empty search_path, so every name the catalog
# prints comes qualified and the same object reads the same in both databases.
# A privilege list the catalog leaves NULL holds the defaults, and is read as
# them, so a grant that spells a default out does not read as a difference.
_SNAPSHOT = {
    "relation": (
        "SELECT c.relname, c.relkind::text, c.relrowsecurity, "
        "c.relforcerowsecurity, coalesce(c.relacl, acldefault("
        "CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END::\"char\", c.relowner"
        "))::text[] "
        "FROM pg_class c WHERE c.relnamespace = $1::regnamespace "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
    ),
    "column": (
        "SELECT c.relname || '.' || a.attname, format_type(a.atttypid, a.atttypmod), "
        "a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attidentity::text, "
        "a.attgenerated::text, a.attacl::text[] "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE c.relnamespace = $1::regnamespace "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
        "AND a.attnum > 0 AND NOT a.attisdropped"
    ),
    "constraint": (
        "SELECT c.relname || '.' || k.conname, pg_get_constraintdef(k.oid) "
        "FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
        "WHERE c.relnamespace = $1::regnamespace"
    ),
    "index": ("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = $1::text"),
    "trigger": (
        "SELECT c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid), "
        "t.tgenabled::text "
        "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE c.relnamespace = $1::regnamespace AND NOT t.tgisinternal"
    ),
    "policy": (
        "SELECT tablename || '.' || policyname, permissive, roles::text[], "
        "cmd, qual, with_check FROM pg_policies WHERE schemaname = $1::text"
    ),
    "function": (
        "SELECT p.oid::regprocedure::text, pg_get_functiondef(p.oid), "
        "pg_get_userbyid(p.proowner), "
        "coalesce(p.proacl, acldefault('f'::\"char\", p.proowner))::text[] "
        "FROM pg_proc p WHERE p.pronamespace = $1::regnamespace "
        "AND p.prokind IN ('f', 'p')"
    ),
    "enum": (
        "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) "
        "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
        "WHERE t.typnamespace = $1::regnamespace GROUP BY t.typname"
    ),
    "view": (
        "SELECT c.relname, pg_get_viewdef(c.oid) FROM pg_class c "
        "WHERE c.relnamespace = $1::regnamespace AND c.relkind IN ('v', 'm')"
    ),
    "default privilege": (
        "SELECT pg_get_userbyid(d.defaclrole) || ' ' || d.defaclobjtype::text, "
        "d.defaclacl::text[] FROM pg_default_acl d "
        "WHERE d.defaclnamespace = $1::regnamespace "
        "OR (d.defaclnamespace = 0 AND $1::text = 'public')"
    ),
    "schema": (
        "SELECT nspname, coalesce(nspacl, acldefault('n'::\"char\", nspowner))"
        "::text[] FROM pg_namespace WHERE nspname = $1::text"
    ),
}

_COMMUNITY = re.compile(r"\bguild_\d+")

#: A string literal or an array literal inside parentheses of its own.
_WRAPPED_ATOM = re.compile(r"\(\s*('(?:[^']|'')*'|ARRAY\[[^\]]*\])\s*\)")


def _normalize(kind: str, value: object) -> object:
    """One community's schema and roles read the same as another's.

    A privilege list is a set, and each community's roles collapse to one name
    in it. A function body is compared by digest, to keep a report readable. A
    constraint the provisioning render round-tripped comes back with its string
    array casts re-spelled and its literals and arrays parenthesized; those are
    not compared, and the parentheses that group an expression are.
    """
    if isinstance(value, list) and kind != "enum":
        return sorted({_COMMUNITY.sub("guild_#", item) for item in value})
    if not isinstance(value, str):
        return value
    value = _COMMUNITY.sub("guild_#", value)
    if kind == "function" and value.startswith("CREATE"):
        return hashlib.md5(value.encode()).hexdigest()
    if kind == "constraint":
        value = re.sub(r"::(?:character varying|text)(?:\[\])?", "", value)
        while True:
            unwrapped = _WRAPPED_ATOM.sub(r"\1", value)
            if unwrapped == value:
                return value
            value = unwrapped
    return value


async def _snapshot(conn: asyncpg.Connection, schema: str) -> dict[str, str]:
    shape: dict[str, str] = {}
    for kind, query in _SNAPSHOT.items():
        for name, *rest in await conn.fetch(query, schema):
            key = f"{kind} {_COMMUNITY.sub('guild_#', name)}"
            shape[key] = repr([_normalize(kind, value) for value in rest])
    return shape


def _app_role(alias: str) -> str:
    """Every role but Postgres's own and the owner login the check connects
    as: what the app made, whatever its names."""
    return f"{alias}.rolname !~ '^pg_' AND {alias}.rolname <> current_user"


_ROLES = {
    "role": (
        "SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, "
        "rolcanlogin, rolreplication, rolbypassrls, rolconnlimit "
        f"FROM pg_roles r WHERE {_app_role('r')}"
    ),
    "membership": (
        # One row per grantor: the same membership can be held twice.
        "SELECT m.rolname || ' in ' || g.rolname || ' from ' || "
        "pg_get_userbyid(a.grantor), a.admin_option, "
        "a.inherit_option, a.set_option "
        "FROM pg_auth_members a JOIN pg_roles m ON m.oid = a.member "
        "JOIN pg_roles g ON g.oid = a.roleid "
        f"WHERE ({_app_role('m')}) OR ({_app_role('g')})"
    ),
}


async def _roles(conn: asyncpg.Connection) -> dict[str, str]:
    """The roles and memberships, with each community's id read as ``guild_#``.

    A database holds a role set per community, so one name stands for several:
    every distinct record under it is kept, and a community whose roles differ
    from another's shows as an extra one.
    """
    records: dict[str, set[str]] = {}
    for kind, query in _ROLES.items():
        for name, *rest in await conn.fetch(query):
            key = f"{kind} {_COMMUNITY.sub('guild_#', name)}"
            records.setdefault(key, set()).add(repr(rest))
    return {key: repr(sorted(values)) for key, values in records.items()}


async def _schemas(server: str) -> dict[str, dict[str, str]]:
    conn = await asyncpg.connect(
        f"{server}/{DATABASE}", server_settings={"search_path": ""}
    )
    try:
        names = [
            row[0]
            for row in await conn.fetch(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('public', 'guild_template') "
                "OR nspname ~ '^guild_[0-9]+$' ORDER BY nspname"
            )
        ]
        shapes = {name: await _snapshot(conn, name) for name in names}
        shapes["roles"] = await _roles(conn)
        return shapes
    finally:
        await conn.close()


def _differences(
    label: str,
    got: dict[str, str],
    want: dict[str, str],
    names: tuple[str, str] = ("upgraded", "fresh"),
) -> list[str]:
    lines = []
    for key in sorted(set(got) | set(want)):
        if key not in got:
            lines.append(f"{label}: {names[0]} lacks {key} ({names[1]}: {want[key]})")
        elif key not in want:
            lines.append(f"{label}: {names[1]} lacks {key} ({names[0]}: {got[key]})")
        elif got[key] != want[key]:
            lines.append(
                f"{label}: {key}\n"
                f"    {names[0]}: {got[key]}\n"
                f"    {names[1]}: {want[key]}"
            )
    return lines


def _divergence(
    upgraded: dict[str, dict[str, str]], fresh: dict[str, dict[str, str]]
) -> list[str]:
    """Where the upgraded database differs from the fresh install: ``public``
    and the template against theirs, and every community schema against a
    community the fresh install created."""
    communities = sorted(name for name in fresh if _COMMUNITY.fullmatch(name))
    assert communities, "the fresh install has no community schema to compare with"
    reference = fresh[communities[0]]
    lines: list[str] = []
    for name in ("public", "guild_template", "roles"):
        lines += _differences(name, upgraded[name], fresh[name])
    for name, shape in upgraded.items():
        if _COMMUNITY.fullmatch(name):
            lines += _differences(name, shape, reference)
    return lines


def _other_setup(
    mine: dict[str, dict[str, str]], theirs: dict[str, dict[str, str]], shape: str
) -> list[str]:
    """Where this fresh install differs from the other setup's: ``public``, the
    template and the roles, and one community schema against one of theirs."""
    names = (shape, "other setup")
    lines: list[str] = []
    for name in ("public", "guild_template", "roles"):
        lines += _differences(name, mine[name], theirs[name], names)
    ours = sorted(name for name in mine if _COMMUNITY.fullmatch(name))
    others = sorted(name for name in theirs if _COMMUNITY.fullmatch(name))
    lines += _differences("community", mine[ours[0]], theirs[others[0]], names)
    return lines


def _restart_changes(
    first: dict[str, dict[str, str]], second: dict[str, dict[str, str]]
) -> list[str]:
    """What a second start changed. A start repairs what is out of date and
    nothing else, so on a database the first one left current there is
    nothing for it to do."""
    lines: list[str] = []
    for name in sorted(set(first) | set(second)):
        lines += _differences(
            name,
            second.get(name, {}),
            first.get(name, {}),
            ("after a restart", "first start"),
        )
    return lines


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _release_image(tag: str) -> str:
    return f"{RELEASE_IMAGE}:{tag.removeprefix('v')}"


def _docker(
    *args: str, env: dict[str, str] | None = None, image_env: tuple[str, ...] = ()
) -> None:
    """Run ``docker run`` with ``image_env`` passed by name, so the command
    printed carries no values."""
    names = [arg for name in image_env for arg in ("-e", name)]
    _run(["docker", "run", "--network", "host", *names, *args], cwd=REPO, env=env)


def _explicit_logins(name: str) -> dict[str, str]:
    """What the explicit-logins deployment tells the image beyond its logins,
    for the server the pooler calls ``name``: requests, system work and
    dashboard reads pooled, communities in cohorts, uploads in object storage,
    and a proxy in front."""
    pooled = f"{POOLER}/{name}"
    return {
        "DATABASE_URL_APP": f"postgresql+asyncpg://app_user:app_user@{pooled}",
        "DATABASE_URL_ADMIN": f"postgresql+asyncpg://app_admin:app_admin@{pooled}",
        "DATABASE_URL_QUERY": f"postgresql+asyncpg://app_user:app_user@{pooled}",
        "DB_COHORTS": str(COHORTS),
        "DB_COHORT_DATABASE": f"{name}_c{{cohort}}",
        "STORAGE_BACKEND": "s3",
        "S3_BUCKET": "uploads",
        "S3_ENDPOINT_URL": STORE,
        "S3_REGION": "garage",
        "S3_USE_PATH_STYLE": "true",
        "S3_ACCESS_KEY_ID": STORE_KEY,
        "S3_SECRET_ACCESS_KEY": STORE_SECRET,
        "BEHIND_PROXY": "true",
        "APP_URL": PROXIED_AT,
    }


@contextlib.contextmanager
def _explicit_logins_services(
    servers: dict[str, str],
) -> Generator[ssl.SSLContext]:
    """Run what the explicit-logins deployment runs beside the image, and stop
    it after: PgBouncer in transaction mode, with a database for each of
    ``servers`` (a name and an owner URL) and one for each of its cohorts;
    Garage with an ``uploads`` bucket; and Caddy serving :data:`PROXIED_AT`
    over HTTPS from its own certificate authority, whose root the context
    yielded trusts."""
    tag = os.getpid()
    names = [
        f"upgrade-from-release-{part}-{tag}" for part in ("pooler", "store", "proxy")
    ]
    databases = []
    for name, server in servers.items():
        url = urlsplit(server)
        target = f"host={url.hostname} port={url.port} dbname={DATABASE}"
        aliases = [name, *(f"{name}_c{cohort}" for cohort in range(COHORTS))]
        databases += [f"{alias} = {target}" for alias in aliases]
    pooler_config = "\n".join(
        [
            "[databases]",
            *databases,
            "[pgbouncer]",
            f"listen_addr = {POOLER.split(':')[0]}",
            f"listen_port = {POOLER.split(':')[1]}",
            "auth_type = scram-sha-256",
            "auth_file = /etc/pgbouncer/userlist.txt",
            "pool_mode = transaction",
            "max_prepared_statements = 500",
            "max_client_conn = 500",
            "default_pool_size = 20",
            "ignore_startup_parameters = extra_float_digits",
        ]
    )
    store_config = "\n".join(
        [
            'metadata_dir = "/tmp/meta"',
            'data_dir = "/tmp/data"',
            'db_engine = "sqlite"',
            "replication_factor = 1",
            'rpc_bind_addr = "127.0.0.1:3901"',
            'rpc_public_addr = "127.0.0.1:3901"',
            f'rpc_secret = "{STORE_SECRET}"',
            "[s3_api]",
            's3_region = "garage"',
            f'api_bind_addr = "{STORE.removeprefix("http://")}"',
        ]
    )
    with tempfile.TemporaryDirectory(prefix="upgrade-from-release-") as scratch:
        config = Path(scratch)
        (config / "pgbouncer.ini").write_text(pooler_config + "\n")
        (config / "userlist.txt").write_text(
            "".join(f'"{role}" "{role}"\n' for role in ("app_user", "app_admin"))
        )
        (config / "garage.toml").write_text(store_config + "\n")
        for address in (
            POOLER,
            STORE.removeprefix("http://"),
            f"127.0.0.1:{urlsplit(PROXIED_AT).port}",
        ):
            _free(address)
        try:
            pooler, store, proxy = names
            _docker(
                "-d",
                "--name",
                pooler,
                "-v",
                f"{config}/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini:ro",
                "-v",
                f"{config}/userlist.txt:/etc/pgbouncer/userlist.txt:ro",
                POOLER_IMAGE,
            )
            _docker(
                "-d",
                "--name",
                store,
                "-v",
                f"{config}/garage.toml:/etc/garage.toml:ro",
                "-e",
                f"GARAGE_DEFAULT_ACCESS_KEY={STORE_KEY}",
                "-e",
                f"GARAGE_DEFAULT_SECRET_KEY={STORE_SECRET}",
                "-e",
                "GARAGE_DEFAULT_BUCKET=uploads",
                STORE_IMAGE,
                "/garage",
                "server",
                "--single-node",
                "--default-bucket",
            )
            _docker(
                "-d",
                "--name",
                proxy,
                PROXY_IMAGE,
                "caddy",
                "reverse-proxy",
                "--from",
                PROXIED_AT,
                "--to",
                SERVED_AT.removeprefix("http://"),
                "--internal-certs",
                "--disable-redirects",
            )
            _listening(POOLER)
            _listening(STORE.removeprefix("http://"))
            deadline = time.monotonic() + 60
            while True:
                root = subprocess.run(
                    [
                        "docker",
                        "exec",
                        proxy,
                        "cat",
                        "/data/caddy/pki/authorities/local/root.crt",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if root.returncode == 0:
                    break
                if time.monotonic() > deadline:
                    _fail("Caddy made no certificate authority", [root.stderr])
                time.sleep(1)
            yield ssl.create_default_context(cadata=root.stdout)
        finally:
            for name in names:
                subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, check=False
                )


@dataclass(frozen=True)
class Setup:
    """How ``--image`` is deployed: what it is told beyond its logins, and
    where the check reaches it."""

    settings: dict[str, str] = field(default_factory=dict)
    url: str = SERVED_AT
    tls: ssl.SSLContext | None = None


def _get(path: str, setup: Setup = Setup()) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(
            f"{setup.url}{path}", timeout=10, context=setup.tls
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _free(address: str) -> None:
    """Fail if something already listens on ``address``, which a container
    started on the host's network could not then take."""
    host, port = address.rsplit(":", 1)
    with contextlib.suppress(OSError), socket.create_connection((host, int(port)), 2):
        _fail(f"Something already listens on {address}; stop it first", [])


def _listening(address: str, seconds: int = 60) -> None:
    host, port = address.rsplit(":", 1)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with (
            contextlib.suppress(OSError),
            socket.create_connection((host, int(port)), 2),
        ):
            return
        time.sleep(1)
    _fail(f"Nothing is listening on {address}", [])


def _answering(name: str) -> None:
    """Wait until the container answers, or fail with its log if it stops."""
    deadline = time.monotonic() + BOOT_SECONDS
    while time.monotonic() < deadline:
        try:
            if _get("/api/v1/version")[0] == 200:
                return
        except OSError:
            pass
        running = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if running != "true":
            break
        time.sleep(2)
    subprocess.run(["docker", "logs", name], check=False)
    _fail(f"{name} did not start answering on {SERVED_AT}", [])


def _ready(setup: Setup, seconds: int = 60) -> str | None:
    """Wait for every dependency to report ready; what it said last if not.

    Some connect after the app starts serving (the notification bus), so a
    first answer of ``degraded`` is asked again."""
    deadline = time.monotonic() + seconds
    while True:
        status, body = _get("/api/v1/readyz", setup)
        if status == 200 and json.loads(body).get("status") == "ok":
            return None
        if time.monotonic() > deadline:
            return f"/api/v1/readyz answered {status}: {body[:300]!r}"
        time.sleep(2)


#: Run inside ``--image`` once it serves, with its own code and settings: a
#: connection from every pool of every cohort, each to its own cohort's
#: database, and an object written, read back and removed through the storage
#: uploads use. Prints what failed, one line each.
_IN_THE_IMAGE = """
import asyncio
from sqlalchemy import text
from app.core.config import settings
from app.db import cohorts
from app.services import storage


async def pools():
    kinds = {
        "request": cohorts.request_sessionmaker,
        "system": cohorts.system_sessionmaker,
        "read": cohorts.read_sessionmaker,
        "query": cohorts.query_sessionmaker,
    }
    for guild_id in range(cohorts.cohort_count()):
        cohort = cohorts.cohort_of(guild_id)
        for kind, maker in kinds.items():
            try:
                async with maker(guild_id)() as session:
                    await session.execute(text("SELECT 1"))
                    database = session.bind.url.database
            except Exception as error:
                print(f"cohort {cohort}'s {kind} pool: {error!r}")
                continue
            template = settings.DB_COHORT_DATABASE
            if template and database != template.format(cohort=cohort):
                print(f"cohort {cohort}'s {kind} pool connected to {database}")


def objects():
    store = storage.get_guild_storage(1)
    key = "upgrade-from-release-probe"
    try:
        store.write(key, b"probe", content_type="text/plain")
        blob = store.open_readable(key)
        if blob is None:
            print("storage: a written object reads back as missing")
        else:
            # Object storage streams it; local storage names the file.
            if blob.stream is not None:
                data = b"".join(blob.stream)
            elif blob.path is not None:
                data = blob.path.read_bytes()
            else:
                data = None
            if data != b"probe":
                print(f"storage: a written object reads back as {data!r}")
        store.delete(key)
    except Exception as error:
        print(f"storage: {error!r}")


asyncio.run(pools())
objects()
"""


def _in_the_image(name: str) -> list[str]:
    result = subprocess.run(
        ["docker", "exec", "-u", f"{IMAGE_UID}:{IMAGE_UID}", name]
        + ["python", "-c", _IN_THE_IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    problems = result.stdout.splitlines()
    if result.returncode != 0:
        problems.append(f"the probe exited {result.returncode}: {result.stderr[-500:]}")
    return problems


def _serving(setup: Setup) -> list[str]:
    """Whatever ``--image`` does not serve that a deployment needs."""
    problems = [problem] if (problem := _ready(setup)) else []
    status, body = _get("/", setup)
    if status != 200 or b'<div id="root">' not in body:
        problems.append(f"/ answered {status} without the web app")
    version = (REPO / "VERSION").read_text().strip()
    status, body = _get("/api/v1/version", setup)
    if status != 200 or json.loads(body).get("version") != version:
        problems.append(
            f"/api/v1/version answered {status} {body[:200]!r}, not {version}"
        )
    status, body = _get("/api/v1/native/bundle/manifest", setup)
    if status != 200 or json.loads(body).get("version") != version:
        problems.append(
            f"/api/v1/native/bundle/manifest answered {status} {body[:200]!r}, "
            f"not {version}"
        )
    return problems


def _boot(
    image: str,
    env: dict[str, str],
    *,
    setup: Setup | None = None,
) -> None:
    """Start ``image`` as a deployment does, wait until it answers, check what
    it serves when it is this tree's (``setup``), and stop it."""
    given = {"APP_URL": APP_URL}
    if setup is not None:
        given |= {
            "PUID": IMAGE_UID,
            "PGID": IMAGE_UID,
            "MARKETPLACE_REGISTRY_URL": OFFLINE_REGISTRY,
            **setup.settings,
        }
    env = {**env, **given}
    image_env = (
        "SECRET_KEY",
        *(k for k in env if k.startswith("DATABASE_URL") or k in given),
    )
    # The image binds its port once its migrations have run; until then,
    # anything else answering there would read as this boot.
    try:
        _get("/api/v1/version")
    except OSError:
        pass
    else:
        _fail(f"Something already answers on {SERVED_AT}; stop it first", [])
    name = f"upgrade-from-release-{os.getpid()}"
    _docker("-d", "--name", name, image, env=env, image_env=image_env)
    try:
        _answering(name)
        problems = [*_serving(setup), *_in_the_image(name)] if setup is not None else []
        if problems:
            subprocess.run(["docker", "logs", name], check=False)
            _fail(f"{image} booted, but does not serve what it should", problems)
    finally:
        _run(["docker", "stop", "--time", "30", name], cwd=REPO)
        _run(["docker", "rm", name], cwd=REPO)


def _seed(backend: Path, python: str, env: dict[str, str]) -> None:
    _run([python, str(SEED)], cwd=backend, env=env)


def _fail(title: str, lines: list[str]) -> None:
    print(f"::error::{title}")
    for line in lines:
        print(f"  {line}")
    sys.exit(1)


def _boot_keeping_rows(
    label: str,
    server: str,
    image: str,
    env: dict[str, str],
    *,
    setup: Setup | None = None,
) -> None:
    before = asyncio.run(_row_counts(server))
    _boot(image, env, setup=setup)
    lost = _lost(before, asyncio.run(_row_counts(server)))
    if lost:
        _fail(f"Booting {label} lost rows it held", lost)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--from",
        dest="start",
        help="release tag to upgrade from (newest; the baseline's with --walk)",
    )
    parser.add_argument(
        "--walk",
        action="store_true",
        help="boot every release after --from in turn before the current tree",
    )
    parser.add_argument(
        "--one-url",
        action="store_true",
        help="give every boot one owner DATABASE_URL, as the example compose file does",
    )
    parser.add_argument(
        "--same-as",
        metavar="SERVER",
        help="owner URL of the other setup's fresh-install server, to match exactly",
    )
    parser.add_argument(
        "--image", required=True, help="this tree's image, built and loaded locally"
    )
    parser.add_argument("--server", required=True, help="owner URL, no database")
    parser.add_argument(
        "--fresh-server", required=True, help="a second server for the fresh install"
    )
    args = parser.parse_args()

    tags = _release_tags()
    floor = _floor()
    start = args.start or (floor if args.walk else tags[-1])
    if tags.index(start) < tags.index(floor):
        parser.error(f"{start} is older than {floor}, where the migrations start")
    releases = (
        [tag for tag in tags[tags.index(start) :] if tag not in WITHDRAWN]
        if args.walk
        else [WITHDRAWN.get(start, start)]
    )
    upgraded_env = _environment(args.server, one_url=args.one_url)
    fresh_env = _environment(args.fresh_server, one_url=args.one_url)
    shape = "one DATABASE_URL" if args.one_url else "explicit logins"

    asyncio.run(_recreate_database(args.server))
    asyncio.run(_recreate_database(args.fresh_server))

    for index, tag in enumerate(releases):
        _boot_keeping_rows(
            tag,
            args.server,
            _release_image(tag),
            upgraded_env,
        )
        if index == 0:
            # The seed is written against the release's own test factories,
            # which its image does not ship.
            with tempfile.TemporaryDirectory(prefix="upgrade-from-release-") as scratch:
                checkout = Path(scratch) / "release"
                release_env = {
                    **upgraded_env,
                    "UV_PROJECT_ENVIRONMENT": f"{scratch}/venv",
                }
                _run(
                    ["git", "worktree", "add", "--detach", str(checkout), tag], cwd=REPO
                )
                try:
                    _run(
                        ["uv", "sync", "--frozen"],
                        cwd=checkout / "backend",
                        env=release_env,
                    )
                    _seed(
                        checkout / "backend", f"{scratch}/venv/bin/python", release_env
                    )
                finally:
                    _run(
                        ["git", "worktree", "remove", "--force", str(checkout)],
                        cwd=REPO,
                    )

    with contextlib.ExitStack() as stack:
        if args.one_url:
            upgraded_setup = fresh_setup = Setup()
        else:
            tls = stack.enter_context(
                _explicit_logins_services(
                    {"upgraded": args.server, "fresh": args.fresh_server}
                )
            )
            upgraded_setup = Setup(_explicit_logins("upgraded"), PROXIED_AT, tls)
            fresh_setup = Setup(_explicit_logins("fresh"), PROXIED_AT, tls)

        _boot_keeping_rows(
            "the current tree",
            args.server,
            args.image,
            upgraded_env,
            setup=upgraded_setup,
        )
        _seed(BACKEND, sys.executable, upgraded_env)

        _boot(args.image, fresh_env, setup=fresh_setup)
        _seed(BACKEND, sys.executable, fresh_env)
        fresh = asyncio.run(_schemas(args.fresh_server))
        _boot_keeping_rows(
            "a fresh install again",
            args.fresh_server,
            args.image,
            fresh_env,
            setup=fresh_setup,
        )

    problems = [
        *_restart_changes(fresh, asyncio.run(_schemas(args.fresh_server))),
        *_divergence(asyncio.run(_schemas(args.server)), fresh),
    ]
    if problems:
        _fail(
            f"Upgrading from {start} ({shape}) does not reach the schema a fresh "
            "install keeps across restarts",
            problems,
        )
    if args.same_as:
        other = _other_setup(fresh, asyncio.run(_schemas(args.same_as)), shape)
        if other:
            _fail(f"A fresh install with {shape} differs from the other setup's", other)
    print(
        f"Upgraded {' → '.join(releases)} → {args.image} ({shape}); "
        "matches a fresh install, and a restart changes nothing"
        + ("; the fresh install matches the other setup's." if args.same_as else ".")
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        _fail(f"{' '.join(map(str, error.cmd))} exited {error.returncode}", [])
