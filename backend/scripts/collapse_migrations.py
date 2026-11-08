"""Collapse the migration chain at a release into one baseline revision.

Every revision up to the head of ``--release`` is replaced by a baseline that
builds what they built: the group roles and memberships they made, the
extensions, and one ``pg_dump`` of ``public`` and ``guild_template``. The
baseline keeps the cut's revision id, so a database already stamped there (or
later) never runs it; an older one is refused at boot and told to start that
release first (``app.db.init_db.check_pre_baseline_db``).

1. Find the cut: the head of the release tag's ``backend/alembic/versions``.
   Refuse if the tree is dirty or a revision at or before it differs from the
   tag's copy: a collapse freezes what shipped.
2. Build a database to the cut, as a fresh install does (bootstrap, then
   ``alembic upgrade``), and snapshot it.
3. Build the whole chain to ``head``, for the proof.
4. Write the baseline, delete the revisions it replaces and the old baseline's
   SQL, and the tests that load a deleted revision.
5. Build the new chain to ``head`` and compare it with step 3: structure (as
   ``upgrade_from_release.py`` compares it), roles, extensions and every row.
   A difference puts the tree back and fails.

Each build gets a throwaway Postgres container of its own, because roles are
cluster-wide. Nothing is committed. Run from ``backend/`` on a branch of its
own::

    uv run python scripts/collapse_migrations.py --release v0.75.0
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import json
import os
import re
import secrets
import subprocess
import sys
import textwrap
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))

import upgrade_from_release as release_check

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
VERSIONS = BACKEND / "alembic" / "versions"
BASELINE_SQL = BACKEND / "alembic" / "baseline"
POSTGRES_IMAGE = "postgres:17"
OWNER = "initiative"
DATABASE = "initiative"
#: The login that runs the migrations, and so owns what they make.
RUNNER = "app_provisioner"
#: Where the platform-role prefix goes in the snapshot; the baseline fills it
#: in at apply time, as the test suite runs with one.
PREFIX_MARK = "@@PLATFORM_ROLE_PREFIX@@"
REVISION_ID = re.compile(r"\d{8}_\d{4}")
REVISION_FILE = re.compile(r"(\d{8}_\d{4})_\w+(?:\.py)?")
_TIMESTAMPS = ("timestamp with time zone", "timestamp without time zone", "date")


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    # git grep finding nothing is an answer, not a failure.
    if done.returncode and not (args[0] == "grep" and done.returncode == 1):
        raise subprocess.CalledProcessError(done.returncode, done.args, done.stderr)
    return done.stdout


def _revision_of(name: str) -> str:
    match = REVISION_ID.match(name)
    assert match, name
    return match.group(0)


# ---------------------------------------------------------------------------
# The cut
# ---------------------------------------------------------------------------


def find_cut(tag: str) -> str:
    """The head revision of ``tag``'s chain: the one no other revises."""
    names = [
        Path(path).name
        for path in _git(
            "ls-tree", "--name-only", tag, "backend/alembic/versions/"
        ).split()
        if path.endswith(".py")
    ]
    revised = set()
    for name in names:
        source = _git("show", f"{tag}:backend/alembic/versions/{name}")
        found = re.search(r"^down_revision\s*=\s*(.+)$", source, re.MULTILINE)
        if found:
            revised.update(REVISION_ID.findall(found.group(1)))
    heads = sorted({_revision_of(name) for name in names} - revised)
    if len(heads) != 1:
        raise SystemExit(f"{tag} has {len(heads)} heads: {heads}")
    return heads[0]


def require_frozen(tag: str, cut: str) -> list[Path]:
    """The revision files the baseline replaces, once each matches ``tag``."""
    if _git("status", "--porcelain"):
        raise SystemExit("The tree has uncommitted changes; collapse a clean one.")
    replaced = sorted(path for path in VERSIONS.glob("*.py") if path.name[:13] <= cut)
    changed = _git(
        "diff", "--name-only", tag, "HEAD", "--", *(str(p) for p in replaced)
    ).split()
    if changed:
        raise SystemExit(
            f"These revisions differ from {tag}'s, so the baseline would freeze "
            f"something that never shipped: {', '.join(changed)}"
        )
    return replaced


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------


