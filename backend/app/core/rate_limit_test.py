"""Tests for the shared rate limiter configuration.

These assert *configuration* rather than throttling behaviour: the suite sets
``limiter.enabled = False`` (see ``conftest.py``), so a burst test would be
meaningless here and would flake against the hundreds of rapid requests other
tests make from the same client IP. We instead verify that the global default
limit and storage backend are settings-driven, and that ``SlowAPIMiddleware`` is
actually registered on the app so ``default_limits`` is no longer inert.
"""

import uuid

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware, _find_route_handler
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

from app.core import audit_context, identify, rate_limit
from app.core.config import settings
from app.core.plugin_access_token import seal_install_token
from app.core.rate_limit import (
    _default_limits,
    build_limiter,
    get_user_or_ip_key,
    limiter,
)
from app.core.routing import MOUNTED, route_endpoint
from app.core.security import (
    SESSION_COOKIE_NAME,
    create_upload_token,
    mint_access_token,
)
from app.main import app
from app.testing import create_user, get_auth_headers, in_request_tasks


class TestDefaultLimitsBuilder:
    """The default-limit list is derived from RATE_LIMIT_DEFAULT."""

    def test_configured_value_produces_one_entry(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "100/minute")
        assert _default_limits() == ["100/minute"]

    def test_empty_string_disables_default(self, monkeypatch):
        """An empty value means "no global default" — and must NOT be passed to
        slowapi as ``[""]`` (which raises ValueError during parsing)."""
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "")
        assert _default_limits() == []

    def test_whitespace_only_disables_default(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "   ")
        assert _default_limits() == []

    def test_empty_default_builds_a_usable_limiter(self, monkeypatch):
        """A limiter built from an empty default must construct without error."""
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "")
        built = build_limiter(settings.RATE_LIMIT_STORAGE_URI)
        assert built._default_limits == []


class TestLimiterConfiguration:
    """The shared limiter instance reflects the configured settings."""

    def test_default_limit_registered(self):
        # The module is imported with the packaged default ("100/minute"), so a
        # single default LimitGroup should be present.
        assert len(limiter._default_limits) == 1

    def test_storage_uri_is_settings_driven(self):
        # Defaults to in-memory; a multi-worker deploy can point this at Redis
        # via RATE_LIMIT_STORAGE_URI with no code change.
        assert limiter._storage_uri == settings.RATE_LIMIT_STORAGE_URI

    def test_default_storage_is_in_memory(self):
        assert settings.RATE_LIMIT_STORAGE_URI == "memory://"


class TestMiddlewareRegistration:
    """SlowAPIMiddleware must be in the app's middleware stack, otherwise the
    limiter's default_limits never apply to undecorated routes."""

    def test_slowapi_middleware_registered(self):
        registered = {m.cls for m in app.user_middleware}
        assert any(issubclass(cls, SlowAPIMiddleware) for cls in registered), registered

    def test_app_uses_shared_limiter(self):
        assert app.state.limiter is rate_limit.limiter


