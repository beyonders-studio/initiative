"""The database and ``app.db.authorization`` say the same thing.

These functions used to live only inside the migrations that created them, so
"what is the rule right now" was answered by reading three migrations and a
baseline in the right order. Now the module is the source — boot applies the
ones that live in ``public``, provisioning renders the ones that live in each
guild schema — which is only true for as long as something checks. This is
that something.

The comparison is on ``pg_get_functiondef`` output, which round-trips: feeding
Postgres its own rendering back produces the identical text, so an exact match
is a fair test rather than a brittle one.
"""

import pytest
from sqlalchemy import text

from app.db.authorization import (
    AUTHORIZATION_FUNCTIONS,
    GUILD_AUTHORIZATION_FUNCTIONS,
    GUILD_FUNCTION_SIGNATURES,
    INITIATIVE_ACCESS,
    apply_authorization_functions,
    authorization_functions_digest,
    drop_public_copies,
)
from app.db.schema_provisioning import guild_schema_name
from app.testing import create_guild

#: ``pg_get_functiondef`` needs the argument types to identify an overload.
#: These are the only signatures in ``public``; a second overload
#: of any of them would be a design change, and
#: ``test_no_unexpected_overloads`` is what would say so.
PUBLIC_SIGNATURES = {
    "guild_holds_option": "(int,text)",
    "guild_auth_satisfied": "()",
    "platform_factor_satisfied": "()",
    "session_amr": "()",
    "guild_connection_admits": "(int,int[],jsonb,int)",
    "guild_connection_satisfied": "(int,int)",
    "guild_superadmin": "(int,int)",
    "guest_membership_live": "(timestamptz,guild_role)",
}


async def _live_def(session, qualified: str) -> str:
    return (
        await session.exec(
            text("SELECT pg_get_functiondef(CAST(:sig AS regprocedure))").bindparams(
                sig=qualified
            )
        )
    ).one()[0]


async def _exists(engine, qualified: str) -> bool:
    """Asked on a fresh connection: a long-lived one can answer from a catalog
    view older than another connection's committed drop."""
    async with engine.connect() as conn:
        return bool(
            (
                await conn.execute(
                    text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
                    {"sig": qualified},
                )
            ).scalar()
        )


@pytest.mark.parametrize(
    "name,expected",
    AUTHORIZATION_FUNCTIONS,
    ids=[n for n, _ in AUTHORIZATION_FUNCTIONS],
)
async def test_the_database_matches_this_module(session, name, expected):
    """What is deployed in ``public`` is what this file says.

    A failure means one of two things and the diff says which: a migration
    changed a function without changing the module, or the module was edited
    and the change has not reached this database.
    """
    live = await _live_def(session, f"public.{name}{PUBLIC_SIGNATURES[name]}")
    assert live.strip() == expected.strip()


@pytest.mark.parametrize(
    "name,expected",
    GUILD_AUTHORIZATION_FUNCTIONS,
    ids=[n for n, _ in GUILD_AUTHORIZATION_FUNCTIONS],
)
async def test_a_guild_schema_matches_this_module(session, name, expected):
    """What provisioning rendered into a guild schema is what this file says.

    ``pg_get_functiondef`` prints the name schema-qualified; the module text is
    schema-relative, so the prefix comes off before the comparison.
    """
    guild = await create_guild(session)
    schema = guild_schema_name(guild.id)
    live = await _live_def(session, f"{schema}.{name}{GUILD_FUNCTION_SIGNATURES[name]}")
    assert live.replace(f"FUNCTION {schema}.", "FUNCTION ", 1).strip() == (
        expected.strip()
    )


async def test_applying_is_idempotent(session):
    """Boot runs this on every start, so it has to be safe to run twice."""
    conn = await session.connection()
    before = {
        n: await _live_def(session, f"public.{n}{PUBLIC_SIGNATURES[n]}")
        for n, _ in AUTHORIZATION_FUNCTIONS
    }
    await apply_authorization_functions(conn)
    after = {
        n: await _live_def(session, f"public.{n}{PUBLIC_SIGNATURES[n]}")
        for n, _ in AUTHORIZATION_FUNCTIONS
    }
    assert before == after
    await session.rollback()


async def test_none_runs_as_its_owner(session):
    """Each runs as its caller: these are declared ``SECURITY INVOKER``, in
    ``public`` and in a guild schema alike."""
    guild = await create_guild(session)
    schema = guild_schema_name(guild.id)
    rows = (
        await session.exec(
            text(
                "SELECT n.nspname, p.proname, p.prosecdef FROM pg_proc p"
                " JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE (n.nspname = 'public' AND p.proname = ANY(:public_names))"
                " OR (n.nspname = :schema AND p.proname = ANY(:guild_names))"
            ).bindparams(
                public_names=list(PUBLIC_SIGNATURES),
                schema=schema,
                guild_names=list(GUILD_FUNCTION_SIGNATURES),
            )
        )
    ).all()
    found = {(r[0], r[1]) for r in rows}
    expected = {("public", n) for n in PUBLIC_SIGNATURES} | {
        (schema, n) for n in GUILD_FUNCTION_SIGNATURES
    }
    assert found == expected, f"missing {sorted(expected - found)}"
    definer = [(r[0], r[1]) for r in rows if r[2]]
    assert definer == [], f"declared SECURITY DEFINER: {definer}"


