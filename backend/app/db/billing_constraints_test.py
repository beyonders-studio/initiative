"""The caps are a community's paid rules: no row is unlimited, and a row's
``amount`` has a NULL-aware non-negativity CHECK (migration 0561, which carried
the columns' CHECKs across). ``CHECK (x >= 0)`` passes on NULL, so the pairing
is pinned here; the columns' nullability is ``model_drift_test``'s."""

from __future__ import annotations

from sqlalchemy import text


async def test_guild_caps_are_never_below_zero(session):
    amount = (
        await session.exec(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_community_rules_amount_nonnegative'"
            )
        )
    ).one()[0]
    # NULL-aware form: the CHECK constrains values without outlawing NULL.
    assert "amount IS NULL" in amount and ">= 0" in amount
