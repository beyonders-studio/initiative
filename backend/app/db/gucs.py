"""The request's session variables, and the one way SQL reads each of them.

A routing writes these (``app.db.session``), the standing statement fills the
standing (``app.db.guild_standing``), and every policy, gate and trigger reads
them. Each variable is declared here once, with its kind, and each read is
rendered from that declaration: a policy, a gate body and a trigger reading
``app.current_user_id`` all spell it the same way, and a module that needs one
imports it rather than writing its own.

The spelling is the one ``pg_get_expr`` and ``pg_get_functiondef`` report
(``'app.x'::text``, ``''::text``), so a rendered body reads back unchanged.

A ``Guc`` formats as its typed read, so ``f"{USER_ID}"`` is the reader's id.
The other readings:

``raw``
    ``current_setting`` itself: NULL when the variable was never written, and
    whatever text it holds otherwise.
``text``
    The same with ``''`` read as NULL, since a routing writes ``''`` for
    "nothing" in every variable it does not set.
``once``
    The typed read as a sub-select naming no row, which the planner evaluates
    once for the statement rather than once per row. For a policy. The
    sub-select calls ``setting_<bind>()``, a function rendered into each guild
    schema, so a policy stores a call rather than the read itself; only a
    variable declared ``read_once`` has one.

A boolean reads true only when the variable says ``true``, and NULL when it is
unset. A leg that asks for "not true" says ``IS NOT TRUE`` so an unset
variable answers the same way an explicit ``false`` does.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "FLAGS",
    "Guc",
    "Kind",
    "READ_ONCE",
    "REQUEST_GUCS",
    "ROUTED_COMMUNITY",
    "ROUTED_GUILD_ID",
    "STANDING",
]


class Kind(Enum):
    """How a variable's text is read, and the SQL type the read has."""

    INT = "integer"
    BOOL = "boolean"
    TEXT = "text"
    #: A comma list of ids.
    IDS = "integer[]"
    #: A comma list of names, or of ``"<id>:<name>"`` pairs.
    NAMES = "text[]"
    JSON = "jsonb"


@dataclass(frozen=True)
class Guc:
    """One session variable."""

    name: str
    kind: Kind
    #: Written by a standing statement rather than by the routing alone.
    standing: bool = False
    #: A policy reads it with :attr:`once`, so each guild schema renders its
    #: ``setting_<bind>()``.
    read_once: bool = False

    @property
    def raw(self) -> str:
        return f"current_setting('{self.name}'::text, true)"

    @property
    def text(self) -> str:
        return f"NULLIF({self.raw}, ''::text)"

    @property
    def sql(self) -> str:
        kind = self.kind
        if kind is Kind.BOOL:
            return f"{self.raw} = 'true'::text"
        if kind is Kind.TEXT:
            return self.text
        if kind is Kind.IDS:
            return (
                f"COALESCE(string_to_array({self.text}, ','::text)::integer[],"
                " ARRAY[]::integer[])"
            )
        if kind is Kind.NAMES:
            return f"COALESCE(string_to_array({self.text}, ','::text), ARRAY[]::text[])"
        return f"{self.text}::{kind.value}"

    @property
    def once(self) -> str:
        if not self.read_once:
            raise ValueError(f"{self.name} is not declared read_once")
        # Cast to the kind's type: ``x = ANY ((SELECT a))`` would otherwise
        # read as a comparison against a sub-query's rows, not an array.
        return f"((SELECT {self.once_function}())::{self.kind.value})"

    @property
    def once_function(self) -> str:
        """The guild-schema function :attr:`once` calls."""
        return f"setting_{self.bind}"

    def __str__(self) -> str:
        return self.sql

    # --- Writing and reading back ------------------------------------------

    @property
    def bind(self) -> str:
        """The variable's name without its ``app.`` prefix: the bind parameter
        a routing writes it with, and the column a standing statement returns
        it as."""
        return self.name.removeprefix("app.")

    @property
    def empty(self) -> str:
        """What a routing writes where it has nothing to say."""
        return "false" if self.kind is Kind.BOOL else ""

    def encode(self, value: Any) -> str:
        """``value`` as the text the variable holds. ``None`` is :attr:`empty`.

        A set is written sorted, so one value always writes one string.
        """
        if value is None:
            return self.empty
        kind = self.kind
        if kind is Kind.BOOL:
            return "true" if value else "false"
        if kind is Kind.INT:
            return str(int(value))
        if kind is Kind.JSON:
            return (
                json.dumps(value, separators=(",", ":"), sort_keys=True)
                if value
                else ""
            )
        if kind in (Kind.IDS, Kind.NAMES):
            items = sorted(value) if isinstance(value, (set, frozenset)) else value
            return ",".join(str(item) for item in items)
        return str(value)

    def decode(self, text: str | None) -> Any:
        """The value a variable's text says, as :meth:`encode` wrote it."""
        kind = self.kind
        if kind is Kind.BOOL:
            return text == "true"
        if kind is Kind.INT:
            return int(text) if text else None
        if kind is Kind.JSON:
            return json.loads(text) if text else None
        if kind is Kind.IDS:
            return tuple(int(part) for part in _parts(text))
        if kind is Kind.NAMES:
            return tuple(_parts(text))
        return text or None


