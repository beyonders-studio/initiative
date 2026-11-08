"""Showing an address back without disclosing it.

Read paths return a shortened form of an address rather than the address
itself. The shortened form keeps enough for a reader to recognise an address
they already have — matching a support ticket to a row, telling one pending
invite from another — and drops the rest.

Masking is applied by the response shapes (``OperatorUserRead``,
``CommunityInviteRead``, ``AccessGrantRead``) rather than by each endpoint, so a
new route serving one of those shapes gets it without doing anything. The
stored address is read in full only where the reader is its owner
(``/me``) and by the code that sends mail.
"""

from __future__ import annotations

#: What replaces the elided middle. A fixed width regardless of how much was
#: removed, so the length of the original does not show through.
ELISION = "***"


def _mask_part(part: str) -> str:
    """First character, elision, last character — ``example`` -> ``e***e``.

    A one-character part has no distinct last character, and repeating the
    single one would suggest a second that isn't there, so it gets the elision
    alone.
    """
    if len(part) == 1:
        return f"{part}{ELISION}"
    return f"{part[0]}{ELISION}{part[-1]}"


def mask_email(value: str | None) -> str | None:
    """``user1@example.com`` -> ``u***1@e***m``.

    Both halves are reduced the same way: first character, elision, last
    character. The domain is reduced along with the local part, and everything
    between them — dots included — goes with it.

    ``None`` and ``""`` pass through unchanged so callers don't special-case an
    address that was never set. A value that doesn't parse as an address (no
    ``@``, or nothing on one side of it) returns the elision alone rather than
    being echoed back.
    """
    if not value:
        return value
    local, separator, domain = value.strip().partition("@")
    if not separator or not local or not domain:
        return ELISION
    return f"{_mask_part(local)}@{_mask_part(domain)}"
