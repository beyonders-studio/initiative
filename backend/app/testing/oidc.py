"""A fake OIDC IdP for tests: discovery, JWKS, token, and userinfo endpoints
served through an ``httpx.MockTransport``.

Lets both the unit tests of the relying-party flow and the endpoint tests of
the login/callback routes exercise the full begin → callback → verified-claims
path with real RSA-signed id_tokens and no network. Shared here so the two
suites drive one fake rather than drifting copies.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://idp.example.com"
CLIENT_ID = "client-123"

# Generated once at import: keygen is the slow part, and every test can share
# the same keypair (plus a second one for wrong-key signature tests).
IDP_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def private_key_pem(priv=IDP_KEY) -> str:
    return priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def jwks_doc(priv=IDP_KEY, kid: str = "k1") -> dict:
    data = json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    data.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return {"keys": [data]}


def mint_id_token(
    *,
    nonce: str,
    priv=IDP_KEY,
    kid: str = "k1",
    issuer: str = ISSUER,
    audience: str = CLIENT_ID,
    **claim_overrides,
) -> str:
    """A signed id_token with sane defaults; override any claim by keyword.
    Passing ``None`` for a claim removes it from the token entirely."""
    now = datetime.now(UTC)
    claims = {
        "iss": issuer,
        "sub": "idp-subject-1",
        "aud": audience,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": nonce,
        "email": "alice@example.com",
    }
    claims.update(claim_overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(
        claims, private_key_pem(priv), algorithm="RS256", headers={"kid": kid}
    )


class FakeIdp:
    """Routes discovery/JWKS/token/userinfo requests; records what it saw.

    ``algs`` fills ``id_token_signing_alg_values_supported``; ``None`` means the
    discovery document omits the field entirely (an immutable tuple default —
    do not "fix" it to ``None``, which has that distinct meaning).

    ``userinfo_claims`` — when not ``None``, discovery advertises a
    ``userinfo_endpoint`` and the fake serves these claims from it (the bearer
    token each request presented is recorded in ``userinfo_bearer_tokens``).
    """

    def __init__(
        self,
        *,
        algs: tuple[str, ...] | None = ("RS256", "ES256"),
        userinfo_claims: dict | None = None,
    ):
        doc: dict[str, object] = {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks",
        }
        if algs is not None:
            doc["id_token_signing_alg_values_supported"] = list(algs)
        if userinfo_claims is not None:
            doc["userinfo_endpoint"] = f"{ISSUER}/userinfo"
        self.discovery_doc = doc
        self.jwks_doc = jwks_doc()
        # A fixed httpx.Response, or a callable building one from the parsed form.
        self.token_response: (
            httpx.Response | Callable[[dict[str, str]], httpx.Response] | None
        ) = None
        self.token_request_form: dict[str, str] = {}
        self.userinfo_claims = userinfo_claims
        # Override to simulate a userinfo failure (takes precedence over claims).
        self.userinfo_response: httpx.Response | None = None
        self.userinfo_bearer_tokens: list[str] = []
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        path = request.url.path
        self.calls.append(path)
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=self.discovery_doc)
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks_doc)
        if path == "/token":
            form = parse_qs(request.content.decode())
            self.token_request_form = {k: v[0] for k, v in form.items()}
            resp = self.token_response
            if resp is None:
                return httpx.Response(500, text="test did not set token_response")
            if isinstance(resp, httpx.Response):
                return resp
            return resp(self.token_request_form)
        if path == "/userinfo":
            self.userinfo_bearer_tokens.append(request.headers.get("Authorization", ""))
            if self.userinfo_response is not None:
                return self.userinfo_response
            if self.userinfo_claims is not None:
                return httpx.Response(200, json=self.userinfo_claims)
            return httpx.Response(404)
        return httpx.Response(404)

    def client_factory(self):
        transport = httpx.MockTransport(self.handler)
        return lambda: httpx.AsyncClient(transport=transport)
