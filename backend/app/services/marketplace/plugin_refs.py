"""What one installed plug-in calls one member.

A plug-in needs a stable name for a member: to store their preferences, to
recognise them across two visits, and to act as them.

That name is a **pairwise pseudonymous identifier** (OpenID Connect Core §8.1):
a value stable for one *sector*, and unrelated to the value any other sector
holds for the same person. Here the sector is the **install**, matching
``connection_ref``'s precedent of being minted per (install, connection,
member) and matching the fact that plug-ins are guild-pinned everywhere else.

That is the same thing ``services.platform.identity_refs`` provides for every
other sector, so this module is a thin scoping layer over it rather than a
second implementation — an install is ``(guild_id, plugin_install_id)``, because
install ids are per-guild-schema and not unique on their own.

Two things to keep in mind here.

``identity_refs`` is a platform-wide table, so the guild is a **predicate** on
every read rather than the schema the query runs in. ``resolve_plugin_ref``
therefore takes the guild and will not answer without it.

Most of it is reachable only on the system engine, and every function here
that writes on it opens a session of its own (the two ``ensure_`` ones only
when this process has not seen the reference in the last minute);
``resolve_plugin_ref`` takes one, because its caller composes it with a
guild-routed read in the same transaction. The exception is :func:`install_refs`, which an installed plug-in's
own request runs on its routed session: ``guild_<id>_plugin`` may read and mint
references in its own install's sector and nowhere else (``app.db.public_rls``).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import gucs
from app.db import cohorts
from app.db import session as db_session
from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
)
from app.services.platform import identity_refs
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.request_context import SystemGuild

__all__ = [
    "REF_MAX_LENGTH",
    "forget_guild",
    "ensure_install_ref",
    "ensure_plugin_guild_ref",
    "ensure_plugin_guild_refs",
    "resolve_plugin_guild_ref",
    "drop_guild_plugin_refs",
    "drop_install_refs",
    "guild_for_plugin_ref",
    "ensure_plugin_ref",
    "install_refs",
    "reissue_plugin_ref",
    "reissue_install_refs",
    "resolve_plugin_ref",
]

logger = logging.getLogger(__name__)

_PURPOSE = IdentityPurpose.plugin

#: How long a process remembers what an install calls somebody. A reference is
#: stable, and one that has been replaced keeps resolving for its grace window.
INSTALL_REF_TTL_SECONDS = 60.0
#: Entries the process keeps before it sheds the expired ones.
_INSTALL_REF_CACHE_LIMIT = 100_000

#: ``(guild, install, entity, row id) -> (reference, expiry)``.
_install_ref_cache: dict[tuple[int, int, str, int], tuple[str, float]] = {}

_IN_SECTOR = (
    f"r.purpose = '{_PURPOSE.value}'"
    f" AND r.sector_guild_id = {gucs.GUILD_ID}"
    f" AND r.sector_id = {gucs.INSTALL_ID}"
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
    (ref, entity_type, entity_id, purpose, sector_guild_id, sector_id, created_at)
  SELECT w.ref, w.entity_type, w.entity_id, '{_PURPOSE.value}', {gucs.GUILD_ID}, {gucs.INSTALL_ID}, now()
  FROM wanted w
  WHERE {gucs.GUILD_ID} IS NOT NULL AND {gucs.INSTALL_ID} IS NOT NULL
  ON CONFLICT (entity_type, entity_id, purpose, sector_guild_id, sector_id)
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


def _forget_install(guild_id: int, install_id: int) -> None:
    """Drop what this process remembers one install calling anybody."""
    for key in [k for k in _install_ref_cache if k[:2] == (guild_id, install_id)]:
        del _install_ref_cache[key]


def forget_cached_install_refs() -> None:
    """Empty this process's install reference cache."""
    _install_ref_cache.clear()


