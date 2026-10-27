"""What a member may know exists in their initiatives without opening it.

Inside an initiative, a member may learn that something shareable is there —
its kind, its id, the tool whose sharing decides it, and whether it is in the
trash — and nothing more: no name, no content, no owner. That is what lets a
collection say how many of its files a reader can't open, and a link to
something they can't open offer to ask for it. Outside the initiatives a
reader is a member of, nothing is present: a row there reads as absent, as
before.

It is one view per community schema, ``entity_presence``: an arm per kind an
edge may name that has sharing behind it (:data:`ENDPOINT_KINDS`), a tool
naming itself and a sub-item (a task, an event, a wiki page…) naming the tool
above it. The view is owned by ``app_presence_reader``, a NOLOGIN role nobody
is routed as, so it reads its tables as that role, under their row security as
any role is (``public.guild_member_profiles`` is built the same way, over
``app_profile_reader``). Each arm's table carries one more permissive policy,
``presence_read``, for that role alone, admitting the rows of the initiatives
the request's standing is a member of. Nothing else reaches that policy, and
the view returns these six columns of what it admits.

The policy refuses an installed plug-in's request and the query surface, so a
plug-in and a dashboard read no presence: those roles hold ``SELECT`` on the
view only because policies on tables they read ask it. An item guest is in no
initiative's members, so nothing is present for them either.

A guild migration that drops or retypes a column the view reads (``id``,
``initiative_id``, ``deleted_at``, a sub-item's parent column) drops the view
first; provisioning puts it back.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db import gucs
from app.db.authorization import IN_POLICY

VIEW = "entity_presence"
POLICY = "presence_read"
#: The role that owns the view. Created by migration ``20261027_0547``.
READER = "app_presence_reader"


def present_to_member(initiative_expr: str) -> str:
    """Whether the request may know of a row in the initiative
    ``initiative_expr`` names: a person's own request, not a plug-in's or the
    query surface's, from a member of that initiative or the community's
    admin."""
    return (
        f"({IN_POLICY.this_guild} AND {IN_POLICY.auth_ok}"
        f" AND {IN_POLICY.install_id} IS NULL"
        f" AND {gucs.QUERY.once} IS NOT TRUE"
        f" AND ({IN_POLICY.admin}"
        f" OR {initiative_expr} = ANY ({IN_POLICY.field('member_initiatives')})))"
    )


def present(kind_expr: str, id_expr: str) -> str:
    """Whether the row of kind ``kind_expr`` and id ``id_expr`` is present to
    the request and out of the trash."""
    return (
        f"EXISTS (SELECT 1 FROM {VIEW} ep WHERE ep.kind = {kind_expr}"
        f" AND ep.id = {id_expr} AND NOT ep.trashed)"
    )


@dataclass(frozen=True)
class Arm:
    """One kind in the view: its table and, for a sub-item, the tool above it
    and the column naming that tool's row."""

    kind: str
    table: str
    tool: str
    parent_table: str | None = None
    parent_column: str | None = None

    def select(self, schema: str) -> str:
        t = f'"{schema}"."{self.table}"'
        if self.parent_table is None:
            return (
                f"SELECT '{self.kind}'::text AS kind, x.id, x.initiative_id,"
                " (x.deleted_at IS NOT NULL) AS trashed,"
                f" '{self.tool}'::text AS tool, x.id AS tool_id FROM {t} x"
            )
        return (
            f"SELECT '{self.kind}'::text AS kind, x.id, p.initiative_id,"
            " (x.deleted_at IS NOT NULL OR p.deleted_at IS NOT NULL) AS trashed,"
            f" '{self.tool}'::text AS tool, x.{self.parent_column} AS tool_id"
            f' FROM {t} x JOIN "{schema}"."{self.parent_table}" p'
            f" ON p.id = x.{self.parent_column}"
        )


def arms() -> tuple[Arm, ...]:
    """Every kind with sharing behind it, from the edge registry."""
    from app.core.relationships import ENDPOINT_KINDS
    from app.core.search import SearchEntityType
    from app.core.tools import Tool

    tools = {tool.value for tool in Tool}
    out: list[Arm] = []
    for kind, spec in sorted(ENDPOINT_KINDS.items(), key=lambda item: item[0].value):
        if spec.parent is None and kind.value in tools:
            out.append(Arm(kind.value, spec.table, kind.value))
        elif spec.parent is not None and spec.parent_column is not None:
            parent = ENDPOINT_KINDS[SearchEntityType(spec.parent.value)]
            out.append(
                Arm(
                    kind.value,
                    spec.table,
                    spec.parent.value,
                    parent.table,
                    spec.parent_column,
                )
            )
    return tuple(out)


def view_statements(schema: str, readers: tuple[str, ...]) -> list[str]:
    """Make ``schema``'s view, owned by :data:`READER` and readable by
    ``readers`` and by nobody else.

    The reader reads every table of the schema, under row security: the
    policies on an arm's table read others, and a policy is planned against
    everything it names. New relations take the schema's default privileges,
    which would give the guild roles writes and the query role a read, so
    everything is taken back before the read is given.
    """
    body = "\nUNION ALL\n".join(arm.select(schema) for arm in arms())
    view = f'"{schema}".{VIEW}'
    names = ", ".join(f'"{role}"' for role in readers)
    return [
        f'GRANT USAGE ON SCHEMA "{schema}" TO {READER}',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO {READER}',
        f"CREATE OR REPLACE VIEW {view} WITH (security_barrier) AS\n{body}",
        # Ownership can only be handed to a role that may create in the
        # schema; given for the assignment and taken straight back.
        f'GRANT CREATE ON SCHEMA "{schema}" TO {READER}',
        f"ALTER VIEW {view} OWNER TO {READER}",
        f'REVOKE CREATE ON SCHEMA "{schema}" FROM {READER}',
        f"REVOKE ALL ON {view} FROM PUBLIC, {names}",
        f"GRANT SELECT ON {view} TO {names}",
    ]


def render_presence_policies() -> str:
    """The ``presence_read`` policy on each arm's table, for :data:`READER`
    alone. Rendered after every table's own row security is on."""
    from app.db.initiative_rls import INITIATIVE_PATHS

    lines = [
        "-- " + "=" * 75,
        "-- Presence: what the entity_presence view's owner reads, on a",
        "-- request's standing (app.db.presence).",
        "-- " + "=" * 75,
    ]
    for table in sorted({arm.table for arm in arms()}):
        initiative = INITIATIVE_PATHS[table].initiative_expr(table)
        lines += [
            f"DROP POLICY IF EXISTS {POLICY} ON {table};",
            f"CREATE POLICY {POLICY} ON {table} FOR SELECT TO {READER}",
            f"  USING {present_to_member(initiative)};",
        ]
    return "\n".join(lines)
