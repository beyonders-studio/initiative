"""The signed request envelope between Initiative and billing.

Each side signs its own requests with its own Ed25519 key, and verifies the
other's with the public half. Nothing secret is shared across the boundary.
The signature is a compact JWS in ``Authorization: Bearer``, binding:

* ``iss`` and ``aud``: who sent it, and for whom;
* ``htm``, ``htp``: the method and the path (never the query);
* ``bsh``: the SHA-256 of the exact body bytes, base64url without padding;
* ``iat`` and ``exp``: at most :data:`MAX_LIFETIME_SECONDS` apart;
* ``jti``: one use, burned by the receiver.

The header's ``typ`` is pinned to :data:`TYP`, so no other token this
deployment or billing signs reads as an envelope.

Billing holds the same definition (``billing/boundary/envelope.py`` in
initiative-billing); the two are kept to one shape by the constants below,
which are not deployment knobs. There's no crypto of our own: PyJWT's EdDSA
over PyCA, and :func:`verify` passes PyJWT the one algorithm the key allows,
never the token's.
"""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt

from app.core.security import PUBLIC_KEY_JWT_ALGORITHM, sign_eddsa

#: The longest an envelope may live.
MAX_LIFETIME_SECONDS = 60
#: Clock difference allowed between the two services.
LEEWAY_SECONDS = 10
TYP = "initiative-boundary+jwt"

BILLING = "initiative-billing"
INITIATIVE = "initiative"
#: The audience of billing's requests to Initiative.
TO_INITIATIVE = "initiative:billing-boundary"
#: The audience of Initiative's pings to billing.
TO_BILLING = "initiative-billing:boundary"
#: The audience of Initiative's signed reads from billing.
TO_BILLING_READS = "initiative-billing:reads"

_REQUIRED = ["iss", "aud", "iat", "exp", "jti", "htm", "htp", "bsh"]
#: The blocklist's column width.
MAX_JTI_LENGTH = 64


class EnvelopeRefused(ValueError):
    """The envelope doesn't verify; ``code`` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Verified:
    issuer: str
    jti: str
    #: The last moment the envelope is accepted (``exp`` plus the leeway).
    expires_at: datetime


def body_hash(body: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()


def sign(
    private_pem: str,
    kid: str | None,
    *,
    issuer: str,
    audience: str,
    method: str,
    path: str,
    body: bytes,
) -> str:
    """The envelope for one request, signed with ``private_pem``."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + MAX_LIFETIME_SECONDS,
        "jti": uuid.uuid4().hex,
        "htm": method.upper(),
        "htp": path,
        "bsh": body_hash(body),
    }
    return sign_eddsa(claims, private_pem, kid, typ=TYP)


def verify(
    token: str,
    *,
    keys: tuple[Any, ...],
    issuer: str,
    audience: str,
    method: str,
    path: str,
    body: bytes,
) -> Verified:
    """The envelope's claims, if it was signed by one of ``keys`` for this
    request; :class:`EnvelopeRefused` otherwise. The ``jti`` is the caller's
    to burn."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise EnvelopeRefused("BOUNDARY_MALFORMED") from None
    if header.get("typ") != TYP:
        raise EnvelopeRefused("BOUNDARY_WRONG_TYPE")
    claims: dict[str, Any] | None = None
    expired = False
    for key in keys:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[PUBLIC_KEY_JWT_ALGORITHM],
                audience=audience,
                issuer=issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": _REQUIRED},
            )
            break
        except jwt.ExpiredSignatureError:
            expired = True
        except jwt.PyJWTError:
            continue
    if claims is None:
        raise EnvelopeRefused("BOUNDARY_EXPIRED" if expired else "BOUNDARY_INVALID")
    if int(claims["exp"]) - int(claims["iat"]) > MAX_LIFETIME_SECONDS:
        raise EnvelopeRefused("BOUNDARY_LIFETIME")
    if claims["htm"] != method.upper() or claims["htp"] != path:
        raise EnvelopeRefused("BOUNDARY_WRONG_REQUEST")
    if claims["bsh"] != body_hash(body):
        raise EnvelopeRefused("BOUNDARY_WRONG_BODY")
    jti = str(claims["jti"])
    if not jti or len(jti) > MAX_JTI_LENGTH:
        raise EnvelopeRefused("BOUNDARY_INVALID")
    return Verified(
        issuer=str(claims["iss"]),
        jti=jti,
        # The last moment it's accepted, leeway included: its jti is kept
        # until then, so it can't be presented again in the leeway.
        expires_at=datetime.fromtimestamp(int(claims["exp"]) + LEEWAY_SECONDS, tz=UTC),
    )