@dataclass
class Server:
    container: str
    address: str

    def url(self, role: str, password: str, *, driver: str = "") -> str:
        scheme = f"postgresql+{driver}" if driver else "postgresql"
        return f"{scheme}://{role}:{password}@{self.address}/{DATABASE}"

    @property
    def owner(self) -> str:
        return self.url(OWNER, OWNER)

    def environment(self) -> dict[str, str]:
        """The app's settings for this server, each login named explicitly
        (``upgrade_from_release.py`` gives a boot the same ones)."""
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("DATABASE_URL") and not k.endswith("_ROLE_PREFIX")
        }
        logins = {
            name: self.url(role, role, driver="asyncpg")
            for name, role in release_check.LOGINS.items()
        }
        return {
            **base,
            **logins,
            "DATABASE_URL_BOOTSTRAP": self.url(OWNER, OWNER, driver="asyncpg"),
            "GUILD_ROLE_PREFIX": "",
            "PLATFORM_ROLE_PREFIX": "",
            "SECRET_KEY": base.get("SECRET_KEY") or secrets.token_hex(32),
        }

    def run(self, *args: str) -> None:
        subprocess.run(
            [sys.executable, *args], cwd=BACKEND, env=self.environment(), check=True
        )

    def dump(self, *args: str) -> str:
        return subprocess.run(
            ["docker", "exec", self.container, "pg_dump", "-U", OWNER, "-d", DATABASE]
            + list(args),
            check=True,
            capture_output=True,
            text=True,
        ).stdout


@contextlib.contextmanager
def server(label: str) -> Generator[Server]:
    name = f"initiative-collapse-{label}-{os.getpid()}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name]
        + ["-e", f"POSTGRES_USER={OWNER}", "-e", f"POSTGRES_PASSWORD={OWNER}"]
        + ["-e", f"POSTGRES_DB={DATABASE}", "-p", "127.0.0.1::5432", POSTGRES_IMAGE],
        check=True,
        capture_output=True,
    )
    try:
        port = subprocess.run(
            ["docker", "port", name, "5432"], check=True, capture_output=True, text=True
        ).stdout.split()[0]
        found = Server(name, port)
        asyncio.run(_ready(found))
        yield found
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


