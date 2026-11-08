"""Contacts from a spreadsheet: one contact a row, each column read as the
person importing says it reads.

The file is read twice and kept by neither read: once to say what it holds —
its header, its first rows, and what each column looks like it holds — and
again, sent back with the columns as the person mapped them, to make the
contacts. The headers this tool's own export writes are known in every
language it writes them in, so an export comes back in with nothing to map;
so are a few that address books write (``E-mail 1 - Value``, ``Company``).

Each contact is made as the create route makes one: held to its schema, in a
place the importer may create one, owned by them — or, among the community's
contacts, by the community contacts plug-in's install — and shared as a new
one is. A row that fails is left out and named in the result, and the rest
come in. A person's organization is the organization contact of that name in
the same place, made if there is none, and linked ``part_of`` as the contact
page links one.

A large file is applied by the import worker, as a large envelope is: the
request is staged as it was made, and read again at apply time.
"""

from __future__ import annotations

import asyncio
import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.core.email_i18n import SUPPORTED_EMAIL_LOCALES
from app.core.messages import ImportEngineMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.guild_standing import GuildContext
from app.models.platform.user import User
from app.models.tenant.contact import DETAILS, Contact
from app.models.tenant.data_job import DataJob, DataJobDirection, DataJobStatus
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.initiative import Initiative
from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.schemas.tenant.contact import ContactCreate
from app.schemas.tenant.import_job import (
    MAX_CSV_COLUMNS,
    ContactCsvColumn,
    ContactCsvImportRequest,
    ContactCsvPreview,
)
from app.schemas.tenant.import_job import (
    ContactCsvTarget as Target,
)
from app.schemas.tenant.tag import TagCreate
from app.services.export import values
from app.services.export.i18n import et
from app.services.import_engine import engine as import_engine
from app.services.import_engine import limits as import_limits
from app.services.import_engine.common import (
    handle_key,
    load_initiative_member_handles,
    load_initiative_properties,
)
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
    ImportRowFailure,
    InlineImport,
)
from app.services.import_engine.importers._base import TagRestore, grant_ownership
from app.services.import_engine.mapping import dedupe_names
from app.services.platform.csv_export import restore_cell
from app.services.tenant import contacts as contacts_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import relationships as relationships_service

#: What a spreadsheet import's job is filed under.
SOURCE = "contacts-csv"

#: How many rows the preview shows of the file.
_SAMPLE_ROWS = 3

#: Headers address books write, by what they hold.
_HEADERS: dict[str, Target] = {
    "full name": Target.name,
    "display name": Target.name,
    "organisation": Target.organization,
    "company": Target.organization,
    "company name": Target.organization,
    "organization name": Target.organization,
    "organization 1 - name": Target.organization,
    "labels": Target.tags,
    "email": Target.emails,
    "e-mail": Target.emails,
    "email address": Target.emails,
    "e-mail address": Target.emails,
    "phone": Target.phones,
    "phone number": Target.phones,
    "mobile": Target.phones,
    "mobile phone": Target.phones,
    "telephone": Target.phones,
    "address": Target.addresses,
    "website": Target.websites,
    "web page": Target.websites,
    "url": Target.websites,
}

#: The parts of a name a spreadsheet keeps apart, read together when it holds
#: no whole name.
_NAME_PARTS = frozenset(
    {"first name", "given name", "middle name", "last name", "family name"}
)

#: How the address books that number their details head them:
#: ``E-mail 1 - Value``, ``Phone 2 - Label``, ``Address 1 - Formatted``.
_NUMBERED_KINDS = {
    "e-mail": Target.emails,
    "email": Target.emails,
    "phone": Target.phones,
    "address": Target.addresses,
    "website": Target.websites,
}
_NUMBERED_PARTS = {
    "value": "value",
    "formatted": "value",
    "label": "label",
    "type": "label",
}

#: Where the number goes in a numbered header, and the name in a metadata
#: one, while it is read.
_SLOT = "\0"


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _items(cell: str) -> list[str]:
    """The tags or choices one cell holds: one a line, or apart by Google
    Contacts' `` ::: ``. A comma is part of the item it is in."""
    return [
        item.strip()
        for item in cell.replace(" ::: ", "\n").splitlines()
        if item.strip()
    ]


