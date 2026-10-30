from typing import Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PGEnum, JSONB
from sqlmodel import Enum as SQLEnum, Field, SQLModel
from pydantic import ConfigDict

from app.core.login_methods import (
    DEFAULT_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
)
from app.models.platform.user_dm_settings import DmPolicy

# Platform OIDC config lives on the provider registry row (``auth_providers``
# slug ``oidc``), not here. Which ways in the deployment permits does — see
# ``login_methods`` below and ``app.services.platform.auth_posture``.


#: ``DEFAULT_LOGIN_METHODS`` as Postgres writes an array literal, so the set is
#: stated once rather than here and in ``login_methods`` below. The migrations
#: that moved this default keep their own copies: a migration is the record of
#: what changed when, and is not read for what the default is now.
_DEFAULT_LOGIN_METHODS_SQL = "{%s}" % ",".join(m.value for m in DEFAULT_LOGIN_METHODS)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(default=1, primary_key=True)

    light_accent_color: str = Field(
        default="#2563eb",
        sa_column=Column(String(20), nullable=False, server_default="#2563eb"),
    )
    dark_accent_color: str = Field(
        default="#60a5fa",
        sa_column=Column(String(20), nullable=False, server_default="#60a5fa"),
    )

    # What this deployment is running, and what it was running before that.
    # A notice that only matters to somebody upgrading past a given release has
    # no way to know that from a publication date — a fresh install of 0.70 was
    # never on 0.64. The pair is rolled forward at boot: when the running
    # version differs from ``last_seen_version``, the old value becomes
    # ``previous_version``. Both are NULL on a fresh install, which is exactly
    # what "never upgraded from anything" looks like.
    last_seen_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    previous_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    # When this deployment first booted with each change in
    # ``app.core.transitions``, by name, as an ISO timestamp.
    transitions: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )

    # Which ways in this deployment permits. A Postgres enum array: adding a
    # method later is a value on the type, not a column per method, and the
    # database validates the elements rather than a hand-kept CHECK list. The
    # non-empty constraint is the "at least one" rule — see
    # ``app.core.login_methods``.
    login_methods: list[str] = Field(
        default_factory=lambda: [m.value for m in DEFAULT_LOGIN_METHODS],
        sa_column=Column(
            ARRAY(PGEnum(LoginMethod, name="login_method", create_type=False)),
            nullable=False,
            server_default=_DEFAULT_LOGIN_METHODS_SQL,
        ),
    )

    # Who this deployment asks to hold a second factor. A Postgres enum for
    # the same reason ``login_methods`` is one: the database validates the
    # value, and a rung added later is a value on the type rather than a
    # column here. ``nobody`` on every fresh and upgraded install, so an
    # upgrade asks nothing of anybody it was not already asking.
    #
    # What answers it is the account holding one — a confirmed authenticator
    # or a registered passkey — or a session that presented one, which is what
    # an identity provider's own second factor looks like from here. The
    # per-session reading is a community's question (``require_methods``);
    # this one is about the account.
    second_factor_requirement: SecondFactorRequirement = Field(
        default=SecondFactorRequirement.nobody,
        sa_column=Column(
            PGEnum(
                SecondFactorRequirement,
                name="second_factor_requirement",
                create_type=False,
            ),
            nullable=False,
            server_default=SecondFactorRequirement.nobody.value,
        ),
    )

    smtp_host: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_port: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    smtp_secure: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    smtp_reject_unauthorized: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    smtp_username: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    # The SMTP password lives on ``app_setting_secrets``.
    smtp_from_address: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_test_recipient: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )

    # Whether this deployment runs as the demo (``DEMO_MODE``), written from
    # the environment at every boot. Only here may a guest membership carry a
    # rung above ``guest``.
    demo_mode: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # The direct-message policy a newly created account starts on. Read once,
    # when the account is created, and copied into its ``user_dm_settings`` row;
    # changing it later moves nobody, so raising it opens no existing account
    # and lowering it revokes no channel anybody is using.
    default_dm_policy: DmPolicy = Field(
        default=DmPolicy.private,
        sa_column=Column(
            SQLEnum(DmPolicy, name="user_dm_policy", create_type=False),
            nullable=False,
            server_default=DmPolicy.private.value,
        ),
    )

    # AI config ownership mode: "platform" (the operator's connections apply to
    # every guild), "guild" (each guild admin configures its own), or "disabled".
    # Provider config itself lives in platform_ai_connections /
    # guild_ai_connections; only the global mode lives here.
    ai_config_mode: str = Field(
        default="disabled",
        sa_column=Column(String(20), nullable=False, server_default="disabled"),
    )
    # Monotonic counter bumped on every operator AI-config write (mode or
    # platform connection). Read on the request's own (guild) session as the
    # cross-worker cache-freshness signal, so a change is picked up by every
    # replica at once instead of after a per-process TTL.
    ai_config_version: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    # Object storage (blob backend). "local" = filesystem under UPLOADS_DIR;
    # "s3" = any S3-compatible store. Seeded from the STORAGE_BACKEND / S3_* env
    # vars on first creation, then DB-authoritative (see app_settings service).
    storage_backend: str = Field(
        default="local",
        sa_column=Column(String(20), nullable=False, server_default="local"),
    )
    s3_bucket: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    s3_region: str = Field(
        default="us-east-1",
        sa_column=Column(String(64), nullable=False, server_default="us-east-1"),
    )
    s3_endpoint_url: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    s3_access_key_id: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    # The S3 secret access key lives on ``app_setting_secrets``.
    s3_use_path_style: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    s3_local_fallback: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # ── captcha ────────────────────────────────────────────────────────
    # The registration captcha, moved off env-only configuration in 0368. The
    # provider name and site key are public — the site key is rendered into the
    # page — so they sit here; the secret that verifies a token is on
    # ``app_setting_secrets``. Enforcement needs all three, which is what
    # ``app.services.captcha_config`` resolves.
    captcha_provider: Optional[str] = Field(
        default=None, sa_column=Column(String(50), nullable=True)
    )
    captcha_site_key: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )

    # ── push notifications (FCM) ───────────────────────────────────────
    # Same move, same split. Everything here reaches a device or a page; the
    # service-account JSON that mints an access token does not, and is on
    # ``app_setting_secrets``.
    fcm_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    fcm_project_id: Optional[str] = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    fcm_application_id: Optional[str] = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    # Firebase's API key is public by design (it ships in the client).
    fcm_api_key: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    fcm_sender_id: Optional[str] = Field(
        default=None, sa_column=Column(String(50), nullable=True)
    )

    # The guild that receives this deployment's operations work — security,
    # moderation, support and feedback cases. NULL on every fresh and existing
    # install, which is what "this deployment routes nothing" looks like: the
    # writer resolves no binding and every call it makes is a no-op.
    #
    # An ordinary guild in every other respect. Which project each stream lands
    # in is per-guild config inside it (``intake_bindings``), so the platform
    # holds a pointer and no second copy of the tooling.
    operations_guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="SET NULL"), nullable=True
        ),
    )

    # Who somebody is told to contact about operations work, set on the
    # owner's intake settings page. One catch-all address for the deployment,
    # and one optional address per intake stream keyed by its value; a stream
    # with none of its own falls back to the catch-all and never to another
    # stream (``app.services.platform.intake.contact_for``). Independent of the
    # operations guild: a deployment that routes nothing can still say who to
    # write to.
    intake_general_contact: Optional[str] = Field(
        default=None, sa_column=Column(String(320), nullable=True)
    )
    intake_contacts: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
