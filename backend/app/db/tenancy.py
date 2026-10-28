"""Authoritative table classification for schema-per-guild multi-tenancy.

Single source of truth for *where each table lives* and *how it is access-scoped*
once each guild becomes its own PostgreSQL schema. Two orthogonal levels:

**Level 1 — schema placement:**

- **Shared tables** stay in the ``public`` schema — identity, the tenancy
  roster, platform config, and per-user / cross-guild concerns read *without* a
  guild context (login, "list my guilds", platform staff, SSO auto-join, the
  notification inbox). ``SHARED_TABLES`` is *derived* from
  ``app.db.public_rls.SHARED_TABLE_REGISTRY``, where each one is declared with
  its row security and grants.
- **Guild-scoped tables** move into a per-guild schema (``guild_<id>``) — the
  actual tenant content. ``GUILD_SCOPED_TABLES`` is *derived* as
  ``INITIATIVE_SCOPED_TABLES | GUILD_LEVEL_TABLES`` (level 2), so a guild table
  is declared in exactly one of those — never copied here.

**Level 2 — initiative access boundary (within a guild schema):**

- **Initiative-scoped** tables carry the four ``initiative_member_*`` RLS
  policies deferring to ``initiative_access(...)``. They are declared once
  in ``app.db.initiative_rls.INITIATIVE_PATHS`` (table -> initiative path);
  ``INITIATIVE_SCOPED_TABLES`` is the keys of that registry, and
  the RLS DDL is rendered from it at provisioning time (``app.db.guild_ddl``).
  So adding an initiative-scoped table is a *single* edit (a path in
  ``initiative_rls``).
- **Guild-level** tables (``GUILD_LEVEL_TABLES``) are exempt — guild-wide,
  structural, or own-row — protected only by the schema boundary (the
  ``guild_<id>`` role). Adding one here is the explicit "not initiative-scoped"
  decision.

Every ``table=True`` model MUST land in ``SHARED_TABLES`` or (via level 2)
``GUILD_SCOPED_TABLES``. ``tenancy_test.py`` enforces this against
``SQLModel.metadata`` so a new table can't be added without a placement
decision.
"""

from __future__ import annotations

from app.db.initiative_rls import INITIATIVE_SCOPED_TABLES
from app.db.public_rls import SHARED_TABLE_REGISTRY

__all__ = [
    "NON_MODEL_SHARED_TABLES",
    "SHARED_TABLES",
    "GUILD_LEVEL_TABLES",
    "MANAGED_TABLES",
    "OWN_ROW_TABLES",
    "MEMBER_CREDENTIAL_TABLES",
    "MEMBER_SECRET_TABLES",
    "PRIVATE_ROW_SHARED_READ",
    "PRIVATE_ROW_TABLES",
    "CREATED_BY_EXEMPT_TABLES",
    "INITIATIVE_SCOPED_TABLES",
    "GUILD_SCOPED_TABLES",
    "ALL_CLASSIFIED_TABLES",
    "is_guild_scoped",
    "is_shared",
    "is_initiative_scoped",
]

# --- Shared (stay in the ``public`` schema) ---------------------------------
# Read without a guild context, or inherently cross-guild. Must never be
# duplicated per schema.

#: The ``public`` tables no model maps: Alembic's own, and
#: ``storage_backfill_state``, which ``app.services.storage_backfill`` creates
#: at runtime. Each still has a registry record for its grants.
NON_MODEL_SHARED_TABLES: frozenset[str] = frozenset(
    {"alembic_version", "storage_backfill_state"}
)

#: Every shared table a model maps: the shared-table registry, which records
#: why each one is shared, less the tables no model maps.
SHARED_TABLES: frozenset[str] = (
    frozenset(SHARED_TABLE_REGISTRY) - NON_MODEL_SHARED_TABLES
)

