"""The autogenerate object filter shared by Alembic and the drift test.

``alembic/env.py`` builds its ``include_object`` hook from here, and
``app/db/model_drift_test.py`` runs ``compare_metadata`` through the same
filter — one source of truth for what each autogenerate mode manages, so the
drift test proves exactly what ``alembic revision --autogenerate`` would see.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator

from sqlalchemy import ForeignKeyConstraint

from app.db.tenancy import (
    GUILD_SCOPED_TABLES,
    NON_MODEL_SHARED_TABLES,
    OPERATIONS_TABLES,
)

IncludeObject = Callable[[object, str, str, bool, object], bool]


def make_include_object(guild_autogen: bool) -> IncludeObject:
    """Build the ``include_object`` hook for one autogenerate mode.

    Keeps each mode on its own tables — and, in guild mode, on its own OBJECT
    KINDS.

    Default mode compares shared/public tables only: guild-content tables live
    in the per-guild schemas, so without the filter autogenerate would try to
    CREATE them in ``public`` (the model metadata still declares them for the
    ORM). ``NON_MODEL_SHARED_TABLES`` drops out of both modes — those tables
    carry no SQLModel on purpose (``storage_backfill_state`` is created lazily
    by its service), so every autogenerate run would otherwise want to DROP
    them.

    Guild mode (``-x guild``) inverts the table filter (guild-content tables
    only, compared against ``guild_template``) and additionally scopes WHAT
    autogenerate manages, mirroring the established division of labor:

    * models own **tables + columns** — that's what guild autogen diffs;
    * the artifacts own the dressing — FKs keep their PG-authored names and
      deliberately omit cross-schema references, partial/GIN indexes carry
      opclasses reflection loses (preserving them is WHY provisioning
      reflects pg catalogs — see app.db.guild_ddl), and CHECKs come from
      pg_get_constraintdef — so
      constraint/index objects that exist only on one side are not diffs to
      emit. Metadata-declared indexes/uniques missing from the template are
      still created (a real model change); reflected-only ones are never
      dropped.
    """

    def include_object(obj, name, type_, reflected, compare_to) -> bool:
        if type_ == "table":
            if name in NON_MODEL_SHARED_TABLES:
                return False
            return (name in GUILD_SCOPED_TABLES) == guild_autogen

        table = getattr(obj, "table", None)  # indexes/constraints/columns
        in_guild_tables = table is not None and table.name in GUILD_SCOPED_TABLES
        if not guild_autogen:
            return not in_guild_tables
        if table is not None and not in_guild_tables:
            return False

        if type_ == "foreign_key_constraint":
            return False  # wholly artifact-owned (names + cross-schema omissions)
        if type_ in ("index", "unique_constraint", "check_constraint"):
            return not reflected or compare_to is not None  # never drop artifact-owned
        return True

    return include_object


def _reaches_out_of_the_schema(item: Any) -> bool:
    """Whether ``item`` is a foreign key to a table outside the guild schema."""
    return isinstance(item, ForeignKeyConstraint) and any(
        element.target_fullname.rsplit(".", 1)[0] not in GUILD_SCOPED_TABLES
        for element in item.elements
    )


def strip_cross_schema_foreign_keys(directives: Iterable[Any]) -> None:
    """Drop the keys a guild schema cannot hold from newly generated tables.

    ``include_object`` above already refuses foreign keys as a *diff*, but a
    table being created carries its constraints inside the ``CreateTableOp``
    rather than beside it, so none of them is ever offered to that filter. A
    new tool table therefore arrived with
    ``sa.ForeignKeyConstraint(["created_by"], ["users.id"])`` written into its
    migration — a reference from a ``guild_<id>`` schema to ``public``, which
    provisioning omits when it renders the schema (``app.db.guild_ddl``). It
    reached ``guild_template`` and stopped there, which is how twenty-three of
    them accumulated before 20260922_0349 removed them.

    The models keep declaring ``foreign_key="users.id"``: it is what tells the
    app that an integer column names a person, which is how a filter on
    ``created_by`` gets a member picker (``app.services.fields.derive``) and
    how search resolves the resource a row is gated against. This strips it
    only where it would become DDL.

    Guild mode only — a reference between two ``public`` tables is an ordinary
    key that the database does hold.
    """
    for script in directives:
        for container in (
            getattr(script, "upgrade_ops", None),
            getattr(script, "downgrade_ops", None),
        ):
            if container is not None:
                _strip(container)


def reaches_operations_only(directives: Iterable[Any]) -> bool:
    """Whether the generated guild ops change :data:`OPERATIONS_TABLES` alone,
    which only the operations community's schema has, so they run where those
    tables are. Raises for ops that change them beside other tables: those
    are two revisions, one for every community and one for it."""
    names = {
        name
        for script in directives
        for container in (
            getattr(script, "upgrade_ops", None),
            getattr(script, "downgrade_ops", None),
        )
        if container is not None
        for name in _table_names(container)
    }
    operations = names & OPERATIONS_TABLES
    if operations and names - OPERATIONS_TABLES:
        raise ValueError(
            f"{sorted(operations)} are the operations community's alone; generate"
            f" their change apart from {sorted(names - OPERATIONS_TABLES)}"
        )
    return bool(operations)


def _table_names(container: Any) -> Iterator[str]:
    for operation in getattr(container, "ops", ()):
        name = getattr(operation, "table_name", None)
        if name:
            yield name
        if hasattr(operation, "ops"):
            yield from _table_names(operation)


def _strip(container: Any) -> None:
    for operation in getattr(container, "ops", ()):
        if hasattr(operation, "ops"):  # ModifyTableOps and friends nest
            _strip(operation)
        if hasattr(operation, "columns"):  # CreateTableOp
            operation.columns = [
                item
                for item in operation.columns
                if not _reaches_out_of_the_schema(item)
            ]
