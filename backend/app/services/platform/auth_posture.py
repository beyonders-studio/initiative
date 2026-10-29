"""Which ways in this deployment and its communities permit.

The one read of each setting, and the one write. Everything that gates a
sign-in route asks here, so the rules live in exactly one place. (A fresh
deployment's first value is the env's, ``AUTH_LOGIN_METHODS`` — seeded once
into the settings row when it is created, see
``app_settings._seeded_login_methods`` — and every change after that goes
through :func:`change`.)

**Writing a rule.** Every rule about how somebody reaches the deployment or a
community, and what leaves a community on its behalf, is a :class:`Rule` in
:data:`PLATFORM_RULES` or :data:`COMMUNITY_RULES`, and is written by
:func:`change`, which runs the same steps for each:

1. Take the rows a change depends on: the settings row for the deployment's
   rules; the community's row, and while anything tightens, the settings row
   shared and the seat lock.
2. Loosen first. A loosening write only admits more, so it is never refused
   for want of an entitlement or of anything to answer it.
3. Then tighten, each against the state the loosening left. A tightening
   needs the community's entitlement, something the deployment permits that
   can answer it, and a writer who already answers it themselves.
4. Write, and record each rule that moved. One that did not move records
   nothing.
5. Follow up and commit: switching push off drops the tokens it was sent to.

A community's rule applies only while it holds the option the rule needs
(``guild_administration.auth_options``), and every point that enforces
one asks. Taking an option away stops the rule applying and
leaves it set, so it applies again when the option comes back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, status
from sqlalchemy import select as sa_select
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import rules as rule_catalog
from app.core.rules import SignInRequirement
from app.core.audit_events import AuditEventType
from app.core.login_methods import (
    FACTOR_METHODS,
    PRIMARY_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
    methods_from_values,
)
from app.core.guild_auth_options import CommunityAuthOption
from app.core.messages import AuthMessages, GuildMessages, SettingsMessages
from app.core.security import AUTH_POLICY_UNMET_HEADER, has_usable_password
from app.models.platform.app_setting import AppSetting
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild import Guild
from app.models.platform.rule import CommunityRule
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.models.platform.user_totp import UserTotp
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import guild_provider_connections as guild_connections
from app.services.auth import identity as identity_service
from app.services.auth.platform_provider import is_login_ready
from app.services.platform import app_settings as app_settings_service
from app.services.platform import guild_entitlements
from app.services.platform import guilds as guilds_service
from app.services.platform import push_tokens
from app.services.platform import rules as rules_service
from app.services.platform.app_settings import GLOBAL_SETTINGS_ID

logger = logging.getLogger(__name__)


def methods_from_row(row: AppSetting) -> frozenset[LoginMethod]:
    """The sign-in methods one ``app_settings`` row permits.

    Never empty. The column is constrained non-empty and the write path refuses
    to empty it; should this read one anyway, it resolves to the default set.
    Conservative for a *gate* and conservative for an *account* point opposite
    ways here, and this resolves in the account's favour.

    Pure, so a caller that already holds the settings row does not fetch it
    twice; :func:`resolve_login_methods` is the form for callers that do not.
    """
    return methods_from_values(row.login_methods)


async def resolve_login_methods(session: AsyncSession) -> frozenset[LoginMethod]:
    """The sign-in methods this deployment permits. See :func:`methods_from_row`."""
    return methods_from_row(await app_settings_service.get_app_settings(session))


async def login_method_allowed(session: AsyncSession, method: LoginMethod) -> bool:
    """Whether one method may be used to open a session right now."""
    return method in await resolve_login_methods(session)


async def password_confirms(session: AsyncSession, user: User) -> bool:
    """Whether a confirmation asks this account for its password.

    It holds one, and this deployment signs people in with passwords. Where it
    does not, the password is not a way in, and a recent sign-in answers
    instead. What the settings surfaces read to decide whether to show the
    field.
    """
    return has_usable_password(user.hashed_password) and await login_method_allowed(
        session, LoginMethod.password
    )


def requirement_from_row(row: AppSetting) -> SecondFactorRequirement:
    """What this ``app_settings`` row asks of an account.

    Pure, so a caller holding the row does not fetch it twice. A value this
    version does not recognise reads as ``nobody``: the column is a database
    enum, so that can only be a row written by a later version, and asking for
    something this one cannot describe is worse than asking for nothing.
    """
    try:
        return SecondFactorRequirement(row.second_factor_requirement)
    except ValueError:
        return SecondFactorRequirement.nobody


async def second_factor_requirement(session: AsyncSession) -> SecondFactorRequirement:
    """What this deployment asks of an account. See :func:`requirement_from_row`."""
    return requirement_from_row(await app_settings_service.get_app_settings(session))


def rule_covers(level: SecondFactorRequirement, role: UserRole) -> bool:
    """Whether ``level`` asks this account for a second factor.

    The rung is the whole distinction: ``platform_roles`` means everybody above
    ``member`` on the ladder in :mod:`app.core.capabilities`, which is the one
    fact the database re-derives for itself from ``app.platform_role``.
    """
    if level is SecondFactorRequirement.everyone:
        return True
    return (
        level is SecondFactorRequirement.platform_roles and role is not UserRole.member
    )


def _holds_a_factor_clause():
    """Accounts holding a second factor: a confirmed authenticator, or a key.

    Either answers the deployment, which asks only that the account has one —
    unlike a community, which names the method it wants and reads what the
    session presented.
    """
    return (
        select(UserTotp.user_id)
        .where(UserTotp.user_id == User.id, UserTotp.confirmed_at.is_not(None))
        .exists()
        | select(UserPasskey.id).where(UserPasskey.user_id == User.id).exists()
    )


async def holds_second_factor(session: AsyncSession, *, user_id: int) -> bool:
    """Whether this account holds a second factor of its own.

    On the system engine: both credential stores are ``app_admin``-only.
    """
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.id == user_id, _holds_a_factor_clause())
        )
    )


def _without_factor_clause(level: SecondFactorRequirement):
    """Accounts ``level`` would ask to set one up.

    Live accounts the level covers that hold neither an authenticator nor a
    key. Counted before the write, so an operator turning the rule on knows how
    many people meet it the next time they open the app.

    An account whose identity provider carries out the second factor is
    counted here and asked for nothing in practice: the session it arrives on
    says the factor was used, which answers the rule without a local one. The
    figure is therefore the most it could be, which is the honest direction
    for a warning.
    """
    clause = (User.status == UserStatus.active) & ~_holds_a_factor_clause()
    if level is SecondFactorRequirement.platform_roles:
        clause = clause & (User.role != UserRole.member)
    return clause


#: The levels the settings page states a figure for. ``nobody`` asks nothing.
_FACTOR_LEVELS = (
    SecondFactorRequirement.platform_roles,
    SecondFactorRequirement.everyone,
)


async def account_figures(
    session: AsyncSession, *, permitted: frozenset[LoginMethod]
) -> tuple[dict[LoginMethod, int], dict[SecondFactorRequirement, int]]:
    """What the settings page states about accounts, in one pass over them.

    How many accounts withdrawing each permitted method would leave with no way
    in (:func:`app.services.auth.identity.stranded_clause`) — a method not
    permitted strands nobody — and how many each level of the second-factor
    rule would ask to set one up.
    """
    withdrawable = [method for method in LoginMethod if method in permitted]
    columns = [
        func.count().filter(
            identity_service.stranded_clause(
                current=permitted, requested=permitted - {method}
            )
        )
        for method in withdrawable
    ] + [func.count().filter(_without_factor_clause(level)) for level in _FACTOR_LEVELS]
    row = (await session.exec(sa_select(*columns).select_from(User))).one()
    stranding = dict.fromkeys(LoginMethod, 0) | dict(zip(withdrawable, row))
    return stranding, dict(zip(_FACTOR_LEVELS, row[len(withdrawable) :]))


#: The rule keys that hold a community's sign-in requirements.
_REQUIREMENTS = ("auth_policy", "guest_auth_policy")


async def guilds_requiring_sign_in(session: AsyncSession) -> int:
    """How many guilds require a sign-in of their own.

    A requirement is enforced from its rule alone — the gate in ``deps.py``
    and ``public.guild_auth_satisfied()`` read nothing else — so it stands
    whatever happens to the route that satisfies it. Counted before single
    sign-on is withdrawn for that reason.

    A requirement of its members or of its guests counts. It names a provider,
    or a way in, or both, and a table constraint is what makes that list
    complete — so this stays right when a third thing becomes requirable,
    rather than quietly skipping it.
    """
    return (
        await session.exec(
            select(func.count(func.distinct(CommunityRule.guild_id))).where(
                CommunityRule.key.in_(_REQUIREMENTS),  # type: ignore[attr-defined]
                CommunityRule.user_id.is_(None),  # type: ignore[union-attr]
            )
        )
    ).one()


async def guilds_requiring_method(session: AsyncSession, method: LoginMethod) -> int:
    """How many communities ask for this particular method.

    Narrower than :func:`guilds_requiring_sign_in`, which counts every rule
    that is not open because withdrawing single sign-on can undo a rule that
    names a provider as well as one that names the method. Asking for a second
    factor is only ever named, so only the rules that name it are at stake.
    """
    return (
        await session.exec(
            select(func.count(func.distinct(CommunityRule.guild_id))).where(
                CommunityRule.key.in_(_REQUIREMENTS),  # type: ignore[attr-defined]
                CommunityRule.user_id.is_(None),  # type: ignore[union-attr]
                CommunityRule.methods.contains([method.value]),  # type: ignore[union-attr]
            )
        )
    ).one()


async def stranded_between(
    session: AsyncSession,
    *,
    current: frozenset[LoginMethod],
    requested: frozenset[LoginMethod],
) -> int:
    """How many accounts can sign in under ``current`` and could not under
    ``requested``.

    Both sets in one question, so an account holding two credentials is
    counted for the pair of methods going together as well as for either alone.

    ``totp`` never moves this figure: a second factor accompanies a sign-in
    rather than beginning one, so withdrawing it leaves every account able to
    sign in exactly as it did. What it does do is stop the factor being asked
    for, which the surface says plainly.
    """
    return await identity_service.stranded_between(
        session, current=current, requested=requested
    )


async def second_factor_available(session: AsyncSession) -> bool:
    """Whether this deployment offers a second factor at all.

    What a community's own requirement is offered against: with no kind of
    factor permitted here, there is nothing for anybody to be asked to hold,
    so the question is not put.
    """
    permitted = await resolve_login_methods(session)
    return any(method in permitted for method in FACTOR_METHODS)


async def hold_settings_for_read(session: AsyncSession) -> AppSetting:
    """The settings row under a shared lock, for a write that depends on what it
    says staying true until that write commits.

    Shared locks do not block each other, so concurrent guild admins proceed
    normally; only a write to this row waits.
    """
    await app_settings_service.ensure_settings_row(session)
    return (
        await session.exec(
            select(AppSetting)
            .where(AppSetting.id == GLOBAL_SETTINGS_ID)
            .with_for_update(read=True)
        )
    ).one()


async def answers_the_rule(session: AsyncSession, *, user: User) -> bool:
    """Whether this request's account answers the deployment's rule.

    Two ways, and either will do: the account holds a factor of its own, or
    this session presented one — which is what an identity provider's own
    second factor looks like from here, an account holding nothing locally.

    Read fresh rather than from the request context, which the gate fills in
    only where the rule applies: a write that turns the rule *on* has to know
    the answer before there is a rule to have gated anything.
    """
    from app.core import auth_context
    from app.services.auth.assurance import SECOND_FACTOR_AMR

    if SECOND_FACTOR_AMR in auth_context.current().session_amr:
        return True
    return await holds_second_factor(session, user_id=user.id)


# ---------------------------------------------------------------------------
# Writing a rule
# ---------------------------------------------------------------------------


def not_offered(unmet: str | None = None) -> HTTPException:
    """Refuse a rule nothing the deployment permits could answer."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=AuthMessages.AUTH_RULE_NOT_OFFERED,
        headers={AUTH_POLICY_UNMET_HEADER: unmet} if unmet else None,
    )


