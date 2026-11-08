"""Signing and sending one webhook envelope.

:func:`deliver` POSTs one envelope to one subscription's target, signed with
the subscription's HMAC secret. The outbox poller
(``app.services.tenant.outbox_poller``) is its caller: it drains the change log
and the events plug-ins emit to each subscription, and holds the retry, backoff and
dead-letter state around each send.

Verification (the receiver's job, in initiative-auto):

  1. Parse ``X-Initiative-Timestamp`` and reject if older than ~5 min.
  2. Compute HMAC-SHA256 over ``timestamp + "." + body`` with the
     subscription's stored secret.
  3. Compare to ``X-Initiative-Signature`` (constant-time).
  4. Dedup on ``X-Initiative-Event-ID`` so retries don't double-fire.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import _origin_of
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)


_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)
#: The most one delivery may take, end to end, and the most of a receiver's
#: answer it reads: only the status is used.
_DEADLINE_SECONDS = 15.0
_MAX_RESPONSE_BYTES = 1024 * 1024


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``timestamp + "." + body`` matching what the
    receiver will compute. The timestamp is included so a resigned
    replay of a captured body fails the signature check (the timestamp
    differs)."""
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(body)
    return f"sha256={mac.hexdigest()}"


async def deliver(
    *,
    target_url: str,
    secret: str,
    envelope: dict[str, Any],
) -> bool:
    """POST one envelope to one target. Returns whether it was accepted.

    Logs and swallows any error so one bad subscriber can't break the rest of
    the dispatch. The boolean is what the poller advances a cursor on: a row is
    only considered drained once its target answered 2xx, so a failed delivery
    is retried on a later pass instead of being lost.

    Delivery goes through :func:`request_public_target`, which resolves
    the target host once and connects to that validated address. The
    target is re-checked here (not only at create/update time) because a
    hostname's resolution can change between registration and delivery.
    """
    body = json.dumps(envelope, default=str, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = _sign(secret, timestamp, body)

    headers = {
        "Content-Type": "application/json",
        "X-Initiative-Event-ID": envelope["event_id"],
        "X-Initiative-Timestamp": timestamp,
        "X-Initiative-Signature": signature,
        "User-Agent": "initiative-webhooks/1",
    }

    # Lines below name the delivery by its event id and the target's origin.
    origin = _origin_of(target_url)

    try:
        answer = await asyncio.wait_for(
            request_public_target(
                "POST",
                target_url,
                headers=headers,
                content=body,
                timeout=_TIMEOUT,
                max_bytes=_MAX_RESPONSE_BYTES,
            ),
            timeout=_DEADLINE_SECONDS,
        )
        status_code: int | None = answer.status_code
    except ResponseTooLargeError as exc:
        # Only the status is read, and it arrived before the body did.
        status_code = exc.status_code
    except (WebhookTargetUrlError, WebhookTargetUrlPrivateError) as exc:
        logger.warning(
            "webhook delivery skipped — target failed validation: "
            "origin=%s event=%s err=%s",
            origin,
            envelope.get("event_id"),
            type(exc).__name__,
        )
        return False
    except Exception as exc:  # best-effort delivery
        logger.warning(
            "webhook delivery failed: origin=%s event=%s err=%s",
            origin,
            envelope.get("event_id"),
            type(exc).__name__,
        )
        return False

    # Accepted means 2xx and nothing else. A redirect is not a delivery — the
    # request is pinned to a validated address and not followed, so treating 3xx
    # as success would drop the batch from retry without a receiver ever having
    # seen it.
    if status_code is None or not 200 <= status_code < 300:
        logger.warning(
            "webhook delivery not accepted: origin=%s event=%s status=%s",
            origin,
            envelope.get("event_id"),
            status_code,
        )
        return False

    return True
