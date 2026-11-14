"""Simple JSON-based i18n loader for email templates.

Usage:
    from app.core.email_i18n import email_t

    email_t("verification.subject")                    # "Verify your Initiative account"
    email_t("verification.greeting", name="Jordan")    # "Hi Jordan,"
    email_t("overdue.body", count=3)                   # picks _one/_other based on count
"""

from __future__ import annotations

import html as _html
import json
import re
from functools import lru_cache
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

#: The languages this deployment writes email in — the locale directories
#: beside this module. Read once: they ship with the image and do not change
#: while it runs.
SUPPORTED_EMAIL_LOCALES: frozenset[str] = frozenset(
    path.name for path in _LOCALES_DIR.iterdir() if path.is_dir()
)
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# Namespaces whose templates are rendered into HTML email bodies. Interpolated
# variable VALUES (display names, resource titles, comment text — all
# user-controlled) are HTML-escaped by default for these namespaces so a
# display name containing markup shows as literal text instead of rendering
# inside the email.
# The template text itself (e.g. ``<strong>{{actor}}</strong>``) is trusted and
# never escaped. Plain-text contexts (subjects, textBody alternatives) opt out
# per call with ``escape=False`` — a missed opt-out shows a cosmetic ``&amp;``,
# whereas a missed opt-in would render user markup, so HTML-safe is the
# default.
_HTML_NAMESPACES = frozenset({"email"})


@lru_cache(maxsize=32)
def _load_locale(locale: str, namespace: str) -> dict:
    path = (_LOCALES_DIR / locale / f"{namespace}.json").resolve()
    if not path.is_relative_to(_LOCALES_DIR.resolve()):
        return {}
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _lookup(key: str, locale: str, namespace: str, count: int | None) -> str | None:
    """Resolve a key (with optional plural suffix) within a single locale."""
    data = _load_locale(locale, namespace)
    if count is not None:
        suffix = "_one" if int(count) == 1 else "_other"
        plural_value = _resolve_key(data, f"{key}{suffix}")
        if plural_value is not None:
            return plural_value
    return _resolve_key(data, key)


def _resolve_key(data: dict, key: str) -> str | None:
    """Walk dot-separated key through nested dict."""
    parts = key.split(".")
    current: dict | str | None = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
            if current is None:
                return None
        else:
            return None
    return current if isinstance(current, str) else None


def translate(
    key: str,
    locale: str = "en",
    *,
    namespace: str = "email",
    escape: bool | None = None,
    **kwargs: str | int,
) -> str:
    """Look up a translation key with ``{{var}}`` interpolation.

    ``namespace`` selects the per-locale JSON file (``email`` or
    ``notifications``). Supports simple plural selection via the ``count``
    kwarg: if ``count`` is provided and a ``_one`` / ``_other`` suffixed key
    exists, the appropriate variant is returned.

    ``escape`` controls HTML-escaping of the interpolated variable *values*
    (never the template text). ``None`` (the default) escapes for namespaces
    in ``_HTML_NAMESPACES`` and leaves others raw; pass ``escape=False`` when
    rendering an HTML-namespace key into a plain-text context (subject lines,
    ``textBody`` alternatives).

    Resolution falls back to the ``en`` locale when the key is missing for the
    requested locale (e.g. a locale file that hasn't been translated yet), so
    callers never surface a raw key to users. If the key is missing everywhere,
    the key itself is returned as a last resort.
    """
    count = kwargs.get("count")
    value = _lookup(key, locale, namespace, count)
    if value is None and locale != "en":
        value = _lookup(key, "en", namespace, count)
    if value is None:
        return key  # last-resort fallback: return the key itself

    if escape is None:
        escape = namespace in _HTML_NAMESPACES

    def _substitute(match: re.Match[str]) -> str:
        raw = str(kwargs.get(match.group(1), match.group(0)))
        return _html.escape(raw) if escape else raw

    return _VAR_RE.sub(_substitute, value)


def email_t(
    key: str, locale: str = "en", *, escape: bool | None = None, **kwargs: str | int
) -> str:
    """Translate a key from the ``email`` namespace (back-compatible helper)."""
    return translate(key, locale, namespace="email", escape=escape, **kwargs)
