"""Initiative's requests to billing: the ping, and the reads.

Pinned properties:

* FOSS gating — with billing unconfigured (the self-host default) nothing is
  sent;
* the ping carries nothing: an empty body, signed in the v2 envelope with
  Initiative's handoff key under ``initiative-billing:boundary``;
* a read carries only the community's reference, signed the same way under
  ``initiative-billing:reads``, and its answer is taken only when it holds;
* a failing billing service never surfaces into the caller.
"""

from __future__ import annotations

import base64
import json

import httpx2
import pytest

from app.core.security import load_verification_keys
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform import billing_envelope as envelope
from app.services.platform import billing_ping
from app.services.platform.identity_refs import existing_ref
from app.testing import create_guild
from app.testing.billing_boundary import (
    OTHER_PRIVATE_PEM,
    OTHER_PUBLIC_PEM,
    configure_outbound,
)


@pytest.fixture
def billing_configured(monkeypatch):
    configure_outbound(monkeypatch, "https://billing.internal")


def _verify(request: httpx2.Request, *, audience: str) -> envelope.Verified:
    """The request's envelope, verified as billing verifies it."""
    scheme, _, token = request.headers["Authorization"].partition(" ")
    assert scheme == "Bearer"
    return envelope.verify(
        token,
        keys=load_verification_keys(OTHER_PUBLIC_PEM),
        issuer=envelope.INITIATIVE,
        audience=audience,
        method=request.method,
        path=request.url.path,
        body=request.content,
    )


def test_an_envelope_is_kept_spent_until_its_leeway_ends():
    """Its jti is kept until ``expires_at``, so that is the last moment it's
    accepted, leeway included: never ``exp`` itself."""
    token = envelope.sign(
        OTHER_PRIVATE_PEM,
        None,
        issuer=envelope.INITIATIVE,
        audience=envelope.TO_BILLING,
        method="POST",
        path="/ping",
        body=b"",
    )
    seen = envelope.verify(
        token,
        keys=load_verification_keys(OTHER_PUBLIC_PEM),
        issuer=envelope.INITIATIVE,
        audience=envelope.TO_BILLING,
        method="POST",
        path="/ping",
        body=b"",
    )
    exp = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==").decode())[
        "exp"
    ]
    assert seen.expires_at.timestamp() == exp + envelope.LEEWAY_SECONDS


def test_disabled_by_default():
    assert billing_ping.billing_ping_enabled() is False


_REAL_ASYNC_CLIENT = httpx2.AsyncClient


def _answering(monkeypatch, handler):
    seen: list[httpx2.Request] = []

    def _recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx2.MockTransport(_recording)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(billing_ping.httpx2, "AsyncClient", _client)
    return seen


@pytest.fixture
def known_ref(monkeypatch):
    async def _existing_ref(**kwargs):
        return "gbil_known"

    monkeypatch.setattr(billing_ping, "existing_ref", _existing_ref)


_SUMMARY = {
    "tier_name": "Gold",
    "trial_ends_on": None,
    "renews_on": "2026-11-01",
    "next_charge": {"total": 1250, "currency": "USD"},
    "scheduled_change": {"action": "cancel", "on": "2026-11-01"},
    "payment_failed": False,
}


@pytest.mark.parametrize(
    "response,failed",
    [
        (httpx2.Response(200, json={**_SUMMARY, "payment_failed": True}), True),
        (httpx2.Response(200, json=_SUMMARY), False),
        (httpx2.Response(200, json={**_SUMMARY, "payment_failed": "true"}), False),
        (httpx2.Response(500, json={**_SUMMARY, "payment_failed": True}), False),
    ],
)
async def test_payment_failed_is_the_plan_summary_flag(
    billing_configured, known_ref, monkeypatch, response, failed
):
    """Read from the plan summary: a summary billing cannot give says no."""
    seen = _answering(monkeypatch, lambda r: response)
    assert await billing_ping.guild_payment_failed(7) is failed
    (request,) = seen
    assert str(request.url) == "https://billing.internal/api/v1/plan-summary"


