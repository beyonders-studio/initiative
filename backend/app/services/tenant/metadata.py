"""Metadata — every custom value, whoever owns its definition — the one seam.

A definition (``metadata_definitions``) is owned by its initiative (a
property), a project, a collection or an installed plug-in, and its values
live in one table, ``metadata_values``, addressed by ``(entity_type,
entity_id)``. Every tool and every sub-tool (``PROPERTY_TARGETS``) may carry a
value of any property defined in its initiative; a task carries its project's
metadata too, a file in a collection that collection's, and an item
(``ITEM_KINDS``) or an install itself the values an install keeps. This module
is the only code that turns a target or an owner into behaviour.
:data:`PROPERTY_LINKS` holds one :class:`PropertyLinkSpec` per target, derived
from the registries the policies are rendered from, and every surface — the
write route, the read field, list filters, copying and moving — reads it.

Responsibilities:
* Validate raw input values against a definition's type and return the typed
  columns to store.
* Replace-all and partial writes, the annotation every serializer reads, and
  the copy and drop a duplicate, an occurrence, a move or a purge asks for.
* List filter predicates over the value table.
* What an installed plug-in keeps (the last part of this module): its values
  by key, held to the plug-in kit's contract.

The caller owns session lifecycle (commit) — these functions only issue the
in-transaction statements; RLS context replays automatically on each
transaction.
"""

import json
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
)

from fastapi import HTTPException, status
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from pydantic_core import PydanticCustomError
from sqlalchemy import (
    Integer,
    Table,
    and_,
    any_,
    column,
    exists,
    func,
    insert,
    literal,
    literal_column,
    or_,
    true,
    tuple_,
    values,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import SQLModel, col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import PluginChannelError
from app.core.identity_boundary import current_install_boundary
from app.core.messages import (
    PluginChannelMessages,
    PluginMessages,
    PropertyMessages,
    QueryMessages,
)
from app.core.plugin_scopes import tool_resource
from app.core.tools import (
    INSTALL_METADATA_KIND,
    ITEM_KINDS,
    KINDS,
    PROPERTY_TARGETS,
    Tool,
)
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.base import MODELS_BY_TABLE
from app.db.guild_standing import GuildContext, InstallContext
from app.db.initiative_rls import entity_tables, governing_path
from app.db.request_context import SystemGuild
from app.db.session import (
    RLS_CONTEXT_MAX_AGE_SECONDS,
    guild_context,
    routed_guild_id,
    set_rls_context,
)
from app.models.platform.identity_ref import IdentityEntity
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.metadata import (
    REF_LENGTH,
    VALUE_COLUMNS,
    MetadataDefinition,
    MetadataType,
    MetadataValue,
)
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.schemas.query import FilterOp
from app.services.marketplace import contract
from app.services.marketplace.expressions import UNDEFINED
from app.services.marketplace.manifest_values import is_identifier, is_metadata_key
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.schemas.tenant.property import (
    MAX_PROPERTY_FILTERS,
    PropertyOption,
    PropertyOptionsChange,
    PropertySummary,
    PropertyValueInput,
)
from app.services.tenant import named_people


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


#: Run after a target's values changed, for a target whose own shape reacts:
#: ``(session, row)``.
ValuesChanged = Callable[[AsyncSession, Any], Awaitable[None]]


@dataclass(frozen=True)
class PropertyLinkSpec:
    """How one target carries properties.

    Three facts, all read from registries that already hold them: the row's
    model (from its table), the tool whose sharing governs it, and the column
    on the row naming that tool's row — ``None`` where the row IS the tool row.
    ``shared`` is false for a row no sharing governs (a collection), which
    answers to its tool in its initiative alone.
    """

    target: str
    model: type[SQLModel]
    tool: Tool
    via: Optional[str]
    changed: Optional[ValuesChanged] = None
    shared: bool = True

    def governing_id(self, row: Any) -> int:
        return row.id if self.via is None else getattr(row, self.via)

    def governing(self, row: Any, initiative_id: Optional[int]) -> Any:
        """What decides who may be named on ``row``."""
        if not self.shared:
            return named_people.Governing.of_collection(row)
        return named_people.Governing(self.tool, self.governing_id(row), initiative_id)


async def _occurrences_follow(session: AsyncSession, row: Any) -> None:
    """A series' values carry to the occurrences that follow it."""
    from app.services.tenant import calendar_occurrences

    await calendar_occurrences.followed(session, row, "properties")


#: What a target does when its values change, beyond the write itself.
_CHANGED: dict[str, ValuesChanged] = {"calendar_event": _occurrences_follow}


def _link(target: str, models: dict[str, type[SQLModel]]) -> PropertyLinkSpec:
    table = entity_tables()[target]
    kind = KINDS[target]
    if kind.standalone:
        return PropertyLinkSpec(
            target=target, model=models[table], tool=kind.tool, via=None, shared=False
        )
    governed = governing_path(table)
    if governed is None:  # pragma: no cover - every target has a tool
        raise RuntimeError(f"no single tool governs {table!r}")
    tool, hops = governed
    if len(hops) > 1:  # pragma: no cover - a target is a tool or one hop under it
        raise RuntimeError(f"{table!r} is more than one hop from its tool")
    return PropertyLinkSpec(
        target=target,
        model=models[table],
        tool=tool,
        via=hops[0][0] if hops else None,
        changed=_CHANGED.get(target),
    )


def _links() -> dict[str, PropertyLinkSpec]:
    return {target: _link(target, MODELS_BY_TABLE) for target in PROPERTY_TARGETS}


#: One spec per ``PROPERTY_TARGETS`` entry, keyed by the wire name.
PROPERTY_LINKS: dict[str, PropertyLinkSpec] = _links()

#: The same registry keyed by model, so a caller holding rows need not also say
#: what they are. Derived, never a second list.
PROPERTY_LINKS_BY_MODEL: dict[type[SQLModel], PropertyLinkSpec] = {
    spec.model: spec for spec in PROPERTY_LINKS.values()
}


def link_for(entity: Any) -> PropertyLinkSpec:
    """The spec for a row or its model. Raises for a type that carries none."""
    model = entity if isinstance(entity, type) else type(entity)
    try:
        return PROPERTY_LINKS_BY_MODEL[model]
    except KeyError:  # pragma: no cover - a programming error, not a request
        raise KeyError(f"{model.__name__} carries no properties") from None


def _of(target: str, entity_ids: Iterable[int]) -> Any:
    """The value rows on these ``target`` rows."""
    return (MetadataValue.entity_type == target) & MetadataValue.entity_id.in_(
        list(entity_ids)
    )


def _carried(row: Any, collection_id: Optional[int]) -> Any:
    """The definitions people write on ``row`` together: the initiative's
    properties and, on a task, its project's metadata; or with
    ``collection_id`` that collection's metadata, on a file in it."""
    if collection_id is not None:
        return MetadataDefinition.collection_id == collection_id
    project = col(MetadataDefinition.project_id).is_(None)
    if (project_id := _project_of(row)) is not None:
        project = project | (MetadataDefinition.project_id == project_id)
    return and_(
        col(MetadataDefinition.collection_id).is_(None),
        col(MetadataDefinition.install_id).is_(None),
        project,
    )


def _project_of(row: Any) -> Optional[int]:
    """The project whose metadata ``row`` carries: a task's own."""
    return row.project_id if isinstance(row, Task) else None


def _values_of(definitions: Any) -> Any:
    """The value rows of the definitions ``definitions`` selects."""
    return col(MetadataValue.property_id).in_(
        select(MetadataDefinition.id).where(definitions)
    )


#: The types whose value is ``value_number``.
_NUMBER_TYPES = frozenset(
    {MetadataType.number, MetadataType.currency, MetadataType.scale}
)

#: The range of a scale.
SCALE_RANGE = range(0, 101)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _empty_columns() -> Dict[str, Any]:
    """Return all typed value columns set to None (baseline for an update)."""
    return {col: None for col in VALUE_COLUMNS}


def _bad_value(code: str = PropertyMessages.INVALID_VALUE_FOR_TYPE) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=code)


def _coerce_text(raw: Any) -> str:
    if not isinstance(raw, str):
        raise _bad_value()
    stripped = raw.strip()
    if not stripped:
        raise _bad_value()
    return stripped


def _coerce_number(raw: Any) -> Decimal:
    if isinstance(raw, bool):
        raise _bad_value()
    try:
        if isinstance(raw, Decimal):
            return raw
        if isinstance(raw, (int, float)):
            return Decimal(str(raw))
        if isinstance(raw, str):
            return Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise _bad_value() from exc
    raise _bad_value()


def _coerce_scale(raw: Any) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in SCALE_RANGE:
        raise _bad_value()
    return Decimal(raw)


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    raise _bad_value()


def _coerce_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise _bad_value() from exc
    raise _bad_value()


