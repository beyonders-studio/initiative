import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    CommunityIdPath,
    get_current_active_user,
    UserSessionDep,
    SystemSessionDep,
)
from app.api.v1.platform_endpoints.access_grants import check_second_factor
from app.api.v1.platform_endpoints.operator import (
    BillingContractsDep,
    BillingControlDep,
    BillingDirectoryDep,
    BillingInsightsDep,
    CommunitiesReadDep,
    CommunitiesSuspendDep,
    ConfigManageDep,
    GuildsManageDep,
)
from app.api.v1.platform_endpoints.session_opening import MOBILE_CALLBACK_URI
from app.core.audit_events import AuditEventType
from app.core.config import DEFAULT_OIDC_SCOPES
from app.core.config import settings as app_config
from app.core.intake import IntakeStream
from app.core.rules import (
    OPTION_RULES,
    RETENTION_WINDOWS,
    SURFACE_AI_CONNECTIONS,
    SURFACE_CUSTOM_ROLES,
    SURFACE_PLUGINS,
)
from app.db import cohorts
from app.db.query import build_paginated_response, paginated_query
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.app_setting_secret import AppSettingSecret
from app.models.platform.guild import (
    Guild,
    GuildMembership,
    CommunityRole,
)
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.identity_ref import IdentityEntity
from app.schemas.platform.settings import (
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
    CommunityNarrowingAgreement,
    CommunityNarrowingPending,
    CommunitySettingsResponse,
    CommunitySettingsUpdate,
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailTestRequest,
    EmailTestResponse,
    InterfaceSettingsResponse,
    InterfaceSettingsUpdate,
    LoginMethodStatus,
    AccountsWithoutFactor,
    OIDCSettingsResponse,
    PlatformAuthSettingsResponse,
    PlatformAuthSettingsUpdate,
    StorageBackfillStatusResponse,
    CaptchaSettingsResponse,
    CaptchaSettingsUpdate,
    PushSettingsResponse,
    PushSettingsUpdate,
    StorageSettingsResponse,
    StorageSettingsUpdate,
    StorageTestResponse,
)
from app.models.platform.guild import CommunityStatus, operator_status_choices
from app.schemas.platform.guild import (
    CommunityAction,
    CommunitySuspensionUpdate,
    PlatformCommunityRestore,
    PlatformCommunityStorageListResponse,
    PlatformCommunityStorageRead,
    PlatformCommunityStorageUpdate,
)
from app.core.capabilities import Capability, user_has_capability
from app.core.clock import utcnow
from app.models.platform.access_grant import (
    AccessGrant,
    AccessGrantPurpose,
    AccessLevel,
)
from app.models.platform.user import User
from app.schemas.platform.access_grant import BreakGlassCreate, SecondFactorAnswer
from app.schemas.platform.billing import BillingPortalHandoffResponse
from app.schemas.platform.push import FCMConfigResponse
from app.schemas.tenant.plugin_data import PluginDataResponse, PluginSummaryListResponse
from app.core.messages import (
    AuthMessages,
    BillingMessages,
    GuildMessages,
    SettingsMessages,
)
from app.core.security import (
    BillingSupportHandoffNotConfiguredError,
    HandoffSigningNotConfiguredError,
    create_billing_contracts_handoff_token,
    create_billing_control_handoff_token,
    create_billing_directory_handoff_token,
    create_billing_insights_handoff_token,
    create_billing_support_handoff_token,
)
from app.services.platform.identity_refs import billing_ref, billing_refs
from app.services.platform import access_grants as access_grants_service
from app.services.auth import narrowing_review
from app.services.marketplace import plugin_data as plugin_data_service
from app.services.auth import platform_provider as platform_provider_service
from app.services.auth import provider_registry
from app.core.login_methods import (
    FACTOR_METHODS,
    PRIMARY_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
)
from app.services.platform import auth_posture, rules
from app.services.platform import app_settings as app_settings_service
from app.services.platform import push_config, push_relay
from app.services import captcha as captcha_service
from app.services.captcha_config import ResolvedCaptchaConfig
from app.services.platform import billing as billing_service
from app.services.platform.retention import (
    ACCOUNT_DELETION,
    COMMUNITY_DELETION,
    COMMUNITY_HOLD,
)
from app.services.platform import guilds as guilds_service
from app.services.platform import case_activity, grant_cases
from app.core.user_display import handle_of
from app.services.platform.intake import stream_is_bound
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import storage_backfill, storage_config

logger = logging.getLogger(__name__)

# Reason stamped on a grant self-issued by the Guilds tab's billing button.
BILLING_PORTAL_GRANT_REASON = "Opened the billing portal from the Guilds tab"


router = APIRouter()


def _email_settings_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> EmailSettingsResponse:
    return EmailSettingsResponse(
        host=settings_obj.smtp_host,
        port=settings_obj.smtp_port,
        secure=settings_obj.smtp_secure,
        reject_unauthorized=settings_obj.smtp_reject_unauthorized,
        username=settings_obj.smtp_username,
        has_password=bool(secrets.smtp_password_encrypted),
        from_address=settings_obj.smtp_from_address,
        test_recipient=settings_obj.smtp_test_recipient,
    )


def _platform_oidc_response(provider) -> OIDCSettingsResponse:
    """The redirect addresses that belong to the install rather than to any one
    provider.

    The provider fields are the platform row's, kept for readers that have not
    moved to the registry; a provider is configured through
    ``/settings/auth/providers``, which is the only place that writes one."""
    return OIDCSettingsResponse(
        enabled=provider.enabled if provider else False,
        issuer=provider.issuer if provider else None,
        client_id=provider.client_id if provider else None,
        redirect_uri=provider_registry.provider_callback_url(
            platform_provider_service.PLATFORM_OIDC_SLUG
        ),
        post_login_redirect=provider_registry.frontend_callback_url(),
        mobile_redirect_uri=MOBILE_CALLBACK_URI,
        provider_name=provider.display_name if provider else None,
        scopes=platform_provider_service.scopes_list(provider)
        if provider
        else list(DEFAULT_OIDC_SCOPES),
    )


