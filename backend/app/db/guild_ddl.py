"""Render the per-guild DDL from its two live sources — no committed artifacts.

A guild schema has two layers, each with a single source of truth:

* **Structure** (tables, indexes, constraints, guild_id triggers) — the
  Alembic-maintained ``guild_template`` schema. :func:`render_guild_schema_ddl`
  reflects it live (columns/PK/UNIQUE via SQLAlchemy; CHECK/FK/index/trigger
  text via ``pg_get_*def`` — PG's authoritative text, preserving opclasses and
  partial-index predicates reflection loses) and emits idempotent,
  schema-relative DDL (run with ``search_path = <guild_schema>, public``).
  Cross-schema FKs (to public.users/guilds/…) are omitted — those refs stay
  soft; the schema is the tenant boundary.
* **Initiative RLS policies** — the ``INITIATIVE_PATHS`` registry.
  :func:`render_guild_rls_ddl` stamps the uniform policy boilerplate around
  each table's path.

``schema_provisioning.get_provisioning_bundle()`` renders both once per
process and derives the skip-stamp from them, so NEW guilds always match the
live template + registry by construction, and any change to either triggers
the one-time re-provisioning sweep. Guild-schema CHANGES are ordinary Alembic
migrations (``scripts/gen_guild_migration.py``).
"""

from __future__ import annotations

import re

from sqlalchemy import MetaData, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import CheckConstraint, CreateTable

from app.core.plugin_scopes import PluginScopeResource, tool_resource
from app.core.tools import INSTALL_METADATA_KIND, ITEM_KINDS, PROPERTY_TARGETS, Tool
from app.db.plugin_rls import (
    PLUGIN_REFUSED_TABLES,
    PLUGIN_TABLE_ACCESS,
    SEARCH_ENTRY_READ_SCOPE,
    PluginTableKind,
)
from app.db.initiative_rls import (
    ANSWERED,
    COMMENT_PARENTS,
    INITIATIVE_PATHS,
    NAMED_PEOPLE,
    NamedPerson,
    initiative_of,
    INITIATIVE_SCOPED_TABLES,
    dac_asks_at_write,
    entity_tables,
    governing_path,
    managed_write,
    render_entity_access_fn,
    render_entity_initiative_fn,
    InitiativePath,
)
from app.db import gucs
from app.db.authorization import (
    IN_POLICY,
    POLICY_SEAT,
    POLICY_SETTINGS_ADMIN,
    RETIRED_GUILD_FUNCTION_SIGNATURES,
    STANDING,
    plugin_refused,
    plugin_scope,
    render_guild_authorization_functions,
    sql_values,
)
from app.db.frozen import (
    FROZEN_TABLES,
    LIFECYCLE_COLUMNS,
    freeze_leg,
    frozen_write_triggers,
    frozen_guard_trigger,
    render_frozen_ancestor_fn,
    render_frozen_guard_fn,
    render_frozen_parent_guard_fn,
    render_resource_frozen_fn,
    render_resource_frozen_for_grant_fn,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import (
    GUILD_SCOPED_TABLES,
    LEDGER_TABLES,
    MANAGED_TABLES,
    OWN_ROW_TABLES,
    PRIVATE_ROW_SHARED_READ,
    PRIVATE_ROW_TABLES,
    SEAT_READ_TABLES,
    SEAT_TABLES,
)
from app.models.tenant.initiative import InitiativeJoinPolicy
from app.models.tenant.resource_grant import ResourceAccessLevel


# Hard delete = purge, and only a guild admin may purge (the interactive endpoint
# 403s otherwise; the background auto-purge worker runs as app_admin/BYPASSRLS, so
# RLS — including this RESTRICTIVE policy — does not apply to it). We back that with
# a DB-layer RESTRICTIVE FOR DELETE guard so a stray non-admin DELETE is refused by
# Postgres, not just by app code. The source of truth for "which tables are
# soft-deletable" is SOFT_DELETE_TABLES (derived from the SoftDeleteMixin
# subclasses). The guard goes on EVERY soft-delete table, split by how RLS is
# already set up on the table:
#   - initiative-scoped soft-delete tables already ENABLE RLS (for the membership
#     gate), so the RESTRICTIVE policy is appended to their existing block.
#   - the guild-level soft-delete tables (initiatives, tags) are RLS-free; they get
#     a dedicated guard block that ENABLEs RLS solely to host the purge guard (see
#     _guild_level_guard_block — the access policy there is a deliberate allow-all,
#     NOT a membership gate; initiative is the gate, guilds gate at the schema).
_PURGE_GUARD_TABLES: frozenset[str] = (
    frozenset(SOFT_DELETE_TABLES) & INITIATIVE_SCOPED_TABLES
)
_GUILD_LEVEL_PURGE_TABLES: frozenset[str] = (
    frozenset(SOFT_DELETE_TABLES) - INITIATIVE_SCOPED_TABLES
)

# Admit only a community's administrator, or trusted system maintenance.
# Matches the same two legs of initiative_access exactly: the admin fact the
# standing statement computed from the membership row, and the connection's own
# login for a sweep.
_PURGE_GUARD_PREDICATE = f"({IN_POLICY.system} OR {IN_POLICY.admin})"

# Who may READ a row that is in the trash. Deleting something takes it out of
# sight, so the ordinary answer is nobody: the trash is a place to recover from,
# not a second copy of the guild's content that outlives the decision to remove
# it. Two legs open it — the guild admin, who manages the trash for everyone,
# and whoever deleted the row, who gets their own deletions back from /me/trash.
# RESTRICTIVE, so it AND-combines with the membership gate rather than widening
# it: a trashed row is still only visible to someone who could see it alive.
_TRASH_READ_PREDICATE = (
    "deleted_at IS NULL"
    f" OR {_PURGE_GUARD_PREDICATE}"
    f" OR deleted_by = {gucs.USER_ID.once}"
)


def _trash_read_policy(table: str) -> list[str]:
    """Hide a trashed row from everyone but the admin and whoever deleted it."""
    return [
        f"DROP POLICY IF EXISTS trashed_read ON {table};",
        f"CREATE POLICY trashed_read ON {table} AS RESTRICTIVE FOR SELECT",
        f"  USING ({_TRASH_READ_PREDICATE});",
    ]


# Reader-written SQL reports on live content only.
#
# The trash is a place to recover from, and recovering from it is what the
# trash screen is for. A dashboard is a different question: what it counts
# should be the same for everybody reading it, and a deleted row is not part of
# that for anyone. RESTRICTIVE and keyed on the query flag, so it applies to the
# statements a reader writes and to nothing else.
_QUERY_TRASH_PREDICATE = f"deleted_at IS NULL OR {gucs.QUERY.once} IS NOT TRUE"


def _query_trash_policy(table: str) -> list[str]:
    """Keep a trashed row out of what a reader's own statement returns."""
    return [
        f"DROP POLICY IF EXISTS query_excludes_trash ON {table};",
        f"CREATE POLICY query_excludes_trash ON {table} AS RESTRICTIVE FOR SELECT",
        f"  USING ({_QUERY_TRASH_PREDICATE});",
    ]


_HEADER = """\
-- RENDERED AT RUNTIME from app/db/initiative_rls.py (INITIATIVE_PATHS).
-- Initiative-member-level RLS for the per-guild CONTENT tables. Schema-relative
-- (run with search_path = <guild_schema>, public). Idempotent.
--
-- The access RULE lives in ONE place, initiative_access (initiative member
-- OR guild admin OR PAM, read from the request GUCs); each policy below is just the
-- join that resolves a table's initiative id and defers to it. The per-table paths
-- are the single source of truth in app/db/initiative_rls.py (INITIATIVE_PATHS).
--
-- SCOPE: only INITIATIVE-scoped CONTENT tables are here, exactly
-- app.db.initiative_rls.INITIATIVE_SCOPED_TABLES. The STRUCTURAL initiative tables
-- (initiatives, initiative_members, initiative_roles, initiative_role_permissions)
-- are read within the schema boundary (co-members read their roster, and the
-- standing statement reads the membership table before any standing exists) and
-- written by their managers — the managed_* policies further down, from
-- app.db.tenancy.MANAGED_TABLES. Guild-level / own-row tables
-- (app.db.tenancy.GUILD_LEVEL_TABLES) are guild-scoped by the schema boundary.
-- The app layer still does finer filtering (e.g. the initiatives list shows
-- member-only for non-admins).
--
-- To add a new initiative-scoped table: add a path to INITIATIVE_PATHS in
-- app/db/initiative_rls.py — provisioning and the boot back-fill apply the
-- rendered policies automatically (the provisioning stamp includes this
-- rendering, so a registry change triggers the one-time sweep).
--
-- One table deviates on INSERT: the change log (event_outbox) is written by the
-- capture trigger and by nothing else, so its insert policy admits the trigger
-- rather than re-deciding the writer's access — see _TRIGGER_WRITTEN_INSERT.
--
-- Soft-delete tables additionally carry a RESTRICTIVE FOR DELETE policy
-- (soft_delete_admin_purge): hard delete = purge, and only a community's
-- administrator may. It is RESTRICTIVE, so it AND-combines with the PERMISSIVE
-- delete policy above — a write-member clears the latter but not this one. The
-- purge sweep is admitted by the connection's own login. Source of truth for the table set is
-- app.db.soft_delete_filter.SOFT_DELETE_TABLES (the SoftDeleteMixin subclasses).
-- The guild-level soft-delete tables (initiatives, tags) are RLS-free, so they get
-- the guard via the dedicated section at the bottom of this file.
--
-- Write commands additionally carry the LIFECYCLE freeze (app.db.frozen):
-- archived and trashed content is read-only, and so is everything under it.
-- INSERT carries a RESTRICTIVE policy deferring to one function,
-- resource_frozen(kind, id, trashed_ok), which walks the same join chains
-- the sharing legs are rendered from. UPDATE and DELETE are triggers, at the
-- bottom of this file — telling an edit from an unarchive needs the old row and
-- the new row together, which a policy never has. SELECT carries neither.
"""

# Header for the guild-level guard section (initiatives, tags).
_GUILD_LEVEL_SECTION = """\
-- ===========================================================================
-- Guild-level soft-delete tables: admin-only purge guard ONLY.
--
-- These tables are NOT initiative-membership-gated: initiative is the gate (its
-- content tables point AT it via initiative_access), and the initiative anchor
-- tables can't gate themselves; guilds gate at the SCHEMA level (SET ROLE), which
-- already isolates these rows. RLS is enabled here SOLELY to host the RESTRICTIVE
-- admin-only-purge guard, so the access policy (guild_level_open) is a deliberate
-- allow-all — it adds no row gate, it just lets the RESTRICTIVE delete policy bind.
-- ==========================================================================="""

# Header for the own-row section (export_jobs, …).
_OWN_ROW_SECTION = """\
-- ===========================================================================
-- Own-row guild-level tables (app.db.tenancy.OWN_ROW_TABLES): rows belong to
-- ONE user. Unlike guild_level_open, this IS a row gate — a member must not
-- see another member's rows (an export_jobs row leaks the selector and gates
-- the artifact download). Owner OR the community's administrator OR trusted
-- system maintenance; the last two legs match initiative_access and the purge
-- guard exactly. A settings rung reads them, and writes them only beside a
-- read_write grant. A read-only PAM grantee is routed to guild_<id>_ro with
-- none of them set: no rows, by design.
-- ==========================================================================="""

# Own-row predicate: the owner column is compared against the request GUC.
# NULLIF-guard the cast — an unset context leaves the value empty, and a bare
# ''::int raises and faults the whole query for every PERMISSIVE policy on the
# table (same rule as the public shared-table policies; see CLAUDE.md §5).
_MANAGED_SECTION = """\
-- ===========================================================================
-- The structural initiative tables (app.db.tenancy.MANAGED_TABLES): read within
-- the schema, written by the initiative's managers. Reading stays open — a
-- roster is read by its co-members, and the standing statement reads
-- initiative_members before any standing exists. Writing asks the standing:
-- a manager of that initiative (app.manager_initiatives, a value the seam
-- computed, so the membership table is not gated by a read of itself), the
-- community's admin, a settings rung beside a read_write grant, or the system
-- engine. A member's own row into an initiative whose join policy is open is
-- the one further way in. initiatives keeps its purge guard and trash reads.
-- ==========================================================================="""


#: A member's own row into an initiative that is open to join — the self-join
#: route. Names the community's members (``app.current_guild_id`` is set for a
#: membership routing and for nothing else) and the initiative's policy.
_SELF_JOIN_LEG = (
    f"(user_id = {gucs.USER_ID.once}"
    f" AND {gucs.GUILD_ID.once} IS NOT NULL"
    " AND EXISTS (SELECT 1 FROM initiatives i WHERE i.id = initiative_id"
    f" AND i.join_policy = '{InitiativeJoinPolicy.open.value}' AND i.deleted_at IS NULL))"
)


def _managed_block(table: str, initiative_expr: str) -> str:
    """RLS for a structural initiative table: reading open within the schema,
    writing by the managed-write predicate. ``initiatives`` keeps its admin-only
    purge guard and trash-read policies beside these."""
    pred = managed_write(initiative_expr)
    insert_pred = (
        f"({pred} OR {_SELF_JOIN_LEG})" if table == "initiative_members" else pred
    )
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        # The shape before this one: an allow-all for every command.
        f"DROP POLICY IF EXISTS guild_level_open ON {table};",
        f"DROP POLICY IF EXISTS managed_select ON {table};",
        f"CREATE POLICY managed_select ON {table} AS PERMISSIVE FOR SELECT",
        "  USING (true);",
        f"DROP POLICY IF EXISTS managed_insert ON {table};",
        f"CREATE POLICY managed_insert ON {table} AS PERMISSIVE FOR INSERT",
        f"  WITH CHECK ({insert_pred});",
        f"DROP POLICY IF EXISTS managed_update ON {table};",
        f"CREATE POLICY managed_update ON {table} AS PERMISSIVE FOR UPDATE",
        f"  USING ({pred}) WITH CHECK ({pred});",
        f"DROP POLICY IF EXISTS managed_delete ON {table};",
        f"CREATE POLICY managed_delete ON {table} AS PERMISSIVE FOR DELETE",
        f"  USING ({pred});",
    ]
    if table in _GUILD_LEVEL_PURGE_TABLES:
        lines += [
            f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table};",
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE",
            f"  USING ({_PURGE_GUARD_PREDICATE});",
            *_trash_read_policy(table),
            *_query_trash_policy(table),
        ]
    return "\n".join(lines)


