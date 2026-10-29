"""The authorization functions the guild policies defer to.

Every initiative-scoped table in every ``guild_<id>`` schema carries policies
that call into one of these. They come in two kinds. The four in
:data:`GUILD_AUTHORIZATION_FUNCTIONS` read only guild tables and are rendered
into each guild schema beside the policies that call them (``guild_ddl``), so
a community's access rules live inside its own boundary and a change rolls
out schema by schema with the provisioning stamp. The eight in
:data:`AUTHORIZATION_FUNCTIONS` read shared tables and live in ``public``,
applied once at boot. Both kinds name the tables they read unqualified, so the
routed ``search_path`` binds ``initiative_members`` to the caller's own schema
(see ``search_path_pinning_test``). Each runs as its caller.

The guild four used to live in ``public`` too, one definition for every
community. The migrations that created them there are frozen, so the copies
they left are retired by :func:`drop_public_copies` on boot, after the guild
back-fill has re-rendered every schema's policies against its local copy:
Postgres refuses the drop while any policy still binds a public one, and the
step reads that refusal as "not yet" and tries again next boot.

**Why they are here and not only in a migration.** They used to exist solely
inside the migrations that created them, carried forward by ``CREATE OR
REPLACE`` and copied again into each downgrade. That left the rules the whole
access model rests on with no file to read, nothing to diff against, and no
repair for a deployment whose migration only half-applied. Every other
DB-enforced rule in this codebase is already rendered from app code and
re-applied on boot — the RLS policies from ``initiative_rls``, the frozen
guards from ``frozen``, the search triggers from ``search_index``,
``search_tsmatch`` from ``bootstrap``. These were the exception.

So: this module is the source, :func:`apply_authorization_functions` runs on
every boot, and ``authorization_test`` fails if the database and this file
disagree. Migrations still create them for the upgrade path, importing from
here rather than holding a copy.

**Editing one.** Change the text here and ship it; boot applies it. A change
that alters *behaviour* still wants a migration, so the deployment converges
before it serves rather than at its next restart. That migration states the
new body in full and keeps the one it replaces for its downgrade: a revision
is a record of one moment, and a body read from this module would change what
a past revision does every time this file is edited. ``CREATE OR REPLACE``
keeps the OID, so every policy deferring to the function picks the new body up
unrewritten.

A guild copy is created with the guild schema first on the ``search_path``,
so the tables its body names are resolved and checked at creation. Resolution
at call time is still the caller's route, which is the same schema.
"""

from __future__ import annotations
from collections.abc import Iterable
from app.db import gucs
from app.core.plugin_scopes import PluginScopeResource, tool_resource
from app.core.tools import Tool
from app.models.platform.access_grant import (
    AccessGrantPurpose,
    AccessGrantStatus,
    SettingsLevel,
)
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey
from app.models.tenant.resource_grant import (
    RESOURCE_LEVEL_LADDER,
    WRITE_LEVELS,
    ResourceAccessLevel,
)

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: SQLSTATE 2BP01: Postgres refusing a DROP because something still depends
#: on the object.
DEPENDENT_OBJECTS_STILL_EXIST_SQLSTATE = "2BP01"

__all__ = [
    "AUTHORIZATION_FUNCTIONS",
    "CURRENT_STANDING",
    "GUILD_AUTHORIZATION_FUNCTIONS",
    "IN_BODY",
    "IN_POLICY",
    "Legs",
    "STANDING",
    "STANDING_FIELDS",
    "READ_FUNCTIONS",
    "GUILD_FUNCTION_SIGNATURES",
    "RETIRED_GUILD_FUNCTION_SIGNATURES",
    "GUILD_SUPERADMIN",
    "GUEST_MEMBERSHIP_LIVE",
    "DropReport",
    "plugin_narrowed",
    "plugin_refused",
    "plugin_scope",
    "apply_authorization_functions",
    "authorization_functions_digest",
    "drop_public_copies",
    "ensure_authorization_functions",
    "live_membership",
    "ensure_public_copies_dropped",
    "render_guild_authorization_functions",
    "in_body",
    "standing_arg",
]

#: Gate 0a: the rule itself — does an authentication satisfy one of a
#: community's connections?
#:
#: Takes the facts rather than reading them, so the request path can ask the
#: same question before a session's context exists. ``p_providers`` is what
#: the credential proved; ``p_claims`` is what those providers asserted,
#: ``{"12": {"hd": ["acme.com"]}}``.
GUILD_CONNECTION_ADMITS = """\
CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    WITH effective AS (
        -- What this community said, and the deployment's own answer for a
        -- provider it has said nothing about. One row shadows one row: a
        -- community's own connection replaces the default outright, including
        -- one it wrote with `enabled` off to decline it.
        SELECT c.provider_id, c.enabled, c.claim, c.claim_values
        FROM public.guild_provider_connections c
        WHERE c.guild_id = p_guild_id
        UNION ALL
        SELECT d.provider_id, d.enabled, d.claim, d.claim_values
        FROM public.platform_provider_defaults d
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.guild_provider_connections own
            WHERE own.guild_id = p_guild_id
              AND own.provider_id = d.provider_id
        )
    )
    SELECT EXISTS (
        SELECT 1
        FROM effective c
        WHERE c.enabled
          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)
          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))
          -- A connection names a claim and the values that count, or it
          -- admits nobody. An arrangement that says who belongs by saying
          -- nothing is not one this reads as everybody.
          AND c.claim IS NOT NULL
          AND c.claim_values IS NOT NULL
          AND (
              EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(
                      CASE
                          WHEN jsonb_typeof(
                                   COALESCE(p_claims, '{}'::jsonb)
                                       -> c.provider_id::text -> c.claim
                               ) = 'array'
                          THEN COALESCE(p_claims, '{}'::jsonb)
                                   -> c.provider_id::text -> c.claim
                          ELSE '[]'::jsonb
                      END
                  ) AS asserted(value)
                  WHERE lower(asserted.value) = ANY (
                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted
                  )
              )
          )
    )
$function$

"""


#: Gate 0b: the same question for the current request, off the GUCs the
#: session context sets. This is what the policy legs call.
GUILD_CONNECTION_SATISFIED = f"""\
CREATE OR REPLACE FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer DEFAULT NULL::integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT public.guild_connection_admits(
        p_guild_id,
        -- NULLIF twice: an unset value and the system sentinel both leave
        -- nothing to cast, and a bare ''::int[] would fault every policy on
        -- the table.
        COALESCE(
            string_to_array(
                NULLIF({gucs.SATISFIED_PROVIDERS.text}, 'system'::text),
                ','
            )::integer[],
            ARRAY[]::integer[]
        ),
        COALESCE(
            {gucs.SATISFIED_CLAIMS},
            '{{}}'::jsonb
        ),
        p_provider_id
    )
$function$

"""


