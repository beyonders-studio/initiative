"""What the operations community's schema has that no other community's does.

The operations community is the one ``app_settings.operations_guild_id``
names. Two things exist there alone:

* **Its tables**, :data:`app.db.tenancy.OPERATIONS_TABLES`: where each stream
  lands, the cases, and the access grants each case asked for. Provisioning
  leaves them out of every community, and they are created here from
  ``guild_template`` with their policies, grants and the sweeps only this
  community runs (``app.services.guild_sweeps.Scope.OPERATIONS``). Their
  presence is how a session tells it is in the operations community
  (:func:`holds_operations`).
* **The filer role**, ``guild_<ops>_filer``, below.

Choosing the operations community creates both. Moving the choice to another
community drops both from the one it leaves, with the files its cases held.
Clearing it drops the filer role and keeps the tables, so choosing the same
community again finds its streams where they were. Boot re-asserts them and
removes what a move left behind.

What the person who filed a case may read of it is held by the database. A
filer is not a member of the operations community. They reach the cases they
filed, and within those only their status and the part of the conversation
said to them, through the filer role. Two things bound it, and both are the
database's:

* **Grants.** The role holds ``SELECT`` on the columns in
  :data:`FILER_TABLE_ACCESS` and on the columns the community's own row
  policies read while deciding a statement, and on nothing else: not the
  roster, not the initiatives' settings, not a task's title or description,
  not a property. A column it was not granted is refused outright, whatever a
  query asks.
* **Rows.** One permissive policy per granted table, ``TO`` this role alone,
  admits the rows of cases whose ``filer_user_id`` is the routed account: the
  case, its task, the task's status, the stream's binding, and the comments on
  the task said to the filer. Every other policy on those tables answers no
  for a filer, who holds no standing in the community.

The role writes nothing. A filer's reply goes through the filing service, on
the writer's own session, after a read through this role has confirmed the
case is theirs.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import gucs
from app.db.advisory_locks import LockNamespace, advisory_lock, advisory_unlock
from app.db import session as db_session
from app.db.tenancy import OPERATIONS_TABLES

logger = logging.getLogger(__name__)

#: The operations table whose presence :func:`holds_operations` reads.
OPERATIONS_MARKER = "intake_cases"

#: The filer role's suffix. Not a ``GuildRoleKind``: those exist in every
#: community, and this one exists only in the operations community.
FILER_ROLE_SUFFIX = "_filer"

#: What a filer reads, by table and column. The case and what they called it;
#: its task's status, never its title or description; the statuses' kinds;
#: which status of the stream's project means "waiting on you"; and the
#: comments, of which the row policy admits only those said to them.
FILER_TABLE_ACCESS: dict[str, tuple[str, ...]] = {
    "intake_cases": (
        "id",
        "task_id",
        "stream",
        "topic",
        "filer_user_id",
        "filer_subject",
        "opened_at",
    ),
    "tasks": ("id", "project_id", "task_status_id", "updated_at", "deleted_at"),
    "task_statuses": ("id", "project_id", "category"),
    "intake_bindings": ("id", "stream", "project_id", "awaiting_filer_status_id"),
    "comments": (
        "id",
        "task_id",
        "content",
        "created_by",
        "created_at",
        "updated_at",
        "audience",
        "deleted_at",
        "deleted_by",
    ),
    # Their own attachments: what they are and when they sent them. Never the
    # stored key or the wrapped key: serving reads those on its own session
    # once this read has shown the file is theirs.
    "evidence": (
        "id",
        "case_task_id",
        "comment_id",
        "display_name",
        "content_type",
        "size_bytes",
        "created_by",
        "created_at",
    ),
}

#: Columns the community's own row policies read while deciding a filer's
#: statement — the child tables' read shortcut into their parent, and the
#: statements of the gate functions those policies call. A function keeps its
#: statements' plans for the session, and a kept plan is checked against every
#: column it names, including those in a branch this call never takes. Granted
#: so a policy can be evaluated, not so a filer can read them: their rows
#: answer no.
POLICY_READS: dict[str, tuple[str, ...]] = {
    "projects": ("id", "initiative_id", "held_at"),
    "moderation_reports": ("id", "initiative_id"),
    # Every holdable table's ``held_restrict`` reads ``held_at``
    # (``app.db.holds``), whoever is reading.
    "tasks": ("held_at",),
    "comments": ("held_at",),
}

#: The row each granted table admits a filer to, as SQL over that table, with
#: ``{s}`` for the community's schema: a policy binds the tables it names when
#: it is created, not when it is read.
_UID = gucs.USER_ID.once
_CASES = gucs.FILER_CASES.once
FILER_ROWS: dict[str, str] = {
    # The one read of a filer's own cases: the seam takes their tasks from
    # here into ``app.filer_cases``, which the rows below read instead of
    # ``intake_cases`` — whose own policy reads ``tasks``, and a policy may not
    # come back round to its own table.
    "intake_cases": f"filer_user_id = {_UID}",
    "tasks": f"id = ANY ({_CASES})",
    "task_statuses": (
        'EXISTS (SELECT 1 FROM "{s}".tasks t WHERE t.task_status_id = task_statuses.id)'
    ),
    "intake_bindings": (
        'EXISTS (SELECT 1 FROM "{s}".intake_cases c'
        " WHERE c.stream = intake_bindings.stream)"
    ),
    "comments": f"audience = 'filer' AND task_id = ANY ({_CASES})",
    "evidence": f"created_by = {_UID} AND case_task_id = ANY ({_CASES})",
}

#: The policies that hold a filer to those rows, on each table: one
#: PERMISSIVE that admits them, and one RESTRICTIVE that admits nothing else.
#: The second is what keeps a child table's read shortcut — "whoever reads the
#: parent reads its rows" — from handing a filer the staff's comments on a
#: task they may read.
FILER_POLICY = "filer_read"
FILER_ONLY_POLICY = "filer_only"


def filer_role_name(guild_id: int) -> str:
    """The filer role for ``guild_id``, e.g. ``guild_7_filer``."""
    return f"{settings.GUILD_ROLE_PREFIX}guild_{int(guild_id)}{FILER_ROLE_SUFFIX}"


def filer_role_pattern() -> str:
    """A Postgres regex matching every community's filer role."""
    return f"^{settings.GUILD_ROLE_PREFIX}guild_[0-9]+{FILER_ROLE_SUFFIX}$"


