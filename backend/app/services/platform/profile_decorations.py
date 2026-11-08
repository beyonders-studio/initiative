"""What one person may dress their profile in.

One function answers it — :func:`owned_decorations` — over two sources: what
ships with the app, which everyone has, and what the account acquired, which is
a row in ``public.user_decorations``. Every caller goes through it, so the
picker offers exactly what the write path accepts.

A pack is an ordinary marketplace listing of kind ``profile_pack``: the ones
that ship with this build differ from a published one only by ``source``, and
what a granted row records is the listing's ``uid`` — the one name that means
this pack on every deployment carrying the catalog.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.profile_decorations import SHIPPED_DECORATIONS
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.user import User
from app.models.platform.user_decoration import UserDecoration
from app.schemas.platform.user import OwnedDecoration, ProfileDecorations
from app.services.marketplace import catalog as catalog_service

#: A ceiling on one read of the shelf. The catalog paginates; this surface does
#: not, because a person's decoration store is not a browsing problem.
_MAX_PACKS = 200


async def _as_the_packs_stand(
    session: AsyncSession, granted: list[UserDecoration]
) -> list[UserDecoration]:
    """The granted rows, re-read against what their packs carry today.

    Returned as unsaved ``UserDecoration`` objects rather than written back: the
    row is the record of a grant and stays as it was, and what a pack contains
    is the catalog's answer, asked each time. A row whose pack this deployment
    no longer offers is kept exactly as it is — losing a decoration because a
    listing was withdrawn is the one thing withdrawal is not supposed to do.
    """
    sources = {row.source for row in granted if row.source}
    if not sources:
        return granted

    fresh: list[UserDecoration] = []
    seen: set[str] = set()
    for source in sorted(sources):
        pack = await pack_by_uid(session, source)
        rows = [row for row in granted if row.source == source]
        if pack is None:
            fresh.extend(row for row in rows if row.decoration_id not in seen)
            seen.update(row.decoration_id for row in rows)
            continue
        first = rows[0]
        for decoration_id, kind in sorted(pack.decorations.items()):
            if decoration_id in seen or decoration_id in SHIPPED_DECORATIONS:
                continue
            seen.add(decoration_id)
            fresh.append(
                UserDecoration(
                    user_id=first.user_id,
                    decoration_id=decoration_id,
                    kind=kind,
                    source=source,
                    acquired_at=first.acquired_at,
                )
            )
    # A row with no pack behind it at all — hand-granted, or from a listing this
    # build has never seen — is still the account's.
    fresh.extend(
        row for row in granted if not row.source and row.decoration_id not in seen
    )
    return fresh


async def _granted_names(
    session: AsyncSession, sources: set[str]
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """``decoration id -> its name``, ``decoration id -> its pack's name``, and
    ``decoration id -> the picture its pack carries for it``.

    A pack from outside this build has no translation here, so the name its
    publisher wrote is the only one there is. One lookup for the packs an
    account holds, rather than one per decoration.
    """
    if not sources:
        return {}, {}, {}
    listings = [
        listing
        for listing in [
            await catalog_service.get_listing_by_uid(session, uid) for uid in sources
        ]
        if listing is not None and listing.kind == "profile_pack"
    ]
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    names: dict[str, str] = {}
    packs: dict[str, str] = {}
    for listing in listings:
        version = versions.get(listing.latest_version_id)
        definition = (version.definition if version is not None else None) or {}
        for entry in definition.get("decorations", []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("name"):
                names[str(entry["id"])] = str(entry["name"])
                packs[str(entry["id"])] = listing.name
    return names, packs, _decoration_images(versions.values())


async def owned_decorations(
    session: AsyncSession, user_id: int
) -> list[OwnedDecoration]:
    """Everything this account may wear, shipped first and then acquired.

    Shipped decorations carry no ``source``: nobody granted them, they came
    with the app, and their names are translated in the client. An acquired one
    carries the uid of the pack that granted it and the name that pack gave it.

    An acquired row naming an id that also ships is dropped rather than listed
    twice — you cannot own a thing twice, and a pack that includes a default
    should not make the picker stutter.
    """
    owned = [
        OwnedDecoration(id=decoration_id, kind=kind, name=None, source=None)
        for decoration_id, kind in SHIPPED_DECORATIONS.items()
    ]
    rows = (
        await session.exec(
            select(UserDecoration)
            .where(UserDecoration.user_id == user_id)
            .order_by(
                UserDecoration.acquired_at.asc(), UserDecoration.decoration_id.asc()
            )
        )
    ).all()
    granted = [row for row in rows if row.decoration_id not in SHIPPED_DECORATIONS]
    # A pack that gains a piece gives it to everybody who has the pack. The rows
    # record *which packs* an account took, and the pack itself says what that
    # means now — so a piece added in a later version is in the library on the
    # next read rather than only for whoever installs it after today.
    granted = await _as_the_packs_stand(session, granted)
    names, packs, images = await _granted_names(
        session, {row.source for row in granted if row.source}
    )
    # By theme, alphabetically, then by what the pack called the piece: a
    # library is browsed rather than read in the order it was acquired, and
    # once there are a dozen packs in it the acquisition order is nobody's
    # order at all. What ships with the app leads, because it is always there.
    granted.sort(
        key=lambda row: (
            packs.get(row.decoration_id, "").casefold(),
            names.get(row.decoration_id, row.decoration_id).casefold(),
            row.decoration_id,
        )
    )
    owned.extend(
        OwnedDecoration(
            id=row.decoration_id,
            kind=row.kind,
            name=names.get(row.decoration_id),
            source=row.source,
            image_url=images.get(row.decoration_id),
        )
        for row in granted
    )
    return owned


async def owned_kinds(session: AsyncSession, user_id: int) -> dict[str, str]:
    """``id -> slot`` for everything this account may wear.

    The shape the write path checks against: an id has to be here, and it has
    to be here as the slot it is being put in.
    """
    return {item.id: item.kind for item in await owned_decorations(session, user_id)}


def unwearable(wanted: Iterable[tuple[str, str]], owned: dict[str, str]) -> list[str]:
    """Which of these ``(id, slot)`` pairs this library does not answer for.

    Both failures land here: an id the account does not have, and one it has
    in a different slot — a trophy cannot be worn as a frame.
    """
    return [
        decoration_id
        for decoration_id, kind in wanted
        if owned.get(decoration_id) != kind
    ]


@dataclass(frozen=True)
class Pack:
    """A profile pack, as the install path needs it.

    A listing plus the decorations its published version grants. The listing is
    the identity — ``uid`` is what a granted row records, because it is the one
    name for this pack on every deployment that carries the catalog.
    """

    listing: MarketplaceListing
    decorations: dict[str, str]
    #: ``id -> picture`` for the decorations whose art the pack carries.
    images: dict[str, str] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return self.listing.uid


def _decoration_images(versions: Iterable) -> dict[str, str]:
    """``id -> picture`` for every decoration these versions carry art for."""
    images: dict[str, str] = {}
    for version in versions:
        definition = (version.definition if version is not None else None) or {}
        for entry in definition.get("decorations", []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("image"):
                images.setdefault(str(entry["id"]), str(entry["image"]))
    return images


def _decorations_of(version) -> dict[str, str]:
    """``id -> slot`` from a published version's definition."""
    definition = (version.definition if version is not None else None) or {}
    return {
        str(entry["id"]): str(entry["slot"])
        for entry in definition.get("decorations", [])
        if isinstance(entry, dict) and "id" in entry and "slot" in entry
    }


