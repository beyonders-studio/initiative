"""Shared import conventions — extracted from ``project_import.py`` (the
proven importer) so every per-type importer resolves cross-references the
same way:

* tags match-or-create by ``(guild_id, name)``;
* property definitions match by name+type with option-set compatibility,
  renamed on collision (never mutate the target's definition);
* people resolve by handle against the TARGET INITIATIVE's members only,
  with unmatched handles reported, never guessed;
* names de-duplicate with an ``" (imported)"`` suffix.

``project_import.py`` re-imports these — one implementation, two callers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.user_display import handle_of
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.models.tenant.tag import Tag

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.import_engine.people import PeopleMap


class TagResolved:
    __slots__ = ("id", "created")

    def __init__(self, *, id: int, created: bool) -> None:
        self.id = id
        self.created = created


_SELECT_TYPES = {MetadataType.select, MetadataType.multi_select}


def options_compatible(
    prop_type: MetadataType,
    target_options: list[dict] | None,
    source_options: list[dict] | None,
) -> bool:
    """Return True when reusing the target's definition is safe.

    For non-select types, options are irrelevant. For select / multi_select,
    the *value* sets must match: stored values reference the option's
    ``value`` field, so a target definition with a different option list
    would silently break filtering and rendering for imported rows. Labels
    are cosmetic and ignored.
    """
    if prop_type not in _SELECT_TYPES:
        return True
    target_values = {
        o.get("value") for o in (target_options or []) if isinstance(o, dict)
    }
    source_values = {
        o.get("value") for o in (source_options or []) if isinstance(o, dict)
    }
    return target_values == source_values


async def ensure_tag(
    session: AsyncSession,
    *,
    name: str,
    color: str,
) -> TagResolved:
    """Find a tag by name in the routed guild's schema, or create it there.

    The match is case-insensitive to mirror the tag CRUD's duplicate-name
    rule — otherwise an import could mint a case-variant duplicate that the
    endpoints would reject with a 409.
    """
    stmt = select(Tag).where(func.lower(Tag.name) == name.strip().lower())
    existing = (await session.exec(stmt)).one_or_none()
    if existing is not None:
        return TagResolved(id=existing.id, created=False)
    tag = Tag(name=name, color=color)
    session.add(tag)
    await session.flush()
    return TagResolved(id=tag.id, created=True)


def unique_name(existing: set[str], desired: str, *, suffix: str = "imported") -> str:
    """Append ' (imported)' / ' (imported 2)' until the name is free.
    Soft, non-fatal collision handling — the always-create policy."""
    if desired not in existing:
        return desired
    candidate = f"{desired} ({suffix})"
    n = 2
    while candidate in existing:
        candidate = f"{desired} ({suffix} {n})"
        n += 1
    return candidate


async def unique_name_in_initiative(
    session: AsyncSession, model: Any, initiative_id: int, desired: str
) -> str:
    """``desired``, made free (:func:`unique_name`) among the names the
    initiative's ``model`` rows already have."""
    taken = await session.exec(
        select(model.name).where(model.initiative_id == initiative_id)
    )
    return unique_name(set(taken.all()), desired)


async def unique_property_name(
    session: AsyncSession, *, initiative_id: int, desired_name: str
) -> str:
    stmt = select(MetadataDefinition.name).where(
        MetadataDefinition.of_initiative(initiative_id)
    )
    existing = {row for row in (await session.exec(stmt)).all()}
    if desired_name not in existing:
        return desired_name
    n = 2
    while f"{desired_name}_{n}" in existing:
        n += 1
    return f"{desired_name}_{n}"


async def load_initiative_member_handles(
    session: AsyncSession, *, initiative_id: int
) -> dict[str, int]:
    """Map ``handle → user_id`` for the target initiative's members.

    People are matched against members of the *initiative*, not the wider
    guild. The handle is what identifies somebody here: it is unique, it is
    what the export writes, and it is readable from a guild — an address is
    not.

    Keyed case-insensitively on the name part, because a handle never differs
    from another by case alone (``ix_users_handle``).
    """
    stmt = (
        select(MemberProfile)
        .join(InitiativeMember, InitiativeMember.user_id == MemberProfile.id)
        .where(InitiativeMember.initiative_id == initiative_id)
    )
    members = (await session.exec(stmt)).all()
    return {handle_key(handle_of(member)): member.id for member in members}


async def load_guild_member_handles(
    session: AsyncSession, *, guild_id: int
) -> dict[str, int]:
    """Map ``handle → user_id`` for everybody in the target community.

    Wider than :func:`load_initiative_member_handles` for one job: restoring
    an initiative's roster places people who are in the community but not yet
    in that initiative, which is exactly the set the narrower map excludes.
    An archive names people; it never creates accounts, so a handle nobody
    here answers to resolves to nothing and is passed over.

    Reads ``GuildMember``, the projection already narrowed to the routed
    guild's members.
    """
    from app.models.platform.user_profile_view import GuildMember

    members = (await session.exec(select(GuildMember))).all()
    return {handle_key(handle_of(member)): member.id for member in members}


def handle_key(handle: str | None) -> str:
    """A handle as it is looked up: trimmed, and lowercased on the name part."""
    return (handle or "").strip().lower()


async def load_initiative_properties(
    session: AsyncSession, *, initiative_id: int
) -> dict[str, MetadataDefinition]:
    stmt = select(MetadataDefinition).where(
        MetadataDefinition.of_initiative(initiative_id)
    )
    return {pd.name: pd for pd in (await session.exec(stmt)).all()}


class _EnvelopePropertyValue(Protocol):
    property_type: MetadataType
    value_text: str | None
    value_number: float | None
    value_boolean: bool | None
    value_json: Any
    value_handle: str | None


def decode_property_value(
    pv: _EnvelopePropertyValue,
    initiative_member_handles: dict[str, int],
    *,
    people: "PeopleMap | None" = None,
) -> dict[str, Any] | None:
    """Convert an envelope property value back to the typed column kwargs.

    A user reference names somebody by handle, and is placed the way an
    assignee is (``people.initiative_member_id``): the account the import's
    people step mapped the handle to, else a member whose handle is the same
    string — and a member of the target initiative either way, because a
    property on a task in an initiative points at somebody in it.

    Returns ``None`` when a user reference places nobody — the caller skips
    that one value, and the property reads as empty.
    """
    t = pv.property_type
    if t in (MetadataType.text, MetadataType.url, MetadataType.select):
        return {"value_text": pv.value_text}
    if t in (MetadataType.number, MetadataType.currency, MetadataType.scale):
        return {"value_number": pv.value_number}
    if t == MetadataType.checkbox:
        return {"value_boolean": pv.value_boolean}
    if t == MetadataType.date:
        return {"value_date": parse_date(pv.value_text)}
    if t == MetadataType.datetime:
        return {"value_datetime": parse_datetime(pv.value_text)}
    if t == MetadataType.multi_select:
        return {"value_json": pv.value_json}
    if t == MetadataType.user_reference:
        if not pv.value_handle:
            return {"value_user_id": None}
        from app.services.import_engine.people import PeopleMap, initiative_member_id

        uid = initiative_member_id(
            pv.value_handle,
            people=people if people is not None else PeopleMap(),
            member_handles=initiative_member_handles,
        )
        if uid is None:
            # Drop the value rather than the whole row; the UI renders the
            # property as "—".
            return None
        return {"value_user_id": uid}
    return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
