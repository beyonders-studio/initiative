"""Enforcement for the initiative-member RLS layer.

Two guarantees, mirroring how ``tenancy_test.py`` keeps the table classification
honest:

- **Presence** (DB): in a freshly provisioned guild schema, every
  ``INITIATIVE_SCOPED_TABLES`` table actually has ``FORCE`` RLS + all four
  ``initiative_member_*`` policies, and no ``GUILD_LEVEL_TABLES`` table does.
  So an initiative-level table cannot reach a live schema without its policies.
- **Agreement** (pure): the governing tool the app layer reads out of the
  registry is the one the rendered policy actually asks about. The endpoints
  resolving a sub-resource's parent and the policy gating that sub-resource's
  rows come from one declaration, and this is what keeps them there.
"""

import pytest
from sqlalchemy import text

from app.core.reactions import ReactionTarget
from app.db.initiative_rls import (
    COMMENT_PARENTS,
    CONTENT_KIND_TABLES,
    entity_tables,
    initiative_of,
    render_entity_access_fn,
)
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)
from app.db.guild_ddl import _QUERY_TOMBSTONES
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import (
    MANAGED_TABLES,
    GUILD_LEVEL_TABLES,
    INITIATIVE_SCOPED_TABLES,
    LEDGER_TABLES,
    OWN_ROW_TABLES,
    PRIVATE_ROW_SHARED_READ,
    PRIVATE_ROW_TABLES,
    SEAT_TABLES,
)

pytestmark = pytest.mark.always

_EXPECTED_POLICIES = {
    "initiative_member_select",
    "initiative_member_insert",
    "initiative_member_update",
    "initiative_member_delete",
}

_OWN_ROW_POLICIES = {
    "own_row_select",
    "own_row_insert",
    "own_row_update",
    "own_row_delete",
}

_GID_POLICIES = 990_201
_GID_PURGE = 990_202
_GID_OWN_ROW = 990_203
_GID_FUNCTIONS = 990_204

# EVERY soft-delete table carries the RESTRICTIVE admin-only purge guard. They split
# by how RLS reaches the table: initiative-scoped ones already have RLS (for the
# membership gate); the guild-level ones (initiatives, tags) get RLS enabled SOLELY
# to host the guard, with a permissive allow-all (guild_level_open) — isolation is
# the schema boundary, initiative is the gate, so this is not a membership scope.
_PURGE_GUARD_TABLES = frozenset(SOFT_DELETE_TABLES)
_GUILD_LEVEL_PURGE = (
    frozenset(SOFT_DELETE_TABLES) - INITIATIVE_SCOPED_TABLES - set(MANAGED_TABLES)
)
_MANAGED_POLICIES = frozenset(
    {"managed_select", "managed_insert", "managed_update", "managed_delete"}
)


async def test_a_provisioned_schema_holds_its_own_authorization_functions(engine):
    """The functions a schema's policies call live in that schema, and no
    policy in it binds a function anywhere else. The legacy
    ``is_initiative_member`` rule stays gone (dropped in migration 0111)."""
    from app.db.authorization import GUILD_FUNCTION_SIGNATURES

    schema = guild_schema_name(_GID_FUNCTIONS)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_FUNCTIONS)
        async with engine.connect() as conn:
            local = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT proname FROM pg_proc "
                        "WHERE pronamespace = CAST(:s AS regnamespace)"
                    ),
                    {"s": schema},
                )
            }
            outside = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT n.nspname || '.' || f.proname "
                            "FROM pg_policy p "
                            "JOIN pg_class c ON c.oid = p.polrelid "
                            "JOIN pg_depend d ON d.classid = 'pg_policy'::regclass "
                            "AND d.objid = p.oid "
                            "JOIN pg_proc f ON d.refclassid = 'pg_proc'::regclass "
                            "AND f.oid = d.refobjid "
                            "JOIN pg_namespace n ON n.oid = f.pronamespace "
                            "WHERE c.relnamespace = CAST(:s AS regnamespace) "
                            "AND n.nspname <> CAST(:name AS text) ORDER BY 1"
                        ),
                        {"s": schema, "name": schema},
                    )
                )
                .scalars()
                .all()
            )
            legacy = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_proc WHERE proname = 'is_initiative_member'"
                    )
                )
            ).scalar()
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_FUNCTIONS)
    assert local == set(GUILD_FUNCTION_SIGNATURES), (
        f"{schema} holds {sorted(local)}; expected exactly "
        f"{sorted(GUILD_FUNCTION_SIGNATURES)}"
    )
    assert outside == [], f"policies in {schema} bind functions outside it: {outside}"
    assert legacy == 0, "is_initiative_member still exists (see migration 0111)"