@router.get("/auth", response_model=OIDCSettingsResponse)
async def get_oidc_settings(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> OIDCSettingsResponse:
    """The install's redirect addresses. System engine: ``auth_providers``
    carries no request-path grant; the capability gate stays
    ``config.manage``."""
    provider = await platform_provider_service.get_platform_provider(session)
    return _platform_oidc_response(provider)


async def _platform_auth_payload(session) -> PlatformAuthSettingsResponse:
    """The permitted ways in, and what withdrawing one would cost.

    The counts are computed on every read so the page can state the
    consequence before the write instead of after a refusal — and so the figure
    an operator acknowledges is one the page actually showed them.
    """
    stored = await rules.platform_values(session)
    permitted = stored["login_methods"]
    stranding, without_factor = await auth_posture.account_figures(
        session, permitted=permitted
    )
    return PlatformAuthSettingsResponse(
        methods=[
            LoginMethodStatus(
                method=method,
                enabled=method in permitted,
                primary=method in PRIMARY_LOGIN_METHODS,
                answers_factor=method in FACTOR_METHODS,
                would_strand=stranding[method],
            )
            for method in LoginMethod
        ],
        communities_requiring_sign_in=await auth_posture.guilds_requiring_sign_in(
            session
        ),
        factor_methods_permitted=bool(permitted.intersection(FACTOR_METHODS)),
        session_max_hours=stored["session_max_hours"],
        session_idle_minutes=stored["session_idle_minutes"],
        second_factor_requirement=stored["second_factor_requirement"],
        breached_password_check_enabled=stored["breached_password_check_enabled"],
        accounts_without_factor=AccountsWithoutFactor(
            platform_roles=without_factor[SecondFactorRequirement.platform_roles],
            everyone=without_factor[SecondFactorRequirement.everyone],
        ),
    )


@router.get("/auth/platform", response_model=PlatformAuthSettingsResponse)
async def get_platform_auth_settings(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> PlatformAuthSettingsResponse:
    """Which ways in are permitted. System engine: the guard counts read
    ``auth_providers`` and ``federated_identities``, neither of which carries a
    request-path grant."""
    return await _platform_auth_payload(session)


@router.patch("/auth/platform", response_model=PlatformAuthSettingsResponse)
async def update_platform_auth_settings(
    payload: PlatformAuthSettingsUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> PlatformAuthSettingsResponse:
    """Change how somebody reaches this deployment: the ways in it permits,
    who it asks for a second factor, and how long a session lasts.

    Loosening a rule is never refused. Tightening one is refused when the
    deployment permits nothing that could answer it (409), and when the
    account writing it does not meet it itself (400, naming the unmet
    method). Withdrawing a way in that is somebody's only one is refused (409)
    with the count in ``X-Affected-Count``, and proceeds only when the caller
    echoes that exact number back in ``acknowledge_stranded``.

    Nobody is signed out. A session already open keeps the terms it was
    opened under.
    """
    changes: dict[str, object] = {
        key: getattr(payload, key)
        for key in ("session_max_hours", "session_idle_minutes")
        if key in payload.model_fields_set
    }
    if payload.breached_password_check_enabled is not None:
        changes["breached_password_check_enabled"] = (
            payload.breached_password_check_enabled
        )
    if payload.methods is not None:
        changes["login_methods"] = frozenset(payload.methods)
    if payload.second_factor_requirement is not None:
        changes["second_factor_requirement"] = payload.second_factor_requirement
    await auth_posture.change(
        auth_posture.RuleContext.platform(
            session, owner, acknowledge_stranded=payload.acknowledge_stranded
        ),
        changes,
    )
    return await _platform_auth_payload(session)


async def _notification_payload(session) -> NotificationSettingsResponse:
    stored = await rules.platform_values(session)
    return NotificationSettingsResponse(
        push_notifications_enabled=stored["push_notifications_enabled"],
        email_notifications_enabled=stored["email_notifications_enabled"],
        redact_notification_content=stored["redact_notification_content"],
    )


@router.get("/notifications", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> NotificationSettingsResponse:
    """What this deployment permits a notification to leave the app carrying."""
    return await _notification_payload(session)


@router.put("/notifications", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> NotificationSettingsResponse:
    """Decide what this deployment permits a notification to leave the app with.

    Every community is held to this as a ceiling: one may decline a channel the
    deployment permits, and none may take back one the deployment has declined.

    Switching push off drops the push tokens this deployment was holding, and
    the registration endpoint declines while it stays off — so the deployment
    stops sending and stops keeping the addresses it was sending to. Devices
    register again the next time the app starts, which is what restores
    delivery when it is switched back on.

    Switching email off stops notification email and nothing else: a sign-in
    code, an address to confirm, a password reset and the notices an account
    gets about itself keep going, because this must not lock anybody out of
    their account.
    """
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner),
        {
            "push_notifications_enabled": payload.push_notifications_enabled,
            "email_notifications_enabled": payload.email_notifications_enabled,
            "redact_notification_content": payload.redact_notification_content,
        },
    )
    return await _notification_payload(session)


@router.put("/interface", response_model=InterfaceSettingsResponse)
async def update_interface_settings(
    payload: InterfaceSettingsUpdate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> InterfaceSettingsResponse:
    """The accent colours, and whether arriving visitors are asked about
    cookies. ``cookie_consent_enabled`` is left alone when omitted, so saving a
    colour does not silently answer it."""
    await app_settings_service.update_interface_settings(
        session,
        light_accent_color=payload.light_accent_color,
        dark_accent_color=payload.dark_accent_color,
        actor_user_id=owner.id,
    )
    changes: dict[str, object] = {}
    if payload.cookie_consent_enabled is not None:
        changes["cookie_consent_enabled"] = payload.cookie_consent_enabled
    # Commits the colours with the rule.
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner), changes
    )
    settings_obj = await app_settings_service.get_app_settings(session)
    return InterfaceSettingsResponse(
        light_accent_color=settings_obj.light_accent_color,
        dark_accent_color=settings_obj.dark_accent_color,
        cookie_consent_enabled=(await rules.platform_values(session))[
            "cookie_consent_enabled"
        ],
    )


#: The community page's switches and limits that are left alone when omitted,
#: by field and the rule each writes.
_COMMUNITY_RULE_FIELDS = (
    ("age_gate_enabled", "community_age_gate_enabled"),
    ("default_dm_policy", "default_dm_policy"),
    ("direct_messages_enabled", "direct_messages_enabled"),
    ("engagement_ranking_enabled", "engagement_ranking_enabled"),
    ("guests_enabled", "guests_enabled"),
    ("max_guest_days", "max_guest_days"),
    ("public_registration_enabled", "public_registration_enabled"),
    ("community_creation_enabled", "community_creation_enabled"),
    ("community_creation_daily_limit", "community_creation_daily_limit"),
    ("community_export_cooldown_hours", "community_export_cooldown_hours"),
)


async def _community_payload(session: AsyncSession) -> CommunitySettingsResponse:
    stored = await rules.platform_values(session)
    return CommunitySettingsResponse(
        community_directory_enabled=stored["community_directory_enabled"],
        age_gate_enabled=stored["community_age_gate_enabled"],
        default_dm_policy=stored["default_dm_policy"],
        direct_messages_enabled=stored["direct_messages_enabled"],
        deleted_community_retention_days=COMMUNITY_DELETION.days(stored),
        deleted_account_retention_days=ACCOUNT_DELETION.days(stored),
        on_hold_community_deletion_days=COMMUNITY_HOLD.days(stored),
        engagement_ranking_enabled=stored["engagement_ranking_enabled"],
        guests_enabled=stored["guests_enabled"],
        max_guest_days=stored["max_guest_days"],
        public_registration_enabled=stored["public_registration_enabled"],
        community_creation_enabled=stored["community_creation_enabled"],
        community_creation_daily_limit=stored["community_creation_daily_limit"],
        community_export_cooldown_hours=stored["community_export_cooldown_hours"],
    )


@router.get("/community", response_model=CommunitySettingsResponse)
async def read_community_settings(
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> CommunitySettingsResponse:
    """The community-wide decisions, for the owner's settings page.

    Three of them are also on ``GET /config``, which is where every signed-in
    page reads them. ``default_dm_policy`` is not: nothing in the SPA acts on it
    — the server applies it when an account is made — so it is served here,
    behind the capability that writes it, rather than added to everyone's boot
    payload.
    """
    return await _community_payload(session)


@router.put("/community", response_model=CommunitySettingsResponse)
async def update_community_settings(
    payload: CommunitySettingsUpdate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> CommunitySettingsResponse:
    """Turn the community directory on or off for the whole deployment.

    Write-only on purpose: the current value is public — every signed-in page
    needs it to decide whether to offer the directory — so it is served from
    ``GET /config`` with the rest of the SPA's boot configuration rather than
    from a second, capability-gated read of the same boolean.

    Switching it off hides the directory and refuses new listings; it does not
    clear the opt-in a guild already made, so switching it back on restores the
    same set of listed guilds.

    ``default_dm_policy`` is the third decision here and behaves like the
    second: omitted, it is left alone. It is the policy a newly created account
    starts on, and changing it moves no existing account.

    ``age_gate_enabled`` is the second switch: whether an account must confirm
    it belongs to somebody 16 or older before it takes a place in a listed
    guild. That join is all it gates; an invited guild asks nobody's age. Turning it off is the owner asserting that every account on this
    deployment already belongs to an adult, which is why it is a deliberate
    write and not a side effect of the first — omitting it leaves it alone.

    ``direct_messages_enabled`` is the fourth, and independent of the other
    three: a deployment can run a directory without messaging, or messaging
    without a directory. Off, My Messages is not offered and every
    direct-message route refuses; nothing is deleted, so turning it back on
    restores the channels people already had.

    ``deleted_community_retention_days`` is the fifth: how long a deleted
    community is kept before it is destroyed. ``null`` means never, which is
    the answer for a deployment that has undertaken to keep what its members
    put in it, so this field reads its presence rather than its value — omit it
    to leave the window alone. The figure is the deployment's; a community has
    no say in its own.

    ``on_hold_community_deletion_days`` reads the same way: how long a
    community stays on hold before it is deleted, and ``null`` for never.

    ``engagement_ranking_enabled`` says whether search may order any
    community's content by how many members engaged with it lately. Each
    community is asked too, and off wins. Omitted, it is left alone.

    ``guests_enabled`` lets communities have guests, and ``max_guest_days`` is
    the longest one may stay. Off, no guest reaches anything until it is back
    on. Omitted, each is left alone.
    """
    changes: dict[str, object] = {
        "community_directory_enabled": payload.community_directory_enabled
    }
    for field, key in _COMMUNITY_RULE_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            changes[key] = value
    for key, switch in RETENTION_WINDOWS.items():
        if key in payload.model_fields_set:
            days = getattr(payload, key)
            changes[switch] = days is not None
            if days is not None:
                changes[key] = days
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner), changes
    )
    return await _community_payload(session)


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> EmailSettingsResponse:
    # Whether a password is stored is read on the system engine, which alone
    # holds app_setting_secrets.
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _email_settings_payload(settings_obj, secrets)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    payload: EmailSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> EmailSettingsResponse:
    # The settings row is written under the owner's tier; the password, when
    # one is sent, on the system engine.
    data = payload.model_dump(exclude_unset=True)
    password_provided = "password" in data
    updated, secrets = await app_settings_service.update_email_settings(
        session,
        system_session=system_session,
        host=payload.host,
        port=payload.port,
        secure=payload.secure,
        reject_unauthorized=payload.reject_unauthorized,
        username=payload.username,
        password=payload.password,
        password_provided=password_provided,
        from_address=payload.from_address,
        test_recipient=payload.test_recipient,
        actor_user_id=owner.id,
    )
    return _email_settings_payload(updated, secrets)


@router.post("/email/test")
async def send_test_email(
    payload: EmailTestRequest,
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> EmailTestResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    recipient = payload.recipient or settings_obj.smtp_test_recipient
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.PROVIDE_TEST_EMAIL,
        )
    try:
        await email_service.send_test_email(session, recipient)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE,
        ) from None
    except RuntimeError as exc:
        # The send records the failure's type and SMTP reply code; the response
        # carries only a machine-readable code.
        logger.warning("Test email delivery failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SettingsMessages.EMAIL_SEND_FAILED,
        ) from exc
    return EmailTestResponse(status="sent")


# --- Object storage ---


def _storage_settings_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> StorageSettingsResponse:
    backend = (settings_obj.storage_backend or "local").lower()
    return StorageSettingsResponse(
        backend="s3" if backend == "s3" else "local",
        s3_bucket=settings_obj.s3_bucket,
        s3_region=settings_obj.s3_region or "us-east-1",
        s3_endpoint_url=settings_obj.s3_endpoint_url,
        s3_access_key_id=settings_obj.s3_access_key_id,
        has_secret_access_key=bool(secrets.s3_secret_access_key_encrypted),
        s3_use_path_style=settings_obj.s3_use_path_style,
        s3_local_fallback=settings_obj.s3_local_fallback,
    )


@router.get("/storage", response_model=StorageSettingsResponse)
async def get_storage_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> StorageSettingsResponse:
    # Whether a secret key is stored is read on the system engine, which alone
    # holds app_setting_secrets.
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _storage_settings_payload(settings_obj, secrets)


@router.put("/storage", response_model=StorageSettingsResponse)
async def update_storage_settings(
    payload: StorageSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> StorageSettingsResponse:
    # The settings row is written under the owner's tier; the secret key, when
    # one is sent, on the system engine.
    data = payload.model_dump(exclude_unset=True)
    secret_provided = "s3_secret_access_key" in data
    updated, secrets = await app_settings_service.update_storage_settings(
        session,
        system_session=system_session,
        backend=payload.backend,
        s3_bucket=payload.s3_bucket,
        s3_region=payload.s3_region,
        s3_endpoint_url=payload.s3_endpoint_url,
        s3_access_key_id=payload.s3_access_key_id,
        s3_secret_access_key=payload.s3_secret_access_key,
        secret_provided=secret_provided,
        s3_use_path_style=payload.s3_use_path_style,
        s3_local_fallback=payload.s3_local_fallback,
        actor_user_id=owner.id,
    )
    return _storage_settings_payload(updated, secrets)


@router.post("/storage/test", response_model=StorageTestResponse)
async def test_storage_connection(
    payload: StorageSettingsUpdate,
    _owner: ConfigManageDep,
) -> StorageTestResponse:
    # Test the submitted (possibly unsaved) config. If the owner left the secret
    # blank, fall back to the saved one so they can re-test without re-typing it
    # (read on the system engine, which alone holds app_setting_secrets).
    data = payload.model_dump(exclude_unset=True)
    secret = payload.s3_secret_access_key
    if "s3_secret_access_key" not in data or not secret:
        secret = await storage_config.resolve_saved_secret()
    candidate = storage_config.ResolvedStorageConfig(
        backend="s3" if payload.backend == "s3" else "local",
        bucket=(payload.s3_bucket or "").strip() or None,
        region=(payload.s3_region or "us-east-1").strip() or "us-east-1",
        endpoint_url=(payload.s3_endpoint_url or "").strip() or None,
        access_key_id=(payload.s3_access_key_id or "").strip() or None,
        secret_access_key=secret,
        use_path_style=bool(payload.s3_use_path_style),
        local_fallback=bool(payload.s3_local_fallback),
    )
    ok, message = await storage_config.test_connection(candidate)
    return StorageTestResponse(success=ok, message=message)


def _backfill_payload(row: dict) -> StorageBackfillStatusResponse:
    started = row.get("started_at")
    finished = row.get("finished_at")
    return StorageBackfillStatusResponse(
        status=row["status"],
        copied=row["copied"],
        skipped=row["skipped"],
        failed=row["failed"],
        hash_mismatches=row["hash_mismatches"],
        failed_keys=list(row.get("failed_keys") or []),
        started_at=started.isoformat() if started else None,
        finished_at=finished.isoformat() if finished else None,
        error=row.get("error"),
    )


@router.post("/storage/backfill", response_model=StorageBackfillStatusResponse)
async def start_storage_backfill(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> StorageBackfillStatusResponse:
    # The backfill writes to S3 via the saved credentials, so they must be set
    # (the documented flow runs it while still serving on "local").
    settings_obj = await app_settings_service.get_app_settings(session)
    if not settings_obj.s3_bucket:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.STORAGE_BACKFILL_NOT_CONFIGURED,
        )
    # Make sure the detached task resolves the freshly-saved S3 credentials.
    await storage_config.refresh_storage_config(session)
    try:
        row = await storage_backfill.start_backfill(session)
    except storage_backfill.BackfillAlreadyRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SettingsMessages.STORAGE_BACKFILL_RUNNING,
        ) from None
    return _backfill_payload(row)


@router.get("/storage/backfill", response_model=StorageBackfillStatusResponse)
async def get_storage_backfill_status(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> StorageBackfillStatusResponse:
    return _backfill_payload(await storage_backfill.get_status(session))


# --- Registration captcha ---


def _captcha_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> CaptchaSettingsResponse:
    has_secret = bool(secrets.captcha_secret_key_encrypted)
    provider = settings_obj.captcha_provider
    return CaptchaSettingsResponse(
        provider=provider,
        site_key=settings_obj.captcha_site_key,
        has_secret_key=has_secret,
        # The client cannot see the secret, so it cannot work out whether
        # enforcement is on. Answered here, by the same predicate the verifier
        # uses, so the page and the register endpoint agree.
        enforcing=captcha_service.is_configured(
            ResolvedCaptchaConfig(
                provider=provider,
                site_key=settings_obj.captcha_site_key,
                secret_key="stored" if has_secret else None,
            )
        ),
    )


@router.get("/captcha", response_model=CaptchaSettingsResponse)
async def get_captcha_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> CaptchaSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _captcha_payload(settings_obj, secrets)


@router.put("/captcha", response_model=CaptchaSettingsResponse)
async def update_captcha_settings(
    payload: CaptchaSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> CaptchaSettingsResponse:
    # An absent secret_key keeps the stored one; an explicit null or "" clears
    # it. Same contract as the storage page, so an owner can edit the site key
    # without re-typing a secret they cannot read back.
    data = payload.model_dump(exclude_unset=True)
    updated, secrets = await app_settings_service.update_captcha_settings(
        session,
        system_session=system_session,
        provider=payload.provider,
        site_key=payload.site_key,
        secret_key=payload.secret_key,
        secret_provided="secret_key" in data,
        actor_user_id=owner.id,
    )
    return _captcha_payload(updated, secrets)


# --- Push notifications (FCM) ---


def _push_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> PushSettingsResponse:
    return PushSettingsResponse(
        enabled=settings_obj.fcm_enabled,
        project_id=settings_obj.fcm_project_id,
        application_id=settings_obj.fcm_application_id,
        api_key=settings_obj.fcm_api_key,
        sender_id=settings_obj.fcm_sender_id,
        has_service_account=bool(secrets.fcm_service_account_json_encrypted),
    )


@router.get("/push", response_model=PushSettingsResponse)
async def get_push_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> PushSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _push_payload(settings_obj, secrets)


@router.put("/push", response_model=PushSettingsResponse)
async def update_push_settings(
    payload: PushSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> PushSettingsResponse:
    data = payload.model_dump(exclude_unset=True)
    updated, secrets = await app_settings_service.update_push_settings(
        session,
        system_session=system_session,
        enabled=payload.enabled,
        project_id=payload.project_id,
        application_id=payload.application_id,
        api_key=payload.api_key,
        sender_id=payload.sender_id,
        service_account_json=payload.service_account_json,
        secret_provided="service_account_json" in data,
        actor_user_id=owner.id,
    )
    return _push_payload(updated, secrets)


@router.get("/fcm-config", response_model=FCMConfigResponse)
async def get_fcm_config(
    request: Request,
    platform: Literal["ios", "android"] | None = Query(
        default=None,
        description=(
            "The phone asking. Its relay id is served only to a phone whose "
            "pushes go through the relay."
        ),
    ),
) -> FCMConfigResponse:
    """Get public FCM configuration for mobile app initialization.

    This endpoint is public (no authentication required) and only exposes
    public fields needed by the mobile app to initialize Firebase.
    Service account credentials are NOT exposed.

    Rate limited to 20 requests per minute to prevent abuse.

    With no service account configured, pushes go through BeyondersStudio's push
    relay, and the Firebase settings served are the relay's (fetched with this
    server's relay key and cached); if the relay cannot say, no Firebase
    settings are served.

    The relay id is served to a phone whose pushes go through the relay, which
    names its ``platform``: an iPhone always, an Android phone when there is no
    service account. Asking for it registers this server with the relay first
    if it has not yet; a failed registration is retried no more than once
    every few minutes (``push_relay.REGISTRATION_RETRY_SECONDS``), however
    often this is asked. Anyone else is not served it, and asking registers
    nothing: a server with its own Firebase and only Android phones never
    contacts the relay at all.

    Read from the settings row (``push_config``), not the environment: an owner
    who turns push on in Settings has the mobile clients pick it up on their
    next launch rather than on the next redeploy. The resolver opens its own
    system-engine session, which is what lets this endpoint stay
    unauthenticated and sessionless.
    """
    cfg = await push_config.ensure_push_config_fresh()
    if not cfg.enabled:
        return FCMConfigResponse(enabled=False)
    via_relay = platform == "ios" or (
        platform == "android" and not cfg.service_account_json
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        relay_server_id = (
            await push_relay.current_server_id(client) if via_relay else None
        )
        if cfg.service_account_json:
            return FCMConfigResponse(
                enabled=True,
                project_id=cfg.project_id,
                application_id=cfg.application_id,
                api_key=cfg.api_key,
                sender_id=cfg.sender_id,
                push_relay_server_id=relay_server_id,
                android_via_relay=False,
            )
        # No service account: Android pushes go through the push relay, so the
        # app starts Firebase with the relay's project.
        relay = await push_relay.android_config(client)
    if relay is None:
        return FCMConfigResponse(
            enabled=True,
            push_relay_server_id=relay_server_id,
            android_via_relay=True,
        )
    return FCMConfigResponse(
        enabled=True,
        project_id=relay.project_id,
        application_id=relay.application_id,
        api_key=relay.api_key,
        sender_id=relay.sender_id,
        push_relay_server_id=relay_server_id,
        android_via_relay=True,
    )


# --- Guild storage limits (Operator dashboard → Guilds tab) ---


#: The statuses a community may be suspended from.
_SUSPENDABLE = frozenset(
    {
        CommunityStatus.active,
        CommunityStatus.read_only,
        CommunityStatus.on_hold,
        CommunityStatus.deleted,
    }
)


def _community_actions(
    actor: User, status_: CommunityStatus, *, moderating: bool
) -> list[CommunityAction]:
    """What ``actor`` may do to a community at ``status_``, in the order the
    row draws them. ``moderating`` says they hold a live ``moderate`` grant on
    it, which suspending and lifting need beside the capability."""
    actions: list[CommunityAction] = []
    manages = user_has_capability(actor, Capability.COMMUNITIES_MANAGE)
    if manages:
        actions.append(CommunityAction.manage)
        if status_ is not CommunityStatus.deleted:
            actions.append(CommunityAction.set_status)
    if moderating and user_has_capability(actor, Capability.COMMUNITIES_SUSPEND):
        if status_ is CommunityStatus.suspended:
            actions.append(CommunityAction.lift)
        elif status_ in _SUSPENDABLE:
            actions.append(CommunityAction.suspend)
    if user_has_capability(actor, Capability.BILLING_SUPPORT):
        actions.append(CommunityAction.billing_support)
    if manages:
        actions.append(CommunityAction.billing_operator)
    if user_has_capability(actor, Capability.ACCESS_REQUEST):
        actions.append(CommunityAction.request_access)
    if user_has_capability(actor, Capability.DATA_BYPASS):
        actions.append(CommunityAction.break_glass)
    return actions


async def _moderating(session: Any, *, user_id: int, guild_ids: list[int]) -> set[int]:
    """Which of ``guild_ids`` ``user_id`` holds a live ``moderate`` grant on.
    One read for the page."""
    if not guild_ids:
        return set()
    rows = await session.exec(
        select(AccessGrant.guild_id).where(
            AccessGrant.user_id == user_id,
            AccessGrant.guild_id.in_(guild_ids),
            AccessGrant.purpose == AccessGrantPurpose.content.value,
            AccessGrant.access_level == AccessLevel.moderate.value,
            AccessGrant.live(utcnow()),
        )
    )
    return {int(guild_id) for guild_id in rows.all()}


def _plan_fields(plan: rules.Values) -> dict[str, Any]:
    """What the operator's caps and entitlements for one community consist of:
    its paid rules, under the names the operator's page and its records use."""
    return {
        "max_storage_bytes": plan["max_storage_bytes"],
        "max_users": plan["max_users"],
        "max_guests": plan["max_guests"],
        "auth_options": sorted(
            option.value for option, key in OPTION_RULES.items() if plan[key]
        ),
        "banner_image_enabled": plan["banner_image"],
        "support_enabled": plan["help_requests"],
        "ai_connections_open": plan[SURFACE_AI_CONNECTIONS],
        "plugins_open": plan[SURFACE_PLUGINS],
        "custom_roles_open": plan[SURFACE_CUSTOM_ROLES],
    }


def _guild_storage_read(
    guild: Guild,
    administration: GuildAdministration | None,
    *,
    plan: rules.Values,
    member_count: int,
    has_seat: bool,
    deployment: rules.Values,
    actor: User,
    moderating: bool = False,
) -> PlatformCommunityStorageRead:
    """One row of the Guilds tab, as ``actor`` may act on it.

    ``administration`` is None only for a guild missing its companion row,
    which is listed with a blank plan label rather than dropped. ``plan`` is
    its rules (``rules.community_values``). The status choices are offered
    only to whoever sets them.
    """
    current = CommunityStatus(guild.status)
    recorded = administration.billing_status if administration else None
    actions = _community_actions(actor, current, moderating=moderating)
    billing_status = CommunityStatus(recorded) if recorded else None
    return PlatformCommunityStorageRead(
        id=guild.id,
        name=guild.name,
        member_count=member_count,
        purge_at=COMMUNITY_DELETION.ends_at(guild, deployment),
        has_seat=has_seat,
        tier_name=administration.tier_name if administration else None,
        max_storage_bytes=plan["max_storage_bytes"],
        max_users=plan["max_users"],
        max_guests=plan["max_guests"],
        status=current,
        status_changed_at=guild.status_changed_at,
        status_choices=(
            list(
                operator_status_choices(
                    current,
                    billing_status=billing_status,
                    billing_managed=billing_service.billing_managed(),
                )
            )
            if CommunityAction.set_status in actions
            else []
        ),
        lifts_to=(
            guilds_service.lifted_status(guild, billing_status=billing_status)
            if current is CommunityStatus.suspended
            else None
        ),
        allowed_actions=actions,
        auth_options=_plan_fields(plan)["auth_options"],
        banner_image_enabled=plan["banner_image"],
        support_enabled=plan["help_requests"],
        ai_connections_open=plan[SURFACE_AI_CONNECTIONS],
        plugins_open=plan[SURFACE_PLUGINS],
        custom_roles_open=plan[SURFACE_CUSTOM_ROLES],
    )


async def _member_tallies(
    guild_ids: list[int],
) -> tuple[dict[int, int], set[int]]:
    """Each listed community's member count, and which of them hold their seat.

    Two grouped queries for the page, on the system engine: the platform tier
    reads no roster but its own memberships, and this list needs only the
    totals, not the rows behind them.
    """
    from app.db.session import SystemSessionLocal

    if not guild_ids:
        return {}, set()
    async with SystemSessionLocal() as system_session:
        counts = dict(
            (
                await system_session.exec(
                    select(GuildMembership.guild_id, func.count())
                    .where(
                        GuildMembership.guild_id.in_(guild_ids),
                        GuildMembership.guest_until.is_(None),
                    )
                    .group_by(GuildMembership.guild_id)
                )
            ).all()
        )
        seated = set(
            (
                await system_session.exec(
                    select(GuildMembership.guild_id)
                    .where(
                        GuildMembership.guild_id.in_(guild_ids),
                        GuildMembership.role == CommunityRole.superadmin,
                    )
                    .distinct()
                )
            ).all()
        )
    return counts, seated


_GUILD_SORT_FIELDS = {"id": Guild.id, "name": Guild.name}


@router.get("/communities", response_model=PlatformCommunityStorageListResponse)
async def list_platform_community_storage(
    session: UserSessionDep,
    reader: CommunitiesReadDep,
    search: str | None = Query(default=None, description="Matches the name."),
    sort_by: Literal["id", "name"] = "name",
    sort_dir: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PlatformCommunityStorageListResponse:
    """One page of the deployment's guilds with their storage caps, for the
    Operator dashboard Guilds tab.

    Support and above (``communities.read``). Reads only shared ``public``
    tables. The guilds and their administration rows are read on the caller's
    platform tier, under the ``communities.read`` policies on both; the caps
    join in a single pass. Each row says what the reader may do to it. Member counts and seats are totals read on the system engine
    (``_member_tallies``), one grouped query each for the page.
    """
    # Outer join on purpose: this is the operator's view of *every* guild, and a
    # guild missing its companion row must still be listed (with blank caps) so
    # it stays manageable, rather than silently vanishing from the moderation
    # surface. Creation writes the pair together, so this is a floor, not a
    # normal case.
    base = select(Guild, GuildAdministration).outerjoin(
        GuildAdministration, GuildAdministration.guild_id == Guild.id
    )
    if search and (term := search.strip()):
        # A number, with or without its ``#``, also finds the community by id,
        # so one of many sharing a name can still be picked.
        number = term.removeprefix("#")
        matches = Guild.name.ilike(f"%{term}%")
        # ASCII digits only, and no more than an id can hold: anything else
        # is a name to look for.
        if number.isascii() and number.isdigit() and int(number) < 2**31:
            matches = or_(matches, Guild.id == int(number))
        base = base.where(matches)
    order = _GUILD_SORT_FIELDS[sort_by]
    rows, total_count, actual_page = await paginated_query(
        session,
        base.order_by(
            order.desc() if sort_dir == "desc" else order.asc(), Guild.id.asc()
        ),
        select(func.count()).select_from(base.subquery()),
        page=page,
        page_size=page_size,
    )
    deployment = await rules.platform_values(session)
    plans = await rules.community_values(session, [g.id for g, _ in rows])
    counts, seated = await _member_tallies([g.id for g, _ in rows])
    # The reader's own grants, under the requester's own-row policy.
    moderating = await _moderating(
        session, user_id=reader.id, guild_ids=[g.id for g, _ in rows]
    )
    items = [
        _guild_storage_read(
            g,
            administration,
            plan=plans[g.id],
            member_count=counts.get(g.id, 0),
            has_seat=g.id in seated,
            deployment=deployment,
            actor=reader,
            moderating=g.id in moderating,
        )
        for g, administration in rows
    ]
    return PlatformCommunityStorageListResponse(
        **build_paginated_response(items, total_count, actual_page, page_size),
        support_bound=await stream_is_bound(IntakeStream.support),
    )


@router.patch(
    "/communities/{community_id}", response_model=PlatformCommunityStorageRead
)
async def update_platform_community_storage(
    guild_id: CommunityIdPath,
    payload: PlatformCommunityStorageUpdate,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> PlatformCommunityStorageRead:
    """Set a guild's storage/member caps and/or lifecycle status. Operator/owner.

    Writes only shared ``public`` columns — the caps and the sign-in entitlement
    on ``guild_administration``, the lifecycle ``status`` on ``guilds`` — so no
    guild-schema routing is needed. Both are system-engine writes: no
    request-path role holds INSERT/UPDATE on ``guild_administration`` at all.
    ``model_fields_set`` tells an omitted cap (leave untouched) from one sent as
    ``null`` (reset to unlimited). ``status`` (active / read_only / suspended) is
    a moderation action: it downgrades or cuts off member access on the request
    path (see ``_load_guild_context``) but never touches stored data, and PAM /
    break-glass grants override it so operators can't lock themselves out.
    Lowering a cap below current usage just blocks further uploads / new joins.

    Where billing sets plans (``billing_service.billing_managed``), the caps and
    entitlements are refused and the status may only move to one of the row's
    ``status_choices``; the triggers of migration 0364 hold the database to the
    same rule.
    """
    provided = payload.model_fields_set
    managed = billing_service.billing_managed()
    if managed and (
        "max_storage_bytes" in provided
        or "max_users" in provided
        or "max_guests" in provided
        or payload.auth_options is not None
        or payload.banner_image_enabled is not None
        or payload.support_enabled is not None
        or payload.ai_connections_open is not None
        or payload.plugins_open is not None
        or payload.custom_roles_open is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildMessages.COMMUNITY_PLAN_SET_BY_BILLING,
        )
    before: dict[str, Any] = {}
    status_before: str | None = None
    status_after: str | None = None
    try:
        before = _plan_fields(
            (await rules.community_values(session, [guild_id]))[guild_id]
        )
        guild = await guilds_service.update_guild(
            session,
            guild_id=guild_id,
            max_storage_bytes=payload.max_storage_bytes,
            max_storage_bytes_provided="max_storage_bytes" in provided,
            max_users=payload.max_users,
            max_users_provided="max_users" in provided,
            max_guests=payload.max_guests,
            max_guests_provided="max_guests" in provided,
            auth_options=payload.auth_options,
            banner_image_enabled=payload.banner_image_enabled,
            support_enabled=payload.support_enabled,
            ai_connections_open=payload.ai_connections_open,
            plugins_open=payload.plugins_open,
            custom_roles_open=payload.custom_roles_open,
        )
        if payload.status is not None and guild.status != payload.status.value:
            recorded = (
                await guilds_service.get_administration(session, guild_id=guild_id)
            ).billing_status
            choices = operator_status_choices(
                CommunityStatus(guild.status),
                billing_status=CommunityStatus(recorded) if recorded else None,
                billing_managed=managed,
            )
            if payload.status not in choices:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        GuildMessages.COMMUNITY_STATUS_SET_BY_BILLING
                        if managed
                        else GuildMessages.COMMUNITY_STATUS_NOT_SETTABLE
                    ),
                )
            logger.info(
                "guild %s status %s -> %s by user %s",
                guild_id,
                guild.status,
                payload.status.value,
                operator.id,
            )
            status_before, status_after = guild.status, payload.status.value
            guild = await guilds_service.set_guild_status(
                session, guild_id=guild_id, status=payload.status
            )
    except ValueError as exc:
        # update_guild -> get_guild raises ValueError(COMMUNITY_NOT_FOUND) when the row
        # is gone. Letting it own the existence check (rather than a separate
        # pre-SELECT) closes the TOCTOU window where a concurrent delete between
        # the two queries would otherwise surface as an unhandled 500.
        if str(exc) == GuildMessages.COMMUNITY_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=GuildMessages.COMMUNITY_NOT_FOUND,
            ) from exc
        if str(exc) == GuildMessages.COMMUNITY_PURGE_STARTED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=GuildMessages.COMMUNITY_PURGE_STARTED,
            ) from exc
        raise
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    changed = audit_service.changed_fields(
        before,
        _plan_fields((await rules.community_values(session, [guild_id]))[guild_id]),
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_SETTINGS_CHANGED,
            actor_user_id=operator.id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"area": "administration", **changed},
        )
    if status_after is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_STATUS_CHANGED,
            actor_user_id=operator.id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"from": status_before, "to": status_after},
        )
    await session.commit()
    if status_after is not None:
        if status_after == CommunityStatus.on_hold.value:
            await guilds_service.announce_on_hold(session, guild_id)
            guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return _guild_storage_read(
        guild,
        administration,
        plan=(await rules.community_values(session, [guild.id]))[guild.id],
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        has_seat=await guilds_service.guild_has_seat(session, guild_id=guild.id),
        deployment=await rules.platform_values(session),
        actor=operator,
        moderating=guild.id
        in await _moderating(session, user_id=operator.id, guild_ids=[guild.id]),
    )


