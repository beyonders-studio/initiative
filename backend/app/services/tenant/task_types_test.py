"""The starting types' names, in every language the app speaks."""

import json
from pathlib import Path

import pytest

from app.core.task_types import DEFAULT_TASK_TYPES
from app.services.tenant import task_statuses as task_statuses_service

pytestmark = pytest.mark.always

_LOCALES = Path(__file__).resolve().parents[2] / "locales"


def _flatten(data: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _flatten(value, path) if isinstance(value, dict) else {path}
    return keys


def _catalogs() -> dict[str, dict]:
    return {
        path.name: json.loads((path / "projects.json").read_text("utf-8"))
        for path in _LOCALES.iterdir()
        if path.is_dir()
    }


def test_every_language_names_every_starting_type_and_status():
    """A key missing in one language would name that project's types in
    English beside its own."""
    catalogs = _catalogs()
    reference = _flatten(catalogs["en"])
    assert {
        f"taskTypes.defaults.{spec.key}" for spec in DEFAULT_TASK_TYPES
    } <= reference
    assert {
        f"taskStatuses.defaults.{status['key']}"
        for status in task_statuses_service.DEFAULT_TASK_STATUSES
    } <= reference
    for locale, catalog in catalogs.items():
        assert _flatten(catalog) == reference, f"{locale} key mismatch"


def test_the_starting_types_are_named_uniquely_in_every_language():
    """Names are unique in a project whatever their case."""
    for locale, catalog in _catalogs().items():
        names = [name.lower() for name in catalog["taskTypes"]["defaults"].values()]
        assert len(set(names)) == len(names), locale
