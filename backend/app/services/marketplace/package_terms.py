"""A listing's terms, as the package serving it signs them.

A package (one of the registry's delivery channels) may sign, under its own
TUF role ``package``, one file per listing it serves:
``entitlements/<listing_uid>.json``::

    {"listing_uid": "...", "access": "open" | "entitled",
     "mandatory": true | false, "meters": ["runs", ...]}

* ``access`` — who may install the listing: anyone (``open``), or a community
  holding an active entitlement statement (``entitled``).
* ``mandatory`` — every community has it, whatever the registration says. It
  can add the registration's flag and never clear it.
* ``meters`` — the usage counters the plug-in may report.

Only two shapes are valid, and anything else is refused here as the package
build refuses it: ``entitled``, not mandatory, no meters; or ``open`` and
mandatory, which may meter. The file carries nothing else.

The ``package`` role is delegated by the top-level ``targets`` role over
``entitlements/*`` and ``grants/*``. The public index carries the delegation and
no role file, which reads as "no terms here". Terms are honoured only from a
repository verified under the root shipped in the image, so a deployment
following any other root has no listing with terms.

Pure parsing and the write onto the listings; the client
(:mod:`app.services.marketplace.tuf_registry`) fetches and verifies.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import MarketplaceRegistryMessages as Codes
from app.models.platform.marketplace import (
    ACCESS_ENTITLED,
    ACCESS_OPEN,
    MarketplaceListing,
)
from app.models.platform.plugin_entitlement import METER_PATTERN
from app.models.platform.publisher import publisher_prefix
from app.services.marketplace.catalog import REGISTRY_SOURCE
from app.services.marketplace.registry_entries import RegistryError, listing_path

__all__ = [
    "MAX_TERMS_BYTES",
    "PACKAGE_ROLE",
    "ListingTerms",
    "apply_terms",
    "parse_terms",
    "terms_path",
]

#: The delegated role a package signs its terms with.
PACKAGE_ROLE = "package"
#: The directory of the package role's terms files.
TERMS_DIR = "entitlements/"
#: A terms file is a handful of short fields.
MAX_TERMS_BYTES = 4 * 1024
#: The most meters one listing's terms may name.
MAX_METERS = 32

_KEYS = frozenset({"listing_uid", "access", "mandatory", "meters"})


@dataclass(frozen=True)
class ListingTerms:
    """What a package says about one listing."""

    access: str
    mandatory: bool
    meters: tuple[str, ...] = ()


def terms_path(uid: str) -> str:
    return f"{TERMS_DIR}{uid}.json"


def _invalid(detail: str) -> RegistryError:
    return RegistryError(Codes.TERMS_INVALID, detail)


def parse_terms(raw: bytes, *, uid: str) -> ListingTerms:
    """The terms in ``raw`` for listing ``uid``. Raises ``RegistryError``."""
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise _invalid(f"{terms_path(uid)} is not JSON") from exc
    if not isinstance(document, dict):
        raise _invalid(f"{terms_path(uid)} is not a JSON object")
    extra = sorted(set(document) - _KEYS)
    if extra:
        raise _invalid(f"{terms_path(uid)} carries {', '.join(extra)}")
    if document.get("listing_uid") != uid:
        raise _invalid(f"{terms_path(uid)} names another listing")
    access = document.get("access")
    if access not in (ACCESS_OPEN, ACCESS_ENTITLED):
        raise _invalid(f"{terms_path(uid)} has no usable access")
    mandatory = document.get("mandatory")
    if not isinstance(mandatory, bool):
        raise _invalid(f"{terms_path(uid)} has no usable mandatory")
    meters = document.get("meters", [])
    if (
        not isinstance(meters, list)
        or len(meters) > MAX_METERS
        or any(
            not isinstance(m, str) or not re.fullmatch(METER_PATTERN, m) for m in meters
        )
        or len(set(meters)) != len(meters)
    ):
        raise _invalid(f"{terms_path(uid)} has no usable meters")
    if access == ACCESS_ENTITLED and (mandatory or meters):
        raise _invalid(f"{terms_path(uid)}: an entitled listing is never mandatory")
    if access == ACCESS_OPEN and not mandatory:
        raise _invalid(f"{terms_path(uid)}: an open listing with terms is mandatory")
    return ListingTerms(access=access, mandatory=mandatory, meters=tuple(meters))


async def apply_terms(
    session: AsyncSession,
    terms: Mapping[str, ListingTerms],
    *,
    keep: Collection[str] | None = (),
    uncertain: Callable[[str], bool] = lambda path: False,
) -> int:
    """Write ``terms`` onto the registry's listings; returns how many changed.

    Every registry listing takes the terms keyed by its uid, or none. A uid in
    ``keep`` keeps what it has, because its terms could not be read this time,
    as does a listing whose publisher's role did not load (``uncertain`` over
    its listing path); ``keep=None`` keeps every listing as it is. Listings
    from any other source are never touched: they hold no terms.
    """
    if keep is None:
        return 0
    listings = (
        await session.exec(
            select(MarketplaceListing).where(
                MarketplaceListing.source == REGISTRY_SOURCE
            )
        )
    ).all()
    changed = 0
    for listing in listings:
        if listing.uid in keep or uncertain(
            listing_path(publisher_prefix(listing.public_id), listing.uid)
        ):
            continue
        stated = terms.get(listing.uid)
        access = stated.access if stated else None
        mandatory = stated.mandatory if stated else False
        meters = list(stated.meters) if stated else []
        if (listing.access, listing.mandatory, list(listing.meters or [])) == (
            access,
            mandatory,
            meters,
        ):
            continue
        listing.access = access
        listing.mandatory = mandatory
        listing.meters = meters
        session.add(listing)
        changed += 1
    await session.flush()
    return changed
