"""Provision and tear down a per-guild PostgreSQL schema.

`provision_guild_schema` creates `guild_<id>` (tables via `apply_guild_schema`,
which RUNS structure DDL reflected LIVE from the guild_template schema),
per-guild Postgres roles, and the initiative-level RLS policies (via
`apply_guild_rls`, running RLS DDL rendered from the INITIATIVE_PATHS
registry); `drop_guild_schema`
removes the schema + roles. Idempotent — re-running back-fills any guild-scoped
table a later migration added and re-asserts the policies. The model is never
used to build the DB: Alembic is the single source, applied per schema.
Per-request routing (search_path + SET ROLE in `set_rls_context`) sends
guild-scoped queries into the schema, where the RLS policies (deferring to
`initiative_access`) enforce initiative membership for non-admin roles.

`backfill_guild_schemas` runs on every boot and brings each guild up to date:
a guild provisioned before guild_template gained a table/column/index, or
before a registry changed, gets the parts that changed since; a crash
mid-provision that left a guild row without its schema gets all of them. Each
schema's comment records a digest per part, so a boot with nothing changed
touches no guild.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import bootstrap
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db import session as db_session

logger = logging.getLogger(__name__)

# The roles the app connects as must reach the guild schema, since per-request
# routing (search_path) sends guild-scoped queries there: app_user for the RLS
# request path, app_admin for guild creation / seeding / background jobs.
# (Tightening to per-guild roles + SET ROLE is the fail-closed step.)
APP_LOGIN_ROLE, _ = settings.database_login("DATABASE_URL_APP")
SYSTEM_LOGIN_ROLE, _ = settings.database_login("DATABASE_URL_ADMIN")


def guild_schema_name(guild_id: int) -> str:
    """Schema name for a guild, e.g. ``guild_42``."""
    return f"guild_{int(guild_id)}"


class GuildRoleKind(StrEnum):
    """A guild's roles, each spelled ``guild_<id>`` plus its suffix. The login
    roles can ``SET ROLE`` into every one and hold no standing access to any.
    """

    #: The full role: DML on the schema, and the ``app_guild_base`` floor. A
    #: member's request assumes it.
    full = ""
    #: SELECT on the schema and nothing written, over the read-only floor
    #: ``app_guild_base_ro``. Assumed by PAM *read* grants, read-only members
    #: and settings-only grants.
    read_only = "_ro"
    #: A scoped ``read_write`` grant (the ``support`` identity): DML on content,
    #: SELECT-only on ``SUPPORT_WRITE_PROTECTED_TABLES``, so the grantee cannot
    #: manage who is in the guild or who can see what.
    support = "_support"
    #: The SQL query surface: ``USAGE`` on the schema, ``SELECT`` on its
    #: tables, and in ``public`` only the routed community's members
    #: (``current_guild_members``). No shared floor, so a statement reaches no
    #: other community. Initiative RLS still applies, because the policies read
    #: the request's identity rather than its role.
    query = "_q"
    #: The seat: inherits the full role and ``app_superadmin``, the floor
    #: carrying the community's sign-in configuration. Assumed by a request
    #: that asked for the seat and holds it; an ordinary request by a seat
    #: holder routes as the full role.
    seat = "_superadmin"
    #: An installed plug-in's request: only what ``app.db.plugin_rls.PLUGIN_TABLE_ACCESS``
    #: names, no default privileges, and ``plugin_install_base`` for ``public``.
    plugin = "_plugin"
    #: A guest's request: only what ``app.db.guest_access.GUEST_TABLE_ACCESS``
    #: names, the row narrowing ``TO guest_base`` there, and ``guest_base`` for
    #: ``public``. No default privileges.
    guest = "_guest"
    #: The same, SELECT-only: a guest in a ``read_only`` community.
    guest_read_only = "_guest_ro"


def guild_role_name(guild_id: int, kind: GuildRoleKind = GuildRoleKind.full) -> str:
    """Cluster-global role name for a guild, e.g. ``guild_42`` or ``guild_42_ro``.

    Carries ``settings.GUILD_ROLE_PREFIX`` (empty in prod/dev). Roles are
    cluster-global — unlike schemas, which are per-database — so the test suite
    sets a prefix (``test_``) to avoid colliding with a co-located dev DB's roles.
    Deliberately a separate name from the schema: a role and a schema are
    different objects with different collision scopes.
    """
    return f"{settings.GUILD_ROLE_PREFIX}guild_{int(guild_id)}{kind.value}"


def guild_role_regex() -> str:
    """A Postgres regex matching every guild's roles, under the current prefix."""
    suffixes = "|".join(k.value for k in GuildRoleKind if k.value)
    return f"^{settings.GUILD_ROLE_PREFIX}guild_[0-9]+({suffixes})?$"


# Permission tables the restricted ``support`` role may READ but never WRITE:
# what a resource is shared with, and what an installed plug-in may do in
# somebody's name — access management, which a content grant is not for.
# Coarse by design (table/verb, not row-level). The initiative's own
# structure (its roster, roles and their permissions) is not here: the
# ``managed_*`` policies decide those writes from the standing, and a settings
# rung beside a ``read_write`` grant is among what they admit. Kept in
# lockstep with the guild schema by ``schema_provisioning_test``.
SUPPORT_WRITE_PROTECTED_TABLES: tuple[str, ...] = (
    "resource_grants",
    # A member's own credential for an installed plug-in. Deciding who reaches an
    # outside system through this guild is access management, not the
    # edit-existing-content a scoped read_write grant is for.
    "guild_plugin_user_connections",
    # A member's answer to a plug-in asking to act as them. Access management for
    # the same reason, and pointedly so: the row holds what one person decided
    # about their own name, which is not a support grantee's to write in either
    # direction.
    "plugin_member_consents",
)

# Direct grants for the guild-scoped system operations that must not go through
# tenant visibility rules: removing an account's embedded display name, and the
# webhook poller's scan for what each subscription is still owed. The columns
# the name is removed from are every column somebody writes in
# (``search_index.written_columns``); they are added by
# :func:`system_maintenance_grants`, so this names only the rest. The system
# login can already assume every guild role, so this adds no reachable guild;
# it lets those narrowly bounded operations retain app_admin's BYPASSRLS
# identity instead of putting a comments UPDATE, or a scan of the whole change
# log every five seconds, through initiative_access() one row at a time.
SYSTEM_GUILD_MAINTENANCE_GRANTS: dict[str, tuple[str, ...]] = {
    "task_assignment_digest_items": ("SELECT", "UPDATE"),
    # The frozen-ancestor guard reads each supported parent into a composite
    # record (``SELECT *``) before capture/search triggers resolve identifiers.
    # PostgreSQL therefore requires table-level SELECT for these dependencies.
    "projects": ("SELECT",),
    "queues": ("SELECT",),
    "counter_groups": ("SELECT",),
    "calendars": ("SELECT",),
    "dashboards": ("SELECT",),
    "collections": ("SELECT",),
    # A comment can hang off a wiki, and off one of its pages — which is where
    # a wiki's conversation actually happens — so the guard reads both while
    # the scrub rewrites that comment.
    "wikis": ("SELECT",),
    "wiki_pages": ("SELECT",),
    "initiatives": ("SELECT",),
    # Content and search-index triggers must still record the scrub. Their
    # writes are column-scoped where possible; DELETE needs a table privilege.
    "event_outbox": (
        "INSERT (txn_id, occurred_at, actor_user_id, actor_install_id, "
        "initiative_id, resource_type, resource_id, action, changed, parents, "
        "dac_tool, dac_id)",
        # The poller's candidate scan: which transactions exist, in what order.
        # Nothing of what a row says — that is read per transaction, as the
        # subscription's owner, where RLS decides it.
        "SELECT (id, txn_id)",
    ),
    # The same scan over the events plug-ins emit.
    "plugin_event_outbox": ("SELECT (id, txn_id)",),
    # The other half of that scan: what the ledger already records as settled
    # or leased for a subscription, so only the remainder is named.
    "webhook_deliveries": (
        "SELECT (subscription_id, txn_id, delivered_at, dead_lettered_at, next_attempt_at)",
    ),
    "search_entries": (
        "SELECT (entity_type, entity_id)",
        "INSERT (entity_type, entity_id, chunk_ix, initiative_id, dac_tool, "
        "dac_id, title, body, archived, template, updated_at, tsv)",
        "DELETE",
    ),
}