async def install_refs(
    session: AsyncSession,
    *,
    guild_id: int,
    install_id: int,
    wanted: Iterable[tuple[IdentityEntity, int]],
) -> tuple[dict[tuple[IdentityEntity, int], str], bool]:
    """What the routed install calls each of ``wanted``, minting what it lacks.

    ``session`` is the install's own request session, routed as
    ``guild_<id>_plugin``; ``guild_id`` and ``install_id`` are that routing's, and
    key this process's cache. Cached answers cost nothing; everything else is
    one statement. Returns the references and whether any was minted, which
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


async def ensure_install_ref(
    *, guild_id: int, plugin_install_id: int, entity: IdentityEntity, entity_id: int
) -> str:
    """What one install calls one entity, from this process's cache or, on a
    miss, a system-engine session of its own from the guild's cohort."""
    key = _cache_key(guild_id, plugin_install_id, entity, entity_id)
    cached = _install_ref_cache.get(key)
    if cached is not None and cached[1] > time.monotonic():
        return cached[0]
    async with cohorts.system_session(guild_id) as session:
        ref = await identity_refs.ensure_ref(
            session,
            entity_type=entity,
            entity_id=entity_id,
            purpose=_PURPOSE,
            sector_guild_id=guild_id,
            sector_id=plugin_install_id,
        )
        await session.commit()
    _remember(key, ref, time.monotonic())
    return ref


async def ensure_plugin_ref(
    *, guild_id: int, plugin_install_id: int, user_id: int
) -> str:
    """This member's reference at this install, minting one on first use.

    The table is reachable only on the system engine, and the caller is a
    request handler routed into a guild role, so a miss opens a session of its
    own, like ``identity_refs.billing_refs``.
    """
    return await ensure_install_ref(
        guild_id=guild_id,
        plugin_install_id=plugin_install_id,
        entity=IdentityEntity.user,
        entity_id=user_id,
    )


async def ensure_plugin_guild_ref(*, guild_id: int, plugin_install_id: int) -> str:
    """What this install calls the guild it is installed in.

    The guild's own reference at the same sector the member's uses, so a plug-in
    installed in two guilds holds two unrelated values for them — the same
    property the member reference has, applied to the tenant.
    """
    return await ensure_install_ref(
        guild_id=guild_id,
        plugin_install_id=plugin_install_id,
        entity=IdentityEntity.guild,
        entity_id=guild_id,
    )


async def ensure_plugin_guild_refs(
    installs: Iterable[tuple[int, int]],
) -> dict[tuple[int, int], str]:
    """:func:`ensure_plugin_guild_ref` for several ``(guild_id, install_id)`` at
    once, in one transaction."""
    refs: dict[tuple[int, int], str] = {}
    async with db_session.SystemSessionLocal() as session:
        for guild_id, install_id in installs:
            refs[(guild_id, install_id)] = await identity_refs.ensure_ref(
                session,
                entity_type=IdentityEntity.guild,
                entity_id=guild_id,
                purpose=_PURPOSE,
                sector_guild_id=guild_id,
                sector_id=install_id,
            )
        await session.commit()
    return refs


async def resolve_plugin_guild_ref(*, ref: str) -> tuple[int, int] | None:
    """Which guild **and which install** a guild reference names, or None.

    The inverse of ``ensure_plugin_guild_ref``, for a token that names its guild by
    reference. Opens its own session: the caller at this point holds none.

    Both halves are returned because the sector is the install, so both are part
    of what the reference says. A value minted for one install names that
    install and no later one in the same guild — the sector is what makes the
    reference specific, and dropping it would widen it to the guild.
    """
    async with db_session.SystemSessionLocal() as session:
        row = await identity_refs.resolve_ref(session, ref=ref)
    if row is None:
        return None
    if row.purpose != _PURPOSE or row.entity_type != IdentityEntity.guild:
        return None
    if row.sector_guild_id != row.entity_id or row.sector_id is None:
        return None
    return row.entity_id, row.sector_id