@cache
def _export_headers() -> tuple[
    dict[str, Target],
    tuple[tuple[str, str, str, str], ...],
    tuple[tuple[str, str], ...],
]:
    """The headers the export writes, in every language it writes them: the
    fixed ones by name, each numbered one as the text either side of its
    number, with the field and the part of it the column holds, and a
    metadata one as the text either side of the metadata's name."""
    fixed: dict[str, Target] = {}
    numbered: list[tuple[str, str, str, str]] = []
    metadata: list[tuple[str, str]] = []
    for locale in sorted(SUPPORTED_EMAIL_LOCALES):
        before, _, after = _norm(et("contacts.metadata", locale, name=_SLOT)).partition(
            _SLOT
        )
        metadata.append((before, after))
        fixed[_norm(et("contacts.name", locale))] = Target.name
        fixed[_norm(et("contacts.type", locale))] = Target.type
        fixed[_norm(et("contacts.partOf", locale))] = Target.organization
        fixed[_norm(values.label("tag_ids", locale))] = Target.tags
        for detail in DETAILS:
            for part, key in (("value", detail), ("label", f"{detail}Label")):
                text = _norm(et(f"contacts.{key}", locale, n=_SLOT))
                before, _, after = text.partition(_SLOT)
                numbered.append((before, after, detail, part))
    return fixed, tuple(numbered), tuple(metadata)


@cache
def _words() -> tuple[dict[str, bool], dict[str, bool]]:
    """What a type cell and a checkbox cell say, in any language the export
    writes them: whether the contact is an organization, and yes or no."""
    kinds = {"person": False, "organization": True, "organisation": True}
    kinds["company"] = True
    answers = {"true": True, "false": False, "1": True, "0": False}
    for locale in SUPPORTED_EMAIL_LOCALES:
        kinds[_norm(et("contacts.person", locale))] = False
        kinds[_norm(et("contacts.organization", locale))] = True
        answers[_norm(values.yes_no(True, locale))] = True
        answers[_norm(values.yes_no(False, locale))] = False
    return kinds, answers


def _reads_as(header: str, properties: dict[str, int]) -> tuple[Target, Any] | None:
    """What a column looks like it holds, by its header: a target, with the
    property it fills, or a detail's ``(number, part)`` where it is numbered,
    or ``"part"`` for one part of a name. ``None`` for a header nothing
    reads. A property the export heads as metadata comes first, then the
    export's own headers, then the address books', then a property by its
    name alone."""
    key = _norm(header)
    fixed, numbered, metadata = _export_headers()
    for before, after in metadata:
        name = key[len(before) : len(key) - len(after)]
        if key.startswith(before) and key.endswith(after) and name in properties:
            return Target.property, properties[name]
    if key in fixed:
        return fixed[key], None
    for before, after, detail, part in numbered:
        number = key[len(before) : len(key) - len(after)]
        if (
            key.startswith(before)
            and key.endswith(after)
            and len(key) > len(before) + len(after)
            and number.isdecimal()
        ):
            return Target(detail), (int(number), part)
    if key in _HEADERS:
        return _HEADERS[key], None
    if key in _NAME_PARTS:
        return Target.name, "part"
    numbered_kind, _, part = key.rpartition(" - ")
    kind, _, number = numbered_kind.rpartition(" ")
    if kind in _NUMBERED_KINDS and number.isdecimal() and part in _NUMBERED_PARTS:
        return _NUMBERED_KINDS[kind], (int(number), _NUMBERED_PARTS[part])
    if key in properties:
        return Target.property, properties[key]
    return None


def read(content: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """The file's header, and each row holding anything with the row a
    spreadsheet shows it on. Each cell reads as it was before the export
    wrote it (``restore_cell``). Separated by commas, or by the semicolons
    or tabs some spreadsheets write instead."""
    text = content.removeprefix("\ufeff")
    first = text.split("\n", 1)[0]
    try:
        records = list(
            csv.reader(io.StringIO(text), delimiter=max(",;\t", key=first.count))
        )
    except csv.Error as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_FILE_UNREADABLE) from exc
    if not records or not any(cell.strip() for cell in records[0]):
        raise ImportEngineError(ImportEngineMessages.IMPORT_FILE_UNREADABLE)
    if len(records[0]) > MAX_CSV_COLUMNS:
        raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
    rows = [
        (number, [restore_cell(cell.strip()) for cell in record])
        for number, record in enumerate(records[1:], start=2)
        if any(cell.strip() for cell in record)
    ]
    return [cell.strip() for cell in records[0]], rows