def system_maintenance_grants() -> dict[str, tuple[str, ...]]:
    """:data:`SYSTEM_GUILD_MAINTENANCE_GRANTS`, plus reading and rewriting every
    column somebody writes in — and the collaboration state beside it, which
    has to be cleared when the text under it changes."""
    from app.db.search_index import written_columns

    grants = dict(SYSTEM_GUILD_MAINTENANCE_GRANTS)
    for model, columns in written_columns().items():
        if "yjs_state" in model.__table__.c:
            columns = (*columns, "yjs_state")
        grants[model.__table__.name] = ("SELECT", f"UPDATE ({', '.join(columns)})")
    return grants


SYSTEM_GUILD_MAINTENANCE_SEQUENCE_GRANTS: dict[str, tuple[str, ...]] = {
    "event_outbox_id_seq": ("USAGE",),
}


#: What provisioning applies to a guild schema, in the order it applies them.
#: A schema's comment records one digest per part; a boot re-applies only the
#: parts whose digest moved, except that new structure re-applies every part,
#: since the others reach the tables it adds.
PARTS = ("schema", "checks", "grants", "rls", "capture", "search", "timers")
_STAMP_PREFIX = "provisioned:"


@dataclass(frozen=True)
class ProvisioningBundle:
    """The per-process render of everything provisioning applies.

    ``schema_ddl`` is reflected LIVE from the Alembic-maintained
    ``guild_template`` schema; ``checks_ddl`` from the CHECKs the models mark as
    following a registry (``app.db.registry_checks``); ``rls_ddl`` from the
    ``INITIATIVE_PATHS`` registry (see ``app.db.guild_ddl``). There are no
    committed artifacts — new guilds match the template + registry by
    construction. ``digests`` hashes each part's render (the grants as
    rendered statements), so a guild migration, a registry edit or a grants
    change moves the digest of the part it touches and nothing else.
    """

    schema_ddl: str
    checks_ddl: str
    #: Not digested: it follows from ``checks_ddl``.
    validate_ddl: str
    rls_ddl: str
    capture_ddl: str
    search_ddl: str
    timer_ddl: str
    digests: dict[str, str]

    @property
    def stamp(self) -> str:
        """The schema comment a guild carries once every part is applied."""
        return self.stamp_pending()

    def stamp_pending(self, *parts: str) -> str:
        """The stamp, with ``parts`` still to finish: a later boot applies
        them again."""
        return _STAMP_PREFIX + ",".join(
            f"{p}={'pending' if p in parts else self.digests[p]}" for p in PARTS
        )

    def stale_parts(self, stamp: str | None) -> tuple[str, ...]:
        """The parts a schema commented ``stamp`` still needs, in apply order."""
        applied = dict(
            item.split("=", 1)
            for item in (stamp or "").removeprefix(_STAMP_PREFIX).split(",")
            if "=" in item
        )
        stale = tuple(p for p in PARTS if applied.get(p) != self.digests[p])
        return PARTS if "schema" in stale else stale


_bundle: ProvisioningBundle | None = None
_bundle_lock = asyncio.Lock()


def _digest(*renders: str) -> str:
    return hashlib.sha256("\n".join(renders).encode()).hexdigest()[:12]


async def get_provisioning_bundle() -> ProvisioningBundle:
    """Render (once per process, after migrations have run) and cache."""
    global _bundle
    if _bundle is not None:
        return _bundle
    async with _bundle_lock:
        if _bundle is not None:
            return _bundle
        from app.db.event_capture import render_guild_capture_ddl
        from app.db.guild_ddl import render_guild_rls_ddl, render_guild_schema_ddl
        from app.db.registry_checks import (
            render_guild_registry_check_ddl,
            render_guild_registry_validate_ddl,
        )
        from app.db.search_index import render_guild_search_ddl
        from app.db.timers import render_guild_timer_ddl

        schema_ddl = await render_guild_schema_ddl(db_session.provisioning_engine)
        checks_ddl = render_guild_registry_check_ddl()
        rls_ddl = render_guild_rls_ddl()
        capture_ddl = render_guild_capture_ddl()
        # Naming the operator class in the rendered text is what makes the
        # digest move when it is installed later, so the sweep rebuilds indexes
        # that were created without it.
        opclass = f"public.{SEARCH_OPCLASS}" if await search_operator_ready() else None
        search_ddl = render_guild_search_ddl(opclass)
        timer_ddl = render_guild_timer_ddl()
        grants = _grant_statements("__stamp__", 0)
        _bundle = ProvisioningBundle(
            schema_ddl=schema_ddl,
            checks_ddl=checks_ddl,
            validate_ddl=render_guild_registry_validate_ddl(),
            rls_ddl=rls_ddl,
            capture_ddl=capture_ddl,
            search_ddl=search_ddl,
            timer_ddl=timer_ddl,
            digests={
                "schema": _digest(schema_ddl),
                "checks": _digest(checks_ddl),
                "grants": _digest(*grants),
                "rls": _digest(rls_ddl),
                "capture": _digest(capture_ddl),
                "search": _digest(search_ddl),
                "timers": _digest(timer_ddl),
            },
        )
        return _bundle


def reset_provisioning_bundle() -> None:
    """Drop the cached render (tests; or after in-process template changes)."""
    global _bundle
    _bundle = None


async def apply_guild_schema(conn: AsyncConnection, schema: str) -> None:
    """Build/refresh ``schema``'s guild-scoped tables by RUNNING the canonical,
    Alembic-owned DDL with the search_path pointed at it.

    The same DDL builds ``guild_template`` (a migration) and every ``guild_<id>``
    (provisioning) — one source of truth, applied per schema. It's schema-relative
    (unqualified names resolve in ``schema``; shared types/tables fall through to
    ``public``) and idempotent (``IF NOT EXISTS`` / guarded constraints), so a
    re-run back-fills anything a later migration added. No model, no clone.
    """
    ddl = (await get_provisioning_bundle()).schema_ddl
    raw = await conn.get_raw_connection()
    # search_path so unqualified CREATEs land in the schema and intra-schema FKs
    # resolve there; reset to public so it doesn't leak onto the pooled connection.
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def apply_guild_checks(
    conn: AsyncConnection, schema: str, *, replace: bool = True, validate: bool = True
) -> None:
    """Replace and/or validate the registry CHECKs on ``schema``'s tables
    (``app.db.registry_checks``), with the search_path pointed at it."""
    bundle = await get_provisioning_bundle()
    ddl = "\n".join(
        ([bundle.checks_ddl] if replace else [])
        + ([bundle.validate_ddl] if validate else [])
    )
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def apply_guild_rls(conn: AsyncConnection, schema: str) -> None:
    """Apply the initiative-level RLS policies to ``schema``'s tables by RUNNING
    the registry-rendered RLS DDL with the search_path pointed at it.

    Schema-relative + idempotent (``ENABLE/FORCE`` + ``DROP POLICY IF EXISTS`` +
    ``CREATE POLICY``), so a re-run (provisioning, boot back-fill) re-asserts the
    policies harmlessly. Policies defer to the schema's own ``initiative_access``,
    rendered at the top of the same DDL so each policy binds the local copy; the
    per-table EXISTS joins resolve against the guild-local tables. The
    ``public`` functions those copies call are applied at boot before this runs.
    """
    ddl = (await get_provisioning_bundle()).rls_ddl
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def apply_guild_trigger_functions(conn: AsyncConnection) -> None:
    """Re-assert the shared ``public`` functions the capture, search and
    timer triggers call, from their registries.

    Migrations create them, but a migration freezes the body it was written
    with; the registries are the current truth, so re-rendering them here is
    what lets a change to the capture or search rule reach existing installs
    on the next boot rather than needing a migration per edit. Runs once per
    boot, ahead of the guild back-fill, not once per guild. Idempotent
    ``CREATE OR REPLACE``.
    """
    from app.db.event_capture import CAPTURE_FUNCTION_SQL
    from app.db.search_index import (
        DEPENDENT_FUNCTION_SQL,
        SEARCH_FUNCTION_SQL,
        WRITE_FUNCTION_SQL,
    )
    from app.db.timers import ARM_FUNCTION_SQL, ARM_ON_WRITE_FUNCTION_SQL

    raw = await conn.get_raw_connection()
    # The write function first: both search trigger functions call it.
    await raw.driver_connection.execute(
        "SET check_function_bodies = false;\n"
        + "\n".join(
            (
                CAPTURE_FUNCTION_SQL,
                WRITE_FUNCTION_SQL,
                SEARCH_FUNCTION_SQL,
                DEPENDENT_FUNCTION_SQL,
                ARM_FUNCTION_SQL,
                ARM_ON_WRITE_FUNCTION_SQL,
            )
        )
    )


