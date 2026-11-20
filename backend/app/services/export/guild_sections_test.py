"""The registry must account for every guild-level table.

``GUILD_LEVEL_TABLES`` in ``db.tenancy`` is the independent source here — it is
maintained for the tenancy classification and knows nothing about exports, so
a table added there for RLS reasons fails these tests until somebody decides
whether a backup carries it.
"""

import pytest

from app.db.tenancy import GUILD_LEVEL_TABLES
from app.services.export.guild_sections import EXEMPT, SECTION_TABLES
from app.services.export.provenance import is_exportable


def test_every_guild_level_table_is_carried_or_exempt():
    decided = set(SECTION_TABLES) | set(EXEMPT)
    undecided = set(GUILD_LEVEL_TABLES) - decided
    assert not undecided, (
        "guild-level tables with no export decision: "
        f"{sorted(undecided)} — carry them in a section (SECTION_TABLES) or "
        "name them in EXEMPT with a reason"
    )


def test_registry_does_not_name_unknown_tables():
    """A rename in ``tenancy`` must not leave a dangling decision behind."""
    stale = (set(SECTION_TABLES) | set(EXEMPT)) - set(GUILD_LEVEL_TABLES)
    assert not stale, f"decisions for tables that no longer exist: {sorted(stale)}"


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