#: What this session recorded about how it was opened, as an array.
#:
#: ``app.session_amr`` holds the markers narrowed to the closed vocabulary in
#: ``app.services.auth.assurance`` — ``mfa`` where a code was presented,
#: ``hwk``/``swk`` where a key answered — comma-joined and sorted. One reader
#: rather than the parse repeated in each leg, and one place for the COALESCE:
#: ``string_to_array`` of an unset setting is NULL, and the empty array is what
#: the legs below are written against, so an absent setting reads as a session
#: that recorded nothing.
SESSION_AMR = f"""\
CREATE OR REPLACE FUNCTION public.session_amr()
 RETURNS text[]
 LANGUAGE sql
 STABLE
AS $function$
    SELECT {gucs.SESSION_AMR}
$function$

"""


#: Gate 0, first half: the deployment's own second-factor rule.
#:
#: The level is read from the settings row rather than from a GUC — what the
#: deployment asks is a fact it holds, and the singleton is readable under
#: every routed role, the SELECT-only guild floor included. Which rung the
#: session holds arrives as ``app.platform_role``, because ``public.users`` is
#: not on a guild request's path, and whether the account answers the rule
#: arrives as ``app.platform_factor`` — the second factor it holds, or one
#: this session presented. Both are written with the rest of the request's
#: context.
#:
#: Unset reads as fail-closed: no rung recorded is not ``member``, and no
#: standing recorded is not answered.
PLATFORM_FACTOR_SATISFIED = f"""\
CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR {gucs.PLATFORM_ROLE} IS DISTINCT FROM '{UserRole.member.value}'
          )
          AND ({gucs.PLATFORM_FACTOR}) IS NOT TRUE
    )
$function$

"""


#: Whether a rule that needs an operator-granted option applies to the
#: community: true unless its row shows the option withdrawn. A role that
#: reads no settings sees no row, and is asked the rule as it stands. The
#: sign-in gate asks it here, and the app's queries ask the same function.
GUILD_HOLDS_OPTION = """\
CREATE OR REPLACE FUNCTION public.guild_holds_option(p_guild_id integer, p_option text)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN NOT EXISTS (
        SELECT 1
        FROM public.guild_administration a
        WHERE a.guild_id = p_guild_id
          AND NOT p_option::public.guild_auth_option = ANY(a.auth_options)
    );
END
$function$

"""


#: Gate 0: the guild's sign-in policy, satisfied by this session.
GUILD_AUTH_SATISFIED = f"""\
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        {gucs.USER_ID.text} IS NULL
        OR {gucs.SATISFIED_PROVIDERS.raw} = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1
            FROM public.community_rules p
            -- The requirement that applies: a request routed into one of the
            -- community's guest roles, each granted the guest floor, is asked
            -- what the community asks of its guests.
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.member = to_regrole(current_user)
                      AND m.roleid = to_regrole('guest_base')
                ) AS guest
            ) routed
            -- A requirement is a row, so there is one only where it asks
            -- something.
            WHERE p.guild_id = {gucs.ROUTED_GUILD_ID}
              AND p.user_id IS NULL
              AND p.key = CASE WHEN routed.guest
                  THEN 'guest_auth_policy' ELSE 'auth_policy' END
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  -- Both factor legs apply while the community holds
                  -- ``providers``; the arrival legs apply whatever it holds.
                  OR (
                      'totp' = ANY(p.methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. A rule of its own rather than part of the
            -- requirement, because a community that asks nothing about arrival
            -- holds no requirement and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.community_rules r
            WHERE r.guild_id = {gucs.ROUTED_GUILD_ID}
              AND r.user_id IS NULL
              AND r.key = 'require_second_factor'
              AND r.enabled
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(r.guild_id, 'restrictions')
        ))
$function$

"""

# --- The legs every gate below shares ---------------------------------------
#
# Each is a SQL fragment, written once and substituted into the bodies. They
# read the request's standing — what the establishment seam computed for this
# reader in this community, once, in one statement (``app.db.guild_standing``)
# — rather than walking a table per row.
#
# The four gates that carry them are ``plpgsql`` rather than ``LANGUAGE sql``.
# Each holds a sub-select (the system leg's catalog lookup, and in
# ``resource_access`` the grants probe), which is what stops Postgres inlining
# a SQL function; a SQL function that is not inlined is planned again on every
# query execution that first calls it, and inside another function every call
# is one. A plpgsql function keeps its plan for the session.

#: Trusted system maintenance: work on the system engine's login with nobody
#: routed. A sweep assumes a community's role for its schema, which drops the
#: login's bypass, and this is what says the login was the system engine's.
#: ``session_user`` is the connection's, not the assumed role's. Somebody routed
#: on that login, a person or an install, is read as themselves, so which pool a
#: job draws from never decides what it may read. The sub-select names no row
#: variable, so the planner evaluates it once per statement.
SYSTEM_SESSION = (
    "(EXISTS (SELECT 1 FROM pg_roles r"
    " WHERE r.rolname = session_user AND r.rolbypassrls)"
    f" AND {gucs.USER_ID.text} IS NULL AND {gucs.INSTALL_ID.text} IS NULL)"
)

#: The community this session reads: a member routes with
#: ``app.current_guild_id``, a content grantee with ``app.pam_guild_id`` and a
#: settings grantee with ``app.settings_guild_id``. Whichever names one is the
#: one community the session is in.
ROUTED_COMMUNITY = gucs.ROUTED_COMMUNITY

#: The standing on this session was computed for the community it is routed
#: into. A standing means nothing outside the community it came from —
#: initiative 5 is a different row in every schema — so every leg that reads
#: one says which community it belongs to first.
STANDING_IS_THIS_GUILD = (
    f"{gucs.STANDING_GUILD_ID.text} IS NOT DISTINCT FROM {ROUTED_COMMUNITY}"
)

#: The reader administers this community: the membership row's own answer, as
#: the standing statement read it, written where a policy can read it.
GUILD_ADMIN = f"({STANDING_IS_THIS_GUILD} AND {gucs.GUILD_ADMIN})"

#: This request administers the community's configuration: a live settings
#: grant, at either rung, as the standing statement read it from the rows.
#: Its own axis — what a grant reaches of the community's settings — beside
#: :data:`GUILD_ADMIN`, which only a membership row answers.
SETTINGS_ADMIN = f"({STANDING_IS_THIS_GUILD} AND {gucs.SETTINGS_RUNG.raw} <> ''::text)"

#: This request holds the community's seat: the membership row's superadmin,
#: or a live superadmin settings grant, as the standing statement read it
#: through ``guild_superadmin()``.
GUILD_SEAT = f"({STANDING_IS_THIS_GUILD} AND {gucs.GUILD_SEAT})"

#: A grant that is in force right now: approved and unexpired. Written over the
#: ``access_grants`` alias ``g``; the standing statement and
#: ``guild_superadmin()`` both read grants through it.
LIVE_GRANT = f"g.status = '{AccessGrantStatus.approved.value}' AND g.expires_at > now()"


