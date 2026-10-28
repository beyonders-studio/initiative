"""A reader's standing in one community, computed once per request.

Every initiative-scoped table's policies defer to three functions —
``initiative_access`` (membership), ``initiative_role_permits`` (the reader's
role in the initiative) and ``resource_access`` (sharing) — plus an inline
sub-select for the tool switch. Each of those contains a sub-select, so
Postgres never inlines it: one executor start per call, per row, per nesting
level. Everything they compute except the ``resource_grants`` probe is the
same for every row of a request: who the reader is, which initiatives they are
in, what their role there permits, whether the community's sign-in policy is
satisfied, the admin fact and the grant flags.

Gate 1 already worked the other way: ``SET ROLE guild_<id>`` once per request.
This module is the rest of the reader's standing, written the same way — in
one statement, after the routing, by the database, from its own rows.

**One statement, no binds.** :data:`STANDING_SQL` is a single ``SELECT`` of
``set_config`` calls whose values are sub-selects. It binds no user and no
community: every sub-select reads them back from ``app.current_user_id`` and
``app.current_guild_id``, which the routing statement has just written, so
there is one source and no way to compute a standing that disagrees with the
session it lands on. ``set_config`` returns what it wrote, so the row the
statement returns is what the policies will read, and :class:`GuildContext` is
built from that row rather than from what Python believed.

**Bound to its community.** A standing means nothing outside the community it
was computed in — initiative 5 in ``guild_7`` and initiative 5 in ``guild_9``
are different rows. Two things keep one from answering under another's
routing. The routing statement writes ``''`` into every key here, so between
routing and standing the standing is empty and an empty standing answers no on
every membership leg. And the standing records the community it was computed
for (``app.standing_guild_id``) — a member's routed community, or the one a
grantee's grant names — which every gate that reads it compares against the
routed one.

**Where it lives.** In ``session.info`` as part of the stored routing
parameters, so the ``after_begin`` replay hook re-applies the routing and the
standing together from one entry: a replayed transaction cannot carry the
routing of one community and the standing of another.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any, Optional, Sequence

from app.core.capabilities import may_hold_grant
from app.core.plugin_scopes import (
    PLUGIN_SCOPE_PREFIX,
    LEVEL_SCOPES,
    STANDING_SCOPES,
    InstallLevel,
)
from app.core.tools import Tool
from app.db import gucs
from app.db.authorization import LIVE_GRANT, live_membership, sql_values
from app.models.platform.access_grant import (
    AccessGrantPurpose,
    AccessLevel,
    SettingsLevel,
)
from app.models.platform.plugin_service_registration import (
    RegistrationKind,
    registration_live_sql,
)
from app.models.platform.guild import (
    GUILD_LADDER,
    LIVE_STATUS_VALUES,
    CommunityRole,
    CommunityStatus,
)
from app.models.platform.identity_ref import (
    REF_GRACE_PERIOD,
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    ref_prefix,
)
from app.models.platform.user import UserRole, UserStatus
from app.models.tenant.plugin_member_consent import ConsentAccess
from app.models.tenant.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.platform.access_grant import AccessGrant
    from app.models.platform.guild import Guild, GuildMembership, CommunityRole

__all__ = [
    "ActorContext",
    "GuildContext",
    "INSTALL_STANDING_SQL",
    "ISSUABLE_SCOPES_SQL",
    "InstallContext",
    "STANDING_SQL",
    "compute_guild_standing",
    "compute_install_standing",
    "named_ref_candidates",
    "standing_values",
]


#: The rungs that administer a community, as the ladder orders them — the
#: one spelling the admin fact and the settings rung are read off.
_ADMIN_RUNGS: tuple[CommunityRole, ...] = tuple(
    rung for rung in GUILD_LADDER if rung.reaches(CommunityRole.admin)
)
_ADMIN_RUNGS_SQL = sql_values(rung.value for rung in _ADMIN_RUNGS)
#: The highest rung held wins, so the ladder is walked from the top.
_SETTINGS_RUNG_CASE = "\n".join(
    f"               WHEN bool_or(rung = '{rung.value}') THEN '{rung.value}'"
    for rung in reversed(_ADMIN_RUNGS)
)


def _tool_switch_values() -> str:
    """The per-initiative tool switches as a ``VALUES`` list.

    Rendered from the ``Tool`` enum, the way the switch column names already
    are, so a new tool reaches the standing the moment it reaches the enum.
    """
    return ", ".join(f"('{tool.value}', i.{tool.plural}_enabled)" for tool in Tool)


def _writes(values: dict[gucs.Guc, str]) -> str:
    """A standing statement's select list: each key written with its
    expression, and returned under its name."""
    return ",\n".join(
        f"  set_config('{guc.name}', {expr}, true) AS {guc.bind}"
        for guc, expr in values.items()
    )


def _tiers_holding(purpose: AccessGrantPurpose, level: str) -> str:
    """The platform tiers that may hold a grant of ``purpose`` at ``level``,
    as a SQL list."""
    return ", ".join(
        f"'{role.value}'"
        for role in sorted(UserRole, key=str)
        if may_hold_grant(role, purpose.value, level)
    )


#: A grant row ``g`` its holder may hold at their tier as it stands now, not as
#: it stood when the grant was approved (:func:`may_hold_grant`): a
#: ``moderate`` grant while they moderate, any other while they may ask for
#: any or break glass.
_GRANT_HELD = f"""COALESCE(CASE
      WHEN g.purpose = '{AccessGrantPurpose.content.value}'
       AND g.access_level::text = '{AccessLevel.moderate.value}'
      THEN {gucs.PLATFORM_ROLE.sql} IN ({_tiers_holding(AccessGrantPurpose.content, AccessLevel.moderate.value)})
      ELSE {gucs.PLATFORM_ROLE.sql} IN ({_tiers_holding(AccessGrantPurpose.content, AccessLevel.read.value)})
    END, false)"""

#: The request is routed into a guest role: the role in use carries the guest
#: floor. A ``guest`` membership row is read only under one, and under any
#: other role it is no membership and its holder is in no initiative.
_ROUTED_AS_GUEST = "pg_has_role(current_user, 'guest_base', 'USAGE')"

#: The reader's own rows the person statement reads, each table once. Every
#: key below is an aggregate over one of these, so a new key picks a row set
#: rather than reading its table again. ``my_items`` is a guest's: the
#: initiatives of the items shared with them by name, read only when the
#: membership row is a guest's.
_PERSON_ROWS = f"""
WITH my_row AS MATERIALIZED (
  SELECT m.role,
         (m.role <> '{CommunityRole.guest.value}' OR {_ROUTED_AS_GUEST}) AS routed
  FROM public.guild_memberships m
  WHERE m.guild_id = {gucs.GUILD_ID} AND m.user_id = {gucs.USER_ID}
    AND {live_membership("m")}
),
my_membership AS MATERIALIZED (
  SELECT r.role FROM my_row r WHERE r.routed
),
my_initiatives AS MATERIALIZED (
  SELECT im.initiative_id, im.role_id,
         COALESCE(r.is_manager, false) AS is_manager,
         COALESCE(r.override_share_restrictions, false) AS overrides
  FROM initiative_members im
  LEFT JOIN initiative_roles r ON r.id = im.role_id
  WHERE im.user_id = {gucs.USER_ID}
    AND NOT EXISTS (SELECT 1 FROM my_row mr WHERE NOT mr.routed)
),
my_items AS MATERIALIZED (
  SELECT DISTINCT g.initiative_id
  FROM resource_grants g
  WHERE g.user_id = {gucs.USER_ID} AND g.initiative_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM my_membership m WHERE m.role = '{CommunityRole.guest.value}'
    )
),
my_role_permissions AS MATERIALIZED (
  SELECT mi.initiative_id, rp.permission_key, rp.enabled
  FROM my_initiatives mi
  JOIN initiative_role_permissions rp ON rp.initiative_role_id = mi.role_id
),
my_grants AS MATERIALIZED (
  SELECT g.purpose, g.access_level::text AS access_level
  FROM public.access_grants g
  WHERE g.guild_id = {gucs.ROUTED_GUILD_ID}
    AND g.user_id = {gucs.USER_ID}
    AND {LIVE_GRANT}
    AND {_GRANT_HELD}
)"""

#: What the person statement writes: each standing key and its expression.
_PERSON_STANDING: dict[gucs.Guc, str] = {
    gucs.STANDING_GUILD_ID: f"""COALESCE({gucs.ROUTED_COMMUNITY}, '')""",
    gucs.GUILD_ADMIN: f"""COALESCE((
      SELECT (m.role IN ({_ADMIN_RUNGS_SQL}))::text FROM my_membership m
    ), 'false')""",
    # The seat as ``guild_superadmin()`` answers it, lent by a grant only while
    # the grant is still held.
    gucs.GUILD_SEAT: f"""COALESCE((
      SELECT (public.guild_superadmin({gucs.ROUTED_GUILD_ID}, {gucs.USER_ID})
        AND (EXISTS (
          SELECT 1 FROM my_membership m
          WHERE m.role = '{CommunityRole.superadmin.value}'
        ) OR EXISTS (
          SELECT 1 FROM my_grants g
          WHERE g.purpose = '{AccessGrantPurpose.settings.value}'
            AND g.access_level = '{SettingsLevel.superadmin.value}'
        )))::text
    ), 'false')""",
    gucs.SETTINGS_RUNG: f"""COALESCE((
      SELECT CASE
{_SETTINGS_RUNG_CASE}
             END
      FROM (
        SELECT m.role::text AS rung
        FROM my_membership m
        WHERE m.role IN ({_ADMIN_RUNGS_SQL})
        UNION ALL
        SELECT g.access_level FROM my_grants g
        WHERE g.purpose = '{AccessGrantPurpose.settings.value}'
      ) AS rungs
    ), '')""",
    gucs.PAM_READ: f"""(
      SELECT EXISTS (
        SELECT 1 FROM my_grants g
        WHERE g.purpose = '{AccessGrantPurpose.content.value}'
      )::text
    )""",
    gucs.PAM_WRITE: f"""(
      SELECT EXISTS (
        SELECT 1 FROM my_grants g
        WHERE g.purpose = '{AccessGrantPurpose.content.value}'
          AND g.access_level = '{AccessLevel.read_write.value}'
      )::text
    )""",
    # A moderate grant reads what the platform holds only while its holder
    # still moderates, which ``my_grants`` holds every grant to.
    gucs.PAM_MODERATE: f"""(
      SELECT EXISTS (
        SELECT 1 FROM my_grants g
        WHERE g.purpose = '{AccessGrantPurpose.content.value}'
          AND g.access_level = '{AccessLevel.moderate.value}'
      )::text
    )""",
    gucs.MEMBER_INITIATIVES: """COALESCE((
      SELECT string_agg(DISTINCT mi.initiative_id::text, ',')
      FROM my_initiatives mi
    ), '')""",
    gucs.MANAGER_INITIATIVES: """COALESCE((
      SELECT string_agg(DISTINCT mi.initiative_id::text, ',')
      FROM my_initiatives mi
      WHERE mi.is_manager
    ), '')""",
    gucs.MEMBER_ROLE_IDS: """COALESCE((
      SELECT string_agg(DISTINCT mi.role_id::text, ',')
      FROM my_initiatives mi
      WHERE mi.role_id IS NOT NULL
    ), '')""",
    gucs.ROLE_GRANTS: """COALESCE((
      SELECT string_agg(DISTINCT rp.initiative_id || ':' || rp.permission_key, ',')
      FROM my_role_permissions rp
      WHERE rp.enabled
    ), '')""",
    gucs.ROLE_DENIES: """COALESCE((
      SELECT string_agg(DISTINCT rp.initiative_id || ':' || rp.permission_key, ',')
      FROM my_role_permissions rp
      WHERE NOT rp.enabled
    ), '')""",
    gucs.ENABLED_TOOLS: f"""COALESCE((
      SELECT string_agg(DISTINCT i.id || ':' || t.tool, ',')
      FROM initiatives i
      CROSS JOIN LATERAL (VALUES {_tool_switch_values()}) AS t(tool, enabled)
      WHERE t.enabled
        AND i.id IN (
          SELECT mi.initiative_id FROM my_initiatives mi
          UNION ALL
          SELECT it.initiative_id FROM my_items it
        )
    ), '')""",
    gucs.OVERRIDE_INITIATIVES: """COALESCE((
      SELECT string_agg(DISTINCT mi.initiative_id::text, ',')
      FROM my_initiatives mi
      WHERE mi.overrides
    ), '')""",
    gucs.GUEST: f"""COALESCE((
      SELECT (m.role = '{CommunityRole.guest.value}')::text FROM my_membership m
    ), 'false')""",
    gucs.GUEST_ITEM_INITIATIVES: """COALESCE((
      SELECT string_agg(it.initiative_id::text, ',') FROM my_items it
    ), '')""",
    gucs.GUILD_AUTH_OK: """   (SELECT public.guild_auth_satisfied()::text)""",
    gucs.CONTENT_HOLD: f"""COALESCE((
      SELECT (g.status = '{CommunityStatus.read_only.value}')::text
      FROM public.guilds g
      WHERE g.id = {gucs.GUILD_ID}
    ), 'false')""",
}

#: The one statement. Runs as the routed role, after ``SET ROLE``, so the
#: reads of the shared tables go through those tables' own policies and the
#: routed role's grants (``app_guild_base`` holds ``SELECT`` on
#: ``guild_memberships`` and ``access_grants``, and the read-only floor is
#: derived from it), and the read of ``initiative_members`` resolves in the
#: community's own schema.
STANDING_SQL = f"""{_PERSON_ROWS}
SELECT
{_writes(_PERSON_STANDING)}
"""


# --- An installed plug-in's standing -----------------------------------------
#: The ``plugins:`` scope family names another plug-in rather than a resource of the
#: community's, so it adds nothing to what the install reads or writes.
_PLUGIN_SCOPE_FAMILY = PLUGIN_SCOPE_PREFIX.rstrip(":")
#: The standings, as a SQL list: they name no resource.
_STANDING_SCOPES_SQL = ", ".join(f"'{scope}'" for scope in sorted(STANDING_SCOPES))
_MODERATE_SCOPE = LEVEL_SCOPES[InstallLevel.moderator]
_GUILD_ADMIN_SCOPE = LEVEL_SCOPES[InstallLevel.community_admin]
#: The community statuses whose content is in use, as the person seam reads
#: them.
_LIVE_STATUSES_SQL = sql_values(sorted(LIVE_STATUS_VALUES))

#: A reference row in this install's own sector: the ``plugin`` purpose, the
#: routed community and the plug-in the token was issued to, which ``install``
#: below holds to the routed install's registration. The same predicate the
#: ``identity_refs`` policies for the install floor hold every read and insert
#: to (``app.db.public_rls``).
_IN_INSTALL_SECTOR = (
    f"r.purpose = '{IdentityPurpose.plugin.value}'"
    f" AND r.sector_guild_id = {gucs.GUILD_ID}"
    f" AND r.sector_plugin = {gucs.TOKEN_CLIENT_ID}"
)
#: How long a replaced reference keeps resolving, as an interval.
_GRACE_INTERVAL = f"interval '{int(REF_GRACE_PERIOD.total_seconds())} seconds'"


def _tool_permission_values() -> str:
    """Each tool's two role keys as a ``VALUES`` list of ``(resource, key,
    for_write)``: viewing it answers to the tool's read scope, creating it to
    its write scope. Rendered from the ``Tool`` enum, as the switches are."""
    return ", ".join(
        f"('{tool.plural}', '{key}', {str(for_write).lower()})"
        for tool in Tool
        for key, for_write in (
            (tool.view_permission, False),
            (tool.create_permission, True),
        )
    )


def _permission_key_values() -> str:
    """Every initiative role key, as a one-column ``VALUES`` list."""
    return ", ".join(f"('{key.value}')" for key in PermissionKey)


def _permission_default_values() -> str:
    """Every initiative role key with the answer it gets where a role has no
    row for it, as a ``VALUES`` list of ``(key, is_default)``: the defaults
    the content policies hand ``initiative_role_permits``."""
    return ", ".join(
        f"('{key.value}', {str(DEFAULT_PERMISSION_VALUES.get(key, False)).lower()})"
        for key in PermissionKey
    )


#: The scopes an install may use, as ``text[]`` over ``guild_plugins a``: those
#: the seat granted that the pinned version still requests, a container's in
#: its ``service`` block and a declarative plug-in's, which has none, at the top
#: of its manifest. The grant itself is left as the seat set it, so a scope a
#: later version stops requesting stops being carried by every token at once.
#: Read by token issuance, the install standing and the plug-in hub alike.
ISSUABLE_SCOPES_SQL = (
    "ARRAY(SELECT s FROM unnest(a.granted_scopes) AS s "
    "WHERE COALESCE(a.definition -> 'service', a.definition) -> 'scopes' "
    "@> jsonb_build_array(s))"
)


#: What the install statement writes: each key and its expression.
_INSTALL_STANDING: dict[gucs.Guc, str] = {
    gucs.STANDING_GUILD_ID: f"""COALESCE({gucs.GUILD_ID.text}, '')""",
    gucs.GUILD_ADMIN: """COALESCE((
      SELECT lv.administers::text FROM standing_level lv
    ), 'false')""",
    gucs.GUILD_SEAT: """'false'""",
    gucs.SETTINGS_RUNG: """''""",
    gucs.PAM_GUILD_ID: """''""",
    gucs.PAM_READ: """'false'""",
    gucs.PAM_WRITE: """'false'""",
    gucs.PAM_MODERATE: """'false'""",
    gucs.GUEST: """'false'""",
    gucs.GUEST_ITEM_INITIATIVES: """''""",
    gucs.MEMBER_INITIATIVES: """COALESCE((
      SELECT string_agg(p.initiative_id::text, ',' ORDER BY p.initiative_id)
      FROM placed p
    ), '')""",
    gucs.MANAGER_INITIATIVES: """COALESCE((
      SELECT string_agg(p.initiative_id::text, ',' ORDER BY p.initiative_id)
      FROM placed p
      JOIN standing_level lv ON lv.moderates
    ), '')""",
    gucs.MEMBER_ROLE_IDS: """COALESCE((
      SELECT string_agg(DISTINCT mr.role_id::text, ',')
      FROM member_role mr
      JOIN placed p ON p.initiative_id = mr.initiative_id
      WHERE mr.role_id IS NOT NULL
    ), '')""",
    gucs.ROLE_GRANTS: """COALESCE((
      SELECT string_agg(gr.pair, ',' ORDER BY gr.pair) FROM granted gr
    ), '')""",
    gucs.ROLE_DENIES: """COALESCE((
      SELECT string_agg(d.pair, ',' ORDER BY d.pair) FROM denied d
    ), '')""",
    gucs.ENABLED_TOOLS: f"""COALESCE((
      SELECT string_agg(DISTINCT i.id || ':' || t.tool, ',')
      FROM initiatives i
      JOIN placed p ON p.initiative_id = i.id
      CROSS JOIN LATERAL (VALUES {_tool_switch_values()}) AS t(tool, enabled)
      WHERE t.enabled
    ), '')""",
    gucs.OVERRIDE_INITIATIVES: """COALESCE((
      SELECT string_agg(DISTINCT o.initiative_id::text, ',')
      FROM (
        SELECT mr.initiative_id
        FROM member_role mr
        JOIN placed p ON p.initiative_id = mr.initiative_id
        WHERE mr.overrides
        UNION
        SELECT p.initiative_id
        FROM placed p
        JOIN standing_level lv ON lv.moderates
      ) o
    ), '')""",
    gucs.INSTALL_READ: """COALESCE((
      SELECT string_agg(DISTINCT h.resource, ',') FROM held h
    ), '')""",
    gucs.INSTALL_WRITE: """COALESCE((
      SELECT string_agg(DISTINCT h.resource, ',') FROM held h WHERE h.writes
    ), '')""",
    gucs.GUILD_AUTH_OK: """   (SELECT EXISTS (SELECT 1 FROM install))::text""",
    gucs.CONTENT_HOLD: f"""COALESCE((
      SELECT (g.status = '{CommunityStatus.read_only.value}')::text
      FROM public.guilds g
      WHERE g.id = {gucs.GUILD_ID}
    ), 'false')""",
}

#: An installed plug-in's standing, in one statement. Runs as
#: ``guild_<id>_plugin`` after the install routing. The community, the install, the client the token
#: was issued to, the token's scopes, the narrowed initiative and, for a member
#: token, the member and the purpose are read back from that routing; the one
#: bind, ``:named_refs``, is the references the request names (below).
#:
#: ``install`` is the install when it may act at all: the community's status is
#: one its members use, the install is on, and the operator's registration for
#: its listing is live in this community (on, its publisher on, a container's
#: holding a key set, and not limited to the operations community unless this
#: is it) and the client the token names. That registration is a container's,
#: or a declarative plug-in's for an install pinned to a declarative version: a
#: declarative plug-in is issued no token, and Initiative routes as its install
#: itself, with the scopes the install holds. Every value below is computed from
#: it, so an install that may not act has an empty standing. ``live`` says
#: which.
#:
#: An install is a member of the initiatives it is placed in (narrowed to one
#: when the token names it), and its initiative role is exactly what its scopes
#: allow there: a tool's view key for a read scope on it, its create key for a
#: write scope, and every other key denied, so no member default answers for
#: it. It administers nothing, manages nothing, holds no initiative role a
#: share could name, and carries no grant — unless its token carries a
#: standing (``standing_level``), which only an installation token that asked
#: for one does, and only while the seat's grant still holds that scope:
#: ``initiatives:moderate`` on a token narrowed to an initiative makes it a
#: manager there with "Full access", as a moderator is; ``community:admin`` makes
#: it a guild admin, within the one initiative a narrowed token names. Either is still bounded by
#: its resource scopes, which every tool policy asks first. The community's
#: sign-in rules
#: govern people signing in; an install's admission is the seat's consent, so
#: that value is what ``live`` says.
#:
#: A **member token** names a member (``app.current_user_id``) and the purpose
#: they consented to (``app.token_purpose``). ``install`` then also asks that
#: the member still belongs to the community, their account is active, and
#: their consent for this install and purpose is granted and not revoked (and,
#: when it is bound to an initiative, that the token is narrowed to it). What it
#: reaches is the member's own within the install's: the initiatives the member
#: is in and the install is placed in; there, the keys the member's role
#: permits (a manager role, a stored yes, or a default no stored row turns off)
#: that the scopes also allow, and every other key denied; the member's roles
#: and "Full access" within those initiatives; and writes only when the
#: consent is ``read_write``. It is never an admin, the seat, a grantee or a
#: manager. The consent was given from a session that met the community's
#: sign-in rules, so that value too is what ``live`` says.
#:
#: Two more columns carry what the install calls things, both read only in its
#: own sector (``purpose = 'plugin'``, the routed community and the token's
#: plug-in): ``guild_ref``, its live reference for the community, and
#: ``named_refs``, the references in ``:named_refs`` that name somebody there,
#: as ``{ref: [entity_type, entity_id, member]}``, where ``member`` says
#: whether a person is a member of the community — the profiles an install
#: reads are its members' — which is who a mention the request writes may
#: name. A replaced reference still
#: resolves for its grace window, as ``identity_refs.resolve_ref`` has it. The
#: array chooses which rows are looked up; the sector is the routing's.
INSTALL_STANDING_SQL = f"""
WITH consent AS (
  SELECT c.initiative_id,
         c.granted_access = '{ConsentAccess.read_write.value}' AS writes
  FROM plugin_member_consents c
  WHERE {gucs.USER_ID} IS NOT NULL
    AND c.install_id = {gucs.INSTALL_ID}
    AND c.user_id = {gucs.USER_ID}
    AND c.purpose IS NOT DISTINCT FROM {gucs.TOKEN_PURPOSE}
    AND c.granted_access IS NOT NULL
    AND c.revoked_at IS NULL
    AND (c.initiative_id IS NULL OR c.initiative_id = {gucs.SCOPE_INITIATIVE_ID})
),
install AS (
  SELECT a.id, {ISSUABLE_SCOPES_SQL} AS granted_scopes,
         g.status = '{CommunityStatus.read_only.value}' AS read_only
  FROM guild_plugins a
  JOIN public.guilds g ON g.id = {gucs.GUILD_ID}
  WHERE a.id = {gucs.INSTALL_ID}
    AND a.enabled
    AND g.status IN ({_LIVE_STATUSES_SQL})
    AND EXISTS (
      SELECT 1
      FROM public.plugin_service_registrations r
      JOIN public.publishers p ON p.id = r.publisher_id
      WHERE r.listing_uid = a.listing_uid
        AND r.public_id = {gucs.TOKEN_CLIENT_ID}
        AND (r.kind = '{RegistrationKind.CONTAINER}'
          OR (r.kind = '{RegistrationKind.DECLARATIVE}'
            AND a.definition -> 'service' IS NULL))
        AND {registration_live_sql("r", "p", "g.id")}
    )
    AND ({gucs.USER_ID} IS NULL OR (
      EXISTS (SELECT 1 FROM consent)
      AND EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = {gucs.GUILD_ID} AND m.user_id = {gucs.USER_ID}
          AND {live_membership("m")}
      )
      AND EXISTS (
        SELECT 1
        FROM public.users u
        WHERE u.id = {gucs.USER_ID} AND u.status = '{UserStatus.active.value}'
      )
    ))
),
granted_scope AS (
  SELECT split_part(s.scope, ':', 1) AS resource,
         bool_or(split_part(s.scope, ':', 2) = 'write') AS writes
  FROM install i
  CROSS JOIN LATERAL unnest(i.granted_scopes) AS s(scope)
  WHERE split_part(s.scope, ':', 1) <> '{_PLUGIN_SCOPE_FAMILY}'
    AND s.scope NOT IN ({_STANDING_SCOPES_SQL})
  GROUP BY 1
),
token_scope AS (
  SELECT split_part(t.scope, ':', 1) AS resource,
         bool_or(split_part(t.scope, ':', 2) = 'write') AS writes
  FROM unnest({gucs.TOKEN_SCOPES}) AS t(scope)
  WHERE split_part(t.scope, ':', 1) <> '{_PLUGIN_SCOPE_FAMILY}'
    AND t.scope NOT IN ({_STANDING_SCOPES_SQL})
  GROUP BY 1
),
standing_level AS (
  SELECT
    bool_or(t.scope = '{_MODERATE_SCOPE}')
      AND {gucs.SCOPE_INITIATIVE_ID} IS NOT NULL AS moderates,
    bool_or(t.scope = '{_GUILD_ADMIN_SCOPE}') AS administers
  FROM install i
  CROSS JOIN LATERAL unnest({gucs.TOKEN_SCOPES}) AS t(scope)
  WHERE {gucs.USER_ID} IS NULL
    AND t.scope = ANY (i.granted_scopes)
),
held AS (
  SELECT g.resource,
         g.writes AND t.writes AND NOT i.read_only
           AND ({gucs.USER_ID} IS NULL OR EXISTS (SELECT 1 FROM consent c WHERE c.writes))
           AS writes
  FROM granted_scope g
  JOIN token_scope t ON t.resource = g.resource
  CROSS JOIN install i
),
member_role AS (
  SELECT im.initiative_id, im.role_id,
         COALESCE(r.is_manager, false) AS is_manager,
         COALESCE(r.override_share_restrictions, false) AS overrides
  FROM initiative_members im
  LEFT JOIN initiative_roles r ON r.id = im.role_id
  WHERE {gucs.USER_ID} IS NOT NULL AND im.user_id = {gucs.USER_ID}
),
placed AS (
  SELECT DISTINCT p.initiative_id
  FROM plugin_placements p
  JOIN install i ON i.id = p.install_id
  WHERE ({gucs.SCOPE_INITIATIVE_ID} IS NULL OR p.initiative_id = {gucs.SCOPE_INITIATIVE_ID})
    AND ({gucs.USER_ID} IS NULL OR (
      p.initiative_id IN (SELECT mr.initiative_id FROM member_role mr)
      AND NOT EXISTS (
        SELECT 1 FROM consent c WHERE c.initiative_id <> p.initiative_id
      )
    ))
),
permitted AS (
  SELECT p.initiative_id, k.key
  FROM placed p
  JOIN member_role mr ON mr.initiative_id = p.initiative_id
  CROSS JOIN (VALUES {_permission_default_values()}) AS k(key, is_default)
  WHERE mr.is_manager
     OR EXISTS (
       SELECT 1 FROM initiative_role_permissions rp
       WHERE rp.initiative_role_id = mr.role_id
         AND rp.permission_key = k.key
         AND rp.enabled
     )
     OR (k.is_default AND NOT EXISTS (
       SELECT 1 FROM initiative_role_permissions rp
       WHERE rp.initiative_role_id = mr.role_id
         AND rp.permission_key = k.key
         AND NOT rp.enabled
     ))
),
granted AS (
  SELECT DISTINCT p.initiative_id || ':' || k.key AS pair
  FROM placed p
  CROSS JOIN (VALUES {_tool_permission_values()}) AS k(resource, key, for_write)
  JOIN held h ON h.resource = k.resource AND (h.writes OR NOT k.for_write)
  WHERE {gucs.USER_ID} IS NULL OR EXISTS (
    SELECT 1 FROM permitted pm
    WHERE pm.initiative_id = p.initiative_id AND pm.key = k.key
  )
),
denied AS (
  SELECT DISTINCT p.initiative_id || ':' || k.key AS pair
  FROM placed p
  CROSS JOIN (VALUES {_permission_key_values()}) AS k(key)
  WHERE NOT EXISTS (
    SELECT 1 FROM granted gr WHERE gr.pair = p.initiative_id || ':' || k.key
  )
)
SELECT
  (SELECT EXISTS (SELECT 1 FROM install)) AS live,
{_writes(_INSTALL_STANDING)},
  (
    SELECT r.ref
    FROM public.identity_refs r
    WHERE {_IN_INSTALL_SECTOR}
      AND r.entity_type = '{IdentityEntity.guild.value}'
      AND r.entity_id = {gucs.GUILD_ID}
      AND r.retired_at IS NULL
      AND EXISTS (SELECT 1 FROM install)
  ) AS guild_ref,
  COALESCE((
      SELECT jsonb_object_agg(
        r.ref,
        jsonb_build_array(
          r.entity_type, r.entity_id,
          r.entity_type = '{IdentityEntity.user.value}' AND EXISTS (
            SELECT 1 FROM public.guild_member_profiles p WHERE p.id = r.entity_id
          )
        )
      )
      FROM public.identity_refs r
      WHERE r.ref = ANY(CAST(:named_refs AS text[]))
        AND {_IN_INSTALL_SECTOR}
        AND (r.retired_at IS NULL OR r.retired_at > now() - {_GRACE_INTERVAL})
        AND EXISTS (SELECT 1 FROM install)
    ), '{{}}'::jsonb) AS named_refs
