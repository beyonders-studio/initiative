"""The vendor flows Initiative runs for a plug-in's connections.

A connection whose manifest declares a ``flow`` is established by Initiative,
not by the plug-in. Initiative is the OAuth client: it sends the person to the
vendor, takes the code back at its own callback, exchanges it, keeps the
tokens in its custody, refreshes them, and ends the grant when the connection
ends. The plug-in never holds the vendor client's secret or a refresh token; it
asks for a usable access token by ``connection_ref`` when it needs one.

The vendor client itself is the deployment's: its values come from the plug-in's
registration (:mod:`app.services.marketplace.vendor_values`) and are named in
the manifest as ``{vendor.<key>}``. A URL may also name one of the
connection's own stored values as ``{<key>}``.

Three things happen here and nowhere else:

* **The flow.** :func:`start_url` builds where the person is sent, with the
  state (:mod:`app.services.tenant.connection_flow_state`) carrying everything
  the callback needs. :func:`complete_setup` and :func:`complete_callback` are
  the two returns. An installation-style flow (``install_url``) sends the
  person to the vendor's install page first; the vendor returns to the setup
  address with the installation's id, and one authorization trip follows so
  ``after_connect`` (the plug-in's hook, or a declarative plug-in's request) can check
  who installed it.
* **Tokens.** :func:`seal_tokens` and :func:`unseal_tokens` hold a token set
  in a connection's stored values under reserved keys; :func:`refresh_tokens`
  renews one; :func:`mint_jwt_bearer` mints a token for a connection that
  declares a ``jwt_bearer`` token, and caches it.
* **Hooks.** :func:`call_hook` calls the plug-in at ``POST {base}/v1/hooks/{name}``
  with a ``lifecycle`` context token naming the install and the hook. Only
  :mod:`app.services.marketplace.community_hooks` calls it, under one lock per
  community and plug-in: the hooks about the community, queued and retried, and
  ``after_connect``, ``webhook`` and ``schedule``, sent at once by its
  ``call_now``. A ``revoke`` rides that queue too (``plugin_revocation``).

Every call to a vendor goes through the pinned egress helper, https only, with
a timeout and a size cap. A call to the plug-in goes to its registration's
address, as an endpoint call does.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
import jwt
from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rules import SURFACE_PLUGINS
from app.services.platform import rules
from app.core.config import settings
from app.core.encryption import SALT_PLUGIN_CONFIG, decrypt_field, encrypt_field
from app.core.errors import CodedError
from app.core.messages import GuildPluginMessages, PluginChannelMessages
from app.core.security import PluginPlatformSigningNotConfiguredError
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.access_grant import AccessLevel
from app.models.platform.guild import (
    LIVE_STATUS_VALUES,
    CommunityStatus,
    Guild,
    GuildMembership,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.services.auth.oidc._http import (
    OidcHttpError,
    OidcHttpStatusError,
    post_form_json_pinned,
)
from app.services.marketplace import (
    expressions,
    plugin_installs,
    registration_lookup,
)
from app.services.marketplace.community_status import community_status
from app.services.marketplace.context_jwt import mint_context_token
from app.services.marketplace.plugin_data import (
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT_SECONDS,
)
from app.services.marketplace.plugin_refs import (
    PluginNameRefused,
    ensure_plugin_guild_ref,
)
from app.services.marketplace.vendor_values import load_vendor_values
from app.services.platform import access_grants as access_grants_service
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import plugin_config as plugin_config_service
from app.services.tenant import plugin_connections as connections_service
from app.services.tenant.connection_flow_state import (
    MAX_INSTALLATION_ID_LENGTH,
    ConnectionFlowState,
    FlowStateError,
    code_challenge,
    decode_state,
    encode_state,
    new_state,
)
from app.services.tenant.plugin_config import (
    install_settings,
    mint_connection_ref,
    token_of,
    without_tokens,
)
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CALLBACK_PATH",
    "OUTCOMES",
    "REFRESH_WINDOW_SECONDS",
    "SETUP_PATH",
    "ConnectionFlowError",
    "HookError",
    "TokenSet",
    "call_hook",
    "callback_url",
    "clear_token_cache",
    "forget_minted",
    "complete_callback",
    "complete_setup",
    "flow_of",
    "landing_url",
    "mint_jwt_bearer",
    "refresh_tokens",
    "seal_tokens",
    "setup_url",
    "start_url",
    "unseal_tokens",
    "webhook_url",
]

#: Where the vendor returns a person, on this deployment's own address.
CALLBACK_PATH = "/api/v1/plugin-connections/callback"
#: Where an installation-style vendor returns a person from its install page.
SETUP_PATH = "/api/v1/plugin-connections/setup"
#: Where a vendor sends a plug-in's webhooks, followed by the plug-in's public_id.
WEBHOOK_PATH = "/api/v1/plugin-hooks"

#: How a flow ended, as the landing page reads it.
OUTCOMES: frozenset[str] = frozenset(
    {
        "connected",
        "refused",
        "expired",
        "not_recorded",
        "awaiting_approval",
        "sign_in_required",
        # Another community on this deployment holds the vendor installation.
        "taken",
    }
)

#: A stored token this close to its expiry is refreshed before it is handed out.
REFRESH_WINDOW_SECONDS = 120
#: A minted token is reused until this long before it expires.
_MINTED_REUSE_MARGIN_SECONDS = 60
#: What a vendor's token endpoint may take and answer with.
VENDOR_TIMEOUT_SECONDS = 10.0
VENDOR_MAX_RESPONSE_BYTES = 512 * 1024
#: The hooks Initiative calls.
HOOKS_PATH = "/v1/hooks"
HOOK_NAMES: frozenset[str] = frozenset(
    {"after_connect", "revoke", "webhook", "schedule", "entitlement"}
    # The hooks about the community's install, delivered by
    # ``app.services.marketplace.community_hooks``.
    | {"installed", "uninstalled", "erase", "community_status"}
)
#: The widest account label kept, matching what the members view shows.
MAX_ACCOUNT_LABEL_LENGTH = 200

#: Injectable for tests: the transport every vendor and plug-in call uses.
http_transport: httpx.AsyncBaseTransport | None = None


class ConnectionFlowError(CodedError):
    """A step of a connection's flow or token that could not go ahead."""

    status_code = 409


class VendorRefusedError(Exception):
    """The vendor answered, and said no."""


class HookError(Exception):
    """The plug-in's hook could not be reached, or answered with something else.

    ``status`` is the HTTP status the plug-in answered with, when it answered.
    """

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class HookNameRefused(HookError):
    """The plug-in may not be given a name for the community (no live install,
    or an erase is pending), so it has none to be told under and nothing is
    sent."""


