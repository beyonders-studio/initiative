"""Unit tests: SQL-identifier builders reject invalid input (Tier 3).

The tenancy model leans on one property — a request-supplied string never
becomes a Postgres role/schema name. Two mechanisms
enforce it: guild identifiers are coerced with ``int()`` inside every name
builder, and the two string-valued role inputs (guild role, platform tier) are
allow-listed in :func:`set_rls_context` before they reach the ``SET ROLE`` sink.
These tests pin both so a regression fails here.
"""

from __future__ import annotations

import re
from functools import partial

import pytest

from app.db.request_context import Platform
from app.db.schema_provisioning import (
    GuildRoleKind,
    guild_role_name,
    guild_schema_name,
)

_GUILD_ID_BUILDERS = {
    "schema": guild_schema_name,
    **{
        f"role_{kind.name}": partial(guild_role_name, kind=kind)
        for kind in GuildRoleKind
    },
}

# Non-integer values a path/query param could carry.
_HOSTILE_GUILD_IDS = [
    "3; DROP ROLE app_admin",
    "1 OR 1=1",
    "1'; --",
    "42) ; SELECT",
    "guild_1",
    "",
    "  ",
    None,
    3.5,
    42,  # a real id: never refused, and named guild_42
]


@pytest.mark.parametrize(
    "builder", _GUILD_ID_BUILDERS.values(), ids=list(_GUILD_ID_BUILDERS)
)
@pytest.mark.parametrize("hostile", _HOSTILE_GUILD_IDS, ids=repr)
def test_guild_name_builders_reject_or_sanitize_hostile_ids(builder, hostile):
    """A guild-name builder only ever emits a digits-only identifier from a
    non-integer id — it either raises (``int()`` on a string/None) or coerces
    to a digits-only name (a float truncates to its integer part). A real id
    is never refused and keeps its number."""
    try:
        name = builder(hostile)
    except ValueError, TypeError:
        assert not isinstance(hostile, int)
        return  # rejected outright — the common case
    assert re.fullmatch(rf"[A-Za-z0-9_]*guild_{int(hostile)}[a-z_]*", name), name


@pytest.mark.parametrize(
    "hostile_platform_role",
    ["owner'; DROP ROLE app_admin; --", "superuser", "member ", "", "ADMIN"],
)
def test_a_routing_rejects_unknown_platform_tier(hostile_platform_role):
    """The platform tier is allow-listed against the known ladder before it can
    reach the ``SET ROLE`` name sink — the shape refuses it when it is built,
    before any session is touched, so a bad value fails closed."""
    with pytest.raises(ValueError):
        Platform(user_id=1, tier=hostile_platform_role)
