"""Static guard: where the platform surface routes into a community's schema.

The platform's routes and services (``app/api/v1/platform_endpoints/`` and
``app/services/platform/``) reach guild content only at the call sites named in
``_ALLOWED`` below. A platform actor who needs to read or change what is inside
a community holds a grant and goes through the seam on that community's own
routes; what is listed here is lifecycle work, aggregates, and the routes that
are already the seam or act on the caller's own community.

A call site is a call, in one of those two trees, to something that routes a
session into ``guild_<id>`` and is given a community to route into:

* the primitives — a routing shape that names a community (``SystemGuild``,
  ``SystemMaintenance``, ``Member``, ``ContentGrantee``, ``SettingsGrantee``,
  ``Install``), ``establish_guild_access``, and the test helpers ``route_as``
  / ``route_system``;
* a *wrapper* — a function in those trees, other than a route handler, that
  passes one of its own parameters as the community to any of the above (or to
  another wrapper). Its callers are the call sites, since they pick the
  community. The wrappers are pinned in ``_WRAPPERS`` so a new one is a
  decision too.

``Billing`` is not a routing into ``guild_<id>``: it assumes the billing
service's own role, which reads billing rows only.

Each entry is keyed by (module, enclosing function) and carries the reason it
is there. A call site missing from the list fails; an entry with no call site
left fails too, so the list stays a statement of what is true.

The walk is syntactic, in the style of ``context_seam_guard_test``: it matches
calls as written and does not follow a callable through a variable.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


_APP_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _APP_DIR.parent

_SCANNED = ("api/v1/platform_endpoints", "services/platform")

#: Callee name → (keyword naming the community, its position when passed
#: positionally, or None where it is keyword-only).
_PRIMITIVES: dict[str, tuple[str, int | None]] = {
    **{
        shape: ("guild_id", 0)
        for shape in (
            "SystemGuild",
            "SystemMaintenance",
            "Member",
            "ContentGrantee",
            "SettingsGrantee",
            "Install",
        )
    },
    "establish_guild_access": ("guild_id", 2),
    "route_as": ("guild_id", None),
    "route_system": ("guild_id", None),
}

_ROUTE_DECORATORS = frozenset(
    {"get", "post", "put", "patch", "delete", "websocket", "api_route"}
)

_ENDPOINTS = "app/api/v1/platform_endpoints"
_SERVICES = "app/services/platform"

#: Functions that route into whichever community their caller names.
_WRAPPERS: dict[tuple[str, str], str] = {
    (f"{_SERVICES}/holds.py", "place"): (
        "holds: writes a hold, as the platform, in the community whose own "
        "session the caller just read the target on"
    ),
    (f"{_SERVICES}/holds.py", "release"): (
        "holds: releases a hold, as the platform, in the community a moderate "
        "grantee's request was routed into"
    ),
    (f"{_SERVICES}/intake.py", "add_filer_reply"): (
        "writes a filer's answer in the operations community its caller read "
        "the case in"
    ),
    (f"{_SERVICES}/users.py", "_erase_in_guild"): (
        "erases an account's rows in one community, on that community's cohort session"
    ),
    (f"{_SERVICES}/guild_purge.py", "_end_plugin_connections"): (
        "deletes a community's plug-in connections in its own schema, for "
        "whichever deletion its caller is making"
    ),
    (f"{_SERVICES}/guilds.py", "seed_guild_content"): (
        "provisions and seeds a new community's schema"
    ),
    (f"{_SERVICES}/intake_setup.py", "_route"): (
        "intake setup's routing helper: the platform owner's Intake page, into the operations community"
    ),
    (f"{_SERVICES}/provider_placement.py", "_initiatives_in"): (
        "reads one community's initiatives and roles for a provider placement rule"
    ),
    (f"{_SERVICES}/provider_placement.py", "_resolve_destination"): (
        "checks a provider placement rule's initiative is the named community's"
    ),
    (f"{_SERVICES}/provider_placement.py", "list_targets"): (
        "lists a placeable community's initiatives for a provider placement rule"
    ),
    (f"{_ENDPOINTS}/settings.py", "_routed_to_community"): (
        "routes the operator's community sheet into a community that is still there"
    ),
}

#: Every call site that routes into a community, and why it may.
_ALLOWED: dict[tuple[str, str], str] = {
    (
        f"{_SERVICES}/guilds.py",
        "align_admin_initiative_roles.align_guild_admin_membership_roles",
    ): (
        "reconciles a promoted admin's initiative rows after the role write "
        "commits, on the community's cohort session"
    ),
    (
        f"{_SERVICES}/guilds.py",
        "enroll_new_member_in_auto_join_initiatives.enroll_in_auto_join_initiatives",
    ): (
        "enrolls a new member in the auto-join initiatives after the membership "
        "commits, on the community's cohort session"
    ),
    (f"{_SERVICES}/guilds.py", "_give_guest_invite_grants.give"): (
        "gives a new guest what their invite names after the membership "
        "commits, on the community's cohort session"
    ),
    (f"{_SERVICES}/users.py", "_in_each_guild"): (
        "an account's per-community part of deactivation and erasure, one "
        "cohort session per community it belonged to"
    ),
    # --- The seam itself ---------------------------------------------------
    (f"{_ENDPOINTS}/guilds.py", "leave_community"): (
        "routes the leaving member through establish_guild_access"
    ),
    # --- The caller's own community, behind its settings gate -------------
    # --- Joining and creating ----------------------------------------------
    (f"{_SERVICES}/guilds.py", "provision_new_guild"): (
        "seeds a community just created, for the create endpoint, registration "
        "and first boot"
    ),
    # --- Lifecycle -----------------------------------------------------------
    (f"{_SERVICES}/app_settings.py", "ensure_defaults"): (
        "startup seeding of the primary community"
    ),
    (f"{_SERVICES}/guild_purge.py", "_delete_expired_hold"): (
        "the scheduled sweep that deletes a community whose hold ran out, "
        "letting go of its plug-in connections in its own schema"
    ),
    (f"{_SERVICES}/guild_purge.py", "destroy_now"): (
        "destroys a community without a retention window, letting go of its "
        "plug-in connections in its own schema"
    ),
    # --- Aggregates ----------------------------------------------------------
    (f"{_ENDPOINTS}/settings.py", "list_community_plugin_summaries"): (
        "the operator's community sheet: which installs report a usage summary"
    ),
    (f"{_ENDPOINTS}/settings.py", "read_community_plugin_summary"): (
        "the operator's community sheet: one install's usage summary, read "
        "with no member's connection"
    ),
    # --- Account closure and erasure -----------------------------------------
    # --- Intake: the platform owner's setting, in the operations community ---
    (f"{_SERVICES}/intake.py", "stream_is_bound"): (
        "intake: opens a case in the operations community on the deployment's behalf"
    ),
    (f"{_SERVICES}/intake.py", "open_case"): (
        "intake: opens a case in the operations community on the deployment's behalf"
    ),
    (f"{_SERVICES}/intake.py", "release_subject_guild"): (
        "intake: unnames a case's community again, for a grant that was not "
        "made after all"
    ),
    (f"{_SERVICES}/intake.py", "claim_subject_guild"): (
        "intake: settles the community a case is about, as an access grant for "
        "it is asked for"
    ),
    (f"{_SERVICES}/grant_cases.py", "_as_reader"): (
        "grant cases: routes the person naming a case into the operations "
        "community through the seam, as themselves, to read it"
    ),
    (f"{_SERVICES}/grant_cases.py", "note"): (
        "grant cases: notes on an operations case what became of a grant for it"
    ),
    (f"{_SERVICES}/grant_cases.py", "case_exists"): (
        "grant cases: reads whether a case a grant serves is still there to be told"
    ),
    (f"{_SERVICES}/grant_cases.py", "_case_stream"): (
        "grant cases: reads which stream a grant's case is in, so the letter "
        "telling its community says what kind of case it was"
    ),
    (f"{_SERVICES}/intake.py", "case_locked"): (
        "intake: holds a case's task locked while a hold naming it is written, "
        "so evidence retention never decides the case's files in between"
    ),
    (f"{_SERVICES}/evidence.py", "held_cases"): (
        "evidence retention: asks the community a case is about whether a "
        "hold there still names the case, before its files are deleted"
    ),
    (f"{_SERVICES}/grant_cases.py", "activate"): (
        "grant cases: puts a case to work when access for it is approved"
    ),
    (f"{_SERVICES}/grant_cases.py", "cases_required"): (
        "grant cases: reads whether the operations community takes cases a "
        "grant may serve"
    ),
    (f"{_SERVICES}/intake.py", "open_case_counts"): (
        "intake: counts the open cases about an account, for the staff roster, "
        "naming no case's content"
    ),
    (f"{_SERVICES}/intake.py", "open_cases_for"): (
        "intake: lists where an account's open cases are, for staff to link to; "
        "opening one is its initiative's to allow"
    ),
    (f"{_SERVICES}/tickets.py", "reply"): (
        "tickets: writes a filer's answer in the operations community the "
        "filer role just read their case in"
    ),
    (f"{_SERVICES}/holds.py", "_require_case"): (
        "holds: checks the case a platform moderator names is one the "
        "operations community is working"
    ),
    (f"{_SERVICES}/holds.py", "_note_on_case"): (
        "holds: notes a placement, release or reminder on its operations case"
    ),
    (f"{_SERVICES}/evidence.py", "carry_report"): (
        "evidence: carries an escalated report's files into the operations case"
    ),
    (f"{_ENDPOINTS}/tickets.py", "read_filed_evidence"): (
        "tickets: opens a file the filer role has just shown is the reader's own"
    ),
    (f"{_SERVICES}/ticket_notices.py", "notify_filers"): (
        "the scheduled sweep that tells filers their case moved"
    ),
    (f"{_SERVICES}/intake_setup.py", "bind"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "unbind"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "list_bindings"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "list_options"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "provision_from_blueprint"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    # --- Provider placement rules: one placeable community at a time ------
    (f"{_ENDPOINTS}/provider_placement.py", "list_placement_targets"): (
        "the initiatives a provider placement rule may name, in a community "
        "its rules apply to"
    ),
    (f"{_SERVICES}/provider_placement.py", "list_rules"): (
        "names the initiatives provider placement rules place into, in the "
        "communities they apply to"
    ),
    (f"{_SERVICES}/provider_placement.py", "_read_one"): (
        "names the initiative a provider placement rule places into"
    ),
    (f"{_SERVICES}/provider_placement.py", "create_rule"): (
        "checks a new provider placement rule's initiative"
    ),
    (f"{_SERVICES}/provider_placement.py", "update_rule"): (
        "checks a changed provider placement rule's initiative"
    ),
}


@dataclass(frozen=True)
class _Function:
    module: str
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef

    @property
    def key(self) -> tuple[str, str]:
        return (self.module, self.qualname)


def _scanned_files() -> list[Path]:
    return [
        path
        for root in _SCANNED
        for path in sorted((_APP_DIR / root).rglob("*.py"))
        if not path.name.endswith("_test.py")
    ]


def _functions(path: Path) -> list[_Function]:
    module = path.relative_to(_BACKEND_DIR).as_posix()
    found: list[_Function] = []

    def visit(node: ast.AST, prefix: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = (*prefix, child.name)
                found.append(_Function(module, ".".join(name), child))
                visit(child, name)
            elif isinstance(child, ast.ClassDef):
                visit(child, (*prefix, child.name))
            else:
                visit(child, prefix)

    visit(ast.parse(path.read_text()), ())
    return found


def _callee(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _own_calls(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    """Calls in the function's own body, not in functions nested inside it."""
    calls: list[ast.Call] = []
    pending: list[ast.AST] = list(fn.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            calls.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return calls


def _community_argument(
    call: ast.Call, keyword: str, position: int | None
) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == keyword:
            if isinstance(kw.value, ast.Constant) and kw.value.value is None:
                return None
            return kw.value
    if position is not None and len(call.args) > position:
        return call.args[position]
    return None


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr in _ROUTE_DECORATORS
        for d in fn.decorator_list
    )


