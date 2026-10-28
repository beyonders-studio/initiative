"""Collections: groups of files in an initiative's Files.

A collection has no sharing. Who sees one, and every count and cover it
shows, is what the reader's own file policies let through
(``app.db.initiative_rls.collections_path``), so nothing here filters by
person. A collection is never empty for long: once its last live file leaves,
:func:`settle` takes it to the trash, and restoring one of its files brings it
back.

A collection owns its fields (``property_definitions.collection_id``): it can
start with a ready-made shape's (:func:`apply_shape`) or another collection's
(:func:`copy_shape`), and a file taken out of it leaves its values for them
behind.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.collection_shapes import (
    SHAPE_GROUPS,
    SHAPES,
    CollectionShape,
    ShownField,
)
from app.core.email_i18n import translate
from app.core.tools import KINDS, LIST_LAYOUTS
from app.db import post_commit
from app.db.query import ids_in
from app.db.session import guild_context, install_context, routed_guild_id
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.file import File
from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.schemas.tenant.collection import (
    CollectionShapeEntry,
    CollectionShapeMetadata,
    CollectionShapeGroup,
)
from app.schemas.tenant.property import PropertyDefinitionRead
from app.schemas.tenant.tool_layout import PROPERTY_FIELD_PREFIX
from app.services.tenant import comments as comments_service
from app.services.tenant import named_people
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant import tool_layouts


async def get_collection(
    session: AsyncSession, collection_id: int, *, populate_existing: bool = False
) -> Collection | None:
    """One collection the reader can see, with its initiative."""
    statement = (
        select(Collection)
        .where(Collection.id == collection_id)
        .options(selectinload(Collection.initiative))
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(statement)).one_or_none()


async def readable_file_ids(
    session: AsyncSession, initiative_id: int, file_ids: Iterable[int]
) -> set[int]:
    """Those of ``file_ids`` that are live files of the initiative the reader
    can open."""
    wanted = sorted(set(file_ids))
    if not wanted:
        return set()
    found = await session.exec(
        select(File.id).where(
            ids_in(File.id, wanted), File.initiative_id == initiative_id
        )
    )
    return set(found.all())


async def holds(session: AsyncSession, collection_id: int, file_id: int) -> bool:
    """Whether the collection holds this file, as a live file the reader can
    open."""
    found = await session.exec(
        select(CollectionFile.file_id)
        .join(File, col(File.id) == CollectionFile.file_id)
        .where(
            CollectionFile.collection_id == collection_id,
            CollectionFile.file_id == file_id,
        )
    )
    return found.one_or_none() is not None


async def add_files(
    session: AsyncSession,
    collection: Collection,
    file_ids: Iterable[int],
    *,
    added_by: Optional[int],
) -> list[int]:
    """Put these files in the collection, leaving out any already there, and
    return the ones added. The caller has checked the reader can open them.

    The collection's row is locked first, as :func:`settle` locks it before
    asking whether the collection is empty, so the two take turns. A
    collection found in the trash by then is not there to add to."""
    locked = (
        await session.exec(
            select_including_deleted(Collection.id, Collection.deleted_at)
            .where(Collection.id == collection.id)
            .with_for_update()
        )
    ).first()
    # A collection made in this transaction, with no entries yet, is out of
    # its maker's sight: nobody else can reach it before it commits.
    if locked is not None and locked.deleted_at is not None:
        raise KINDS["collection"].not_found()
    wanted = sorted(set(file_ids))
    present = set(
        (
            await session.exec(
                select(CollectionFile.file_id).where(
                    CollectionFile.collection_id == collection.id,
                    ids_in(CollectionFile.file_id, wanted),
                )
            )
        ).all()
    )
    added = [file_id for file_id in wanted if file_id not in present]
    now = datetime.now(timezone.utc)
    session.add_all(
        CollectionFile(
            collection_id=collection.id,
            file_id=file_id,
            initiative_id=collection.initiative_id,
            added_by=added_by,
            added_at=now,
        )
        for file_id in added
    )
    # The entries first: a collection with none is out of its reader's sight,
    # and so out of reach of the update below.
    await session.flush()
    if added:
        collection.updated_at = now
        session.add(collection)
        await session.flush()
    return added


async def remove_files(
    session: AsyncSession, collection: Collection, file_ids: Iterable[int]
) -> None:
    """Take these files out of the collection. One that is not in it is
    nothing to take out. An emptied collection goes to the trash once the
    removal commits (:func:`settle`)."""
    wanted = sorted(set(file_ids))
    # The collection first: taking out the last file its reader can open puts
    # it out of their sight, and so out of reach of an update after. Its
    # metadata's values on the files go while the files are still in it.
    if collection.cover_file_id in wanted:
        collection.cover_file_id = None
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    await session.flush()
    await metadata_service.drop_collection_values(session, collection.id, wanted)
    await session.exec(
        delete(CollectionFile).where(
            col(CollectionFile.collection_id) == collection.id,
            ids_in(CollectionFile.file_id, wanted),
        )
    )
    settle_after_commit(session, collections=[collection.id])


async def collection_ids_of(
    session: AsyncSession, file_ids: Sequence[int]
) -> dict[int, list[int]]:
    """The live collections the reader can see that each file is in."""
    if not file_ids:
        return {}
    rows = await session.exec(
        select(CollectionFile.file_id, CollectionFile.collection_id)
        .join(Collection, col(Collection.id) == CollectionFile.collection_id)
        .where(ids_in(CollectionFile.file_id, file_ids))
        .order_by(col(CollectionFile.collection_id))
    )
    found: dict[int, list[int]] = {}
    for file_id, collection_id in rows.all():
        found.setdefault(file_id, []).append(collection_id)
    return found


async def added_at_of(
    session: AsyncSession, collection_id: int, file_ids: Sequence[int]
) -> dict[int, datetime]:
    """When each file was added to the collection."""
    if not file_ids:
        return {}
    rows = await session.exec(
        select(CollectionFile.file_id, CollectionFile.added_at).where(
            CollectionFile.collection_id == collection_id,
            ids_in(CollectionFile.file_id, file_ids),
        )
    )
    return dict(rows.all())


def added_from(collection_id: int, until: datetime, *, oldest_first: bool) -> Any:
    """The files added to the collection at or before ``until``, or at or
    after it read oldest first: where a page that starts at a month of the
    collection's timeline begins."""
    added = col(CollectionFile.added_at)
    return col(File.id).in_(
        select(CollectionFile.file_id).where(
            CollectionFile.collection_id == collection_id,
            added >= until if oldest_first else added <= until,
        )
    )


