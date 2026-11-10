"""Ending a connection's grant at the vendor.

Deleting our copy is the authoritative half of ending access: the platform
will never hand the plug-in a token for that credential again. It is not the whole
of it, because the grant is still live at the vendor until somebody ends it.
Initiative holds the grant for every connection whose flow it ran, so it ends
it too, the way the connection's manifest says (``flow.revoke``):

* ``rfc7009`` — a revocation request to the vendor's ``revoke_url`` (RFC 7009),
  with the vendor client's credentials;
* ``github_grant`` — a ``DELETE`` to GitHub's grant address (``revoke_url``),
  with the vendor client's credentials and the access token;
* ``hook`` — the plug-in's revoke hook, with the tokens, for a vendor whose
  revocation the plug-in knows how to ask for;
* absent — the tokens are deleted and nothing is sent.

A typed connection whose values the plug-in's ``after_connect`` checked has no
flow and no grant, but the plug-in may have made things at the vendor with
them. When it is cleared or replaced, or values it checked are not kept, the
plug-in's revoke hook is sent the values it held.

Three properties this module keeps:

* **A revocation to the plug-in rides its hook queue.** One whose flow says
  ``hook`` is written as a ``revoke`` row on the community-hook queue
  (``community_hooks``) in the caller's own transaction, so it is sent by the
  one sender every hook to a plug-in goes through, in order: an uninstall's go
  ahead of its ``uninstalled`` and ``erase``. The tokens stay sealed in the
  row and are opened only to be sent; a rollback writes nothing.
* **A revocation to a vendor is captured during the transaction and sent after
  it.** ``rfc7009`` and ``github_grant`` go to the vendor, never to the plug-in,
  and name nobody to it. An intent carries the sealed tokens of the row it
  ends, read before the row is deleted, and is queued on the session's commit
  (:func:`app.db.post_commit.after_commit`), so a rolled-back delete, or one in
  a rolled-back savepoint, never ends a grant.
* **Never able to fail a teardown.** Each vendor intent is tried three times
  and a failure is logged. A member who left a community has left it whether
  or not the vendor answered.

A transaction's intents are sent together once it commits, several at a
time, since each is its own vendor round trip with its own tries. They run as a
task of their own, so a request's answer does not wait on the vendors; a caller
that must know they have gone awaits :func:`app.db.post_commit.settle`.

Every path that deletes a connection's stored values queues an intent here,
whether or not the connection declares a way to revoke it, so each ending is
logged in one place.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from app.db import post_commit
from app.db.session import routed_guild_id
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import registration_lookup
from app.services.marketplace.registration_lookup import (
    is_declarative,
    service_public_id,
)
from app.services.tenant.plugin_config import (
    RESERVED_TOKEN_KEYS,
    checks_typed_values,
    without_tokens,
)

logger = logging.getLogger(__name__)

__all__ = [
    "REVOKE_ATTEMPTS",
    "RevocationIntent",
    "dispatch_revocations",
    "queue_install_revocations",
    "queue_revocations_for_rows",
    "queue_values_revocation",
]

_STEP_KEY = "plugin_credential_revocations"

#: How many times one revocation is sent before it is logged and dropped.
REVOKE_ATTEMPTS = 3
#: The pause before the second and third tries, in seconds.
retry_delays: tuple[float, ...] = (0.5, 1.0)
#: How many intents are sent at once.
REVOKE_CONCURRENCY = 8


@dataclass(frozen=True)
class RevocationIntent:
    """One grant to end.

    ``connection_ref`` is absent for a community connection, which is not
    addressed per person. ``user_id`` is carried for the log line only.

    ``flow`` is the connection's declared flow as the install had it, ``fields``
    its plain stored values (what a ``revoke_url`` template may name), and
    ``sealed_tokens`` its tokens as they were stored, still sealed. All three
    are captured before the row is deleted.
    """

    guild_id: int
    plugin_id: int
    listing_uid: str
    connection_id: str
    connection_ref: str | None = None
    user_id: int | None = None
    reason: str = "revoked"
    public_id: str | None = None
    #: The plug-in is declarative, and is named by its listing.
    declarative: bool = False
    flow: dict[str, Any] | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    sealed_tokens: dict[str, str] = field(default_factory=dict)
    #: When the stored access token lapses, from the connection's values.
    expires_at: int | None = None
    #: A typed connection the plug-in's ``after_connect`` checked: its secret
    #: values as they were stored, still sealed, sent with ``fields``.
    checked: bool = False
    sealed_values: dict[str, str] = field(default_factory=dict)


def _intent_for(
    *,
    guild_id: int,
    plugin_id: int,
    listing_uid: str,
    definition: Mapping[str, Any] | None,
    connection_id: str,
    config: Mapping[str, Any] | None,
    secrets: Mapping[str, Any] | None,
    reason: str,
    connection_ref: str | None = None,
    user_id: int | None = None,
) -> RevocationIntent:
    """An intent for one connection's stored values, read before they go."""
    connection = None
    for entry in (definition or {}).get("connections") or []:
        if isinstance(entry, dict) and entry.get("id") == connection_id:
            connection = entry
            break
    flow = (connection or {}).get("flow")
    checked = checks_typed_values(connection)
    return RevocationIntent(
        guild_id=guild_id,
        plugin_id=plugin_id,
        listing_uid=listing_uid,
        connection_id=connection_id,
        connection_ref=connection_ref,
        user_id=user_id,
        reason=reason,
        public_id=service_public_id(definition),
        declarative=is_declarative(definition),
        flow=dict(flow) if isinstance(flow, dict) else None,
        fields=without_tokens(config),
        sealed_tokens={
            key: value
            for key, value in (secrets or {}).items()
            if key in RESERVED_TOKEN_KEYS and isinstance(value, str)
        },
        expires_at=(
            expiry
            if isinstance(expiry := (config or {}).get("expires_at"), int)
            and not isinstance(expiry, bool)
            else None
        ),
        checked=checked,
        sealed_values={
            key: value
            for key, value in without_tokens(secrets).items()
            if isinstance(value, str)
        }
        if checked
        else {},
    )


