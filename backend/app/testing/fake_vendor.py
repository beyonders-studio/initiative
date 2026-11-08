"""A vendor and a plug-in, answering the calls a connection's flow makes.

Every outbound call the flow module makes goes through one transport
(``plugin_connection_flows.http_transport``) after the pinned egress helper has
resolved its host. :meth:`FakeVendor.install` points both at this object: the
host resolves to a fixed public address, and the request is answered here by
the host it names.

The vendor side is an OAuth 2.0 authorization server with PKCE, refresh,
revocation and a GitHub-style installation token exchange, and signs the
webhooks it sends. Its API at ``api_host`` answers a declarative plug-in's calls
from recorded answers, in order. The plug-in side answers the hooks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

import httpx

from app.services import safe_http
from app.services.webhook_target_url import ValidatedTarget

__all__ = ["FakeVendor", "declarative_github", "declarative_plugin"]

VENDOR_HOST = "github.test"
API_HOST = "api.github.test"


def declarative_plugin(public_id: str) -> dict[str, Any]:
    """A declarative plug-in calling this vendor's API on a community connection:
    a read of a repository's issues and a write that labels one."""
    api = f'"https://{API_HOST}/repos/" & params.repo'
    return {
        "plugin_kind": "service",
        "features": ["endpoints"],
        "hosts": [API_HOST],
        "vendor": {
            "fields": [
                {
                    "key": "client_id",
                    "type": "string",
                    "required": True,
                    "label": {"en": "Client id"},
                }
            ]
        },
        "connections": [
            {
                "id": "workspace",
                "scope": "static",
                "label": {"en": "Workspace"},
                "fields": [],
                "flow": {
                    "type": "oauth2",
                    "authorize_url": f"https://{VENDOR_HOST}/login/oauth/authorize",
                    "token_url": f"https://{VENDOR_HOST}/login/oauth/access_token",
                    "client_id": "{vendor.client_id}",
                },
            }
        ],
        "endpoints": [
            {
                "id": f"plugin.{public_id}.issues",
                "direction": "read",
                "public": True,
                "actors": ["installation"],
                "cache_ttl_seconds": 60,
                "params": [
                    {"key": "repo", "type": "string", "label": {"en": "Repository"}}
                ],
                "returns": [
                    {"key": "titles", "type": "string", "list": True},
                    {"key": "total", "type": "int"},
                    {"key": "unavailable", "type": "string"},
                ],
                "request": {
                    "method": "GET",
                    "url": f'{api} & "/issues"',
                    "connection": "workspace",
                },
                "map": '{"titles": response.body.title[], "total": $count(response.body)}',
            },
            {
                "id": f"plugin.{public_id}.label",
                "direction": "write",
                "public": True,
                "actors": ["installation"],
                "params": [
                    {"key": "repo", "type": "string", "label": {"en": "Repository"}},
                    {"key": "number", "type": "int", "label": {"en": "Issue"}},
                ],
                "returns": [{"key": "number", "type": "int"}],
                "unavailable": ["locked"],
                "request": {
                    "method": "PUT",
                    "url": f'{api} & "/issues/" & params.number & "/labels"',
                    "body": '{"labels": ["bug"]}',
                    "connection": "workspace",
                },
                "map": '{"number": response.body.number}',
                "errors": [
                    {
                        "status": 422,
                        "when": 'response.body.message = "locked"',
                        "code": "locked",
                    }
                ],
            },
        ],
    }


