"""The steps every sign-in rule's write takes, proved once for every rule.

Each rule in ``PLATFORM_RULES`` and ``COMMUNITY_RULES`` has a case below: a
loose and a tight value, and how to put the tight one in place. What the
rules have of their own (the stranded-account count, a provider's
connection) is tested beside the routes that take it.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod, SecondFactorRequirement
from app.models.platform.user_dm_settings import DmPolicy
from app.schemas.ai_settings import AIConfigMode
from app.core.security import AUTH_POLICY_UNMET_HEADER
from app.models.platform.user import UserRole
from app.services.platform import auth_posture, rules
from app.services.platform.auth_posture import (
    COMMUNITY_RULES,
    PLATFORM_RULES,
    RuleContext,
    SignInRequirement,
)
from app.testing import emitted
from app.testing.factories import create_guild, create_user

#: Every way in but the emailed code, which also needs mail set up.
ALL_METHODS = frozenset(LoginMethod) - {LoginMethod.email_otp}
FACTOR_REQUIREMENT = SignInRequirement("required", None, frozenset({LoginMethod.totp}))


async def _put(session: AsyncSession, guild_id: int | None, key: str, value: Any):
    """Put ``value`` in place directly, as a rule's own write would leave it."""
    await rules.put(session, key, value, guild_id=guild_id)
    await session.commit()


@dataclass(frozen=True)
class Case:
    loose: Any
    tight: Any
    event: AuditEventType
    #: Leaves the deployment permitting nothing that could answer the tight
    #: value, for a rule that asks.
    unoffer: Callable[[AsyncSession], Awaitable[None]] | None = None
    #: The unmet header a writer without a second factor is refused with.
    unmet: str | None = None


async def _no_factor_methods(session: AsyncSession) -> None:
    await _put(session, None, "login_methods", frozenset({LoginMethod.password}))


PLATFORM_SETTINGS = AuditEventType.PLATFORM_SETTINGS_CHANGED
GUILD_SETTINGS = AuditEventType.GUILD_SETTINGS_CHANGED

CASES: dict[tuple[str, str], Case] = {
    ("platform", "login_methods"): Case(
        ALL_METHODS,
        frozenset({LoginMethod.password}),
        AuditEventType.PLATFORM_LOGIN_METHODS_CHANGED,
    ),
    ("platform", "second_factor_requirement"): Case(
        SecondFactorRequirement.nobody,
        SecondFactorRequirement.everyone,
        AuditEventType.PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED,
        unoffer=_no_factor_methods,
        unmet=LoginMethod.totp.value,
    ),
    ("platform", "session_max_hours"): Case(None, 12, PLATFORM_SETTINGS),
    ("platform", "session_idle_minutes"): Case(None, 30, PLATFORM_SETTINGS),
    ("platform", "push_notifications_enabled"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "email_notifications_enabled"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "redact_notification_content"): Case(False, True, PLATFORM_SETTINGS),
    ("platform", "engagement_ranking_enabled"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "cookie_consent_enabled"): Case(False, True, PLATFORM_SETTINGS),
    ("platform", "default_dm_policy"): Case(
        DmPolicy.private, DmPolicy.public, PLATFORM_SETTINGS
    ),
    ("platform", "ai_config_mode"): Case(
        AIConfigMode.disabled, AIConfigMode.platform, PLATFORM_SETTINGS
    ),
    ("platform", "community_directory_enabled"): Case(False, True, PLATFORM_SETTINGS),
    ("platform", "community_age_gate_enabled"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "direct_messages_enabled"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "guests_enabled"): Case(False, True, PLATFORM_SETTINGS),
    ("platform", "max_guest_days"): Case(90, 30, PLATFORM_SETTINGS),
    ("platform", "erase_deleted_accounts"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "deleted_account_retention_days"): Case(30, 7, PLATFORM_SETTINGS),
    ("platform", "destroy_deleted_communities"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "deleted_community_retention_days"): Case(90, 7, PLATFORM_SETTINGS),
    ("platform", "delete_held_communities"): Case(True, False, PLATFORM_SETTINGS),
    ("platform", "on_hold_community_deletion_days"): Case(30, 7, PLATFORM_SETTINGS),
    ("platform", "marketplace_members_publish_directly"): Case(
        False, True, PLATFORM_SETTINGS
    ),
    ("platform", "marketplace_registry_enabled"): Case(True, False, PLATFORM_SETTINGS),
    ("community", "auth_policy"): Case(
        SignInRequirement(),
        FACTOR_REQUIREMENT,
        AuditEventType.GUILD_AUTH_POLICY_CHANGED,
        unoffer=_no_factor_methods,
        unmet=LoginMethod.totp.value,
    ),
    ("community", "require_second_factor"): Case(
        False,
        True,
        GUILD_SETTINGS,
        unoffer=_no_factor_methods,
        unmet=LoginMethod.totp.value,
    ),
    ("community", "enforce_compliance_session"): Case(False, True, GUILD_SETTINGS),
    ("community", "allow_push_notifications"): Case(True, False, GUILD_SETTINGS),
    ("community", "allow_email_notifications"): Case(True, False, GUILD_SETTINGS),
    ("community", "redact_notification_content"): Case(False, True, GUILD_SETTINGS),
    ("community", "allow_engagement_ranking"): Case(True, False, GUILD_SETTINGS),
    ("community", "allow_ai"): Case(True, False, GUILD_SETTINGS),
    # Its writer is not a guest, so is not asked to meet it.
    ("community", "guest_auth_policy"): Case(
        SignInRequirement(),
        FACTOR_REQUIREMENT,
        AuditEventType.GUILD_AUTH_POLICY_CHANGED,
    ),
    ("community", "guest_max_days"): Case(None, 30, GUILD_SETTINGS),
}