async def resolve_plugin_ref(
    session: AsyncSession, *, ref: str, guild_id: int
) -> IdentityRef | None:
    """Which member a reference names inside this guild, or None.

    Returns the row rather than the member id so the caller can also check
    which install it was minted for: the guild narrows the value to this
    deployment's copy, and the install is the sector it actually belongs to.
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


async def reissue_plugin_ref(
    session: AsyncSession, *, guild_id: int, plugin_install_id: int, user_id: int
) -> str:
    """Replace what one install calls one member, and return the new value.

    The old value keeps resolving for the grace window, so a call already in
    flight lands.
    """
    _install_ref_cache.pop(
        _cache_key(guild_id, plugin_install_id, IdentityEntity.user, user_id), None
    )
    return await identity_refs.reissue_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user_id,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_id=plugin_install_id,
    )


async def reissue_install_refs(
    session: AsyncSession, *, guild_id: int, plugin_install_id: int
) -> int:
    """Replace what one install calls every member. Returns the count."""
    _forget_install(guild_id, plugin_install_id)
    return await identity_refs.reissue_all_refs(
        session,
        entity_type=IdentityEntity.user,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_id=plugin_install_id,
    )


async def guild_for_plugin_ref(*, ref: str, public_id: str) -> int | None:
    """Which guild a reference names, if it was minted at ``public_id``'s install.

    :func:`resolve_plugin_guild_ref` answers which install a reference belongs to;
    this adds the question a caller naming one of its own references is really
    asking — that it IS one of its own. A value minted at another plug-in's install
    resolves fine and is not an answer to this.
    """
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import select

    from app.models.tenant.guild_plugin import GuildPlugin

    resolved = await resolve_plugin_guild_ref(ref=ref)
    if resolved is None:
        return None
    guild_id, plugin_install_id = resolved

    async with cohorts.system_session(guild_id) as session:
        try:
            # The install lives in the guild's own schema, so the read is
            # routed there.
            await db_session.set_rls_context(session, SystemGuild(guild_id))
            found = (
                await session.exec(
                    select(GuildPlugin.id).where(
                        GuildPlugin.id == plugin_install_id,
                        GuildPlugin.definition["plugin_kind"].astext == "service",
                        GuildPlugin.definition["service"]["public_id"].astext
                        == public_id,
                    )
                )
            ).first()
        except SQLAlchemyError:
            logger.warning(
                "plug-in refs: install lookup could not read guild %s", guild_id
            )
            return None
    return None if found is None else guild_id


async def drop_install_refs(*, guild_id: int, plugin_install_id: int) -> int:
    """Remove every reference minted for one install. Returns the count.

    Called when the plug-in is uninstalled, from a guild-routed request session —
    so this opens its own, like ``ensure_plugin_ref``. ``sector_id`` is not a
    foreign key (``guild_plugins`` lives in a guild schema and ``identity_refs``
    does not), so this stands in for the cascade the column cannot carry.
    """
    _forget_install(guild_id, plugin_install_id)
    async with cohorts.system_session(guild_id) as session:
        dropped = await identity_refs.drop_sector_refs(
            session,
            sector_guild_id=guild_id,
            sector_id=plugin_install_id,
            purpose=_PURPOSE,
        )
        await session.commit()
    return dropped


async def drop_guild_plugin_refs(*, guild_id: int, keep_billing: bool = False) -> int:
    """Remove every reference minted in one guild. Returns the count.

    Every purpose, not only this module's, and the guild's own names as well
    as its members': the guild is going, so nothing it appears in has anything
    left to name. ``keep_billing`` spares billing's name for the guild — see
    ``identity_refs.drop_guild_refs``.

    Called when the guild is deleted, for the same reason as
    ``drop_install_refs``, and like it opens its own session: guild deletion
    reaches this from three call sites holding three different sessions, one of
    them routed into the guild role being deleted.
    """
    async with cohorts.system_session(guild_id) as session:
        dropped = await identity_refs.drop_guild_refs(
            session, guild_id=guild_id, keep_billing=keep_billing
        )
        await session.commit()
    return dropped


async def forget_guild(*, guild_id: int, keep_billing: bool = False) -> None:
    """Drop a deleted guild's references, reporting rather than raising.

    Called after the deletion has committed, so there is nothing left to roll
    back and a failure here must not fail the request. It is logged with the
    guild, and what it leaves behind is reclaimed by
    ``identity_refs.purge_orphaned_sector_refs``.

    A soft delete passes ``keep_billing``: its plug-ins let go now, and the
    guild's billing reference stays until the purge.
    """
    try:
        await drop_guild_plugin_refs(guild_id=guild_id, keep_billing=keep_billing)
    except SQLAlchemyError:
        logger.warning(
            "plug-in refs: references for deleted guild %s were not removed; "
            "the orphan sweep will reclaim them",
            guild_id,
        )
