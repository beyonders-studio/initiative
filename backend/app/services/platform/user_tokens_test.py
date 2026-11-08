"""Unit tests for app.services.user_tokens.

Covers the at-rest hashing and TTL:
- tokens are stored as SHA-256 hashes, never plaintext
- lookups hash the presented value and match the stored hash
- expired / past-TTL tokens are rejected
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services.platform import user_tokens
from app.services.platform.user_tokens import _hash_token
from app.testing.factories import create_user


async def test_create_token_stores_hash_not_plaintext(session: AsyncSession):
    """create_token returns the raw token but persists only its SHA-256 hash."""
    user = await create_user(session)
    raw = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.password_reset,
    )

    row = (
        await session.exec(select(UserToken).where(UserToken.user_id == user.id))
    ).one()
    assert row.token != raw
    assert row.token == _hash_token(raw)


async def test_get_valid_token_matches_hashed_value(session: AsyncSession):
    """Lookup hashes the presented value and finds the stored hash; a wrong
    token does not match."""
    user = await create_user(session)
    raw = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.email_verification,
    )

    found = await user_tokens.get_valid_token(
        session, token=raw, purpose=UserTokenPurpose.email_verification
    )
    assert found is not None
    assert found.user_id == user.id

    missing = await user_tokens.get_valid_token(
        session, token="not-the-token", purpose=UserTokenPurpose.email_verification
    )
    assert missing is None

    # Spent once, and then no more.
    spent = await user_tokens.consume_token(
        session, token=raw, purpose=UserTokenPurpose.email_verification
    )
    assert spent is not None and spent.consumed_at is not None
    again = await user_tokens.consume_token(
        session, token=raw, purpose=UserTokenPurpose.email_verification
    )
    assert again is None


async def test_expired_token_rejected(session: AsyncSession):
    """A token whose expires_at is in the past is not returned by lookup."""
    user = await create_user(session)
    raw = "expired-raw-token-value"
    session.add(
        UserToken(
            user_id=user.id,
            token=_hash_token(raw),
            purpose=UserTokenPurpose.password_reset,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await session.commit()

    found = await user_tokens.get_valid_token(
        session, token=raw, purpose=UserTokenPurpose.password_reset
    )
    assert found is None


async def test_changing_the_password_drops_a_part_way_sign_in(
    session: AsyncSession,
):
    """A challenge rests on the password it proved, so revoking an account's
    credentials takes it with them."""
    from app.services.auth import challenges as challenge_service

    user = await create_user(session)
    bystander = await create_user(session)
    mine = await challenge_service.create(
        session,
        user_id=user.id,
        purpose=challenge_service.ChallengePurpose.sign_in,
    )
    theirs = await challenge_service.create(
        session,
        user_id=bystander.id,
        purpose=challenge_service.ChallengePurpose.sign_in,
    )
    await session.commit()

    await user_tokens.revoke_user_sessions(session, user=user)
    await session.commit()

    assert (
        await challenge_service.claim_attempt(
            session,
            value=mine.value,
            purposes=[challenge_service.ChallengePurpose.sign_in],
        )
        is None
    )
    assert (
        await challenge_service.claim_attempt(
            session,
            value=theirs.value,
            purposes=[challenge_service.ChallengePurpose.sign_in],
        )
        is not None
    )


async def test_the_sweep_clears_the_part_way_sign_ins_too(session: AsyncSession):
    """The hourly pass takes challenges as well as tokens: one whose time has
    run out, and one already spent. A challenge still standing is left."""
    from app.models.platform.auth_challenge import AuthChallenge
    from app.services.auth import challenges as challenge_service

    user = await create_user(session)
    purpose = challenge_service.ChallengePurpose.sign_in
    standing = await challenge_service.create(session, user_id=user.id, purpose=purpose)
    stale = await challenge_service.create(session, user_id=user.id, purpose=purpose)
    spent = await challenge_service.create(session, user_id=user.id, purpose=purpose)
    stale.challenge.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.add(stale.challenge)
    assert await challenge_service.consume(session, spent.challenge)
    await session.commit()

    standing_id = standing.challenge.id
    stale_id = stale.challenge.id
    spent_id = spent.challenge.id

    await user_tokens.process_expired_token_purge()

    remaining = {row.id for row in (await session.exec(select(AuthChallenge))).all()}
    assert stale_id not in remaining
    assert spent_id not in remaining
    assert standing_id in remaining