class RevocationAnsweredError(HookError):
    """The vendor answered a revocation with something other than success."""

    def __init__(self, status: int) -> None:
        super().__init__(f"revocation answered {status}", status=status)


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: Optional[str] = None
    #: Epoch seconds, or ``None`` when the vendor did not say.
    expires_at: Optional[int] = None
    refresh_expires_at: Optional[int] = None


# --- reading a connection's declaration --------------------------------------


def flow_of(connection: Mapping[str, Any] | None) -> Optional[dict[str, Any]]:
    """The connection's ``flow``, when it declares one."""
    flow = (connection or {}).get("flow")
    return flow if isinstance(flow, dict) else None


# --- addresses --------------------------------------------------------------


def _app_url() -> str:
    return settings.APP_URL.rstrip("/")


def callback_url() -> str:
    """The redirect address a vendor's client registers for every flow."""
    return f"{_app_url()}{CALLBACK_PATH}"


def setup_url() -> str:
    """The address an installation-style vendor returns to from its install
    page."""
    return f"{_app_url()}{SETUP_PATH}"


def webhook_url(public_id: str) -> str:
    """The address a vendor sends this plug-in's webhooks to."""
    return f"{_app_url()}{WEBHOOK_PATH}/{public_id}"


def return_path(public_id: str, connection_id: str) -> str:
    """The landing page's path, naming the plug-in and the connection."""
    return f"/plugins/connected?{urlencode([('plugin', public_id), ('connection', connection_id)])}"


def landing_url(path: Optional[str], outcome: str) -> str:
    """Where a person is sent when a flow ends, with how it ended."""
    base = path if path and path.startswith("/") else "/plugins/connected"
    joiner = "&" if "?" in base else "?"
    return f"{_app_url()}{base}{joiner}{urlencode([('outcome', outcome)])}"


# --- templates --------------------------------------------------------------


def render(
    template: str,
    *,
    vendor: Mapping[str, str],
    fields: Mapping[str, Any],
    in_url: bool,
) -> str:
    """Fill ``{vendor.<key>}`` and ``{<key>}`` in one declared value.

    A vendor value is the operator's and goes in as it is. A connection's own
    value is percent-encoded in a URL, so it stays one segment. A name with no
    value refuses the step rather than sending a half-filled address.
    """
    out: list[str] = []
    position = 0
    while True:
        start = template.find("{", position)
        if start == -1:
            out.append(template[position:])
            break
        end = template.find("}", start + 1)
        if end == -1:
            out.append(template[position:])
            break
        out.append(template[position:start])
        name = template[start + 1 : end]
        if name.startswith("vendor."):
            value = vendor.get(name[len("vendor.") :])
            if not value:
                raise ConnectionFlowError(
                    GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED
                )
            out.append(value)
        else:
            raw = fields.get(name)
            if raw is None or raw == "":
                raise ConnectionFlowError(
                    GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED
                )
            text = str(raw)
            out.append(quote(text, safe="-._~") if in_url else text)
        position = end + 1
    return "".join(out)


def _render_url(
    template: Optional[str], *, vendor: Mapping[str, str], fields: Mapping[str, Any]
) -> str:
    if not template:
        raise ConnectionFlowError(GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED)
    url = render(template, vendor=vendor, fields=fields, in_url=True)
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise ConnectionFlowError(GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED)
    return url


def _with_query(url: str, params: list[tuple[str, str]]) -> str:
    """``url`` with ``params`` added to whatever query it already carries."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + params
    return urlunsplit(parts._replace(query=urlencode(query)))


def _client(
    flow: Mapping[str, Any], *, vendor: Mapping[str, str], fields: Mapping[str, Any]
) -> tuple[str, Optional[str]]:
    client_id = render(
        str(flow.get("client_id") or ""), vendor=vendor, fields=fields, in_url=False
    )
    if not client_id:
        raise ConnectionFlowError(GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED)
    secret_template = flow.get("client_secret")
    secret = (
        render(str(secret_template), vendor=vendor, fields=fields, in_url=False)
        if secret_template
        else None
    )
    return client_id, secret


# --- starting ---------------------------------------------------------------


def authorize_url(
    flow: Mapping[str, Any],
    *,
    vendor: Mapping[str, str],
    fields: Mapping[str, Any],
    state: ConnectionFlowState,
) -> str:
    """The vendor's authorization request (RFC 6749 §4.1.1), with PKCE when the
    flow sends a challenge (RFC 7636)."""
    url = _render_url(flow.get("authorize_url"), vendor=vendor, fields=fields)
    client_id, _ = _client(flow, vendor=vendor, fields=fields)
    params: list[tuple[str, str]] = [
        ("response_type", "code"),
        ("client_id", client_id),
        ("redirect_uri", callback_url()),
        ("state", encode_state(state)),
    ]
    scopes = [scope for scope in flow.get("scopes") or [] if isinstance(scope, str)]
    if scopes:
        params.append(("scope", " ".join(scopes)))
    if state.verifier:
        params += [
            ("code_challenge", code_challenge(state.verifier)),
            ("code_challenge_method", "S256"),
        ]
    for key, value in (flow.get("authorize_params") or {}).items():
        if isinstance(key, str) and isinstance(value, str):
            params.append(
                (key, render(value, vendor=vendor, fields=fields, in_url=False))
            )
    return _with_query(url, params)


async def start_url(
    *,
    plugin: GuildPlugin,
    connection: Mapping[str, Any],
    guild_id: int,
    user_id: Optional[int],
    started_by: int,
    public_id: str,
    fields: Mapping[str, Any],
) -> str:
    """Where to send the person starting this connection's flow.

    The vendor's install page for an installation-style flow, its
    authorization endpoint otherwise. Nothing is stored: the state carries it.
    """
    flow = flow_of(connection)
    if flow is None:
        raise ConnectionFlowError(GuildPluginMessages.CONNECTION_NOT_INTERACTIVE)
    vendor = await load_vendor_values(public_id)
    install = flow.get("install_url")
    state = new_state(
        guild_id=guild_id,
        install_id=plugin.id,
        connection_id=str(connection.get("id")),
        user_id=user_id,
        started_by=started_by,
        return_path=return_path(public_id, str(connection.get("id"))),
        pkce=flow.get("pkce") is not False,
        phase="install" if install else "authorize",
    )
    if install:
        url = _render_url(install, vendor=vendor, fields=fields)
        return _with_query(url, [("state", encode_state(state))])
    return authorize_url(flow, vendor=vendor, fields=fields, state=state)


# --- tokens -----------------------------------------------------------------


def _epoch(value: Any, *, now: int) -> Optional[int]:
    """An ``expires_in`` in seconds, as an epoch time."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return now + int(value)
    if isinstance(value, str) and value.isdigit():
        return now + int(value)
    return None


