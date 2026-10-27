"""Router-level resource authorization — one load-and-check choke point.

`authorize` is the single access decision (feature gate + manage block + DAC);
`load_authorized` and `resource_dependency` add loading on top for fetch-then-act
handlers and FastAPI-injected routes. `RESOURCE_ACCESS` is the enforcement-side
registry: one entry per `Tool`, carrying only how a row is loaded and addressed.
Everything it answers with is derived from the tool itself.

`load_child` does the same for a row inside a tool (`SUB_TOOLS`), which its
tool's sharing reaches — or, for a kind in no one instance of its tool (a
collection), its own rule.
"""

# NOT `from __future__ import annotations`: resource_dependency builds a signature
# with Annotated[int, Path(alias=cfg.path_param)] closing over a local; stringized
# annotations re-evaluate it where cfg is out of scope → FastAPI drops the path
# param and 422s.

from dataclasses import dataclass, field
from typing import Annotated, Any, Awaitable, Callable, Mapping, Optional, TypeVar

from fastapi import Depends, HTTPException, status

from app.api.deps import (
    ActorContext,
    get_current_active_user,
)
from app.core.plugin_scopes import PluginScopeAccess, scope_name, tool_resource
from app.core.messages import (
    CommonMessages,
    KindMessages,
    PluginMessages,
    InitiativeMessages,
)
from app.core.errors import CodedError
from app.core.tools import KIND_BY_TABLE, KINDS, Tool, kind_refusal
from app.db.frozen import row_is_frozen
from app.db.guild_standing import InstallContext
from app.db.initiative_rls import governing_path
from app.db.session import require_actor_context
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.counter import Counter
from app.models.tenant.collection import Collection
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.queue import QueueItem
from app.models.tenant.wiki import WikiPage
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.task import Task
from app.models.platform.user import User
from sqlalchemy import inspect
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.services import permissions as permissions_service
from app.services.permissions import Action
from app.services import rls as rls_service
from app.services import reachability
from app.services.tenant import ownership as ownership_service
from app.services.tenant import calendar_events as events_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import counters as counters_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import files as files_service
from app.services.tenant import collections as collections_service
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import wikis as wikis_service
from app.services.tenant import posts as posts_service
from app.services.tenant import named_people
from app.services.tenant import project_grants
from app.services.tenant import queues as queues_service
from app.services.tenant import task_queries

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@dataclass(frozen=True)
class ResourceAccessConfig:
    """How one tool is loaded, and what it says when it refuses.

    Only the function that loads a row is genuinely per-tool. The path
    parameter a row is addressed by and every refusal are derived from
    ``tool``, so each tool has the full set and none of them can be written out
    by hand.
    """

    tool: Tool
    #: async (session, id) -> row | None
    loader: Callable[..., Awaitable[Any]]
    #: async (session, id) -> row | None, for a handler that also *serializes*
    #: the row it authorized: the eager loads a read response reads off it.
    #: ``None`` where ``loader`` already carries them. A tool whose response
    #: reads more than the decision does — its tags, properties, comment
    #: count, a project's statuses, a file's body — has one, so a gate
    #: check does not cost every caller the queries none of them reads.
    hydrated_loader: Optional[Callable[..., Awaitable[Any]]] = None
    #: A path parameter that differs from ``<tool>_id``.
    id_param: Optional[str] = None

    @property
    def path_param(self) -> str:
        """The path parameter a row is addressed by."""
        return self.id_param or f"{self.tool.value}_id"

    @property
    def dac_kind(self) -> Tool:
        """Key into ``permissions.DAC_RESOURCES``."""
        return self.tool

    @property
    def feature_attr(self) -> str:
        """The initiative flag gating the whole tool."""
        return self.tool.view_permission


RESOURCE_ACCESS: dict[Tool, ResourceAccessConfig] = {
    Tool.project: ResourceAccessConfig(
        Tool.project,
        project_grants.get_project,
        hydrated_loader=project_grants.get_project_hydrated,
    ),
    Tool.file: ResourceAccessConfig(
        Tool.file,
        files_service.get_file_for_grants,
        hydrated_loader=files_service.get_file_hydrated,
    ),
    Tool.queue: ResourceAccessConfig(
        Tool.queue,
        queues_service.get_queue,
        hydrated_loader=queues_service.get_queue_hydrated,
    ),
    # Counter group routes name their row ``group_id``.
    Tool.counter_group: ResourceAccessConfig(
        Tool.counter_group, counters_service.get_counter_group, id_param="group_id"
    ),
    Tool.calendar: ResourceAccessConfig(Tool.calendar, calendars_service.get_calendar),
    Tool.dashboard: ResourceAccessConfig(
        Tool.dashboard,
        dashboards_service.get_dashboard,
        hydrated_loader=dashboards_service.get_dashboard_hydrated,
    ),
    Tool.post: ResourceAccessConfig(Tool.post, posts_service.get_post),
    Tool.wiki: ResourceAccessConfig(
        Tool.wiki,
        wikis_service.get_wiki,
        hydrated_loader=wikis_service.get_wiki_hydrated,
    ),
}