async def apply_guild_capture(conn: AsyncConnection, schema: str) -> None:
    """Install the change-capture triggers on ``schema``'s evented tables.

    Schema-relative + idempotent (``DROP TRIGGER IF EXISTS`` + ``CREATE
    TRIGGER``), so a re-run re-asserts them harmlessly. Every trigger calls the
    one ``public.capture_change`` (qualified, so it resolves regardless of
    search_path), kept current by :func:`apply_guild_trigger_functions`; the
    per-table initiative lookups it runs resolve against the guild-local
    tables through the caller's search_path, the same way the RLS policies'
    EXISTS joins do.
    """
    ddl = (await get_provisioning_bundle()).capture_ddl
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def apply_guild_search(conn: AsyncConnection, schema: str) -> None:
    """Install the search-index refresh triggers on ``schema``'s indexed tables.

    Same shape as :func:`apply_guild_capture`: per-table triggers calling
    shared functions that :func:`apply_guild_trigger_functions` keeps current.
    """
    ddl = (await get_provisioning_bundle()).search_ddl
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def apply_guild_timers(conn: AsyncConnection, schema: str) -> None:
    """Install the sweep-timer triggers on ``schema``'s tables.

    Same shape as :func:`apply_guild_capture`: per-table triggers calling
    shared functions that :func:`apply_guild_trigger_functions` keeps current.
    """
    ddl = (await get_provisioning_bundle()).timer_ddl
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def strip_template_registry_objects(conn: AsyncConnection) -> int:
    """Remove from ``guild_template`` what only a renderer would have put there.

    Migrations shape the template and provisioning reflects its structure.
    Boots before the template became structure-only also rendered the
    registries into it: policies, and the freeze, capture and search
    triggers. This drops those — every policy on a template table, every
    trigger whose name the renderers produce, and any of the guild functions —
    and leaves the migrations' own objects alone. Idempotent; a no-op once the template is clean.
    Returns how many objects went.
    """
    from app.db.guild_ddl import TEMPLATE_SCHEMA, rendered_trigger_names

    policies = (
        await conn.execute(
            text("SELECT tablename, policyname FROM pg_policies WHERE schemaname = :s"),
            {"s": TEMPLATE_SCHEMA},
        )
    ).all()
    for table, policy in policies:
        await conn.execute(
            text(f'DROP POLICY IF EXISTS "{policy}" ON "{TEMPLATE_SCHEMA}"."{table}"')
        )
    rendered = rendered_trigger_names()
    triggers = [
        (table, trigger)
        for table, trigger in (
            await conn.execute(
                text(
                    "SELECT c.relname, t.tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "WHERE c.relnamespace = CAST(:s AS regnamespace) "
                    "AND NOT t.tgisinternal"
                ),
                {"s": TEMPLATE_SCHEMA},
            )
        ).all()
        if trigger in rendered
    ]
    for table, trigger in triggers:
        await conn.execute(
            text(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{TEMPLATE_SCHEMA}"."{table}"')
        )
    # The functions the render now puts in a guild schema, should a render
    # ever have been pointed at the template; dropped after the policies that
    # would bind them.
    from app.db.authorization import (
        GUILD_FUNCTION_SIGNATURES,
        RETIRED_GUILD_FUNCTION_SIGNATURES,
    )

    functions = 0
    for name, args in (
        *GUILD_FUNCTION_SIGNATURES.items(),
        *RETIRED_GUILD_FUNCTION_SIGNATURES,
    ):
        present = (
            await conn.execute(
                text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
                {"sig": f"{TEMPLATE_SCHEMA}.{name}{args}"},
            )
        ).scalar()
        if present:
            await conn.execute(text(f'DROP FUNCTION "{TEMPLATE_SCHEMA}".{name}{args}'))
            functions += 1
    return len(policies) + len(triggers) + functions


#: What ``guild_<id>_plugin`` reads outside ``PLUGIN_TABLE_ACCESS``: table -> the
#: columns, or ``()`` for the whole row. The install standing statement reads
#: the install, the scopes its pinned version requests and where it is
#: placed, and for a member token the member's
#: consent and what their initiative roles permit; the sharing gate reads the
#: grant rows; a notification about what the install did names it; a task
#: written for a member is held to its board's column limits, which its
#: project's board layout holds. No route addresses any of them for a plug-in.
PLUGIN_ROLE_MACHINERY_READS: dict[str, tuple[str, ...]] = {
    "guild_plugins": (
        "id",
        "listing_uid",
        "enabled",
        "granted_scopes",
        "definition",
        "name",
    ),
    "plugin_placements": ("install_id", "initiative_id"),
    "plugin_member_consents": (
        "install_id",
        "user_id",
        "purpose",
        "initiative_id",
        "granted_access",
        "revoked_at",
    ),
    "initiative_role_permissions": ("initiative_role_id", "permission_key", "enabled"),
    "resource_grants": (),
    "tool_layouts": ("initiative_id", "tool", "tool_id", "kind", "definition"),
}

#: What ``guild_<id>_plugin`` writes outside ``PLUGIN_TABLE_ACCESS``: table -> the
#: verbs. The owner grant on a resource an install creates names the install,
#: and an install with ``sharing:write`` rewrites a resource's shares; the row
#: policies on ``resource_grants`` admit those rows and no other.
PLUGIN_ROLE_MACHINERY_WRITES: dict[str, tuple[str, ...]] = {
    "resource_grants": ("INSERT", "DELETE"),
}


def _plugin_role_grant_statements(schema: str, plugin_role: str) -> list[str]:
    """The plug-in role's grants, rendered from ``PLUGIN_TABLE_ACCESS`` in table order.

    A scoped table a plug-in writes, a side-effect table and the subscriptions
    table take DML (the row policies decide which rows); a scoped read-only
    table takes ``SELECT``. Every other table in the schema takes nothing.
    The role's table grants are cleared first, so a re-provision leaves it
    holding what the registry says now.
    """
    from app.db.plugin_rls import PLUGIN_TABLE_ACCESS, PluginTableKind

    stmts = [
        f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{plugin_role}"',
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{plugin_role}"',
    ]
    for table in sorted(PLUGIN_TABLE_ACCESS):
        access = PLUGIN_TABLE_ACCESS[table]
        if access.writable or access.kind is PluginTableKind.side_effect:
            verbs = "SELECT, INSERT, UPDATE, DELETE"
        else:
            verbs = "SELECT"
        stmts.append(f'GRANT {verbs} ON TABLE "{schema}"."{table}" TO "{plugin_role}"')
    # Read by the install standing statement and the gates, never addressed
    # by a plug-in: the install's own row and its placements, column by column,
    # and the sharing rows ``resource_access`` reads under the invoker's role.
    for table, columns in sorted(PLUGIN_ROLE_MACHINERY_READS.items()):
        target = f" ({', '.join(columns)})" if columns else ""
        stmts.append(
            f'GRANT SELECT{target} ON TABLE "{schema}"."{table}" TO "{plugin_role}"'
        )
    for table, verbs in sorted(PLUGIN_ROLE_MACHINERY_WRITES.items()):
        stmts.append(
            f'GRANT {", ".join(verbs)} ON TABLE "{schema}"."{table}" TO "{plugin_role}"'
        )
    stmts += [
        # Ids of the rows it writes come from the schema's sequences.
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{plugin_role}"',
        f'GRANT plugin_install_base TO "{plugin_role}"',
        f'GRANT "{plugin_role}" TO "{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}" '
        f"WITH INHERIT FALSE",
    ]
    return stmts


def _grant_statements(schema: str, guild_id: int) -> list[str]:
    """Fail-closed grants tying each of the guild's roles to its ``schema``.

    NOTE: the provisioning-bundle stamp hashes this function's RENDERED
    output, so changing WHAT it grants invalidates every guild's stamp and
    schedules one full (idempotent) re-provisioning sweep on the next boot —
    cosmetic edits here don't.

    Each role inherits shared/public access from ``app_guild_base``. The login
    roles are granted membership in all of them ``WITH INHERIT FALSE`` — they can
    ``SET ROLE`` into any but hold no standing access to the schema, so a
    guild's data is reachable only by assuming one of its roles. The read-only
    role (assumed by PAM read grants) gets SELECT only, so a write is denied.
    The support role (scoped read_write grants) gets DML on content but is
    revoked write on the structural/permission tables — the DB-enforced
    "no member/permission management" line. The query role holds no shared
    floor: its schema and the routed community's members. The plug-in role (an
    installed plug-in's requests) holds only what ``_plugin_role_grant_statements``
    renders, and the guest roles only what ``guest_role_grant_statements`` does.
    """
    (
        role,
        ro_role,
        support_role,
        query_role,
        seat_role,
        plugin_role,
        guest_role,
        guest_ro_role,
    ) = _guild_roles(guild_id)
    stmts = [
        # Account-erasure maintenance: direct, table-bounded access lets the
        # app_admin login retain BYPASSRLS while it removes embedded names.
        # Its grants are cleared first, like the plug-in role's, so a re-provision
        # leaves it holding what the registry says now rather than what an
        # earlier release granted too.
        f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{SYSTEM_LOGIN_ROLE}"',
        f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA "{schema}" FROM "{SYSTEM_LOGIN_ROLE}"',
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{SYSTEM_LOGIN_ROLE}"',
        *(
            f"GRANT {', '.join(privileges)} ON TABLE "
            f'"{schema}"."{table}" TO "{SYSTEM_LOGIN_ROLE}"'
            for table, privileges in system_maintenance_grants().items()
        ),
        *(
            f"GRANT {', '.join(privileges)} ON SEQUENCE "
            f'"{schema}"."{sequence}" TO "{SYSTEM_LOGIN_ROLE}"'
            for sequence, privileges in (
                SYSTEM_GUILD_MAINTENANCE_SEQUENCE_GRANTS.items()
            )
        ),
        # Full role: DML on its schema.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT USAGE ON SEQUENCES TO "{role}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"',
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"',
        f'GRANT app_guild_base TO "{role}"',
        f'GRANT "{role}" TO "{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}" WITH INHERIT FALSE',
        # Read-only role: SELECT only on the schema (PAM read grants, read-only
        # members), and the read-only shared floor.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{ro_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{ro_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON SEQUENCES TO "{ro_role}"',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{ro_role}"',
        f'GRANT SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{ro_role}"',
        f'GRANT app_guild_base_ro TO "{ro_role}"',
        f'GRANT "{ro_role}" TO "{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}" WITH INHERIT FALSE',
        # Support role: read_write on content, but SELECT-only on the structural /
        # permission tables. Grant broadly (incl. default privileges for future
        # content tables) then REVOKE write on the protected set — coarse by design.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{support_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{support_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT USAGE ON SEQUENCES TO "{support_role}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" '
        f'TO "{support_role}"',
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{support_role}"',
        f'GRANT app_guild_base TO "{support_role}"',
        f'GRANT "{support_role}" TO "{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}" '
        f"WITH INHERIT FALSE",
        # Query role: SELECT on the schema's tables and nothing else. No
        # sequences — a read names no sequence — and no DML at any level.
        #
        # No shared floor: a query reads its own community and nothing in
        # ``public`` but the routed community's members. ``USAGE`` on
        # ``public`` names that view and the types the gates take, and holds
        # no table. The floor it once inherited is revoked, for the schemas
        # provisioned while it did.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{query_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT ON TABLES TO "{query_role}"',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{query_role}"',
        f'REVOKE app_guild_base_ro FROM "{query_role}"',
        f'GRANT USAGE ON SCHEMA public TO "{query_role}"',
        f'GRANT SELECT ON public.current_guild_members TO "{query_role}"',
        f'GRANT "{query_role}" TO "{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}" '
        f"WITH INHERIT FALSE",
        # Seat role: the full guild role's reach into the schema and the
        # shared floor, plus app_superadmin — the one shared floor carrying
        # the community's sign-in configuration. Composed from the guild role
        # rather than granted afresh, so a content table added later reaches
        # it by the same default privilege that reaches that one.
        f'GRANT "{role}" TO "{seat_role}"',
        f'GRANT app_superadmin TO "{seat_role}"',
        f'GRANT "{seat_role}" TO "{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}" '
        f"WITH INHERIT FALSE",
    ]
    # Cap the support role: SELECT stays, writes are revoked on the permission
    # tables (these exist in every schema, so the REVOKE always applies).
    for table in SUPPORT_WRITE_PROTECTED_TABLES:
        stmts.append(
            f'REVOKE INSERT, UPDATE, DELETE ON "{schema}"."{table}" '
            f'FROM "{support_role}"'
        )
    # Plug-in role: table by table from the plug-in registry, with no default
    # privileges and no guild role composed in.
    stmts.extend(_plugin_role_grant_statements(schema, plugin_role))
    # Guest roles: table by table from the guest registry, likewise.
    from app.db.guest_access import guest_role_grant_statements

    members = f'"{APP_LOGIN_ROLE}", "{SYSTEM_LOGIN_ROLE}"'
    for guest, writes in ((guest_role, True), (guest_ro_role, False)):
        stmts.extend(
            guest_role_grant_statements(schema, guest, writes=writes, members=members)
        )
    # What a member may know exists: read by every role whose policies ask it
    # (``app.db.presence``), which answers only a person's own request.
    from app.db.presence import view_statements

    stmts.extend(
        view_statements(
            schema,
            (
                role,
                ro_role,
                support_role,
                query_role,
                plugin_role,
                guest_role,
                guest_ro_role,
            ),
        )
    )
    return stmts


async def _exec_batch(conn: AsyncConnection, statements: list[str]) -> None:
    """Run many DDL/GRANT statements in a single round-trip.

    SQLAlchemy's exec_driver_sql uses asyncpg's extended (single-statement)
    protocol; dropping to the raw connection's simple-query path runs the whole
    batch at once, on the same (transactional) connection.
    """
    await conn.exec_driver_sql("SET search_path TO public")  # enums resolve in public
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(";\n".join(statements) + ";")


def _guild_roles(guild_id: int) -> tuple[str, ...]:
    """A guild's roles, one per :class:`GuildRoleKind`, in its order."""
    return tuple(guild_role_name(guild_id, kind) for kind in GuildRoleKind)


async def _existing_roles(conn: AsyncConnection, roles: tuple[str, ...]) -> set[str]:
    rows = await conn.execute(
        text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"),
        {"r": list(roles)},
    )
    return set(rows.scalars())


#: How many guilds one process back-fills at once.
_BACKFILL_CONCURRENCY = 4


async def _write_stamp(conn: AsyncConnection, schema: str, stamp: str) -> None:
    # Constant hex digests, safe to inline.
    await conn.exec_driver_sql(f"COMMENT ON SCHEMA \"{schema}\" IS '{stamp}'")


async def _apply_parts(
    conn: AsyncConnection,
    guild_id: int,
    parts: tuple[str, ...],
    *,
    validate_checks: bool = True,
) -> None:
    """Apply ``parts`` of the bundle to ``guild_<id>``, then stamp the schema.

    Every part is idempotent (``IF NOT EXISTS``, ``CREATE OR REPLACE``, drop
    and re-create), so re-applying one that was current changes nothing.
    ``validate_checks=False`` replaces the registry CHECKs without checking
    the rows already there, and stamps ``checks`` pending until the caller
    validates them in a transaction of its own.
    """
    schema = guild_schema_name(guild_id)
    if "schema" in parts:
        await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await apply_guild_schema(conn, schema)  # canonical Alembic-owned table DDL
    if "checks" in parts:  # CHECKs that follow a registry
        await apply_guild_checks(conn, schema, validate=validate_checks)
    if "grants" in parts:
        roles = _guild_roles(guild_id)
        existing = await _existing_roles(conn, roles)
        await _exec_batch(
            conn,
            [
                *(f'CREATE ROLE "{r}" NOLOGIN' for r in roles if r not in existing),
                *_grant_statements(schema, guild_id),
            ],
        )
    if "rls" in parts:
        await apply_guild_rls(conn, schema)  # initiative-level RLS policies
    if "capture" in parts:
        await apply_guild_capture(conn, schema)  # change-capture triggers
    if "search" in parts:
        await apply_guild_search(conn, schema)  # search-index refresh triggers
    if "timers" in parts:
        await apply_guild_timers(conn, schema)  # sweep-timer triggers
    bundle = await get_provisioning_bundle()
    pending = "checks" in parts and not validate_checks
    await _write_stamp(
        conn, schema, bundle.stamp_pending("checks") if pending else bundle.stamp
    )


async def provision_guild_schema(conn: AsyncConnection, guild_id: int) -> str:
    """Create/refresh ``guild_<id>`` (schema, tables, roles, grants, policies,
    triggers) under the guild's provisioning lock. Idempotent.

    Needs a privileged connection (CREATEROLE + CREATE on the database).
    """
    await advisory_lock(conn, LockNamespace.GUILD_PROVISION, guild_id)
    await _apply_parts(conn, guild_id, PARTS)
    return guild_schema_name(guild_id)


async def drop_guild_schema(conn: AsyncConnection, guild_id: int) -> None:
    """Drop ``guild_<id>`` (schema + role) under the guild's provisioning lock.
    Safe if either is already absent."""
    schema = guild_schema_name(guild_id)

    # DROP SCHEMA needs an exclusive lock on the schema's tables (and on
    # public.guilds to drop their FKs); concurrent app sessions can hold it. Fail
    # fast rather than hang: the guild-purge pass reclaims any schema whose row
    # is gone, and this drop is idempotent so that retry recovers cleanly.
    await conn.exec_driver_sql("SET lock_timeout = '10s'")
    # One drop or provisioning run per guild at a time; a drop that waited
    # finds the schema and roles already gone.
    await advisory_lock(conn, LockNamespace.GUILD_PROVISION, guild_id)
    await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    provisioning_login, _ = settings.database_login("DATABASE_URL")
    from app.db.filer_access import filer_role_name

    # The filer role is created only in the operations community, but goes
    # with whichever community holds it.
    roles = (*_guild_roles(guild_id), filer_role_name(guild_id))
    existing = await _existing_roles(conn, roles)
    for role in roles:
        if role in existing:
            # DROP OWNED requires the role's PRIVILEGES, not just ADMIN OPTION
            # on it (PG16+ separates the two). The provisioning login
            # administers every guild role, so grant itself membership first —
            # a no-op under a superuser DATABASE_URL.
            await conn.exec_driver_sql(f'GRANT "{role}" TO "{provisioning_login}"')
            await conn.exec_driver_sql(f'DROP OWNED BY "{role}"')  # clear grants first
            await conn.exec_driver_sql(f'DROP ROLE "{role}"')


async def provision_guild(guild_id: int) -> str:
    """Provision a guild's schema + role on the superuser engine, atomically.

    Opens its own transaction on the provisioning (superuser) engine — the
    request-path session can't run this DDL. Looked up via the module so tests
    can point it at the test database.
    """
    async with db_session.provisioning_engine.begin() as conn:
        return await provision_guild_schema(conn, guild_id)


async def deprovision_guild(guild_id: int) -> None:
    """Drop a guild's schema + role on the superuser engine, and remove its blobs.

    Refused with ``HoldsInForce`` while the platform holds anything there
    (``app.db.holds``): the schema stays until every hold is released."""
    from app.db.holds import refuse_while_held

    await refuse_while_held(guild_id)
    async with db_session.provisioning_engine.begin() as conn:
        await drop_guild_schema(conn, guild_id)
    # Destroy the guild's storage key first: that is what makes everything it
    # stored encrypted unreadable — here, in the bucket's old versions, and in
    # any copy anyone made — whatever becomes of the purge below.
    try:
        from app.services import storage_keys

        async with db_session.SystemSessionLocal() as session:
            if await storage_keys.destroy(session, guild_id):
                logger.info("deprovision guild %s: destroyed its storage key", guild_id)
            await session.commit()
    except Exception:  # noqa: BLE001 — logged loudly; the row's FK cascades with the guild
        logger.exception("failed to destroy the storage key of guild %s", guild_id)
    # Remove the guild's stored blobs (the ``guild_<id>/`` storage namespace).
    # Best-effort and after the schema drop succeeds: a storage hiccup must not
    # strand a half-deleted guild, and delete_prefix needs no DB so order is moot.
    try:
        from app.services.storage import purge_guild_blobs

        # Offload to a thread: the S3 path makes paginated blocking calls, and this
        # runs on the event loop. A one-shot teardown shouldn't stall the loop.
        removed = await asyncio.to_thread(purge_guild_blobs, guild_id)
        logger.info(
            "deprovision guild %s: removed %d stored blob(s)", guild_id, removed
        )
    except Exception:  # noqa: BLE001 — blob cleanup must not block teardown
        logger.exception("failed to purge stored blobs for guild %s", guild_id)


@dataclass
class BackfillSummary:
    """Outcome of a `backfill_guild_schemas` sweep, for a one-line boot log."""

    total: int
    provisioned: int
    failed: int
    skipped: int = 0  # every part current, here or in another process
    failed_guild_ids: list[int] = field(default_factory=list)


async def _backfill_guild(guild_id: int, *, wait: bool) -> bool | None:
    """Apply the parts ``guild_<id>`` is missing, under its provisioning lock.

    Returns whether anything was applied, or None when ``wait`` is False and
    another process holds the lock.
    """
    bundle = await get_provisioning_bundle()
    async with db_session.provisioning_engine.begin() as conn:
        if not await advisory_lock(
            conn, LockNamespace.GUILD_PROVISION, guild_id, wait=wait
        ):
            return None
        # Read again under the lock: another process may have just done it.
        stamp = await conn.scalar(
            text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
            {"s": guild_schema_name(guild_id)},
        )
        parts = PARTS if settings.FORCE_GUILD_BACKFILL else bundle.stale_parts(stamp)
        if parts:
            await _apply_parts(conn, guild_id, parts, validate_checks=False)
    if "checks" in parts:
        # After the replacement commits, so the scan holds no lock that stops
        # the guild's reads and writes. A failure leaves ``checks`` pending.
        async with db_session.provisioning_engine.begin() as conn:
            await advisory_lock(conn, LockNamespace.GUILD_PROVISION, guild_id)
            schema = guild_schema_name(guild_id)
            await apply_guild_checks(conn, schema, replace=False)
            await _write_stamp(conn, schema, bundle.stamp)
    return bool(parts)


async def backfill_guild_schemas() -> BackfillSummary:
    """Bring every guild schema up to the current bundle.

    Enumerates guild ids and their schema-comment stamps, and for each guild
    whose stamp is behind applies the parts that moved: every part for a
    schema that is missing, unstamped or behind on structure, otherwise only
    the grants, policies or triggers whose render changed. Set
    ``FORCE_GUILD_BACKFILL=true`` to re-apply every part of every guild.

    Several processes booting at once share the work: each guild is applied
    under its advisory lock, a first pass takes only the guilds nobody else
    holds, and a second waits for the rest and re-reads their stamps, so every
    process returns with every guild current and each guild applied once.

    Per-guild failures are logged with the guild id and skipped so one broken
    guild can't take down boot for the rest; each guild runs in its own
    transaction, so a failure rolls back only that guild. Returns a summary
    for the caller to log.
    """
    bundle = await get_provisioning_bundle()

    # The template carries structure only. Earlier boots rendered the
    # registries into it as well, and those copies bind functions the
    # registries have since moved into the guild schemas; nothing reads them,
    # and the retirement step after this sweep needs them gone.
    try:
        async with db_session.provisioning_engine.begin() as conn:
            stripped = await strip_template_registry_objects(conn)
        if stripped:
            logger.info("guild_template: removed %d rendered objects", stripped)
    except Exception:  # noqa: BLE001 — never block boot on the template
        logger.exception("guild_template clean-up failed")

    async with db_session.provisioning_engine.begin() as conn:
        await advisory_lock(conn, LockNamespace.GUILD_PROVISION, 0)
        await apply_guild_trigger_functions(conn)

    # Enumerate on the SYSTEM engine, not the provisioning engine: guild ids
    # live in the RLS-forced public.guilds, and the provisioner is a pure DDL
    # actor — FORCE RLS filters its unrouted data reads to zero rows (by
    # design). Reading data is the system engine's job (BYPASSRLS).
    async with db_session.system_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT g.id, obj_description(n.oid) "
                    "FROM public.guilds g "
                    "LEFT JOIN pg_namespace n ON n.nspname = 'guild_' || g.id "
                    "ORDER BY g.id"
                )
            )
        ).all()
    behind = [
        gid
        for gid, stamp in rows
        if settings.FORCE_GUILD_BACKFILL or bundle.stale_parts(stamp)
    ]

    limit = asyncio.Semaphore(_BACKFILL_CONCURRENCY)
    failed_guild_ids: list[int] = []

    async def backfill(guild_id: int, wait: bool) -> bool | None:
        async with limit:
            try:
                return await _backfill_guild(guild_id, wait=wait)
            except Exception:  # noqa: BLE001 — one broken guild must not block boot
                failed_guild_ids.append(guild_id)
                logger.exception("guild schema back-fill failed for guild %s", guild_id)
                return False

    first = await asyncio.gather(*(backfill(gid, False) for gid in behind))
    held = [gid for gid, applied in zip(behind, first, strict=True) if applied is None]
    second = await asyncio.gather(*(backfill(gid, True) for gid in held))
    provisioned = sum(1 for applied in (*first, *second) if applied)

    return BackfillSummary(
        total=len(rows),
        provisioned=provisioned,
        failed=len(failed_guild_ids),
        skipped=len(rows) - provisioned - len(failed_guild_ids),
        failed_guild_ids=failed_guild_ids,
    )