class _Revocations(list[RevocationIntent]):
    """One transaction's intents, sent together once it commits."""

    def join(self, released: list[RevocationIntent]) -> None:
        """Take a released savepoint's intents."""
        self.extend(released)

    def __call__(self) -> Awaitable[None]:
        return dispatch_revocations(self)


def _to_the_plugin(intent: RevocationIntent) -> bool:
    """Whether an intent goes to the plug-in itself (its revoke hook), and so
    rides the community-hook queue, rather than to a vendor after the
    commit."""
    held = (
        (intent.flow or {}).get("revoke") == "hook" and bool(intent.sealed_tokens)
    ) or (intent.checked and bool(intent.fields or intent.sealed_values))
    return held and not intent.declarative and bool(intent.public_id)


async def _queue(session: Any, intent: RevocationIntent) -> None:
    """Record one intent, logged once it commits. One to the plug-in is also
    written to its hook queue now, in ``session``'s transaction; one to a
    vendor is sent once the caller commits."""
    post_commit.after_commit(session, _Revocations(), key=_STEP_KEY).append(intent)
    if not _to_the_plugin(intent):
        return
    from app.services.marketplace import community_hooks

    await community_hooks.queue_community_hooks(
        session,
        guild_id=intent.guild_id,
        public_id=str(intent.public_id),
        hooks=("revoke",),
        install_id=intent.plugin_id,
        body={
            "connection": intent.connection_id,
            "sealed_tokens": dict(intent.sealed_tokens),
            "fields": dict(intent.fields) if intent.checked else {},
            "sealed_values": dict(intent.sealed_values),
        },
    )


async def queue_install_revocations(
    session: Any,
    plugin: GuildPlugin,
    connection_ids: Iterable[str],
    *,
    secrets: Mapping[str, Any],
    reason: str,
) -> None:
    """Record an intent for each of ``plugin``'s community connections whose
    stored values are about to go.

    Read from ``plugin.config``, ``secrets`` and ``plugin.definition`` as they are,
    so it is called before any of them changes.
    """
    # Imported here: the flow module reads connection rows, whose own module
    # queues intents here.
    from app.services.tenant import plugin_connection_flows as flows

    guild_id = routed_guild_id(session)
    for connection_id in sorted(connection_ids):
        flows.forget_minted(guild_id, plugin.id, connection_id)
        await _queue(
            session,
            _intent_for(
                guild_id=guild_id,
                plugin_id=plugin.id,
                listing_uid=plugin.listing_uid,
                definition=plugin.definition,
                connection_id=connection_id,
                config=(plugin.config or {}).get(connection_id),
                secrets=secrets.get(connection_id),
                reason=reason,
            ),
        )


async def queue_values_revocation(
    session: Any,
    plugin: GuildPlugin,
    connection_id: str,
    *,
    config: Mapping[str, Any],
    secrets: Mapping[str, Any],
    reason: str,
) -> None:
    """Record an intent for values of one of ``plugin``'s community
    connections that the plug-in checked and that are not kept."""
    await _queue(
        session,
        _intent_for(
            guild_id=routed_guild_id(session),
            plugin_id=plugin.id,
            listing_uid=plugin.listing_uid,
            definition=plugin.definition,
            connection_id=connection_id,
            config=config,
            secrets=secrets,
            reason=reason,
        ),
    )


