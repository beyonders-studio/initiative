"""HaveIBeenPwned Pwned Passwords client (k-anonymity).

The k-anonymity endpoint accepts the first 5 hex chars of a password's
SHA-1 hash and returns every breached hash sharing that prefix, along
with how many breaches each appears in. The full hash, and therefore
the password, never leaves the server.

Reference: https://haveibeenpwned.com/API/v3#PwnedPasswords

Fail-open by design: any error (network, parse, timeout) is logged and
treated as "not breached". A flaky HIBP outage shouldn't block all
password changes; the length floor in ``app.core.password_policy``
still applies as a hard gate.
"""

from __future__ import annotations

import hashlib
import logging

import httpx


logger = logging.getLogger(__name__)


# The padding header asks HIBP to pad the response with random,
# non-matching hashes so an on-path observer can't infer which prefix
# was queried from the response size. Costs nothing on our end.
_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_HEADERS = {
    "User-Agent": "initiative-plugin",
    "Add-Padding": "true",
}
_TIMEOUT = httpx.Timeout(2.0)


async def is_password_breached(password: str) -> bool:
    """Return ``True`` iff the password's SHA-1 appears in the HIBP corpus.

    Returns ``False`` on any network or parse error, or when the hash isn't
    found. The empty string is treated as not breached (caller already
    enforces a length floor). Whether to ask at all is the deployment's rule
    ``breached_password_check_enabled``, which ``password_policy`` reads.
    """
    if not password:
        return False

    # ``usedforsecurity=False`` is required so this call doesn't raise
    # ValueError on FIPS-enforcing OpenSSL builds (SHA-1 is disallowed
    # there for security uses, but the HIBP k-anonymity scheme uses it
    # purely as a content fingerprint for an external lookup). Without
    # this flag, the exception escapes the ``httpx.HTTPError`` handler
    # below and turns every password change into a 500 instead of
    # failing open.
    sha1 = (
        hashlib.sha1(password.encode("utf-8"), usedforsecurity=False)
        .hexdigest()
        .upper()
    )
    prefix, suffix = sha1[:5], sha1[5:]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                _RANGE_URL.format(prefix=prefix), headers=_HEADERS
            )
            response.raise_for_status()
            body = response.text
    except httpx.HTTPError as exc:
        logger.warning("HIBP lookup failed; allowing password (fail-open): %s", exc)
        return False

    # Each line: ``<35-char-hex-suffix>:<count>``. Padding lines have
    # ``count == 0`` and are still listed — match on suffix only and
    # then check the count to skip them.
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        candidate_suffix, _, count_str = line.partition(":")
        if candidate_suffix.upper() != suffix:
            continue
        try:
            count = int(count_str.strip())
        except ValueError:
            continue
        if count > 0:
            return True

    return False
