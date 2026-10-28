"""What a guest's request reaches in a community, held by the database.

A guest is a membership with an end and the ``guest`` rung
(``app.models.platform.guild``). Their request is routed into one of the
community's two guest roles, ``guild_<id>_guest`` or, in a ``read_only``
community, ``guild_<id>_guest_ro``. Three things bound it:

* **Grants.** :data:`GUEST_TABLE_ACCESS` is every table in the community's
  schema the role holds anything on. A table it does not name is refused
  outright, whatever a policy says: the community's settings, its plug-ins, AI,
  imports and exports, join requests, webhooks, moderation and intake. In
  ``public`` the role holds only the ``guest_base`` floor
  (``app.db.public_rls``).
* **The community's own policies,** read off the guest's standing. A guest in
  an initiative reaches what their role there reaches. A guest given items one
  at a time passes the initiative gate in those items' initiatives
  (``guest_item_initiatives``), and sharing decides which rows: every tool
  table and its children ask ``resource_access``.
* **Row narrowing for guests,** in :data:`GUEST_ROWS`: restrictive policies
  ``TO guest_base``, so they never run for anyone else. They keep a guest to
  the initiatives they reach and the sharing rows that name them, on the
  tables no tool's sharing governs.

``guest_base`` reads a guest's own sharing rows outright
(:data:`GUEST_OWN_GRANTS`): the standing statement computes the item
initiatives from them before any standing exists.
"""

from __future__ import annotations

from enum import Enum

from app.db import gucs
from app.db.authorization import IN_POLICY
from app.db.initiative_rls import INITIATIVE_PATHS, governing_path

#: The guest floor in ``public``, which both guest roles inherit and the row
#: policies below are granted to.
GUEST_FLOOR = "guest_base"


class GuestAccess(str, Enum):
    #: Reads and writes, as the table's policies allow.
    write = "write"
    #: Reads only.
    read = "read"
    #: Written as a step of a write the guest makes (a trigger), never read.
    insert = "insert"


#: Tables a tool governs that are not a guest's to touch: the reminder
#: scheduler's own record, and operations intake, which the community's staff
#: runs.
_NOT_GUEST_SURFACE: frozenset[str] = frozenset(
    {"event_reminder_dispatches", "intake_bindings", "intake_cases"}
)

#: The tables no tool governs that a guest reaches, by name.
_NAMED: dict[str, GuestAccess] = {
    # Responding to what they reach, and their own history of visiting it
    # and bookmarking it.
    "comments": GuestAccess.write,
    "reactions": GuestAccess.write,
    "reaction_digest_items": GuestAccess.write,
    # The sweep timers a guest's writes arm (public.arm_timer reads the mark
    # before it writes one).
    "timer_marks": GuestAccess.write,
    "personal_items": GuestAccess.write,
    # Asking to edit what was shared with them, and reading their own asks.
    "share_requests": GuestAccess.write,
    # How widely what they reach was engaged with, read beside it.
    "engagement_levels": GuestAccess.read,
    "relationships": GuestAccess.write,
    "metadata_values": GuestAccess.write,
    "metadata_definitions": GuestAccess.read,
    # Read beside a task, and refused to a guest row by row (GUEST_ROWS).
    "intake_cases": GuestAccess.read,
    # The files content shows, stored and claimed as a step of saving it.
    "uploads": GuestAccess.write,
    # The search index, kept by the refresh trigger on what they write.
    "search_entries": GuestAccess.write,
    # The change log, written by the capture trigger on what they write.
    "event_outbox": GuestAccess.insert,
    # The collections the files given to them are in, seen through those files.
    "collections": GuestAccess.read,
    "collection_files": GuestAccess.read,
    # What they are in, and the vocabulary items are labelled with.
    "initiatives": GuestAccess.read,
    "initiative_members": GuestAccess.read,
    "initiative_roles": GuestAccess.read,
    "initiative_role_permissions": GuestAccess.read,
    "tags": GuestAccess.read,
}


def _derive() -> dict[str, GuestAccess]:
    access = {
        table: GuestAccess.write
        for table in INITIATIVE_PATHS
        if table not in _NOT_GUEST_SURFACE and governing_path(table) is not None
    }
    access.update(_NAMED)
    # The sharing rows. Read as narrowed below; written only as the owner row
    # the tool table's trigger adds when a guest makes something.
    access["resource_grants"] = GuestAccess.read
    return access


GUEST_TABLE_ACCESS: dict[str, GuestAccess] = _derive()

#: Written beside a read grant: the owner row on what a guest makes.
GUEST_TRIGGER_INSERTS: frozenset[str] = frozenset({"resource_grants"})

#: Columns the policies on those tables read while deciding a guest's
#: statement, in a branch that answers for an installed plug-in. A statement's
#: plan is checked against every column its policies name, including those in
#: a branch it never takes, so they are granted for the policy to be planned.
GUEST_POLICY_READS: dict[str, tuple[str, ...]] = {
    "plugin_placements": ("install_id", "initiative_id"),
}

_P = IN_POLICY
_UID = gucs.USER_ID.once
_MEMBER_OF = _P.field("member_initiatives")
#: The initiatives a guest is in, read from their own roster rows rather than
#: the standing, which the standing statement is still computing when it
#: reads these tables.
_IN_INITIATIVES = (
    f"(SELECT im.initiative_id FROM initiative_members im WHERE im.user_id = {_UID})"
)