def _token_set(body: Any, *, previous_refresh: Optional[str] = None) -> TokenSet:
    """A token endpoint's answer (RFC 6749 §5.1), or :class:`VendorRefusedError`.

    Some vendors answer an error with a success status, so an ``error`` member
    is a refusal whatever the status was.
    """
    if not isinstance(body, dict) or body.get("error"):
        raise VendorRefusedError(str((body or {}).get("error") or "no token"))
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise VendorRefusedError("no access_token")
    now = int(time.time())
    refresh = body.get("refresh_token")
    return TokenSet(
        access_token=access,
        refresh_token=refresh
        if isinstance(refresh, str) and refresh
        else previous_refresh,
        expires_at=_epoch(body.get("expires_in"), now=now),
        refresh_expires_at=_epoch(body.get("refresh_token_expires_in"), now=now),
    )


async def _token_request(url: str, form: dict[str, str]) -> Any:
    try:
        return await post_form_json_pinned(
            url,
            form,
            transport=http_transport,
            timeout_seconds=VENDOR_TIMEOUT_SECONDS,
            max_response_bytes=VENDOR_MAX_RESPONSE_BYTES,
        )
    except OidcHttpStatusError as exc:
        if 400 <= exc.status < 500:
            raise VendorRefusedError(str(exc)) from exc
        raise


async def exchange_code(
    flow: Mapping[str, Any],
    *,
    vendor: Mapping[str, str],
    fields: Mapping[str, Any],
    code: str,
    verifier: str,
) -> TokenSet:
    """The authorization code, exchanged at the vendor's token endpoint (RFC
    6749 §4.1.3), with the client's credentials in the body."""
    url = _render_url(flow.get("token_url"), vendor=vendor, fields=fields)
    client_id, secret = _client(flow, vendor=vendor, fields=fields)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url(),
        "client_id": client_id,
    }
    if secret:
        form["client_secret"] = secret
    if verifier:
        form["code_verifier"] = verifier
    return _token_set(await _token_request(url, form))


async def refresh_tokens(
    flow: Mapping[str, Any],
    *,
    vendor: Mapping[str, str],
    fields: Mapping[str, Any],
    refresh_token: str,
) -> TokenSet:
    """A new token set from a refresh token (RFC 6749 §6). Raises
    :class:`VendorRefusedError` when the vendor turns it down, and
    :class:`OidcHttpError` when it could not be asked."""
    url = _render_url(flow.get("token_url"), vendor=vendor, fields=fields)
    client_id, secret = _client(flow, vendor=vendor, fields=fields)
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if secret:
        form["client_secret"] = secret
    return _token_set(await _token_request(url, form), previous_refresh=refresh_token)


