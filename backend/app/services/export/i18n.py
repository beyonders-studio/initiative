"""Locale resolution + translation for export *content* (the strings baked
into generated reports — column headers, titles, footers, status flags,
empty-state messages).

Reuses the JSON loader the email system uses (``app/locales/<locale>/
exports.json``), keyed to the export **creator's** ``user.locale``. That
locale is available at both delivery paths: inline (the request's
``current_user``) and the worker's replay (it loads the full creator row),
so no locale needs to be persisted in the job selector.

Scope: only human-facing report chrome is translated. JSON envelopes stay
canonical (``type``/``schema_version``/``view_mode`` and field keys are
importable machine data — translating them would break round-trip), and user
data (titles, names, tags, status names) is never touched.
"""

from __future__ import annotations

from app.core.email_i18n import translate
from app.models.platform.user import User

_NAMESPACE = "exports"


def export_locale(user: User) -> str:
    """The creator's locale, defaulting to English (``translate`` also falls
    back to ``en`` per-key, so a partially translated catalog is safe)."""
    return getattr(user, "locale", None) or "en"


def et(key: str, locale: str, **kwargs: str | int) -> str:
    """Translate an ``exports``-namespace key. ``count`` selects the
    ``_one``/``_other`` plural; ``{{var}}`` kwargs interpolate."""
    return translate(key, locale, namespace=_NAMESPACE, **kwargs)
