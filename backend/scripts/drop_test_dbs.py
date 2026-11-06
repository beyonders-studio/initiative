"""Drop the test databases and cluster-global test roles a checkout leaves behind.

``conftest.py`` gives every (checkout, xdist worker) pair its own database and its
own role prefix so parallel runs and parallel checkouts don't collide. Those
persist on purpose — a warm database skips the migration — but a deleted worktree
has no way to clean up after itself, so they accumulate in the cluster.

    python scripts/drop_test_dbs.py              # this checkout's, and dry-run first
    python scripts/drop_test_dbs.py --yes        # actually drop them
    python scripts/drop_test_dbs.py --orphaned --yes   # checkouts that are gone
    python scripts/drop_test_dbs.py --all --yes

``--orphaned`` keeps every checkout that still exists — this repository's
worktrees and any checkout in the dev-ports registry — and drops what the rest
left behind. It is safe while other checkouts are testing: it never disconnects
a session, so a database something is still using is reported and kept. It also
drops the dev database and roles of a worktree that is gone
(``initiative_dev_<id>``, ``dev_<id>_…``): ``scripts/dev-ports.sh`` gives a
worktree whose branch changes migrations a dev database of its own. A checkout's
own dev database is never dropped here, and neither is the shared one.

Credentials come from POSTGRES_USER/POSTGRES_PASSWORD (the dev-compose bootstrap
superuser) and the host/port in DATABASE_URL, exactly as the suite does.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402

# Must match conftest.CHECKOUT_ID, which is the definition — importing conftest
# here would pull in the whole app, so the level is spelled out instead:
# parents[2] is the repo root from backend/scripts/drop_test_dbs.py.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _checkout_id(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]


CHECKOUT_ID = _checkout_id(REPO_ROOT)

# Every name the suite and the migration tests create, with the checkout id in
# the first group: initiative_test_<id>_<worker>, test_<id>_<worker>_..., and the
# migration tests' initiative_migrations_test_<id>_... and migtest_<id>_....
_NAME_CHECKOUT = re.compile(
    r"^(?:initiative_test|initiative_migrations_test|test|migtest)_([0-9a-f]{8})_"
)

# A worktree's own dev database and roles (scripts/dev-ports.sh):
# initiative_dev_<id> and dev_<id>_....
_DEV_NAME_CHECKOUT = re.compile(r"^(?:initiative_dev|dev)_([0-9a-f]{8})(?:_|$)")

# scripts/dev-ports.sh's registry: one "<offset>\t<checkout path>" line each.
DEV_PORTS_REGISTRY = Path(
    os.environ.get("DEV_PORTS_REGISTRY")
    or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    / "initiative"
    / "dev-ports"
)


def _live_checkout_ids() -> set[str]:
    """The ids of every checkout that still exists on disk.

    The repository's worktrees, plus any checkout the dev-ports registry knows
    of (a separate clone is not a worktree of this one). Raises if git can't
    list the worktrees, so a failed lookup never reads as "everything is gone".
    """
    listing = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths = [
        line[len("worktree ") :]
        for line in listing.splitlines()
        if line.startswith("worktree ")
    ]
    if DEV_PORTS_REGISTRY.is_file():
        for line in DEV_PORTS_REGISTRY.read_text().splitlines():
            _, _, path = line.partition("\t")
            if path:
                paths.append(path)
    ids = {_checkout_id(Path(path)) for path in paths if Path(path).is_dir()}
    ids.add(CHECKOUT_ID)
    return ids


def _is_orphaned(
    name: str, live: set[str], pattern: re.Pattern = _NAME_CHECKOUT
) -> bool:
    match = pattern.match(name)
    return match is not None and match.group(1) not in live


async def _connect() -> asyncpg.Connection:
    url = make_url(settings.DATABASE_URL)
    return await asyncpg.connect(
        user=os.environ.get("POSTGRES_USER", "initiative"),
        password=os.environ.get("POSTGRES_PASSWORD", "initiative"),
        host=url.host,
        port=url.port or 5432,
        database="postgres",
    )


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "--all",
        action="store_true",
        help="every checkout's, not just this one — run it when nothing is testing",
    )
    which.add_argument(
        "--orphaned",
        action="store_true",
        help="those of checkouts that no longer exist — safe to run at any time",
    )
    parser.add_argument("--yes", action="store_true", help="drop, instead of listing")
    args = parser.parse_args()

    live: set[str] = set()
    if args.orphaned:
        try:
            live = _live_checkout_ids()
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Could not list the live checkouts, so nothing was dropped: {exc}")
            return 1

    scope = "" if args.all or args.orphaned else f"{CHECKOUT_ID}_"
    db_like = f"initiative_test_{scope}%"
    mig_like = f"initiative_migrations_test_{scope}%"
    # Two role namespaces: the suite's (conftest) and the migration tests' own.
    role_likes = (f"test_{scope}%", f"migtest_{scope}%")

    conn = await _connect()
    try:
        databases = [
            r["datname"]
            for r in await conn.fetch(
                "SELECT datname FROM pg_database WHERE datname LIKE $1 OR datname LIKE $2"
                " ORDER BY datname",
                db_like,
                mig_like,
            )
        ]
        roles = [
            r["rolname"]
            for r in await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE $1 OR rolname LIKE $2"
                " ORDER BY rolname",
                *role_likes,
            )
        ]
        if args.orphaned:
            databases = [name for name in databases if _is_orphaned(name, live)]
            roles = [name for name in roles if _is_orphaned(name, live)]
            databases += [
                r["datname"]
                for r in await conn.fetch(
                    "SELECT datname FROM pg_database WHERE datname LIKE 'initiative_dev_%'"
                    " ORDER BY datname"
                )
                if _is_orphaned(r["datname"], live, _DEV_NAME_CHECKOUT)
            ]
            roles += [
                r["rolname"]
                for r in await conn.fetch(
                    "SELECT rolname FROM pg_roles WHERE rolname LIKE 'dev\\_%' ORDER BY rolname"
                )
                if _is_orphaned(r["rolname"], live, _DEV_NAME_CHECKOUT)
            ]

        if args.all:
            where = "every checkout"
        elif args.orphaned:
            where = f"checkouts that no longer exist ({len(live)} still do)"
        else:
            where = f"checkout {CHECKOUT_ID}"
        print(f"{len(databases)} database(s) and {len(roles)} role(s) for {where}")
        for name in databases:
            print(f"  db   {name}")
        for name in roles:
            print(f"  role {name}")

        if not args.yes:
            print("\nNothing dropped. Re-run with --yes to drop them.")
            return 0

        for name in databases:
            # FORCE disconnects a run that is still holding the database rather
            # than failing the whole sweep on it. --orphaned leaves a database in
            # use alone instead: whatever holds it is not finished with it.
            if args.orphaned:
                try:
                    await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
                except asyncpg.ObjectInUseError as exc:
                    print(f"kept db      {name}: {exc}")
                    continue
            else:
                await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            print(f"dropped db   {name}")
        for name in roles:
            # The roles' grants lived in the databases just dropped, so nothing
            # should own them by now; report the ones that still do.
            try:
                await conn.execute(f'DROP ROLE IF EXISTS "{name}"')
                print(f"dropped role {name}")
            except asyncpg.PostgresError as exc:
                print(f"kept role    {name}: {exc}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