# The tools whose sharing can be set through the unified *local* grant flow
# (``set_resource_grants`` / the bulk endpoint) — exactly the tools registered
# above, derived so the two never drift.
GRANTABLE_KINDS: tuple[Tool, ...] = tuple(RESOURCE_ACCESS)


def governing_tool(table: str) -> Tool:
    """The tool whose sharing governs one content table's rows.

    Read from ``initiative_rls.governing_path`` — the same registry the table's
    RLS policy is rendered from — so an endpoint that reaches a sub-resource's
    parent cannot name a different tool from the one the database asked about.
    A task's is ``project``, and it is one edit away from staying that way if
    the hierarchy ever changes.
    """
    path = governing_path(table)
    if path is None:
        # Config bug, not a request error: the caller named a table whose
        # governing tool is a property of the row (a comment, a reaction) or
        # that no tool's sharing governs at all.
        raise RuntimeError(f"no single tool governs {table!r}")
    return path[0]


def require_tool_enabled(kind: Tool, initiative: Any) -> None:
    """Raise 403 unless ``initiative`` has ``kind``'s master switch on.

    Gate 3's first half at the moment of creation, where there is no row yet for
    ``require_access`` to read the switch off. The message comes from the
    registry, so a tool is gated by registering it rather than by spelling the
    refusal again at each create endpoint.

    The database asks the same question on INSERT — the rendered policy's
    ``{plural}_enabled`` leg. This runs first so the answer is a named 403
    rather than a row that silently fails to appear.
    """
    attr = RESOURCE_ACCESS[kind].feature_attr
    if attr is not None and not getattr(initiative, attr):
        raise kind.disabled()


async def require_create(
    session: Any,
    kind: Tool,
    initiative: Any,
    user: Optional[User],
    guild_context: ActorContext,
) -> None:
    """Raise 403 unless this caller may create a ``kind`` in ``initiative``.

    Gate 3 at the moment of creation: the initiative role's create right for
    the tool, with a guild admin above it. The permission key comes from the
    tool (``Tool.create_permission``) and so does the refusal, so a new tool
    is gated by registering it rather than by copying this.

    The database asks the same question on INSERT — the rendered policy's
    ``initiative_role_permits(..., create_<plural>, false)`` leg. This one runs
    first so the answer is a named 403.
    """
    if guild_context.is_admin:
        return
    if await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=PermissionKey(kind.create_permission),
    ):
        return
    raise kind.create_denied()


async def prepare_create(
    session: Any,
    kind: Tool,
    initiative_id: Optional[int],
    user: Optional[User],
    guild_context: ActorContext,
) -> Initiative:
    """The initiative a new ``kind`` goes into, once the caller may make one
    there: it is named and exists (404), its switch for the tool is on
    (:func:`require_tool_enabled`) and the caller's role may create the tool
    (:func:`require_create`). Every tool's create and duplicate start here.
    """
    initiative = (
        await session.get(Initiative, initiative_id)
        if initiative_id is not None
        else None
    )
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    require_tool_enabled(kind, initiative)
    await require_create(session, kind, initiative, user, guild_context)
    return initiative


def duplicate_sharing(source: Any, *, initiative_id: int) -> list[ResourceGrantSchema]:
    """Who a duplicate of ``source`` is shared with: the same people and roles
    as ``source`` while it stays in the same initiative, where they exist, and
    the create default when it goes to another. ``source.grants`` is loaded."""
    if initiative_id != source.initiative_id:
        return initiative_readable()
    return [
        ResourceGrantSchema.model_validate(grant)
        for grant in source.grants
        if grant.level != ResourceAccessLevel.owner and grant.plugin_install_id is None
    ]


#: The scope an installed plug-in holds to change a resource's sharing.
SHARING_WRITE = "sharing:write"

#: What else an installed plug-in's sharing change reads: the initiative's roster,
#: and the roles on it, which validate the grantees and settle who keeps
#: write access afterwards.
_SHARING_READS = ("members:read", "initiatives:read")


