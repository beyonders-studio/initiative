"""CRUD endpoints for metadata definitions: an initiative's properties, and a
project's or a collection's metadata.

A project's metadata is made, changed and removed by whoever may write the
project's tasks, as its task types are, and an installed plug-in does so with
the projects scope. A collection's is by whoever may change the collection
(``resource_access.require_may_change``), and an installed plug-in does so
with the files scope, since a collection is part of Files. A plug-in's own
metadata is declared by its manifest, and never made here."""

from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import joinedload, selectinload, undefer
from sqlmodel import col, delete, or_, select

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    InstallContext,
    plugin_scope_checked,
)
from app.core.errors import CodedError
from app.core.messages import InitiativeMessages, PluginMessages, PropertyMessages
from app.core.plugin_scopes import tool_resource
from app.core.tools import KINDS, Tool
from app.db.frozen import row_is_frozen
from app.models.tenant.collection import Collection
from app.models.tenant.initiative import Initiative
from app.models.platform.user import User
from app.models.tenant.project import Project
from app.models.tenant.metadata import (
    MetadataDefinition,
    MetadataType,
)
from app.schemas.tenant.property import (
    MetadataOwnerKind,
    PropertyDefinitionBulkDelete,
    PropertyDefinitionCreate,
    PropertyDefinitionGroup,
    PropertyDefinitionGroups,
    PropertyDefinitionPromote,
    PropertyDefinitionRead,
    PropertyDefinitionUpdate,
    PropertyDefinitionUpdateResponse,
)
from app.services.tenant import metadata as metadata_service
from app.services.tenant.names import ensure_name_free

router = APIRouter(route_class=ActorRoute)

#: An installed plug-in reads definitions with ``properties:read``, or with any
#: tool's scope: a value is set with the scope of the tool its item belongs to,
#: and it is chosen from these.
_DEFINITION_READ_SCOPES: tuple[str, ...] = (
    "properties:read",
    *(f"{tool_resource(tool).value}:read" for tool in Tool),
)
PropertyDefinitionsRead = Annotated[
    ActorContext, Depends(plugin_scope_checked(_DEFINITION_READ_SCOPES, per="tool"))
]
_PROPERTIES_WRITE = "properties:write"
_PROJECTS_WRITE = f"{tool_resource(Tool.project).value}:write"
_FILES_WRITE = f"{tool_resource(Tool.file).value}:write"
#: An installed plug-in writes an initiative's properties with
#: ``properties:write``, a project's metadata with ``projects:write``, and a
#: collection's with ``files:write``.
PropertyDefinitionsWrite = Annotated[
    ActorContext,
    Depends(
        plugin_scope_checked(
            (_PROPERTIES_WRITE, _PROJECTS_WRITE, _FILES_WRITE), per="owner's scope"
        )
    ),
]


def _require_scope(guild_context: ActorContext, scope: str) -> None:
    """A 403 for an installed plug-in without ``scope``."""
    if isinstance(guild_context, InstallContext) and not guild_context.holds(scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )


def _require_write_scope(
    guild_context: ActorContext,
    defn: MetadataDefinition | PropertyDefinitionCreate,
) -> None:
    """A 403 for an installed plug-in without the scope this definition's
    writes take."""
    _require_scope(
        guild_context,
        _PROJECTS_WRITE
        if defn.project_id is not None
        else _FILES_WRITE
        if defn.collection_id is not None
        else _PROPERTIES_WRITE,
    )


async def _changed_collection(
    session: AsyncSession, collection_id: int, initiative_id: int
) -> Collection:
    """The collection a field belongs to, once the request may change it, in
    ``initiative_id``."""
    collection = await resource_access.load_child(
        session, Collection, collection_id, access="write"
    )
    if collection.initiative_id != initiative_id:
        raise KINDS["collection"].not_found()
    return collection


async def _configured_project(
    session: AsyncSession,
    project_id: int,
    initiative_id: int,
    user: User,
    guild_context: ActorContext,
) -> Project:
    """The project a definition belongs to, once the request may write its
    tasks, as its task types ask, in ``initiative_id``."""
    project = await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        user,
        guild_context,
        access="write",
    )
    if project.initiative_id != initiative_id:
        raise Tool.project.not_found()
    return project


async def _require_owner_writable(
    session: AsyncSession,
    defn: MetadataDefinition | PropertyDefinitionCreate,
    user: User,
    guild_context: ActorContext,
) -> bool:
    """Raise unless the request may define a project's or a collection's
    metadata, answering whether ``defn`` is one; an initiative's property is
    the caller's to decide."""
    if defn.project_id is not None:
        await _configured_project(
            session, defn.project_id, defn.initiative_id or 0, user, guild_context
        )
    elif defn.collection_id is not None:
        await _changed_collection(session, defn.collection_id, defn.initiative_id or 0)
    else:
        return False
    return True