@router.post(
    "/communities/{community_id}/suspension",
    response_model=PlatformCommunityStorageRead,
)
async def set_platform_community_suspension(
    guild_id: CommunityIdPath,
    payload: CommunitySuspensionUpdate,
    session: SystemSessionDep,
    moderator: CommunitiesSuspendDep,
) -> PlatformCommunityStorageRead:
    """Suspend a community, or lift its suspension (``communities.suspend``).

    Only under a live ``moderate`` grant on that community, held by whoever
    asks: a moderator suspends a community they are looking at. A suspension
    starts from active, read-only, on hold or deleted — taking a deleted one
    out of its purge countdown — and lifting it returns the community where it
    was. One suspended out of deletion goes back to deleted with its countdown
    started again, so its owners have the whole window to notice.
    """
    if guild_id not in await _moderating(
        session, user_id=moderator.id, guild_ids=[guild_id]
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_SUSPENSION_NEEDS_GRANT,
        )
    # Locked for the rest of the transaction, so a deletion or a purge pass
    # deciding on the same community waits for this and reads what it wrote.
    guild = (
        await session.exec(
            select(Guild)
            .where(Guild.id == guild_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_NOT_FOUND,
        )
    current = CommunityStatus(guild.status)
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    if payload.suspended:
        if current not in _SUSPENDABLE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=GuildMessages.COMMUNITY_NOT_SUSPENDABLE,
            )
        target = CommunityStatus.suspended
    else:
        if current is not CommunityStatus.suspended:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=GuildMessages.COMMUNITY_NOT_SUSPENDED,
            )
        recorded = administration.billing_status
        target = guilds_service.lifted_status(
            guild, billing_status=CommunityStatus(recorded) if recorded else None
        )
    grant = await access_grants_service.get_live_grant(
        session, user_id=moderator.id, guild_id=guild_id
    )
    try:
        guild = await guilds_service.set_guild_status(
            session, guild_id=guild_id, status=target
        )
    except ValueError as exc:
        if str(exc) != GuildMessages.COMMUNITY_PURGE_STARTED:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_STATUS_CHANGED,
        actor_user_id=moderator.id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={
            "from": current.value,
            "to": target.value,
            "grant_id": grant.id if grant is not None else None,
        },
    )
    await session.commit()
    if grant is not None:
        await grant_cases.note(
            grant.case_task_id,
            case_activity.ActivityKind.guild_act,
            f"{handle_of(moderator)} "
            + ("suspended" if payload.suspended else "lifted the suspension of")
            + f" community {guild.name} (#{guild_id}): {current.value} to "
            f"{target.value}.",
        )
    return _guild_storage_read(
        guild,
        administration,
        plan=(await rules.community_values(session, [guild.id]))[guild.id],
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        has_seat=await guilds_service.guild_has_seat(session, guild_id=guild_id),
        deployment=await rules.platform_values(session),
        actor=moderator,
        moderating=True,
    )


