"""The system engine's own tables, as the request path meets them.

Sessions, sign-in providers and their secrets, API keys and email tokens are
resolved before an account is known, so they are read and written on the
system engine alone: no request role holds a grant on them, and every one is
refused at the grant layer, the row's own account included.

``SET ROLE`` drops the superuser setup session to the role under test, so the
table grants are enforced as they are on a real request.
"""

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.public_rls import platform_tier, role_name
from app.models.platform.user import UserRole
from app.testing import as_role, create_user


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("auth_sessions", "refresh_token_hash"),
        ("auth_providers", "id"),
        ("auth_provider_secrets", "client_secret_encrypted"),
        ("user_api_keys", "token_hash"),
        ("user_tokens", "token"),
    ],
)
async def test_a_system_engine_table_is_refused_to_every_request_role(
    session, table, column
):
    user = await create_user(session)
    roles = (
        "app_user",
        "app_guild_base",
        "app_guild_base_ro",
        *(role_name(platform_tier(tier)) for tier in UserRole),
    )
    for role in roles:
        for statement in (f"SELECT {column} FROM {table}", f"DELETE FROM {table}"):
            async with as_role(session, role, user.id):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.exec(text(statement))


async def test_session_cannot_be_its_own_rotation_parent(session):
    """ck_auth_sessions_parent_not_self: a row whose parent_id equals its own id
    is rejected — a self-loop would hang the theft-detection chain walk."""
    u1 = await create_user(session)
    sid = uuid.uuid4()
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(
                text(
                    "INSERT INTO auth_sessions "
                    "(id, user_id, refresh_token_hash, parent_id, expires_at, created_at) "
                    "VALUES (:sid, :u, :h, :sid, now() + interval '1 day', now())"
                ),
                params={
                    "sid": sid,
                    "u": u1.id,
                    "h": hashlib.sha256(b"self-parent").digest(),
                },
            )
