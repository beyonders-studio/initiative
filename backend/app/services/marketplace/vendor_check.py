"""A plug-in's vendor check, run when its vendor values are saved.

A manifest may declare ``vendor.check`` (the plug-in contract): a call to the
vendor made before the values are written, and the rows its answer must pass.
Initiative knows no vendor here. It signs what the check says to sign, sends
what it says to send, and reads the answer with the rows the plug-in wrote
(:func:`app.services.marketplace.declarative.vendor_check`).

* **When**: a save that sets a value the check reads, whether the operator
  typed it or the vendor's own setup wrote it. A save that sets none of them
  does not ask.
* **A refusal** keeps the values from being written: the save is refused with
  ``VENDOR_CHECK_REFUSED``, naming the row's fields, its message and what it
  shows. A signing value that is not a key is refused the same way, as
  ``VENDOR_KEY_UNUSABLE``.
* **No answer** (the vendor not reached, an expression failing, an answer no
  row reads) never keeps an operator from saving: the values are written and
  the save says the check did not run.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Any

import jwt

from app.core.errors import CodedError
from app.core.messages import PluginServiceMessages
from app.services.marketplace import declarative
from app.services.marketplace.vendor_values import vendor_fields
from app.services.tenant import plugin_connection_flows as flows

logger = logging.getLogger(__name__)

__all__ = ["CheckResult", "reads", "run"]

#: A vendor value an expression names.
_VENDOR_NAME = r"\bvendor\.([A-Za-z_][A-Za-z0-9_]*)"
#: A vendor value a template names.
_TEMPLATE_NAME = r"\{vendor\.([^{}]+)\}"


class CheckResult(StrEnum):
    """What a save's vendor check came to, when it ran and refused nothing."""

    passed = "passed"
    not_run = "not_run"


def _texts(check: Mapping[str, Any]) -> Iterator[str]:
    request = check["request"]
    yield request["url"]
    yield from (request.get("query") or {}).values()
    yield from (request.get("headers") or {}).values()
    if "body" in request:
        yield request["body"]
    for row in check["expect"]:
        yield row["holds"]
        if "shows" in row:
            yield row["shows"]


def reads(check: Mapping[str, Any]) -> set[str]:
    """The vendor values a check reads: those its JWT is signed and issued
    with, and those its expressions name."""
    names = {name for text in _texts(check) for name in re.findall(_VENDOR_NAME, text)}
    sign = check.get("sign") or {}
    for template in (sign.get("iss"), sign.get("key")):
        if template:
            names.update(re.findall(_TEMPLATE_NAME, template))
    return names


def _sign(sign: Mapping[str, Any], values: Mapping[str, str]) -> str | None:
    """The JWT the check carries; ``None`` when a value it is made from is
    not set, so the check cannot run."""
    try:
        issuer = flows.render(sign["iss"], vendor=values, fields={}, in_url=False)
        key = flows.render(sign["key"], vendor=values, fields={}, in_url=False)
    except flows.ConnectionFlowError:
        return None
    now = int(time.time())
    try:
        # Issued a little early, for a vendor whose clock runs behind.
        return jwt.encode(
            {"iat": now - 30, "exp": now + sign.get("lifetime", 60), "iss": issuer},
            key,
            algorithm=sign.get("alg", "RS256"),
        )
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        logger.info("plug-in services: the vendor check's key does not sign (%s)", exc)
        raise CodedError(
            PluginServiceMessages.VENDOR_KEY_UNUSABLE,
            params={"fields": "\n".join(re.findall(_TEMPLATE_NAME, sign["key"]))},
        ) from exc


async def run(
    definition: Mapping[str, Any] | None,
    *,
    held: Mapping[str, str],
    submitted: Mapping[str, str | None],
) -> CheckResult | None:
    """Run the listing's vendor check against the values a save would leave:
    ``held`` with ``submitted`` written over it. ``None`` when there is no
    check, or the save sets nothing it reads; raises :class:`CodedError` when
    it refuses the values."""
    check = ((definition or {}).get("vendor") or {}).get("check")
    if not check or not reads(check) & set(submitted):
        return None
    values = dict(held)
    for key, value in submitted.items():
        text = value.strip() if isinstance(value, str) else ""
        if text:
            values[key] = text
        else:
            values.pop(key, None)

    credential: str | None = None
    if check.get("sign"):
        credential = _sign(check["sign"], values)
        if credential is None:
            logger.info(
                "plug-in services: a value the vendor check signs with is not set"
            )
            return CheckResult.not_run

    secret = {
        field["key"]
        for field in vendor_fields(definition)
        if field.get("type") == "secret"
    }
    try:
        refusal = await declarative.vendor_check(
            definition or {},
            check,
            vendor={key: value for key, value in values.items() if key not in secret},
            credential=credential,
        )
    except declarative.CheckNotRun as exc:
        logger.warning("plug-in services: the vendor check did not run (%s)", exc)
        return CheckResult.not_run
    if refusal is None:
        return CheckResult.passed
    params = {
        "fields": "\n".join(refusal.fields),
        "message": json.dumps(refusal.message, ensure_ascii=False),
    }
    if refusal.shows:
        params["shows"] = refusal.shows
    raise CodedError(PluginServiceMessages.VENDOR_CHECK_REFUSED, params=params)
