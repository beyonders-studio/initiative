"""Unit tests for token signing and claims.

These exercise the minting functions directly without hitting the API, so
they're cheap to run and don't need a database. The HTTP-level gating is
covered separately in the endpoint tests.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from app.core import security
from app.core.config import settings
from app.core.security import (
    AUTH_ACCESS_AUDIENCE,
    BILLING_PORTAL_HANDOFF_LIFETIME,
    JWT_ALGORITHM,
    TOKEN_ISSUER,
    UPLOAD_TOKEN_AUDIENCE,
    UPLOAD_TOKEN_LIFETIME,
    UPLOAD_TOKEN_SCOPE,
    HandoffSigningNotConfiguredError,
    UploadTokenError,
    create_upload_token,
    decode_session_token,
    mint_access_token,
    verify_upload_token,
)


def _decode_unverified(token: str) -> dict:
    """Return the JWT payload without checking signature/audience.

    The tests assert specific claims; signature verification is exercised
    separately in the EdDSA round-trip test.
    """
    return jwt.decode(token, options={"verify_signature": False})


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.mark.parametrize(
    ("stored_hash", "expected_match"),
    [
        (None, False),
        ("!", False),
        ("$2b$12$retired-scheme-fixture", False),
        ("$argon2id$independent-fixture", True),
    ],
)
def test_sign_in_password_check_runs_one_argon2_check_whatever_the_account(
    monkeypatch, stored_hash: str | None, expected_match: bool
) -> None:
    """Account state selects a result, not how much KDF work is scheduled."""
    observed: list[str] = []

    class FakeArgon2:
        def verify(self, hashed: str, plain: str) -> bool:
            assert plain == "candidate"
            observed.append(hashed)
            return hashed == stored_hash

    monkeypatch.setattr(security, "_argon2_hasher", FakeArgon2())

    assert security.verify_sign_in_password("candidate", stored_hash) is expected_match
    assert len(observed) == 1
    assert (stored_hash in observed) is expected_match


def test_sign_in_password_check_accepts_only_a_matching_account_hash() -> None:
    """Dummy work can never turn an absent or unusable credential into a login."""
    password = "independent-password-fixture"
    argon_hash = security.get_password_hash(password)

    assert security.verify_sign_in_password(password, argon_hash) is True
    assert security.verify_sign_in_password("wrong", argon_hash) is False
    assert security.verify_sign_in_password(password, None) is False
    assert security.verify_sign_in_password(password, "!") is False


def test_billing_portal_handoff_carries_admin_claims_and_distinct_audience(
    handoff_signing_key,
):
    """Claims present, and the audience is the portal's own."""
    token, seconds = security.create_billing_portal_handoff_token(
        guild_role="admin",
        user_ref="ubil_test42",
        guild_ref="gbil_test7",
    )
    assert seconds == int(BILLING_PORTAL_HANDOFF_LIFETIME.total_seconds())
    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"

    payload = _decode_unverified(token)
    assert payload["aud"] == security.BILLING_PORTAL_AUDIENCE
    assert payload["iss"] == "initiative"
    assert payload["community_role"] == "admin"
    assert payload["jti"] and isinstance(payload["jti"], str)
    # The two are named by reference and by nothing else — `sub` carries the
    # user's, and no row id of ours appears anywhere in the claims.
    assert payload["sub"] == "ubil_test42"
    assert payload["user_ref"] == "ubil_test42"
    assert payload["community_ref"] == "gbil_test7"
    assert "guild_id" not in payload
    assert "guild_name" not in payload


def test_billing_portal_handoff_refuses_to_mint_without_private_key(monkeypatch):
    """No Ed25519 key configured -> mint fails closed."""
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)
    with pytest.raises(HandoffSigningNotConfiguredError):
        security.create_billing_portal_handoff_token(
            guild_role="admin",
            user_ref="ubil_test1",
            guild_ref="gbil_test2",
        )


def test_billing_handoff_refuses_to_mint_with_an_rsa_key(monkeypatch):
    """Ed25519 is the only handoff key: an RSA one is refused, not used."""
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", rsa_pem)
    with pytest.raises(HandoffSigningNotConfiguredError, match="Ed25519"):
        security.create_billing_insights_handoff_token(user_ref="ubil_test1")


# ──────────────────────────────────────────────────────────────────────────
# Scoped upload tokens
# ──────────────────────────────────────────────────────────────────────────