def seal_tokens(
    tokens: TokenSet,
    *,
    config: Mapping[str, Any] | None,
    secrets: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A connection's stored maps with ``tokens`` in the reserved keys."""
    plain = without_tokens(config)
    sealed = without_tokens(secrets)
    sealed["access_token"] = encrypt_field(tokens.access_token, SALT_PLUGIN_CONFIG)
    if tokens.refresh_token:
        sealed["refresh_token"] = encrypt_field(
            tokens.refresh_token, SALT_PLUGIN_CONFIG
        )
    if tokens.expires_at is not None:
        plain["expires_at"] = tokens.expires_at
    if tokens.refresh_expires_at is not None:
        plain["refresh_expires_at"] = tokens.refresh_expires_at
    return plain, sealed


def unseal_tokens(
    config: Mapping[str, Any] | None, secrets: Mapping[str, Any] | None
) -> Optional[TokenSet]:
    """The token set a connection holds, or ``None`` when it holds none."""
    sealed = secrets or {}
    access = sealed.get("access_token")
    if not isinstance(access, str):
        return None
    refresh = sealed.get("refresh_token")
    plain = config or {}

    def _time(key: str) -> Optional[int]:
        value = plain.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return TokenSet(
        access_token=decrypt_field(access, SALT_PLUGIN_CONFIG),
        refresh_token=decrypt_field(refresh, SALT_PLUGIN_CONFIG)
        if isinstance(refresh, str)
        else None,
        expires_at=_time("expires_at"),
        refresh_expires_at=_time("refresh_expires_at"),
    )


def needs_refresh(tokens: TokenSet, *, now: Optional[int] = None) -> bool:
    if tokens.expires_at is None:
        return False
    current = int(time.time()) if now is None else now
    return tokens.expires_at - current <= REFRESH_WINDOW_SECONDS


# --- minted tokens ----------------------------------------------------------


@dataclass
class _Minted:
    token: str
    expires_at: Optional[int]
    reuse_until: float


#: Minted tokens, per worker, by the connection and the exact request that
#: minted them. Each token minted drops those past reuse.
_minted: dict[tuple[Any, ...], _Minted] = {}
#: How many times each connection's minted tokens were forgotten, so a mint
#: that was waiting on the vendor when they were keeps nothing.
_forgotten: dict[tuple[Any, ...], int] = {}


def clear_token_cache() -> None:
    """Forget every minted token."""
    _minted.clear()


def forget_minted(guild_id: int, install_id: int, connection_id: str) -> None:
    """Forget the tokens minted for one community connection, as its stored
    values go, those a mint still waiting for will answer included."""
    connection = (guild_id, install_id, connection_id)
    _forgotten[connection] = _forgotten.get(connection, 0) + 1
    for key in [held for held in _minted if held[:3] == connection]:
        del _minted[key]


def _keep_minted(key: tuple[Any, ...], minted: _Minted) -> None:
    """Hold ``minted`` under ``key``, and drop every token past reuse."""
    now = time.monotonic()
    for stale in [held for held, one in _minted.items() if one.reuse_until <= now]:
        del _minted[stale]
    _minted[key] = minted


def _parse_expiry(body: Mapping[str, Any], *, now: int) -> Optional[int]:
    raw = body.get("expires_at")
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return _epoch(body.get("expires_in"), now=now)


def _filled(value: Any, *, vendor: Mapping[str, str], fields: Mapping[str, Any]) -> Any:
    """``value`` with ``{vendor.<key>}`` and ``{<key>}`` filled in every string
    it holds, at any depth."""
    if isinstance(value, str):
        return render(value, vendor=vendor, fields=fields, in_url=False)
    if isinstance(value, dict):
        return {
            key: _filled(child, vendor=vendor, fields=fields)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_filled(child, vendor=vendor, fields=fields) for child in value]
    return value


async def _answered_body(text: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """What a token's ``exchange_body`` expression answers over the
    connection's own fields, which must be an object."""
    try:
        answer = await expressions.evaluate(text, {"connection": dict(fields)})
    except expressions.ExpressionError as exc:
        logger.warning("plug-in connection: the exchange body failed (%s)", exc)
        raise ConnectionFlowError(PluginChannelMessages.TOKEN_UNAVAILABLE, 502) from exc
    if not isinstance(answer, dict):
        logger.warning("plug-in connection: the exchange body is not an object")
        raise ConnectionFlowError(PluginChannelMessages.TOKEN_UNAVAILABLE, 502)
    return answer


async def mint_jwt_bearer(
    spec: Mapping[str, Any],
    *,
    vendor: Mapping[str, str],
    fields: Mapping[str, Any],
    cache_key: tuple[Any, ...],
) -> TokenSet:
    """A token for a connection that declares a ``jwt_bearer`` token.

    A JWT signed with the vendor key is posted to the exchange address, with
    the token's ``exchange_body`` when it declares one: the object with its
    names filled, or what its expression answers over the connection's own
    fields. The answer's token is reused until a minute before it expires.
    """
    url = _render_url(spec.get("exchange_url"), vendor=vendor, fields=fields)
    issuer = render(
        str(spec.get("iss") or ""), vendor=vendor, fields=fields, in_url=False
    )
    key = render(str(spec.get("key") or ""), vendor=vendor, fields=fields, in_url=False)
    if not issuer or not key:
        raise ConnectionFlowError(GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED)
    declared = spec.get("exchange_body")
    body = (
        _filled(declared, vendor=vendor, fields=fields)
        if isinstance(declared, dict)
        else None
    )
    # An expression's body is made from the connection's fields alone, so
    # those key it, and it is evaluated only when no token is held for them.
    asked = (declared, fields) if isinstance(declared, str) else body
    full_key = (
        *cache_key,
        url,
        issuer,
        hashlib.sha256(
            json.dumps(asked, sort_keys=True, default=str).encode()
        ).hexdigest(),
    )
    cached = _minted.get(full_key)
    if cached is not None and cached.reuse_until > time.monotonic():
        return TokenSet(access_token=cached.token, expires_at=cached.expires_at)
    forgotten = _forgotten.get(cache_key[:3], 0)
    if isinstance(declared, str):
        body = await _answered_body(declared, fields)

    lifetime = spec.get("lifetime")
    seconds = lifetime if isinstance(lifetime, int) and lifetime > 0 else 540
    now = int(time.time())
    try:
        assertion = jwt.encode(
            # Issued a minute early, for a vendor whose clock runs behind.
            {"iat": now - 60, "exp": now - 60 + seconds, "iss": issuer},
            key,
            algorithm=str(spec.get("alg") or "RS256"),
        )
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        logger.warning("plug-in connection: the vendor key does not sign (%s)", exc)
        raise ConnectionFlowError(
            GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED
        ) from exc

    try:
        response = await request_public_target(
            "POST",
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {assertion}",
            },
            json=body,
            timeout=VENDOR_TIMEOUT_SECONDS,
            transport=http_transport,
            max_bytes=VENDOR_MAX_RESPONSE_BYTES,
        )
        body = response.json() if response.status_code < 400 else None
    except (
        httpx.HTTPError,
        ResponseTooLargeError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
        ValueError,
    ) as exc:
        logger.warning("plug-in connection: token exchange failed (%s)", exc)
        raise ConnectionFlowError(PluginChannelMessages.TOKEN_UNAVAILABLE, 502) from exc
    if not isinstance(body, dict):
        raise ConnectionFlowError(PluginChannelMessages.TOKEN_UNAVAILABLE, 502)
    token = body.get("token") or body.get("access_token")
    if not isinstance(token, str) or not token:
        raise ConnectionFlowError(PluginChannelMessages.TOKEN_UNAVAILABLE, 502)
    expires_at = _parse_expiry(body, now=now)
    remaining = (expires_at - now) if expires_at is not None else 0
    if remaining > _MINTED_REUSE_MARGIN_SECONDS and forgotten == _forgotten.get(
        cache_key[:3], 0
    ):
        _keep_minted(
            full_key,
            _Minted(
                token=token,
                expires_at=expires_at,
                reuse_until=time.monotonic() + remaining - _MINTED_REUSE_MARGIN_SECONDS,
            ),
        )
    return TokenSet(access_token=token, expires_at=expires_at)


# --- hooks ------------------------------------------------------------------


async def call_hook(
    name: str,
    *,
    public_id: str,
    base_url: str,
    guild_id: int,
    install_id: int,
    body: Mapping[str, Any],
    guild_ref: Optional[str] = None,
) -> Optional[Any]:
    """Call one of the plug-in's hooks and return its JSON answer (``None`` for an
    empty one). Raises :class:`HookError` for anything but a 2xx answer, with
    the status the plug-in answered with when it answered.

    The token names the community by what the plug-in calls it, minted on first
    use; ``guild_ref`` hands one in instead, for a hook that must not mint a
    name (``erase``). ``install_id`` is the install the hook is about, or ``0``
    when the community has none to name."""
    if name not in HOOK_NAMES:
        raise HookError(f"unknown hook {name!r}")
    if guild_ref is None:
        try:
            guild_ref = await ensure_plugin_guild_ref(
                guild_id=guild_id, public_id=public_id
            )
        except PluginNameRefused as exc:
            raise HookNameRefused(f"hook {name}: no name for the community") from exc
    standing = await community_status(guild_id)
    try:
        token, _ = mint_context_token(
            public_id=public_id,
            guild_ref=guild_ref,
            plugin_install_id=install_id,
            scope="lifecycle",
            hook=name,
            community_status=standing,
        )
    except PluginPlatformSigningNotConfiguredError as exc:
        raise HookError("signing is not configured") from exc
    try:
        response = await request_public_target(
            "POST",
            f"{base_url.rstrip('/')}{HOOKS_PATH}/{name}",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            content=json.dumps(dict(body)).encode("utf-8"),
            timeout=httpx.Timeout(
                REQUEST_TIMEOUT_SECONDS, connect=REQUEST_TIMEOUT_SECONDS
            ),
            transport=http_transport,
            # A plug-in service is an operator-configured destination, often on
            # the deployment's own network.
            allow_private=True,
            max_bytes=MAX_RESPONSE_BYTES,
        )
    except (
        httpx.HTTPError,
        ResponseTooLargeError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
    ) as exc:
        raise HookError(f"hook {name} could not be reached: {exc}") from exc
    if not 200 <= response.status_code < 300:
        raise HookError(
            f"hook {name} answered {response.status_code}", status=response.status_code
        )
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HookError(
            f"hook {name} did not answer with JSON", status=response.status_code
        ) from exc


@dataclass(frozen=True)
class AfterConnect:
    refused: bool
    values: dict[str, Any]
    account_label: Optional[str]
    #: What a declarative refusal answers.
    code: Optional[str] = None


def connected(answer: Mapping[str, Any]) -> AfterConnect:
    """An ``after_connect`` answer's managed values and account label."""
    values = answer.get("values") or {}
    if not isinstance(values, dict):
        raise HookError("after_connect values is not an object")
    label = answer.get("account_label")
    cleaned = label.strip()[:MAX_ACCOUNT_LABEL_LENGTH] if isinstance(label, str) else ""
    return AfterConnect(refused=False, values=values, account_label=cleaned or None)


async def after_connect(
    *,
    public_id: str,
    base_url: str,
    guild_id: int,
    install_id: int,
    connection_id: str,
    actor: str,
    access_token: str,
    params: Mapping[str, str],
) -> AfterConnect:
    # Sent through the one door every hook goes through (community_hooks).
    from app.services.marketplace import community_hooks

    answer = await community_hooks.call_now(
        "after_connect",
        public_id=public_id,
        base_url=base_url,
        guild_id=guild_id,
        install_id=install_id,
        body={
            "connection": connection_id,
            "actor": actor,
            "access_token": access_token,
            "params": dict(params),
        },
    )
    if not isinstance(answer, dict):
        raise HookError("after_connect answered with something other than an object")
    if answer.get("refuse") is True:
        return AfterConnect(refused=True, values={}, account_label=None)
    return connected(answer)


# --- finishing --------------------------------------------------------------


@dataclass(frozen=True)
class _Loaded:
    plugin: GuildPlugin
    connection: dict[str, Any]
    flow: dict[str, Any]
    public_id: str
    base_url: str


async def _load_for_flow(
    session: AsyncSession, state: ConnectionFlowState
) -> Optional[_Loaded]:
    """The install and connection a state names, with the session — one from
    its community's cohort — routed into that community, or ``None`` when the
    flow can no longer finish."""
    await set_rls_context(session, Unattributed())
    guild = (
        await session.exec(select(Guild).where(Guild.id == state.guild_id))
    ).first()
    if (
        guild is None
        or guild.status not in LIVE_STATUS_VALUES
        or guild.status == CommunityStatus.read_only.value
    ):
        return None
    if state.user_id is not None:
        member = (
            await session.exec(
                select(GuildMembership.user_id).where(
                    GuildMembership.guild_id == state.guild_id,
                    GuildMembership.user_id == state.user_id,
                )
            )
        ).first()
        if member is None:
            return None
    session.expunge_all()
    await set_rls_context(session, SystemGuild(state.guild_id))
    plugin = (
        await session.exec(
            select(GuildPlugin).where(GuildPlugin.id == state.install_id)
        )
    ).first()
    if plugin is None or not plugin.enabled:
        return None
    connection = plugin_config_service.connection_by_id(
        plugin.definition, state.connection_id
    )
    flow = flow_of(connection)
    if connection is None or flow is None:
        return None
    expected = "interactive" if state.user_id is not None else "static"
    if connection.get("scope") != expected:
        return None
    registration = await registration_lookup.registration_for_definition(
        plugin.definition, listing_uid=plugin.listing_uid
    )
    if registration is None or not registration.live_in(state.guild_id):
        return None
    return _Loaded(
        plugin=plugin,
        connection=connection,
        flow=flow,
        public_id=registration.public_id,
        base_url=registration.base_url,
    )


def _clean_installation_id(value: Optional[str]) -> Optional[str]:
    """An installation id as a vendor's setup address returns it: letters,
    digits, ``-`` and ``_``, and short."""
    if not value or len(value) > MAX_INSTALLATION_ID_LENGTH:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return value if all(char in allowed for char in value) else None


async def _is_member(session: AsyncSession, state: ConnectionFlowState) -> bool:
    """Whether the flow's starter holds a membership row in its community."""
    member = (
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == state.guild_id,
                GuildMembership.user_id == state.started_by,
            )
        )
    ).first()
    return member is not None


async def _person_outcome(
    state: ConnectionFlowState, signed_in: Optional[int]
) -> Optional[str]:
    """Whether the person finishing a flow may: the landing outcome when not,
    ``None`` when they may go on.

    The flow is finished only by the signed-in person who started it. A
    community connection is finished only while that person still holds the
    community's seat, and may still change what the seat holds: the
    membership row's seat may, a lent seat only beside a live ``read_write``
    content grant — what ``require_grant_writes`` asks of the route that
    started it.
    """
    if signed_in is None or signed_in != state.started_by:
        return "sign_in_required"
    if state.user_id is None:
        async with cohorts.system_session(state.guild_id) as session:
            await set_rls_context(session, Unattributed())
            holds = (
                await session.exec(
                    select(func.guild_superadmin(state.guild_id, state.started_by))
                )
            ).first()
            if holds and not await _is_member(session, state):
                content = await access_grants_service.get_live_grant(
                    session, user_id=state.started_by, guild_id=state.guild_id
                )
                holds = (
                    content is not None
                    and content.access_level == AccessLevel.read_write.value
                )
        if not holds:
            return "refused"
    return None


async def complete_setup(
    *,
    state_token: Optional[str],
    installation_id: Optional[str],
    setup_action: Optional[str],
    signed_in: Optional[int],
) -> str:
    """The return from an installation-style vendor's install page.

    Answers the address to send the person to next: the authorization
    endpoint, carrying the claimed installation id in a fresh state, or the
    landing page when the install is waiting on someone's approval or cannot
    go on.
    """
    try:
        state = decode_state(state_token)
    except FlowStateError:
        return landing_url(None, "expired")
    if state.phase != "install":
        return landing_url(state.return_path, "expired")
    outcome = await _person_outcome(state, signed_in)
    if outcome is not None:
        return landing_url(state.return_path, outcome)
    if setup_action == "request":
        return landing_url(state.return_path, "awaiting_approval")
    claimed = _clean_installation_id(installation_id)
    if claimed is None:
        return landing_url(state.return_path, "not_recorded")

    async with cohorts.system_session(state.guild_id) as session:
        loaded = await _load_for_flow(session, state)
        if loaded is None:
            return landing_url(state.return_path, "not_recorded")
        fields = without_tokens((loaded.plugin.config or {}).get(state.connection_id))
    try:
        vendor = await load_vendor_values(loaded.public_id)
        return authorize_url(
            loaded.flow,
            vendor=vendor,
            fields=fields,
            state=state.authorizing(claimed),
        )
    except ConnectionFlowError:
        return landing_url(state.return_path, "not_recorded")