def self_unsatisfied(unmet: str) -> HTTPException:
    """Refuse a rule its writer does not answer, naming the part they don't."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.AUTH_RULE_SELF_UNSATISFIED,
        headers={AUTH_POLICY_UNMET_HEADER: unmet},
    )


@dataclass
class RuleContext:
    """One change: the sessions it runs on, who makes it, and the rows it holds.

    ``session`` writes the rules' rows: the system engine for the deployment's,
    the seat for a community's. ``system`` reads what the deployment permits
    and runs the follow-ups; for the deployment's rules it is ``session``.
    ``actor`` is ``None`` for the system, which only ever loosens.
    """

    session: AsyncSession
    system: AsyncSession
    actor: User | None
    guild_id: int | None = None
    #: The stranded-account count the writer was shown (``login_methods``).
    acknowledge_stranded: int | None = None
    settings: AppSetting = field(init=False)
    guild: Guild = field(init=False)
    #: The layer's stored rules as written, whether or not each applies.
    rules: dict[str, Any] = field(default_factory=dict, init=False)
    stranded: int = field(default=0, init=False)

    @classmethod
    def platform(
        cls,
        session: AsyncSession,
        actor: User,
        *,
        acknowledge_stranded: int | None = None,
    ) -> RuleContext:
        return cls(session, session, actor, acknowledge_stranded=acknowledge_stranded)

    @classmethod
    def community(
        cls,
        session: AsyncSession,
        system: AsyncSession,
        actor: User | None,
        guild_id: int,
    ) -> RuleContext:
        return cls(session, system, actor, guild_id=guild_id)


FollowUp = Callable[[RuleContext, Any, Any], Awaitable[None]]


@dataclass(frozen=True)
class Rule:
    """One rule, as :func:`change` writes it.

    The base is a stored rule (``app.core.rules``) of the deployment or of
    the community: ``loose`` is its most permissive value, which is also its
    default, ``None`` for a limit where no limit is the loosest. Rules stored
    anywhere else override the hooks.
    """

    key: str
    area: str
    loose: Any = None
    entitlement: CommunityAuthOption | None = None
    follow_up: FollowUp | None = None

    async def read(self, ctx: RuleContext) -> Any:
        return ctx.rules[self.key]

    def tightens(self, before: Any, after: Any) -> bool:
        if self.loose is None:
            return after is not None and (before is None or after < before)
        return before == self.loose and after != self.loose

    async def offered(self, ctx: RuleContext, after: Any) -> None:
        """Refuse a tightening the deployment permits nothing to answer."""

    async def writer_meets(self, ctx: RuleContext, after: Any) -> None:
        """Refuse a tightening its writer does not answer themselves."""

    async def check(self, ctx: RuleContext, before: Any, after: Any) -> None:
        """Refusals of this rule's own, asked of every change to it."""

    async def write(self, ctx: RuleContext, after: Any) -> None:
        await rules_service.put(ctx.session, self.key, after, guild_id=ctx.guild_id)
        ctx.rules[self.key] = after

    async def audit(self, ctx: RuleContext, moved: dict[str, tuple[Any, Any]]) -> None:
        """Record this rule's area: every column rule in it that moved, once."""
        names = [k for k, rule in _rules(ctx).items() if rule.area == self.area]
        if self.key != next(k for k in names if k in moved):
            return
        await audit_service.record_settings_change(
            ctx.session,
            guild_id=ctx.guild_id,
            actor_user_id=ctx.actor.id if ctx.actor else None,
            area=self.area,
            before={k: moved[k][0] for k in names if k in moved},
            after={k: moved[k][1] for k in names if k in moved},
        )