async def _require_removable(
    session: AsyncSession,
    definitions: Sequence[MetadataDefinition],
    user: User,
    guild_context: ActorContext,
) -> None:
    """Raise unless the request may remove every one of ``definitions``, as
    removing each alone asks: its project or collection writable, or for the
    initiative's metadata, a manager. Each owner is asked once."""
    asked: set[tuple[Optional[int], Optional[int]]] = set()
    for defn in definitions:
        _require_write_scope(guild_context, defn)
        owner = (defn.project_id, defn.collection_id)
        if owner in asked:
            continue
        asked.add(owner)
        if not await _require_owner_writable(
            session, defn, user, guild_context
        ) and not _manages(guild_context, defn.initiative_id):
            raise _manager_required()


async def _editable_projects(
    session: AsyncSession, project_ids: set[int], guild_context: ActorContext
) -> dict[int, str]:
    """The name of each of these projects whose properties the request may
    edit, by id: the projects it may write the tasks of, as defining a
    project's property asks (:func:`_configured_project`)."""
    if not project_ids:
        return {}
    rows = await session.exec(
        select(Project)
        .where(col(Project.id).in_(project_ids))
        .options(joinedload(Project.initiative), undefer(Project.actions))
    )
    editable: dict[int, str] = {}
    for project in rows.unique().all():
        try:
            resource_access.authorize(
                Tool.project, project, context=guild_context, access="write"
            )
        except (HTTPException, CodedError):
            continue
        editable[int(project.id or 0)] = project.name
    return editable


async def _editable_collections(
    session: AsyncSession, collection_ids: set[int], guild_context: ActorContext
) -> dict[int, str]:
    """The name of each of these collections whose properties the request may
    edit, by id: the collections it may change, as defining a collection's
    property asks (:func:`_changed_collection`). The answer is the
    initiative's and whether the collection is put away, so it is asked once
    for each."""
    if not collection_ids:
        return {}
    rows = await session.exec(
        select(Collection)
        .where(col(Collection.id).in_(collection_ids))
        .options(selectinload(Collection.initiative))
    )
    answers: dict[tuple[int, bool], bool] = {}
    editable: dict[int, str] = {}
    for collection in rows.all():
        key = (collection.initiative_id, row_is_frozen(collection))
        if key not in answers:
            answers[key] = await resource_access.may_change(
                session, collection, guild_context
            )
        if answers[key]:
            editable[int(collection.id or 0)] = collection.name
    return editable


async def _definitions_or_404(
    session: AsyncSession,
    initiative_id: int,
    ids: Sequence[int],
    *,
    owned: bool = False,
) -> list[MetadataDefinition]:
    """``ids``, each a definition of the initiative's that people define, in
    the order named; with ``owned``, each a project's or a collection's
    property. One that is not answers 404 for them all. Read, not locked: a
    definition the request may read but not change is refused by name once
    asked (:func:`_require_removable`), and then locked (:func:`_lock`)."""
    stmt = select(MetadataDefinition).where(
        col(MetadataDefinition.id).in_(ids),
        MetadataDefinition.initiative_id == initiative_id,
        col(MetadataDefinition.install_id).is_(None),
    )
    if owned:
        stmt = stmt.where(
            or_(
                col(MetadataDefinition.project_id).is_not(None),
                col(MetadataDefinition.collection_id).is_not(None),
            )
        )
    found = {defn.id: defn for defn in (await session.exec(stmt)).all()}
    if set(found) != set(ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PropertyMessages.DEFINITION_NOT_FOUND,
        )
    return [found[definition_id] for definition_id in dict.fromkeys(ids)]


async def _lock(
    session: AsyncSession, definitions: Sequence[MetadataDefinition]
) -> None:
    """Lock ``definitions`` for the change, once the request may make it,
    reading each again as it now stands. Locking takes the write policy, so
    one gone or out of reach since it was read answers 404."""
    ids = [defn.id for defn in definitions]
    locked = await session.exec(
        select(MetadataDefinition.id)
        .where(col(MetadataDefinition.id).in_(ids))
        .with_for_update()
    )
    if set(locked.all()) != set(ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PropertyMessages.DEFINITION_NOT_FOUND,
        )
    for defn in definitions:
        await session.refresh(defn)