async def queue_revocations_for_rows(
    session: Any,
    rows: Iterable[Any],
    *,
    reason: str,
    installs: Mapping[int, tuple[str, Mapping[str, Any] | None]],
) -> None:
    """Record an intent for each member connection row whose values are about
    to go. ``installs`` gives, per install id, its listing and the definition
    its connections were made under. The sealed values are the member's own,
    so they are read as the platform, whoever is ending the connection."""
    from app.services.tenant.plugin_connections import connection_secrets_of

    rows = list(rows)
    sealed = await connection_secrets_of(session, [row.id for row in rows])
    guild_id = routed_guild_id(session)
    for row in rows:
        listing_uid, definition = installs.get(row.plugin_id, ("", None))
        await _queue(
            session,
            _intent_for(
                guild_id=guild_id,
                plugin_id=row.plugin_id,
                listing_uid=listing_uid,
                definition=definition,
                connection_id=row.connection_id,
                config=row.config,
                secrets=sealed.get(row.id, {}),
                reason=reason,
                connection_ref=row.connection_ref,
                user_id=row.user_id,
            ),
        )


async def dispatch_revocations(intents: list[RevocationIntent]) -> None:
    """Send queued intents, several at a time. Best-effort, and never raises."""
    limit = asyncio.Semaphore(REVOKE_CONCURRENCY)

    async def bounded(intent: RevocationIntent) -> None:
        async with limit:
            await _dispatch_one(intent)

    await asyncio.gather(*(bounded(intent) for intent in intents))


async def _dispatch_one(intent: RevocationIntent) -> None:
    logger.info(
        "plug-in credential revoked: guild=%s plug-in=%s listing=%s connection=%s "
        "ref=%s reason=%s",
        intent.guild_id,
        intent.plugin_id,
        intent.listing_uid,
        intent.connection_id,
        intent.connection_ref or "-",
        intent.reason,
    )
    try:
        await _deliver(intent)
    except Exception:
        logger.exception(
            "plug-in credential revocation: guild=%s plug-in=%s connection=%s failed",
            intent.guild_id,
            intent.plugin_id,
            intent.connection_id,
        )


async def _deliver(intent: RevocationIntent) -> None:
    """End one grant at its vendor the way its flow says, with three tries. A
    ``hook`` intent is already on the plug-in's hook queue (:func:`_queue`)."""
    method = (intent.flow or {}).get("revoke")
    if method not in ("rfc7009", "github_grant") or not intent.sealed_tokens:
        return
    if intent.public_id is None and intent.declarative:
        # A declarative plug-in is its listing's: the registration that listing
        # applied names it.
        registration = await registration_lookup.declarative_registration(
            intent.listing_uid
        )
        if registration is not None:
            intent = replace(intent, public_id=registration.public_id)
    if not intent.public_id:
        logger.info(
            "plug-in credential revocation: plug-in %s names no service; dropped",
            intent.plugin_id,
        )
        return

    # Imported here: the flow module reads connection rows, whose own module
    # queues intents here.
    from app.services.tenant import plugin_connection_flows as flows

    try:
        send = await flows.revocation_sender(
            method=method,
            public_id=intent.public_id,
            flow=intent.flow or {},
            fields=intent.fields,
            sealed_tokens=intent.sealed_tokens,
            guild_id=intent.guild_id,
            install_id=intent.plugin_id,
            connection_id=intent.connection_id,
            expires_at=intent.expires_at,
        )
    except flows.ConnectionFlowError as exc:
        logger.warning(
            "plug-in credential revocation: plug-in %s connection %s cannot be sent (%s); "
            "dropped",
            intent.public_id,
            intent.connection_id,
            exc.code,
        )
        return
    if send is None:
        return
    await _with_tries(send, intent)


async def _with_tries(
    send: Callable[[], Awaitable[None]], intent: RevocationIntent
) -> None:
    for attempt in range(REVOKE_ATTEMPTS):
        try:
            await send()
            return
        except Exception as exc:
            if attempt + 1 >= REVOKE_ATTEMPTS:
                logger.warning(
                    "plug-in credential revocation: plug-in %s connection %s was not "
                    "accepted after %s tries (%s)",
                    intent.public_id,
                    intent.connection_id,
                    REVOKE_ATTEMPTS,
                    exc,
                )
                return
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            if delay > 0:
                await asyncio.sleep(delay)
