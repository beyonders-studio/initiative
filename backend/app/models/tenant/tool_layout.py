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

from datetime import datetime, timezone
from typing import Any, Optional

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

_TOOL_VALUES = ", ".join(f"'{target}'" for target in LAYOUT_TARGETS)
_SHARED_VALUES = ", ".join(f"'{tool.value}'" for tool in LAYOUTS_SHARED)
_KIND_VALUES = ", ".join(f"'{kind}'" for kind in LAYOUT_KINDS)
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
            f"tool IN ({_TOOL_VALUES})",
            name="ck_tool_layouts_tool",
            info={FROM_REGISTRY: True},
        ),
        # A shared tool names no instance, and every other tool's layout names one.
        CheckConstraint(
            f"(tool IN ({_SHARED_VALUES})) = (tool_id IS NULL)",
            name="ck_tool_layouts_target",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            f"kind IN ({_KIND_VALUES})",
            name="ck_tool_layouts_kind",
            info={FROM_REGISTRY: True},
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

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tool: str = Field(sa_column=Column(String(32), nullable=False))
    tool_id: Optional[int] = Field(default=None, sa_column=Column(Integer))
    kind: str = Field(sa_column=Column(String(32), nullable=False))
    #: The type of task a project's task page is for; None for every other
    #: layout. Goes with its type.
    task_type_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("task_types.id", ondelete="CASCADE"), index=True
        ),
    )
    definition: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