async def _drop_push_tokens(ctx: RuleContext, before: Any, after: Any) -> None:
    # The deployment stops keeping the addresses it was sending to. Devices
    # register again the next time the app starts, once push is back on.
    if before and not after:
        dropped = await push_tokens.purge_all(ctx.system)
        logger.info("push notifications switched off; dropped %d token(s)", dropped)


@dataclass(frozen=True)
class _LoginMethods(Rule):
    """Which ways in the deployment permits. At least one, and one of them a
    way to begin a session; the column's own constraint holds both.

    Its refusals are its own, asked of every change. Permitting the emailed
    code asks that the deployment can send mail. Withdrawing a method that a
    community's requirement names, or the last factor method while the
    deployment asks for a factor, is refused: that rule is lifted first and
    the withdrawal then goes through. A write that leaves somebody with no way
    in is refused with the count, unless the writer acknowledges exactly that
    number; the writer's own account is refused outright, and adds another way
    in first. Withdrawing a method signs nobody out.
    """

    async def read(self, ctx: RuleContext) -> frozenset[LoginMethod]:
        return methods_from_row(ctx.settings)

    def tightens(self, before: Any, after: Any) -> bool:
        return bool(before - after)

    async def check(self, ctx: RuleContext, before: Any, after: Any) -> None:
        session = ctx.session
        if not after:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=SettingsMessages.LOGIN_METHODS_EMPTY,
            )
        if not after.intersection(PRIMARY_LOGIN_METHODS):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=SettingsMessages.LOGIN_METHODS_NO_PRIMARY,
            )
        withdrawn = before - after
        # Checked on the way up only: an operator who later clears the SMTP
        # settings is told by the send route, at the moment it cannot send.
        if LoginMethod.email_otp in after - before and not (
            await email_service.email_configured(session)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_NO_EMAIL,
            )
        # ``sso`` counts every rule that is not open, since a rule naming a
        # provider rests on it too; the factor methods count the rules that
        # name them.
        for method in sorted(withdrawn & _COMMUNITY_REQUIRABLE):
            requiring = await (
                guilds_requiring_sign_in(session)
                if method is LoginMethod.sso
                else guilds_requiring_method(session, method)
            )
            if requiring:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=SettingsMessages.LOGIN_METHODS_GUILD_POLICIES,
                    headers={"X-Affected-Count": str(requiring)},
                )
        if (
            withdrawn.intersection(FACTOR_METHODS)
            and not after.intersection(FACTOR_METHODS)
            and requirement_from_row(ctx.settings) is not SecondFactorRequirement.nobody
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_FACTOR_REQUIRED,
            )
        if ctx.actor is not None and await identity_service.stranded_between(
            session, current=before, requested=after, user_id=ctx.actor.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_WOULD_STRAND_SELF,
            )
        ctx.stranded = await stranded_between(session, current=before, requested=after)
        if ctx.stranded and ctx.acknowledge_stranded != ctx.stranded:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    SettingsMessages.LOGIN_METHODS_WOULD_STRAND
                    if ctx.acknowledge_stranded is None
                    else SettingsMessages.LOGIN_METHODS_STALE_ACKNOWLEDGEMENT
                ),
                headers={"X-Affected-Count": str(ctx.stranded)},
            )

    async def write(self, ctx: RuleContext, after: Any) -> None:
        ctx.settings.login_methods = sorted(m.value for m in after)
        ctx.session.add(ctx.settings)

    async def audit(self, ctx: RuleContext, moved: dict[str, tuple[Any, Any]]) -> None:
        before, after = moved[self.key]
        await audit_service.record(
            ctx.session,
            event_type=AuditEventType.PLATFORM_LOGIN_METHODS_CHANGED,
            actor_user_id=ctx.actor.id if ctx.actor else None,
            detail={
                "from": sorted(m.value for m in before),
                "to": sorted(m.value for m in after),
                "acknowledged_stranded": ctx.stranded or None,
            },
        )