# --- Guild-scoped, NOT initiative-scoped (level 2 exemptions) ----------------
# Guild-wide, structural, or own-row tables protected only by the schema
# boundary. The complement of this set within a guild schema is
# ``INITIATIVE_SCOPED_TABLES`` (declared in ``app.db.initiative_rls``).
GUILD_LEVEL_TABLES: frozenset[str] = frozenset(
    {
        # NB: "guild-level" = not initiative-membership-gated. Two members here
        # (initiatives, tags) are soft-deletable and so DO carry RLS — but only to
        # host the admin-only purge guard (guild_level_open allow-all +
        # soft_delete_admin_purge), never a membership scope. See the rendered RLS DDL.
        # Guild-wide config / data (no initiative scope)
        "guild_settings",
        # Installed plug-ins: guild-wide by definition, and readable by any member —
        # the sidebar has to know a plug-in is there. Installing, configuring and
        # removing are the seat's (SEAT_TABLES below); what a member may do
        # *inside* a plug-in is decided by that instance's own grants, not by this
        # row.
        "guild_plugins",
        # The secret values of each install's connections, one row per
        # install. Read and written by the seat and the system engine alone
        # (SEAT_READ_TABLES below); members read which keys hold a value off
        # guild_plugins.secret_fields.
        "guild_plugin_secrets",
        # Where an install appears, one row per initiative, with the roles
        # allowed to open it there. A fact about the install rather than
        # initiative content: read within the schema, written by the seat
        # (SEAT_TABLES below).
        "plugin_placements",
        "guild_ai_connections",  # the seat's AI connections (guild config mode);
        # guild-wide config, no initiative scope, written by the seat (SEAT_TABLES
        # below).
        # The shared key of each of those connections, one row per connection.
        # Read and written by the seat and the system engine alone
        # (SEAT_READ_TABLES below); members read whether there is one off
        # guild_ai_connections.has_api_key.
        "guild_ai_connection_keys",
        "webhook_deliveries",  # per-subscription delivery ledger, no initiative of
        # its own; read through its subscription (LEDGER_TABLES below).
        "subscription_progress",  # how far through the change log subscribers
        # were told; the system engine's alone (LEDGER_TABLES below).
        "plugin_hook_deliveries",  # vendor webhook deliveries an install accepted;
        # read through the install (LEDGER_TABLES below).
        "plugin_schedule_runs",  # when an install's schedules last ran and run
        # next; read through the install (LEDGER_TABLES below).
        "timer_marks",  # the earliest sweep timer the community has waiting,
        # written by public.arm_timer as a step of the write that armed it.
        "tags",  # tags are guild-level, shared across initiatives (purge-guarded)
        # Structural initiative tables — guild-scoped for reading (a roster is
        # read by its co-members, and the standing statement reads it before
        # any standing exists), written by the initiative's managers: see
        # MANAGED_TABLES below and the rendered RLS DDL header.
        "initiatives",  # purge-guarded (admin-only DELETE) as well
        "initiative_members",
        "initiative_roles",
        "initiative_role_permissions",
        # Join requests: the requester is by definition NOT yet a member, so an
        # initiative-membership row gate would hide their own request from them
        # — the same reasoning that keeps initiative_members structural. Its
        # own policies admit the requester and whoever answers the
        # initiative's queue (app.db.guild_ddl._authored_block).
        "initiative_join_requests",
        # Own-row tables (also listed in OWN_ROW_TABLES below): guild-level
        # placement, but rows belong to ONE user and carry own_row_* policies.
        "export_jobs",  # a job may span initiatives ("export all my tasks"), so
        # it can't use initiative_access; the row holds selector text and gates
        # the artifact download, so it must not be guild-wide-readable either.
        "import_jobs",  # same shape as export_jobs: a backup import spans
        # initiatives, and the row's options/plan/report text plus the staged
        # payload it gates must not be guild-wide-readable.
        "pending_uploads",  # a file arriving in pieces is its uploader's until
        # an endpoint takes it; a backup being uploaded spans initiatives.
        # A member's own credentials: their connection to an installed plug-in's
        # vendor (MEMBER_CREDENTIAL_TABLES). No FK to any initiative — a
        # plug-in is community-wide.
        "guild_plugin_user_connections",
        # What those credentials hold, beside them (MEMBER_SECRET_TABLES): the
        # member and the system engine alone.
        "plugin_connection_secrets",
        # A member's answer to an installed plug-in asking to act as them, one per
        # purpose. The same shape as the connections beside it: no FK to any
        # initiative is required (a purpose may be app-wide), one owner per
        # row, and the community's administration reads and revokes, so
        # own_row_* policies. A member token's standing reads the member's own
        # row for its install.
        "plugin_member_consents",
        # The platform's record of what it holds in the community: why, by
        # whom, under which case. Read by the system engine and a ``moderate``
        # grantee alone, never by the community — its policies are rendered
        # from ``app.db.holds``, with no admin leg.
        "content_holds",
    }
)

# --- Managed overlay on the structural initiative tables ----------------------
# Guild-level tables whose rows are an initiative's own structure: table -> the
# SQL expression a row's initiative is read from. Reading stays open within the
# schema; writing is the initiative's managers', the community's admin's, a
# settings rung's beside a read_write grant, or the system engine's — rendered
# as ``managed_*`` policies by ``app.db.guild_ddl.render_guild_rls_ddl`` from
# the standing (``app.manager_initiatives``), so the membership table is gated
# by a value the seam computed rather than by a read of itself. Every entry
# here MUST also be in ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
MANAGED_TABLES: dict[str, str] = {
    "initiatives": "id",
    "initiative_members": "initiative_id",
    "initiative_roles": "initiative_id",
    "initiative_role_permissions": (
        "(SELECT r.initiative_id FROM initiative_roles r WHERE r.id = initiative_role_id)"
    ),
}