async def _ready(found: Server, seconds: int = 60) -> None:
    """The image answers on its socket while it initialises and only then
    listens on TCP, so a TCP connection is the sign it is done."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            await (await asyncpg.connect(found.owner)).close()
            return
        except (OSError, asyncpg.PostgresError):
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(1)


@dataclass(frozen=True)
class Cluster:
    roles: dict[str, tuple]
    memberships: frozenset[tuple]
    extensions: frozenset[tuple[str, str]]
    settings: frozenset[tuple]


async def _cluster(found: Server) -> Cluster:
    conn = await asyncpg.connect(found.owner)
    try:
        roles = {
            row[0]: tuple(row[1:])
            for row in await conn.fetch(
                "SELECT rolname, rolcanlogin, rolinherit, rolcreaterole, "
                "rolcreatedb, rolbypassrls, rolreplication, rolconnlimit "
                "FROM pg_roles WHERE rolname !~ '^pg_'"
            )
        }
        memberships = frozenset(
            tuple(row)
            for row in await conn.fetch(
                "SELECT g.rolname, m.rolname, pg_get_userbyid(a.grantor), "
                "a.admin_option, a.inherit_option, a.set_option "
                "FROM pg_auth_members a JOIN pg_roles g ON g.oid = a.roleid "
                "JOIN pg_roles m ON m.oid = a.member"
            )
        )
        extensions = frozenset(
            (row[0], row[1])
            for row in await conn.fetch(
                "SELECT extname, extnamespace::regnamespace::text FROM pg_extension"
            )
        )
        settings = frozenset(
            (row[0], tuple(row[1]))
            for row in await conn.fetch(
                "SELECT setrole::regrole::text, setconfig FROM pg_db_role_setting"
            )
        )
        return Cluster(roles, memberships, extensions, settings)
    finally:
        await conn.close()


async def _rows(found: Server) -> dict[str, str]:
    """Every row of ``public`` and ``guild_template`` but the alembic stamp,
    less the columns that hold a time: a seeded row's ``created_at`` is when
    its build ran."""
    conn = await asyncpg.connect(found.owner)
    try:
        tables = await conn.fetch(
            "SELECT n.nspname, c.relname, coalesce(array_agg(a.attname::text) "
            "FILTER (WHERE format_type(a.atttypid, NULL) = ANY($1)), '{}') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 "
            "AND NOT a.attisdropped "
            "WHERE n.nspname IN ('public', 'guild_template') "
            "AND c.relkind IN ('r', 'p') AND c.relname <> 'alembic_version' "
            "GROUP BY 1, 2",
            list(_TIMESTAMPS),
        )
        rows = {}
        for schema, table, times in tables:
            rows[f"rows {schema}.{table}"] = await conn.fetchval(
                "SELECT coalesce(jsonb_agg(to_jsonb(t) - $1::text[] "
                "ORDER BY (to_jsonb(t) - $1::text[])::text), '[]')::text "
                f'FROM "{schema}"."{table}" t',
                list(times),
            )
        return rows
    finally:
        await conn.close()


async def _shape(found: Server) -> dict[str, dict[str, str]]:
    conn = await asyncpg.connect(found.owner, server_settings={"search_path": ""})
    try:
        shape = {
            schema: await release_check._snapshot(conn, schema)
            for schema in ("public", "guild_template")
        }
        shape["roles"] = await release_check._roles(conn)
    finally:
        await conn.close()
    cluster = await _cluster(found)
    shape["extensions"] = {
        f"extension {name}": schema for name, schema in cluster.extensions
    }
    shape["rows"] = await _rows(found)
    return shape


def build(found: Server, target: str) -> tuple[Cluster, Cluster]:
    """Bootstrap and migrate to ``target``; the cluster before and after the
    migrations."""
    found.run("-m", "app.db.bootstrap")
    before = asyncio.run(_cluster(found))
    found.run("-m", "alembic", "upgrade", target)
    return before, asyncio.run(_cluster(found))


# ---------------------------------------------------------------------------
# The baseline
# ---------------------------------------------------------------------------


def _prefixed(role: str) -> bool:
    """Whether the app spells ``role`` with the platform-role prefix
    (``app.db.public_rls.role_name``)."""
    return role.startswith("platform_") or role == "initiative_billing"


@dataclass(frozen=True)
class Snapshot:
    roles: list[tuple]
    memberships: list[tuple]
    extensions: list[tuple[str, str]]
    sql: str


def snapshot(found: Server, before: Cluster, after: Cluster) -> Snapshot:
    if after.settings != before.settings:
        raise SystemExit(
            "The migrations set a role or database setting; carry it by hand."
        )
    made = {
        name: attrs for name, attrs in after.roles.items() if name not in before.roles
    }
    for name, (
        login,
        _inherit,
        createrole,
        createdb,
        bypass,
        repl,
        limit,
    ) in made.items():
        if login or createrole or createdb or bypass or repl or limit != -1:
            raise SystemExit(f"A migration made {name} more than a group role.")
    memberships = []
    for granted in sorted(after.memberships - before.memberships):
        role, member, grantor, *options = granted
        if grantor == RUNNER:
            memberships.append((role, member, *options))
        elif not (grantor == OWNER and member == RUNNER and role in made):
            # Postgres grants a role's creator ADMIN on it, from the bootstrap
            # superuser; the baseline's CREATE ROLE does the same.
            raise SystemExit(f"Unexpected membership {granted}")
    roles = [(name, attrs[1]) for name, attrs in sorted(made.items())]
    extensions = sorted(after.extensions - before.extensions)
    sql = curate(
        found.dump(
            "--inserts",
            "--schema=public",
            "--schema=guild_template",
            "--exclude-table=public.alembic_version",
        ),
        [name for name in after.roles if _prefixed(name)],
    )
    return Snapshot(roles, memberships, extensions, sql)


_ENTRY = re.compile(
    r"^-- (?:Data for )?Name: .*; Schema: (\S*); Owner: (\S*)$", re.MULTILINE
)
_OWNER_TO = re.compile(r"^ALTER .* OWNER TO (\S+);$", re.MULTILINE)
_SESSION = re.compile(
    r"^(?:SET \w+ = .*;|SELECT pg_catalog\.set_config\(.*\);|\\\w+.*|"
    r"CREATE SCHEMA public;)$",
    re.MULTILINE,
)


def curate(dump: str, prefixed: list[str]) -> str:
    """The dump less its session settings and the entries bootstrap owns
    (the superuser's search operator), with prefixed role names marked."""
    starts = [m.start() for m in _ENTRY.finditer(dump)]
    kept = []
    for start, end in zip(starts, [*starts[1:], len(dump)], strict=True):
        entry = dump[start:end]
        header = _ENTRY.match(entry)
        assert header
        schema, owner = header.groups()
        if owner == OWNER:
            continue
        if owner != RUNNER and schema != "-":
            # Owning an object in a schema takes CREATE on it, which the
            # migrations lent each such owner for the change; the schema's
            # own grants, later in the dump, are what it ends with.
            entry = _OWNER_TO.sub(
                lambda m, schema=schema: (
                    f"GRANT CREATE ON SCHEMA {schema} TO {m.group(1)};\n{m.group(0)}\n"
                    f"REVOKE CREATE ON SCHEMA {schema} FROM {m.group(1)};"
                ),
                entry,
            )
        kept.append(entry)
    sql = _SESSION.sub("", "".join(kept))
    if prefixed:
        names = "|".join(sorted(map(re.escape, prefixed), key=len, reverse=True))
        sql = re.sub(rf"\b(?:{names})\b", lambda m: PREFIX_MARK + m.group(0), sql)
    sql = re.sub(r"\n{3,}", "\n\n", sql)
    return sql.strip() + "\n"


def write_baseline(tag: str, cut: str, shot: Snapshot) -> list[Path]:
    sql_path = BASELINE_SQL / f"schema_{cut[9:]}.sql"
    sql_path.write_text(
        f"-- The schema the chain built at {tag} (revision {cut}), for\n"
        f"-- versions/{cut}_baseline.py. Written by scripts/collapse_migrations.py;\n"
        f"-- never edited. {PREFIX_MARK} is the platform-role prefix.\n\n" + shot.sql
    )
    py_path = VERSIONS / f"{cut}_baseline.py"
    about = textwrap.fill(
        f"Every revision up to {cut} was collapsed into this one by "
        "``scripts/collapse_migrations.py``. A database stamped at it or later "
        "never runs it. A fresh one gets the group roles and memberships those "
        "revisions made (the logins are ``app.db.bootstrap``'s), their "
        f"extensions, and ``alembic/baseline/{sql_path.name}``. A database "
        f"stamped before it is refused at boot and told to start {tag} first "
        "(``app.db.init_db.check_pre_baseline_db``).",
        width=79,
    )
    py_path.write_text(
        _BASELINE.format(
            about=about,
            tag=tag,
            cut=cut,
            sql=sql_path.name,
            mark=PREFIX_MARK,
            roles=_literal(shot.roles),
            memberships=_literal(shot.memberships),
            extensions=_literal(shot.extensions),
        )
    )
    return [py_path, sql_path]


def _literal(rows: list[tuple]) -> str:
    if not rows:
        return "()"
    return "(\n" + "".join(f"    {row!r},\n" for row in rows) + ")"


_BASELINE = '''"""Baseline: the schema the chain built at {tag}.

{about}

Revision ID: {cut}
Revises:
Create Date: (collapsed)
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import split_sql_statements

revision = "{cut}"
down_revision = None
branch_labels = None
depends_on = None

#: The release this baseline was cut at: the oldest a database may come from.
release = "{tag}"

_SQL = Path(__file__).resolve().parents[1] / "baseline" / "{sql}"
_MARK = "{mark}"

#: Each group role: its name and whether it inherits.
_ROLES = {roles}

#: Each membership: role, member, and its admin, inherit and set options.
_MEMBERSHIPS = {memberships}

#: Each extension and its schema.
_EXTENSIONS = {extensions}


def _prefix() -> str:
    from app.core.config import settings

    return settings.PLATFORM_ROLE_PREFIX


def _name(role: str) -> str:
    """A role as the catalog holds it (``app.db.public_rls.role_name``)."""
    prefixed = role.startswith("platform_") or role == "initiative_billing"
    return f"{{_prefix()}}{{role}}" if prefixed else role


def upgrade() -> None:
    bind = op.get_bind()
    for role, inherit in _ROLES:
        exists = bind.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {{"role": _name(role)}}
        ).scalar()
        if not exists:
            bind.execute(
                text(
                    f'CREATE ROLE "{{_name(role)}}" NOLOGIN '
                    f"{{'INHERIT' if inherit else 'NOINHERIT'}}"
                )
            )
    for role, member, admin, inherit, can_set in _MEMBERSHIPS:
        bind.execute(
            text(
                f'GRANT "{{_name(role)}}" TO "{{_name(member)}}" WITH ADMIN {{admin}}, '
                f"INHERIT {{inherit}}, SET {{can_set}}"
            )
        )
    for extension, schema in _EXTENSIONS:
        bind.execute(
            text(f'CREATE EXTENSION IF NOT EXISTS "{{extension}}" WITH SCHEMA "{{schema}}"')
        )
    bind.execute(text("SET LOCAL check_function_bodies = false"))
    sql = _SQL.read_text().replace(_MARK, _prefix())
    for statement in split_sql_statements(sql):
        # Raw, so a colon in a function body is not read as a parameter.
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError(
        "Nothing comes before the {tag} baseline; restore a backup instead."
    )
'''


# ---------------------------------------------------------------------------
# What goes with the revisions
# ---------------------------------------------------------------------------


def _gone(text_: str, cut: str) -> bool:
    match = REVISION_FILE.fullmatch(text_)
    return bool(match and match.group(1) <= cut)


def _names_gone(node: ast.AST, cut: str, gone_names: set[str]) -> bool:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and _gone(child.value, cut)
        ):
            return True
        if isinstance(child, ast.Name) and child.id in gone_names:
            return True
    return False


