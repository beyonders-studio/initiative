"""Export-content i18n: catalog parity across locales. A report localizing to
its creator is tested through the export endpoints."""

import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parents[2] / "locales"
_LOCALES = ("en", "de", "es", "fr")


def _flatten(data: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _flatten(value, path)
        else:
            keys.add(path)
    return keys


def _catalog(locale: str) -> dict:
    return json.loads((_LOCALES_DIR / locale / "exports.json").read_text("utf-8"))


def test_every_locale_has_the_same_export_keys():
    """A missing key in a non-en catalog silently falls back to English, so a
    partial translation ships an English word into an otherwise-localized
    report. Parity keeps the catalogs honest."""
    reference = _flatten(_catalog("en"))
    assert reference  # guard against an empty/renamed catalog passing vacuously
    for locale in _LOCALES:
        assert _flatten(_catalog(locale)) == reference, f"{locale} key mismatch"


def test_every_task_priority_enum_value_has_a_catalog_entry():
    """The adapters build the priority key dynamically from the enum
    (``et(f"priority.{task.priority.value}", …)``). A new enum value without a
    matching catalog entry would fall through ``translate``'s last resort and
    leak the raw key (``priority.critical``) into the exported document. Pin
    every enum value to a key in every locale so adding one fails CI here."""
    from app.models.tenant.task import TaskPriority

    for locale in _LOCALES:
        keys = _flatten(_catalog(locale))
        for priority in TaskPriority:
            assert f"priority.{priority.value}" in keys, (
                f"{locale} missing priority.{priority.value}"
            )