async def test_plan_summary_unconfigured_makes_no_call(monkeypatch, known_ref):
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json=_SUMMARY))
    assert await billing_ping.guild_plan_summary(7) is None
    assert seen == []


async def test_plan_summary_without_a_ref_is_empty_and_mints_nothing(
    session, billing_configured, monkeypatch
):
    guild = await create_guild(session)
    await session.commit()
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json=_SUMMARY))
    assert await billing_ping.guild_plan_summary(guild.id) == (
        billing_ping.PlanSummary()
    )
    assert seen == []
    assert (
        await existing_ref(
            entity_type=IdentityEntity.guild,
            entity_id=guild.id,
            purpose=IdentityPurpose.billing,
        )
        is None
    )


async def test_plan_summary_sends_only_the_ref_signed(
    billing_configured, known_ref, monkeypatch
):
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json=_SUMMARY))
    summary = await billing_ping.guild_plan_summary(7)
    assert summary is not None
    # A billing that doesn't say what its portal offers yet reads as the plan
    # every community starts on: plans above it, nothing to cancel.
    assert summary.model_dump(mode="json") == {
        **_SUMMARY,
        "can_upgrade": True,
        "can_cancel": False,
    }
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://billing.internal/api/v1/plan-summary"
    body = request.content
    assert json.loads(body) == {"community_ref": "gbil_known"}
    _verify(request, audience=envelope.TO_BILLING_READS)


async def test_plan_summary_ignores_fields_it_does_not_know(
    billing_configured, known_ref, monkeypatch
):
    _answering(
        monkeypatch,
        lambda r: httpx2.Response(200, json={**_SUMMARY, "later": "field"}),
    )
    summary = await billing_ping.guild_plan_summary(7)
    assert summary is not None and summary.tier_name == "Gold"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json={**_SUMMARY, "payment_failed": "true"}),
        httpx2.Response(200, json={**_SUMMARY, "renews_on": "next month"}),
        httpx2.Response(200, json={**_SUMMARY, "renews_on": 20261101}),
        httpx2.Response(
            200, json={**_SUMMARY, "next_charge": {"total": "12.50", "currency": "USD"}}
        ),
        httpx2.Response(
            200, json={**_SUMMARY, "next_charge": {"total": -1, "currency": "USD"}}
        ),
        httpx2.Response(
            200, json={**_SUMMARY, "next_charge": {"total": 1250, "currency": "usd"}}
        ),
        httpx2.Response(
            200,
            json={**_SUMMARY, "scheduled_change": {"action": "x", "on": "2026-11-01"}},
        ),
        httpx2.Response(200, json={**_SUMMARY, "tier_name": "x" * 65}),
        httpx2.Response(200, json=[_SUMMARY]),
        httpx2.Response(200, content=b"not json"),
        httpx2.Response(200, json={**_SUMMARY, "pad": "x" * 1100}),
        httpx2.Response(302, headers={"Location": "https://elsewhere"}),
        httpx2.Response(500, json=_SUMMARY),
    ],
)
async def test_plan_summary_anything_malformed_is_none(
    billing_configured, known_ref, monkeypatch, response
):
    _answering(monkeypatch, lambda r: response)
    assert await billing_ping.guild_plan_summary(7) is None


async def test_plan_summary_unreachable_is_none(
    billing_configured, known_ref, monkeypatch
):
    def _down(request):
        raise httpx2.ConnectError("down")

    _answering(monkeypatch, _down)
    assert await billing_ping.guild_plan_summary(7) is None


async def test_the_ping_is_empty_and_signed(billing_configured, monkeypatch):
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json={"ok": True}))
    await billing_ping.nudge()
    (request,) = seen
    assert str(request.url) == "https://billing.internal/api/v1/pings"
    assert request.content == b"{}"
    _verify(request, audience=envelope.TO_BILLING)
    # A read's audience doesn't open the ping's door, nor the other way round.
    with pytest.raises(envelope.EnvelopeRefused):
        _verify(request, audience=envelope.TO_BILLING_READS)