# --- Own-row overlay on guild-level tables -----------------------------------
# Guild-level tables whose rows belong to ONE user: table -> owner FK column.
# These get per-command ``own_row_*`` RLS policies (owner OR routed guild
# admin) rendered by ``app.db.guild_ddl.render_guild_rls_ddl`` — unlike the
# allow-all ``guild_level_open`` tables, this IS a row gate. Every entry here
# MUST also be in ``GUILD_LEVEL_TABLES`` (that's the schema-placement decision;
# this is the policy overlay) — enforced in ``tenancy_test.py``.
OWN_ROW_TABLES: dict[str, str] = {
    "export_jobs": "created_by",
    "import_jobs": "created_by",
    "pending_uploads": "created_by",
    "plugin_member_consents": "user_id",
}

# --- Private-row overlay on initiative-scoped tables --------------------------
# Initiative-scoped tables whose rows are one member's own state about content
# they reach: table -> owner FK column. Only that member and the system engine
# reach a row — no guild admin, settings rung or grant — through RESTRICTIVE
# ``private_row_*`` policies rendered by ``app.db.guild_ddl.render_guild_rls_ddl``
# on top of the table's initiative gate. Every entry here MUST also be in
# ``INITIATIVE_PATHS`` — enforced in ``tenancy_test.py``.
PRIVATE_ROW_TABLES: dict[str, str] = {
    "personal_items": "user_id",
    "post_reads": "user_id",
    "post_poll_votes": "user_id",
    "reactions": "created_by",
}

# The private-row tables the rest of the initiative reads (a notice's read
# count, a poll's tally and who chose what, who reacted): written by their owner alone, read
# under the initiative gate. Every entry here MUST also be in
# ``PRIVATE_ROW_TABLES`` — enforced in ``tenancy_test.py``.
PRIVATE_ROW_SHARED_READ: frozenset[str] = frozenset(
    {"post_reads", "post_poll_votes", "reactions"}
)

# --- A member's credentials ----------------------------------------------------
# Guild-level tables saying that a member holds a credential: table -> owner
# column. The member, the community's seat and the system engine read and write
# them — not a plain admin or a settings rung — rendered as
# ``member_credential_*`` policies by ``app.db.guild_ddl.render_guild_rls_ddl``.
# Every entry here MUST also be in ``GUILD_LEVEL_TABLES`` — enforced in
# ``tenancy_test.py``.
MEMBER_CREDENTIAL_TABLES: dict[str, str] = {
    "guild_plugin_user_connections": "user_id",
}

# --- What a member's credentials hold -----------------------------------------
# The secret values beside a MEMBER_CREDENTIAL_TABLES row: table -> (that
# table, the column naming the row). Only the member the row names and the
# system engine reach them, rendered as ``member_secret_*`` policies. Deleting
# the credential row takes its secret with it (ON DELETE CASCADE). Every entry
# here MUST also be in ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
MEMBER_SECRET_TABLES: dict[str, tuple[str, str]] = {
    "plugin_connection_secrets": ("guild_plugin_user_connections", "connection_row_id"),
}

# --- Seat overlay on guild-level tables ---------------------------------------
# Guild-level configuration the community's seat holds. Read within the schema:
# a member's AI request reads the connection it runs on, and opening a plug-in
# reads where it is placed. Written by the seat — the membership row's
# superadmin, or a superadmin settings grant beside a read_write content grant
# — or the system engine; the same answer the routes in front of it ask for.
# A table a trigger also writes names that in
# ``app.db.guild_ddl._SEAT_TRIGGER_WRITTEN_INSERT``. Rendered as ``seat_*`` policies by
# ``app.db.guild_ddl.render_guild_rls_ddl``. Every entry here MUST also be in
# ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
SEAT_TABLES: frozenset[str] = frozenset(
    {
        "plugin_placements",
        "guild_ai_connection_keys",
        "guild_ai_connections",
        "guild_plugin_secrets",
        "guild_plugins",
    }
)

# --- Seat tables read by the seat alone ---------------------------------------
# The seat tables whose rows are read by the seat or the system engine rather
# than within the schema: rendered with the same ``seat_*`` policies, whose
# read predicate is the seat's. Every entry here MUST also be in
# ``SEAT_TABLES`` — enforced in ``tenancy_test.py``.
SEAT_READ_TABLES: frozenset[str] = frozenset(
    {"guild_ai_connection_keys", "guild_plugin_secrets"}
)

