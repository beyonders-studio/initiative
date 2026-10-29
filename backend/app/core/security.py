import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Iterable, Literal, Sequence

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from app.core.config import settings


# ──────────────────────────────────────────────────────────────────────────
# Verifying keys for the services that call us
#
# A peer's signing key has to be replaceable without arranging for both
# sides to change in the same instant, so the settings that hold one take
# concatenated PEM blocks and every block is trusted: append the new key,
# let the peer start signing with it, drop the old block a release later.
# Every block is an Ed25519 key: the one kind of key on any boundary.
# ──────────────────────────────────────────────────────────────────────────

#: Marks the start of each block in a concatenated PEM bundle.
_PEM_HEADER = "-----BEGIN "


class PublicKeyBundleError(Exception):
    """A configured PEM bundle could not be read."""


@lru_cache(maxsize=8)
def load_verification_keys(pem_bundle: str) -> tuple[Any, ...]:
    """Load the public keys in a configured PEM bundle, in order.

    Keyed on the configured text and cached, so a bundle is parsed once rather
    than on every call that verifies against it. A block that will not load
    raises instead of being skipped — a silently dropped block leaves a
    rotation looking configured while the key it added does nothing. So does
    a block that is not an Ed25519 key.
    """
    blocks = [_PEM_HEADER + rest for rest in pem_bundle.split(_PEM_HEADER)[1:]]
    keys: list[ed25519.Ed25519PublicKey] = []
    for index, block in enumerate(blocks):
        try:
            key = load_pem_public_key(block.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise PublicKeyBundleError(
                f"PEM block {index + 1} is not a readable public key: {exc}"
            ) from exc
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise PublicKeyBundleError(f"PEM block {index + 1} is not an Ed25519 key")
        keys.append(key)
    return tuple(keys)


# Deliberately constants, not settings: each signing key has one algorithm.
#: Tokens this deployment both mints and verifies: :func:`sign_hs256` /
#: :func:`verify_hs256`.
JWT_ALGORITHM = "HS256"
#: Tokens another service verifies against the public half of one of our
#: keys (billing handoffs, the support and operator consoles' included, and
#: the envelope on our requests to billing; plug-in context, lifecycle and
#: page handoff tokens), and the tokens we verify from billing:
#: :func:`sign_eddsa`.
#: Ed25519, the one kind of key on any boundary.
PUBLIC_KEY_JWT_ALGORITHM = "EdDSA"

#: ``iss`` on every token this deployment mints that names an issuer. Pinned on
#: both sides of each boundary — not a deployment knob.
TOKEN_ISSUER = "initiative"


def sign_hs256(
    payload: dict[str, Any],
    *,
    key: str | None = None,
    headers: dict[str, Any] | None = None,
) -> str:
    """Sign ``payload`` as an HS256 JWT.

    ``key`` defaults to the deployment's JWT signing key.
    """
    return jwt.encode(
        payload,
        settings.jwt_signing_key if key is None else key,
        algorithm=JWT_ALGORITHM,
        headers=headers,
    )


def verify_hs256(
    token: str,
    *,
    audience: str,
    require: list[str],
    issuer: str | None = None,
) -> dict[str, Any]:
    """Verify an HS256 JWT this deployment signed; return its claims.

    Checks the signature against the JWT signing key, ``exp``, the
    ``audience``, the ``issuer`` when one is given, and that every claim in
    ``require`` is present. Raises :class:`jwt.PyJWTError` on any failure.
    """
    return jwt.decode(
        token,
        settings.jwt_signing_key,
        algorithms=[JWT_ALGORITHM],
        audience=audience,
        issuer=issuer,
        options={"require": require},
    )


def sign_eddsa(
    payload: dict[str, Any],
    private_pem: str,
    kid: str | None,
    *,
    typ: str | None = None,
) -> str:
    """Sign ``payload`` as an EdDSA JWT with an Ed25519 key, for a service
    that verifies it with the public half of ``private_pem``.

    The header carries ``kid`` when there is one, so the receiver picks the
    right key during a rotation, and ``typ`` when the token kind names one.
    """
    headers: dict[str, Any] = {}
    if typ:
        headers["typ"] = typ
    if kid:
        headers["kid"] = kid
    return jwt.encode(
        payload, private_pem, algorithm=PUBLIC_KEY_JWT_ALGORITHM, headers=headers
    )


# Cookie names are part of the auth contract, not deployment configuration.
SESSION_COOKIE_NAME = "session_token"
# The rotating refresh token rides in its own HttpOnly cookie, path-scoped to
# the auth routes (sent only on refresh/logout, never on ordinary API calls —
# smaller exposure than the session cookie).
REFRESH_COOKIE_NAME = "refresh_token"

# The hash schemes ``verify_password`` below can actually check. A stored value
# outside this set — the ``'!'`` marker the 0152 downgrade writes, or anything
# else — never verifies, which makes it the definition of "no usable password"
# for callers that have to ask about a hash without checking one.
ARGON2_HASH_PREFIX = "$argon2"
BCRYPT_HASH_PREFIXES = ("$2a$", "$2b$", "$2y$")
USABLE_HASH_PREFIXES = (ARGON2_HASH_PREFIX, *BCRYPT_HASH_PREFIXES)


def has_usable_password(hashed: str | None) -> bool:
    """Whether a stored hash is one :func:`verify_password` can actually check.

    The question a caller asks when it must know whether an account holds a
    password *without* checking one — re-authenticating before a change, or
    deciding whether there is anything to re-authenticate against at all.

    A value outside :data:`USABLE_HASH_PREFIXES` never verifies, so it is not a
    password: NULL and the ``'!'`` marker a 0152 downgrade writes read the same
    here. The one thing it cannot see is an account provisioned before 0152,
    whose throwaway hash is a real argon2 value — that reads as holding a
    password, which is the conservative direction, and such an account reaches
    itself through password reset.

    The row-level form of the same question is
    ``services.auth.identity._no_usable_password_clause``; both read these
    prefixes, so there is one definition.
    """
    return bool(hashed) and hashed.startswith(USABLE_HASH_PREFIXES)


# argon2id with library defaults — OWASP-aligned. Stored hashes embed the
# parameters, so verification keeps working if we tune these later.
_argon2_hasher = PasswordHasher()

# Sign-in refuses an unknown address, an account without a usable password,
# and a wrong password through one fixed KDF schedule. Neither hash belongs to
# an account; they exist only to fill the unused slot in that schedule.
_SIGN_IN_DUMMY_PASSWORD = "initiative-login-dummy-password"
_SIGN_IN_DUMMY_ARGON2_HASH = _argon2_hasher.hash(_SIGN_IN_DUMMY_PASSWORD)
#: Work factor for the stand-in bcrypt hash below.
#:
#: Pinned rather than taking `bcrypt.gensalt()`'s default, because this number
#: decides what an address with no account costs to probe. Every sign-in pays a
#: bcrypt check so that an unknown address costs the same as a legacy bcrypt
#: account; that equality holds only while this matches the cost those stored
#: hashes carry. Adjacent costs are far apart -- measured here, cost 10 verifies
#: in ~102 ms against ~400 ms for cost 12 -- so inheriting the library default
#: would let a dependency release move it for every legacy account at once,
#: on upgrade, with nothing saying so. 12 is that default today; changing it
#: should be an edit somebody makes on purpose.
SIGN_IN_BCRYPT_COST = 12

_SIGN_IN_DUMMY_BCRYPT_HASH = bcrypt.hashpw(
    _SIGN_IN_DUMMY_PASSWORD.encode("utf-8"), bcrypt.gensalt(SIGN_IN_BCRYPT_COST)
).decode("utf-8")


def get_password_hash(password: str) -> str:
    """Hash a plaintext password using argon2id."""
    return _argon2_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a plaintext password against either an argon2id or legacy bcrypt hash.

    A ``None`` hash means the account has no password (SSO-only) — never a
    match, so every caller gets uniform "incorrect credentials" behavior
    without a separate check. Existing users still have bcrypt hashes from the
    passlib era; those are verified directly with the bcrypt library. The login
    flow rehashes them as argon2id on next successful login (see
    ``password_needs_rehash``).
    """
    if hashed_password is None:
        return False
    if hashed_password.startswith(ARGON2_HASH_PREFIX):
        try:
            _argon2_hasher.verify(hashed_password, plain_password)
            return True
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if hashed_password.startswith(BCRYPT_HASH_PREFIXES):
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except ValueError:
            return False
    return False


def verify_sign_in_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a sign-in while always paying one Argon2 and one bcrypt check.

    The stored credential replaces the dummy for its own scheme. The other
    scheme still runs, and an absent or unsupported credential uses both
    dummies. Only a match against the stored credential can authenticate.
    """
    is_argon2 = bool(hashed_password and hashed_password.startswith(ARGON2_HASH_PREFIX))
    is_bcrypt = bool(
        hashed_password and hashed_password.startswith(BCRYPT_HASH_PREFIXES)
    )
    argon2_hash = hashed_password if is_argon2 else _SIGN_IN_DUMMY_ARGON2_HASH
    bcrypt_hash = hashed_password if is_bcrypt else _SIGN_IN_DUMMY_BCRYPT_HASH

    argon2_matches = verify_password(plain_password, argon2_hash)
    bcrypt_matches = verify_password(plain_password, bcrypt_hash)

    return bool((is_argon2 and argon2_matches) or (is_bcrypt and bcrypt_matches))


def password_needs_rehash(hashed_password: str | None) -> bool:
    """Return True if the stored hash should be rewritten on next successful login.

    Triggers for legacy bcrypt hashes and for argon2 hashes whose parameters
    have drifted from the current PasswordHasher defaults. ``None`` (no
    password set) has nothing to rehash.
    """
    if hashed_password is None:
        return False
    if not hashed_password.startswith(ARGON2_HASH_PREFIX):
        return True
    try:
        return _argon2_hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return True


# ──────────────────────────────────────────────────────────────────────────
# New login model — stateless access token (auth rewrite, Phase 0)
#
# A short-lived JWT that names both the user AND the server-side session
# (``auth_sessions.id``) that backs it, plus the auth methods/providers that
# session satisfied. It is verified locally (no per-request DB hit — the 10k+
# win) and made revocable by its paired refresh token, whose rotation lives in
# ``app.services.auth.sessions``. Its distinct ``aud`` keeps it from being
# confused with the legacy session JWT, the upload token, or the handoff token
# during the dual-verify cutover window (verification lands with the endpoint).
# ──────────────────────────────────────────────────────────────────────────

# Audience/issuer that mark a token as a new-model access credential. The
# session-JWT verification path (added with ``/auth/refresh``) MUST check both,
# and the upload/handoff paths already reject anything carrying this audience.
AUTH_ACCESS_AUDIENCE = "initiative:access"

#: The ``WWW-Authenticate`` challenge for a session that authenticated, but not
#: to the level the guild being addressed asks for — RFC 9470 §3. A protocol
#: constant rather than a message: ``error`` is the part a client matches on,
#: and ``AuthMessages``/``errors.json`` carry what a person reads.
#:
#: RFC 9470 also defines ``acr_values`` and ``max_age``, both optional and both
#: absent here. A community's sign-in requirement names a provider and nothing about
#: assurance or freshness, so there is no value to put in either; they arrive
#: with the columns that hold one (phases E and C2b).
STEP_UP_CHALLENGE = 'Bearer error="insufficient_user_authentication"'

#: Which part of a sign-in rule a refused write did not itself meet, so the
#: page that wrote it can offer the one thing that would: a provider to sign
#: in with, or a factor to present. Named here because two surfaces answer
#: with it — a community's requirement and the deployment's own.
AUTH_POLICY_UNMET_HEADER = "X-Auth-Policy-Unmet"


def mint_access_token(
    *,
    subject: str,
    token_version: int,
    session_id: uuid.UUID,
    amr: list[str],
    satisfied_providers: list[int],
    provider_auth: dict[str, Any] | None = None,
    expires_in: timedelta | None = None,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Mint a short-lived, stateless access token for one session.

    Claims: ``sub`` (the account, named
    by its ``client``-sector reference — ``services.auth.subject``), ``sid``
    (the ``auth_sessions`` row), ``ver`` (``users.token_version`` — coarse "sign
    out everywhere"), ``amr`` (auth methods satisfied), ``sat`` (satisfied-auth
    provider ids → the per-guild auth-policy gate), plus ``iss``/``aud``/
    ``iat``/``exp``. Returns ``(token, expires_in_seconds)`` so the caller can
    schedule a refresh before it lapses.

    ``satd`` joins them when the session has one: each satisfied provider's own
    account of its authentication event, keyed by provider id (see
    ``services.auth.assurance``). Absent when no provider contributed one, so a
    password session's token keeps the shape it always had.
    """
    issued = now or datetime.now(timezone.utc)
    ttl = expires_in or timedelta(minutes=settings.AUTH_ACCESS_TTL_MINUTES)
    payload: dict[str, Any] = {
        "sub": subject,
        "sid": str(session_id),
        "ver": token_version,
        "amr": amr,
        "sat": satisfied_providers,
        "iss": TOKEN_ISSUER,
        "aud": AUTH_ACCESS_AUDIENCE,
        "iat": int(issued.timestamp()),
        "exp": issued + ttl,
    }
    if provider_auth:
        payload["satd"] = provider_auth
    return sign_hs256(payload), int(ttl.total_seconds())


def decode_session_token(token: str) -> dict[str, Any]:
    """Decode a session credential.

    One shape: the access token ``mint_access_token`` issues —
    ``aud=initiative:access`` / ``iss=initiative``, carrying ``sub``, ``ver``
    (the caller checks it against ``users.token_version``) and
    ``sid``/``amr``/``sat``.

    Anything else raises :class:`jwt.PyJWTError`, which every call site maps to
    401. That covers the scoped credentials — an upload or handoff token
    carries its own ``aud`` — and the pre-session JWT this accepted until
    0.69.0, whose holder renews through the refresh cookie and carries on.
    """
    return verify_hs256(
        token,
        audience=AUTH_ACCESS_AUDIENCE,
        issuer=TOKEN_ISSUER,
        require=["exp", "sub", "ver", "aud", "iss"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Scoped upload tokens
#
# Native (Capacitor) WebViews can't attach an Authorization header or send the
# HttpOnly session cookie to <img>/<iframe> media loads, so the URL has to carry
# the credential as a ``?token=`` query param. The 7-day session JWT never goes
# in a URL; instead the app mints one of these: a short-lived, uploads-only JWT
# that the /uploads route (and file download routes) accept via ``?token=``
# but that is useless for any other API call (it carries no ``ver`` and a distinct
# ``aud``/``scope``, so ``get_current_user`` rejects it).
# ──────────────────────────────────────────────────────────────────────────

# Audience + scope claims that mark a token as a scoped upload credential. The
# uploads auth dependency MUST verify both before honoring a query-param token,
# and the general session-JWT path MUST reject any token carrying this audience.
UPLOAD_TOKEN_AUDIENCE = "initiative:uploads"
UPLOAD_TOKEN_SCOPE = "uploads"

# Short lifetime: long enough to render a page's worth of media after the SPA
# fetches one, short enough that a copy kept in history or a log expires soon.
# The SPA refreshes it transparently when it expires.
UPLOAD_TOKEN_LIFETIME = timedelta(minutes=10)


class UploadTokenError(Exception):
    """Raised when a presented upload token fails verification."""


class UploadTokenClaims(BaseModel):
    """What an upload token carries, copied from the session that minted it.

    Validated from the token's claims by their wire names: ``sub`` the user
    id, ``sat`` the satisfied provider ids, ``satc`` what those providers
    asserted, ``amr`` the markers the minting session recorded about how it
    was opened, and ``scope``, which names the uploads scope.
    """

    model_config = ConfigDict(frozen=True)

    user_id: int = Field(validation_alias="sub")
    satisfied: frozenset[int] = Field(frozenset(), validation_alias="sat")
    claims: dict[str, Any] = Field({}, validation_alias="satc")
    #: Narrowed again by the caller against the closed vocabulary: what a
    #: token says about itself is not what decides which markers count.
    markers: frozenset[str] = Field(frozenset(), validation_alias="amr")
    scope: Literal["uploads"]

    @field_validator("satisfied", "claims", "markers", mode="before")
    @classmethod
    def _null_reads_as_empty(cls, value: Any, info: ValidationInfo) -> Any:
        if value is not None:
            return value
        return {} if info.field_name == "claims" else ()


def create_upload_token(
    *,
    user_id: int,
    satisfied_providers: Sequence[int] = (),
    satisfied_claims: dict | None = None,
    session_amr: Iterable[str] = (),
    expires_in: timedelta = UPLOAD_TOKEN_LIFETIME,
    not_after: datetime | None = None,
) -> tuple[str, int]:
    """Mint a short-lived, uploads-scoped JWT for ``user_id``.

    Returns ``(token, expires_in_seconds)`` so the SPA can schedule a refresh
    before the token lapses. Signed with the same HS256 JWT key as the session
    JWT but distinguished by its ``aud``/``scope`` claims and the absence of
    ``ver`` — the general auth path will not accept it.

    ``satisfied_providers`` copies the minting session's ``sat`` claim, and
    ``satisfied_claims`` what those providers asserted, so a download or
    keepalive in a guild with a requirement carries the same standing as the
    session that requested it (bounded by this token's short lifetime).

    ``not_after`` is the latest the token may stand, whatever ``expires_in``
    says: the expiry of the credential that asked for it.
    """
    now = datetime.now(timezone.utc)
    expires = now + expires_in
    if not_after is not None:
        expires = min(expires, not_after)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": UPLOAD_TOKEN_AUDIENCE,
        "scope": UPLOAD_TOKEN_SCOPE,
        "sat": [int(pid) for pid in satisfied_providers],
        "satc": dict(satisfied_claims or {}),
        # Copied from the minting session like the two above, so a community
        # that asks how somebody signed in gets the same answer from an upload
        # as from the session that asked for it.
        "amr": sorted(session_amr),
        "iat": int(now.timestamp()),
        "exp": expires,
    }
    return sign_hs256(payload), max(0, int((expires - now).total_seconds()))


def verify_upload_token(token: str) -> UploadTokenClaims:
    """Verify a scoped upload token and return what it carries.

    Raises :class:`UploadTokenError` on any failure (bad signature, expired,
    wrong audience, missing/extra-scoped claims). The caller treats that as
    "this isn't a valid upload token" and 401s — it never falls back to
    accepting it as a session credential.
    """
    try:
        payload = verify_hs256(
            token,
            audience=UPLOAD_TOKEN_AUDIENCE,
            require=["exp", "iat", "sub", "aud"],
        )
        return UploadTokenClaims.model_validate(payload)
    except (jwt.PyJWTError, ValidationError) as exc:
        raise UploadTokenError(str(exc)) from exc


HANDLE_OFFER_AUDIENCE = "initiative:handle-offer"
#: How long a number shown beside a name stays the one an account gets: long
#: enough to outlast a sign-up left open, since it is used only while free.
HANDLE_OFFER_LIFETIME = timedelta(days=1)


def create_handle_offer(name: str, discriminator: int) -> str:
    """Sign the number shown beside ``name`` while somebody picks a handle."""
    now = datetime.now(timezone.utc)
    payload = {
        "aud": HANDLE_OFFER_AUDIENCE,
        "name": name.lower(),
        "num": discriminator,
        "iat": int(now.timestamp()),
        "exp": now + HANDLE_OFFER_LIFETIME,
    }
    return sign_hs256(payload)


def read_handle_offer(token: str | None, name: str) -> int | None:
    """The number a handle offer signed for ``name``; ``None`` for anything
    else: no offer, another name, expired, or not one this server signed."""
    if not token:
        return None
    try:
        payload = verify_hs256(
            token, audience=HANDLE_OFFER_AUDIENCE, require=["exp", "aud"]
        )
    except jwt.PyJWTError:
        return None
    number = payload.get("num")
    if payload.get("name") != name.lower() or not isinstance(number, int):
        return None
    return number


class HandoffSigningNotConfiguredError(RuntimeError):
    """Raised when a handoff token is requested but no Ed25519 signing key is
    configured. The token is verified by a separate service, so there is no
    symmetric fallback — the caller must translate this into a fail-closed
    response (503) rather than mint an unverifiable token."""


def _resolve_handoff_signing_material() -> tuple[str, str | None]:
    """Return (private_key_pem, kid) for signing handoff JWTs.

    Handoff tokens cross a trust boundary: the receiving service verifies them
    with the public half of this key, so they are always EdDSA — never a
    symmetric scheme that would force sharing a secret across that boundary.
    Set HANDOFF_SIGNING_KEY_ID for a stable ``kid`` so the receiver can pick
    the right verifying key out of a JWKS during rotation.

    Fails closed (raises) when no key is configured, or when the one configured
    is not Ed25519: a deployment that links a companion service must also
    supply HANDOFF_SIGNING_PRIVATE_KEY_PEM.
    """
    private_pem = settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM
    if not private_pem:
        raise HandoffSigningNotConfiguredError(
            "HANDOFF_SIGNING_PRIVATE_KEY_PEM is required to mint handoff tokens"
        )
    if not _is_ed25519_private_key(private_pem):
        raise HandoffSigningNotConfiguredError(
            "HANDOFF_SIGNING_PRIVATE_KEY_PEM must be an Ed25519 key (EdDSA)"
        )
    return private_pem, settings.HANDOFF_SIGNING_KEY_ID


@lru_cache(maxsize=4)
def _is_ed25519_private_key(private_pem: str) -> bool:
    try:
        key = load_pem_private_key(private_pem.encode("utf-8"), password=None)
    except (ValueError, TypeError):
        return False
    return isinstance(key, ed25519.Ed25519PrivateKey)


BILLING_PORTAL_AUDIENCE = "initiative:billing-portal"

# This handoff's lifetime, owned here like the support handoff's below. Used
# both as the default ``expires_in`` and as the value the function reports back,
# so the response's ``expires_in_seconds`` and the JWT's ``exp`` claim can never
# disagree.
BILLING_PORTAL_HANDOFF_LIFETIME = timedelta(seconds=60)


def create_billing_portal_handoff_token(
    *,
    guild_role: str,
    user_ref: str,
    guild_ref: str,
    guild_name: str | None = None,
    expires_in: timedelta = BILLING_PORTAL_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the billing-portal handoff token (EdDSA; raises if unconfigured).

    ``community_name`` is what the community calls itself, so the portal can
    title its pages and billing keep its copy current.

    ``user_ref`` / ``guild_ref`` are the only names for the pair that cross —
    see ``services.platform.identity_refs.billing_refs``. ``sub`` carries the
    user's, which is what a pairwise pseudonymous identifier is for (OpenID
    Connect Core §8.1); no row id of ours is a parameter here, so none can
    reach the claims.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "sub": user_ref,
        "aud": BILLING_PORTAL_AUDIENCE,
        "iss": TOKEN_ISSUER,
        "iat": int(now.timestamp()),
        "exp": now + expires_in,
        "community_role": guild_role,
        "user_ref": user_ref,
        "community_ref": guild_ref,
    }
    if guild_name:
        payload["community_name"] = guild_name
    token = sign_eddsa(payload, *_resolve_handoff_signing_material())
    return token, int(expires_in.total_seconds())


BILLING_INSIGHTS_AUDIENCE = "initiative:billing-insights"
BILLING_INSIGHTS_HANDOFF_LIFETIME = timedelta(seconds=60)


def billing_insights_handoff_enabled() -> bool:
    """True when this deployment can mint the insights handoff."""
    return bool(settings.BILLING_URL and settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM)


def create_billing_insights_handoff_token(
    *,
    user_ref: str,
    expires_in: timedelta = BILLING_INSIGHTS_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the handoff into the billing service's insights page.

    The same Ed25519 key as the portal handoff, under its own audience, so
    neither token opens the other's door. It names the person by billing's
    pairwise reference and nothing else: no community and no grant, because
    the page shows nothing about any one community.
    """
    return _billing_staff_handoff(BILLING_INSIGHTS_AUDIENCE, user_ref, expires_in)


BILLING_CONTRACTS_AUDIENCE = "initiative:billing-contracts"


def create_billing_contracts_handoff_token(
    *,
    user_ref: str,
    expires_in: timedelta = BILLING_INSIGHTS_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the handoff into the billing service's contracts console.

    The insights handoff's shape under the contracts audience: a person and no
    community, because a contract is a payer's and some cover no community
    here. The audience is what keeps an insights handoff, minted for a
    read-only page, from opening a console that writes.
    """
    return _billing_staff_handoff(BILLING_CONTRACTS_AUDIENCE, user_ref, expires_in)


BILLING_DIRECTORY_AUDIENCE = "initiative:billing-directory"


def create_billing_directory_handoff_token(
    *,
    user_ref: str,
    expires_in: timedelta = BILLING_INSIGHTS_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the handoff into the billing service's owner directory.

    The same shape again under the directory's audience: a person and no
    community, because the page lists every account. The audience is what
    keeps an operator's insights or contracts handoff from opening it.
    """
    return _billing_staff_handoff(BILLING_DIRECTORY_AUDIENCE, user_ref, expires_in)


BILLING_CONTROL_AUDIENCE = "initiative:billing-control"


def create_billing_control_handoff_token(
    *,
    user_ref: str,
    expires_in: timedelta = BILLING_INSIGHTS_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the handoff into the billing service's Control, where owners
    define the deployment's plans.

    A person and no community, under Control's own audience: what it changes
    is every community's, and no other door's handoff may open it.
    """
    return _billing_staff_handoff(BILLING_CONTROL_AUDIENCE, user_ref, expires_in)


def _billing_staff_handoff(
    audience: str, user_ref: str, expires_in: timedelta
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "sub": user_ref,
        "aud": audience,
        "iss": TOKEN_ISSUER,
        "iat": int(now.timestamp()),
        "exp": now + expires_in,
    }
    token = sign_eddsa(payload, *_resolve_handoff_signing_material())
    return token, int(expires_in.total_seconds())


class PluginPlatformSigningNotConfiguredError(RuntimeError):
    """Raised when plugin-platform signing material is needed but absent.

    The plug-in platform has its own dedicated keypair and deliberately no
    fallback to any other configured key: a plug-in verifies context JWTs against
    the published public half, and two boundaries sharing one key would share
    one rotation. Callers translate this into a fail-closed 503.
    """


#: The key the deployment generated for the plug-in platform, as
#: ``(private_pem, kid)``, loaded at startup. Used only while
#: ``PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM`` is unset.
_stored_plugin_platform_key: tuple[str, str] | None = None


def use_stored_plugin_platform_signing_key(private_pem: str, kid: str) -> None:
    """Sign plugin-platform tokens with the deployment's stored key."""
    global _stored_plugin_platform_key
    _stored_plugin_platform_key = (private_pem, kid)


def plugin_platform_signing_enabled() -> bool:
    """True when this deployment can sign for the plug-in platform."""
    return bool(
        settings.PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM or _stored_plugin_platform_key
    )


def resolve_plugin_platform_signing_material() -> tuple[str, str | None]:
    """Return (private_key_pem, kid) for plugin-platform tokens.

    ``PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM`` when it is set, with
    ``PLUGIN_PLATFORM_SIGNING_KEY_ID``; otherwise the key the deployment generated
    and stored, with its RFC 7638 thumbprint as the kid.
    """
    private_pem = settings.PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM
    if private_pem:
        return private_pem, settings.PLUGIN_PLATFORM_SIGNING_KEY_ID
    if _stored_plugin_platform_key is not None:
        return _stored_plugin_platform_key
    raise PluginPlatformSigningNotConfiguredError(
        "no plug-in platform signing key is loaded; it has no fallback to another "
        "service's key"
    )


# Pinned on both sides of the boundary — not deployment knobs.
#: ``aud`` is this prefix plus the registration's public_id, so a token minted
#: for one plug-in is not accepted by another.
PLUGIN_PLATFORM_AUDIENCE_PREFIX = "initiative-plugin:"
#: ``typ`` in the header of each kind of token a plug-in receives (RFC 8725
#: §3.11): a call to an endpoint or a hook, and a page handoff. A plug-in checks it
#: to take each kind only where it expects that kind.
PLUGIN_CONTEXT_TOKEN_TYPE = "initiative-context+jwt"
PLUGIN_HANDOFF_TOKEN_TYPE = "initiative-handoff+jwt"


def plugin_platform_audience(public_id: str) -> str:
    """The ``aud`` a token minted for one plug-in service carries."""
    return f"{PLUGIN_PLATFORM_AUDIENCE_PREFIX}{public_id}"


BILLING_SUPPORT_HANDOFF_AUDIENCE = "initiative:billing-support"

BILLING_SUPPORT_CONSOLE = "support"
BILLING_OPERATOR_CONSOLE = "operator"
BILLING_CONSOLES = (BILLING_SUPPORT_CONSOLE, BILLING_OPERATOR_CONSOLE)

_BILLING_CONSOLE_AUDIENCES = {
    BILLING_SUPPORT_CONSOLE: BILLING_SUPPORT_HANDOFF_AUDIENCE,
    BILLING_OPERATOR_CONSOLE: "initiative:billing-operator",
}

# Lifetime of a billing-support handoff, and the ceiling the receiver accepts.
BILLING_SUPPORT_HANDOFF_LIFETIME = timedelta(seconds=60)
BILLING_SUPPORT_HANDOFF_MAX_LIFETIME = timedelta(seconds=300)


class BillingSupportHandoffNotConfiguredError(RuntimeError):
    """Raised when a billing console handoff is requested but this deployment
    can't mint one: no billing portal, or no Ed25519 handoff key. Fails closed —
    the caller returns 503."""


def billing_support_handoff_enabled(
    console: str = BILLING_SUPPORT_CONSOLE,
) -> bool:
    """True when this deployment can mint handoffs into ``console``: signed
    with the same Ed25519 key as every other handoff into billing, under the
    console's own audience."""
    return console in BILLING_CONSOLES and bool(
        settings.BILLING_URL and settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM
    )


def create_billing_support_handoff_token(
    *,
    grant_id: int | str,
    user_ref: str,
    guild_ref: str,
    approver_ref: str | None = None,
    expires_in: timedelta = BILLING_SUPPORT_HANDOFF_LIFETIME,
    console: str = BILLING_SUPPORT_CONSOLE,
) -> tuple[str, int]:
    """Mint the billing-support handoff token.

    ``grant_id`` names the ``access_grants`` row that authorises the visit, so
    both sides log the same grant. Everyone else on it is named by reference —
    the operator visiting, the guild visited, and whoever approved the visit —
    see ``services.platform.identity_refs.billing_refs``. ``sub`` carries the
    operator's, which is what a pairwise pseudonymous identifier is for
    (OpenID Connect Core §8.1).
    """
    if console not in BILLING_CONSOLES:
        raise BillingSupportHandoffNotConfiguredError(
            f"unknown billing console {console!r}"
        )
    if not billing_support_handoff_enabled(console):
        raise BillingSupportHandoffNotConfiguredError(
            f"the billing {console} console's handoff needs BILLING_URL and"
            " HANDOFF_SIGNING_PRIVATE_KEY_PEM"
        )
    lifetime = min(expires_in, BILLING_SUPPORT_HANDOFF_MAX_LIFETIME)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "sub": user_ref,
        "aud": _BILLING_CONSOLE_AUDIENCES[console],
        "iss": TOKEN_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "grant_id": str(grant_id),
        "user_ref": user_ref,
        "community_ref": guild_ref,
    }
    if approver_ref is not None:
        payload["approver"] = approver_ref
    try:
        material = _resolve_handoff_signing_material()
    except HandoffSigningNotConfiguredError as exc:
        raise BillingSupportHandoffNotConfiguredError(str(exc)) from exc
    token = sign_eddsa(payload, *material)
    return token, int(lifetime.total_seconds())