def _parts(text: str | None) -> Collection[str]:
    return [part for part in (text or "").split(",") if part]


# --- Who the request is -------------------------------------------------------
USER_ID = Guc("app.current_user_id", Kind.INT, read_once=True)
#: The community a membership routes into.
GUILD_ID = Guc("app.current_guild_id", Kind.INT, read_once=True)
#: The community a content grant reaches.
PAM_GUILD_ID = Guc("app.pam_guild_id", Kind.INT)
#: The community a settings grant reaches.
SETTINGS_GUILD_ID = Guc("app.settings_guild_id", Kind.INT)
#: The community the billing role was routed to.
BILLING_GUILD_ID = Guc("app.billing_guild_id", Kind.INT)
PLATFORM_ROLE = Guc("app.platform_role", Kind.TEXT)
#: The account answers the deployment's own second-factor rule.
PLATFORM_FACTOR = Guc("app.platform_factor", Kind.BOOL)

# --- How the session signed in ------------------------------------------------
#: The providers the credential proved, comma-joined, or the ``system``
#: sentinel for user-attributed system work.
SATISFIED_PROVIDERS = Guc("app.satisfied_providers", Kind.TEXT)
#: What those providers asserted, ``{"<provider id>": {claim: [values]}}``.
SATISFIED_CLAIMS = Guc("app.satisfied_claims", Kind.JSON)
#: The assurance markers the credential recorded.
SESSION_AMR = Guc("app.session_amr", Kind.NAMES)

# --- What narrows the read ----------------------------------------------------
SCOPE_INITIATIVE_ID = Guc("app.scope_initiative_id", Kind.INT)
#: The statement is reader-written, on the query surface.
QUERY = Guc("app.query", Kind.BOOL, read_once=True)

# --- An installed plug-in -----------------------------------------------------
INSTALL_ID = Guc("app.current_install_id", Kind.INT)
TOKEN_CLIENT_ID = Guc("app.token_client_id", Kind.TEXT)
TOKEN_SCOPES = Guc("app.token_scopes", Kind.NAMES)
TOKEN_PURPOSE = Guc("app.token_purpose", Kind.TEXT)

# --- The standing -------------------------------------------------------------
#: The community the standing was computed for.
STANDING_GUILD_ID = Guc("app.standing_guild_id", Kind.INT, standing=True)
GUILD_ADMIN = Guc("app.guild_admin", Kind.BOOL, standing=True)
GUILD_SEAT = Guc("app.guild_seat", Kind.BOOL, standing=True, read_once=True)
#: The rung a live settings grant lends, or ``''``.
SETTINGS_RUNG = Guc("app.settings_rung", Kind.TEXT, standing=True, read_once=True)
#: A live content grant covers the request, at read / read_write.
PAM_READ = Guc("app.pam_read", Kind.BOOL, standing=True)
PAM_WRITE = Guc("app.pam_write", Kind.BOOL, standing=True)
MEMBER_INITIATIVES = Guc("app.member_initiatives", Kind.IDS, standing=True)
MANAGER_INITIATIVES = Guc("app.manager_initiatives", Kind.IDS, standing=True)
MEMBER_ROLE_IDS = Guc("app.member_role_ids", Kind.IDS, standing=True)
#: ``"<initiative id>:<permission key>"`` where the role's row says yes / no.
ROLE_GRANTS = Guc("app.role_grants", Kind.NAMES, standing=True)
ROLE_DENIES = Guc("app.role_denies", Kind.NAMES, standing=True)
#: ``"<initiative id>:<tool>"`` where the initiative's switch is on.
ENABLED_TOOLS = Guc("app.enabled_tools", Kind.NAMES, standing=True)
#: Initiatives where the reader's role holds "Full access".
OVERRIDE_INITIATIVES = Guc("app.override_initiatives", Kind.IDS, standing=True)
#: The community's sign-in policy is satisfied by this session.
GUILD_AUTH_OK = Guc("app.guild_auth_ok", Kind.BOOL, standing=True)
#: The resources an installed plug-in's scopes let it read, and write.
INSTALL_READ = Guc("app.install_read", Kind.NAMES, standing=True)
INSTALL_WRITE = Guc("app.install_write", Kind.NAMES, standing=True)
#: The community's content is on hold (``read_only``) for this reader.
CONTENT_HOLD = Guc("app.content_hold", Kind.BOOL, standing=True)
#: A live content grant at ``moderate`` covers the request: it may read what
#: the platform holds (``app.db.holds``). Never set by membership.
PAM_MODERATE = Guc("app.pam_moderate", Kind.BOOL, standing=True)
#: The membership row's rung is ``guest``: the request is a guest's.
GUEST = Guc("app.guest", Kind.BOOL, standing=True)
#: A guest's initiatives of the items shared with them one at a time. Empty
#: for everyone else.
GUEST_ITEM_INITIATIVES = Guc("app.guest_item_initiatives", Kind.IDS, standing=True)
#: The surfaces the deployment has closed for the community: the ``surface.*``
#: keys of ``app.core.rules`` whose deployment row says off.
CLOSED_SURFACES = Guc("app.closed_surfaces", Kind.NAMES, standing=True)
#: ``"<tool>=on"`` / ``"<tool>=off"`` where the community set a tool's switch
#: for every initiative in it (``app.models.tenant.initiative.INITIATIVE_TOOL_KEYS``).
COMMUNITY_TOOLS = Guc("app.community_tools", Kind.NAMES, standing=True)
#: The admin surfaces the reader holds here
#: (``app.models.platform.guild.AdminSurface``): every one for the admin
#: rung, none below it.
HELD_SURFACES = Guc("app.held_surfaces", Kind.NAMES, standing=True)

