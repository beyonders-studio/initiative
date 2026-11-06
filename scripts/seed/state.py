"""Whether the dev database is seeded, and ``--clean``."""

from __future__ import annotations

import contextlib

from sqlmodel import select

import app.db.session as db_session
from app.db.request_context import Unattributed
from app.db.session import SystemSessionLocal, set_rls_context
from app.models.platform.access_grant import AccessGrant
from app.services.auth import addresses
from app.services.platform import rules

from seed.accounts import USERS


async def seed_status() -> str:
    """What the database holds of a seed: ``none``, ``partial`` or ``complete``.

    The database is the record, so a recreated volume reads as unseeded and
    every checkout on the same database agrees. A seed writes its accounts
    first and its PAM access grants last, so accounts with no grant are a seed
    that stopped partway, whose rows the next one would collide with.
    """
    async with SystemSessionLocal() as session:
        if await addresses.account_holding(session, USERS[0][0]) is None:
            return "none"
        await set_rls_context(session, Unattributed())
        grant = (await session.exec(select(AccessGrant.id).limit(1))).first()
    return "complete" if grant is not None else "partial"


async def clean() -> None:
    """Remove all seeded dev data.

    Under schema-per-guild the guild-scoped data lives in per-guild schemas, so
    cleanup just drops every guild_<id> schema + role and wipes the shared rows
    (users, guilds) — no dependency-ordered row deletes. This also recovers a
    half-broken state. Run dev-migrate afterwards to recreate the primary guild +
    superuser.
    """
    print("Cleaning up dev data (dropping community schemas + wiping shared rows)...")
    async with db_session.provisioning_engine.begin() as conn:
        schemas = [
            s
            for (s,) in (
                await conn.exec_driver_sql(
                    "SELECT nspname FROM pg_namespace WHERE nspname ~ '^guild_[0-9]+$'"
                )
            ).all()
        ]
        roles = [
            r
            for (r,) in (
                await conn.exec_driver_sql(
                    "SELECT rolname FROM pg_roles WHERE rolname ~ '^guild_[0-9]+(_ro)?$'"
                )
            ).all()
        ]

    # One transaction per schema, and the truncate in its own. A community schema is
    # ~40 tables plus their indexes, so dropping every one of them and cascading
    # a truncate in a single transaction holds more locks than a default
    # `max_locks_per_transaction` allows — and the whole clean then rolls back,
    # leaving the state it was asked to clear.
    for schema in schemas:
        async with db_session.provisioning_engine.begin() as sconn:
            await sconn.exec_driver_sql("SET lock_timeout = '10s'")
            await sconn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')

    async with db_session.provisioning_engine.begin() as tconn:
        await tconn.exec_driver_sql("SET lock_timeout = '10s'")
        await tconn.exec_driver_sql(
            "TRUNCATE TABLE users, guilds RESTART IDENTITY CASCADE"
        )

    # Drop community roles best-effort, each in its own transaction: community roles are
    # cluster-global, so one a co-located test DB also uses owns objects in *that*
    # database and can't be dropped here — that must not abort the cleanup.
    dropped = 0
    for role in roles:
        with contextlib.suppress(Exception):
            async with db_session.provisioning_engine.begin() as rconn:
                await rconn.exec_driver_sql("SET lock_timeout = '5s'")
                await rconn.exec_driver_sql(f'DROP OWNED BY "{role}"')
                await rconn.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
            dropped += 1
    print(
        f"  Dropped {len(schemas)} community schema(s) + {dropped}/{len(roles)} role(s); wiped users + communities"
    )

    # The directory switch is a platform rule, so it outlives every community
    # that was listed in it. Put it back to the off state a fresh install has,
    # or the next un-seeded dev database starts with a directory nobody asked
    # for. platform_rules is not truncated above, so this is its own write.
    async with SystemSessionLocal() as session:
        await set_rls_context(session, Unattributed())
        await rules.put(session, "community_directory_enabled", False)
        await session.commit()
    print("  Community directory switched back off")

    print(
        "Done! All dev data removed. Run dev-migrate to recreate the primary community + superuser."
    )