async def test_every_initiative_scoped_table_has_policies(engine):
    """Provision a real guild schema and verify the policy invariant per table."""
    schema = guild_schema_name(_GID_POLICIES)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_POLICIES)
        async with engine.connect() as conn:
            pol_rows = await conn.execute(
                text(
                    "SELECT tablename, policyname, permissive FROM pg_policies "
                    "WHERE schemaname = :s"
                ),
                {"s": schema},
            )
            policies: dict[str, set[str]] = {}
            kinds: dict[tuple[str, str], str] = {}
            for tbl, pol, kind in pol_rows:
                policies.setdefault(tbl, set()).add(pol)
                kinds[(tbl, pol)] = kind

            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}

        # A private-row table narrows its gate to its member: RESTRICTIVE, and
        # with no SELECT policy of its own where the initiative reads it.
        for tbl in sorted(PRIVATE_ROW_TABLES):
            private = {
                p for p in policies.get(tbl, set()) if p.startswith("private_row_")
            }
            commands = {"insert", "update", "delete"}
            if tbl not in PRIVATE_ROW_SHARED_READ:
                commands.add("select")
            assert private == {f"private_row_{c}" for c in commands}, tbl
            assert {kinds[(tbl, p)] for p in private} == {"RESTRICTIVE"}, tbl

        # Every initiative-scoped table: FORCE RLS + the four policies.
        for tbl in sorted(INITIATIVE_SCOPED_TABLES):
            enabled, forced = rls.get(tbl, (False, False))
            assert enabled and forced, (
                f"{tbl} is initiative-scoped but RLS is not ENABLED+FORCED "
                f"(enabled={enabled}, forced={forced}) — regenerate guild_rls.sql."
            )
            missing = _EXPECTED_POLICIES - policies.get(tbl, set())
            assert not missing, (
                f"{tbl} is initiative-scoped but missing policies {sorted(missing)} "
                "— add a path in scripts/gen_guild_rls.py and regenerate."
            )

        # No guild-level table should carry the initiative-member policies.
        for tbl in sorted(GUILD_LEVEL_TABLES):
            leaked = _EXPECTED_POLICIES & policies.get(tbl, set())
            assert not leaked, (
                f"{tbl} is GUILD_LEVEL (exempt) but has initiative_member policies "
                f"{sorted(leaked)} — it should not. Reclassify or remove the path."
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_POLICIES)


