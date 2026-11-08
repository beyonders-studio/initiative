"""Whether somebody is old enough for a plug-in, where they are.

A plug-in may declare ``minimum_age`` by ISO 3166-1 country, with ``default``
for every country it does not list — the age of digital consent differs by
country (13 under COPPA in the US, up to 16 under the GDPR). This module is the
one place that answers it for one person, and every path a person uses a
plug-in through asks it: the page handoff and the sidebar that offers it
(through ``guild_plugins.surface_access``), a widget's data, and connecting an
account or consenting to be acted for.

Two facts feed it, and neither is the client's to state:

* **Age** — from the date of birth the account gave, kept encrypted
  (``users.birthdate_of``). No date on file is *not allowed*: the person is
  asked for one, once, and until they answer nothing age-limited opens. On a
  deployment whose owner has turned the age check off
  (``community_age_gate_enabled``), every account counts as an adult and no
  limit applies.
* **Country** — from the request, through the header a trusted proxy in front
  of the deployment writes (``CLIENT_COUNTRY_HEADER``, ``CF-IPCountry`` behind
  Cloudflare). Read per request and never stored. Not configured, absent, or
  not a country (``XX`` unknown, ``T1`` Tor) is *not known*, and then the
  plug-in's **highest** declared age applies, so not knowing where somebody is
  never lets them in younger.

Installs are never refused here: a community installs what it likes, and the
answer is per person.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from starlette.requests import HTTPConnection

from app.core.config import settings

#: Values a country header carries that name no country.
_NOT_A_COUNTRY = frozenset({"XX", "T1"})


@dataclass(frozen=True)
class AgeViewer:
    """What an age decision needs about the person asking."""

    #: Whole years, or None when no date of birth is on file.
    age: int | None
    #: ISO 3166-1 alpha-2, or None when not known.
    country: str | None
    #: The deployment does not check age, so every account counts as an adult.
    waived: bool = False


def request_country(connection: HTTPConnection) -> str | None:
    """The client's country from the trusted header, or None."""
    header = settings.CLIENT_COUNTRY_HEADER
    if not header:
        return None
    raw = (connection.headers.get(header) or "").strip().upper()
    if len(raw) != 2 or not raw.isascii() or not raw.isalpha() or raw in _NOT_A_COUNTRY:
        return None
    return raw


async def viewer_for(connection: HTTPConnection, user_id: int) -> AgeViewer:
    """The age and country of the person making this request."""
    return await viewer_of(user_id, request_country(connection))


async def current_viewer(user_id: int) -> AgeViewer:
    """The same, for a caller that holds no request: the country from the
    request being served (``audit_context.client_country``)."""
    from app.core import audit_context

    return await viewer_of(user_id, audit_context.client_country())


async def viewer_of(user_id: int, country: str | None) -> AgeViewer:
    """The age of ``user_id``, in ``country``."""
    # Imported here so this module stays importable from ``app.api.deps``.
    from app.db.session import SystemSessionLocal
    from app.services.platform import app_settings as app_settings_service
    from app.services.platform import users as users_service

    async with SystemSessionLocal() as system_session:
        if not await app_settings_service.community_age_gate_enabled(system_session):
            return AgeViewer(age=None, country=None, waived=True)
        birthdate = await users_service.birthdate_of(system_session, user_id=user_id)
    return AgeViewer(
        age=None if birthdate is None else users_service.years_old(birthdate),
        country=country,
    )


def declared_minimum(definition: Mapping[str, Any] | None) -> dict[str, int]:
    """The plug-in's ``minimum_age`` map, or empty when it declares none."""
    raw = (definition or {}).get("minimum_age")
    if not isinstance(raw, dict):
        return {}
    return {
        str(region): age
        for region, age in raw.items()
        if isinstance(age, int) and not isinstance(age, bool)
    }


def minimum_for(
    definition: Mapping[str, Any] | None, country: str | None
) -> int | None:
    """The minimum age that applies in ``country``, or None for no limit."""
    return minimum_in(declared_minimum(definition), country)


def minimum_in(declared: Mapping[str, int], country: str | None) -> int | None:
    """The age a ``{country: years}`` map asks in ``country``, or None.

    The country's own entry, else ``default``; where the country is not known,
    the highest age declared anywhere. Plug-ins declare one map each; sign-up
    reads the platform's own (``users.ACCOUNT_MINIMUM_AGE``).
    """
    if not declared:
        return None
    if country is None:
        return max(declared.values())
    if country in declared:
        return declared[country]
    if "default" in declared:
        return declared["default"]
    return None


def age_allows(definition: Mapping[str, Any] | None, viewer: AgeViewer) -> bool:
    """Whether ``viewer`` is old enough for the plug-in ``definition`` describes."""
    if viewer.waived:
        return True
    minimum = minimum_for(definition, viewer.country)
    if minimum is None:
        return True
    return viewer.age is not None and viewer.age >= minimum