async def complete_callback(
    *,
    state_token: Optional[str],
    code: Optional[str],
    error: Optional[str],
    signed_in: Optional[int],
) -> str:
    """The vendor's return with an authorization code. Exchanges it, asks the
    plug-in's ``after_connect`` hook when the flow says so, stores the result, and
    answers the landing page's address with how it ended."""
    try:
        state = decode_state(state_token)
    except FlowStateError:
        return landing_url(None, "expired")
    if state.phase != "authorize":
        return landing_url(state.return_path, "expired")
    outcome = await _person_outcome(state, signed_in)
    if outcome is not None:
        return landing_url(state.return_path, outcome)
    if error or not code:
        return landing_url(state.return_path, "refused")

    async with cohorts.system_session(state.guild_id) as session:
        loaded = await _load_for_flow(session, state)
        if loaded is None:
            return landing_url(state.return_path, "not_recorded")
        fields = without_tokens((loaded.plugin.config or {}).get(state.connection_id))
        install_id = loaded.plugin.id
        definition = loaded.plugin.definition
        installed = install_settings(loaded.plugin)

    # The vendor and the plug-in are asked with no transaction open. What they
    # answer is stored against the install as it stands once they have.
    try:
        vendor = await load_vendor_values(loaded.public_id)
        tokens = await exchange_code(
            loaded.flow,
            vendor=vendor,
            fields=fields,
            code=code,
            verifier=state.verifier,
        )
    except VendorRefusedError as exc:
        logger.info("plug-in connection: the vendor refused the code (%s)", exc)
        return landing_url(state.return_path, "refused")
    except (ConnectionFlowError, OidcHttpError) as exc:
        logger.warning("plug-in connection: the code exchange failed (%s)", exc)
        return landing_url(state.return_path, "not_recorded")

    values: dict[str, Any] = {}
    label: Optional[str] = None
    declared = loaded.flow.get("after_connect")
    if declared is True or isinstance(declared, dict):
        params: dict[str, str] = {}
        if state.installation_id is not None:
            params["installation_id"] = state.installation_id
        try:
            if isinstance(declared, dict):
                # Initiative makes a declarative plug-in's request itself.
                from app.services.marketplace import declarative

                answer = await declarative.after_connect(
                    definition,
                    declared,
                    params=params,
                    access_token=tokens.access_token,
                    installed=installed,
                )
            else:
                answer = await after_connect(
                    public_id=loaded.public_id,
                    base_url=loaded.base_url,
                    guild_id=state.guild_id,
                    install_id=install_id,
                    connection_id=state.connection_id,
                    actor="member" if state.user_id is not None else "installation",
                    access_token=tokens.access_token,
                    params=params,
                )
        except HookError as exc:
            logger.warning("plug-in connection: after_connect failed (%s)", exc)
            return landing_url(state.return_path, "not_recorded")
        if answer.refused:
            if answer.code is not None:
                logger.info(
                    "plug-in connection: after_connect refused (%s)", answer.code
                )
            return landing_url(state.return_path, "refused")
        values = answer.values
        label = answer.account_label

    async with cohorts.system_session(state.guild_id) as session:
        loaded = await _load_for_flow(session, state)
        if loaded is None:
            return landing_url(state.return_path, "not_recorded")
        plugin = loaded.plugin
        try:
            if state.user_id is not None:
                outcome = await _store_member(
                    session,
                    plugin=plugin,
                    connection=loaded.connection,
                    user_id=state.user_id,
                    tokens=tokens,
                    values=values,
                    label=label,
                )
            elif not await rules.community_value(
                session, state.guild_id, SURFACE_PLUGINS
            ):
                # The deployment closed the community's plug-ins while the
                # vendor's page was open: its own credential is no longer its
                # seat's to set.
                return landing_url(state.return_path, "refused")
            else:
                outcome = await _store_community(
                    session,
                    guild_id=state.guild_id,
                    plugin_id=plugin.id,
                    connection=loaded.connection,
                    tokens=None if loaded.flow.get("install_url") else tokens,
                    values=values,
                )
        except plugin_config_service.PluginConfigError as exc:
            logger.warning(
                "plug-in connection: after_connect values refused (%s)", exc.code
            )
            return landing_url(state.return_path, "not_recorded")
    return landing_url(state.return_path, outcome)


def _managed_only(connection: Mapping[str, Any], values: Mapping[str, Any]) -> dict:
    """Values for declared managed fields; anything else the hook sent is
    dropped."""
    managed = {
        field.get("key")
        for field in connection.get("fields") or []
        if isinstance(field, dict) and field.get("managed") is True
    }
    return {key: value for key, value in values.items() if key in managed}


async def _store_member(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    connection: Mapping[str, Any],
    user_id: int,
    tokens: TokenSet,
    values: Mapping[str, Any],
    label: Optional[str],
) -> str:
    """The member's row: their token set, the managed values and the account
    label, ``connected``. A blocked member's row is left as it is. Answers the
    landing outcome."""
    connection_id = str(connection.get("id"))
    row = (
        await session.exec(
            select(GuildPluginUserConnection)
            .where(
                GuildPluginUserConnection.plugin_id == plugin.id,
                GuildPluginUserConnection.connection_id == connection_id,
                GuildPluginUserConnection.user_id == user_id,
            )
            .with_for_update()
        )
    ).first()
    if row is not None and row.blocked_at is not None:
        return "not_recorded"
    if row is None:
        row = GuildPluginUserConnection(
            plugin_id=plugin.id,
            connection_id=connection_id,
            user_id=user_id,
            connection_ref=mint_connection_ref(),
            status="pending",
        )
    stored = (
        await connections_service.load_connection_secrets(session, row)
        if row.id is not None
        else {}
    )
    config, secrets = plugin_config_service.apply_connection_values(
        connection,
        _managed_only(connection, values),
        current=without_tokens(row.config),
        current_secrets=without_tokens(stored),
        allow_managed=True,
    )
    row.config, sealed = seal_tokens(tokens, config=config, secrets=secrets)
    row.account_label = label
    row.status = "connected"
    row.updated_at = datetime.now(timezone.utc)
    await connections_service.store_connection_secrets(session, row, sealed)
    await session.commit()
    return "connected"


async def _store_community(
    session: AsyncSession,
    *,
    guild_id: int,
    plugin_id: int,
    connection: Mapping[str, Any],
    tokens: Optional[TokenSet],
    values: Mapping[str, Any],
) -> str:
    """The community's own connection: the managed values, and the token set
    unless the flow is installation-style, whose person's token is not kept.
    Answers the landing outcome.

    The route the values give the install's vendor webhooks is claimed in the
    install index before anything is stored, and nothing is stored when
    another community holds it (``taken``). A store that fails after the claim
    has the index sweep write the row again from what the community holds."""
    plugin = await guild_plugins_service.lock_install(session, plugin_id)
    if plugin is None:
        return "not_recorded"
    connection_id = str(connection.get("id"))
    all_secrets = await guild_plugins_service.load_secrets(session, plugin)
    stored_config = (plugin.config or {}).get(connection_id) or {}
    stored_secrets = all_secrets.get(connection_id) or {}
    config, secrets = plugin_config_service.apply_connection_values(
        connection,
        _managed_only(connection, values),
        current=without_tokens(stored_config),
        current_secrets=without_tokens(stored_secrets),
        allow_managed=True,
    )
    if tokens is not None:
        config, secrets = seal_tokens(tokens, config=config, secrets=secrets)
    entries = _replace_entry(plugin.config, connection_id, config)
    route = plugin_installs.hook_route(plugin.definition, entries)
    if not await plugin_installs.claim(guild_id, plugin, route):
        return "taken"
    try:
        plugin.config = entries
        plugin_config_service.guild_connection_ref(plugin, connection_id)
        plugin.config_state = "unverified"
        plugin.config_state_detail = None
        plugin.updated_at = datetime.now(timezone.utc)
        session.add(plugin)
        await guild_plugins_service.store_secrets(
            session, plugin, _replace_entry(all_secrets, connection_id, secrets)
        )
        await session.commit()
    except Exception:
        # The route was claimed for values that were not stored: the index
        # sweep writes the row again from what the community holds.
        await session.rollback()
        await session.exec(
            text("SELECT arm_timer(:kind, now())").bindparams(
                kind=plugin_installs.INDEX_SWEEP
            )
        )
        await session.commit()
        raise
    return "connected"


