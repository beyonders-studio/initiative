"""Tests for application settings parsing."""

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from sqlalchemy.engine import make_url

from app.core.config import (
    CAPACITOR_NATIVE_ORIGINS,
    DATABASE_LOGINS,
    DEFAULT_OIDC_SCOPES,
    Settings,
    derive_database_password,
)

# Test-only key satisfying the SECRET_KEY validator (64 hex chars). Not a secret.
TEST_SECRET_KEY = "f2d8a1c4b7e90365d4a2f8c1b6e3079a5c8d2e4f6a1b3c5d7e9f0a2b4c6d8e1f"


class _HermeticSettings(Settings):
    """``Settings`` without the dotenv source: keeps these unit tests hermetic —
    otherwise a developer's real backend/.env (e.g. a legitimately-set
    JWT_SIGNING_KEY) leaks into every field the test didn't override."""

    model_config = SettingsConfigDict(env_file=None)


def _settings(**overrides) -> Settings:
    overrides.setdefault("APP_URL", "https://app.example.com")
    overrides.setdefault("SECRET_KEY", TEST_SECRET_KEY)
    return _HermeticSettings(
        DATABASE_URL_APP="postgresql+asyncpg://app:app@localhost/app",
        DATABASE_URL_ADMIN="postgresql+asyncpg://admin:admin@localhost/app",
        **overrides,
    )


@pytest.mark.parametrize("field", ["GUILD_ROLE_PREFIX", "PLATFORM_ROLE_PREFIX"])
@pytest.mark.parametrize(
    "bad_prefix",
    [
        "a; DROP ROLE app_admin",
        "x'",
        "p-1",
        "test prefix",
        "p.g",
        'q"',
        "réle_",
        # Digit-leading: valid characters but Postgres rejects it as an
        # unquoted identifier, so the prefix must be refused at load.
        "9prod_",
        "0",
    ],
)
def test_role_prefix_rejects_non_identifier_chars(field, bad_prefix):
    """The role-name prefixes are interpolated into Postgres ROLE DDL and into
    every request's SET ROLE, so a prefix that isn't a valid unquoted
    identifier must fail closed at load rather than reach that sink."""
    with pytest.raises(ValidationError):
        _settings(**{field: bad_prefix})


@pytest.mark.parametrize("field", ["GUILD_ROLE_PREFIX", "PLATFORM_ROLE_PREFIX"])
@pytest.mark.parametrize("ok_prefix", ["", "test_", "test_gw0_", "Prod9_"])
def test_role_prefix_accepts_identifier_safe(field, ok_prefix):
    """Empty (the production default) and identifier-safe prefixes pass."""
    assert getattr(_settings(**{field: ok_prefix}), field) == ok_prefix


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "   ",
        "change-me",
        "CHANGE-ME",
        "super-secret-key",
        "changeme",
        "secret",
        "tooshort1234567890",  # < 32 chars
        # Padded otherwise-valid key: rejected rather than silently stripped,
        # since normalizing would rotate the effective HMAC/Fernet key.
        " f2d8a1c4b7e90365d4a2f8c1b6e3079a5c8d2e4f6a1b3c5d7e9f0a2b4c6d8e1f ",
    ],
)
def test_secret_key_rejects_weak_values(bad_key):
    # Known placeholders and short keys must fail closed at startup —
    # this one key signs JWTs and the OIDC state HMAC and roots all Fernet
    # field encryption.
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(SECRET_KEY=bad_key)


def test_secret_key_accepts_strong_value():
    assert _settings().SECRET_KEY == TEST_SECRET_KEY


def test_secret_key_failure_points_at_safe_rotation_path():
    """The boot-crash message must steer operators to the rotation path, not the
    destructive 'just generate a new one' fix — SECRET_KEY encrypts stored data. It
    must lead with the automatic restart flow (issue #730: the bare CLI instruction
    left operators unsure where to run it), keeping the CLI only as an advanced note."""
    with pytest.raises(ValidationError) as exc:
        _settings(SECRET_KEY="tooshort")
    msg = str(exc.value)
    assert "PREVIOUS_SECRET_KEY" in msg
    assert "restart" in msg
    assert "automatically" in msg
    assert "app.db.secret_key_rotation" in msg