def _top_names(node: ast.stmt) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    targets = node.targets if isinstance(node, ast.Assign) else []
    if isinstance(node, ast.AnnAssign):
        targets = [node.target]
    return [t.id for t in targets if isinstance(t, ast.Name)]


def prune_test(path: Path, cut: str) -> str | None:
    """Take out of a test file what loads a revision at or before ``cut``:
    each such test, module-level name and helper, and the private helpers only
    they used. ``"deleted"`` when no test is left, ``"edited"`` when some went,
    ``None`` when the file names none."""
    source = path.read_text()
    tree = ast.parse(source)
    gone: set[int] = set()
    gone_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for index, node in enumerate(tree.body):
            if index not in gone and _names_gone(node, cut, gone_names):
                gone.add(index)
                gone_names.update(_top_names(node))
                changed = True
    if not gone:
        return None
    while True:
        kept = [n for i, n in enumerate(tree.body) if i not in gone]
        used = {
            child.id
            for node in kept
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
        } | {
            child.attr
            for node in kept
            for child in ast.walk(node)
            if isinstance(child, ast.Attribute)
        }
        unused = {
            i
            for i, node in enumerate(tree.body)
            if i not in gone
            and (names := _top_names(node))
            and all(n.startswith("_") and n not in used for n in names)
        }
        if not unused:
            break
        gone |= unused
    tests = [
        node
        for i, node in enumerate(tree.body)
        if i not in gone
        and _top_names(node)
        and any(n.startswith(("test_", "Test")) for n in _top_names(node))
    ]
    if not tests:
        path.unlink()
        return "deleted"
    lines = source.splitlines(keepends=True)
    drop: set[int] = set()
    for index in gone:
        node = tree.body[index]
        first = min(
            [node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))]
        )
        while first > 1 and lines[first - 2].lstrip().startswith("#"):
            first -= 1
        drop.update(range(first - 1, node.end_lineno or node.lineno))
    path.write_text("".join(line for i, line in enumerate(lines) if i not in drop))
    return "edited"


