import hashlib
import hmac
import json
import logging
import re
import uuid
from collections.abc import Sequence
from enum import Enum
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    BeforeValidator,
    EmailStr,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from starlette.requests import Request


# App identity/shape — deliberately constants, not settings: the SPA, the
# docs-CSP route, and the OpenAPI export all assume this prefix, so making it
# configurable only creates ways to break them.
PROJECT_NAME = "Initiative API"
API_V1_STR = "/api/v1"
#: Where an installed plug-in calls the API from. The ``0`` stands for the
#: install's own community, which its token names.
PLUGIN_SERVER_URL = f"{API_V1_STR}/c/0"

# Origins used by the Capacitor native apps (iOS, Android and the desktop app).
# Must always be allowed regardless of CORS_ALLOWED_ORIGINS setting.
CAPACITOR_NATIVE_ORIGINS = [
    "https://studio.beyonders.initiative",  # Capacitor custom hostname (Android + iOS with iosScheme=https)
    "capacitor://studio.beyonders.initiative",  # Capacitor default iOS scheme with custom hostname; the desktop app
    "capacitor://localhost",  # Capacitor fallback (no custom hostname)
]


def is_device(request: Request) -> bool:
    """Whether the request comes from the phone or desktop app.

    The one place that decides. The apps present their own origin, which no
    page can, and a device keeps its own refresh token and stays signed in
    longer than a browser.
    """
    return request.headers.get("origin") in CAPACITOR_NATIVE_ORIGINS


#: Where the app names the copy of itself a request comes from.
INSTALL_HEADER = "X-Initiative-Install"


def install_id(request: Request) -> uuid.UUID | None:
    """The installed copy of the app a request names, read beside
    :func:`is_device` and only where it holds.

    The app makes the name once per server and keeps it through sign-out, so a
    device signing in again continues its own session rather than counting as
    another device. ``None`` for a browser, or an app too old to send one.
    """
    if not is_device(request):
        return None
    try:
        return uuid.UUID(request.headers.get(INSTALL_HEADER, ""))
    except ValueError:
        return None


# Third-party origins the built SPA legitimately embeds in iframes, used to build
# the Content-Security-Policy (pentest MED-001). These are the file
# "smart link" providers available in the editor (always present).
CSP_EMBED_FRAME_ORIGINS = [
    "https://www.youtube-nocookie.com",
    "https://www.youtube.com",
    "https://www.figma.com",
    "https://www.loom.com",
    "https://player.vimeo.com",
    "https://docs.google.com",
    "https://miro.com",
    "https://airtable.com",
]


class CaptchaProvider(str, Enum):
    """The registration captcha vendors ``CAPTCHA_PROVIDER`` may name."""

    hcaptcha = "hcaptcha"
    turnstile = "turnstile"
    recaptcha = "recaptcha"


class StorageBackendKind(str, Enum):
    """Where uploads are kept: ``STORAGE_BACKEND``."""

    local = "local"
    s3 = "s3"


# Captcha providers → the extra origins each needs (script/frame/style/connect).
# Only the configured provider's origins are added; the gate is off by default.
CSP_CAPTCHA_ORIGINS: dict[str, list[str]] = {
    CaptchaProvider.hcaptcha: ["https://hcaptcha.com", "https://*.hcaptcha.com"],
    CaptchaProvider.turnstile: ["https://challenges.cloudflare.com"],
    CaptchaProvider.recaptcha: ["https://www.google.com", "https://www.gstatic.com"],
}

# Origins the SPA fetches non-script assets from via fetch()/XHR, used to build
# the connect-src directive. The spell checker lazy-loads its English dictionary
# (.aff/.dic) from jsDelivr — see frontend/src/lib/spell-check.ts.
CSP_CONNECT_ORIGINS = [
    "https://cdn.jsdelivr.net",
]

# Origins the SPA loads web fonts from (font-src). The bundled Excalidraw
# whiteboard lazy-loads its .woff2 faces (Cascadia, Comic Shanns, Excalifont,
# etc.) from esm.sh at runtime.
CSP_FONT_ORIGINS = [
    "https://esm.sh",  # Do not promote esm.sh to script-src
]

# Swagger UI (/docs) pulls its bundle + stylesheet from jsDelivr and, behind a
# Cloudflare proxy, a Web Analytics beacon. These get a relaxed, docs-ONLY CSP
# (Settings.docs_content_security_policy) applied per-route so the app-wide
# script-src can stay 'self' (pentest MED-001) — never add these to the main CSP.
CSP_SWAGGER_SCRIPT_ORIGINS = [
    "https://cdn.jsdelivr.net",
    "https://static.cloudflareinsights.com",
]
CSP_SWAGGER_STYLE_ORIGINS = ["https://cdn.jsdelivr.net"]


#: What the platform OIDC provider asks for when nothing names its scopes.
DEFAULT_OIDC_SCOPES = ("openid", "profile", "email", "offline_access")


def _split_env_list(value: object) -> object:
    """A list setting's value: a JSON list, or items separated by commas and/or
    whitespace. Items are trimmed, blanks drop out, and a repeat keeps its first
    place."""
    if isinstance(value, str):
        text = value.strip()
        value = (
            json.loads(text) if text.startswith("[") else text.replace(",", " ").split()
        )
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))
    return value


#: Every list setting reads its value by ``_split_env_list``.
EnvList = Annotated[list[str], NoDecode, BeforeValidator(_split_env_list)]


def _format_csp(directives: dict[str, list[str]]) -> str:
    """Render a directive map to a CSP header string, de-duplicating sources."""
    return "; ".join(
        f"{name} {' '.join(dict.fromkeys(values))}"
        for name, values in directives.items()
    )


def captcha_frame_content_security_policy(provider: str, nonce: str) -> str:
    """The policy for the captcha page the apps frame (``/config/captcha``).

    The page holds one widget and nothing else, so it may load only the
    provider and its own script, and only the apps may frame it.
    """
    provider_origins = CSP_CAPTCHA_ORIGINS[provider]
    return _format_csp(
        {
            "default-src": ["'none'"],
            "script-src": [f"'nonce-{nonce}'", *provider_origins],
            "style-src": ["'unsafe-inline'", *provider_origins],
            "img-src": ["data:", *provider_origins],
            "connect-src": provider_origins,
            "frame-src": provider_origins,
            "object-src": ["'none'"],
            "base-uri": ["'none'"],
            "form-action": ["'none'"],
            "frame-ancestors": CAPACITOR_NATIVE_ORIGINS,
        }
    )


#: The billing portal's pricing grid, the one page of it the front door frames.
BILLING_PRICING_EMBED_PATH = "/embed/pricing"

#: Characters a path may carry into a CSP source expression.
_CSP_PATH = re.compile(r"^[A-Za-z0-9._~/-]*$")


