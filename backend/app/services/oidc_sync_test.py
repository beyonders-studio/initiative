"""Claim sync: a user's first arrival in a guild beside auto-join enrolment,
and leaving a tenant whose rules no longer grant a membership."""

from datetime import UTC

import pytest
from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rules import SetBy
from app.db import cohorts, post_commit
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.oidc_claim_mapping import (
    ClaimRuleAuthor,
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.models.platform.platform_provider_default import PlatformProviderDefault
from app.models.tenant.claim_rule_initiative import ClaimRuleInitiative
from app.models.tenant.custom_role import (
    CustomRole,
    CustomRoleClaimRule,
    CustomRoleMember,
)
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.services import oidc_sync
from app.services.oidc_sync import sync_oidc_assignments
from app.services.platform import provider_placement, rules
from app.services.tenant import custom_roles as custom_roles_service
from app.services.tenant import plugin_revocation
from app.services.tenant.initiatives import get_role_by_name
from app.testing.factories import (
    NARROWED_CLAIM,
    NARROWED_VALUE,
    create_auth_provider,
    create_claim_rule,
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_guild_provider_connection,
    create_initiative,
    create_plugin_user_connection,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild

#: What an arrival from the tenant the factory's connections narrow to carries.
_ADMITTED = {NARROWED_CLAIM: NARROWED_VALUE}


async def _membership(
    session: AsyncSession, *, guild_id: int, initiative_id: int, user_id: int
) -> InitiativeMember | None:
    session.expunge_all()
    await set_rls_context(session, SystemGuild(guild_id))
    return (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative_id,
                InitiativeMember.user_id == user_id,
            )
        )
    ).one_or_none()


@pytest.mark.parametrize(
    "on_arrival",
    [
        pytest.param(False, id="the rule admits them"),
        pytest.param(True, id="the connection joins them on arrival"),
    ],
)
async def test_claim_mapped_role_survives_auto_join(
    session: AsyncSession, on_arrival: bool
):
    """A mapped role wins over the plain membership auto-join would write.

    Both apply to the same initiative on the same first arrival. Enrolment runs
    after the mapping for this reason: it writes a non-oidc-managed row, and the
    mapping loop leaves those alone by design, so enrolling first would silently
    strand a manager on the member role. A community its connection joins the
    person to on arrival is enrolled by the sync too, after the rules.
    """
    from app.services.auth.guild_provider_connections import join_on_arrival

    provider = await create_auth_provider(session)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(
        session, guild, owner, name="Onboarding", join_policy="open", auto_join=True
    )
    pm_role = await get_role_by_name(
        session, initiative_id=initiative.id, role_name="project_manager"
    )
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, auto_join=on_arrival
    )

    newcomer = await create_user(session)
    await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        claim_value="engineering",
        initiative=initiative,
        initiative_role_id=pm_role.id,
    )

    await set_rls_context(session, Unattributed())
    arrived = []
    if on_arrival:
        arrived = await join_on_arrival(
            session,
            provider_id=provider.id,
            user_id=newcomer.id,
            claims=_ADMITTED,
            auto_join=False,
        )
        await post_commit.settle(session)
        assert arrived == [guild.id]
    await sync_oidc_assignments(
        session,
        user_id=newcomer.id,
        provider_id=provider.id,
        claim_values={"engineering"},
        claims=_ADMITTED,
        arrived=arrived,
    )
    await session.commit()

    membership = await _membership(
        session, guild_id=guild.id, initiative_id=initiative.id, user_id=newcomer.id
    )
    assert membership is not None
    # The claim's role, not the built-in member role enrolment hands out.
    assert membership.role_id == pm_role.id
    assert membership.oidc_provider_id == provider.id


async def _guild_rule(session: AsyncSession, *, provider_id: int, guild_id: int):
    session.add(
        OIDCClaimMapping(
            provider_id=provider_id,
            claim_value="staff",
            target_type=OIDCMappingTargetType.guild,
            guild_id=guild_id,
            guild_role=CommunityRole.member.value,
        )
    )