def test_upload_token_round_trips_to_user_id():
    """A freshly minted upload token verifies back to the user it names,
    carrying its minting session's auth standing (empty by default)."""
    token, seconds = create_upload_token(user_id=123)
    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == int(UPLOAD_TOKEN_LIFETIME.total_seconds())
    upload = verify_upload_token(token)
    assert upload.user_id == 123
    assert (upload.satisfied, upload.claims, upload.markers) == (
        frozenset(),
        {},
        frozenset(),
    )

    satisfied_token, _ = create_upload_token(
        user_id=123,
        satisfied_providers=[5, 2],
        satisfied_claims={"5": {"hd": ["acme.com"]}},
    )
    satisfied = verify_upload_token(satisfied_token)
    assert satisfied.user_id == 123
    assert satisfied.satisfied == frozenset({2, 5})
    assert satisfied.claims == {"5": {"hd": ["acme.com"]}}
    assert satisfied.markers == frozenset()


def test_upload_token_carries_how_the_session_was_opened():
    """A community can ask for a second factor or for a passkey, and the token
    carries the markers that answer each — a code presented after a password
    is not a key, so a rule asking for one is not answered by the other."""
    factor, _ = create_upload_token(user_id=7, session_amr={"mfa"})
    assert verify_upload_token(factor).markers == frozenset({"mfa"})

    key, _ = create_upload_token(user_id=7, session_amr={"mfa", "hwk"})
    assert verify_upload_token(key).markers == frozenset({"mfa", "hwk"})

    neither, _ = create_upload_token(user_id=7)
    assert verify_upload_token(neither).markers == frozenset()


def test_upload_token_carries_scope_and_audience_but_no_ver():
    """The token must carry the uploads aud/scope and deliberately omit
    ``ver`` — the general session-JWT path keys on ``ver`` and so will
    reject this token as an API credential."""
    token, _ = create_upload_token(user_id=7)
    payload = _decode_unverified(token)
    assert payload["aud"] == UPLOAD_TOKEN_AUDIENCE
    assert payload["scope"] == UPLOAD_TOKEN_SCOPE
    assert payload["sub"] == "7"
    assert "ver" not in payload


def test_verify_upload_token_rejects_session_jwt():
    """A normal session JWT (different shape, no uploads aud) must not pass
    upload-token verification."""
    session_jwt, _ = mint_access_token(
        subject="ucli_seven",
        token_version=1,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
    )
    with pytest.raises(UploadTokenError):
        verify_upload_token(session_jwt)


def test_verify_upload_token_rejects_expired_token():
    """An expired upload token is rejected."""
    token, _ = create_upload_token(user_id=7, expires_in=timedelta(seconds=-1))
    with pytest.raises(UploadTokenError):
        verify_upload_token(token)


def test_session_jwt_signed_with_dedicated_jwt_signing_key(monkeypatch):
    """When JWT_SIGNING_KEY is set, session JWTs are signed/verified with it — so it
    can be rotated independently of the encryption-rooting SECRET_KEY."""
    jwt_key = "j" * 48
    monkeypatch.setattr(security.settings, "JWT_SIGNING_KEY", jwt_key)

    token, _ = mint_access_token(
        subject="ucli_seven",
        token_version=1,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
    )
    # Verifies under the dedicated key...
    payload = jwt.decode(
        token,
        jwt_key,
        algorithms=[security.JWT_ALGORITHM],
        audience=AUTH_ACCESS_AUDIENCE,
        issuer=TOKEN_ISSUER,
    )
    assert payload["sub"] == "ucli_seven"
    # ...and NOT under SECRET_KEY (proving the keys are actually decoupled).
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.JWT_ALGORITHM],
        )


def test_jwt_signing_key_does_not_affect_encryption(monkeypatch):
    """Setting/rotating JWT_SIGNING_KEY must not change encryption or the email HMAC —
    those are rooted in SECRET_KEY alone, so a JWT rotation can't orphan data."""
    from app.core.encryption import SALT_EMAIL, encrypt_field, hash_email

    before_ct = encrypt_field("alice@example.com", SALT_EMAIL)
    before_hash = hash_email("alice@example.com")

    monkeypatch.setattr(security.settings, "JWT_SIGNING_KEY", "j" * 48)

    # Same email hash, and the pre-rotation ciphertext still decrypts.
    from app.core.encryption import decrypt_field

    assert hash_email("alice@example.com") == before_hash
    assert decrypt_field(before_ct, SALT_EMAIL) == "alice@example.com"