async def test_no_unexpected_overloads(session):
    """One definition per name in ``public`` — the signatures above are
    the whole set there."""
    rows = (
        await session.exec(
            text(
                "SELECT p.proname, count(*) FROM pg_proc p"
                " JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'public' AND p.proname = ANY(:names)"
                " GROUP BY p.proname"
            ).bindparams(names=list(PUBLIC_SIGNATURES))
        )
    ).all()
    assert {r[0]: r[1] for r in rows} == {n: 1 for n in PUBLIC_SIGNATURES}


def test_the_digest_changes_with_the_definitions(monkeypatch):
    """The stamp is of the text, so an edit moves it."""
    import app.db.authorization as module

    first = authorization_functions_digest()
    assert first == authorization_functions_digest(), "should be deterministic"

    name, sql = module.AUTHORIZATION_FUNCTIONS[0]
    monkeypatch.setattr(
        module,
        "AUTHORIZATION_FUNCTIONS",
        ((name, sql + "\n-- edited"),) + module.AUTHORIZATION_FUNCTIONS[1:],
    )
    assert module.authorization_functions_digest() != first


async def test_public_copies_drop_only_after_nothing_binds_them(engine):
    """The boot step that retires the ``public`` copies, in the order it must
    run: refused while a policy still binds one, through once none does.

    Stands up what every install carried before the move — a copy of
    ``initiative_access`` in ``public`` and a policy bound to it — then runs
    the step twice: once to see the refusal, with the dependent counted, and
    once after the policy is gone to see the drop go through. Counted
    relative to whatever else binds the copy, so a database that still holds
    older bindings reports them rather than hiding the probe.
    """
    sig = f"public.initiative_access{GUILD_FUNCTION_SIGNATURES['initiative_access']}"
    scratch = "authz_drop_order_probe"
    public_copy = INITIATIVE_ACCESS.replace(
        "CREATE OR REPLACE FUNCTION initiative_access(",
        "CREATE OR REPLACE FUNCTION public.initiative_access(",
        1,
    )
    async with engine.begin() as conn:
        # The body names guild tables, which are not on the path in public.
        await conn.execute(text("SET LOCAL check_function_bodies = false"))
        await conn.execute(text(public_copy))
    # Whatever binds the copy before the probe does (nothing, on a database
    # built by the migrations and cleaned as boot cleans it).
    baseline = (await drop_public_copies(engine)).blocked.get("initiative_access", 0)
    if baseline == 0:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL check_function_bodies = false"))
            await conn.execute(text(public_copy))
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{scratch}"'))
        await conn.execute(
            text(f'CREATE TABLE IF NOT EXISTS "{scratch}".t (initiative_id int)')
        )
        await conn.execute(text(f'ALTER TABLE "{scratch}".t ENABLE ROW LEVEL SECURITY'))
        await conn.execute(
            text(
                f'CREATE POLICY bound ON "{scratch}".t '
                "USING (public.initiative_access(initiative_id, 1, false, NULL::public.standing))"
            )
        )
    try:
        refused = await drop_public_copies(engine)
        assert refused.blocked.get("initiative_access") == baseline + 1, refused
        assert "initiative_access" not in refused.dropped
        assert await _exists(engine, sig), "refused, so the copy must remain"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{scratch}" CASCADE'))

    retired = await drop_public_copies(engine)
    if baseline:
        assert retired.blocked.get("initiative_access") == baseline, retired
        pytest.skip(
            f"{baseline} older bindings of the public copy remain in this "
            "database, so the drop cannot be seen to go through here"
        )
    assert "initiative_access" in retired.dropped, retired
    assert not await _exists(engine, sig), "nothing bound it, so it goes"
    # And running it again reports the copy as already gone, not as an error.
    again = await drop_public_copies(engine)
    assert "initiative_access" in again.absent


async def test_the_standing_type_is_this_module(session):
    """``public.standing``'s attributes are :data:`STANDING_FIELDS`, in order.

    ``current_standing()`` builds the value positionally, so an attribute out
    of place would hand a gate one leg under another's name.
    """
    from app.db.authorization import STANDING_FIELDS

    live = (
        await session.exec(
            text(
                "SELECT a.attname, format_type(a.atttypid, a.atttypmod)"
                " FROM pg_attribute a"
                " JOIN pg_type t ON t.typrelid = a.attrelid"
                " WHERE t.typname = 'standing'"
                "   AND t.typnamespace = 'public'::regnamespace"
                "   AND a.attnum > 0 AND NOT a.attisdropped"
                " ORDER BY a.attnum"
            )
        )
    ).all()
    assert [tuple(r) for r in live] == [(n, t) for n, t, _e in STANDING_FIELDS]
