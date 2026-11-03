"""The registry must account for every guild-level table.

``GUILD_LEVEL_TABLES`` in ``db.tenancy`` is the independent source here — it is
maintained for the tenancy classification and knows nothing about exports, so
a table added there for RLS reasons fails these tests until somebody decides
whether a backup carries it.
"""

import pytest

from app.db.tenancy import GUILD_LEVEL_TABLES
from app.services.export.guild_sections import (
    EXEMPT,
    GUILD_SECTIONS,
    SECTION_TABLES,
)
from app.services.export.provenance import BUILTIN_SOURCE, is_exportable


def test_every_guild_level_table_is_carried_or_exempt():
    decided = set(SECTION_TABLES) | set(EXEMPT)
    undecided = set(GUILD_LEVEL_TABLES) - decided
    assert not undecided, (
        "guild-level tables with no export decision: "
        f"{sorted(undecided)} — carry them in a section (SECTION_TABLES) or "
        "name them in EXEMPT with a reason"
    )


def test_no_table_is_both_carried_and_exempt():
    both = set(SECTION_TABLES) & set(EXEMPT)
    assert not both, f"tables both carried and exempt: {sorted(both)}"


def test_registry_does_not_name_unknown_tables():
    """A rename in ``tenancy`` must not leave a dangling decision behind."""
    stale = (set(SECTION_TABLES) | set(EXEMPT)) - set(GUILD_LEVEL_TABLES)
    assert not stale, f"decisions for tables that no longer exist: {sorted(stale)}"


def test_every_exemption_states_a_reason():
    assert all(reason for reason in EXEMPT.values())


def test_section_keys_are_unique_and_have_paths_under_guild():
    keys = [section.key for section in GUILD_SECTIONS]
    assert len(keys) == len(set(keys))
    for section in GUILD_SECTIONS:
        assert section.path.startswith("guild/")
        assert section.path.endswith(".json")


def test_credential_tables_are_never_carried():
    """The rule the builders hold to, asserted rather than trusted."""
    for table, reason in EXEMPT.items():
        if reason == "credentials":
            assert table not in SECTION_TABLES


@pytest.mark.parametrize(
    "listing_uid,builtin,expected",
    [
        (None, frozenset(), True),  # hand-made here
        ("", frozenset(), True),
        ("abc", frozenset({"abc"}), True),  # built on a built-in plug-in
        ("abc", frozenset(), False),  # third-party or withdrawn
        ("abc", frozenset({"xyz"}), False),
    ],
)
def test_is_exportable_follows_provenance(listing_uid, builtin, expected):
    assert is_exportable(listing_uid, builtin) is expected


def test_builtin_source_is_a_known_listing_source():
    from app.services.marketplace.definitions import LISTING_SOURCES

    assert BUILTIN_SOURCE in LISTING_SOURCES


async def test_the_roles_section_carries_each_role_and_who_holds_it(
    session, acting_user
):
    from app.models.platform.guild import CommunityRole
    from app.models.tenant.custom_role import CustomRole, CustomRoleMember
    from app.services.export.guild_sections import GUILD_SECTIONS, SectionContext
    from app.db.request_context import SystemGuild
    from app.db.session import set_rls_context
    from app.testing.schema_harness import route_session_to_guild

    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await route_session_to_guild(session, admin.guild.id)
    doors = CustomRole(name="Doors", base_rung="member", surfaces=["invites"])
    session.add(doors)
    await session.flush()
    session.add(CustomRoleMember(user_id=member.user.id, role_id=doors.id))
    await session.commit()

    (section,) = [s for s in GUILD_SECTIONS if s.key == "roles"]
    await set_rls_context(session, SystemGuild(admin.guild.id))
    built = await section.build(
        SectionContext(session=session, user=admin.user, guild_id=admin.guild.id)
    )
    assert built is not None
    payload, count = built

    assert count == 1
    (role,) = payload["roles"]
    assert (role["name"], role["base_rung"], role["surfaces"]) == (
        "Doors",
        "member",
        ["invites"],
    )
    assert len(role["holders"]) == 1
