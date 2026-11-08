"""A policy for the platform tiers names its capability; the render spells the
tiers.

The unit tests pin the spelling. The database tests ask each such policy the
way a request does — on the request login, as every tier in turn — and
compare its answer with the capability registry's.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, roles_with_capability
from app.db.public_rls import (
    PLATFORM_TIER_ROLES,
    PUBLIC_RLS,
    SELECT,
    Policy,
    policy_roles,
)
from app.db.request_context import Platform
from app.db.session import set_rls_context
from app.models.platform.ai_connection import PlatformAIConnection
from app.models.platform.announcement import Announcement, AnnouncementImage
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import UserRole
from app.testing import (
    create_access_grant,
    create_guild,
    create_user,
)

pytestmark = pytest.mark.always


def test_a_capability_is_spelled_as_the_tiers_holding_it():
    policy = Policy("p", SELECT, Capability.USERS_READ, using="true")
    assert policy_roles(policy) == (
        "platform_moderator",
        "platform_operator",
        "platform_owner",
        "platform_support",
    )
    assert policy_roles(Policy("p", SELECT, ("public",), using="true")) == ("public",)


def test_every_policy_on_the_platform_tiers_names_a_capability():
    """Which tier holds what is the capability registry's to say, so no policy
    spells a tier by hand."""
    for table, rls in PUBLIC_RLS.items():
        for policy in rls.policies:
            if set(policy_roles(policy)) & PLATFORM_TIER_ROLES:
                assert isinstance(policy.roles, Capability), (
                    f"{table}.{policy.name} names platform tiers by hand"
                )


# --- the rendered policies, asked as each tier --------------------------------

# A row only the named policy admits, and the statement a tier runs against it.
# ``select`` is admitted when the row comes back; ``update`` when it changes.
Probe = tuple[str, str, dict]


async def _another_user(session: AsyncSession) -> Probe:
    other = await create_user(session)
    return "select", "SELECT id FROM public.users WHERE id = :id", {"id": other.id}


async def _another_users_grant(session: AsyncSession) -> Probe:
    other = await create_user(session)
    guild = await create_guild(session)
    grant = await create_access_grant(session, user=other, guild=guild)
    return (
        "select",
        "SELECT id FROM public.access_grants WHERE id = :id",
        {"id": grant.id},
    )


async def _a_connection(session: AsyncSession) -> Probe:
    row = PlatformAIConnection(label="probe", provider="openai")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return (
        "select",
        "SELECT id FROM public.platform_ai_connections WHERE id = :id",
        {"id": row.id},
    )


async def _the_settings_row(session: AsyncSession) -> Probe:
    if await session.get(AppSetting, 1) is None:
        session.add(AppSetting(id=1))
        await session.commit()
    return (
        "update",
        (
            "UPDATE public.app_settings SET light_accent_color = light_accent_color "
            "WHERE id = 1"
        ),
        {},
    )


async def _a_community_nobody_asked_about(session: AsyncSession) -> Probe:
    guild = await create_guild(session)
    return "select", "SELECT id FROM public.guilds WHERE id = :id", {"id": guild.id}


async def _its_administration(session: AsyncSession) -> Probe:
    guild = await create_guild(session)
    return (
        "select",
        "SELECT guild_id FROM public.guild_administration WHERE guild_id = :id",
        {"id": guild.id},
    )


async def _a_draft(session: AsyncSession) -> Probe:
    row = Announcement(title="probe")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return (
        "select",
        "SELECT id FROM public.announcements WHERE id = :id",
        {"id": row.id},
    )


async def _a_picture(session: AsyncSession) -> Probe:
    digest = secrets.token_hex(32)
    session.add(
        AnnouncementImage(
            sha256=digest,
            content_type="image/png",
            byte_size=1,
            width=1,
            height=1,
            data=b"\x00",
        )
    )
    await session.commit()
    return (
        "update",
        (
            "UPDATE public.announcement_images SET created_at = created_at "
            "WHERE sha256 = :sha"
        ),
        {"sha": digest},
    )


CASES: list[tuple[str, str, Capability, Callable[[AsyncSession], Awaitable[Probe]]]] = [
    ("users", "users_platform_read", Capability.USERS_READ, _another_user),
    (
        "access_grants",
        "access_grants_admin",
        Capability.ACCESS_APPROVE,
        _another_users_grant,
    ),
    (
        "platform_ai_connections",
        "platform_ai_connections_owner",
        Capability.CONFIG_MANAGE,
        _a_connection,
    ),
    ("app_settings", "app_settings_owner", Capability.CONFIG_MANAGE, _the_settings_row),
    (
        "guilds",
        "guilds_manage_read",
        Capability.COMMUNITIES_READ,
        _a_community_nobody_asked_about,
    ),
    (
        "guild_administration",
        "guild_administration_guilds_manage_read",
        Capability.COMMUNITIES_READ,
        _its_administration,
    ),
    (
        "announcements",
        "announcements_manage",
        Capability.ANNOUNCEMENTS_MANAGE,
        _a_draft,
    ),
    (
        "announcement_images",
        "announcement_images_manage",
        Capability.ANNOUNCEMENTS_MANAGE,
        _a_picture,
    ),
]


@pytest.mark.parametrize("table, name, capability, _probe", CASES)
def test_the_registry_declares_what_the_probe_asks(table, name, capability, _probe):
    policy = next(p for p in PUBLIC_RLS[table].policies if p.name == name)
    assert policy.roles is capability


@pytest.mark.parametrize("table, name, capability, probe", CASES)
@pytest.mark.parametrize("tier", list(UserRole))
async def test_a_tier_is_admitted_as_the_capability_says(
    session, role_session, table, name, capability, probe, tier
):
    kind, sql, params = await probe(session)
    actor = await create_user(session, role=tier)

    s = await role_session("app_user")
    await set_rls_context(s, Platform(user_id=actor.id, tier=tier.value))
    try:
        result = await s.exec(text(sql), params=params)
        admitted = bool(result.all()) if kind == "select" else result.rowcount == 1
    except DBAPIError:
        # The tier holds no privilege on the table at all.
        await s.rollback()
        admitted = False

    assert admitted is (tier in roles_with_capability(capability)), (
        f"{table}.{name} as platform_{tier.value}"
    )
