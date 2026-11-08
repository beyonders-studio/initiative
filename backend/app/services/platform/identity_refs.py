"""Minting and resolving the references outside parties know entities by.

The table is ``public.identity_refs`` and every function here expects a session
on the **system engine** (``SystemSessionDep``): these mint and remove, which is
where that stays. The request path reads one sector of its own, in
``services.auth.subject``.

Forward (entity -> reference) is ``ensure_ref``, which mints on first use, so a
new purpose needs no migration and no backfill: every existing user and guild
acquires a reference for it the first time one is asked for. Reverse (reference
-> entity) is ``resolve_ref``, an indexed lookup.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import Unattributed
from app.models.platform.guild import Guild, GuildInvite
from app.models.platform.identity_ref import (
    REF_ENTROPY_BYTES,
    REF_GRACE_PERIOD,
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
    ref_prefix,
)
from app.models.platform.user import User, UserStatus

__all__ = [
    "IDENTITY_REF_SWEEP_POLL_SECONDS",
    "REF_GRACE_PERIOD",
    "billing_ref",
    "billing_refs",
    "drop_entity_refs",
    "drop_guild_refs",
    "drop_sector_refs",
    "ensure_ref",
    "existing_ref",
    "forget_user",
    "mint_ref",
    "process_identity_ref_sweep",
    "purge_orphaned_entity_refs",
    "purge_orphaned_sector_refs",
    "purge_retired_refs",
    "reissue_all_refs",
    "reissue_ref",
    "resolve_billing_ref",
    "resolve_billing_refs",
    "resolve_ref",
    "resolve_refs",
    "sweep_identity_refs",
]

logger = logging.getLogger(__name__)

IDENTITY_REF_SWEEP_POLL_SECONDS = 3600


def mint_ref(entity_type: IdentityEntity, purpose: IdentityPurpose) -> str:
    """A fresh reference. Random, and unrelated to the row it will name."""
    return (
        f"{ref_prefix(entity_type, purpose)}_{secrets.token_urlsafe(REF_ENTROPY_BYTES)}"
    )


async def ensure_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_plugin: str | None = None,
    before_mint: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """This entity's live reference for this sector, minting one on first use.

    ``before_mint`` runs only when there is none to return, before one is
    minted, and refuses the mint by raising.

    Idempotent under concurrency: two callers racing the same first mint both
    insert, one loses on the partial unique index, and both read back the same
    row.
    """
    sector = (sector_guild_id, sector_plugin)
    existing = await _live_ref(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        sector=sector,
    )
    if existing is not None:
        return existing.ref
    if before_mint is not None:
        await before_mint()

    await session.exec(
        pg_insert(IdentityRef.__table__)
        .values(
            ref=mint_ref(entity_type, purpose),
            entity_type=entity_type.value,
            entity_id=entity_id,
            purpose=purpose.value,
            sector_guild_id=sector_guild_id,
            sector_plugin=sector_plugin,
            created_at=datetime.now(UTC),
        )
        # A core-level insert, so the model's default factories do not run and
        # the conflict target must name the partial index's columns and
        # predicate.
        .on_conflict_do_nothing(
            index_elements=[
                "entity_type",
                "entity_id",
                "purpose",
                "sector_guild_id",
                "sector_plugin",
            ],
            index_where=IdentityRef.retired_at.is_(None),
        )
    )

    # Read back rather than returning what was offered: on a lost race the
    # stored value is the winner's, and that is the one the caller must use.
    stored = await _live_ref(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        sector=sector,
    )
    if stored is None:  # pragma: no cover - the insert either landed or lost
        raise RuntimeError("identity ref was neither inserted nor found")
    return stored.ref


async def billing_ref(entity_type: IdentityEntity, entity_id: int) -> str:
    """The reference billing knows one user or guild by, minting on first use.

    For the paths that name one entity to billing: the membership nudge, and
    the people a handoff names besides the one presenting it — the approver of
    a support visit. A system-engine session of its own, as ``billing_refs``.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        ref = await ensure_ref(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            purpose=IdentityPurpose.billing,
        )
        await session.commit()
    return ref


