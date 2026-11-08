"""What a look at a provider reports, and what it keeps to itself."""

import httpx2

from app.core.messages import AuthProviderMessages
from app.services.auth import provider_probe
from app.services.auth.oidc.discovery import OidcDiscovery
from app.testing.oidc import ISSUER, FakeIdp


def _discovery(idp: FakeIdp) -> OidcDiscovery:
    return provider_probe.fresh_discovery(client_factory=idp.client_factory())


def _discovery_from(handler) -> OidcDiscovery:
    return provider_probe.fresh_discovery(
        client_factory=lambda: httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        )
    )


async def test_reports_the_endpoints_it_found():
    idp = FakeIdp()

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    assert result.ok is True
    assert result.error_code is None
    assert result.issuer == ISSUER
    assert result.authorization_endpoint == f"{ISSUER}/authorize"
    assert result.token_endpoint == f"{ISSUER}/token"
    assert result.jwks_uri == f"{ISSUER}/jwks"
    assert result.signing_algs == ["RS256", "ES256"]


async def test_reports_what_the_provider_says_it_offers():
    idp = FakeIdp()
    idp.discovery_doc["scopes_supported"] = ["openid", "email", "profile", "groups"]
    idp.discovery_doc["claims_supported"] = ["sub", "email", "groups"]

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    assert result.scopes_supported == ["openid", "email", "profile", "groups"]
    assert result.claims_supported == ["sub", "email", "groups"]


async def test_a_provider_listing_nothing_costs_only_the_suggestions():
    idp = FakeIdp()

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    assert result.ok is True
    assert result.scopes_supported == []
    assert result.claims_supported == []


async def test_a_malformed_offer_is_dropped_not_refused():
    idp = FakeIdp()
    # Advisory fields only steer a form, so something unexpected here costs a
    # suggestion rather than the whole document.
    idp.discovery_doc["scopes_supported"] = "openid email"
    idp.discovery_doc["claims_supported"] = [1, None, "groups"]

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    assert result.ok is True
    assert result.scopes_supported == []
    assert result.claims_supported == ["groups"]


async def test_a_pasted_well_known_url_is_trimmed():
    idp = FakeIdp()

    result = await provider_probe.probe_issuer(
        f"{ISSUER}/.well-known/openid-configuration",
        discovery=_discovery(idp),
    )

    assert result.ok is True
    assert result.issuer == ISSUER


async def test_nothing_answering_says_unreachable():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    result = await provider_probe.probe_issuer(
        ISSUER, discovery=_discovery_from(handler)
    )

    assert result.ok is False
    assert result.error_code == AuthProviderMessages.DISCOVERY_UNREACHABLE


async def test_a_document_for_another_issuer_says_mismatch():
    idp = FakeIdp()
    idp.discovery_doc["issuer"] = "https://somewhere-else.example.com"

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    assert result.ok is False
    assert result.error_code == AuthProviderMessages.DISCOVERY_ISSUER_MISMATCH


async def test_a_document_missing_an_endpoint_says_invalid():
    idp = FakeIdp()
    del idp.discovery_doc["token_endpoint"]

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    assert result.ok is False
    assert result.error_code == AuthProviderMessages.DISCOVERY_INVALID


async def test_an_upstream_error_body_is_not_reported_back():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            500, json={"internal": "db host pg-01.internal refused the connection"}
        )

    result = await provider_probe.probe_issuer(
        ISSUER, discovery=_discovery_from(handler)
    )

    # A code and nothing else: no status, no body, nothing named in the result.
    assert result.ok is False
    assert result.error_code == AuthProviderMessages.DISCOVERY_UNREACHABLE
    assert result.issuer is None
    assert "pg-01" not in repr(result)
    assert "500" not in repr(result)


async def test_each_probe_looks_again():
    idp = FakeIdp()
    discovery = _discovery(idp)

    await provider_probe.probe_issuer(ISSUER, discovery=discovery)
    await provider_probe.probe_issuer(ISSUER, discovery=discovery)

    # Testing a saved provider has to report what answers now, so a second
    # look is a second request rather than the first one's answer again.
    assert idp.calls.count("/.well-known/openid-configuration") == 2


async def test_reports_where_the_callback_will_be():
    idp = FakeIdp()

    result = await provider_probe.probe_issuer(ISSUER, discovery=_discovery(idp))

    # Computed from the deployment's own APP_URL, because it has to match the
    # finished provider's callback exactly at the far end.
    assert result.callback_url_template.endswith("/auth/{slug}/callback")


async def test_reports_the_callback_even_when_nothing_answered():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    result = await provider_probe.probe_issuer(
        ISSUER, discovery=_discovery_from(handler)
    )

    # Somebody whose address did not answer is still mid-setup.
    assert result.ok is False
    assert result.callback_url_template.endswith("/auth/{slug}/callback")
