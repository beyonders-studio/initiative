"""Export-content i18n: catalog parity across locales + the translation seam."""

import json
from pathlib import Path

from app.services.export.i18n import et, export_locale

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


def test_plural_and_interpolation_variants_present_in_every_locale():
    """The summary keys are plural (``_one``/``_other``); every locale must
    carry both variants or a count would fall back to English mid-sentence."""
    for locale in _LOCALES:
        keys = _flatten(_catalog(locale))
        for base in ("summary.tasks", "summary.items", "summary.counters"):
            assert f"{base}_one" in keys and f"{base}_other" in keys


def test_et_translates_and_interpolates():
    assert et("fields.title", "es") == "Tarea"
    assert et("status.held", "fr") == "En attente"
    assert et("footer.project", "de", name="Ada") == "Ada — Projektbericht"


def test_et_selects_plural_by_count():
    assert et("summary.tasks", "en", count=1) == "1 task"
    assert et("summary.tasks", "en", count=3) == "3 tasks"
    assert et("summary.counters", "fr", count=2) == "2 compteurs"


def test_et_falls_back_to_english_for_unknown_locale():
    assert et("fields.task_status_id", "zz") == "Status"


def test_export_locale_defaults_to_english():
    class _NoLocale:
        pass

    assert export_locale(_NoLocale()) == "en"

    class _WithLocale:
        locale = "fr"

    assert export_locale(_WithLocale()) == "fr"
