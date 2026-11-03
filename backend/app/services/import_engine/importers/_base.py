"""Shared importer plumbing: version gating, envelope parsing, the owner
grant every importer writes for what it creates, by-name tag restoring, and
by-name property-value restoring for envelopes that carry values without their
definitions (every tool's but the project's)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Type

from pydantic import BaseModel, ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.metadata import MetadataDefinition, MetadataType, MetadataValue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.import_envelopes import (
    CURRENT_SCHEMA_VERSION,
    MIN_SUPPORTED_IMPORT_VERSION,
    EnvelopePropertyValue,
)
from app.schemas.tenant.project_export import (
    ProjectExportPropertyDefinition,
    ProjectExportTag,
)
from app.services.import_engine.common import (
    decode_property_value,
    ensure_tag,
    load_initiative_member_handles,
    load_initiative_properties,
    options_compatible,
    unique_property_name,
)
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.people import bring_in_named
from app.services.tenant import tags as tags_service
from app.services.tenant import named_people
from app.services.tenant import metadata as metadata_service
from app.services.tenant.metadata import link_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.schemas.tenant.backup_export import ManifestPerson
    from app.services.import_engine.context import ImportContext


class QuotesNobody:
    """An envelope that names no people, which is most of them.

    The people step exists to ask who the handles in an envelope are, and an
    envelope carrying no handles has nothing to ask. Mixed in rather than
    left to a default on the protocol, so "this one quotes nobody" is a
    statement each importer makes rather than something it forgot to say —
    the day a tool's envelope starts carrying comments, dropping this base
    class is what makes the wizard notice.
    """

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        return []


class NamesPeopleInPassing:
    """An envelope that names people without quoting them: through user-type
    property values, and through the mentions in its body.

    A file's properties and a calendar event's can say who somebody is —
    an owner, a reviewer — and a file or a post can mention somebody.
    Both are placed through the people step's answer, like an assignee is. So
    these envelopes are a question whenever they carry one: the wizard asks,
    rather than the value or the mention landing on whoever happens to share
    the name, or on nobody.
    """

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        from app.schemas.tenant.backup_export import ManifestPerson
        from app.services.import_engine.common import handle_key
        from app.services.import_engine.mentions import mention_handles_in
        from app.services.import_engine.people import user_reference_handles

        payload = validated.model_dump(mode="json")
        handles: dict[str, str] = {}
        for handle in (
            *user_reference_handles(payload),
            *mention_handles_in(payload),
        ):
            handles.setdefault(handle_key(handle), handle)
        return [
            ManifestPerson(handle=handle, name=None, comment_count=0)
            for handle in sorted(handles.values(), key=str.lower)
        ]


def parse_envelope(model: Type[BaseModel], envelope: dict[str, Any]) -> BaseModel:
    """Pydantic-parse + version-gate a raw envelope dict."""
    try:
        validated = model.model_validate(envelope)
    except ValidationError as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE) from exc
    version = getattr(validated, "schema_version", CURRENT_SCHEMA_VERSION)
    if not (MIN_SUPPORTED_IMPORT_VERSION <= version <= CURRENT_SCHEMA_VERSION):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SCHEMA_VERSION_UNSUPPORTED)
    return validated


async def grant_ownership(
    session: AsyncSession,
    *,
    tool: Tool,
    entity_id: int,
    target_initiative: Initiative,
    importer: User,
) -> None:
    """Make the importer the owner of what it just created. Sharing does not
    cross in any envelope — who may read a thing is a fact about the community
    it was written in — so every importer writes this one row and no other.

    Created on the importer's own request, the row is already there: the
    table's owner trigger wrote it. A job's request names nobody, and the row
    is written here.

    The flush is part of it: the sharing has to be in the database before the
    content it governs, and a flush orders its statements by table rather than
    by the order things were added.
    """
    owned = (
        await session.exec(
            select(ResourceGrant.id).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == entity_id,
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).first()
    if owned is not None:
        return
    session.add(
        ResourceGrant(
            resource_type=tool.value,
            resource_id=entity_id,
            user_id=importer.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            initiative_id=target_initiative.id,
        )
    )
    await session.flush()


#: The colour a tag an envelope names by name alone is created in.
_NAMED_TAG_COLOR = "#6b7280"


class TagRestore:
    """Binds the tags an envelope names to the community's own, attaches them
    to the rows one import creates, and counts what that took across all of
    them. Every importer restores tags through it.

    A tag matches the community's of the same name in any case, and is
    created otherwise (``ensure_tag``) — once each, however many rows name it.
    A row gets each tag once, however often or in whatever case its list
    names it.

    One per savepoint: a tag created inside one that rolls back is gone with
    it, so a restore that outlived it would attach a tag that is not there.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        #: Tags made, and matched, once each however many rows name them.
        self.created = 0
        self.matched = 0
        #: Each tag's id by the name it is looked up under.
        self._ids: dict[str, int] = {}

    async def resolve(self, name: str, color: str = _NAMED_TAG_COLOR) -> int:
        """The id of the community's tag named ``name``, made in ``color``
        if there is none."""
        key = name.strip().lower()
        if (known := self._ids.get(key)) is not None:
            return known
        resolved = await ensure_tag(self._session, name=name, color=color)
        if resolved.created:
            self.created += 1
        else:
            self.matched += 1
        self._ids[key] = resolved.id
        return resolved.id

    async def attach(self, row: Any, tags: Iterable[str | ProjectExportTag]) -> None:
        """Tag ``row``, a persisted taggable row, with each of ``tags`` — a
        name, or a name with the colour it is made in."""
        tag_ids: dict[int, None] = {}
        for tag in tags:
            if isinstance(tag, str):
                tag_ids[await self.resolve(tag)] = None
            else:
                tag_ids[await self.resolve(tag.name, tag.color)] = None
        spec = tags_service.spec_for(row)
        self._session.add_all(
            tags_service.tag_edge(spec, row.id, tag_id) for tag_id in tag_ids
        )