@dataclass(frozen=True)
class Card:
    """What a list shows of a collection beyond its row: how many of its
    files the reader can see, and the one standing for it."""

    file_count: int = 0
    cover: Optional[File] = None


async def cards(session: AsyncSession, rows: Sequence[Collection]) -> dict[int, Card]:
    """Each collection's count and cover, as its reader sees them: the chosen
    cover where they can open it, else the file added most recently."""
    ids = [row.id for row in rows if row.id is not None]
    if not ids:
        return {}
    entries = (
        await session.exec(
            select(CollectionFile.collection_id, CollectionFile.file_id)
            .join(File, col(File.id) == CollectionFile.file_id)
            .where(ids_in(CollectionFile.collection_id, ids))
            .order_by(
                col(CollectionFile.added_at).desc(), col(CollectionFile.file_id).desc()
            )
        )
    ).all()
    by_collection: dict[int, list[int]] = {}
    for collection_id, file_id in entries:
        by_collection.setdefault(collection_id, []).append(file_id)
    chosen: dict[int, int] = {}
    for row in rows:
        seen = by_collection.get(row.id or 0, [])
        if row.cover_file_id in seen:
            chosen[row.id or 0] = row.cover_file_id or 0
        elif seen:
            chosen[row.id or 0] = seen[0]
    covers = {
        file.id: file
        for file in (
            await session.exec(
                select(File)
                .where(ids_in(File.id, sorted(set(chosen.values()))))
                .options(selectinload(File.current_version))
            )
        ).all()
    }
    return {
        collection_id: Card(
            file_count=len(by_collection.get(collection_id, [])),
            cover=covers.get(chosen[collection_id])
            if collection_id in chosen
            else None,
        )
        for collection_id in ids
    }


async def metadata_of(
    session: AsyncSession, collection_ids: Sequence[int]
) -> dict[int, list[MetadataDefinition]]:
    """Each collection's metadata, in order."""
    if not collection_ids:
        return {}
    rows = await session.exec(
        select(MetadataDefinition)
        .where(ids_in(MetadataDefinition.collection_id, collection_ids))
        .order_by(col(MetadataDefinition.position), col(MetadataDefinition.id))
    )
    found: dict[int, list[MetadataDefinition]] = {}
    for row in rows.all():
        found.setdefault(row.collection_id or 0, []).append(row)
    return found


