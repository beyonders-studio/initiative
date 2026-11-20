"""The webhook dispatcher's signature and delivery verdict."""

from __future__ import annotations

import hashlib
import hmac

from app.services.tenant.webhook_dispatcher import _sign


def test_the_signature_is_an_hmac_of_the_timestamp_and_body():
    """The receiver recomputes HMAC-SHA256 over ``timestamp.body`` with the
    shared secret, so the timestamp and every byte of the body are signed."""
    expected = hmac.new(b"topsecret", b'1748000000.{"a":1}', hashlib.sha256)

    assert _sign("topsecret", "1748000000", b'{"a":1}') == (
        f"sha256={expected.hexdigest()}"
    )
    assert _sign("topsecret", "1748000001", b'{"a":1}') != _sign(
        "topsecret", "1748000000", b'{"a":1}'
    )


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