async def reject_privileged_database_url() -> None:
    """Refuse to start when DATABASE_URL connects as a SUPERUSER/BYPASSRLS role.

    The application's own connection is meant to be ``app_provisioner``: the
    least-privilege login that can run migrations and provision guild schemas.
    The access rules ``SECURITY.md`` describes are enforced by the database and
    assume this connection is bound by them.

    Migrations and guild provisioning fit in ``app_provisioner`` (NOSUPERUSER
    CREATEROLE + CREATE on the database + ownership of the app's objects), so
    this URL never needs more. Creating that role is :mod:`app.db.bootstrap`'s
    job, over the owner connection -- the one connection that legitimately
    holds the privilege, and which this does not touch.

    When ``DATABASE_URL`` was given as the owner, the app made this login
    itself, so reaching the refusal means ``app_provisioner`` was granted
    more afterwards.
    """
    async with db_session.provisioning_engine.connect() as conn:
        rolsuper, rolbypassrls = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    if not (rolsuper or rolbypassrls):
        return

    held = "SUPERUSER" if rolsuper else "BYPASSRLS"
    if settings.database_logins_derived:
        raise SystemExit(
            f"\n{'=' * 70}\n"
            f"REFUSING TO START: the app_provisioner login holds {held}.\n\n"
            f"The app never needs this privilege, and the access rules\n"
            f"described in SECURITY.md are not in force for a connection that\n"
            f"holds it. Remove it as a Postgres superuser, then restart:\n\n"
            f"  ALTER ROLE app_provisioner NOSUPERUSER NOBYPASSRLS;\n"
            f"{'=' * 70}\n"
        )
    raise SystemExit(
        f"\n{'=' * 70}\n"
        f"REFUSING TO START: DATABASE_URL connects as a {held} role.\n\n"
        f"The app never needs these privileges, and the access rules\n"
        f"described in SECURITY.md are not in force for a connection that\n"
        f"holds them. Make the three logins -- either way takes a minute,\n"
        f"and neither touches your data:\n\n"
        f"  Let the app do it\n"
        f"    Keep DATABASE_URL as it is, remove DATABASE_URL_APP and\n"
        f"    DATABASE_URL_ADMIN (and DATABASE_URL_BOOTSTRAP, if set), and\n"
        f"    restart. The app then treats DATABASE_URL as the database owner:\n"
        f"    it creates its logins and hands the app's objects over to them.\n\n"
        f"  Or do it by hand\n"
        f"    1. Point DATABASE_URL at app_provisioner, with a password of\n"
        f"       your choosing.\n"
        f"    2. Print the SQL for exactly those logins (reads the URLs;\n"
        f"       connects to nothing):\n"
        f"         python -m app.db.bootstrap --print-sql\n"
        f"    3. Run it as the database owner, then start the app.\n\n"
        f"See the deployment docs for details.\n"
        f"{'=' * 70}\n"
    )


