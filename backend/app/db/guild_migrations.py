"""Apply a guild-scoped schema change to every guild schema, from a migration.

Under schema-per-guild a guild-scoped table (tasks, projects, files, …)
exists once per guild schema — ``guild_template``, ``guild_1.tasks``,
``guild_2.tasks``, … A normal Alembic migration runs once against ``public``, so
it would change none of them.

The forward pattern has two halves, kept in sync:

1. **Existing guilds (and the template)** — a guild-scoped migration calls
   :func:`apply_to_all_guild_schemas` in its ``upgrade()`` (and the reverse in
   ``downgrade()``); the targets include ``guild_template``. The migration owns
   the DDL (so the migration stays a self-contained, immutable record of *what*
   changed); this helper only owns the stable mechanism of *where* it runs.

2. **New guilds** — provisioning reflects the LIVE ``guild_template`` (see
   ``app.db.guild_ddl`` / ``schema_provisioning.get_provisioning_bundle``), so
   guilds created later include the change by construction — nothing to
   regenerate or commit.

The **drift-guard test** (``schema_provisioning_test``) provisions a fresh
schema and diffs it against ``guild_template`` as a clone-fidelity check.

``public`` is never a target: guild-content tables exist only in guild schemas
(20260811_0163 dropped the last frozen pre-squash copies).

Example migration::

    from alembic import op
    from app.db.guild_migrations import apply_to_all_guild_schemas

    def upgrade() -> None:
        apply_to_all_guild_schemas(
            op.get_bind(),
            "ALTER TABLE tasks ADD COLUMN archived boolean NOT NULL DEFAULT false",
        )

    def downgrade() -> None:
        apply_to_all_guild_schemas(op.get_bind(), "ALTER TABLE tasks DROP COLUMN archived")
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

#: Every provisioned guild schema, ``guild_<id>``
#: (``schema_provisioning.guild_schema_name``).
GUILD_SCHEMA_REGEX = "^guild_[0-9]+$"
#: Those plus ``guild_template``, which guild migrations also maintain.
GUILD_OR_TEMPLATE_SCHEMA_REGEX = "^guild_([0-9]+|template)$"

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_0-9]*\$")


def split_sql_statements(sql: str) -> list[str]:
    """Split an SQL script into single statements for asyncpg's extended
    (one-statement-per-execute) protocol.

    Handles ``--`` line comments, ``/* … */`` block comments (nested, as
    Postgres allows), single-quoted strings, and dollar-quoted bodies
    (``$$ … $$`` / ``$tag$ … $tag$``), so a ``;`` inside any of those does not
    split. Used by migrations that RUN the committed SQL artifacts
    (the baseline snapshots; the runtime-rendered guild DDL)."""
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    dollar_tag: str | None = None
    while i < n:
        ch = sql[i]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue
        if ch == "-" and sql.startswith("--", i):
            eol = sql.find("\n", i)
            i = n if eol == -1 else eol + 1  # drop comment, keep statement flow
            continue
        if ch == "/" and sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):  # Postgres block comments nest
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            continue  # dropped, like line comments
        if ch == "'":
            end = i + 1
            while end < n:
                if sql[end] == "'":
                    if end + 1 < n and sql[end + 1] == "'":  # escaped ''
                        end += 2
                        continue
                    break
                end += 1
            buf.append(sql[i : end + 1])
            i = end + 1
            continue
        if ch == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                dollar_tag = m.group(0)
                buf.append(dollar_tag)
                i = m.end()
                continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def guild_schema_names(connection: Connection) -> list[str]:
    """Every provisioned guild schema (``guild_<id>`` and ``guild_template`` if
    present), sorted. For guild-scoped migrations."""
    rows = connection.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname ~ :pat ORDER BY nspname"),
        {"pat": GUILD_OR_TEMPLATE_SCHEMA_REGEX},
    )
    return [row[0] for row in rows]


def run_for_each_guild_schema(
    connection: Connection, fn, *, operations: bool = False
) -> None:
    """Run a migration-op callback once per guild schema (``guild_template`` +
    every ``guild_<id>``), with ``search_path`` routed so unqualified names
    resolve in that schema (shared types fall through to ``public``).
    ``operations`` runs it in ``guild_template`` and the schema that has the
    operations tables (``app.db.tenancy.OPERATIONS_TABLES``) instead.

    The callback form of :func:`apply_to_all_guild_schemas`, used by
    GUILD-SCOPED AUTOGENERATED migrations (``scripts/gen_guild_migration.py``):
    the generated ``op.*`` calls execute against unqualified table names, so
    routing the search_path per schema applies them everywhere. Same
    transaction-local mechanics as the string variant below.
    """
    from app.db.operations_schema import OPERATIONS_MARKER

    for schema in guild_schema_names(connection):
        if (
            operations
            and schema != "guild_template"
            and not connection.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"),
                {"t": f'"{schema}".{OPERATIONS_MARKER}'},
            ).scalar()
        ):
            continue
        connection.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        fn()
    connection.execute(text("SELECT set_config('search_path', 'public', true)"))


def apply_to_all_guild_schemas(
    connection: Connection,
    *statements: str,
) -> None:
    """Run schema-relative DDL in every guild schema (``guild_template`` +
    every ``guild_<id>``).

    Each statement must be written WITHOUT a schema qualifier — e.g.
    ``ALTER TABLE tasks ADD COLUMN …`` — because it is run once per target schema
    with ``search_path`` pointed there (unqualified table/enum names resolve in
    that schema, falling through to ``public`` for shared types). Pass several
    statements to apply them as an ordered group per schema.

    Must run inside a transaction (migrations always do): the per-schema
    ``search_path`` is set with ``is_local=true`` so it's scoped to that
    transaction. If a statement fails, the error propagates uncaught and the
    transaction rollback reverts the search_path — there is deliberately no
    ``finally`` reset, which on an aborted transaction would itself raise and
    mask the original error (and could strand a stale search_path on the
    connection). On success we reset to ``public`` for any later statements in
    the same transaction, since Alembic may batch migrations into one.

    Newly provisioned guilds pick the change up automatically: provisioning
    reflects the LIVE ``guild_template`` (``app.db.guild_ddl``).
    """
    for schema in guild_schema_names(connection):
        # set_config (not SET) so it lands on this exact connection, matching how
        # set_rls_context routes; is_local=true scopes it to the transaction.
        # Schema names come from pg_namespace, so they're already safe identifiers.
        connection.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        for statement in statements:
            connection.execute(text(statement))
    connection.execute(text("SELECT set_config('search_path', 'public', true)"))
