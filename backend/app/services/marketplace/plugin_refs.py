"""What one plug-in calls one member, and the community, in one guild.

A plug-in needs a stable name for a member: to store their preferences, to
recognise them across two visits, and to act as them.

That name is a **pairwise pseudonymous identifier** (OpenID Connect Core §8.1):
a value stable for one *sector*, and unrelated to the value any other sector
holds for the same person. Here the sector is **the plug-in in one guild**:
``(guild_id, public_id)``, the guild and the registration's ``public_id``,
which is the identity every wire contract with a plug-in already uses. The
sector is the relying party, as OIDC has it, so the same person is unrelated
values to two plug-ins, and to one plug-in in two guilds.

The sector is not the install. Uninstalling a plug-in keeps what it calls
everyone, and installing it again brings the same values back, so whatever the
plug-in kept for the community still fits. Forgetting is its own act: the guild
erasing the plug-in's data (:func:`drop_plugin_refs`, once the plug-in has
answered the ``erase`` hook), the guild being purged, or a person's account
being erased.

That is the same thing ``services.platform.identity_refs`` provides for every
other sector, so this module is a thin scoping layer over it rather than a
second implementation.

Two things to keep in mind here.

``identity_refs`` is a platform-wide table, so the guild is a **predicate** on
every read rather than the schema the query runs in. ``resolve_plugin_ref``
therefore takes the guild and will not answer without it.

Most of it is reachable only on the system engine, and every function here
that writes on it opens a session of its own;
``resolve_plugin_ref`` takes one, because its caller composes it with a
guild-routed read in the same transaction. The exception is :func:`install_refs`, which an installed plug-in's
own request runs on its routed session: ``guild_<id>_plugin`` may read and mint
references in its own plug-in's sector and nowhere else (``app.db.public_rls``).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts, gucs
from app.db import session as db_session
from app.db.request_context import SystemGuild
from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
)
from app.services.platform import identity_refs

__all__ = [
    "REF_MAX_LENGTH",
    "PluginNameRefused",
    "current_install_id",
    "drop_guild_plugin_refs",
    "drop_plugin_refs",
    "ensure_plugin_entity_ref",
    "ensure_plugin_guild_ref",
    "ensure_plugin_guild_refs",
    "ensure_plugin_ref",
    "existing_plugin_guild_ref",
    "forget_cached_install_refs",
    "forget_guild",
    "guild_for_plugin_ref",
    "install_refs",
    "mint_guard",
    "plugins_with_refs",
    "reissue_plugin_ref",
    "reissue_plugin_refs",
    "resolve_plugin_guild_ref",
    "resolve_plugin_ref",
]

logger = logging.getLogger(__name__)

_PURPOSE = IdentityPurpose.plugin

#: How long a process remembers what an install's plug-in calls somebody, for
#: the install's own requests (:func:`install_refs`). A reference is stable,
#: and one that has been replaced keeps resolving for its grace window.
#:
#: Keyed by the install as well as the plug-in. An erase drops a plug-in's
#: references only once it is uninstalled, when no request of that install is
#: served any more, and a later install is another key: so no process hands
#: out a reference an erase dropped, whatever it remembers. The system-engine
#: lookups (``ensure_*``) have no install to key on and remember nothing.
INSTALL_REF_TTL_SECONDS = 60.0
#: Entries the process keeps before it sheds the expired ones.
_INSTALL_REF_CACHE_LIMIT = 100_000

#: ``(guild, install, entity, row id) -> (reference, expiry)``.
_install_ref_cache: dict[tuple[int, int, str, int], tuple[str, float]] = {}

#: The routed install's sector: its community, and the plug-in its token was
#: issued to (the same predicate as ``public_rls.INSTALL_SECTOR``).
_IN_SECTOR = (
    f"r.purpose = '{_PURPOSE.value}'"
    f" AND r.sector_guild_id = {gucs.GUILD_ID}"
    f" AND r.sector_plugin = {gucs.TOKEN_CLIENT_ID}"
)

#: Mint what the routed install is missing, and return what it holds, in one
#: statement on an install's routed session. The sector is the routing's own;
#: the arrays say only which entities are wanted and the fresh value to use for
#: each one that has none. The second branch reads the live rows as the
#: statement began, so a row is returned once: by the insert when it was
#: minted here, by the read when it already stood.
_MINT_INSTALL_REFS_SQL = f"""
WITH wanted AS (
  SELECT w.entity_type, w.entity_id, w.ref
  FROM unnest(
    CAST(:entity_types AS text[]),
    CAST(:entity_ids AS int[]),
    CAST(:fresh AS text[])
  ) AS w(entity_type, entity_id, ref)
),
minted AS (
  INSERT INTO public.identity_refs
    (ref, entity_type, entity_id, purpose, sector_guild_id, sector_plugin, created_at)
  SELECT w.ref, w.entity_type, w.entity_id, '{_PURPOSE.value}', {gucs.GUILD_ID}, {gucs.TOKEN_CLIENT_ID}, now()
  FROM wanted w
  WHERE {gucs.GUILD_ID} IS NOT NULL AND {gucs.TOKEN_CLIENT_ID} IS NOT NULL
  ON CONFLICT (entity_type, entity_id, purpose, sector_guild_id, sector_plugin)
    WHERE retired_at IS NULL
    DO NOTHING
  RETURNING entity_type, entity_id, ref
)
SELECT m.entity_type, m.entity_id, m.ref, true AS minted FROM minted m
UNION ALL
SELECT r.entity_type, r.entity_id, r.ref, false AS minted
FROM public.identity_refs r
JOIN wanted w ON w.entity_type = r.entity_type AND w.entity_id = r.entity_id
WHERE {_IN_SECTOR} AND r.retired_at IS NULL
"""

#: The live rows for entities the statement above neither minted nor saw: a
#: second request minted them between that statement's start and its insert.
_LIVE_INSTALL_REFS_SQL = f"""
SELECT r.entity_type, r.entity_id, r.ref
FROM public.identity_refs r
JOIN unnest(CAST(:entity_types AS text[]), CAST(:entity_ids AS int[]))
  AS w(entity_type, entity_id)
  ON w.entity_type = r.entity_type AND w.entity_id = r.entity_id