_LISTED = re.compile(r"^\s*['\"](\d{8}_\d{4})(?:_\w+(?:\.py)?)?['\"],\s*$")


def unlist(path: Path, cut: str) -> bool:
    """Drop the lines that list a revision at or before ``cut`` on their own
    (an entry of a set or tuple), each with the comment above it."""
    lines = path.read_text().splitlines(keepends=True)
    drop: set[int] = set()
    for index, line in enumerate(lines):
        match = _LISTED.match(line)
        if match and match.group(1) <= cut:
            first = index
            while first > 0 and lines[first - 1].lstrip().startswith("#"):
                first -= 1
            drop.update(range(first, index + 1))
    if drop:
        path.write_text("".join(line for i, line in enumerate(lines) if i not in drop))
    return bool(drop)


def retire(cut: str, replaced: list[Path]) -> dict[str, list[Path]]:
    """Delete the revisions, the old baseline's SQL and what loads them."""
    done: dict[str, list[Path]] = {"deleted": [], "edited": []}
    for path in [*replaced, *BASELINE_SQL.glob("*.sql")]:
        path.unlink()
        done["deleted"].append(path)
    code = [
        path
        for path in sorted((BACKEND / "app").rglob("*.py"))
        + sorted((BACKEND / "alembic").glob("*.py"))
        if "__pycache__" not in path.parts
    ]
    for path in code:
        if path.name.endswith("_test.py"):
            outcome = prune_test(path, cut)
            if outcome:
                done[outcome].append(path)
                if outcome == "deleted":
                    continue
        if unlist(path, cut) and path not in done["edited"]:
            done["edited"].append(path)
    return done


