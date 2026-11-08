"""Validation and safe resolution for outbound target URLs.

Some outbound requests go to URLs a guild member can set (webhook
delivery targets and the custom AI provider base URL). These helpers
constrain such URLs to public destinations and resolve them so the
caller connects to exactly the address that was validated.

Policy: only ``https`` is accepted, and the host must resolve to globally
routable unicast addresses (private, shared, loopback, link-local,
multicast, reserved and unspecified are rejected). When a name resolves to several
addresses, all of them must pass. A local-dev setting
(``WEBHOOK_ALLOW_PRIVATE_TARGETS``) relaxes both for round-tripping with
a locally run initiative-auto; address pinning still applies.

``resolve_validated_target(_async)`` returns the approved addresses so
the caller can connect to one of them directly (see
:mod:`app.services.safe_http`). Use the async variant from coroutine
code — :func:`socket.getaddrinfo` is blocking; the sync variant is for
scripts and tests.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class WebhookTargetUrlError(ValueError):
    """Raised when a target URL is structurally invalid (bad scheme,
    missing host, unresolvable, unparseable port, etc.)."""


class WebhookTargetUrlPrivateError(ValueError):
    """Raised when a target URL resolves to a private/loopback/link-local
    address. Distinct from :class:`WebhookTargetUrlError` so the API
    layer can return a more specific error code."""


@dataclass(frozen=True)
class ValidatedTarget:
    """A target URL that passed policy. ``addresses`` are all public
    unicast; ``hostname`` is the original host to use for TLS SNI,
    certificate verification, and the ``Host`` header when connecting to
    one of ``addresses``."""

    hostname: str
    addresses: tuple[_IPAddress, ...]

    @property
    def pinned_ip(self) -> str:
        """The address to connect to. Every address passed policy, so the
        first one is used."""
        return str(self.addresses[0])


def _unwrap_mapped(ip: _IPAddress) -> _IPAddress:
    """Return the embedded IPv4 for an IPv4-mapped IPv6 address
    (``::ffff:10.0.0.1``), else the address unchanged. ``ipaddress``
    classifies the mapped form by IPv6 rules, so its ``.is_private`` etc.
    do not reflect the embedded IPv4 — unwrap before classifying."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_public_address(ip: _IPAddress) -> bool:
    """True only for globally routable unicast addresses, as the IANA
    special-purpose registries define them. Everything else (private, shared,
    loopback, link-local, multicast, reserved, unspecified) is refused."""
    ip = _unwrap_mapped(ip)
    return ip.is_global and not ip.is_multicast


def _allow_private_targets() -> bool:
    """Local-dev escape hatch, read at call time so tests can monkeypatch
    ``settings``. When true, http and private/loopback targets are
    permitted (for round-tripping with a locally run initiative-auto)."""
    from app.core.config import settings

    return settings.WEBHOOK_ALLOW_PRIVATE_TARGETS


def _parse_host(url: str, *, allow_private: bool = False) -> tuple[str, str]:
    """Parse the URL and return ``(scheme, hostname)``. Only ``https`` is
    accepted unless a private target is permitted (per-call ``allow_private``
    or the dev escape hatch), which also tentatively allows ``http``; the
    address policy then restricts that ``http`` allowance to non-public
    targets."""
    parsed = urlparse(url)
    http_ok = allow_private or _allow_private_targets()
    allowed = ("https", "http") if http_ok else ("https",)
    if parsed.scheme not in allowed:
        want = "https or http" if http_ok else "https"
        raise WebhookTargetUrlError(
            f"unsupported scheme: {parsed.scheme!r} ({want} required)"
        )
    # Credentials must not ride in the URL. A stored target is read back by its
    # owner and by guild admins, and userinfo turns the address itself into a
    # secret — receivers that need one should be given the HMAC signature or a
    # header, both of which stay out of the stored string.
    if parsed.username or parsed.password:
        raise WebhookTargetUrlError("target URL must not embed credentials")
    if not parsed.hostname:
        raise WebhookTargetUrlError("missing hostname")
    return parsed.scheme, parsed.hostname


def _addresses_from_getaddrinfo_results(infos: list, host: str) -> list[_IPAddress]:
    """Convert a ``getaddrinfo`` result list to ``ipaddress`` objects,
    stripping IPv6 zone identifiers."""
    addresses: list[_IPAddress] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            addresses.append(ipaddress.IPv4Address(sockaddr[0]))
        elif family == socket.AF_INET6:
            addr_str = sockaddr[0].split("%", 1)[0]
            addresses.append(ipaddress.IPv6Address(addr_str))
    if not addresses:
        raise WebhookTargetUrlError(f"no usable address for host {host!r}")
    return addresses


def _enforce_policy(
    host: str,
    scheme: str,
    addresses: list[_IPAddress],
    *,
    allow_private: bool = False,
) -> None:
    """Apply the scheme + address policy to a resolved target.

    Non-public addresses (private/loopback/link-local/...) require
    ``allow_private`` (per-call, e.g. an operator-configured internal
    destination) or the dev escape hatch. Public addresses always require
    https — plain http is only ever allowed when no resolved address is
    public, so a mixed set over http is rejected regardless (any address may
    be connected to)."""
    public = [a for a in addresses if _is_public_address(a)]
    non_public = [a for a in addresses if not _is_public_address(a)]

    if non_public and not (allow_private or _allow_private_targets()):
        raise WebhookTargetUrlPrivateError(
            f"host {host!r} resolves to non-public address {non_public[0]}"
        )
    if public and scheme != "https":
        raise WebhookTargetUrlError(
            f"plain http to public host {host!r} is not permitted"
        )


def _literal_or_none(host: str) -> list[_IPAddress] | None:
    """If ``host`` is an IP literal, return ``[ip]``; otherwise ``None``
    so the caller does a DNS lookup."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        return None


def resolve_validated_target(
    url: str, *, allow_private: bool = False
) -> ValidatedTarget:
    """Resolve ``url`` and apply the target policy. Use outside the event
    loop. ``allow_private`` permits private/loopback targets (still pinned)
    for operator-configured destinations. Raises
    :class:`WebhookTargetUrlError` for malformed input or
    :class:`WebhookTargetUrlPrivateError` for a disallowed non-public
    address."""
    scheme, host = _parse_host(url, allow_private=allow_private)
    addresses = _literal_or_none(host)
    if addresses is None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise WebhookTargetUrlError(
                f"could not resolve host {host!r}: {exc}"
            ) from exc
        addresses = _addresses_from_getaddrinfo_results(infos, host)
    _enforce_policy(host, scheme, addresses, allow_private=allow_private)
    return ValidatedTarget(hostname=host, addresses=tuple(addresses))


async def resolve_validated_target_async(
    url: str, *, allow_private: bool = False
) -> ValidatedTarget:
    """Async form of :func:`resolve_validated_target`. DNS runs in a
    thread so the event loop stays free."""
    scheme, host = _parse_host(url, allow_private=allow_private)
    addresses = _literal_or_none(host)
    if addresses is None:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except socket.gaierror as exc:
            raise WebhookTargetUrlError(
                f"could not resolve host {host!r}: {exc}"
            ) from exc
        addresses = _addresses_from_getaddrinfo_results(infos, host)
    _enforce_policy(host, scheme, addresses, allow_private=allow_private)
    return ValidatedTarget(hostname=host, addresses=tuple(addresses))


async def assert_target_url_is_public_async(
    url: str, *, allow_private: bool = False
) -> None:
    """Policy check only, discarding the resolution. For create/update
    validation where no connection is made yet."""
    await resolve_validated_target_async(url, allow_private=allow_private)
