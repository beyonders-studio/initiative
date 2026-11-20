"""``public.relationship_kind_code``, rendered at boot from the kinds.

The generated node columns on ``relationships`` pack ``(kind, id)`` into one
integer through this function, so it is the one database object that lists
every kind's code. Its arms come from :data:`~app.core.tools.KINDS` and
:data:`~app.core.relationships.PERSON` here, on every boot, over the
provisioning engine that owns it, rather than from a migration restating it:
a kind added to the registry is admitted on the next boot.

The function is replaced only when the body stored in the database differs
from the render, and ``CREATE OR REPLACE`` keeps its signature, its owner, its
grants and the generated columns that call it. A kind's code never changes and
a retired one is never reused, so a new body only admits new rows: no stored
node id moves.

A tool plug-in's kinds take their codes from ``public.plugin_kind_codes``
(:func:`assign_plugin_kind_codes`, when a listing version declaring them is
registered), and the function gains an arm for each. That table is the system
engine's alone, so its rows are read there and the function is written on the
provisioning engine that owns it: at boot, and once the registration that gave
a new code commits.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select

from app.core.relationships import PERSON
from app.core.tools import KINDS
from app.db import post_commit
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.plugin_kind_code import (
    ADOPTED_KIND_CODES,
    FIRST_PLUGIN_KIND_CODE,
    PluginKindCode,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncConnection
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

#: A plug-in's kinds and their codes, as ``plugin_kind_codes`` holds them.
PluginCodes = dict[str, int]


def kind_code_body(plugin_codes: PluginCodes | None = None) -> str:
    """The function's body: one arm per kind, the person's and each plug-in
    kind's, by code. A plug-in's kind is written as a literal, so it is held
    to the form of a plug-in's kind before it is."""
    from app.db.plugin_tools import is_plugin_kind

    arms = [(kind.value, kind.code) for kind in (*KINDS.values(), PERSON)]
    for kind, code in (plugin_codes or {}).items():
        if not is_plugin_kind(kind):
            raise ValueError(f"{kind!r} is not a plug-in kind")
        arms.append((kind, code))
    spelled = " ".join(
        f"WHEN '{kind}' THEN {code}"
        for kind, code in sorted(arms, key=lambda arm: arm[1])
    )
    return f"SELECT (CASE kind {spelled} END)::bigint"


def kind_code_sql(plugin_codes: PluginCodes | None = None) -> str:
    """The statement that writes the function with :func:`kind_code_body`."""
    return (
        "CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)\n"
        " RETURNS bigint\n"
        " LANGUAGE sql\n"
        " IMMUTABLE STRICT\n"
        f"AS $function${kind_code_body(plugin_codes)}$function$"
    )


async def plugin_kind_codes(conn: AsyncConnection) -> PluginCodes:
    """Every plug-in kind's code, read on a connection that reaches the
    table's rows (the system engine's)."""
    rows = await conn.execute(select(PluginKindCode.kind, PluginKindCode.code))
    return {kind: code for kind, code in rows.all()}


async def apply_kind_codes_if_changed(
    conn: AsyncConnection, *, reader: AsyncConnection | None = None
) -> bool:
    """Write the function when its stored body differs from the render, with
    the plug-in kinds' codes read on ``reader`` (``conn`` when not given).
    Returns whether it was written.

    Takes turns with :func:`assign_plugin_kind_codes` and with itself, from
    before the read until ``conn`` commits: a code given meanwhile is read by
    the next render, and an older render never lands after a newer one."""
    await advisory_lock(conn, LockNamespace.PLUGIN_KIND_CODES)
    plugin_codes = await plugin_kind_codes(reader or conn)
    stored = (
        await conn.execute(
            text(
                "SELECT prosrc FROM pg_proc WHERE oid = "
                "to_regprocedure('public.relationship_kind_code(text)')"
            )
        )
    ).scalar()
    if stored == kind_code_body(plugin_codes):
        return False
    await conn.execute(text(kind_code_sql(plugin_codes)))
    return True


async def ensure_kind_codes() -> None:
    """Render the function from the codes as they stand: on boot, after the
    migrations and before the guild back-fill, whose ``relationships`` tables
    call it, and after a registration gives a kind its code."""
    from app.db import session as db_session

    async with (
        db_session.system_engine.connect() as reader,
        db_session.provisioning_engine.begin() as conn,
    ):
        written = await apply_kind_codes_if_changed(conn, reader=reader)
    if written:
        logger.info("relationship kind codes written")


async def assign_plugin_kind_codes(
    session: AsyncSession, kinds: Iterable[str]
) -> PluginCodes:
    """Give each of ``kinds`` a code, if it has none, and return every one's.

    A kind keeps the code it was first given, and a new one takes the next
    code after the highest ever given, so none is given twice; a kind that
    took over a retired built-in kind takes that kind's code
    (``ADOPTED_KIND_CODES``). Registrations
    take turns, so two never reach for the same code. Once the session
    commits, the function is rendered with any code given here.
    """
    wanted = list(dict.fromkeys(kinds))
    await advisory_lock(session, LockNamespace.PLUGIN_KIND_CODES)
    rows = await session.exec(
        select(PluginKindCode.kind, PluginKindCode.code).where(
            col(PluginKindCode.kind).in_(wanted)
        )
    )
    held = {kind: code for kind, code in rows.all()}
    missing = [kind for kind in wanted if kind not in held]
    if not missing:
        return held
    # A kind that took over a retired built-in kind keeps that kind's code.
    given = {
        kind: ADOPTED_KIND_CODES[kind] for kind in missing if kind in ADOPTED_KIND_CODES
    }
    fresh = [kind for kind in missing if kind not in given]
    highest = (await session.exec(select(func.max(PluginKindCode.code)))).one()
    first = max(highest + 1 if highest is not None else 0, FIRST_PLUGIN_KIND_CODE)
    given |= {kind: first + offset for offset, kind in enumerate(fresh)}
    await session.exec(
        insert(PluginKindCode).values(
            [{"kind": kind, "code": code} for kind, code in given.items()]
        )
    )
    post_commit.after_commit(session, ensure_kind_codes, key=ensure_kind_codes)
    return {**held, **given}
