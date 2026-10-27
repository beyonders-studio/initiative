"""Custom properties on every tool and sub-tool — the one seam.

Every tool and every sub-tool (``PROPERTY_TARGETS``) may carry a value for any
property defined in its initiative. The values live in one table,
``property_values``, addressed by ``(entity_type, entity_id)``; this module is
the only code that turns a target into behaviour. :data:`PROPERTY_LINKS` holds
one :class:`PropertyLinkSpec` per target, derived from the registries the
policies are rendered from, and every surface — the write route, the read
field, list filters, copying and moving — reads it.

Responsibilities:
* Validate raw input values against a definition's type and return the typed
  columns to store.
* Replace-all and partial writes, the annotation every serializer reads, and
  the copy and drop a duplicate, an occurrence, a move or a purge asks for.
* List filter predicates over the value table.

The caller owns session lifecycle (commit) — these functions only issue the
in-transaction statements; RLS context replays automatically on each
transaction.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import (
    Any,
    Awaitable,
    Callable,
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
from sqlalchemy import Integer, column, exists, func, insert, literal, true, values
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import current_install_boundary
from app.core.messages import PluginMessages, PropertyMessages, QueryMessages
from app.core.tools import KINDS, PROPERTY_TARGETS, Tool
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.base import MODELS_BY_TABLE
from app.db.initiative_rls import entity_tables, governing_path
from app.db.session import routed_guild_id
from app.models.platform.identity_ref import IdentityEntity
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.property import (
    VALUE_COLUMNS,
    PropertyDefinition,
    PropertyType,
    PropertyValue,
)
from app.schemas.tenant.property import (
    PropertyOption,
    PropertyOptionsChange,
    PropertySummary,
    PropertyValueInput,
)
from app.services.tenant import named_people

# Cap on the number of property predicates accepted by list endpoints.
# Bounds the per-request subquery count against the value table.
MAX_PROPERTY_FILTERS = 5

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
    return (PropertyValue.entity_type == target) & PropertyValue.entity_id.in_(
        list(entity_ids)
    )


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


def _option_slugs(defn: PropertyDefinition) -> Set[str]:
    options = defn.options or []
    slugs: Set[str] = set()
    for opt in options:
        slug = (
            opt.get("value") if isinstance(opt, dict) else getattr(opt, "value", None)
        )
        if slug:
            slugs.add(slug)
    return slugs


def _parsed_options(defn: PropertyDefinition) -> List[PropertyOption]:
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
    defn: PropertyDefinition, raw_value: Any
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

    if ptype is PropertyType.text:
        cols["value_text"] = _coerce_text(raw_value)
    elif ptype is PropertyType.number:
        cols["value_number"] = _coerce_number(raw_value)
    elif ptype is PropertyType.checkbox:
        cols["value_boolean"] = _coerce_bool(raw_value)
    elif ptype is PropertyType.date:
        cols["value_date"] = _coerce_date(raw_value)
    elif ptype is PropertyType.datetime:
        cols["value_datetime"] = _coerce_datetime(raw_value)
    elif ptype is PropertyType.url:
        cols["value_text"] = _coerce_url(raw_value)
    elif ptype is PropertyType.select:
        slug = _coerce_text(raw_value)
        if slug not in _option_slugs(defn):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PropertyMessages.OPTION_NOT_IN_DEFINITION,
            )
        cols["value_text"] = slug
    elif ptype is PropertyType.multi_select:
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
    elif ptype is PropertyType.user_reference:
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise _bad_value()
        cols["value_user_id"] = raw_value
    else:  # pragma: no cover - defensive; PropertyType is closed
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
) -> None:
    """Replace every property value on ``row`` with ``values``. Given
    ``removed``, write only the properties ``values`` names and take off the
    ones ``removed`` names, leaving every other value as it is, so two writes
    of different properties both stand. ``options`` (with ``removed``)
    changes options of multi-select values against what each holds when it
    is written, so two changes of the same value both stand too.

    Each value's definition must belong to ``initiative_id`` — the row's own
    initiative — and a person a value names must be able to open the tool row
    that governs ``row``. The caller has authorized the write and owns the
    commit.
    """
    spec = link_for(row)
    held = _of(spec.target, [row.id])
    named_ids = [
        *(removed or ()),
        *(entry.property_id for entry in values),
        *(change.property_id for change in options),
    ]
    stored = await _in_turn(session, spec.target, row.id, named_ids, options)
    if removed is None:
        await session.exec(delete(PropertyValue).where(held))
    elif named_ids:
        await session.exec(
            delete(PropertyValue).where(
                held,
                PropertyValue.property_id.in_(named_ids),
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

    def definition(property_id: int) -> PropertyDefinition:
        defn = definitions.get(property_id)
        if defn is None or initiative_id is None or defn.initiative_id != initiative_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=PropertyMessages.DEFINITION_NOT_FOUND,
            )
        return defn

    named: set[int] = set()
    rows = [
        PropertyValue(
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
            PropertyValue(
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
        select(PropertyValue.property_id, PropertyValue.value_json).where(
            _of(target, [entity_id]),
            PropertyValue.property_id.in_([c.property_id for c in options]),
        )
    )
    return {property_id: list(slugs or []) for property_id, slugs in held.all()}


def _options_changed(
    defn: PropertyDefinition, stored: list[str], change: PropertyOptionsChange
) -> Dict[str, Any]:
    """The typed columns of a multi-select value once ``change`` is applied to
    the options it holds. What it holds stays, in its order, an option the
    definition has since dropped included; only what ``change`` adds is held
    to the definition."""
    if defn.type is not PropertyType.multi_select:
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
) -> None:
    """The whole write a person or a plug-in makes: resolve a plug-in's person
    references, write the values (all of them, or with ``removed`` only those
    named, as :func:`write_values`), mark the row changed, and let a target
    whose own shape reacts (a repeating event) do so. Authorization is the
    caller's."""
    await write_values(
        session,
        row,
        await property_values_by_row_id(session, values),
        initiative_id=initiative_id,
        removed=removed,
        options=options,
    )
    if hasattr(row, "updated_at"):
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
    rows of ``model``), replacing its own. Two statements however many rows.

    For a duplicate or an occurrence: the same definitions apply, so each pair
    must share an initiative — a caller copying across initiatives copies
    nothing instead.
    """
    if not copies:
        return
    target = link_for(model).target
    # The copies' pending changes first (a series' override takes its calendar
    # just before), so their values are held to where they now sit.
    await session.flush()
    await session.exec(delete(PropertyValue).where(_of(target, copies.values())))
    pairs = values(
        column("source_id", Integer), column("copy_id", Integer), name="pairs"
    ).data(list(copies.items()))
    columns = ("property_id", *VALUE_COLUMNS)
    now = datetime.now(timezone.utc)
    await session.exec(
        insert(PropertyValue).from_select(
            ["entity_type", "entity_id", *columns, "created_at", "updated_at"],
            select(
                literal(target),
                pairs.c.copy_id,
                *(getattr(PropertyValue, c) for c in columns),
                literal(now),
                literal(now),
            )
            .join(pairs, PropertyValue.entity_id == pairs.c.source_id)
            .where(_of(target, copies.keys())),
        )
    )


async def drop_values(
    session: AsyncSession, target: str, entity_ids: Iterable[int]
) -> None:
    """Remove every value on these rows: a move to another initiative, whose
    definitions are not theirs, or a purge."""
    ids = list(entity_ids)
    if ids:
        await session.exec(delete(PropertyValue).where(_of(target, ids)))


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
            and defn.type is PropertyType.user_reference
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
    defn: PropertyDefinition, row: Any, user: Optional[MemberProfile]
) -> Any:
    ptype = defn.type
    if ptype in {PropertyType.text, PropertyType.url, PropertyType.select}:
        return row.value_text
    if ptype is PropertyType.number:
        return _number_to_json(row.value_number)
    if ptype is PropertyType.checkbox:
        return row.value_boolean
    if ptype is PropertyType.date:
        return row.value_date
    if ptype is PropertyType.datetime:
        return row.value_datetime
    if ptype is PropertyType.multi_select:
        return list(row.value_json) if row.value_json is not None else []
    if ptype is PropertyType.user_reference:
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


def summaries_from_rows(rows: Iterable[PropertyValue]) -> List[PropertySummary]:
    """:class:`PropertySummary` list from value rows with ``property_definition``
    (and ``value_user`` where it applies) loaded, sorted by name."""
    summaries: List[PropertySummary] = []
    for row in rows:
        defn = row.property_definition
        if defn is None:
            continue
        summaries.append(
            PropertySummary(
                property_id=defn.id,
                name=defn.name,
                type=defn.type,
                options=_parsed_options(defn) or None,
                value=_rehydrate_value(defn, row, row.value_user),
            )
        )
    summaries.sort(key=lambda s: s.name.lower())
    return summaries


async def summaries_by_id(
    session: AsyncSession, target: str, entity_ids: Iterable[int]
) -> dict[int, List[PropertySummary]]:
    """Every value on these ``target`` rows, as summaries, by row id."""
    ids = list(dict.fromkeys(entity_ids))
    if not ids:
        return {}
    rows = (
        await session.exec(
            select(PropertyValue)
            .where(_of(target, ids))
            .options(
                selectinload(PropertyValue.property_definition),
                selectinload(PropertyValue.value_user),
            )
        )
    ).all()
    grouped: dict[int, list[PropertyValue]] = defaultdict(list)
    for row in rows:
        grouped[row.entity_id].append(row)
    return {
        entity_id: summaries_from_rows(values) for entity_id, values in grouped.items()
    }


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
        PropertyValue.property_id == defn_id,
        PropertyValue.value_text.is_not(None),
        PropertyValue.value_text.not_in(valid_list) if valid_list else true(),
    )
    # value_json (multi_select): not fully contained in the valid set means
    # at least one element is orphaned.
    stmt_json = select(func.count()).where(
        PropertyValue.property_id == defn_id,
        PropertyValue.value_json.is_not(None),
        ~PropertyValue.value_json.op("<@")(valid_list),
    )
    return (await session.exec(stmt_text)).one() + (await session.exec(stmt_json)).one()


# ---------------------------------------------------------------------------
# List filters
# ---------------------------------------------------------------------------


def typed_column_for_property(property_type: PropertyType) -> Any:
    """The value column a property of this type is stored in."""
    if property_type in {PropertyType.text, PropertyType.url, PropertyType.select}:
        return PropertyValue.value_text
    if property_type is PropertyType.number:
        return PropertyValue.value_number
    if property_type is PropertyType.checkbox:
        return PropertyValue.value_boolean
    if property_type is PropertyType.date:
        return PropertyValue.value_date
    if property_type is PropertyType.datetime:
        return PropertyValue.value_datetime
    if property_type is PropertyType.user_reference:
        return PropertyValue.value_user_id
    if property_type is PropertyType.multi_select:
        return PropertyValue.value_json
    raise ValueError(f"Unsupported property type: {property_type!r}")


def _coerce_filter_scalar(property_type: PropertyType, raw: Any) -> Any:
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
        if property_type is PropertyType.number:
            if isinstance(raw, bool):
                return None
            if isinstance(raw, Decimal):
                return raw
            if isinstance(raw, (int, float)):
                return Decimal(str(raw))
            if isinstance(raw, str):
                return Decimal(raw.strip())
            return None
        if property_type is PropertyType.checkbox:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
            return None
        if property_type is PropertyType.date:
            if isinstance(raw, datetime):
                return raw.date()
            if isinstance(raw, date):
                return raw
            if isinstance(raw, str):
                return date.fromisoformat(raw.strip())
            return None
        if property_type is PropertyType.datetime:
            if isinstance(raw, datetime):
                return raw
            if isinstance(raw, str):
                return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            return None
        if property_type is PropertyType.user_reference:
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


def _coerce_filter_value(property_type: PropertyType, op: Any, raw: Any) -> Any:
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
    property_type: PropertyType,
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

    if property_type is PropertyType.multi_select:
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
            PropertyValue.entity_type == target,
            PropertyValue.entity_id == parent_id,
            PropertyValue.property_id == property_id,
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
    property_type: PropertyType,
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
    if property_type is PropertyType.multi_select:
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
    defn: PropertyDefinition,
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
    defs_map: Dict[int, PropertyDefinition],
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
) -> Dict[int, PropertyDefinition]:
    """Load property definitions by id.

    Used by list filters so the endpoint can resolve the correct typed
    column per condition without issuing one query per condition. RLS
    constrains visibility to the caller's accessible initiatives.
    """
    ids = list({did for did in definition_ids if did is not None})
    if not ids:
        return {}
    stmt = select(PropertyDefinition).where(PropertyDefinition.id.in_(ids))
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
        and definition.type is PropertyType.user_reference
        for condition in parsed
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    return build_property_filter_clauses(target, parsed, definitions)