#: The methods a community's requirement can name.
_COMMUNITY_REQUIRABLE = frozenset(
    {LoginMethod.sso, LoginMethod.totp, LoginMethod.passkey}
)

_FACTOR_ORDER = {
    SecondFactorRequirement.nobody: 0,
    SecondFactorRequirement.platform_roles: 1,
    SecondFactorRequirement.everyone: 2,
}


@dataclass(frozen=True)
class _FactorRequirement(Rule):
    """Who the deployment asks to hold a second factor. Nobody is signed out:
    an account the rule covers is asked at its next request."""

    async def read(self, ctx: RuleContext) -> SecondFactorRequirement:
        return requirement_from_row(ctx.settings)

    def tightens(self, before: Any, after: Any) -> bool:
        return _FACTOR_ORDER[after] > _FACTOR_ORDER[before]

    async def offered(self, ctx: RuleContext, after: Any) -> None:
        if not methods_from_row(ctx.settings).intersection(FACTOR_METHODS):
            raise not_offered()

    async def writer_meets(self, ctx: RuleContext, after: Any) -> None:
        if (
            ctx.actor is not None
            and rule_covers(after, ctx.actor.role)
            and not await answers_the_rule(ctx.system, user=ctx.actor)
        ):
            raise self_unsatisfied(LoginMethod.totp.value)

    async def write(self, ctx: RuleContext, after: Any) -> None:
        ctx.settings.second_factor_requirement = after
        ctx.session.add(ctx.settings)

    async def audit(self, ctx: RuleContext, moved: dict[str, tuple[Any, Any]]) -> None:
        before, after = moved[self.key]
        await audit_service.record(
            ctx.session,
            event_type=AuditEventType.PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED,
            actor_user_id=ctx.actor.id if ctx.actor else None,
            detail={"from": before.value, "to": after.value},
        )