def _grant_statements(schema: str, role: str) -> list[str]:
    from app.db.schema_provisioning import APP_LOGIN_ROLE

    stmts = [
        f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{role}"',
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"',
        # The shared type and functions the community's policies call resolve
        # in public; no table there is granted.
        f'GRANT USAGE ON SCHEMA public TO "{role}"',
    ]
    readable: dict[str, tuple[str, ...]] = {}
    for source in (FILER_TABLE_ACCESS, POLICY_READS):
        for table, columns in source.items():
            seen = readable.get(table, ())
            readable[table] = seen + tuple(c for c in columns if c not in seen)
    for table, columns in sorted(readable.items()):
        cols = ", ".join(f'"{c}"' for c in columns)
        stmts.append(f'GRANT SELECT ({cols}) ON "{schema}"."{table}" TO "{role}"')
    stmts.append(f'GRANT "{role}" TO "{APP_LOGIN_ROLE}" WITH INHERIT FALSE')
    return stmts


def _policy_statements(schema: str, role: str) -> list[str]:
    # The setting functions a policy reads resolve in the community's schema,
    # bound when the policy is created.
    stmts: list[str] = [f'SET search_path TO "{schema}", public']
    for table, template in sorted(FILER_ROWS.items()):
        rows = template.replace("{s}", schema)
        for name, kind in (
            (FILER_POLICY, "PERMISSIVE"),
            (FILER_ONLY_POLICY, "RESTRICTIVE"),
        ):
            stmts.append(f'DROP POLICY IF EXISTS {name} ON "{schema}"."{table}"')
            stmts.append(
                f'CREATE POLICY {name} ON "{schema}"."{table}" AS {kind}'
                f' FOR SELECT TO "{role}" USING ({rows})'
            )
    stmts.append("SET search_path TO public")
    return stmts


async def _role_exists(conn: AsyncConnection, role: str) -> bool:
    return bool(
        await conn.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
        )
    )