# ──────────────────────────────────────────────────────────────────────────
# DATABASE_URL: the owner alone, or the three logins
# ──────────────────────────────────────────────────────────────────────────

OWNER_URL = "postgresql+asyncpg://owner:p%40ss@db.internal:5433/initiative?ssl=require"


def _owner_settings(**overrides) -> Settings:
    """DATABASE_URL as the owner, with the two login URLs explicitly unset so
    nothing in the test process's environment selects the other shape."""
    overrides.setdefault("DATABASE_URL", OWNER_URL)
    overrides.setdefault("DATABASE_URL_APP", "")
    overrides.setdefault("DATABASE_URL_ADMIN", "")
    return _HermeticSettings(
        APP_URL="https://app.example.com", SECRET_KEY=TEST_SECRET_KEY, **overrides
    )


def test_owner_url_alone_derives_the_three_logins():
    settings = _owner_settings()

    assert settings.database_logins_derived is True
    assert settings.DATABASE_URL_BOOTSTRAP == OWNER_URL
    for setting, role in DATABASE_LOGINS:
        url = make_url(getattr(settings, setting))
        assert url.username == role
        assert url.password == derive_database_password(TEST_SECRET_KEY, role)
        # Everything but the credentials is the owner's.
        assert (url.drivername, url.host, url.port, url.database) == (
            "postgresql+asyncpg",
            "db.internal",
            5433,
            "initiative",
        )
        assert url.query == {"ssl": "require"}


def test_derived_passwords_are_per_role_and_follow_secret_key():
    passwords = {
        derive_database_password(TEST_SECRET_KEY, r) for _, r in DATABASE_LOGINS
    }
    assert len(passwords) == len(DATABASE_LOGINS)
    # Stable for one key, so every replica and every restart agrees.
    assert derive_database_password(TEST_SECRET_KEY, "app_user") == (
        derive_database_password(TEST_SECRET_KEY, "app_user")
    )
    assert derive_database_password("e" * 64, "app_user") != (
        derive_database_password(TEST_SECRET_KEY, "app_user")
    )


def test_three_login_urls_are_used_as_given():
    settings = _settings(DATABASE_URL="postgresql+asyncpg://prov:pw@localhost/app")

    assert settings.database_logins_derived is False
    assert settings.DATABASE_URL == "postgresql+asyncpg://prov:pw@localhost/app"
    assert settings.DATABASE_URL_APP == "postgresql+asyncpg://app:app@localhost/app"
    assert settings.DATABASE_URL_BOOTSTRAP is None


def test_database_login_reads_the_url_and_falls_back_to_the_canonical_name():
    settings = _settings(DATABASE_URL="postgresql+asyncpg://prov:p%40ss@localhost/app")

    assert settings.database_login("DATABASE_URL") == ("prov", "p@ss")
    settings.DATABASE_URL_ADMIN = "postgresql+asyncpg://localhost/app"
    assert settings.database_login("DATABASE_URL_ADMIN") == ("app_admin", None)


@pytest.mark.parametrize(
    ("given", "missing"),
    [
        ("DATABASE_URL_APP", "DATABASE_URL_ADMIN"),
        ("DATABASE_URL_ADMIN", "DATABASE_URL_APP"),
    ],
)
def test_one_login_url_without_the_other_is_refused(given, missing):
    """The error names the settings and shows none of their values."""
    with pytest.raises(ValidationError) as exc_info:
        _owner_settings(**{given: "postgresql+asyncpg://x:pw-7Qz@localhost/app"})
    assert f"{given} is set but {missing} is not" in str(exc_info.value)
    assert "pw-7Qz" not in str(exc_info.value)
    assert "input_value" not in str(exc_info.value)


def test_bootstrap_url_beside_an_owner_database_url_is_refused():
    with pytest.raises(ValidationError, match="so remove DATABASE_URL_BOOTSTRAP"):
        _owner_settings(DATABASE_URL_BOOTSTRAP=OWNER_URL)


