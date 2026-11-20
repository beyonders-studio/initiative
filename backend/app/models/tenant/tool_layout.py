"""How an instance of a tool lists what it holds, and shows one of them: its
layouts.

A row belongs to a target: one instance of a tool (``tool``, ``tool_id``: a
project), a collection (``tool`` is ``collection``), or, for a tool the whole
initiative shares, the initiative itself (``tool_id`` NULL: the calendar). A
tool plug-in's table is its own target, named by its kind, in each place its
rows are listed: the initiative for the tool's own rows (``tool_id`` NULL),
and the row an item's rows sit under (``tool_id`` that row's), so each item
table of a row keeps its own. Its ``kind`` says which layout it is: one way
the target lists what it holds (``table``, ``board``, ``calendar``), its
detail (``task``; a tool plug-in's table's rows' page, by the table's kind),
or which list it opens on (``default``). A target has at most one of each.

A row is stored when what it holds is changed, and only then, so its
``updated_at`` is its own; what is not stored is drawn as shipped
(``app.services.tenant.tool_layouts``).

A project's task page is one per task type (``task_type_id``,
``app.core.tools.TYPED_DETAILS``), and goes with its type.

``definition`` holds the validated tree (``app.schemas.tenant.tool_layout``).
There is no foreign key to the instance: the purge removes an instance's
layouts explicitly, as it does its property values. The initiative is a
foreign key, so a shared tool's layouts go with their initiative.

Read by the initiative's members; written by whoever may write the instance
(for a tool plug-in's item, the row it sits under), or, for a shared tool and
a tool plug-in's own table, by the initiative's managers and the community's
admin (``app.db.initiative_rls``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.core.tools import LAYOUT_KINDS, LAYOUT_TARGETS, LAYOUTS_SHARED, TYPED_DETAILS
from app.db.registry_checks import FROM_REGISTRY
from app.models.tenant._mixins import CreatedByMixin

if TYPE_CHECKING:
    from app.core.tool_set import ToolSet


def _listed(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _tables(tools: ToolSet | None) -> list[str]:
    """Each installed tool plug-in's tables in a community with ``tools``, by
    kind: the tool's own, then its items'."""
    installed = () if tools is None else tools.installed
    return [
        kind
        for tool in installed
        for kind in (tool.kind, *(child.value for child in tool.children))
    ]


def _tool_rule(tools: ToolSet | None) -> str:
    """Which targets a row may name in a community with ``tools``: the
    built-in ones, and each installed tool plug-in's tables."""
    return f"tool IN ({_listed((*LAYOUT_TARGETS, *_tables(tools)))})"


def _target_rule(tools: ToolSet | None) -> str:
    """A shared tool, and a tool plug-in's own table, name no row; every
    other target names one."""
    installed = () if tools is None else tools.installed
    shared = (*(tool.value for tool in LAYOUTS_SHARED), *(t.kind for t in installed))
    return f"(tool IN ({_listed(shared)})) = (tool_id IS NULL)"


def _kind_rule(tools: ToolSet | None) -> str:
    """Which layouts a row may be in a community with ``tools``: the built-in
    ones, and the page of each installed tool plug-in's table's rows, by its
    kind (its lists are among the built-in ones)."""
    return f"kind IN ({_listed((*LAYOUT_KINDS, *_tables(tools)))})"


_TYPED = " OR ".join(
    f"(tool = '{tool.value}' AND kind = '{kind}')"
    for tool, kind in TYPED_DETAILS.items()
)

#: The columns a row's target is named by.
_TARGET = ("initiative_id", "tool", "tool_id")


class ToolLayout(CreatedByMixin, table=True):
    __tablename__ = "tool_layouts"
    __table_args__ = (
        CheckConstraint(
            _tool_rule(None),
            name="ck_tool_layouts_tool",
            info={FROM_REGISTRY: _tool_rule},
        ),
        # A shared tool names no instance, and every other tool's layout names one.
        CheckConstraint(
            _target_rule(None),
            name="ck_tool_layouts_target",
            info={FROM_REGISTRY: _target_rule},
        ),
        CheckConstraint(
            _kind_rule(None),
            name="ck_tool_layouts_kind",
            info={FROM_REGISTRY: _kind_rule},
        ),
        # A detail laid out per type names its type, and nothing else does.
        CheckConstraint(
            f"({_TYPED}) = (task_type_id IS NOT NULL)",
            name="ck_tool_layouts_typed",
            info={FROM_REGISTRY: True},
        ),
        Index(
            "uq_tool_layouts_kind",
            *_TARGET,
            "kind",
            "task_type_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tool: str = Field(sa_column=Column(String(32), nullable=False))
    tool_id: int | None = Field(default=None, sa_column=Column(Integer))
    kind: str = Field(sa_column=Column(String(32), nullable=False))
    #: The type of task a project's task page is for; None for every other
    #: layout. Goes with its type.
    task_type_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("task_types.id", ondelete="CASCADE"), index=True
        ),
    )
    definition: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
