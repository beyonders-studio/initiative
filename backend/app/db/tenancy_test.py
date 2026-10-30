"""Completeness guard for the schema-per-guild table classification.

These tests fail if any ``table=True`` model is missing a placement decision,
or if the manifest names a table that does not exist. They are the safety net
that keeps ``tenancy.py`` honest as the schema evolves: adding a new table
without classifying it breaks CI here.

Pure metadata checks — no database required.
"""

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.db.tenancy import (
    ALL_CLASSIFIED_TABLES,
    GUILD_LEVEL_TABLES,
    MANAGED_TABLES,
    GUILD_SCOPED_TABLES,
    INITIATIVE_SCOPED_TABLES,
    LEDGER_TABLES,
    OWN_ROW_TABLES,
    PRIVATE_ROW_SHARED_READ,
    PRIVATE_ROW_TABLES,
    SEAT_READ_TABLES,
    SEAT_SURFACES,
    SEAT_TABLES,
    SHARED_TABLES,
    is_guild_scoped,
    is_initiative_scoped,
    is_shared,
)

pytestmark = pytest.mark.always


def _metadata_tables() -> set[str]:
    return set(SQLModel.metadata.tables.keys())


def test_shared_and_guild_scoped_are_disjoint():
    """A table cannot be both shared and guild-scoped."""
    overlap = SHARED_TABLES & GUILD_SCOPED_TABLES
    assert not overlap, f"Tables classified in BOTH buckets: {sorted(overlap)}"


def test_every_table_is_classified():
    """Every real table must appear in exactly one bucket (no silent gaps).

    ``GUILD_SCOPED_TABLES`` is derived as ``INITIATIVE_SCOPED_TABLES |
    GUILD_LEVEL_TABLES``, so a new guild table that's in neither the
    ``initiative_rls`` path registry nor ``GUILD_LEVEL_TABLES`` lands here.
    """
    unclassified = _metadata_tables() - ALL_CLASSIFIED_TABLES
    assert not unclassified, (
        f"These tables exist but are unclassified in app/db: {sorted(unclassified)}. "
        "Add each to SHARED_TABLE_REGISTRY in app/db/public_rls.py (public), or — "
        "for guild content — a path in "
        "app/db/initiative_rls.py INITIATIVE_PATHS (initiative-scoped) or to "
        "GUILD_LEVEL_TABLES in tenancy.py (guild-wide)."
    )


def test_manifest_has_no_phantom_tables():
    """The manifest must not name tables that don't exist (typos / renames)."""
    phantom = ALL_CLASSIFIED_TABLES - _metadata_tables()
    assert not phantom, (
        "These tables are classified in app/db/tenancy.py but do not exist in "
        f"the model metadata: {sorted(phantom)}. Remove or fix the names."
    )


def test_helpers_agree_with_sets():
    assert is_guild_scoped("tasks") and not is_shared("tasks")
    assert is_shared("users") and not is_guild_scoped("users")
    # Unknown tables are neither (forces an explicit decision rather than a default).
    assert not is_guild_scoped("does_not_exist")
    assert not is_shared("does_not_exist")


# --- Second-level: initiative-scoped vs guild-level -------------------------
# INITIATIVE_SCOPED_TABLES derives from the app/db/initiative_rls path registry
# and GUILD_SCOPED_TABLES derives from (initiative | guild-level), so the
# "registry matches the set" and "they partition GUILD_SCOPED" invariants hold
# by construction — no test needed. What still needs guarding: the two halves
# must be disjoint, and the polymorphic personal_items path must cover every
# entity type the app records.


def test_initiative_and_guild_level_are_disjoint():
    """A guild table must be initiative-scoped XOR guild-level, never both.

    (GUILD_SCOPED is their union, so an overlap wouldn't show up there — it would
    silently get initiative policies while also being declared 'exempt'.)
    """
    overlap = INITIATIVE_SCOPED_TABLES & GUILD_LEVEL_TABLES
    assert not overlap, (
        f"Tables in BOTH the initiative_rls registry and GUILD_LEVEL_TABLES: "
        f"{sorted(overlap)}. Pick one."
    )


def test_initiative_scoped_helper():
    assert is_initiative_scoped("projects") and not is_initiative_scoped(
        "guild_settings"
    )
    assert not is_initiative_scoped("tags")  # guild-level
    assert not is_initiative_scoped("users")  # shared, not even guild-scoped


def test_managed_tables_are_guild_level():
    """MANAGED_TABLES is a policy overlay, not a placement bucket: every entry
    must also be classified GUILD_LEVEL, and none may be initiative-scoped."""
    assert set(MANAGED_TABLES) <= GUILD_LEVEL_TABLES
    assert not set(MANAGED_TABLES) & INITIATIVE_SCOPED_TABLES


def test_own_row_tables_are_guild_level():
    """OWN_ROW_TABLES is a policy overlay, not a placement bucket: every entry
    must also be classified GUILD_LEVEL (the schema-placement decision), and
    its owner column must exist on the table."""
    not_guild_level = set(OWN_ROW_TABLES) - GUILD_LEVEL_TABLES
    assert not not_guild_level, (
        f"OWN_ROW_TABLES entries {sorted(not_guild_level)} are not in "
        "GUILD_LEVEL_TABLES — add them there too (that is the placement decision)."
    )
    for table, owner_col in OWN_ROW_TABLES.items():
        cols = set(SQLModel.metadata.tables[table].columns.keys())
        assert owner_col in cols, (
            f"OWN_ROW_TABLES maps {table!r} to missing column {owner_col!r}."
        )


def test_private_row_tables_are_initiative_scoped():
    """PRIVATE_ROW_TABLES narrows an initiative gate, so every entry must be
    initiative-scoped and name an owner column the table has; the shared-read
    ones are a subset of it."""
    assert set(PRIVATE_ROW_TABLES) <= INITIATIVE_SCOPED_TABLES
    assert PRIVATE_ROW_SHARED_READ <= set(PRIVATE_ROW_TABLES)
    for table, owner_col in PRIVATE_ROW_TABLES.items():
        assert owner_col in SQLModel.metadata.tables[table].columns, table


def test_seat_and_ledger_tables_are_guild_level():
    """SEAT_TABLES and LEDGER_TABLES are policy overlays, like the two above:
    every entry is GUILD_LEVEL, a seat-read table is a seat table, and a
    ledger's parent key is a real column pointing at a real parent."""
    assert SEAT_TABLES <= GUILD_LEVEL_TABLES
    assert SEAT_READ_TABLES <= SEAT_TABLES
    assert set(SEAT_SURFACES) <= SEAT_TABLES
    assert set(LEDGER_TABLES) <= GUILD_LEVEL_TABLES
    for table, parent_key in LEDGER_TABLES.items():
        if parent_key is None:
            continue
        parent, fk = parent_key
        column = SQLModel.metadata.tables[table].columns[fk]
        assert {key.column.table.name for key in column.foreign_keys} == {parent}