_OWN_ROW_OWNER = "{col} = " + gucs.USER_ID.once

#: Who reads an own-row table's rows: the owner, the community's admin, a
#: settings rung, or the system engine.
_OWN_ROW_READ_PREDICATE = f"({_OWN_ROW_OWNER} OR {IN_POLICY.system} OR {IN_POLICY.admin} OR {POLICY_SETTINGS_ADMIN})"

#: Who writes them: the same, with a settings rung writing only beside a
#: read_write grant.
_OWN_ROW_WRITE_PREDICATE = (
    f"({_OWN_ROW_OWNER} OR {IN_POLICY.system} OR {IN_POLICY.admin}"
    f" OR ({POLICY_SETTINGS_ADMIN} AND {IN_POLICY.pam_write}))"
)

_PRIVATE_ROW_SECTION = """\
-- ===========================================================================
-- Private-row tables (app.db.tenancy.PRIVATE_ROW_TABLES): one member's own
-- state about content they reach — recent views, favorites, an order, a read
-- receipt, a ballot. RESTRICTIVE on top of the table's initiative gate: only
-- the member and trusted system maintenance reach a row, never the community's
-- administrator, a settings rung or a grant. A table in PRIVATE_ROW_SHARED_READ
-- (read counts, poll tallies) is read under its initiative gate and written by
-- its member alone.
-- ==========================================================================="""

#: Who reaches a private row: its member, or the system engine.
_PRIVATE_ROW_PREDICATE = f"({_OWN_ROW_OWNER} OR {IN_POLICY.system})"

_COMMANDS = (
    ("select", "SELECT", "USING", False),
    ("insert", "INSERT", "WITH CHECK", True),
    ("update", "UPDATE", "USING-CHECK", True),
    ("delete", "DELETE", "USING", True),
)

# Tables written only by a trigger or the system engine: their INSERT policy
# admits that writer instead of re-deciding the writer's access.
#
# ``event_outbox`` is the one. A row lands there as a consequence of a content
# write that already cleared its own table's gate, so the log RECORDS what
# happened rather than deciding it a second time — including a change that ends
# the writer's own access, which it must still be able to record. Who may READ
# the log is unchanged: the initiative gate, via the other three policies.
_TRIGGER_WRITTEN_INSERT: dict[str, str] = {
    "event_outbox": "pg_trigger_depth() > 0",
    # The search index is derived: rows arrive from the refresh trigger as a
    # consequence of a content write that already cleared its own table's gate.
    # The reindex sweep routes as the guild admin, which is the second leg.
    "search_entries": f"pg_trigger_depth() > 0 OR {IN_POLICY.system} OR {IN_POLICY.admin}",
    # A plug-in's events are written by the system engine, on the plug-in's behalf.
    "plugin_event_outbox": IN_POLICY.system,
}