def _coerce_datetime(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _bad_value() from exc
    raise _bad_value()


def _coerce_url(raw: Any) -> str:
    if not isinstance(raw, str):
        raise _bad_value()
    candidate = raw.strip()
    if not candidate:
        raise _bad_value()
    try:
        _HTTP_URL_ADAPTER.validate_python(candidate)
    except ValidationError as exc:
        raise _bad_value() from exc
    return candidate


def _option_slugs(defn: MetadataDefinition) -> Set[str]:
    options = defn.options or []
    slugs: Set[str] = set()
    for opt in options:
        slug = (
            opt.get("value") if isinstance(opt, dict) else getattr(opt, "value", None)
        )
        if slug:
            slugs.add(slug)
    return slugs


def _parsed_options(defn: MetadataDefinition) -> List[PropertyOption]:
    if not defn.options:
        return []
    parsed: List[PropertyOption] = []
    for raw in defn.options:
        if isinstance(raw, PropertyOption):
            parsed.append(raw)
            continue
        if isinstance(raw, dict):
            try:
                parsed.append(PropertyOption(**raw))
            except ValidationError:
                # Options in the DB that fail schema validation are ignored
                # at serialize time — they can't be produced through the API.
                continue
    return parsed


def _is_empty_value(raw_value: Any) -> bool:
    """Return True when ``raw_value`` represents "attached but no value".

    Attached-but-empty property rows are allowed so a user can add a
    property definition to anything without being forced to
    enter a value — the row persists (all typed columns null) and the "is
    empty" filter can match it.
    """
    if raw_value is None:
        return True
    if isinstance(raw_value, str) and not raw_value.strip():
        return True
    if isinstance(raw_value, (list, tuple)) and len(raw_value) == 0:
        return True
    return False


def _validate_value_for_type(
    defn: MetadataDefinition, raw_value: Any
) -> Dict[str, Any]:
    """Return the typed-column dict for ``raw_value`` under ``defn``.

    When ``raw_value`` is "empty" (None, blank string, empty list) the
    returned dict has every typed column set to None — the row still
    persists as an attached-but-empty record.

    Raises ``HTTPException`` 400 on type mismatches or select/option
    issues. Who a ``user_reference`` may name is asked of the whole set by
    :func:`write_values`.
    """
    cols = _empty_columns()

    if _is_empty_value(raw_value):
        return cols

    ptype = defn.type

    if ptype is MetadataType.text:
        cols["value_text"] = _coerce_text(raw_value)
    elif ptype is MetadataType.number:
        cols["value_number"] = _coerce_number(raw_value)
    elif ptype is MetadataType.currency:
        amount = _coerce_number(raw_value)
        if not amount.is_finite():
            raise _bad_value()
        cols["value_number"] = amount
    elif ptype is MetadataType.scale:
        cols["value_number"] = _coerce_scale(raw_value)
    elif ptype is MetadataType.checkbox:
        cols["value_boolean"] = _coerce_bool(raw_value)
    elif ptype is MetadataType.date:
        cols["value_date"] = _coerce_date(raw_value)
    elif ptype is MetadataType.datetime:
        cols["value_datetime"] = _coerce_datetime(raw_value)
    elif ptype is MetadataType.url:
        cols["value_text"] = _coerce_url(raw_value)
    elif ptype is MetadataType.select:
        slug = _coerce_text(raw_value)
        if slug not in _option_slugs(defn):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PropertyMessages.OPTION_NOT_IN_DEFINITION,
            )
        cols["value_text"] = slug
    elif ptype is MetadataType.multi_select:
        if not isinstance(raw_value, (list, tuple)):
            raise _bad_value()
        valid = _option_slugs(defn)
        slugs: List[str] = []
        seen: Set[str] = set()
        for entry in raw_value:
            slug = _coerce_text(entry)
            if slug not in valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=PropertyMessages.OPTION_NOT_IN_DEFINITION,
                )
            if slug not in seen:
                seen.add(slug)
                slugs.append(slug)
        cols["value_json"] = slugs
    elif ptype is MetadataType.user_reference:
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise _bad_value()
        cols["value_user_id"] = raw_value
    else:  # pragma: no cover - defensive; MetadataType is closed
        raise _bad_value()

    return cols


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def write_values(
    session: AsyncSession,
    row: Any,
    values: Sequence[PropertyValueInput],
    *,
    initiative_id: Optional[int],
    removed: Optional[Sequence[int]] = None,
    options: Sequence[PropertyOptionsChange] = (),
    collection_id: Optional[int] = None,
) -> None:
    """Replace every property value on ``row`` with ``values``. Given
    ``removed``, write only the properties ``values`` names and take off the
    ones ``removed`` names, leaving every other value as it is, so two writes
    of different properties both stand. ``options`` (with ``removed``)
    changes options of multi-select values against what each holds when it
    is written, so two changes of the same value both stand too.

    Each value's definition must belong to ``initiative_id`` — the row's own
    initiative — and a person a value names must be able to open the tool row
    that governs ``row``. The values are the initiative's properties and, on a
    task, its project's metadata; or with ``collection_id`` that collection's
    metadata on ``row``, a file in it. Neither write touches the other's, nor a
    plug-in's values. The caller has authorized the write and owns the commit.
    """
    spec = link_for(row)
    held = _of(spec.target, [row.id]) & _values_of(_carried(row, collection_id))
    named_ids = [
        *(removed or ()),
        *(entry.property_id for entry in values),
        *(change.property_id for change in options),
    ]
    stored = await _in_turn(session, spec.target, row.id, named_ids, options)
    if removed is None:
        await session.exec(delete(MetadataValue).where(held))
    elif named_ids:
        await session.exec(
            delete(MetadataValue).where(
                held,
                MetadataValue.property_id.in_(named_ids),
            )
        )
    if not values and not options:
        return

    requested_ids = [v.property_id for v in values]
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PropertyMessages.INVALID_VALUE_FOR_TYPE,
        )

    definitions = await load_definitions_by_ids(
        session, [*requested_ids, *(change.property_id for change in options)]
    )

    def definition(property_id: int) -> MetadataDefinition:
        defn = definitions.get(property_id)
        if (
            defn is None
            or initiative_id is None
            or defn.initiative_id != initiative_id
            or defn.collection_id != collection_id
            or defn.project_id not in (None, _project_of(row))
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=PropertyMessages.DEFINITION_NOT_FOUND,
            )
        return defn

    named: set[int] = set()
    rows = [
        MetadataValue(
            entity_type=spec.target,
            entity_id=row.id,
            property_id=change.property_id,
            **_options_changed(
                definition(change.property_id),
                stored.get(change.property_id, []),
                change,
            ),
        )
        for change in options
    ]
    for entry in values:
        defn = definition(entry.property_id)
        cols = _validate_value_for_type(defn, entry.value)
        if cols["value_user_id"] is not None:
            named.add(cols["value_user_id"])
        rows.append(
            MetadataValue(
                entity_type=spec.target,
                entity_id=row.id,
                property_id=defn.id,
                **cols,
            )
        )
    governing = spec.governing(row, initiative_id)
    await named_people.require_readers(session, governing, named)
    session.add_all(rows)


async def _in_turn(
    session: AsyncSession,
    target: str,
    entity_id: int,
    named: Sequence[int],
    options: Sequence[PropertyOptionsChange],
) -> dict[int, list[str]]:
    """Take this write's turn at every value it names, then read the options
    each value ``options`` changes holds: a write of the same value made
    meanwhile is the one a change is applied to, and none lands between the
    read and this write's own."""
    for property_id in sorted(set(named)):
        await advisory_lock(
            session,
            LockNamespace.PROPERTY_VALUE,
            f"{routed_guild_id(session)}:{target}:{entity_id}:{property_id}",
        )
    if not options:
        return {}
    held = await session.exec(
        select(MetadataValue.property_id, MetadataValue.value_json).where(
            _of(target, [entity_id]),
            MetadataValue.property_id.in_([c.property_id for c in options]),
        )
    )
    return {property_id: list(slugs or []) for property_id, slugs in held.all()}


def _options_changed(
    defn: MetadataDefinition, stored: list[str], change: PropertyOptionsChange
) -> Dict[str, Any]:
    """The typed columns of a multi-select value once ``change`` is applied to
    the options it holds. What it holds stays, in its order, an option the
    definition has since dropped included; only what ``change`` adds is held
    to the definition."""
    if defn.type is not MetadataType.multi_select:
        raise _bad_value()
    valid = _option_slugs(defn)
    if any(slug not in valid for slug in change.add):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PropertyMessages.OPTION_NOT_IN_DEFINITION,
        )
    kept = [slug for slug in stored if slug not in change.remove]
    slugs = kept + [slug for slug in dict.fromkeys(change.add) if slug not in kept]
    cols = _empty_columns()
    if slugs:
        cols["value_json"] = slugs
    return cols


async def set_values(
    session: AsyncSession,
    row: Any,
    values: Sequence[PropertyValueInput],
    *,
    initiative_id: Optional[int],
    removed: Optional[Sequence[int]] = None,
    options: Sequence[PropertyOptionsChange] = (),
    collection_id: Optional[int] = None,
) -> None:
    """The whole write a person or a plug-in makes: resolve a plug-in's person
    references, write the values (all of them, or with ``removed`` only those
    named, as :func:`write_values`; a collection's metadata with
    ``collection_id``), mark the row changed, and let a target whose own shape
    reacts (a repeating event) do so. Authorization is the caller's."""
    await write_values(
        session,
        row,
        await property_values_by_row_id(session, values),
        initiative_id=initiative_id,
        removed=removed,
        options=options,
        collection_id=collection_id,
    )
    # A collection's metadata is the collection's, so it leaves the file as
    # it was.
    if collection_id is None and hasattr(row, "updated_at"):
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
    await session.flush()
    spec = link_for(row)
    if spec.changed is not None:
        await spec.changed(session, row)


async def write_on_create(
    session: AsyncSession,
    row: Any,
    values: Sequence[PropertyValueInput],
) -> None:
    """The values a create sent with its row, written in the same transaction,
    so the row and its values land together or not at all.

    Held to the row's own initiative, read the way the policies read it
    (``entity_initiative``), so a row that belongs to none carries none.
    """
    if values:
        await _write_in_place(session, row, values)


async def write_on_update(
    session: AsyncSession,
    row: Any,
    values: Optional[Sequence[PropertyValueInput]],
) -> None:
    """The values an update sent with its row, replacing the ones it holds in
    the same transaction. ``None`` leaves them as they are."""
    if values is not None:
        await _write_in_place(session, row, values)


async def _write_in_place(
    session: AsyncSession, row: Any, values: Sequence[PropertyValueInput]
) -> None:
    """``values`` onto ``row`` in the caller's transaction, held to the row's
    own initiative as the policies read it."""
    await session.flush()
    initiative_id = (
        await session.exec(select(func.entity_initiative(link_for(row).target, row.id)))
    ).one()
    await write_values(
        session,
        row,
        await property_values_by_row_id(session, values),
        initiative_id=initiative_id,
    )


async def copy_values(
    session: AsyncSession, model: type[SQLModel], copies: Mapping[int, int]
) -> None:
    """Give each copy the values its source holds (``{source_id: copy_id}``,
    rows of ``model``), replacing its own. Two statements however many rows,
    and two more for tasks.

    For a duplicate or an occurrence: the same properties apply, so each pair
    must share an initiative — a caller copying across initiatives copies
    nothing instead. A task's project metadata goes onto the metadata of the
    copy's project with the same name and type (its own, for a copy beside
    it), and the rest is not copied. A collection's metadata stays with the
    files in it, since a copy is in no collection; a plug-in's stays with the
    source, since only the plug-in writes it.
    """
    if not copies:
        return
    target = link_for(model).target
    # The copies' pending changes first (a series' override takes its calendar
    # just before), so their values are held to where they now sit.
    await session.flush()
    pairs = values(
        column("source_id", Integer), column("copy_id", Integer), name="pairs"
    ).data(list(copies.items()))
    now = datetime.now(timezone.utc)
    names = ["entity_type", "entity_id", "property_id", *VALUE_COLUMNS]
    held = [getattr(MetadataValue, c) for c in VALUE_COLUMNS]
    await session.exec(
        delete(MetadataValue).where(
            _of(target, copies.values()), _values_of(_properties())
        )
    )
    await session.exec(
        insert(MetadataValue).from_select(
            [*names, "created_at", "updated_at"],
            select(
                literal(target),
                pairs.c.copy_id,
                MetadataValue.property_id,
                *held,
                literal(now),
                literal(now),
            )
            .join(pairs, MetadataValue.entity_id == pairs.c.source_id)
            .where(_of(target, copies.keys()), _values_of(_properties())),
        )
    )
    if model is not Task:
        return
    projects = col(MetadataDefinition.project_id).is_not(None)
    await session.exec(
        delete(MetadataValue).where(_of(target, copies.values()), _values_of(projects))
    )
    source, there = aliased(MetadataDefinition), aliased(MetadataDefinition)
    await session.exec(
        insert(MetadataValue).from_select(
            [*names, "created_at", "updated_at"],
            select(
                literal(target),
                pairs.c.copy_id,
                there.id,
                *held,
                literal(now),
                literal(now),
            )
            .join(pairs, MetadataValue.entity_id == pairs.c.source_id)
            .join(source, source.id == MetadataValue.property_id)
            .join(Task, Task.id == pairs.c.copy_id)
            .join(
                there,
                and_(
                    there.project_id == Task.project_id,
                    func.lower(there.name) == func.lower(source.name),
                    there.type == source.type,
                ),
            )
            .where(_of(target, copies.keys()), col(source.project_id).is_not(None)),
        )
    )


async def copy_definitions(
    session: AsyncSession,
    definitions: Sequence[MetadataDefinition],
    *,
    initiative_id: int,
    project_id: Optional[int] = None,
    collection_id: Optional[int] = None,
) -> dict[int, int]:
    """Give a project or a collection made in this transaction copies of
    ``definitions``, none of their values. Answers the copy of each, by the
    id of the one it copies, for the layouts that place them."""
    made = [
        MetadataDefinition(
            initiative_id=initiative_id,
            project_id=project_id,
            collection_id=collection_id,
            name=defn.name,
            type=defn.type,
            position=defn.position,
            color=defn.color,
            options=defn.options,
            currency=defn.currency,
        )
        for defn in definitions
    ]
    session.add_all(made)
    await session.flush()
    return {
        int(defn.id or 0): int(copy.id or 0) for defn, copy in zip(definitions, made)
    }


