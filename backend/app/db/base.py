"""Every model, registered on ``SQLModel.metadata`` by importing this module.

Table models live in the modules of ``app.models.platform`` and
``app.models.tenant``. Importing this imports each of them, so a model is
registered — for Alembic, the drift checks and every reader of the metadata —
the moment its module exists.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from sqlmodel import SQLModel

import app.models.platform
import app.models.tenant

__all__ = ["MODELS_BY_TABLE", "MODEL_PACKAGES", "import_modules"]

#: The packages the table models live in.
MODEL_PACKAGES: tuple[ModuleType, ...] = (app.models.platform, app.models.tenant)


def import_modules(package: ModuleType) -> list[ModuleType]:
    """Every module directly under ``package``, imported, tests left out."""
    return [
        importlib.import_module(info.name)
        for info in pkgutil.iter_modules(package.__path__, f"{package.__name__}.")
        if not info.name.endswith("_test")
    ]


for _package in MODEL_PACKAGES:
    import_modules(_package)

#: Every table model, by its table. A mapped class that is not a table of its
#: own (a projection over another's rows) has no ``__tablename__`` and is not
#: here.
MODELS_BY_TABLE: dict[str, type[SQLModel]] = {
    str(mapper.class_.__tablename__): mapper.class_
    for mapper in SQLModel._sa_registry.mappers  # type: ignore[attr-defined]
    if isinstance(getattr(mapper.class_, "__tablename__", None), str)
}