async def test_managed_tables_are_written_by_their_managers(engine):
    """Every ``MANAGED_TABLES`` table gets FORCE RLS, an open read and the
    three ``managed_*`` write policies in a freshly provisioned schema; the
    soft-deletable one keeps its purge guard beside them."""
    gid = 990_031
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename, policyname, cmd FROM pg_policies "
                    "WHERE schemaname = :s"
                ),
                {"s": schema},
            )
            policies: dict[str, dict[str, str]] = {}
            for tbl, pol, cmd in rows:
                policies.setdefault(tbl, {})[pol] = cmd
            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}
        for tbl in sorted(MANAGED_TABLES):
            assert rls.get(tbl) == (True, True), f"{tbl} must be ENABLED+FORCED"
            have = policies.get(tbl, {})
            assert _MANAGED_POLICIES <= set(have), (
                f"{tbl} is managed but has {sorted(have)}"
            )
            assert "guild_level_open" not in have, f"{tbl} still carries the allow-all"
            if tbl in SOFT_DELETE_TABLES:
                assert have.get("soft_delete_admin_purge") == "DELETE", tbl
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_own_row_tables_have_policies(engine):
    """Every ``OWN_ROW_TABLES`` table gets FORCE RLS + the four ``own_row_*``
    policies in a freshly provisioned schema — the row gate that keeps one
    member's rows (e.g. an export job's selector + artifact download) hidden
    from other members — and no ``initiative_member_*`` policies (own-row
    tables are guild-level, not membership-gated)."""
    schema = guild_schema_name(_GID_OWN_ROW)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_OWN_ROW)
        async with engine.connect() as conn:
            pol_rows = await conn.execute(
                text(
                    "SELECT tablename, policyname FROM pg_policies "
                    "WHERE schemaname = :s"
                ),
                {"s": schema},
            )
            policies: dict[str, set[str]] = {}
            for tbl, pol in pol_rows:
                policies.setdefault(tbl, set()).add(pol)

            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}

        for tbl in sorted(OWN_ROW_TABLES):
            enabled, forced = rls.get(tbl, (False, False))
            assert enabled and forced, (
                f"{tbl} is own-row but RLS is not ENABLED+FORCED "
                f"(enabled={enabled}, forced={forced})."
            )
            missing = _OWN_ROW_POLICIES - policies.get(tbl, set())
            assert not missing, (
                f"{tbl} is in OWN_ROW_TABLES but missing policies "
                f"{sorted(missing)} — check guild_ddl._own_row_block."
            )
            leaked = _EXPECTED_POLICIES & policies.get(tbl, set())
            assert not leaked, (
                f"{tbl} is own-row (guild-level) but carries initiative_member "
                f"policies {sorted(leaked)} — it must not be membership-gated."
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_OWN_ROW)


async def test_seat_and_ledger_tables_have_policies(engine):
    """Every ``SEAT_TABLES`` table gets FORCE RLS + the four ``seat_*``
    policies, and every ``LEDGER_TABLES`` table the four ``ledger_*``, in a
    freshly provisioned schema."""
    gid = 990_032
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename, policyname FROM pg_policies "
                    "WHERE schemaname = :s"
                ),
                {"s": schema},
            )
            policies: dict[str, set[str]] = {}
            for tbl, pol in rows:
                policies.setdefault(tbl, set()).add(pol)
            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}
        expected = {t: "seat" for t in SEAT_TABLES} | {
            t: "ledger" for t in LEDGER_TABLES
        }
        for tbl, prefix in sorted(expected.items()):
            assert rls.get(tbl) == (True, True), f"{tbl} must be ENABLED+FORCED"
            want = {f"{prefix}_{c}" for c in ("select", "insert", "update", "delete")}
            assert policies.get(tbl, set()) == want, (
                f"{tbl} has {sorted(policies.get(tbl, set()))}, expected {sorted(want)}"
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_soft_delete_tables_have_admin_only_purge_policy(engine):
    """Hard delete is admin-only at the DB layer: EVERY soft-delete table carries a
    RESTRICTIVE FOR DELETE ``soft_delete_admin_purge`` policy in a freshly
    provisioned schema, so a non-admin DELETE is refused by Postgres even if app
    code were bypassed. The guild-level soft-delete tables (initiatives, tags) have
    RLS enabled solely to host that guard, with a permissive allow-all
    (``guild_level_open``) — not a membership gate (initiative is the gate; guilds
    gate at the schema)."""
    schema = guild_schema_name(_GID_PURGE)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_PURGE)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename, policyname, permissive, cmd FROM pg_policies "
                    "WHERE schemaname = :s "
                    "AND policyname IN ('soft_delete_admin_purge', 'guild_level_open')"
                ),
                {"s": schema},
            )
            by_table: dict[str, dict[str, tuple[str, str]]] = {}
            for tbl, pol, perm, cmd in rows:
                by_table.setdefault(tbl, {})[pol] = (perm, cmd)

            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}

        # Every soft-delete table: the RESTRICTIVE admin-purge guard.
        for tbl in sorted(_PURGE_GUARD_TABLES):
            guard = by_table.get(tbl, {}).get("soft_delete_admin_purge")
            assert guard is not None, (
                f"{tbl} is a soft-delete table but has no soft_delete_admin_purge "
                "policy — regenerate guild_rls.sql (scripts/gen_guild_rls.py)."
            )
            assert guard == ("RESTRICTIVE", "DELETE"), (
                f"{tbl}.soft_delete_admin_purge must be RESTRICTIVE FOR DELETE, "
                f"got {guard[0]} FOR {guard[1]}."
            )

        # Guild-level soft-delete tables: RLS enabled + permissive allow-all so the
        # guard can bind, but NO initiative-member policies (not a membership gate).
        for tbl in sorted(_GUILD_LEVEL_PURGE):
            enabled, forced = rls.get(tbl, (False, False))
            assert enabled and forced, (
                f"{tbl} must have RLS ENABLED+FORCED to host the purge guard "
                f"(enabled={enabled}, forced={forced})."
            )
            assert "guild_level_open" in by_table.get(tbl, {}), (
                f"{tbl} has RLS enabled but no permissive guild_level_open policy "
                "— provisioning would deny all access to it."
            )
            leaked = _EXPECTED_POLICIES & set(by_table.get(tbl, {}))
            assert not leaked, (
                f"{tbl} is guild-level but carries initiative_member policies "
                f"{sorted(leaked)} — it must not be membership-gated."
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_PURGE)