def restore(written: list[Path], done: dict[str, list[Path]]) -> None:
    """Put back what the collapse wrote, deleted and edited."""
    for path in written:
        path.unlink(missing_ok=True)
    _git("checkout", "HEAD", "--", *(str(p) for p in done["deleted"] + done["edited"]))


def tidy(paths: list[Path]) -> None:
    if not paths:
        return
    names = [str(p) for p in paths]
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--fix", "--select", "F401,F811,F841,I"]
        + names,
        cwd=BACKEND,
        check=False,
    )
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", *names], cwd=BACKEND, check=True
    )


# ---------------------------------------------------------------------------


def _report(cut: str, old_base: str, edited: list[Path]) -> None:
    named = _git("grep", "-l", "-F", old_base, "--", ".").split()
    stale = [
        str(path.relative_to(REPO))
        for path in edited
        if any(
            i <= cut
            for i in REVISION_ID.findall(
                ast.get_docstring(ast.parse(path.read_text())) or ""
            )
        )
    ]
    print("\nLeft for a person:")
    print("  * the upgrade floor in docs/en/running-a-server/backups-and-updates.md")
    print("  * a CHANGELOG entry naming the new floor")
    if named:
        print(f"  * files that still name the old baseline {old_base}: {named}")
    if stale:
        print(f"  * edited tests whose docstring names a collapsed revision: {stale}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release", required=True, help="the tag to collapse at")
    parser.add_argument("--dry-run", action="store_true", help="find the cut and stop")
    args = parser.parse_args()

    cut = find_cut(args.release)
    replaced = require_frozen(args.release, cut)
    old_base = next(
        _revision_of(path.name)
        for path in replaced
        if re.search(r"^down_revision\s*=\s*None", path.read_text(), re.MULTILINE)
    )
    print(f"{args.release} ends at {cut}: {len(replaced)} revisions collapse.")
    if args.dry_run:
        return 0

    with server("cut") as found:
        print(f"Building to {cut} ...", flush=True)
        shot = snapshot(found, *build(found, cut))
    with server("before") as found:
        print("Building the chain as it stands to head ...", flush=True)
        build(found, "head")
        want = asyncio.run(_shape(found))

    done = retire(cut, replaced)
    written = write_baseline(args.release, cut, shot)
    try:
        with server("after") as found:
            print("Building the collapsed chain to head ...", flush=True)
            build(found, "head")
            got = asyncio.run(_shape(found))
    except BaseException:
        restore(written, done)
        raise
    differences = [
        line
        for name in want.keys() | got.keys()
        for line in release_check._differences(
            name, got.get(name, {}), want.get(name, {}), ("collapsed", "chain")
        )
    ]
    if differences:
        restore(written, done)
        print("\n".join(differences))
        print(f"\n{len(differences)} differences; the tree is back as it was.")
        return 1

    tidy([*done["edited"], written[0]])
    print(
        json.dumps(
            {
                "baseline": [str(p.relative_to(REPO)) for p in written],
                "deleted": len(done["deleted"]),
                "tests deleted": [
                    str(p.relative_to(REPO))
                    for p in done["deleted"]
                    if p.name.endswith("_test.py")
                ],
                "edited": [str(p.relative_to(REPO)) for p in done["edited"]],
            },
            indent=2,
        )
    )
    print("The collapsed chain builds the same database as the chain did.")
    _report(cut, old_base, done["edited"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
