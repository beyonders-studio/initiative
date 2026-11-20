"""The shared-table RLS registry, held to the catalog in both directions.

Unit half: every policy is well formed, and the render is stable. Integration half: applying
the registry to a migrated database changes nothing — so the migrations and
the registry say the same thing, and a fresh install and an upgraded one
carry the same rules — and the catalog holds no policy the registry does not
name.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.public_rls import (
    ALL,
    COMMANDS,
    INSERT,
    KNOWN_ROLES,
    PUBLIC_RLS,
    UPDATE,
    apply_public_rls,
    policy_roles,
    unregistered_policies,
)

pytestmark = pytest.mark.always

# --- unit ---------------------------------------------------------------------


def test_policy_names_are_unique_per_table():
    for table, rls in PUBLIC_RLS.items():
        names = [p.name for p in rls.policies]
        assert len(names) == len(set(names)), f"{table}: duplicate policy names"


def test_every_policy_is_well_formed():
    """A command takes the clauses Postgres gives it: SELECT and DELETE have a
    USING and no WITH CHECK, INSERT the reverse, UPDATE and ALL at least a
    USING. Roles are ones the app creates."""
    for table, rls in PUBLIC_RLS.items():
        for p in rls.policies:
            where = f"{table}.{p.name}"
            assert p.command in COMMANDS, f"{where}: unknown command {p.command}"
            roles = policy_roles(p)
            assert roles, f"{where}: no roles"
            unknown = set(roles) - KNOWN_ROLES
            assert not unknown, f"{where}: unknown roles {sorted(unknown)}"
            if p.command == INSERT:
                assert p.using is None and p.check, f"{where}: INSERT takes WITH CHECK"
            elif p.command in (UPDATE, ALL):
                assert p.using, f"{where}: {p.command} takes USING"
            else:
                assert p.using and p.check is None, (
                    f"{where}: {p.command} takes USING only"
                )


def test_a_table_without_policies_is_forced_or_off():
    """No policies and row security on means forced: the strictest state is
    stated, never a half-state where the owner reads everything."""
    for table, rls in PUBLIC_RLS.items():
        if not rls.policies and rls.enabled:
            assert rls.forced, f"{table}: enabled with no policy must be forced"


# --- integration ----------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _materialize_lazy_shared_tables():
    """``storage_backfill_state`` is created lazily at runtime, not by a
    migration, so it is created up front — as ``security_invariants_test``
    does — so the comparison covers the same tables every run."""
    from app.services.storage_backfill import _ensure_table

    await _ensure_table()


async def _catalog(conn) -> dict:
    policies = (
        await conn.execute(
            text(
                "SELECT tablename, policyname, cmd, permissive, roles, qual, "
                "with_check FROM pg_policies WHERE schemaname = 'public'"
            )
        )
    ).all()
    flags = (
        await conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
            )
        )
    ).all()
    return {
        "policies": {
            (t, p): (cmd, perm, tuple(sorted(roles)), qual, check)
            for t, p, cmd, perm, roles, qual, check in policies
        },
        "flags": {t: (on, forced) for t, on, forced in flags},
    }


async def test_the_catalog_is_what_the_registry_renders(engine):
    """Applying the registry to the worker's database changes nothing.

    The suite applies the registry after migrating, as boot does, so what is
    in the catalog here is the registry's own render as Postgres parsed and
    re-printed it. Applying it again inside a transaction that is rolled back
    must reproduce that exactly: the render is deterministic, every predicate
    parses, and nothing the migrations left behind is out of step with it.
    (That the first version of the registry reproduced the 123 hand-written
    policies name for name was checked once, against a database built by the
    migrations alone, before this step was added to the suite.)"""
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            before = await _catalog(conn)
            await apply_public_rls(conn)
            after = await _catalog(conn)
        finally:
            await trans.rollback()
    for key in sorted(set(before["policies"]) | set(after["policies"])):
        assert before["policies"].get(key) == after["policies"].get(key), (
            f"{key[0]}.{key[1]}: catalog {before['policies'].get(key)} vs "
            f"registry {after['policies'].get(key)}"
        )
    assert before["flags"] == after["flags"]


async def test_the_catalog_holds_no_policy_the_registry_does_not_name(engine):
    async with engine.connect() as conn:
        stray = await unregistered_policies(conn)
    assert stray == [], (
        f"policies on shared tables missing from app/db/public_rls.py: {stray}"
    )


async def test_row_security_flags_match_the_registry(engine):
    async with engine.connect() as conn:
        flags = (await _catalog(conn))["flags"]
    for table, rls in sorted(PUBLIC_RLS.items()):
        if table not in flags:
            continue
        assert flags[table] == (rls.enabled, rls.forced), (
            f"{table}: catalog (enabled, forced) = {flags[table]}, registry says "
            f"{(rls.enabled, rls.forced)}"
        )
