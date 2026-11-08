"""Migration 0489 closes out every grant that had already ended, so the
grant sweep tells no case about a grant from before grants had cases.

Run as the provisioning login, which owns ``access_grants`` and is held to its
row security like any other role until the migration lifts it.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session as db_session
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.access_grant import AccessGrant
from app.testing import create_guild, create_user

_REVISION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261010_0489_grants_report_to_their_case.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location(_REVISION.stem, _REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_ended_grants_are_closed_out_and_live_ones_are_not(
    session: AsyncSession,
):
    user = await create_user(session)
    guild = await create_guild(session)
    now = datetime.now(UTC)

    def grant(status: str, expires_in: timedelta) -> AccessGrant:
        return AccessGrant(
            user_id=user.id,
            guild_id=guild.id,
            access_level="read",
            status=status,
            reason="seeded",
            requested_duration_minutes=60,
            requested_by_id=user.id,
            decided_at=now - timedelta(hours=2),
            expires_at=now + expires_in,
        )

    rows = {
        "live": grant("approved", timedelta(hours=1)),
        "lapsed": grant("approved", -timedelta(minutes=1)),
        "expired": grant("expired", -timedelta(hours=1)),
        "revoked": grant("revoked", timedelta(hours=1)),
        "pending": grant("pending", timedelta(hours=1)),
    }
    await set_rls_context(session, Unattributed())
    for row in rows.values():
        session.add(row)
    await session.commit()
    ids = {name: row.id for name, row in rows.items()}

    async with db_session.provisioning_engine.begin() as conn:
        for statement in _migration().CLOSE_OUT_ENDED:
            await conn.execute(text(statement))

    session.expire_all()
    closed = {
        row.id: row.closed_out_at
        for row in (
            await session.exec(
                select(AccessGrant).where(AccessGrant.id.in_(list(ids.values())))
            )
        ).all()
    }
    assert closed[ids["live"]] is None
    for name in ("lapsed", "expired", "revoked", "pending"):
        assert closed[ids[name]] is not None, name