"""


def _standing_fields(context: Any, row: dict[str, Any]) -> dict[str, Any]:
    """The standing keys ``context`` carries, decoded from a standing
    statement's row."""
    names = {f.name for f in fields(context)}
    return {
        guc.bind: guc.decode(row.get(guc.bind))
        for guc in gucs.STANDING
        if guc.bind in names
    }


@dataclass(frozen=True)
class GuildContext:
    """A reader's standing in one community, for one request.

    Built only by the establishment seam (``app.api.deps``): the lookup decides
    the route, the standing statement computes the facts, and this is what it
    returned. Stored on the session beside the routing parameters — it *is*
    part of them — and replayed per transaction with them.

    The rows come from the lookup (which is what decided there was any access
    at all); every scalar below the row fields came back from the standing
    statement, so what Python believes and what the policies read are the same
    values.
    """

    guild: "Guild"
    user_id: int
    #: The community, as a number. Held rather than read off ``guild``: a
    #: cross-guild gather clears the session's identity map between
    #: communities, and which one a standing is for cannot depend on an
    #: object still being attached to a session.
    guild_id: int
    #: The membership row, when there is one. ``None`` for a grantee.
    membership: Optional["GuildMembership"] = None
    #: That row's role, as a value. Held rather than read off the row for the
    #: reason ``guild_id`` is: what somebody is in a community must not depend
    #: on an object still being attached to a session.
    guild_role: Optional[str] = None
    #: The live content grant, when access is by one rather than by membership.
    grant: Optional["AccessGrant"] = None
    #: The live settings grant, independent of content access, and the rung it
    #: confers.
    settings_grant: Optional["AccessGrant"] = None
    settings_grant_level: Optional[str] = None
    #: True when the community is in ``read_only`` status and access is by real
    #: membership: the session is routed into the SELECT-only ``guild_<id>_ro``
    #: role, so content writes are refused by Postgres. Never set on the grant
    #: branch — a grant carries its own read/write level.
    content_read_only: bool = False

    # --- What the standing statement returned --------------------------------
    #: The community the standing was computed for; ``None`` until it has been.
    standing_guild_id: Optional[int] = None
    #: The membership row's role is ``admin`` or ``superadmin``. Computed from
    #: that row by the database; no grant sets it.
    guild_admin: bool = False
    #: ``public.guild_superadmin(guild, user)`` — the membership row's seat, or
    #: a live ``superadmin`` settings grant.
    guild_seat: bool = False
    #: The rung this request administers the community at, or ``None``.
    settings_rung: Optional[str] = None
    #: A live content grant covers this request, at read / read_write.
    pam_read: bool = False
    pam_write: bool = False
    #: A live content grant at ``moderate`` covers it: held content reads.
    pam_moderate: bool = False
    #: The membership row is a guest's, and the request is routed as one.
    guest: bool = False
    #: A guest's initiatives of the items shared with them one at a time.
    guest_item_initiatives: tuple[int, ...] = ()
    member_initiatives: tuple[int, ...] = ()
    manager_initiatives: tuple[int, ...] = ()
    member_role_ids: tuple[int, ...] = ()
    #: ``"<initiative_id>:<permission_key>"`` where the role's row says yes.
    role_grants: tuple[str, ...] = ()
    #: The same, where it says no.
    role_denies: tuple[str, ...] = ()
    #: ``"<initiative_id>:<tool>"`` where the initiative's switch is on.
    enabled_tools: tuple[str, ...] = ()
    #: Initiatives where the reader's role holds "Full access".
    override_initiatives: tuple[int, ...] = ()
    #: The community's sign-in policy is satisfied by this session.
    guild_auth_ok: bool = False
    #: The community's content is on hold for this reader (``read_only``,
    #: reached by membership). The routing already chose ``guild_<id>_ro``
    #: from the same fact; the gates read it here.
    content_hold: bool = False

    # --- Identity ------------------------------------------------------------

    @property
    def role(self) -> "CommunityRole":
        """The seat this request holds in the community.

        A grantee holds ``support`` — a first-class identity for granted access
        rather than a member masquerade. It clears no guard of its own: what of
        the community's configuration a grant reaches is its settings rung,
        read separately.
        """
        if self.guild_role is None:
            return CommunityRole.support
        return CommunityRole(self.guild_role)

    @property
    def is_admin(self) -> bool:
        """Whether this request carries a community admin's authority.

        The membership row's own fact, as the database computed it. A grant
        never answers yes here: what a grant reaches is its own two axes.
        """
        return self.guild_admin

    @property
    def rung(self) -> "CommunityRole":
        """The rung this request administers the community at.

        The membership row's, or the one a live settings grant lends for its
        window. Where :attr:`role` names who somebody *is* here — and answers
        ``support`` for granted access — this names what they may run, which
        is what a decision about the roster or the seat asks.
        """
        if self.membership is None and self.settings_rung is not None:
            return CommunityRole(self.settings_rung)
        return self.role

    def reaches(self, rung: "CommunityRole", *, settings: bool = False) -> bool:
        """Whether this request carries what ``rung`` carries, by the standing.

        The community's ladder asked of a request rather than of a row: the
        seat is what ``guild_superadmin()`` computed, the admin rung is the
        membership row's fact, and the member rung is a membership row.
        ``support`` is below every rung — granted access is its own identity —
        so every request reaches it.

        ``settings`` asks on the community's configuration surface, where a
        settings grant also answers at the rung it lends. Everywhere else the
        rungs above member are the membership row's alone.
        """
        if rung is CommunityRole.superadmin:
            return self.guild_seat and (settings or self.guild_admin)
        if rung is CommunityRole.admin:
            return self.guild_admin or (settings and self.settings_rung is not None)
        if rung is CommunityRole.member:
            return self.guild_role is not None and CommunityRole(
                self.guild_role
            ).reaches(CommunityRole.member)
        return True

    @property
    def reaches_seat(self) -> bool:
        """Whether the community's top seat is within this request's reach.

        Read from what the lookup found — the membership row's role, or the
        rung of a live settings grant — because the routing has to be chosen
        before the standing statement runs. :attr:`seat` is the same question
        answered by ``public.guild_superadmin()`` from the same rows, and is
        what a guard checks once the standing is in.
        """
        return (
            self.guild_role == CommunityRole.superadmin.value
            or self.settings_grant_level == CommunityRole.superadmin.value
        )

    @property
    def routes_as_guest(self) -> bool:
        """Whether the membership row the lookup found is a guest's, which
        routes the request into the community's guest role. :attr:`guest` is
        the same question answered by the standing statement under that role.
        """
        return self.guild_role == CommunityRole.guest.value

    @property
    def is_pam(self) -> bool:
        return self.grant is not None or self.settings_grant is not None

    @property
    def is_settings_only(self) -> bool:
        return self.grant is None and self.settings_grant is not None

    @property
    def grant_writes(self) -> bool:
        """Whether what reaches the community here may change something: a
        membership row, or a grant beside a live ``read_write`` content grant.
        """
        return not self.is_pam or self.pam_write

    @property
    def writes_settings(self) -> bool:
        """Whether this request may change the community configuration it
        reaches: the rung that reaches it, and a membership row or a
        ``read_write`` content grant beside that rung."""
        return self.reaches(CommunityRole.admin, settings=True) and self.grant_writes

    # --- The two grant axes --------------------------------------------------

    @property
    def settings_level(self) -> Optional[str]:
        """The rung a settings grant confers, read off the grant itself."""
        return self.settings_grant_level

    @property
    def grant_content(self) -> Optional[str]:
        """The content grant's level as the database found it: ``read``,
        ``read_write``, ``moderate``, or ``None`` when no live grant covers
        this request."""
        if self.pam_write:
            return "read_write"
        if self.pam_moderate:
            return "moderate"
        return "read" if self.pam_read else None

    def grant_satisfies(
        self, *, access: str = "read", require_owner: bool = False
    ) -> bool:
        """Whether a live content grant covers this request at ``access``.

        A grant never confers ownership — owner-only operations stay on real
        permissions. A read grant satisfies reads; a read_write grant satisfies
        reads and writes.
        """
        if require_owner:
            return False
        if access == "write":
            return self.pam_write
        return self.pam_read or self.pam_write

    def overrides_sharing(self, initiative_id: Optional[int]) -> bool:
        """Whether this request holds "Full access" in ``initiative_id`` — the
        initiative-scoped sibling of the admin leg."""
        if initiative_id is None:
            return False
        return initiative_id in self.override_initiatives

    def membership_only(self) -> "GuildContext":
        """This standing with what a grant reaches taken off.

        For a decision that has to rest on somebody's own place in the
        community rather than on a window somebody opened for them.
        """
        return replace(
            self,
            grant=None,
            settings_grant=None,
            settings_grant_level=None,
            settings_rung=None,
            pam_read=False,
            pam_write=False,
            pam_moderate=False,
        )

    # --- The standing --------------------------------------------------------

    def with_standing(self, row: dict[str, Any]) -> "GuildContext":
        """This context completed with what the standing statement returned."""
        return replace(self, **_standing_fields(self, row))


