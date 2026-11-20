"""The report registry: what can be reported, and who handles it."""

from __future__ import annotations

import pytest

from app.core.moderation import (
    PlatformReportTarget,
    ReportVenue,
    parse_target,
    target_table,
    venue_for,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool

pytestmark = pytest.mark.always


@pytest.mark.parametrize("tool", list(Tool))
def test_every_tool_is_reportable_to_its_own_community(tool: Tool):
    """Derived from `Tool`, so a new one needs no edit to the report code."""
    target = SearchEntityType(tool.value)
    assert venue_for(target) is ReportVenue.initiative


@pytest.mark.parametrize("target", list(PlatformReportTarget))
def test_identity_targets_are_the_platforms(target: PlatformReportTarget):
    assert venue_for(target) is ReportVenue.platform


def test_the_venue_matches_the_registry_the_policies_are_rendered_from():
    """The venue and the access gate read one declaration, so they agree."""
    from app.db.initiative_rls import INITIATIVE_PATHS

    for target in SearchEntityType:
        scoped = target_table(target) in INITIATIVE_PATHS
        expected = ReportVenue.initiative if scoped else ReportVenue.platform
        assert venue_for(target) is expected, target


def test_a_target_type_nobody_defines_is_refused():
    with pytest.raises(ValueError):
        parse_target("the_vibes")


def test_parsing_accepts_both_planes():
    assert parse_target("comment") is SearchEntityType.comment
    assert parse_target("username") is PlatformReportTarget.username
    assert (
        parse_target("marketplace_listing") is PlatformReportTarget.marketplace_listing
    )


def test_every_platform_target_names_a_public_relation():
    """Each target names a relation the *reporter* can read: ``public.users`` is
    own-row for a platform-tier session, so checking against it would answer
    "not found" for every account but your own. That every target has an entry
    at all is a row in ``core/registry_coverage_test.py``.
    """
    from app.core.moderation import PLATFORM_TARGET_RELATION

    assert set(PLATFORM_TARGET_RELATION.values()) <= {
        "user_profiles",
        "guilds",
        "marketplace_listings",
    }
    assert "users" not in set(PLATFORM_TARGET_RELATION.values())


def test_every_platform_relation_resolves_to_a_table():
    """The name a target maps to must be a relation the query builder finds.

    The visibility check is built from column objects, so an entry naming
    something neither the models nor the views declare would be discovered at
    the first report of that kind rather than here.
    """
    from app.core.moderation import PLATFORM_TARGET_RELATION
    from app.services.tenant.moderation import public_relation

    for target, name in PLATFORM_TARGET_RELATION.items():
        relation = public_relation(name)
        assert "id" in relation.c, f"{target.value} -> {name} has no id column"
    listing = public_relation(
        PLATFORM_TARGET_RELATION[PlatformReportTarget.directory_listing]
    )
    assert "join_policy" in listing.c