async def _provision(conn: AsyncConnection, guild_id: int) -> None:
    from app.db.schema_provisioning import _exec_batch, guild_schema_name

    schema = guild_schema_name(guild_id)
    role = filer_role_name(guild_id)
    await advisory_lock(conn, LockNamespace.GUILD_PROVISION, guild_id)
    statements = []
    if not await _role_exists(conn, role):
        statements.append(f'CREATE ROLE "{role}" NOLOGIN')
    statements += _grant_statements(schema, role)
    statements += _policy_statements(schema, role)
    await _exec_batch(conn, statements)


async def _deprovision(conn: AsyncConnection, role: str, schema: Optional[str]) -> None:
    from app.db.schema_provisioning import _exec_batch

    if not await _role_exists(conn, role):
        return
    provisioning_login, _ = settings.database_login("DATABASE_URL")
    statements = []
    if schema is not None and await conn.scalar(
        text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": schema}
    ):
        statements += [
            f'DROP POLICY IF EXISTS {name} ON "{schema}"."{table}"'
            for table in sorted(FILER_ROWS)
            for name in (FILER_POLICY, FILER_ONLY_POLICY)
        ]
    statements += [
        # DROP OWNED needs the role's privileges, not only ADMIN OPTION on it.
        f'GRANT "{role}" TO "{provisioning_login}"',
        f'DROP OWNED BY "{role}"',
        f'DROP ROLE "{role}"',
    ]
    await _exec_batch(conn, statements)


async def holds_operations(conn: AsyncConnection | AsyncSession, schema: str) -> bool:
    """Whether ``schema`` has the operations tables, which they all mark
    together: created and dropped as one."""
    return bool(
        await conn.scalar(
            text("SELECT to_regclass(:t) IS NOT NULL"),
            {"t": f'"{schema}".{OPERATIONS_MARKER}'},
        )
    )


async def operations_schemas(conn: AsyncConnection) -> set[str]:
    """The community schemas that have the operations tables: the operations
    community's, and any a move has not finished leaving."""
    from app.db.guild_migrations import GUILD_SCHEMA_REGEX

    rows = await conn.execute(
        text(
            "SELECT n.nspname FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :t AND c.relkind = 'r' AND n.nspname ~ :schemas"
        ),
        {"t": OPERATIONS_MARKER, "schemas": GUILD_SCHEMA_REGEX},
    )
    return set(rows.scalars())


async def provision_operations(guild_id: int) -> None:
    """Make ``guild_id``'s schema the operations community's: its tables, with
    everything provisioning applies to them, where they are not there yet, and
    the filer role re-asserted. Idempotent."""
    from app.db.schema_provisioning import PARTS, _apply_parts, guild_schema_name

    schema = guild_schema_name(guild_id)
    async with db_session.provisioning_engine.begin() as conn:
        await advisory_lock(conn, LockNamespace.GUILD_PROVISION, guild_id)
        if not await holds_operations(conn, schema):
            await _apply_parts(conn, guild_id, PARTS, operations=True)
        await _provision(conn, guild_id)


async def deprovision_operations(guild_id: int) -> None:
    """Take from ``guild_id``'s schema what only the operations community has:
    the files its cases held, the filer role, the operations community's own
    sweep triggers, and the operations tables. Safe where there are none.

    One transaction: the tables are locked first, so whoever is writing a
    case finishes before the files are read and nobody starts another; the
    tables go before anyone else can reach them.
    """
    from app.db.schema_provisioning import _exec_batch, guild_schema_name
    from app.db.timers import drop_operations_timers_ddl
    from app.services import sweep_timers
    from app.services.guild_sweeps import Scope
    from app.services.platform import evidence

    schema = guild_schema_name(guild_id)
    tables = [f'"{schema}".{table}' for table in sorted(OPERATIONS_TABLES)]
    gone: list[str] = []
    async with db_session.provisioning_engine.begin() as conn:
        await advisory_lock(conn, LockNamespace.GUILD_PROVISION, guild_id)
        holds = await holds_operations(conn, schema)
        if holds:
            await conn.exec_driver_sql(
                f"LOCK TABLE {', '.join(tables)} IN ACCESS EXCLUSIVE MODE"
            )
            gone = await _drop_case_files(conn, schema)
        # The filer's policies first: some are on the tables that go next.
        await _deprovision(conn, filer_role_name(guild_id), schema)
        if holds:
            statements = [
                f'SET LOCAL search_path TO "{schema}", public',
                *(s for s in drop_operations_timers_ddl().split(";\n") if s),
            ]
            # Every table's policies, then row security, then the tables: a
            # policy on one may read another.
            for table in tables:
                statements += [
                    f'DROP POLICY IF EXISTS "{name}" ON {table}'
                    for name in (
                        await conn.execute(
                            text(
                                "SELECT polname FROM pg_policy"
                                " WHERE polrelid = to_regclass(:t)"
                            ),
                            {"t": table},
                        )
                    ).scalars()
                ]
                statements.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
            statements += [f"DROP TABLE {table}" for table in tables]
            await _exec_batch(conn, statements)
    if holds:
        evidence.discard(guild_id, gone)
        await sweep_timers.disarm(
            guild_id,
            (s.kind for s in sweep_timers.sweeps() if s.scope is Scope.OPERATIONS),
        )


