"""Which references the request path reaches, proved at the SQL layer.

``identity_refs`` holds one row per (entity, sector). The request path resolves
the ``client`` sector, because that is the one an account's own access token
names it by. The sectors for parties outside the deployment stay where they
were, and asserting that through the app's own service would only prove the
``WHERE`` clause in :mod:`app.services.auth.subject` — so these connect AS
``app_user`` and query the table directly (migration 20260913_0267).
"""

import pytest
from sqlalchemy import text

from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform import identity_refs
from app.testing import create_user


async def _refs_visible_to(role_session, ref: str) -> int:
    s = await role_session("app_user")
    return (
        await s.exec(
            text("SELECT count(*) FROM public.identity_refs WHERE ref = :r"),
            params={"r": ref},
        )
    ).scalar_one()


async def test_the_request_path_reads_a_client_reference(session, role_session):
    user = await create_user(session)
    ref = await identity_refs.ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user.id,
        purpose=IdentityPurpose.client,
    )
    await session.commit()

    assert await _refs_visible_to(role_session, ref) == 1


@pytest.mark.parametrize(
    ("purpose", "sector"),
    [
        # The deployment's billing service: one sector for the platform.
        (IdentityPurpose.billing, {}),
        # One plug-in in one community.
        (
            IdentityPurpose.plugin,
            {"sector_guild_id": 1, "sector_plugin": "acme.tracker"},
        ),
    ],
    ids=["billing", "plugin"],
)
async def test_the_request_path_reads_no_other_sector(
    session, role_session, purpose: IdentityPurpose, sector: dict
):
    user = await create_user(session)
    ref = await identity_refs.ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user.id,
        purpose=purpose,
        **sector,
    )
    await session.commit()

    assert await _refs_visible_to(role_session, ref) == 0


async def test_the_request_path_cannot_mint_or_change_one(session, role_session):
    """Reading resolves a name somebody already holds. Writing would issue one,
    and that stays on the system engine with every other sector."""
    from sqlalchemy.exc import DBAPIError

    user = await create_user(session)
    ref = await identity_refs.ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user.id,
        purpose=IdentityPurpose.client,
    )
    await session.commit()

    s = await role_session("app_user")
    for statement, params in (
        (
            (
                "INSERT INTO public.identity_refs "
                "(ref, entity_type, entity_id, purpose, created_at) "
                "VALUES ('ucli_minted_by_a_request', 'user', :u, 'client', now())"
            ),
            {"u": user.id},
        ),
        (
            "UPDATE public.identity_refs SET entity_id = :u WHERE ref = :r",
            {"u": user.id, "r": ref},
        ),
        ("DELETE FROM public.identity_refs WHERE ref = :r", {"r": ref}),
    ):
        with pytest.raises(DBAPIError):
            await s.exec(text(statement), params=params)
        await s.rollback()
