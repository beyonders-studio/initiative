"""Discretionary Access Control (DAC) — per-resource sharing.

The application-level permission layer for every tool. Unlike the mandatory RLS
layer (see ``rls.py``), which PostgreSQL enforces, this resolves what a request
may read, write or own from the ``resource_grants`` rows on a resource.

Postgres decides. The guild-schema policies apply the sharing rule to every
content table — gate 4, rendered from ``app/db/initiative_rls.py`` and calling
``resource_access`` — and what a request may do to a row beyond reading it is
the schema's own ``resource_actions``, read off the loaded row by
:func:`actions_of`. What is left here names and composes those answers:

  - :func:`require_access` — a *named* refusal on a loaded row, for an
    action ``resource_actions`` did not answer yes to
  - :func:`client_access` — the row's ``can``, the same answer
  - :func:`granted_scope_clause` — deliberately NARROWER than the policy for a
    list spanning initiatives (no guild-admin leg)
  - :func:`writable_scope_clause` — "which of these may I change", which a read
    policy does not answer

Guild isolation and initiative membership are separate layers, in ``rls.py`` and
Postgres.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, false, func, inspect, or_, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, undefer
from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.db.guild_standing import ActorContext, InstallContext
from app.services import audit as audit_service
from app.core.tools import Tool

from app.models.platform.guild import GuildMembership
from app.models.tenant.project import Project
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.db.frozen import ancestor_is_frozen, row_is_frozen
from app.db.authorization import standing_arg
from app.core.messages import (
    CommonMessages,
    ExportMessages,
    InitiativeMessages,
    SharingMessages,
    ProjectMessages,
)
from app.models.tenant.resource_grant import (
    ResourceAccessLevel,
    ResourceGrant,
)


def _frozen_community(context: ActorContext | None) -> bool:
    """Whether this request reads a community whose content is on hold.

    The routed role (``guild_<id>_ro``) refuses the write either way; the app
    layer agrees so every derived level reports read rather than offering an
    affordance the database will reject.
    """
    return context is not None and context.content_read_only


def granted_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int | None,
    *,
    context: ActorContext | None,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg for a listing that **spans initiatives** — the cross-guild
    ``/me/*`` views and a guild-wide tool list, which is the guild home's table.

    Such a list is answered by what has been granted to the reader: a grant
    naming them, one on an initiative role they hold, or one shared with every
    member of an initiative they are in. Guild-admin standing is not a leg here.
    An admin's authority still reaches every initiative in their community, and
    every gate that acts on one still honours it; what a list spanning
    initiatives shows is what reaches the reader, the same way their sidebar and
    the community front page list the initiatives they joined.

    ``initiative_id`` is absent from this signature on purpose: the initiative
    "Full access" override answers for one initiative at a time, and a list
    spanning them has no single initiative to ask about.

    A PAM or break-glass grantee keeps their window. They hold no membership row
    and no grant, so the grant legs would answer nothing at all — the grant is
    what they navigate by, exactly as it is in the initiative listing.

    A statement already confined to one initiative asks nothing here — see
    :func:`listing_scope_clause`.
    """
    if isinstance(context, InstallContext):
        # An installed plug-in is granted to by name or through its placements,
        # and is an admin only by a standing its token asked for: the table's
        # own policy answers exactly what reaches it.
        return true()
    if context is not None and context.grant_satisfies(access=access):
        return true()
    if user_id is None:
        raise ValueError("a listing for a person names the person")
    return func.resource_granted(tool.value, id_col, user_id, False, standing_arg())