#: Whether a guest's membership admits them now: before its end, while the
#: platform allows guests, and above the ``guest`` rung only on the demo
#: deployment. ``app_settings`` is one row (``GLOBAL_SETTINGS_ID``).
GUEST_MEMBERSHIP_LIVE = f"""\
CREATE OR REPLACE FUNCTION public.guest_membership_live(p_until timestamp with time zone, p_role guild_role)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN p_until > now() AND EXISTS (
        SELECT 1
        FROM public.app_settings s
        WHERE s.id = 1
          AND s.guests_enabled
          AND (p_role = '{CommunityRole.guest.value}' OR s.demo_mode)
    );
END
$function$

"""


def live_membership(alias: str) -> str:
    """The ``guild_memberships`` row ``alias`` admits its holder now: always
    for a member, and for a guest while :data:`GUEST_MEMBERSHIP_LIVE` says so.
    Every read that decides access from a membership row asks this."""
    return (
        f"({alias}.guest_until IS NULL"
        f" OR public.guest_membership_live({alias}.guest_until, {alias}.role))"
    )


def sql_values(values: Iterable[str]) -> str:
    """``'a', 'b'`` — a value list for an ``IN`` clause.

    Rendered from the enum that owns the vocabulary, the way the tool switches
    are rendered from ``Tool``, so the SQL spells a rung the way Python does
    and a rung added to the ladder reaches every policy on the next render.
    """
    return ", ".join(f"'{value}'" for value in values)


# --- The standing, read once per statement ----------------------------------
#
# The legs above read settings, and a gate asked once per row reads them once
# per row: the system leg's catalog lookup, and each comma list parsed into an
# array again. None of it depends on the row. ``current_standing()`` reads all
# of it once and returns it as one value of type ``public.standing``. A policy
# hands that value to each gate as a sub-select naming no row, which the
# planner evaluates once for the statement, and a gate reads its fields. The
# type is shared; the function is rendered into each guild schema with the
# gates, so a schema's policies still call only that schema's functions.


#: ``public.standing``'s attributes, in order: the name a gate reads, its type,
#: and the leg it is read from. The type is created by a migration, and
#: ``authorization_test`` holds the live type to this list.
def _read(guc: gucs.Guc) -> tuple[str, str, str]:
    """A standing attribute that is one variable, read under its own name."""
    return (guc.bind, guc.kind.value, guc.sql)


STANDING_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("system_session", "boolean", SYSTEM_SESSION),
    ("this_guild", "boolean", STANDING_IS_THIS_GUILD),
    ("guild_admin", "boolean", GUILD_ADMIN),
    _read(gucs.GUILD_AUTH_OK),
    _read(gucs.SCOPE_INITIATIVE_ID),
    _read(gucs.PAM_READ),
    _read(gucs.PAM_WRITE),
    _read(gucs.MEMBER_INITIATIVES),
    _read(gucs.MANAGER_INITIATIVES),
    _read(gucs.OVERRIDE_INITIATIVES),
    _read(gucs.MEMBER_ROLE_IDS),
    _read(gucs.ROLE_GRANTS),
    _read(gucs.ROLE_DENIES),
    _read(gucs.ENABLED_TOOLS),
    # An installed plug-in acting in the community: which install, and the
    # resources its scopes let it read and write. Unset on every request a
    # person makes.
    ("install_id", "integer", gucs.INSTALL_ID.sql),
    _read(gucs.INSTALL_READ),
    _read(gucs.INSTALL_WRITE),
    # The community's content is on hold (``read_only``) for this reader: no
    # change to any of it, whatever their rung. A grant is not held.
    _read(gucs.CONTENT_HOLD),
    # A ``moderate`` content grant covers the request: held content is
    # readable (``app.db.holds``).
    _read(gucs.PAM_MODERATE),
    # A guest's request, and the initiatives of the items shared with them one
    # at a time. Last, as ``ALTER TYPE`` appends.
    _read(gucs.GUEST),
    _read(gucs.GUEST_ITEM_INITIATIVES),
)
_STANDING_NAMES = frozenset(name for name, _type, _expr in STANDING_FIELDS)

#: What a policy passes a gate: this statement's standing. A sub-select that
#: names no row, so the planner evaluates it once per statement.
STANDING = "(SELECT current_standing())"

_STANDING_ROW = ",\n        ".join(expr for _name, _type, expr in STANDING_FIELDS)

#: The standing, read once. ``plpgsql`` like the gates, so its plan is kept.
CURRENT_STANDING = f"""\
CREATE OR REPLACE FUNCTION current_standing()
 RETURNS standing
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ROW(
        {_STANDING_ROW}
    )::public.standing;
END
$function$

"""


_STANDING_TYPES = {name: sqltype for name, sqltype, _expr in STANDING_FIELDS}


def _read_function(name: str, sqltype: str, expr: str) -> str:
    """One value a policy reads once per statement, as a function. A policy
    stores the call instead of the expression; ``plpgsql`` like the gates, so
    its plan is kept and the planner has nothing to inline."""
    return f"""\
CREATE OR REPLACE FUNCTION {name}()
 RETURNS {sqltype}
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ({expr})::{sqltype};
END
$function$

"""


#: ``standing_<field>()`` for each standing field, and ``setting_<bind>()`` for
#: each variable a policy reads with ``Guc.once``.
READ_FUNCTIONS: tuple[tuple[str, str], ...] = tuple(
    (f"standing_{name}", _read_function(f"standing_{name}", sqltype, expr))
    for name, sqltype, expr in STANDING_FIELDS
) + tuple(
    (g.once_function, _read_function(g.once_function, g.kind.value, g.sql))
    for g in gucs.READ_ONCE
)


