"""Unit tests for the password policy module."""

from __future__ import annotations

import pytest

from app.core.messages import PasswordMessages
from app.core.password_policy import (
    PASSWORD_MIN_LENGTH,
    PasswordPolicyError,
    validate_new_password,
)
from app.services import hibp
from app.services.platform import rules


class TestValidateNewPassword:
    async def test_accepts_password_at_minimum_length(self, session, monkeypatch):
        # The lookup is already stubbed by the autouse fixture in conftest,
        # but stub it here too to make the unit boundary clear.
        async def _not_breached(_pw: str) -> bool:
            return False

        monkeypatch.setattr(hibp, "is_password_breached", _not_breached)
        # Should not raise.
        await validate_new_password(session, "a" * PASSWORD_MIN_LENGTH)

    async def test_skips_breach_check_while_the_rule_is_off(self, session, monkeypatch):
        """Off for a deployment that cannot reach the corpus."""

        async def _breached(_pw: str) -> bool:
            return True

        monkeypatch.setattr(hibp, "is_password_breached", _breached)
        await rules.put(session, "breached_password_check_enabled", False)
        await session.commit()
        await validate_new_password(session, "long-enough-but-pwned")

    async def test_rejects_password_one_char_short(self, session):
        with pytest.raises(PasswordPolicyError) as excinfo:
            await validate_new_password(session, "a" * (PASSWORD_MIN_LENGTH - 1))
        assert excinfo.value.code == PasswordMessages.TOO_SHORT
        assert excinfo.value.status_code == 422

    async def test_rejects_empty_password(self, session):
        with pytest.raises(PasswordPolicyError) as excinfo:
            await validate_new_password(session, "")
        assert excinfo.value.code == PasswordMessages.TOO_SHORT

    async def test_rejects_breached_password(self, session, monkeypatch):
        calls: list[str] = []

        async def _breached(pw: str) -> bool:
            calls.append(pw)
            return True

        monkeypatch.setattr(hibp, "is_password_breached", _breached)

        candidate = "long-enough-but-pwned"
        with pytest.raises(PasswordPolicyError) as excinfo:
            await validate_new_password(session, candidate)
        assert excinfo.value.code == PasswordMessages.BREACHED
        # The breach lookup must receive the plaintext (so it can hash
        # and send the prefix). If we ever change that boundary, the
        # k-anonymity guarantee breaks — test ratchets it down.
        assert calls == [candidate]

    async def test_skips_breach_check_when_too_short(self, session, monkeypatch):
        """Cheap local checks fire first — a short password is refused
        without a network call."""
        called = False

        async def _breached(_pw: str) -> bool:
            nonlocal called
            called = True
            return True

        monkeypatch.setattr(hibp, "is_password_breached", _breached)

        with pytest.raises(PasswordPolicyError):
            await validate_new_password(session, "short")
        assert called is False