async def _joined(session: AsyncSession, user_id: int) -> set[int]:
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    return set(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )


async def _sync(session: AsyncSession, *, user_id: int, provider_id: int, claims):
    await set_rls_context(session, Unattributed())
    result = await sync_oidc_assignments(
        session,
        user_id=user_id,
        provider_id=provider_id,
        claim_values={"staff"},
        claims=claims,
    )
    await session.commit()
    return result


async def test_a_rule_lands_where_its_community_counts_the_arrival_as_its_own(
    session: AsyncSession,
):
    """A rule speaks for the arrivals its community's connection admits.

    Three communities hold a rule for the same group on one provider: one whose
    connection admits this tenant, one whose connection names another tenant,
    and one with no connection at all. Only the first places the person."""
    owner = await create_user(session)
    home = await create_guild(session, creator=owner)
    other_tenant = await create_guild(session, creator=owner)
    unconnected = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="tenant")
    await create_guild_provider_connection(session, guild=home, provider=provider)
    await create_guild_provider_connection(
        session,
        guild=other_tenant,
        provider=provider,
        claim_values=["elsewhere.example"],
    )

    newcomer = await create_user(session)
    for guild_id in (home.id, other_tenant.id, unconnected.id):
        await _guild_rule(session, provider_id=provider.id, guild_id=guild_id)
    await session.commit()

    result = await _sync(
        session, user_id=newcomer.id, provider_id=provider.id, claims=_ADMITTED
    )

    assert result.guilds_added == [home.id]
    assert await _joined(session, newcomer.id) == {home.id}


async def test_a_community_that_has_not_connected_follows_the_deployment_default(
    session: AsyncSession,
):
    """The provider's default answers for a community with no connection of
    its own, and a community's own disabled connection declines it."""
    owner = await create_user(session)
    inheriting = await create_guild(session, creator=owner)
    declining = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="org")
    session.add(
        PlatformProviderDefault(
            provider_id=provider.id,
            claim=NARROWED_CLAIM,
            claim_values=[NARROWED_VALUE],
            enabled=True,
        )
    )
    await create_guild_provider_connection(
        session,
        guild=declining,
        provider=provider,
        claim=None,
        claim_values=None,
        enabled=False,
    )

    newcomer = await create_user(session)
    for guild_id in (inheriting.id, declining.id):
        await _guild_rule(session, provider_id=provider.id, guild_id=guild_id)
    await session.commit()

    await _sync(session, user_id=newcomer.id, provider_id=provider.id, claims=_ADMITTED)

    assert await _joined(session, newcomer.id) == {inheriting.id}


async def test_leaving_the_tenant_hands_back_what_its_rules_granted(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """The same group asserted for somebody the connection no longer admits
    releases the membership that provider's rules gave them, as leaving does:
    the plug-in credentials they connected there end with it."""
    revoked: list = []

    async def _capture(intents):
        revoked.extend(intents)

    monkeypatch.setattr(plugin_revocation, "dispatch_revocations", _capture)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    guild_id = guild.id
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    person = await create_user(session)
    person_id = person.id
    plugin = await create_guild_plugin(
        session,
        guild,
        owner,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.sync", "protocol": 1},
            "connections": [{"id": "github", "scope": "member"}],
        },
    )
    await create_plugin_user_connection(session, plugin, person)
    await _guild_rule(session, provider_id=provider.id, guild_id=guild_id)
    await session.commit()

    await _sync(session, user_id=person_id, provider_id=provider.id, claims=_ADMITTED)
    assert await _joined(session, person_id) == {guild_id}

    result = await _sync(
        session,
        user_id=person_id,
        provider_id=provider.id,
        claims={NARROWED_CLAIM: "elsewhere.example"},
    )
    await post_commit.settle_all()

    assert result.guilds_removed == [guild_id]
    assert await _joined(session, person_id) == set()
    await set_rls_context(session, SystemGuild(guild_id))
    assert (
        await session.exec(
            select(GuildPluginUserConnection).where(
                GuildPluginUserConnection.user_id == person_id
            )
        )
    ).all() == []
    assert [i.reason for i in revoked] == ["claim_sync"]


