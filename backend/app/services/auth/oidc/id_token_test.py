"""Tests for the OIDC id_token verifier.

For every way a token can be invalid or malformed, assert it is rejected.
Tokens are minted with locally-generated RSA/EC keys (no
network), so the verification logic is exercised in complete isolation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as stdlib_hmac
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.services.auth.oidc.id_token import (
    IdTokenVerificationError,
    verify_id_token,
)

ISSUER = "https://idp.example.com"
AUDIENCE = "client-123"
NONCE = "nonce-abc"

# Sentinel: pass as an override value to DROP that claim entirely.
_DROP = object()


def _pem_private(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _pem_public(key) -> str:
    return key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _rsa_keypair() -> tuple[str, str]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _pem_private(priv), _pem_public(priv.public_key())


def _ec_keypair() -> tuple[str, str]:
    priv = ec.generate_private_key(ec.SECP256R1())
    return _pem_private(priv), _pem_public(priv.public_key())


# One keypair per family, generated once for the module.
RSA_PRIV, RSA_PUB = _rsa_keypair()
EC_PRIV, EC_PUB = _ec_keypair()


def _rsa_pyjwk() -> jwt.PyJWK:
    """A ``PyJWK`` for ``RSA_PUB`` — the key type the production ``PyJWKClient``
    path hands to the verifier, and the type CVE-2026-48523 (alg-allowlist bypass
    with a PyJWK key, fixed in PyJWT 2.13.0) concerned."""
    from jwt.algorithms import RSAAlgorithm

    pub_obj = serialization.load_pem_public_key(RSA_PUB.encode())
    data = json.loads(RSAAlgorithm.to_jwk(pub_obj))
    data["alg"] = "RS256"
    data.setdefault("use", "sig")
    return jwt.PyJWK.from_dict(data)


def _claims(**overrides) -> dict:
    now = datetime.now(UTC)
    base = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": NONCE,
    }
    for key, value in overrides.items():
        if value is _DROP:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def _encode(claims: dict, *, priv: str = RSA_PRIV, alg: str = "RS256") -> str:
    return jwt.encode(claims, priv, algorithm=alg)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forge_hs256(claims: dict, secret: str) -> str:
    """Hand-roll an HS256 token with ``secret`` as the HMAC key.

    Done manually because PyJWT's ``encode`` refuses to HMAC-sign with a PEM
    public key — we need the token to exist so the *verifier's*
    asymmetric-only allowlist is what rejects it. Claims use
    integer timestamps so they're plain-JSON serializable.
    """
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{body}"
    sig = stdlib_hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url(sig)}"


def _verify(token: str, **overrides):
    kwargs = {
        "signing_key": RSA_PUB,
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "nonce": NONCE,
    }
    kwargs.update(overrides)
    return verify_id_token(token, **kwargs)


# --- happy paths ------------------------------------------------------------


def test_valid_rs256_token_accepted():
    claims = _verify(_encode(_claims()))
    assert claims["sub"] == "user-1"
    assert claims["nonce"] == NONCE


def test_valid_es256_token_accepted():
    token = _encode(_claims(), priv=EC_PRIV, alg="ES256")
    claims = _verify(token, signing_key=EC_PUB, algorithms=["ES256"])
    assert claims["sub"] == "user-1"


def test_multi_aud_with_correct_azp_accepted():
    token = _encode(_claims(aud=[AUDIENCE, "other-plugin"], azp=AUDIENCE))
    claims = _verify(token)
    assert claims["azp"] == AUDIENCE


def test_accepts_pyjwk_signing_key():
    """Production key type: PyJWKClient resolves a ``PyJWK``, not a PEM. Verify
    the verifier accepts it and returns the claims."""
    claims = _verify(_encode(_claims()), signing_key=_rsa_pyjwk())
    assert claims["sub"] == "user-1"


def test_pyjwk_signing_key_still_rejects_alg_confusion():
    """Even when the key is a ``PyJWK`` bound to RS256, an HS256 token is
    rejected by our allowlist — the header alg is checked against the allowlist
    regardless of the key object's bound alg."""
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "exp": now + 300,
        "iat": now,
        "nonce": NONCE,
    }
    forged = _forge_hs256(claims, RSA_PUB)
    with pytest.raises(IdTokenVerificationError):
        _verify(forged, signing_key=_rsa_pyjwk())


# --- signature / algorithm -------------------------------------------------


def test_alg_none_rejected():
    """A stripped (unsigned) token must never be accepted."""
    token = jwt.encode(_claims(), key="", algorithm="none")
    with pytest.raises(IdTokenVerificationError):
        _verify(token)


def test_hs256_confusion_rejected():
    """An HS256 token signed with the *public* key as the shared secret.
    HS256 isn't in the asymmetric allowlist, so it's refused before any
    signature check."""
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "exp": now + 300,
        "iat": now,
        "nonce": NONCE,
    }
    forged = _forge_hs256(claims, RSA_PUB)
    with pytest.raises(IdTokenVerificationError):
        _verify(forged)


def test_tampered_signature_rejected():
    token = _encode(_claims())
    header, payload, sig = token.split(".")
    i = len(sig) // 2
    sig = sig[:i] + ("A" if sig[i] != "A" else "B") + sig[i + 1 :]
    with pytest.raises(IdTokenVerificationError):
        _verify(f"{header}.{payload}.{sig}")


def test_token_signed_by_a_different_key_rejected():
    other_priv, _ = _rsa_keypair()
    token = jwt.encode(_claims(), other_priv, algorithm="RS256")
    with pytest.raises(IdTokenVerificationError):
        _verify(token)


def test_token_alg_outside_narrowed_allowlist_rejected():
    """The token's *actual* alg must be in the allowlist — narrowing to ES256
    rejects an RS256 token (not a caller error: ES256 is legal, the token isn't)."""
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims()), algorithms=["ES256"])


# --- claims ----------------------------------------------------------------


def test_expired_token_rejected():
    token = _encode(_claims(exp=datetime.now(UTC) - timedelta(minutes=5)))
    with pytest.raises(IdTokenVerificationError):
        _verify(token)


def test_wrong_audience_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(aud="a-different-client")))


def test_wrong_issuer_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(iss="https://evil.example.com")))


def test_missing_sub_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(sub=_DROP)))


def test_missing_exp_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(exp=_DROP)))


# --- nonce -----------------------------------------------------------------


def test_nonce_mismatch_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(nonce="a-different-nonce")))


def test_missing_nonce_claim_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(nonce=_DROP)))


# --- azp (authorized party) -------------------------------------------------


def test_multi_aud_without_azp_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(aud=[AUDIENCE, "other-plugin"])))


def test_azp_mismatch_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(azp="an-evil-client")))


# --- caller misconfiguration (programming errors → ValueError) --------------
@pytest.mark.parametrize(
    ("kwargs"),
    [
        # An allowlist that names nothing, or names an algorithm this verifier
        # will not accept, is refused before any token is read.
        {"algorithms": []},
        {"algorithms": ["HS256"]},
        {"algorithms": ["none"]},
        # The values every token is checked against cannot themselves be blank.
        {"issuer": ""},
        {"audience": ""},
        {"nonce": ""},
    ],
    ids=lambda k: ",".join(f"{a}={b!r}" for a, b in k.items()),
)
def test_verifying_with_an_unusable_setting_is_a_caller_error(kwargs):
    """These are our misuse, not a bad token, so they surface as ``ValueError``
    rather than as a rejected login."""
    with pytest.raises(ValueError):
        _verify(_encode(_claims()), **kwargs)
