"""Cross-endpoint validators for user-supplied profile fields.

These were originally module-private helpers in
``app.api.v1.platform_endpoints.users``. Moving them here lets the registration
endpoint (``app.api.v1.platform_endpoints.auth``) reuse the same rules without
reaching across to a sibling endpoint's underscore-prefixed symbol.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.core.messages import CommonMessages, UserMessages


def resolve_zone(value: str | None) -> ZoneInfo:
    """The zone a stored IANA name refers to, or UTC when it is missing or
    names no zone. For values already saved, where a drifted profile field
    must not fail the work that reads it."""
    try:
        return ZoneInfo(value or "UTC")
    except KeyError, ValueError, OSError:
        return ZoneInfo("UTC")


def normalize_timezone(value: str | None) -> str | None:
    """Validate an IANA timezone name (e.g. ``"America/Los_Angeles"``) sent
    in a request.

    Returns the trimmed value when valid, ``None`` for missing/blank
    input, and raises ``400 UNKNOWN_TIMEZONE`` for anything that names no
    zone.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if resolve_zone(cleaned).key != cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CommonMessages.UNKNOWN_TIMEZONE,
        )
    return cleaned


# 0 == "at the time of the event"; reminders are turned off via the
# email/push toggles, not via this lead time.
ALLOWED_REMINDER_MINUTES = {0, 5, 10, 15, 30, 60, 1440}


def normalize_reminder_minutes(value: int | str | None) -> int | None:
    """Validate the event-reminder lead time in minutes.

    ``None`` is passed through (legacy "off"); ``0`` means "at the time of the
    event". Any other value must be one of the allowed presets (5, 10, 15, 30
    min, 1 hour, 1 day); raises ``400 USER_INVALID_REMINDER_MINUTES`` otherwise.
    """
    if value is None:
        return None
    try:
        number = int(value)
    except TypeError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_REMINDER_MINUTES,
        )
    if number not in ALLOWED_REMINDER_MINUTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_REMINDER_MINUTES,
        )
    return number


#: The clock conventions an account can pick between. ``system`` names none:
#: the browser's locale decides, which is what every account did before the
#: setting existed, so it is the default and the upgrade changes nothing.
TIME_FORMATS = frozenset({"system", "12", "24"})


def normalize_time_format(value: str | None) -> str | None:
    """Validate a clock convention (``system``, ``12``, or ``24``)."""
    if value is None:
        return None
    candidate = str(value).strip()
    if candidate not in TIME_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_TIME_FORMAT,
        )
    return candidate


def normalize_week_starts_on(value: int | str | None) -> int | None:
    """Validate a Sunday-Saturday weekday index (0–6)."""
    if value is None:
        return None
    try:
        number = int(value)
    except TypeError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_WEEK_START,
        )
    if number < 0 or number > 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_WEEK_START,
        )
    return number


# Provider slugs form the login URLs (/auth/{slug}/login), so the alphabet is
# fixed: lowercase ASCII letters, digits, and inner dashes.
PROVIDER_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
PROVIDER_SLUG_MAX_LENGTH = 64


def validate_provider_slug(value: str) -> str:
    """Return ``value`` if it is a well-formed provider slug, else raise
    :class:`ValueError` naming the violated rule."""
    if not 1 <= len(value) <= PROVIDER_SLUG_MAX_LENGTH:
        raise ValueError(f"slug must be 1-{PROVIDER_SLUG_MAX_LENGTH} characters")
    if not set(value) <= PROVIDER_SLUG_CHARS:
        raise ValueError("slug may contain only lowercase letters, digits, and dashes")
    if value.startswith("-") or value.endswith("-"):
        raise ValueError("slug may not start or end with a dash")
    return value


def is_valid_provider_slug(value: str) -> bool:
    try:
        validate_provider_slug(value)
    except ValueError:
        return False
    return True


# Post-login return paths must stay inside the SPA: a single-slash-rooted
# relative path with no scheme, host, or backslash forms.
NEXT_PATH_MAX_LENGTH = 512


def is_safe_next_path(value: str) -> bool:
    """Whether ``value`` is a same-origin SPA path a login flow may return to."""
    if not value or len(value) > NEXT_PATH_MAX_LENGTH:
        return False
    if not value.startswith("/") or value.startswith("//"):
        return False
    if "\\" in value:
        return False
    return all(ord(ch) >= 0x20 for ch in value)
