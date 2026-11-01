"""What one webhook subscriber calls the guild, and the people writing in it.

A delivery leaves this deployment, so the guild it came from and the member
whose write caused it are named by reference rather than by row id — the same
rule every other boundary follows.

Which reference depends on who is receiving, because a reference is pairwise:

* **A plug-in registered the subscription.** It already holds a name for the guild
  and for each member, minted for it in this guild and used on every other
  exchange it has with us. A delivery arrives under those, so the plug-in can match an
  envelope to what it has stored without learning a second set of names for the
  same people. They are kept in ``public.identity_refs``, beside the plug-in's
  other names.
* **A member registered it against a URL of their own.** There is no plug-in to
  borrow a sector from, so the subscription is the sector. The names are stable
  for that subscription and unrelated to every other subscriber's. They are the
  guild's own, kept in its schema under the subscription
  (``models.tenant.webhook_ref``), and go when it does.

Minted on the system engine, like every other name, so each call opens a session
of its own from the guild's cohort: the callers are a background poller routed
into a guild role and a request handler doing the same.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from datetime import datetime, timezone

from sqlalchemy import tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.models.tenant.webhook_ref import WebhookRef
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.marketplace import plugin_refs
from app.services.platform import identity_refs

__all__ = [
    "name_for_subscriber",
    "names_for_subscribers",
]


#: ``(plugin, subscription_id, actor_ids)`` — one subscriber to name, by the
#: ``public_id`` of the plug-in that registered it (or ``None`` for a member's
#: own), and the people it will be told about.
Subscriber = tuple[str | None, int, Collection[int]]

#: ``(guild_ref, {user_id: ref})`` — what one subscriber calls the guild and
#: each person.
Names = tuple[str, dict[int, str]]

#: ``(subscription_id, entity_type, entity_id)`` — one name a subscription holds.
_Key = tuple[int, IdentityEntity, int]


async def name_for_subscriber(
    *,
    guild_id: int,
    plugin: str | None,
    subscription_id: int,
    actor_ids: Collection[int] = (),
) -> Names | None:
    """This subscriber's names for the guild and for each actor it will be told about.

    Returns ``(guild_ref, {user_id: ref})``, or ``None`` for a subscription
    deleted meanwhile. Minted on first use, in one session for the whole
    batch, because a delivery names as many people as the transaction it
    describes touched.
    """
    (names,) = await names_for_subscribers(
        guild_id=guild_id, subscribers=[(plugin, subscription_id, actor_ids)]
    )
    return names


async def names_for_subscribers(
    *, guild_id: int, subscribers: Sequence[Subscriber]
) -> list[Names | None]:
    """:func:`name_for_subscriber` for each of many subscribers, in order — one
    session and one commit for the lot, for a page listing them."""
    if not subscribers:
        return []
    names: dict[int, Names | None] = {}
    own: dict[int, tuple[int, Collection[int]]] = {}
    async with cohorts.system_session(guild_id) as session:
        for index, (plugin, subscription_id, actor_ids) in enumerate(subscribers):
            if plugin is not None:
                try:
                    names[index] = await _named_by_plugin(
                        session, guild_id=guild_id, plugin=plugin, actor_ids=actor_ids
                    )
                    continue
                except plugin_refs.PluginNameRefused:
                    # The plug-in may not be named here any more (its data was
                    # erased): what it registered is named as its own sector.
                    # Only a subscription switched off with its install comes
                    # here; the delivery roster needs a live install.
                    pass
            own[index] = (subscription_id, actor_ids)
        if own:
            # A subscription's own names are in the guild's schema and the
            # plug-ins' above are not, so this routes after them.
            await set_rls_context(session, SystemGuild(guild_id))
            held = await _subscription_refs(
                session, guild_id=guild_id, wanted=own.values()
            )
            for index, (subscription_id, actor_ids) in own.items():
                guild_ref = held.get((subscription_id, IdentityEntity.guild, guild_id))
                names[index] = (
                    None
                    if guild_ref is None
                    else (
                        guild_ref,
                        {
                            actor_id: held[
                                subscription_id, IdentityEntity.user, actor_id
                            ]
                            for actor_id in _people(actor_ids)
                        },
                    )
                )
        await session.commit()
    return [names[index] for index in range(len(subscribers))]


def _people(actor_ids: Collection[int]) -> list[int]:
    return sorted({actor_id for actor_id in actor_ids if actor_id is not None})


async def _named_by_plugin(
    session: AsyncSession,
    *,
    guild_id: int,
    plugin: str,
    actor_ids: Collection[int],
) -> Names:
    """The guild's and each actor's names in one plug-in's sector, minted on
    first use."""
    before_mint = plugin_refs.mint_guard(guild_id, plugin)
    guild_ref = await identity_refs.ensure_ref(
        session,
        entity_type=IdentityEntity.guild,
        entity_id=guild_id,
        purpose=IdentityPurpose.plugin,
        sector_guild_id=guild_id,
        sector_plugin=plugin,
        before_mint=before_mint,
    )
    actor_refs = {
        actor_id: await identity_refs.ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=actor_id,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=guild_id,
            sector_plugin=plugin,
            before_mint=before_mint,
        )
        for actor_id in _people(actor_ids)
    }
    return guild_ref, actor_refs


async def _subscription_refs(
    session: AsyncSession,
    *,
    guild_id: int,
    wanted: Iterable[tuple[int, Collection[int]]],
) -> dict[_Key, str]:
    """What each subscription calls the guild and each of its people, minting
    the names it does not hold yet: one read when it holds them all. A
    subscription deleted meanwhile has none.

    ``session`` is routed into the guild as the platform, which alone writes
    these.
    """
    wanted = list(wanted)
    # Held while they are named, as the names' key would hold them: one
    # deleted first is left out, and none is deleted until this commits.
    standing = set(
        (
            await session.exec(
                select(WebhookSubscription.id)
                .where(
                    WebhookSubscription.id.in_(  # type: ignore[union-attr]
                        {subscription_id for subscription_id, _ in wanted}
                    )
                )
                .with_for_update(key_share=True)
            )
        ).all()
    )
    keys = {
        key
        for subscription_id, actor_ids in wanted
        if subscription_id in standing
        for key in (
            (subscription_id, IdentityEntity.guild, guild_id),
            *(
                (subscription_id, IdentityEntity.user, actor_id)
                for actor_id in _people(actor_ids)
            ),
        )
    }
    held = await _held(session, keys)
    missing = sorted(keys - held.keys())
    if missing:
        now = datetime.now(timezone.utc)
        await session.exec(
            pg_insert(WebhookRef.__table__)
            .values(
                [
                    {
                        "subscription_id": subscription_id,
                        "entity_type": entity_type.value,
                        "entity_id": entity_id,
                        "ref": identity_refs.mint_ref(
                            entity_type, IdentityPurpose.webhook
                        ),
                        "created_at": now,
                    }
                    for subscription_id, entity_type, entity_id in missing
                ]
            )
            # Two callers racing the same first mint both insert and one loses
            # here; both read back the winner's value below.
            .on_conflict_do_nothing(
                index_elements=["subscription_id", "entity_type", "entity_id"]
            )
        )
        held |= await _held(session, missing)
    return held


async def _held(session: AsyncSession, keys: Collection[_Key]) -> dict[_Key, str]:
    rows = await session.exec(
        select(
            WebhookRef.subscription_id,
            WebhookRef.entity_type,
            WebhookRef.entity_id,
            WebhookRef.ref,
        ).where(
            tuple_(
                WebhookRef.subscription_id,
                WebhookRef.entity_type,
                WebhookRef.entity_id,
            ).in_(
                [
                    (subscription_id, entity_type.value, entity_id)
                    for subscription_id, entity_type, entity_id in keys
                ]
            )
        )
    )
    return {
        (subscription_id, IdentityEntity(entity_type), entity_id): ref
        for subscription_id, entity_type, entity_id, ref in rows
    }