_OPEN = SignInRequirement()

#: The methods of a requirement that are a second factor rather than a way in.
_FACTOR_REQUIREMENTS = frozenset({LoginMethod.totp, LoginMethod.passkey})


@dataclass(frozen=True)
class _SignInRequirement(Rule):
    """The community's sign-in requirement, of its members or, with ``guest``,
    of its guests.

    The provider or single sign-on it names applies whatever the community
    holds, and clearing it is always reachable: lifting a requirement only
    ever admits more. The second factor it asks for applies only while the
    community holds ``providers``.
    """

    guest: bool = False

    def tightens(self, before: Any, after: Any) -> bool:
        return after.policy == "required" and (
            before.policy == "open"
            or after.provider_id not in (None, before.provider_id)
            or not after.methods <= before.methods
        )

    async def check(self, ctx: RuleContext, before: Any, after: Any) -> None:
        if (
            after.policy == "required"
            and after.provider_id is None
            and not after.methods
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildMessages.COMMUNITY_AUTH_POLICY_INVALID_PROVIDER,
            )

    async def offered(self, ctx: RuleContext, after: Any) -> None:
        # A provider is this community's to require because it connects to it.
        if after.provider_id is not None:
            provider = await ctx.system.get(AuthProvider, after.provider_id)
            if (
                provider is None
                or not is_login_ready(provider)
                or await guild_connections.connection_for(
                    ctx.system, guild_id=ctx.guild_id, provider_id=provider.id
                )
                is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=GuildMessages.COMMUNITY_AUTH_POLICY_INVALID_PROVIDER,
                )
        for method in sorted(after.methods & _FACTOR_REQUIREMENTS):
            if not await login_method_allowed(ctx.system, method):
                raise not_offered(method.value)
        # The members' rule is met by its writer before it is written, which
        # shows the community's own single sign-on works. A guests' rule is
        # not, so the sign-on it asks for has to be offered and connected.
        if (
            self.guest
            and LoginMethod.sso in after.methods
            and not (
                await login_method_allowed(ctx.system, LoginMethod.sso)
                and await guild_connections.connected_providers(
                    ctx.system, guild_id=ctx.guild_id
                )
            )
        ):
            raise not_offered(LoginMethod.sso.value)

    async def writer_meets(self, ctx: RuleContext, after: Any) -> None:
        from app.core import auth_context
        from app.services.auth.assurance import SECOND_FACTOR_AMR, carries_passkey

        # Whoever writes the guests' rule is not a guest, and is not asked it.
        if self.guest:
            return
        recorded = auth_context.current()
        amr = recorded.session_amr
        if (
            after.provider_id is not None
            and after.provider_id not in recorded.satisfied_providers
        ):
            raise self_unsatisfied("provider")
        # Coming in by any of the community's own providers is also proof it
        # has one that works.
        if LoginMethod.sso in after.methods and not (
            await guild_connections.admits_this_session(
                ctx.system, guild_id=ctx.guild_id
            )
        ):
            raise self_unsatisfied(LoginMethod.sso.value)
        if LoginMethod.totp in after.methods and SECOND_FACTOR_AMR not in amr:
            raise self_unsatisfied(LoginMethod.totp.value)
        # Read from the passkey markers, so holding a factor is not taken for
        # holding a key.
        if LoginMethod.passkey in after.methods and not carries_passkey(amr):
            raise self_unsatisfied(LoginMethod.passkey.value)

    async def audit(self, ctx: RuleContext, moved: dict[str, tuple[Any, Any]]) -> None:
        before, after = moved[self.key]
        await audit_service.record(
            ctx.session,
            event_type=AuditEventType.GUILD_AUTH_POLICY_CHANGED,
            actor_user_id=ctx.actor.id if ctx.actor else None,
            guild_id=ctx.guild_id,
            target_type="guild",
            target_id=ctx.guild_id,
            detail={
                "from": before.policy,
                "to": after.policy,
                "provider_id": after.provider_id,
                "require_methods": sorted(m.value for m in after.methods),
                **({"of": "guests"} if self.guest else {}),
            },
        )