def _table_block(table: str, path: InitiativePath) -> str:
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
    ]
    for suffix, command, clause, write in _COMMANDS:
        pred = path.predicate(table, write)
        if path.dac is not None:
            # What the command asks of sharing is per table: changing content
            # takes write on the resource, where responding to it (a comment,
            # a reaction) and keeping a reader's own record of it do not.
            sharing = path.dac.predicate(
                table, command, dac_asks_at_write(table, command)
            )
            # A resource has no sharing before it exists, so the table that IS
            # the resource carries no leg on INSERT — creating one answers to
            # the initiative-role gate instead. A child table keeps it: adding a
            # task means reaching the project it goes in.
            if sharing is not None and sharing != ANSWERED:
                pred = f"{pred} AND {sharing}"
        if command == "INSERT" and table in _TRIGGER_WRITTEN_INSERT:
            pred = _TRIGGER_WRITTEN_INSERT[table]
        name = f"initiative_member_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        lines.append(f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    lines.extend(_freeze_policies(table))
    if table in SOFT_DELETE_TABLES:
        lines.extend(_trash_read_policy(table))
        lines.extend(_query_trash_policy(table))
    if table in _PURGE_GUARD_TABLES:
        # Admin-only hard delete (purge), AND-combined with the PERMISSIVE delete
        # policy above. RESTRICTIVE, so a write-member who clears the permissive
        # leg is still refused unless they are the routed guild admin.
        lines.append("DROP POLICY IF EXISTS soft_delete_admin_purge ON " + table + ";")
        lines.append(
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE"
        )
        lines.append(f"  USING ({_PURGE_GUARD_PREDICATE});")
    return "\n".join(lines)


def _freeze_policies(table: str) -> list[str]:
    """The lifecycle freeze for one table on INSERT: a RESTRICTIVE policy
    refusing a row whose ancestors are archived or trashed.

    RESTRICTIVE, so it AND-combines with the permissive access policies.
    ``WITH CHECK``, so a failure is raised rather than filtered out of the
    statement. UPDATE and DELETE are triggers (see ``app.db.frozen``) — they
    need the old row and the new row together, which a policy never has —
    and SELECT takes neither.
    """
    lines: list[str] = []
    for command in ("INSERT",):
        leg = freeze_leg(table, command)
        name = f"frozen_ancestor_{command.lower()}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        if leg is None:
            continue
        lines.append(f"CREATE POLICY {name} ON {table} AS RESTRICTIVE FOR {command}")
        lines.append(f"  WITH CHECK (NOT {leg});")
    # Earlier shapes carried these; drop them wherever one was left.
    lines.append(f"DROP POLICY IF EXISTS frozen_ancestor_update ON {table};")
    lines.append(f"DROP POLICY IF EXISTS frozen_ancestor_delete ON {table};")
    return lines


def _own_row_block(table: str, owner_col: str) -> str:
    """RLS for an own-row guild-level table: per-command policies admitting the
    row's owner or the routed guild admin. INSERT/UPDATE WITH CHECK use the
    write predicate, so a member can't author rows owned by someone else
    either."""
    read = _OWN_ROW_READ_PREDICATE.format(col=owner_col)
    write = _OWN_ROW_WRITE_PREDICATE.format(col=owner_col)
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            *_policies(table, "own_row", read, write),
        ]
    )


def _private_row_block(table: str, owner_col: str) -> str:
    """RLS for a private-row table: RESTRICTIVE per-command policies admitting
    the row's member or the system engine, on top of its initiative gate. A
    ``PRIVATE_ROW_SHARED_READ`` table leaves reading to that gate."""
    pred = _PRIVATE_ROW_PREDICATE.format(col=owner_col)
    read = None if table in PRIVATE_ROW_SHARED_READ else pred
    return "\n".join(_policies(table, "private_row", read, pred, restrictive=True))


_AUTHORED_SECTION = """\
-- ===========================================================================
-- What one person says, written by that person.
--
-- initiative_join_requests: read by the requester and by whoever answers the
--   initiative's queue (its managers, the community's admin, the system
--   engine); filed by the requester, answered by those who read the queue.
-- tr_<t>_stamp_author (AUTHORED_TABLES): the person writing a comment, a post
--   or a reaction is its author. An import keeps the author it maps, and the
--   system engine writes what it is given. Only the system engine changes an
--   author afterwards.
-- tr_comments_author_guard: only its author changes a comment. Someone else
--   moves it in or out of the trash only with what it is on: trashing it, the
--   thing it is on goes to the trash at the same moment, which
--   tr_comments_trash_follows checks at commit, after the cascade has stamped
--   it; restoring it, they are the one who trashed it, or the community's
--   admin. The system engine moderates, and the admin's purge leaves
--   tombstones.
-- calendar_event_answers: an answer is filed by the person it names, an
--   import, or the system engine. tr_calendar_event_answers_owner_guard keeps
--   who answered and what they answered theirs; the event's editors may still
--   move an answer with the event, or clear it.
-- ==========================================================================="""

#: Where what someone writes carries them as its author.
AUTHORED_TABLES: tuple[str, ...] = ("comments", "posts", "reactions")

#: The requester of a join request, or the system engine.
_REQUESTER = f"(user_id = {gucs.USER_ID.once} OR {IN_POLICY.system})"

_STAMP_AUTHOR_FN = f"""
CREATE OR REPLACE FUNCTION public.fn_stamp_author() RETURNS trigger
    LANGUAGE plpgsql AS $stamp_author$
BEGIN
    IF {IN_POLICY.system} THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
            RAISE EXCEPTION 'an author does not change' USING ERRCODE = '42501';
        END IF;
    ELSIF ({gucs.IMPORTING}) IS NOT TRUE AND {gucs.USER_ID.once} IS NOT NULL THEN
        NEW.created_by := {gucs.USER_ID.once};
    END IF;
    RETURN NEW;
END;
$stamp_author$;
"""

_COMMENT_AUTHOR_GUARD_FN = f"""
CREATE OR REPLACE FUNCTION public.fn_comment_author_guard() RETURNS trigger
    LANGUAGE plpgsql AS $comment_author$
DECLARE
    lifecycle text[] := ARRAY[{", ".join(f"'{c}'" for c in LIFECYCLE_COLUMNS)}];
BEGIN
    IF {IN_POLICY.system} OR ({IN_POLICY.admin} AND {gucs.PURGING})
       OR OLD.created_by = {gucs.USER_ID.once} THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - lifecycle) IS NOT DISTINCT FROM (to_jsonb(OLD) - lifecycle) AND (
        (OLD.deleted_at IS NULL AND NEW.deleted_by = {gucs.USER_ID.once})
        OR (NEW.deleted_at IS NULL
            AND ({IN_POLICY.admin} OR OLD.deleted_by = {gucs.USER_ID.once}))
    ) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'only its author changes a comment' USING ERRCODE = '42501';
END;
$comment_author$;
"""


def _trashed_with(table: str, column: str) -> str:
    return (
        f"EXISTS (SELECT 1 FROM {table} c WHERE c.id = NEW.{column}"  # noqa: S608
        " AND c.deleted_at = NEW.deleted_at)"
    )


_COMMENT_TRASH_FOLLOWS_FN = f"""
CREATE OR REPLACE FUNCTION public.fn_comment_trash_follows() RETURNS trigger
    LANGUAGE plpgsql AS $trash_follows$
BEGIN
    IF {IN_POLICY.system} OR OLD.created_by = {gucs.USER_ID.once}
       OR {_trashed_with("comments", "parent_comment_id")}
       OR {" OR ".join(_trashed_with(p.table, p.column) for p in COMMENT_PARENTS.values())} THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'a comment goes to the trash with what it is on'
        USING ERRCODE = '42501';
END;
$trash_follows$;
"""


_ANSWER_OWNER_GUARD_FN = f"""
CREATE OR REPLACE FUNCTION public.fn_calendar_event_answer_owner_guard() RETURNS trigger
    LANGUAGE plpgsql AS $answer_owner$
BEGIN
    IF {IN_POLICY.system} OR (NEW.user_id = OLD.user_id AND (
        NEW.rsvp_status = OLD.rsvp_status OR OLD.user_id = {gucs.USER_ID.once}
    )) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'only its member changes an answer' USING ERRCODE = '42501';
END;
$answer_owner$;
"""


def _authored_block() -> str:
    queue = managed_write("initiative_id")
    return "\n".join(
        [
            "ALTER TABLE initiative_join_requests ENABLE ROW LEVEL SECURITY;",
            "ALTER TABLE initiative_join_requests FORCE ROW LEVEL SECURITY;",
            *_policies(
                "initiative_join_requests",
                "join_request",
                f"({_REQUESTER} OR {queue})",
                queue,
                insert=f"({_REQUESTER} AND status = 'pending')",
            ),
            _STAMP_AUTHOR_FN,
            *(
                f"CREATE OR REPLACE TRIGGER tr_{t}_stamp_author"
                f" BEFORE INSERT OR UPDATE OF created_by ON {t} FOR EACH ROW"
                " EXECUTE FUNCTION public.fn_stamp_author();"
                for t in AUTHORED_TABLES
            ),
            _COMMENT_AUTHOR_GUARD_FN,
            "CREATE OR REPLACE TRIGGER tr_comments_author_guard"
            " BEFORE UPDATE ON comments FOR EACH ROW"
            " EXECUTE FUNCTION public.fn_comment_author_guard();",
            _COMMENT_TRASH_FOLLOWS_FN,
            "DROP TRIGGER IF EXISTS tr_comments_trash_follows ON comments;",
            "CREATE CONSTRAINT TRIGGER tr_comments_trash_follows"
            " AFTER UPDATE ON comments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            " WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)"
            " EXECUTE FUNCTION public.fn_comment_trash_follows();",
            "DROP POLICY IF EXISTS owner_insert ON calendar_event_answers;",
            "CREATE POLICY owner_insert ON calendar_event_answers AS RESTRICTIVE"
            f" FOR INSERT WITH CHECK ({_REQUESTER} OR ({gucs.IMPORTING}) IS TRUE);",
            _ANSWER_OWNER_GUARD_FN,
            "CREATE OR REPLACE TRIGGER tr_calendar_event_answers_owner_guard"
            " BEFORE UPDATE ON calendar_event_answers FOR EACH ROW"
            " EXECUTE FUNCTION public.fn_calendar_event_answer_owner_guard();",
        ]
    )