async def test_the_ping_is_a_noop_unconfigured(monkeypatch):
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200))
    await billing_ping.nudge()
    assert seen == []


async def test_a_failing_ping_never_raises(billing_configured, monkeypatch):
    def _down(request):
        raise httpx2.ConnectError("down")

    _answering(monkeypatch, _down)
    await billing_ping.nudge()


_OFFER = {
    "charge": "subscription",
    "way": "buy",
    "upgrade": False,
    "lines": [
        {"id": "hoard-small", "name": "Small", "display": "$12/mo"},
        {"id": "hoard-large", "name": "Large", "display": None},
    ],
}


async def test_plugin_offer_sends_the_ref_listing_and_locale_signed(
    billing_configured, known_ref, monkeypatch
):
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json=_OFFER))
    offer = await billing_ping.plugin_offer(7, listing_uid="hoard", locale="de")
    assert offer is not None
    assert offer.model_dump(mode="json") == _OFFER
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://billing.internal/api/v1/plugin-offer"
    assert json.loads(request.content) == {
        "community_ref": "gbil_known",
        "listing_uid": "hoard",
        "locale": "de",
    }
    _verify(request, audience=envelope.TO_BILLING_READS)


async def test_plugin_offer_unconfigured_makes_no_call(monkeypatch, known_ref):
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json=_OFFER))
    assert await billing_ping.plugin_offer(7, listing_uid="hoard", locale="en") is None
    assert seen == []


async def test_plugin_offer_without_a_ref_asks_nothing(
    session, billing_configured, monkeypatch
):
    guild = await create_guild(session)
    await session.commit()
    seen = _answering(monkeypatch, lambda r: httpx2.Response(200, json=_OFFER))
    assert (
        await billing_ping.plugin_offer(guild.id, listing_uid="hoard", locale="en")
        is None
    )
    assert seen == []


@pytest.mark.parametrize(
    "response",
    [
        # A listing billing doesn't sell as an app of its own.
        httpx2.Response(404, json={"detail": "OFFER_UNKNOWN_LISTING"}),
        httpx2.Response(500, json=_OFFER),
        httpx2.Response(302, headers={"Location": "https://elsewhere"}),
        httpx2.Response(200, json={**_OFFER, "way": "maybe"}),
        httpx2.Response(200, json={**_OFFER, "charge": "weekly"}),
        httpx2.Response(200, json={**_OFFER, "upgrade": "yes"}),
        httpx2.Response(200, json={**_OFFER, "lines": [{"id": "x"}]}),
        httpx2.Response(200, json={**_OFFER, "lines": [{"id": "x", "name": 3}]}),
        httpx2.Response(200, json={**_OFFER, "pad": "x" * 9000}),
        httpx2.Response(200, content=b"not json"),
    ],
)
async def test_plugin_offer_anything_but_an_answer_is_none(
    billing_configured, known_ref, monkeypatch, response
):
    _answering(monkeypatch, lambda r: response)
    assert await billing_ping.plugin_offer(7, listing_uid="hoard", locale="en") is None


async def test_plugin_offer_ignores_fields_it_does_not_know(
    billing_configured, known_ref, monkeypatch
):
    _answering(monkeypatch, lambda r: httpx2.Response(200, json={**_OFFER, "later": 1}))
    offer = await billing_ping.plugin_offer(7, listing_uid="hoard", locale="en")
    assert offer is not None and offer.way == "buy"


async def test_plugin_offer_unreachable_is_none(
    billing_configured, known_ref, monkeypatch
):
    def _down(request):
        raise httpx2.ConnectError("down")

    _answering(monkeypatch, _down)
    assert await billing_ping.plugin_offer(7, listing_uid="hoard", locale="en") is None