#: Re-exported from the module that installs them, so each name has one home.
SEARCH_OPCLASS = bootstrap.SEARCH_OPCLASS
SEARCH_MATCH_FUNCTION = bootstrap.SEARCH_MATCH_FUNCTION


#: Cached at boot by :func:`search_operator_ready`. ``False`` until checked, so
#: a query path that runs before the check falls back to the stock operator —
#: same rows, no index.
_search_operator_ready: bool = False


def search_operator_available() -> bool:
    """The cached answer, for the query path (sync, no round trip)."""
    return _search_operator_ready


async def search_operator_ready() -> bool:
    """Whether guild search can use its index.

    :mod:`app.db.bootstrap` installs the match operator and its operator
    class; both must be present.
    """
    async with db_session.provisioning_engine.connect() as conn:
        ready = await bootstrap.search_operator_present(conn)
    global _search_operator_ready
    _search_operator_ready = ready
    return _search_operator_ready


#: Rows per reindex transaction. Bounded so a large table is walked rather than
#: rebuilt in one long-running statement, and kept small because each batch
#: holds row locks on the source table until it commits.
SEARCH_REINDEX_BATCH = 500


async def reindex_guild_search(
    session: AsyncSession, guild_id: int, *, force: bool = False
) -> int:
    """Rebuild one guild's search entries when its generation marker is stale.

    ``session`` is a system session routed into the guild, and each batch
    commits on it. The marker is a comment on the guild's ``search_entries``,
    the same shape as the provisioning stamp on the schema, written on the
    provisioning engine, which owns the table. Adding a source or changing an
    extraction moves :func:`search_generation`, and this walks each source table
    in batches, writing through the same function the refresh trigger uses.

    Returns the number of entities rewritten; zero when already current.
    """
    from app.db.search_index import reindex_plan, search_generation

    schema = guild_schema_name(guild_id)
    generation = search_generation()
    conn = await session.connection()
    current = await conn.scalar(
        text("SELECT obj_description(to_regclass(:t), 'pg_class')"),
        {"t": f'"{schema}".search_entries'},
    )
    if current == generation and not force:
        return 0

    written = 0
    for _entity_type, statement in reindex_plan():
        cursor = 0
        while True:
            conn = await session.connection()
            rows = (
                await conn.execute(
                    text(statement),
                    {
                        "schema": schema,
                        "cursor": cursor,
                        "batch": SEARCH_REINDEX_BATCH,
                    },
                )
            ).all()
            await session.commit()
            if not rows:
                break
            cursor = max(r.id for r in rows)
            written += len(rows)

    async with db_session.provisioning_engine.begin() as conn:
        await conn.exec_driver_sql(
            f"COMMENT ON TABLE \"{schema}\".search_entries IS '{generation}'"
        )
    return written