_SEAT_SECTION = """\
-- ===========================================================================
-- Seat-held guild-level tables (app.db.tenancy.SEAT_TABLES): configuration the
-- community's seat holds. Read within the schema — a member's AI request reads
-- the connection it runs on, and opening a plug-in reads where it is placed —
-- except a table in SEAT_READ_TABLES, which the seat or the system engine
-- reads. Written by the seat (app.guild_seat, from the standing), which a lent
-- seat holds beside a read_write content grant, or by the system engine. A
-- table a trigger also fills admits that trigger on INSERT.
--
-- tr_guild_plugin_secrets_fields: each write to an install's secret values
-- rewrites guild_plugins.secret_fields, the keys that hold a value and a digest
-- of each, as whoever made the write.
-- tr_guild_ai_connection_keys_present: each write to a connection's shared
-- key sets guild_ai_connections.has_api_key, as whoever made the write.
-- ==========================================================================="""

_SEAT_READ_PREDICATE = f"({IN_POLICY.system} OR {POLICY_SEAT})"

_SEAT_WRITE_PREDICATE = f"({IN_POLICY.system} OR ({POLICY_SEAT} AND ({IN_POLICY.admin} OR {IN_POLICY.pam_write})))"


# Seat tables a trigger also writes: table -> the leg OR'd into the INSERT
# policy beside the seat's. ``plugin_placements`` gains a row for each install that
# follows new initiatives when an initiative's built-in moderator role is
# created, by whoever created the initiative.
_SEAT_TRIGGER_WRITTEN_INSERT: dict[str, str] = {
    "plugin_placements": "pg_trigger_depth() > 0",
}


def _policies(
    table: str,
    prefix: str,
    read: str | None,
    write: str,
    *,
    insert: str | None = None,
    restrictive: bool = False,
) -> list[str]:
    """One policy per command: ``read`` for SELECT, ``write`` for the other
    three — or ``insert`` for INSERT, when given. PERMISSIVE unless
    ``restrictive``; a RESTRICTIVE set with no ``read`` leaves SELECT alone."""
    kind = "RESTRICTIVE" if restrictive else "PERMISSIVE"
    lines: list[str] = []
    for suffix, command, clause, is_write in _COMMANDS:
        pred = write if is_write else read
        if command == "INSERT" and insert is not None:
            pred = insert
        name = f"{prefix}_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        if pred is None:
            continue
        lines.append(f"CREATE POLICY {name} ON {table} AS {kind} FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    return lines


def _seat_block(table: str) -> str:
    """RLS for a seat-held guild-level table: reading open within the schema,
    or by the seat and the system engine for a ``SEAT_READ_TABLES`` table,
    writing by the seat or the system engine, and inserting by a trigger too
    where ``_SEAT_TRIGGER_WRITTEN_INSERT`` names one."""
    read = _SEAT_READ_PREDICATE if table in SEAT_READ_TABLES else "true"
    trigger = _SEAT_TRIGGER_WRITTEN_INSERT.get(table)
    insert = f"({trigger} OR {_SEAT_WRITE_PREDICATE})" if trigger else None
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            *_policies(table, "seat", read, _SEAT_WRITE_PREDICATE, insert=insert),
        ]
    )


#: ``guild_plugins.secret_fields`` from an install's secret values: the same
#: connection and field keys, each holding the SHA-256 hex digest of its
#: ciphertext. Shared, in ``public``; the row it writes is in the schema the
#: trigger fired in.
PLUGIN_SECRET_FIELDS_FN = """
CREATE OR REPLACE FUNCTION public.fn_plugin_secret_fields() RETURNS trigger
    LANGUAGE plpgsql AS $secret_fields$
DECLARE
    v_install integer;
    v_secrets jsonb := '{}'::jsonb;
    v_fields jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_install := OLD.install_id;
    ELSE
        v_install := NEW.install_id;
        v_secrets := NEW.secrets;
    END IF;
    SELECT COALESCE(jsonb_object_agg(c.key, (
        SELECT COALESCE(jsonb_object_agg(
            f.key, encode(sha256(convert_to(f.value, 'UTF8')), 'hex')
        ), '{}'::jsonb)
        FROM jsonb_each_text(c.value) f
    )), '{}'::jsonb)
    INTO v_fields
    FROM jsonb_each(v_secrets) c
    WHERE jsonb_typeof(c.value) = 'object';
    EXECUTE format(
        $q$UPDATE %I.guild_plugins SET secret_fields = $1
            WHERE id = $2 AND secret_fields IS DISTINCT FROM $1$q$,
        TG_TABLE_SCHEMA
    ) USING v_fields, v_install;
    RETURN NULL;
END;
$secret_fields$;
"""

PLUGIN_SECRET_FIELDS_TRIGGER = (
    "CREATE OR REPLACE TRIGGER tr_guild_plugin_secrets_fields"
    " AFTER INSERT OR UPDATE OR DELETE ON guild_plugin_secrets FOR EACH ROW"
    " EXECUTE FUNCTION public.fn_plugin_secret_fields();"
)

#: ``guild_ai_connections.has_api_key`` from whether the connection has a row in
#: ``guild_ai_connection_keys``. Shared, in ``public``; the row it writes is in
#: the schema the trigger fired in.
AI_KEY_PRESENT_FN = """
CREATE OR REPLACE FUNCTION public.fn_ai_connection_key_present() RETURNS trigger
    LANGUAGE plpgsql AS $key_present$
BEGIN
    EXECUTE format(
        $q$UPDATE %I.guild_ai_connections SET has_api_key = $1
            WHERE id = $2 AND has_api_key IS DISTINCT FROM $1$q$,
        TG_TABLE_SCHEMA
    ) USING TG_OP <> 'DELETE',
        CASE WHEN TG_OP = 'DELETE' THEN OLD.connection_id ELSE NEW.connection_id END;
    RETURN NULL;
END;
$key_present$;
"""

AI_KEY_PRESENT_TRIGGER = (
    "CREATE OR REPLACE TRIGGER tr_guild_ai_connection_keys_present"
    " AFTER INSERT OR DELETE ON guild_ai_connection_keys FOR EACH ROW"
    " EXECUTE FUNCTION public.fn_ai_connection_key_present();"
)


_LEDGER_SECTION = """\
-- ===========================================================================
-- Ledger guild-level tables (app.db.tenancy.LEDGER_TABLES): bookkeeping a
-- system job keeps about a parent row. Read through the parent — the sub-select
-- runs the parent's own SELECT policy, so a row is visible to whoever sees its
-- parent. Written by the system engine alone.
-- ==========================================================================="""


def _ledger_block(table: str, parent: str, fk: str) -> str:
    """RLS for a ledger table: read through its parent, written by the system
    engine."""
    read = (
        f"({IN_POLICY.system} OR EXISTS (SELECT 1 FROM {parent}"
        f" WHERE {parent}.id = {table}.{fk}))"
    )
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            *_policies(table, "ledger", read, IN_POLICY.system),
        ]
    )


_PLUGIN_SECTION = """\
-- ===========================================================================
-- An installed plug-in's scopes, on the tables no tool's gate answers for
-- (app.db.plugin_rls.PLUGIN_TABLE_ACCESS). RESTRICTIVE, so each AND-combines with
-- the table's own policies, and each opens with the install id: a request a
-- person makes carries none and passes in one comparison, once per statement.
--
-- One policy per command, because reading and writing ask different scopes:
-- SELECT asks the resource's read scope, INSERT/UPDATE/DELETE its write scope
-- (nothing, for a resource no scope writes). An install reads the initiatives
-- it is placed in whatever its scopes, since its own standing and the
-- lifecycle checks on its writes read them. An install sees and changes its
-- own event subscriptions and no one else's, and the stored files of the
-- initiatives it is placed in. The change log and the search
-- index are written by triggers, and an install writes them only there; it
-- reads a search entry with the read scope of the entry's kind and of the tool
-- governing it, and a narrowed token reads no entry of a tool that belongs to
-- no initiative, as on the tables the entries describe. The
-- grants an install's request writes are the owner row naming it (the
-- member, for a member token), written by the trigger on the resource it
-- creates, and, with sharing:write and the tool's write scope, the read and
-- write shares of a resource it holds write on. Reactions and recent views
-- are refused. A member token also reads
-- the member's own roster rows and the roles they name, and its own install's
-- consent rows, which its standing reads; it writes no consent.
-- ==========================================================================="""

