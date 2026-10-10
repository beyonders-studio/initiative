"""Row-level security and grants on the shared (``public``) tables, from one
registry.

The guild schemas have had this since the squash: their policies are rendered
from ``INITIATIVE_PATHS`` and applied per schema, stamped, and held to the
catalog by ``guild_rls_test``. The shared tables did not. Their policies were
written by hand in the migrations that created each table, re-applied by
nothing and checked by nothing. This module is the same shape for ``public``.

``SHARED_TABLE_REGISTRY`` declares every shared table once: its row-security
state and policies, the table-level verbs each request-path role holds
(``Grants``; read per role by ``app.db.system_grants``), and what the platform
tiers holding a capability hold directly. ``PUBLIC_RLS`` is its row security,
with the platform read floor derived. ``render_public_rls_ddl`` turns that
into DDL; ``ensure_public_rls`` applies it at boot on the provisioning engine
(the tables' owner), after the migrations and before the guild back-fill, and
stamps the ``public`` schema's comment with the render's digest so a boot with
nothing changed does nothing.
``public_rls_test`` holds the registry to the catalog in both directions.

A migration still creates a shared table, backfills it, sets ``ENABLE`` and
``FORCE ROW LEVEL SECURITY`` and runs the ``GRANT``/``REVOKE`` — the record of
*when* access changed. Its policies come from here, for the reason guild
migrations stopped rendering theirs: a migration freezes what the registry
said the day it was written. Boot re-asserts what is registered and never
drops what is not — a policy on a shared table that this registry does not
name is reported at boot and fails the drift test, so whoever added it
registers it.

A table registered with no policy and row security forced is in the strictest
state Postgres has: a grant on it reads nothing until a policy admits a row.
That is stated here on purpose rather than implied by absence.

A policy for the platform tiers names the capability it guards
(``Capability.USERS_READ``), not the tiers: ``policy_roles`` spells them from
the capability registry, so which tier holds what is decided in one place and
the policy says what it is for.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.capabilities import Capability, roles_with_capability
from app.core.config import settings
from app.db import gucs
from app.db.authorization import GUILD_ADMIN, SETTINGS_ADMIN, SYSTEM_SESSION
from app.models.platform.user import UserRole

logger = logging.getLogger(__name__)

__all__ = [
    "PLATFORM_ROUTES",
    "PLATFORM_SUSPENDED",
    "PLATFORM_TIER_ROLES",
    "PUBLIC_RLS",
    "Grants",
    "Policy",
    "SHARED_TABLE_REGISTRY",
    "SharedTable",
    "TableRls",
    "apply_public_rls",
    "apply_public_rls_if_changed",
    "existing_public_tables",
    "platform_tier",
    "policy_name",
    "policy_roles",
    "ensure_public_rls",
    "public_rls_digest",
    "render_public_rls_ddl",
    "render_table_rls",
    "role_name",
    "unregistered_policies",
]

# --- The request context a policy reads ---------------------------------------
# Every variable is read through ``app.db.gucs``. The community whose own
# configuration this request administers: a content grant names none, since
# what it reaches is the community's work, not its settings, so the two are kept
# apart here rather than in each policy.
CONFIGURED_GID = f"COALESCE({gucs.GUILD_ID}, {gucs.SETTINGS_GUILD_ID})"
#: The reader administers the routed community. A lookup on the membership
#: row, made by the standing statement and written where a policy can read it
#: — the same leg the guild schemas' gates carry, from one definition — beside
#: the rung a live settings grant confers, which is its own axis.
ROUTED_ADMIN = f"({SYSTEM_SESSION} OR {GUILD_ADMIN} OR {SETTINGS_ADMIN})"
#: The reader changes what they administer. The membership row's admin does;
#: a settings rung reads, and writes only beside a live read_write content
#: grant — the two asks together.
ROUTED_ADMIN_WRITE = (
    f"({SYSTEM_SESSION} OR {GUILD_ADMIN} OR ({SETTINGS_ADMIN} AND {gucs.PAM_WRITE}))"
)

# --- Predicate builders -------------------------------------------------------
# Each returns the SQL of a policy predicate. ``{table}`` is replaced with the
# table's name at render time, for the correlated references.

OPEN = "true"  # the role is the rule: whoever may assume it reads every row
CLOSED = "false"
SIGNED_IN = f"{gucs.USER_ID} IS NOT NULL"


def own_row(col: str = "user_id") -> str:
    """The row belongs to the reader."""
    return f"{col} = {gucs.USER_ID}"


def guild_scoped(col: str = "guild_id") -> str:
    """The row belongs to the community this request configures."""
    return f"{col} = {CONFIGURED_GID}"


def routed_admin(col: str = "guild_id") -> str:
    """The row belongs to this request's community and the reader administers
    it — as its admin, or at the rung a live settings grant confers."""
    return f"{col} = {CONFIGURED_GID} AND {ROUTED_ADMIN}"


def routed_admin_write(col: str = "guild_id") -> str:
    """The row belongs to this request's community and the reader changes what
    they administer — as its admin, or on a settings grant beside a read_write
    content grant."""
    return f"{col} = {CONFIGURED_GID} AND {ROUTED_ADMIN_WRITE}"


def routed_or_own(guild_col: str, user_col: str) -> str:
    return f"{guild_col} = {gucs.ROUTED_GUILD_ID} OR {user_col} = {gucs.USER_ID}"


def routed_and_own(guild_col: str, user_col: str) -> str:
    return f"{guild_col} = {gucs.GUILD_ID} AND {user_col} = {gucs.USER_ID}"


def member_of_guild(col: str = "guild_id") -> str:
    """The reader is a member of the row's community, by the membership table."""
    return (
        "EXISTS (SELECT 1 FROM guild_memberships"
        f" WHERE guild_memberships.guild_id = {{table}}.{col}"
        f" AND guild_memberships.user_id = {gucs.USER_ID})"
    )


def routed_or_member(col: str = "guild_id") -> str:
    """The routed community, or one the reader belongs to (the pre-routing
    reads: a member's guild list, an invite preview, a guild image)."""
    return f"{col} = {gucs.ROUTED_GUILD_ID} OR {member_of_guild(col)}"


def routed_or_pam(col: str = "guild_id") -> str:
    """The routed community, whichever of the three named it."""
    return f"{col} = {gucs.ROUTED_GUILD_ID}"


def pam_read(col: str = "guild_id") -> str:
    """A live read grant on the row's community (the PAM leg)."""
    return f"{col} = {gucs.PAM_GUILD_ID} AND {gucs.PAM_READ}"


def billing_scoped(col: str = "guild_id") -> str:
    """The community the billing role was routed to (``SET ROLE`` + GUC)."""
    return f"{col} = {gucs.BILLING_GUILD_ID}"


def seat(col: str = "guild_id") -> str:
    """The community this request configures, and the reader holds its
    superadmin seat — by the membership row, or by a live settings grant at
    that rung, which is what ``guild_superadmin()`` asks."""
    return f"{col} = {CONFIGURED_GID} AND guild_superadmin({col}, {gucs.USER_ID})"


def seat_write(col: str = "guild_id") -> str:
    """The seat, changing what it holds: by the membership row, or lent by a
    settings grant beside a live read_write content grant."""
    return f"{seat(col)} AND ({GUILD_ADMIN} OR {gucs.PAM_WRITE})"


# Predicates one table family shares, named once.
EITHER_END = f"(user_id_low = {gucs.USER_ID}) OR (user_id_high = {gucs.USER_ID})"
OWN_DEVICE_KEY = (
    "EXISTS (SELECT 1 FROM dm_devices d"
    f" WHERE d.id = dm_one_time_keys.device_id AND d.user_id = {gucs.USER_ID})"
)
OWN_DEVICE_QUEUE = (
    "recipient_device_id IN"
    f" (SELECT dm_devices.id FROM dm_devices WHERE dm_devices.user_id = {gucs.USER_ID})"
)
#: A verification message the account writes between two of its own devices.
OWN_DEVICE_PAIR = (
    f"({own_row('user_id')}) AND (sender_device_id IN"
    f" (SELECT dm_devices.id FROM dm_devices WHERE dm_devices.user_id = {gucs.USER_ID}))"
    " AND (recipient_device_id IN"
    f" (SELECT dm_devices.id FROM dm_devices WHERE dm_devices.user_id = {gucs.USER_ID}))"
)
OWN_OR_DM_OPEN = (
    f"(user_id = {gucs.USER_ID}) OR"
    f" (({gucs.USER_ID} IS NOT NULL) AND (dm_apparent_permission(user_id) = 'open'))"
)
#: A membership is written as the service writes one, on a conversation whose
#: roster names both the writer and the member. The writer's own row, only while
#: nobody on the conversation has accepted: the one opening or proposing it.
#: Somebody else's row pending, as an invitation to anybody the writer may ask;
#: or accepted, only on a pair the writer may already message.
DM_MEMBER_WRITE = (
    f"({gucs.USER_ID} IS NOT NULL)"
    f" AND dm_roster_names(conversation_id, ARRAY[{gucs.USER_ID}, user_id]) AND ("
    f"((user_id = {gucs.USER_ID}) AND NOT dm_roster_answered(conversation_id)) OR"
    f" ((user_id <> {gucs.USER_ID}) AND ("
    "((accepted_at IS NULL) AND (dm_apparent_permission(user_id) <> 'denied')) OR"
    " ((accepted_at IS NOT NULL) AND dm_conversation_direct(conversation_id)"
    " AND (dm_apparent_permission(user_id) = 'open')))))"
)
#: An invitation is answered once, by the one it was sent to.
DM_MEMBER_ANSWER = f"({own_row('user_id')}) AND (accepted_at IS NULL)"
#: A message grant is accepted without an answer only between connected accounts.
CONNECTED_MESSAGE = (
    "(kind = 'message') AND dm_pair_connected(user_id_low, user_id_high)"
)
#: A grant is written as a request from the writer, or as the message grant a
#: connection opens, naming the writer or whoever asked for the connection.
CONTACT_GRANT_WRITE = (
    f"({EITHER_END}) AND ("
    f"((state = 'pending') AND (requested_by = {gucs.USER_ID})) OR"
    f" ((state = 'accepted') AND {CONNECTED_MESSAGE} AND ("
    f"(requested_by = {gucs.USER_ID}) OR"
    " (requested_by = dm_connection_requester(user_id_low, user_id_high)))))"
)
#: Only a request is answered.
CONTACT_GRANT_PENDING = f"({EITHER_END}) AND (state = 'pending')"
#: Nobody accepts their own request, beyond the message grant a connection opens.
CONTACT_GRANT_ANSWER = (
    f"({EITHER_END}) AND ((state <> 'accepted') OR"
    f" (requested_by <> {gucs.USER_ID}) OR ({CONNECTED_MESSAGE}))"
)
LIVE_WINDOW = (
    "(published_at IS NOT NULL) AND (published_at <= now())"
    " AND ((expires_at IS NULL) OR (expires_at > now()))"
)
CLIENT_SECTOR = "purpose = 'client' AND entity_type = 'user'"
#: A reference in the routed install's own sector: what an installed plug-in's
#: request calls somebody, and nothing any other install or purpose holds.
INSTALL_SECTOR = f"purpose = 'plugin' AND sector_guild_id = {gucs.GUILD_ID} AND sector_id = {gucs.INSTALL_ID}"
#: A reference an installed plug-in's request mints: in its own sector, live, and
#: naming a person or its own community.
INSTALL_SECTOR_MINT = (
    f"{INSTALL_SECTOR} AND retired_at IS NULL"
    f" AND (entity_type = 'user' OR (entity_type = 'guild' AND entity_id = {gucs.GUILD_ID}))"
)
MEMBER_ROLE_ONLY = f"role = '{UserRole.member.value}'"

