"""Which guild tables a plug-in can reach, and under which scope.

One registry, ``PLUGIN_TABLE_ACCESS``, table -> :class:`PluginTableAccess`. What an
plug-in's routed role is granted on a table, and the scope that table's policies
ask of a plug-in, are both read from it. A guild table with no entry is out of
every plug-in's reach.

Most of it is derived:

- a table a tool governs (``initiative_rls.governing_path``) takes that tool's
  scope, so ``tasks`` answers to ``projects`` and ``calendar_events`` to
  ``calendars``;
- the surfaces that span tools, and the read-only structure a plug-in needs to
  address an initiative, are named here.

What is left out on purpose is listed in :data:`_NOT_PLUGIN_SURFACE`: rows that
are one person's own state, and machinery a scheduler or an operator runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.plugin_scopes import (
    PluginScopeResource,
    READ_ONLY_RESOURCES,
    tool_resource,
)
from app.core.search import SearchEntityType
from app.db import gucs
from app.db.initiative_rls import INITIATIVE_PATHS, governing_path
from app.db.search_index import SEARCH_SOURCES


class PluginTableKind(str, Enum):
    #: Content a plug-in reads, and writes when its scope allows.
    scoped = "scoped"
    #: Written as a consequence of a scoped write (a trigger, or a service
    #: step), never addressed by a plug-in.
    side_effect = "side_effect"
    #: Event subscriptions: reachable with the read scope of each event's tool,
    #: which is a property of the row rather than of the table.
    subscriptions = "subscriptions"


@dataclass(frozen=True)
class PluginTableAccess:
    kind: PluginTableKind
    resource: PluginScopeResource | None = None

    @property
    def writable(self) -> bool:
        """Whether a plug-in may ever write this table directly."""
        if self.kind is PluginTableKind.scoped:
            return self.resource not in READ_ONLY_RESOURCES
        return self.kind is PluginTableKind.subscriptions


def _scoped(resource: str) -> PluginTableAccess:
    return PluginTableAccess(PluginTableKind.scoped, PluginScopeResource(resource))


#: Tables a tool governs that are not a plug-in's to touch.
_NOT_PLUGIN_SURFACE: frozenset[str] = frozenset(
    {
        # One person's own state: their ordering, bookmarks, read markers and
        # ballots.
        "post_reads",
        "post_poll_votes",
        # Run by the reminder scheduler.
        "event_reminder_dispatches",
        # How an initiative lays its tools out, which its own managers set.
        "tool_layouts",
        # Operations intake, which the community's own staff runs.
        "intake_bindings",
        "intake_cases",
    }
)

#: Written as a consequence of a scoped write.
_SIDE_EFFECTS: frozenset[str] = frozenset(
    {
        # The change log, written by the capture trigger.
        "event_outbox",
        # The search index, written by the refresh trigger.
        "search_entries",
        # Queued when a task is assigned, cleared when it is unassigned.
        "task_assignment_digest_items",
        # The sweep timers a write arms, read and written by public.arm_timer.
        "timer_marks",
        # The files content shows, stored, copied and claimed as a step of
        # saving that content, by the filenames the saved row shows.
        "uploads",
    }
)

#: The tables no tool governs that a plug-in reaches, by name.
_NAMED: dict[str, PluginTableAccess] = {
    "comments": _scoped("comments"),
    # Part of Files, with no sharing of their own.
    "collections": _scoped("files"),
    "collection_files": _scoped("files"),
    "relationships": _scoped("relationships"),
    "tags": _scoped("tags"),
    "initiatives": _scoped("initiatives"),
    "initiative_roles": _scoped("initiatives"),
    # Also readable with any tool's scope, so a plug-in setting a value on an
    # item can read the definitions it chooses from, and an install's own
    # with none (``guild_ddl._plugin_predicates``).
    "metadata_definitions": _scoped("properties"),
    # No scope of its own: a value takes the scope of the tool that governs the
    # row it is on, per row, and an install reaches its own on itself with
    # none (``guild_ddl._metadata_values_scope``).
    "metadata_values": PluginTableAccess(PluginTableKind.scoped),
    "initiative_members": _scoped("members"),
    "webhook_subscriptions": PluginTableAccess(PluginTableKind.subscriptions),
    **{
        table: PluginTableAccess(PluginTableKind.side_effect) for table in _SIDE_EFFECTS
    },
}


def _derive() -> dict[str, PluginTableAccess]:
    access: dict[str, PluginTableAccess] = {}
    for table in INITIATIVE_PATHS:
        if table in _NOT_PLUGIN_SURFACE or table in _NAMED:
            continue
        governed = governing_path(table)
        if governed is not None:
            access[table] = PluginTableAccess(
                PluginTableKind.scoped, tool_resource(governed[0])
            )
    access.update(_NAMED)
    return access


PLUGIN_TABLE_ACCESS: dict[str, PluginTableAccess] = _derive()


def _search_entry_read_scopes() -> dict[SearchEntityType, PluginScopeResource]:
    """Each kind the search index holds, and the read scope of the table it is
    indexed from. A kind whose table no plug-in reaches has no entry, and its
    entries are out of every plug-in's reach."""
    scopes: dict[SearchEntityType, PluginScopeResource] = {}
    for table, source in SEARCH_SOURCES.items():
        access = PLUGIN_TABLE_ACCESS.get(table)
        if (
            access is not None
            and access.kind is PluginTableKind.scoped
            and access.resource is not None
        ):
            scopes[source.entity_type] = access.resource
    return scopes


#: The read scope an installed plug-in holds to find a search entry of each kind:
#: the scope of the table the kind is indexed from, so ``task`` answers to
#: ``projects`` and ``tag`` to ``tags``. An entry that names a governing tool
#: also needs that tool's read scope (a comment on a task needs ``projects``
#: beside ``comments``), which the index's policy reads off the row.
SEARCH_ENTRY_READ_SCOPE: dict[SearchEntityType, PluginScopeResource] = (
    _search_entry_read_scopes()
)

#: Tables no plug-in reaches, whose policies refuse an installed plug-in outright
#: beside the grant it does not hold: a reaction and the line queued about it
#: are one person's gesture, a recent view one person's history, a bookmark one
#: person's pick, and an engagement level what many people's history adds up to.
PLUGIN_REFUSED_TABLES: frozenset[str] = frozenset(
    {
        "reactions",
        "reaction_digest_items",
        "personal_items",
        "engagement_levels",
    }
)


#: The trigger function every tool table carries (``tr_<table>_install_owns``,
#: attached with the tool's value as its argument): when a request creates a
#: tool's resource, it writes the one owner row. That row names the person who
#: made it, the install, or, for a member token, the member it acts for. A
#: system job names nobody, and the function writes nothing. Nor does it for a
#: row outside any initiative: that is community level, and the calendar plug-in
#: whose install mounts it is named as its owner by the code that makes it.
#: Shared, in ``public``; the row lands in the schema the trigger fired in.
#: Restated in full by the migration that sets it (20260927_0407).
INSTALL_OWNS_WHAT_IT_CREATES = f"""
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := {gucs.INSTALL_ID};
    v_member integer := {gucs.USER_ID};
BEGIN
    IF NEW.initiative_id IS NULL OR (v_install IS NULL AND v_member IS NULL) THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, plugin_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""