WHERE {_IN_SECTOR} AND r.retired_at IS NULL
"""


def _cache_key(
    guild_id: int, install_id: int, entity: IdentityEntity, entity_id: int
) -> tuple[int, int, str, int]:
    return (guild_id, install_id, entity.value, entity_id)


def _remember(key: tuple[int, int, str, int], ref: str, now: float) -> None:
    if len(_install_ref_cache) >= _INSTALL_REF_CACHE_LIMIT:
        for stale in [k for k, (_, exp) in _install_ref_cache.items() if exp <= now]:
            del _install_ref_cache[stale]
        if len(_install_ref_cache) >= _INSTALL_REF_CACHE_LIMIT:
            _install_ref_cache.clear()
    _install_ref_cache[key] = (ref, now + INSTALL_REF_TTL_SECONDS)


def forget_cached_install_refs() -> None:
    """Empty this process's reference cache."""
    _install_ref_cache.clear()


async def install_refs(
    session: AsyncSession,
    *,
    guild_id: int,
    install_id: int,
    wanted: Iterable[tuple[IdentityEntity, int]],
) -> tuple[dict[tuple[IdentityEntity, int], str], bool]:
    """What the routed install's plug-in calls each of ``wanted``, minting what
    it lacks.

    ``session`` is the install's own request session, routed as
    ``guild_<id>_plugin``, whose token names the plug-in (the sector);
    ``guild_id`` and ``install_id`` are that routing's community and install,
    and key this process's cache. Cached answers cost nothing; everything else
    is one statement. Returns the references and whether any was minted, which
    the caller commits.
    """
    now = time.monotonic()
    found: dict[tuple[IdentityEntity, int], str] = {}
    missing: list[tuple[IdentityEntity, int]] = []
    for entity, entity_id in sorted(set(wanted), key=lambda w: (w[0].value, w[1])):
        cached = _install_ref_cache.get(
            _cache_key(guild_id, install_id, entity, entity_id)
        )
        if cached is not None and cached[1] > now:
            found[(entity, entity_id)] = cached[0]
        else:
            missing.append((entity, entity_id))
    if not missing:
        return found, False

    rows = (
        await session.exec(
            text(_MINT_INSTALL_REFS_SQL).bindparams(
                entity_types=[entity.value for entity, _ in missing],
                entity_ids=[entity_id for _, entity_id in missing],
                fresh=[
                    identity_refs.mint_ref(entity, _PURPOSE) for entity, _ in missing
                ],
            )
        )
    ).all()
    minted = False
    for row in rows:
        found[(IdentityEntity(row.entity_type), int(row.entity_id))] = row.ref
        minted = minted or bool(row.minted)

    raced = [w for w in missing if w not in found]
    if raced:
        for row in (
            await session.exec(
                text(_LIVE_INSTALL_REFS_SQL).bindparams(
                    entity_types=[entity.value for entity, _ in raced],
                    entity_ids=[entity_id for _, entity_id in raced],
                )
            )
        ).all():
            found[(IdentityEntity(row.entity_type), int(row.entity_id))] = row.ref

    now = time.monotonic()
    for entity, entity_id in missing:
        ref = found.get((entity, entity_id))
        if ref is not None:
            _remember(_cache_key(guild_id, install_id, entity, entity_id), ref, now)
    return found, minted