async def test_auto_join_still_covers_what_the_claims_do_not(session: AsyncSession):
    """Enrolment fills the gaps the mapping left, and only those."""
    provider = await create_auth_provider(session)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    mapped = await create_initiative(session, guild, owner, name="Mapped")
    unmapped = await create_initiative(
        session, guild, owner, name="Welcome", join_policy="open", auto_join=True
    )
    mapped_pm = await get_role_by_name(
        session, initiative_id=mapped.id, role_name="project_manager"
    )
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    newcomer = await create_user(session)
    await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        claim_value="engineering",
        initiative=mapped,
        initiative_role_id=mapped_pm.id,
    )

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=newcomer.id,
        provider_id=provider.id,
        claim_values={"engineering"},
        claims=_ADMITTED,
    )
    await session.commit()

    # The claim placed them here, at its own role.
    claimed = await _membership(
        session, guild_id=guild.id, initiative_id=mapped.id, user_id=newcomer.id
    )
    assert claimed is not None and claimed.role_id == mapped_pm.id
    # Nothing claimed this one, so arriving in the guild did.
    enrolled = await _membership(
        session, guild_id=guild.id, initiative_id=unmapped.id, user_id=newcomer.id
    )
    assert enrolled is not None
    # Enrolment's rows stay outside OIDC's remit, so its sweep never reaps them.
    assert enrolled.oidc_provider_id is None


async def test_one_providers_sign_in_leaves_anothers_memberships_alone(
    session: AsyncSession,
):
    """Two providers, one account, and a sign-in through each in turn.

    The sync both grants and reclaims, so a rule set that is not this
    provider's must reach neither half: signing in through one must not read
    the other's rules, and must not take back what the other's rules gave.
    """
    from app.models.platform.guild import GuildMembership

    corp = await create_auth_provider(session, slug="corp")
    partner = await create_auth_provider(session, slug="partner")

    owner = await create_user(session)
    corp_guild = await create_guild(session, creator=owner, name="Corp")
    partner_guild = await create_guild(session, creator=owner, name="Partner")
    await create_guild_provider_connection(session, guild=corp_guild, provider=corp)
    await create_guild_provider_connection(
        session, guild=partner_guild, provider=partner
    )

    person = await create_user(session)
    session.add(
        OIDCClaimMapping(
            provider_id=corp.id,
            claim_value="staff",
            target_type=OIDCMappingTargetType.guild,
            guild_id=corp_guild.id,
            guild_role=CommunityRole.member.value,
        )
    )
    session.add(
        OIDCClaimMapping(
            provider_id=partner.id,
            claim_value="vendors",
            target_type=OIDCMappingTargetType.guild,
            guild_id=partner_guild.id,
            guild_role=CommunityRole.member.value,
        )
    )
    await session.commit()

    async def _guild_ids() -> set[int]:
        session.expunge_all()
        await set_rls_context(session, Unattributed())
        rows = (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == person.id
                )
            )
        ).all()
        return set(rows)

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=corp.id,
        claim_values={"staff"},
        claims=_ADMITTED,
    )
    await session.commit()
    assert await _guild_ids() == {corp_guild.id}

    # The partner's claims admit them to the partner guild...
    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=partner.id,
        claim_values={"vendors"},
        claims=_ADMITTED,
    )
    await session.commit()
    assert await _guild_ids() == {corp_guild.id, partner_guild.id}

    # ...and signing in through the corporate provider again keeps both. Its
    # claims say nothing about the partner guild because its rules do not
    # mention it, which is not the same as saying the person does not belong.
    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=corp.id,
        claim_values={"staff"},
        claims=_ADMITTED,
    )
    await session.commit()
    assert await _guild_ids() == {corp_guild.id, partner_guild.id}