@dataclass(frozen=True)
class InstallContext:
    """An installed plug-in's standing in its community, for one request.

    Built only by the establishment seam (``app.api.deps``) from a verified
    install: the routing names the community, the install, the client and the
    token's scopes, and the install standing statement computes the rest from
    rows. Stored on the session as part of the routing parameters, and
    replayed per transaction with them, like :class:`GuildContext`.
    """

    guild_id: int
    install_id: int
    #: The registration's ``public_id`` the token was issued to.
    client_id: str
    #: The scopes the token carries. What the install may use is these and
    #: the seat's grant together, which the standing computes.
    token_scopes: frozenset[str]
    #: The one initiative the token is narrowed to, when it is.
    scope_initiative_id: Optional[int] = None
    #: The member a member token acts for, and the purpose they consented to
    #: (``None`` for app-wide consent). ``None`` for the install itself. A write
    #: that names its author, such as the owner grant on something created,
    #: names this member.
    member_user_id: Optional[int] = None
    purpose: Optional[str] = None

    # --- What the install standing statement returned -------------------------
    #: The community the standing was computed for; ``None`` until it has been.
    standing_guild_id: Optional[int] = None
    #: The community is in use, the install is on, and its registration is
    #: live and the client the token names.
    live: bool = False
    #: The community's content is on hold (``read_only`` status).
    content_hold: bool = False
    #: The initiatives the install is placed in, narrowed to one when asked.
    member_initiatives: tuple[int, ...] = ()
    #: ``"<initiative_id>:<permission_key>"`` its scopes allow there.
    role_grants: tuple[str, ...] = ()
    #: Every other key, in the same initiatives.
    role_denies: tuple[str, ...] = ()
    #: ``"<initiative_id>:<tool>"`` where the initiative's switch is on.
    enabled_tools: tuple[str, ...] = ()
    #: For a member token, the member's initiative roles, and the initiatives
    #: where their role holds "Full access", within ``member_initiatives``.
    #: For the install itself, no roles, and "Full access" exactly where its
    #: token holds the moderator standing.
    member_role_ids: tuple[int, ...] = ()
    override_initiatives: tuple[int, ...] = ()
    #: The initiative its token holds the moderator standing in, as a manager
    #: of it. Empty otherwise, and always for a member token.
    manager_initiatives: tuple[int, ...] = ()
    #: Its token holds the guild admin standing. Never for a member token.
    guild_admin: bool = False
    #: The resources its scopes let it read, and write.
    install_read: tuple[str, ...] = ()
    install_write: tuple[str, ...] = ()
    #: What this install calls its community, when it has been named to it.
    guild_ref: Optional[str] = None
    #: The references this request named that resolve in the install's own
    #: sector, as ``(ref, entity_type, entity_id)``. For this request only:
    #: the replay writes the standing, and names nobody.
    named_refs: tuple[tuple[str, str, int], ...] = ()
    #: The members of the community among the people those references name.
    named_members: frozenset[int] = frozenset()

    @property
    def guild_auth_ok(self) -> bool:
        """What the standing wrote for the community's sign-in gate: an install
        that may act answers it."""
        return self.live

    def overrides_sharing(self, initiative_id: Optional[int]) -> bool:
        """Whether the request holds "Full access" in ``initiative_id``: the
        member a member token acts for, by their role, or the install itself,
        by the moderator standing."""
        return initiative_id is not None and initiative_id in self.override_initiatives

    # --- A person's standing, as an install answers it -----------------------
    # A route that serves both actors reads these off whichever context it was
    # handed. Each is what the install standing statement wrote for the key a
    # person's standing sets: an install is never a grantee, it is an admin or
    # a manager only by a standing its token holds, and it is nobody. A member
    # token names its member in ``member_user_id``; what that member's writes
    # own is written by the tool table's trigger, as for the install.

    @property
    def user_id(self) -> None:
        """An install is not a person, even when it acts for one."""
        return None

    @property
    def is_admin(self) -> bool:
        return self.guild_admin

    @property
    def content_read_only(self) -> bool:
        """The community is in ``read_only`` status. The standing leaves the
        install no write scope there; this reports the same hold."""
        return self.content_hold

    @property
    def is_pam(self) -> bool:
        return False

    @property
    def guest(self) -> bool:
        return False

    @property
    def guest_item_initiatives(self) -> tuple[int, ...]:
        return ()

    @property
    def pam_read(self) -> bool:
        return False

    @property
    def pam_write(self) -> bool:
        return False

    @property
    def grant_content(self) -> Optional[str]:
        return None

    def grant_satisfies(
        self, *, access: str = "read", require_owner: bool = False
    ) -> bool:
        return False

    def holds(self, scope: str) -> bool:
        """Whether the standing lets this install use ``scope``: its resource
        among what the token and the seat's grant hold together (write implies
        read), writing only where the standing writes."""
        resource, _, access = scope.partition(":")
        return resource in (
            self.install_write if access == "write" else self.install_read
        )

    def with_standing(self, row: dict[str, Any]) -> "InstallContext":
        """This context completed with what the install standing statement
        returned."""
        return replace(
            self,
            **_standing_fields(self, row),
            live=bool(row.get("live")),
            guild_ref=row.get("guild_ref") or None,
            named_refs=_named_refs(row.get("named_refs")),
            named_members=_named_members(row.get("named_refs")),
        )


