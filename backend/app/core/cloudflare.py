"""Who a request came from when Cloudflare's proxy sits in front of the
deployment's own.

Cloudflare's proxied DNS in front of a local Caddy or nginx is a common way to
run a server, and the local proxy names Cloudflare's edge as the client: nginx
appends it to ``X-Forwarded-For`` and Caddy replaces the header with it. The
visitor is in ``CF-Connecting-IP``, which Cloudflare writes on every request
it passes on. So a request whose resolved client is one of Cloudflare's own
addresses is taken to come from the visitor that header names, with no setting
to make; any other request is taken as resolved.

The ranges are the ones Cloudflare publishes at https://www.cloudflare.com/ips/.
"""

from __future__ import annotations

import ipaddress

#: Cloudflare's published edge ranges.
NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def _address(
    text: str | None,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not text:
        return None
    try:
        return ipaddress.ip_address(text.strip().split("%", 1)[0])
    except ValueError:
        return None


def visitor(client: str | None, connecting_ip: str | None) -> str | None:
    """The visitor a request came from when ``client``, the address the
    server resolved, is one of Cloudflare's: the address ``CF-Connecting-IP``
    names, normalized. ``None`` when ``client`` is not Cloudflare's or the
    header names no address."""
    edge = _address(client)
    if edge is None or not any(edge in network for network in NETWORKS):
        return None
    named = _address(connecting_ip)
    return str(named) if named is not None else None
