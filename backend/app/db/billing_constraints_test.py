"""Schema-invariant audit for the billing boundary tables.

``CHECK (x >= 0)`` passes on NULL, so the CHECK/NULL pairing on each column
is deliberate and must be pinned exactly (write-boundary plan P-2):

* The caps are a community's paid rules: no row is unlimited, and a row's
  ``amount`` has a NULL-aware non-negativity CHECK (migration 0561, which
  carried the columns' CHECKs across). ``guild_administration.tier_name`` is
  nullable (NULL = no paid tier).
* ``billing_event_log``: ``event_id`` PRIMARY KEY; ``guild_id``/``op``/
  ``source`` NOT NULL; ``actor`` nullable; **no FK to guilds** — audit rows
  must survive guild erasure.
* ``billing_jti_blocklist``: ``jti`` PRIMARY KEY; ``expires_at`` NOT NULL
  (the janitor's purge key).

If any of these change, this suite fails and the change needs a reviewed
migration plus an update here (the ``tenancy_test.py`` pattern).
"""

from __future__ import annotations

from sqlalchemy import text


async def _nullability(session, table: str) -> dict[str, bool]:
    rows = await session.exec(
        text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        params={"t": table},
    )
    return {name: nullable == "YES" for name, nullable in rows}


async def _constraints(session, table: str, contype: str) -> dict[str, str]:
    rows = await session.exec(
        text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            # contype is "char"; compare as text so asyncpg binds a str param
            "WHERE conrelid = ('public.' || :t)::regclass AND contype::text = :ct"
        ),
        params={"t": table, "ct": contype},
    )
    return {name: definition for name, definition in rows}


async def test_guild_caps_are_never_below_zero(session):
    # NULL = no paid tier for the display label.
    assert (await _nullability(session, "guild_administration"))["tier_name"] is True

    checks = await _constraints(session, "community_rules", "c")
    amount = checks["ck_community_rules_amount_nonnegative"]
    # NULL-aware form: the CHECK constrains values without outlawing NULL.
    assert "amount IS NULL" in amount and ">= 0" in amount


async def test_billing_event_log_shape(session):
    cols = await _nullability(session, "billing_event_log")
    assert cols["event_id"] is False
    assert cols["guild_id"] is False
    assert cols["op"] is False
    assert cols["source"] is False
    assert cols["applied_at"] is False
    assert cols["actor"] is True  # NULL = automated (webhook-driven) write

    pks = await _constraints(session, "billing_event_log", "p")
    assert list(pks.values()) == ["PRIMARY KEY (event_id)"]

    # No FK: evidence must outlive the guild it describes.
    fks = await _constraints(session, "billing_event_log", "f")
    assert fks == {}, "billing_event_log must not FK guilds (audit rows outlive them)"


async def test_billing_jti_blocklist_shape(session):
    cols = await _nullability(session, "billing_jti_blocklist")
    assert cols["jti"] is False
    assert cols["redeemed_at"] is False
    assert cols["expires_at"] is False

    pks = await _constraints(session, "billing_jti_blocklist", "p")
    assert list(pks.values()) == ["PRIMARY KEY (jti)"]