@dataclass(frozen=True)
class _CommunityFactor(Rule):
    """A community asking everybody reaching it for a second factor. Which
    kinds exist, and which providers' own account of one counts, is the
    deployment's answer."""

    async def offered(self, ctx: RuleContext, after: Any) -> None:
        if not await second_factor_available(ctx.system):
            raise not_offered()

    async def writer_meets(self, ctx: RuleContext, after: Any) -> None:
        if ctx.actor is not None and not await answers_the_rule(
            ctx.system, user=ctx.actor
        ):
            raise self_unsatisfied(LoginMethod.totp.value)


def _platform(key: str, area: str, follow_up: FollowUp | None = None) -> Rule:
    """A stored rule of the deployment, its loosest value its default."""
    stored = rule_catalog.PLATFORM_RULES[key]
    return Rule(key, area=area, loose=stored.default, follow_up=follow_up)


def _community(key: str, area: str, cls: type[Rule] = Rule) -> Rule:
    """A stored rule of a community, with the option it needs."""
    stored = rule_catalog.COMMUNITY_RULES[key]
    return cls(key, area=area, loose=stored.default, entitlement=stored.entitlement)


#: The deployment's rules, by the field that names each.
PLATFORM_RULES: dict[str, Rule] = {
    rule.key: rule
    for rule in (
        _LoginMethods("login_methods", area="login_methods"),
        _FactorRequirement("second_factor_requirement", area="second_factor"),
        _platform("session_max_hours", "session_lifetime"),
        _platform("session_idle_minutes", "session_lifetime"),
        _platform(
            "push_notifications_enabled",
            "notifications",
            follow_up=_drop_push_tokens,
        ),
        _platform("email_notifications_enabled", "notifications"),
        _platform("redact_notification_content", "notifications"),
        _platform("engagement_ranking_enabled", "engagement_ranking"),
        _platform("cookie_consent_enabled", "cookie_consent"),
        _platform("community_directory_enabled", "community"),
        _platform("community_age_gate_enabled", "community"),
        _platform("direct_messages_enabled", "community"),
        # Guests made or extended after the ceiling changes are held to it.
        _platform("guests_enabled", "community"),
        _platform("max_guest_days", "community"),
        # Each window is counted from each deletion or hold, so changing one
        # moves the date for every row already waiting.
        *(
            _platform(key, "community")
            for window in rule_catalog.RETENTION_WINDOWS.items()
            for key in window
        ),
        _platform("marketplace_members_publish_directly", "marketplace"),
        _platform("marketplace_registry_enabled", "marketplace_registry"),
    )
}

