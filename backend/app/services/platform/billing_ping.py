"""Initiative's two kinds of request to the external billing service: the
ping, and its three reads.

* **The ping** says the change log moved, and nothing else: billing reads the
  log itself (``app.services.platform.billing_changes``). It's sent once per
  committed change row per process, collapsed, fire-and-forget with a tight
  timeout, and a lost one costs latency only, since billing also pulls on a
  schedule.
* **The reads** (plan summary, uninstall notice) are queries that change
  nothing on billing's side: Initiative never writes to billing.

Each request carries the v2 envelope (``app.services.platform.billing_envelope``),
signed with Initiative's handoff key (``HANDOFF_SIGNING_PRIVATE_KEY_PEM``),
the key billing already trusts for handoffs: the ping under
``initiative-billing:boundary``, a read under ``initiative-billing:reads``.

FOSS balance: on a self-hosted install (``BILLING_SERVICE_URL`` or the handoff
key unset — the default) nothing is sent and nothing is logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform import billing_envelope as envelope
from app.services.platform.identity_refs import existing_ref

logger = logging.getLogger(__name__)

PING_PATH = "/api/v1/pings"
PLAN_SUMMARY_PATH = "/api/v1/plan-summary"
UNINSTALL_NOTICE_PATH = "/api/v1/plugin-uninstall-notice"

# httpx defaults to no total deadline; keep the whole attempt short — the
# ping is advisory and must never hold resources behind a slow billing pod.
_PING_TIMEOUT = httpx2.Timeout(3.0, connect=2.0)
_PLAN_SUMMARY_TIMEOUT = httpx2.Timeout(2.0, connect=1.0)
_PLAN_SUMMARY_MAX_BYTES = 1024
#: The whole answer to an uninstall-notice read, before it is shown verbatim.
UNINSTALL_NOTICE_SECONDS = 2.0
_UNINSTALL_NOTICE_MAX_BYTES = 4096


def billing_ping_enabled() -> bool:
    """True only when a hosted deployment configured the outbound side."""
    return bool(
        settings.BILLING_SERVICE_URL and settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM
    )


def _signed_post(
    route: str, payload: dict, *, audience: str
) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one signed request. Pure — no I/O.

    The envelope is bound to the path component billing's verifier will see,
    so a base URL with a path prefix still signs correctly.
    """
    url = settings.BILLING_SERVICE_URL.rstrip("/") + route
    body = json.dumps(payload, separators=(",", ":")).encode()
    token = envelope.sign(
        settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM,
        settings.HANDOFF_SIGNING_KEY_ID,
        issuer=envelope.INITIATIVE,
        audience=audience,
        method="POST",
        path=urlsplit(url).path,
        body=body,
    )
    return (
        url,
        body,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def build_ping() -> tuple[str, bytes, dict[str, str]]:
    return _signed_post(PING_PATH, {}, audience=envelope.TO_BILLING)


async def nudge() -> None:
    """Tell billing the change log moved. One attempt, no retry; never
    raises."""
    if not billing_ping_enabled():
        return
    try:
        url, body, headers = build_ping()
        async with httpx2.AsyncClient(timeout=_PING_TIMEOUT) as client:
            await client.post(url, content=body, headers=headers)
    except Exception:
        logger.debug("billing: ping failed (billing pulls on its own schedule too)")


class PlanCharge(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    # Minor units of ``currency``.
    total: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class PlanChange(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    action: Literal["cancel", "pause", "resume"]
    on: date


class PlanSummary(BaseModel):
    """Billing's account of a guild's plan, as billing answered it.

    Read for one response and never stored: what a plan costs is billing's to
    hold (see ``app.models.platform.billing``). Fields billing adds later are
    ignored; a field that is here and malformed refuses the whole answer.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    tier_name: str | None = Field(default=None, max_length=64)
    trial_ends_on: date | None = None
    renews_on: date | None = None
    next_charge: PlanCharge | None = None
    scheduled_change: PlanChange | None = None
    payment_failed: bool = False
    #: The portal offers a plan above this one. A community billing has never
    #: seen is on the plan every community starts on, with plans above it.
    can_upgrade: bool = True
    #: The portal can cancel this plan: a card subscription is running.
    can_cancel: bool = False


def build_plan_summary_query(guild_ref: str) -> tuple[str, bytes, dict[str, str]]:
    return _signed_post(
        PLAN_SUMMARY_PATH,
        {"community_ref": guild_ref},
        audience=envelope.TO_BILLING_READS,
    )


async def guild_plan_summary(guild_id: int) -> PlanSummary | None:
    """Ask billing for ``guild_id``'s plan, or ``None`` when it cannot say.

    A read. The signed POST is a query and changes nothing on billing's side:
    initiative never writes to billing, and every change to a plan is made in
    the billing portal.

    A guild billing holds no reference for has never been there, so it has no
    trial, charge or failure to report: that is an empty summary, not a
    missing one, and nothing is minted to ask.
    """
    if not billing_ping_enabled():
        return None
    try:
        guild_ref = await existing_ref(
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=IdentityPurpose.billing,
        )
        if guild_ref is None:
            return PlanSummary()
        url, body, headers = build_plan_summary_query(guild_ref)
        async with httpx2.AsyncClient(
            timeout=_PLAN_SUMMARY_TIMEOUT, follow_redirects=False
        ) as client:
            response = await client.post(url, content=body, headers=headers)
        if (
            response.status_code != 200
            or len(response.content) > _PLAN_SUMMARY_MAX_BYTES
        ):
            return None
        return PlanSummary.model_validate_json(response.content)
    except Exception:
        return None


async def guild_payment_failed(guild_id: int) -> bool:
    """Whether billing reports ``guild_id``'s last payment as failed.

    Read from the plan summary; a summary billing cannot give says no.
    """
    summary = await guild_plan_summary(guild_id)
    return summary is not None and summary.payment_failed


class UninstallNotice(BaseModel):
    """What billing says about removing one plug-in, in the reader's language.

    Shown verbatim and kept nowhere. Fields billing adds later are ignored.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    message: str = Field(min_length=1, max_length=500)
    action_url: str | None = Field(default=None, max_length=2000)

    @field_validator("action_url")
    @classmethod
    def _web_address(cls, value: str | None) -> str | None:
        if value is not None and urlsplit(value).scheme not in ("https", "http"):
            raise ValueError("action_url is not a web address")
        return value


def build_uninstall_notice_query(
    guild_ref: str, *, listing_uid: str, locale: str
) -> tuple[str, bytes, dict[str, str]]:
    return _signed_post(
        UNINSTALL_NOTICE_PATH,
        {"community_ref": guild_ref, "listing_uid": listing_uid, "locale": locale},
        audience=envelope.TO_BILLING_READS,
    )


async def _ask_uninstall_notice(
    guild_id: int, listing_uid: str, locale: str
) -> UninstallNotice | None:
    guild_ref = await existing_ref(
        entity_type=IdentityEntity.guild,
        entity_id=guild_id,
        purpose=IdentityPurpose.billing,
    )
    if guild_ref is None:
        return None
    url, body, headers = build_uninstall_notice_query(
        guild_ref, listing_uid=listing_uid, locale=locale
    )
    async with httpx2.AsyncClient(
        timeout=_PLAN_SUMMARY_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.post(url, content=body, headers=headers)
    if (
        response.status_code != 200
        or len(response.content) > _UNINSTALL_NOTICE_MAX_BYTES
    ):
        return None
    return UninstallNotice.model_validate_json(response.content)


async def plugin_uninstall_notice(
    guild_id: int, *, listing_uid: str, locale: str
) -> UninstallNotice | None:
    """Ask billing what to tell somebody removing a plug-in, or ``None`` when
    it cannot say within :data:`UNINSTALL_NOTICE_SECONDS`.

    A read that changes nothing on billing's side. A guild billing holds no
    reference for has never been there, and is told nothing; so is one on a
    deployment with no billing.
    """
    if not billing_ping_enabled():
        return None
    try:
        return await asyncio.wait_for(
            _ask_uninstall_notice(guild_id, listing_uid, locale),
            timeout=UNINSTALL_NOTICE_SECONDS,
        )
    except Exception:
        return None
