"""The state a plug-in connection's vendor flow carries through the vendor.

Initiative runs every connection's flow, and nothing is stored while one is in
progress: what the callback needs to finish it travels in the ``state``
parameter as a Fernet token (the pattern :mod:`app.services.auth.oidc.
flow_state` uses for sign-in, under a salt of its own). It is confidential,
cannot be altered, and expires ten minutes after it was minted.

It names the install, the connection and the member (or none, for the
community's own connection), or, for a connection the platform makes for every
community, no community and no install but the registration's ``public_id``; the person who started it, the PKCE verifier,
the path to send the person back to, and the phase: ``install`` while a person is on the vendor's install
page, ``authorize`` once the authorization request is sent. An
installation-style flow's second leg carries the installation id the vendor's
setup address returned.

A flow an app began also carries the app's S256 challenge and how the flow is
handed back to it (:data:`HANDBACKS`): the app holds no session in the browser
the vendor returns to, so the flow ends in the app, which redeems it with the
verifier behind that challenge and its own session.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, replace
from enum import StrEnum

from cryptography.fernet import InvalidToken

from app.core.encryption import (
    SALT_PLUGIN_CONNECTION_FLOW,
    decrypt_field,
    encrypt_field,
)

__all__ = [
    "HANDBACKS",
    "PHASES",
    "STATE_MAX_AGE_SECONDS",
    "ConnectingApp",
    "ConnectionFlowState",
    "FlowStateError",
    "PluginConnectionOutcome",
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

#: How a flow an app began is handed back to it: ``https`` — this deployment's
#: own handback address, which the app catches before any browser loads it;
#: ``scheme`` — ``initiative://``, which the system hands the app.
HANDBACKS: frozenset[str] = frozenset({"https", "scheme"})

#: 64 random bytes: an 86-character verifier, within RFC 7636's 43..128.
_VERIFIER_BYTES = 64

#: The widest installation id a vendor's setup address may hand back.
MAX_INSTALLATION_ID_LENGTH = 64


class ConnectingApp(StrEnum):
    """The app starting a flow, which says how it can be handed back
    (``plugin_connection_flows.app_handback``)."""

    #: Opens the vendor in a window of its own, and catches the handback there.
    desktop = "desktop"
    #: Opens the vendor in the system's browser, and is handed a link.
    phone = "phone"


class PluginConnectionOutcome(StrEnum):
    """How a flow ended, as the landing page and the app read it."""

    connected = "connected"
    refused = "refused"
    expired = "expired"
    not_recorded = "not_recorded"
    awaiting_approval = "awaiting_approval"
    sign_in_required = "sign_in_required"
    #: A browser loaded the handback of a flow an app began, which only that
    #: app finishes.
    app_only = "app_only"


class FlowStateError(Exception):
    """The state is missing, expired, altered or malformed."""


@dataclass(frozen=True)
class ConnectionFlowState:
    #: The community and install, or ``None`` for the platform's connection.
    guild_id: int | None
    install_id: int | None
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
    #: The registration whose connection the platform makes for every
    #: community; ``None`` for a community's.
    public_id: str | None = None
    #: The S256 challenge of the app that began the flow, and how the flow is
    #: handed back to it (one of :data:`HANDBACKS`). Both empty for a flow a
    #: browser began.
    app_challenge: str = ""
    handback: str = ""

    @property
    def for_platform(self) -> bool:
        return self.public_id is not None

    def authorizing(self, installation_id: str | None) -> ConnectionFlowState:
        """The same flow, on its way to the authorization endpoint."""
        return replace(self, phase="authorize", installation_id=installation_id)


def code_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier (RFC 7636 §4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_state(
    *,
    guild_id: int | None,
    install_id: int | None,
    connection_id: str,
    user_id: int | None,
    started_by: int,
    return_path: str,
    pkce: bool,
    phase: str,
    public_id: str | None = None,
    app_challenge: str = "",
    handback: str = "",
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
        public_id=public_id,
        app_challenge=app_challenge,
        handback=handback,
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
            "s": state.public_id,
            "a": state.app_challenge,
            "h": state.handback,
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
            guild_id=None if data["g"] is None else int(data["g"]),
            install_id=None if data["i"] is None else int(data["i"]),
            connection_id=str(data["c"]),
            user_id=None if data.get("u") is None else int(data["u"]),
            started_by=int(data["b"]),
            verifier=str(data.get("v") or ""),
            return_path=str(data["r"]),
            phase=str(data["p"]),
            installation_id=None if data.get("x") is None else str(data["x"]),
            public_id=None if data.get("s") is None else str(data["s"]),
            app_challenge=str(data.get("a") or ""),
            handback=str(data.get("h") or ""),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise FlowStateError("malformed state") from exc
    if state.phase not in PHASES or not state.return_path.startswith("/"):
        raise FlowStateError("malformed state")
    # A community's flow names its install; the platform's names neither.
    if (state.guild_id is None) != state.for_platform or (
        (state.install_id is None) != state.for_platform
    ):
        raise FlowStateError("malformed state")
    # An app's flow says how it goes back to the app; a browser's says nothing.
    if (state.handback or state.app_challenge) and (
        state.handback not in HANDBACKS or not state.app_challenge
    ):
        raise FlowStateError("malformed state")
    return state