def _parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = fn.args
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


def _walk() -> tuple[dict[tuple[str, str], list[int]], set[tuple[str, str]]]:
    """(call sites → line numbers, wrappers found)."""
    functions = [fn for path in _scanned_files() for fn in _functions(path)]

    routers = dict(_PRIMITIVES)
    wrappers: dict[str, tuple[str, str]] = {}
    grew = True
    while grew:
        grew = False
        for fn in functions:
            if _is_route(fn.node) or fn.node.name in routers:
                continue
            params = _parameters(fn.node)
            for call in _own_calls(fn.node):
                name = _callee(call)
                if name not in routers:
                    continue
                arg = _community_argument(call, *routers[name])
                if isinstance(arg, ast.Name) and arg.id in params:
                    positional = [
                        a.arg for a in (*fn.node.args.posonlyargs, *fn.node.args.args)
                    ]
                    routers[fn.node.name] = (
                        arg.id,
                        positional.index(arg.id) if arg.id in positional else None,
                    )
                    wrappers[fn.node.name] = fn.key
                    grew = True
                    break

    wrapper_keys = set(wrappers.values())
    sites: dict[tuple[str, str], list[int]] = {}
    for fn in functions:
        if fn.key in wrapper_keys:
            continue
        for call in _own_calls(fn.node):
            name = _callee(call)
            if name not in routers:
                continue
            if _community_argument(call, *routers[name]) is None:
                continue
            sites.setdefault(fn.key, []).append(call.lineno)
    return sites, wrapper_keys