_PLUGIN_POLICY_PREFIX = "plugin_scope"

_IID = IN_POLICY.install_id


def _plugin_placed_initiatives() -> str:
    """The initiatives the install is placed in, narrowed like its token."""
    scope = IN_POLICY.scope
    return (
        "(SELECT p.initiative_id FROM plugin_placements p"
        f" WHERE p.install_id = {_IID}"
        f" AND ({scope} IS NULL OR p.initiative_id = {scope}))"
    )


#: The member a member token acts for, read back from the routing. Empty for
#: an installation token, which then matches no row.
_PLUGIN_MEMBER = gucs.USER_ID.once

#: The owner row on a tool's resource an installed plug-in creates, written by
#: ``public.fn_install_owns_what_it_creates`` and never by the request itself.
#: It names the install, or, for a member token, the member it acts for.
_PLUGIN_CREATED_OWNER_ROW = (
    "(pg_trigger_depth() > 0"
    f" AND level = '{ResourceAccessLevel.owner.value}'"
    " AND role_id IS NULL"
    " AND NOT all_initiative_members"
    f" AND ((plugin_install_id = {_IID} AND user_id IS NULL AND {_PLUGIN_MEMBER} IS NULL)"
    f" OR (user_id = {_PLUGIN_MEMBER} AND plugin_install_id IS NULL)))"
)

#: The write scope of the tool a grant row is about: the row names its tool
#: by value, and the scope by the tool's plural.
_GRANT_TOOL_SCOPE = (
    "(CASE resource_grants.resource_type "
    + " ".join(
        f"WHEN '{tool.value}' THEN '{tool_resource(tool).value}'" for tool in Tool
    )
    + " END)"
)

#: The rungs a share gives; owner is held, never shared.
_SHARED_LEVELS = (ResourceAccessLevel.read, ResourceAccessLevel.write)

#: A sharing row an installed plug-in with ``sharing:write`` changes, as a person
#: with its rung changes one: it holds the scope and the tool's write scope,
#: and the rung that lets a person share (``resource_shares``). The row
#: shares with a person, a role or all initiative members at read or write;
#: owner rows and plug-in grants are not a share.
_PLUGIN_SHARE_ROW = (
    f"('{PluginScopeResource.sharing.value}' = ANY ({IN_POLICY.field('install_write')})"
    f" AND COALESCE({_GRANT_TOOL_SCOPE}"
    f" = ANY ({IN_POLICY.field('install_write')}), false)"
    f" AND level IN ({sql_values(level.value for level in _SHARED_LEVELS)})"
    " AND plugin_install_id IS NULL"
    " AND resource_shares(resource_grants.resource_type, resource_grants.resource_id,"
    f" {_PLUGIN_MEMBER}, resource_grants.initiative_id, {STANDING}))"
)

#: What an installed plug-in's request writes on ``resource_grants``: the owner
#: row on what it creates, and, with ``sharing:write``, the sharing rows of a
#: resource it may share. A share is rewritten by deleting and inserting rows,
#: so an install updates none.
_PLUGIN_GRANT_INSERT = (
    f"({_IID} IS NULL OR {_PLUGIN_CREATED_OWNER_ROW} OR {_PLUGIN_SHARE_ROW})"
)
_PLUGIN_GRANT_DELETE = f"({_IID} IS NULL OR {_PLUGIN_SHARE_ROW})"

#: What a member token's standing reads of the member's own place in their
#: initiatives, whatever its scopes: their roster rows, and the roles those
#: rows name. Read beside the resource's scope, never instead of the row's own
#: policies.
_PLUGIN_MEMBER_OWN_READ: dict[str, str] = {
    "initiative_members": f"initiative_members.user_id = {_PLUGIN_MEMBER}",
    "initiative_roles": (
        "initiative_roles.id IN (SELECT im.role_id FROM initiative_members im"
        f" WHERE im.user_id = {_PLUGIN_MEMBER})"
    ),
}

#: A member's answers to the plug-ins asking to act as them. A member token's
#: standing reads the one for its own install and purpose; nothing a plug-in
#: sends reads or writes the table otherwise.
_PLUGIN_CONSENT_READ = f"({_IID} IS NULL OR plugin_member_consents.install_id = {_IID})"


def _plugin_search_read() -> str:
    """What an installed plug-in asks to read one search entry.

    The read scope of the entry's kind (``SEARCH_ENTRY_READ_SCOPE``), and of
    the tool governing it where it names one, which is what the table the
    entry describes asks. A token narrowed to one initiative reads no entry of
    a tool's content that belongs to no initiative; the guild's tags stay
    readable to it, as the tags table is. The table's own policies still ask
    placement, the tool's switch, the role and sharing, as they do of a person.
    """
    held = IN_POLICY.field("install_read")
    kinds = " ".join(
        f"WHEN '{kind.value}' THEN '{resource.value}'"
        for kind, resource in sorted(
            SEARCH_ENTRY_READ_SCOPE.items(), key=lambda item: item[0].value
        )
    )
    tools = " ".join(
        f"WHEN '{tool.value}' THEN '{tool_resource(tool).value}'" for tool in Tool
    )
    return (
        f"(COALESCE((CASE search_entries.entity_type {kinds} END) = ANY ({held}), false)"
        " AND (search_entries.dac_tool IS NULL"
        f" OR COALESCE((CASE search_entries.dac_tool {tools} END) = ANY ({held}), false))"
        f" AND ({IN_POLICY.scope} IS NULL OR search_entries.dac_tool IS NULL"
        " OR search_entries.initiative_id IS NOT NULL))"
    )


def _entity_tool_scope(table: str, kinds: tuple[str, ...]) -> str:
    """The scope resource of the tool that governs the thing a ``table`` row
    names by ``(entity_type, entity_id)`` — a task's is ``projects``."""
    tables = entity_tables()
    arms = " ".join(
        f"WHEN '{kind}' THEN '{tool_resource(governing_path(tables[kind])[0]).value}'"  # ty: ignore[not-subscriptable] — every kind has a tool
        for kind in kinds
    )
    return f"(CASE {table}.entity_type {arms} END)"


def _property_values_scope(write: bool) -> str:
    """An installed plug-in reaches a property value with the scope of the tool
    that governs the row it is on — a task's with ``projects``."""
    held = IN_POLICY.field("install_write" if write else "install_read")
    scope = _entity_tool_scope("property_values", PROPERTY_TARGETS)
    return f"({_IID} IS NULL OR {scope} = ANY ({held}))"


def _plugin_metadata_scope(write: bool) -> str:
    """An installed plug-in reaches its own values and no other install's: on
    an item with the read scope of the tool that governs it, for writing too,
    and on the install itself with none. It writes none while the community's
    content is on hold."""
    held = IN_POLICY.field("install_read")
    scope = _entity_tool_scope("plugin_metadata", ITEM_KINDS)
    reach = (
        f"(plugin_metadata.entity_type = '{INSTALL_METADATA_KIND}'"
        f" OR COALESCE({scope} = ANY ({held}), false))"
    )
    hold = f" AND NOT {IN_POLICY.content_hold}" if write else ""
    return (
        f"({_IID} IS NULL OR (plugin_metadata.install_id = {_IID}{hold} AND {reach}))"
    )