async def backfill_guild_search() -> int:
    """Reindex every guild whose search generation is stale.

    Runs after schema provisioning. One read of the catalog finds the stale
    guilds (the marker is a comment on each one's ``search_entries``), and
    only those are visited, each on a system session from its cohort. A
    guild's content is walked in bounded transactions, so a large install
    fills in progressively instead of holding one transaction open across the
    whole sweep. A guild that fails is logged and the others carry on.
    """
    from app.db.search_index import search_generation
    from app.services.guild_sweeps import Scope, each_guild

    async with db_session.provisioning_engine.connect() as conn:
        stale = (
            (
                await conn.execute(
                    text(
                        "SELECT substr(n.nspname, 7)::int FROM pg_class c"
                        " JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE c.relname = 'search_entries'"
                        " AND n.nspname ~ '^guild_[0-9]+$'"
                        " AND obj_description(c.oid, 'pg_class')"
                        " IS DISTINCT FROM :generation"
                    ),
                    {"generation": search_generation()},
                )
            )
            .scalars()
            .all()
        )
    if not stale:
        return 0
    total = 0

    async def reindex(session: AsyncSession, guild_id: int) -> None:
        nonlocal total
        total += await reindex_guild_search(session, guild_id)

    await each_guild([(Scope.PROVISIONED, reindex)], name="search-reindex", only=stale)
    if total:
        logger.info("search reindex wrote %d entries", total)
    return total


