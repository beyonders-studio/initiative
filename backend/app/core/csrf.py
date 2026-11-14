"""Where a state-changing request came from, for cookie-authenticated callers.

The session cookie authenticates ordinary API requests, not only the refresh
route: ``get_current_user`` falls back to it when no ``Authorization: Bearer``
header is present. So for those callers this asks for one more thing before an
unsafe method is allowed through -- that the request came from a page this
deployment serves.

Scope, and why it is drawn here:

* **Only cookie-authenticated callers.** A bearer header is never attached by
  a browser on someone else's behalf, so bearer tokens and API keys are not
  asked for anything. That is also what keeps mobile shells and API scripts
  working unchanged.
* **Unsafe methods, and every WebSocket handshake.** ``OPTIONS`` is excluded
  along with the read methods: it is the CORS preflight and is answered before
  this runs. A handshake has no method to branch on and opens a two-way
  channel, so it is treated as state-changing.
* **No token to mint, store or rotate.** A synchroniser or double-submit token
  is a stronger primitive and can be added on top of this later. It also needs
  every client that writes to carry it, which is a change across the whole
  frontend; this is backend-only.
* **``Sec-Fetch-Site: same-site`` is not accepted on its own**, because it
  includes sibling subdomains. Only ``same-origin`` is conclusive by itself;
  anything else is matched against the same origin allowlist CORS uses.
* **A browser that sends no ``Sec-Fetch-*`` at all still has an answer.** Those
  headers are only sent to origins the browser considers trustworthy -- HTTPS,
  ``localhost`` or ``127.0.0.1`` -- so a deployment reached over plain HTTP at
  a LAN name or address never gets the conclusive answer above, however
  same-origin the request is. Comparing the ``Origin`` against the ``Host`` the
  request was addressed to asks the same question from headers a browser always
  sends, which is what keeps such a deployment writable without its operator
  having to match ``APP_URL`` to it by hand.

Detail beyond what the code does lives in the private tracker, per
CLAUDE.md "Security-sensitive comments".
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.identify import presented_credential
from app.core.messages import AuthMessages

#: Methods that cannot change state, per RFC 9110.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Kept as a name so callers can refer to the code without repeating it.
CSRF_ERROR_CODE = AuthMessages.REQUEST_ORIGIN_NOT_RECOGNIZED


def _carries_session_cookie(scope: Scope) -> bool:
    """Whether this request is authenticated by the cookie rather than a header.

    Read by the same rule ``identify`` authenticates by, so the request this
    asks about is the one authentication sees.
    """
    presented = presented_credential(HTTPConnection(scope))
    return presented is not None and not presented.bearer


def _request_scheme(scope: Scope) -> str:
    """The scheme the request arrived on, as an ``Origin`` would spell it.

    A WebSocket scope says ``ws``/``wss`` where the handshake's ``Origin``
    says ``http``/``https``. Behind a reverse proxy this is the forwarded
    scheme when the server was started with ``--proxy-headers``
    (``BEHIND_PROXY=true``), and the proxy's own scheme otherwise.
    """
    return "https" if scope.get("scheme") in {"https", "wss"} else "http"


def _origin_is_the_requested_host(headers: Headers, origin: str, scheme: str) -> bool:
    """Whether ``origin`` names the very host this request was addressed to.

    Host and port must match exactly. The scheme has to agree too, with one
    allowance: an ``https`` page reaching a server that sees ``http`` is a TLS
    reverse proxy that did not forward the scheme, whereas the other direction
    -- an ``http`` page writing to a request this server received over TLS --
    is a different origin and is refused.
    """
    host = headers.get("host")
    if not host:
        return False
    parts = urlsplit(origin)
    if parts.netloc.lower() != host.lower():
        return False
    return parts.scheme == "https" or parts.scheme == scheme


def intent_is_proven(headers: Headers, scheme: str = "http") -> bool:
    """Whether the request came from a page this deployment serves.

    ``Sec-Fetch-Site: same-origin`` is conclusive on its own and is checked
    first, because a same-origin fetch is the common case and needs no
    allowlist lookup. Otherwise the ``Origin`` must be one this deployment
    serves, which is how a split-origin deployment -- SPA hosted somewhere
    other than the API -- still works. That list is the one CORS already
    credentials, so the two cannot drift apart.

    Failing both, and only when the browser sent no ``Sec-Fetch-Site`` to
    believe instead, the ``Origin`` is compared with the ``Host`` the request
    was addressed to -- see the module docstring for why a same-origin request
    can arrive with no fetch metadata on it.

    No ``Origin`` header means the answer is no. Browsers send it on an unsafe
    method as a matter of course.
    """
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site == "same-origin":
        return True
    origin = headers.get("origin")
    if origin is None:
        return False
    if origin in settings.cors_origins:
        return True
    if fetch_site is not None:
        return False
    return _origin_is_the_requested_host(headers, origin, scheme)


def _count_refusal(scope: Scope) -> None:
    """A refusal is counted by the security rules, never written down one by
    one (``app.core.security_rules.Signal``)."""
    from app.core.security_rules import Signal
    from app.services.platform import security_signals

    client = scope.get("client")
    security_signals.signal(
        Signal.csrf_rejected, source_ip=client[0] if client else None
    )


class CsrfOriginMiddleware:
    """Refuse a cookie-authenticated write that cannot say where it came from.

    Pure ASGI rather than ``BaseHTTPMiddleware``: the decision is made from
    headers alone, so there is no reason to buffer a body that is not going to
    be used.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
            return

        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not _carries_session_cookie(scope) or intent_is_proven(
            headers, _request_scheme(scope)
        ):
            await self.app(scope, receive, send)
            return

        # A machine-readable code, mapped to text in
        # frontend/public/locales/*/errors.json, per CLAUDE.md "Backend: Error
        # code constants".
        _count_refusal(scope)
        response = JSONResponse(status_code=403, content={"detail": CSRF_ERROR_CODE})
        await response(scope, receive, send)

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Apply the same rule to a handshake.

        A WebSocket carries the session cookie like any other request and is not
        bound by the same-origin policy, and the routes here fall back to that
        cookie when the first message supplies no token. There is no method to
        branch on -- a handshake is always the start of a two-way channel, so it
        is treated as state-changing.

        Refused before the route sees it, by closing in response to the connect
        rather than accepting first: a channel that is accepted and then closed
        has already run whatever the route does on accept.
        """
        headers = Headers(scope=scope)
        if not _carries_session_cookie(scope) or intent_is_proven(
            headers, _request_scheme(scope)
        ):
            await self.app(scope, receive, send)
            return

        # Drain the connect so the close is a valid reply to it.
        message = await receive()
        if message["type"] != "websocket.connect":  # pragma: no cover - spec order
            return
        _count_refusal(scope)
        # 1008 policy violation, which is what the routes here already use for a
        # handshake they refuse.
        await send({"type": "websocket.close", "code": 1008})
