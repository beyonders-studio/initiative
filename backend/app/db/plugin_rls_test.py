"""Which guild tables a plug-in reaches, checked against the models."""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.core.plugin_scopes import PluginScopeResource
from app.db.plugin_rls import PLUGIN_TABLE_ACCESS, PluginTableKind
from app.db.tenancy import GUILD_SCOPED_TABLES


def test_every_table_named_is_a_guild_table_that_exists():
    """Every entry names a guild table the models declare."""
    for table in PLUGIN_TABLE_ACCESS:
        assert table in SQLModel.metadata.tables, table
        assert table in GUILD_SCOPED_TABLES, table


@pytest.mark.parametrize(
    ("table", "resource"),
    [
        ("projects", "projects"),
        ("tasks", "projects"),
        ("task_assignees", "projects"),
        ("calendar_event_attendees", "calendars"),
        ("queue_items", "queues"),
        ("comments", "comments"),
        ("tags", "tags"),
    ],
)
def test_content_answers_to_the_scope_of_what_it_belongs_to(table, resource):
    access = PLUGIN_TABLE_ACCESS[table]
    assert access.kind is PluginTableKind.scoped
    assert access.resource is PluginScopeResource(resource)
    assert access.writable


@pytest.mark.parametrize("table", ["initiatives", "initiative_members"])
def test_structure_is_read_only(table):
    assert not PLUGIN_TABLE_ACCESS[table].writable


@pytest.mark.parametrize(
    "table",
    [
        "guild_settings",
        "guild_plugins",
        "initiative_rules",
        "personal_items",
        "post_reads",
        "intake_cases",
    ],
)
def test_administration_and_personal_state_are_out_of_reach(table):
    assert table not in PLUGIN_TABLE_ACCESS


@pytest.mark.parametrize("table", ["event_outbox", "uploads"])
def test_side_effects_are_never_written_directly(table):
    access = PLUGIN_TABLE_ACCESS[table]
    assert access.kind is PluginTableKind.side_effect
    assert not access.writable