# ---------------------------------------------------------------------------
# Agreement: one declaration, read two ways
# ---------------------------------------------------------------------------


#: Tables the app layer deliberately derives NO single governing tool for, and
#: why. Stated rather than tolerated: a new sub-resource that the app cannot
#: resolve a parent for has to be added here on purpose, which is the moment to
#: notice it needs one.
_NO_SINGLE_PARENT = {
    # Polymorphic — the governing tool is a property of the row, and the policy
    # is a CASE over the column naming it.
    "comments": "one of eight tools, per row",
    "reactions": "one of eight tools, per row",
    "batched_notices": "gated like the task or reaction it describes",
    "personal_items": "any tool or sub-tool, per row",
    "engagement_levels": "any tool or sub-tool, per row",
    "metadata_values": "any tool or sub-tool, per row: read through its own table, written through entity_access, or the install itself",
    "search_entries": "names its tool in dac_tool",
    "tool_layouts": "any viewable tool, per row, or its initiative for a shared tool",
    "share_requests": "any shareable tool, per row: read by the requester and whoever shares it",
    # One tool, two parents: a link must clear the gate on BOTH files, so
    # there is no single row to authorize against.
    # Two parents of any kind: an edge clears the gate on each end through
    # entity_access, which asks each end's own entry here.
    "relationships": "source and target must both clear it, whatever they are",
    # No sharing leg at all — see the registry for each.
    "event_outbox": "names its tool in dac_tool",
    "plugin_event_outbox": "the events plug-ins emit are no tool's own table",
    "metadata_definitions": "initiative, project or collection configuration, or a plug-in's, not a tool's content",
    "resource_grants": "sharing itself; resource_access reads this table",
    "webhook_subscriptions": "integration config, gated by the initiative",
    "guest_invite_grants": "an invite's terms, the community's administration's",
    "uploads": "a stored file, gated by the initiative whose content shows it",
    # No sharing: seen through the files in it, changed by file makers.
    "collections": "seen through its files, changed by the initiative's file makers",
    "collection_files": "read as its file, written as its collection is changed",
    # Gated on full access rather than sharing: the standing that opens these
    # is the one that already reaches every resource, so there is no per-resource
    # grant left to ask about.
    "moderation_reports": "full access in the initiative, not a shared resource",
    "moderation_report_reporters": "reached through the report it belongs to",
    "moderation_actions": "full access in the initiative: the moderation log",
    "evidence": "reached through the report or case it hangs off, whichever it names",
}