def _billing_embed_source(url: str) -> str | None:
    """The exact address of the billing portal's pricing grid, as a CSP
    source: its origin and path, so a frame may load that page and no other.
    None when the portal's URL cannot be reduced to one safely."""
    origin = _origin_of(url)
    if not origin:
        return None
    base = urlsplit(url.strip()).path.rstrip("/")
    if not _CSP_PATH.match(base):
        return None
    return f"{origin}{base}{BILLING_PRICING_EMBED_PATH}"


def _origin_of(url: str) -> str | None:
    """Return the ``scheme://host[:port]`` origin of a URL, or None if unparseable."""
    parts = urlsplit(url.strip())
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None


# How an operator safely changes the encryption root. Appended to SECRET_KEY
# validation failures (rotation_hint=True) so the boot-crash message points at the
# rotation path instead of inviting the destructive "just generate a new one" fix.
# It must travel in the ValueError text itself: pydantic validators run at settings
# load, before logging is configured, so there's nowhere else for it to surface.
_SECRET_KEY_ROTATION_HINT = (
    " To CHANGE SECRET_KEY on an existing deployment, do NOT swap it directly — it "
    "encrypts stored data (emails, OIDC/SMTP/AI secrets) and roots email lookup, so a "
    "bare swap locks out every user and orphans those secrets. Instead set the old "
    "value as PREVIOUS_SECRET_KEY, set SECRET_KEY to the new key, and restart — the "
    "server re-encrypts the stored data automatically on startup. Once the logs report "
    "the rotation is complete, UNSET PREVIOUS_SECRET_KEY. (Advanced: you can instead "
    "run `python -m app.db.secret_key_rotation` from the backend/ directory to rotate "
    "out-of-band, but a restart is all that's required.)"
)


def _validate_strong_key(value: str, var_name: str, *, rotation_hint: bool) -> str:
    """Enforce the shared strength rules for SECRET_KEY / JWT_SIGNING_KEY: non-empty,
    not a known placeholder, no surrounding whitespace, >= 32 chars. ``rotation_hint``
    appends the safe-change instructions for keys that encrypt stored data."""
    hint = _SECRET_KEY_ROTATION_HINT if rotation_hint else ""
    known_placeholders = {"change-me", "changeme", "super-secret-key", "secret"}
    normalized = value.strip()
    if not normalized or normalized.lower() in known_placeholders:
        raise ValueError(
            f"{var_name} is unset or a known placeholder. Generate a real key "
            f"with: openssl rand -hex 32{hint}"
        )
    # Reject (rather than silently strip) surrounding whitespace: every byte of this
    # value feeds HMAC/Fernet key derivation, so quietly normalizing it would rotate
    # the effective key out from under a deployment whose env var carried whitespace.
    if normalized != value:
        raise ValueError(
            f"{var_name} has leading or trailing whitespace. Remove it — the exact "
            f"value is used for key derivation.{hint}"
        )
    if len(normalized) < 32:
        raise ValueError(
            f"{var_name} must be at least 32 characters. Generate one with: "
            f"openssl rand -hex 32{hint}"
        )
    return value


#: Settings whose environment variable is only a FIRST-BOOT SEED.
#:
#: Each of these is stored in the database on first start and edited in
#: Settings → Platform from then on, so the env var is read once and the row wins
#: afterwards. ``app/services/platform/app_settings.py`` (``_seed_from_env``) is
#: the mechanism; the credential-bearing ones are encrypted at rest under a salt
#: their column declares, so ``app/db/secret_key_rotation.py`` rotates them
#: with SECRET_KEY.
#:
#: Declared here so the deployment contract can say so out loud: an operator
#: does not need any of these to bring the app up, and a deployment tool does
#: not need to carry them as deploy-time secrets. See ``env-contract.json``.
RUNTIME_SEEDED_SETTINGS = frozenset(
    {
        # Outbound mail.
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_SECURE",
        "SMTP_REJECT_UNAUTHORIZED",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_ADDRESS",
        "SMTP_TEST_RECIPIENT",
        # Object storage.
        "STORAGE_BACKEND",
        "S3_BUCKET",
        "S3_REGION",
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_USE_PATH_STYLE",
        "S3_LOCAL_FALLBACK",
        # The platform OIDC provider. Seeded into the provider row by
        # app/services/auth/platform_provider.py; after that the row holds the
        # secret, which is why rotating it upstream needs a paste in Settings.
        "OIDC_ENABLED",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_PROVIDER_NAME",
        "OIDC_SCOPES",
        # The registration captcha (0368). Provider and site key are public;
        # the verification secret is encrypted on app_setting_secrets.
        "CAPTCHA_PROVIDER",
        "CAPTCHA_SITE_KEY",
        "CAPTCHA_SECRET_KEY",
        # Push notifications (0368). Everything but the service-account JSON
        # reaches a device or a page; that one is encrypted at rest.
        "FCM_ENABLED",
        "FCM_PROJECT_ID",
        "FCM_APPLICATION_ID",
        "FCM_API_KEY",
        "FCM_SENDER_ID",
        "FCM_SERVICE_ACCOUNT_JSON",
    }
)

#: Operator-supplied credentials with no database path, and so no way to set
#: them after deployment. The environment would be the only place they could
#: live, which makes them the only reason a deployment tool needs a free-form
#: secret passthrough.
#:
#: **Empty since 0368**, when the captcha secret and the FCM service account --
#: the last two -- moved onto the settings singleton. Kept rather than deleted
#: because it is a claim worth being able to check: anything added here is a
#: setting an operator can never change without a redeploy, and a deployment
#: tool has to carry it as a secret. Prefer the seeded set above.
ENV_ONLY_FEATURE_CREDENTIALS: frozenset[str] = frozenset()

#: The app's three logins: the setting whose URL connects as each, and the
#: login's canonical name — what the app calls it when it makes the login
#: itself, and what a URL naming no user is read as.
DATABASE_LOGINS: tuple[tuple[str, str], ...] = (
    ("DATABASE_URL", "app_provisioner"),
    ("DATABASE_URL_APP", "app_user"),
    ("DATABASE_URL_ADMIN", "app_admin"),
)