#: Who a request that names a plug-in scope is serving: a person's standing in
#: the community, or an installed plug-in's.
ActorContext = GuildContext | InstallContext


def by_a_person(context: ActorContext) -> bool:
    """Whether a person makes this request: through the app or the API, or
    through a plug-in acting for them. A plug-in acting as itself is not one,
    nor is anything that writes with no request (an import, an automation, a
    repeating task's next one)."""
    return not isinstance(context, InstallContext) or context.member_user_id is not None


def _named(value: Any) -> dict[str, list[Any]]:
    """The statement's ``named_refs`` column. The driver hands a ``jsonb``
    column read through ``text()`` back as its text."""
    if not value:
        return {}
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _named_refs(value: Any) -> tuple[tuple[str, str, int], ...]:
    """The statement's ``named_refs`` column as sorted triples."""
    return tuple(
        sorted(
            (str(ref), str(entity_type), int(entity_id))
            for ref, (entity_type, entity_id, *_) in _named(value).items()
        )
    )


def _named_members(value: Any) -> frozenset[int]:
    """The members of the community the ``named_refs`` column names."""
    return frozenset(
        int(entity_id) for _, entity_id, member in _named(value).values() if member
    )


def standing_values(
    context: "GuildContext | InstallContext | None",
) -> dict[gucs.Guc, Any]:
    """The standing ``context`` carries, as the routing statement writes it.

    Nothing for no context, or one whose standing has not been computed — a
    system route, an unattributed context, the window between the routing and
    the standing — so the routing writes every standing key empty. A key the
    context does not carry is written empty too.
    """
    if context is None or context.standing_guild_id is None:
        return {}
    return {guc: getattr(context, guc.bind, None) for guc in gucs.STANDING}


