"""Outbound webhook subscriptions for a guild.

Register a URL and the change events it should receive; the delivery worker
POSTs signed, content-free envelopes to it (see
``app.services.tenant.outbox_poller``).

**A subscription's reach is the scope it names.** ``initiative_id`` means that
initiative's changes; omitting it means the whole community's, which is why
registering one of those is a guild admin's to do. Nobody's standing is read at
delivery: an envelope is identifiers and changed column names, and a consumer
reads current state back through the REST path, where every gate applies to the
read. An installed plug-in calling back does so on its own token, whose standing is
read on every call.

So a subscription is the community's integration configuration rather than the
personal property of whoever registered it, and it outlives their membership,
their role and their account.

  POST   /api/v1/c/{community_id}/webhooks/subscriptions
    body: {target_url, event_types, fields?, initiative_id?}
    → returns subscription + plaintext hmac_secret (one-time)
  GET    /api/v1/c/{community_id}/webhooks/subscriptions
  PATCH  /api/v1/c/{community_id}/webhooks/subscriptions/{id}
  DELETE /api/v1/c/{community_id}/webhooks/subscriptions/{id}

Every read includes ``dead_letter_count`` — how many of the poller's ledger
rows for that subscription (``app.services.tenant.outbox_poller``) gave up
retrying. It is the only surface a broken target has: the poller itself never
raises, so a nonzero count is what tells whoever owns the subscription to
check the target or deactivate it.

Who may rewrite or remove one is the row's own gates, the same ones that govern
the content it watches: initiative write access for an initiative-scoped
subscription, guild admin for a community-wide one. Authorship is not a gate in
this app.

An installed plug-in registers and removes subscriptions on its installation token.
What it may register depends on the
event types it names — each needs the read scope of its tool — so the two
routes take :func:`app.api.deps.plugin_scope_checked` and the service asks those
scopes of the install's standing. An install sees and removes only the
subscriptions it registered.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    RLSSessionDep,
    plugin_scope_checked,
    get_current_active_user,
    GuildContextDep,
)
from app.core import webhook_events
from app.core.messages import WebhookSubscriptionMessages
from app.db.guild_standing import InstallContext
from app.models.platform.user import User
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.schemas.tenant.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import webhook_refs
from app.services.tenant import webhook_subscriptions as subscriptions_service
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
)

router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call. Registering asks the read scope of
#: each event type's tool, which the service checks once it has the body;
#: removing reaches only the install's own subscriptions.
SubscriptionsByEventType = Annotated[
    ActorContext,
    Depends(plugin_scope_checked(webhook_events.event_read_scopes(), per="event type")),
]


async def _validate_target_url(url: str) -> None:
    """Reject URLs that resolve into private/loopback/link-local space.

    Async because DNS resolution can block; we don't want to stall the
    event loop on a slow resolver. Raises HTTPException with codes the
    frontend can localize.
    """
    try:
        await assert_target_url_is_public_async(url)
    except WebhookTargetUrlPrivateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WebhookSubscriptionMessages.PRIVATE_TARGET_URL,
        ) from exc
    except WebhookTargetUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WebhookSubscriptionMessages.INVALID_TARGET_URL,
        ) from exc


async def _subscriber_plugins(
    session: AsyncSession, install_ids: set[int]
) -> dict[int, str]:
    """The ``public_id`` of the plug-in behind each install in ``install_ids``,
    for those that have one: the sector a subscription it registered is named
    in."""
    if not install_ids:
        return {}
    installs = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id.in_(install_ids)))
    ).all()
    named: dict[int, str] = {}
    for install in installs:
        public_id = await guild_plugins_service.install_public_id(install)
        if public_id is not None:
            named[int(install.id)] = public_id
    return named


async def _named(
    session: AsyncSession,
    rows: list[WebhookSubscription],
    *,
    guild_id: int,
    dead_letter_counts: dict[int, int],
    actor: ActorContext | None = None,
) -> list[WebhookSubscriptionRead]:
    """Subscriptions, with the guild and each creator named for its receiver.

    Minted rather than stored, and in the same sector its deliveries use, so
    what a receiver reads here is what it will be sent — all of them in one
    session. An installed plug-in that registered one names no person on it, and
    its standing already carries what the install calls the guild, so nothing
    is minted for it here.
    """
    own_ref: str | None = None
    own: set[int | None] = set()
    if isinstance(actor, InstallContext) and actor.guild_ref is not None:
        own_ref = actor.guild_ref
        own = {
            row.id
            for row in rows
            if row.plugin_install_id == actor.install_id and row.created_by is None
        }
    # An install's own subscriptions are its token's plug-in; any other is read
    # from its install row.
    known = (
        {actor.install_id: actor.client_id} if isinstance(actor, InstallContext) else {}
    )
    plugins = known | await _subscriber_plugins(
        session,
        {
            row.plugin_install_id
            for row in rows
            if row.id not in own
            and row.plugin_install_id is not None
            and row.plugin_install_id not in known
        },
    )
    minted = iter(
        await webhook_refs.names_for_subscribers(
            guild_id=guild_id,
            subscribers=[
                (
                    plugins.get(row.plugin_install_id)
                    if row.plugin_install_id is not None
                    else None,
                    row.id,
                    () if row.created_by is None else (row.created_by,),
                )
                for row in rows
                if row.id not in own
            ],
        )
    )
    reads = []
    for row in rows:
        if own_ref is not None and row.id in own:
            guild_ref, actor_refs = own_ref, {}
        else:
            guild_ref, actor_refs = next(minted)
        reads.append(
            WebhookSubscriptionRead(
                id=row.id,
                community_ref=guild_ref,
                initiative_id=row.initiative_id,
                created_by_ref=(
                    None if row.created_by is None else actor_refs[row.created_by]
                ),
                target_url=row.target_url,
                event_types=row.event_types,
                fields=row.fields,
                active=row.active,
                dead_letter_count=dead_letter_counts.get(row.id, 0),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return reads


@router.post(
    "/subscriptions",
    response_model=WebhookSubscriptionCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    payload: WebhookSubscriptionCreate,
    session: ActorSessionDep,
    guild_context: SubscriptionsByEventType,
) -> WebhookSubscriptionCreated:
    """Register a new webhook subscription.

    The HMAC secret is included in the response *only here*; subsequent reads
    omit it. The receiver must persist it from this response or rotate the
    subscription if they lose it.

    A subscription is the community's configuration: delivery carries the change
    log of the scope it names, the initiative it was registered against or, for
    one a guild admin registers, the whole community.

    An installed plug-in registers one as its community, naming no person: each
    event type needs the read scope of its tool, a token narrowed to one
    initiative registers for that initiative only, and a community-wide one
    needs a token that is not narrowed. Otherwise 403 (``PLUGIN_SCOPE_REQUIRED``).

    Target policy: ``target_url`` must be https and resolve to a public unicast
    address; private, loopback and link-local addresses are rejected.
    """
    await _validate_target_url(str(payload.target_url))

    if isinstance(guild_context, InstallContext):
        (
            subscription,
            secret,
        ) = await subscriptions_service.create_install_subscription(
            session, context=guild_context, payload=payload
        )
    else:
        subscription, secret = await subscriptions_service.create_subscription(
            session,
            payload=payload,
            created_by=guild_context.user_id,
            guild_id=guild_context.guild_id,
        )

    return WebhookSubscriptionCreated(
        # A subscription that was just created has no delivery history yet.
        **(
            await _named(
                session,
                [subscription],
                guild_id=guild_context.guild_id,
                dead_letter_counts={},
                actor=guild_context,
            )
        )[0].model_dump(),
        hmac_secret=secret,
    )


@router.get("/subscriptions", response_model=list[WebhookSubscriptionRead])
async def list_subscriptions(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[WebhookSubscriptionRead]:
    """List subscriptions in the caller's guild. ``hmac_secret`` is
    intentionally absent from the response — it is returned once, on create."""
    rows = await subscriptions_service.list_subscriptions(
        session, guild_id=guild_context.guild_id
    )
    counts = await subscriptions_service.dead_letter_counts(
        session, subscription_ids=[row.id for row in rows]
    )
    return await _named(
        session, rows, guild_id=guild_context.guild_id, dead_letter_counts=counts
    )


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=WebhookSubscriptionRead,
)
async def update_subscription(
    subscription_id: int,
    payload: WebhookSubscriptionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> WebhookSubscriptionRead:
    """Partial-update target_url, event_types, or active flag.

    Who may is the UPDATE policy — initiative write access, or guild admin for
    a community-wide subscription. ``target_url`` (when provided) is
    re-validated: it must resolve to a public address.
    """
    if payload.target_url is not None:
        await _validate_target_url(str(payload.target_url))

    row = await subscriptions_service.update_subscription(
        session,
        subscription_id=subscription_id,
        guild_id=guild_context.guild_id,
        payload=payload,
        actor_user_id=current_user.id,
    )
    counts = await subscriptions_service.dead_letter_counts(
        session, subscription_ids=[row.id]
    )
    (read,) = await _named(
        session, [row], guild_id=guild_context.guild_id, dead_letter_counts=counts
    )
    return read


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_subscription(
    subscription_id: int,
    session: ActorSessionDep,
    guild_context: SubscriptionsByEventType,
) -> None:
    """Hard-delete a subscription. Who may is the DELETE policy, the same gates
    that govern the content it watches; a cross-guild lookup is a 404. An
    installed plug-in reaches only the subscriptions it registered, and any other
    is a 404.

    The names it minted for itself go with it. One a plug-in registered is
    named in that plug-in's sector, which outlives any single subscription."""
    await subscriptions_service.delete_subscription(
        session,
        subscription_id=subscription_id,
        guild_id=guild_context.guild_id,
        actor_user_id=guild_context.user_id,
        by_install=isinstance(guild_context, InstallContext),
    )