async def test_deleting_the_last_rule_hands_back_what_it_granted(
    session: AsyncSession,
):
    """A provider with no rules grants nothing, which is not the same as having
    nothing to take back. Its next sign-in releases what its rules had given."""
    from app.models.platform.guild import GuildMembership

    provider = await create_auth_provider(session, slug="corp")
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner, name="Corp")
    person = await create_user(session)
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    rule = OIDCClaimMapping(
        provider_id=provider.id,
        claim_value="staff",
        target_type=OIDCMappingTargetType.guild,
        guild_id=guild.id,
        guild_role=CommunityRole.member.value,
    )
    session.add(rule)
    await session.commit()

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=provider.id,
        claim_values={"staff"},
        claims=_ADMITTED,
    )
    await session.commit()

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    assert (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == person.id)
        )
    ).all()

    # The operator deletes the rule, and the next sign-in reconciles.
    await session.delete(await session.get(OIDCClaimMapping, rule.id))
    await session.commit()

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=provider.id,
        claim_values={"staff"},
        claims=_ADMITTED,
    )
    await session.commit()

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    assert not (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == person.id)
        )
    ).all()


async def test_stale_provider_claim_preserves_a_promoted_superadmin(
    session: AsyncSession,
):
    provider = await create_auth_provider(session, slug="corp")
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner, name="Corp")
    person = await create_user(session)
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    rule = OIDCClaimMapping(
        provider_id=provider.id,
        claim_value="staff",
        target_type=OIDCMappingTargetType.guild,
        guild_id=guild.id,
        guild_role=CommunityRole.member.value,
    )
    session.add(rule)
    await session.commit()

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=provider.id,
        claim_values={"staff"},
        claims=_ADMITTED,
    )
    await session.commit()

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == person.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one()
    membership.role = CommunityRole.superadmin
    session.add(membership)
    await session.delete(await session.get(OIDCClaimMapping, rule.id))
    await session.commit()

    await set_rls_context(session, Unattributed())
    result = await sync_oidc_assignments(
        session,
        user_id=person.id,
        provider_id=provider.id,
        claim_values={"staff"},
        claims=_ADMITTED,
    )

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    preserved = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == person.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one_or_none()
    assert preserved is not None
    assert preserved.role == CommunityRole.superadmin
    assert result.guilds_removed == []


@pytest.mark.parametrize(
    "listed,admitted",
    [
        pytest.param(True, False, id="a listed community keeps them out"),
        pytest.param(False, True, id="a private one admits them"),
    ],
)
async def test_claim_sync_keeps_an_under_age_answer_out_of_a_listed_guild(
    session: AsyncSession, listed: bool, admitted: bool
):
    """This is the way in with nobody at a keyboard to ask.

    A listed community is open to anyone signed in, so the deployment's age
    rule holds however somebody arrived — including a claim matching on a
    background refresh, hours after they last touched the app. What counts
    here is the answer already on the record, because there is no one to put
    the question to. A private guild is its own to answer for and admits them.
    """
    from datetime import datetime

    from app.services.platform import rules

    await rules.put(session, "community_directory_enabled", True)
    await rules.put(session, "community_age_gate_enabled", True)
    await session.commit()
    provider = await create_auth_provider(session)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    if listed:
        guild.is_community = True
        guild.categories = ["other"]
        guild.has_adult_content = False
        session.add(guild)
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    # The two are the two answers to one question, and ck_users_age_answer
    # holds them apart — so saying one is said is unsaying the other.
    newcomer = await create_user(session, age_confirmed_at=None)
    newcomer.age_below_minimum_at = datetime.now(UTC)
    session.add(newcomer)
    session.add(
        OIDCClaimMapping(
            provider_id=provider.id,
            claim_value="engineering",
            target_type=OIDCMappingTargetType.guild,
            guild_id=guild.id,
            guild_role=CommunityRole.member.value,
        )
    )
    await session.commit()

    await set_rls_context(session, Unattributed())
    await sync_oidc_assignments(
        session,
        user_id=newcomer.id,
        provider_id=provider.id,
        claim_values={"engineering"},
        claims=_ADMITTED,
    )

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == newcomer.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one_or_none()
    assert (membership is not None) is admitted


