"""Logic tests for the session lifecycle (create / rotate / revoke).

Exercises the real ``auth_sessions`` table on the setup (privileged) session —
the role-security wall (request path can't touch the table) is proven separately
in ``app.db.auth_sessions_rls_test``. These focus on the rotation + theft-
detection behaviour the refresh endpoint will depend on.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.auth_session import AuthSession
from app.models.platform.dm_device import DmDevice
from app.services.auth import sessions as session_service
from app.services.auth.sessions import RefreshOutcome
from app.testing import create_user


def _at(*, days: int = 0, minutes: int = 0) -> datetime:
    """A fixed instant offset from a stable base — keeps TTL math deterministic
    without ``datetime.now`` (and without the frozen-time helpers)."""
    base = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
    return base + timedelta(days=days, minutes=minutes)


async def _rotate_ok(session, raw, when, **kwargs):
    """Rotate, assert it succeeded, and return the resulting IssuedSession."""
    result = await session_service.rotate_session(
        session, raw_refresh_token=raw, now=when, **kwargs
    )
    assert result.ok, f"expected ROTATED, got {result.outcome}"
    return result.issued


async def test_create_session_persists_hash_and_returns_raw(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[7],
        user_agent="pytest",
        ip="203.0.113.9",
        now=_at(),
    )

    # The raw token is returned once; only its SHA-256 is stored.
    assert issued.refresh_token
    stored = await session.get(AuthSession, issued.session.id)
    assert stored is not None
    assert (
        stored.refresh_token_hash
        == hashlib.sha256(issued.refresh_token.encode()).digest()
    )
    assert stored.amr == ["pwd"]
    assert stored.satisfied_providers == [7]
    assert stored.revoked_at is None
    assert stored.parent_id is None
    # A browser's session: the deployment's 30-day window.
    assert stored.install_id is None
    assert stored.expires_at == _at(days=30)
    assert str(stored.ip) == "203.0.113.9"


async def test_rotate_spends_parent_and_carries_context(session):
    user = await create_user(session)
    first = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["oidc:acme"],
        satisfied_providers=[3],
        provider_auth={"3": {"auth_time": 1757600000, "amr": ["mfa"]}},
        device_name="Pixel",
        install_id=uuid.uuid4(),
        now=_at(),
    )
    # A device's session stands 90 days unused, where a browser's stands 30.
    assert first.session.expires_at == _at(days=90)

    second = await _rotate_ok(session, first.refresh_token, _at(minutes=5))

    assert second.refresh_token != first.refresh_token
    assert second.session.id != first.session.id
    assert second.session.parent_id == first.session.id
    # amr / providers / device carry forward when not overridden.
    assert second.session.amr == ["oidc:acme"]
    assert second.session.satisfied_providers == [3]
    assert second.session.provider_auth == {
        "3": {"auth_time": 1757600000, "amr": ["mfa"]}
    }
    assert second.session.device_name == "Pixel"
    assert second.session.install_id == first.session.install_id
    # Sliding window: the child expires 90d from the rotation, not from creation.
    assert second.session.expires_at == _at(days=90, minutes=5)

    await session.refresh(first.session)
    assert first.session.revoked_at == _at(minutes=5)
    assert first.session.last_used_at == _at(minutes=5)


async def test_rotate_can_widen_amr_and_providers(session):
    """A step-up rotation replaces the satisfied set instead of carrying it."""
    user = await create_user(session)
    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )

    second = await _rotate_ok(
        session,
        first.refresh_token,
        _at(minutes=1),
        amr=["pwd", "otp"],
        satisfied_providers=[9],
        provider_auth={"9": {"auth_time": 1757600000}},
    )

    assert second.session.amr == ["pwd", "otp"]
    assert second.session.satisfied_providers == [9]
    assert second.session.provider_auth == {"9": {"auth_time": 1757600000}}


async def test_rotate_unknown_token_returns_unknown(session):
    result = await session_service.rotate_session(
        session, raw_refresh_token="never-issued", now=_at()
    )
    assert result.outcome is RefreshOutcome.UNKNOWN
    assert result.issued is None


async def test_rotate_expired_token_returns_expired(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        refresh_ttl=timedelta(minutes=10),
        now=_at(),
    )

    result = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token, now=_at(minutes=11)
    )
    assert result.outcome is RefreshOutcome.EXPIRED


async def test_rotate_runs_the_idle_window_from_the_last_input(session):
    """A renewal keeps the session for the window after the person's last input,
    not after the renewal, and ends one whose window has already run out."""
    user = await create_user(session)
    first = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        refresh_ttl=timedelta(minutes=15),
        now=_at(),
    )

    second = await _rotate_ok(
        session,
        first.refresh_token,
        _at(minutes=14),
        refresh_ttl=timedelta(minutes=15),
        idle=timedelta(minutes=4),
    )
    assert second.session.expires_at == _at(minutes=25)

    result = await session_service.rotate_session(
        session,
        raw_refresh_token=second.refresh_token,
        refresh_ttl=timedelta(minutes=15),
        idle=timedelta(minutes=15),
        now=_at(minutes=24),
    )
    assert result.outcome is RefreshOutcome.EXPIRED
    await session.refresh(second.session)
    assert second.session.revoked_at == _at(minutes=24)


async def test_reuse_of_spent_token_revokes_whole_chain(session):
    """Presenting an already-rotated token revokes the entire chain —
    including the live tail."""
    user = await create_user(session)
    r1 = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    r2 = await _rotate_ok(session, r1.refresh_token, _at(minutes=1))
    r3 = await _rotate_ok(session, r2.refresh_token, _at(minutes=2))

    # Present r1's (long-spent) token again.
    result = await session_service.rotate_session(
        session, raw_refresh_token=r1.refresh_token, now=_at(minutes=3)
    )
    assert result.outcome is RefreshOutcome.REUSED
    assert result.issued is None

    # The live tail (r3) is now revoked, so the user must sign in again.
    for issued in (r1, r2, r3):
        await session.refresh(issued.session)
        assert issued.session.revoked_at is not None


async def test_revoke_session_is_idempotent(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )

    revoked = await session_service.revoke_session(
        session, session_id=issued.session.id, now=_at(minutes=1)
    )
    assert revoked == 1

    # Already revoked ⇒ no-op.
    again = await session_service.revoke_session(
        session, session_id=issued.session.id, now=_at(minutes=2)
    )
    assert again == 0

    await session.refresh(issued.session)
    assert issued.session.revoked_at == _at(minutes=1)


async def test_revoked_session_cannot_rotate(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    await session_service.revoke_session(
        session, session_id=issued.session.id, now=_at(minutes=1)
    )

    result = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token, now=_at(minutes=2)
    )
    assert result.outcome is RefreshOutcome.REUSED


async def test_revoke_all_for_user_scoped_to_that_user(session):
    user = await create_user(session)
    other = await create_user(session)
    a = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    b = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    c = await session_service.create_session(
        session, user_id=other.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )

    # The sign-in asking is spared, renewals of it included.
    kept = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    kept_renewal = await _rotate_ok(session, kept.refresh_token, _at(minutes=1))

    revoked = await session_service.revoke_all_for_user(
        session,
        user_id=user.id,
        now=_at(minutes=1),
        except_session_id=str(kept.session.id),
    )
    assert set(revoked) == {a.session.id, b.session.id}

    for issued in (a, b):
        await session.refresh(issued.session)
        assert issued.session.revoked_at == _at(minutes=1)
    for spared in (c, kept_renewal):
        await session.refresh(spared.session)
        assert spared.session.revoked_at is None


async def test_revoke_chain_from_any_member_revokes_all(session):
    """Given a middle node, the whole chain (ancestors + descendants) is revoked."""
    user = await create_user(session)
    r1 = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    r2 = await _rotate_ok(session, r1.refresh_token, _at(minutes=1))
    r3 = await _rotate_ok(session, r2.refresh_token, _at(minutes=2))
    # r2 is already revoked (it rotated); re-run from r2 to prove reachability
    # both up (r1) and down (r3). r1/r2 stay revoked, r3 gets revoked.
    revoked = await session_service.revoke_chain(
        session, session_id=r2.session.id, now=_at(minutes=3)
    )
    assert revoked == {r3.session.id}  # only r3 was still live

    for issued in (r1, r2, r3):
        await session.refresh(issued.session)
        assert issued.session.revoked_at is not None


async def test_revoke_chain_takes_a_renewal_committed_while_it_ran(session, engine):
    """A renewal that had claimed the live row before the revocation began holds
    it until it commits. The revocation waits for it, and the row the renewal
    opened is ended too rather than left live."""
    user = await create_user(session)
    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as renewing, maker() as revoking:
        renewed = await session_service.rotate_session(
            renewing, raw_refresh_token=first.refresh_token
        )
        assert renewed.ok and renewed.issued is not None

        async def revoke() -> set[uuid.UUID]:
            ended = await session_service.revoke_chain(
                revoking, session_id=first.session.id
            )
            await revoking.commit()
            return ended

        revocation = asyncio.create_task(revoke())
        await asyncio.sleep(0.3)  # long enough for it to be waiting on the row
        await renewing.commit()
        ended = await revocation

    child = renewed.issued.session.id
    assert ended == {child}
    stored = await session.get(AuthSession, child, populate_existing=True)
    assert stored is not None and stored.revoked_at is not None


async def test_revoke_chain_missing_id_is_noop(session):
    revoked = await session_service.revoke_chain(
        session, session_id=uuid.uuid4(), now=_at()
    )
    assert revoked == set()


async def test_purge_removes_dead_sessions_and_keeps_live_ones(session):
    """The sweep takes what can no longer be used and is past the window: a
    long-expired row and a long-revoked one. A live session, a session that
    expired only yesterday, and one revoked only yesterday all stay.

    A browser's key store goes once its sign-in has ended, though not in the
    moment a renewal may still be moving it; a device's stays through it, and
    so does a live browser's."""
    user = await create_user(session)
    now = _at(days=100)

    live = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=now
    )
    long_expired = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        now=now,
        refresh_ttl=timedelta(days=-40),
    )
    just_expired = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        now=now,
        refresh_ttl=timedelta(days=-1),
    )
    long_revoked = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=now
    )
    just_revoked = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=now
    )
    await session_service.revoke_session(
        session, session_id=long_revoked.session.id, now=now - timedelta(days=40)
    )
    signed_out_device = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        install_id=uuid.uuid4(),
        now=now,
    )
    ending = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=now
    )
    for ended in (just_revoked, signed_out_device):
        await session_service.revoke_session(
            session, session_id=ended.session.id, now=now - timedelta(days=1)
        )
    await session_service.revoke_session(
        session, session_id=ending.session.id, now=now - timedelta(minutes=1)
    )
    stores = {
        name: DmDevice(
            user_id=user.id,
            identity_key=b"i",
            fingerprint_key=b"f",
            signature=b"s",
            session_id=issued.session.id,
        )
        for name, issued in {
            "live_browser": live,
            "ended_browser": just_revoked,
            "ending_browser": ending,
            "signed_out_device": signed_out_device,
        }.items()
    }
    session.add_all(stores.values())
    await session.commit()
    store_ids = {name: store.id for name, store in stores.items()}
    # Plain values before the sweep: the rows are expired afterwards, and an
    # ORM attribute read then would lazy-load.
    ids = {
        name: issued.session.id
        for name, issued in {
            "live": live,
            "just_expired": just_expired,
            "just_revoked": just_revoked,
            "long_expired": long_expired,
            "long_revoked": long_revoked,
        }.items()
    }

    removed = await session_service.purge_dead_sessions(session, now=now)
    assert removed == 2

    session.expire_all()
    assert await session.get(AuthSession, ids["live"]) is not None
    assert await session.get(AuthSession, ids["just_expired"]) is not None
    assert await session.get(AuthSession, ids["just_revoked"]) is not None
    assert await session.get(AuthSession, ids["long_expired"]) is None
    assert await session.get(AuthSession, ids["long_revoked"]) is None
    assert await session.get(DmDevice, store_ids["live_browser"]) is not None
    assert await session.get(DmDevice, store_ids["ended_browser"]) is None
    assert await session.get(DmDevice, store_ids["ending_browser"]) is not None
    assert await session.get(DmDevice, store_ids["signed_out_device"]) is not None


async def test_delete_all_for_user_leaves_other_accounts_alone(session):
    user = await create_user(session)
    bystander = await create_user(session)
    mine = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    theirs = await session_service.create_session(
        session, user_id=bystander.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    mine_id, theirs_id = mine.session.id, theirs.session.id

    removed = await session_service.delete_all_for_user(session, user_id=user.id)
    await session.commit()
    assert removed == 1

    session.expire_all()
    assert await session.get(AuthSession, mine_id) is None
    assert await session.get(AuthSession, theirs_id) is not None
