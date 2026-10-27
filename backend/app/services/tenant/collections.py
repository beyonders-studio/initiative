"""Collections: groups of files in an initiative's Files.

A collection has no sharing. Who sees one, and every count and cover it
shows, is what the reader's own file policies let through
(``app.db.initiative_rls.collections_path``), so nothing here filters by
person. A collection is never empty for long: once its last live file leaves,
:func:`settle` takes it to the trash, and restoring one of its files brings it
back.
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

from app.db import post_commit
from app.db.query import ids_in
from app.db.session import guild_context, install_context, routed_guild_id
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.file import File
from app.services.tenant import comments as comments_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service


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
    return the ones added. The caller has checked the reader can open them."""
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
    await session.exec(
        delete(CollectionFile).where(
            col(CollectionFile.collection_id) == collection.id,
            ids_in(CollectionFile.file_id, wanted),
        )
    )
    if collection.cover_file_id in wanted:
        collection.cover_file_id = None
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    await session.flush()
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


async def collection_names_of(
    session: AsyncSession, file_ids: Sequence[int]
) -> dict[int, list[str]]:
    """The names of the live collections the reader can see that each file
    is in, as an export carries them."""
    if not file_ids:
        return {}
    rows = await session.exec(
        select(CollectionFile.file_id, Collection.name)
        .join(Collection, col(Collection.id) == CollectionFile.collection_id)
        .where(ids_in(CollectionFile.file_id, file_ids))
        .order_by(col(Collection.name))
    )
    found: dict[int, list[str]] = {}
    for file_id, name in rows.all():
        found.setdefault(file_id, []).append(name)
    return found


async def gather(
    session: AsyncSession,
    made: dict[tuple[int, str], Collection],
    *,
    file_id: int,
    names: Iterable[str],
    initiative_id: int,
    user_id: Optional[int],
) -> None:
    """Put a file an import made in the collections it was in, by name: one
    collection per name per initiative per import, made the first time a
    name is met (``made`` is the import's own record of them)."""
    for name in dict.fromkeys(names):
        collection = made.get((initiative_id, name))
        if collection is None:
            collection = Collection(
                initiative_id=initiative_id, name=name, created_by=user_id
            )
            session.add(collection)
            await session.flush()
            made[(initiative_id, name)] = collection
        await add_files(session, collection, [file_id], added_by=user_id)


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


async def annotate(
    session: AsyncSession, rows: Sequence[Collection]
) -> dict[int, Card]:
    """Everything a serialized collection reads beside its row: its tags,
    properties, comment count, and :func:`cards`."""
    await tags_service.annotate_tags(session, rows)
    await properties_service.annotate_properties(session, rows)
    await comments_service.annotate_comment_counts(
        session, rows, column="collection_id"
    )
    return await cards(session, rows)


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
    collections, the ones these files left, and the ones these restored files
    are in. Asked of the community as a whole, since whether a collection
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
    no live file; bring back the trashed collections a restored file is in
    that held no other. Run on a session that sees the whole community."""
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
        live = set((await session.exec(_live_entry())).all()) & candidates
        emptied = (
            await session.exec(
                select(Collection).where(
                    ids_in(Collection.id, sorted(candidates - live))
                )
            )
        ).all()
        for collection in emptied:
            await trash(session, collection, deleted_by_user_id=actor_id)

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