@dataclass(frozen=True)
class Legs:
    """Every leg, read off a standing. Two readings of the same fields: a gate
    reads its parameter; a policy reads each field as a sub-select naming no
    row, evaluated once for the statement, and computes only that field."""

    standing: str
    #: Inside a policy, a field is its own once-per-statement sub-select
    #: rather than a field of the whole standing, which would compute every
    #: other field alongside it. The sub-select calls the field's
    #: ``standing_<field>()``, so the policy stores a call, not the expression.
    per_field: bool = False

    def field(self, name: str) -> str:
        if name not in _STANDING_NAMES:
            raise ValueError(f"public.standing has no attribute {name!r}")
        if self.per_field:
            # Cast to the field's type: ``x = ANY ((SELECT a))`` would otherwise
            # read as a comparison against a sub-query's rows, not an array.
            return f"((SELECT standing_{name}())::{_STANDING_TYPES[name]})"
        return f"({self.standing}).{name}"

    @property
    def system(self) -> str:
        return self.field("system_session")

    @property
    def this_guild(self) -> str:
        return self.field("this_guild")

    @property
    def admin(self) -> str:
        return self.field("guild_admin")

    @property
    def auth_ok(self) -> str:
        return self.field("guild_auth_ok")

    @property
    def scope(self) -> str:
        return self.field("scope_initiative_id")

    @property
    def pam_read(self) -> str:
        return self.field("pam_read")

    @property
    def pam_write(self) -> str:
        return self.field("pam_write")

    @property
    def install_id(self) -> str:
        return self.field("install_id")

    @property
    def content_hold(self) -> str:
        return self.field("content_hold")

    @property
    def pam_moderate(self) -> str:
        return self.field("pam_moderate")

    @property
    def guest(self) -> str:
        return self.field("guest")

    @property
    def guest_items(self) -> str:
        return self.field("guest_item_initiatives")

    @property
    def pam_any(self) -> str:
        return f"({self.pam_read} OR {self.pam_write})"

    def pam_at_level(self, need_write: str) -> str:
        return (
            f"(CASE WHEN {need_write} THEN {self.pam_write}"
            f" ELSE {self.pam_read} OR {self.pam_write} END)"
        )

    @property
    def system_or_admin(self) -> str:
        return f"({self.system} OR {self.admin})"

    @property
    def unnarrowed_install(self) -> str:
        """An installed plug-in acting in this community on a token that is not
        narrowed to one initiative."""
        return (
            f"({self.install_id} IS NOT NULL AND {self.scope} IS NULL"
            f" AND {self.this_guild} AND {self.auth_ok})"
        )

    @property
    def guild_row_writer(self) -> str:
        """Who changes a row that belongs to the whole community rather than
        one initiative: the guild admin or the system, a live write grant, or
        an installed plug-in on a token not narrowed to one initiative."""
        return (
            f"({self.system_or_admin} OR {self.pam_write} OR {self.unnarrowed_install})"
        )


def standing_arg():
    """This statement's standing, for an app query that asks a gate directly.

    The same once-per-statement sub-select a policy passes, as a SQLAlchemy
    expression.
    """
    from sqlalchemy import func, select

    return select(func.current_standing()).scalar_subquery()


#: Inside a gate's body, the standing is its last parameter.
IN_BODY = Legs("p_st")
#: Inside a policy, the standing is this statement's.
IN_POLICY = Legs(STANDING, per_field=True)

#: The settings rung and the seat, as a policy reads them: once per statement.
#: ``public.standing`` carries neither, so a policy reads them beside it.
POLICY_SETTINGS_ADMIN = (
    f"({IN_POLICY.this_guild} AND {gucs.SETTINGS_RUNG.once} <> ''::text)"
)
POLICY_SEAT = f"({IN_POLICY.this_guild} AND {gucs.GUILD_SEAT.once})"


# --- An installed plug-in's scopes ------------------------------------------
#
# A person's request carries no install, so each of these answers for it with
# its first comparison. Every field is read off the standing, once per
# statement: a sub-select naming no row in a policy, a field of the parameter
# in a gate.


def plugin_scope(resource: str, write: bool, legs: Legs) -> str:
    """An installed plug-in holds ``resource``'s read scope, or its write scope
    when ``write``. ``resource`` is a ``PluginScopeResource`` value."""
    name = PluginScopeResource(getattr(resource, "value", resource)).value
    held = legs.field("install_write" if write else "install_read")
    return f"({legs.install_id} IS NULL OR '{name}' = ANY ({held}))"


def plugin_narrowed(initiative_expr: str, legs: Legs) -> str:
    """A token narrowed to one initiative reaches rows that belong to an
    initiative, and none that belong to the community as a whole.
    ``initiative_access`` already keeps it to the one it names."""
    return (
        f"({legs.install_id} IS NULL OR {legs.scope} IS NULL"
        f" OR {initiative_expr} IS NOT NULL)"
    )


def plugin_refused(legs: Legs) -> str:
    """No installed plug-in reaches the row."""
    return f"({legs.install_id} IS NULL)"


def in_body(sql: str) -> str:
    """A policy predicate, read inside a gate's body instead.

    ``entity_access`` answers each kind with the predicate that kind's own
    policy renders, and inside the function the standing is its parameter: the
    statement's standing becomes ``p_st``, and each field a policy reads on its
    own becomes a field of ``p_st``. The longest field text first, so one that
    contains another is replaced whole.
    """
    swaps = sorted(
        ((IN_POLICY.field(name), IN_BODY.field(name)) for name in _STANDING_NAMES),
        key=lambda pair: -len(pair[0]),
    )
    for policy_text, body_text in swaps:
        sql = sql.replace(policy_text, body_text)
    return sql.replace(STANDING, IN_BODY.standing)


_B = IN_BODY


#: Gate 2: the hard isolation boundary. Every initiative-scoped table's
#: policies defer to this one function.
INITIATIVE_ACCESS = f"""\
CREATE OR REPLACE FUNCTION initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        {_B.auth_ok}
        AND (
            -- The read's own scope, when the surface asking has one. A row of
            -- another initiative is not the answer to the question, whatever
            -- else the context allows. Guild-level rows belong to no
            -- initiative and stay in scope.
            p_initiative_id IS NULL
            OR {_B.scope} IS NULL
            OR p_initiative_id = {_B.scope}
        )
        AND (
            -- Guild-level scope: the row belongs to no initiative, so the
            -- initiative gate has nothing to decide. The schema boundary still
            -- confines it to this guild; grants decide who may read or write it.
            p_initiative_id IS NULL
            OR {_B.system}
            OR {_B.admin}
            OR {_B.pam_at_level("p_need_write")}
            OR ({_B.this_guild}
                AND p_initiative_id = ANY ({_B.field("member_initiatives")}))
            -- A guest's initiatives of the items shared with them one at a
            -- time: sharing (gate 4) still decides which rows.
            OR ({_B.this_guild}
                AND p_initiative_id = ANY ({_B.guest_items}))
        )
    ;
END
$function$

"""

#: Gate 2, narrowed: full standing in the initiative rather than membership.
INITIATIVE_FULL_ACCESS = f"""\
CREATE OR REPLACE FUNCTION initiative_full_access(p_initiative_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        {_B.auth_ok}
        AND (
            {_B.system}
            OR {_B.admin}
            OR {_B.pam_at_level("p_need_write")}
            OR ({_B.this_guild}
                AND p_initiative_id = ANY ({_B.field("override_initiatives")}))
        )
    ;
END
$function$

"""

#: Each tool's view key: all a guest's role permits in an initiative they reach
#: only through items shared with them.
_VIEW_KEYS = sql_values(tool.view_permission for tool in Tool)