def test_query_url_beside_an_owner_url_takes_the_request_login():
    settings = _owner_settings(
        DATABASE_URL_QUERY="postgresql+asyncpg://initiative-ro:5432/initiative"
    )

    url = make_url(settings.DATABASE_URL_QUERY)
    assert (url.host, url.database) == ("initiative-ro", "initiative")
    assert url.username == "app_user"
    assert url.password == derive_database_password(TEST_SECRET_KEY, "app_user")


def test_query_url_beside_named_logins_is_used_as_given():
    query = "postgresql+asyncpg://app:app@replica/app"
    assert _settings(DATABASE_URL_QUERY=query).DATABASE_URL_QUERY == query


def test_query_url_on_another_login_is_refused():
    with pytest.raises(ValidationError, match="same login as DATABASE_URL_APP"):
        _settings(DATABASE_URL_QUERY="postgresql+asyncpg://reader:pw@replica/app")


def test_no_query_url_leaves_it_unset():
    assert _owner_settings().DATABASE_URL_QUERY is None
    assert _settings().DATABASE_URL_QUERY is None


# ──────────────────────────────────────────────────────────────────────────
# PREVIOUS_SECRET_KEY / JWT_SIGNING_KEY / jwt_signing_key
# ──────────────────────────────────────────────────────────────────────────


def test_previous_secret_key_taken_verbatim_without_validation():
    """The OLD key must be reproduced exactly — it may be the weak/whitespaced key
    being escaped, so the strong-key rules must NOT apply to it."""
    weak_old = "  short-old-key  "  # would fail SECRET_KEY validation
    settings = _settings(PREVIOUS_SECRET_KEY=weak_old)
    assert settings.PREVIOUS_SECRET_KEY == weak_old
    # Default when unset.
    assert _settings().PREVIOUS_SECRET_KEY is None


def test_jwt_signing_key_falls_back_to_secret_key_when_unset():
    settings = _settings()
    assert settings.JWT_SIGNING_KEY is None
    assert settings.jwt_signing_key == settings.SECRET_KEY


def test_jwt_signing_key_prefers_dedicated_key_when_set():
    other = "c" * 48
    settings = _settings(JWT_SIGNING_KEY=other)
    assert settings.jwt_signing_key == other
    assert settings.jwt_signing_key != settings.SECRET_KEY


def test_jwt_signing_key_enforces_strong_rules_when_set():
    # Same bar as SECRET_KEY, but only when present.
    with pytest.raises(ValidationError, match="JWT_SIGNING_KEY"):
        _settings(JWT_SIGNING_KEY="tooshort")
    with pytest.raises(ValidationError, match="JWT_SIGNING_KEY"):
        _settings(JWT_SIGNING_KEY="change-me")


def test_cors_allowed_origins_accepts_comma_separated_string():
    settings = _settings(
        CORS_ALLOWED_ORIGINS="https://a.example.com, https://b.example.com",
    )

    # The raw field holds only the operator-supplied extras.
    assert settings.CORS_ALLOWED_ORIGINS == [
        "https://a.example.com",
        "https://b.example.com",
    ]
    # The effective allowlist always prepends APP_URL and appends native origins.
    assert settings.cors_origins == [
        "https://app.example.com",
        "https://a.example.com",
        "https://b.example.com",
        *CAPACITOR_NATIVE_ORIGINS,
    ]


def test_cors_origins_blank_does_not_fall_back_to_wildcard():
    # CRIT-001 regression: an unset/blank allowlist must NOT become "*".
    settings = _settings(CORS_ALLOWED_ORIGINS="")

    assert settings.CORS_ALLOWED_ORIGINS == []
    assert "*" not in settings.cors_origins
    assert settings.cors_origins == [
        "https://app.example.com",
        *CAPACITOR_NATIVE_ORIGINS,
    ]


def test_cors_origins_wildcard_is_dropped():
    # Even an explicit "*" is ignored — never reflected with credentials.
    settings = _settings(CORS_ALLOWED_ORIGINS="*, https://ok.example.com")

    assert "*" not in settings.cors_origins
    assert "https://ok.example.com" in settings.cors_origins
    assert "https://app.example.com" in settings.cors_origins