async def preview(
    session: AsyncSession, content: str, *, initiative_id: int | None
) -> ContactCsvPreview:
    """What the file holds, and the columns it looks like it has: each
    detail's value beside the label numbered with it, and a column headed with
    one of the initiative's properties as that property."""
    headers, rows = read(content)
    properties = (
        {
            _norm(name): definition.id
            for name, definition in (
                await load_initiative_properties(session, initiative_id=initiative_id)
            ).items()
            if definition.id is not None
            and definition.type is not MetadataType.signature
        }
        if initiative_id is not None
        else {}
    )
    reads = [_reads_as(header, properties) for header in headers]
    labels = {
        (read_as[0], read_as[1][0]): index
        for index, read_as in enumerate(reads)
        if read_as is not None
        and isinstance(read_as[1], tuple)
        and read_as[1][1] == "label"
    }
    whole_name = (Target.name, None) in reads
    columns: list[ContactCsvColumn] = []
    for index, read_as in enumerate(reads):
        if read_as is None:
            continue
        target, extra = read_as
        if target is Target.property:
            columns.append(
                ContactCsvColumn(column=index, target=target, property_id=extra)
            )
        elif isinstance(extra, tuple):
            if extra[1] == "value":
                columns.append(
                    ContactCsvColumn(
                        column=index,
                        target=target,
                        label_column=labels.get((target, extra[0])),
                    )
                )
        elif extra != "part" or not whole_name:
            columns.append(ContactCsvColumn(column=index, target=target))
    return ContactCsvPreview(
        headers=headers,
        row_count=len(rows),
        samples=[cells for _, cells in rows[:_SAMPLE_ROWS]],
        columns=columns,
    )


@dataclass
class _Row:
    """One row as a contact's create takes it, and what it names beside."""

    number: int
    contact: dict[str, Any]
    organization: str | None
    tags: list[str]
    properties: dict[int, str]
    #: A field the row fills with something that reads as nothing.
    unreadable: str | None = None


def _row(number: int, cells: list[str], columns: list[ContactCsvColumn]) -> _Row:
    def cell(index: int | None) -> str:
        return cells[index] if index is not None and index < len(cells) else ""

    names: list[str] = []
    details: dict[str, list[dict[str, str]]] = {detail: [] for detail in DETAILS}
    tags: list[str] = []
    properties: dict[int, str] = {}
    kind = organization = None
    for column in columns:
        value = cell(column.column)
        if not value:
            continue
        if column.target is Target.name:
            names.append(value)
        elif column.target is Target.type:
            kind = kind or value
        elif column.target is Target.organization:
            organization = organization or value
        elif column.target is Target.tags:
            tags += _items(value)
        elif column.target is Target.property and column.property_id is not None:
            properties[column.property_id] = value
        elif column.target.value in details:
            details[column.target.value].append(
                {"label": cell(column.label_column), "value": value}
            )
    is_organization = _words()[0].get(_norm(kind)) if kind else False
    return _Row(
        number=number,
        contact={
            "name": " ".join(names),
            "is_organization": bool(is_organization),
            **details,
        },
        organization=organization,
        tags=dedupe_names(tags),
        properties=properties,
        unreadable=Target.type.value if is_organization is None else None,
    )


def _property_value(
    definition: MetadataDefinition, text: str, handles: dict[str, int]
) -> Any:
    """``text`` as a create takes a value of ``definition``: a choice by its
    label or its value, a checkbox by yes or no in any language, a scale as a
    whole number, a person by handle. Anything else is the text, which the
    property's own checks hold to its type."""
    kind = definition.type
    if kind in (MetadataType.select, MetadataType.multi_select):
        options: dict[str, Any] = {}
        for option in definition.options or ():
            options[_norm(str(option.get("value", "")))] = option.get("value")
            options.setdefault(_norm(str(option.get("label", ""))), option.get("value"))
        many = kind is MetadataType.multi_select
        picked = [
            options.get(_norm(part), part.strip())
            for part in (_items(text) if many else [text])
        ]
        return picked if many else picked[0]
    if kind is MetadataType.checkbox:
        return _words()[1].get(_norm(text), text)
    if kind is MetadataType.scale:
        return int(text) if text.isdecimal() else text
    if kind is MetadataType.user_reference:
        return handles.get(handle_key(text), text)
    return text