#: A community's rules, by the field that names each.
COMMUNITY_RULES: dict[str, Rule] = {
    rule.key: rule
    for rule in (
        _SignInRequirement(
            "auth_policy", area="auth_policy", entitlement=CommunityAuthOption.providers
        ),
        _SignInRequirement(
            "guest_auth_policy",
            area="guest_auth_policy",
            entitlement=CommunityAuthOption.providers,
            guest=True,
        ),
        _community("require_second_factor", "second_factor", _CommunityFactor),
        _community("enforce_compliance_session", "session_limit"),
        _community("allow_push_notifications", "notifications"),
        _community("allow_email_notifications", "notifications"),
        _community("redact_notification_content", "notifications"),
        _community("allow_engagement_ranking", "engagement_ranking"),
        _community("allow_ai", "ai"),
        # The longest a guest may stay. It bounds the guests made or extended
        # after it changes, and no others.
        _community("guest_max_days", "guests"),
    )
}


def _rules(ctx: RuleContext) -> dict[str, Rule]:
    return PLATFORM_RULES if ctx.guild_id is None else COMMUNITY_RULES


async def _load(ctx: RuleContext) -> None:
    """Take the rows the rules read: the settings row, held, and the stored
    rules for the deployment's; the community's row and its stored rules for a
    community's."""
    if ctx.guild_id is None:
        ctx.settings = await app_settings_service.locked_settings(ctx.session)
        ctx.rules = await rules_service.platform_values(ctx.session)
        return
    guild = await ctx.session.get(Guild, ctx.guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_NOT_FOUND,
        )
    ctx.guild = guild
    ctx.rules = (
        await rules_service.community_values(ctx.session, [ctx.guild_id], applied=False)
    )[ctx.guild_id]