async def annotate(
    session: AsyncSession, rows: Sequence[Collection]
) -> dict[int, Card]:
    """Everything a serialized collection reads beside its row: its tags,
    properties, metadata, comment count, and :func:`cards`."""
    fields = await metadata_of(session, [row.id for row in rows if row.id is not None])
    for row in rows:
        object.__setattr__(
            row,
            "metadata",
            [
                PropertyDefinitionRead.model_validate(f)
                for f in fields.get(row.id or 0, [])
            ],
        )
    await tags_service.annotate_tags(session, rows)
    await metadata_service.annotate_properties(session, rows)
    await comments_service.annotate_comment_counts(
        session, rows, column="collection_id"
    )
    return await cards(session, rows)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def shape_word(key: str, locale: str) -> str:
    """One of the ready-made shapes' words (``collections.shapes.<key>``), in
    ``locale``."""
    return translate(f"collections.shapes.{key}", locale, namespace="files")


def shapes(locale: str) -> list[CollectionShapeGroup]:
    """The ready-made shapes, grouped, in ``locale``."""
    currency = shape_word("currency", locale)
    return [
        CollectionShapeGroup(
            key=group,
            name=shape_word(f"groups.{group}", locale),
            entries=[
                CollectionShapeEntry(
                    key=shape.key,
                    name=shape_word(f"shapes.{shape.key}.name", locale),
                    hint=shape_word(f"shapes.{shape.key}.hint", locale),
                    lists=list(shape.lists),
                    metadata=[
                        CollectionShapeMetadata(
                            name=shape_word(f"fields.{field.key}", locale),
                            type=MetadataType(field.type),
                            display=field.display,
                            currency=(
                                currency
                                if field.type == MetadataType.currency.value
                                else None
                            ),
                        )
                        for field in shape.fields
                    ],
                )
                for shape in SHAPES
                if shape.group == group
            ],
        )
        for group in SHAPE_GROUPS
    ]


def _target(collection: Collection) -> tool_layouts.Target:
    return tool_layouts.Target("collection", collection.id, collection.initiative_id)


async def apply_shape(
    session: AsyncSession,
    collection: Collection,
    shape: CollectionShape,
    *,
    locale: str,
) -> dict[str, MetadataDefinition]:
    """Give a collection made in this transaction a ready-made shape: its
    fields, named in ``locale``, and its lists, each showing what the shape
    has a card or the table show. Its files are in it already, so whoever
    makes it sees it. Answers the fields made, by the shape's key for each."""
    made = [
        MetadataDefinition(
            initiative_id=collection.initiative_id,
            collection_id=collection.id,
            name=shape_word(f"fields.{field.key}", locale),
            type=MetadataType(field.type),
            position=float(position),
            currency=(
                shape_word("currency", locale)
                if field.type == MetadataType.currency.value
                else None
            ),
        )
        for position, field in enumerate(shape.fields, start=1)
    ]
    session.add_all(made)
    await session.flush()
    ids = {field.key: definition.id for field, definition in zip(shape.fields, made)}

    def shown(entry: ShownField) -> str:
        return (
            entry
            if isinstance(entry, str)
            else f"{PROPERTY_FIELD_PREFIX}{ids[entry.key]}"
        )

    displays = {
        f"{PROPERTY_FIELD_PREFIX}{ids[field.key]}": field.display
        for field in shape.fields
        if field.display is not None
    }
    card = {
        "type": "card",
        "children": [
            {"type": "field", "props": {"field": shown(entry)}} for entry in shape.card
        ],
    }
    lists: dict[str, dict[str, Any]] = {}
    for kind in LIST_LAYOUTS["collection"]:
        definition: dict[str, Any] = {"hidden": kind not in shape.lists}
        if kind == "table":
            definition["columns"] = [shown(entry) for entry in shape.columns]
        else:
            definition["card"] = card
        if displays:
            definition["displays"] = displays
        lists[kind] = definition
    await tool_layouts.start(session, _target(collection), lists, shape.lists[0])
    return {field.key: definition for field, definition in zip(shape.fields, made)}


async def copy_shape(
    session: AsyncSession, source: Collection, collection: Collection
) -> None:
    """Give a collection made in this transaction the fields and lists of
    ``source``, none of its values."""
    fields = await metadata_service.copy_definitions(
        session,
        (await metadata_of(session, [source.id or 0])).get(source.id or 0, []),
        initiative_id=collection.initiative_id,
        collection_id=collection.id,
    )
    await tool_layouts.copy_layouts(
        session,
        _target(source),
        _target(collection),
        status_mapping={},
        type_mapping={},
        fields=fields,
    )


