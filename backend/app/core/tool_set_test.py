"""The tool set the community's rules are rendered from."""

from dataclasses import replace

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlmodel import SQLModel

from app.core.tool_set import BUILTIN_TOOLS, ToolSet
from app.core.tools import COMMENT_TARGETS, CONTENT_KINDS, Tool
from app.db.guild_ddl import render_guild_rls_ddl
from app.db.registry_checks import check_expression, registry_checks


@pytest.mark.always
def test_the_builtin_tools_are_the_records():
    assert [tool.kind for tool in BUILTIN_TOOLS] == [tool.value for tool in Tool]
    for tool in BUILTIN_TOOLS:
        spec = Tool(tool.kind).spec
        assert tool.table is SQLModel.metadata.tables[tool.plural]
        assert tuple(item.name for item in tool.items) == spec.item_tables
    assert BUILTIN_TOOLS.content_kinds == CONTENT_KINDS
    assert BUILTIN_TOOLS.comment_targets == COMMENT_TARGETS


@pytest.mark.always
def test_every_registry_check_over_the_builtin_tools_is_the_models():
    """A CHECK written from the tool set says, over the built-in tools, what
    the model's own expression says."""
    for _table, constraint in registry_checks():
        assert check_expression(constraint, BUILTIN_TOOLS) == str(constraint.sqltext), (
            constraint.name
        )


def test_a_tool_with_no_model_is_ruled_as_a_builtin_is():
    """The rules are rendered from the set handed in: a tool built from
    tables alone gets its policies, its gate arms and its switch."""
    metadata = MetaData()
    Table("initiatives", metadata, Column("id", Integer, primary_key=True))
    widgets = Table(
        "widgets",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("initiative_id", ForeignKey("initiatives.id")),
    )
    widget = replace(
        BUILTIN_TOOLS.by_kind[Tool.dashboard.value],
        kind="widget",
        plural="widgets",
        table=widgets,
        view_permission="widgets_enabled",
        create_permission="create_widgets",
    )
    ddl = render_guild_rls_ddl(ToolSet((*BUILTIN_TOOLS, widget)))
    assert "CREATE POLICY initiative_member_select ON widgets" in ddl
    assert "WHEN 'widget' THEN" in ddl
    assert "'widgets_enabled'" in ddl
    assert "FROM widgets WHERE id = p_resource_id" in ddl
    assert "WHEN 'widgets' THEN\n        SELECT * INTO fz FROM widgets" in ddl
    assert "widget" not in render_guild_rls_ddl(BUILTIN_TOOLS)