def _same_scope(defn: MetadataDefinition | PropertyDefinitionCreate) -> list:
    """What a definition's name is unique among: the initiative's properties,
    the project's metadata, or the collection's."""
    return [
        MetadataDefinition.initiative_id == defn.initiative_id,
        col(MetadataDefinition.project_id).is_not_distinct_from(defn.project_id),
        col(MetadataDefinition.collection_id).is_not_distinct_from(defn.collection_id),
    ]


async def _get_definition_or_404(
    session: AsyncSession, definition_id: int
) -> MetadataDefinition:
    """Fetch a definition by id, relying on RLS for scope enforcement.

    MUST be called with a routed session (``ActorSessionDep``). Under
    schema-per-guild, ``property_definitions`` lives only in the active
    guild's schema, and definition ids are unique per-guild — the routing is
    what decides which guild's row an id resolves to.
    """
    stmt = select(MetadataDefinition).where(
        MetadataDefinition.id == definition_id,
        col(MetadataDefinition.install_id).is_(None),
    )
    result = await session.exec(stmt)
    defn = result.one_or_none()
    if defn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PropertyMessages.DEFINITION_NOT_FOUND,
        )
    return defn


async def _ensure_initiative_member(
    session: AsyncSession,
    guild_context: ActorContext,
    initiative_id: int,
) -> None:
    """Raise 403 unless the caller is in the initiative, or administers the
    community.

    The initiative must exist in this community's schema first, so a foreign or
    deleted id answers ``NOT_INITIATIVE_MEMBER`` rather than a foreign-key
    error on insert. A person is in the initiatives they are a member of, and
    an installed plug-in in the ones it is placed in; the standing holds both.
    """
    init_stmt = select(Initiative.id).where(Initiative.id == initiative_id)
    if (await session.exec(init_stmt)).one_or_none() is None or not (
        guild_context.is_admin or initiative_id in guild_context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PropertyMessages.NOT_INITIATIVE_MEMBER,
        )


def _manages(guild_context: ActorContext, initiative_id: int) -> bool:
    """Reshaping or removing a definition is how the initiative is set up, so it
    takes a manager of the initiative or an admin of the community."""
    return guild_context.is_admin or initiative_id in guild_context.manager_initiatives


def _manager_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=InitiativeMessages.MANAGER_REQUIRED,
    )


def _added_options(defn: MetadataDefinition, options: list) -> list[dict]:
    """The options among ``options`` that ``defn`` does not have yet — what a
    member adds picking a value nobody has offered. One it already has stays
    as it is."""
    existing = {opt.get("value") for opt in defn.options or []}
    return [
        opt for opt in _serialize_options(options) or [] if opt["value"] not in existing
    ]


def _serialize_options(options: Optional[list]) -> Optional[list[dict]]:
    """Coerce PropertyOption models into plain dicts for JSONB storage."""
    if options is None:
        return None
    serialized: list[dict] = []
    for opt in options:
        if hasattr(opt, "model_dump"):
            serialized.append(opt.model_dump(exclude_none=True))
        elif isinstance(opt, dict):
            serialized.append(opt)
    return serialized


@router.get("/", response_model=List[PropertyDefinitionRead])
async def list_property_definitions(
    session: ActorSessionDep,
    guild_context: PropertyDefinitionsRead,
    initiative_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(
        default=None,
        description="List this project's metadata instead of properties.",
    ),
    collection_id: Optional[int] = Query(
        default=None,
        description="List this collection's metadata instead of properties.",
    ),
) -> Sequence[MetadataDefinition]:
    """List property definitions, or a project's or a collection's metadata.

    With ``initiative_id``, returns definitions for that initiative only
    (filtered explicitly and subject to RLS). Without it, RLS returns the
    union across every initiative the caller can see — used by global
    views (My Tasks, Created Tasks, global Files list). A project's metadata
    is listed only with its ``project_id``, and only to whoever can open the
    project; a collection's only with its ``collection_id``, and only to
    whoever sees the collection.
    """
    if isinstance(guild_context, InstallContext) and not any(
        guild_context.holds(scope) for scope in _DEFINITION_READ_SCOPES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )
    stmt = select(MetadataDefinition).where(
        col(MetadataDefinition.project_id).is_not_distinct_from(project_id),
        col(MetadataDefinition.collection_id).is_not_distinct_from(collection_id),
        col(MetadataDefinition.install_id).is_(None),
    )
    if initiative_id is not None:
        stmt = stmt.where(MetadataDefinition.initiative_id == initiative_id)
    stmt = stmt.order_by(
        MetadataDefinition.position.asc(), MetadataDefinition.name.asc()
    )
    result = await session.exec(stmt)
    return result.all()


