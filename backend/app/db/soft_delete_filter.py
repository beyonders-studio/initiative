"""Session-wide ORM filter that hides soft-deleted rows by default.

Wires a ``do_orm_execute`` listener that injects a
``with_loader_criteria(<Model>, deleted_at IS NULL)`` option for every
soft-deletable model into every SELECT statement issued through a Session.
SQLAlchemy applies each criterion only to queries that actually reference the
matching table, so the per-statement overhead is small.

To opt out (for the trash listing / restore endpoints), pass
``execution_options(include_deleted=True)`` either on the Session or on the
individual statement. The ``select_including_deleted`` helper wraps that for
convenience.

The soft-deletable models are the ``SoftDeleteMixin`` subclasses, read once
here after every model is registered.
"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.orm.session import ORMExecuteState
from sqlmodel import SQLModel
from sqlmodel import select as sqlmodel_select

import app.db.base  # noqa: F401 — registers every model
from app.models.tenant._mixins import soft_delete_models

#: Every model with the trash-can lifecycle, by table name.
SOFT_DELETE_MODELS: tuple[type[SQLModel], ...] = tuple(soft_delete_models())

#: Their tables: what the guild RLS renderer's purge guard and the freeze read.
SOFT_DELETE_TABLES: tuple[str, ...] = tuple(
    str(model.__tablename__) for model in SOFT_DELETE_MODELS
)


_INSTALLED = False


def install_soft_delete_filter() -> None:
    """Install the listener exactly once. Safe to call from app startup
    or test setup multiple times."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(Session, "do_orm_execute")
    def _filter_deleted(state: ORMExecuteState) -> None:
        if not state.is_select:
            return
        if state.execution_options.get("include_deleted", False):
            return
        # Request-scoped opt-out: a handler reading a resource back after a
        # deleted event flags its session (see api.deps.IncludeDeletedDep) so
        # every load it performs — helpers and DAC loaders included — can see
        # the trashed row without threading a parameter through each one.
        if state.session is not None and state.session.info.get("include_deleted"):
            return
        for model_cls in SOFT_DELETE_MODELS:
            state.statement = state.statement.options(
                with_loader_criteria(
                    model_cls,
                    model_cls.deleted_at.is_(None),
                    include_aliases=True,
                )
            )


def select_including_deleted(*entities: Any):
    """Construct a SELECT that bypasses the active-row filter.

    Usage:
        stmt = select_including_deleted(Project).where(Project.deleted_at.isnot(None))
        result = await session.exec(stmt)
    """
    return sqlmodel_select(*entities).execution_options(include_deleted=True)
