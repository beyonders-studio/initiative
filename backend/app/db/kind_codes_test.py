"""A tool plug-in's kinds take their codes at registration, once.

A code is the high half of every node id a relationship stores for that kind,
so a kind keeps the code it was first given, a code is never given twice, and
the database function packs node ids with it as soon as the registration that
gave it commits."""

from sqlalchemy import text

from app.db import post_commit
from app.db.kind_codes import assign_plugin_kind_codes, kind_code_body
from app.models.platform.plugin_kind_code import FIRST_PLUGIN_KIND_CODE
from app.testing import (
    COUNTERS_UID,
    counters_tool_manifest,
    create_marketplace_listing,
    marketplace_uid,
)

GROUP = f"counter_group.{COUNTERS_UID.lower()}"
COUNTER = f"counter.{COUNTERS_UID.lower()}"


async def _register(
    session, *, uid=COUNTERS_UID, public_id="beyonders.counters", version="1.0.0"
):
    await create_marketplace_listing(
        session,
        uid=uid,
        public_id=public_id,
        kind="plugin",
        name="Counters",
        version=version,
        definition=counters_tool_manifest(),
    )
    await post_commit.settle(session)


async def _code(session, kind: str) -> int | None:
    return (
        await session.exec(
            text("SELECT public.relationship_kind_code(:kind)").bindparams(kind=kind)
        )
    ).scalar()


async def _codes(session) -> dict[str, int]:
    rows = await session.exec(text("SELECT kind, code FROM public.plugin_kind_codes"))
    return {kind: code for kind, code in rows.all()}


async def test_registering_a_tool_gives_its_kinds_codes_the_database_packs_with(
    session,
):
    await _register(session)

    assert await _codes(session) == {
        GROUP: FIRST_PLUGIN_KIND_CODE,
        COUNTER: FIRST_PLUGIN_KIND_CODE + 1,
    }
    assert await _code(session, GROUP) == FIRST_PLUGIN_KIND_CODE
    assert await _code(session, COUNTER) == FIRST_PLUGIN_KIND_CODE + 1
    assert await _code(session, "counter_group") == 4


async def test_a_kind_keeps_its_code_and_a_new_one_takes_the_next(session):
    await _register(session)
    await _register(session, version="1.1.0")
    assert await _codes(session) == {
        GROUP: FIRST_PLUGIN_KIND_CODE,
        COUNTER: FIRST_PLUGIN_KIND_CODE + 1,
    }

    # Another publisher's Counters declares the same keys under its own uid.
    other = marketplace_uid("othercounters")
    await _register(session, uid=other, public_id="others.counters")
    assert await _codes(session) == {
        GROUP: FIRST_PLUGIN_KIND_CODE,
        COUNTER: FIRST_PLUGIN_KIND_CODE + 1,
        f"counter_group.{other.lower()}": FIRST_PLUGIN_KIND_CODE + 2,
        f"counter.{other.lower()}": FIRST_PLUGIN_KIND_CODE + 3,
    }
    assert (
        await _code(session, f"counter.{other.lower()}") == FIRST_PLUGIN_KIND_CODE + 3
    )


async def test_assigning_only_adds(session):
    """Assigning answers every kind's code, adding a row only for a kind that
    had none; a kind already given one keeps it whatever else is asked for."""
    first = await assign_plugin_kind_codes(session, ["a.one", "b.one"])
    again = await assign_plugin_kind_codes(session, ["c.one", "b.one", "c.one"])
    await session.commit()
    await post_commit.settle(session)

    assert first == {"a.one": 1024, "b.one": 1025}
    assert again == {"c.one": 1026, "b.one": 1025}
    assert await _codes(session) == {"a.one": 1024, "b.one": 1025, "c.one": 1026}
    assert await _code(session, "c.one") == 1026


async def test_a_code_is_never_taken_back_or_moved(session):
    """The system engine, which registers listings, may read and add codes
    and nothing else."""
    privileges = (
        (
            await session.exec(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE table_schema = 'public' AND table_name = 'plugin_kind_codes'"
                    " AND grantee = 'app_admin'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(privileges) == ["INSERT", "SELECT"]


def test_only_a_plug_in_kind_is_written_into_the_function():
    assert "WHEN 'a.one' THEN 1024" in kind_code_body({"a.one": 1024})
    for kind in ("a'b", "A.one", "a one"):
        try:
            kind_code_body({kind: 1024})
        except ValueError:
            continue
        raise AssertionError(f"{kind!r} was written into the function")