#: The rows of each table a guest reaches, as SQL over that table. Read
#: narrowing only: what a guest may write is the table's own policies'.
GUEST_ROWS: dict[str, str] = {
    # The initiatives they are in, and those of the items shared with them.
    "initiatives": (
        f"(initiatives.id IN {_IN_INITIATIVES}"
        " OR initiatives.id IN (SELECT g.initiative_id FROM resource_grants g"
        f" WHERE g.user_id = {_UID}))"
    ),
    # The rosters and roles of the initiatives they are in, and nothing of an
    # initiative they reach only through items.
    "initiative_members": (
        f"(initiative_members.user_id = {_UID}"
        f" OR initiative_members.initiative_id = ANY ({_MEMBER_OF}))"
    ),
    "initiative_roles": f"(initiative_roles.initiative_id IN {_IN_INITIATIVES})",
    "initiative_role_permissions": (
        "EXISTS (SELECT 1 FROM initiative_roles r"
        " WHERE r.id = initiative_role_permissions.initiative_role_id"
        f" AND r.initiative_id IN {_IN_INITIATIVES})"
    ),
    # Only the sharing rows that reach them: not who else something is
    # shared with.
    "resource_grants": (
        f"(resource_grants.user_id = {_UID}"
        f" OR resource_grants.role_id = ANY ({_P.field('member_role_ids')})"
        " OR (resource_grants.all_initiative_members"
        f" AND resource_grants.initiative_id = ANY ({_MEMBER_OF})))"
    ),
    # Operations intake is the community's staff's: a task's case reads as
    # none.
    "intake_cases": "false",
    # Files of the initiatives they reach, as a member of one reads them, and
    # their own; none that belongs to the whole community.
    "uploads": (
        f"(uploads.created_by = {_UID}"
        f" OR uploads.initiative_id = ANY ({_MEMBER_OF})"
        f" OR uploads.initiative_id = ANY ({_P.guest_items}))"
    ),
}

#: A guest reads the sharing rows naming them, whatever the initiative gate
#: says: the standing statement reads them to find the item initiatives.
GUEST_OWN_GRANTS = f"resource_grants.user_id = {_UID}"

GUEST_ROWS_POLICY = "guest_rows"
GUEST_OWN_GRANTS_POLICY = "guest_own_grants"

_GUEST_SECTION = """\
-- ===========================================================================
-- A guest's rows (app.db.guest_access). RESTRICTIVE and TO the guest floor, so
-- they narrow a guest's reads and never run for anyone else; and the one
-- PERMISSIVE read of a guest's own sharing rows.
-- ==========================================================================="""


def render_guest_rls_ddl() -> str:
    """The guest policies, schema-relative, for the community's RLS render."""
    lines = [_GUEST_SECTION]
    for table, rows in sorted(GUEST_ROWS.items()):
        lines += [
            f"DROP POLICY IF EXISTS {GUEST_ROWS_POLICY} ON {table};",
            f"CREATE POLICY {GUEST_ROWS_POLICY} ON {table} AS RESTRICTIVE FOR SELECT",
            f"  TO {GUEST_FLOOR} USING ({rows});",
        ]
    lines += [
        f"DROP POLICY IF EXISTS {GUEST_OWN_GRANTS_POLICY} ON resource_grants;",
        f"CREATE POLICY {GUEST_OWN_GRANTS_POLICY} ON resource_grants AS PERMISSIVE",
        f"  FOR SELECT TO {GUEST_FLOOR} USING ({GUEST_OWN_GRANTS});",
    ]
    return "\n".join(lines)


def guest_role_grant_statements(
    schema: str, role: str, *, writes: bool, members: str
) -> list[str]:
    """A guest role's grants, from :data:`GUEST_TABLE_ACCESS`. ``writes`` is
    the full guest role; without it, SELECT only. ``members`` is the quoted
    login roles that may assume it. The role's table grants are cleared first,
    so a re-provision leaves it holding what the registry says now."""
    stmts = [
        f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{role}"',
        f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA "{schema}" FROM "{role}"',
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"',
    ]
    for table, access in sorted(GUEST_TABLE_ACCESS.items()):
        if access is GuestAccess.insert:
            verbs = "INSERT" if writes else None
        elif access is GuestAccess.write and writes:
            verbs = "SELECT, INSERT, UPDATE, DELETE"
        else:
            verbs = "SELECT"
        if writes and table in GUEST_TRIGGER_INSERTS:
            verbs = f"{verbs}, INSERT"
        if verbs is not None:
            stmts.append(f'GRANT {verbs} ON TABLE "{schema}"."{table}" TO "{role}"')
    for table, columns in sorted(GUEST_POLICY_READS.items()):
        stmts.append(
            f'GRANT SELECT ({", ".join(columns)}) ON TABLE "{schema}"."{table}" TO "{role}"'
        )
    if writes:
        stmts.append(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"')
    stmts += [
        f'GRANT {GUEST_FLOOR} TO "{role}"',
        f'GRANT "{role}" TO {members} WITH INHERIT FALSE',
    ]
    return stmts