def test_the_plugin_reads_the_same_governing_tool_the_policy_asks_about():
    """``governing_path`` must name the tool the rendered sharing leg calls.

    The app layer asks this registry which tool governs a sub-resource — a
    task's project, an event's calendar — and the DDL renderer asks the same
    entry to build the policy. A table where those two answered differently
    would be one where an endpoint authorized against one resource while the
    database gated on another.

    Read off a **write** command. A child's read leg is the walk to its parent
    and nothing else — the parent's own policy is what asks about sharing
    there — so the tool is named on the commands that restate it.
    """
    import re

    from app.db.initiative_rls import (
        INITIATIVE_PATHS,
        dac_asks_at_write,
        governing_path,
    )

    mismatches = []
    for table, path in sorted(INITIATIVE_PATHS.items()):
        derived = governing_path(table)
        leg = (
            path.dac.predicate(table, "UPDATE", dac_asks_at_write(table, "UPDATE"))
            if path.dac
            else None
        )
        asked = set(re.findall(r"resource_access\('([a-z_]+)'", leg or ""))
        if derived is None:
            if table not in _NO_SINGLE_PARENT:
                mismatches.append(
                    f"{table}: policy asks {sorted(asked) or 'nothing'}, app derives "
                    "nothing and the table is not in _NO_SINGLE_PARENT"
                )
            continue
        if asked != {derived[0].value}:
            mismatches.append(
                f"{table}: policy asks {sorted(asked)}, app derives {derived[0].value}"
            )
    assert mismatches == [], mismatches


def test_no_single_parent_names_only_real_tables():
    """The exemption list cannot outlive the tables it names."""
    from app.db.initiative_rls import INITIATIVE_PATHS

    stale = sorted(set(_NO_SINGLE_PARENT) - set(INITIATIVE_PATHS))
    assert stale == [], stale


def test_every_declared_hop_walks_a_real_column_to_a_real_table():
    """``via`` is walked to load a parent, so every step of it has to exist.

    Each hop names a column on the table reached so far and the table that
    column points at, and the walk has to arrive at the governing tool's own
    table. Checking only the first hop would let a renamed intermediate — the
    ``tasks`` in ``task_tags -> tasks -> projects`` — reach CI green and fail
    at the moment something followed it.

    A table absent from the mapped metadata fails rather than skips: it means
    the registry names something the models do not, which is the drift this
    is here to catch.
    """
    import app.db.base  # noqa: F401 — imported for its side effect
    from sqlmodel import SQLModel

    from app.db.initiative_rls import INITIATIVE_PATHS, governing_path

    # app.db.base registers every model, so the metadata is complete whether
    # this runs alone or in a suite. Without it an unimported model looks like
    # registry drift.
    mapped = SQLModel.metadata.tables
    problems: list[str] = []

    for table, _path in sorted(INITIATIVE_PATHS.items()):
        derived = governing_path(table)
        if derived is None:
            continue
        tool, hops = derived

        current = table
        if current not in mapped:
            problems.append(f"{current}: registered but not a mapped table")
            continue

        for column, target in hops:
            if column not in mapped[current].columns:
                problems.append(f"{current}.{column}: no such column")
                break
            if target not in mapped:
                problems.append(f"{current}.{column} -> {target}: no such mapped table")
                break
            current = target
        else:
            # The walk has to end AT the governing resource, not merely near
            # it — that is what makes the tool and the chain one declaration.
            if current != tool.plural:
                problems.append(
                    f"{table}: chain ends at {current}, governed by {tool.value} "
                    f"(expected {tool.plural})"
                )

    assert problems == [], problems


