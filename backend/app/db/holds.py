"""Holds, as the database enforces them.

A hold keeps content in place for the platform (``app.services.platform.holds``
places and releases one). While a row's ``held_at`` is set:

- **It reads as absent to the whole community.** One RESTRICTIVE policy per
  holdable table, ``held_restrict``, admits a held row only to the system
  engine and to a request covered by a ``moderate`` content grant
  (``pam_moderate``). It narrows every permissive leg, the community admin's
  included: the one place a community admin does not reach everything in their
  community. Exports, search, ``/me`` views and plug-ins all read through the
  same policies, so none of them has anything to remember.
- **Nobody in the community can change it.** The policy's ``WITH CHECK``
  admits a held row from the system engine alone, so a ``moderate`` grantee
  reads but never writes, and nobody else can set ``held_at``.
- **Nothing deletes it.** ``held_guard`` refuses a DELETE of a held row from
  anyone, cascades included, and an UPDATE from anyone but the system engine.
  Destroying held content means releasing it first, in the same transaction.

``HOLDABLE_TABLES`` is read off ``HoldMixin``, which every reportable kind and
``uploads`` carry, so a new kind is holdable the day it declares the mixin.

``content_holds`` is the platform's record of each hold. It is read by the
system engine and a ``moderate`` grantee, and written by the system engine;
there is no community leg, so a community moderator who places a hold can't
read it back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.authorization import IN_POLICY, SYSTEM_SESSION
from app.db.frozen import FROZEN_SQLSTATE, HELD_CONSTRAINT
from app.db.names import object_name

if TYPE_CHECKING:
    from app.core.tool_set import ToolSet


def _holdable() -> frozenset[str]:
    import app.db.base  # noqa: F401 — every model registered
    from app.models.tenant._mixins import hold_models

    return frozenset(str(model.__tablename__) for model in hold_models())


#: Every table whose rows can be held.
HOLDABLE_TABLES: frozenset[str] = _holdable()

#: The policy that hides held rows, on each holdable table.
HELD_POLICY = "held_restrict"

#: Who reads a held row: the system engine, and a ``moderate`` grantee
#: (``app.db.authorization.READS_HELD``), read once per statement.
HELD_READERS = "((SELECT reads_held())::boolean)"

_SECTION = """\
-- ===========================================================================
-- Holds (app.db.holds): a held row reads as absent to the community, admins
-- included, and only the system engine changes it. Nothing deletes it.
-- ==========================================================================="""


def held_guard_fn() -> str:
    """``public.fn_held_guard()``: refuse a DELETE of a held row, and an
    UPDATE from anyone but the system engine."""
    return f"""
CREATE OR REPLACE FUNCTION public.fn_held_guard() RETURNS trigger
    LANGUAGE plpgsql AS $held_guard$
BEGIN
    IF TG_OP = 'UPDATE' AND {SYSTEM_SESSION} THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'held content is preserved as it is'
        USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{HELD_CONSTRAINT}';
END;
$held_guard$;
"""


def _table_block(table: str) -> str:
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"DROP POLICY IF EXISTS {HELD_POLICY} ON {table};",
            f"CREATE POLICY {HELD_POLICY} ON {table} AS RESTRICTIVE FOR ALL",
            f"  USING (held_at IS NULL OR {HELD_READERS})",
            f"  WITH CHECK (held_at IS NULL OR {IN_POLICY.system});",
            (
                f"CREATE OR REPLACE TRIGGER {object_name('tr', table, 'held_guard')} "
                f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                "WHEN (OLD.held_at IS NOT NULL) "
                "EXECUTE FUNCTION public.fn_held_guard();"
            ),
        ]
    )


def _record_block() -> str:
    """``content_holds``: the system engine and a ``moderate`` grantee read
    it, and the system engine writes it."""
    from app.db.guild_ddl import _policies

    return "\n".join(
        [
            "ALTER TABLE content_holds ENABLE ROW LEVEL SECURITY;",
            "ALTER TABLE content_holds FORCE ROW LEVEL SECURITY;",
            *_policies(
                "content_holds", "platform_hold", HELD_READERS, IN_POLICY.system
            ),
        ]
    )


def render_holds_ddl(tools: ToolSet) -> str:
    """Everything above, for one guild schema with ``tools``: a tool
    plug-in's tables carry the hold columns from the same mixin. Rendered
    after every table's own row security is on."""
    holdable = HOLDABLE_TABLES | tools.tables_carrying("held_at")
    blocks = [_table_block(table) for table in sorted(holdable)]
    return "\n\n".join([_SECTION, held_guard_fn(), *blocks, _record_block()])


class HoldsInForce(Exception):
    """A community whose content the platform holds is not destroyed."""

    def __init__(self, guild_id: int, count: int) -> None:
        super().__init__(f"guild {guild_id} has {count} hold(s) in force")
        self.guild_id = guild_id
        self.count = count


async def holds_in_force(guild_id: int) -> int:
    """How many holds are in force in ``guild_id``'s community. Zero for one
    whose schema or role is already gone: nothing there can be read, or held."""
    from sqlalchemy import text

    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.schema_provisioning import guild_role_name, guild_schema_name
    from app.db.session import set_rls_context

    schema = guild_schema_name(guild_id)
    async with cohorts.system_session(guild_id) as session:
        present = (
            await session.exec(
                text(
                    "SELECT to_regclass(:table) IS NOT NULL"
                    " AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"
                ),
                params={
                    "table": f'"{schema}".content_holds',
                    "role": guild_role_name(guild_id),
                },
            )
        ).scalar()
        if not present:
            return 0
        await set_rls_context(session, SystemGuild(guild_id, read_only=True))
        count = (
            await session.exec(
                text("SELECT count(*) FROM content_holds WHERE released_at IS NULL")
            )
        ).scalar()
        await session.rollback()
    return int(count or 0)


async def refuse_while_held(guild_id: int) -> None:
    """Raise :class:`HoldsInForce` while the platform holds anything in
    ``guild_id``'s community."""
    count = await holds_in_force(guild_id)
    if count:
        raise HoldsInForce(guild_id, count)