def refuse_plugin_sharing(actor: ActorContext, payload: Any, *fields: str) -> None:
    """Raise 403 when an installed plug-in's create sets any of ``fields`` — its
    initial sharing — without ``sharing:write``.

    What a plug-in creates is owned by its install, whose owner row the tool
    table's trigger writes. With the scope, the initial sharing is applied as
    a later share would be (:func:`apply_plugin_initial_sharing`). A field left at
    its default is not a request to share, so only the ones the payload sets
    are refused.
    """
    if not isinstance(actor, InstallContext):
        return
    if not any(field in payload.model_fields_set for field in fields):
        return
    require_install_may_share(actor, None)


def require_install_may_share(actor: ActorContext, kind: Optional[Tool]) -> None:
    """Raise 403 unless an installed plug-in's standing lets it change sharing:
    ``sharing:write``, the tool's write scope when ``kind`` is named, and the
    roster reads a sharing change makes. A person passes; their rung on the
    resource is asked by :func:`authorize`, as the install's is too.
    """
    if not isinstance(actor, InstallContext):
        return
    if not actor.holds(SHARING_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SHARING_NOT_AVAILABLE,
        )
    needed = list(_SHARING_READS)
    if kind is not None:
        needed.append(scope_name(tool_resource(kind), PluginScopeAccess.write))
    if not all(actor.holds(scope) for scope in needed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )


def refuse_install_community_share(
    actor: ActorContext, initiative_id: Optional[int]
) -> None:
    """Raise 403 when an installed plug-in would share a resource that belongs to
    no initiative. Such a resource is shared with the community's members,
    whom a plug-in does not read."""
    if isinstance(actor, InstallContext) and initiative_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SHARING_NOT_AVAILABLE,
        )


async def apply_plugin_initial_sharing(
    session: Any,
    actor: ActorContext,
    kind: Tool,
    *,
    resource_id: int,
    initiative_id: Optional[int],
    payload: Any,
    grants: list[ResourceGrantSchema],
) -> None:
    """Apply the initial sharing an installed plug-in's create asked for.

    Only when the payload set ``grants``: a plug-in's content is otherwise shared
    with nobody beyond its owner row until it shares it. The install's own
    owner row went in with the resource, so its rung there is the owner's, and
    the database asks the same of each grant row it writes. Caller flushes.
    """
    if not isinstance(actor, InstallContext):
        return
    if payload is None or "grants" not in payload.model_fields_set:
        return
    require_install_may_share(actor, kind)
    refuse_install_community_share(actor, initiative_id)
    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind.value,
        resource_id=resource_id,
        guild_id=actor.guild_id,
        initiative_id=initiative_id,
        # A member token's creation is owned by the member it acts for.
        owner_id=actor.member_user_id,
        grants=grants,
        by_install=True,
    )


async def grant_initial_sharing(
    session: Any,
    actor: ActorContext,
    kind: Tool,
    *,
    user: Optional[User],
    resource_id: int,
    initiative_id: Optional[int],
    payload: Any,
    grants: list[ResourceGrantSchema],
) -> None:
    """Share a resource that has just been made: its maker owns it — the
    table's own trigger wrote that row as the resource went in — and ``grants``
    says who else may reach it. An installed plug-in applies only the sharing its
    create asked for (:func:`apply_plugin_initial_sharing`). A guest shares
    nothing: what they make is theirs alone. The row is flushed first; the
    caller commits.
    """
    if actor.guest:
        return
    if actor.user_id is None or user is None:
        await apply_plugin_initial_sharing(
            session,
            actor,
            kind,
            resource_id=resource_id,
            initiative_id=initiative_id,
            payload=payload,
            grants=grants,
        )
        return
    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind.value,
        resource_id=resource_id,
        guild_id=actor.guild_id,
        initiative_id=initiative_id,
        owner_id=user.id,
        grants=grants,
        actor_user_id=user.id,
    )


def authorize(
    kind: Tool,
    row: Any,
    user: Optional[User] = None,
    *,
    context: Optional[ActorContext],
    access: str = "read",
    action: Optional[Action] = None,
) -> None:
    """Feature gate → the action ``resource_actions`` answered for the row.

    ``context`` is the reader's standing in the community, as the seam computed
    it — the same object the session was routed with, so what this decides and
    what the policies evaluate are the same facts.

    ``action`` names what the caller is about to do beyond reading;
    ``access="write"`` is an edit."""
    cfg = RESOURCE_ACCESS[kind]
    initiative = getattr(row, "initiative", None)
    if initiative is not None and not getattr(initiative, cfg.feature_attr):
        raise kind.disabled()
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[cfg.dac_kind],
        row,
        context=context,
        access=access,
        action=action,
    )