async def _provider_rule(
    session: AsyncSession, *, provider_id: int, guild_id: int, **kw
):
    session.add(
        OIDCClaimMapping(
            author=ClaimRuleAuthor.provider,
            provider_id=provider_id,
            target_type=OIDCMappingTargetType.guild,
            guild_id=guild_id,
            guild_role=CommunityRole.member.value,
            **{"claim_value": "staff", **kw},
        )
    )


async def test_a_provider_rule_places_where_the_community_accepts_it(
    session: AsyncSession,
):
    """The platform's rule reaches a community whose connection accepts the
    provider's rules, and none that has not."""
    owner = await create_user(session)
    accepting = await create_guild(session, creator=owner)
    declining = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="org")
    await create_guild_provider_connection(
        session, guild=accepting, provider=provider, accepts_provider_placement=True
    )
    await create_guild_provider_connection(session, guild=declining, provider=provider)
    newcomer = await create_user(session)
    for guild_id in (accepting.id, declining.id):
        await _provider_rule(session, provider_id=provider.id, guild_id=guild_id)
    await session.commit()

    await _sync(session, user_id=newcomer.id, provider_id=provider.id, claims={})

    assert await _joined(session, newcomer.id) == {accepting.id}


async def test_a_provider_rule_places_everywhere_when_the_deployment_says_so(
    session: AsyncSession,
):
    from app.services.platform import rules

    await rules.put(session, "provider_placement_everywhere", True)
    owner = await create_user(session)
    unconnected = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="org")
    newcomer = await create_user(session)
    await _provider_rule(session, provider_id=provider.id, guild_id=unconnected.id)
    await session.commit()

    await _sync(session, user_id=newcomer.id, provider_id=provider.id, claims={})

    assert await _joined(session, newcomer.id) == {unconnected.id}


async def test_a_provider_rule_naming_a_directory_places_only_its_arrivals(
    session: AsyncSession,
):
    """Behind a bridge, one provider signs in several directories. A rule
    naming one places the people from it — by group, or everybody from it
    where the rule names no group."""
    owner = await create_user(session)
    acme = await create_guild(session, creator=owner)
    everyone = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="bridge")
    for guild in (acme, everyone):
        await create_guild_provider_connection(
            session, guild=guild, provider=provider, accepts_provider_placement=True
        )
    await _provider_rule(
        session,
        provider_id=provider.id,
        guild_id=acme.id,
        scope_claim="idp",
        scope_value="acme-adfs",
    )
    await _provider_rule(
        session,
        provider_id=provider.id,
        guild_id=everyone.id,
        claim_value=None,
        scope_claim="idp",
        scope_value="acme-adfs",
    )
    from_acme = await create_user(session)
    from_elsewhere = await create_user(session)
    await session.commit()

    await _sync(
        session,
        user_id=from_acme.id,
        provider_id=provider.id,
        claims={"idp": "acme-adfs"},
    )
    await _sync(
        session,
        user_id=from_elsewhere.id,
        provider_id=provider.id,
        claims={"idp": "globex-okta"},
    )

    assert await _joined(session, from_acme.id) == {acme.id, everyone.id}
    assert await _joined(session, from_elsewhere.id) == set()


async def test_a_provider_rule_places_whatever_the_communitys_own_narrowing_says(
    session: AsyncSession,
):
    """A community that narrows a shared provider for its own rules still takes
    the arrivals a provider rule places, in its tenant or not: who a provider
    rule places is the operator's to say."""
    owner = await create_user(session)
    accepting = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="shared")
    await create_guild_provider_connection(
        session, guild=accepting, provider=provider, accepts_provider_placement=True
    )
    await _provider_rule(session, provider_id=provider.id, guild_id=accepting.id)
    out_of_tenant = await create_user(session)
    await session.commit()

    await _sync(
        session,
        user_id=out_of_tenant.id,
        provider_id=provider.id,
        claims={NARROWED_CLAIM: "elsewhere.example"},
    )

    assert await _joined(session, out_of_tenant.id) == {accepting.id}