class PluginNameRefused(Exception):
    """A plug-in may not be given a new name in this community: it has no live
    install here, the community's request that it erase its data is not
    finished, or the community is being purged. A name that already exists is
    still answered."""


def mint_guard(guild_id: int, public_id: str) -> Callable[[], Awaitable[None]]:
    """What ``identity_refs.ensure_ref`` runs before it mints a name in
    ``public_id``'s sector in the community: raises :class:`PluginNameRefused`
    unless the community has a live install of the plug-in, no erase of it is
    pending, and no purge of the community has begun. Asked once however many
    names are minted with it, and only when one is."""
    allowed: list[bool] = []

    async def check() -> None:
        if not allowed:
            from app.services.marketplace import community_hooks

            allowed.append(
                await current_install_id(guild_id=guild_id, public_id=public_id)
                is not None
                and not await community_hooks.naming_closed(
                    guild_id=guild_id, public_id=public_id
                )
            )
        if not allowed[0]:
            raise PluginNameRefused(public_id)

    return check


async def ensure_plugin_entity_ref(
    *, guild_id: int, public_id: str, entity: IdentityEntity, entity_id: int
) -> str:
    """What one plug-in calls one entity in one guild, minting it on first use,
    on a system-engine session of its own from the guild's cohort. Read every
    time: an erase that has committed is never answered from memory.

    Raises :class:`PluginNameRefused` instead of minting a name for a plug-in
    the community has no live install of, or is erasing (:func:`mint_guard`),
    so no late call can bring back a name an erase dropped."""
    async with cohorts.system_session(guild_id) as session:
        ref = await identity_refs.ensure_ref(
            session,
            entity_type=entity,
            entity_id=entity_id,
            purpose=_PURPOSE,
            sector_guild_id=guild_id,
            sector_plugin=public_id,
            before_mint=mint_guard(guild_id, public_id),
        )
        await session.commit()
    return ref


async def ensure_plugin_ref(*, guild_id: int, public_id: str, user_id: int) -> str:
    """This member's reference for this plug-in in this guild, minting one on
    first use.

    The table is reachable only on the system engine, and the caller is a
    request handler routed into a guild role, so a miss opens a session of its
    own, like ``identity_refs.billing_refs``.
    """
    return await ensure_plugin_entity_ref(
        guild_id=guild_id,
        public_id=public_id,
        entity=IdentityEntity.user,
        entity_id=user_id,
    )


async def ensure_plugin_guild_ref(*, guild_id: int, public_id: str) -> str:
    """What this plug-in calls the guild it is installed in.

    The guild's own reference in the same sector the member's uses, so a plug-in
    installed in two guilds holds two unrelated values for them — the same
    property the member reference has, applied to the tenant. It is the
    ``community_ref`` every token for the plug-in carries, and survives an
    uninstall and a reinstall.
    """
    return await ensure_plugin_entity_ref(
        guild_id=guild_id,
        public_id=public_id,
        entity=IdentityEntity.guild,
        entity_id=guild_id,
    )


