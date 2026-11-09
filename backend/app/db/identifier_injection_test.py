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

from app.db.public_rls import platform_tier, role_name
from app.db.request_context import Platform
from app.db.schema_provisioning import (
    GuildRoleKind,
    guild_role_name,
    guild_schema_name,
)
from app.db.session import set_rls_context
from app.models.platform.user import UserRole

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
]


@pytest.mark.parametrize(
    "builder", _GUILD_ID_BUILDERS.values(), ids=list(_GUILD_ID_BUILDERS)
)
@pytest.mark.parametrize("hostile", _HOSTILE_GUILD_IDS, ids=repr)
def test_guild_name_builders_reject_or_sanitize_hostile_ids(builder, hostile):
    """A guild-name builder only ever emits a digits-only identifier from a
    non-integer id — it either raises (``int()`` on a string/None) or coerces
    to a digits-only name (a float truncates to its integer part)."""
    try:
        name = builder(hostile)
    except ValueError, TypeError:
        return  # rejected outright — the common case
    assert re.fullmatch(r"[A-Za-z0-9_]*guild_[0-9]+[a-z_]*", name), name


@pytest.mark.parametrize(
    "builder", _GUILD_ID_BUILDERS.values(), ids=list(_GUILD_ID_BUILDERS)
)
def test_guild_name_builders_emit_identifier_safe_names(builder):
    """For a real integer id the output is only ``<prefix>guild_<digits>`` with
    an optional role suffix — no quotable characters."""
    name = builder(42)
    assert re.fullmatch(r"[A-Za-z0-9_]*guild_42[a-z_]*", name), name


@pytest.mark.parametrize("tier", [role.value for role in UserRole])
def test_platform_role_names_are_identifier_safe_for_valid_tiers(tier):
    name = role_name(platform_tier(tier))
    assert re.fullmatch(rf"[A-Za-z0-9_]*platform_{tier}", name), name


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


async def test_set_rls_context_takes_no_role_to_claim():
    """There is no name sink here at all any more.

    A routing says which community it is in. What the reader is there is a row
    the database reads into the request's standing, so there is no parameter to
    hand a value to.
    """
    import inspect

    assert "guild_role" not in inspect.signature(set_rls_context).parameters
