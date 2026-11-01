"""Which name a webhook subscriber is given for a guild, and why that one.

The rule has one branch, and both sides of it matter. A plug-in that registered a
subscription already knows this guild and these people — it was told them in
this guild, and every other exchange it has with us uses those names. A delivery
has to arrive under the same ones, or the plug-in is holding two unrelated values
for one guild and can match an envelope to nothing.

A member registering a URL of their own has no plug-in to borrow from, so the
subscription is its own sector, and its names are the guild's own: kept in its
schema, under the subscription, and gone with it.
"""

from __future__ import annotations

from sqlalchemy import text

from app.models.platform.identity_ref import IdentityPurpose
from app.services.marketplace.plugin_refs import (
    ensure_plugin_guild_ref,
    ensure_plugin_ref,
)
from app.services.tenant import webhook_refs
from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_user,
    create_webhook_subscription,
)


async def _with_plugin(session, user):
    """A guild with ``acme.tracker`` installed: only a plug-in installed in a
    community is given names there."""
    guild = await create_guild(session, creator=user)
    await create_guild_plugin(
        session,
        guild,
        user,
        definition={"plugin_kind": "service", "service": {"public_id": "acme.tracker"}},
    )
    await session.commit()
    return guild


async def _held(session, guild_id: int) -> set[tuple]:
    """Every name the guild's schema holds, as ``(subscription_id,
    entity_type, entity_id, ref)``."""
    rows = await session.exec(
        text(
            "SELECT subscription_id, entity_type, entity_id, ref"
            f' FROM "guild_{guild_id}".webhook_refs'
        )
    )
    return {tuple(row) for row in rows.all()}


async def test_a_plugin_hears_the_names_it_already_holds(session):
    """The whole point of the branch. The plug-in channel minted these for it;
    a delivery repeats them rather than introducing a second set."""
    user = await create_user(session)
    guild = await _with_plugin(session, user)
    plugin = "acme.tracker"

    guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=plugin,
        subscription_id=1,
        actor_ids=(user.id,),
    )

    assert guild_ref == await ensure_plugin_guild_ref(
        guild_id=guild.id, public_id=plugin
    )
    assert actor_refs[user.id] == await ensure_plugin_ref(
        guild_id=guild.id, public_id=plugin, user_id=user.id
    )
    assert await _held(session, guild.id) == set()


async def test_a_member_registered_target_is_named_by_its_subscription(session):
    """No plug-in to borrow a sector from, so the subscription is one, and its
    names are kept under it in the guild's own schema."""
    user = await create_user(session)
    guild = await _with_plugin(session, user)
    subscription = await create_webhook_subscription(session, guild, user)

    guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=None,
        subscription_id=subscription.id,
        actor_ids=(user.id,),
    )

    assert guild_ref.startswith("g" + IdentityPurpose.webhook.code + "_")
    assert actor_refs[user.id].startswith("u" + IdentityPurpose.webhook.code + "_")
    assert guild_ref != await ensure_plugin_guild_ref(
        guild_id=guild.id, public_id="acme.tracker"
    )
    assert await _held(session, guild.id) == {
        (subscription.id, "guild", guild.id, guild_ref),
        (subscription.id, "user", user.id, actor_refs[user.id]),
    }


async def test_two_subscriptions_in_one_guild_are_unrelated(session):
    """Two targets comparing notes learn nothing about each other's guild."""
    user = await create_user(session)
    guild = await _with_plugin(session, user)
    one = await create_webhook_subscription(session, guild, user)
    other = await create_webhook_subscription(session, guild, user)

    (
        (first, first_actors),
        (second, second_actors),
    ) = await webhook_refs.names_for_subscribers(
        guild_id=guild.id,
        subscribers=[(None, one.id, (user.id,)), (None, other.id, (user.id,))],
    )

    assert first != second
    assert first_actors[user.id] != second_actors[user.id]


async def test_the_same_subscription_is_named_the_same_way_twice(session):
    """Minted on first use and then stable — a receiver stores it."""
    user = await create_user(session)
    guild = await _with_plugin(session, user)
    subscription = await create_webhook_subscription(session, guild, user)

    first = await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=None,
        subscription_id=subscription.id,
        actor_ids=(user.id,),
    )
    again = await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=None,
        subscription_id=subscription.id,
        actor_ids=(user.id,),
    )

    assert first == again
    assert len(await _held(session, guild.id)) == 2


async def test_a_subscriptions_names_go_with_it(session):
    """Deleting a subscription takes its own names, and never a plug-in's,
    which outlive any one subscription it registered."""
    user = await create_user(session)
    guild = await _with_plugin(session, user)
    subscription = await create_webhook_subscription(session, guild, user)
    await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=None,
        subscription_id=subscription.id,
        actor_ids=(user.id,),
    )
    borrowed = await ensure_plugin_guild_ref(
        guild_id=guild.id, public_id="acme.tracker"
    )

    await session.exec(
        text(f'DELETE FROM "guild_{guild.id}".webhook_subscriptions WHERE id = :id'),
        params={"id": subscription.id},
    )
    await session.commit()

    assert await _held(session, guild.id) == set()
    assert (
        await ensure_plugin_guild_ref(guild_id=guild.id, public_id="acme.tracker")
        == borrowed
    )


async def test_a_subscription_deleted_before_it_is_named_has_no_names(session):
    """A page lists its subscriptions, then names them: one deleted in between
    is named nothing, and the rest as ever."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    kept = await create_webhook_subscription(session, guild, user)
    gone = await create_webhook_subscription(session, guild, user)
    gone_id = gone.id
    await session.exec(
        text(f'DELETE FROM "guild_{guild.id}".webhook_subscriptions WHERE id = :id'),
        params={"id": gone_id},
    )
    await session.commit()

    named, deleted = await webhook_refs.names_for_subscribers(
        guild_id=guild.id,
        subscribers=[(None, kept.id, (user.id,)), (None, gone_id, (user.id,))],
    )

    assert named is not None and set(named[1]) == {user.id}
    assert deleted is None
    assert {row[3] for row in await _held(session, guild.id)} == {
        named[0],
        named[1][user.id],
    }


async def test_an_initiatives_subscriptions_take_their_names_with_them(session):
    """A subscription to one initiative goes when the initiative does, and its
    names with it."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    subscription = await create_webhook_subscription(
        session, guild, user, initiative_id=initiative.id
    )
    await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        plugin=None,
        subscription_id=subscription.id,
        actor_ids=(user.id,),
    )

    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()
    await hard_purge_entity(session, initiative)
    await session.commit()

    assert await _held(session, guild.id) == set()


async def test_an_erased_plugins_subscription_is_named_as_its_own(session):
    """Once a plug-in may not be named here (it has no install), a subscription
    it registered is named in the subscription's own sector rather than
    bringing the plug-in's names back."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    subscription = await create_webhook_subscription(session, guild)

    guild_ref, _ = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, plugin="acme.tracker", subscription_id=subscription.id
    )

    assert guild_ref.startswith("g" + IdentityPurpose.webhook.code + "_")
    assert await _held(session, guild.id) == {
        (subscription.id, "guild", guild.id, guild_ref)
    }