RULES = pytest.mark.parametrize(
    ("scope", "key"),
    [("platform", key) for key in PLATFORM_RULES]
    + [("community", key) for key in COMMUNITY_RULES],
    ids=lambda value: value,
)


async def _context(session: AsyncSession, scope: str, *, entitled: bool = True):
    """A writer with no second factor, in a community holding its options or
    none of them, on a deployment permitting every way in."""
    owner = await create_user(session, role=UserRole.owner)
    await _put(session, None, "login_methods", ALL_METHODS)
    await _put(
        session, None, "second_factor_requirement", SecondFactorRequirement.nobody
    )
    if scope == "platform":
        return RuleContext.platform(session, owner)
    options = {} if entitled else {"auth_options": []}
    guild = await create_guild(session, creator=owner, **options)
    return RuleContext.community(session, session, owner, guild.id)


async def _refused(ctx: RuleContext, key: str, value: Any) -> HTTPException:
    with pytest.raises(HTTPException) as refused:
        await auth_posture.change(ctx, {key: value})
    await ctx.session.rollback()
    return refused.value


@RULES
async def test_loosening_is_never_refused_and_records_once(
    session: AsyncSession, capfd, scope: str, key: str
):
    """From the tight value, with no entitlement, nothing to answer it and a
    writer who does not: the rule loosens and is recorded once. Saving the
    same value again records nothing."""
    case = CASES[scope, key]
    ctx = await _context(session, scope, entitled=False)
    await _put(session, ctx.guild_id, key, case.tight)
    if case.unoffer:
        await case.unoffer(session)
    emitted(capfd)

    await auth_posture.change(ctx, {key: case.loose})
    assert len(emitted(capfd, case.event)) == 1

    await auth_posture.change(ctx, {key: case.loose})
    assert emitted(capfd, case.event) == []


@RULES
async def test_tightening_asks_for_entitlement_offer_and_writer(
    session: AsyncSession, scope: str, key: str
):
    """In order: a community rule needs its entitlement; a rule something must
    answer needs the deployment to permit it; and its writer must answer it."""
    case = CASES[scope, key]
    if scope == "community":
        refused = await _refused(
            await _context(session, scope, entitled=False), key, case.tight
        )
        assert (refused.status_code, refused.detail) == (
            404,
            "COMMUNITY_AUTH_NOT_ENABLED",
        )
    if case.unoffer is None:
        return
    ctx = await _context(session, scope)
    await case.unoffer(session)
    refused = await _refused(ctx, key, case.tight)
    assert (refused.status_code, refused.detail) == (409, "AUTH_RULE_NOT_OFFERED")

    ctx = await _context(session, scope)
    refused = await _refused(ctx, key, case.tight)
    assert (refused.status_code, refused.detail) == (400, "AUTH_RULE_SELF_UNSATISFIED")
    assert refused.headers == {AUTH_POLICY_UNMET_HEADER: case.unmet}


async def test_one_change_loosens_before_it_tightens(session: AsyncSession):
    """Lowering the deployment's factor requirement and withdrawing the last
    method that answers it is one change: the withdrawal is checked against
    the lowered requirement."""
    ctx = await _context(session, "platform")
    await _put(
        session, None, "second_factor_requirement", SecondFactorRequirement.everyone
    )

    await auth_posture.change(
        ctx,
        {
            "login_methods": ALL_METHODS - {LoginMethod.totp, LoginMethod.passkey},
            "second_factor_requirement": SecondFactorRequirement.nobody,
        },
    )