def declarative_github(public_id: str) -> dict[str, Any]:
    """:func:`declarative_plugin` as GitHub's is: its community connection is an
    installation, found among the person's own by ``after_connect`` and
    checked by ``health``, and the vendor's deliveries become its
    ``issue-opened`` event and the installation's state."""
    plugin = declarative_plugin(public_id)
    issue_opened = f"plugin.{public_id}.issue-opened"
    plugin["vendor"] = {
        "fields": [
            {"key": key, "type": "string", "required": True, "label": {"en": key}}
            for key in (
                "client_id",
                "client_secret",
                "app_slug",
                "app_id",
                "private_key",
                "webhook_secret",
            )
        ]
    }
    plugin["connections"] = [
        {
            "id": "workspace",
            "scope": "static",
            "label": {"en": "Organization"},
            "fields": [
                {"key": key, "type": "string", "label": {"en": key}, "managed": True}
                for key in ("owner", "installation_id")
            ],
            "flow": {
                "type": "oauth2",
                "authorize_url": f"https://{VENDOR_HOST}/login/oauth/authorize",
                "token_url": f"https://{VENDOR_HOST}/login/oauth/access_token",
                "client_id": "{vendor.client_id}",
                "client_secret": "{vendor.client_secret}",
                "install_url": (
                    f"https://{VENDOR_HOST}/apps/{{vendor.app_slug}}/installations/new"
                ),
                "after_connect": {
                    "request": {
                        "method": "GET",
                        "url": f'"https://{API_HOST}/user/installations"',
                        "paging": {
                            "kind": "page_number",
                            "page_param": "page",
                            "per_page_param": "per_page",
                            "per_page": 2,
                            "items": "response.body.installations",
                            "max_pages": 5,
                            "on_limit": "refuse",
                        },
                    },
                    "map": (
                        "($i := response.body[$string(id) = $$.params.installation_id][0];"
                        ' {"values": {"owner": $i.account.login,'
                        ' "installation_id": $string($i.id)},'
                        ' "account_label": $i.account.login})'
                    ),
                    "refuse_when": "$not($exists(result.values.installation_id))",
                    "code": "not-your-installation",
                },
            },
            "token": {
                "type": "jwt_bearer",
                "exchange_url": (
                    f"https://{VENDOR_HOST}/app/installations/"
                    "{installation_id}/access_tokens"
                ),
                "iss": "{vendor.app_id}",
                "key": "{vendor.private_key}",
            },
            "health": {
                "request": {
                    "method": "GET",
                    "url": f'"https://{API_HOST}/installation/repositories"',
                },
                "every": "15m",
                "states": [
                    {"status": 404, "state": "removed"},
                    {"status": 403, "state": "suspended"},
                ],
            },
        }
    ]
    plugin["endpoints"].append(
        {
            "id": issue_opened,
            "direction": "emit",
            "label": {"en": "Issue opened"},
            "returns": [
                {"key": "repository", "type": "string"},
                {"key": "number", "type": "int"},
                {"key": "title", "type": "string"},
            ],
        }
    )
    installation = 'headers."x-github-event" = "installation" and payload.action = '
    plugin["webhooks"] = {
        "verify": {
            "scheme": "hmac_sha256",
            "header": "X-Hub-Signature-256",
            "prefix": "sha256=",
            "encoding": "hex",
            "secret": "{vendor.webhook_secret}",
        },
        "dedup": "X-GitHub-Delivery",
        "route": {
            "path": "installation.id",
            "connection": "workspace",
            "field": "installation_id",
        },
        "events": [
            {
                "when": (
                    'headers."x-github-event" = "issues" and payload.action = "opened"'
                    " and $not($exists(payload.issue.pull_request))"
                ),
                "emit": issue_opened,
                "map": (
                    '{"repository": payload.repository.full_name,'
                    ' "number": payload.issue.number, "title": payload.issue.title}'
                ),
            }
        ],
        "status": [
            {
                "when": f'{installation}"deleted"',
                "connection": "workspace",
                "state": "removed",
            },
            {
                "when": f'{installation}"suspend"',
                "connection": "workspace",
                "state": "suspended",
            },
            {
                "when": f'{installation}"unsuspend"',
                "connection": "workspace",
                "state": "ok",
            },
        ],
    }
    return plugin


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class FakeVendor:
    client_id: str = "client-123"
    client_secret: str = "client-secret-456"
    #: What each new access token lives, in seconds.
    expires_in: int = 28800
    #: The vendor refuses every refresh.
    refuse_refresh: bool = False
    #: What the plug-in's after_connect hook answers.
    after_connect_answer: Any = field(
        default_factory=lambda: {
            "values": {"login": "alice"},
            "account_label": "@alice",
        }
    )
    #: The status the plug-in's hooks answer with.
    hook_status: int = 200
    #: The status the vendor's revocation endpoint answers with.
    revoke_status: int = 200
    #: The status GitHub's grant deletion answers with.
    grant_status: int = 204
    #: The status the installation token exchange answers with.
    exchange_status: int = 201
    #: What the vendor signs its webhooks with.
    webhook_secret: str = "webhook-secret-789"
    #: Where its API answers, and what it answers, in order: each a recorded
    #: answer's ``status`` (200 when left out), ``headers`` and JSON ``body``.
    api_host: str = API_HOST
    api_answers: list[dict[str, Any]] = field(default_factory=list)
    #: Each API request: its method, address, headers and JSON body.
    api_requests: list[dict[str, Any]] = field(default_factory=list)

    codes: dict[str, str] = field(default_factory=dict)
    token_requests: list[dict[str, str]] = field(default_factory=list)
    refreshes: int = 0
    revocations: list[dict[str, str]] = field(default_factory=list)
    #: Access tokens the grant deletion no longer accepts (answered 404).
    lapsed_tokens: set[str] = field(default_factory=set)
    #: Each grant deletion: its method, path, Authorization header and body.
    grant_deletions: list[tuple[str, str, str, Any]] = field(default_factory=list)
    hooks: list[tuple[str, dict[str, Any], str]] = field(default_factory=list)
    #: Each token exchange: its Authorization header and JSON body (``None``
    #: when it sent none).
    exchanges: list[tuple[str, Any]] = field(default_factory=list)
    _serial: Any = field(default_factory=lambda: itertools.count(1))

    # --- the test's side ------------------------------------------------

    def install(self, monkeypatch: Any) -> None:
        """Answer every outbound call of the flow module from here."""
        from app.services.tenant import plugin_connection_flows

        async def resolve(url: str, *, allow_private: bool = False) -> ValidatedTarget:
            host = httpx.URL(url).host
            return ValidatedTarget(
                hostname=host, addresses=(ipaddress.ip_address("93.184.216.34"),)
            )

        monkeypatch.setattr(safe_http, "resolve_validated_target_async", resolve)
        monkeypatch.setattr(
            plugin_connection_flows, "http_transport", httpx.MockTransport(self.handle)
        )

    def authorize(self, challenge: str | None) -> str:
        """What the vendor's authorization page does when the person agrees:
        mint a code bound to the challenge it was sent."""
        code = f"code-{next(self._serial)}"
        self.codes[code] = challenge or ""
        return code

    def webhook(
        self, payload: dict[str, Any], *, delivery: str = "delivery-1"
    ) -> tuple[bytes, dict[str, str]]:
        """One webhook delivery as the vendor sends it: the body, and its
        headers with the signature over it."""
        body = json.dumps(payload).encode("utf-8")
        digest = hmac.new(
            self.webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return body, {
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": f"sha256={digest}",
        }

    # --- the vendor's and the plug-in's side --------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host", "")
        path = request.url.path
        if host == self.api_host:
            return self._api(request, host)
        if host == VENDOR_HOST:
            if path == "/login/oauth/access_token":
                return self._token(request)
            if path == "/revoke":
                self.revocations.append(dict(parse_qsl(request.content.decode())))
                return httpx.Response(self.revoke_status)
            if path.startswith("/applications/") and path.endswith("/grant"):
                body = json.loads(request.content or b"null")
                self.grant_deletions.append(
                    (
                        request.method,
                        path,
                        request.headers.get("authorization", ""),
                        body,
                    )
                )
                if (body or {}).get("access_token") in self.lapsed_tokens:
                    return httpx.Response(404)
                return httpx.Response(self.grant_status)
            if path.startswith("/app/installations/"):
                return self._exchange(request)
            return httpx.Response(404)
        if path.startswith("/v1/hooks/"):
            name = path[len("/v1/hooks/") :]
            self.hooks.append(
                (
                    name,
                    json.loads(request.content or b"{}"),
                    request.headers.get("authorization", ""),
                )
            )
            if self.hook_status >= 300:
                return httpx.Response(self.hook_status)
            if name == "revoke":
                return httpx.Response(204)
            return httpx.Response(200, json=self.after_connect_answer)
        return httpx.Response(404)

    def _api(self, request: httpx.Request, host: str) -> httpx.Response:
        self.api_requests.append(
            {
                "method": request.method,
                "url": f"https://{host}{request.url.raw_path.decode('ascii')}",
                "headers": dict(request.headers),
                "body": json.loads(request.content) if request.content else None,
            }
        )
        answer = self.api_answers.pop(0)
        if "body" not in answer:
            return httpx.Response(
                answer.get("status", 200), headers=answer.get("headers")
            )
        return httpx.Response(
            answer.get("status", 200),
            headers=answer.get("headers"),
            json=answer["body"],
        )

    def _issue(self) -> dict[str, Any]:
        serial = next(self._serial)
        return {
            "access_token": f"gho_access_{serial}",
            "refresh_token": f"ghr_refresh_{serial}",
            "expires_in": self.expires_in,
            "token_type": "bearer",
        }

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        self.token_requests.append(form)
        if (
            form.get("client_id") != self.client_id
            or form.get("client_secret") != self.client_secret
        ):
            return httpx.Response(401, json={"error": "invalid_client"})
        if form.get("grant_type") == "refresh_token":
            self.refreshes += 1
            if self.refuse_refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._issue())
        code = form.get("code", "")
        if code not in self.codes:
            # A success status carrying an error, as some vendors answer.
            return httpx.Response(200, json={"error": "bad_verification_code"})
        challenge = self.codes.pop(code)
        verifier = form.get("code_verifier", "")
        if challenge and _challenge(verifier) != challenge:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json=self._issue())

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        self.exchanges.append(
            (
                request.headers.get("authorization", ""),
                json.loads(request.content) if request.content else None,
            )
        )
        if self.exchange_status >= 300:
            return httpx.Response(self.exchange_status)
        expires = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            self.exchange_status,
            json={
                "token": f"ghs_installation_{next(self._serial)}",
                "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