#: Gate 3: what a member's role in the initiative permits.
#:
#: The roles' stored rows arrive in the standing as two sets of
#: ``"<initiative>:<key>"`` pairs — the ones the role turns on and the ones it
#: turns off — so the answer is a membership test rather than a three-table
#: join per row. A manager holds every key, stored or not; for everyone else a
#: stored row decides, and the tool's own default decides when there is none.
INITIATIVE_ROLE_PERMITS = f"""\
CREATE OR REPLACE FUNCTION initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        -- A row belonging to no initiative has no initiative role to answer to.
        p_initiative_id IS NULL
        OR {_B.system}
        OR {_B.admin}
        OR {_B.pam_any}
        OR ({_B.this_guild} AND (
                p_initiative_id = ANY ({_B.field("manager_initiatives")})
             OR (p_initiative_id::text || ':' || p_key)
                    = ANY ({_B.field("role_grants")})
             OR (
                 p_default
                 AND p_initiative_id = ANY ({_B.field("member_initiatives")})
                 AND NOT ((p_initiative_id::text || ':' || p_key)
                              = ANY ({_B.field("role_denies")}))
             )
             OR (p_initiative_id = ANY ({_B.guest_items})
                 AND p_key IN ({_VIEW_KEYS}))
        ))
    ;
END
$function$

"""

#: Gate 4: per-resource sharing (the ``resource_grants`` table).
#:
#: Two functions answer it, from one spelling of every leg. ``resource_level``
#: says which rung of the sharing ladder the request holds on a row — what a
#: serializer reports and a route compares against. ``resource_access`` says
#: whether it holds the rung a command needs — what every content policy asks,
#: once per row, and so kept to an existence test rather than a reduction over
#: the matched grants. ``resource_level_test`` holds the two to each other.
#:
#: The one gate that still probes a table, because which readers a resource was
#: shared with is genuinely per resource. What the standing removes is the two
#: reader sub-selects inside it: the roles they hold and the initiatives they
#: are in are the same for every row.

#: The legs that answer the whole question before sharing is consulted. A row
#: that carries no sharing identity (guild vocabulary) has nothing to decide;
#: the system engine, the community's admin and a reader holding "Full access"
#: in the row's initiative reach it whatever its grants say.
FULL_ACCESS = f"""\
p_tool IS NULL
        OR {_B.system}
        OR {_B.admin}
        OR ({_B.this_guild}
            AND p_initiative_id = ANY ({_B.field("override_initiatives")}))"""

#: The grant rows on ``(p_tool, p_resource_id)`` that reach this reader: one
#: naming them, one on an initiative role they hold, one shared with every
#: member of an initiative they are in (or of the community, on a row that
#: belongs to no initiative, unless they are a guest), or one naming the
#: installed plug-in the request is for. Written over the row alias ``g``.
GRANT_REACHES_READER = f"""\
g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (
                   g.user_id = p_user_id
                OR ({_B.this_guild}
                    AND g.role_id = ANY ({_B.field("member_role_ids")}))
                OR (g.all_initiative_members
                    AND {_B.this_guild}
                    AND ((g.initiative_id IS NULL AND NOT {_B.guest})
                         OR g.initiative_id = ANY ({_B.field("member_initiatives")})))
                OR (g.plugin_install_id IS NOT NULL
                    AND g.plugin_install_id = {_B.install_id})
              )"""


def _highest_rung_case() -> str:
    """The highest rung among the matched grant rows, spelled from the ladder:
    one arm per rung above the lowest, and the lowest for any match at all."""
    lowest, *higher = RESOURCE_LEVEL_LADDER
    arms = [
        f"WHEN bool_or(g.level = '{level.value}') THEN '{level.value}'"
        for level in reversed(higher)
    ]
    arms.append(f"WHEN count(*) > 0 THEN '{lowest.value}'")
    return "\n             ".join(arms)


#: The rung the request holds on one row, or NULL for none. A content grant
#: lends its own rung beside whatever the grant rows give, and never owner;
#: nor is a guest ever more than a writer.
RESOURCE_LEVEL = f"""\
CREATE OR REPLACE FUNCTION resource_level(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_st standing)
 RETURNS text
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text;
BEGIN
    IF {FULL_ACCESS}
    THEN
        RETURN CASE WHEN {_B.guest} THEN '{ResourceAccessLevel.write.value}'
                    ELSE '{ResourceAccessLevel.owner.value}' END;
    END IF;
    SELECT CASE
             {_highest_rung_case()}
           END
      INTO v_level
      FROM resource_grants g
     WHERE {GRANT_REACHES_READER};
    IF {_B.pam_write}
       AND v_level IS DISTINCT FROM '{ResourceAccessLevel.owner.value}' THEN
        RETURN '{ResourceAccessLevel.write.value}';
    END IF;
    IF {_B.pam_read} AND v_level IS NULL THEN
        RETURN '{ResourceAccessLevel.read.value}';
    END IF;
    IF {_B.guest} AND v_level = '{ResourceAccessLevel.owner.value}' THEN
        RETURN '{ResourceAccessLevel.write.value}';
    END IF;
    RETURN v_level;
END
$function$

"""

#: Whether the request holds the rung a command needs on one row. A dashboard's
#: grant is ``read`` by constraint, so the level filter answers the write
#: question for it too.
RESOURCE_ACCESS = f"""\
CREATE OR REPLACE FUNCTION resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        {FULL_ACCESS}
        OR {_B.pam_at_level("p_need_write")}
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE {GRANT_REACHES_READER}
              AND (NOT p_need_write OR g.level IN ({sql_values(level.value for level in WRITE_LEVELS)}))
        )
    ;
END
$function$

"""

_WRITE_RUNGS = sql_values(level.value for level in WRITE_LEVELS)
_OWNER = ResourceAccessLevel.owner.value

#: The row can be changed at all: it is not archived or in the trash, and the
#: community is not read-only. (Archiving or trashing an initiative stamps
#: its tools too, so the row's own columns are enough.)
_MAY_CHANGE = f"""(p_archived_at IS NULL AND p_deleted_at IS NULL
        AND NOT {_B.content_hold})"""

#: The request may change the row itself, as the table's write policy answers
#: it for a row naming no initiative (``initiative_rls.direct_or_guild``).
_WRITES_ROW = f"""(p_initiative_id IS NOT NULL
               OR {_B.guild_row_writer})"""

#: The request may change who the resource is shared with: it is the owner,
#: in its own right rather than through an access grant, it may change the row
#: itself, and — if it is an installed plug-in — it holds ``sharing:write`` and
#: the tool's write scope.
_SHARES = f"""(v_level = '{_OWNER}'
        AND NOT {_B.pam_any}
        AND {_WRITES_ROW}
        AND ({_B.install_id} IS NULL
             OR ('{PluginScopeResource.sharing.value}' = ANY ({_B.field("install_write")})
                 AND COALESCE((CASE p_tool
                   {" ".join(f"WHEN '{t.value}' THEN '{tool_resource(t).value}'" for t in Tool)}
                   END) = ANY ({_B.field("install_write")}), false))))"""

