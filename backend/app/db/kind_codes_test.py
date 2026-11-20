"""A tool plug-in's kinds take their codes at registration, once.

A code is the high half of every node id a relationship stores for that kind,
so a kind keeps the code it was first given, a code is never given twice, and
the database function packs node ids with it as soon as the registration that
gave it commits."""

import asyncio

from sqlalchemy import text

from app.db import post_commit
from app.db.kind_codes import (
    assign_plugin_kind_codes,
    ensure_kind_codes,
    kind_code_body,
)
from app.models.platform.plugin_kind_code import FIRST_PLUGIN_KIND_CODE
from app.testing import (
    COUNTERS_UID,
    counters_tool_manifest,
    create_marketplace_listing,
    marketplace_uid,
)

GROUP = f"counter_group.{COUNTERS_UID.lower()}"
COUNTER = f"counter.{COUNTERS_UID.lower()}"
#: Kinds of the form a tool plug-in's take, named for the order they get codes.
A, B, C = (f"{key}.{COUNTERS_UID.lower()}" for key in "abc")


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


async def test_a_kind_keeps_its_code_and_a_new_one_takes_the_next(session):
    """Counters' kinds hold the codes of the built-in kinds they replaced,
    which their migration gave them; registering Counters, at any version,
    keeps them. Another publisher's Counters declares the same keys under its
    own uid, and its kinds take codes from the plug-in range, which the
    database packs with once the registration commits."""
    adopted = {GROUP: 4, COUNTER: 3}
    assert await _codes(session) == adopted
    await _register(session)
    await _register(session, version="1.1.0")
    assert await _codes(session) == adopted
    assert await _code(session, GROUP) == 4
    assert await _code(session, COUNTER) == 3

    other = marketplace_uid("othercounters")
    await _register(session, uid=other, public_id="others.counters")
    assert await _codes(session) == {
        **adopted,
        f"counter_group.{other.lower()}": FIRST_PLUGIN_KIND_CODE,
        f"counter.{other.lower()}": FIRST_PLUGIN_KIND_CODE + 1,
    }
    assert (
        await _code(session, f"counter.{other.lower()}") == FIRST_PLUGIN_KIND_CODE + 1
    )
    assert await _code(session, "wiki") == 15


async def test_assigning_only_adds(session):
    """Assigning answers every kind's code, adding a row only for a kind that
    had none; a kind already given one keeps it whatever else is asked for."""
    first = await assign_plugin_kind_codes(session, [A, B, GROUP])
    again = await assign_plugin_kind_codes(session, [C, B, C])
    await session.commit()
    await post_commit.settle(session)

    assert first == {A: 1024, B: 1025, GROUP: 4}
    assert again == {C: 1026, B: 1025}
    assert await _codes(session) == {GROUP: 4, COUNTER: 3, A: 1024, B: 1025, C: 1026}
    assert await _code(session, C) == 1026


async def test_a_render_waits_for_a_registration_giving_codes(session):
    """A render that starts while a registration is giving codes reads them
    once it commits, so it never writes the function without them."""
    await assign_plugin_kind_codes(session, [A])
    render = asyncio.create_task(ensure_kind_codes())
    await asyncio.sleep(0.3)
    assert not render.done()

    await session.commit()
    await render
    await post_commit.settle(session)
    assert await _code(session, A) == FIRST_PLUGIN_KIND_CODE


def test_only_a_plug_in_kind_is_written_into_the_function():
    assert f"WHEN '{A}' THEN 1024" in kind_code_body({A: 1024})
    for kind in ("a'b", "A.one", "a one", "a.one", f"{A}'"):
        try:
            kind_code_body({kind: 1024})
        except ValueError:
            continue
        raise AssertionError(f"{kind!r} was written into the function")