def test_cors_origins_always_includes_app_url_and_native_origins():
    settings = _settings(CORS_ALLOWED_ORIGINS="https://prod.example.com")

    assert "https://app.example.com" in settings.cors_origins
    for origin in CAPACITOR_NATIVE_ORIGINS:
        assert origin in settings.cors_origins


def test_cors_origins_no_duplicates():
    # Listing APP_URL / native origins explicitly must not duplicate them.
    settings = _settings(
        CORS_ALLOWED_ORIGINS=", ".join(
            [
                "https://app.example.com",
                "https://prod.example.com",
                *CAPACITOR_NATIVE_ORIGINS,
            ]
        ),
    )

    for origin in ["https://app.example.com", *CAPACITOR_NATIVE_ORIGINS]:
        assert settings.cors_origins.count(origin) == 1


def test_cors_origins_strips_trailing_slash():
    settings = _settings(
        APP_URL="https://app.example.com/",
        CORS_ALLOWED_ORIGINS="https://b.example.com/",
    )

    assert "https://app.example.com" in settings.cors_origins
    assert "https://b.example.com" in settings.cors_origins
    assert "https://app.example.com/" not in settings.cors_origins


def test_cors_origins_strips_path_component():
    # An Origin header is scheme+host only; a path on APP_URL (or an operator
    # origin) must be dropped or every credentialed cross-origin request fails.
    settings = _settings(
        APP_URL="https://app.example.com/initiative",
        CORS_ALLOWED_ORIGINS="https://admin.example.com/console",
    )

    assert "https://app.example.com" in settings.cors_origins
    assert "https://admin.example.com" in settings.cors_origins
    assert all(
        "/initiative" not in origin and "/console" not in origin
        for origin in settings.cors_origins
    )


def _csp(settings: Settings) -> str:
    """The app-wide policy, framing no plug-in, for the settings' own captcha."""
    return settings.content_security_policy_with_frames(
        (), captcha_provider=settings.CAPTCHA_PROVIDER
    )


def _directive(policy: str, name: str) -> str:
    """Return one directive segment (e.g. "script-src 'self'") from a CSP string."""
    for part in policy.split(";"):
        part = part.strip()
        if part == name or part.startswith(name + " "):
            return part
    return ""


def test_csp_confines_scripts_and_locks_down_vectors():
    csp = _csp(_settings())

    # Scripts are same-origin only — NO unsafe-inline/eval.
    assert _directive(csp, "script-src") == "script-src 'self'"
    assert "'unsafe-eval'" not in csp

    # High-value hardening directives.
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_allows_inline_styles_but_not_scripts():
    # The chart component / UI libs inject inline <style>, so style-src must
    # permit 'unsafe-inline' — but script-src must not (asserted above).
    csp = _csp(_settings())
    assert "'unsafe-inline'" in _directive(csp, "style-src")
    assert "'unsafe-inline'" not in _directive(csp, "script-src")


def test_webassembly_is_named_only_on_the_wasm_worker_policy():
    # Dashboard widgets are evaluated by QuickJS compiled to WebAssembly and
    # direct messages are ratcheted by vodozemac compiled to WebAssembly, which
    # needs a source expression the app-wide policy does not carry. It is named
    # on those workers' own responses and nowhere else.
    settings = _settings()
    assert "'wasm-unsafe-eval'" not in _csp(settings)
    assert "'wasm-unsafe-eval'" not in settings.docs_content_security_policy

    sandbox = settings.wasm_worker_content_security_policy
    assert _directive(sandbox, "script-src") == "script-src 'self' 'wasm-unsafe-eval'"


def test_wasm_worker_policy_grants_only_what_the_workers_use():
    # Their own script, WebAssembly, and the same-origin fetch for the .wasm
    # file. Everything else — DOM-adjacent fetches, frames, workers — falls to
    # default-src 'none'.
    sandbox = _settings().wasm_worker_content_security_policy
    assert {part.strip() for part in sandbox.split(";")} == {
        "default-src 'none'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "connect-src 'self'",
    }