async def load_authorized(
    session: Any,
    kind: Tool,
    resource_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    *,
    access: str = "read",
    action: Optional[Action] = None,
    hydrated: bool = False,
) -> Any:
    """Load by id (RLS scopes to the guild) → 404 if absent, then authorize.

    ``hydrated=True`` takes the tool's wider loader, for a handler that goes on
    to serialize the row it just authorized.
    """
    cfg = RESOURCE_ACCESS[kind]
    loader = cfg.hydrated_loader if hydrated and cfg.hydrated_loader else cfg.loader
    row = await loader(session, resource_id)
    if row is None:
        reader = guild_context.user_id
        if reader is not None and await reachability.reader_is_in_the_initiative(
            kind.plural, resource_id, reader, guild_context.guild_id
        ):
            # In the initiative, so the row is theirs to know about — sharing is
            # what refused it, and "denied" is the answer to that.
            raise kind.not_found(status.HTTP_403_FORBIDDEN)
        raise kind.not_found()
    authorize(
        kind,
        row,
        user,
        context=guild_context,
        access=access,
        action=action,
    )
    return row


@dataclass(frozen=True)
class SubTool:
    """A row inside a tool, reached by its tool's sharing. Which tool, and the
    column that names it, come from ``initiative_rls.governing_path``."""

    #: async (session, id, *, populate_existing) -> the row, with its tool,
    #: that tool's initiative and ``actions`` loaded.
    load: Callable[..., Awaitable[Any]]
    #: The column holding what it is called.
    name: str = "title"
    #: Columns a copy starts afresh rather than carries.
    copy_resets: Mapping[str, Any] = field(default_factory=dict)


SUB_TOOLS: dict[type, SubTool] = {
    Task: SubTool(task_queries.load_for_change),
    CalendarEvent: SubTool(events_service.get_event),
    Counter: SubTool(counters_service.get_counter, name="name"),
    # A copy is not held out of the rotation.
    QueueItem: SubTool(
        queues_service.get_queue_item,
        name="label",
        copy_resets={"held_at_round": None},
    ),
    WikiPage: SubTool(
        wikis_service.get_page,
        copy_resets={"yjs_state": None, "yjs_updated_at": None},
    ),
    Collection: SubTool(collections_service.get_collection, name="name"),
}


def _standalone(model: type) -> bool:
    """Whether ``model`` sits in its tool but in no one instance of it."""
    return KIND_BY_TABLE[model.__tablename__].standalone


def parent_column(model: type) -> str:
    """The column of a row inside a tool that names its tool."""
    path = governing_path(model.__tablename__)
    assert path is not None, model
    ((column, _table),) = path[1]
    return column


async def require_may_change(
    session: Any, row: Any, user: Optional[User], context: ActorContext
) -> None:
    """Raise unless the request may change ``row``, a kind in no one instance
    of its tool: its tool switched on in the row's initiative, a role there
    that creates the tool, and the row neither archived nor in the trash. A
    collection, which a file maker changes whoever's files are in it."""
    kind = KIND_BY_TABLE[type(row).__tablename__]
    if context.content_read_only:
        raise kind_refusal(kind.value, KindMessages.WRITE_ACCESS_REQUIRED, 403)
    if row_is_frozen(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.CONTENT_IS_FROZEN,
        )
    require_tool_enabled(kind.tool, row.initiative)
    await require_create(session, kind.tool, row.initiative, user, context)


async def may_change(session: Any, row: Any, context: ActorContext) -> bool:
    """Whether :func:`require_may_change` would let the request change ``row``,
    for a read that reports it."""
    try:
        await require_may_change(session, row, None, context)
    except (HTTPException, CodedError):
        return False
    return True


Child = TypeVar("Child")


