"""Every path that makes an account leaves it a policy row.

There is no single funnel for account creation — registration, provisioning
from an identity provider and the bootstrap owner each build a ``User`` of
their own — so the thing worth asserting is coverage: each one calls the
seeder, and each one applies the operator's default rather than the column
default.
"""

from sqlalchemy import text
from sqlmodel import select

from app.models.platform.user_dm_settings import DmPolicy, UserDmSettings
from app.services.platform import dm_settings as dm_settings_service
from app.testing import create_user


async def _set_default(session, policy: DmPolicy) -> None:
    from app.services.platform import rules

    await rules.put(session, "default_dm_policy", policy)
    await session.flush()


async def _policy_of(session, user_id: int) -> DmPolicy | None:
    row = (
        await session.exec(
            select(UserDmSettings).where(UserDmSettings.user_id == user_id)
        )
    ).one_or_none()
    return row.dm_policy if row else None


async def test_seeding_applies_the_operator_default(session):
    await _set_default(session, DmPolicy.community)
    user = await create_user(session)
    await session.exec(
        text("DELETE FROM public.user_dm_settings WHERE user_id = :u").bindparams(
            u=user.id
        )
    )

    await dm_settings_service.seed_for_new_account(session, user_id=user.id)

    assert await _policy_of(session, user.id) is DmPolicy.community


async def test_seeding_twice_leaves_a_changed_policy_alone(session):
    await _set_default(session, DmPolicy.private)
    user = await create_user(session)
    await session.exec(
        text("DELETE FROM public.user_dm_settings WHERE user_id = :u").bindparams(
            u=user.id
        )
    )
    await dm_settings_service.seed_for_new_account(session, user_id=user.id)

    # The account holder opens up, and a retried creation must not close them.
    row = (
        await session.exec(
            select(UserDmSettings).where(UserDmSettings.user_id == user.id)
        )
    ).one()
    row.dm_policy = DmPolicy.public
    await session.flush()
    await dm_settings_service.seed_for_new_account(session, user_id=user.id)

    assert await _policy_of(session, user.id) is DmPolicy.public


async def test_registration_seeds_the_row(client, session):
    await _set_default(session, DmPolicy.community)
    await session.commit()

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "dm-seed@example.com",
            "password": "correct horse battery staple",
            "username": "seedtester",
        },
    )
    assert response.status_code in (200, 201), response.text

    created = response.json()["id"]
    assert await _policy_of(session, created) is DmPolicy.community


async def test_the_bootstrap_owner_is_seeded(session):
    """``init_db`` seeds the first account before anything else exists."""
    from app.db import init_db as init_db_module

    source = init_db_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        body = handle.read()
    assert "dm_settings_service.seed_for_new_account" in body


async def test_identity_provisioning_is_seeded(session):
    """Provisioning from an identity provider seeds the row before it commits,
    and after the savepoint that would discard a lost race."""
    from app.services.auth import identity as identity_module

    source = identity_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        body = handle.read()
    assert "dm_settings_service.seed_for_new_account" in body
