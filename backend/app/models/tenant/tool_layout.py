"""How an instance of a tool lists what it holds, and shows one of them: its
layouts.

A row belongs to a target: one instance of a tool (``tool``, ``tool_id``: a
project), a collection (``tool`` is ``collection``), or, for a tool the whole
initiative shares, the initiative itself (``tool_id`` NULL: the calendar). Its ``kind`` says which layout it is: one way
the target lists what it holds (``table``, ``board``, ``calendar``), its
detail (``task``), or which list it opens on (``default``). A target has
at most one of each.

A row is stored when what it holds is changed, and only then, so its
``updated_at`` is its own; what is not stored is drawn as shipped
(``app.services.tenant.tool_layouts``).

A project's task page is one per task type (``task_type_id``,
``app.core.tools.TYPED_DETAILS``), and goes with its type.

``definition`` holds the validated tree (``app.schemas.tenant.tool_layout``).
There is no foreign key to the instance: the purge removes an instance's
layouts explicitly, as it does its property values. The initiative is a
foreign key, so a shared tool's layouts go with their initiative.

Read by the initiative's members; written by whoever may write the instance,
or, for a shared tool, by the initiative's managers and the community's admin
(``app.db.initiative_rls``).
"""

from __future__ import annotations

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

_TOOL_VALUES = ", ".join(f"'{target}'" for target in LAYOUT_TARGETS)
_SHARED_VALUES = ", ".join(f"'{tool.value}'" for tool in LAYOUTS_SHARED)
_KIND_VALUES = ", ".join(f"'{kind}'" for kind in LAYOUT_KINDS)
_TYPED = " OR ".join(
    f"(tool = '{tool.value}' AND kind = '{kind}')"
    for tool, kind in TYPED_DETAILS.items()
)

#: The columns a row's target is named by.
_TARGET = ("initiative_id", "tool", "tool_id")

#: The layout a tool plug-in's table shows one of its rows in; it lists them
#: as its declaration's list says (``tool_plugins.TOOL_LIST_LAYOUTS``).
PLUGIN_DETAIL = "detail"


def _plugin_tables(tools: ToolSet | None) -> str:
    """Every table of the community's tool plug-ins' tools, by its kind: the
    targets of the starting layouts each declares. None for the built-in
    tools alone."""
    if tools is None:
        return ""
    return ", ".join(
        f"'{kind}'"
        for record in tools.installed
        for kind in (record.kind, *(child.value for child in record.children))
    )


def _tool_check(tools: ToolSet | None) -> str:
    plugin = _plugin_tables(tools)
    return f"tool IN ({_TOOL_VALUES}{', ' + plugin if plugin else ''})"


def _target_check(tools: ToolSet | None) -> str:
    shared = f"(tool IN ({_SHARED_VALUES})) = (tool_id IS NULL)"
    plugin = _plugin_tables(tools)
    return f"({shared} OR tool IN ({plugin}))" if plugin else shared


def _kind_check(tools: ToolSet | None) -> str:
    """The layouts a row may be: every built-in tool's, and with a tool
    plug-in installed its table's item page too (its lists are a grid or a
    table, which built-in tools have)."""
    detail = f", '{PLUGIN_DETAIL}'" if _plugin_tables(tools) else ""
    return f"kind IN ({_KIND_VALUES}{detail})"


class ToolLayout(CreatedByMixin, table=True):
    __tablename__ = "tool_layouts"
    __table_args__ = (
        CheckConstraint(
            _tool_check(None),
            name="ck_tool_layouts_tool",
            info={FROM_REGISTRY: _tool_check},
        ),
        # A shared tool names no instance, and every other tool's layout names one.
        CheckConstraint(
            _target_check(None),
            name="ck_tool_layouts_target",
            info={FROM_REGISTRY: _target_check},
        ),
        CheckConstraint(
            _kind_check(None),
            name="ck_tool_layouts_kind",
            info={FROM_REGISTRY: _kind_check},
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
