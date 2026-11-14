"""The state a plug-in connection's vendor flow carries through the vendor.

Initiative runs every connection's flow, and nothing is stored while one is in
progress: what the callback needs to finish it travels in the ``state``
parameter as a Fernet token (the pattern :mod:`app.services.auth.oidc.
flow_state` uses for sign-in, under a salt of its own). It is confidential,
cannot be altered, and expires ten minutes after it was minted.

It names the install, the connection and the member (or none, for the
community's own connection), the person who started it, the PKCE verifier,
the path to send the person back to, and the phase: ``install`` while a person is on the vendor's install
page, ``authorize`` once the authorization request is sent. An
installation-style flow's second leg carries the installation id the vendor's
setup address returned.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, replace

from cryptography.fernet import InvalidToken

from app.core.encryption import (
    SALT_PLUGIN_CONNECTION_FLOW,
    decrypt_field,
    encrypt_field,
)

__all__ = [
    "PHASES",
    "STATE_MAX_AGE_SECONDS",
    "ConnectionFlowState",
    "FlowStateError",
    "code_challenge",
    "decode_state",
    "encode_state",
    "new_state",
]

#: How long a flow may take from start to callback.
STATE_MAX_AGE_SECONDS = 600

#: ``install`` — sent to the vendor's install page; ``authorize`` — sent to its
#: authorization endpoint.
PHASES: frozenset[str] = frozenset({"install", "authorize"})

#: 64 random bytes: an 86-character verifier, within RFC 7636's 43..128.
_VERIFIER_BYTES = 64

#: The widest installation id a vendor's setup address may hand back.
MAX_INSTALLATION_ID_LENGTH = 64


class FlowStateError(Exception):
    """The state is missing, expired, altered or malformed."""


@dataclass(frozen=True)
class ConnectionFlowState:
    guild_id: int
    install_id: int
    connection_id: str
    #: The member connecting their own account; ``None`` for the community's.
    user_id: int | None
    #: The signed-in person who started the flow, and the only one who may
    #: finish it.
    started_by: int
    #: The PKCE verifier, or empty when the flow sends no challenge.
    verifier: str
    #: Where to send the person when the flow ends, as a path on this
    #: deployment.
    return_path: str
    phase: str
    #: The id an installation-style flow's setup address returned.
    installation_id: str | None = None

    def authorizing(self, installation_id: str | None) -> ConnectionFlowState:
        """The same flow, on its way to the authorization endpoint."""
        return replace(self, phase="authorize", installation_id=installation_id)


def code_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier (RFC 7636 §4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_state(
    *,
    guild_id: int,
    install_id: int,
    connection_id: str,
    user_id: int | None,
    started_by: int,
    return_path: str,
    pkce: bool,
    phase: str,
) -> ConnectionFlowState:
    return ConnectionFlowState(
        guild_id=guild_id,
        install_id=install_id,
        connection_id=connection_id,
        user_id=user_id,
        started_by=started_by,
        verifier=secrets.token_urlsafe(_VERIFIER_BYTES) if pkce else "",
        return_path=return_path,
        phase=phase,
    )


def encode_state(state: ConnectionFlowState) -> str:
    plaintext = json.dumps(
        {
            "g": state.guild_id,
            "i": state.install_id,
            "c": state.connection_id,
            "u": state.user_id,
            "b": state.started_by,
            "v": state.verifier,
            "r": state.return_path,
            "p": state.phase,
            "x": state.installation_id,
        },
        separators=(",", ":"),
    )
    return encrypt_field(plaintext, SALT_PLUGIN_CONNECTION_FLOW)


def decode_state(
    token: str | None, *, max_age_seconds: int = STATE_MAX_AGE_SECONDS
) -> ConnectionFlowState:
    """The state a callback carries, or :class:`FlowStateError`."""
    if not token:
        raise FlowStateError("missing state")
    try:
        plaintext = decrypt_field(
            token, SALT_PLUGIN_CONNECTION_FLOW, ttl_seconds=max_age_seconds
        )
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise FlowStateError("invalid or expired state") from exc
    try:
        data = json.loads(plaintext)
        state = ConnectionFlowState(
            guild_id=int(data["g"]),
            install_id=int(data["i"]),
            connection_id=str(data["c"]),
            user_id=None if data.get("u") is None else int(data["u"]),
            started_by=int(data["b"]),
            verifier=str(data.get("v") or ""),
            return_path=str(data["r"]),
            phase=str(data["p"]),
            installation_id=None if data.get("x") is None else str(data["x"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise FlowStateError("malformed state") from exc
    if state.phase not in PHASES or not state.return_path.startswith("/"):
        raise FlowStateError("malformed state")
    return state