async def warn_if_search_operator_missing() -> None:
    """Say so, loudly, when the search operator is absent.

    Its absence is not a failure: search returns the same rows either way, and
    reads more of the index table to do it. Nothing else reports it, so a
    restore or a major-version upgrade that lost the objects would otherwise
    show up only as search getting slower.

    :mod:`app.db.bootstrap` installs the objects at startup whenever its owner
    connection is a superuser, so reaching this warning means there is no
    owner connection or its role is not a superuser — Postgres accepts the
    ``LEAKPROOF`` attribute only from one.

    Names the database it checked, because a host commonly has more than one and
    the objects are per-database.
    """
    if await search_operator_ready():
        return
    database = db_session.provisioning_engine.url.database or "?"
    logger.warning(
        "\n%s\n"
        'Guild search is running without its index (database "%s").\n'
        "Results are unchanged; each search reads more of the index table,\n"
        "which grows with the guild.\n"
        "\n"
        "Set %s to a superuser connection for this\n"
        "database and restart, and the app installs it. To apply it by hand\n"
        "instead:\n"
        "\n"
        "  python -m app.db.bootstrap --print-sql \\\n"
        "    | psql -v ON_ERROR_STOP=1 -U <superuser> -d %s\n"
        "\n"
        "Either way the index is rebuilt on the next provisioning sweep.\n"
        "Re-running is safe.\n"
        "%s",
        "=" * 70,
        database,
        bootstrap.owner_setting(),
        database,
        "=" * 70,
    )


def _bypassrls_exit_message(admin_login: str) -> str:
    """The boot-stopping message for a policy-bound system engine."""
    return (
        f"\n{'=' * 70}\n"
        f"DATABASE_URL_ADMIN connects as {admin_login!r}, which does not hold\n"
        "the BYPASSRLS attribute. This login is the app's system engine\n"
        "(startup seeding, background jobs); policy-bound, it reads every\n"
        "shared table as empty and boot fails with a row-level security\n"
        "error. Roles are cluster state — restoring a database from a dump\n"
        "does not restore them.\n\n"
        "Give the app its owner connection and restart, and the bootstrap\n"
        "sets it again; or repair it as a Postgres superuser:\n\n"
        f'  ALTER ROLE "{admin_login}" WITH BYPASSRLS;\n\n'
        "then restart the app.\n"
        f"{'=' * 70}"
    )


async def ensure_system_engine_bypassrls() -> None:
    """Verify the system engine (``DATABASE_URL_ADMIN``) actually bypasses RLS.

    Every seeding/background-job query assumes the system engine holds
    BYPASSRLS. A login that connects fine but is policy-bound (roles are
    cluster state — a ``pg_dump``-based restore recreates none of their
    attributes, and hand-created logins may omit the attribute) reads every
    shared table as empty, so the first boot after such a restore dies deep in
    startup seeding with an opaque "new row violates row-level security policy
    for table \"guilds\"" while trying to re-create the primary guild it cannot
    see (issue #835).

    The bootstrap sets the attribute on every start that has an owner
    connection; this is the check for one that has none. Boot stops with the
    exact repair command instead of the downstream RLS error.
    """
    async with db_session.system_engine.connect() as conn:
        admin_login, bypasses = (
            await conn.execute(
                text(
                    "SELECT current_user, "
                    "(SELECT rolsuper OR rolbypassrls FROM pg_roles "
                    " WHERE rolname = current_user)"
                )
            )
        ).one()
    if not bypasses:
        raise SystemExit(_bypassrls_exit_message(admin_login))


# --- shared-table grant healing (issue #835) ----------------------------------
#
# Roles are cluster state, and an already-stamped database never re-runs the
# migrations that issued its grants, so a restored or recreated cluster can
# bring the logins back without their per-table grants. `backfill_guild_schemas`
# re-asserts guild-schema grants on every boot; this does the same for the
# shared `public` tables, from the `system_grants` registry, additively and
# idempotently, for the logins the deployment's URLs connect as.

#: Every column-owned sequence of the named ``public`` tables, serial or
#: identity, qualified and quoted.
_ROW_ID_SEQUENCES = text(
    "SELECT seq FROM ("
    "  SELECT pg_get_serial_sequence(format('public.%I', c.relname), a.attname)"
    "    AS seq"
    "  FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid"
    "  WHERE c.relnamespace = 'public'::regnamespace"
    "    AND c.relname = ANY(CAST(:tables AS text[]))"
    "    AND a.attnum > 0 AND NOT a.attisdropped"
    ") s WHERE seq IS NOT NULL ORDER BY seq"
)