async def _drop_case_files(conn: AsyncConnection, schema: str) -> list[str]:
    """Delete the rows of the files ``schema``'s cases held, and return the
    stored objects no remaining row names, to remove once the transaction has
    committed. Row security is lifted from ``evidence`` for the delete and put
    back as it was."""
    evidence = f'"{schema}".evidence'
    forced = await conn.scalar(
        text("SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"),
        {"t": evidence},
    )
    if forced:
        await conn.exec_driver_sql(
            f"ALTER TABLE {evidence} NO FORCE ROW LEVEL SECURITY"
        )
    keys = set(
        (
            await conn.execute(
                text(
                    f"DELETE FROM {evidence} WHERE case_task_id IS NOT NULL"
                    " RETURNING storage_key"
                )
            )
        ).scalars()
    )
    still = (
        set(
            (
                await conn.execute(
                    text(
                        f"SELECT storage_key FROM {evidence} WHERE storage_key = ANY(:k)"
                    ),
                    {"k": sorted(keys)},
                )
            ).scalars()
        )
        if keys
        else set()
    )
    if forced:
        await conn.exec_driver_sql(f"ALTER TABLE {evidence} FORCE ROW LEVEL SECURITY")
    return sorted(keys - still)


async def reconcile_operations() -> None:
    """Make the operations tables and the filer role exist where the
    operations community is, as the deployment names it now.

    Run when the choice changes, and by boot after the guild back-fill:
    re-asserts the operations community's, and takes them from every other
    community, left behind by a move the process did not finish. With no
    operations community, only the filer role goes: the tables stay for the
    community that had them, until another is chosen.

    One runs at a time across the deployment, and each reads the choice once
    it has its turn: one that started before a later choice acts on the later
    one.
    """
    from app.services.platform.intake import configured_operations_guild_id

    async with db_session.provisioning_engine.connect() as turn:
        await advisory_lock(turn, LockNamespace.OPERATIONS_CHOICE, xact=False)
        await turn.commit()
        try:
            await _reconcile(await configured_operations_guild_id())
        finally:
            await advisory_unlock(turn, LockNamespace.OPERATIONS_CHOICE)


async def _reconcile(operations_guild_id: Optional[int]) -> None:
    from app.db.schema_provisioning import guild_schema_name

    keep = guild_schema_name(operations_guild_id) if operations_guild_id else None
    async with db_session.provisioning_engine.begin() as conn:
        holders = await operations_schemas(conn)
        roles = (
            await conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname ~ :p"),
                {"p": filer_role_pattern()},
            )
        ).scalars()
        prefix = len(settings.GUILD_ROLE_PREFIX) + len("guild_")
        left = {int(schema.removeprefix("guild_")) for schema in holders} | {
            int(role[prefix : -len(FILER_ROLE_SUFFIX)]) for role in roles
        }
        exists = operations_guild_id is not None and bool(
            await conn.scalar(
                text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": keep}
            )
        )
    for guild_id in sorted(left - {operations_guild_id}):
        if operations_guild_id is None:
            async with db_session.provisioning_engine.begin() as conn:
                await _deprovision(
                    conn, filer_role_name(guild_id), guild_schema_name(guild_id)
                )
            continue
        logger.info(
            "operations: leaving community %s, no longer the operations one",
            guild_id,
        )
        await deprovision_operations(guild_id)
    if exists:
        await provision_operations(operations_guild_id)