def _plugin_predicates(table: str) -> dict[str, str]:
    """What each command asks of an installed plug-in on ``table``, beside what
    the table's own policies ask. Empty where a tool's gate already asks it."""
    refused = plugin_refused(IN_POLICY)
    if table == "resource_grants":
        return {
            "INSERT": _PLUGIN_GRANT_INSERT,
            "UPDATE": refused,
            "DELETE": _PLUGIN_GRANT_DELETE,
        }
    if table == "plugin_member_consents":
        return {
            "SELECT": _PLUGIN_CONSENT_READ,
            "INSERT": refused,
            "UPDATE": refused,
            "DELETE": refused,
        }
    if table in PLUGIN_REFUSED_TABLES:
        return dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), refused)
    if table == "property_values":
        write = _property_values_scope(True)
        return {
            "SELECT": _property_values_scope(False),
            "INSERT": write,
            "UPDATE": write,
            "DELETE": write,
        }
    if table == "plugin_metadata":
        write = _plugin_metadata_scope(True)
        return {
            "SELECT": _plugin_metadata_scope(False),
            "INSERT": write,
            "UPDATE": write,
            "DELETE": write,
        }
    access = PLUGIN_TABLE_ACCESS[table]
    if access.kind is PluginTableKind.subscriptions:
        own = f"({_IID} IS NULL OR plugin_install_id = {_IID})"
        return dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), own)
    if access.kind is PluginTableKind.side_effect:
        if table == "uploads":
            # Stored and claimed as a step of saving content, in the
            # initiatives the install is placed in.
            placed = (
                f"({_IID} IS NULL OR uploads.initiative_id IN "
                f"{_plugin_placed_initiatives()})"
            )
            return dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), placed)
        if table not in _TRIGGER_WRITTEN_INSERT:
            return {}
        by_trigger = f"({_IID} IS NULL OR pg_trigger_depth() > 0)"
        predicates = dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), by_trigger)
        if table == "search_entries":
            predicates["SELECT"] = (
                f"({_IID} IS NULL OR pg_trigger_depth() > 0 OR {_plugin_search_read()})"
            )
        return predicates
    if governing_path(table) is not None or access.resource is None:
        return {}
    read = plugin_scope(access.resource, False, IN_POLICY)
    if table == "initiatives":
        read = f"({read} OR initiatives.id IN {_plugin_placed_initiatives()})"
    elif table == "property_definitions":
        # A value is set with the scope of the tool its item belongs to, and
        # any item in the initiative may carry any of its definitions.
        tools = ", ".join(f"'{tool_resource(tool).value}'" for tool in Tool)
        held = IN_POLICY.field("install_read")
        read = f"({read} OR {held} && ARRAY[{tools}]::text[])"
    elif table in _PLUGIN_MEMBER_OWN_READ:
        read = f"({read} OR {_PLUGIN_MEMBER_OWN_READ[table]})"
    write = (
        plugin_scope(access.resource, True, IN_POLICY) if access.writable else refused
    )
    return {"SELECT": read, "INSERT": write, "UPDATE": write, "DELETE": write}


#: Every table carrying the policies above.
PLUGIN_POLICY_TABLES: frozenset[str] = frozenset(
    t
    for t in (
        *PLUGIN_TABLE_ACCESS,
        *PLUGIN_REFUSED_TABLES,
        "resource_grants",
        "plugin_member_consents",
    )
    if _plugin_predicates(t)
)


def _plugin_block(table: str) -> str:
    """The installed-plugin policies on one table: RESTRICTIVE, one per command
    it asks something of, and the others dropped wherever an earlier render
    left them."""
    predicates = _plugin_predicates(table)
    lines: list[str] = []
    for suffix, command, clause, _write in _COMMANDS:
        name = f"{_PLUGIN_POLICY_PREFIX}_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        pred = predicates.get(command)
        if pred is None:
            continue
        lines.append(f"CREATE POLICY {name} ON {table} AS RESTRICTIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    return "\n".join(lines)


def _guild_level_guard_block(table: str) -> str:
    """RLS for a guild-level soft-delete table (initiatives, tags): a permissive
    allow-all (isolation is the schema boundary, not RLS) plus the RESTRICTIVE
    admin-only-purge guard. NOT an access gate — see _GUILD_LEVEL_SECTION."""
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"DROP POLICY IF EXISTS guild_level_open ON {table};",
            f"CREATE POLICY guild_level_open ON {table} AS PERMISSIVE FOR ALL",
            "  USING (true) WITH CHECK (true);",
            f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table};",
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE",
            f"  USING ({_PURGE_GUARD_PREDICATE});",
            *_trash_read_policy(table),
            *_query_trash_policy(table),
        ]
    )


_SHARING_SECTION = """\
-- ===========================================================================
-- Sharing: who may add, change or remove a row in resource_grants.
--
-- These policies are checked in addition to the table's usual initiative
-- check (RESTRICTIVE: both must pass). A grant row may be written when:
--   * the request may share the resource: it is the owner, in its own right
--     rather than through an access grant (resource_shares);
--   * a trigger writes it: the owner row made along with a new resource, or
--     the grants removed when someone leaves an initiative;
--   * it is an owner row giving an unowned resource back to the person who
--     wrote it (resource_reclaimable).
-- ==========================================================================="""

#: The request may share the resource, or a trigger is writing the row.
_SHARES_ROW = (
    "(pg_trigger_depth() > 0 OR resource_shares(resource_grants.resource_type,"
    f" resource_grants.resource_id, {_PLUGIN_MEMBER}, resource_grants.initiative_id,"
    f" {STANDING}))"
)
#: An owner row naming the author of a resource that has no owner.
_RECLAIMS_ROW = (
    f"(level = '{ResourceAccessLevel.owner.value}' AND user_id IS NOT NULL"
    " AND resource_reclaimable(resource_grants.resource_type,"
    " resource_grants.resource_id, user_id))"
)


def _sharing_block() -> str:
    """The share gate on ``resource_grants``, one RESTRICTIVE policy per write
    command."""
    lines = [
        "DROP POLICY IF EXISTS shares_insert ON resource_grants;",
        "CREATE POLICY shares_insert ON resource_grants AS RESTRICTIVE FOR INSERT",
        f"  WITH CHECK ({_SHARES_ROW} OR {_RECLAIMS_ROW});",
        "DROP POLICY IF EXISTS shares_update ON resource_grants;",
        "CREATE POLICY shares_update ON resource_grants AS RESTRICTIVE FOR UPDATE",
        f"  USING ({_SHARES_ROW}) WITH CHECK ({_SHARES_ROW} OR {_RECLAIMS_ROW});",
        "DROP POLICY IF EXISTS shares_delete ON resource_grants;",
        "CREATE POLICY shares_delete ON resource_grants AS RESTRICTIVE FOR DELETE",
        f"  USING ({_SHARES_ROW});",
    ]
    return "\n".join(lines)


_DRAFT_SECTION = """\
-- ===========================================================================
-- Drafts: a post that is not published yet, or a wiki page marked as a draft,
-- can only be read by people who can edit it.
--
-- RESTRICTIVE on SELECT, so it applies on top of the usual read check.
-- Comments, reactions and polls read their post, so they are hidden with it.
-- ==========================================================================="""


#: What makes a row a draft, per table. The draft policies below and the
#: not-found answer in ``app.services.reachability`` both read it.
DRAFTS: dict[str, str] = {
    "posts": "posts.published_at IS NULL",
    "wiki_pages": "wiki_pages.is_draft",
}


def _draft_block() -> str:
    return "\n".join(
        [
            "DROP POLICY IF EXISTS published_read ON posts;",
            "CREATE POLICY published_read ON posts AS RESTRICTIVE FOR SELECT",
            f"  USING (NOT ({DRAFTS['posts']}) OR resource_access('post', posts.id,"
            f" {_PLUGIN_MEMBER}, posts.initiative_id, true, {STANDING}));",
            "DROP POLICY IF EXISTS finished_read ON wiki_pages;",
            "CREATE POLICY finished_read ON wiki_pages AS RESTRICTIVE FOR SELECT",
            f"  USING (NOT ({DRAFTS['wiki_pages']}) OR EXISTS (SELECT 1 FROM wikis w"
            " WHERE w.id = wiki_pages.wiki_id AND resource_access('wiki', w.id,"
            f" {_PLUGIN_MEMBER}, w.initiative_id, true, {STANDING})));",
        ]
    )


_DEPARTURE_SECTION = """\
-- ===========================================================================
-- Leaving: when someone's initiative membership row is deleted, every grant
-- naming them in that initiative is deleted too, owner rows included, and
-- they are taken off its content: task assignees, event attendees, person
-- fields and queue items. Anything they owned there becomes unowned, and a
-- community admin can claim it. A trigger, so this happens however the
-- membership is removed. Leaving the community runs the same function once
-- more for the community's own content (no initiative).
--
-- departure_*: the trigger may read and remove a row that names someone who
-- is not a member of the row's initiative, whoever removed the membership.
-- ==========================================================================="""


def _departs(named: NamedPerson) -> str:
    """One statement of ``member_departs``: take the person off ``named``'s
    rows in the initiative. Outside a trigger (the community's own content,
    on leaving it), archived or trashed content is left as it is."""
    initiative = initiative_of(named.table, "t", qualify="%1$I.")
    if named.clear:
        head = f"UPDATE %1$I.{named.table} t SET {named.column} = NULL"
        frozen = freeze_leg(named.table, "UPDATE", alias="t")
    else:
        head = f"DELETE FROM %1$I.{named.table} t"
        frozen = freeze_leg(named.table, "DELETE", alias="t")
    return (
        f"    EXECUTE format($q${head} WHERE t.{named.column} = $1"
        f" AND {initiative} IS NOT DISTINCT FROM $2"
        f" AND (pg_trigger_depth() > 0 OR NOT COALESCE({frozen}, false))$q$,"
        " p_schema) USING p_user_id, p_initiative_id;"
    )