@dataclass(frozen=True)
class Place:
    """Where a spreadsheet's contacts go: an initiative, or the community's
    contacts held by the plug-in's install; and the initiative's properties
    its columns fill."""

    initiative: Initiative | None
    plugin: GuildPlugin | None
    properties: dict[int, MetadataDefinition] = field(default_factory=dict)


async def place(
    session: AsyncSession,
    *,
    context: GuildContext,
    user: User,
    request: ContactCsvImportRequest,
) -> Place:
    """Where ``request`` puts its contacts, held to what a create there takes:
    in an initiative, its contacts switched on and the create permission; in
    the community's contacts, the ``community_contacts`` surface and the
    plug-in. The columns name a name, each column once, and only properties
    the initiative has."""
    mapped = {c.property_id for c in request.columns if c.target is Target.property}
    initiative: Initiative | None = None
    plugin: GuildPlugin | None = None
    definitions: dict[int, MetadataDefinition] = {}
    if request.initiative_id is None:
        plugin = await contacts_service.community_holder(session, user, context)
    else:
        initiative = await resource_access.prepare_create(
            session, Tool.contact, request.initiative_id, user, context
        )
        definitions = {
            definition.id: definition
            for definition in (
                await load_initiative_properties(session, initiative_id=initiative.id)
            ).values()
            # A column fills a value for nobody's signature.
            if definition.id is not None
            and definition.type is not MetadataType.signature
        }
    if (
        not any(c.target is Target.name for c in request.columns)
        or len({c.column for c in request.columns}) != len(request.columns)
        or not mapped <= set(definitions)
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    return Place(
        initiative,
        plugin,
        {
            property_id: definitions[property_id]
            for property_id in mapped
            if property_id
        },
    )


def rows_of(request: ContactCsvImportRequest) -> list[tuple[int, list[str]]]:
    """The file's rows, once every column ``request`` names is one it has."""
    headers, rows = read(request.content)
    if any(
        c.column >= len(headers)
        or (
            c.label_column is not None
            and (c.label_column >= len(headers) or c.label_column == c.column)
        )
        for c in request.columns
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    return rows


async def start_import(
    session: AsyncSession,
    *,
    context: GuildContext,
    user: User,
    request: ContactCsvImportRequest,
) -> InlineImport | DataJob:
    """Apply a small file in the request; stage a larger one for the worker,
    as a large envelope is, and answer with its job."""
    rows = rows_of(request)
    found = await place(session, context=context, user=user, request=request)
    if len(rows) > import_limits.IMPORT_MAX_ROWS:
        raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
    if len(rows) <= import_limits.IMPORT_INLINE_MAX_ROWS:
        result = await apply(
            session,
            context=context,
            user=user,
            place=found,
            columns=request.columns,
            rows=rows,
        )
        await session.commit()
        return InlineImport(result=result)

    await import_engine.count_active_jobs_locked(session, user=user)
    payload_ref = await asyncio.to_thread(
        import_engine.stage_payload,
        context.guild_id,
        request.model_dump_json().encode("utf-8"),
        suffix="json",
    )
    job = DataJob(
        direction=DataJobDirection.import_,
        created_by=user.id,
        source=SOURCE,
        params={"initiative_id": request.initiative_id},
        file_ref=payload_ref,
        status=DataJobStatus.queued,
        expires_at=datetime.now(UTC)
        + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _make(
    session: AsyncSession,
    *,
    context: GuildContext,
    user: User,
    place: Place,
    contact_in: ContactCreate,
) -> Contact:
    """One contact, as the create route makes it: owned by its maker, or by
    the plug-in's install, and shared as the create says."""
    contact = Contact(
        initiative_id=contact_in.initiative_id,
        created_by=user.id,
        **contact_in.model_dump(include={"name", "is_organization", *DETAILS}),
    )
    session.add(contact)
    await session.flush()
    if place.plugin is not None:
        await ownership_service.give_to_install(
            session,
            Tool.contact,
            contact,
            install_id=place.plugin.id,
            guild_id=context.guild_id,
            grants=contact_in.grants,
            actor_user_id=user.id,
        )
        return contact
    assert place.initiative is not None
    await grant_ownership(
        session,
        tool=Tool.contact,
        entity_id=contact.id,
        target_initiative=place.initiative,
        importer=user,
    )
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        context,
        Tool.contact,
        user=user,
        resource_id=contact.id,
        initiative_id=contact_in.initiative_id,
        payload=contact_in,
        grants=contact_in.grants,
    )
    return contact


async def apply(
    session: AsyncSession,
    *,
    context: GuildContext,
    user: User,
    place: Place,
    columns: list[ContactCsvColumn],
    rows: list[tuple[int, list[str]]],
) -> EnvelopeImportResult:
    """Make a contact of every row that reads as one. Flush-only; the caller
    commits."""
    initiative_id = place.initiative.id if place.initiative is not None else None
    handles = (
        await load_initiative_member_handles(session, initiative_id=initiative_id)
        if initiative_id is not None
        and any(
            d.type is MetadataType.user_reference for d in place.properties.values()
        )
        else {}
    )
    organizations: dict[str, int] = {}
    for existing_id, name in await session.exec(
        select(Contact.id, Contact.name)
        .where(
            col(Contact.is_organization).is_(True),
            col(Contact.initiative_id) == initiative_id
            if initiative_id is not None
            else col(Contact.initiative_id).is_(None),
            col(Contact.deleted_at).is_(None),
            col(Contact.archived_at).is_(None),
        )
        .order_by(col(Contact.id))
    ):
        organizations.setdefault(_norm(name), existing_id)

    failed: list[ImportRowFailure] = []
    created = tags_created = tags_matched = 0
    parsed = [_row(number, cells, columns) for number, cells in rows]
    # Organizations go in first: a person's may be a row further down.
    for row in sorted(parsed, key=lambda r: not r.contact["is_organization"]):
        if row.unreadable is not None:
            failed.append(ImportRowFailure(row=row.number, field=row.unreadable))
            continue
        try:
            contact_in = ContactCreate.model_validate(
                {
                    **row.contact,
                    "initiative_id": initiative_id,
                    "properties": [
                        {
                            "property_id": property_id,
                            "value": _property_value(
                                place.properties[property_id], text, handles
                            ),
                        }
                        for property_id, text in row.properties.items()
                    ],
                }
            )
        except ValidationError as exc:
            loc = exc.errors()[0]["loc"]
            failed.append(
                ImportRowFailure(
                    row=row.number,
                    field=str(loc[0]) if loc else Target.name.value,
                )
            )
            continue
        try:
            tag_names = [TagCreate(name=name).name for name in row.tags]
        except ValidationError:
            failed.append(ImportRowFailure(row=row.number, field=Target.tags.value))
            continue
        # Named as the create names it: a property value is one of its
        # ``properties``.
        blamed = "properties"
        made: int | None = None
        try:
            async with session.begin_nested():
                contact = await _make(
                    session,
                    context=context,
                    user=user,
                    place=place,
                    contact_in=contact_in,
                )
                # Its own restore: what the row's savepoint rolls back goes
                # with it.
                tags = TagRestore(session)
                await tags.attach(contact, tag_names)
                await metadata_service.write_on_create(
                    session, contact, contact_in.properties
                )
                if row.organization and not contact.is_organization:
                    blamed = Target.organization.value
                    org_id = organizations.get(_norm(row.organization))
                    if org_id is None:
                        org = await _make(
                            session,
                            context=context,
                            user=user,
                            place=place,
                            contact_in=ContactCreate(
                                name=row.organization,
                                is_organization=True,
                                initiative_id=initiative_id,
                            ),
                        )
                        org_id = made = org.id
                    await relationships_service.link(
                        session,
                        relationships_service.Link(
                            source=relationships_service.Endpoint(
                                SearchEntityType.contact, contact.id
                            ),
                            relationship_type=RelationshipType.part_of,
                            target=relationships_service.Endpoint(
                                SearchEntityType.contact, org_id
                            ),
                        ),
                        user_id=user.id,
                    )
        except (HTTPException, ValidationError):
            failed.append(ImportRowFailure(row=row.number, field=blamed))
            continue
        created += 1
        tags_created += tags.created
        tags_matched += tags.matched
        if contact.is_organization:
            organizations.setdefault(_norm(contact.name), contact.id)
        if made is not None and row.organization:
            created += 1
            organizations[_norm(row.organization)] = made
    await session.flush()
    return EnvelopeImportResult(
        created={Tool.contact.plural: created, "tags": tags_created},
        matched={"tags": tags_matched},
        failed={Tool.contact.plural: len(failed)} if failed else {},
        failed_rows=sorted(failed, key=lambda failure: failure.row),
    )