def _options_for_value(pv: EnvelopePropertyValue) -> list[dict] | None:
    """Synthesize a minimal option set for a select/multi_select definition
    reconstructed from values alone (the flat by-name encoding carries no
    definition), so the stored value is a valid option on the target side."""
    if pv.property_type == MetadataType.select and pv.value_text:
        return [{"value": pv.value_text, "label": pv.value_text}]
    if pv.property_type == MetadataType.multi_select and isinstance(
        pv.value_json, list
    ):
        return [{"value": v, "label": v} for v in pv.value_json if isinstance(v, str)]
    return None


class PropertyRestore:
    """Binds the properties an envelope carries to the target initiative's
    definitions, writes their values onto the rows one import creates, and
    counts what that took across all of them. Every importer restores
    properties through it.

    A property binds to the target's definition of the same name and type. An
    envelope that declares its definitions (``declare``) has a select's options
    checked as well, and a missing one created whole; one known only from its
    values is created minimally (select options synthesized from the value so
    it stays valid). A name already taken by another type, or by a select with
    other options, goes to ``<name>_<type>`` rather than changing the target's,
    and reuses one already there, so a later import lands on the same one. A
    property unticked on the review is left out with its values. A person
    value is placed through the people step's answer; one that lands on
    nobody is dropped and its handle collected.

    A project's own metadata is made again on the project an import makes
    (``declare`` with ``project_id``), as a copy makes it, and a value of it
    goes onto the one of the same name and type there.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        initiative_id: int,
        context: "ImportContext | None",
        member_handles: dict[str, int] | None = None,
    ) -> None:
        self._session = session
        self._initiative_id = initiative_id
        self._people = context.people if context is not None else None
        self._excluded = (
            context.excluded_properties if context is not None else frozenset()
        )
        #: Read on the first value that needs it, when not handed in.
        self._member_handles = member_handles
        #: Definitions made, and matched, once each however many rows name them.
        self.created = 0
        self.matched = 0
        #: The names a definition was made under in place of its own.
        self.renamed: list[str] = []
        #: Person values placed, by account, with the handle that named them.
        self.named: dict[int, str] = {}
        #: Person values whose handle landed on nobody.
        self.unmatched: set[str] = set()
        #: The target initiative's definitions by name, read once.
        self._existing: dict[str, MetadataDefinition] | None = None
        #: What each envelope property became in the target, so every row
        #: naming it shares one definition — a renamed one included.
        self._resolved: dict[tuple[str, MetadataType], MetadataDefinition] = {}
        #: The project's metadata made, by name and type.
        self._project: dict[tuple[str, MetadataType], int] = {}
        #: The target definitions already standing for one envelope property.
        #: One definition holds one value a row, so no second property may
        #: bind to it — a ``Priority`` renamed onto ``Priority_select`` beside
        #: a ``Priority_select`` of the envelope's own.
        self._bound: set[int] = set()

    async def declare(
        self,
        definitions: list[ProjectExportPropertyDefinition],
        *,
        project_id: int | None = None,
    ) -> None:
        """Bind the definitions an envelope declares, before any value names
        them, so each is matched with its options or created whole; and with
        ``project_id``, make the project's own metadata on it."""
        own = [declared for declared in definitions if declared.project]
        if own and project_id is not None:
            made = await metadata_service.copy_definitions(
                self._session,
                [
                    MetadataDefinition(
                        id=place, **declared.model_dump(exclude={"project"})
                    )
                    for place, declared in enumerate(own, start=1)
                ],
                initiative_id=self._initiative_id,
                project_id=project_id,
            )
            for place, declared in enumerate(own, start=1):
                self._project[(declared.name, declared.type)] = made[place]
        for declared in definitions:
            if not declared.project and declared.name not in self._excluded:
                await self._definition(declared.name, declared.type, declared=declared)

    def bound_id(
        self, name: str, prop_type: MetadataType, *, project: bool = False
    ) -> int | None:
        """The target definition an envelope property became, or None for one
        left out; with ``project``, the project's metadata."""
        if project:
            return self._project.get((name, prop_type))
        found = self._resolved.get((name, prop_type))
        return found.id if found is not None else None

    async def _definition(
        self,
        name: str,
        prop_type: MetadataType,
        *,
        declared: ProjectExportPropertyDefinition | None = None,
        value: EnvelopePropertyValue | None = None,
    ) -> MetadataDefinition:
        """The target's definition for ``name`` and ``prop_type``, matched or
        made once for the whole import."""
        key = (name, prop_type)
        if (known := self._resolved.get(key)) is not None:
            return known
        if self._existing is None:
            self._existing = await load_initiative_properties(
                self._session, initiative_id=self._initiative_id
            )
        currency = (declared.currency if declared is not None else None) or (
            value.currency if value is not None else None
        )
        for candidate in (name, f"{name}_{prop_type.value}"):
            found = self._existing.get(candidate)
            if (
                found is not None
                and found.id not in self._bound
                and found.type == prop_type
                and (
                    declared is None
                    or options_compatible(prop_type, found.options, declared.options)
                )
                # Amounts in one currency are not amounts in another.
                and found.currency == currency
            ):
                self.matched += 1
                self._resolved[key] = found
                self._bound.add(found.id)
                return found
        target_name = name
        if name in self._existing:
            target_name = await unique_property_name(
                self._session,
                initiative_id=self._initiative_id,
                desired_name=f"{name}_{prop_type.value}",
            )
            self.renamed.append(target_name)
        definition = MetadataDefinition(
            initiative_id=self._initiative_id,
            name=target_name,
            type=prop_type,
            position=(
                declared.position if declared is not None else len(self._existing)
            ),
            color=declared.color if declared is not None else None,
            currency=currency,
            options=(
                declared.options
                if declared is not None
                else _options_for_value(value)
                if value is not None
                else None
            ),
        )
        self._session.add(definition)
        await self._session.flush()
        self._existing[target_name] = definition
        self.created += 1
        self._resolved[key] = definition
        self._bound.add(definition.id)
        return definition

    async def attach(self, row: Any, values: list[EnvelopePropertyValue]) -> None:
        """Write ``values`` onto ``row``, a persisted property target."""
        # The review lists the initiative's properties an import would add,
        # so an unticked name leaves a project's metadata of that name alone.
        values = [
            pv for pv in values if pv.project or pv.property_name not in self._excluded
        ]
        if not values:
            return
        if self._member_handles is None:
            self._member_handles = await load_initiative_member_handles(
                self._session, initiative_id=self._initiative_id
            )
        # One value per definition: the last one named wins.
        column_kwargs_by_id: dict[int, dict[str, Any]] = {}
        for pv in values:
            if pv.project:
                property_id = self._project.get((pv.property_name, pv.property_type))
                if property_id is None:
                    continue
            else:
                property_id = (
                    await self._definition(pv.property_name, pv.property_type, value=pv)
                ).id
            column_kwargs = decode_property_value(
                pv, self._member_handles, people=self._people
            )
            if column_kwargs is None:
                if pv.value_handle:
                    self.unmatched.add(pv.value_handle)
                continue
            if column_kwargs.get("value_user_id") is not None and pv.value_handle:
                self.named.setdefault(column_kwargs["value_user_id"], pv.value_handle)
            column_kwargs_by_id[property_id] = column_kwargs  # ty: ignore[invalid-assignment] — persisted row, id is set
        target = link_for(row).target
        self._session.add_all(
            MetadataValue(
                entity_type=target,
                entity_id=row.id,
                property_id=property_id,
                **column_kwargs,
            )
            for property_id, column_kwargs in column_kwargs_by_id.items()
        )

    async def settle(self, tool_row: Any) -> list[str]:
        """Flush what was written, bring everyone the values name into
        ``tool_row`` — the tool row whose sharing governs them — and return
        every handle that placed nobody or could not be let in.

        A collection has no sharing to bring anybody into: who it may name is
        whoever can open a file in it, as when its values are written, so
        anybody else its values name is taken off it."""
        await self._session.flush()
        gone: set[int] = set()
        if self.named:
            link = link_for(tool_row)
            if link.shared:
                gone = await bring_in_named(
                    self._session,
                    link.governing(tool_row, tool_row.initiative_id),
                    initiative_id=self._initiative_id,
                )
            else:
                gone = await named_people.sweep_collections(self._session, [tool_row])
        return sorted(self.unmatched | {self.named[user_id] for user_id in gone})