def test_verify_upload_token_rejects_wrong_audience_and_claims(handoff_signing_key):
    """A token carrying a foreign audience (e.g. a handoff into another
    service) is not an upload token, and neither is one with the uploads
    audience whose scope or claims are not the shape an upload token has."""
    handoff, _ = security.create_billing_portal_handoff_token(
        guild_role="admin",
        user_ref="ubil_test1",
        guild_ref="gbil_test2",
    )
    with pytest.raises(UploadTokenError):
        verify_upload_token(handoff)

    now = datetime.now(UTC)
    claims = {
        "sub": "7",
        "aud": UPLOAD_TOKEN_AUDIENCE,
        "scope": UPLOAD_TOKEN_SCOPE,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=1),
    }
    assert verify_upload_token(security.sign_hs256(claims)).user_id == 7
    for change in (
        {"scope": "files"},
        {"scope": None},
        {"sub": "ucli_seven"},
        {"sat": ["one"]},
        {"satc": ["not", "an", "object"]},
    ):
        with pytest.raises(UploadTokenError):
            verify_upload_token(security.sign_hs256({**claims, **change}))
    # A null collection reads as empty.
    nulls = verify_upload_token(
        security.sign_hs256({**claims, "sat": None, "satc": None, "amr": None})
    )
    assert (nulls.satisfied, nulls.claims, nulls.markers) == (
        frozenset(),
        {},
        frozenset(),
    )


# ── New-model access token (auth rewrite, Phase 0) ─────────────────────────


def test_mint_access_token_carries_session_claims():
    """The access token names the user, the backing session, and the auth
    context (amr/sat) that the guild-policy gate reads locally."""
    sid = uuid.uuid4()
    token, seconds = mint_access_token(
        subject="ucli_forty_two",
        token_version=3,
        session_id=sid,
        amr=["pwd", "otp"],
        satisfied_providers=[7, 9],
    )

    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == settings.AUTH_ACCESS_TTL_MINUTES * 60

    payload = _decode_unverified(token)
    assert payload["sub"] == "ucli_forty_two"
    assert payload["sid"] == str(sid)
    assert payload["ver"] == 3
    assert payload["amr"] == ["pwd", "otp"]
    assert payload["sat"] == [7, 9]
    assert payload["iss"] == TOKEN_ISSUER
    assert payload["aud"] == AUTH_ACCESS_AUDIENCE


def test_mint_access_token_exp_matches_advertised_seconds():
    """``exp`` must equal ``iat`` + the returned seconds — the SPA schedules its
    refresh off that number, so drift would refresh late (or never)."""
    sid = uuid.uuid4()
    token, seconds = mint_access_token(
        subject="ucli_one",
        token_version=0,
        session_id=sid,
        amr=["pwd"],
        satisfied_providers=[],
    )

    payload = _decode_unverified(token)
    assert payload["exp"] - payload["iat"] == seconds


def test_mint_access_token_is_verifiable_with_expected_audience():
    """A round-trip decode with the audience the verification path will require
    must succeed — signature + aud + iss all line up."""
    sid = uuid.uuid4()
    token, _ = mint_access_token(
        subject="ucli_five",
        token_version=1,
        session_id=sid,
        amr=["pwd"],
        satisfied_providers=[],
    )

    payload = jwt.decode(
        token,
        settings.jwt_signing_key,
        algorithms=[JWT_ALGORITHM],
        audience=AUTH_ACCESS_AUDIENCE,
        issuer=TOKEN_ISSUER,
        options={"require": ["exp", "iat", "sub", "sid", "aud", "iss"]},
    )
    assert payload["sub"] == "ucli_five"


# ── Dual-verify decode (accepts new + legacy, rejects scoped) ───────────────


def test_decode_session_token_accepts_new_access_token():
    token, _ = mint_access_token(
        subject="ucli_seven",
        token_version=2,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[3],
    )
    payload = decode_session_token(token)
    assert payload["sub"] == "ucli_seven"
    assert payload["ver"] == 2
    assert payload["aud"] == AUTH_ACCESS_AUDIENCE
    assert payload["sat"] == [3]