def render_departure_fns() -> str:
    """``public.member_departs`` and the trigger function that calls it."""
    grants = (
        "    EXECUTE format($q$DELETE FROM %1$I.resource_grants t"
        " WHERE t.user_id = $1 AND t.initiative_id IS NOT DISTINCT FROM $2"
        " AND (pg_trigger_depth() > 0 OR NOT COALESCE(resource_frozen_for_grant("
        "t.resource_type, t.resource_id, true), false))$q$, p_schema)"
        " USING p_user_id, p_initiative_id;"
    )
    body = "\n".join([grants, *(_departs(n) for n in NAMED_PEOPLE)])
    return f"""
CREATE OR REPLACE FUNCTION public.member_departs(
    p_schema text, p_user_id integer, p_initiative_id integer
) RETURNS void LANGUAGE plpgsql AS $member_departs$
BEGIN
{body}
END;
$member_departs$;

CREATE OR REPLACE FUNCTION public.fn_initiative_departure() RETURNS trigger
    LANGUAGE plpgsql AS $departure$
BEGIN
    PERFORM public.member_departs(TG_TABLE_SCHEMA, OLD.user_id, OLD.initiative_id);
    RETURN NULL;
END;
$departure$;
"""


INITIATIVE_DEPARTURE_TRIGGER = (
    "CREATE OR REPLACE TRIGGER tr_initiative_members_departure"
    " AFTER DELETE ON initiative_members FOR EACH ROW"
    " EXECUTE FUNCTION public.fn_initiative_departure();"
)


def _departure_policies() -> str:
    lines: list[str] = []
    for named in NAMED_PEOPLE:
        t, col = named.table, named.column
        initiative = initiative_of(t, t)
        departed = (
            f"pg_trigger_depth() > 0 AND {initiative} IS NOT NULL AND NOT EXISTS"
            " (SELECT 1 FROM initiative_members m"
            f" WHERE m.user_id = {t}.{col} AND m.initiative_id = {initiative})"
        )
        write = (
            f"departure_update ON {t} AS PERMISSIVE FOR UPDATE"
            f"  USING ({departed}) WITH CHECK ({col} IS NULL);"
            if named.clear
            else f"departure_delete ON {t} AS PERMISSIVE FOR DELETE"
            f"  USING ({departed});"
        )
        lines += [
            f"DROP POLICY IF EXISTS departure_read ON {t};",
            f"DROP POLICY IF EXISTS departure_update ON {t};",
            f"DROP POLICY IF EXISTS departure_delete ON {t};",
            f"CREATE POLICY departure_read ON {t} AS PERMISSIVE FOR SELECT"
            f"  USING ({departed});",
            f"CREATE POLICY {write}",
        ]
    return "\n".join(lines)


_FREEZE_SECTION = """\
-- ===========================================================================
-- The lifecycle freeze: the parts that need the old row and the new row
-- together, which a policy never has.
--
-- tr_<t>_frozen_guard: the row is itself archived or trashed.
-- tr_<t>_frozen_ancestor_update: it carries no stamp of its own and hangs off
--   something that is, or is being moved to hang off something that is.
-- Both permit a change to the lifecycle columns and nothing else, so a frozen
-- row can still be unarchived, restored, or given a new purge date. Their WHEN
-- clauses keep an ordinary write on live content from reaching the function.
--
-- tr_<t>_frozen_trashed_ancestor_update: the same rule about coming out
--   unstamped, for a row that can be trashed but never archived. Unstamped
--   inside an archived thing is the only state such a row has, so it is asked
--   about a trashed ancestry alone — otherwise a restore could never put the
--   comments, queue items, counters, pictures and events back.
--
-- tr_<t>_frozen_delete / tr_<t>_frozen_ancestor_delete: DELETE has no WITH
-- CHECK, so RLS could only refuse it by returning no rows. A row that carries
-- its own stamp is asked about itself; one that does not is asked about its
-- ancestry, with trashed_ok so a purge cascade — the one delete a trashed row
-- is FOR — runs.
-- ==========================================================================="""


def render_retired_functions_ddl() -> str:
    """Drop the functions an earlier render put in the schema and this one no
    longer calls. Last in the script, after every policy that named one has
    been re-created without it.

    Only the copy in the schema being rendered. The script runs with the
    search path set to ``<schema>, public``, so an unqualified name with no
    local copy resolves to ``public`` — and a release that kept the function
    there (0.71 did) has every other guild's policies still bound to that
    copy. Dropping it from one guild's render fails that guild, and then the
    next, so no guild is ever re-rendered. The shared copy is retired once, at
    boot, after every guild has stopped using it
    (``ensure_public_copies_dropped``).
    """
    drops = " ".join(
        f"IF to_regprocedure(format('%I.{name}{args}', current_schema())) "
        "IS NOT NULL THEN "
        f"EXECUTE format('DROP FUNCTION %I.{name}{args}', current_schema()); "
        "END IF;"
        for name, args in RETIRED_GUILD_FUNCTION_SIGNATURES
    )
    return f"DO $retire$ BEGIN {drops} END $retire$;"


def render_guild_rls_ddl() -> str:
    from app.db.holds import render_holds_ddl
    from app.db.moderation_log import render_moderation_log_ddl

    blocks = [_table_block(t, INITIATIVE_PATHS[t]) for t in sorted(INITIATIVE_PATHS)]
    # Shared, and written before the policies that call it. Re-rendered on every
    # provisioning run from the same registry the policies come from, so a kind
    # added to the graph reaches the gate the moment its entry does.
    out = (
        _HEADER
        + "\n"
        + render_guild_authorization_functions()
        + "\n"
        + render_entity_access_fn()
        + "\n"
        + render_entity_initiative_fn()
        + "\n"
        + render_resource_frozen_fn()
        + "\n"
        + render_resource_frozen_for_grant_fn()
        + "\n"
        + render_frozen_guard_fn()
        + "\n"
        + render_frozen_parent_guard_fn()
        + "\n"
        + render_frozen_ancestor_fn()
        + "\n"
        + "\n\n".join(blocks)
    )
    guards = [
        _guild_level_guard_block(t)
        for t in sorted(_GUILD_LEVEL_PURGE_TABLES - set(MANAGED_TABLES))
    ]
    if guards:
        out += "\n\n" + _GUILD_LEVEL_SECTION + "\n\n" + "\n\n".join(guards)
    managed = [_managed_block(t, e) for t, e in sorted(MANAGED_TABLES.items())]
    out += "\n\n" + _MANAGED_SECTION + "\n\n" + "\n\n".join(managed)
    own_rows = [_own_row_block(t, c) for t, c in sorted(OWN_ROW_TABLES.items())]
    if own_rows:
        out += "\n\n" + _OWN_ROW_SECTION + "\n\n" + "\n\n".join(own_rows)
    private = [_private_row_block(t, c) for t, c in sorted(PRIVATE_ROW_TABLES.items())]
    out += "\n\n" + _PRIVATE_ROW_SECTION + "\n\n" + "\n\n".join(private)
    out += "\n\n" + _AUTHORED_SECTION + "\n" + _authored_block()
    seats = [_seat_block(t) for t in sorted(SEAT_TABLES)]
    out += "\n\n" + _SEAT_SECTION + "\n\n" + "\n\n".join(seats)
    out += "\n" + PLUGIN_SECRET_FIELDS_FN + "\n" + PLUGIN_SECRET_FIELDS_TRIGGER
    out += "\n" + AI_KEY_PRESENT_FN + "\n" + AI_KEY_PRESENT_TRIGGER
    ledgers = [_ledger_block(t, p, fk) for t, (p, fk) in sorted(LEDGER_TABLES.items())]
    out += "\n\n" + _LEDGER_SECTION + "\n\n" + "\n\n".join(ledgers)
    # After every block above, so each table's RLS is on before its plug-in
    # policies join the ones already there.
    plugin_blocks = [_plugin_block(t) for t in sorted(PLUGIN_POLICY_TABLES)]
    out += "\n\n" + _PLUGIN_SECTION + "\n\n" + "\n\n".join(plugin_blocks)
    out += "\n\n" + _SHARING_SECTION + "\n\n" + _sharing_block()
    out += "\n\n" + _DRAFT_SECTION + "\n\n" + _draft_block()
    out += "\n\n" + render_holds_ddl()
    out += "\n\n" + render_moderation_log_ddl()
    out += (
        "\n\n"
        + _DEPARTURE_SECTION
        + "\n"
        + render_departure_fns()
        + "\n"
        + INITIATIVE_DEPARTURE_TRIGGER
        + "\n"
        + _departure_policies()
    )
    guards = [f"{frozen_guard_trigger(t)};" for t in sorted(FROZEN_TABLES)]
    guards += [
        f"{trigger};"
        for table in sorted(INITIATIVE_PATHS)
        for trigger in frozen_write_triggers(table)
    ]
    out += "\n\n" + _FREEZE_SECTION + "\n" + "\n".join(guards)
    return out + "\n\n" + render_retired_functions_ddl() + "\n"


# ============================================================================
# Structure rendering (reflected live from guild_template)
# ============================================================================

_DIALECT = postgresql.dialect()

# The schema the artifact is reflected from: Alembic-maintained guild_template.
# Public because provisioning also re-asserts RLS on it, and the name should
# be stated once.
TEMPLATE_SCHEMA = "guild_template"
_SRC_SCHEMA = TEMPLATE_SCHEMA