# --- The registry ---------------------------------------------------------------

SELECT = "SELECT"
INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"
ALL = "ALL"
COMMANDS = frozenset({SELECT, INSERT, UPDATE, DELETE, ALL})
#: Every table-level DML verb, for a grant that holds them all.
DML = frozenset({SELECT, INSERT, UPDATE, DELETE})


#: The platform role a suspended account assumes whatever its tier: it holds no
#: rung while in time out. ``platform_suspended`` inherits only
#: ``platform_base_ro``, the read half of ``platform_base``, so what it reaches
#: is its own rows, read, and nothing written. Not a rung — ``users.role`` never
#: holds it — so it sits beside the ladder rather than on it.
PLATFORM_SUSPENDED = "suspended"

#: Every platform role a request may assume: one ``platform_<tier>`` per rung
#: of the ladder (``users.role``), and the time-out role.
PLATFORM_ROUTES: tuple[str, ...] = (
    *(role.value for role in UserRole),
    PLATFORM_SUSPENDED,
)


def platform_tier(tier: UserRole | str) -> str:
    """The Postgres role a platform tier's request assumes, unprefixed. ``tier``
    is a rung of the ladder or :data:`PLATFORM_SUSPENDED`."""
    return f"platform_{tier.value if isinstance(tier, UserRole) else tier}"


#: The platform ladder as policy roles, one per ``UserRole``.
PLATFORM_TIER_ROLES = frozenset(platform_tier(role) for role in UserRole)

#: The shared NOLOGIN roles the migrations create, by their unprefixed names.
SHARED_ROLES = frozenset(
    {
        "app_guild_base",
        "app_guild_base_ro",
        "app_dm_reader",
        "app_profile_reader",
        "app_superadmin",
        "plugin_install_base",
        "platform_base",
        "platform_base_ro",
    }
)

#: Roles a policy may be granted to, by their unprefixed names (see
#: :func:`role_name` for how each is spelled in the catalog).
KNOWN_ROLES = (
    frozenset({"public", "app_user", "initiative_billing"})
    | SHARED_ROLES
    | PLATFORM_TIER_ROLES
)


def role_name(role: str) -> str:
    """A cluster role as the catalog holds it, from its unprefixed name.

    The platform roles (``platform_*``) and the billing role carry
    ``settings.PLATFORM_ROLE_PREFIX`` — empty in production, per run under the
    suite, so databases sharing a cluster keep their own; the rest are fixed
    names.
    """
    prefixed = role.startswith("platform_") or role == "initiative_billing"
    return f"{settings.PLATFORM_ROLE_PREFIX}{role}" if prefixed else role


@dataclass(frozen=True)
class Policy:
    """One policy: its name in the catalog, the command it governs, the roles
    it is granted to, and its predicate. ``roles`` is either the roles
    themselves or the capability whose holders they are, in which case the
    render grants the policy to the platform tiers holding it. ``using`` is
    the row test for reading, updating and deleting; ``check`` the test on a
    written row. An UPDATE or ALL policy given only ``using`` checks the
    written row with the same predicate, which is how every such policy here
    was written."""

    name: str
    command: str
    roles: tuple[str, ...] | Capability
    using: str | None = None
    check: str | None = None
    restrictive: bool = False


@dataclass(frozen=True)
class TableRls:
    """A shared table's row security: whether it is on, whether the owner is
    bound by it too, and its policies. ``enabled`` with no policies is the
    strictest state (see the module docstring)."""

    policies: tuple[Policy, ...] = ()
    enabled: bool = True
    forced: bool = True


def policy_roles(policy: Policy) -> tuple[str, ...]:
    """The roles a policy is granted to: a capability is spelled as the
    platform tiers holding it, in name order."""
    if isinstance(policy.roles, Capability):
        return tuple(
            sorted(platform_tier(role) for role in roles_with_capability(policy.roles))
        )
    return policy.roles


#: Row security on, forced, no policy: only the system engine reaches the rows.
FORCED_NO_POLICY = TableRls()
#: No row security at all: the table is governed by grants alone.
NO_RLS = TableRls(enabled=False, forced=False)

Verbs = frozenset[str] | None


@dataclass(frozen=True)
class Grants:
    """The table-level verbs each request-path role holds on a shared table,
    ``None`` for nothing. One field per role, named as the catalog names it.

    * ``app_admin`` — the system engine (BYPASSRLS trusted-batch actor). Its
      security boundary *is* this grant set: a new shared table gives it
      nothing until a decision here says otherwise.
    * ``app_user`` — the bare login serving the pre-routing / unauthenticated
      surface (RLS-enforced, no ``SET ROLE`` yet).
    * ``app_guild_base`` — the floor every ``guild_<id>`` role inherits, so the
      reach of a routed community session into ``public``. Its read-only twin
      ``app_guild_base_ro`` is held to it by ``guild_base_ro_parity_test``.
    * ``platform_base`` — the floor every ``platform_<tier>`` role inherits,
      the reach of an unrouted, authenticated request.
    * ``app_superadmin`` — the seat floor, which only ``guild_<id>_superadmin``
      inherits.
    * ``plugin_install_base`` — the install floor, which only ``guild_<id>_plugin``
      inherits: an installed plug-in's reach into ``public``.

    The two floors are granted the other way round from the rest: the schema
    default gives each full DML on a new table, and the migration that adds
    the table takes back what it does not want. The seat and install floors
    take no default privileges at all. Column-scoped grants live in the column
    ACL, not the table ACL, and are asserted separately
    (``security_invariants_test``, ``install_standing_test``).
    """

    app_admin: Verbs = None
    app_user: Verbs = None
    app_guild_base: Verbs = None
    platform_base: Verbs = None
    app_superadmin: Verbs = None
    plugin_install_base: Verbs = None


@dataclass(frozen=True)
class SharedTable:
    """One shared table: its row security, what each request-path role holds
    on it, and what the ``platform_<tier>`` roles holding a capability hold
    directly rather than through ``platform_base`` (spelled as tiers by
    ``system_grants.tier_table_grants``)."""

    rls: TableRls
    grants: Grants = Grants()
    tiers: dict[Capability, frozenset[str]] = field(default_factory=dict)