#: The actions the request may take on one tool row. The routes check this
#: list before doing anything, and the row's ``can`` reports it to the client,
#: so the two always agree.
#:
#: - ``contribute``: write or owner access, and the row can be changed: the
#:   request may write what the row holds (a calendar's events, a project's
#:   tasks).
#: - ``edit``: as contribute, and the request may change the row itself. A row
#:   that belongs to the whole community rather than one initiative is changed
#:   by the writer its policy names (``Legs.guild_row_writer``).
#: - ``delete``: owner, the row can be changed, and the request may change
#:   the row itself (as ``edit``).
#: - ``share``: as delete, and see ``_SHARES`` above.
#: - ``configure`` (projects): owner or a manager of the initiative who is
#:   not a guest, and the row can be changed.
#: - ``export``: owner, on a row of no initiative or of one the request reads
#:   that does not keep its content in. Allowed even when archived, since
#:   exporting changes nothing.
#: - ``unarchive``: as edit, for a row that was archived on its own. A row
#:   archived because its initiative was archived comes back with the
#:   initiative instead.
RESOURCE_ACTIONS = f"""\
CREATE OR REPLACE FUNCTION resource_actions(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_archived_at timestamp with time zone, p_deleted_at timestamp with time zone, p_st standing)
 RETURNS text[]
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text := resource_level(p_tool, p_resource_id, p_user_id, p_initiative_id, p_st);
    v_actions text[] := ARRAY[]::text[];
BEGIN
    IF v_level IS NULL THEN
        RETURN v_actions;
    END IF;
    IF v_level = '{_OWNER}'
       AND (p_initiative_id IS NULL
            OR EXISTS (SELECT 1 FROM initiatives i
                       WHERE i.id = p_initiative_id AND NOT i.keep_content_in)) THEN
        v_actions := v_actions || 'export'::text;
    END IF;
    IF {_MAY_CHANGE} THEN
        IF v_level IN ({_WRITE_RUNGS}) THEN
            v_actions := v_actions || 'contribute'::text;
            IF {_WRITES_ROW} THEN
                v_actions := v_actions || 'edit'::text;
            END IF;
        END IF;
        IF v_level = '{_OWNER}' AND {_WRITES_ROW} THEN
            v_actions := v_actions || 'delete'::text;
        END IF;
        IF {_SHARES} THEN
            v_actions := v_actions || 'share'::text;
        END IF;
        IF v_level = '{_OWNER}'
           OR ({_B.this_guild} AND NOT {_B.guest}
               AND p_initiative_id = ANY ({_B.field("manager_initiatives")})) THEN
            v_actions := v_actions || 'configure'::text;
        END IF;
    ELSIF p_archived_at IS NOT NULL
          AND NOT {_B.content_hold}
          AND v_level IN ({_WRITE_RUNGS})
          AND {_WRITES_ROW}
          AND (p_initiative_id IS NULL
               OR NOT resource_frozen('initiatives', p_initiative_id)) THEN
        v_actions := v_actions || 'unarchive'::text;
    END IF;
    RETURN v_actions;
END
$function$

"""

#: Whether the request may change who a resource is shared with. The same
#: rule as ``share`` in :data:`RESOURCE_ACTIONS`, for the policies on
#: ``resource_grants``. It skips the archived/trashed check, which those rows
#: already get from ``app.db.frozen``.
RESOURCE_SHARES = f"""\
CREATE OR REPLACE FUNCTION resource_shares(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text := resource_level(p_tool, p_resource_id, p_user_id, p_initiative_id, p_st);
BEGIN
    RETURN NOT {_B.content_hold} AND {_SHARES};
END
$function$

"""


def _author_arms() -> str:
    return "\n".join(
        f"      WHEN '{tool.value}' THEN\n"
        f"        SELECT created_by INTO v_author FROM {tool.plural} WHERE id = p_resource_id;"
        for tool in Tool
    )


#: Whether ``p_user_id`` wrote this resource and nobody owns it now. Lets an
#: owner row be written that gives unowned content back to its author (trash
#: restore does this), by someone who is not its owner.
RESOURCE_RECLAIMABLE = f"""\
CREATE OR REPLACE FUNCTION resource_reclaimable(p_tool text, p_resource_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_author integer;
BEGIN
    CASE p_tool
{_author_arms()}
      ELSE
        RETURN false;
    END CASE;
    RETURN v_author IS NOT NULL
       AND v_author = p_user_id
       AND NOT EXISTS (
           SELECT 1 FROM resource_grants g
           WHERE g.resource_type = p_tool
             AND g.resource_id = p_resource_id
             AND g.level = '{_OWNER}'
       );
END
$function$

"""

#: The people each resource in ``p_resource_ids`` is shared with, as
#: ``(resource_id, user_id)`` rows. ``permissions.audience`` narrows it to who
#: can open the resource now (``named_people.readers_of``), for who gets a
#: notification and who a post counts as its readers.
#:
#: Someone is included when a grant names them, names a role they hold, or is
#: shared with everyone in the initiative — and only while they are still a
#: member of it. A guest given the resource itself is included without being
#: in its initiative. For a resource in no initiative, "everyone" means the
#: community's members (``p_guild_id``), not its guests. Community admins and
#: access-grant holders are not included unless a grant names them.
RESOURCE_AUDIENCE = f"""\
CREATE OR REPLACE FUNCTION resource_audience(p_tool text, p_resource_ids integer[], p_guild_id integer)
 RETURNS TABLE(resource_id integer, user_id integer)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN QUERY
    SELECT DISTINCT g.resource_id, im.user_id
      FROM resource_grants g
      JOIN initiative_members im
        ON im.initiative_id = g.initiative_id
       AND (g.user_id = im.user_id
            OR g.role_id = im.role_id
            OR g.all_initiative_members)
     WHERE g.resource_type = p_tool
       AND g.resource_id = ANY (p_resource_ids)
       AND g.initiative_id IS NOT NULL
    UNION
    SELECT DISTINCT g.resource_id, m.user_id
      FROM resource_grants g
      JOIN public.guild_memberships m
        ON m.guild_id = p_guild_id
       AND m.user_id = g.user_id
       AND m.role = '{CommunityRole.guest.value}'
     WHERE g.resource_type = p_tool
       AND g.resource_id = ANY (p_resource_ids)
       AND g.initiative_id IS NOT NULL
    UNION
    SELECT DISTINCT g.resource_id, m.user_id
      FROM resource_grants g
      JOIN public.guild_memberships m
        ON m.guild_id = p_guild_id
       AND (g.user_id = m.user_id
            OR (g.all_initiative_members
                AND m.role <> '{CommunityRole.guest.value}'))
     WHERE g.resource_type = p_tool
       AND g.resource_id = ANY (p_resource_ids)
       AND g.initiative_id IS NULL;
END
$function$

"""

