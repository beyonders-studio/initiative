"""Re-homing a registry uid: the registry gives a uid it published under one
listing to another listing.

A uid names one listing everywhere, and the catalog refuses to reassign one
(:func:`app.services.marketplace.catalog.upsert_listing`). The registry is
where uids are issued, though, and when it corrects a listing that was
published under the wrong uid, it gives that uid to the listing that owns it
and the misplaced listing a uid of its own. A deployment that refused both
halves of that correction would keep the wrong mapping forever, so a registry
refresh re-homes the uid when all of these hold:

* the row is the registry's, and so is the publish: no other source's listing
  is ever taken over;
* both are the same publisher's. The publisher's signing role already covers
  every listing under its prefix, so re-homing gives it no power over the old
  listing it did not have;
* no community runs one of the old listing's versions under the uid, or has
  one of the dashboards it bundled. An install pins its version and keeps
  working from it, so the uid cannot start meaning something else while one
  does. An install at a version the old listing never published (one the new
  listing's publisher shipped some other way) does not block it.

Re-homing removes the old listing from the uid: its versions, the dashboards
it bundled (they come back with it under its new uid, under their own uids)
and the beta list its registration kept by the uid. The registration it
declared is detached rather than deleted, because the deployment facts on it
(where the container runs, its keys) belong to the plug-in, not to the uid:
the old listing's publish under its new uid claims it again. The row then
takes the new listing's identity, and the publish that called this writes its
content. Terms are signed per uid, so the same refresh writes the new
listing's.

When a community still runs the old listing, the uid is left as it is and the
publish is refused with its own code, which tells the operator what to do.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from sqlalchemy import delete as sa_delete
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.db import cohorts
from app.db import session as db_session
from app.db.request_context import SystemGuild
from app.db.schema_provisioning import guild_schema_name
from app.models.platform.guild import Guild
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.plugin_service_registration import (
    PluginBetaCommunity,
    PluginServiceRegistration,
)
from app.models.platform.publisher import Publisher, publisher_prefix
from app.services import audit as audit_service
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace.catalog import (
    REGISTRY_SOURCE,
    CatalogListingRehomed,
    get_listing,
)
from app.services.marketplace.registration_lookup import invalidate_registrations

logger = logging.getLogger(__name__)

__all__ = ["communities_running", "rehome_registry_uid"]


async def rehome_registry_uid(
    session: AsyncSession,
    *,
    uid: str,
    public_id: str,
    publisher: Publisher,
) -> bool:
    """Free ``uid`` for the registry listing ``public_id`` when the registry
    moved the listing it held to another uid. Returns whether it did.

    Called by a registry refresh before it publishes the entry, on its
    session; the entry's savepoint covers both. Returns ``False``, changing
    nothing, wherever the catalog's own refusals still apply (another source,
    another publisher, a ``public_id`` another uid holds), so the publish
    that follows refuses exactly as it would have. Raises
    :class:`CatalogListingRehomed` when a community still runs the old
    listing.
    """
    listing = (
        await session.exec(
            select(MarketplaceListing)
            .where(MarketplaceListing.uid == uid)
            .with_for_update()
        )
    ).first()
    if (
        listing is None
        or listing.public_id == public_id
        or listing.source != REGISTRY_SOURCE
        or listing.bundled_with_uid is not None
        or publisher_prefix(listing.public_id) != publisher_prefix(public_id)
        or listing.publisher_id is None
        or listing.publisher_id != publisher.id
        or await get_listing(session, public_id) is not None
    ):
        return False

    bundled = (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.bundled_with_uid == uid)
        )
    ).all()
    rows = {row.id: row.uid for row in (listing, *bundled)}
    held: dict[str, list[str]] = {row_uid: [] for row_uid in rows.values()}
    for listing_id, version in (
        await session.exec(
            select(
                MarketplaceListingVersion.listing_id,
                MarketplaceListingVersion.version,
            ).where(col(MarketplaceListingVersion.listing_id).in_(sorted(rows)))
        )
    ).all():
        held[rows[listing_id]].append(version)

    running = await communities_running(session, held)
    if running:
        raise CatalogListingRehomed(
            f"uid {uid} held {listing.public_id}, which the registry moved to "
            f"another uid; {len(running)} communities still run it"
        )

    old_public_id = listing.public_id
    listing.latest_version_id = None
    listing.public_id = public_id
    # The count was the old listing's installs.
    listing.installs_count = 0
    listing.updated_at = utcnow()
    session.add(listing)
    await session.flush()
    await session.exec(
        sa_delete(MarketplaceListingVersion).where(
            col(MarketplaceListingVersion.listing_id).in_(sorted(rows))
        )
    )
    if bundled:
        await session.exec(
            sa_delete(MarketplaceListing).where(
                col(MarketplaceListing.id).in_(sorted(row.id for row in bundled))
            )
        )
    # Who the old listing reached in beta, not who the new one reaches.
    await session.exec(
        sa_delete(PluginBetaCommunity).where(
            col(PluginBetaCommunity.listing_uid) == uid
        )
    )
    await _detach_registrations(session, uid)
    await session.flush()
    logger.info(
        "marketplace registry: uid %s moves from %s to %s",
        uid,
        old_public_id,
        public_id,
    )
    return True


async def _detach_registrations(session: AsyncSession, uid: str) -> None:
    """Unlink every registration naming ``uid``, so it reaches no install
    until the listing that declares it claims it again."""
    registrations = (
        await session.exec(
            select(PluginServiceRegistration)
            .where(PluginServiceRegistration.listing_uid == uid)
            .with_for_update()
        )
    ).all()
    for row in registrations:
        before = audit_service.snapshot(row, registrations_service.AUDITED_FIELDS)
        row.listing_uid = None
        row.updated_at = utcnow()
        session.add(row)
        await session.flush()
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_SERVICE_UPDATED,
            actor_user_id=None,
            target_type="plugin_service_registration",
            target_id=row.id,
            detail={
                "via": "registry",
                **audit_service.changed_fields(
                    before,
                    audit_service.snapshot(row, registrations_service.AUDITED_FIELDS),
                ),
            },
        )
    if registrations:
        invalidate_registrations()


#: The tables in one community's schema that record which listing a row was
#: installed from and at which version: its plug-ins, its dashboards, and every
#: tool's content. Read from the catalog rather than listed here, so a table
#: that gains the pair is covered without this changing.
_INSTALL_TABLES = text(
    "SELECT c.relname FROM pg_catalog.pg_class c"
    " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
    " WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')"
    " AND (SELECT count(*) FROM pg_catalog.pg_attribute a"
    " WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped"
    " AND a.attname IN ('listing_uid', 'listing_version')) = 2"
    " ORDER BY c.relname"
)


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def communities_running(
    session: AsyncSession, held: Mapping[str, Sequence[str]]
) -> list[int]:
    """The communities with a row installed from one of ``held``'s listings
    (uid → versions) at one of those versions, in community order.

    Every community's schema is read, not the install index: the index is
    written by a sweep and holds plug-ins only. A community that cannot be
    read is counted as running it, so a failure never frees a uid that is
    in use.
    """
    pairs = [(uid, version) for uid, versions in held.items() for version in versions]
    if not pairs:
        return []
    params = {
        "uids": [uid for uid, _ in pairs],
        "versions": [version for _, version in pairs],
    }
    guild_ids = (await session.exec(select(Guild.id).order_by(col(Guild.id)))).all()
    running: list[int] = []
    for guild_id in guild_ids:
        assert guild_id is not None
        schema = guild_schema_name(guild_id)
        try:
            async with cohorts.system_session(guild_id) as guild_session:
                await db_session.set_rls_context(
                    guild_session, SystemGuild(guild_id, read_only=True)
                )
                tables = (
                    await guild_session.exec(_INSTALL_TABLES, params={"schema": schema})
                ).all()
                for (table,) in tables:
                    found = (
                        await guild_session.exec(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM"
                                f" {_identifier(schema)}.{_identifier(table)} AS x"
                                " JOIN unnest(CAST(:uids AS text[]),"
                                " CAST(:versions AS text[])) AS held(uid, version)"
                                " ON x.listing_uid = held.uid"
                                " AND x.listing_version = held.version)"
                            ),
                            params=params,
                        )
                    ).one()[0]
                    if found:
                        running.append(guild_id)
                        break
        except SQLAlchemyError:
            logger.exception(
                "marketplace registry: could not read the installs of community %s",
                guild_id,
            )
            running.append(guild_id)
    return running