def _properties() -> Any:
    """The initiative's properties, which no project, collection or plug-in
    owns."""
    return and_(
        col(MetadataDefinition.project_id).is_(None),
        col(MetadataDefinition.collection_id).is_(None),
        col(MetadataDefinition.install_id).is_(None),
    )


async def lift_project_values(
    session: AsyncSession, task: Task, project_id: int
) -> list[MetadataValue]:
    """Take ``task``'s project metadata off before it moves to ``project_id``,
    answering what to put back once it has moved: each value on the metadata
    there with its definition's name and type. The rest is dropped.

    Taken off first and put back after, because a project's metadata is
    written only on a task in that project."""
    held = (
        await session.exec(
            select(MetadataValue, MetadataDefinition)
            .join(
                MetadataDefinition,
                MetadataDefinition.id == MetadataValue.property_id,
            )
            .where(
                _of("task", [task.id]), col(MetadataDefinition.project_id).is_not(None)
            )
        )
    ).all()
    if not held:
        return []
    there = {
        (defn.name.lower(), defn.type): defn.id
        for defn in await session.exec(
            select(MetadataDefinition).where(
                MetadataDefinition.project_id == project_id
            )
        )
    }
    await session.exec(
        delete(MetadataValue).where(
            _of("task", [task.id]),
            _values_of(col(MetadataDefinition.project_id).is_not(None)),
        )
    )
    return [
        MetadataValue(
            entity_type="task",
            entity_id=task.id,
            property_id=there[key],
            **{c: getattr(value, c) for c in VALUE_COLUMNS},
        )
        for value, defn in held
        if (key := (defn.name.lower(), defn.type)) in there
    ]


async def drop_values(
    session: AsyncSession,
    target: str,
    entity_ids: Iterable[int],
    *,
    moved: bool = False,
) -> None:
    """Remove every value on these rows, as they are purged; or once they
    have ``moved`` to another initiative, whose definitions are not theirs,
    every value but a plug-in's, whose definitions are no initiative's."""
    ids = list(entity_ids)
    if ids:
        await session.exec(
            delete(MetadataValue).where(
                _of(target, ids),
                _values_of(col(MetadataDefinition.install_id).is_(None))
                if moved
                else true(),
            )
        )


async def drop_collection_values(
    session: AsyncSession, collection_id: int, file_ids: Iterable[int]
) -> None:
    """Remove the values of a collection's metadata on these files, which are
    leaving it."""
    ids = list(file_ids)
    if ids:
        await session.exec(
            delete(MetadataValue).where(
                _of(Tool.file.value, ids),
                _values_of(MetadataDefinition.collection_id == collection_id),
            )
        )


async def property_values_by_row_id(
    session: AsyncSession, values: Sequence[PropertyValueInput]
) -> list[PropertyValueInput]:
    """``values`` with each person a ``user_reference`` value names as a row
    id.

    Unchanged for a person. An installed plug-in names a person by the reference
    it was given for them, which is resolved here the way a ``PersonId`` field
    is; anything else in that place is a 422 (``PLUGIN_REFERENCE_UNKNOWN``). Only
    a person-valued property's value is read this way, since which values
    name a person depends on each value's definition.
    """
    boundary = current_install_boundary()
    if boundary is None or not values:
        return list(values)
    definitions = await load_definitions_by_ids(
        session, [entry.property_id for entry in values]
    )
    resolved: list[PropertyValueInput] = []
    for entry in values:
        defn = definitions.get(entry.property_id)
        if (
            defn is not None
            and defn.type is MetadataType.user_reference
            and entry.value is not None
        ):
            try:
                row_id = boundary.resolve(entry.value, IdentityEntity.user)
            except PydanticCustomError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=PluginMessages.REFERENCE_UNKNOWN,
                )
            entry = entry.model_copy(update={"value": row_id})
        resolved.append(entry)
    return resolved


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _number_to_json(v: Optional[Decimal]) -> Optional[float]:
    if v is None:
        return None
    # Represent as float for JSON serialization; callers needing exact
    # arithmetic should hit the raw value directly.
    return float(v)


def _rehydrate_value(
    defn: MetadataDefinition, row: Any, user: Optional[MemberProfile]
) -> Any:
    ptype = defn.type
    if ptype in {MetadataType.text, MetadataType.url, MetadataType.select}:
        return row.value_text
    if ptype in {MetadataType.number, MetadataType.currency}:
        return _number_to_json(row.value_number)
    if ptype is MetadataType.scale:
        return int(row.value_number) if row.value_number is not None else None
    if ptype is MetadataType.checkbox:
        return row.value_boolean
    if ptype is MetadataType.date:
        return row.value_date
    if ptype is MetadataType.datetime:
        return row.value_datetime
    if ptype is MetadataType.multi_select:
        return list(row.value_json) if row.value_json is not None else []
    if ptype is MetadataType.user_reference:
        if user is None:
            return {"id": row.value_user_id} if row.value_user_id else None
        # The same person shape the rest of the API ships. ``value_user`` is
        # the guild projection, so its name is the one set in this guild.
        return {
            "id": user.id,
            "username": user.username,
            "discriminator": user.discriminator,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
        }
    return None  # pragma: no cover


def summaries_from_rows(rows: Iterable[MetadataValue]) -> List[PropertySummary]:
    """:class:`PropertySummary` list from value rows with ``definition``
    (and ``value_user`` where it applies) loaded, sorted by name."""
    summaries: List[PropertySummary] = []
    for row in rows:
        defn = row.definition
        if defn is None:
            continue
        summaries.append(
            PropertySummary(
                property_id=defn.id,
                name=defn.name,
                type=defn.type,
                project_id=defn.project_id,
                collection_id=defn.collection_id,
                options=_parsed_options(defn) or None,
                currency=defn.currency,
                value=_rehydrate_value(defn, row, row.value_user),
            )
        )
    summaries.sort(key=lambda s: s.name.lower())
    return summaries


async def summaries_by_id(
    session: AsyncSession,
    target: str,
    entity_ids: Iterable[int],
    *,
    collection_id: Optional[int] = None,
) -> dict[int, List[PropertySummary]]:
    """Every value the reader reads on these ``target`` rows, as summaries, by
    row id: the initiative's properties, a task's project metadata, a file's
    metadata of each collection it is in, and the values plug-ins show on an
    item (:func:`_plugin_summaries`). With ``collection_id``, only that
    collection's metadata."""
    ids = list(dict.fromkeys(entity_ids))
    if not ids:
        return {}
    owned = (
        MetadataDefinition.collection_id == collection_id
        if collection_id is not None
        else col(MetadataDefinition.install_id).is_(None)
    )
    rows = (
        await session.exec(
            select(MetadataValue)
            .where(_of(target, ids), _values_of(owned))
            .options(
                selectinload(MetadataValue.definition),
                selectinload(MetadataValue.value_user),
            )
        )
    ).all()
    grouped: dict[int, list[MetadataValue]] = defaultdict(list)
    for row in rows:
        grouped[row.entity_id].append(row)
    found = {
        entity_id: summaries_from_rows(values) for entity_id, values in grouped.items()
    }
    if collection_id is None:
        for entity_id, shown in (await _plugin_summaries(session, target, ids)).items():
            found[entity_id] = sorted(
                [*found.get(entity_id, []), *shown], key=lambda s: s.name.lower()
            )
    return found


async def annotate_properties(session: AsyncSession, entities: Iterable[Any]) -> None:
    """Set ``.properties`` on every row — the single serialization path.

    The target comes from the rows themselves, so a caller never states twice
    what it is already holding. One query for the whole page.
    """
    rows = [entity for entity in entities if entity is not None]
    if not rows:
        return
    by_id = await summaries_by_id(
        session, link_for(rows[0]).target, [r.id for r in rows]
    )
    for row in rows:
        object.__setattr__(row, "properties", by_id.get(row.id, []))


async def count_orphaned_values(
    session: AsyncSession,
    defn_id: int,
    valid_slugs: Set[str],
) -> int:
    """Count attached values whose option slug is no longer valid.

    Used on PATCH of a select/multi_select definition when the option list
    changes — the SPA surfaces the count as a warning. Orphaned values are
    preserved (not cleared) by design.

    Two ``COUNT`` queries (one for value_text, one for value_json) rather than
    pulling rows into Python. For multi_select the JSONB ``<@`` operator asks
    Postgres whether every stored slug is contained in the valid-slug set —
    rows that fail that check (i.e. contain at least one slug outside the new
    option list) count as orphans.
    """
    valid_list = list(valid_slugs)
    # value_text (single select): NOT IN the new slug list counts.
    stmt_text = select(func.count()).where(
        MetadataValue.property_id == defn_id,
        MetadataValue.value_text.is_not(None),
        MetadataValue.value_text.not_in(valid_list) if valid_list else true(),
    )
    # value_json (multi_select): not fully contained in the valid set means
    # at least one element is orphaned.
    stmt_json = select(func.count()).where(
        MetadataValue.property_id == defn_id,
        MetadataValue.value_json.is_not(None),
        ~MetadataValue.value_json.op("<@")(valid_list),
    )
    return (await session.exec(stmt_text)).one() + (await session.exec(stmt_json)).one()


# ---------------------------------------------------------------------------
# List filters
# ---------------------------------------------------------------------------


def typed_column_for_property(property_type: MetadataType) -> Any:
    """The value column a property of this type is stored in."""
    if property_type in {
        MetadataType.text,
        MetadataType.url,
        MetadataType.select,
        MetadataType.link,
        MetadataType.badge,
    }:
        return MetadataValue.value_text
    if property_type in _NUMBER_TYPES:
        return MetadataValue.value_number
    if property_type is MetadataType.checkbox:
        return MetadataValue.value_boolean
    if property_type is MetadataType.date:
        return MetadataValue.value_date
    if property_type is MetadataType.datetime:
        return MetadataValue.value_datetime
    if property_type is MetadataType.user_reference:
        return MetadataValue.value_user_id
    if property_type is MetadataType.multi_select:
        return MetadataValue.value_json
    raise ValueError(f"Unsupported property type: {property_type!r}")