async def _reassert_shared_grants(conn: AsyncConnection, role: str) -> int:
    """Re-GRANT the registry's table verbs to ``role``'s login, and for the
    tables it inserts into, their row-id sequences. Additive and idempotent —
    never REVOKEs, so it only restores what is missing. Returns the number of
    tables granted."""
    from app.db import system_grants
    from app.db.public_rls import existing_public_tables

    matrix = system_grants.ROLE_GRANTS[role]
    existing = await existing_public_tables(conn)
    tables = sorted(t for t, verbs in matrix.items() if verbs and t in existing)
    sequences = (
        await conn.execute(
            _ROW_ID_SEQUENCES,
            {"tables": [t for t in tables if "INSERT" in (matrix[t] or ())]},
        )
    ).scalars()
    for statement in system_grants.grant_statements(
        role, tables, sequences=sequences.all()
    ):
        await conn.execute(text(statement))
    return len(tables)


def _missing_grants_exit_message(role: str, missing: list[tuple[str, str]]) -> str:
    from app.db import system_grants

    login = system_grants.grantee(role)
    tables = sorted({table for table, _verb in missing})
    grant_lines = "\n".join(
        f"  {statement};" for statement in system_grants.grant_statements(role, tables)
    )
    return (
        f"\n{'=' * 70}\n"
        f"{system_grants.LOGIN_SETTINGS[role]} connects as {login!r}, which is\n"
        "missing privileges the app requires on the shared tables, and the\n"
        "provisioning login could not grant them (roles are cluster state; a\n"
        "restore does not bring their grants back). Grant them as the tables'\n"
        "owner:\n\n"
        f"{grant_lines}\n\n"
        "(a table granted INSERT also needs GRANT USAGE on its id sequence)\n"
        "then restart the app.\n"
        f"{'=' * 70}"
    )


async def ensure_shared_table_grants() -> None:
    """Heal missing table/sequence GRANTs on the shared ``public`` tables for the
    logins the app connects as directly (the system engine and the bare request
    login), and stop boot with the exact repair when they cannot be healed.

    Companion to :func:`ensure_system_engine_bypassrls`: that checks the RLS
    *attribute*, this repairs the table *grants* one gate deeper. Both answer the
    same class of drift — a ``pg_dump``-based restore or a hand-recreated role
    loses cluster state that an already-stamped database never re-applies
    (issue #835). Runs right after the BYPASSRLS check on every boot; a healthy
    posture is one probe per login.
    """
    from app.db import system_grants

    logins = tuple(system_grants.LOGIN_SETTINGS)
    async with db_session.provisioning_engine.connect() as conn:
        lacking = [
            role for role in logins if await system_grants.missing_grants(conn, role)
        ]
    if not lacking:
        return
    # The object owner (the provisioning login, which the grant-issuing
    # migrations also use) re-asserts the full audited set for each login.
    granted = 0
    try:
        async with db_session.provisioning_engine.begin() as conn:
            for role in lacking:
                granted += await _reassert_shared_grants(conn, role)
    except DBAPIError as exc:
        logger.warning("Shared-table grants could not be re-asserted: %s", exc)
    async with db_session.provisioning_engine.connect() as conn:
        for role in lacking:
            missing = await system_grants.missing_grants(conn, role)
            if missing:
                raise SystemExit(_missing_grants_exit_message(role, missing))
    logger.warning(
        "Shared-table grants were incomplete for the app's directly-connecting "
        "logins (%s) — re-asserted the audited grants on %d table(s) (plus the "
        "row-id sequences of insertable tables) from the system_grants "
        "registry. Restored databases lose role grants (issue #835); no action "
        "needed.",
        ", ".join(system_grants.grantee(role) for role in lacking),
        granted,
    )


# --- engine identity ----------------------------------------------------------
#
# A deployment's URLs may connect as logins other than the canonical ones
# (hand-created roles, swapped APP/ADMIN strings, one login doing double duty).
# This boot check names the three logins in the log and warns on wiring that
# collapses the role separation.


async def verify_engine_identities() -> None:
    """Log which Postgres logins the three engines connect as, and warn loudly
    on wiring that collapses the role separation.

    The three connection strings are distinct trust surfaces: a policy-bound
    request login (``DATABASE_URL_APP``), a row-level-security-exempt system
    engine (``DATABASE_URL_ADMIN``), and a DDL-only provisioning login
    (``DATABASE_URL``). Self-hosted deployments sometimes run the app and
    admin URLs on one login (or the app URL on a privileged login) — that
    functions, because routed requests ``SET ROLE`` into guild/platform roles
    either way, but the unrouted request surface then runs at the system
    engine's privileges and loses its database-level row-security backstop.
    That wiring gets a framed WARNING naming the recommended split, not a
    boot stop. It is a weaker backstop, not an absent boundary --- which is
    why it warns where ``reject_privileged_database_url`` refuses.

    Runs before the heals so the operator sees which login each repair will
    act on. Probes ``session_user`` (the login) rather than ``current_user``
    so residual pool state can never skew the answer.
    """
    async with db_session.engine.connect() as conn:
        app_login, app_db, app_bypasses, app_temp = (
            await conn.execute(
                text(
                    "SELECT session_user, current_database(), "
                    "(SELECT rolsuper OR rolbypassrls FROM pg_roles "
                    " WHERE rolname = session_user), "
                    "has_database_privilege("
                    "  session_user, current_database(), 'TEMP')"
                )
            )
        ).one()
    async with db_session.system_engine.connect() as conn:
        admin_login, admin_db = (
            await conn.execute(text("SELECT session_user, current_database()"))
        ).one()
    async with db_session.provisioning_engine.connect() as conn:
        prov_login = (await conn.execute(text("SELECT session_user"))).scalar()

    logger.info(
        "database logins: provisioning=%r app=%r admin=%r",
        prov_login,
        app_login,
        admin_login,
    )
    bar = "=" * 70
    if (app_login, app_db) == (admin_login, admin_db):
        logger.warning(
            "\n%s\n"
            "NOT RECOMMENDED: DATABASE_URL_APP and DATABASE_URL_ADMIN both\n"
            "connect to database %r as %r.\n"
            "These are meant to be separate trust surfaces — a policy-bound\n"
            "request login (app_user) and an RLS-exempt system engine\n"
            "(app_admin). On a shared login the request path's unrouted\n"
            "queries run at the system engine's privileges, without the\n"
            "database-level row-security backstop.\n"
            "Point DATABASE_URL_APP at app_user and DATABASE_URL_ADMIN at\n"
            "app_admin (see docker-compose.example.yml).\n"
            "%s",
            bar,
            app_db,
            app_login,
            bar,
        )
    elif app_bypasses:
        logger.warning(
            "\n%s\n"
            "NOT RECOMMENDED: DATABASE_URL_APP connects as %r, which holds\n"
            "SUPERUSER or BYPASSRLS. The request path is designed to run\n"
            "policy-bound; with these attributes its unrouted queries read\n"
            "shared tables without the row-security backstop. If the APP and\n"
            "ADMIN connection strings are swapped, swap them back; otherwise\n"
            "point DATABASE_URL_APP at the app_user role (see\n"
            "docker-compose.example.yml).\n"
            "%s",
            bar,
            app_login,
            bar,
        )

    if app_temp:
        logger.warning(
            "\n%s\n"
            "PRIVILEGE DRIFT: the request login %r holds TEMPORARY on database\n"
            "%r. The request path creates no temporary objects, so this grant\n"
            "is unused; the bootstrap revokes it from PUBLIC. Deployments\n"
            "created before that still carry it. To align, run as the database\n"
            "owner:\n"
            "  REVOKE TEMPORARY ON DATABASE %s FROM PUBLIC;\n"
            "or set DATABASE_URL_BOOTSTRAP and restart, which does this and\n"
            "verifies it took effect.\n"
            "%s",
            bar,
            app_login,
            app_db,
            app_db,
            bar,
        )