async def available_packs(session: AsyncSession) -> list[Pack]:
    """Every profile pack this deployment offers, with what each one grants.

    Read from the catalog rather than a list in this repository: a pack is an
    ordinary listing, and the ones that ship with the build differ from a
    published one only by ``source``.
    """
    listings, _total = await catalog_service.list_listings(
        session, kind="profile_pack", page_size=_MAX_PACKS
    )
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    packs = []
    for listing in listings:
        version = versions.get(listing.latest_version_id)
        decorations = _decorations_of(version)
        # A listing whose published version grants nothing is not offered:
        # there would be nothing to take.
        if decorations:
            packs.append(
                Pack(
                    listing=listing,
                    decorations=decorations,
                    images=_decoration_images([version]),
                )
            )
    return packs


async def pack_by_uid(session: AsyncSession, uid: str) -> Pack | None:
    """One pack, by the uid a granted row records."""
    listing = await catalog_service.get_listing_by_uid(session, uid)
    if listing is None or listing.kind != "profile_pack" or not listing.available:
        return None
    version = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    decorations = _decorations_of(version)
    if not decorations:
        return None
    return Pack(
        listing=listing,
        decorations=decorations,
        images=_decoration_images([version]),
    )


async def installed_pack_ids(session: AsyncSession, user_id: int) -> set[str]:
    """Which packs this account has, by listing uid. A pack is installed when
    its rows are there, so nothing else records it."""
    sources = (
        await session.exec(
            select(UserDecoration.source).where(
                UserDecoration.user_id == user_id,
                UserDecoration.source.is_not(None),
            )
        )
    ).all()
    return {source for source in sources if source}


