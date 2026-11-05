"""What the person who filed a case may read of it, held by the database.

A filer is not a member of the operations community. They reach the cases they
filed, and within those only their status and the part of the conversation
said to them, through one role that exists in the operations community alone:
``guild_<ops>_filer``. Choosing the operations community creates it; moving or
clearing that choice drops it; boot re-asserts it and removes any copy left in
a community that is no longer the operations one.

Two things bound it, and both are the database's:

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

from app.core.config import settings
from app.db import gucs
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db import session as db_session

logger = logging.getLogger(__name__)

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


async def provision_filer_access(guild_id: int) -> None:
    """Create or re-assert the filer role, its grants and its policies in
    ``guild_id``. Idempotent."""
    async with db_session.provisioning_engine.begin() as conn:
        await _provision(conn, guild_id)


async def deprovision_filer_access(guild_id: int) -> None:
    """Drop ``guild_id``'s filer role and policies. Safe where there are none."""
    from app.db.schema_provisioning import guild_schema_name

    async with db_session.provisioning_engine.begin() as conn:
        await _deprovision(conn, filer_role_name(guild_id), guild_schema_name(guild_id))


async def reconcile_filer_access(operations_guild_id: Optional[int]) -> None:
    """Make the filer role exist exactly where the operations community is.

    Boot's half of the lifecycle, after the guild back-fill: re-asserts the
    operations community's role, grants and policies, and drops every other
    community's — left behind by a move the process did not finish.
    """
    from app.db.schema_provisioning import guild_schema_name

    keep = filer_role_name(operations_guild_id) if operations_guild_id else None
    async with db_session.provisioning_engine.begin() as conn:
        found = (
            await conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname ~ :p"),
                {"p": filer_role_pattern()},
            )
        ).scalars()
        strays = [role for role in found if role != keep]
    for role in strays:
        guild_id = int(
            role[
                len(settings.GUILD_ROLE_PREFIX) + len("guild_") : -len(
                    FILER_ROLE_SUFFIX
                )
            ]
        )
        logger.info(
            "filer access: dropping %s, no longer the operations community", role
        )
        async with db_session.provisioning_engine.begin() as conn:
            await _deprovision(conn, role, guild_schema_name(guild_id))
    if operations_guild_id is not None:
        await provision_filer_access(operations_guild_id)