# --- Somebody who filed a case ------------------------------------------------
#: The tasks of the cases the routed account filed, read by the filer seam
#: through the filer role's own row on ``intake_cases``. What the filer
#: policies on a case's task and its comments admit, so neither has to read
#: ``intake_cases`` back — whose own policy reads ``tasks``.
FILER_CASES = Guc("app.filer_cases", Kind.IDS, read_once=True)

# --- Per-transaction flags ----------------------------------------------------
#: Transaction-local flag marking a transaction as a purge.
#:
#: Purge is the one lifecycle step that writes frozen content rather than only
#: removing it: a file being purged leaves references behind in the files
#: that pointed at it, and those are unlinked before the row goes — including
#: in files that are themselves in the trash, which would otherwise be
#: restored holding a link to nothing.
#:
#: Raised by ``hard_purge_entity`` with ``app.db.session.raise_flag``, so it
#: lasts one transaction and never reaches a pooled connection.
PURGING = Guc("app.purging", Kind.BOOL)

#: Transaction-local flag marking a transaction as a restructure of the board a
#: frozen row sits on.
#:
#: Retiring or recategorising a status column moves every task in it: the ones
#: still live, and the ones archived or in the trash, which have to land
#: somewhere too. The frozen task is not being edited — where it hangs is
#: changing, and it keeps its stamp — so the row guards let the write through
#: while this is set. The ancestry guards do not read it: nothing about a column
#: can put a task under a different project or initiative.
#:
#: Retiring a task type moves its tasks to another type the same way.
#:
#: Raised by the status-column and task-type routes with
#: ``app.db.session.raise_flag``, inside
#: the transaction that moves the tasks and after every check that should still
#: be able to refuse. It lasts one transaction.
RESTRUCTURING = Guc("app.restructuring", Kind.BOOL)


#: Transaction-local flag marking a transaction as an import.
#:
#: An import writes what it brings in under the people it maps the source's
#: authors to, so the author stamp (``app.db.guild_ddl.AUTHORED_TABLES``)
#: keeps the author it is given while this is set.
#:
#: Raised by the import engine with ``app.db.session.raise_flag`` around the
#: one call that writes an envelope, and lowered after it.
IMPORTING = Guc("app.importing", Kind.BOOL)


#: Raised for one transaction by the code that needs them
#: (``app.db.session.raise_flag``), never by a routing.
FLAGS: tuple[Guc, ...] = (PURGING, RESTRUCTURING, IMPORTING)

#: Everything a routing writes: every variable declared above but the flags, in
#: the order they are declared.
REQUEST_GUCS: tuple[Guc, ...] = tuple(
    value
    for value in list(globals().values())
    if isinstance(value, Guc) and value not in FLAGS
)

STANDING: tuple[Guc, ...] = tuple(g for g in REQUEST_GUCS if g.standing)

#: The variables a policy reads once per statement, each through its
#: ``setting_<bind>()``.
READ_ONCE: tuple[Guc, ...] = tuple(g for g in REQUEST_GUCS if g.read_once)


#: The community this session reads, as text: a member routes with
#: ``current_guild_id``, a content grantee with ``pam_guild_id`` and a settings
#: grantee with ``settings_guild_id``. Whichever names one is the one community
#: the session is in.
ROUTED_COMMUNITY = (
    f"COALESCE({GUILD_ID.text}, {PAM_GUILD_ID.text}, {SETTINGS_GUILD_ID.text})"
)
#: The same, as the id.
ROUTED_GUILD_ID = f"({ROUTED_COMMUNITY})::integer"