# --- Ledger overlay on guild-level tables -------------------------------------
# Guild-level bookkeeping a system job keeps about a parent row: table ->
# (parent table, FK column). Read through the parent, so a row is visible to
# whoever the parent's own policy shows the parent to; written by the system
# engine alone. ``None`` for bookkeeping about no row, read and written by the
# system engine alone. Rendered as ``ledger_*`` policies by
# ``app.db.guild_ddl.render_guild_rls_ddl``. Every entry here MUST also be in
# ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
LEDGER_TABLES: dict[str, tuple[str, str] | None] = {
    "webhook_deliveries": ("webhook_subscriptions", "subscription_id"),
    "subscription_progress": None,
    "plugin_hook_deliveries": ("guild_plugins", "install_id"),
    "plugin_schedule_runs": ("guild_plugins", "install_id"),
}

# --- Row-attribution overlay on guild-schema tables ---------------------------
# Every guild-schema table that models something a person made carries
# ``created_by`` + ``updated_by`` by subclassing
# ``app.models.tenant._mixins.CreatedByMixin``. Membership is therefore
# declared by the model, not copied into a list here; what IS declared here is
# the opposite — the tables that deliberately do NOT carry the pair, each with
# the reason it does not need one. ``created_by_test.py`` fails CI when a guild
# table is in neither bucket, so a new table forces the decision.
CREATED_BY_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        # A file in a collection: ``added_by`` already names who put it there.
        "collection_files",
        # Roster rows: the membership IS the fact, and ``user_id`` already names
        # whose it is.
        "calendar_event_attendees",
        "calendar_event_answers",
        "initiative_members",
        "initiative_role_permissions",
        "task_assignees",
        # A knock at a door: ``user_id`` is both the author and the subject, and
        # ``resolved_by`` already names the manager who answered it.
        "initiative_join_requests",
        # Per-user state, keyed by the user it belongs to. ``user_id`` is both
        # the author and the subject, so a second copy of it says nothing.
        "guild_plugin_user_connections",
        "plugin_member_consents",
        "post_reads",
        # A fact about an install: where it appears. The rows a new initiative's
        # trigger writes have no person placing them.
        "plugin_placements",
        # An install's secret values, one row per install. The install row
        # names who made it.
        "guild_plugin_secrets",
        # A member's secret values, one row per credential row, which names
        # whose it is.
        "plugin_connection_secrets",
        # A connection's shared key. The connection row names who made it.
        "guild_ai_connection_keys",
        # A ballot: ``user_id`` is the voter, which is both the author of the
        # row and its whole content.
        "post_poll_votes",
        "personal_items",
        # A value belongs to its definition's owner, not to whoever set it.
        "metadata_values",
        # Machinery. Written by a trigger, a poller or a scheduler rather than
        # by a person; each already records the actor it needs (the outbox
        # carries ``actor_user_id``) or has none to record.
        "event_outbox",
        "plugin_event_outbox",
        "plugin_hook_deliveries",
        "plugin_schedule_runs",
        "event_reminder_dispatches",
        "search_entries",
        "engagement_levels",
        "reaction_digest_items",
        "task_assignment_digest_items",
        "webhook_deliveries",
        "subscription_progress",
        "timer_marks",
        # The key -> task map the intake writer reads. The case it points at
        # carries the author, and a system-opened one has none by design.
        "intake_cases",
        # A report is not authored — it is a thing several people said about
        # one target. Who said it is the reporters table, and who settled it is
        # ``decided_by``; a creator column would be a third answer to neither
        # question.
        "moderation_reports",
        "moderation_report_reporters",
        # A hold names who placed it in ``placed_by``, and may be placed by a
        # moderator of another community entirely: the platform's.
        "content_holds",
    }
)

# --- Guild-scoped (derived) -------------------------------------------------
# Everything that moves into a ``guild_<id>`` schema = the initiative-scoped
# content (keys of INITIATIVE_PATHS) plus the guild-level exemptions. Derived,
# so a guild table is declared in exactly ONE place.
GUILD_SCOPED_TABLES: frozenset[str] = INITIATIVE_SCOPED_TABLES | GUILD_LEVEL_TABLES

# Union of every table that has an explicit placement decision.
ALL_CLASSIFIED_TABLES: frozenset[str] = SHARED_TABLES | GUILD_SCOPED_TABLES


def is_guild_scoped(table_name: str) -> bool:
    """Return True if ``table_name`` moves into per-guild schemas."""
    return table_name in GUILD_SCOPED_TABLES


def is_shared(table_name: str) -> bool:
    """Return True if ``table_name`` stays in the ``public`` schema."""
    return table_name in SHARED_TABLES


def is_initiative_scoped(table_name: str) -> bool:
    """Return True if ``table_name`` carries the initiative-member RLS policies
    (vs being guild-level / structural / own-row and exempt)."""
    return table_name in INITIATIVE_SCOPED_TABLES