@router.get("/by-owner", response_model=PropertyDefinitionGroups)
async def list_property_definitions_by_owner(
    session: ActorSessionDep,
    guild_context: PropertyDefinitionsRead,
    initiative_id: int = Query(),
) -> PropertyDefinitionGroups:
    """The initiative's metadata, then the properties of each of its projects
    and each of its collections, under the owner's name.

    A project's or a collection's are listed only to whoever may edit them,
    as making, changing and removing one asks; a role that reaches every
    project and collection (the community's admin, a live grant) is listed
    them all. ``can_edit`` says whether the reader may rename, reorder and
    delete a group's: a project's and a collection's always, as listed, and
    the initiative's for its managers and the community's admin.
    """
    if isinstance(guild_context, InstallContext) and not any(
        guild_context.holds(scope) for scope in _DEFINITION_READ_SCOPES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )
    await _ensure_initiative_member(session, guild_context, initiative_id)
    definitions = (
        await session.exec(
            select(MetadataDefinition)
            .where(
                MetadataDefinition.initiative_id == initiative_id,
                col(MetadataDefinition.install_id).is_(None),
            )
            .order_by(MetadataDefinition.position.asc(), MetadataDefinition.name.asc())
        )
    ).all()
    projects = await _editable_projects(
        session,
        {defn.project_id for defn in definitions if defn.project_id is not None},
        guild_context,
    )
    collections = await _editable_collections(
        session,
        {defn.collection_id for defn in definitions if defn.collection_id is not None},
        guild_context,
    )
    groups = [
        PropertyDefinitionGroup(
            owner=MetadataOwnerKind.initiative,
            can_edit=_manages(guild_context, initiative_id),
            definitions=[
                PropertyDefinitionRead.model_validate(defn)
                for defn in definitions
                if defn.project_id is None and defn.collection_id is None
            ],
        )
    ]
    for kind, names, column in (
        (MetadataOwnerKind.project, projects, "project_id"),
        (MetadataOwnerKind.collection, collections, "collection_id"),
    ):
        for owner_id, name in sorted(
            names.items(), key=lambda item: (item[1].casefold(), item[0])
        ):
            groups.append(
                PropertyDefinitionGroup(
                    owner=kind,
                    owner_id=owner_id,
                    name=name,
                    can_edit=True,
                    definitions=[
                        PropertyDefinitionRead.model_validate(defn)
                        for defn in definitions
                        if getattr(defn, column) == owner_id
                    ],
                )
            )
    return PropertyDefinitionGroups(groups=groups)


@router.post("/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property_definitions(
    payload: PropertyDefinitionBulkDelete,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertyDefinitionsWrite,
) -> None:
    """Delete several of the initiative's definitions at once, with every
    value of each: all of them, or, when any may not be removed as deleting it
    alone asks, none."""
    definitions = await _definitions_or_404(session, payload.initiative_id, payload.ids)
    await _require_removable(session, definitions, current_user, guild_context)
    await _lock(session, definitions)
    await session.exec(
        delete(MetadataDefinition).where(col(MetadataDefinition.id).in_(payload.ids))
    )
    await session.commit()


@router.post("/promote", response_model=PropertyDefinitionRead)
async def promote_property_definitions(
    payload: PropertyDefinitionPromote,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertyDefinitionsWrite,
) -> MetadataDefinition:
    """Merge properties of one type, from the initiative's projects and
    collections, into one of its metadata named ``name``, answering it.

    It is the initiative's metadata of that name and type if there is one, or
    a new one. Its options gain theirs, their values move to it, every layout
    showing one of them shows it instead, and they are deleted, in one
    transaction (``metadata_service.promote``). It asks to remove each of them
    as deleting it alone does, and to define the initiative's metadata, as
    making one does; an installed plug-in also needs ``properties:write``.
    """
    sources = await _definitions_or_404(
        session, payload.initiative_id, payload.ids, owned=True
    )
    await _require_removable(session, sources, current_user, guild_context)
    _require_scope(guild_context, _PROPERTIES_WRITE)
    await _ensure_initiative_member(session, guild_context, payload.initiative_id)
    await _lock(session, sources)
    target = await metadata_service.promote(session, sources, name=payload.name)
    await session.commit()
    await session.refresh(target)
    return target


