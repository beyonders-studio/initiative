"""The report registry: what can be reported, and who handles it."""

from __future__ import annotations

import pytest

from app.core.moderation import (
    PlatformReportTarget,
    ReportOutcome,
    ReportVenue,
    parse_target,
    target_table,
    venue_for,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool

pytestmark = pytest.mark.always


@pytest.mark.parametrize("target", list(SearchEntityType))
def test_every_community_target_resolves_to_a_venue(target: SearchEntityType):
    """A tool added later must not ship un-reportable."""
    assert venue_for(target) in (ReportVenue.initiative, ReportVenue.platform)


@pytest.mark.parametrize("tool", list(Tool))
def test_every_tool_is_reportable_to_its_own_community(tool: Tool):
    """Derived from `Tool`, so a new one needs no edit to the report code."""
    target = SearchEntityType(tool.value)
    assert venue_for(target) is ReportVenue.initiative


def test_a_guild_level_target_falls_to_the_platform():
    """A tag belongs to no initiative, so no community owns the complaint."""
    assert venue_for(SearchEntityType.tag) is ReportVenue.platform


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


def test_every_outcome_closes_a_report():
    """There is no "pending" member: a report is work or a record."""
    assert set(ReportOutcome) == {
        ReportOutcome.dismissed,
        ReportOutcome.content_removed,
        ReportOutcome.member_warned,
        ReportOutcome.escalated,
        ReportOutcome.held,
    }


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


def test_a_marketplace_listing_is_the_platforms():
    """The catalog is the server's, so a listing is reported to its operators,
    whichever community the reporter was standing in."""
    assert venue_for(PlatformReportTarget.marketplace_listing) is ReportVenue.platform
    assert (
        parse_target("marketplace_listing") is PlatformReportTarget.marketplace_listing
    )


def test_private_conversations_are_not_reportable():
    """Direct messages are not moderated, so nothing can name one.

    The server holds ciphertext and no key, so a report about a private
    conversation could show a moderator nothing. Asserted rather than left to
    the enum, because adding the member would be a policy change and should
    fail here first.
    """
    assert "dm_conversation" not in {t.value for t in PlatformReportTarget}
    assert "dm" not in {t.value for t in PlatformReportTarget}


def test_every_target_carries_an_id_a_report_can_hold():
    """A report holds an integer id, so every target must be keyed by one."""
    from app.core.moderation import PLATFORM_TARGET_RELATION

    assert all(
        relation in {"user_profiles", "guilds", "marketplace_listings"}
        for relation in PLATFORM_TARGET_RELATION.values()
    )


def test_every_moderation_error_code_is_localized():
    """A refusal reaches the reader as its own sentence."""
    import json
    from pathlib import Path

    from app.core.messages import ModerationMessages

    codes = {
        value
        for name, value in vars(ModerationMessages).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    locales = Path(__file__).resolve().parents[2].parent / "frontend/public/locales"
    for locale in ("de", "en", "es", "fr"):
        catalogue = json.loads((locales / locale / "errors.json").read_text())
        missing = sorted(codes - set(catalogue))
        assert not missing, f"{locale}/errors.json is missing {missing}"
