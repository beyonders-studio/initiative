"""CRUD endpoints for custom property definitions: an initiative's properties,
and a collection's own fields.

A collection's field is made, changed and removed by whoever may change the
collection (``resource_access.require_may_change``), and an installed plug-in
does so with the files scope, since a collection is part of Files."""

from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    InstallContext,
    plugin_scope_checked,
)
from app.core.messages import InitiativeMessages, PluginMessages, PropertyMessages
from app.core.plugin_scopes import tool_resource
from app.core.tools import KINDS, Tool
from app.models.tenant.collection import Collection
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import (
    PropertyDefinition,
    PropertyType,
)
from app.schemas.tenant.property import (
    PropertyDefinitionCreate,
    PropertyDefinitionRead,
    PropertyDefinitionUpdate,
    PropertyDefinitionUpdateResponse,
)
from app.services.tenant import properties as properties_service
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
_FIELDS_WRITE = f"{tool_resource(Tool.file).value}:write"
#: An installed plug-in writes an initiative's properties with
#: ``properties:write``, and a collection's own fields with ``files:write``.
PropertyDefinitionsWrite = Annotated[
    ActorContext,
    Depends(
        plugin_scope_checked((_PROPERTIES_WRITE, _FIELDS_WRITE), per="property scope")
    ),
]


def _require_write_scope(
    guild_context: ActorContext, collection_id: Optional[int]
) -> None:
    """A 403 for an installed plug-in without the scope this definition's
    writes take."""
    scope = _PROPERTIES_WRITE if collection_id is None else _FIELDS_WRITE
    if isinstance(guild_context, InstallContext) and not guild_context.holds(scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
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


def _same_scope(defn: PropertyDefinition | PropertyDefinitionCreate) -> list:
    """What a definition's name is unique among: the initiative's properties,
    or the collection's own fields."""
    return [
        PropertyDefinition.initiative_id == defn.initiative_id,
        col(PropertyDefinition.collection_id).is_not_distinct_from(defn.collection_id),
    ]


async def _get_definition_or_404(
    session: AsyncSession,
    definition_id: int,
    *,
    lock: bool = False,
) -> PropertyDefinition:
    """Fetch a definition by id, relying on RLS for scope enforcement.

    MUST be called with a routed session (``ActorSessionDep``). Under
    schema-per-guild, ``property_definitions`` lives only in the active
    guild's schema, and definition ids are unique per-guild — the routing is
    what decides which guild's row an id resolves to.
    """
    stmt = select(PropertyDefinition).where(PropertyDefinition.id == definition_id)
    if lock:
        stmt = stmt.with_for_update()
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


def _added_options(defn: PropertyDefinition, options: list) -> list[dict]:
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
    collection_id: Optional[int] = Query(
        default=None,
        description="List this collection's own fields instead of properties.",
    ),
) -> Sequence[PropertyDefinition]:
    """List property definitions.

    With ``initiative_id``, returns definitions for that initiative only
    (filtered explicitly and subject to RLS). Without it, RLS returns the
    union across every initiative the caller can see — used by global
    views (My Tasks, Created Tasks, global Files list). A collection's own
    fields are listed only with its ``collection_id``, and only to whoever
    sees the collection.
    """
    if isinstance(guild_context, InstallContext) and not any(
        guild_context.holds(scope) for scope in _DEFINITION_READ_SCOPES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )
    stmt = select(PropertyDefinition).where(
        col(PropertyDefinition.collection_id).is_not_distinct_from(collection_id)
    )
    if initiative_id is not None:
        stmt = stmt.where(PropertyDefinition.initiative_id == initiative_id)
    stmt = stmt.order_by(
        PropertyDefinition.position.asc(), PropertyDefinition.name.asc()
    )
    result = await session.exec(stmt)
    return result.all()


@router.post(
    "/", response_model=PropertyDefinitionRead, status_code=status.HTTP_201_CREATED
)
async def create_property_definition(
    payload: PropertyDefinitionCreate,
    session: ActorSessionDep,
    guild_context: PropertyDefinitionsWrite,
) -> PropertyDefinition:
    """Create a new property definition on an initiative, or with
    ``collection_id`` a field of that collection's own.

    A property requires the caller to be in the target initiative (or a guild
    admin); an installed plug-in also needs ``properties:write``. A
    collection's field requires the right to change the collection (and
    ``files:write`` of a plug-in). A rating is a collection's field only.
    """
    _require_write_scope(guild_context, payload.collection_id)
    if payload.collection_id is None:
        await _ensure_initiative_member(session, guild_context, payload.initiative_id)
    else:
        await _changed_collection(session, payload.collection_id, payload.initiative_id)
    await ensure_name_free(
        session,
        PropertyDefinition.name,
        payload.name,
        *_same_scope(payload),
        detail=PropertyMessages.NAME_ALREADY_EXISTS,
    )

    defn = PropertyDefinition(
        initiative_id=payload.initiative_id,
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
    guild_context: PropertyDefinitionsWrite,
) -> PropertyDefinitionUpdateResponse:
    """Update a property definition.

    Type changes are not allowed via this endpoint; callers should
    delete the definition and re-create. Changing the option list on a
    select / multi_select definition returns ``orphaned_value_count`` so
    the SPA can warn about dangling values. A collection's field is changed
    by whoever may change the collection.
    """
    defn = await _get_definition_or_404(session, definition_id, lock=True)
    _require_write_scope(guild_context, defn.collection_id)

    data = payload.model_dump(exclude_unset=True)
    if defn.collection_id is not None:
        await _changed_collection(session, defn.collection_id, defn.initiative_id)
    elif not _manages(guild_context, defn.initiative_id):
        # A member adds options and nothing else: the ones sent that are new
        # join the list as it stands, so two members adding at once both land,
        # and the options already there are left as they are.
        if set(data) != {"options"} or defn.type not in {
            PropertyType.select,
            PropertyType.multi_select,
        }:
            raise _manager_required()
        added = _added_options(defn, payload.options or [])
        await _ensure_initiative_member(session, guild_context, defn.initiative_id)
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
            PropertyDefinition.name,
            data["name"],
            *_same_scope(defn),
            PropertyDefinition.id != defn.id,
            detail=PropertyMessages.NAME_ALREADY_EXISTS,
        )
        defn.name = data["name"].strip()

    if "position" in data and data["position"] is not None:
        defn.position = data["position"]

    if "color" in data:
        defn.color = data["color"]

    if payload.currency is not None and defn.type is PropertyType.currency:
        defn.currency = payload.currency.value

    orphaned_value_count = 0
    if "options" in data:
        if defn.type not in {PropertyType.select, PropertyType.multi_select}:
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
            orphaned_value_count = await properties_service.count_orphaned_values(
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
    guild_context: PropertyDefinitionsWrite,
) -> None:
    """Delete a property definition. Cascades to remove all attached values.
    A collection's field is removed by whoever may change the collection."""
    defn = await _get_definition_or_404(session, definition_id)
    _require_write_scope(guild_context, defn.collection_id)
    if defn.collection_id is not None:
        await _changed_collection(session, defn.collection_id, defn.initiative_id)
    elif not _manages(guild_context, defn.initiative_id):
        raise _manager_required()
    await session.delete(defn)
    await session.commit()