_GID_QUERY_TRASH = 990_412

#: What ``query_excludes_trash`` has to say, as Postgres normalises it.
#:
#: Pinned whole rather than matched loosely: the policy has to say exactly
#: this, so the test is an equality against the rendered predicate. Postgres
#: normalises it the same way for every table, which is what makes that stable
#: to compare.
_QUERY_TRASH_QUAL = (
    "(({column} IS NULL) OR (( SELECT {schema}.setting_query() AS setting_query)"
    " IS NOT TRUE))"
)


async def test_soft_delete_tables_keep_the_trash_out_of_reader_written_sql(engine):
    """Every soft-delete table carries ``query_excludes_trash`` in a freshly
    provisioned schema — RESTRICTIVE, FOR SELECT, and saying the same thing.
    So does every table whose rows are tombstoned, of its own column.

    Asked of the whole set rather than one table, because the rule is that a
    statement a reader wrote reports on live content — and that is a statement
    about every dataset, not about the one a test happened to pick.

    What the policy does is proved end to end against real rows in
    ``query_test.py``: a trashed task is absent from a query, and still there
    through the endpoint that manages the trash. This is the shape, for every
    table, so that proof holds for more than the one table it was run on.
    """
    schema = guild_schema_name(_GID_QUERY_TRASH)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_QUERY_TRASH)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename, permissive, cmd, qual FROM pg_policies "
                    "WHERE schemaname = :s AND policyname = 'query_excludes_trash'"
                ),
                {"s": schema},
            )
            found = {tbl: (perm, cmd, qual) for tbl, perm, cmd, qual in rows}

        columns = dict.fromkeys(SOFT_DELETE_TABLES, "deleted_at") | _QUERY_TOMBSTONES
        missing = sorted(set(columns) - set(found))
        assert not missing, (
            f"these tables have no query_excludes_trash policy: {missing}"
        )

        for tbl, column in sorted(columns.items()):
            permissive, cmd, qual = found[tbl]
            assert (permissive, cmd) == ("RESTRICTIVE", "SELECT"), (
                f"{tbl}.query_excludes_trash must be RESTRICTIVE FOR SELECT, got "
                f"{permissive} FOR {cmd}."
            )
            expected = _QUERY_TRASH_QUAL.format(column=column, schema=schema)
            assert qual == expected, (
                f"{tbl}.query_excludes_trash does not say what it must.\n"
                f"  expected: {expected}\n"
                f"  got:      {qual}"
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_QUERY_TRASH)


# ---------------------------------------------------------------------------
# entity_access: the kinds it answers for
# ---------------------------------------------------------------------------


def test_every_comment_parent_is_a_kind_the_entity_function_answers_for():
    """A comment's policy names its parent as a ``(kind, id)`` pair and asks
    ``entity_access`` about it, so every parent column has to resolve to one of
    the function's arms — at the table the parent actually lives in."""
    tables = entity_tables()
    for parent in COMMENT_PARENTS.values():
        assert parent.kind in tables, parent.column
        assert tables[parent.kind] == parent.table, parent.column


def test_initiative_of_reads_its_own_column_or_walks_to_it():
    assert initiative_of("projects", "x") == "x.initiative_id"
    assert initiative_of("tasks", "x") == (
        "(SELECT h1.initiative_id FROM projects h1 WHERE h1.id = x.project_id)"
    )


def test_every_reaction_target_and_recentable_kind_is_an_arm():
    tables = entity_tables()
    for target in ReactionTarget:
        assert tables[target.value] == target.table
    for kind, table in CONTENT_KIND_TABLES.items():
        assert tables[kind] == table


def test_the_entity_function_carries_one_arm_per_kind():
    fn = render_entity_access_fn()
    for kind, table in entity_tables().items():
        assert f"WHEN '{kind}' THEN" in fn, kind
        assert f"FROM {table} re WHERE re.id = p_entity_id" in fn, kind
    assert fn.count("WHEN '") == len(entity_tables())