async def existing_plugin_guild_ref(*, guild_id: int, public_id: str) -> str | None:
    """What this plug-in calls the guild, or None when it calls it nothing.

    :func:`ensure_plugin_guild_ref` for a caller that must not mint: telling a
    plug-in to erase what it holds about a community it was never told about
    would hand it a fresh name only to forget it.
    """
    return await identity_refs.existing_ref(
        entity_type=IdentityEntity.guild,
        entity_id=guild_id,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_plugin=public_id,
    )


async def ensure_plugin_guild_refs(
    sectors: Iterable[tuple[int, str]],
) -> dict[tuple[int, str], str]:
    """:func:`ensure_plugin_guild_ref` for several ``(guild_id, public_id)`` at
    once, in one transaction. A sector refused a new name
    (:class:`PluginNameRefused`) is left out of the answer."""
    refs: dict[tuple[int, str], str] = {}
    async with db_session.SystemSessionLocal() as session:
        for guild_id, public_id in sectors:
            try:
                refs[(guild_id, public_id)] = await identity_refs.ensure_ref(
                    session,
                    entity_type=IdentityEntity.guild,
                    entity_id=guild_id,
                    purpose=_PURPOSE,
                    sector_guild_id=guild_id,
                    sector_plugin=public_id,
                    before_mint=mint_guard(guild_id, public_id),
                )
            except PluginNameRefused:
                continue
        await session.commit()
    return refs


async def resolve_plugin_guild_ref(*, ref: str) -> tuple[int, str] | None:
    """Which guild a guild reference names, **and for which plug-in**, or None.

    The inverse of ``ensure_plugin_guild_ref``, for a token that names its guild
    by reference. Opens its own session: the caller at this point holds none.

    Both halves are returned because the sector is the plug-in, so both are part
    of what the reference says: a caller holds it to the plug-in it is talking
    to. It names no install; the guild's install of that plug-in, if it has one
    now, is :func:`current_install_id`'s answer.
    """
    async with db_session.SystemSessionLocal() as session:
        row = await identity_refs.resolve_ref(session, ref=ref)
    if row is None:
        return None
    if row.purpose != _PURPOSE or row.entity_type != IdentityEntity.guild:
        return None
    if row.sector_guild_id != row.entity_id or not row.sector_plugin:
        return None
    return row.entity_id, row.sector_plugin


async def resolve_plugin_ref(
    session: AsyncSession, *, ref: str, guild_id: int
) -> IdentityRef | None:
    """Which member a reference names inside this guild, or None.

    Returns the row rather than the member id so the caller can also check
    which plug-in it was minted for (``sector_plugin``): the guild narrows the
    value to this deployment's copy, and the plug-in is the sector it actually
    belongs to.
    """
    row = await identity_refs.resolve_ref(session, ref=ref)
    if row is None:
        return None
    if (
        row.purpose != _PURPOSE
        or row.entity_type != IdentityEntity.user
        or row.sector_guild_id != guild_id
    ):
        return None
    return row


async def current_install_id(*, guild_id: int, public_id: str) -> int | None:
    """The guild's install of ``public_id`` now, or None when it has none.

    Read in the guild's own schema on a system session from its cohort. One
    guild holds at most one install per listing, and a registration speaks for
    one listing, so there is at most one answer. A guild whose schema cannot be
    read has none.
    """
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.services.marketplace.registration_lookup import load_registrations

    # The registration names the listing an install comes from, a declarative
    # plug-in's included; with none, the pinned definition names its service.
    registration = (await load_registrations()).get(public_id)
    which = (
        GuildPlugin.listing_uid == registration.listing_uid
        if registration is not None and registration.listing_uid
        else GuildPlugin.definition["service"]["public_id"].astext == public_id
    )
    async with cohorts.system_session(guild_id) as session:
        try:
            # The install lives in the guild's own schema, so the read is
            # routed there.
            await db_session.set_rls_context(session, SystemGuild(guild_id))
            found = (
                await session.exec(
                    select(GuildPlugin.id).where(
                        GuildPlugin.plugin_kind == "service", which
                    )
                )
            ).first()
        except SQLAlchemyError:
            logger.warning(
                "plug-in refs: install lookup could not read guild %s", guild_id
            )
            return None
    return None if found is None else int(found)