async def load_child(
    session: Any,
    model: type[Child],
    child_id: int,
    *,
    access: str = "read",
    action: Optional[Action] = None,
    parent_id: Optional[int] = None,
) -> Child:
    """A row inside a tool, by its own loader, refused as its tool would be
    (:func:`authorize`) for the standing the session was routed with.
    ``parent_id`` is the tool a route addresses it under, whose own refusal
    comes first when the row is out of reach."""
    context = require_actor_context(session)
    if _standalone(model):
        row = await SUB_TOOLS[model].load(session, child_id)
        if row is None:
            raise _missing(model)
        if access != "read" or action is not None:
            await require_may_change(session, row, None, context)
        return row
    kind = governing_tool(model.__tablename__)
    column = parent_column(model)
    row = await SUB_TOOLS[model].load(session, child_id)
    if row is None or (parent_id is not None and getattr(row, column) != parent_id):
        if parent_id is not None:
            await load_authorized(
                session, kind, parent_id, None, context, access=access, action=action
            )
        raise _missing(model)
    authorize(kind, parent_of(row), context=context, access=access, action=action)
    return row


async def load_kind(
    session: Any,
    kind: str,
    entity_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> Any:
    """A tool or a row inside one, by its kind, read as its own page reads it
    and refused in its own words."""
    from app.db.base import MODELS_BY_TABLE

    if KINDS[kind].parent is None:
        return await load_authorized(
            session, Tool(kind), entity_id, user, guild_context
        )
    return await load_child(session, MODELS_BY_TABLE[KINDS[kind].table], entity_id)


def parent_of(row: Any) -> Any:
    """The tool a row inside a tool sits in. A kind in no one instance of its
    tool answers for itself."""
    model = type(row)
    if _standalone(model):
        return row
    column = parent_column(model)
    return next(
        getattr(row, r.key)
        for r in inspect(model).relationships
        if [c.name for c in r.local_columns] == [column]
    )


async def require_stays_in(
    session: Any, source_initiative_id: Optional[int], initiative_id: Optional[int]
) -> None:
    """Refuse taking content of ``source_initiative_id`` into
    ``initiative_id`` when the source keeps its content in. Every copy and
    move into another initiative asks it."""
    if source_initiative_id != initiative_id and (
        await initiatives_service.keeps_content_in(session, [source_initiative_id])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.CONTENT_KEPT_IN,
        )


async def require_may_move(session: Any, row: Any, destination: Any) -> None:
    """Whether ``row``, a row inside a tool, may go into ``destination``,
    another of its tool: not out of an initiative that keeps its content in
    (:func:`require_stays_in`)."""
    await require_stays_in(
        session, parent_of(row).initiative_id, destination.initiative_id
    )


async def reload_child(session: Any, model: type[Child], child_id: int) -> Child:
    """A row inside a tool again after a change, as its loader reads it."""
    row = await SUB_TOOLS[model].load(session, child_id, populate_existing=True)
    if row is None:
        raise _missing(model)
    return row


def _missing(model: type) -> Exception:
    return KIND_BY_TABLE[model.__tablename__].not_found()


# ── Unified grant-set flow ───────────────────────────────────────────────────
# One code path for replacing a resource's sharing — used by every per-resource
# ``PUT /{id}/grants`` endpoint and by the bulk endpoint.


async def set_resource_grants(
    session: Any,
    kind: Tool,
    resource_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    grants: list[ResourceGrantSchema],
) -> None:
    """Replace one resource's sharing the unified way: load + 404, authorize
    the share action (``Action.share``), rebuild every non-owner grant from
    ``grants`` (owner preserved), then take anyone the new sharing does not
    reach off the content inside it (``named_people.sweep``). Commits. Raises
    ``HTTPException`` 404 (missing) / 403 (no manage access) / 409 (archived or
    trashed). The single source of truth behind the per-resource grant
    endpoints and the bulk endpoint.

    An installed plug-in changes sharing where a person with its rung could, and
    only with ``sharing:write`` and the tool's write scope
    (:func:`require_install_may_share`)."""
    require_install_may_share(guild_context, kind)
    row = await load_authorized(
        session,
        kind,
        resource_id,
        user,
        guild_context,
        action=Action.share,
    )
    refuse_install_community_share(guild_context, row.initiative_id)
    settled = named_people.Governing.of(kind, row)
    if kind is Tool.file:
        # Who a collection may name is whoever can open a file in it.
        collections_service.settle_after_commit(session, left_files=[row.id])
    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind,
        resource_id=row.id,
        guild_id=guild_context.guild_id,
        initiative_id=row.initiative_id,
        owner_id=ownership_service.owner_user_id_of(row),
        grants=grants,
        actor_user_id=guild_context.user_id,
        by_install=isinstance(guild_context, InstallContext),
    )
    await session.commit()
    # Only people who can open the resource are named inside it: those the new
    # sharing does not reach are let go, once that sharing is committed.
    if await named_people.sweep(session, settled):
        await session.commit()
