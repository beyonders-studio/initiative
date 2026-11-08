"""Unit tests for the webhook dispatcher's signature.

Given a known secret and known body, the signature is deterministic and
verifies.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from app.services.tenant.webhook_dispatcher import _sign


def _verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """What the receiver does on its side. Re-implementing here so the
    tests don't depend on shared receiver code."""
    expected = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    expected.update(timestamp.encode("utf-8"))
    expected.update(b".")
    expected.update(body)
    return hmac.compare_digest(f"sha256={expected.hexdigest()}", signature)


def test_sign_is_deterministic_for_same_inputs():
    """Two signatures over the same (secret, timestamp, body) must
    match — load-bearing for the receiver's verification."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000000", b'{"a":1}')
    assert sig1 == sig2
    assert sig1.startswith("sha256=")


def test_sign_differs_when_body_changes():
    """Even a single-byte body change must produce a different signature."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000000", b'{"a":2}')
    assert sig1 != sig2


def test_sign_differs_when_timestamp_changes():
    """Timestamp is part of the signed input so a valid (body, sig) pair
    captured at T can't be re-presented at T+ seconds later — the
    receiver re-computes with the *new* timestamp and the signature
    won't match."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000001", b'{"a":1}')
    assert sig1 != sig2


def test_sign_round_trips_through_verifier():
    """Signing then verifying must succeed for the same inputs."""
    secret = "shared-with-receiver"
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = json.dumps({"event_type": "task.created"}).encode()

    sig = _sign(secret, timestamp, body)
    assert _verify_signature(secret, timestamp, body, sig)


def test_verifier_rejects_wrong_secret():
    """A receiver with the wrong secret must NOT verify successfully —
    that's the entire point of HMAC."""
    timestamp = "1748000000"
    body = b'{"event_type":"task.created"}'

    sig = _sign("real-secret", timestamp, body)
    assert not _verify_signature("attacker-guess", timestamp, body, sig)


async def test_a_delivery_is_judged_by_its_status_within_its_deadline(monkeypatch):
    """A receiver that never finishes answering counts as a failed delivery,
    left for a later pass; one that accepts with a long answer is accepted."""
    import asyncio

    from app.services.safe_http import ResponseTooLargeError
    from app.services.tenant import webhook_dispatcher

    async def _stalled(*_args, **_kwargs):
        await asyncio.sleep(60)

    async def _long_answer(*_args, **_kwargs):
        raise ResponseTooLargeError(1, status_code=200)

    monkeypatch.setattr(webhook_dispatcher, "_DEADLINE_SECONDS", 0.05)
    delivery = {
        "target_url": "https://hooks.example.com/in",
        "secret": "s",
        "envelope": {"event_id": "e1"},
    }

    monkeypatch.setattr(webhook_dispatcher, "request_public_target", _stalled)
    assert await webhook_dispatcher.deliver(**delivery) is False

    monkeypatch.setattr(webhook_dispatcher, "request_public_target", _long_answer)
    assert await webhook_dispatcher.deliver(**delivery) is True