# CHECK + FK constraint definitions straight from Postgres (authoritative text).
# The session search_path is set to "<src>, public" before these run, so
# pg_get_constraintdef / pg_get_indexdef / pg_get_triggerdef emit visible names
# UNQUALIFIED — the artifact stays schema-relative.
_CONSTRAINT_SQL = text(
    f"""
    SELECT cl.relname AS tbl, con.conname, con.contype::text AS contype,
           pg_get_constraintdef(con.oid) AS condef,
           tgt.relname AS tgt
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = cl.relnamespace AND ns.nspname = '{_SRC_SCHEMA}'
    LEFT JOIN pg_class tgt ON tgt.oid = con.confrelid
    WHERE con.contype IN ('c', 'f') AND cl.relname = ANY(:t)
    ORDER BY con.contype, cl.relname, con.conname
    """
)


def _build_tables(sync_conn) -> list[str]:
    md = MetaData()
    md.reflect(
        bind=sync_conn, schema=_SRC_SCHEMA, only=lambda n, _m: n in GUILD_SCOPED_TABLES
    )
    rel = MetaData()
    out: list[str] = []
    for name in sorted(GUILD_SCOPED_TABLES):
        t = md.tables[f"{_SRC_SCHEMA}.{name}"].to_metadata(rel, schema=None)
        # CHECK + FK come from pg_get_constraintdef below; drop them here so the
        # CREATE TABLE only carries columns + PRIMARY KEY + UNIQUE.
        for con in list(t.constraints):
            if isinstance(con, CheckConstraint):
                t.constraints.discard(con)
        # ``CreateTable`` renders constraints in the order reflection happened to
        # build them, which the catalog does not promise to repeat. That order
        # reaches the provisioning stamp, and the stamp is what decides whether a
        # guild schema is stale — so an unstable one would re-provision every
        # guild on every boot. Restamp it from each constraint's own name, which
        # is fixed. Only visible on a table carrying more than one.
        for order, con in enumerate(
            sorted(t.constraints, key=lambda c: (type(c).__name__, c.name or ""))
        ):
            con._creation_order = order
        for col in t.columns:
            if hasattr(col.type, "create_type"):
                col.type.create_type = False  # ty: ignore[invalid-assignment]
        out.append(
            str(
                CreateTable(
                    t, if_not_exists=True, include_foreign_key_constraints=[]
                ).compile(dialect=_DIALECT)
            ).strip()
            + ";"
        )
    return out


# Non-constraint indexes from Postgres itself (pg_get_indexdef preserves opclasses
# like jsonb_path_ops, partial-index WHERE, etc. that SQLAlchemy reflection drops).
# The only interpolation below is the _SRC_SCHEMA string literal — no user input
# reaches this module's rendered SQL (scanner: hardcoded_sql_expressions is the
# point; this file IS the DDL renderer).
_INDEX_SQL = text(  # noqa: S608
    f"""
    SELECT tc.relname AS tbl, pg_get_indexdef(i.indexrelid) AS indexdef
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class tc ON tc.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = tc.relnamespace AND n.nspname = '{_SRC_SCHEMA}'
    WHERE tc.relname = ANY(:t)
      AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid)
    ORDER BY tc.relname, ic.relname
    """
)


def _schema_relative_index(indexdef: str) -> str:
    # CREATE [UNIQUE] INDEX name ON <src>.tbl USING ...  ->  schema-relative + idempotent
    indexdef = re.sub(
        r"^CREATE (UNIQUE )?INDEX ", r"CREATE \1INDEX IF NOT EXISTS ", indexdef
    )
    indexdef = indexdef.replace(f" ON {_SRC_SCHEMA}.", " ON ")
    return indexdef + ";"


# The migration-owned triggers (``tr_<t>_set_created_by``, migration 0188). The
# trigger FUNCTIONS are shared in public with no pinned search_path, so under
# search_path=<guild_schema>,public they act on the guild's own rows. Triggers
# the registries render (freeze, capture, search) are not structure and are
# left out by name below — see ``rendered_trigger_names`` — so a template that
# still carries them from an earlier boot contributes nothing of theirs here.
_TRIGGER_SQL = text(  # noqa: S608 — interpolates only the _SRC_SCHEMA literal
    f"""
    SELECT cl.relname AS tbl, tg.tgname AS name, pg_get_triggerdef(tg.oid) AS triggerdef
    FROM pg_trigger tg
    JOIN pg_class cl ON cl.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = '{_SRC_SCHEMA}'
    WHERE NOT tg.tgisinternal AND cl.relname = ANY(:t)
    ORDER BY cl.relname, tg.tgname
    """
)


def _schema_relative_trigger(triggerdef: str) -> str:
    # CREATE TRIGGER name ... ON <src>.tbl ... EXECUTE FUNCTION fn()  ->
    # schema-relative + idempotent (CREATE OR REPLACE; the function stays shared).
    triggerdef = triggerdef.replace("CREATE TRIGGER ", "CREATE OR REPLACE TRIGGER ")
    triggerdef = triggerdef.replace(f" ON {_SRC_SCHEMA}.", " ON ")
    return triggerdef + ";"


_TRIGGER_NAME_RE = re.compile(r"CREATE (?:OR REPLACE )?(?:CONSTRAINT )?TRIGGER (\w+)")
_CONSTRAINT_NAME_RE = re.compile(r"ADD CONSTRAINT (\w+)")


def _registry_ddl() -> str:
    """Everything the registries render into a guild schema, as one text."""
    from app.db.event_capture import render_guild_capture_ddl
    from app.db.search_index import render_guild_search_ddl

    return "\n".join(
        (
            render_guild_rls_ddl(),
            render_guild_capture_ddl(),
            render_guild_search_ddl(None),
        )
    )


def rendered_trigger_names() -> frozenset[str]:
    """Every trigger name the registries render into a guild schema.

    Read off the rendered DDL itself — the freeze triggers in the RLS render,
    the change-capture triggers, the search-index triggers — so the set is
    whatever the renderers currently produce, with no list to keep in step.
    The structure reflection and the clone-fidelity test both use it to tell a
    migration-owned object from a rendered one.
    """
    return frozenset(_TRIGGER_NAME_RE.findall(_registry_ddl()))


def rendered_constraint_names() -> frozenset[str]:
    """Every constraint name the registries render into a guild schema.

    Today that is the search index's entity-type CHECK, which names the
    indexed set and is re-asserted per guild so a source added to the registry
    is admitted everywhere. Read off the rendered DDL, like the triggers.
    """
    return frozenset(_CONSTRAINT_NAME_RE.findall(_registry_ddl()))


def _guard(conname: str, body: str) -> str:
    # Idempotent ADD CONSTRAINT: skip if a constraint of this name already exists
    # in the current schema (search_path puts the guild schema first).
    return (
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{conname}' AND connamespace = current_schema()::regnamespace) "
        f"THEN {body}; END IF; END $$;"
    )


async def render_guild_schema_ddl(engine: AsyncEngine) -> str:
    """Reflect the live ``guild_template`` and return the schema-relative,
    idempotent structure DDL for provisioning a guild schema."""
    async with engine.connect() as conn:
        # Visible-name resolution: with the template first on the search_path,
        # pg_get_*def emit its tables unqualified (and shared public objects
        # qualified only when shadowed) — keeping the DDL schema-relative.
        await conn.execute(text(f'SET search_path TO "{_SRC_SCHEMA}", public'))
        table_stmts = await conn.run_sync(_build_tables)
        index_rows = (
            await conn.execute(_INDEX_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()
        rows = (
            await conn.execute(_CONSTRAINT_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()
        trigger_rows = (
            await conn.execute(_TRIGGER_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()

    rendered = rendered_trigger_names()
    rendered_constraints = rendered_constraint_names()
    indexes = [_schema_relative_index(r.indexdef) for r in index_rows]
    triggers = [
        _schema_relative_trigger(r.triggerdef)
        for r in trigger_rows
        if r.name not in rendered
    ]
    checks, fks = [], []
    for r in rows:
        if r.contype == "c" and r.conname not in rendered_constraints:
            checks.append(
                _guard(
                    r.conname,
                    f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}',
                )
            )
        elif r.contype == "f" and r.tgt in GUILD_SCOPED_TABLES:  # intra-schema only
            fks.append(
                _guard(
                    r.conname,
                    f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}',
                )
            )

    header = (
        "-- RENDERED AT RUNTIME from the live guild_template schema. Schema-relative:\n"
        "-- run with search_path = <guild_schema>, public. Idempotent.\n\n"
    )
    return (
        header
        + "\n".join(table_stmts)
        + "\n\n-- indexes\n"
        + "\n".join(indexes)
        + "\n\n-- CHECK constraints\n"
        + "\n".join(checks)
        + "\n\n-- intra-schema FOREIGN KEYs\n"
        + "\n".join(fks)
        + "\n\n-- migration-owned triggers (functions are shared in public)\n"
        + "\n".join(triggers)
        + "\n"
    )