def _replace_entry(
    current: Mapping[str, Any] | None, connection_id: str, values: Mapping[str, Any]
) -> dict[str, Any]:
    kept = {k: v for k, v in (current or {}).items() if k != connection_id}
    if values:
        kept[connection_id] = dict(values)
    return kept


# --- a token for a plug-in ------------------------------------------------------


def _expired_before(tokens: TokenSet, *, now: int) -> bool:
    return tokens.expires_at is not None and tokens.expires_at <= now


async def _renewed(
    flow: Mapping[str, Any],
    *,
    public_id: str,
    fields: Mapping[str, Any],
    tokens: TokenSet,
) -> Optional[TokenSet]:
    """A refreshed token set, the same one when it needs no refresh, or
    ``None`` when the grant is over."""
    now = int(time.time())
    if not needs_refresh(tokens, now=now):
        return tokens
    if not tokens.refresh_token:
        return None if _expired_before(tokens, now=now) else tokens
    vendor = await load_vendor_values(public_id)
    try:
        return await refresh_tokens(
            flow, vendor=vendor, fields=fields, refresh_token=tokens.refresh_token
        )
    except VendorRefusedError as exc:
        logger.info("plug-in connection: the vendor refused a refresh (%s)", exc)
        return None
    except OidcHttpError as exc:
        logger.warning(
            "plug-in connection: a refresh could not reach the vendor (%s)", exc
        )
        raise ConnectionFlowError(PluginChannelMessages.TOKEN_UNAVAILABLE, 502) from exc


async def _hold_renewal(
    session: AsyncSession, *, guild_id: int, install_id: int, connection: str
) -> None:
    """Hold one connection's token for the rest of the transaction.

    Two readers of a token about to expire take turns, so the second finds the
    first's refreshed token rather than refreshing again. Nothing else waits on
    it: the install's and the member's rows are locked only for the write that
    stores what the vendor answered. Keyed by guild as well as install, because
    install ids repeat across guild schemas.
    """
    await advisory_lock(
        session, LockNamespace.PLUGIN_TOKEN, f"{guild_id}:{install_id}:{connection}"
    )


async def _member_row(
    session: AsyncSession, *, plugin_id: Optional[int], connection_ref: str, lock: bool
) -> Optional[GuildPluginUserConnection]:
    query = select(GuildPluginUserConnection).where(
        GuildPluginUserConnection.plugin_id == plugin_id,
        GuildPluginUserConnection.connection_ref == connection_ref,
    )
    if lock:
        query = query.with_for_update()
    return (await session.exec(query.execution_options(populate_existing=True))).first()


def _member_tokens(
    plugin: GuildPlugin, row: GuildPluginUserConnection, secrets: dict[str, Any]
) -> tuple[dict[str, Any], TokenSet]:
    """The flow and token set of a member connection that may be handed out."""
    if row.blocked_at is not None:
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_BLOCKED, 403)
    if row.status == "expired":
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_EXPIRED)
    connection = plugin_config_service.connection_by_id(
        plugin.definition, row.connection_id
    )
    flow = flow_of(connection)
    tokens = unseal_tokens(row.config, secrets)
    if flow is None or tokens is None or row.status != "connected":
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_NO_TOKEN)
    return flow, tokens


async def member_token(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    public_id: str,
    connection_ref: str,
    guild_id: int,
) -> Optional[TokenSet]:
    """A member connection's access token, refreshed when it is about to
    expire.

    ``None`` when no member connection of this install has that ref. A
    connection changed while the vendor was asked answers as it stands now,
    and what the vendor said is dropped.
    """
    await _hold_renewal(
        session, guild_id=guild_id, install_id=plugin.id, connection=connection_ref
    )
    row = await _member_row(
        session, plugin_id=plugin.id, connection_ref=connection_ref, lock=False
    )
    if row is None:
        return None
    flow, tokens = _member_tokens(
        plugin, row, await connections_service.load_connection_secrets(session, row)
    )
    renewed = await _renewed(
        flow, public_id=public_id, fields=without_tokens(row.config), tokens=tokens
    )
    if renewed is tokens:
        await session.commit()
        return tokens

    row = await _member_row(
        session, plugin_id=plugin.id, connection_ref=connection_ref, lock=True
    )
    if row is None:
        return None
    stored = await connections_service.load_connection_secrets(session, row)
    _, current = _member_tokens(plugin, row, stored)
    if current != tokens:
        await session.commit()
        return current
    if renewed is None:
        row.status = "expired"
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
        await session.commit()
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_EXPIRED)
    row.config, sealed = seal_tokens(renewed, config=row.config, secrets=stored)
    row.updated_at = datetime.now(timezone.utc)
    await connections_service.store_connection_secrets(session, row, sealed)
    await session.commit()
    return renewed