async def compute_guild_standing(session: "AsyncSession") -> dict[str, Any]:
    """Run :data:`STANDING_SQL` and return the row it wrote.

    The routed session has just had every standing key cleared, so what this
    writes is the whole of it. It binds nothing: the user and the community are
    read back from the context the routing statement wrote.
    """
    from sqlalchemy import text

    row = (await session.exec(text(STANDING_SQL))).one()
    return dict(row._mapping)


def named_ref_candidates(values: Sequence[str]) -> list[str]:
    """The strings among ``values`` shaped like a reference an install holds,
    once each: the ``plugin`` purpose's prefix for a person or a community,
    and no longer than a reference can be. What the install standing statement
    is asked to look up."""
    prefixes = tuple(
        f"{ref_prefix(entity, IdentityPurpose.plugin)}_" for entity in IdentityEntity
    )
    return sorted(
        {
            value
            for value in values
            if len(value) <= REF_MAX_LENGTH and value.startswith(prefixes)
        }
    )


async def compute_install_standing(
    session: "AsyncSession", named_refs: Sequence[str] = ()
) -> dict[str, Any]:
    """Run :data:`INSTALL_STANDING_SQL` and return the row it wrote.

    The install and its community are read back from the routing, as
    :func:`compute_guild_standing` reads the person back. ``named_refs`` is
    the one bind: the references the request names, resolved in the same
    statement, in the install's own sector.
    """
    from sqlalchemy import text

    row = (
        await session.exec(
            text(INSTALL_STANDING_SQL).bindparams(
                named_refs=named_ref_candidates(named_refs)
            )
        )
    ).one()
    return dict(row._mapping)