async def reissue_plugin_ref(
    session: AsyncSession, *, guild_id: int, public_id: str, user_id: int
) -> str:
    """Replace what one plug-in calls one member, and return the new value.

    The old value keeps resolving for the grace window, so a call already in
    flight lands.
    """
    return await identity_refs.reissue_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user_id,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_plugin=public_id,
    )


async def reissue_plugin_refs(
    session: AsyncSession, *, guild_id: int, public_id: str
) -> int:
    """Replace what one plug-in calls every member in one guild. Returns the
    count."""
    return await identity_refs.reissue_all_refs(
        session,
        entity_type=IdentityEntity.user,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_plugin=public_id,
    )


async def guild_for_plugin_ref(*, ref: str, public_id: str) -> int | None:
    """Which guild a reference names, if it is ``public_id``'s own and that
    plug-in is installed there now.

    :func:`resolve_plugin_guild_ref` answers which plug-in a reference belongs to;
    this adds the question a caller naming one of its own references is really
    asking — that it IS one of its own, in a guild that has it. A value minted
    for another plug-in resolves fine and is not an answer to this.
    """
    resolved = await resolve_plugin_guild_ref(ref=ref)
    if resolved is None:
        return None
    guild_id, plugin = resolved
    if plugin != public_id:
        return None
    if await current_install_id(guild_id=guild_id, public_id=public_id) is None:
        return None
    return guild_id


async def plugins_with_refs(*, guild_id: int) -> list[str]:
    """The plug-ins that call anybody anything in one guild, by ``public_id``:
    the ones a purge of the guild tells to erase what they hold."""
    async with cohorts.system_session(guild_id) as session:
        rows = (
            await session.exec(
                select(IdentityRef.sector_plugin)
                .where(
                    IdentityRef.purpose == _PURPOSE,
                    IdentityRef.sector_guild_id == guild_id,
                    IdentityRef.sector_plugin.is_not(None),
                )
                .distinct()
                .order_by(IdentityRef.sector_plugin)
            )
        ).all()
    return [str(row) for row in rows]


async def drop_plugin_refs(*, guild_id: int, public_id: str) -> int:
    """Remove every reference one plug-in holds in one guild. Returns the count.

    The guild erasing the plug-in's data, once the plug-in has answered the
    ``erase`` hook: a later install starts afresh, under new names. Opens its
    own session, like ``ensure_plugin_ref``.
    """
    async with cohorts.system_session(guild_id) as session:
        dropped = await identity_refs.drop_sector_refs(
            session,
            sector_guild_id=guild_id,
            sector_plugin=public_id,
        )
        await session.commit()
    return dropped


async def drop_guild_plugin_refs(*, guild_id: int) -> int:
    """Remove every reference minted in one guild. Returns the count.

    Every purpose, not only this module's, and the guild's own names as well
    as its members': the guild is purged, so nothing it appears in has anything
    left to name — see ``identity_refs.drop_guild_refs``.

    Like :func:`drop_plugin_refs` this opens its own session: guild removal
    reaches this from call sites holding different sessions, one of them
    routed into the guild role being removed.
    """
    async with cohorts.system_session(guild_id) as session:
        dropped = await identity_refs.drop_guild_refs(session, guild_id=guild_id)
        await session.commit()
    return dropped


async def forget_guild(*, guild_id: int) -> None:
    """Drop a removed guild's references, reporting rather than raising.

    Called after the guild row's removal has committed, so there is nothing
    left to roll back and a failure here must not fail the caller. It is logged
    with the guild, and what it leaves behind is reclaimed by
    ``identity_refs.purge_orphaned_sector_refs``. A guild that is only deleted,
    and may come back, keeps them.
    """
    try:
        await drop_guild_plugin_refs(guild_id=guild_id)
    except SQLAlchemyError:
        logger.warning(
            "plug-in refs: references for removed guild %s were not removed; "
            "the orphan sweep will reclaim them",
            guild_id,
        )
