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
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.core.relationships import PERSON
from app.core.tools import KINDS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)


def kind_code_body() -> str:
    """The function's body: one arm per kind, and the person's, by code."""
    ends = sorted((*KINDS.values(), PERSON), key=lambda kind: kind.code)
    arms = " ".join(f"WHEN '{kind.value}' THEN {kind.code}" for kind in ends)
    return f"SELECT (CASE kind {arms} END)::bigint"


def kind_code_sql() -> str:
    """The statement that writes the function with :func:`kind_code_body`."""
    return (
        "CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)\n"
        " RETURNS bigint\n"
        " LANGUAGE sql\n"
        " IMMUTABLE STRICT\n"
        f"AS $function${kind_code_body()}$function$"
    )


async def apply_kind_codes_if_changed(conn: AsyncConnection) -> bool:
    """Write the function when its stored body differs from the render.
    Returns whether it was written."""
    stored = (
        await conn.execute(
            text(
                "SELECT prosrc FROM pg_proc WHERE oid = "
                "to_regprocedure('public.relationship_kind_code(text)')"
            )
        )
    ).scalar()
    if stored == kind_code_body():
        return False
    await conn.execute(text(kind_code_sql()))
    return True


async def ensure_kind_codes() -> None:
    """Render the function on boot, after the migrations and before the guild
    back-fill, whose ``relationships`` tables call it."""
    from app.db import session as db_session

    async with db_session.provisioning_engine.begin() as conn:
        written = await apply_kind_codes_if_changed(conn)
    if written:
        logger.info("relationship kind codes written: %s", kind_code_body())