async def existing_ref(
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_plugin: str | None = None,
) -> str | None:
    """This entity's live reference for one sector, or None if it has none.

    :func:`ensure_ref` for a caller that must not mint. Reporting which entity
    a sector already names is one thing; letting a party outside that sector
    create a row in it is another, and a reference that does not exist is an
    answer rather than a gap to fill.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        row = await _live_ref(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            purpose=purpose,
            sector=(sector_guild_id, sector_plugin),
        )
    return None if row is None else row.ref


async def billing_refs(*, user_id: int, guild_id: int) -> tuple[str, str]:
    """The references billing knows one user and one guild by.

    Opens a system-engine session of its own: the table is reachable only
    there (``app.db.system_grants``), while the callers are request handlers
    routed to other roles and one background task holding no session at all.
    The same pattern ``services.platform.user_tokens`` uses for its sweep.
    """
    from app.db.session import SystemSessionLocal

    purpose = IdentityPurpose.billing
    async with SystemSessionLocal() as session:
        user_ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=purpose,
        )
        guild_ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=purpose,
        )
        await session.commit()
    return user_ref, guild_ref


async def resolve_billing_ref(ref: str, entity_type: IdentityEntity) -> int | None:
    """Which user or guild one billing reference names, or None.

    The inverse of ``billing_refs``, for the endpoints billing calls: it names
    a guild, or the person a notice is for, by the reference it was given, and
    this is where that becomes the row id everything inside works on. Opens a
    system-engine session of its own for the same reason ``billing_refs`` does
    — the callers are request handlers routed to other roles.

    Narrower than ``resolve_ref``: a reference minted for the other kind of
    entity, or for another purpose, is not an answer to this question.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        row = await resolve_ref(session, ref=ref)
    if (
        row is None
        or row.entity_type != entity_type
        or row.purpose != IdentityPurpose.billing
    ):
        return None
    return row.entity_id