def test_app_url_scheme_decides_https():
    """Only the URL scheme counts, and it drives the Secure cookie flag, HSTS
    and the websocket scheme the CSP admits alike."""
    https = _settings(APP_URL="https://app.example.com")
    assert https.app_url_is_https is True
    assert "wss:" in _directive(_csp(https), "connect-src").split()

    for app_url in ("http://localhost:5173", "http://https.example.com"):
        http = _settings(APP_URL=app_url)
        assert http.app_url_is_https is False
        assert "ws:" in _directive(_csp(http), "connect-src").split()


def test_csp_allows_spell_check_dictionary_cdn():
    # The spell checker fetches its English dictionary from jsDelivr
    # (frontend/src/lib/spell-check.ts); connect-src must allow it.
    csp = _csp(_settings())
    assert "https://cdn.jsdelivr.net" in _directive(csp, "connect-src")


def test_csp_allows_excalidraw_font_cdn():
    # The bundled Excalidraw whiteboard loads its .woff2 faces from esm.sh;
    # font-src must allow it.
    csp = _csp(_settings())
    assert "https://esm.sh" in _directive(csp, "font-src")


def test_csp_captcha_origins_only_when_configured():
    assert "hcaptcha.com" not in _csp(_settings())

    on = _csp(_settings(CAPTCHA_PROVIDER="hcaptcha"))
    assert "https://*.hcaptcha.com" in _directive(on, "script-src")


def test_csp_billing_origin_only_when_portal_configured():
    """The landing page fetches the pricing catalog from the billing portal,
    so its origin is allowed for fetch() only on a deployment that names one,
    and only the origin, never the path it was configured with. It frames the
    portal's pricing grid, and that page alone is allowed in a frame."""
    assert "billing.example.com" not in _csp(_settings())

    on = _csp(_settings(BILLING_URL="https://billing.example.com/portal/"))
    assert "https://billing.example.com" in _directive(on, "connect-src")
    assert "/portal" not in _directive(on, "connect-src")
    # One page of the portal may be framed, its pricing grid; not the portal.
    frames = _directive(on, "frame-src").split()
    assert "https://billing.example.com/portal/embed/pricing" in frames
    assert "https://billing.example.com" not in frames
    assert "billing.example.com" not in _directive(on, "script-src")


@pytest.mark.parametrize(
    ("billing_url", "frame"),
    [
        ("https://billing.example.com", "https://billing.example.com/embed/pricing"),
        ("https://billing.example.com/", "https://billing.example.com/embed/pricing"),
        ("http://localhost:8100", "http://localhost:8100/embed/pricing"),
    ],
)
def test_csp_frames_only_the_billing_pricing_grid(billing_url, frame):
    frames = _directive(_csp(_settings(BILLING_URL=billing_url)), "frame-src").split()
    assert frame in frames
    assert not any(f.startswith(billing_url.rstrip("/")) and f != frame for f in frames)


def test_csp_frames_nothing_from_a_billing_url_it_cannot_reduce_safely():
    on = _csp(_settings(BILLING_URL="https://billing.example.com/a;b"))
    assert "billing.example.com" not in _directive(on, "frame-src")


def test_csp_collector_origin_only_when_one_is_on_another_origin():
    """The SPA posts measurements to the named collector, so only its origin
    joins connect-src; a same-origin path needs nothing beyond 'self'."""
    assert "faro.example.com" not in _csp(_settings())

    on = _csp(_settings(FARO_COLLECTOR_URL="https://faro.example.com/collect"))
    assert "https://faro.example.com" in _directive(on, "connect-src")
    assert "/collect" not in _directive(on, "connect-src")

    path = _csp(_settings(FARO_COLLECTOR_URL="/collect"))
    assert _directive(path, "connect-src") == _directive(
        _csp(_settings()), "connect-src"
    )


@pytest.mark.parametrize("value", ["faro.example.com", "//faro.example.com", "ftp://x"])
def test_collector_url_must_be_a_path_or_http_url(value):
    with pytest.raises(ValidationError, match="FARO_COLLECTOR_URL") as raised:
        _settings(FARO_COLLECTOR_URL=value)
    assert "input_value" not in str(raised.value)


def test_blank_collector_url_is_unset():
    assert _settings(FARO_COLLECTOR_URL="  ").FARO_COLLECTOR_URL is None


