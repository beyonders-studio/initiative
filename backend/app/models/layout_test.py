"""Guard: the model file layout must agree with the tenancy classification.

Schema-per-guild is a hard DB-layer boundary (per-guild Postgres schemas in
isolated namespaces, no cross-guild context). To keep that boundary legible in
the source tree, every ``table=True`` model lives under exactly one of:

- ``app/models/tenant/``   — tables in ``GUILD_SCOPED_TABLES`` (per-guild schema)
- ``app/models/platform/`` — tables in ``SHARED_TABLES`` (public schema)

This test fails if a model is in the wrong folder, sits unbucketed at the
models root, or maps to a table that ``tenancy.py`` hasn't classified. The single
source of truth stays ``app.db.tenancy`` / ``app.db.initiative_rls`` — this only
asserts the directory mirrors it, so the two can never silently drift.
"""

from __future__ import annotations

import inspect

import pytest
from sqlmodel import SQLModel

import app.models.platform as platform_pkg
import app.models.tenant as tenant_pkg
from app.db.base import import_modules
from app.db.tenancy import GUILD_SCOPED_TABLES, SHARED_TABLES
from app.models.tenant._mixins import SoftDeleteMixin

pytestmark = pytest.mark.always

_TABLE_NAMES = set(SQLModel.metadata.tables)


def _table_models_in(pkg) -> list[type]:
    found: list[type] = []
    for module in import_modules(pkg):
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue  # imported into the module, not defined here
            table_name = getattr(obj, "__tablename__", None)
            if isinstance(table_name, str) and table_name in _TABLE_NAMES:
                found.append(obj)
    return found


def _collect() -> list[tuple[str, str, str]]:
    """(tablename, module, bucket) for every table model under tenant/ + platform/."""
    rows: list[tuple[str, str, str]] = []
    for bucket, pkg in (("tenant", tenant_pkg), ("platform", platform_pkg)):
        for cls in _table_models_in(pkg):
            rows.append((cls.__tablename__, cls.__module__, bucket))
    return rows


def test_every_table_model_is_bucketed_correctly():
    """tenant/ ⇔ GUILD_SCOPED_TABLES and platform/ ⇔ SHARED_TABLES."""
    wrong: list[str] = []
    for table, module, bucket in _collect():
        expected = (
            "tenant"
            if table in GUILD_SCOPED_TABLES
            else "platform"
            if table in SHARED_TABLES
            else None
        )
        if expected is None:
            wrong.append(f"{table} ({module}): not classified in tenancy.py")
        elif expected != bucket:
            wrong.append(
                f"{table} ({module}): in app/models/{bucket}/ but tenancy.py "
                f"classifies it {expected} — move it to app/models/{expected}/"
            )
    assert not wrong, "model file placement disagrees with tenancy.py:\n" + "\n".join(
        wrong
    )


def test_no_table_model_left_at_models_root():
    """A table model directly under app/models/ has no tenancy placement."""
    import app.models as models_pkg

    stray = [
        cls.__name__
        for cls in _table_models_in(models_pkg)
        # iter_modules over the package root won't descend into tenant/ or platform/
    ]
    assert not stray, (
        "table models must live in app/models/tenant/ or app/models/platform/, "
        f"found at the root: {stray}"
    )


def test_every_classified_table_has_a_bucketed_model():
    """Every classified table must map to a model under tenant/ or platform/ —
    catches a model dropped or moved out of its bucket entirely."""
    unplaced = (GUILD_SCOPED_TABLES | SHARED_TABLES) - {t for t, _, _ in _collect()}
    assert not unplaced, (
        f"{sorted(unplaced)} classified in tenancy.py but no model under "
        f"app/models/tenant|platform/ maps to it"
    )


# --- Mixin placement: model mixins belong to a layer too, not the root --------
#
# A mixin is not a table, so the table-classification guards above can't see it.
# But it is still layer-bound: SoftDeleteMixin adds the trash-can lifecycle to
# guild *content*, and platform/public tables have no trash can. These guards
# pin "platform shouldn't need this at all" as a CI invariant — every model that
# mixes it in must live under app/models/tenant/ and map to a GUILD_SCOPED
# (never SHARED) table.


def test_every_soft_delete_model_is_tenant_and_guild_scoped():
    """No platform table may inherit SoftDeleteMixin; every subclass is a
    guild-scoped table defined under app/models/tenant/."""
    wrong: list[str] = []
    for cls in SoftDeleteMixin.__subclasses__():
        table = getattr(cls, "__tablename__", None)
        if not (isinstance(table, str) and table in _TABLE_NAMES):
            continue  # a non-table mixin/abstract subclass, not our concern
        if not cls.__module__.startswith("app.models.tenant"):
            wrong.append(f"{cls.__name__} ({cls.__module__}): not under tenant/")
        elif table in SHARED_TABLES or table not in GUILD_SCOPED_TABLES:
            wrong.append(
                f"{cls.__name__} ({table}): soft-delete is guild-content only, "
                f"but {table} is not a GUILD_SCOPED_TABLE"
            )
    assert not wrong, "soft-delete mixin used outside the tenant layer:\n" + "\n".join(
        wrong
    )
