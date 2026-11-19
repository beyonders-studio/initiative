"""CHECK constraints whose values a registry lists, rendered at boot.

A guild model marks such a constraint ``info={FROM_REGISTRY: True}``. Its
values come from the registry its expression reads (the tools, the kinds a
recent view or a relationship may name, the permission keys), so provisioning
renders it into every guild schema rather than a migration freezing a copy: a
value added to the registry is admitted on the next boot, with no migration
restating the list. Where the values are the community's tools and the kinds
inside them, the mark is instead the rule that writes the expression from a
tool set (``info={FROM_REGISTRY: rule}``), and the model's own expression is
that rule over the built-in tools.

Replacing a constraint and validating it are two renders, run in two
transactions. ``ADD … NOT VALID`` checks only new rows and holds its exclusive
lock just until its transaction commits; ``VALIDATE``, run after, checks the
rows already there under a lock that lets reads and writes go on. Both run
only when the replacement's digest moves, so only when a registry changed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Table
from sqlmodel import SQLModel

if TYPE_CHECKING:
    from app.core.tool_set import ToolSet

#: The ``info`` key a model sets on a CHECK that follows a registry.
FROM_REGISTRY = "from_registry"


def listed(values: Iterable[str]) -> str:
    """``values`` as the list an ``IN (…)`` takes."""
    return ", ".join(f"'{value}'" for value in values)


def check_expression(constraint: CheckConstraint, tools: ToolSet) -> str:
    """What ``constraint`` checks in a community with ``tools``."""
    rule = constraint.info[FROM_REGISTRY]
    return rule(tools) if callable(rule) else str(constraint.sqltext)


def registry_checks() -> list[tuple[Table, CheckConstraint]]:
    """Every guild-schema CHECK a model marks as following a registry, by table
    and name."""
    import app.db.base  # noqa: F401  # every model on the metadata
    from app.db.tenancy import GUILD_SCOPED_TABLES

    found = [
        (table, constraint)
        for table in SQLModel.metadata.tables.values()
        if table.name in GUILD_SCOPED_TABLES
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.info.get(FROM_REGISTRY)
    ]
    return sorted(found, key=lambda pair: (pair[0].name, str(pair[1].name)))


def render_guild_registry_check_ddl(tools: ToolSet) -> str:
    """The DDL that replaces every registry CHECK in a guild schema, checking
    new rows only. Run with the search_path on that schema."""
    lines: list[str] = []
    for table, constraint in registry_checks():
        name = constraint.name
        lines += [
            f"ALTER TABLE {table.name} DROP CONSTRAINT IF EXISTS {name};",
            (
                f"ALTER TABLE {table.name} ADD CONSTRAINT {name}"
                f" CHECK ({check_expression(constraint, tools)}) NOT VALID;"
            ),
        ]
    return "\n".join(lines)


def render_guild_registry_validate_ddl() -> str:
    """The DDL that checks the rows already in a guild schema against every
    registry CHECK, after the replacement has committed."""
    return "\n".join(
        f"ALTER TABLE {table.name} VALIDATE CONSTRAINT {constraint.name};"
        for table, constraint in registry_checks()
    )