class TestRouteResolution:
    """The middleware has to read the route the router will actually run.

    Upstream picks one by scanning every route and keeping the LAST that
    matches; this app ends with a catch-all serving the SPA, which matches
    everything. ``route_endpoint`` resolves the way the router does instead.
    """

    @staticmethod
    def _scope(path: str, method: str = "GET", host=app) -> dict:
        return {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "root_path": "",
            "app": host,
        }

    def _endpoint(self, path: str, method: str = "GET", host=app):
        return route_endpoint(self._scope(path, method, host))

    def test_resolves_the_route_the_router_runs(self):
        assert self._endpoint("/api/v1/version").__name__ == "get_version"
        assert self._endpoint("/api/v1/readyz").__name__ == "readyz"

    def test_a_request_is_resolved_once_for_every_layer_that_asks(self):
        """The body bound and the default limit share one resolution."""
        scope = self._scope("/api/v1/version")
        first = route_endpoint(scope)
        scope["app"] = Starlette()
        assert route_endpoint(scope) is first

    def test_upstream_would_have_answered_the_catch_all(self):
        """Pins why this app cannot use the stock middleware. Should a later
        slowapi resolve first-match, this fails and the override can go."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/version",
            "headers": [],
            "root_path": "",
        }
        assert _find_route_handler(app.routes, scope).__name__ == "serve_spa"

    def test_an_unmatched_request_resolves_to_nothing(self):
        assert self._endpoint("/api/v1/version", method="DELETE") is None

    def test_a_mounted_sub_app_is_told_apart_from_no_match(self):
        """A mount carries no endpoint. That must not read back as "no route",
        which slowapi treats as exempt — a whole mounted surface would lose the
        default limit. Built here rather than read off the app so the case is
        covered whether or not this configuration mounts anything."""
        host = Starlette(routes=[Mount("/sub", app=Starlette())])
        assert self._endpoint("/sub/anything", host=host) is MOUNTED


class TestDefaultLimitThrottlesUndecoratedRoute:
    """The global default applied via the middleware actually throttles a route
    that has no ``@limiter.limit`` decorator.

    Built on a throwaway app + a fresh Limiter (its own in-memory storage), so
    it shares no state with the suite-wide limiter and can't flake against other
    tests' requests. Enabled here on purpose; the suite-wide limiter stays off.
    """

    def _build_app(self, default: str, burst_limiter: Limiter | None = None) -> FastAPI:
        burst_limiter = burst_limiter or Limiter(
            key_func=lambda request: "fixed-test-key",
            default_limits=[default] if default else [],
            storage_uri="memory://",
        )
        burst_app = FastAPI()
        burst_app.state.limiter = burst_limiter
        burst_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        burst_app.add_middleware(SlowAPIMiddleware)

        @burst_app.get("/undecorated")
        async def undecorated() -> dict[str, bool]:
            return {"ok": True}

        return burst_app

    async def test_burst_past_default_is_rejected(self):
        burst_app = self._build_app("3/minute")
        transport = ASGITransport(app=in_request_tasks(burst_app))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            statuses = [(await c.get("/undecorated")).status_code for _ in range(5)]
        # First 3 within the window succeed, the rest are throttled.
        assert statuses[:3] == [200, 200, 200]
        assert 429 in statuses[3:]

    # slowapi announces the fallback with the deprecated ``Logger.warn``.
    @pytest.mark.filterwarnings(
        "ignore:The 'warn' method is deprecated:DeprecationWarning"
    )
    async def test_unreachable_storage_still_throttles(self, monkeypatch):
        """With the shared storage down, the limits are counted in memory
        rather than every request failing."""
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "3/minute")
        unreachable = build_limiter("redis://127.0.0.1:1/0")
        burst_app = self._build_app("", unreachable)
        transport = ASGITransport(app=in_request_tasks(burst_app))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            statuses = [(await c.get("/undecorated")).status_code for _ in range(5)]
        assert unreachable._storage_dead
        assert statuses == [200, 200, 200, 429, 429]

    async def test_empty_default_does_not_throttle(self):
        """With RATE_LIMIT_DEFAULT unset, undecorated routes are unthrottled."""
        burst_app = self._build_app("")
        transport = ASGITransport(app=in_request_tasks(burst_app))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            statuses = [(await c.get("/undecorated")).status_code for _ in range(10)]
        assert all(code == 200 for code in statuses)


def _session_token(subject: str) -> str:
    token, _ = mint_access_token(
        subject=subject,
        token_version=0,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
    )
    return token


def _install_token() -> str:
    token, _ = seal_install_token(
        guild_id=7,
        install_id=3,
        client_id="acme.widgets",
        scopes=frozenset(),
        initiative_id=None,
    )
    return token


class TestUserOrIpKey:
    """``get_user_or_ip_key`` counts per account where there is one.

    Several accounts commonly share one address, so the account is the
    counter rather than the address it arrived from — the one the request was
    admitted as, or before that, the one its credential names.
    """

    @pytest.fixture(autouse=True)
    def _from_one_address(self):
        """The address the request's context holds, as the outermost
        middleware reads it."""
        _, token = audit_context.begin(request_id="x", source_ip="198.51.100.7")
        yield
        audit_context.end(token)

    @staticmethod
    def _request(
        *,
        user_id: int | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
        query: bytes = b"",
    ) -> Request:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": headers or [],
                "query_string": query,
            }
        )
        if user_id is not None:
            request.state.user_id = user_id
        return request

    def _bearer(self, token: str) -> Request:
        return self._request(headers=[(b"authorization", f"Bearer {token}".encode())])

    def test_every_limit_is_keyed_by_it(self):
        assert limiter._key_func is get_user_or_ip_key
        upload = "app.api.v1.platform_endpoints.auth.issue_upload_token"
        assert all(
            limit.key_func is get_user_or_ip_key
            for limit in limiter._route_limits[upload]
        )

    def test_a_session_is_counted_by_its_subject_before_it_is_admitted(self):
        assert get_user_or_ip_key(self._bearer(_session_token("ref-1"))) == (
            "subject:ref-1"
        )

    def test_a_token_that_fails_its_check_is_counted_by_address(self):
        forged = jwt.encode({"sub": "ref-1"}, "x" * 32, algorithm="HS256")
        assert get_user_or_ip_key(self._bearer(forged)) == "198.51.100.7"
        assert get_user_or_ip_key(self._bearer("junk")) == "198.51.100.7"

    def test_an_upload_token_in_the_url_is_counted_by_its_account(self):
        token, _ = create_upload_token(user_id=9)
        request = self._request(query=f"token={token}".encode())
        assert get_user_or_ip_key(request) == "user:9"

    def test_an_installed_plugins_bearer_token_is_counted_by_its_install(self):
        assert get_user_or_ip_key(self._bearer(_install_token())) == (
            "install:acme.widgets:7:3"
        )

    def test_an_installed_plugins_token_is_read_only_as_a_bearer(self):
        cookie = f"{SESSION_COOKIE_NAME}={_install_token()}".encode()
        request = self._request(headers=[(b"cookie", cookie)])
        assert get_user_or_ip_key(request) == "198.51.100.7"

    def test_a_signed_in_account_is_its_own_counter(self):
        assert get_user_or_ip_key(self._request(user_id=42)) == "user:42"

    def test_the_address_is_the_counter_when_nobody_is_named(self):
        assert get_user_or_ip_key(self._request()) == "198.51.100.7"
        _, token = audit_context.begin(request_id="y", source_ip="testclient")
        try:
            assert get_user_or_ip_key(self._request()) == "127.0.0.1"
        finally:
            audit_context.end(token)

    def test_an_installed_plugin_is_counted_by_client_and_install(self):
        request = self._request()
        request.state.plugin_install = ("acme.widgets", 7, 3)
        assert get_user_or_ip_key(request) == "install:acme.widgets:7:3"


class TestDefaultLimitOnTheRealApp:
    """What the default does on the app as assembled, catch-all and all.

    ``TestDefaultLimitThrottlesUndecoratedRoute`` above builds a throwaway app
    with two routes, where slowapi's last-match resolution happens to land on
    the right one. These go through the real router, which is where it does
    not.
    """

    @pytest.fixture(autouse=True)
    def _throttled(self, rate_limit_of_one_per_minute):
        pass

    async def test_an_undecorated_route_takes_the_default(self, client):
        assert (await client.get("/api/v1/version")).status_code == 200
        assert (await client.get("/api/v1/version")).status_code == 429

    async def test_a_decorated_route_takes_its_own_limit_instead(self, client, session):
        """A route carrying ``@limiter.limit`` is left to its decorator rather
        than also counted against the default, so one set ABOVE the default is
        not quietly held down to it. ``/auth/upload-token`` asks for 60 a
        minute, so under a 1-a-minute default it still answers a second time."""
        headers = get_auth_headers(await create_user(session))
        for _ in range(2):
            response = await client.post("/api/v1/auth/upload-token", headers=headers)
            assert response.status_code == 200, response.text

    async def test_accounts_behind_one_address_each_get_their_own_allowance(
        self, client, session
    ):
        first = get_auth_headers(await create_user(session))
        second = get_auth_headers(await create_user(session))
        assert (await client.get("/api/v1/version", headers=first)).status_code == 200
        assert (await client.get("/api/v1/version", headers=first)).status_code == 429
        assert (await client.get("/api/v1/version", headers=second)).status_code == 200

    async def test_a_junk_credential_shares_the_address_with_none(self, client):
        junk = {"Authorization": "Bearer junk"}
        assert (await client.get("/api/v1/version", headers=junk)).status_code == 200
        assert (await client.get("/api/v1/version")).status_code == 429

    async def test_the_credential_is_read_once_for_the_limit_and_the_route(
        self, client, session, monkeypatch
    ):
        """The default limit reads the credential before the dependencies run,
        and they read what it read rather than decoding it again."""
        headers = get_auth_headers(await create_user(session))
        decoded: list[str] = []
        decode = identify.decode_session_token

        def _counting(token: str):
            decoded.append(token)
            return decode(token)

        monkeypatch.setattr(identify, "decode_session_token", _counting)
        response = await client.get("/api/v1/me", headers=headers)
        assert response.status_code == 200, response.text
        assert len(decoded) == 1

    async def test_an_exempt_route_takes_no_limit_at_all(self, client):
        assert (await client.get("/api/v1/healthz")).status_code == 200
        assert (await client.get("/api/v1/healthz")).status_code == 200

    async def test_the_apps_own_files_take_no_limit(
        self, client, tmp_path, monkeypatch
    ):
        """A built file is served without counting; a path that falls back to
        the index is counted like any other request."""
        from app import main

        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "index.js").write_text("")
        monkeypatch.setattr(main, "static_path", tmp_path)
        monkeypatch.setattr(main, "static_root", tmp_path.resolve())
        for _ in range(2):
            assert (await client.get("/assets/index.js")).status_code == 200
        assert (await client.get("/no-such-page")).status_code != 429
        assert (await client.get("/no-such-page")).status_code == 429