async def test_the_first_role_rule_a_sign_in_matches_gives_its_role(
    session: AsyncSession,
):
    """A community's custom-role rules, in its own schema, are read in order:
    the first whose group the sign-in carries decides. A role somebody gave
    by hand is the claims' to leave alone."""
    owner = await create_user(session)
    home = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="tenant")
    await create_guild_provider_connection(session, guild=home, provider=provider)
    await _guild_rule(session, provider_id=provider.id, guild_id=home.id)
    newcomer = await create_user(session)
    await route_session_to_guild(session, home.id)
    doors = CustomRole(name="Doors", base_rung="member", surfaces=["invites"])
    roll = CustomRole(name="Roll", base_rung="member", surfaces=["members"])
    session.add_all([doors, roll])
    await session.flush()
    session.add_all(
        [
            CustomRoleClaimRule(
                provider_id=provider.id, claim_value="crew", role_id=roll.id, position=1
            ),
            CustomRoleClaimRule(
                provider_id=provider.id,
                claim_value="staff",
                role_id=doors.id,
                position=2,
            ),
        ]
    )
    await session.commit()
    home_id, provider_id, user_id = home.id, provider.id, newcomer.id

    async def sync(groups: set[str]) -> tuple[int, int | None]:
        await set_rls_context(session, Unattributed())
        await sync_oidc_assignments(
            session,
            user_id=user_id,
            provider_id=provider_id,
            claim_values=groups,
            claims=_ADMITTED,
        )
        await session.commit()
        session.expunge_all()
        await set_rls_context(session, SystemGuild(home_id))
        held = await session.get(CustomRoleMember, user_id)
        assert held is not None
        return held.role_id, held.oidc_provider_id

    assert await sync({"staff", "crew"}) == (roll.id, provider_id)
    assert await sync({"staff"}) == (doors.id, provider_id)

    await custom_roles_service.assign(session, user_id=user_id, role_id=roll.id)
    await session.commit()
    assert await sync({"staff"}) == (roll.id, None)


async def test_a_role_stays_until_a_sign_in_says_the_claim(session: AsyncSession):
    """A refresh can come back without the claim a community narrows by. Its
    custom-role rules live in its schema, out of the refresh guard's sight, so
    there the role is left as it is; a sign-in that carries the claim but not
    the group takes it back."""
    owner = await create_user(session)
    home = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="tenant")
    await create_guild_provider_connection(session, guild=home, provider=provider)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=home)
    await route_session_to_guild(session, home.id)
    doors = CustomRole(name="Doors", base_rung="member", surfaces=["invites"])
    session.add(doors)
    await session.flush()
    session.add(
        CustomRoleClaimRule(
            provider_id=provider.id, claim_value="staff", role_id=doors.id, position=1
        )
    )
    await session.commit()
    home_id, provider_id, user_id, doors_id = home.id, provider.id, member.id, doors.id

    async def sync(groups: set[str], claims: dict) -> int | None:
        await set_rls_context(session, Unattributed())
        await sync_oidc_assignments(
            session,
            user_id=user_id,
            provider_id=provider_id,
            claim_values=groups,
            claims=claims,
        )
        await session.commit()
        session.expunge_all()
        await set_rls_context(session, SystemGuild(home_id))
        held = await session.get(CustomRoleMember, user_id)
        return held.role_id if held is not None else None

    assert await sync({"staff"}, _ADMITTED) == doors_id
    assert await sync(set(), {}) == doors_id
    assert await sync(set(), _ADMITTED) is None


