"""Every property target reaches each registry its values are gated by.

``PROPERTY_LINKS`` is derived from ``PROPERTY_TARGETS``; what can drift is the
rest of the stack each target has to be known to — the polymorphic gate, the
freeze walk and the read schema. The CHECK on a value's kind follows the
registry (``app.db.registry_checks``).
"""

import importlib

import pytest

from app.db.frozen import render_resource_frozen_fn
from app.db.initiative_rls import entity_tables, render_entity_initiative_fn
from app.schemas.tenant.property import PropertiesOnCreate, PropertiesOnUpdate
from app.services.tenant.metadata import PROPERTY_LINKS

pytestmark = pytest.mark.always


def test_every_target_is_known_to_the_gates_and_its_read():
    """``entity_access`` and ``entity_initiative`` answer for it, a value on it
    freezes with it, its read schema carries ``properties``, and so does its
    create — every JSON create; a picture is created by uploading its file,
    and takes its values once it exists. An update that carries its row's
    tags carries its properties the same way."""
    tables = entity_tables()
    initiative_of = render_entity_initiative_fn()
    frozen = render_resource_frozen_fn()
    for target, spec in PROPERTY_LINKS.items():
        assert tables.get(target) == spec.model.__tablename__, target
        assert f"WHEN '{target}' THEN" in initiative_of, target
        assert f"WHEN '{tables[target]}' THEN" in frozen, target
        schemas = importlib.import_module(
            spec.model.__module__.replace("app.models.", "app.schemas.", 1)
        )
        read = getattr(schemas, f"{spec.model.__name__}Read")
        assert "properties" in read.model_fields, read.__name__
        create = getattr(schemas, f"{spec.model.__name__}Create", None)
        if create is not None:
            assert issubclass(create, PropertiesOnCreate), create.__name__
        update = getattr(schemas, f"{spec.model.__name__}Update", None)
        if update is not None and "tag_ids" in update.model_fields:
            assert issubclass(update, PropertiesOnUpdate), update.__name__
