"""Rejection tests for the encrypted OIDC flow state.

The state parameter round-trips through the browser, so the suite checks it
from there: altered, expired, cross-context, wrong-key and malformed tokens
must all be rejected; the secrets it carries must not be readable from the
token itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest

from app.core.config import settings
from app.core.encryption import (
    SALT_OIDC_CLIENT_SECRET,
    SALT_OIDC_FLOW_STATE,
    _get_fernet,
    encrypt_field,
)
from app.services.auth.oidc.flow_state import (
    FlowStateError,
    OidcFlowState,
    create_flow_state,
    decode_flow_state,
)

# --- round-trip ---------------------------------------------------------------


def test_round_trip():
    state, payload = create_flow_state(
        mobile=True, device_name="Léa's Pixel 9", app_challenge="c" * 43
    )
    decoded = decode_flow_state(state)
    assert decoded == payload
    assert decoded.mobile is True
    assert decoded.device_name == "Léa's Pixel 9"
    assert decoded.app_challenge == "c" * 43


def test_defaults_round_trip():
    state, payload = create_flow_state()
    decoded = decode_flow_state(state)
    assert decoded.mobile is False
    assert decoded.device_name == ""
    assert decoded.app_challenge == ""
    assert decoded.code_verifier == payload.code_verifier
    assert decoded.nonce == payload.nonce


def test_each_flow_is_unique():
    s1, p1 = create_flow_state()
    s2, p2 = create_flow_state()
    assert s1 != s2
    assert p1.code_verifier != p2.code_verifier
    assert p1.nonce != p2.nonce


# --- confidentiality ----------------------------------------------------------


def test_secrets_not_readable_from_state_token():
    """The whole point of encrypting: the verifier and nonce must not appear in
    the state string that transits the browser."""
    state, payload = create_flow_state(device_name="pixel")
    assert payload.code_verifier not in state
    assert payload.nonce not in state
    assert "pixel" not in state


# --- PKCE correctness -----------------------------------------------------------


def test_code_challenge_is_rfc7636_s256():
    _, payload = create_flow_state()
    expected = (
        base64.urlsafe_b64encode(
            hashlib.sha256(payload.code_verifier.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    assert payload.code_challenge == expected
    assert "=" not in payload.code_challenge  # unpadded per the RFC


def test_verifier_meets_rfc7636_requirements():
    _, payload = create_flow_state()
    assert 43 <= len(payload.code_verifier) <= 128
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert set(payload.code_verifier) <= allowed


# --- rejection paths ------------------------------------------------------------


def test_tampered_state_rejected():
    state, _ = create_flow_state()
    i = len(state) // 2
    tampered = state[:i] + ("A" if state[i] != "A" else "B") + state[i + 1 :]
    with pytest.raises(FlowStateError):
        decode_flow_state(tampered)


def test_expired_state_rejected():
    payload = json.dumps(
        {"code_verifier": "v" * 43, "nonce": "n", "mobile": False, "device_name": ""}
    )
    fernet = _get_fernet(SALT_OIDC_FLOW_STATE, settings.SECRET_KEY)
    old = fernet.encrypt_at_time(
        payload.encode(), current_time=int(time.time()) - 3600
    ).decode()
    with pytest.raises(FlowStateError):
        decode_flow_state(old, max_age_seconds=600)


@pytest.mark.parametrize("state", ["", "garbage", "gAAAAA..not-a-token"])
def test_missing_or_garbage_state_rejected(state):
    with pytest.raises(FlowStateError):
        decode_flow_state(state)


@pytest.mark.parametrize(
    ("case", "payload", "salt", "secret_key"),
    [
        # Minted somewhere else: right library, wrong purpose or wrong key.
        (
            "another salt",
            '{"code_verifier":"v","nonce":"n"}',
            SALT_OIDC_CLIENT_SECRET,
            None,
        ),
        (
            "another secret key",
            '{"code_verifier":"v","nonce":"n"}',
            SALT_OIDC_FLOW_STATE,
            "a-different-secret-key",
        ),
        # Decryptable, but not flow state.
        ("not json", "not json", SALT_OIDC_FLOW_STATE, None),
        ("no verifier", '{"nonce":"n"}', SALT_OIDC_FLOW_STATE, None),
        # Present but unusable: a flow state always carries non-empty string
        # secrets, so these are a rejected login rather than a caller error
        # surfacing further downstream.
        (
            "empty verifier",
            '{"code_verifier":"","nonce":"n"}',
            SALT_OIDC_FLOW_STATE,
            None,
        ),
        ("empty nonce", '{"code_verifier":"v","nonce":""}', SALT_OIDC_FLOW_STATE, None),
        (
            "null verifier",
            '{"code_verifier":null,"nonce":"n"}',
            SALT_OIDC_FLOW_STATE,
            None,
        ),
        (
            "non-string nonce",
            '{"code_verifier":"v","nonce":42}',
            SALT_OIDC_FLOW_STATE,
            None,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v or v is None else "",
)
def test_a_token_that_is_not_this_flow_state_is_rejected(
    case, payload, salt, secret_key
):
    """Everything that is not a live flow state minted here — wrong salt, wrong
    key, wrong payload — comes back as ``FlowStateError``."""
    token = encrypt_field(payload, salt, secret_key=secret_key)
    with pytest.raises(FlowStateError):
        decode_flow_state(token)


def test_valid_token_with_non_utf8_plaintext_rejected():
    """A same-key token whose plaintext isn't UTF-8 must still surface as
    FlowStateError — the function's whole contract — not UnicodeDecodeError."""
    fernet = _get_fernet(SALT_OIDC_FLOW_STATE, settings.SECRET_KEY)
    token = fernet.encrypt(b"\xff\xfe\xfa garbage bytes").decode()
    with pytest.raises(FlowStateError):
        decode_flow_state(token)


# --- device_name cap ------------------------------------------------------------


def test_device_name_truncated_on_create():
    state, payload = create_flow_state(device_name="x" * 500)
    assert len(payload.device_name) == 64
    assert len(decode_flow_state(state).device_name) == 64


def test_device_name_capped_on_decode():
    """Even a hand-minted token with an oversized device_name is capped at the
    decode boundary."""
    token = encrypt_field(
        json.dumps({"code_verifier": "v" * 43, "nonce": "n", "device_name": "y" * 500}),
        SALT_OIDC_FLOW_STATE,
    )
    assert len(decode_flow_state(token).device_name) == 64


# --- dataclass behavior ---------------------------------------------------------


def test_flow_state_is_immutable():
    _, payload = create_flow_state()
    # setattr rather than direct assignment: the runtime frozen-dataclass check is
    # what's under test, and static checkers rightly refuse the assignment form.
    with pytest.raises(AttributeError):
        setattr(payload, "nonce", "overwritten")  # noqa: B010


def test_challenge_is_deterministic_for_a_verifier():
    a = OidcFlowState(code_verifier="v" * 43, nonce="n")
    b = OidcFlowState(code_verifier="v" * 43, nonce="m")
    assert a.code_challenge == b.code_challenge
