"""What a token's ``sub`` names, and what it refuses to name."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.auth.subject import subject_for_user, user_for_subject
from app.services.platform import identity_refs
from app.testing.factories import create_user


async def test_a_subject_is_a_reference_and_resolves_back(session: AsyncSession):
    """Minting is on first use, so a renewal names the account as the sign-in
    did rather than handing out a second live reference; two accounts get
    unrelated names."""
    user = await create_user(session)
    other = await create_user(session)

    subject = await subject_for_user(session, user_id=user.id)
    again = await subject_for_user(session, user_id=user.id)
    others = await subject_for_user(session, user_id=other.id)
    await session.commit()

    assert subject.startswith("ucli_")
    assert subject != str(user.id)
    assert again == subject
    assert others != subject
    assert await user_for_subject(session, subject=subject) == user


@pytest.mark.parametrize(
    "subject",
    [
        "",
        "ucli_nothing_was_ever_minted_for_this",
        "x" * 400,
        "9" * 40,
    ],
)
async def test_a_name_nothing_answers_to_resolves_to_nobody(
    session: AsyncSession, subject: str
):
    assert await user_for_subject(session, subject=subject) is None


async def test_another_sector_is_not_a_subject(session: AsyncSession):
    """Every sector mints from the same table. A reference billing holds names
    the same person, and presenting it as a session subject resolves nothing."""
    user = await create_user(session)

    billing = await identity_refs.ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user.id,
        purpose=IdentityPurpose.billing,
    )
    await session.commit()

    assert await user_for_subject(session, subject=billing) is None


async def test_a_retired_reference_stops_resolving(session: AsyncSession):
    user = await create_user(session)

    old = await subject_for_user(session, user_id=user.id)
    new = await identity_refs.reissue_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user.id,
        purpose=IdentityPurpose.client,
    )
    await session.commit()

    assert new != old
    assert await user_for_subject(session, subject=old) is None
    assert await user_for_subject(session, subject=new) == user


async def test_erasure_takes_the_name_with_it(session: AsyncSession):
    """``forget_user`` drops every sector's reference, this one among them."""
    user = await create_user(session)

    subject = await subject_for_user(session, user_id=user.id)
    await session.commit()

    await identity_refs.forget_user(user_id=user.id)
    session.expire_all()

    assert await user_for_subject(session, subject=subject) is None