async def install_pack(session: AsyncSession, *, user_id: int, pack: Pack) -> list[str]:
    """Put a pack's decorations in this account's library.

    One statement, and it is the insert: reading first and then inserting what
    was missing is two steps that two requests can interleave, and both would
    conclude the same row was missing. ``ON CONFLICT DO NOTHING`` lets the
    primary key settle it instead, so a double click is idempotent rather than
    a race.

    Returns the ids this library already holds **from a different pack**. A
    decoration id names one thing — the profile stores the bare id and artwork
    is resolved from it — so two packs claiming the same id claim the same
    thing, and a row can only be attributed to one of them. The caller reports
    that rather than the insert quietly doing nothing while the install says it
    worked.

    Runs on the system engine — the request path reads its library and never
    writes it.
    """
    now = datetime.now(UTC)
    await session.exec(
        pg_insert(UserDecoration)
        .values(
            [
                {
                    "user_id": user_id,
                    "decoration_id": decoration_id,
                    "kind": kind,
                    "source": pack.uid,
                    "acquired_at": now,
                }
                for decoration_id, kind in pack.decorations.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "decoration_id"])
    )
    held = (
        await session.exec(
            select(UserDecoration.decoration_id, UserDecoration.source).where(
                UserDecoration.user_id == user_id,
                UserDecoration.decoration_id.in_(list(pack.decorations)),
            )
        )
    ).all()
    return sorted(decoration_id for decoration_id, source in held if source != pack.uid)


async def remove_pack(
    session: AsyncSession,
    *,
    user_id: int,
    pack: Pack,
) -> ProfileDecorations:
    """Take a pack out of a library, and off the profile, in one transaction.

    Both halves or neither. A library emptied without the profile being
    undressed leaves the account wearing what it does not have, which the
    write path would refuse on the next unrelated edit — so the two are one
    statement pair the caller commits once, rather than two commits with a
    window between them.

    What is being worn is read **here, under a row lock**, not passed in.
    Undressing is a read-modify-write of one JSONB value, so the read and the
    write belong to the same transaction: the lock makes concurrent writers of
    that column take turns, and an edit either lands first and is read, or
    waits and is applied to the stripped value.

    The delete is scoped to rows this pack granted: a decoration that arrived
    from somewhere else and happens to share an id is not this pack's to
    remove. What is taken off the profile is narrower still — only what the
    library no longer answers for once those rows are gone. Returns what the
    profile is left wearing.
    """
    worn_raw = (
        await session.exec(
            select(User.profile_decorations).where(User.id == user_id).with_for_update()
        )
    ).first()
    worn = ProfileDecorations.model_validate(worn_raw or {})

    # What this pack gave *this* library, which is not the same as what its
    # current version grants: a pack that has published since may no longer
    # list something the account was given and is still wearing. The rows are
    # the record of what was granted, so they decide both what is deleted and
    # what comes off.
    granted = set(
        (
            await session.exec(
                select(UserDecoration.decoration_id).where(
                    UserDecoration.user_id == user_id,
                    UserDecoration.source == pack.uid,
                )
            )
        ).all()
    )
    await session.exec(
        delete(UserDecoration).where(
            UserDecoration.user_id == user_id,
            UserDecoration.source == pack.uid,
        )
    )
    # What comes off is what the account no longer owns, which is not the same
    # as what this pack granted: a decoration another pack also gave, or one
    # that ships with the app, is still wearable and would be a look nobody
    # gave up. Read after the delete, so it is the library as it now stands.
    remaining = set(
        (
            await session.exec(
                select(UserDecoration.decoration_id).where(
                    UserDecoration.user_id == user_id
                )
            )
        ).all()
    )
    stripped = undress(
        worn,
        {
            decoration_id
            for decoration_id in granted
            if decoration_id not in remaining
            and decoration_id not in SHIPPED_DECORATIONS
        },
    )
    if stripped != worn:
        await session.exec(
            update(User)
            .where(User.id == user_id)
            .values(
                profile_decorations=stripped.model_dump(),
                updated_at=datetime.now(UTC),
            )
        )
    return stripped


def undress(worn: ProfileDecorations, gone: set[str]) -> ProfileDecorations:
    """The same look with anything in ``gone`` taken off.

    Takes ids rather than a pack, because what has to come off is what the
    account no longer holds — a question about the whole library, not about
    one pack's current definition, which answers it wrongly for anybody who
    installed an earlier version of it.

    A slot that held one of them is left empty, which is the default a bare
    profile has always had: no banner behind the name, no frame around the
    picture. A badge simply leaves the row.
    """
    return ProfileDecorations(
        banner=None if worn.banner in gone else worn.banner,
        frame=None if worn.frame in gone else worn.frame,
        trophies=[trophy for trophy in worn.trophies if trophy not in gone],
    )