#: Whether a grant row gives the request access to the resource — grants
#: only, ignoring admin, "Full access" and access grants. Lists that span
#: initiatives show only what was shared with the reader
#: (``permissions.granted_scope_clause``). With ``p_need_write`` the grant must
#: allow editing.
RESOURCE_GRANTED = f"""\
CREATE OR REPLACE FUNCTION resource_granted(p_tool text, p_resource_id integer, p_user_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM resource_grants g
        WHERE {GRANT_REACHES_READER}
          AND (NOT p_need_write OR g.level IN ({_WRITE_RUNGS}))
    );
END
$function$

"""


def _initiative_tool_actions() -> str:
    """Two checks per tool, only when the initiative has the tool switched on:
    ``view:<tool>`` if the reader's role allows viewing it, and
    ``create:<tool>`` if the role allows creating it, the community is not
    read-only, and the reader is not here through an access grant (those can
    edit existing things but not create new ones)."""
    arms = []
    for tool in Tool:
        switch = f"v_initiative.{tool.view_permission}"
        view_default = str(
            DEFAULT_PERMISSION_VALUES[PermissionKey(tool.view_permission)]
        ).lower()
        create_default = str(
            DEFAULT_PERMISSION_VALUES[PermissionKey(tool.create_permission)]
        ).lower()
        arms.append(
            f"""    IF {switch} THEN
        IF initiative_role_permits(p_initiative_id, p_user_id, '{tool.view_permission}', {view_default}, p_st) THEN
            v_actions := v_actions || 'view:{tool.value}'::text;
        END IF;
        IF NOT {_B.content_hold} AND NOT {_B.pam_any}
           AND initiative_role_permits(p_initiative_id, p_user_id, '{tool.create_permission}', {create_default}, p_st) THEN
            v_actions := v_actions || 'create:{tool.value}'::text;
        END IF;
    END IF;"""
        )
    return "\n".join(arms)


#: The actions the request may take in one initiative, for the initiative's
#: ``can``:
#:
#: - ``manage``: change its settings, members and roles — a community admin
#:   or one of its managers who is not a guest.
#: - ``moderate``: act on its moderation reports — "Full access" or a
#:   community admin (:data:`INITIATIVE_FULL_ACCESS`), never a guest.
#: - ``roster``: read who is in it — a member (a guest in it included), a
#:   community admin or a grantee; not a guest given items in it.
#: - ``view:<tool>`` and ``create:<tool>`` per tool.
INITIATIVE_ACTIONS = f"""\
CREATE OR REPLACE FUNCTION initiative_actions(p_initiative_id integer, p_user_id integer, p_st standing)
 RETURNS text[]
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_initiative initiatives%ROWTYPE;
    v_actions text[] := ARRAY[]::text[];
BEGIN
    SELECT * INTO v_initiative FROM initiatives WHERE id = p_initiative_id;
    IF NOT FOUND THEN
        RETURN v_actions;
    END IF;
    IF {_B.system} OR {_B.admin}
       OR ({_B.this_guild} AND NOT {_B.guest}
           AND p_initiative_id = ANY ({_B.field("manager_initiatives")})) THEN
        v_actions := v_actions || 'manage'::text;
    END IF;
    IF NOT {_B.guest} AND initiative_full_access(p_initiative_id, true, p_st) THEN
        v_actions := v_actions || 'moderate'::text;
    END IF;
    IF {_B.system} OR {_B.admin} OR {_B.pam_any}
       OR ({_B.this_guild}
           AND p_initiative_id = ANY ({_B.field("member_initiatives")})) THEN
        v_actions := v_actions || 'roster'::text;
    END IF;
{_initiative_tool_actions()}
    RETURN v_actions;
END
$function$

"""

#: Who holds a guild's top seat — its sign-in configuration and its billing.
#:
#: Named ``public.guild_memberships`` in full, unlike its neighbours: this one
#: answers about a shared table rather than a guild-local one, so it resolves
#: the same way from a routed session and an unrouted one.
#:
#: Not ``SECURITY DEFINER``, like everything else here: it runs as its caller
#: and reads what that caller may read. ``guild_memberships_select`` admits a
#: session its own rows and, when routed, the addressed guild's — which covers
#: both questions asked of this: "am I the seat here" on the platform path, and
#: "is the writer the seat" from inside a policy.
#:
#: A live ``superadmin`` settings grant satisfies the same predicate for the
#: duration of its grant.
#:
#: The one definition of the rule. The seat's policies on ``community_rules`` call
#: it, and so does the app — ``func.guild_superadmin(...)`` where an endpoint
#: has to decide before it writes, the way ``initiative_scope_clause`` already
#: defers to ``initiative_access`` rather than restating it in Python.
GUILD_SUPERADMIN = f"""\
CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = '{CommunityRole.superadmin.value}'
          AND {live_membership("m")}
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = '{AccessGrantPurpose.settings.value}'
          AND g.access_level = '{SettingsLevel.superadmin.value}'
          AND {LIVE_GRANT}
    )
$function$

"""


#: Name -> definition, in dependency order: ``guild_auth_satisfied`` calls
#: ``guild_holds_option``, ``guild_connection_satisfied``
#: calls ``guild_connection_admits``, ``guild_auth_satisfied`` calls
#: ``guild_connection_satisfied``, ``session_amr`` and
#: ``platform_factor_satisfied``, and
#: ``initiative_access`` and ``initiative_full_access`` call
#: ``guild_auth_satisfied``. Applied in this order, a fresh database never
#: sees a dangling call.
AUTHORIZATION_FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("guild_holds_option", GUILD_HOLDS_OPTION),
    ("guild_connection_admits", GUILD_CONNECTION_ADMITS),
    ("guild_connection_satisfied", GUILD_CONNECTION_SATISFIED),
    ("session_amr", SESSION_AMR),
    ("platform_factor_satisfied", PLATFORM_FACTOR_SATISFIED),
    ("guild_auth_satisfied", GUILD_AUTH_SATISFIED),
    ("guest_membership_live", GUEST_MEMBERSHIP_LIVE),
    ("guild_superadmin", GUILD_SUPERADMIN),
)

#: The ones that read only guild tables. Rendered into every guild schema by
#: ``guild_ddl.render_guild_rls_ddl`` ahead of the policies that call them,
#: in this order: the SQL bodies are checked at creation, and each names only
#: tables and the ``public`` functions above.
#: Whether this statement reads what the platform holds (``app.db.holds``):
#: the system engine, or a ``moderate`` content grantee. One function, so each
#: holdable table's policy names one once-per-statement call.
READS_HELD = """\
CREATE OR REPLACE FUNCTION reads_held()
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN standing_system_session() OR standing_pam_moderate();
END
$function$

"""