def test_docs_csp_allows_swagger_cdn_but_main_csp_does_not():
    # Swagger's jsDelivr + Cloudflare beacon scripts are permitted ONLY on the
    # docs-scoped policy; the app-wide script-src stays 'self' (pentest MED-001).
    settings = _settings()
    docs = settings.docs_content_security_policy
    main = _csp(settings)

    assert "https://cdn.jsdelivr.net" in _directive(docs, "script-src")
    assert "https://static.cloudflareinsights.com" in _directive(docs, "script-src")
    assert "https://cdn.jsdelivr.net" in _directive(docs, "style-src")
    # Swagger boots from an inline <script>, and its bundle fetches a .map.
    assert "'unsafe-inline'" in _directive(docs, "script-src")
    assert "https://cdn.jsdelivr.net" in _directive(docs, "connect-src")

    # The relaxation must not leak into the global policy.
    assert "cdn.jsdelivr.net" not in _directive(main, "script-src")
    assert "cloudflareinsights.com" not in main
    assert "'unsafe-inline'" not in _directive(main, "script-src")
    # Docs page keeps the remaining directives strict.
    assert "object-src 'none'" in docs
    assert "frame-ancestors 'none'" in docs
    assert "form-action 'self'" in docs


def test_log_level_defaults_to_info():
    assert _settings().LOG_LEVEL == "INFO"


@pytest.mark.parametrize("given", ["debug", " Warning ", "ERROR"])
def test_log_level_is_read_as_a_standard_level_name(given):
    assert _settings(LOG_LEVEL=given).LOG_LEVEL == given.strip().upper()


@pytest.mark.parametrize("bad", ["verbose", "NOTSET", "", "20"])
def test_log_level_refuses_anything_else(bad):
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        _settings(LOG_LEVEL=bad)


def test_auth_login_methods_accepts_comma_separated_string():
    settings = _settings(AUTH_LOGIN_METHODS="sso, Passkey,totp email_otp,sso")

    # One of each, lower case: the shape the seed compares against the enum.
    assert settings.AUTH_LOGIN_METHODS == ["sso", "passkey", "totp", "email_otp"]


def test_auth_login_methods_blank_means_unset():
    """Blank and unset read the same: no methods, so the seed keeps the app's
    own default."""
    assert _settings().AUTH_LOGIN_METHODS == []
    assert _settings(AUTH_LOGIN_METHODS="").AUTH_LOGIN_METHODS == []
    assert _settings(AUTH_LOGIN_METHODS=" , ").AUTH_LOGIN_METHODS == []


def test_list_settings_read_from_the_environment(monkeypatch):
    """Every list setting takes items separated by commas and/or spaces, or a
    JSON list; a blank OIDC_SCOPES is the default scope list, as an unset one is,
    and one naming no scope asks for openid, profile and email."""
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", "https://a.example.com, https://b.example.com"
    )
    monkeypatch.setenv("AUTH_LOGIN_METHODS", '["SSO", "passkey", "sso"]')
    monkeypatch.setenv("OIDC_SCOPES", "openid profile,groups openid")
    settings = _settings()

    assert settings.CORS_ALLOWED_ORIGINS == [
        "https://a.example.com",
        "https://b.example.com",
    ]
    assert settings.AUTH_LOGIN_METHODS == ["sso", "passkey"]
    assert settings.OIDC_SCOPES == ["openid", "profile", "groups"]

    monkeypatch.setenv("OIDC_SCOPES", " , ")
    assert _settings().OIDC_SCOPES == ["openid", "profile", "email"]
    monkeypatch.setenv("OIDC_SCOPES", " ")
    blank = _settings().OIDC_SCOPES
    monkeypatch.delenv("OIDC_SCOPES")
    assert blank == _settings().OIDC_SCOPES == list(DEFAULT_OIDC_SCOPES)


def test_database_name_points_every_url_at_that_database():
    for settings in (
        _settings(DATABASE_NAME="initiative_dev_ab12cd34"),
        _owner_settings(DATABASE_NAME="initiative_dev_ab12cd34"),
    ):
        for url in (
            settings.DATABASE_URL,
            settings.DATABASE_URL_APP,
            settings.DATABASE_URL_ADMIN,
        ):
            assert make_url(url).database == "initiative_dev_ab12cd34"