async def test_a_full_community_takes_nobody_new_from_its_rules(
    session: AsyncSession,
):
    """A seat is a seat however somebody arrives: at its cap, a community's
    rules place nobody new in it, nor in its initiatives, and the rest of the
    sign-in goes on."""
    owner = await create_user(session)
    full = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, full, owner)
    member_role = await get_role_by_name(
        session, initiative_id=initiative.id, role_name="member"
    )
    provider = await create_auth_provider(session, slug="tenant")
    await create_guild_provider_connection(session, guild=full, provider=provider)
    await create_claim_rule(
        session,
        provider=provider,
        guild=full,
        initiative=initiative,
        initiative_role_id=member_role.id,
    )
    await rules.put(session, "max_users", 1, guild_id=full.id, set_by=SetBy.deployment)
    newcomer = await create_user(session)
    await session.commit()
    full_id, initiative_id, user_id = full.id, initiative.id, newcomer.id

    result = await _sync(
        session, user_id=user_id, provider_id=provider.id, claims=_ADMITTED
    )

    assert result.guilds_added == []
    assert result.initiatives_added == []
    assert await _joined(session, user_id) == set()
    assert (
        await _membership(
            session, guild_id=full_id, initiative_id=initiative_id, user_id=user_id
        )
        is None
    )


async def test_a_rule_whose_initiative_is_deleted_places_in_the_community_alone(
    session: AsyncSession,
):
    """A rule's initiative is kept beside the initiative, in the community's
    schema, and goes when the initiative does: the rule then places people in
    the community and in no initiative."""
    provider = await create_auth_provider(session)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner, name="Gone")
    member_role = await get_role_by_name(
        session, initiative_id=initiative.id, role_name="member"
    )
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    rule = await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        initiative=initiative,
        initiative_role_id=member_role.id,
    )
    newcomer = await create_user(session)
    guild_id, initiative_id = guild.id, initiative.id
    rule_id, user_id = rule.id, newcomer.id

    await route_session_to_guild(session, guild_id)
    await session.exec(delete(Initiative).where(Initiative.id == initiative_id))
    await session.commit()
    assert await session.get(ClaimRuleInitiative, (rule_id, 0)) is None

    result = await _sync(
        session, user_id=user_id, provider_id=provider.id, claims=_ADMITTED
    )

    assert result.guilds_added == [guild_id]
    assert result.initiatives_added == []
    assert await _joined(session, user_id) == {guild_id}


async def test_a_rule_moved_during_a_sign_in_takes_nothing_away(
    session: AsyncSession, monkeypatch
):
    """A sign-in reads its rules, then each community's half reads where they
    place people. A rule moved twice in between has no row at the version the
    sign-in read: the person keeps their place, and the next sign-in decides."""
    provider = await create_auth_provider(session)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    member_role = await get_role_by_name(
        session, initiative_id=initiative.id, role_name="member"
    )
    manager_role = await get_role_by_name(
        session, initiative_id=initiative.id, role_name="project_manager"
    )
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    rule = await create_claim_rule(
        session,
        provider=provider,
        guild=guild,
        initiative=initiative,
        initiative_role_id=member_role.id,
    )
    newcomer = await create_user(session)
    guild_id, initiative_id, manager_role_id = guild.id, initiative.id, manager_role.id
    rule_id, user_id, provider_id = rule.id, newcomer.id, provider.id
    await _sync(session, user_id=user_id, provider_id=provider_id, claims=_ADMITTED)
    assert await _membership(
        session, guild_id=guild_id, initiative_id=initiative_id, user_id=user_id
    )

    each_guild = oidc_sync.each_guild

    async def moved_meanwhile(visits, **kwargs):
        if kwargs["name"] == "oidc-sync":
            await provider_placement.set_rule_initiative(
                guild_id,
                rule_id,
                version=2,
                initiative_id=initiative_id,
                initiative_role_id=manager_role_id,
                alike=[],
            )
            async with cohorts.system_session(None) as system:
                await system.exec(
                    update(OIDCClaimMapping)
                    .where(OIDCClaimMapping.id == rule_id)
                    .values(placement_version=2)
                )
                await system.commit()
            await provider_placement.drop_rule_initiative(guild_id, rule_id, before=1)
        return await each_guild(visits, **kwargs)

    monkeypatch.setattr(oidc_sync, "each_guild", moved_meanwhile)
    result = await _sync(
        session, user_id=user_id, provider_id=provider_id, claims=_ADMITTED
    )

    assert result.initiatives_removed == []
    assert await _membership(
        session, guild_id=guild_id, initiative_id=initiative_id, user_id=user_id
    )
