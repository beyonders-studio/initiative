"""Push in tests: a deployment with it switched on, and a phone to send to."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from app.services.platform import push_config


@contextmanager
def push_switched_on() -> Generator[None]:
    """Resolve the push configuration as enabled for the duration.

    The switch lives on the settings row, behind a process-wide snapshot, so
    this patches the resolved answer rather than seeding the row and the cache.
    """
    enabled = push_config.ResolvedPushConfig(
        enabled=True,
        project_id="test-project",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=None,
    )
    with patch.object(
        push_config, "ensure_push_config_fresh", AsyncMock(return_value=enabled)
    ):
        yield


async def create_push_token(session, user, *, token: str | None = None) -> str:
    """Register a phone for ``user`` under a live sign-in, as the app does when
    it starts. Returns the token's value."""
    from app.services.auth import sessions as session_service
    from app.services.platform import push_tokens

    signed_in = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    value = token or f"token-{user.id}"
    await push_tokens.register_push_token(
        session=session,
        user_id=user.id,
        push_token=value,
        platform="android",
        session_id=signed_in.session.id,
    )
    return value