def _coerce_filter_scalar(property_type: MetadataType, raw: Any) -> Any:
    """Coerce a raw filter value to the Python type matching the column.

    Filter values arrive as JSON scalars (string / number / bool). Postgres
    refuses to compare a DATE column to a VARCHAR literal, so we convert
    before building the predicate. Returns the coerced value on success;
    returns ``None`` when coercion is impossible (the caller skips the
    filter rather than 500-ing on a bad value).
    """
    if raw is None:
        return None
    try:
        if property_type in _NUMBER_TYPES:
            if isinstance(raw, bool):
                return None
            if isinstance(raw, Decimal):
                return raw
            if isinstance(raw, (int, float)):
                return Decimal(str(raw))
            if isinstance(raw, str):
                return Decimal(raw.strip())
            return None
        if property_type is MetadataType.checkbox:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
            return None
        if property_type is MetadataType.date:
            if isinstance(raw, datetime):
                return raw.date()
            if isinstance(raw, date):
                return raw
            if isinstance(raw, str):
                return date.fromisoformat(raw.strip())
            return None
        if property_type is MetadataType.datetime:
            if isinstance(raw, datetime):
                return raw
            if isinstance(raw, str):
                return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            return None
        if property_type is MetadataType.user_reference:
            if isinstance(raw, bool):
                return None
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str):
                return int(raw.strip())
            return None
        # text, url, select — use raw string comparison.
        if isinstance(raw, str):
            return raw
        return str(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _coerce_filter_value(property_type: MetadataType, op: Any, raw: Any) -> Any:
    """Coerce either a scalar or a list (for ``in_``) for a typed column."""
    from app.schemas.query import FilterOp  # noqa: WPS433 - local to avoid cycles

    if op == FilterOp.in_:
        if not isinstance(raw, (list, tuple)):
            return None
        coerced = [_coerce_filter_scalar(property_type, entry) for entry in raw]
        coerced = [c for c in coerced if c is not None]
        return coerced or None
    if op == FilterOp.ilike:
        # ilike only applies to text-like columns; keep the string as-is.
        return raw if isinstance(raw, str) else None
    return _coerce_filter_scalar(property_type, raw)


def build_property_value_predicate(
    column: Any,
    property_type: MetadataType,
    op: Any,
    value: Any,
) -> Any:
    """Build a single WHERE clause on a property-value typed column.

    ``op`` is a :class:`app.schemas.query.FilterOp`. For ``multi_select``
    the predicate uses the JSONB containment operator so that a value of
    ``["alpha"]`` matches rows whose ``value_json`` array contains that
    slug. All other types use the generic column comparisons after
    coercing ``value`` to the Python type that matches the typed column
    (see :func:`_coerce_filter_value`).

    Callers must handle :attr:`FilterOp.is_null` separately via
    :func:`property_value_presence_predicate` — "empty" needs to match
    entities that lack a row entirely, not just rows with a null value.
    """
    # Import locally to avoid circular dependency: query.py depends on
    # nothing app-specific but this service module is imported from
    # endpoints that also depend on query.py.
    from app.schemas.query import FilterOp  # noqa: WPS433 - intentional local import

    if op == FilterOp.is_null:
        # Presence vs. absence needs the parent-entity id column to
        # compose a NOT IN / IN subquery — delegate to
        # ``property_value_presence_predicate``.
        return None

    if property_type is MetadataType.multi_select:
        # Only ``contains-any`` semantics are meaningful for multi_select.
        # Coerce the incoming value into a JSONB array literal. Accept
        # either a single slug or a list of slugs.
        if isinstance(value, (list, tuple)):
            payload = [entry for entry in value if isinstance(entry, str)]
        elif isinstance(value, str):
            payload = [value]
        else:
            payload = []
        if not payload:
            return None
        return column.op("@>")(payload)

    coerced = _coerce_filter_value(property_type, op, value)
    if coerced is None:
        return None

    if op == FilterOp.eq:
        return column == coerced
    if op == FilterOp.lt:
        return column < coerced
    if op == FilterOp.lte:
        return column <= coerced
    if op == FilterOp.gt:
        return column > coerced
    if op == FilterOp.gte:
        return column >= coerced
    if op == FilterOp.in_:
        return column.in_(tuple(coerced))
    if op == FilterOp.ilike:
        return column.ilike(f"%{coerced}%")
    return None


def _value_on(target: str, parent_id: Any, property_id: int, predicate: Any) -> Any:
    """Whether the row ``parent_id`` names holds a value for ``property_id``
    that ``predicate`` accepts.

    Correlated to the row rather than ``parent.id IN (…)``: the planner can
    start from the rows the list has already narrowed to, and the negation is
    an anti-join, where ``NOT IN`` would read every value of the property.
    """
    return (
        exists()
        .where(
            MetadataValue.entity_type == target,
            MetadataValue.entity_id == parent_id,
            MetadataValue.property_id == property_id,
            predicate,
        )
        # Named, so a query that does not select the row's table fails
        # rather than reading every value as one row's.
        .correlate(parent_id.expression.table)
    )


def property_value_presence_predicate(
    target: str,
    parent_id_column: Any,
    property_id: int,
    property_type: MetadataType,
    is_empty: bool,
) -> Any:
    """Match rows by whether they hold a value for the property.

    - ``is_empty=True`` → match rows that either have no value row OR have one
      whose typed column is NULL (multi_select: empty / null JSON array).
    - ``is_empty=False`` → match rows that have a non-empty value.

    ``parent_id_column`` is the target's own id column (``Task.id``, …).
    """
    typed = typed_column_for_property(property_type)
    non_empty = typed.is_not(None)
    if property_type is MetadataType.multi_select:
        # Treat a stored empty array as "empty" too, so the filter
        # behaves the same way as the UI does for multi-selects.
        non_empty = typed.is_not(None) & (func.jsonb_array_length(typed) > 0)

    held = _value_on(target, parent_id_column, property_id, non_empty)
    return ~held if is_empty else held


def build_single_property_clause(
    target: str,
    property_id: int,
    op: Any,
    value: Any,
    defn: MetadataDefinition,
) -> Any:
    """Compile one property filter condition on ``target`` rows into a single
    WHERE clause: ``EXISTS (SELECT 1 FROM property_values …)`` on the row.

    Returns ``None`` when the condition is unsupported (unknown type,
    malformed value) — callers skip it.
    """
    from app.schemas.query import FilterOp  # noqa: WPS433 - local to avoid cycles

    parent_id = PROPERTY_LINKS[target].model.id

    if op == FilterOp.is_null:
        # Callers using the parsed-filter API have already normalized
        # ``value`` to a bool. The tasks inline handler hands us the raw
        # value, so normalize defensively here too.
        try:
            is_empty = (
                normalize_is_null_value(value) if not isinstance(value, bool) else value
            )
        except ValueError:
            return None
        return property_value_presence_predicate(
            target, parent_id, property_id, defn.type, is_empty=is_empty
        )

    try:
        column = typed_column_for_property(defn.type)
    except ValueError:
        return None
    predicate = build_property_value_predicate(column, defn.type, op, value)
    if predicate is None:
        return None
    return _value_on(target, parent_id, property_id, predicate)


def build_property_filter_clauses(
    target: str,
    conditions: Sequence["ParsedPropertyFilter"],
    defs_map: Dict[int, MetadataDefinition],
) -> List[Any]:
    """The WHERE-clause list for a set of parsed property filters on
    ``target`` rows. Unknown / inaccessible property ids are skipped: RLS on
    ``property_definitions`` decided visibility when ``defs_map`` was loaded.
    """
    clauses: List[Any] = []
    for cond in conditions:
        defn = defs_map.get(cond.property_id)
        if defn is None:
            continue
        clause = build_single_property_clause(
            target, cond.property_id, cond.op, cond.value, defn
        )
        if clause is not None:
            clauses.append(clause)
    return clauses


class ParsedPropertyFilter:
    """A single decoded property filter condition.

    Kept as a plain dataclass-like object to avoid pulling Pydantic into
    the hot path — these are ephemeral parser outputs.
    """

    __slots__ = ("property_id", "op", "value")

    def __init__(self, property_id: int, op: Any, value: Any) -> None:
        self.property_id = property_id
        self.op = op
        self.value = value


def normalize_is_null_value(raw: Any) -> bool:
    """Coerce an ``is_null`` filter's ``value`` into an explicit bool.

    ``is_null`` semantics: ``True`` means "is empty" (no row / null
    value), ``False`` means "is not empty". A missing ``value`` key
    defaults to ``True`` — reading the op name literally, the natural
    meaning of ``is_null`` without a value is "is null". Explicit
    booleans pass through. Explicit non-booleans (strings, numbers,
    arrays) raise :class:`ValueError` so callers don't silently fall
    back to ``bool()`` coercion that would treat ``"false"`` as truthy.
    """
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    raise ValueError(
        "is_null filter value must be a boolean (True = is empty, False = is not empty)"
    )


def parse_property_filters(raw: Optional[str]) -> List[ParsedPropertyFilter]:
    """Parse the ``property_filters`` query param into validated conditions.

    Raises :class:`ValueError` on malformed input (caller converts to 400).
    Returns an empty list when ``raw`` is falsy. Caps the number of
    predicates at :data:`MAX_PROPERTY_FILTERS`. For ``is_null`` entries
    the ``value`` is normalized via :func:`normalize_is_null_value` so
    the downstream predicate always sees an explicit bool.
    """
    import json

    from app.schemas.query import FilterOp  # noqa: WPS433 - local to avoid cycles

    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("property_filters is not valid JSON") from exc

    if not isinstance(payload, list):
        raise ValueError("property_filters must be a JSON array")

    if len(payload) > MAX_PROPERTY_FILTERS:
        raise ValueError(f"too many property filters (max {MAX_PROPERTY_FILTERS})")

    parsed: List[ParsedPropertyFilter] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("each property filter must be an object")
        pid_raw = entry.get("property_id")
        op_raw = entry.get("op", "eq")
        value = entry.get("value")
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("property_id must be an integer") from exc
        try:
            op = FilterOp(op_raw)
        except ValueError as exc:
            raise ValueError(f"unknown filter op: {op_raw!r}") from exc
        if op == FilterOp.is_null:
            value = normalize_is_null_value(value)
        parsed.append(ParsedPropertyFilter(property_id=pid, op=op, value=value))
    return parsed


async def load_definitions_by_ids(
    session: AsyncSession,
    definition_ids: Iterable[int],
) -> Dict[int, MetadataDefinition]:
    """Load property definitions by id.

    Used by list filters so the endpoint can resolve the correct typed
    column per condition without issuing one query per condition. RLS
    constrains visibility to the caller's accessible initiatives.
    """
    ids = list({did for did in definition_ids if did is not None})
    if not ids:
        return {}
    stmt = select(MetadataDefinition).where(MetadataDefinition.id.in_(ids))
    result = await session.exec(stmt)
    return {defn.id: defn for defn in result.all() if defn.id is not None}


async def property_filter_clauses(
    session: AsyncSession, target: str, raw: Optional[str], *, names_people: bool
) -> list:
    """WHERE clauses for the ``property_filters`` a list of ``target`` carries.

    The one reading of the param, for every list and every view of one (a
    tool's list, the event list, the posts timeline). A filter on a
    person-valued property takes row ids, which an installed plug-in does not
    hold, so it is left to people (``names_people``), as the task list does.
    """
    from app.schemas.query import FilterOp  # noqa: WPS433 - local to avoid cycles

    try:
        parsed = parse_property_filters(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    if not parsed:
        return []
    definitions = await load_definitions_by_ids(
        session, [condition.property_id for condition in parsed]
    )
    if not names_people and any(
        condition.op is not FilterOp.is_null
        and (definition := definitions.get(condition.property_id)) is not None
        and definition.type is MetadataType.user_reference
        for condition in parsed
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    return build_property_filter_clauses(target, parsed, definitions)


# ---------------------------------------------------------------------------
# What an installed plug-in keeps
# ---------------------------------------------------------------------------
#
# An install keeps values by key, on the items it can read and on itself. Each
# key is one of the install's definitions (``install_id`` and ``key``), made the
# first time the install writes it and typed from the field its pinned version
# declares for it, ``json`` where none does. Every function here that takes an
# :class:`InstallContext` runs on the request's session, routed as the install
# by the install seam, so the table's policies decide which rows it reaches:
# its own, on an item it can read, with the read scope of the item's tool. The
# checks here answer the same questions first, so a refusal names its reason
# instead of surfacing as a policy violation.
#
# A container plug-in writes its values through the installation API. A
# declarative plug-in's are the changes its expressions answer, which
# :func:`apply_changes` makes on a session of its own, routed as the install
# through the same seam.
#
# A value on an item is shown where the install's pinned version declares its
# key as a field on the item's kind (``shown_on``): whoever can read the item
# reads it then, and it comes back with the item (:func:`summaries_by_id`).
# :func:`sync_definitions` brings the definitions up to date when the install
# moves to another version.
#
# A list field's key holds a list of elements, a row each, which a change adds
# to, merges into and takes from by their refs (:func:`write`). Every read
# answers the list as an array, newest first (:func:`assembled`).
#
# The caps are the plug-in kit's (``metadataValueBytes`` and the rest), read
# from the vendored contract.

#: The most one value may take, as JSON.
VALUE_BYTES = contract.cap("metadataValueBytes")
#: What one install may keep on one item.
ITEM_KEYS = contract.cap("metadataKeysPerObject")
ITEM_BYTES = contract.cap("metadataBytesPerObject")
#: What an install may keep on itself.
INSTALL_KEYS = contract.cap("installMetadataKeys")
INSTALL_BYTES = contract.cap("installMetadataBytes")
#: The most items one read may name.
READ_IDS = 500
#: The most items one look-up answers.
FIND_LIMIT = 100
#: The most targeted changes one of a declarative plug-in's ``write``
#: expressions may answer.
WRITE_TARGETS = contract.cap("writeTargets")
#: How long one routing as the install serves a run of changes before it is
#: established again, well inside the age a routing may reach.
_REROUTE_SECONDS = RLS_CONTEXT_MAX_AGE_SECONDS / 2
#: The largest id an item's row holds: a change naming one past it names an
#: item that is not there.
_MAX_ITEM_ID = 2**31 - 1
#: How a list's elements are read: newest first, then by ref.
NEWEST_FIRST = (
    col(MetadataValue.updated_at).desc(),
    col(MetadataValue.ref).collate("C"),
)
#: The tones a badge, and a list's element, may take.
_TONES = contract.enum("tone")
#: The type a field's ``kind`` is kept as.
_KIND_TYPES: dict[str, MetadataType] = {kind.value: kind for kind in MetadataType}
#: The types a value is kept in ``value_json`` with its words in
#: ``value_text``.
_OBJECT_TYPES = frozenset({MetadataType.link, MetadataType.badge})


def _table(kind: str) -> Table:
    return SQLModel.metadata.tables[KINDS[kind].table]


def _read_scope(kind: str) -> str:
    """The scope an install reads ``kind`` with: its tool's read scope."""
    governed = governing_path(KINDS[kind].table)
    assert governed is not None, kind
    return f"{tool_resource(governed[0]).value}:read"


def _check_key(key: str) -> None:
    if not is_metadata_key(key):
        raise PluginChannelError(PluginChannelMessages.METADATA_KEY_INVALID)


def _size(value: Any) -> int:
    """``value``'s size as compact JSON, in bytes."""
    return len(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _invalid() -> PluginChannelError:
    return PluginChannelError(PluginChannelMessages.METADATA_VALUE_INVALID)


def _json_number(number: Decimal) -> int | float:
    """A kept number as JSON writes it: whole numbers without a fraction."""
    return int(number) if number == number.to_integral_value() else float(number)


#: How a person a plug-in names comes in and goes out: as the install's own
#: reference for them through the request's boundary, and as a row id where
#: Initiative itself moves a value (:func:`sync_definitions`).
@dataclass(frozen=True)
class _People:
    takes: Callable[[Any], int]
    gives: Callable[[int], Any]


def _install_people() -> _People:
    """People as the install being answered names them."""
    boundary = current_install_boundary()

    def takes(value: Any) -> int:
        if boundary is None or not isinstance(value, str):
            raise _invalid()
        # A person this request already answered with, kept in an element
        # an upsert merges into.
        marked, _, user_id = value.rpartition(":")
        if (
            marked == f"{boundary.nonce}:{IdentityEntity.user.code}"
            and user_id.isdigit()
        ):
            return int(user_id)
        try:
            return boundary.resolve(value, IdentityEntity.user)
        except PydanticCustomError:
            raise _invalid() from None

    def gives(user_id: int) -> Any:
        return (
            user_id if boundary is None else boundary.mark(IdentityEntity.user, user_id)
        )

    return _People(takes, gives)


_ROW_IDS = _People(takes=lambda value: value, gives=lambda user_id: user_id)


def _is_state(value: Any) -> bool:
    return isinstance(value, dict) and all(
        is_identifier(facet) and is_identifier(key) for facet, key in value.items()
    )


def _stored(
    defn: MetadataDefinition, value: Any, people: _People, *, element: bool = False
) -> Dict[str, Any]:
    """The columns that keep ``value`` under a plug-in's ``defn``: its typed
    column, ``value_json`` and ``value_text`` for a link or a badge, and its
    ``state``. ``element`` is one element of a list field's value, its ``ref``
    already taken. Raises for a value that is not one of the type's."""
    cols: Dict[str, Any] = {**_empty_columns(), "state": None}
    kind = defn.type
    if kind is MetadataType.json:
        cols["value_json"] = (
            {name: held for name, held in value.items() if name != "ref"}
            if element
            else value
        )
        return cols
    figure, whole = value, None
    if isinstance(value, dict):
        rest = {name: held for name, held in value.items() if name != "ref"}
        if "state" in rest:
            if not _is_state(rest["state"]):
                raise _invalid()
            cols["state"] = rest.pop("state")
        if kind in _OBJECT_TYPES:
            figure = rest
        elif set(rest) <= {"value", "max"} and "value" in rest:
            figure, whole = rest["value"], rest.get("max")
        else:
            raise _invalid()
    if (whole is not None and kind is not MetadataType.scale) or (
        kind in _OBJECT_TYPES and not isinstance(figure, dict)
    ):
        raise _invalid()
    if kind is MetadataType.link:
        url, words = figure.get("url"), figure.get("text")
        if (
            set(figure) - {"url", "text"}
            or not isinstance(url, str)
            or not (words is None or isinstance(words, str))
        ):
            raise _invalid()
        cols["value_json"] = figure
        cols["value_text"] = words or url
    elif kind is MetadataType.badge:
        words, tone = figure.get("text"), figure.get("tone")
        if (
            set(figure) - {"text", "tone"}
            or not isinstance(words, str)
            or not (tone is None or tone in _TONES)
        ):
            raise _invalid()
        cols["value_json"] = figure
        cols["value_text"] = words
    elif kind is MetadataType.scale:
        number = _plugin_number(figure)
        if whole is not None:
            parts = _plugin_number(whole)
            if parts <= 0:
                raise _invalid()
            number = number / parts * 100
        if not 0 <= number <= 100:
            raise _invalid()
        cols["value_number"] = number
    elif kind in (MetadataType.number, MetadataType.currency):
        cols["value_number"] = _plugin_number(figure)
    elif kind in (MetadataType.text, MetadataType.select):
        if not isinstance(figure, str) or (
            kind is MetadataType.select and figure not in _option_slugs(defn)
        ):
            raise _invalid()
        cols["value_text"] = figure
    elif kind is MetadataType.url:
        cols["value_text"] = _plugin_coerced(_coerce_url, figure)
    elif kind is MetadataType.checkbox:
        cols["value_boolean"] = _plugin_coerced(_coerce_bool, figure)
    elif kind is MetadataType.date:
        if not isinstance(figure, str):
            raise _invalid()
        cols["value_date"] = _plugin_coerced(_coerce_date, figure)
    elif kind is MetadataType.datetime:
        if not isinstance(figure, str):
            raise _invalid()
        moment = _plugin_coerced(_coerce_datetime, figure)
        cols["value_datetime"] = (
            moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        )
    elif kind is MetadataType.multi_select:
        valid = _option_slugs(defn)
        if not isinstance(figure, list) or not all(
            isinstance(slug, str) and slug in valid for slug in figure
        ):
            raise _invalid()
        cols["value_json"] = list(dict.fromkeys(figure))
    elif kind is MetadataType.user_reference:
        cols["value_user_id"] = people.takes(figure)
    return cols


def _plugin_number(raw: Any) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _invalid()
    number = _plugin_coerced(_coerce_number, raw)
    if not number.is_finite():
        raise _invalid()
    return number


def _plugin_coerced(coerce: Callable[[Any], Any], raw: Any) -> Any:
    """``coerce``'s answer for ``raw``, its refusal a plug-in's."""
    try:
        return coerce(raw)
    except HTTPException:
        raise _invalid() from None


def _told(defn: MetadataDefinition, row: Any, people: _People) -> Any:
    """A kept value as the plug-in wrote it: under a list field, an element
    with its ``ref``; with a ``state``, the state beside it."""
    kind = defn.type
    if kind is MetadataType.json:
        return {"ref": row.ref, **(row.value_json or {})} if row.ref else row.value_json
    if kind in _OBJECT_TYPES:
        parts = dict(row.value_json or {})
    else:
        if kind is MetadataType.multi_select:
            figure = row.value_json
        elif kind in _NUMBER_TYPES:
            figure = (
                None if row.value_number is None else _json_number(row.value_number)
            )
        elif kind is MetadataType.checkbox:
            figure = row.value_boolean
        elif kind is MetadataType.date:
            figure = row.value_date and row.value_date.isoformat()
        elif kind is MetadataType.datetime:
            figure = row.value_datetime and row.value_datetime.isoformat()
        elif kind is MetadataType.user_reference:
            figure = (
                None if row.value_user_id is None else people.gives(row.value_user_id)
            )
        else:
            figure = row.value_text
        if not row.ref and not row.state:
            return figure
        parts = {"value": figure}
    if row.state:
        parts["state"] = row.state
    return {"ref": row.ref, **parts} if row.ref else parts


def assembled(rows: Iterable[tuple[str, str, Any]]) -> dict[str, Any]:
    """Values by key, from ``(key, ref, value)`` rows read
    :data:`NEWEST_FIRST`: a value as it is kept, and a list's elements as an
    array in the rows' order."""
    values: dict[str, Any] = {}
    lists: set[str] = set()
    for key, ref, value in rows:
        if ref:
            if key not in lists:
                lists.add(key)
                values[key] = []
            values[key].append(value)
        elif key not in lists:
            values[key] = value
    return values


async def _installed(
    session: AsyncSession, install_id: int, keys: Optional[Collection[str]] = None
) -> dict[str, MetadataDefinition]:
    """The install's definitions by key: every one, or those of ``keys``."""
    query = select(MetadataDefinition).where(
        MetadataDefinition.install_id == install_id
    )
    if keys is not None:
        query = query.where(col(MetadataDefinition.key).in_(list(keys)))
    return {str(defn.key): defn for defn in await session.exec(query) if defn.key}


async def _kept(
    session: AsyncSession, install_id: int, where: Sequence[Any]
) -> list[tuple[MetadataDefinition, MetadataValue]]:
    """The install's value rows ``where`` names, each with its definition,
    :data:`NEWEST_FIRST`."""
    return list(
        (
            await session.exec(
                select(MetadataDefinition, MetadataValue)
                .join(MetadataValue, MetadataValue.property_id == MetadataDefinition.id)
                .where(MetadataDefinition.install_id == install_id, *where)
                .order_by(*NEWEST_FIRST)
            )
        ).all()
    )


def _grouped(
    rows: Iterable[tuple[MetadataDefinition, MetadataValue]], people: _People
) -> dict[tuple[str, int], dict[str, Any]]:
    """Each item's values (:func:`assembled`), from its rows read
    :data:`NEWEST_FIRST`."""
    held: dict[tuple[str, int], list[tuple[str, str, Any]]] = defaultdict(list)
    for defn, row in rows:
        held[(row.entity_type, row.entity_id)].append(
            (str(defn.key), row.ref, _told(defn, row, people))
        )
    return {item: assembled(values) for item, values in held.items()}


async def _readable(session: AsyncSession, kind: str, entity_id: int) -> bool:
    """Whether the routed install can read the item. Its table's policies
    decide, as they do for every read of it."""
    table = _table(kind)
    return bool(await session.scalar(exists().where(table.c.id == entity_id).select()))


def _fields_on(declared: Any, kind: Optional[str] = None) -> list[dict[str, Any]]:
    """The fields a pinned definition, or its ``fields`` alone, declares: on
    ``kind``, or on any."""
    fields = declared.get("fields") if isinstance(declared, dict) else declared
    return [
        field
        for field in (fields if isinstance(fields, list) else [])
        if isinstance(field, dict)
        and isinstance(field.get("key"), str)
        and (kind is None or kind in (field.get("on") or ()))
    ]


def shown_keys(definition: Any, kind: str) -> frozenset[str]:
    """The keys a pinned definition declares as fields on ``kind``."""
    return frozenset(field["key"] for field in _fields_on(definition, kind))


def _declared(field: Optional[Mapping[str, Any]], key: str) -> Dict[str, Any]:
    """What a definition of ``key`` is under the pinned ``field`` declaring
    it, or under none."""
    if field is None:
        return {
            "name": key,
            "type": MetadataType.json,
            "list": False,
            "shown_on": [],
            "options": None,
            "currency": None,
        }
    kind = _KIND_TYPES.get(str(field.get("kind")), MetadataType.json)
    return {
        "name": key,
        "type": kind,
        "list": field.get("list") is True,
        "shown_on": sorted(field.get("on") or ()),
        "options": (
            [_option(option) for option in field.get("options") or ()]
            if kind in _SELECT_TYPES
            else None
        ),
        "currency": field.get("currency") if kind is MetadataType.currency else None,
    }


#: The types whose definitions hold options.
_SELECT_TYPES = frozenset({MetadataType.select, MetadataType.multi_select})
#: The longest label an option keeps (``PropertyOption``).
_OPTION_LABEL_LENGTH = 100


def _option(declared: Mapping[str, Any]) -> Dict[str, Any]:
    """A manifest field's option as a definition keeps one
    (``PropertyOption``): its value, its label in English or else the first
    language it names, and its colour."""
    label = declared.get("label")
    if isinstance(label, dict):
        label = label.get("en") or next(iter(label.values()), None)
    option = {
        "value": declared.get("value"),
        "label": str(label or declared.get("value"))[:_OPTION_LABEL_LENGTH],
    }
    if declared.get("color"):
        option["color"] = declared["color"]
    return option


async def _defined(
    session: AsyncSession, install_id: int, keys: Collection[str], fields: Any
) -> dict[str, MetadataDefinition]:
    """The install's definitions of ``keys``, each made as the pinned
    ``fields`` declare it the first time the install writes it."""
    found = await _installed(session, install_id, keys)
    missing = [key for key in keys if key not in found]
    if missing:
        declared = {field["key"]: field for field in _fields_on(fields)}
        now = datetime.now(timezone.utc)
        statement = pg_insert(MetadataDefinition).values(
            [
                {
                    "install_id": install_id,
                    "key": key,
                    "created_at": now,
                    "updated_at": now,
                    **_declared(declared.get(key), key),
                }
                for key in missing
            ]
        )
        await session.exec(
            statement.on_conflict_do_nothing(
                index_elements=["install_id", "key"],
                index_where=col(MetadataDefinition.install_id).is_not(None),
            )
        )
        found.update(await _installed(session, install_id, missing))
    return found


async def read(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_ids: Sequence[int],
) -> list[tuple[str, int, dict[str, Any]]]:
    """The install's values on each item it can read, by item. An item holding
    none, or one it cannot read, is left out. For the install's own values,
    ``entity_ids`` is not read."""
    if kind == INSTALL_METADATA_KIND:
        entity_ids = [context.install_id]
    elif len(entity_ids) > READ_IDS:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    if not entity_ids:
        return []
    rows = await _kept(session, context.install_id, [_of(kind, set(entity_ids))])
    grouped = _grouped(rows, _install_people())
    return [
        (entity_type, entity_id, values)
        for (entity_type, entity_id), values in sorted(grouped.items())
    ]


def is_ref(value: Any) -> bool:
    """Whether ``value`` is a list element's ``ref``: 1 to :data:`REF_LENGTH`
    characters."""
    return isinstance(value, str) and 0 < len(value) <= REF_LENGTH


#: What a list's element may hold, and what each takes (the contract's
#: ``listElement``).
_ELEMENT_TERMS: dict[str, Callable[[Any], bool]] = {
    "ref": is_ref,
    "value": lambda value: isinstance(value, (str, int, float)),
    "url": lambda value: isinstance(value, str),
    "text": lambda value: isinstance(value, str),
    "tone": lambda value: isinstance(value, str) and value in _TONES,
    "max": lambda value: (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ),
    "state": _is_state,
}


def _is_element(value: Any) -> bool:
    """Whether ``value`` is one element of a list field's value: an object with
    a ``ref``, holding only :data:`_ELEMENT_TERMS`, each what it takes."""
    return (
        isinstance(value, dict)
        and "ref" in value
        and all(
            name in _ELEMENT_TERMS and _ELEMENT_TERMS[name](held)
            for name, held in value.items()
        )
    )


@dataclass(frozen=True)
class Change:
    """A change to the install's values on one item, or on itself, held to the
    contract's ``change`` (:func:`change`): ``values`` sets them by key, a
    ``None`` removing its key, and ``upsert`` and ``remove`` change a list
    field's elements by their refs (:func:`write`)."""

    values: Mapping[str, Any]
    upsert: Mapping[str, Sequence[Mapping[str, Any]]]
    remove: Mapping[str, Sequence[str]]


def change(*, values: Any = None, upsert: Any = None, remove: Any = None) -> Change:
    """``values``, ``upsert`` and ``remove`` held to the contract's ``change``:
    at least one of the three, each an object by metadata key, and each key in
    one of them; ``upsert`` gives a list of elements under each key, and
    ``remove`` a list of refs. Each element, and each value that is not an
    array, is at most :data:`VALUE_BYTES` as JSON. Whether an array is a list's
    elements or one value is the key's definition's to say, and :func:`write`
    measures it then."""
    given = [ops for ops in (values, upsert, remove) if ops is not None]
    if not given or not all(isinstance(ops, dict) for ops in given):
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    keys = [key for ops in given for key in ops]
    for key in keys:
        _check_key(key)
    if len(set(keys)) < len(keys):
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    for elements in (upsert or {}).values():
        if not isinstance(elements, list) or not all(map(_is_element, elements)):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    measured = [
        *(element for elements in (upsert or {}).values() for element in elements),
        *(
            one
            for value in (values or {}).values()
            if value is not None
            for one in (value if isinstance(value, list) else [value])
        ),
    ]
    if any(_size(one) > VALUE_BYTES for one in measured):
        raise PluginChannelError(
            PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
        )
    for refs in (remove or {}).values():
        if not isinstance(refs, list) or not all(map(is_ref, refs)):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    return Change(values=values or {}, upsert=upsert or {}, remove=remove or {})


def _merged(held: Any, given: Mapping[str, Any]) -> dict[str, Any]:
    """An upserted element over the one with its ref: the properties given
    replace its own, the rest stay, and its ``state`` merges facet by facet."""
    if not isinstance(held, dict):
        return dict(given)
    merged = {**held, **given}
    if isinstance(held.get("state"), dict) and "state" in given:
        merged["state"] = {**held["state"], **given["state"]}
    return merged


async def write(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_id: Optional[int],
    changes: Sequence[Change],
    pinned: Callable[[], Awaitable[Any]],
    *,
    made: Optional[Callable[[dict[str, Any]], Awaitable[Sequence[Change]]]] = None,
) -> dict[str, Any]:
    """Make ``changes``, in turn, to the install's values on one item, or on
    itself. Answers every value it keeps there now (:func:`assembled`).

    A key whose definition is a list field holds a list of elements, a row
    each: ``values`` replaces them with a list of elements, or with none for a
    ``None``; ``upsert`` adds an element with a ref the list does not hold,
    and merges into the one it does (the properties given replace its own, the
    rest stay, and its ``state`` merges facet by facet); ``remove`` takes the
    elements with those refs, and a ref the list does not hold changes
    nothing. Any other key holds one value, which ``values`` sets and a
    ``None`` removes. Each value is held to its definition's type, and each
    value, and each element, is at most :data:`VALUE_BYTES` as JSON; a list
    counts as one key, and its elements' bytes add up.

    A key the install writes for the first time is defined then, as its
    pinned definition declares it (``pinned``, :func:`pinned_fields`), or as
    ``json`` where it declares no field for it.

    With ``made``, the changes made are those it answers when given what the
    install holds there (:func:`assembled`), under the item's lock, so writes
    made at once each read what the one before left.

    On an item, the install needs its tool's read scope and to be able to read
    it: the values are the install's own, and writing them changes nothing on
    the item. Nothing is written while the community's content is on hold.
    """
    if context.content_hold:
        raise PluginChannelError(PluginChannelMessages.GUILD_READ_ONLY, status_code=409)
    if kind == INSTALL_METADATA_KIND:
        entity_id = context.install_id
        max_keys, max_bytes = INSTALL_KEYS, INSTALL_BYTES
    else:
        if entity_id is None:
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
        if not context.holds(_read_scope(kind)):
            raise PluginChannelError(PluginMessages.SCOPE_REQUIRED, status_code=403)
        if not await _readable(session, kind, entity_id):
            raise PluginChannelError(
                PluginChannelMessages.METADATA_ITEM_NOT_FOUND, status_code=404
            )
        max_keys, max_bytes = ITEM_KEYS, ITEM_BYTES

    # Lock order: the install's fields lock (shared here), then the item's
    # lock. Holding the first while the definitions are read, to the commit,
    # means a sync to a new version (which takes it exclusively) runs either
    # before this read, which then sees the definitions it left, or after this
    # commit, and corrects what it wrote.
    await _lock_fields(session, context.guild_id, context.install_id, shared=True)
    # Writes to one item take turns, so the caps hold across them.
    await advisory_lock(
        session,
        LockNamespace.PLUGIN_METADATA,
        f"{context.guild_id}:{context.install_id}:{kind}:{entity_id}",
    )
    people = _install_people()
    where = [_of(kind, [entity_id])]
    stored = {
        (str(defn.key), row.ref): (_told(defn, row, people), row.updated_at)
        for defn, row in await _kept(session, context.install_id, where)
    }
    if made is not None:
        changes = await made(
            assembled((key, ref, value) for (key, ref), (value, _) in stored.items())
        )
    # The keys an item ends up with are counted below; a write may remove every
    # key it holds and set as many again, and no more.
    named = {
        key
        for each in changes
        for ops in (each.values, each.upsert, each.remove)
        for key in ops
    }
    if len(named) > 2 * max_keys:
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )
    # Every key the item ends up holding has its definition; one only
    # removed needs none.
    needed = {key for key, _ in stored} | {
        key
        for each in changes
        for key in (*each.upsert, *(k for k, v in each.values.items() if v is not None))
    }
    definitions = await _defined(
        session, context.install_id, sorted(needed), await pinned()
    )
    lists = {key for key, defn in definitions.items() if defn.list}
    # What the item holds as each change is made, by key: its value under the
    # ref '', or its list's elements by their refs.
    held: dict[str, dict[str, Any]] = defaultdict(dict)
    for (key, ref), (value, _) in stored.items():
        held[key][ref] = value
    written: set[tuple[str, str]] = set()
    for each in changes:
        for key, value in each.values.items():
            if key not in lists:
                held[key] = {} if value is None else {"": value}
            elif value is None or (
                isinstance(value, list) and all(map(_is_element, value))
            ):
                held[key] = {element["ref"]: element for element in value or ()}
            else:
                raise PluginChannelError(PluginChannelMessages.METADATA_LIST_MISMATCH)
            written.update((key, ref) for ref in held[key])
        for key in (*each.upsert, *each.remove):
            if key not in lists:
                raise PluginChannelError(PluginChannelMessages.METADATA_LIST_MISMATCH)
        for key, elements in each.upsert.items():
            held[key].pop("", None)
            for element in elements:
                ref = element["ref"]
                held[key][ref] = _merged(held[key].get(ref), element)
                written.add((key, ref))
        for key, refs in each.remove.items():
            for ref in refs:
                held[key].pop(ref, None)

    sizes = {
        (key, ref): _size(value)
        for key, elements in held.items()
        for ref, value in elements.items()
    }
    if any(sizes[item] > VALUE_BYTES for item in written if item in sizes):
        raise PluginChannelError(
            PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
        )
    if (
        sum(1 for values in held.values() if values) > max_keys
        or sum(sizes.values()) > max_bytes
    ):
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )

    now = datetime.now(timezone.utc)
    kept: dict[tuple[str, str], tuple[Any, Dict[str, Any]]] = {}
    for key, elements in held.items():
        for ref, value in elements.items():
            if (key, ref) not in written:
                kept[(key, ref)] = (value, {})
                continue
            cols = _stored(definitions[key], value, people, element=bool(ref))
            kept[(key, ref)] = (
                _told(definitions[key], SimpleNamespace(ref=ref, **cols), people),
                cols,
            )
    gone = [item for item in stored if item not in kept]
    if gone:
        await session.exec(
            delete(MetadataValue).where(
                *where,
                tuple_(MetadataValue.property_id, MetadataValue.ref).in_(
                    [(definitions[key].id, ref) for key, ref in gone]
                ),
            )
        )
    fresh = [
        {
            "entity_type": kind,
            "entity_id": entity_id,
            "property_id": definitions[key].id,
            "ref": ref,
            **cols,
            "created_at": now,
            "updated_at": now,
        }
        for (key, ref), (_, cols) in kept.items()
        if (key, ref) in written
    ]
    for start in range(0, len(fresh), _WRITE_BATCH):
        statement = pg_insert(MetadataValue).values(fresh[start : start + _WRITE_BATCH])
        await session.exec(
            statement.on_conflict_do_update(
                index_elements=["entity_type", "entity_id", "property_id", "ref"],
                set_={
                    name: getattr(statement.excluded, name)
                    for name in (*VALUE_COLUMNS, "state", "updated_at")
                },
            )
        )
    await session.commit()
    # Newest first, then by ref, as a read answers them.
    rows = [(key, ref, told) for (key, ref), (told, _) in kept.items()]
    rows.sort(key=lambda row: row[1])
    rows.sort(
        key=lambda row: now if row[:2] in written else stored[row[:2]][1],
        reverse=True,
    )
    return assembled(rows)


#: Rows one statement writes, within the parameters a statement may bind.
_WRITE_BATCH = 500


def _matching(defn: MetadataDefinition, value: str) -> Any:
    """The rows of ``defn`` that hold ``value``: a list's element by its
    ``ref``, and any other value by its text, a number or a boolean as JSON
    writes it. ``None`` when no value of the definition can be ``value``."""
    if defn.list:
        return MetadataValue.ref == value
    kind = defn.type
    if kind is MetadataType.json:
        return and_(
            func.jsonb_typeof(MetadataValue.value_json).in_(
                ("string", "number", "boolean")
            ),
            col(MetadataValue.value_json).op("#>>")(literal_column("'{}'::text[]"))
            == value,
        )
    if kind in (MetadataType.multi_select, MetadataType.user_reference):
        return None
    compared = _coerce_filter_scalar(kind, value)
    column = typed_column_for_property(kind)
    return None if compared is None else column == compared


async def holders(
    session: AsyncSession,
    context: InstallContext,
    key: str,
    value: str,
    *,
    limit: Optional[int] = None,
) -> list[tuple[str, int]]:
    """The items the install can read holding ``value`` under ``key``, a list
    holding it as an element's ref, in kind and id order: every one, or the
    first ``limit``. The install's own values are not an item."""
    _check_key(key)
    defn = (await _installed(session, context.install_id, [key])).get(key)
    held = None if defn is None or len(value) > REF_LENGTH else _matching(defn, value)
    if held is None:
        return []
    return [
        (entity_type, entity_id)
        for entity_type, entity_id in await session.exec(
            select(MetadataValue.entity_type, MetadataValue.entity_id)
            .where(
                MetadataValue.property_id == defn.id,
                held,
                MetadataValue.entity_type != INSTALL_METADATA_KIND,
            )
            .order_by(MetadataValue.entity_type, MetadataValue.entity_id)
            .limit(limit)
        )
    ]


async def find(
    session: AsyncSession,
    context: InstallContext,
    key: str,
    value: str,
    *,
    limit: int = FIND_LIMIT,
) -> list[tuple[str, int, dict[str, Any]]]:
    """The first ``limit`` items holding ``value`` under ``key``
    (:func:`holders`), with the values the install keeps on each: the lookup
    route's page."""
    matches = await holders(session, context, key, value, limit=limit)
    if not matches:
        return []
    by_kind: dict[str, list[int]] = defaultdict(list)
    for entity_type, entity_id in matches:
        by_kind[entity_type].append(entity_id)
    rows = await _kept(
        session,
        context.install_id,
        [or_(*(_of(entity_type, ids) for entity_type, ids in by_kind.items()))],
    )
    grouped = _grouped(rows, _install_people())
    return [
        (entity_type, entity_id, grouped.get((entity_type, entity_id), {}))
        for entity_type, entity_id in matches
    ]


async def shown_values(
    session: AsyncSession, install_id: int, kind: str, entity_id: int
) -> dict[str, Any]:
    """The values an install shows on one item, by key, as the plug-in wrote
    them, read on the reader's session."""
    rows = await _kept(
        session,
        install_id,
        [
            _of(kind, [entity_id]),
            MetadataValue.entity_type == any_(MetadataDefinition.shown_on),
        ],
    )
    return _grouped(rows, _ROW_IDS).get((kind, entity_id), {})


def _is_target(target: Any) -> bool:
    """Whether ``target`` is one of the contract's ``changeTarget`` shapes: an
    item, the install, or the items the install holds a value on."""
    if not isinstance(target, dict):
        return False
    if set(target) == {"kind", "id"}:
        kind, entity_id = target["kind"], target["id"]
        return (
            isinstance(kind, str)
            and kind in ITEM_KINDS
            and isinstance(entity_id, int)
            and not isinstance(entity_id, bool)
            and entity_id >= 1
        )
    if set(target) == {"install"}:
        return target["install"] is True
    holding = target.get("holding") if set(target) == {"holding"} else None
    return (
        isinstance(holding, dict)
        and set(holding) == {"key", "value"}
        and is_metadata_key(holding["key"])
        and isinstance(holding["value"], str)
        and len(holding["value"]) <= REF_LENGTH
    )


def _targeted(answer: Any) -> list[tuple[dict[str, Any], Change]]:
    """What a declarative plug-in's ``write`` answered, held to the contract's
    ``targetedChange``: a list of at most :data:`WRITE_TARGETS`, each a target
    and a change (:func:`change`). Nothing answered is no change. An answer
    that is not that is refused whole, before anything is written."""
    if answer is UNDEFINED:
        return []
    if not isinstance(answer, list) or len(answer) > WRITE_TARGETS:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    changes: list[tuple[dict[str, Any], Change]] = []
    for raw in answer:
        if not (
            isinstance(raw, dict)
            and set(raw) <= {"target", "set", "upsert", "remove"}
            and _is_target(raw.get("target"))
        ):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
        changes.append(
            (
                raw["target"],
                change(
                    values=raw.get("set"),
                    upsert=raw.get("upsert"),
                    remove=raw.get("remove"),
                ),
            )
        )
    return changes


@asynccontextmanager
async def _as_install(
    plugin: GuildPlugin, registration: RegistrationSnapshot, guild_id: int
) -> AsyncIterator[
    tuple[
        AsyncSession,
        Callable[[], Awaitable[InstallContext]],
        Callable[[], Awaitable[Any]],
    ]
]:
    """A session of its own routed as the install, through the install seam
    with the scopes the install holds (:func:`guild_plugins.install_scopes`):
    the session, what routes it again, and what reads the install's pinned
    definition."""
    from app.api.deps import (
        InstallAccessError,
        VerifiedInstall,
        establish_install_access,
    )
    from app.services.tenant import guild_plugins

    install = VerifiedInstall(
        guild_id=guild_id,
        install_id=int(plugin.id or 0),
        client_id=registration.public_id,
        scopes=guild_plugins.install_scopes(plugin, registration),
    )
    async with cohorts.request_sessionmaker(guild_id)() as session:

        async def route() -> InstallContext:
            try:
                return await establish_install_access(session, install)
            except InstallAccessError as exc:
                raise PluginChannelError(
                    PluginChannelMessages.INSTALL_NOT_FOUND, status_code=404
                ) from exc

        async def pinned() -> Any:
            return await pinned_fields(session, install.install_id)

        yield session, route, pinned


async def pinned_fields(session: AsyncSession, install_id: int) -> Any:
    """The fields an install's pinned definition declares, read on a session
    routed as the install (the plug-in's role reads that column)."""
    return await session.scalar(
        select(GuildPlugin.definition["fields"]).where(GuildPlugin.id == install_id)
    )


async def apply_changes(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    answer: Any,
    *,
    guild_id: int,
) -> None:
    """Make the changes a declarative plug-in's ``write`` answered, as its
    install, on a session of its own routed through the install seam with the
    scopes the install holds (:func:`guild_plugins.install_scopes`).

    ``answer`` is held to the contract first (:func:`_targeted`). Each target
    is then found as the install: one item, the install itself, or every item
    the install holds a value on, at most :data:`FIND_LIMIT` (:func:`find`).
    An item more than one change reaches is written once, its changes made in
    the order they were answered. Each item is written by :func:`write`, under
    its checks, caps and locks, and committed; one the install cannot read, or
    that is not there, is skipped.

    Raises :class:`PluginChannelError` for an answer that is not targeted
    changes, an install that may not act, and a write refused for any other
    reason. The items written before a refusal keep what was written: every
    change sets, merges or removes values, so making the same changes again
    leaves the same values.
    """
    changes = _targeted(answer)
    if not changes:
        return
    async with _as_install(plugin, registration, guild_id) as (session, route, pinned):
        context = await route()
        routed = time.monotonic()
        targets: dict[tuple[str, int], list[Change]] = {}
        for target, made in changes:
            if "holding" in target:
                found = await holders(
                    session,
                    context,
                    target["holding"]["key"],
                    target["holding"]["value"],
                )
            elif "install" in target:
                found = [(INSTALL_METADATA_KIND, context.install_id)]
            elif target["id"] <= _MAX_ITEM_ID:
                found = [(target["kind"], target["id"])]
            else:
                found = []
            for item in found:
                targets.setdefault(item, []).append(made)

        for (kind, entity_id), made in targets.items():
            if time.monotonic() - routed > _REROUTE_SECONDS:
                context = await route()
                routed = time.monotonic()
            try:
                await write(session, context, kind, entity_id, made, pinned)
            except PluginChannelError as exc:
                if exc.code not in (
                    PluginMessages.SCOPE_REQUIRED,
                    PluginChannelMessages.METADATA_ITEM_NOT_FOUND,
                ):
                    raise


async def change_item(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    kind: str,
    entity_id: int,
    made: Callable[[dict[str, Any]], Awaitable[Any]],
    *,
    guild_id: int,
) -> None:
    """Make the change ``made`` answers on one item, as :func:`apply_changes`
    makes a change, from what the install holds there: ``made`` is given those
    values, by key, under the item's lock (:func:`write`), so changes made at
    once each start from what the one before left. It answers one change,
    held to the contract's ``change``, or ``None`` for none. An item the
    install cannot read, or that is not there, is refused rather than
    skipped."""

    async def changes(held: dict[str, Any]) -> list[Change]:
        answer = await made(held)
        if answer is None:
            return []
        ((_, changed),) = _targeted(
            [{**answer, "target": {"kind": kind, "id": entity_id}}]
        )
        return [changed]

    async with _as_install(plugin, registration, guild_id) as (session, route, pinned):
        await write(session, await route(), kind, entity_id, [], pinned, made=changes)


async def _lock_fields(
    session: AsyncSession, guild_id: int, install_id: int, *, shared: bool
) -> None:
    """The lock that orders writing an install's values against bringing its
    definitions up to date with a new version."""
    await advisory_lock(
        session, LockNamespace.PLUGIN_FIELDS, f"{guild_id}:{install_id}", shared=shared
    )


async def sync_definitions(
    guild_id: int, install_id: int, *, session: Optional[AsyncSession] = None
) -> None:
    """Bring the install's definitions up to date with its pinned version,
    after it moves to another: each key's type, list field, options and
    currency as the field declaring it says, or ``json`` where none does, and
    the kinds it is shown on. A definition whose type changes keeps each value
    that is one of the new type's, and loses the rest; one that becomes, or
    stops being, a list field loses its values.

    The definition is read once no write is between reading it and committing
    (:func:`write`), so what a write read before the move is corrected here.

    ``session`` is the community's system session, routed, whose caller
    commits; without one the rows are written and committed on a system
    session of their own."""
    if session is None:
        async with cohorts.system_session(guild_id) as own:
            await set_rls_context(own, SystemGuild(guild_id))
            await sync_definitions(guild_id, install_id, session=own)
            await own.commit()
        return
    await _lock_fields(session, guild_id, install_id, shared=False)
    fields = await session.scalar(
        select(GuildPlugin.definition["fields"]).where(GuildPlugin.id == install_id)
    )
    declared = {field["key"]: field for field in _fields_on(fields)}
    for key, defn in (await _installed(session, install_id)).items():
        wanted = _declared(declared.get(key), key)
        was = (defn.type, defn.list)
        for name, value in wanted.items():
            setattr(defn, name, value)
        if was == (defn.type, defn.list):
            continue
        values = (
            await session.exec(
                select(MetadataValue).where(MetadataValue.property_id == defn.id)
            )
        ).all()
        old = SimpleNamespace(type=was[0])
        for row in values:
            try:
                if was[1] != defn.list:
                    raise _invalid()
                cols = _stored(
                    defn, _told(old, row, _ROW_IDS), _ROW_IDS, element=bool(row.ref)
                )
            except PluginChannelError:
                await session.delete(row)
                continue
            for name, value in cols.items():
                setattr(row, name, value)
        defn.updated_at = datetime.now(timezone.utc)
    await session.flush()


class _Offered:
    """Whether a reader is drawn an install's values in an initiative: it is
    placed there with a role the reader holds (or the reader is the
    community's admin), and the reader is old enough for it. Each pair is
    decided once, and the reader's age read only if a plug-in asks for one."""

    def __init__(self, context: GuildContext) -> None:
        self._context = context
        self._viewer: Any = None
        self._known: dict[tuple[int, int], bool] = {}

    async def __call__(
        self, install_id: int, initiative_id: int, roles: Any, minimum: Any
    ) -> bool:
        from app.services.tenant import guild_plugins, plugin_age

        if (install_id, initiative_id) not in self._known:
            old_enough = True
            if minimum is not None:
                self._viewer = self._viewer or await plugin_age.current_viewer(
                    self._context.user_id
                )
                old_enough = plugin_age.age_allows(
                    {"minimum_age": minimum}, self._viewer
                )
            self._known[(install_id, initiative_id)] = (
                guild_plugins.surface_access(
                    guild_plugins.ITEM_SURFACE,
                    initiative_id=initiative_id,
                    placement_role_ids=list(roles or ()),
                    is_guild_admin=self._context.is_admin,
                    member_role_ids=self._context.member_role_ids,
                    age_allows=old_enough,
                )
                is guild_plugins.SurfaceAccess.open
            )
        return self._known[(install_id, initiative_id)]


async def _plugin_summaries(
    session: AsyncSession, target: str, ids: Sequence[int]
) -> dict[int, List[PropertySummary]]:
    """The shown plug-in values on items of one kind, by item id, a list's as
    an array (:func:`assembled`): those of the installs whose actions the
    reader could run there — on, placed in the item's initiative with a role
    the reader holds (or the reader its admin), and the reader old enough for
    the plug-in (``guild_plugins.surface_access``). One query for the page.

    ``session`` is the reader's, so which values it reads is the table's
    policies' answer; which installs' values are drawn is decided here. An
    item no initiative holds is drawn none, nor is an installed plug-in reading
    items: it reads its own values through its metadata routes. Nor is a
    guest, who runs no plug-in."""
    context = guild_context(session)
    if target not in ITEM_KINDS or context is None or context.guest:
        return {}
    initiative = func.entity_initiative(target, MetadataValue.entity_id)
    rows = (
        await session.exec(
            select(
                MetadataDefinition,
                MetadataValue,
                PluginPlacement.initiative_id,
                PluginPlacement.role_ids,
                GuildPlugin.definition["minimum_age"],
            )
            .join(MetadataValue, MetadataValue.property_id == MetadataDefinition.id)
            .join(GuildPlugin, GuildPlugin.id == MetadataDefinition.install_id)
            .join(
                PluginPlacement,
                and_(
                    PluginPlacement.install_id == MetadataDefinition.install_id,
                    PluginPlacement.initiative_id == initiative,
                ),
            )
            .where(
                _of(target, ids),
                MetadataValue.entity_type == any_(MetadataDefinition.shown_on),
                GuildPlugin.enabled.is_(True),
            )
            .order_by(MetadataDefinition.id, *NEWEST_FIRST)
        )
    ).all()
    offered = _Offered(context)
    definitions: dict[int, MetadataDefinition] = {}
    held: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for defn, row, initiative_id, roles, minimum in rows:
        if await offered(int(defn.install_id or 0), initiative_id, roles, minimum):
            definitions[defn.id] = defn
            held[(row.entity_id, defn.id)].append(row)
    found: dict[int, List[PropertySummary]] = defaultdict(list)
    for (item_id, defn_id), kept in held.items():
        defn = definitions[defn_id]
        told = [_told(defn, row, _ROW_IDS) for row in kept]
        found[item_id].append(
            PropertySummary(
                property_id=defn.id,
                name=defn.name,
                type=defn.type,
                install_id=defn.install_id,
                key=defn.key,
                options=_parsed_options(defn) or None,
                currency=defn.currency,
                value=told if defn.list else told[0],
            )
        )
    return found


@dataclass(frozen=True)
class FilterField:
    """A plug-in field a reader may filter tasks by: its definition, the
    facets of its states, and the initiatives where they are drawn it."""

    definition: MetadataDefinition
    facets: frozenset[str]
    initiatives: frozenset[int]


async def filter_fields(
    session: AsyncSession, field_ids: Collection[str]
) -> dict[str, FilterField]:
    """Of these ``plugin:<install>:<key>`` ids, the fields the reader may filter
    tasks by: those declared on tasks by an install that is on, where
    :func:`summaries_by_id` would draw them. A filter on any other narrows
    nothing, so it tells nobody which tasks hold a value they are not drawn.
    An installed plug-in and a guest are drawn none."""
    from app.schemas.tenant.tool_layout import PLUGIN_FIELD_PREFIX

    context = guild_context(session)
    wanted: dict[tuple[int, str], str] = {}
    for field_id in field_ids:
        install, _, key = field_id.removeprefix(PLUGIN_FIELD_PREFIX).partition(":")
        if field_id.startswith(PLUGIN_FIELD_PREFIX) and install.isdigit() and key:
            wanted[(int(install), key)] = field_id
    if not wanted or context is None or context.guest:
        return {}
    installs = sorted({install for install, _ in wanted})
    # Each install's fields and minimum age, read once each.
    declares = {
        install_id: (fields, minimum)
        for install_id, fields, minimum in await session.exec(
            select(
                GuildPlugin.id,
                GuildPlugin.definition["fields"],
                GuildPlugin.definition["minimum_age"],
            ).where(GuildPlugin.enabled.is_(True), col(GuildPlugin.id).in_(installs))
        )
    }
    definitions = {
        (int(defn.install_id or 0), str(defn.key)): defn
        for defn in await session.exec(
            select(MetadataDefinition).where(
                col(MetadataDefinition.install_id).in_(list(declares)),
                col(MetadataDefinition.key).in_([key for _, key in wanted]),
            )
        )
    }
    placements = await session.exec(
        select(
            PluginPlacement.install_id,
            PluginPlacement.initiative_id,
            PluginPlacement.role_ids,
        ).where(col(PluginPlacement.install_id).in_(list(declares)))
    )
    offered = _Offered(context)
    reach: dict[tuple[int, str], set[int]] = defaultdict(set)
    # The facets of each field's states.
    facets: dict[tuple[int, str], frozenset[str]] = {}
    for install_id, initiative_id, roles in placements.all():
        fields, minimum = declares[install_id]
        for field in _fields_on(fields, "task"):
            pair = (install_id, field["key"])
            if pair not in wanted or pair not in definitions:
                continue
            states = field.get("states")
            facets[pair] = frozenset(
                map(str, states if isinstance(states, dict) else ())
            )
            if await offered(install_id, initiative_id, roles, minimum):
                reach[pair].add(initiative_id)
    return {
        wanted[pair]: FilterField(definitions[pair], facets[pair], frozenset(found))
        for pair, found in reach.items()
    }


def filter_clause(
    field: FilterField, op: FilterOp, value: Any, facet: Any = None
) -> Any:
    """A task list's condition on one plug-in field: one probe of the task's
    rows of its definition, which a list's element each answers alone, on a
    task in an initiative where the reader is drawn the field. With
    ``facet``, one of the facets of the field's states, a value is compared by
    the key it names for that facet. ``None`` when the value cannot be
    compared."""
    defn = field.definition
    form: Any
    by = defn.type
    if facet is None:
        try:
            form = typed_column_for_property(by)
        except ValueError:
            return None
    elif isinstance(facet, str) and facet in field.facets:
        form, by = col(MetadataValue.state)[facet].astext, MetadataType.text
    else:
        return None

    def held(*where: Any) -> Any:
        return and_(
            exists().where(
                MetadataValue.property_id == defn.id,
                MetadataValue.entity_type == "task",
                MetadataValue.entity_id == Task.id,
                *where,
            ),
            col(Task.project_id).in_(
                select(Project.id).where(
                    col(Project.initiative_id).in_(sorted(field.initiatives))
                )
            ),
        )

    if op == FilterOp.is_null:
        try:
            empty = value if isinstance(value, bool) else normalize_is_null_value(value)
        except ValueError:
            return None
        present = held(form.is_not(None))
        return ~present if empty else present
    predicate = build_property_value_predicate(form, by, op, value)
    return None if predicate is None else held(predicate)
