"""The read-only guild role can answer the gate, not just reach the catalog.

``guild_base_ro_parity_test`` notices when a shared table is granted to the
writable floor and not the read one. This asks the question that difference
actually costs: a session routed into ``guild_<id>_ro`` runs the same
``guild_auth_satisfied()`` every guild content policy runs, and the gate reads
``guild_provider_connections`` and ``platform_provider_defaults`` to answer it.

Two paths route into that role. A PAM read grant carries no
``current_guild_id``, so the gate matches no policy row and stops early. A
community in ``read_only`` lifecycle status routes a **real member** in while
keeping the membership GUCs, so the gate runs in full — which is the case here.
"""

from sqlalchemy import text

from app.db.schema_provisioning import GuildRoleKind, guild_role_name
from app.testing.factories import create_auth_provider, create_guild
from app.core.login_methods import LoginMethod
from app.core.rules import SignInRequirement
from app.services.platform import rules


async def test_the_read_floor_can_answer_the_gate(session, engine):
    """A read-only member of a community that requires a sign-in.

    The gate answers — false here, since this session proved nothing — rather
    than faulting on a table the role cannot read.
    """
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="gate-floor")
    guild_id, provider_id = guild.id, provider.id
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", provider_id, frozenset({LoginMethod.sso})),
        guild_id=guild_id,
    )
    await session.commit()

    async with engine.connect() as conn:
        await conn.execute(
            text(f'SET ROLE "{guild_role_name(guild_id, GuildRoleKind.read_only)}"')
        )
        for key, value in (
            ("app.current_user_id", "1"),
            ("app.current_guild_id", str(guild_id)),
            ("app.satisfied_providers", ""),
            ("app.satisfied_claims", ""),
        ):
            await conn.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value}
            )
        answered = await conn.scalar(text("SELECT public.guild_auth_satisfied()"))

    assert answered is False


async def test_the_read_floor_reads_a_deployment_wide_answer(session, engine):
    """The same, for the arrangement a community inherits rather than wrote."""
    from app.models.platform.platform_provider_default import PlatformProviderDefault

    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="gate-floor-default")
    guild_id, provider_id = guild.id, provider.id
    session.add(
        PlatformProviderDefault(
            provider_id=provider_id,
            claim="tid",
            claim_values=["acme-tenant"],
            enabled=True,
        )
    )
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", None, frozenset({LoginMethod.sso})),
        guild_id=guild_id,
    )
    await session.commit()

    async with engine.connect() as conn:
        await conn.execute(
            text(f'SET ROLE "{guild_role_name(guild_id, GuildRoleKind.read_only)}"')
        )
        for key, value in (
            ("app.current_user_id", "1"),
            ("app.current_guild_id", str(guild_id)),
            ("app.satisfied_providers", str(provider_id)),
            ("app.satisfied_claims", '{"%s": {"tid": ["acme-tenant"]}}' % provider_id),
        ):
            await conn.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value}
            )
        answered = await conn.scalar(text("SELECT public.guild_auth_satisfied()"))

    # The inherited narrowing counts this arrival, so the requirement is met.
    assert answered is True


async def test_the_read_floor_reads_what_the_deployment_asks(session, engine):
    """The gate now asks the deployment's own question first, and that one
    reads ``app_settings`` — so the floor has to reach that too."""
    from app.core.login_methods import SecondFactorRequirement

    guild = await create_guild(session)
    guild_id = guild.id
    await rules.put(
        session, "second_factor_requirement", SecondFactorRequirement.everyone
    )
    await session.commit()

    async with engine.connect() as conn:
        await conn.execute(
            text(f'SET ROLE "{guild_role_name(guild_id, GuildRoleKind.read_only)}"')
        )
        for key, value in (
            ("app.current_user_id", "1"),
            ("app.current_guild_id", str(guild_id)),
            ("app.satisfied_providers", ""),
            ("app.satisfied_claims", ""),
            ("app.platform_role", "member"),
            ("app.platform_factor", "false"),
        ):
            await conn.execute(
                text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value}
            )
        without = await conn.scalar(text("SELECT public.guild_auth_satisfied()"))
        await conn.execute(
            text("SELECT set_config('app.platform_factor', 'true', true)")
        )
        holding = await conn.scalar(text("SELECT public.guild_auth_satisfied()"))

    assert without is False
    assert holding is True