# ---------------------------------------------------------------------------
# Emptied and restored
# ---------------------------------------------------------------------------


@dataclass
class _Settle:
    """What one transaction may have emptied and brought back, settled
    together once it commits."""

    guild_id: int
    actor_id: Optional[int]
    collections: set[int] = field(default_factory=set)
    left_files: set[int] = field(default_factory=set)
    restored_files: set[int] = field(default_factory=set)

    def join(self, other: "_Settle") -> None:
        self.collections |= other.collections
        self.left_files |= other.left_files
        self.restored_files |= other.restored_files

    def __call__(self) -> Any:
        return _settle(self)


def settle_after_commit(
    session: AsyncSession,
    *,
    collections: Iterable[int] = (),
    left_files: Iterable[int] = (),
    restored_files: Iterable[int] = (),
) -> None:
    """Settle collections once ``session`` commits (:func:`settle`): these
    collections, the ones these files left or are in when their sharing
    changed, and the ones these restored files are in. Asked of the community as a whole, since whether a collection
    still holds a file is not one reader's answer."""
    guild_id = routed_guild_id(session)
    if guild_id is None:
        return
    context = guild_context(session) or install_context(session)
    step = post_commit.after_commit(
        session,
        _Settle(guild_id, getattr(context, "user_id", None)),
        key=_Settle,
    )
    step.collections |= set(collections)
    step.left_files |= set(left_files)
    step.restored_files |= set(restored_files)


async def _settle(step: _Settle) -> None:
    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.session import set_rls_context

    async with cohorts.system_session(step.guild_id) as system:
        await set_rls_context(system, SystemGuild(step.guild_id))
        await settle(
            system,
            collection_ids=sorted(step.collections),
            file_ids=sorted(step.left_files),
            restored_files=sorted(step.restored_files),
            actor_id=step.actor_id,
        )
        await system.commit()


def _live_entry() -> Any:
    """A collection holding a live file."""
    return (
        select(CollectionFile.collection_id)
        .join(File, col(File.id) == CollectionFile.file_id)
        .where(col(File.deleted_at).is_(None))
    )


async def settle(
    session: AsyncSession,
    *,
    collection_ids: Sequence[int] = (),
    file_ids: Sequence[int] = (),
    restored_files: Sequence[int] = (),
    actor_id: Optional[int],
) -> None:
    """Trash the named collections, and those holding ``file_ids``, that hold
    no live file, and take anybody who can open none of the files of the rest
    off them; bring back the trashed collections a restored file is in that
    held no other. Run on a session that sees the whole community."""
    from app.services.tenant.soft_delete import restore_entity, trash

    candidates = set(collection_ids)
    if file_ids:
        candidates |= set(
            (
                await session.exec(
                    select(CollectionFile.collection_id).where(
                        ids_in(CollectionFile.file_id, file_ids)
                    )
                )
            ).all()
        )
    if candidates:
        # Each row locked before its entries are counted, in id order, as
        # adding to a collection locks its row before writing an entry: an
        # addition either committed before the count, or waits for the trash.
        locked = (
            await session.exec(
                select(Collection)
                .where(ids_in(Collection.id, sorted(candidates)))
                .order_by(col(Collection.id))
                .with_for_update()
            )
        ).all()
        live = set(
            (
                await session.exec(
                    _live_entry().where(
                        ids_in(CollectionFile.collection_id, sorted(candidates))
                    )
                )
            ).all()
        )
        for collection in locked:
            if collection.id not in live:
                await trash(session, collection, deleted_by_user_id=actor_id)
        await named_people.sweep_collections(
            session, [collection for collection in locked if collection.id in live]
        )

    if restored_files:
        holding = select_including_deleted(CollectionFile.collection_id).where(
            ids_in(CollectionFile.file_id, restored_files)
        )
        others = (
            _live_entry()
            .where(~ids_in(CollectionFile.file_id, restored_files))
            .scalar_subquery()
        )
        trashed = (
            await session.exec(
                select_including_deleted(Collection).where(
                    col(Collection.id).in_(holding),
                    col(Collection.deleted_at).is_not(None),
                    col(Collection.id).not_in(others),
                )
            )
        ).all()
        for collection in trashed:
            await restore_entity(session, collection)
