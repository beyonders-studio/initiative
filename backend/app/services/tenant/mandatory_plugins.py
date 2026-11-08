"""Plug-ins the deployment provides, rather than a guild choosing them.

Some plug-ins are not an optional extra: they are part of what a deployment *is*.
An operator says so on the registration (``mandatory``), and this is what that
statement does — every guild has the plug-in, already there, with no admin
discovering it in a catalog and no admin able to remove it.

Six properties, and each one is a deliberate choice:

* **A guild gets it at creation, and an existing guild gets it at boot.** The
  same sweep pattern that reprovisions stale schemas, so the flag reaches guilds
  that predate it without anyone running anything. The install index
  (``plugin_installs``) says which guilds lack an install, and only those are
  visited.
* **Installing never fails guild creation.** The install is a local row; the
  plug-in's container may be down, its listing may not have arrived yet, and none of
  that is a reason a guild cannot be created. What is missing is logged, and the
  next boot tries again.
* **The kill switch outranks the flag.** A registration the operator turned off
  installs nowhere new — deactivating a plug-in stops it exactly like any other.
  One limited to the operations community (``operations_only``) is installed
  there alone.
* **It is granted what it asks for, within the ceiling.** The manifest's
  requested scopes, capped by the registration's ``scope_ceiling``: the
  operator's registration is the consent a seat would otherwise give. Using
  another plug-in is granted only once the community has it, and a required
  plug-in arriving lets every install that asks use it.
* **It is placed in every initiative there is.** When it is installed.
* **After that it is the seat's.** Its grant and where it appears, new
  initiatives included, are the seat's to change, as for any install. Nothing
  here touches an install that is already there.
* **Clearing the flag destroys nothing.** Nothing here removes an install, so a
  plug-in that stops being mandatory simply becomes an ordinary one a guild admin
  may now remove. Tearing a plug-in down is uninstalling it, which is a different
  path with different consequences.

A self-hosted build that registered no plug-in service has nothing marked mandatory,
so nothing here installs anything and nothing is displayed — the mechanism ships,
and a deployment's configuration decides whether anything uses it.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import GUILD_ADMIN_ROLES, GuildMembership
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.guild_sweeps import Scope, each_guild
from app.services.marketplace import plugin_installs, registration_lookup
from app.services.marketplace.definitions import GUILD_INSTALLABLE_PLUGIN_KINDS
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import plugin_schedules

logger = logging.getLogger(__name__)

__all__ = [
    "BackfillResult",
    "assign_install_settings",
    "backfill_mandatory_plugins",
    "install_mandatory_plugins",
    "mandatory_grant",
]


@dataclass(frozen=True)
class BackfillResult:
    """What one boot sweep did."""

    guilds: int = 0
    installed: int = 0
    failed: int = 0


def mandatory_grant(
    definition: dict,
    registration: registration_lookup.RegistrationSnapshot,
    installed: Collection[str],
) -> list[str]:
    """The scopes a mandatory install is granted: what its manifest requests
    and its registration's ceiling allows, sorted, using only the ``installed``
    plug-ins.

    Written on the system engine, which the install's grant guard admits.
    """
    return sorted(
        guild_plugins_service.grantable_scopes(
            definition, registration.scope_ceiling, installed
        )
    )


async def _installer_user_id(
    session: AsyncSession, *, guild_id: int, preferred: int | None = None
) -> int | None:
    """Who an automatic install is recorded against.

    The install row names a person because every other install does, and a
    guild admin is the honest answer: this is a plug-in they are responsible for
    even though they did not choose it. The guild's own creator is preferred
    when the caller knows them; otherwise the longest-standing admin.
    """
    if preferred is not None:
        return preferred
    return (
        await session.exec(
            select(GuildMembership.user_id)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role.in_(GUILD_ADMIN_ROLES),
            )
            .order_by(GuildMembership.user_id)
            .limit(1)
        )
    ).first()


async def install_mandatory_plugins(
    session: AsyncSession,
    *,
    guild_id: int,
    created_by: int | None = None,
) -> list[str]:
    """Install every mandatory plug-in this guild does not have yet.

    The session must already be routed into the guild's schema. Rows are
    flushed, not committed: the caller owns the transaction, so a guild creation
    commits its plug-ins together with the rest of its seed.

    Returns the listing uids installed. Anything that could not be installed —
    a registration naming no listing, a listing this deployment does not hold,
    a version needing a newer build — is logged and skipped, because none of
    those is a reason to fail whatever the caller was doing.

    ``created_by`` is also the account the caller's session runs as, and is what
    the audit record names: a guild creation routes as its new owner and passes
    them here, and the boot sweep routes as nobody and passes nothing. The row
    an install is *recorded against* can differ — that is ``installer_id``,
    which falls back to the guild's longest-standing admin.
    """
    registrations = [
        registration
        for registration in await registration_lookup.mandatory_registrations()
        if registration.serves(guild_id)
    ]
    if not registrations:
        return []

    installer_id = await _installer_user_id(
        session, guild_id=guild_id, preferred=created_by
    )
    if installer_id is None:
        logger.warning(
            "mandatory plug-ins: guild %s has no admin to record an install against",
            guild_id,
        )
        return []

    installed: list[str] = []
    present = set(await guild_plugins_service.installed_plugin_ids(session))
    for registration in registrations:
        if registration.listing_uid is None:
            # A registration from before the listing was stated names none,
            # so there is nothing to install.
            logger.info(
                "mandatory plug-ins: %s names no listing to install",
                registration.public_id,
            )
            continue

        if (
            await session.exec(
                select(GuildPlugin.id).where(
                    GuildPlugin.listing_uid == registration.listing_uid
                )
            )
        ).first() is not None:
            # Already here: from then on it is the seat's, as any install is.
            continue

        try:
            listing, version = await resolve_listing_install(
                session, registration.listing_uid, kind="plugin"
            )
        except ListingInstallError as exc:
            logger.info(
                "mandatory plug-ins: %s cannot be installed into guild %s (%s)",
                registration.public_id,
                guild_id,
                exc.code,
            )
            continue

        definition = dict(version.definition)
        if definition.get("plugin_kind") not in GUILD_INSTALLABLE_PLUGIN_KINDS:
            logger.warning(
                "mandatory plug-ins: %s is not a kind this build mounts",
                registration.public_id,
            )
            continue

        try:
            plugin = await guild_plugins_service.install_plugin(
                session,
                listing_uid=listing.uid,
                listing_version=version.version,
                definition=definition,
                guild_id=guild_id,
                created_by=installer_id,
                name=(definition.get("default_name") or listing.name).strip(),
                actor_user_id=created_by,
                via="mandatory",
                granted_scopes=mandatory_grant(definition, registration, present),
                # The registration stands in for the seat here too.
                allowed_callers=None,
            )
        except guild_plugins_service.ErasePendingError:
            # The community asked it to erase its data and that is not
            # finished. Left for a later pass, which finds it still missing.
            logger.info(
                "mandatory plug-ins: %s waits for its erase in guild %s",
                registration.public_id,
                guild_id,
            )
            continue
        present.add(registration.public_id)
        await session.flush()
        await guild_plugins_service.place_in_every_initiative(session, plugin)
        await plugin_schedules.reconcile(
            guild_id, plugin.id, definition, session=session
        )
        installed.append(listing.uid)

    return installed


async def assign_install_settings(
    session: AsyncSession, guild_id: int, listing_uids: Collection[str]
) -> None:
    """Give the assigned settings of the community's installs of
    ``listing_uids`` their values, once the transaction that made the installs
    has committed."""
    if not listing_uids:
        return
    for plugin in (
        await session.exec(
            select(GuildPlugin).where(col(GuildPlugin.listing_uid).in_(listing_uids))
        )
    ).all():
        await guild_plugins_service.assign_settings(session, plugin, guild_id=guild_id)


async def _missing(
    registrations: list[registration_lookup.RegistrationSnapshot],
) -> set[int]:
    """The communities missing a mandatory install, read from the install
    index."""
    found = {
        registration.operations_guild_id
        for registration in registrations
        if registration.operations_only and registration.operations_guild_id is not None
    }
    everywhere = sorted(
        {
            registration.listing_uid
            for registration in registrations
            if registration.listing_uid and not registration.operations_only
        }
    )
    if not everywhere:
        return found
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        found.update(
            (
                await session.exec(
                    text(
                        "SELECT g.id FROM guilds g WHERE ("
                        " SELECT count(DISTINCT i.listing_uid) FROM plugin_installs i"
                        " WHERE i.guild_id = g.id"
                        " AND i.listing_uid = ANY(:uids)) < :wanted"
                    ).bindparams(uids=everywhere, wanted=len(everywhere))  # type: ignore[call-overload]
                )
            ).scalars()
        )
    return found


async def backfill_mandatory_plugins() -> BackfillResult:
    """Place mandatory plug-ins into guilds that predate the flag.

    Runs at boot, visiting each guild :func:`_missing` names on a system
    session from its cohort. A guild that fails is rolled back and logged; the others
    still get their plug-in, and the next boot tries again.

    Returns immediately when nothing is marked mandatory, which is every
    deployment that has not asked for this.
    """
    registrations = await registration_lookup.mandatory_registrations()
    if not registrations:
        return BackfillResult()

    visited = succeeded = installed = 0

    async def backfill(session: AsyncSession, guild_id: int) -> None:
        nonlocal visited, succeeded, installed
        visited += 1
        added = await install_mandatory_plugins(session, guild_id=guild_id)
        await session.commit()
        # The next pass reads the index, so it is written now rather than
        # when the sweep comes.
        await plugin_installs.reindex_community(session, guild_id)
        await assign_install_settings(
            session,
            guild_id,
            [
                registration.listing_uid
                for registration in registrations
                if registration.listing_uid and registration.serves(guild_id)
            ],
        )
        succeeded += 1
        installed += len(added)

    await each_guild(
        [(Scope.PROVISIONED, backfill)],
        name="mandatory-plugins",
        only=await _missing(registrations),
    )
    return BackfillResult(
        guilds=visited, installed=installed, failed=visited - succeeded
    )