async def community_token(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    public_id: str,
    connection_id: str,
    guild_id: int,
) -> TokenSet:
    """The community connection's access token: minted for a ``jwt_bearer``
    connection, or its stored token set, refreshed when it is about to expire.

    A connection changed while the vendor was asked answers as it stands now,
    and what the vendor said is dropped.
    """
    connection = plugin_config_service.connection_by_id(
        plugin.definition, connection_id
    )
    if connection is None:
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_NOT_FOUND, 404)
    spec = token_of(connection)
    if spec is not None and spec.get("type") == "jwt_bearer":
        vendor = await load_vendor_values(public_id)
        return await mint_jwt_bearer(
            spec,
            vendor=vendor,
            fields=without_tokens((plugin.config or {}).get(connection_id)),
            cache_key=(guild_id, plugin.id, connection_id),
        )

    flow = flow_of(connection)
    if flow is None:
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_NO_TOKEN)
    await _hold_renewal(
        session, guild_id=guild_id, install_id=plugin.id, connection=connection_id
    )
    await session.refresh(plugin)
    stored_config = (plugin.config or {}).get(connection_id) or {}
    tokens = unseal_tokens(
        stored_config,
        (await guild_plugins_service.load_secrets(session, plugin)).get(connection_id),
    )
    if tokens is None:
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_NO_TOKEN)
    renewed = await _renewed(
        flow, public_id=public_id, fields=without_tokens(stored_config), tokens=tokens
    )
    if renewed is tokens:
        await session.commit()
        return tokens

    locked = await guild_plugins_service.lock_install(session, plugin.id)
    if locked is None:
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_NO_TOKEN)
    plugin = locked
    all_secrets = await guild_plugins_service.load_secrets(session, plugin)
    stored_config = (plugin.config or {}).get(connection_id) or {}
    stored_secrets = all_secrets.get(connection_id) or {}
    current = unseal_tokens(stored_config, stored_secrets)
    if current != tokens:
        await session.commit()
        if current is None:
            raise ConnectionFlowError(PluginChannelMessages.CONNECTION_NO_TOKEN)
        return current
    if renewed is None:
        # The grant is over: the tokens go, and the connection reads as not
        # set until the community connects it again.
        plugin.config = _replace_entry(
            plugin.config, connection_id, without_tokens(stored_config)
        )
        guild_plugins_service.touch(plugin)
        session.add(plugin)
        await guild_plugins_service.store_secrets(
            session,
            plugin,
            _replace_entry(all_secrets, connection_id, without_tokens(stored_secrets)),
        )
        await session.commit()
        raise ConnectionFlowError(PluginChannelMessages.CONNECTION_EXPIRED)
    config, secrets = seal_tokens(renewed, config=stored_config, secrets=stored_secrets)
    plugin.config = _replace_entry(plugin.config, connection_id, config)
    guild_plugins_service.touch(plugin)
    session.add(plugin)
    await guild_plugins_service.store_secrets(
        session, plugin, _replace_entry(all_secrets, connection_id, secrets)
    )
    await session.commit()
    return renewed


def token_response(tokens: TokenSet) -> dict[str, Any]:
    """What the token route answers."""
    return {"access_token": tokens.access_token, "expires_at": tokens.expires_at}


# --- ending a grant ----------------------------------------------------------


async def revoke_request(
    url: str,
    *,
    method: str = "POST",
    headers: Mapping[str, str],
    content: bytes,
) -> None:
    """One request that ends a grant at the vendor. A 2xx answer is success,
    whatever its body."""
    try:
        response = await request_public_target(
            method,
            url,
            headers={"Accept": "application/json", **headers},
            content=content,
            timeout=VENDOR_TIMEOUT_SECONDS,
            transport=http_transport,
            max_bytes=VENDOR_MAX_RESPONSE_BYTES,
        )
    except (
        ResponseTooLargeError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
    ) as exc:
        raise HookError(f"revocation could not be sent: {exc}") from exc
    if not 200 <= response.status_code < 300:
        raise RevocationAnsweredError(response.status_code)


#: What GitHub answers a grant deletion whose access token it no longer
#: accepts with.
GITHUB_INVALID_TOKEN_STATUSES: frozenset[int] = frozenset({404, 422})


async def revocation_sender(
    *,
    method: str,
    public_id: str,
    flow: Mapping[str, Any],
    fields: Mapping[str, Any],
    sealed_tokens: Mapping[str, str],
    guild_id: int,
    install_id: int,
    connection_id: str,
    expires_at: Optional[int] = None,
) -> Optional[Callable[[], Awaitable[None]]]:
    """The request that ends one grant, ready to send, or ``None`` when there
    is nowhere to send it. Raises :class:`ConnectionFlowError` when the vendor
    values it needs are missing.

    ``expires_at`` is when the stored access token lapses, for a method that
    names the grant by a live access token."""
    tokens = {
        key: decrypt_field(value, SALT_PLUGIN_CONFIG)
        for key, value in sealed_tokens.items()
        if isinstance(value, str)
    }
    if not tokens.get("access_token") and not tokens.get("refresh_token"):
        return None

    if method == "rfc7009":
        vendor = await load_vendor_values(public_id)
        url = _render_url(flow.get("revoke_url"), vendor=vendor, fields=fields)
        client_id, secret = _client(flow, vendor=vendor, fields=fields)
        # Revoking the refresh token ends the grant it was issued with (RFC
        # 7009 §2.1); a connection without one revokes its access token.
        if tokens.get("refresh_token"):
            form = {
                "token": tokens["refresh_token"],
                "token_type_hint": "refresh_token",
            }
        else:
            form = {"token": tokens["access_token"], "token_type_hint": "access_token"}
        form["client_id"] = client_id
        if secret:
            form["client_secret"] = secret

        async def send_revocation() -> None:
            # RFC 7009 §2.1: a form post with the client's credentials.
            await revoke_request(
                url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=urlencode(form).encode("ascii"),
            )

        return send_revocation

    if method == "github_grant":
        if not tokens.get("access_token"):
            return None
        access: str = tokens["access_token"]
        refresh_token: Optional[str] = tokens.get("refresh_token")
        lapsed = expires_at is not None and expires_at <= int(time.time())
        if lapsed and not refresh_token:
            logger.info(
                "plug-in credential revocation: plug-in %s connection %s holds a lapsed "
                "access token and no refresh token; dropped",
                public_id,
                connection_id,
            )
            return None
        vendor = await load_vendor_values(public_id)
        url = _render_url(flow.get("revoke_url"), vendor=vendor, fields=fields)
        client_id, secret = _client(flow, vendor=vendor, fields=fields)
        if not secret:
            raise ConnectionFlowError(
                GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED
            )
        # GitHub's "Delete a plug-in authorization": the client's credentials as
        # HTTP Basic auth, and the grant's access token in a JSON body.
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode("ascii")

        async def renew() -> None:
            # GitHub names the grant by a live access token. The connection is
            # going, so the renewed set serves this request and is not kept.
            # Once only, and kept across tries: a refresh token is spent by
            # its first use.
            nonlocal access, refresh_token
            if refresh_token is None:
                return
            renewed = await refresh_tokens(
                flow, vendor=vendor, fields=fields, refresh_token=refresh_token
            )
            access, refresh_token = renewed.access_token, None

        async def delete_grant() -> None:
            await revoke_request(
                url,
                method="DELETE",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/json",
                },
                content=json.dumps({"access_token": access}).encode(),
            )

        async def send_grant_deletion() -> None:
            if lapsed:
                await renew()
            try:
                await delete_grant()
            except RevocationAnsweredError as exc:
                if exc.status not in GITHUB_INVALID_TOKEN_STATUSES or not refresh_token:
                    raise
                await renew()
                await delete_grant()

        return send_grant_deletion

    # ``hook`` rides the community-hook queue (``plugin_revocation``), and
    # every other method sends nothing.
    return None