async def resolve_billing_refs(
    refs: Sequence[str], entity_type: IdentityEntity
) -> dict[str, int]:
    """Which user or guild each of many billing references names, in one read:
    :func:`resolve_billing_ref` for a batch. A reference that names nothing of
    that kind is left out."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        rows = await resolve_refs(session, refs=refs)
    return {
        row.ref: row.entity_id
        for row in rows
        if row.entity_type == entity_type and row.purpose == IdentityPurpose.billing
    }


async def resolve_ref(
    session: AsyncSession, *, ref: str, now: datetime | None = None
) -> IdentityRef | None:
    """Which entity a reference names, or None.

    A retired reference still resolves until its grace window closes; past
    that it is treated as unknown even while the row waits to be swept.
    """
    found = await resolve_refs(session, refs=[ref], now=now)
    return found[0] if found else None


async def resolve_refs(
    session: AsyncSession, *, refs: Sequence[str], now: datetime | None = None
) -> list[IdentityRef]:
    """The rows ``refs`` name, in one read, as :func:`resolve_ref` resolves
    each. A value that names nothing is left out."""
    wanted = [ref for ref in refs if ref and len(ref) <= REF_MAX_LENGTH]
    if not wanted:
        return []
    moment = now or datetime.now(UTC)
    return list(
        (
            await session.exec(
                select(IdentityRef).where(
                    IdentityRef.ref.in_(wanted),
                    or_(
                        IdentityRef.retired_at.is_(None),
                        IdentityRef.retired_at > moment - REF_GRACE_PERIOD,
                    ),
                )
            )
        ).all()
    )


#: ``(sector_guild_id, sector_plugin)``: the guild a sector belongs to, and the
#: plug-in in it that the sector is. Both unset for a platform-wide purpose.
Sector = tuple[int | None, str | None]


def _sector_clause(sector: Sector):
    """Match one sector, treating an unset one as a value rather than unknown."""
    guild_id, plugin = sector
    return and_(
        IdentityRef.sector_guild_id.is_(None)
        if guild_id is None
        else IdentityRef.sector_guild_id == guild_id,
        IdentityRef.sector_plugin.is_(None)
        if plugin is None
        else IdentityRef.sector_plugin == plugin,
    )


async def reissue_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_plugin: str | None = None,
    now: datetime | None = None,
) -> str:
    """Replace one entity's reference for one sector, and return the new one.

    The old value keeps resolving for ``REF_GRACE_PERIOD``. Nothing else about
    the entity moves, and no other entity is touched.
    """
    moment = now or datetime.now(UTC)
    sector = (sector_guild_id, sector_plugin)
    await session.exec(
        update(IdentityRef)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.entity_id == entity_id,
            IdentityRef.purpose == purpose,
            IdentityRef.retired_at.is_(None),
            _sector_clause(sector),
        )
        .values(retired_at=moment)
    )
    return await ensure_ref(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        sector_guild_id=sector_guild_id,
        sector_plugin=sector_plugin,
    )


async def reissue_all_refs(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_plugin: str | None = None,
    now: datetime | None = None,
) -> int:
    """Replace every entity's reference for one sector. Returns the count.

    The coarse lever, for references that have to move together rather than one
    holder at a time. Resumable: retiring and re-minting are separate steps, so
    a run interrupted between them is completed by the next one — an entity left
    with no live reference gets a fresh one, and an entity already re-minted is
    skipped.
    """
    moment = now or datetime.now(UTC)
    sector = (sector_guild_id, sector_plugin)
    retired = await session.exec(
        update(IdentityRef)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.purpose == purpose,
            IdentityRef.retired_at.is_(None),
            _sector_clause(sector),
        )
        .values(retired_at=moment)
        .returning(IdentityRef.entity_id)
    )
    entity_ids = {row for row in retired.scalars().all()}

    # Entities whose retirement landed on a previous, interrupted run.
    stranded = await session.exec(
        select(IdentityRef.entity_id)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.purpose == purpose,
            _sector_clause(sector),
        )
        .group_by(IdentityRef.entity_id)
        .having(func.count().filter(IdentityRef.retired_at.is_(None)) == 0)
    )
    entity_ids.update(stranded.all())

    for entity_id in sorted(entity_ids):
        await ensure_ref(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            purpose=purpose,
            sector_guild_id=sector_guild_id,
            sector_plugin=sector_plugin,
        )
    return len(entity_ids)


async def drop_entity_refs(
    session: AsyncSession, *, entity_type: IdentityEntity, entity_id: int
) -> int:
    """Remove every reference to one entity. Returns the count.

    Called when the row is erased, so that what the outside parties hold stops
    resolving to anybody.
    """
    result = await session.exec(
        delete(IdentityRef).where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.entity_id == entity_id,
        )
    )
    return result.rowcount or 0


async def drop_sector_refs(
    session: AsyncSession,
    *,
    sector_guild_id: int,
    sector_plugin: str | None = None,
) -> int:
    """Remove every reference minted for one sector. Returns the count.

    ``sector_plugin`` omitted takes the whole guild's sectors, which is what
    guild deletion needs. No sector column is a foreign key — a plug-in's
    sector outlives its install — so this stands in for the cascade.
    """
    clause = IdentityRef.sector_guild_id == sector_guild_id
    if sector_plugin is not None:
        clause = and_(clause, IdentityRef.sector_plugin == sector_plugin)
    result = await session.exec(delete(IdentityRef).where(clause))
    return result.rowcount or 0


async def drop_guild_refs(session: AsyncSession, *, guild_id: int) -> int:
    """Everything a purged guild leaves in this table. Returns the count.

    Two halves, because a guild appears here in two ways. The sectors INSIDE
    it name its members to each plug-in there. The guild itself is also named —
    by billing, whose sector is the whole deployment and whose rows therefore
    carry no ``sector_guild_id`` to find them by. What its own webhook
    subscriptions call anybody is in its schema, and goes with that.

    A guild that is deleted but not yet purged keeps both: it can still come
    back, under the names its plug-ins already hold.
    """
    dropped = await drop_sector_refs(session, sector_guild_id=guild_id)
    dropped += await drop_entity_refs(
        session, entity_type=IdentityEntity.guild, entity_id=guild_id
    )
    return dropped


async def forget_user(*, user_id: int) -> int:
    """Drop every reference to one person, reporting rather than raising.

    Called once the account is erased and after the plug-ins holding those
    references have been told, so a revocation already on its way still names
    somebody. Opens its own session for the reason ``billing_ref`` does —
    the callers are request handlers routed to other roles — and runs after the
    commit, where a failure must not undo the erasure;
    :func:`purge_orphaned_entity_refs` removes what it leaves.
    """
    from app.db.session import SystemSessionLocal

    try:
        async with SystemSessionLocal() as session:
            dropped = await drop_entity_refs(
                session, entity_type=IdentityEntity.user, entity_id=user_id
            )
            await session.commit()
    except SQLAlchemyError:
        logger.warning(
            "identity refs: references for erased user %s were not removed", user_id
        )
        return 0
    return dropped


async def purge_orphaned_sector_refs(session: AsyncSession) -> int:
    """Drop references whose sector guild is gone. Returns the count.

    The sector columns cannot be foreign keys, so a guild's references are
    removed by the purge rather than by a cascade. This reclaims the ones the
    purge did not manage to remove — it runs after the guild row has gone,
    where there is nothing left to roll back. A guild that is deleted but not
    yet purged keeps its sectors: its plug-ins are told to erase them first,
    at the purge.
    """
    result = await session.exec(
        delete(IdentityRef).where(
            IdentityRef.sector_guild_id.is_not(None),
            ~exists(select(Guild.id).where(Guild.id == IdentityRef.sector_guild_id)),
        )
    )
    return result.rowcount or 0


async def purge_orphaned_entity_refs(session: AsyncSession) -> int:
    """Drop references naming an erased account, a purged guild or a deleted
    demo link (an invite into a pitch).

    Returns the count. The entity column cannot be a foreign key — erasure
    keeps the ``users`` row as an anonymized husk — so these are removed by
    :func:`forget_user` and the guild purge, both after their commit. This
    reclaims what those did not manage to remove. An account that is deleted
    but not yet erased, and a guild that is deleted but not yet purged, keep
    theirs: either can still come back.
    """
    live_user = select(User.id).where(
        User.id == IdentityRef.entity_id,
        User.status != UserStatus.anonymized,
    )
    live_guild = select(Guild.id).where(Guild.id == IdentityRef.entity_id)
    live_link = select(GuildInvite.id).where(GuildInvite.id == IdentityRef.entity_id)
    result = await session.exec(
        delete(IdentityRef).where(
            or_(
                and_(
                    IdentityRef.entity_type == IdentityEntity.user,
                    ~exists(live_user),
                ),
                and_(
                    IdentityRef.entity_type == IdentityEntity.guild,
                    ~exists(live_guild),
                ),
                and_(
                    IdentityRef.entity_type == IdentityEntity.demo_link,
                    ~exists(live_link),
                ),
            )
        )
    )
    return result.rowcount or 0


async def purge_retired_refs(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Drop the rows whose grace window has closed. Returns the count."""
    moment = now or datetime.now(UTC)
    result = await session.exec(
        delete(IdentityRef).where(
            IdentityRef.retired_at.is_not(None),
            IdentityRef.retired_at <= moment - REF_GRACE_PERIOD,
        )
    )
    return result.rowcount or 0


async def sweep_identity_refs(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """One pass of every reclaim above. Returns how many rows went.

    Split out from the loop entry point so tests can drive it with the test
    session and a chosen ``now``.
    """
    from app.db.session import set_rls_context

    await set_rls_context(session, Unattributed())
    dropped = await purge_orphaned_sector_refs(session)
    dropped += await purge_orphaned_entity_refs(session)
    dropped += await purge_retired_refs(session, now=now)
    await session.commit()
    if dropped:
        logger.info("identity refs: swept %d reference(s)", dropped)
    return dropped


async def process_identity_ref_sweep() -> None:
    """One pass of the identity-ref sweep loop. Idempotent and safe to run on
    a schedule even when nothing is due."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        await sweep_identity_refs(session)


async def _live_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: IdentityPurpose,
    sector: Sector,
) -> IdentityRef | None:
    return (
        await session.exec(
            select(IdentityRef).where(
                IdentityRef.entity_type == entity_type,
                IdentityRef.entity_id == entity_id,
                IdentityRef.purpose == purpose,
                IdentityRef.retired_at.is_(None),
                _sector_clause(sector),
            )
        )
    ).first()