def test_decode_session_token_refuses_the_pre_session_shape():
    """The JWT builds before 0.69.0 issued — signed by us, carrying ``sub`` and
    ``ver``, and no ``aud``/``iss`` — is no longer a session credential.

    Built here rather than minted, because nothing mints one any more. Its
    holder is not stranded: the refresh cookie is a separate credential and
    renewing it returns a token of the shape above."""
    legacy = jwt.encode(
        {
            "sub": "7",
            "ver": 2,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        settings.jwt_signing_key,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(legacy)


def test_decode_session_token_refuses_a_token_with_no_session():
    """Every access token names its session; one that doesn't was not minted
    by this server's ``mint_access_token``."""
    sessionless = jwt.encode(
        {
            "sub": "ucli_seven",
            "ver": 2,
            "aud": AUTH_ACCESS_AUDIENCE,
            "iss": TOKEN_ISSUER,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        settings.jwt_signing_key,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(sessionless)


def test_decode_session_token_rejects_scoped_upload_token():
    """A scoped upload token carries a foreign aud — it must NOT be honored as
    a session credential on either decode path (the key security property)."""
    upload, _ = create_upload_token(user_id=7)
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(upload)


def test_decode_session_token_rejects_handoff_token(handoff_signing_key):
    handoff, _ = security.create_billing_portal_handoff_token(
        guild_role="admin",
        user_ref="ubil_test7",
        guild_ref="gbil_test1",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(handoff)


def test_decode_session_token_rejects_expired_new_token():
    """An expired NEW token must surface its true ``ExpiredSignatureError`` from
    the first decode — not be masked by the legacy fallback's audience error —
    so cutover-window logs stay honest."""
    token, _ = mint_access_token(
        subject="ucli_seven",
        token_version=0,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
        expires_in=timedelta(seconds=-1),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_session_token(token)


def test_decode_session_token_rejects_garbage():
    with pytest.raises(jwt.PyJWTError):
        decode_session_token("not.a.jwt")


# ──────────────────────────────────────────────────────────────────────────
# Rotatable verifying keys
#
# The settings holding a peer's public key take concatenated PEM blocks, so
# both the old and the new key are trusted while that peer rotates. These
# cover the loader; the per-peer wiring is exercised beside each verifier.
# ──────────────────────────────────────────────────────────────────────────


_KEYPAIRS = [ed25519.Ed25519PrivateKey.generate() for _ in range(3)]


def private_pem(index: int) -> str:
    return (
        _KEYPAIRS[index]
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def public_bundle(*indexes: int) -> str:
    """A configured value trusting the given keypairs, in order."""
    return "".join(
        _KEYPAIRS[index]
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
        for index in indexes
    )


def test_loader_reads_every_block_in_order():
    keys = security.load_verification_keys(public_bundle(0, 1, 2))
    assert len(keys) == 3
    assert [k.public_bytes_raw() for k in keys] == [
        _KEYPAIRS[i].public_key().public_bytes_raw() for i in (0, 1, 2)
    ]


def test_loader_reads_a_single_block():
    """The ordinary one-key case is the same code path."""
    assert len(security.load_verification_keys(public_bundle(0))) == 1


def test_loader_treats_empty_as_no_keys():
    """An unset setting is "no peer", not an error — callers decide what that
    means for them."""
    assert security.load_verification_keys("") == ()


def test_loader_refuses_an_unreadable_block_rather_than_skipping_it():
    """A silently dropped block would leave a rotation looking configured
    while the key it added does nothing."""
    bundle = public_bundle(0) + "-----BEGIN PUBLIC KEY-----\nnope\n"
    with pytest.raises(security.PublicKeyBundleError) as excinfo:
        security.load_verification_keys(bundle)
    assert "block 2" in str(excinfo.value)


def test_loader_refuses_a_private_key():
    """Only the public half belongs in a verifying setting."""
    with pytest.raises(security.PublicKeyBundleError):
        security.load_verification_keys(private_pem(0))


def test_loader_refuses_a_key_that_is_not_ed25519():
    """An RSA block is refused outright, not trusted beside the others."""
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    with pytest.raises(security.PublicKeyBundleError) as excinfo:
        security.load_verification_keys(public_bundle(0) + rsa_pem)
    assert "block 2 is not an Ed25519 key" in str(excinfo.value)


def test_has_usable_password_reads_the_hash_not_the_null():
    """The definition of "no usable password": a value outside the scheme
    ``verify_password`` checks, whatever it is."""
    from app.core.security import get_password_hash, has_usable_password

    assert has_usable_password(get_password_hash("something")) is True
    # NULL, and the marker a 0152 downgrade writes, read the same.
    assert has_usable_password(None) is False
    assert has_usable_password("!") is False
    assert has_usable_password("") is False
    assert has_usable_password("not-a-hash") is False
    # A bcrypt hash from before 0.75 is not one any more.
    assert has_usable_password("$2b$12$" + "x" * 53) is False