#: Every shared (``public``) table, with why it is shared, its row security
#: (whose policy names are the ones the migrations gave them) and its grants.
#: ``app.db.tenancy.SHARED_TABLES`` is its keys that a model maps. Migrations remain the record of *when* a grant changed (they run the
#: ``GRANT``/``REVOKE``); this is the current truth, held to the live catalog
#: by ``security_invariants_test`` and ``public_rls_test``.
SHARED_TABLE_REGISTRY: dict[str, SharedTable] = {
    # Time-bound access to a guild: cross-guild by nature (request, approve, scoped).
    "access_grants": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "access_grants_admin", SELECT, Capability.ACCESS_APPROVE, using=OPEN
                ),
                Policy(
                    "access_grants_self", ALL, ("public",), using=own_row("user_id")
                ),
            ),
        ),
        grants=Grants(
            app_admin=DML,
            app_user=frozenset({SELECT}),
            # 0146 moved every write to the system engine for all request-path roles
            # (test_access_grants_are_writable_only_by_the_system_engine). SELECT is
            # narrowed to the reader's own grants by access_grants_self.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
        ),
    ),
    # An announcement's pictures. Deployment-wide, like the announcement.
    "announcement_images": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "announcement_image_read",
                    SELECT,
                    ("platform_base",),
                    using=OPEN,
                ),
                # Stored, re-stamped and pruned by the tier that writes
                # announcements.
                Policy(
                    "announcement_images_manage",
                    ALL,
                    Capability.ANNOUNCEMENTS_MANAGE,
                    using=OPEN,
                ),
            ),
        ),
        grants=Grants(
            # The authoring tier stores and touches the pictures (0365); the system
            # engine's janitor reads their age and prunes the ones no announcement
            # names (0366). The request path reads them under its own role (a
            # signed-in account may fetch any of them).
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT}),
        ),
        tiers={
            Capability.ANNOUNCEMENTS_MANAGE: frozenset({INSERT, UPDATE, DELETE}),
        },
    ),
    # What each person has done with an announcement: kept per account, not per
    # membership.
    "announcement_reads": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "announcement_read_self",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "announcement_read_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "announcement_read_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # Receipts are written by the reader under their own role. The system
            # engine only ever removes them, when the announcement they name goes.
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT, INSERT, UPDATE}),
        ),
    ),
    # Deployment-wide notices. One announcement is shown in every guild and read by an
    # account, not by a membership, so it has no guild to live in.
    "announcements": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "announcement_live_read",
                    SELECT,
                    ("platform_base",),
                    using=LIVE_WINDOW,
                ),
                # Drafts, scheduled and expired rows included: the tier that writes
                # announcements reads and changes every one.
                Policy(
                    "announcements_manage",
                    ALL,
                    Capability.ANNOUNCEMENTS_MANAGE,
                    using=OPEN,
                ),
            ),
        ),
        grants=Grants(
            # Authoring runs under the tier holding announcements.manage (0365); the
            # system engine only reads every row's sections, for the orphan-picture
            # janitor (0366).
            app_admin=frozenset({SELECT}),
            # An announcement is shown to a signed-in account, so nothing about it is
            # read before routing.
            app_user=None,
            # 0360: announcements, their receipts and their pictures are read under a
            # platform tier.
            app_guild_base=None,
            platform_base=frozenset({SELECT}),
        ),
        # Announcements and their pictures are written under the tier that manages
        # them (announcements_manage, announcement_images_manage; migration 0365).
        # Every tier reads them through its floor.
        tiers={
            Capability.ANNOUNCEMENTS_MANAGE: frozenset({INSERT, UPDATE, DELETE}),
        },
    ),
    # Platform-wide configuration (OIDC, SMTP, branding).
    "app_settings": SharedTable(
        rls=TableRls(
            policies=(
                Policy("app_settings_owner", ALL, Capability.CONFIG_MANAGE, using=OPEN),
                Policy("app_settings_read", SELECT, ("public",), using=OPEN),
            ),
        ),
        grants=Grants(
            # singleton config: seeded + updated, never deleted
            app_admin=frozenset({SELECT, INSERT, UPDATE}),
            app_user=frozenset({SELECT}),
            # Deployment settings are read from inside a community as from anywhere
            # (app_settings_read, TO public); writes are the owner's, under RLS.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
            # Deployment settings are read from inside a community as from anywhere
            # (app_settings_read, TO public): a notification an install's write sends
            # asks whether the deployment sends mail (migration 20260924_0386).
            plugin_install_base=frozenset({SELECT}),
        ),
        # Deployment configuration is written under the tier that manages it
        # (app_settings_owner); every request role reads it through its floor.
        tiers={
            Capability.CONFIG_MANAGE: frozenset({INSERT, UPDATE, DELETE}),
        },
    ),
    # The billing write boundary (the external billing service, the initiative_billing
    # role): an idempotency claim and append-only audit, with a weak guild reference.
    "billing_event_log": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "billing_event_insert",
                    INSERT,
                    ("initiative_billing",),
                    check=billing_scoped("guild_id"),
                ),
            ),
        ),
        grants=Grants(
            # billing boundary: writes happen ONLY under the dedicated (SET ROLE)
            # initiative_billing role, never the system engine. app_admin keeps
            # read-only visibility into the append-only evidence, and may prune
            # expired jtis (janitor); neither may mutate the event log.
            app_admin=frozenset({SELECT}),
            # billing tables are reached only via SET ROLE initiative_billing — the
            # bare login role holds nothing (fail-closed, like the guild schemas)
            app_user=None,
            # 0134: the billing boundary took both floors back; only the SET ROLE
            # initiative_billing role reaches these.
            app_guild_base=None,
        ),
    ),
    # Who an account has agreed to hear from. Per-account and cross-guild, like
    # ``user_dm_settings``.
    "contact_grants": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "contact_grants_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=EITHER_END,
                ),
                Policy(
                    "contact_grants_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=CONTACT_GRANT_WRITE,
                ),
                Policy(
                    "contact_grants_self_select",
                    SELECT,
                    ("platform_base",),
                    using=EITHER_END,
                ),
                Policy(
                    "contact_grants_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=CONTACT_GRANT_PENDING,
                    check=CONTACT_GRANT_ANSWER,
                ),
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            ),
        ),
        grants=Grants(
            app_admin=frozenset({SELECT, DELETE}),
            # UPDATE is column-scoped to state and responded_at (migration
            # 0411), so it lives in the column ACL, not here.
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # The demo deployment's links, copies, visitor accounts and left addresses
    # (``DEMO_MODE``): written when a link is made or opened, when a visitor
    # leaves an address, and by the pool loop, and read for an account's own
    # copy and for the sales plug-in, all on the system engine. No request role
    # reaches them.
    "demo_accounts": SharedTable(rls=FORCED_NO_POLICY, grants=Grants(app_admin=DML)),
    "demo_leads": SharedTable(rls=FORCED_NO_POLICY, grants=Grants(app_admin=DML)),
    "demo_links": SharedTable(rls=FORCED_NO_POLICY, grants=Grants(app_admin=DML)),
    "demo_sandboxes": SharedTable(rls=FORCED_NO_POLICY, grants=Grants(app_admin=DML)),
    # Part of the direct-message transport, per-account and cross-guild (see
    # ``dm_devices``).
    "dm_conversation_members": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "dm_conversation_members_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "dm_conversation_members_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=DM_MEMBER_WRITE,
                ),
                Policy(
                    "dm_conversation_members_self_select",
                    SELECT,
                    ("platform_base",),
                    using="dm_on_roster(conversation_id)",
                ),
                Policy(
                    "dm_conversation_members_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=DM_MEMBER_ANSWER,
                    check=own_row("user_id"),
                ),
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            ),
        ),
        grants=Grants(
            # The transport: cleared and swept as dm_devices is, never written.
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # Part of the direct-message transport, per-account and cross-guild (see
    # ``dm_devices``).
    "dm_conversations": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "dm_conversations_self_delete",
                    DELETE,
                    ("platform_base",),
                    using="dm_in_conversation(id)",
                ),
                Policy(
                    "dm_conversations_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=SIGNED_IN,
                ),
                Policy(
                    "dm_conversations_self_select",
                    SELECT,
                    ("platform_base",),
                    using="dm_on_roster(id)",
                ),
                # A member's one write to the row: releasing the roster's name.
                Policy(
                    "dm_conversations_self_update",
                    UPDATE,
                    ("platform_base",),
                    using="dm_in_conversation(id)",
                    check="dm_in_conversation(id) AND (roster_key IS NULL)",
                ),
                # ``dm_conversation_direct`` and ``dm_roster_names`` read the
                # kind and the roster (0411).
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            ),
        ),
        grants=Grants(
            # The transport: cleared and swept as dm_devices is, never written.
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # The direct-message transport (with ``dm_one_time_keys``, ``dm_conversations``,
    # ``dm_conversation_members`` and ``dm_queue``): a directory of public keys, a
    # roster of who is talking to whom, and ciphertext waiting to be collected.
    # Per-account and cross-guild, and none of it holds anything a reader could open.
    "dm_devices": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "dm_devices_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "dm_devices_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "dm_devices_self_select",
                    SELECT,
                    ("platform_base",),
                    using=OWN_OR_DM_OPEN,
                ),
                Policy(
                    "dm_devices_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            ),
        ),
        grants=Grants(
            # The transport. The system engine clears an erased account off all five
            # and sweeps devices that have stopped syncing; it writes none of them.
            # Nothing about a direct message is ever created by anything but the
            # account's own session.
            app_admin=frozenset({SELECT, DELETE}),
            # Same: the transport is reached on the authenticated platform-tier
            # path, never before a session is routed.
            app_user=None,
            # UPDATE is column-scoped to last_seen_at, session_id and signature,
            # so it lives in the column ACL, not here; so is the system engine's
            # UPDATE of session_id, which follows a key store across renewals.
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # Part of the direct-message transport, per-account and cross-guild (see
    # ``dm_devices``).
    "dm_one_time_keys": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "dm_one_time_keys_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=OWN_DEVICE_KEY,
                ),
                Policy(
                    "dm_one_time_keys_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=OWN_DEVICE_KEY,
                ),
                Policy(
                    "dm_one_time_keys_self_select",
                    SELECT,
                    ("platform_base",),
                    using=OWN_DEVICE_KEY,
                ),
                Policy("dm_reader_keys", ALL, ("app_dm_reader",), using=OPEN),
            ),
        ),
        grants=Grants(
            # The transport: cleared and swept as dm_devices is, never written.
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # Part of the direct-message transport, per-account and cross-guild (see
    # ``dm_devices``).
    "dm_queue": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "dm_queue_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=OWN_DEVICE_QUEUE,
                ),
                Policy(
                    "dm_queue_self_insert",
                    INSERT,
                    ("platform_base",),
                    check="dm_in_conversation(conversation_id) AND dm_device_in_conversation(recipient_device_id, conversation_id)",
                ),
                Policy(
                    "dm_queue_self_select",
                    SELECT,
                    ("platform_base",),
                    using=OWN_DEVICE_QUEUE,
                ),
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            ),
        ),
        grants=Grants(
            # The transport: cleared and swept as dm_devices is, never written.
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # The verification relay between one account's own devices: public keys and MACs,
    # deleted when collected or ten minutes after writing.
    "dm_verification_messages": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "dm_verification_messages_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "dm_verification_messages_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=OWN_DEVICE_PAIR,
                ),
                Policy(
                    "dm_verification_messages_self_select",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # The verification relay between one account's own devices: its own
            # session writes, reads and deletes it, and nothing else touches it.
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # (provider, subject) -> user links. One user's identities span guilds.
    "federated_identities": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "federated_identities_self",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # identity linking — resolved/created at login (pre-auth, by subject);
            # link/unlink go through the system engine only
            app_admin=DML,
            # own-row identity links are read on the authenticated (platform_<tier>)
            # path, not the bare pre-routing role
            app_user=None,
            platform_base=frozenset({SELECT}),
        ),
    ),
    # The operator-set half of a guild (caps, plan label, sign-in entitlement), split
    # off ``guilds`` so identity and administration carry different grants. Shared, like
    # the guild row it hangs off.
    "guild_administration": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "billing_guild_administration_select",
                    SELECT,
                    ("initiative_billing",),
                    using=billing_scoped("guild_id"),
                ),
                Policy(
                    "billing_guild_administration_update",
                    UPDATE,
                    ("initiative_billing",),
                    using=billing_scoped("guild_id"),
                ),
                Policy(
                    "guild_administration_pam_read",
                    SELECT,
                    ("public",),
                    using=pam_read("guild_id"),
                ),
                # Before routing and on the platform path: the communities the
                # reader belongs to.
                Policy(
                    "guild_administration_select",
                    SELECT,
                    (
                        "app_user",
                        "platform_base",
                    ),
                    using=routed_or_member("guild_id"),
                ),
                # A routed request reads its own community's row.
                Policy(
                    "guild_administration_select_routed",
                    SELECT,
                    ("app_guild_base",),
                    using=routed_or_pam("guild_id"),
                ),
                # The operator's list of every community reads each one's caps.
                Policy(
                    "guild_administration_guilds_manage_read",
                    SELECT,
                    Capability.COMMUNITIES_MANAGE,
                    using=OPEN,
                ),
                # A settings rung routed read-only reads the community it
                # administers.
                Policy(
                    "guild_administration_settings_read",
                    SELECT,
                    ("app_guild_base_ro",),
                    using=routed_admin("guild_id"),
                ),
            ),
        ),
        grants=Grants(
            # The operator-set caps / plan label / sign-in entitlement. The system engine
            # is the only writer on the request path: the platform Guilds dashboard runs
            # on SystemSessionDep, and provisioning creates the row with the guild. (The
            # verified billing path writes its three columns under its own role, which is
            # granted per column in migration 0178 and so is not listed here.) DELETE
            # rides the FK cascade off ``guilds``, but the guild-deletion path removes it
            # explicitly too.
            app_admin=DML,
            # Read-only for every request-path role, this one included — no login role
            # writes a guild's caps or its sign-in entitlement. RLS narrows the rows to
            # the caller's own guilds (plus a live PAM grant).
            app_user=frozenset({SELECT}),
            # 0179: read-only for every request-path role; a community reads its own
            # caps and plan label (guild_administration_select_routed).
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
        ),
    ),
    # A community's sign-in requirement, read before routing by the gate.
    "guild_auth_policies": SharedTable(
        rls=TableRls(
            policies=(
                # The gate reads a community's rule before any routing exists.
                Policy("guild_auth_policies_read", SELECT, ("app_user",), using=OPEN),
                # The platform path reads the rules of the communities the reader
                # belongs to.
                Policy(
                    "guild_auth_policies_member_read",
                    SELECT,
                    ("platform_base",),
                    using=member_of_guild("guild_id"),
                ),
                # A routed request, the seat's included, reads its own community's
                # rule.
                Policy(
                    "guild_auth_policies_routed_read",
                    SELECT,
                    (
                        "app_guild_base",
                        "app_guild_base_ro",
                        "app_superadmin",
                    ),
                    using=routed_or_pam("guild_id"),
                ),
                Policy(
                    "guild_auth_policies_seat_delete",
                    DELETE,
                    ("public",),
                    using=seat_write("guild_id"),
                ),
                Policy(
                    "guild_auth_policies_seat_insert",
                    INSERT,
                    ("public",),
                    check=seat_write("guild_id"),
                ),
                Policy(
                    "guild_auth_policies_seat_update",
                    UPDATE,
                    ("public",),
                    using=seat_write("guild_id"),
                ),
            ),
        ),
        grants=Grants(
            # per-guild sign-in requirement — written via the guild-admin endpoint
            # (provider validation happens on the system engine)
            app_admin=DML,
            # the guild-access gate reads the policy on the bare login role, pre-routing
            app_user=frozenset({SELECT}),
            # 0147 granted SELECT: the routed community's gate reads its requirement
            # (guild_auth_policies_routed_read, 0360). 0297 added the three writes and
            # 0349 moved them to app_superadmin, the floor only a seat route inherits.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
            app_superadmin=DML,
        ),
    ),
    # The pictures a guild is known by — its icon, and the two renditions of its banner.
    # Identity, like the name and description they sit beside, and read by people
    # browsing the directory, who hold no role in any guild schema.
    "guild_images": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "guild_image_member_read",
                    SELECT,
                    (
                        "app_user",
                        "platform_base",
                    ),
                    using=routed_or_member("guild_id"),
                ),
                Policy(
                    "guild_image_member_read_routed",
                    SELECT,
                    ("app_guild_base",),
                    using=routed_or_pam("guild_id"),
                ),
            ),
        ),
        grants=Grants(
            # Guild icons and banners: the whole table is the system engine's, because
            # the one thing it has to answer — may this caller see this guild's icon or
            # card rendition — depends on a listing the caller may hold no role to read.
            # Serving reads; a guild admin replacing a picture inserts (after the
            # endpoint has checked their role) and deletes the one it replaces.
            app_admin=frozenset({SELECT, INSERT, DELETE}),
            # No TABLE grant: the bytes are the system engine's, and the endpoint that
            # serves them decides who may see which variant. The request path holds a
            # column-scoped SELECT on (guild_id, variant, sha256) instead — enough to
            # name a member's own guild images in their guild list, never enough to
            # read one. Column grants live in pg_attribute, not relacl, so they are
            # asserted separately (security_invariants_test).
            app_user=None,
            # 0200: no table grant; the routed path holds a column-scoped SELECT on
            # (guild_id, variant, sha256), asserted in security_invariants_test, over
            # the routed community's rows (guild_image_member_read_routed).
            app_guild_base=None,
        ),
    ),
    # Looked up by code before the user is a member.
    # An invite is the administrator's: issued, listed and withdrawn on a
    # routed request by the community's admin or a live settings grant at
    # either rung, so the policies name the guild floor. Redeeming, previewing
    # and scrubbing one by code run on the system engine, which these do not
    # bind.
    "guild_invites": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "guild_delete",
                    DELETE,
                    ("app_guild_base",),
                    using=routed_admin_write("guild_id"),
                ),
                Policy(
                    "guild_insert",
                    INSERT,
                    ("app_guild_base",),
                    check=routed_admin_write("guild_id"),
                ),
                Policy(
                    "guild_select",
                    SELECT,
                    (
                        "app_guild_base",
                        "app_guild_base_ro",
                    ),
                    using=routed_admin("guild_id"),
                ),
            ),
        ),
        grants=Grants(
            # invite redemption reads/creates/updates; row removal rides the FK cascade
            app_admin=frozenset({SELECT, INSERT, UPDATE}),
            # Previewed and redeemed by code on the system engine; listed, issued and
            # withdrawn on a routed request (app_guild_base, below).
            app_user=None,
            # Listed, issued and withdrawn on a routed request. The three guild_*
            # policies admit an administrator of the invite's community — by the
            # membership row, or by a live settings grant at either rung. 0357 took
            # UPDATE back: an invite is changed only by redemption and erasure, on the
            # system engine.
            app_guild_base=frozenset({SELECT, INSERT, DELETE}),
            # 0357: an invite is the community's, reached on a routed request or the
            # system engine.
            platform_base=None,
        ),
    ),
    # The tenancy roster: read before a request is routed.
    "guild_memberships": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "billing_membership_select",
                    SELECT,
                    ("initiative_billing",),
                    using=billing_scoped("guild_id"),
                ),
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
                Policy(
                    "guild_membership_projection_read",
                    SELECT,
                    ("app_profile_reader",),
                    using=routed_or_pam("guild_id"),
                ),
                Policy(
                    "guild_memberships_delete",
                    DELETE,
                    ("public",),
                    using=routed_and_own("guild_id", "user_id"),
                ),
                # The routed community's admin removes one of its members.
                Policy(
                    "guild_memberships_admin_delete",
                    DELETE,
                    ("app_guild_base",),
                    using=routed_admin_write("guild_id"),
                ),
                # The reader's own rows and the routed community's, for the bare
                # login, the platform floor, and the roles that own the member
                # projections, the direct-message rules and the billing path.
                Policy(
                    "guild_memberships_select",
                    SELECT,
                    (
                        "app_dm_reader",
                        "app_profile_reader",
                        "app_user",
                        "initiative_billing",
                        "platform_base",
                    ),
                    using=routed_or_own("guild_id", "user_id"),
                ),
                # A routed request reads its own community's roster.
                Policy(
                    "guild_memberships_select_routed",
                    SELECT,
                    (
                        "app_guild_base",
                        "app_guild_base_ro",
                    ),
                    using=routed_or_pam("guild_id"),
                ),
                Policy(
                    "guild_memberships_update",
                    UPDATE,
                    ("public",),
                    using=own_row("user_id"),
                ),
                # A member token's standing reads that the member it acts for still
                # belongs to the community it is routed into (its column grant is
                # guild_id and user_id alone; migration 20260924_0385).
                Policy(
                    "install_reads_its_member",
                    SELECT,
                    ("plugin_install_base",),
                    using=f"guild_id = {gucs.GUILD_ID} AND {own_row('user_id')}",
                ),
            ),
        ),
        grants=Grants(
            app_admin=DML,
            app_user=frozenset({SELECT}),
            # 0145 revoked UPDATE — ``role`` is the system engine's column — and 0266
            # re-granted it on ``position`` alone, as a column grant; 0438 added
            # ``display_name``, the member's own name here. 0354 took INSERT
            # back: joining is the system engine's (invite redemption, a community
            # join, sign-in sync). What remains at the table level is leaving (DELETE
            # of the reader's own row) and reading the routed community's roster
            # (guild_memberships_select_routed).
            app_guild_base=frozenset({SELECT, DELETE}),
            # 0357 took DELETE back: leaving routes into the community first, so the
            # row goes on the guild floor.
            platform_base=frozenset({SELECT}),
            # No TABLE grant: a column-scoped SELECT on (guild_id, user_id), which a
            # member token's standing reads for the member's own row in the routed
            # community (install_reads_its_member; migration 20260924_0385).
            plugin_install_base=None,
        ),
    ),
    # Which of the platform's providers a community signs in through, and the tenant it
    # narrows one to. Read at sign-in on the system engine.
    "guild_provider_connections": SharedTable(
        rls=TableRls(
            policies=(
                # The gate reads a community's connections before any routing
                # exists.
                Policy(
                    "guild_provider_connections_read", SELECT, ("app_user",), using=OPEN
                ),
                Policy(
                    "guild_provider_connections_member_read",
                    SELECT,
                    ("platform_base",),
                    using=member_of_guild("guild_id"),
                ),
                # A routed request reads its own community's connections.
                Policy(
                    "guild_provider_connections_routed_read",
                    SELECT,
                    (
                        "app_guild_base",
                        "app_guild_base_ro",
                    ),
                    using=routed_or_pam("guild_id"),
                ),
            ),
        ),
        grants=Grants(
            # which of the platform's providers a community signs in through — read at
            # login and written by the connection CRUD, both on the system engine
            app_admin=DML,
            # the gate reads the narrowing here on every request, so the rule it
            # applies is the one in force now; a policy scopes a row to its own guild
            app_user=frozenset({SELECT}),
            # 0308: the routed community's gate reads its connections
            # (guild_provider_connections_routed_read, 0360); the writes are the
            # system engine's.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
        ),
    ),
    # The tenancy roster: read before a request is routed.
    "guilds": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "billing_guild_select",
                    SELECT,
                    ("initiative_billing",),
                    using=billing_scoped("id"),
                ),
                Policy(
                    "billing_guild_update",
                    UPDATE,
                    ("initiative_billing",),
                    using=billing_scoped("id"),
                ),
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
                # Before routing and on the platform path: the communities the
                # reader belongs to.
                Policy(
                    "guild_select",
                    SELECT,
                    (
                        "app_user",
                        "platform_base",
                    ),
                    using=routed_or_member("id"),
                ),
                # A routed request, the seat's and a read-only one's included,
                # reads its own community.
                Policy(
                    "guild_select_routed",
                    SELECT,
                    (
                        "app_guild_base",
                        "app_guild_base_ro",
                        "app_superadmin",
                    ),
                    using=routed_or_pam("id"),
                ),
                Policy(
                    "guild_update", UPDATE, ("public",), using=routed_admin_write("id")
                ),
                # The operator's list of every community.
                Policy(
                    "guilds_manage_read",
                    SELECT,
                    Capability.COMMUNITIES_MANAGE,
                    using=OPEN,
                ),
                Policy("guilds_pam_read", SELECT, ("public",), using=pam_read("id")),
                # A settings rung routed read-only reads the community it
                # administers.
                Policy(
                    "guild_settings_read",
                    SELECT,
                    ("app_guild_base_ro",),
                    using=routed_admin("id"),
                ),
                # An installed plug-in's standing reads the status of the community it
                # is routed into (its column grant is id and status alone).
                Policy(
                    "install_reads_its_guild",
                    SELECT,
                    ("plugin_install_base",),
                    using=f"id = {gucs.GUILD_ID}",
                ),
            ),
        ),
        grants=Grants(
            app_admin=DML,
            app_user=frozenset({SELECT}),
            # 0138 revoked INSERT and UPDATE at the table level. UPDATE survives as
            # column grants on the identity columns a community's admin edits (name,
            # description, banner, categories, is_community, has_adult_content,
            # location, updated_at — 0138, 0196, 0200, 0456).
            # guild_select_routed narrows SELECT to the routed community (0360). 0357
            # took DELETE back: creating, deleting and purging a community run on the
            # system engine.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
            # No TABLE grant: a community's name, its icon and its lifecycle status are
            # not the seat's. It holds a column-scoped UPDATE on the six switches its
            # own routes set — what may be used to reach the community, and what its
            # notifications may leave carrying (migration 20260923_0355). Column grants
            # live in pg_attribute, not relacl, so they are asserted separately
            # (security_invariants_test). SELECT comes from app_guild_base_ro, which
            # guild_<id>_superadmin also inherits.
            app_superadmin=None,
            # No TABLE grant: a column-scoped SELECT on (id, status), which the
            # install standing statement reads for the routed community alone
            # (install_reads_its_guild; migration 20260924_0379). Column grants live in
            # pg_attribute, not relacl, so they are asserted separately
            # (install_standing_test).
            plugin_install_base=None,
        ),
    ),
    # What outside parties — a payment processor, an installed plug-in — call a user or
    # a guild. One per purpose, so no two parties hold the same value for the same
    # entity. Cross-guild and pre-routing, like the accounts and guilds it names.
    "identity_refs": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "identity_refs_client_sector",
                    SELECT,
                    ("app_user",),
                    using=CLIENT_SECTOR,
                ),
                # An installed plug-in's request reads what its install calls people and
                # its community, and mints what it has not been told yet — in its
                # own sector only (plugin_refs.install_refs; migration 20260924_0383).
                Policy(
                    "install_reads_its_sector",
                    SELECT,
                    ("plugin_install_base",),
                    using=INSTALL_SECTOR,
                ),
                Policy(
                    "install_mints_in_its_sector",
                    INSERT,
                    ("plugin_install_base",),
                    check=INSTALL_SECTOR_MINT,
                ),
            ),
        ),
        grants=Grants(
            # Minted on first use, replaced by a re-issue, swept once the replaced
            # value stops resolving, and removed when the entity is erased.
            app_admin=DML,
            # Minted on the system engine, behind the surfaces that hand a reference to
            # an outside party. SELECT covers the table and one policy admits the rows:
            # ``purpose = 'client'``, the sector an account's own access token names it
            # by and every authenticated request resolves (migration 0267).
            app_user=frozenset({SELECT}),
            # 0338: the credential is the system engine's from creation to deletion.
            # 0249: minted and resolved on the system engine and the bare login role.
            app_guild_base=None,
            # Its own install's sector, read and minted on the request's session: what
            # the install calls the people and the community a request or response
            # names (install_reads_its_sector / install_mints_in_its_sector; migration
            # 20260924_0383).
            plugin_install_base=frozenset({SELECT, INSERT}),
        ),
    ),
    # What an account agreed to when it was created. A deployment's terms are the
    # platform's, not any one community's, so the record of accepting them belongs
    # beside the account rather than in a schema.
    "legal_acceptances": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "legal_acceptances_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "legal_acceptances_self_read",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # Consent to the deployment's terms. Registration runs on the system
            # engine, so the acceptance it records is written here; SELECT is for the
            # same path asking whether an account already has one. Nothing updates a
            # consent record, and the FK cascade off ``users`` is what removes it, so
            # neither UPDATE nor DELETE is granted.
            app_admin=frozenset({SELECT, INSERT}),
            # Read and written by an account about itself, after its session is
            # routed. Nobody asks what somebody agreed to before then.
            app_user=None,
            platform_base=frozenset({SELECT, INSERT}),
        ),
    ),
    # The marketplace catalog's versions, platform-wide like the listings.
    "marketplace_listing_versions": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "marketplace_listing_versions_read",
                    SELECT,
                    (
                        "app_guild_base",
                        "platform_base",
                    ),
                    using=OPEN,
                ),
            ),
        ),
        grants=Grants(
            # Written with marketplace_listings, by the same seeding and refresh.
            app_admin=DML,
            # Browsed with marketplace_listings (0164).
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
        ),
    ),
    # The marketplace catalog: what is installable, platform-wide. Holds no guild_id by
    # design — the catalog never records who installed what.
    "marketplace_listings": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "marketplace_listings_read",
                    SELECT,
                    (
                        "app_guild_base",
                        "platform_base",
                    ),
                    using=OPEN,
                ),
            ),
        ),
        grants=Grants(
            # Marketplace catalog: the system engine is the only writer — boot seeding of
            # the shipped listings, and later the registry refresh job. DELETE is there
            # for versions a re-seed supersedes; a withdrawn *listing* is flipped to
            # available=false rather than removed, so installs keep their provenance.
            app_admin=DML,
            # The catalog is read under a platform tier or a guild role, never by the
            # bare pre-routing login role — browsing the marketplace requires a session.
            app_user=None,
            # 0164: the catalog is browsed under a guild role or a platform tier.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
        ),
    ),
    # Registry client state, no guild (see ``marketplace_tuf_metadata``).
    "marketplace_media": SharedTable(
        rls=TableRls(
            policies=(
                # Served before a session is routed, to anyone holding the digest.
                Policy(
                    "marketplace_media_read",
                    SELECT,
                    ("app_user",),
                    using=OPEN,
                ),
            ),
        ),
        grants=Grants(
            # Mirrored listing artwork: written by the refresh job; DELETE prunes bytes
            # no listing references any more.
            app_admin=frozenset({SELECT, INSERT, DELETE}),
            # Mirrored listing artwork stands in for the static image files this build
            # ships, so it is served exactly as they are: to anyone holding the digest,
            # before a session is routed. Bytes only, addressed by their own hash.
            app_user=frozenset({SELECT}),
            # 0360: served on the bare login role alone.
            app_guild_base=None,
            # 0360: served on the bare login role alone.
            platform_base=None,
        ),
    ),
    # The operator's AI connections (platform configuration mode).
    "platform_ai_connections": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "platform_ai_connections_owner",
                    ALL,
                    Capability.CONFIG_MANAGE,
                    using=OPEN,
                ),
            ),
        ),
        grants=Grants(
            # operator AI connections: the request path never queries this directly —
            # the resolve step reads it via an in-process cache loaded on the system
            # engine (SELECT), and the secret-key rotation re-encrypts its key column on
            # the system engine (UPDATE). CRUD writes run under the tiers holding
            # config.manage (its tiers), not the system engine.
            app_admin=frozenset({SELECT, UPDATE}),
            # operator AI connections are owner-managed + system-engine-read only; the
            # bare pre-routing login role never touches them
            app_user=None,
            # Owner-managed under RLS on the platform path; read by the system engine.
            app_guild_base=None,
        ),
        # The operator's AI connections, managed under the same tier
        # (platform_ai_connections_owner, migration 0155).
        tiers={
            Capability.CONFIG_MANAGE: DML,
        },
    ),
    # The arrangement ``guild_provider_connections`` makes, answered once for a
    # community that has not made one. Read by the gate on the request path.
    "platform_provider_defaults": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "platform_provider_defaults_read", SELECT, ("public",), using=OPEN
                ),
            ),
        ),
        grants=Grants(
            # Read at login and written by the connection CRUD, as
            # guild_provider_connections is.
            app_admin=DML,
            app_user=frozenset({SELECT}),
            # Read by the routed community's gate beside its connections.
            app_guild_base=frozenset({SELECT}),
            platform_base=frozenset({SELECT}),
        ),
    ),
    # Who one account has starred on My Contacts. Personal, cross-guild and
    # one-directional: the list is the holder's, and it may name people they share no
    # guild with.
    "profile_favorites": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "profile_favorites_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "profile_favorites_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "profile_favorites_self_read",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # My Contacts stars. The request path owns every write under its own-row
            # policies; the system engine reads and deletes only for erasure, which has
            # to clear an anonymized account off other people's lists too — the row
            # survives the husk, so the FK cascade never fires for it.
            app_admin=frozenset({SELECT, DELETE}),
            # A contacts list belongs to a signed-in account, and the bare pre-routing
            # login role serves nobody in particular.
            app_user=None,
            # Platform-tier path only: every policy on these is TO platform_base, and
            # the migration that added each took the schema default back.
            app_guild_base=None,
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # The picture on a user's profile. Public-plane identity like the row it hangs off:
    # one user spans guilds, and the bytes are served to anyone holding the URL.
    "user_avatars": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "user_avatar_public_read",
                    SELECT,
                    (
                        "app_user",
                        "platform_base",
                    ),
                    using=OPEN,
                ),
                Policy(
                    "user_avatar_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_avatar_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "user_avatar_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # Profile pictures. The system engine reads them to serve the bytes before a
            # session exists, writes them on the backfill, and DELETEs on the moderation
            # and anonymization paths — both of which act on someone else's row and so
            # cannot run under the own-row request-path policies.
            app_admin=DML,
            # A name and a face are public information here: any role may read any
            # avatar. The bare login role reads because the serve endpoint answers
            # before routing; a picture is changed under a platform tier or on the
            # system engine.
            app_user=frozenset({SELECT}),
            # 0360: served on the bare login role and changed under a platform tier; a
            # routed payload names the picture by its serving URL.
            app_guild_base=None,
            platform_base=DML,
        ),
    ),
    # What an account allows to be kept in a browser. Per-account and cross-guild: the
    # question is about the deployment, not about any one community.
    "user_cookie_consent": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "user_cookie_consent_self_insert_{prefix}platform_base",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "user_cookie_consent_self_select_{prefix}platform_base",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_cookie_consent_self_update_{prefix}platform_base",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # An account's own payload is built on the system engine during
            # registration, which is the SELECT. DELETE is for erasure sweeps; the FK
            # cascade off ``users`` covers the ordinary case. The answer itself is
            # written on the request path by the account holder, so no INSERT or
            # UPDATE.
            app_admin=frozenset({SELECT, DELETE}),
            # Read and written by an account about itself, after its session is routed.
            # A visitor who has not signed in keeps their answer in their own browser
            # and asks the server for nothing.
            app_user=None,
            # 0360: an account's answer is read and recorded under a platform tier.
            app_guild_base=None,
            platform_base=DML,
        ),
    ),
    # What one account may dress its profile in beyond what ships with the app. Personal
    # and cross-guild, like the row it hangs off.
    "user_decorations": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "user_decoration_self_read",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # A person's decoration library. Grants are issued, never self-served: a
            # pack install writes the rows and an uninstall removes them, both on the
            # system engine. The request path only reads its own (SELECT), so every
            # write verb lives here.
            app_admin=frozenset({SELECT, INSERT, DELETE}),
            # A library belongs to a signed-in account, and the bare pre-routing login
            # role serves nobody in particular.
            app_user=None,
            # 0360: a library is listed, installed and worn under a platform tier.
            app_guild_base=None,
            platform_base=frozenset({SELECT}),
        ),
    ),
    # The communities an account takes no messages from. Per-account and cross-guild,
    # like ``user_dm_settings``.
    "user_dm_guild_optouts": SharedTable(
        rls=TableRls(
            policies=(
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
                Policy(
                    "user_dm_guild_optouts_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_dm_guild_optouts_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "user_dm_guild_optouts_self_select",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            app_admin=frozenset({SELECT, DELETE}),
            # 0225: the direct-message transport and its reach tables grant the guild
            # floor nothing; every policy on them is TO platform_base.
            app_guild_base=None,
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # Who may ask to message an account. Per-account and cross-guild, and no guild's
    # business.
    "user_dm_settings": SharedTable(
        rls=TableRls(
            policies=(
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
                Policy(
                    "user_dm_settings_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_dm_settings_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "user_dm_settings_self_select",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_dm_settings_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # An account is created on the system engine (registration, invite
            # redemption, provisioning from an identity provider), and its policy row is
            # seeded there from the operator default — hence INSERT. The other three are
            # written on the request path by the account holder; the system engine only
            # reads them for the guild-lifecycle sweeps and clears them on erasure.
            app_admin=frozenset({SELECT, INSERT, DELETE}),
            # Read and written on the authenticated platform-tier path, never before a
            # session is routed.
            app_user=None,
            platform_base=DML,
        ),
    ),
    # Who an account has chosen not to hear from. Per-account and cross-guild, like
    # ``user_dm_settings``.
    "user_ignores": SharedTable(
        rls=TableRls(
            policies=(
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
                Policy(
                    "user_ignores_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_ignores_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "user_ignores_self_select",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # SELECT also carries the notification fan-out: who, of a set of
            # recipients, ignores the actor (see app.services.platform.accounts).
            app_admin=frozenset({SELECT, DELETE}),
            platform_base=frozenset({SELECT, INSERT, DELETE}),
        ),
    ),
    # What one account wants to be told about. Off ``users`` on purpose: that table is
    # read whole by the platform tiers.
    "user_notification_prefs": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "user_notification_prefs_self_insert_{prefix}platform_base",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "user_notification_prefs_self_select_{prefix}platform_base",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "user_notification_prefs_self_update_{prefix}platform_base",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # Seeded when an account is created, read on every fan-out to decide who
            # wants what, and updated by the settings endpoint.
            app_admin=DML,
            # Read under the account's own role after routing, never before it.
            app_user=None,
            # 0360: read and changed under a platform tier; delivery reads a
            # recipient's settings on the system engine.
            app_guild_base=None,
            platform_base=DML,
        ),
    ),
    # Personal UI state (filters, sort, view mode), per-account and cross-guild.
    "user_view_preferences": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "user_view_preferences_self_scope",
                    ALL,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # personal UI state — the system engine has no business here
            app_admin=None,
            # 0360: personal UI state, read and written under a platform tier.
            app_guild_base=None,
            platform_base=DML,
        ),
    ),
    # The account. One user spans many guilds.
    "users": SharedTable(
        rls=TableRls(
            policies=(
                Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
                Policy("users_app_user_read", SELECT, ("app_user",), using=OPEN),
                Policy(
                    "users_app_user_self_update",
                    UPDATE,
                    ("app_user",),
                    using=own_row("id"),
                ),
                Policy(
                    "users_no_delete",
                    DELETE,
                    ("public",),
                    using=CLOSED,
                    restrictive=True,
                ),
                Policy(
                    "users_platform_read", SELECT, Capability.USERS_READ, using=OPEN
                ),
                Policy(
                    "users_platform_self", ALL, ("platform_base",), using=own_row("id")
                ),
                Policy(
                    "users_profile_read", SELECT, ("app_profile_reader",), using=OPEN
                ),
                # A member token's standing reads whether the account it acts for is
                # active (its column grant is id and status alone; migration
                # 20260924_0385).
                Policy(
                    "install_reads_its_member",
                    SELECT,
                    ("plugin_install_base",),
                    using=own_row("id"),
                ),
                Policy(
                    "users_request_insert_member_only",
                    INSERT,
                    ("public",),
                    check=MEMBER_ROLE_ONLY,
                    restrictive=True,
                ),
            ),
        ),
        grants=Grants(
            app_admin=DML,
            # SELECT at the table level; UPDATE is column-scoped to every column except
            # ``role`` (migration 0144) so it does not appear here (a column grant lives
            # in the column ACL, not the table ACL). ``role`` is writable only by the
            # system engine — see security_invariants_test.
            app_user=frozenset({SELECT}),
            # 0144 and 0202 revoked every table-level verb from the guild floor: an
            # account's own record is read and written under a platform tier, and the
            # guild-routed path names a member through the guild_member_profiles view
            # (0220). Asserted by test_the_guild_path_holds_nothing_on_the_users_table.
            app_guild_base=None,
            platform_base=frozenset({SELECT}),
            # No TABLE grant: a column-scoped SELECT on (id, status), which a member
            # token's standing reads for the member it acts for alone
            # (install_reads_its_member; migration 20260924_0385). Asserted in
            # install_standing_test beside the ones below.
            plugin_install_base=None,
        ),
    ),
    # What the security rules counted, per key and window
    # (app.services.platform.security_signals). Keys are HMACs, never an
    # address or an account.
    "security_signal_windows": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # Every instance adds its counts here, stamps a window that crossed
            # its rule's threshold, and the intake sweep drops windows no rule
            # can still read — all on the system engine.
            app_admin=DML,
        ),
    ),
    # Spent client-assertion jtis from the plug-in token endpoint. Hangs off a
    # registration, which is platform-wide.
    "plugin_assertion_jtis": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # The token endpoint records each client assertion's jti here, and the
            # shared jti janitor prunes the ones past their assertion's exp. Never
            # updated — a spent jti has one state.
            app_admin=frozenset({SELECT, INSERT, DELETE}),
            # Client-assertion jtis: spent on the system engine alone.
            app_user=None,
        ),
    ),
    # Which community holds which install, and the value a vendor webhook routes to it
    # by. An index over the guild schemas, holding no content.
    "plugin_installs": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # The install index: kept in step with each community's installs, read to
            # list a plug-in's installs and to route its vendor webhooks.
            app_admin=DML,
        ),
    ),
    # The settings' stored credentials.
    "app_setting_secrets": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # The settings singleton's stored credentials (migration 0362): seeded at
            # boot, written by the owner's email/storage routes, read by the mailer and
            # the storage client, and re-keyed by the secret-key rotation — all on the
            # system engine. A singleton like the row it belongs to, never deleted.
            app_admin=frozenset({SELECT, INSERT, UPDATE}),
            # The settings' stored credentials are the system engine's alone.
            app_user=None,
            # 0362 took the schema default back: the system engine's alone.
            app_guild_base=None,
        ),
    ),
    # Deployment-level wiring for external plug-in services (listing, URL, public keys,
    # operator-conferred grants). Platform-wide by definition — one row per plug-in,
    # never per guild — and owner-managed.
    # Everything else is the system engine's. An installed plug-in's standing reads
    # the registration its token was issued to (its column grant is public_id,
    # listing_uid, enabled, publisher_id, jwks, jwks_uri, base_url, vendor_ready,
    # kind and operations_only alone).
    "plugin_service_registrations": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "install_reads_its_registration",
                    SELECT,
                    ("plugin_install_base",),
                    using=f"public_id = {gucs.TOKEN_CLIENT_ID}",
                ),
            ),
        ),
        grants=Grants(
            # Plug-in service registrations: full DML on the system engine, which is the
            # only reader and writer — the owner-gated CRUD endpoints run on
            # SystemSessionDep (as access_grants and auth_providers do), boot
            # reconciliation upserts from PLUGIN_SERVICES_CONFIG, and the registration
            # snapshot reads it. No request-path role holds anything on it beyond the
            # install floor's column grant.
            app_admin=DML,
            # Deployment wiring: read and written on the system engine alone.
            app_user=None,
            # No TABLE grant: a column-scoped SELECT on (public_id, listing_uid,
            # enabled, publisher_id, jwks, jwks_uri, base_url, vendor_ready, kind,
            # operations_only), for the registration the install's token names
            # (install_reads_its_registration; migrations 20260924_0379,
            # 20260924_0387, 20260924_0388, 20260924_0390, 20260925_0393,
            # 20261001_0437 and 20261010_0482). Asserted in install_standing_test
            # beside the one on guilds.
            plugin_install_base=None,
        ),
    ),
    # Who publishes the plug-ins in ``plugin_service_registrations``: one row per
    # public_id prefix, with the switch that stops every plug-in under it. Deployment
    # configuration.
    # Everything else is the system engine's. An installed plug-in's standing reads
    # whether the publisher of its token's registration is on (its column grant
    # is id and enabled alone).
    "publishers": SharedTable(
        rls=TableRls(
            policies=(
                Policy(
                    "install_reads_its_publisher",
                    SELECT,
                    ("plugin_install_base",),
                    using=(
                        "EXISTS (SELECT 1 FROM public.plugin_service_registrations r "
                        "WHERE r.publisher_id = publishers.id "
                        f"AND r.public_id = {gucs.TOKEN_CLIENT_ID})"
                    ),
                ),
            ),
        ),
        grants=Grants(
            # Publishers: written by the plugins.manage routes, seeded at boot, added when
            # a registration names a new prefix, and read with every registration.
            # Nothing deletes one (a registration references it).
            app_admin=frozenset({SELECT, INSERT, UPDATE}),
            # No TABLE grant: a column-scoped SELECT on (id, enabled), for the
            # publisher of that registration (install_reads_its_publisher; migration
            # 20260924_0387).
            plugin_install_base=None,
        ),
    ),
    # A sign-in between its password and its code.
    "auth_challenges": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # resolved by digest before the account is known, as a refresh token is
            app_admin=DML,
        ),
    ),
    # A provider's client secret, the system engine's companion to ``auth_providers``.
    "auth_provider_secrets": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # provider client secret — read/written only by the system engine (provider
            # CRUD via SystemSessionDep + config.manage); no request-path grant
            app_admin=DML,
            # client secrets are system-engine-only; no request role ever reads them
            app_user=None,
        ),
    ),
    # The sign-in provider registry, read before routing; every row is the operator's.
    "auth_providers": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # login provider registry (successor to app_settings.oidc_*): fully managed
            # on the system engine — login reads + provider CRUD via SystemSessionDep with
            # capability/ownership checks (as access_grants). Like oidc_claim_mappings, it
            # carries NO permissive RLS policy; the request path does not read provider
            # config.
            app_admin=DML,
            # provider reads for the login page go via the system engine (SystemSessionDep),
            # not the bare login role
            app_user=None,
            # 0131, 0133, 0142: the login provider registry, its secrets and the
            # identity links are the system engine's; each migration took the schema
            # default back from both floors.
            app_guild_base=None,
        ),
    ),
    # The session and refresh store (a token's sid is the row id).
    "auth_sessions": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # session/refresh store — validated pre-auth by refresh-token hash (user
            # unknown), so all session ops run on the system engine; request path revoked
            app_admin=DML,
            # sessions are system-engine-only; the bare login role never touches them
            app_user=None,
            # 0132, 0261, 0262, 0290, 0307: sessions, addresses, factors and
            # challenges are resolved on the system engine before an account is
            # known; each migration took the schema default back from both floors.
            app_guild_base=None,
        ),
    ),
    # An identity provider's refresh token, the system engine's companion to
    # ``federated_identities``.
    "federated_identity_secrets": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # IdP refresh token per identity link — read/rotated only by the system
            # engine (login + background group re-sync)
            app_admin=DML,
            # IdP refresh tokens are system-engine-only; no request role ever reads them
            app_user=None,
        ),
    ),
    # Registry client state, no guild (see ``marketplace_tuf_metadata``).
    "marketplace_registry_status": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # Refresh bookkeeping beside marketplace_tuf_metadata: one row,
            # recycled in place.
            app_admin=frozenset({SELECT, INSERT, UPDATE}),
        ),
    ),
    # Registry client state (with ``marketplace_registry_status`` and
    # ``marketplace_media``): the TUF metadata this deployment last verified, how the
    # last refresh went, and the artwork its listings named, kept locally so listing
    # media is served from here. Operator and system state, no guild.
    "marketplace_tuf_metadata": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # Registry client state: read and written by the refresh job alone. The
            # verified TUF metadata is replaced role by role, so a superseded version
            # is deleted; the status is one row, recycled in place.
            app_admin=DML,
            # Refresh bookkeeping — system engine only, surfaced to an operator through
            # a capability-gated endpoint rather than read on the request path.
            app_user=None,
        ),
    ),
    # The codes that stand in for an account's second factor, presented while signing
    # in.
    "mfa_recovery_codes": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # The second factor and what it is made of — enrolled, presented
            # and removed on the system engine, like the session store beside it.
            app_admin=DML,
        ),
    ),
    # SSO auto-join rules, read across all guilds at sign-in.
    "oidc_claim_mappings": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # OIDC sync reads mappings; the settings endpoints manage them
            app_admin=DML,
            # Read at sign-in and written by the seat's claim-rule routes, both on the
            # system engine; 0354 took the schema default back from both floors.
            app_guild_base=None,
        ),
    ),
    # Per-account, like the account it hangs off.
    "user_api_keys": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # pre-auth credential store — validated by token_hash before the user is
            # known, so the lookup + create + deactivate all run on the system engine
            # (no request-path grant, no own-row policy), like auth_sessions
            app_admin=DML,
            # system-engine-only credential store; the request path never touches it
            # (auth lookup + management endpoints run on app_admin), like auth_sessions
            app_user=None,
            # 0156: system-engine-only, no request-path grant.
            app_guild_base=None,
        ),
    ),
    # Per-account, like the account it hangs off.
    "user_tokens": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # Email-verification and password-reset tokens, matched by hash
            # before the account is known: minted, redeemed and swept on
            # the system engine alone (0358), like auth_sessions and user_api_keys.
            app_admin=DML,
            # 0358: every token path runs on the system engine, pre-routing included.
            app_user=None,
            # 0358: tokens are the system engine's, and a push is delivered on it; the
            # guild floor reaches neither table.
            app_guild_base=None,
            # 0358: tokens are the system engine's alone.
            platform_base=None,
        ),
    ),
    # Account changes waiting to apply.
    "account_change_holds": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # A change waiting to apply: requested, cancelled and applied on the
            # system engine, beside the session and credential rows it acts on.
            app_admin=DML,
            app_user=None,
            app_guild_base=None,
            platform_base=None,
        ),
    ),
    # Which providers assert an account's addresses.
    "user_email_assertions": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # A pre-auth lookup, as user_emails is.
            app_admin=DML,
        ),
    ),
    # Recent wrong answers, per account.
    "sign_in_locks": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # counted while signing in, before anybody is authenticated
            app_admin=DML,
        ),
    ),
    # The addresses an account signs in with.
    "user_emails": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # resolving an address to an account is a pre-auth lookup, like a session
            app_admin=DML,
        ),
    ),
    # WebAuthn credentials. An assertion arrives before any account is known.
    "user_passkeys": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # Registered, renamed, used and removed on the system engine — the request
            # path reaches a passkey only through a route running there, the same as
            # the other second-factor tables.
            app_admin=DML,
            # the factor tables are system-engine-only; the bare login role never
            # touches them, and neither does any request-path role
            app_user=None,
        ),
    ),
    # The account's own second factor, presented while signing in.
    "user_totp": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # The second factor and what it is made of — enrolled, presented
            # and removed on the system engine, like the session store beside it.
            app_admin=DML,
        ),
    ),
    # The seed behind an account's second factor, presented while signing in.
    "user_totp_secrets": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # The second factor and what it is made of — enrolled, presented
            # and removed on the system engine, like the session store beside it.
            app_admin=DML,
        ),
    ),
    # An account's date of birth, encrypted, checked against a plug-in's minimum age on
    # the system engine.
    "user_birthdates": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # An account's date of birth, encrypted — written when the person
            # answers and read to check a plug-in's minimum age, both on the
            # system engine. No request role sees a date.
            app_admin=DML,
        ),
    ),
    "storage_backfill_state": SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(
            # lazily-created UNLOGGED backfill status singleton: read, seeded idle, and
            # claimed/updated on the system engine; rows are never deleted (the claim
            # UPDATE recycles the singleton). The service grants exactly this set at
            # table creation (app.services.storage_backfill._table_ddl).
            app_admin=frozenset({SELECT, INSERT, UPDATE}),
            # system-engine-only status singleton; no request role reads it
            app_user=None,
            # _table_ddl takes both floors back at creation
            # (app.services.storage_backfill).
            app_guild_base=None,
        ),
    ),
    "alembic_version": SharedTable(
        rls=NO_RLS,
        grants=Grants(
            # migrations-only bookkeeping (the provisioning role owns it)
            app_admin=None,
        ),
    ),
    # One-shot billing service-JWT redemption.
    "billing_jti_blocklist": SharedTable(
        rls=NO_RLS,
        grants=Grants(
            # Read, and pruned by the janitor once expired; written only under
            # initiative_billing (see billing_event_log).
            app_admin=frozenset({SELECT, DELETE}),
        ),
    ),
    # Notification email waiting to go out. Per-account and cross-guild: one message can
    # gather rows from every community somebody is in, so it belongs to none of them.
    "email_outbox": SharedTable(
        rls=NO_RLS,
        grants=Grants(
            # Notification email waiting to go out. The worker owns this table: it
            # reads what is due, claims it, settles it and sweeps it, and the settings
            # endpoint rewrites the due times when somebody changes when they read.
            # Every row is written there too — by the notice worker, the digests and
            # the account letters — so no request floor holds anything
            # (20261001_0428).
            app_admin=DML,
        ),
    ),
    # A notice waiting to be delivered to one account, from whichever community it
    # happened in. Per-account and cross-guild, like ``email_outbox``.
    "notice_outbox": SharedTable(
        rls=NO_RLS,
        grants=Grants(
            # A notice waiting to be delivered. The worker owns this table: it
            # claims what is due, writes the bell line and the email, sends the
            # push and deletes the row. The request path only ever appends.
            app_admin=DML,
            app_user=None,
            # A routed request appends a row per recipient of what it caused,
            # and never reads one back.
            app_guild_base=frozenset({INSERT}),
            platform_base=frozenset({INSERT}),
            # What an install's write causes is told the same way.
            plugin_install_base=frozenset({INSERT}),
        ),
    ),
    # A device of one account, which spans many guilds.
    "push_tokens": SharedTable(
        rls=TableRls(
            policies=(
                # A device registers, re-registers and unregisters under its owner's
                # platform tier; delivery reads and prunes on the system engine.
                Policy(
                    "push_tokens_self_read",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "push_tokens_self_insert",
                    INSERT,
                    ("platform_base",),
                    check=own_row("user_id"),
                ),
                Policy(
                    "push_tokens_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "push_tokens_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # Every push is delivered through the system engine: it reads the
            # recipient's rows, UPDATE stamps last_used_at, DELETE prunes tokens FCM
            # reports as unregistered (0358).
            app_admin=DML,
            # A device's own registration: the upsert reads and writes the row it
            # conflicts on and returns it, and unregistering deletes it. The policies
            # admit the account's own rows (0358).
            platform_base=DML,
        ),
    ),
    # Per-account inbox spanning guilds; each row carries its own place.
    "notifications": SharedTable(
        rls=TableRls(
            policies=(
                # The reader's own bell: list it, mark it read, dismiss it.
                Policy(
                    "notifications_self_read",
                    SELECT,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "notifications_self_update",
                    UPDATE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
                Policy(
                    "notifications_self_delete",
                    DELETE,
                    ("platform_base",),
                    using=own_row("user_id"),
                ),
            ),
        ),
        grants=Grants(
            # UPDATE joined the set for the rolled-up direct-message line: the system
            # engine already creates and reaps these rows, and a rollup rewrites one
            # it wrote itself rather than reaching a row it could not otherwise touch.
            app_admin=DML,
            # The reader's own bell: listed, marked read and dismissed. Every line
            # is written on the system engine — by the notice worker, or inline
            # for a direct message and the suspension notice — so no request
            # floor writes one (0357 for this floor, 20261001_0428 for the routed
            # and install floors).
            platform_base=frozenset({SELECT, UPDATE, DELETE}),
        ),
    ),
}


# --- The platform read floor ----------------------------------------------------
#
# ``platform_base_ro`` is the read half of ``platform_base``: what a suspended
# account's ``platform_suspended`` role inherits, and nothing else does. It is
# derived here rather than written into each entry above, so it reads exactly
# the rows ``platform_base`` reads and the two cannot drift: every SELECT policy
# granted to ``platform_base`` is granted to it as well, and every ALL policy
# gains a SELECT twin for it. Nothing that writes is extended.

PLATFORM_BASE = "platform_base"
PLATFORM_READ_FLOOR = "platform_base_ro"


def _with_read_floor(policy: Policy) -> tuple[Policy, ...]:
    if isinstance(policy.roles, Capability) or PLATFORM_BASE not in policy.roles:
        return (policy,)
    if policy.command == SELECT:
        return (replace(policy, roles=(*policy.roles, PLATFORM_READ_FLOOR)),)
    if policy.command == ALL:
        return (
            policy,
            Policy(
                f"{policy.name}_read_floor",
                SELECT,
                (PLATFORM_READ_FLOOR,),
                using=policy.using,
                restrictive=policy.restrictive,
            ),
        )
    return (policy,)


#: Each shared table's row security, with the platform read floor derived.
PUBLIC_RLS: dict[str, TableRls] = {
    table: replace(
        shared.rls,
        policies=tuple(
            p for policy in shared.rls.policies for p in _with_read_floor(policy)
        ),
    )
    for table, shared in SHARED_TABLE_REGISTRY.items()
}


# --- Rendering ------------------------------------------------------------------


def _roles_sql(roles: tuple[str, ...]) -> str:
    out = []
    for role in roles:
        if role == "public":
            out.append("PUBLIC")
        else:
            out.append(f'"{role_name(role)}"')
    return ", ".join(out)


def policy_name(policy: Policy) -> str:
    """The name as the catalog holds it: ``{prefix}`` is the platform role
    prefix (two migrations named their per-role policies after the role), and
    Postgres keeps the first 63 characters of an identifier."""
    return policy.name.replace("{prefix}", settings.PLATFORM_ROLE_PREFIX)[:63]


def render_policy(table: str, policy: Policy) -> str:
    """The idempotent DDL for one policy: drop what is there, create this."""
    name = policy_name(policy)
    using = policy.using.replace("{table}", table) if policy.using else None
    check = policy.check.replace("{table}", table) if policy.check else None
    if check is None and policy.command in (UPDATE, ALL):
        check = using
    kind = "RESTRICTIVE" if policy.restrictive else "PERMISSIVE"
    lines = [
        f"DROP POLICY IF EXISTS {name} ON public.{table};",
        f"CREATE POLICY {name} ON public.{table} AS {kind} FOR {policy.command}",
        f"  TO {_roles_sql(policy_roles(policy))}",
    ]
    if using is not None:
        lines.append(f"  USING ({using})")
    if check is not None:
        lines.append(f"  WITH CHECK ({check})")
    lines[-1] += ";"
    return "\n".join(lines)


def render_table_rls(table: str, rls: TableRls) -> str:
    """Row security and policies for one table. Never disables: a table that
    has row security on when the registry says off is drift for the test to
    report, not something boot turns off."""
    lines = []
    if rls.enabled:
        lines.append(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")
    if rls.forced:
        lines.append(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
    lines.extend(render_policy(table, p) for p in rls.policies)
    return "\n".join(lines)


def render_public_rls_ddl(tables: frozenset[str] | None = None) -> str:
    """The whole registry as DDL, table by table in name order."""
    blocks = [
        f"-- {table}\n{render_table_rls(table, rls)}"
        for table, rls in sorted(PUBLIC_RLS.items())
        if (tables is None or table in tables) and (rls.enabled or rls.forced)
    ]
    return (
        "-- RENDERED from app.db.public_rls. Idempotent; run as the tables' owner.\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def public_rls_digest() -> str:
    """What the schema comment carries once the render has been applied."""
    return hashlib.sha256(render_public_rls_ddl().encode()).hexdigest()[:16]


STAMP_PREFIX = "public_rls:"


# --- Applying -------------------------------------------------------------------


async def existing_public_tables(conn: AsyncConnection) -> frozenset[str]:
    rows = await conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    return frozenset(r[0] for r in rows)


async def apply_public_rls(conn: AsyncConnection) -> None:
    """Run the registry's DDL for every registered table that exists.

    ``storage_backfill_state`` is created lazily by its service, so a table
    registered here may not exist yet; it is picked up on the next boot.
    """
    existing = await existing_public_tables(conn)
    ddl = render_public_rls_ddl(existing & frozenset(PUBLIC_RLS))
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(ddl)


async def unregistered_policies(conn: AsyncConnection) -> list[tuple[str, str]]:
    """Policies on shared tables that the registry does not name."""
    rows = await conn.execute(
        text(
            "SELECT tablename, policyname FROM pg_policies "
            "WHERE schemaname = 'public' ORDER BY 1, 2"
        )
    )
    known = {
        (table, policy_name(policy))
        for table, rls in PUBLIC_RLS.items()
        for policy in rls.policies
    }
    return [(t, p) for t, p in rows if (t, p) not in known]


async def apply_public_rls_if_changed(conn: AsyncConnection) -> bool:
    """Apply the registry when its render differs from the last one applied.

    The ``public`` schema's comment carries the digest of the render last
    applied, the way a guild schema's carries its provisioning stamp; a boot
    whose render matches it does nothing. Anything on a shared table that the
    registry does not name is left in place and logged. Returns whether the
    render was applied.
    """
    digest = public_rls_digest()
    stamp = (
        await conn.execute(
            text("SELECT obj_description('public'::regnamespace, 'pg_namespace')")
        )
    ).scalar()
    if stamp == STAMP_PREFIX + digest:
        return False
    await apply_public_rls(conn)
    stray = await unregistered_policies(conn)
    if stray:
        logger.warning(
            "policies on shared tables that app.db.public_rls does not name: %s",
            ", ".join(f"{t}.{p}" for t, p in stray),
        )
    try:
        await conn.execute(
            text(f"COMMENT ON SCHEMA public IS '{STAMP_PREFIX}{digest}'")
        )
    except Exception:  # noqa: BLE001 — the render applied; only the stamp did not
        logger.warning(
            "public RLS applied but the public schema could not be stamped; "
            "it will be re-applied on every boot until the schema is owned by "
            "the provisioning login"
        )
    return True


async def ensure_public_rls() -> None:
    """Apply the registry on boot, over the provisioning engine.

    Called after the migrations and before the guild back-fill, on the login
    that owns the shared tables.
    """
    from app.db import session as db_session

    async with db_session.provisioning_engine.begin() as conn:
        applied = await apply_public_rls_if_changed(conn)
    if applied:
        logger.info("public RLS applied: %s", public_rls_digest())