def derive_database_password(secret_key: str, role: str) -> str:
    """The password a derived login is given: one per role, from SECRET_KEY.

    The bootstrap sets it on every start, so it follows SECRET_KEY through a
    rotation without anything else to change.
    """
    return hmac.new(
        secret_key.encode(), b"database-login:" + role.encode(), hashlib.sha256
    ).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # A setting that fails is named in the error, never shown.
        hide_input_in_errors=True,
    )

    # The database, in one of two shapes.
    #
    # Usually the database owner, with DATABASE_URL_APP and DATABASE_URL_ADMIN
    # left unset. The app then makes its three logins itself (see
    # DATABASE_LOGINS), with passwords derived from SECRET_KEY, and
    # `_resolve_database_logins` rewrites these four settings into the second
    # shape, so nothing that reads them needs to know which one was given.
    #
    # Or the app_provisioner login, with DATABASE_URL_APP (app_user, the request
    # path) and DATABASE_URL_ADMIN (app_admin, the system engine) set beside it,
    # for a deployment that names its logins and passwords itself.
    DATABASE_URL: str = (
        "postgresql+asyncpg://initiative:initiative@localhost:5432/initiative"
    )
    DATABASE_URL_APP: str = ""
    DATABASE_URL_ADMIN: str = ""
    # The database owner, used once at startup to apply the prerequisites the
    # three logins above cannot create for themselves: the logins themselves,
    # and the guild-search match operator (see app.db.bootstrap). The
    # connection is opened, used and disposed before the app serves anything.
    # Unset it and the app verifies those prerequisites instead of applying
    # them; a deployment that provisions its database out of band never sets it.
    # Only set it beside DATABASE_URL_APP and DATABASE_URL_ADMIN: otherwise
    # DATABASE_URL is already the owner, and this is filled in from it.
    DATABASE_URL_BOOTSTRAP: str | None = None
    # Where to hold the realtime signal channel's own connection. ``LISTEN`` is
    # session state and so wants a connection of its own, apart from the pooled
    # engines above. Unset (the common case) it uses ``DATABASE_URL``; set it
    # where the app reaches Postgres through something that pools per
    # transaction, which cannot hold a subscription open.
    DATABASE_URL_LISTEN: str | None = None
    # Where reads that may trail the primary by a moment go: dashboard widgets'
    # SQL and export renders. Point it at a read replica. It connects as the
    # same login as DATABASE_URL_APP; when DATABASE_URL names the owner, give
    # only the host and database and the app fills in that login. Unset, those
    # reads use DATABASE_URL_APP.
    DATABASE_URL_QUERY: str | None = None
    # How long a pooled connection may live before it is retired and replaced.
    #
    # A backend permanently caches catalog entries for every table it touches
    # and Postgres never shrinks CacheMemoryContext, so under schema-per-guild
    # a long-lived connection's private memory grows with the number of guild
    # schemas it has served. Only closing it gives that back. Postgres-side
    # idle timeouts do not reach these: a pooled connection is handed out
    # again long before it has been idle long enough to trip one, so age is
    # the only bound that actually applies. 0 disables recycling.
    DB_POOL_RECYCLE_SECONDS: int = 1800
    # Connections each request and system pool keeps open, and how many more it
    # may open under load. With DB_COHORTS above 1 these size every cohort's
    # request pool, not their total.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # How many groups ("cohorts") communities are divided into. Each cohort has
    # a request pool of its own, and a connection only ever serves its own
    # cohort's communities, so the catalog each database connection caches is
    # a K-th of the whole. 1 is one shared pool.
    DB_COHORTS: int = 1
    # The database name each cohort's connections ask for, with ``{cohort}``
    # standing for its number: ``initiative_c{cohort}`` behind a pooler that
    # gives each cohort an alias of its own. Unset, every cohort connects to
    # the database DATABASE_URL_APP names.
    DB_COHORT_DATABASE: str | None = None

    SECRET_KEY: str
    # Optional: the *previous* SECRET_KEY, set only while rotating the encryption
    # root. Read verbatim (NO validation/normalization) so it reproduces the old
    # effective key exactly — it may be the weak/whitespaced key being escaped, and
    # the legacy code never stripped it. Consumed by app.db.secret_key_rotation;
    # remove it once the rotation has run.
    PREVIOUS_SECRET_KEY: str | None = None
    # Optional: dedicated JWT signing key. When set, session/upload/handoff JWTs are
    # signed and verified with this instead of SECRET_KEY (see ``jwt_signing_key``),
    # so it can be rotated freely — the only cost is forcing every user to re-login,
    # with no impact on encrypted-at-rest data. Falls back to SECRET_KEY when unset.
    JWT_SIGNING_KEY: str | None = None

    # The JWT algorithm and cookie names are constants in app.core.security
    # (JWT_ALGORITHM, SESSION_COOKIE_NAME, REFRESH_COOKIE_NAME) — the JWT
    # algorithm is fixed, and the cookie names are part of the auth contract,
    # not deployment configuration.

    # New login model (auth rewrite, Phase 0).
    # The access token is short-lived + stateless: verified locally with no
    # per-request DB read (the 10k+ win), and expires within one TTL. The
    # refresh token is long, opaque, rotating, and revocable via ``auth_sessions``.
    #
    # Together these are how long somebody stays signed in: the browser renews
    # silently every AUTH_ACCESS_TTL_MINUTES and keeps the session for
    # AUTH_REFRESH_TTL_DAYS of not using the app. They are the whole of that
    # setting now — they replaced ``ACCESS_TOKEN_EXPIRE_MINUTES``, which is
    # gone.
    AUTH_ACCESS_TTL_MINUTES: int = 15
    AUTH_REFRESH_TTL_DAYS: int = 30

    @field_validator("DB_COHORTS", "DB_POOL_SIZE")
    @classmethod
    def _at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value

    @field_validator("STORAGE_ENCRYPTION")
    @classmethod
    def _storage_encryption_root(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("", "local", "gcp_kms"):
            raise ValueError('must be unset, "local" or "gcp_kms"')
        return value

    @model_validator(mode="after")
    def _kms_root_names_its_key(self) -> "Settings":
        if self.STORAGE_ENCRYPTION == "gcp_kms" and not self.STORAGE_ENCRYPTION_KMS_KEY:
            raise ValueError(
                'STORAGE_ENCRYPTION="gcp_kms" needs STORAGE_ENCRYPTION_KMS_KEY: '
                "projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>"
            )
        return self

    @field_validator("DB_MAX_OVERFLOW")
    @classmethod
    def _not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must not be negative")
        return value

    @field_validator("DB_COHORT_DATABASE")
    @classmethod
    def _names_the_cohort(cls, value: str | None) -> str | None:
        if not value:
            return None
        if "{cohort}" not in value:
            raise ValueError(
                "DB_COHORT_DATABASE must contain {cohort}, which stands for the "
                "cohort's number"
            )
        try:
            value.format(cohort=0)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                "DB_COHORT_DATABASE may contain {cohort} and nothing else in braces"
            ) from exc
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        # SECRET_KEY signs the OIDC state HMAC and roots all Fernet field encryption
        # (SMTP password, OIDC client secret, AI keys, refresh tokens) plus the
        # email_hash HMAC, so a known placeholder or short key fails closed at
        # startup. The hint points at the safe rotation path because the naive
        # fix — "just set a new key" — silently orphans all encrypted data.
        return _validate_strong_key(value, "SECRET_KEY", rotation_hint=True)

    @field_validator("JWT_SIGNING_KEY")
    @classmethod
    def _validate_jwt_signing_key(cls, value: str | None) -> str | None:
        # Optional, but when present it signs JWTs, so hold it to the same strength
        # bar as SECRET_KEY. No rotation hint: rotating it only forces re-login, so a
        # bare swap is the correct fix.
        if value is None:
            return None
        return _validate_strong_key(value, "JWT_SIGNING_KEY", rotation_hint=False)

    @field_validator("GUILD_ROLE_PREFIX", "PLATFORM_ROLE_PREFIX")
    @classmethod
    def _validate_role_prefix(cls, value: str) -> str:
        # These prefixes are interpolated into Postgres ROLE-name DDL and into
        # every request's SET ROLE. Pin them to an unquoted-identifier-safe
        # shape once at load time (fail closed) so no name-builder or migration
        # has to re-check: empty (the production default), or a leading letter/
        # underscore followed by letters, digits, and underscores. A
        # digit-leading prefix would yield a role name Postgres rejects.
        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(
                "must be empty or start with a letter or underscore and contain "
                "only ASCII letters, digits, and underscores (it becomes part of "
                "Postgres role names)"
            )
        return value

    _database_logins_derived: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _resolve_database_logins(self) -> "Settings":
        has_plugin, has_admin = (
            bool(self.DATABASE_URL_APP),
            bool(self.DATABASE_URL_ADMIN),
        )
        if has_plugin != has_admin:
            given, missing = (
                ("DATABASE_URL_APP", "DATABASE_URL_ADMIN")
                if has_plugin
                else ("DATABASE_URL_ADMIN", "DATABASE_URL_APP")
            )
            raise ValueError(
                f"{given} is set but {missing} is not. Set both, with DATABASE_URL "
                f"as app_provisioner, to name the app's logins yourself; or set "
                f"neither, with DATABASE_URL as the database owner, and the app "
                f"makes them."
            )
        if has_plugin:
            self._check_query_login()
            return self
        if self.DATABASE_URL_BOOTSTRAP:
            raise ValueError(
                "DATABASE_URL_BOOTSTRAP is set without DATABASE_URL_APP and "
                "DATABASE_URL_ADMIN. Without those two, DATABASE_URL is the "
                "database owner and the app makes its own logins, so remove "
                "DATABASE_URL_BOOTSTRAP. To name the logins yourself instead, set "
                "DATABASE_URL (as app_provisioner), DATABASE_URL_APP and "
                "DATABASE_URL_ADMIN."
            )
        owner = make_url(self.DATABASE_URL)
        self.DATABASE_URL_BOOTSTRAP = self.DATABASE_URL
        for setting, role in DATABASE_LOGINS:
            login = owner.set(
                username=role,
                password=derive_database_password(self.SECRET_KEY, role),
            )
            setattr(self, setting, login.render_as_string(hide_password=False))
        if self.DATABASE_URL_QUERY:
            request_login = make_url(self.DATABASE_URL_APP)
            self.DATABASE_URL_QUERY = (
                make_url(self.DATABASE_URL_QUERY)
                .set(username=request_login.username, password=request_login.password)
                .render_as_string(hide_password=False)
            )
        self._database_logins_derived = True
        return self

    def _check_query_login(self) -> None:
        """DATABASE_URL_QUERY connects as DATABASE_URL_APP's login, the one
        the query roles are granted to."""
        if not self.DATABASE_URL_QUERY:
            return
        query_login = make_url(self.DATABASE_URL_QUERY).username
        request_login = make_url(self.DATABASE_URL_APP).username
        if query_login != request_login:
            raise ValueError(
                f"DATABASE_URL_QUERY connects as {query_login!r}, but it must use "
                f"the same login as DATABASE_URL_APP ({request_login!r})."
            )

    @property
    def database_logins_derived(self) -> bool:
        """Whether DATABASE_URL named the owner and the app made its logins."""
        return self._database_logins_derived

    def database_login(self, setting: str) -> tuple[str, str | None]:
        """The (name, password) one of the DATABASE_LOGINS settings connects as.

        A deployment may name its logins anything; this is the name its URL
        gives, or the canonical one when the URL gives none.
        """
        canonical = dict(DATABASE_LOGINS)[setting]
        try:
            url = make_url(getattr(self, setting))
        except ArgumentError:
            return canonical, None
        return url.username or canonical, url.password or None

    @property
    def jwt_signing_key(self) -> str:
        """Key used to sign/verify JWTs. Prefers the dedicated JWT_SIGNING_KEY so it
        can be rotated without touching encrypted-at-rest data; falls back to
        SECRET_KEY for deployments that haven't set one."""
        return self.JWT_SIGNING_KEY or self.SECRET_KEY

    @property
    def registration_open(self) -> bool:
        """Whether somebody may register without an invite."""
        return self.ENABLE_PUBLIC_REGISTRATION and not self.DISABLE_GUILD_CREATION

    @property
    def app_url_is_https(self) -> bool:
        """True when the public app origin is served over HTTPS.

        Drives the ``Secure`` cookie flag, the websocket scheme the CSP admits,
        and whether the ``Strict-Transport-Security`` header is emitted — HSTS
        over plain HTTP is meaningless and would needlessly pin a dev origin to
        HTTPS.
        """
        return urlsplit(self.APP_URL.strip()).scheme == "https"

    # APP_URL should point to the frontend entry so redirect URIs resolve correctly
    APP_URL: str = "http://localhost:5173"
    # Extra browser origins allowed to make credentialed cross-origin requests,
    # beyond APP_URL and the native app (both always allowed — see `cors_origins`).
    # A wildcard is unsupported: ``*`` names no origin, so it adds nothing.
    CORS_ALLOWED_ORIGINS: EnvList = Field(default_factory=list)

    @property
    def cors_origins(self) -> list[str]:
        """Effective CORS allowlist for credentialed requests — never ``*``.

        ``allow_origins=["*"]`` together with ``allow_credentials=True`` makes
        the server reflect any ``Origin`` and echo
        ``Access-Control-Allow-Credentials: true``, letting any website make
        authenticated cross-origin requests on a logged-in user's behalf
        (pentest CRIT-001). We therefore build an explicit allowlist: the app's
        own ``APP_URL`` and the native mobile origins are always included, plus
        whatever operators add via ``CORS_ALLOWED_ORIGINS``.

        Each value is reduced to its bare ``scheme://host[:port]`` origin: an
        ``Origin`` header never carries a path, so an ``APP_URL`` like
        ``https://host/app`` must match as ``https://host`` or every credentialed
        cross-origin request is silently rejected. A value with no scheme and
        host, ``*`` among them, reduces to nothing and is left out.
        """
        origins: list[str] = []
        for candidate in [
            self.APP_URL,
            *self.CORS_ALLOWED_ORIGINS,
            *CAPACITOR_NATIVE_ORIGINS,
        ]:
            origin = _origin_of(candidate) if candidate else None
            if origin and origin not in origins:
                origins.append(origin)
        return origins

    def content_security_policy_with_frames(
        self, plugin_frame_origins: Sequence[str], *, captcha_provider: str | None
    ) -> str:
        """The app-wide CSP, optionally admitting the registered frame origins.

        Locks down the high-value vectors (``object-src``/``base-uri``/
        ``frame-ancestors``/``form-action``) and confines scripts to
        same-origin — scripts get NO ``'unsafe-inline'``/``'unsafe-eval'`` so
        injected markup can't execute. ``style-src`` does allow
        ``'unsafe-inline'`` because the charting component and some UI libraries
        inject inline ``<style>``. Origins the app genuinely loads (Google
        Fonts, file embeds, and — when configured — the captcha provider and
        plug-in pages) are listed explicitly rather than via a blanket
        ``https:``.

        ``plugin_frame_origins`` is how a marketplace plug-in's page gets
        framed. It holds the origins of the plug-in services this deployment has
        registered — the operator's trusted-site list, passed in by
        ``app.api.embed_csp`` on the documents where ``frame-src`` applies, and
        empty here so the app-wide default names none. ``connect-src`` is
        untouched: a plug-in's data reaches the browser same-origin through the
        proxy.
        """
        ws = "wss:" if self.app_url_is_https else "ws:"

        script_src = ["'self'"]
        style_src = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
        font_src = ["'self'", "https://fonts.gstatic.com", "data:", *CSP_FONT_ORIGINS]
        img_src = ["'self'", "data:", "blob:", "https:"]
        connect_src = ["'self'", ws, *CSP_CONNECT_ORIGINS]
        frame_src = ["'self'", *CSP_EMBED_FRAME_ORIGINS]
        worker_src = ["'self'", "blob:"]

        if captcha_provider in CSP_CAPTCHA_ORIGINS:
            extra = CSP_CAPTCHA_ORIGINS[captcha_provider]
            script_src += extra
            style_src += extra
            frame_src += extra
            connect_src += extra

        # The landing page reads the public pricing catalog straight from the
        # billing portal, so its origin joins connect-src only on a deployment
        # that has one. It also frames the portal's pricing grid, and frame-src
        # names that one page, not the portal: no other page may be framed.
        billing_origin = _origin_of(self.BILLING_URL) if self.BILLING_URL else None
        if billing_origin:
            connect_src.append(billing_origin)
            embed = _billing_embed_source(self.BILLING_URL)
            if embed:
                frame_src.append(embed)

        # The measurement collector, where one is named on another origin. A
        # same-origin path is already covered by 'self'.
        collector_origin = (
            _origin_of(self.FARO_COLLECTOR_URL) if self.FARO_COLLECTOR_URL else None
        )
        if collector_origin:
            connect_src.append(collector_origin)

        # Only the surface being opened. Already canonical origins by the time
        # they are stored on a registration, and re-reduced here so a value that
        # somehow carried a path cannot widen the directive.
        for candidate in plugin_frame_origins:
            origin = _origin_of(candidate) if candidate else None
            if origin:
                frame_src.append(origin)

        directives = {
            "default-src": ["'self'"],
            "script-src": script_src,
            "style-src": style_src,
            "font-src": font_src,
            "img-src": img_src,
            "connect-src": connect_src,
            "frame-src": frame_src,
            "worker-src": worker_src,
            "object-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
        }
        return _format_csp(directives)

    @property
    def wasm_worker_content_security_policy(self) -> str:
        """CSP for the WebAssembly worker bundles ONLY (applied per-response).

        Three workers run WebAssembly: the dashboard widget sandbox, which
        evaluates widget code with QuickJS
        (``frontend/src/lib/widgets/runtime/sandbox.worker.ts``); the direct
        message ratchet, which runs vodozemac
        (``frontend/src/crypto/ratchet.worker.ts``); and the PDF viewer's pdf.js
        worker, which decodes JBIG2, CCITT fax and JPEG 2000 images that way.
        A worker takes its policy from the response that served its script
        rather than from the document that started it, so the WebAssembly source
        expression is named here — on those built assets — and the app-wide
        policy above needs no mention of it.

        Each worker is given the three things it uses and nothing else: its own
        script, WebAssembly compilation, and a same-origin fetch for the
        ``.wasm`` file. None has a DOM, loads styles, images, or fonts, or
        talks to anybody but the page that started it.
        """
        return _format_csp(
            {
                "default-src": ["'none'"],
                "script-src": ["'self'", "'wasm-unsafe-eval'"],
                "connect-src": ["'self'"],
            }
        )

    @property
    def docs_content_security_policy(self) -> str:
        """Relaxed CSP for the Swagger docs pages ONLY (applied per-route).

        Swagger UI loads its bundle/stylesheet from jsDelivr and a Cloudflare
        beacon, which the app-wide ``script-src 'self'`` (pentest MED-001)
        rightly blocks. Rather than weaken the global policy, this scoped policy
        whitelists just those origins for the docs HTML response.

        ``script-src`` also needs ``'unsafe-inline'``: ``get_swagger_ui_html``
        boots the UI from an inline ``<script>`` (FastAPI provides no nonce, and
        a hash would break whenever the title/openapi_url change). ``connect-src``
        allows jsDelivr so the bundle's ``.map`` sourcemap fetch doesn't error;
        Try-It-Out still reaches the same-origin API via ``'self'``. This is
        confined to the docs pages — the rest of the app keeps
        ``script-src 'self'``, ``object-src 'none'``, and ``frame-ancestors
        'none'``.
        """
        return _format_csp(
            {
                "default-src": ["'self'"],
                "script-src": [
                    "'self'",
                    "'unsafe-inline'",
                    *CSP_SWAGGER_SCRIPT_ORIGINS,
                ],
                "style-src": ["'self'", "'unsafe-inline'", *CSP_SWAGGER_STYLE_ORIGINS],
                "img-src": ["'self'", "data:", "https:"],
                "font-src": ["'self'", "data:"],
                "connect-src": ["'self'", *CSP_SWAGGER_STYLE_ORIGINS],
                "worker-src": ["'self'", "blob:"],
                "object-src": ["'none'"],
                "base-uri": ["'self'"],
                # form-action does not fall back to default-src (CSP L2+), so set
                # it explicitly to match the global policy's lockdown.
                "form-action": ["'self'"],
                "frame-ancestors": ["'none'"],
            }
        )

    OIDC_ENABLED: bool = False
    OIDC_ISSUER: str | None = None
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    OIDC_PROVIDER_NAME: str | None = None
    OIDC_SCOPES: EnvList = Field(default_factory=lambda: list(DEFAULT_OIDC_SCOPES))
    # Which ways in the deployment permits, seeded into ``app_settings`` on
    # the first boot only — the same rule as the OIDC_* five above, and the
    # same owner afterwards: Settings -> Platform -> Authentication, which the
    # env never overwrites. Comma- or space-separated values of
    # ``app.core.login_methods.LoginMethod``; unset or blank keeps the app's
    # default.
    AUTH_LOGIN_METHODS: EnvList = Field(default_factory=list)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_SECURE: bool = False
    SMTP_REJECT_UNAUTHORIZED: bool = True
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_ADDRESS: str | None = None
    SMTP_TEST_RECIPIENT: str | None = None

    # FCM Push Notifications
    FCM_ENABLED: bool = False
    FCM_PROJECT_ID: str | None = None
    FCM_APPLICATION_ID: str | None = (
        None  # Android: 1:123:android:abc, iOS: 1:123:ios:def
    )
    FCM_API_KEY: str | None = None  # Firebase API key (public, safe to expose)
    FCM_SENDER_ID: str | None = None  # FCM sender ID (numeric)
    FCM_SERVICE_ACCOUNT_JSON: str | None = (
        None  # Service account for backend sending (private)
    )

    UPLOADS_DIR: str = "uploads"
    # Blob storage backend. "local" = filesystem under UPLOADS_DIR (FOSS/self-host/
    # dev default). "s3" = any S3-compatible object store (a self-hosted Garage
    # or MinIO instance, R2, etc.) — see the S3_* settings below.
    STORAGE_BACKEND: str = "local"
    # --- S3 / S3-compatible object storage (only used when STORAGE_BACKEND="s3") ---
    # Point at your own object store (e.g. a self-hosted Garage instance): set
    # S3_BUCKET + S3_ENDPOINT_URL + S3_REGION, S3_USE_PATH_STYLE=true (Garage and
    # most self-hosted stores), and the access/secret keys (or leave them unset to use
    # the ambient credential chain). See docs/en/running-a-server/object-storage.md.
    S3_BUCKET: str | None = None
    S3_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    S3_USE_PATH_STYLE: bool = False
    # Read only by migration 0137's one-time seed, which has shipped and cannot
    # change. Nothing at runtime reads it.
    S3_KMS_KEY_ID: str | None = None
    # Migration safety net: while cutting a deployment over from "local" to "s3",
    # set true so a read that misses in S3 falls back to the local filesystem
    # (serves blobs not yet copied by the backfill). Turn off once the backfill is
    # verified complete. Only consulted when STORAGE_BACKEND="s3".
    S3_LOCAL_FALLBACK: bool = False
    # Encrypt every object a community stores, in the app, under a key of the
    # community's own (app.services.storage_keys, app.core.storage_crypto).
    # Unset (the default): objects are stored as they arrive, as always.
    #   "local"    the community keys are wrapped under SECRET_KEY.
    #   "gcp_kms"  they are wrapped by the Cloud KMS key STORAGE_ENCRYPTION_KMS_KEY,
    #              which the app reaches as its own Google identity.
    # Deployment-level on purpose: nothing in the app's settings turns it off.
    # Objects stored before it was set stay readable, and a background pass
    # encrypts them; objects stored encrypted stay readable if it is unset again.
    STORAGE_ENCRYPTION: str = ""
    # projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>, for "gcp_kms".
    STORAGE_ENCRYPTION_KMS_KEY: str = ""

    # --- Marketplace ------------------------------------------------------
    # A directory of listing manifests (*.json) this deployment publishes as
    # its own. Mount a volume, drop files in, and they appear in the
    # marketplace alongside the ones this build ships — publishing needs no
    # change to the application. Scanned at boot and on demand from
    # Settings → Platform; a file that is removed retires its listing.
    # Unset (the default) means no directory is read and nothing is published
    # beyond the built-ins; any listing a directory published earlier is
    # withdrawn, as if the directory were empty.
    MARKETPLACE_EXTRA_CATALOG_DIR: str | None = None

    # --- Data export engine ---
    # The engine's own row, job and byte bounds are constants in
    # ``app.services.export.limits``; these are the deployment's choices.
    #
    # The line between an archive the app hands back over HTTP and one it
    # writes to the operator's destination. A download is served by this
    # process for as long as the client's connection lasts, so this is a bound
    # on how long one request may hold a worker, not on anything about size in
    # itself. Past it the archive is delivered instead.
    EXPORT_MAX_DOWNLOAD_BYTES: int = 2_147_483_648  # 2 GiB
    # Where a delivered archive is written: an absolute directory on this
    # host, which may be any mount the operator can write to. Unset (the
    # default) means delivery is not configured, and an archive over the
    # download bound is refused rather than produced with nowhere to go.
    EXPORT_DESTINATION_DIR: str | None = None
    # How long a community must wait between whole-community exports. The one
    # control that actually bounds what this costs a deployment: a community's
    # entire content is not a thing to re-read on a loop.
    EXPORT_GUILD_COOLDOWN_HOURS: int = 48
    # Hand a finished export's download off to the object store: the endpoint
    # redirects to a signed URL and the bytes travel from the store to the
    # client instead of through this process for the whole download.
    #
    # Off by default, and opt-in rather than automatic, because the browser
    # fetches the download with XHR: the bucket has to allow this app's origin
    # in its CORS rules for the redirected request to be readable. A
    # deployment that has not set that up would see downloads start failing
    # the moment it switched storage over. Filesystem storage signs nothing,
    # so this does nothing there whatever it is set to.
    EXPORT_PRESIGNED_DOWNLOADS: bool = False
    # First/bootstrap user — becomes the platform `owner` tier (there is no
    # superuser concept). The legacy FIRST_SUPERUSER_* env names are accepted
    # as aliases so existing deployments keep working.
    FIRST_OWNER_EMAIL: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FIRST_OWNER_EMAIL", "FIRST_SUPERUSER_EMAIL"),
    )
    FIRST_OWNER_PASSWORD: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "FIRST_OWNER_PASSWORD", "FIRST_SUPERUSER_PASSWORD"
        ),
    )
    DISABLE_GUILD_CREATION: bool = False
    # Runs this deployment as the product demo.
    DEMO_MODE: bool = False
    # Communities one account may create in a day; 0 means no limit. Accounts
    # holding ``communities.manage`` are not held to it.
    GUILD_CREATION_DAILY_LIMIT: int = Field(default=5, ge=0)
    # Boot back-fill normally skips guild schemas stamped with the current
    # provisioning-artifact version; set true to force a full sweep once.
    FORCE_GUILD_BACKFILL: bool = False
    ENABLE_PUBLIC_REGISTRATION: bool = (
        True  # When False, requires invite code to register
    )

    # Prefix for per-guild Postgres ROLE names (not schemas). Roles are
    # cluster-global, so a test suite sharing a cluster with a seeded dev DB would
    # collide on guild_<id> roles. The suite sets this to "test_" so its roles
    # (test_guild_<id>) are distinct; schemas are per-database and stay unprefixed.
    GUILD_ROLE_PREFIX: str = ""

    # Prefix for the platform-ladder Postgres ROLE names (platform_member …
    # platform_owner + platform_base). Like the guild roles these are
    # cluster-global, so the suite sets this to "test_" (test_platform_<tier>) to
    # avoid colliding with a co-located dev DB's unprefixed platform roles. The
    # creating migration and the routing role-name helper read the SAME setting,
    # so a SET ROLE always targets the role the migration actually created.
    PLATFORM_ROLE_PREFIX: str = ""

    # Optional captcha gate on the public registration endpoint to push
    # back on bot signups. ``CAPTCHA_PROVIDER`` selects the vendor —
    # ``"hcaptcha"`` / ``"turnstile"`` / ``"recaptcha"`` — and the SPA
    # picks the matching widget at runtime via ``GET /api/v1/config``.
    # ``CAPTCHA_SITE_KEY`` is the public key embedded in the widget;
    # ``CAPTCHA_SECRET_KEY`` is the server-side key used to call the
    # provider's siteverify endpoint. When any of the three is unset
    # (or ``CAPTCHA_PROVIDER`` is unrecognised) the check is silently
    # disabled — registrations work as before, no error, no widget.
    # The bootstrap first-user path skips the gate regardless (no bot
    # economics before any users exist).
    CAPTCHA_PROVIDER: str | None = None
    CAPTCHA_SITE_KEY: str | None = None
    CAPTCHA_SECRET_KEY: str | None = None
    # Optional frontend measurement: where the SPA sends page views, errors
    # and Web Vitals, in the Grafana Faro format (an Alloy ``faro.receiver``
    # speaks it). A same-origin path (``/collect``) or an absolute http(s)
    # URL. Unset (the default) ⇒ the SPA loads nothing and the cookie chooser
    # offers no analytics switch. Set ⇒ the chooser offers one, and only a
    # browser that switched it on sends anything.
    FARO_COLLECTOR_URL: str | None = None

    @field_validator("FARO_COLLECTOR_URL", mode="before")
    @classmethod
    def _validate_faro_collector_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        url = value.strip()
        if not url:
            return None
        parts = urlsplit(url)
        same_origin_path = url.startswith("/") and not url.startswith("//")
        absolute = parts.scheme in ("http", "https") and bool(parts.netloc)
        if not (same_origin_path or absolute):
            raise ValueError(
                "FARO_COLLECTOR_URL must be a path starting with / or an http(s) URL"
            )
        return url

    # Ed25519 private key (PEM) for signing handoff JWTs. Handoff tokens cross
    # a trust boundary — the receiving service verifies them with the matching
    # public key — so signing is always EdDSA and no secret is shared across
    # that boundary. Required by whichever handoff a deployment uses: unset, or
    # any other kind of key, and those mint endpoints fail closed (503).
    # Generate one with ``openssl genpkey -algorithm ed25519 -out private.pem``
    # and feed the PEM here.
    HANDOFF_SIGNING_PRIVATE_KEY_PEM: str | None = None
    # Key id stamped on the JWT header. The proprietary side reads ``kid``
    # to pick the right verifying key — useful when rotating.
    HANDOFF_SIGNING_KEY_ID: str | None = None

    # --- Plug-in platform (external plug-in services; default OFF) --------
    # A plug-in service is an external container this deployment has wired up
    # (see the plug-in service registry). Everything below is optional: a default
    # install generates its own signing key, and an owner wires plug-ins up from
    # the settings pages.
    #
    # Ed25519 private key (PEM) signing what Initiative sends a plug-in, EdDSA.
    # Optional: unset, Initiative generates one on first start and keeps it in
    # the database, encrypted under SECRET_KEY, so every replica signs with the
    # same key. Set it to supply your own (``openssl genpkey -algorithm ed25519
    # -out plugin-platform.pem``); while set it wins, and changing it is how the
    # key is rotated. Any other kind of key is refused when it is used.
    PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM: str | None = None
    # Key id stamped on the JWT header for the key above, so a plug-in picks it out
    # of the published JWKS during a rotation. A generated key uses its RFC 7638
    # thumbprint instead.
    PLUGIN_PLATFORM_SIGNING_KEY_ID: str | None = None
    # Path to a mounted JSON file (an array of entries) wiring plug-in services at
    # startup, with no owner clicks. An entry gives the plug-in's ``public_id`` and
    # this deployment's facts about it; what the plug-in is (its listing) comes
    # from the marketplace, and an entry naming a listing field is refused:
    #   [{"public_id": "acme.shopify",
    #     "base_url": "http://shopify:9100",
    #     "page_origin": "https://shopify.example.com",
    #     "jwks": {"keys": […]},
    #     "allowed_origins": ["https://shopify.example.com"],
    #     "vendor_env": {"client_secret": "SHOPIFY_CLIENT_SECRET"},
    #     "mandatory": false,
    #     "operations_only": false}]
    # ``base_url`` is where this server calls the plug-in, so it may be an address
    # only the container network resolves; ``page_origin`` is where a browser
    # loads its pages, omitted when the plug-in answers both at one address. Give
    # the plug-in's public keys as ``jwks``, or as ``jwks_uri`` when the plug-in serves
    # them at ``base_url``'s origin (``/.well-known/jwks.json`` for a plug-in built
    # on the SDK). ``vendor_env`` maps a vendor value to the environment
    # variable holding it, so the file names no secret and can be a plain
    # ConfigMap. ``operations_only`` offers the plug-in to the operations
    # community alone. An entry waits until its plug-in's listing
    # arrives. Unset (the default) ⇒ nothing is reconciled.
    # Reconciliation never re-enables a registration an operator disabled, and
    # never blocks boot.
    PLUGIN_SERVICES_CONFIG: str | None = None

    # --- Billing (hosted deployments only; default OFF) -------------------
    # Billing is an optional EXTERNAL service. Every BILLING_* setting below
    # is unset on a self-hosted install, and with them unset the app behaves
    # exactly as if billing did not exist: the /billing endpoints answer 503,
    # the membership ping is a no-op, and guild caps/status are governed
    # solely by what the operator sets (PATCH /settings/communities/{id}).
    #
    # Billing's requests to Initiative carry a signed envelope: a compact
    # EdDSA JWS that binds the method, the path and the body's hash, lives 60
    # seconds and is used once (``app.services.platform.billing_envelope``).
    # It's verified against this Ed25519 public key. Unset, the /billing
    # endpoints refuse every request.
    #
    # The key accepts more than one, as concatenated PEM blocks, so billing
    # can rotate its key without downtime: append the new key, let billing
    # start signing with it, then drop the old block.
    BILLING_PUBLIC_KEY_PEM: str | None = None
    # The key billing signs entitlement statements with: a different key from
    # the one above, so a request signed with the boundary key can't carry a
    # forged statement. Concatenated PEM blocks, as above. Required with
    # BILLING_PUBLIC_KEY_PEM.
    BILLING_STATEMENT_PUBLIC_KEY_PEM: str | None = None
    # Outbound base URL of the billing service: the ping that says the change
    # log moved, and the signed reads (plan summary, payment issue, uninstall
    # notice). Both are signed with HANDOFF_SIGNING_PRIVATE_KEY_PEM; with
    # either unset, nothing is sent.
    BILLING_SERVICE_URL: str | None = None
    # Public base URL of an external billing portal, surfaced to the SPA via
    # /config. Unset (the default) ⇒ the SPA shows NO tier label, upgrade, or
    # manage-billing UI; the usage panel still shows caps/usage (operator-set
    # numbers). Set ⇒ the link-out buttons appear: the OSS core defers to an
    # external service. Every handoff into it, the support and operator
    # consoles' included, is signed with HANDOFF_SIGNING_PRIVATE_KEY_PEM.
    BILLING_URL: str | None = None

    # --- Marketplace registry --------------------------------------------
    # The registry is a TUF repository of listings on a static host, verified
    # against a trusted root that ships in the image
    # (``app/marketplace/root.json``). Whether this deployment follows it is the
    # platform setting ``marketplace_registry_enabled`` (on by default), not an
    # environment variable.
    #
    # ``MARKETPLACE_REGISTRY_URL`` is the repository's base: its metadata is
    # read from ``<url>metadata/`` and its target files from ``<url>targets/``.
    # Point it at a mirror or a curated repository signed under the same root.
    #
    # ``MARKETPLACE_REGISTRY_ROOT`` is a path to a different trusted root, for a
    # repository signed under somebody else's keys. Listings and plug-ins from it
    # land as usual; a package's entitlement terms are honoured only under the
    # shipped root.
    MARKETPLACE_REGISTRY_URL: str = (
        "https://beyonders-studio.github.io/initiative-developer/public/"
    )
    MARKETPLACE_REGISTRY_ROOT: str | None = None
    # A bearer token sent with registry requests, for a registry that asks for
    # one. It goes only to the origin of ``MARKETPLACE_REGISTRY_URL``. Unset
    # (the default) sends none.
    MARKETPLACE_REGISTRY_TOKEN: str | None = None
    # How often the background refresh asks for new metadata. ~15 minutes keeps
    # a withdrawal reaching deployments promptly without polling a static host.
    MARKETPLACE_REGISTRY_TTL_SECONDS: int = Field(default=900, ge=60)
    # How many processes each server process may run to evaluate declarative
    # plug-ins' expressions at once. Started on first use; an idle one exits after
    # five minutes. A server process with more evaluations than this waits for
    # one to come free.
    EXPRESSION_WORKERS: int = Field(default=2, ge=1, le=16)

    # Local-dev only: when true, outbound webhook / custom-AI targets may
    # use http and resolve to private/loopback addresses, for round-tripping
    # with a locally run initiative-auto (its receiver at
    # ``http://localhost:8201``). Default false; production keeps the
    # https + public-address policy. The connection is pinned to the
    # resolved address regardless of this setting.
    WEBHOOK_ALLOW_PRIVATE_TARGETS: bool = False

    BEHIND_PROXY: bool = (
        False  # Set True when behind nginx/load balancer to trust X-Forwarded-For
    )

    # The request header a trusted proxy in front of the deployment writes the
    # client's country into, as an ISO 3166-1 alpha-2 code — ``CF-IPCountry``
    # behind Cloudflare. Read to apply a plug-in's minimum age for where
    # somebody is; never stored. Unset (the default), or a value that is not a
    # country, means "not known", and a plug-in's highest declared age applies.
    # Only set it when every request reaches the app through that proxy.
    CLIENT_COUNTRY_HEADER: str | None = None

    # Global per-client default rate limit applied (via SlowAPIMiddleware) to
    # every route that lacks its own ``@limiter.limit(...)`` decorator. Uses the
    # slowapi/limits string syntax (e.g. ``"100/minute"``, or
    # ``"200/minute;2000/hour"`` for several windows). Set to an empty string to
    # turn the global default off entirely — per-route decorated limits still
    # apply. The test suite sets ``limiter.enabled = False`` so this never
    # throttles the hundreds of rapid requests a test makes from one client IP.
    RATE_LIMIT_DEFAULT: str = "100/minute"
    # Master on/off switch for ALL rate limiting — the global default *and* every
    # per-route ``@limiter.limit(...)`` cap (e.g. password reset's ``5/15minutes``). Leave
    # True in any shared/production environment; set ``RATE_LIMIT_ENABLED=false``
    # in a local ``.env`` to stop throttling yourself while testing auth flows.
    # This is the same lever the test suite pulls (``limiter.enabled = False``),
    # surfaced as config; it is evaluated at startup, not per request.
    RATE_LIMIT_ENABLED: bool = True
    # Where rate-limit counters are kept. ``memory://`` (the default) counts in
    # each process, so every process holds its own allowance. A ``redis://``,
    # ``rediss://``, ``redis+sentinel://`` or ``redis+cluster://`` URI shares
    # one count across processes. While that storage cannot be reached, each
    # process counts in memory until it answers again (``rate_limit.build_limiter``).
    RATE_LIMIT_STORAGE_URI: str = "memory://"

    # How much the application says about itself on stderr: one of the
    # standard Python level names (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    # The audit stream on stdout is not governed by this; it always emits.
    LOG_LEVEL: str = "INFO"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level == "NOTSET" or level not in logging.getLevelNamesMapping():
            raise ValueError(
                "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL; "
                f"got {value!r}"
            )
        return level

    # The bearer token a Prometheus scrape presents to read
    # ``{API_V1_STR}/metrics``. Unset (the default), that route answers 404.
    METRICS_TOKEN: str | None = None

    @field_validator("METRICS_TOKEN", mode="before")
    @classmethod
    def _blank_metrics_token_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    # Mount the in-app MCP server at ``/api/v1/mcp/`` (route-backed). Off by
    # default; enable per-environment via env / .env. Tools ride the real auth +
    # RLS rails, so a caller only ever sees their own data, and a read-only API
    # key can't write.
    ENABLE_MCP: bool = False

    # Reject passwords that appear in the HaveIBeenPwned breach corpus
    # when a user sets one (registration, reset, change). Uses the
    # k-anonymity API — only the first 5 hex chars of the SHA-1 hash
    # leave the server. Flip to ``False`` to disable the check (e.g.
    # in air-gapped deployments or when egress is blocked); the length
    # floor in ``app.core.password_policy`` still applies.
    HIBP_CHECK_ENABLED: bool = True

    @field_validator("OIDC_SCOPES", mode="before")
    @classmethod
    def _blank_oidc_scopes_are_the_default(cls, value: object) -> object:
        """A blank value reads as unset: the default scope list."""
        if isinstance(value, str) and not value.strip():
            return list(DEFAULT_OIDC_SCOPES)
        return value

    @field_validator("OIDC_SCOPES")
    @classmethod
    def _scopeless_oidc_scopes_ask_for_the_basics(cls, value: list[str]) -> list[str]:
        """A value that names no scope asks for the sign-in basics alone."""
        return value or ["openid", "profile", "email"]

    @field_validator("AUTH_LOGIN_METHODS")
    @classmethod
    def _login_methods_in_lower_case(cls, value: list[str]) -> list[str]:
        """Lower case, the shape the seed compares against ``LoginMethod``."""
        return list(dict.fromkeys(item.lower() for item in value))


@lru_cache
# Use caching to avoid re-reading the env file over and over
# (FastAPI startup imports Config many times).
def get_settings() -> Settings:
    # The required field (SECRET_KEY) is loaded from the environment by
    # pydantic-settings, which ty can't see.
    return Settings()  # ty: ignore[missing-argument]


settings = get_settings()