def test_platform_routes_into_a_community_only_where_listed():
    sites, _ = _walk()
    unlisted = sorted(
        f"{module}:{min(lines)} in {function}"
        for (module, function), lines in sites.items()
        if (module, function) not in _ALLOWED
    )
    assert unlisted == [], (
        "the platform surface routes into a community here, and the list of "
        "places it may does not name it. Reach guild content from a "
        "/c/{community_id} route through the seam instead, or add the site to "
        "_ALLOWED with the reason it belongs to the platform: " + ", ".join(unlisted)
    )


def test_every_listed_site_still_routes():
    sites, _ = _walk()
    stale = sorted(f"{m} {f}" for (m, f) in _ALLOWED if (m, f) not in sites)
    assert stale == [], (
        "these entries name a function that no longer routes into a "
        "community; remove them: " + ", ".join(stale)
    )


def test_the_wrappers_are_the_listed_ones():
    _, wrappers = _walk()
    unlisted = sorted(f"{m} {f}" for (m, f) in wrappers - set(_WRAPPERS))
    stale = sorted(f"{m} {f}" for (m, f) in set(_WRAPPERS) - wrappers)
    assert unlisted == [], (
        "these functions route into whichever community their caller names; "
        "list them in _WRAPPERS with what they are for: " + ", ".join(unlisted)
    )
    assert stale == [], (
        "these _WRAPPERS entries no longer route into a caller-named "
        "community; remove them: " + ", ".join(stale)
    )