@router.post(
    "/", response_model=PropertyDefinitionRead, status_code=status.HTTP_201_CREATED
)
async def create_property_definition(
    payload: PropertyDefinitionCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertyDefinitionsWrite,
) -> MetadataDefinition:
    """Create a new property definition on an initiative, or with
    ``project_id`` or ``collection_id`` that project's or collection's
    metadata.

    A property requires the caller to be in the target initiative (or a guild
    admin); an installed plug-in also needs ``properties:write``. A project's
    metadata requires the right to write the project's tasks (and
    ``projects:write`` of a plug-in); a collection's the right to change the
    collection (and ``files:write`` of a plug-in).
    """
    _require_write_scope(guild_context, payload)
    if not await _require_owner_writable(session, payload, current_user, guild_context):
        await _ensure_initiative_member(session, guild_context, payload.initiative_id)
    await ensure_name_free(
        session,
        MetadataDefinition.name,
        payload.name,
        *_same_scope(payload),
        detail=PropertyMessages.NAME_ALREADY_EXISTS,
    )

    defn = MetadataDefinition(
        initiative_id=payload.initiative_id,
        project_id=payload.project_id,
        collection_id=payload.collection_id,
        name=payload.name.strip(),
        type=payload.type,
        position=payload.position,
        color=payload.color,
        options=_serialize_options(payload.options),
        currency=payload.currency.value if payload.currency else None,
    )
    session.add(defn)
    await session.commit()
    await session.refresh(defn)
    return defn


@router.patch("/{definition_id}", response_model=PropertyDefinitionUpdateResponse)
async def update_property_definition(
    definition_id: int,
    payload: PropertyDefinitionUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertyDefinitionsWrite,
) -> PropertyDefinitionUpdateResponse:
    """Update a property definition.

    Type changes are not allowed via this endpoint; callers should
    delete the definition and re-create. Changing the option list on a
    select / multi_select definition returns ``orphaned_value_count`` so
    the SPA can warn about dangling values. A project's or a collection's
    metadata is changed by whoever may define it.
    """
    defn = await _get_definition_or_404(session, definition_id)
    _require_write_scope(guild_context, defn)

    data = payload.model_dump(exclude_unset=True)
    reshapes = await _require_owner_writable(
        session, defn, current_user, guild_context
    ) or _manages(guild_context, defn.initiative_id)
    if not reshapes:
        # A member adds options and nothing else: the ones sent that are new
        # join the list as it stands, so two members adding at once both land,
        # and the options already there are left as they are.
        if set(data) != {"options"} or defn.type not in {
            MetadataType.select,
            MetadataType.multi_select,
        }:
            raise _manager_required()
        await _ensure_initiative_member(session, guild_context, defn.initiative_id)
    await _lock(session, [defn])
    if not reshapes:
        added = _added_options(defn, payload.options or [])
        defn.options = [*(defn.options or []), *added]
        defn.updated_at = datetime.now(timezone.utc)
        session.add(defn)
        await session.commit()
        await session.refresh(defn)
        return PropertyDefinitionUpdateResponse(
            definition=PropertyDefinitionRead.model_validate(defn),
            orphaned_value_count=0,
        )

    if "name" in data and data["name"] is not None:
        await ensure_name_free(
            session,
            MetadataDefinition.name,
            data["name"],
            *_same_scope(defn),
            MetadataDefinition.id != defn.id,
            detail=PropertyMessages.NAME_ALREADY_EXISTS,
        )
        defn.name = data["name"].strip()

    if "position" in data and data["position"] is not None:
        defn.position = data["position"]

    if "color" in data:
        defn.color = data["color"]

    if payload.currency is not None and defn.type is MetadataType.currency:
        defn.currency = payload.currency.value

    orphaned_value_count = 0
    if "options" in data:
        if defn.type not in {MetadataType.select, MetadataType.multi_select}:
            # Silently ignore options for non-select types to stay consistent
            # with the create-side behavior.
            defn.options = None
        else:
            options_payload = payload.options or []
            if not options_payload:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=PropertyMessages.OPTIONS_REQUIRED,
                )
            new_slugs = {opt.value for opt in options_payload}
            orphaned_value_count = await metadata_service.count_orphaned_values(
                session, defn.id, new_slugs
            )
            defn.options = _serialize_options(options_payload)

    defn.updated_at = datetime.now(timezone.utc)
    session.add(defn)
    await session.commit()
    await session.refresh(defn)
    return PropertyDefinitionUpdateResponse(
        definition=PropertyDefinitionRead.model_validate(defn),
        orphaned_value_count=orphaned_value_count,
    )


@router.delete("/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property_definition(
    definition_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertyDefinitionsWrite,
) -> None:
    """Delete a property definition. Cascades to remove all attached values.
    A project's or a collection's metadata is removed by whoever may define
    it."""
    defn = await _get_definition_or_404(session, definition_id)
    await _require_removable(session, [defn], current_user, guild_context)
    await session.delete(defn)
    await session.commit()