@router.get(
    "/communities/{community_id}/narrowings",
    response_model=list[CommunityNarrowingPending],
)
async def read_community_narrowings(
    guild_id: CommunityIdPath,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> list[CommunityNarrowingPending]:
    """What this community says its own arrivals look like, and whether
    anybody has agreed.

    Operator/owner (``communities.manage``). The community writes these values itself
    and nothing here can tell whether it holds the domain or tenant they name,
    so the answer is the deployment's. Support answers through the case raised
    when they are written; this is the same question where a deployment runs
    no intake, and the place to withdraw an answer either way.
    """
    return await narrowing_review.pending_for_guild(session, guild_id=guild_id)


@router.put(
    "/communities/{community_id}/narrowings/{connection_id}",
    response_model=CommunityNarrowingPending,
)
async def agree_community_narrowing(
    guild_id: CommunityIdPath,
    connection_id: int,
    payload: CommunityNarrowingAgreement,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> CommunityNarrowingPending:
    """Agree that these values are this community's, or withdraw that.

    Agreeing lets arrivals it counts as its own join on sight where the
    community asked for that. Withdrawing leaves the connection and its values
    as they are; what stops is joining people on arrival.
    """
    return await narrowing_review.agree(
        session,
        guild_id=guild_id,
        connection_id=connection_id,
        agreed=payload.agreed,
        actor_user_id=operator.id,
    )


@asynccontextmanager
async def _routed_to_community(
    session: AsyncSession, guild_id: int
) -> AsyncIterator[AsyncSession]:
    """A system session routed to a community that is still there."""
    guild = await session.get(Guild, guild_id)
    if guild is None or guild.status == CommunityStatus.deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_NOT_FOUND,
        )
    async with cohorts.system_session(guild_id) as routed:
        await set_rls_context(routed, SystemGuild(guild_id))
        yield routed


@router.get(
    "/communities/{community_id}/plugin-summaries",
    response_model=PluginSummaryListResponse,
)
async def list_community_plugin_summaries(
    guild_id: CommunityIdPath,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> PluginSummaryListResponse:
    """The community's installs that say where it stands with them, as its
    Usage tab lists them.

    Operator/owner (``communities.manage``), for the community's sheet: the
    caps set there sit beside what the community uses of them.
    """
    async with _routed_to_community(session, guild_id) as routed:
        return await plugin_data_service.community_summaries(routed)


@router.get(
    "/communities/{community_id}/plugin-summaries/{plugin_id}",
    response_model=PluginDataResponse,
)
async def read_community_plugin_summary(
    guild_id: CommunityIdPath,
    plugin_id: int,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> PluginDataResponse:
    """Where the community stands with one installed plug-in, as its Usage tab
    reads it. The operator is not one of the community's people, so a summary
    that needs a member's own connection answers that it needs one."""
    async with _routed_to_community(session, guild_id) as routed:
        return await plugin_data_service.read_community_summary(
            routed, plugin_id=plugin_id, user_id=None
        )


@router.post(
    "/communities/{community_id}/restore", response_model=PlatformCommunityStorageRead
)
async def restore_platform_community(
    guild_id: CommunityIdPath,
    payload: PlatformCommunityRestore,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> PlatformCommunityStorageRead:
    """Bring a deleted guild back before its retention window runs out.

    Operator/owner (``communities.manage``). Deleting a guild keeps it — the shared
    rows, the ``guild_<id>`` schema and the stored blobs all stay until
    ``guild_purge`` destroys them — so restoring is a status write plus, where
    the roster was emptied, seating somebody who can run the community again.

    The operator names the status it returns at, and must name a seat when the
    guild holds none. Both are re-checked in the service rather than trusted
    from the payload. Where billing sets plans, the status is the one billing
    last wrote or ``suspended`` (``restore_status_choices``); the trigger of
    migration 0364 holds the database to the same rule. What does *not* come back is the guild's plug-in
    connections: those were revoked when it was deleted, and the community's
    superadmin reconnects them.

    Writes only shared ``public`` columns (``guilds.status`` and, for the seat,
    ``guild_memberships``), so no guild-schema routing is needed.
    """
    try:
        guild = await guilds_service.restore_guild(
            session,
            guild_id=guild_id,
            status=payload.status,
            seat_user_id=payload.seat_user_id,
            actor_user_id=operator.id,
        )
    except ValueError as exc:
        code = str(exc)
        if code == GuildMessages.COMMUNITY_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=code
            ) from exc
        if code in (
            GuildMessages.COMMUNITY_NOT_DELETED,
            GuildMessages.COMMUNITY_PURGE_STARTED,
            GuildMessages.COMMUNITY_RESTORE_STATUS_SET_BY_BILLING,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=code
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=code
        ) from exc
    logger.info(
        "guild %s restored as %s by user %s", guild_id, guild.status, operator.id
    )
    await session.commit()
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    return _guild_storage_read(
        guild,
        administration,
        plan=(await rules.community_values(session, [guild.id]))[guild.id],
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        has_seat=await guilds_service.guild_has_seat(session, guild_id=guild_id),
        deployment=await rules.platform_values(session),
        actor=operator,
        moderating=guild_id
        in await _moderating(session, user_id=operator.id, guild_ids=[guild_id]),
    )


@router.post(
    "/communities/{community_id}/billing/service-handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_platform_community_billing_service_handoff(
    guild_id: CommunityIdPath,
    session: SystemSessionDep,
    operator: Annotated[User, Depends(get_current_active_user)],
    console: Literal["support", "operator"] = "support",
    answer: SecondFactorAnswer | None = None,
) -> BillingPortalHandoffResponse:
    """Mint the operator handoff into the billing portal for one guild.

    Backs the Guilds tab's billing buttons. The support console is
    ``billing.support`` (support and above); the operator console, which
    changes a plan, is ``communities.manage``.
    The token names the ``access_grants`` row that authorises the visit: a
    live billing grant is reused, otherwise one is self-issued — after the
    account's second factor, as breaking glass takes it — so the visit is
    recorded on both sides. A billing grant reaches the billing account and
    nothing in the guild; what it may do there is the billing service's to
    decide.
    """
    needed = (
        Capability.BILLING_SUPPORT
        if console == "support"
        else Capability.COMMUNITIES_MANAGE
    )
    if not user_has_capability(operator, needed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
        )
    if not app_config.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )

    found = (
        await session.exec(select(Guild.id).where(Guild.id == guild_id))
    ).one_or_none()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_NOT_FOUND,
        )

    grant = await access_grants_service.get_live_grant(
        session,
        user_id=operator.id,
        guild_id=guild_id,
        purpose=AccessGrantPurpose.billing,
    )
    if grant is None:
        await check_second_factor(
            session,
            actor=operator,
            answer=answer or SecondFactorAnswer(),
            during="billing_handoff",
        )
        try:
            grant = await access_grants_service.break_glass(
                session,
                actor=operator,
                # A visit to the portal, and nothing in the guild.
                level=AccessLevel.read.value,
                payload=BreakGlassCreate(
                    community_id=guild_id,
                    reason=BILLING_PORTAL_GRANT_REASON,
                ),
                # Belonging to the guild says nothing about billing authority,
                # so a member still breaks glass for it.
                allow_member=True,
                purpose=AccessGrantPurpose.billing,
            )
        except access_grants_service.AccessGrantError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=BillingMessages.PORTAL_GRANT_UNAVAILABLE,
            ) from exc
        # Recorded like every other grant somebody issues themselves.
        await audit_service.record(
            session,
            event_type=AuditEventType.ACCESS_GRANT_SELF_ISSUED,
            actor_user_id=operator.id,
            guild_id=grant.guild_id,
            target_type="access_grant",
            target_id=grant.id,
            detail={
                "purpose": grant.purpose,
                "level": grant.access_level,
                "self_approved": True,
            },
        )

    try:
        user_ref, guild_ref = await billing_refs(user_id=operator.id, guild_id=guild_id)
        token, expires_in_seconds = create_billing_support_handoff_token(
            grant_id=grant.id,
            user_ref=user_ref,
            guild_ref=guild_ref,
            approver_ref=(
                await billing_ref(IdentityEntity.user, grant.approved_by_id)
                if grant.approved_by_id is not None
                else None
            ),
            console=console,
        )
    except BillingSupportHandoffNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc

    await session.commit()
    logger.info(
        "billing portal: operator %s (%s) opened guild %s under grant %s",
        operator.id,
        operator.role.value,
        guild_id,
        grant.id,
    )
    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )


@router.post(
    "/billing/insights-handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_billing_insights_handoff(
    operator: BillingInsightsDep,
) -> BillingPortalHandoffResponse:
    """Mint the handoff into the billing service's insights page.

    Backs the operator dashboard's Billing tab (``billing.insights``). Unlike
    the console handoffs above it names no community and needs no access
    grant: the page shows Paddle's account-wide figures and counts that name
    no community, and billing reads them as a role that can see nothing else.
    The person is named by billing's pairwise reference, which is what billing
    records the visit under.
    """
    if not app_config.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )
    try:
        token, expires_in_seconds = create_billing_insights_handoff_token(
            user_ref=await billing_ref(IdentityEntity.user, operator.id),
        )
    except HandoffSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc
    logger.info(
        "billing insights: operator %s (%s) opened the insights page",
        operator.id,
        operator.role.value,
    )
    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )


@router.post(
    "/billing/contracts-handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_billing_contracts_handoff(
    operator: BillingContractsDep,
) -> BillingPortalHandoffResponse:
    """Mint the handoff into the billing service's contracts console.

    Backs the operator dashboard's Billing tab (``billing.contracts``). Like
    the insights handoff it names no community and needs no access grant: a
    contract is a payer's, and some cover no community here. The person is
    named by billing's pairwise reference, which is what billing attributes
    every change in the console to.
    """
    if not app_config.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )
    try:
        token, expires_in_seconds = create_billing_contracts_handoff_token(
            user_ref=await billing_ref(IdentityEntity.user, operator.id),
        )
    except HandoffSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc
    logger.info(
        "billing contracts: operator %s (%s) opened the contracts console",
        operator.id,
        operator.role.value,
    )
    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )


@router.post(
    "/billing/directory-handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_billing_directory_handoff(
    owner: BillingDirectoryDep,
) -> BillingPortalHandoffResponse:
    """Mint the handoff into the billing service's owner directory.

    Backs the operator dashboard's Billing tab (``billing.directory``, owners
    only). Like the insights handoff it names no community and needs no access
    grant: the page lists every account, read-only. The person is named by
    billing's pairwise reference, which is what billing records each read
    under.
    """
    if not app_config.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )
    try:
        token, expires_in_seconds = create_billing_directory_handoff_token(
            user_ref=await billing_ref(IdentityEntity.user, owner.id),
        )
    except HandoffSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc
    logger.info(
        "billing directory: owner %s (%s) opened the directory",
        owner.id,
        owner.role.value,
    )
    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )


@router.post(
    "/billing/control-handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_billing_control_handoff(
    owner: BillingControlDep,
) -> BillingPortalHandoffResponse:
    """Mint the handoff into the billing service's Control.

    Backs the operator dashboard's Billing tab (``billing.control``, owners
    only), where the deployment's plans are defined. It names no community
    and needs no access grant: a plan is every community's. The person is
    named by billing's pairwise reference, which is what billing attributes
    each change to.
    """
    if not app_config.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )
    try:
        token, expires_in_seconds = create_billing_control_handoff_token(
            user_ref=await billing_ref(IdentityEntity.user, owner.id),
        )
    except HandoffSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc
    logger.info(
        "billing control: owner %s (%s) opened Control",
        owner.id,
        owner.role.value,
    )
    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )
