"""Completeness guard for the ``created_by`` column.

Every guild-schema table that models something a person made records its author
under ONE name — ``created_by`` — by subclassing ``CreatedByMixin``. That
uniformity is the point: callers that need a row's author (the trash can,
ownership transfer, account erasure) resolve one column name for every table
instead of a per-table lookup, which is what the old spellings (``author_id``,
``uploader_user_id``, ``uploaded_by_id``, ``installed_by_id``,
``created_by_user_id``) cost.

Coverage is a guild-schema question, so the mixin/exemption checks are scoped
there. **The naming checks are not**: they run over every table in the metadata,
``public`` included. ``guilds`` and ``guild_invites`` carried
``created_by_user_id`` until ``20260820_0189``, and a guard that only looked at
guild tables would not have noticed — nor would it notice the next one.

Pure metadata checks — no database required.
"""

from __future__ import annotations

import re

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.db.tenancy import CREATED_BY_EXEMPT_TABLES, GUILD_SCOPED_TABLES, SHARED_TABLES
from app.models.tenant._mixins import created_by_models

#: Spellings this mixin replaced. A table may not reintroduce one.
RETIRED_SPELLINGS = (
    "author_id",
    "uploader_user_id",
    "uploaded_by_id",
    "installed_by_id",
    "created_by_user_id",
)


def _authored_tables() -> set[str]:
    return {str(model.__tablename__) for model in created_by_models()}


def test_every_guild_table_declares_created_by_or_an_exemption():
    unclassified = GUILD_SCOPED_TABLES - _authored_tables() - CREATED_BY_EXEMPT_TABLES
    assert not unclassified, (
        "Guild-schema tables with neither CreatedByMixin nor an entry in "
        f"CREATED_BY_EXEMPT_TABLES: {sorted(unclassified)}. Mix in "
        "CreatedByMixin, or add it to the exempt list with the reason."
    )


def test_exempt_list_names_only_real_guild_tables():
    phantom = CREATED_BY_EXEMPT_TABLES - GUILD_SCOPED_TABLES
    assert not phantom, (
        f"CREATED_BY_EXEMPT_TABLES names non-guild tables: {sorted(phantom)}."
    )


def test_exempt_tables_do_not_also_carry_the_mixin():
    both = CREATED_BY_EXEMPT_TABLES & _authored_tables()
    assert not both, (
        f"Tables both exempt and carrying CreatedByMixin: {sorted(both)}. "
        "Drop the exemption."
    )


def test_created_by_stays_inside_the_guild_schema():
    """The mixin is guild content only — public/platform tables never use it."""
    stray = _authored_tables() & SHARED_TABLES
    assert not stray, (
        f"CreatedByMixin on shared/public tables: {sorted(stray)}. "
        "public holds identity and config, not authored content."
    )


@pytest.mark.parametrize("table", sorted(_authored_tables()))
def test_authored_tables_have_the_column(table: str):
    columns = SQLModel.metadata.tables[table].columns
    assert "created_by" in columns, f"{table} is missing created_by"


#: A "last editor" column under any name. Matching the concept rather than one
#: spelling is the point — the whole reason this file exists is that the same
#: idea wore five different names.
_LAST_EDITOR = re.compile(
    r"(updated|modified|changed|edited|revised|touched)_by|last_(editor|edited)"
)


def test_nothing_carries_a_last_editor_column():
    """There is no "last editor" column anywhere, under any name, on purpose.

    Who changed a row is captured per transaction into ``event_outbox`` by
    ``public.capture_change``, with the transaction id and the columns that
    changed. A mutable column holds strictly less than that and is overwritten
    by the next save. ``files`` carried one until it was checked and found
    to be written on six paths and read on none.
    """
    carriers = {
        f"{name}.{column.key}"
        for name, table in SQLModel.metadata.tables.items()
        for column in table.columns
        if _LAST_EDITOR.search(column.key)
    }
    assert not carriers, (
        f"Last-editor columns: {sorted(carriers)}. Who changed a row is "
        "event_outbox's answer, not a column's."
    )


@pytest.mark.parametrize("table", sorted(SQLModel.metadata.tables))
def test_no_table_reintroduces_a_retired_spelling(table: str):
    """Every table, both schemas — the retired spellings are retired for good."""
    columns = set(SQLModel.metadata.tables[table].columns.keys())
    clashes = columns & set(RETIRED_SPELLINGS)
    assert not clashes, (
        f"{table} names an authorship column {sorted(clashes)}. "
        "It is spelled created_by."
    )