async def change(ctx: RuleContext, changes: dict[str, Any]) -> None:
    """Write ``changes`` (rule key → new value) as one change, and commit."""
    rules = _rules(ctx)
    if ctx.guild_id is not None:
        # Before the rows are read, so two changes to the same community, its
        # two sign-in halves included, take turns rather than each writing
        # back what it read.
        await guilds_service.lock_guild_seats(ctx.session, ctx.guild_id)
    await _load(ctx)
    moved: dict[str, tuple[Any, Any]] = {}
    for key, value in changes.items():
        before = await rules[key].read(ctx)
        if value != before:
            moved[key] = (before, value)
    tightening = {k for k, (b, a) in moved.items() if rules[k].tightens(b, a)}

    if ctx.guild_id is not None and tightening:
        # Ordered against a withdrawal of what the rule rests on, and against
        # the seat being emptied while a rule nobody could lift is set.
        await hold_settings_for_read(ctx.system)
        await guilds_service.lock_guild_seats(ctx.session, ctx.guild_id)

    for key in sorted(moved, key=lambda k: k in tightening):
        rule, (before, after) = rules[key], moved[key]
        await rule.check(ctx, before, after)
        if key in tightening:
            if rule.entitlement is not None:
                await guild_entitlements.require_auth_option(
                    ctx.system, ctx.guild_id, rule.entitlement
                )
            await rule.offered(ctx, after)
            await rule.writer_meets(ctx, after)
        await rule.write(ctx, after)
    for key in moved:
        await rules[key].audit(ctx, moved)
    # The deployment's follow-ups land in the change's own transaction. A
    # community's run on the system engine, which reads what the seat wrote,
    # so the seat's write is committed first.
    if ctx.system is not ctx.session:
        await ctx.session.commit()
    for key, (before, after) in moved.items():
        follow_up = rules[key].follow_up
        if follow_up is not None:
            await follow_up(ctx, before, after)
    await ctx.system.commit()