def listing_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int | None,
    *,
    context: ActorContext | None,
    initiative_id: int | None = None,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg for a tool listing, picking the rule its scope calls for.

    **Confined to one initiative, there is nothing to add.** The question is the
    reader's standing there, and the table's own policy already asked it: every
    content table carries a sharing leg deferring to ``resource_access``
    (guild admin OR PAM at the level OR the "Full access" override OR a grant
    row), ANDed with initiative membership and the reader's initiative role.
    Restating it here would narrow nothing and consult ``resource_grants`` a
    second time per row.

    **Spanning initiatives** — the community front page's table, the sidebar's
    tool lists, the cross-guild ``/me/*`` views — the question is what has been
    granted to the reader, which is NARROWER than the policy: it drops the
    guild-admin leg. An admin navigates what reaches them, and reaches
    everything else the moment they ask for one initiative by name. That is a
    product rule, not an enforcement one, so :func:`granted_scope_clause`
    carries it.
    """
    if initiative_id is not None:
        return true()
    return granted_scope_clause(tool, id_col, user_id, context=context, access=access)


def writable_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int | None,
    *,
    context: ActorContext | None,
    initiative_id: int | None = None,
) -> ColumnElement[bool]:
    """The listing rule narrowed to what the reader may CHANGE.

    This one does NOT collapse the way :func:`listing_scope_clause` does. A read
    policy admits a row shared at any level, so "may I see it" is already
    answered and "may I edit it" is strictly narrower — the grant rows have to
    be filtered to :data:`WRITE_LEVELS` here, whatever the statement's scope.

    The two branches are the scope choice made elsewhere: confined to one
    initiative, the table's own gate answers, asked at write; spanning them,
    only what has been granted does.
    """
    if initiative_id is not None:
        return func.resource_access(
            tool.value, id_col, user_id, initiative_id, True, standing_arg()
        )
    if context is not None and context.grant_satisfies(access="write"):
        return true()
    if user_id is None:
        # Spanning initiatives, what may be changed is read from grants to a
        # person; an installed plug-in asks one initiative at a time.
        return false()
    return func.resource_granted(tool.value, id_col, user_id, True, standing_arg())


# ── Generic DAC engine (registry-driven) ─────────────────────────
# Every DAC resource resolves access from its ``grants`` (resource_grants rows)
# the same way — one registry row + one engine.


@dataclass(frozen=True)
class DacResource:
    """One tool's DAC identity. Its refusals come from the tool (``Tool``), so
    a new member arrives with its full set."""

    name: Tool


#: Every tool, by construction — ``tools_test`` has nothing to catch up on.
DAC_RESOURCES: dict[Tool, DacResource] = {t: DacResource(t) for t in Tool}
#: The same, by the table a tool's row is read from.
_RESOURCE_BY_TABLE: dict[str, DacResource] = {
    t.plural: r for t, r in DAC_RESOURCES.items()
}


def _grant_level(level: Any) -> str:
    return level.value if hasattr(level, "value") else level


#: The scope that lets an installed plug-in see a resource's sharing.
SHARING_READ = "sharing:read"


def serialize_grants(row: Any, *, context: ActorContext | None) -> list:
    """Serialize a resource's eager-loaded ``grants`` into the unified grant list
    — one ``ResourceGrantSchema`` per ``resource_grants`` row (user, role,
    all-initiative-members, or an installed plug-in), owner included.

    An installed plug-in sees the list only with ``sharing:read``; without it the
    list is empty. Who owns the resource is reported beside it either way."""
    from app.schemas.tenant.resource_grant import ResourceGrantSchema

    if isinstance(context, InstallContext) and not context.holds(SHARING_READ):
        return []
    return [
        ResourceGrantSchema(
            level=g.level,
            user_id=g.user_id,
            role_id=g.role_id,
            all_initiative_members=bool(getattr(g, "all_initiative_members", False)),
            plugin_install_id=getattr(g, "plugin_install_id", None),
        )
        for g in getattr(row, "grants", None) or []
    ]


async def audience(
    session: Any, tool: Tool, rows: Iterable[Any]
) -> dict[int, set[int]]:
    """Who each of ``rows`` (``tool`` rows) is shared with and can open now, by
    id: the schema's ``resource_audience``, narrowed to
    :func:`named_people.readers_of`. The people a notification goes to and a
    notice is read by. Rows that reach nobody are absent.

    Read on :func:`named_people.roster_session` with ``whole``: who a thing
    reaches is the community's answer, whoever is asking."""
    from app.db.session import routed_guild_id
    from app.services.tenant import named_people

    by_id = {row.id: row for row in rows}
    if not by_id:
        return {}
    guild_id = routed_guild_id(session)
    if guild_id is None:
        raise RuntimeError("an audience is read inside a community")
    shared = func.resource_audience(tool.value, sorted(by_id), guild_id).table_valued(
        "resource_id", "user_id"
    )
    reaches = or_(
        *(
            and_(
                shared.c.resource_id == row_id,
                shared.c.user_id.in_(
                    named_people.readers_of(
                        named_people.Governing.of(tool, row), guild_id
                    )
                ),
            )
            for row_id, row in by_id.items()
        )
    )
    async with named_people.roster_session(session, whole=True) as reader:
        pairs = (
            await reader.exec(
                select(shared.c.resource_id, shared.c.user_id).where(reaches)
            )
        ).all()
    by_resource: dict[int, set[int]] = {}
    for resource_id, user_id in pairs:
        by_resource.setdefault(resource_id, set()).add(user_id)
    return by_resource


#: One grantee of a resource: ``("user", id)``, ``("role", id)`` or
#: ``("all_members", None)``.
_Grantee = tuple[str, int | None]


def _levels_by_grantee(grants: Any) -> dict[_Grantee, str]:
    """The level each grantee holds, from a set of ``resource_grants`` rows.

    Owner rows and plugin-install rows are left out: neither is part of the list
    a share is rebuilt from.
    """
    levels: dict[_Grantee, str] = {}
    for g in grants:
        if _grant_level(g.level) == "owner" or g.plugin_install_id is not None:
            continue
        if g.user_id is not None:
            key: _Grantee = ("user", g.user_id)
        elif g.role_id is not None:
            key = ("role", g.role_id)
        else:
            key = ("all_members", None)
        levels[key] = _grant_level(g.level)
    return levels


async def _record_grant_changes(
    session: Any,
    *,
    actor_user_id: int | None,
    resource_type: str,
    resource_id: int,
    guild_id: int,
    initiative_id: int | None,
    before: dict[_Grantee, str],
    after: dict[_Grantee, str],
) -> None:
    """One audit record per grantee whose level moved — granted, raised,
    lowered or withdrawn. A grantee that reads back the same level is not one
    of them. Staged in the caller's transaction, like every other record."""
    for key in sorted(before.keys() | after.keys(), key=repr):
        was, now = before.get(key), after.get(key)
        if was == now:
            continue
        kind, grantee_id = key
        await audit_service.record(
            session,
            event_type=AuditEventType.SHARING_GRANT_CHANGED,
            actor_user_id=actor_user_id,
            target_user_id=grantee_id if kind == "user" else None,
            guild_id=guild_id,
            target_type=getattr(resource_type, "value", resource_type),
            target_id=resource_id,
            detail={
                "initiative_id": initiative_id,
                "grantee": {"kind": kind, "id": grantee_id},
                "from": was,
                "to": now,
            },
        )


async def replace_resource_grants(
    session: Any,
    *,
    resource_type: str,
    resource_id: int,
    guild_id: int,
    initiative_id: int | None,
    owner_id: int | None,
    grants: Any,
    actor_user_id: int | None = None,
    by_install: bool = False,
) -> None:
    """Rebuild a resource's non-owner grants from ``grants`` (a list of
    ResourceAccessGrant rows). Each row is sorted by grantee kind — all-members,
    per-user, or per-role. The owner grant is preserved; owner-level entries and
    grantees outside the resource's scope are dropped. Caller commits.

    ``initiative_id`` is None for a guild-level resource. There "all members"
    means the guild's, and a named grantee is validated against guild
    membership; role grants are not resolvable (see below).

    ``owner_id`` is the person holding the owner grant, or None when nobody
    does or an installed plug-in does; a named grantee equal to it is skipped.

    ``actor_user_id`` is who is making the change; pass it on any request path
    and the move of every grantee whose level actually changed is recorded in
    the same transaction. ``by_install`` records an installed plug-in's change the
    same way, with no person as its actor. Left at neither, nothing is
    recorded."""
    all_members_level: str | None = None
    user_levels: dict[int, str] = {}
    role_levels: dict[int, str] = {}
    for g in grants:
        if getattr(g, "plugin_install_id", None) is not None:
            # Reported by this shape, never taken by it: what an installed plug-in
            # may reach is granted by the community's seat.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=SharingMessages.PLUGIN_INSTALL_GRANT_NOT_SET_HERE,
            )
        level = g.level
        if level not in ("read", "write"):
            continue  # owner is preserved server-side, never set via this list
        if getattr(g, "all_initiative_members", False):
            all_members_level = level
        elif g.user_id is not None and g.user_id != owner_id:
            user_levels[g.user_id] = level
        elif g.role_id is not None:
            role_levels[g.role_id] = level

    guild_scoped = initiative_id is None

    valid_users: set[int] = set()
    if user_levels:
        if guild_scoped:
            # The resource belongs to no initiative, so a named grantee is
            # someone in the *guild*. Validating against initiative membership
            # here would compare against NULL and match nobody, silently
            # dropping every named grant on a guild-level resource.
            valid_users = set(
                (
                    await session.exec(
                        select(GuildMembership.user_id).where(
                            GuildMembership.guild_id == guild_id,
                            GuildMembership.user_id.in_(list(user_levels)),
                        )
                    )
                ).all()
            )
        else:
            valid_users = set(
                (
                    await session.exec(
                        select(InitiativeMember.user_id).where(
                            InitiativeMember.initiative_id == initiative_id,
                            InitiativeMember.user_id.in_(list(user_levels)),
                        )
                    )
                ).all()
            )

    valid_roles: set[int] = set()
    # Role grants are initiative roles. A guild-level resource has no initiative
    # for a role to belong to, and a guild role is not an ``initiative_roles``
    # row, so there is nothing to validate against — guild-scope sharing is by
    # everyone or by named user until guild-role principals have a design.
    if role_levels and not guild_scoped:
        valid_roles = set(
            (
                await session.exec(
                    select(InitiativeRoleModel.id).where(
                        InitiativeRoleModel.initiative_id == initiative_id,
                        InitiativeRoleModel.id.in_(list(role_levels)),
                    )
                )
            ).all()
        )

    # Sharing reaches somebody only where their role already lets them use the
    # tool. The picker offers that list; saying so here too means a caller that
    # does not go through it — the API, an agent — is told the same thing
    # rather than writing a grant that does nothing. A guild-level resource
    # belongs to no initiative, so no initiative role speaks for it.
    if not guild_scoped:
        # Local: rls imports this module.
        from app.models.tenant.initiative import PermissionKey
        from app.services import rls as rls_service

        tool = Tool(resource_type)
        view_key = PermissionKey(tool.view_permission)
        permitted_users = await rls_service.members_permitted(
            session,
            initiative_id=initiative_id,
            user_ids=valid_users,
            permission_key=view_key,
        )
        permitted_roles = await rls_service.roles_permitting(
            session,
            initiative_id=initiative_id,
            role_ids=valid_roles,
            permission_key=view_key,
        )
        if valid_users - permitted_users or valid_roles - permitted_roles:
            raise tool.grantee_lacks_access()
        valid_users, valid_roles = permitted_users, permitted_roles

    existing = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
            )
        )
    ).all()
    before = _levels_by_grantee(existing)
    for g in existing:
        if _grant_level(g.level) == "owner":
            continue
        if g.plugin_install_id is not None:
            # An installed plug-in's grant is the seat's, not this list's, and
            # stays whatever the panel sends.
            continue
        await session.delete(g)

    await session.flush()

    def _grant(level: str, **kw: Any) -> ResourceGrant:
        return ResourceGrant(
            resource_type=resource_type,
            resource_id=resource_id,
            initiative_id=initiative_id,
            level=ResourceAccessLevel(level),
            **kw,
        )

    if all_members_level is not None:
        session.add(_grant(all_members_level, all_initiative_members=True))
    session.add_all(
        _grant(level, user_id=uid)
        for uid, level in user_levels.items()
        if uid in valid_users
    )
    session.add_all(
        _grant(level, role_id=rid)
        for rid, level in role_levels.items()
        if rid in valid_roles
    )

    if actor_user_id is not None or by_install:
        after: dict[_Grantee, str] = {}
        if all_members_level is not None:
            after[("all_members", None)] = all_members_level
        after.update(
            {
                ("user", uid): level
                for uid, level in user_levels.items()
                if uid in valid_users
            }
        )
        after.update(
            {
                ("role", rid): level
                for rid, level in role_levels.items()
                if rid in valid_roles
            }
        )
        await _record_grant_changes(
            session,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            guild_id=guild_id,
            initiative_id=initiative_id,
            before=before,
            after=after,
        )


async def share_with(
    session: Any,
    *,
    resource_type: Tool,
    resource_id: int,
    guild_id: int,
    initiative_id: int | None,
    user_id: int | None,
    level: ResourceAccessLevel,
    actor_user_id: int | None,
    raise_lower: bool = False,
) -> None:
    """Share one resource with ``user_id`` at ``level`` — with every member of
    its initiative where ``user_id`` is ``None``. A grant already there is left
    as it is, unless ``raise_lower`` and it gives less, when it is raised.
    Recorded as a share is. Caller commits."""
    key: _Grantee = ("user", user_id) if user_id is not None else ("all_members", None)
    held = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.user_id == user_id
                if user_id is not None
                else ResourceGrant.all_initiative_members.is_(True),
            )
        )
    ).first()
    before: dict[_Grantee, str] = {}
    if held is not None:
        was = _grant_level(held.level)
        if not raise_lower or ResourceAccessLevel(was).reaches(level):
            return
        held.level = level
        session.add(held)
        await session.flush()
        before = {key: was}
    else:
        # Two writers can both find none; the unique grantee key keeps one,
        # and the other is the share the caller asked for.
        try:
            async with session.begin_nested():
                session.add(
                    ResourceGrant(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        initiative_id=initiative_id,
                        user_id=user_id,
                        all_initiative_members=user_id is None,
                        level=level,
                    )
                )
                await session.flush()
        except IntegrityError:
            return
    await _record_grant_changes(
        session,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        guild_id=guild_id,
        initiative_id=initiative_id,
        before=before,
        after={key: _grant_level(level)},
    )


class Action(str, Enum):
    """What somebody may do to one of a tool's rows, beyond reading it — the
    names ``resource_actions`` answers in (``app.db.authorization``)."""

    contribute = "contribute"
    edit = "edit"
    delete = "delete"
    share = "share"
    export = "export"
    unarchive = "unarchive"
    configure = "configure"


#: The actions a tool's read reports under ``can``. ``configure`` is a
#: project's alone (``ProjectCan``).
TOOL_CAN: tuple[Action, ...] = (
    Action.contribute,
    Action.edit,
    Action.delete,
    Action.share,
    Action.export,
    Action.unarchive,
)


def actions_of(row: Any) -> frozenset[str]:
    """What the request may do to ``row``, as the database answered it.

    Read off ``actions``: mapped on every shareable model and asked of the
    schema's ``resource_actions`` in the SELECT that loaded the row, so it was
    answered for the reader the session is routed as, under the standing the
    seam computed. A row loaded without it came through a loader that does not
    decide or serialize, which is where to ask for it.
    """
    if "actions" in inspect(row).unloaded:
        raise RuntimeError(
            f"{type(row).__name__} was loaded without its actions; "
            "undefer it in the loader"
        )
    return frozenset(row.actions or ())


def with_tool(relation: Any) -> Any:
    """The load option for a row's tool, ``relation``, as authorizing it
    reads it: its initiative and its ``actions``."""
    tool = relation.property.mapper.class_
    return joinedload(relation).options(
        joinedload(tool.initiative), undefer(tool.actions)
    )


def allows(row: Any, action: Action) -> bool:
    """Whether the request may take ``action`` on ``row``."""
    return action.value in actions_of(row)


def _refusal(
    resource: DacResource, row: Any, action: Action, context: ActorContext | None
) -> Exception:
    """Which refusal a missing ``action`` is. Only names it: the database
    already decided."""
    if action is Action.export:
        initiative = (
            None
            if "initiative" in inspect(row).unloaded
            else getattr(row, "initiative", None)
        )
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                InitiativeMessages.CONTENT_KEPT_IN
                if initiative is not None and initiative.keep_content_in
                else ExportMessages.EXPORT_OWNER_REQUIRED
            ),
        )
    if context is not None and context.content_read_only:
        return resource.name.write_required()
    # Archived or trashed content is read-only, and so is everything under it.
    # Not a permission answer — the caller may well own it — so it carries its
    # own code and its own status, and the thing to do is bring it back first.
    frozen = (
        ancestor_is_frozen(row) if action is Action.unarchive else row_is_frozen(row)
    )
    if frozen:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.CONTENT_IS_FROZEN,
        )
    if (
        action is Action.share
        and context is not None
        and context.grant_content is not None
    ):
        return resource.name.grant_cannot_manage_members()
    if action in (Action.delete, Action.share):
        return resource.name.owner_required()
    if action is Action.configure:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ProjectMessages.CONFIGURE_REQUIRED,
        )
    return resource.name.write_required()


def require_access(
    resource: DacResource,
    row: Any,
    *,
    context: ActorContext | None,
    access: str = "read",
    action: Action | None = None,
) -> None:
    """Raise unless the request may take ``action`` on ``row`` — ``access``
    ``"write"`` is :attr:`Action.edit` — as ``resource_actions`` answered it.

    Reading asks nothing here: the row was loaded through a routed session, and
    a row the reader may not read does not arrive to be checked."""
    if action is None:
        if access != "write":
            return
        action = Action.edit
    if not allows(row, action):
        raise _refusal(resource, row, action, context)


#: What exporting one tool asks for. An export hands the whole thing over at
#: once, so it takes the rung that may also delete it — archived or not, since
#: an export changes nothing. The initiative and community backups read what
#: their scope reaches instead, and pass ``"read"``.
EXPORT_ACCESS = "owner"


def require_export_access(
    resource: DacResource,
    row: Any,
    *,
    context: ActorContext | None,
    access: str = EXPORT_ACCESS,
) -> None:
    """Raise unless the request may export ``row``: the export action for a
    tool exported on its own, a read for one inside a backup."""
    if access == EXPORT_ACCESS:
        require_access(resource, row, context=context, action=Action.export)


def client_access(
    row: Any, user_id: int | None, *, context: ActorContext | None
) -> dict[str, bool]:
    """What the caller may do to ``row``, for its read schema's ``can``."""
    if user_id is None and not isinstance(context, InstallContext):
        return {}
    held = actions_of(row)
    return {action.value: action.value in held for action in TOOL_CAN}


def require_project_configure(
    project: Project, *, context: ActorContext | None
) -> None:
    """Raise 403 unless the request may configure the project itself — pin it,
    set its default view and its views: a guild admin, a manager of the owning initiative, or the
    project's owner, on a live project."""
    require_access(
        DAC_RESOURCES[Tool.project], project, context=context, action=Action.configure
    )