GUILD_AUTHORIZATION_FUNCTIONS: tuple[tuple[str, str], ...] = (
    *READ_FUNCTIONS,
    ("current_standing", CURRENT_STANDING),
    ("reads_held", READS_HELD),
    ("initiative_access", INITIATIVE_ACCESS),
    ("initiative_full_access", INITIATIVE_FULL_ACCESS),
    ("initiative_role_permits", INITIATIVE_ROLE_PERMITS),
    ("resource_level", RESOURCE_LEVEL),
    ("resource_access", RESOURCE_ACCESS),
    ("resource_actions", RESOURCE_ACTIONS),
    ("resource_shares", RESOURCE_SHARES),
    ("resource_granted", RESOURCE_GRANTED),
    ("resource_reclaimable", RESOURCE_RECLAIMABLE),
    ("resource_audience", RESOURCE_AUDIENCE),
    ("initiative_actions", INITIATIVE_ACTIONS),
)

#: Argument types of every function that lives in a guild schema — the five
#: above plus the three ``frozen`` and ``initiative_rls`` render there. What
#: ``DROP FUNCTION`` and ``pg_get_functiondef`` need to name one.
GUILD_FUNCTION_SIGNATURES: dict[str, str] = {
    **{name: "()" for name, _sql in READ_FUNCTIONS},
    "current_standing": "()",
    "reads_held": "()",
    "initiative_access": "(integer, integer, boolean, public.standing)",
    "initiative_full_access": "(integer, boolean, public.standing)",
    "initiative_role_permits": "(integer, integer, text, boolean, public.standing)",
    "resource_level": "(text, integer, integer, integer, public.standing)",
    "resource_access": "(text, integer, integer, integer, boolean, public.standing)",
    "resource_actions": "(text, integer, integer, integer, timestamp with time zone, timestamp with time zone, public.standing)",
    "resource_shares": "(text, integer, integer, integer, public.standing)",
    "resource_granted": "(text, integer, integer, boolean, public.standing)",
    "resource_reclaimable": "(text, integer, integer)",
    "resource_audience": "(text, integer[], integer)",
    "initiative_actions": "(integer, integer, public.standing)",
    "resource_frozen": "(text, bigint, boolean)",
    "resource_frozen_for_grant": "(text, bigint, boolean)",
    "entity_access": "(text, integer, boolean, boolean, public.standing)",
    "entity_initiative": "(text, integer)",
    "content_item_of": "(text, integer, jsonb)",
}

#: Functions an earlier render put in a guild schema under a name or
#: signature this one no longer produces. The RLS render drops them last,
#: the template strip drops them with the rest, and the boot step that
#: retires ``public`` copies tries these names too.
RETIRED_GUILD_FUNCTION_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("relationship_endpoint_access", "(text, integer, boolean)"),
    # The gates before they took the statement's standing.
    ("initiative_access", "(integer, integer, boolean)"),
    ("initiative_full_access", "(integer, boolean)"),
    ("initiative_role_permits", "(integer, integer, text, boolean)"),
    ("resource_access", "(text, integer, integer, integer, boolean)"),
    ("entity_access", "(text, integer, boolean, boolean)"),
)


def render_guild_authorization_functions() -> str:
    """The guild functions as schema-relative DDL, for the RLS render.

    Each text is one statement; the render is a script, so each is
    terminated here.
    """
    return "\n".join(sql.rstrip() + ";" for _name, sql in GUILD_AUTHORIZATION_FUNCTIONS)


def authorization_functions_digest() -> str:
    """A stable hash of every definition here.

    For a caller that wants to know whether this file changed without diffing
    five function bodies — the same idea as the provisioning stamp, which
    hashes what it renders rather than tracking a version by hand.
    """
    digest = hashlib.sha256()
    for name, sql in AUTHORIZATION_FUNCTIONS + GUILD_AUTHORIZATION_FUNCTIONS:
        digest.update(name.encode())
        digest.update(sql.encode())
    return digest.hexdigest()[:16]


async def apply_authorization_functions(conn: "AsyncConnection") -> None:
    """Create or replace every function in :data:`AUTHORIZATION_FUNCTIONS`.

    Idempotent, and cheap enough to run unconditionally on boot: eight
    ``CREATE OR REPLACE`` statements against ``public``. ``CREATE OR REPLACE``
    keeps each function's OID, so the policies that reference it are untouched
    and no guild schema needs re-rendering.

    Runs on the provisioning engine, which owns these objects.
    """
    from sqlalchemy import text

    for _name, sql in AUTHORIZATION_FUNCTIONS:
        await conn.execute(text(sql))


async def ensure_authorization_functions() -> None:
    """Apply the functions on boot, over the provisioning engine.

    Called after the migrations and before the guild back-fill, so a schema
    rendered in the same boot finds every ``public`` function its own copies
    call. Eight ``CREATE OR REPLACE`` statements on a healthy database — the
    same unconditional-and-cheap shape as the grant heals either side of it.
    """
    from app.db import session as db_session

    async with db_session.provisioning_engine.begin() as conn:
        await apply_authorization_functions(conn)


@dataclass
class DropReport:
    """What :func:`drop_public_copies` did with each of the seven."""

    dropped: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    #: name -> how many policies or triggers still bind the ``public`` copy
    blocked: dict[str, int] = field(default_factory=dict)


_DEPENDENTS_SQL = """
SELECT count(*) FROM pg_depend d
WHERE d.refclassid = 'pg_proc'::regclass
  AND d.refobjid = CAST(:sig AS regprocedure)
  AND d.deptype = 'n'
"""


async def drop_public_copies(engine: "AsyncEngine") -> DropReport:
    """Retire the ``public`` copies of the seven guild functions.

    Runs after the guild back-fill. Each drop is its own transaction: a copy
    still bound by a policy or trigger in a schema the back-fill has not
    re-rendered is refused by Postgres, recorded with its dependent count, and
    left for the next boot; the others are dropped. A copy that is already
    gone is reported as absent. Nothing here touches a guild schema.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db.errors import dbapi_sqlstate

    report = DropReport()
    for name, args in (
        *GUILD_FUNCTION_SIGNATURES.items(),
        *RETIRED_GUILD_FUNCTION_SIGNATURES,
    ):
        sig = f"public.{name}{args}"
        async with engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
                    {"sig": sig},
                )
            ).scalar()
        if not exists:
            report.absent.append(name)
            continue
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"DROP FUNCTION {sig}"))
        except DBAPIError as exc:
            if dbapi_sqlstate(exc) != DEPENDENT_OBJECTS_STILL_EXIST_SQLSTATE:
                raise
            async with engine.connect() as conn:
                count = (
                    await conn.execute(text(_DEPENDENTS_SQL), {"sig": sig})
                ).scalar()
            report.blocked[name] = int(count or 0)
            continue
        report.dropped.append(name)
    return report


async def ensure_public_copies_dropped() -> DropReport:
    """The boot step, over the provisioning engine (the copies' owner)."""
    from app.db import session as db_session

    return await drop_public_copies(db_session.provisioning_engine)
