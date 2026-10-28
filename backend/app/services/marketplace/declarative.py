"""Declarative plug-ins: Initiative makes the plug-in's calls itself.

A declarative plug-in has no container. Each of its reads and writes is a request,
or up to three named steps, rendered from JSONata expressions, sent to the
vendor with the credential its connection holds, and an expression that maps
the answers. This module runs one, exactly as the SDK's ``runEndpoint``
(``initiative-plugin-sdk/testing``) does against recorded answers, and hands back
the envelope a container answers with, ``{endpoint, actor, result}``, so
everything around the call reads it the same way.

It runs the rest of the plug-in the same way, as the SDK's runners do: a
connection's ``after_connect`` (``runAfterConnect``) and ``health``
(``runHealth``), what a vendor's delivery emits, changes in the plug-in's
values and says about a connection (``runWebhook``), a schedule's read and the
changes it makes from the answer (``runSchedule``), and the change an action
makes to the plug-in's values on its item (``runAction``).

* **What an expression sees**: ``params``, the non-secret fields of the
  connection the request carries for the call's actor as ``connection`` and
  of each connection the endpoint's ``requires`` names that this call holds
  as ``connections.<id>``, ``now``,
  for an action's call its item as ``item``, each earlier step's answer as
  ``steps.<name>`` and, once a call is answered, ``response``. Every
  expression also reads the install's ``settings`` and ``aliases``
  (:func:`~app.services.tenant.plugin_config.install_settings`). A credential
  never enters one: it is added to the request as the plug-in's ``auth`` says.
* **Where a request may go**: https, on one of the plug-in's ``hosts``, to a public
  address, following no redirect.
* **What an answer means**: the endpoint's ``errors`` rows first, then the
  defaults. A read answers ``{"unavailable": <code>}``; a write is refused
  with the code. A passing failure is the plug-in being unavailable.

The whole call is held to the envelope's limits (its time and its size); each
vendor answer to the connection egress limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import PluginChannelMessages, PluginDataMessages
from app.db import cohorts
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.services.marketplace import expressions
from app.services.marketplace.plugin_data import (
    _connection_ids,
    endpoint_by_id,
    MAX_RESPONSE_BYTES,
    PluginDataError,
    _request_connection,
    REQUEST_TIMEOUT_SECONDS,
    _required_connection_ids,
    _resolve_connections,
)
from app.services.marketplace.expressions import UNDEFINED, ExpressionError
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.marketplace.service_plugins import (
    DEFAULT_AUTH_HEADER,
    DEFAULT_AUTH_PREFIX,
    PLATFORM_CODES,
    TRANSIENT_CODE,
    _requests,
)
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.tenant import plugin_connection_flows as flows
from app.services.tenant.plugin_channels import PluginChannelError, load_install
from app.services.tenant.plugin_config import (
    connection_by_id,
    install_settings,
    without_tokens,
)
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Delivered",
    "action_change",
    "after_connect",
    "call_endpoint",
    "health_state",
    "map_delivery",
    "request_refusal",
    "run_endpoint",
    "run_schedule",
]

MAPPING_FAILED = "mapping-failed"

#: What a write refused with one of Initiative's own codes answers; any other
#: code is the vendor's state, which the write cannot act on.
_WRITE_STATUS = {"not-authorized": 403, "not-found": 404, "invalid": 400}
_STATE_REFUSED = 422


class _Outcome(Exception):
    """A call's answer, decided wherever it is: a code, or a passing failure."""

    def __init__(self, code: Optional[str] = None, *, detail: str = "") -> None:
        super().__init__(detail or code or TRANSIENT_CODE)
        self.code = code
        self.detail = detail


@dataclass
class _Answer:
    """One vendor answer, as an expression reads it."""

    status: int
    headers: dict[str, str]
    body: Any = UNDEFINED

    def read(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "headers": self.headers}
        if self.body is not UNDEFINED:
            out["body"] = self.body
        return out


@dataclass
class _Page:
    number: int = 1
    url: Optional[str] = None
    cursor: Any = UNDEFINED


def _clock(now: datetime) -> tuple[int, str]:
    """A run's time, as ``$millis()`` and ``now`` read it."""
    millis = int(now.timestamp() * 1000)
    return millis, (
        datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _text(value: Any) -> str:
    """A value as a query parameter or header carries it: a string as it is,
    anything else as JSON."""
    if isinstance(value, str):
        return value
    if value is UNDEFINED:
        return "undefined"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- addresses, as a WHATWG URL holds them ----------------------------------

#: Bytes a path, a query and a form-encoded query keep as they are.
_PATH_SAFE = "/!$&'()*+,;=:@-._~%[]|^"
_QUERY_SAFE = "/!$&()*+,;=:@-._~%?[]{}|^`\\"
_FORM_SAFE = "*-._"


def _form(value: str) -> str:
    """``application/x-www-form-urlencoded``, as ``URLSearchParams`` writes it."""
    return quote(value, safe=_FORM_SAFE).replace("~", "%7E").replace("%20", "+")


def _remove_dot_segments(path: str) -> str:
    out: list[str] = []
    for segment in path.split("/")[1:]:
        if segment in (".", "%2e", "%2E"):
            continue
        if segment in ("..", ".%2e", "%2e.", "%2e%2e", ".%2E", "%2E.", "%2E%2E"):
            if out:
                out.pop()
            continue
        out.append(segment)
    tail = path.rsplit("/", 1)[-1]
    if tail in (".", ".."):
        out.append("")
    return "/" + "/".join(out)


class _Url:
    """An absolute address, parsed and written back as ``new URL()`` does for
    the https addresses a declarative plug-in may call, with its query held as
    ``searchParams`` once anything is added to it."""

    def __init__(self, text: str) -> None:
        parts = urlsplit(text.strip())
        if not parts.scheme or not parts.netloc or not parts.hostname:
            raise ValueError(text)
        self.scheme = parts.scheme.lower()
        self.credentials = bool(parts.username or parts.password)
        self.host = parts.hostname.lower()
        port = parts.port
        self.port = (
            None if (self.scheme, port) in (("https", 443), ("http", 80)) else port
        )
        self.path = quote(_remove_dot_segments(parts.path or "/"), safe=_PATH_SAFE)
        before_fragment, hashed, _ = text.partition("#")
        self.query: Optional[str] = (
            quote(parts.query, safe=_QUERY_SAFE) if "?" in before_fragment else None
        )
        self.fragment = parts.fragment if hashed else None
        self._params: Optional[list[tuple[str, str]]] = None

    def _pairs(self) -> list[tuple[str, str]]:
        if self._params is None:
            self._params = parse_qsl(self.query or "", keep_blank_values=True)
        return self._params

    def append(self, name: str, value: str) -> None:
        self._pairs().append((name, value))

    def set(self, name: str, value: str) -> None:
        pairs = self._pairs()
        found = next((i for i, (key, _) in enumerate(pairs) if key == name), None)
        if found is None:
            pairs.append((name, value))
            return
        pairs[found] = (name, value)
        self._params = [
            pair for i, pair in enumerate(pairs) if i <= found or pair[0] != name
        ]

    def __str__(self) -> str:
        query = self.query
        if self._params is not None:
            query = (
                "&".join(f"{_form(key)}={_form(value)}" for key, value in self._params)
                or None
            )
        port = f":{self.port}" if self.port is not None else ""
        return (
            f"{self.scheme}://{self.host}{port}{self.path}"
            + (f"?{query}" if query is not None else "")
            + (f"#{self.fragment}" if self.fragment is not None else "")
        )


def _on_host(url: _Url, hosts: list[str]) -> bool:
    """https on port 443, with no credentials, on one of the plug-in's hosts: exact,
    or one label in place of a leading ``*``."""
    if url.scheme != "https" or url.port is not None or url.credentials:
        return False
    for host in hosts:
        if not host.startswith("*."):
            if url.host == host:
                return True
            continue
        suffix = host[1:]
        label = url.host[: -len(suffix)] if url.host.endswith(suffix) else ""
        if label and "." not in label:
            return True
    return False


_LINK = r"^\s*<([^>]*)>(.*)$"
_REL = r';\s*rel="?([^";]*)"?'


def _next_link(header: Optional[str], base: str) -> Optional[str]:
    """The address a Link header gives as ``rel="next"``, if any."""
    for link in (header or "").split(","):
        found = re.match(_LINK, link)
        if found is None:
            continue
        rel = re.search(_REL, found.group(2), re.IGNORECASE)
        if rel is not None and "next" in rel.group(1).split():
            return urljoin(base, found.group(1))
    return None


# --- one run -----------------------------------------------------------------


Credentials = Mapping[str, str]


class _Run:
    """One endpoint call: its clock, its hosts, its rules, its credentials
    and who it is made as."""

    def __init__(
        self,
        definition: Mapping[str, Any],
        rules: Optional[list[dict[str, Any]]],
        *,
        credentials: Credentials,
        now: datetime,
        actor: Optional[str] = None,
    ) -> None:
        auth = definition.get("auth") or {}
        self.hosts: list[str] = list(definition.get("hosts") or [])
        self.auth_header: str = auth.get("header", DEFAULT_AUTH_HEADER)
        self.auth_prefix: str = auth.get("prefix", DEFAULT_AUTH_PREFIX)
        #: The rules an answer is held to before the defaults; ``None`` holds
        #: it to neither, for a health check, whose states read every answer.
        self.rules = rules
        self.credentials = credentials
        #: Which connection a request naming one per actor carries.
        self.actor = actor
        self.millis, self.now = _clock(now)

    async def value(self, text: str, document: Any, where: str) -> Any:
        try:
            return await expressions.evaluate(text, document, millis=self.millis)
        except ExpressionError as exc:
            raise _Outcome(MAPPING_FAILED, detail=f"{where}: {exc}") from exc

    async def holds(self, text: str, document: Any, where: str) -> bool:
        try:
            return await expressions.holds(text, document, millis=self.millis)
        except ExpressionError as exc:
            raise _Outcome(MAPPING_FAILED, detail=f"{where}: {exc}") from exc

    async def render(
        self, request: Mapping[str, Any], document: dict, where: str, page: _Page
    ) -> dict[str, Any]:
        address = (
            page.url
            if page.url is not None
            else await self.value(request["url"], document, f"{where}/url")
        )
        try:
            if not isinstance(address, str):
                raise ValueError(address)
            url = _Url(address)
        except ValueError as exc:
            raise _Outcome(
                MAPPING_FAILED,
                detail=f"{where}/url: {_text(address)} is not an address",
            ) from exc
        if page.url is None:
            for name, expression in (request.get("query") or {}).items():
                value = await self.value(expression, document, f"{where}/query/{name}")
                for one in value if isinstance(value, list) else [value]:
                    if one is not UNDEFINED and one is not None:
                        url.append(name, _text(one))
        paging = request.get("paging") or {}
        if paging.get("kind") == "page_number":
            url.set(paging["page_param"], str(page.number))
            if paging.get("per_page_param"):
                url.set(paging["per_page_param"], str(paging["per_page"]))
        if paging.get("kind") == "cursor" and paging.get("param") and page.number > 1:
            url.set(paging["param"], _text(page.cursor))
        if not _on_host(url, self.hosts):
            raise _Outcome(
                MAPPING_FAILED,
                detail=(
                    f"{where}: {url} is not https on one of the plug-in's hosts "
                    f"({', '.join(self.hosts)})"
                ),
            )

        headers: dict[str, str] = {}
        for name, expression in (request.get("headers") or {}).items():
            value = await self.value(expression, document, f"{where}/headers/{name}")
            if value is not UNDEFINED and value is not None:
                headers[name] = _text(value)
        body: Any = (
            await self.value(request["body"], document, f"{where}/body")
            if "body" in request
            else UNDEFINED
        )
        graphql = request.get("graphql")
        if graphql is not None:
            variables: Any = (
                await self.value(
                    graphql["variables"], document, f"{where}/graphql/variables"
                )
                if "variables" in graphql
                else UNDEFINED
            )
            if (
                paging.get("kind") == "cursor"
                and paging.get("variable")
                and page.number > 1
            ):
                variables = {
                    **(variables if isinstance(variables, dict) else {}),
                    **(
                        {}
                        if page.cursor is UNDEFINED
                        else {paging["variable"]: page.cursor}
                    ),
                }
            body = {
                "query": graphql["query"],
                **({} if variables is UNDEFINED else {"variables": variables}),
            }
        return {
            "method": request["method"],
            "url": str(url),
            "headers": headers,
            "body": body,
            "connection": _request_connection(request, self.actor),
        }

    async def send(self, rendered: dict[str, Any]) -> _Answer:
        """One request to the vendor with its connection's credential."""
        headers = dict(rendered["headers"])
        token = self.credentials.get(rendered["connection"] or "")
        if token is not None:
            headers[self.auth_header] = (
                f"{self.auth_prefix} {token}" if self.auth_prefix else token
            )
        content: Optional[bytes] = None
        if rendered["body"] is not UNDEFINED:
            content = json.dumps(
                rendered["body"], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            if not any(name.lower() == "content-type" for name in headers):
                headers["Content-Type"] = "application/json"
        try:
            response = await request_public_target(
                rendered["method"],
                rendered["url"],
                headers=headers,
                content=content,
                timeout=flows.VENDOR_TIMEOUT_SECONDS,
                transport=flows.http_transport,
                max_bytes=flows.VENDOR_MAX_RESPONSE_BYTES,
            )
        except ResponseTooLargeError as exc:
            raise PluginDataError(
                PluginDataMessages.RESPONSE_TOO_LARGE,
                502,
                "the vendor answered too much",
            ) from exc
        except (
            httpx.HTTPError,
            WebhookTargetUrlError,
            WebhookTargetUrlPrivateError,
        ) as exc:
            raise _Outcome(detail=f"the vendor could not be reached: {exc}") from exc
        body: Any = UNDEFINED
        if response.content:
            try:
                body = json.loads(response.content)
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = response.text
        return _Answer(
            status=response.status_code,
            headers={name.lower(): value for name, value in response.headers.items()},
            body=body,
        )

    async def perform(
        self, request: Mapping[str, Any], document: dict, where: str
    ) -> _Answer:
        """One request, every page of it, held to the rules and the defaults."""
        paging = request.get("paging")
        items: list[Any] = []
        page = _Page()
        while True:
            rendered = await self.render(request, document, where, page)
            answer = await self.send(rendered)
            read = {**document, "response": answer.read()}
            if self.rules is not None:
                for index, rule in enumerate(self.rules):
                    if not _matches(rule["status"], answer.status):
                        continue
                    if "when" in rule and not await self.holds(
                        rule["when"], read, f"errors/{index}/when"
                    ):
                        continue
                    raise _Outcome(
                        None if rule["code"] == TRANSIENT_CODE else rule["code"]
                    )
                if not 200 <= answer.status <= 299:
                    raise _Outcome(_by_default(answer.status))
            if not paging:
                return answer

            got = (
                await self.value(paging["items"], read, f"{where}/paging/items")
                if "items" in paging
                else answer.body
            )
            if isinstance(got, list):
                items.extend(got)
            elif got is not UNDEFINED:
                items.append(got)
            if paging["kind"] == "page_number":
                count = len(got) if isinstance(got, list) else int(got is not UNDEFINED)
                more = count >= paging["per_page"]
            elif paging["kind"] == "link_header":
                page.url = _next_link(answer.headers.get("link"), rendered["url"])
                more = page.url is not None
            else:
                more = await self.holds(paging["more"], read, f"{where}/paging/more")
                page.cursor = await self.value(
                    paging["next"], read, f"{where}/paging/next"
                )
            if (
                more
                and page.number == paging["max_pages"]
                and paging["on_limit"] == "refuse"
            ):
                raise _Outcome("range-too-large")
            if not more or page.number == paging["max_pages"]:
                return _Answer(answer.status, answer.headers, items)
            page.number += 1


def _matches(status: int | str, actual: int) -> bool:
    if isinstance(status, int):
        return status == actual
    return status[0] == str(actual)[0]


def _by_default(status: int) -> Optional[str]:
    """What an answer outside 2xx means when no rule says; ``None`` is a
    passing failure."""
    if status in (401, 403):
        return "not-authorized"
    if status == 404:
        return "not-found"
    if status != 429 and 400 <= status < 500:
        return "invalid"
    return None


def _fits(answer: Any, returns: list[dict[str, Any]]) -> Optional[str]:
    """Why a mapped answer does not fit the declared returns, or ``None``."""
    if not isinstance(answer, dict):
        return (
            f"answered {_text(answer)}, which is not an object of the declared returns"
        )
    declared = {entry["key"]: entry for entry in returns}
    for key, value in answer.items():
        spec = declared.get(key)
        if spec is None:
            return f"answered {key!r}, which is not a declared return"
        if value is None:
            continue
        listed = spec.get("list") is True
        if listed and not isinstance(value, list):
            return f"answered {key!r} as {_text(value)}, and it is declared a list"
        for one in value if listed else [value]:
            if spec["type"] == "int":
                ok = isinstance(one, int) and not isinstance(one, bool)
            elif spec["type"] == "bool":
                ok = isinstance(one, bool)
            else:
                ok = isinstance(one, str)
            if not ok:
                return f"answered {key!r} as {_text(one)}, which is not {spec['type']}"
    return None


async def _stepped(
    run: _Run,
    spec: Mapping[str, Any],
    base: dict[str, Any],
    where: str,
    *,
    connection: Optional[Callable[[Mapping[str, Any]], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Make ``spec``'s request, or its named steps in turn, over ``base``, and
    answer what its map reads: ``base``, each earlier step's answer as
    ``steps.<name>`` and the last answer as ``response``. With ``connection``,
    each request's expressions also read the connection it carries."""
    steps = spec.get("steps") or [{"name": "", "request": spec["request"]}]
    named = "steps" in spec
    answers: dict[str, Any] = {}
    read: dict[str, Any] = base
    for index, step in enumerate(steps):
        request = step["request"]
        read = {
            **base,
            **({"connection": connection(request)} if connection else {}),
            **({"steps": dict(answers)} if named else {}),
        }
        at = f"{where}steps/{index}/request" if named else f"{where}request"
        response = (await run.perform(request, read, at)).read()
        if named:
            answers[step["name"]] = response
        read = {
            **read,
            **({"steps": dict(answers)} if named else {}),
            "response": response,
        }
    return read


async def run_endpoint(
    definition: Mapping[str, Any],
    endpoint: Mapping[str, Any],
    *,
    params: Mapping[str, Any],
    connections: Mapping[str, Mapping[str, Any]],
    credentials: Credentials,
    now: datetime,
    installed: Mapping[str, Any],
    item: Optional[Mapping[str, Any]] = None,
    element: Optional[str] = None,
    actor: Optional[str] = None,
) -> dict[str, Any]:
    """One declarative endpoint's answer: its result, or ``{"unavailable":
    <code>}``.

    ``connections`` holds each connection's non-secret fields and
    ``credentials`` its token, by connection id. The call is made as
    ``actor``: a request carries the connection it names, or, naming one per
    actor, the one it names for ``actor``. Expressions read a request's own
    connection as ``connection``, every connection the endpoint's
    ``requires`` names as ``connections.<id>``, the install's ``settings`` and
    ``aliases`` (``installed``), the ``item`` an action's call is made on and
    the ``element`` of a list it was run from. A passing failure raises
    :class:`PluginDataError` as the plug-in being unavailable.
    """
    run = _Run(
        definition,
        list(endpoint.get("errors") or []),
        credentials=credentials,
        now=now,
        actor=actor,
    )
    required, _ = _required_connection_ids(endpoint)
    base = {
        "params": dict(params),
        "connections": {
            connection_id: dict(connections[connection_id])
            for connection_id in required
            if connection_id in connections
        },
        "now": run.now,
        **installed,
        **({} if item is None else {"item": dict(item)}),
        **({} if element is None else {"element": element}),
    }
    try:
        read = await _stepped(
            run,
            endpoint,
            base,
            "",
            connection=lambda request: dict(
                connections.get(_request_connection(request, actor) or "") or {}
            ),
        )
        answer = await run.value(endpoint["map"], read, "map")
        if isinstance(answer, dict) and "unavailable" in answer:
            code = answer["unavailable"]
            codes = {*(endpoint.get("unavailable") or []), *PLATFORM_CODES}
            if not isinstance(code, str) or code not in codes:
                raise _Outcome(
                    MAPPING_FAILED,
                    detail=f"map answered unavailable {_text(code)}, not one of its codes",
                )
            return {"unavailable": code}
        problem = _fits(answer, endpoint.get("returns") or [])
        if problem is not None:
            raise _Outcome(MAPPING_FAILED, detail=f"map {problem}")
        return answer
    except _Outcome as outcome:
        if outcome.code is None:
            raise PluginDataError(
                PluginDataMessages.SERVICE_UNAVAILABLE,
                502,
                outcome.detail or "transient",
            ) from outcome
        if outcome.detail:
            logger.info(
                "plug-in data: %s answered %s", endpoint.get("id"), outcome.code
            )
        return {"unavailable": outcome.code}


# --- a connection's own requests --------------------------------------------


async def after_connect(
    definition: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    params: Mapping[str, str],
    access_token: str,
    installed: Mapping[str, Any],
    now: Optional[datetime] = None,
) -> flows.AfterConnect:
    """A declarative ``after_connect``: its request or steps made with the
    token the flow just obtained, its map's ``{values, account_label}``, and a
    refusal with the declared code when ``refuse_when`` holds over the map's
    answer.

    Its expressions read the flow's ``params``, ``now``, the install's
    ``settings`` and ``aliases`` (``installed``), each earlier step's answer as
    ``steps.<name>`` and, once a call is answered, ``response``. An answer the
    defaults refuse, a passing failure or an expression that fails raises
    :class:`~app.services.tenant.plugin_connection_flows.HookError`, as a hook
    that fails does.
    """
    run = _Run(
        definition,
        [],
        credentials={"": access_token},
        now=now or datetime.now(timezone.utc),
    )
    base: dict[str, Any] = {"params": dict(params), "now": run.now, **installed}
    try:
        read = await _stepped(run, after, base, "after_connect/")
        result = await run.value(after["map"], read, "after_connect/map")
        if not isinstance(result, dict):
            raise _Outcome(
                MAPPING_FAILED,
                detail=f"after_connect/map answered {_text(result)}, "
                "which is not {values, account_label}",
            )
        if "refuse_when" in after and await run.holds(
            after["refuse_when"], {**read, "result": result}, "refuse_when"
        ):
            return flows.AfterConnect(
                refused=True, values={}, account_label=None, code=after["code"]
            )
    except _Outcome as outcome:
        raise flows.HookError(
            f"after_connect answered {outcome.code or TRANSIENT_CODE}"
        ) from outcome
    except PluginDataError as exc:
        raise flows.HookError(f"after_connect answered {exc.code}") from exc
    return flows.connected(result)


async def health_state(
    definition: Mapping[str, Any],
    health: Mapping[str, Any],
    *,
    fields: Mapping[str, Any],
    access_token: str,
    installed: Mapping[str, Any],
    now: Optional[datetime] = None,
) -> str:
    """A connection's health check: its request made with the connection's
    credential, and the state its ``states`` read from the answer.

    Its expressions read the connection's non-secret ``fields`` as
    ``connection``, and the install's ``settings`` and ``aliases``
    (``installed``). An answer no row matches is ``ok`` when it is 2xx and
    ``unavailable`` otherwise; a request that could not be made or read is
    ``unavailable``.
    """
    run = _Run(
        definition,
        None,
        credentials={"": access_token},
        now=now or datetime.now(timezone.utc),
    )
    document: dict[str, Any] = {
        "params": {},
        "connection": dict(fields),
        "now": run.now,
        **installed,
    }
    try:
        answer = await run.perform(health["request"], document, "health/request")
        response = answer.read()
        for index, row in enumerate(health["states"]):
            if "status" in row and not _matches(row["status"], answer.status):
                continue
            if "when" in row and not await run.holds(
                row["when"], {**document, "response": response}, f"states/{index}/when"
            ):
                continue
            return row["state"]
        return "ok" if 200 <= answer.status <= 299 else "unavailable"
    except (_Outcome, PluginDataError) as exc:
        logger.info(
            "plug-in health: the check answered no state (%s)",
            exc.code or TRANSIENT_CODE,
        )
        return "unavailable"


# --- an action's change ------------------------------------------------------


async def action_change(
    write: str,
    *,
    item: Mapping[str, Any],
    held: Mapping[str, Any],
    installed: Mapping[str, Any],
    result: Any = UNDEFINED,
    params: Optional[Mapping[str, Any]] = None,
    element: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """The change a declarative action's ``write`` answers, as the SDK's
    ``runAction`` reads it: the one Initiative makes to the plug-in's values
    on the action's own item, or ``None`` when it answers nothing.

    ``write`` reads ``item`` (its ``kind``, ``id`` and ``title``), ``held``
    (the install's values on it, by key), ``result`` (the endpoint's mapped
    answer, absent when the action names no endpoint), ``params`` (what the
    reader answered, in the endpoint's declared types), ``element`` (the
    ``ref`` of the list element the action was run from, absent when it was
    not), the install's ``settings`` and ``aliases`` (``installed``) and
    ``now``. A change names no target: its item is the action's. The rest of
    the contract's ``change`` is held where the change is made
    (``metadata.apply_changes``). An expression that fails, or an
    answer that is not a change, raises :class:`PluginDataError` as the
    plug-in being unavailable.
    """
    millis, at = _clock(now or datetime.now(timezone.utc))
    document: dict[str, Any] = {
        "item": dict(item),
        "held": dict(held),
        "params": dict(params or {}),
        **installed,
        "now": at,
    }
    if result is not UNDEFINED:
        document["result"] = result
    if element is not None:
        document["element"] = element
    try:
        change = await expressions.evaluate(write, document, millis=millis)
    except ExpressionError as exc:
        raise PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE, 502, f"write: {exc}"
        ) from exc
    if change is UNDEFINED:
        return None
    if not isinstance(change, dict) or "target" in change:
        raise PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE,
            502,
            f"write answered {_text(change)}, which is not a change",
        )
    return change


# --- a vendor's deliveries ---------------------------------------------------


@dataclass(frozen=True)
class Delivered:
    """What one delivery emits, the changes it makes to the plug-in's values,
    and the connection state it sets."""

    #: The emit endpoint's id and its payload.
    event: Optional[tuple[str, dict[str, Any]]] = None
    #: What the matched row's ``write`` answered: the changes the install makes
    #: to its values (``metadata.apply_changes``), :data:`UNDEFINED`
    #: when the row has no ``write`` or it answered nothing.
    writes: Any = UNDEFINED
    #: The connection and its state.
    status: Optional[tuple[str, str]] = None
    #: Why ``events`` or ``status`` answered nothing, when an expression of
    #: theirs failed or a payload did not fit: the same delivery fails the
    #: same way again.
    failures: tuple[str, ...] = ()


async def map_delivery(
    definition: Mapping[str, Any],
    *,
    headers: Mapping[str, str],
    payload: Any,
    connection: Mapping[str, Any],
    installed: Mapping[str, Any],
    now: Optional[datetime] = None,
) -> Delivered:
    """One webhook delivery, as a declarative plug-in's ``webhooks`` map it: the
    first ``events`` row whose ``when`` holds gives the event it emits, its
    payload held to the emit endpoint's returns, and the changes its ``write``
    answers; and the first matching ``status`` row gives the state it sets. A
    delivery nothing matches answers none of them.

    The expressions read ``headers`` (names in lowercase), ``payload``, the
    routed connection's non-secret fields as ``connection``, ``now``, and the
    install's ``settings`` and ``aliases`` (``installed``). The event, the
    changes and the state are read apart: one failing leaves the others'
    answers, and where it failed is in ``failures``. An evaluation that
    may answer if asked again raises :class:`ExpressionError` with
    ``transient`` set.
    """
    millis, at = _clock(now or datetime.now(timezone.utc))
    document = {
        "headers": {name.lower(): value for name, value in headers.items()},
        "payload": payload,
        "connection": dict(connection),
        "now": at,
        **installed,
    }
    webhooks = definition.get("webhooks") or {}
    returns = {
        entry.get("id"): entry.get("returns") or []
        for entry in definition.get("endpoints") or []
        if isinstance(entry, dict)
    }
    failures: list[str] = []

    async def first(what: str) -> Optional[tuple[int, dict[str, Any]]]:
        """The first row of ``what`` whose ``when`` holds."""
        for index, row in enumerate(webhooks.get(what) or []):
            try:
                if await expressions.holds(row["when"], document, millis=millis):
                    return index, row
            except ExpressionError as exc:
                if exc.transient:
                    raise
                failures.append(f"{what}/{index}/when: the expression failed")
                return None
        return None

    event: Optional[tuple[str, dict[str, Any]]] = None
    writes: Any = UNDEFINED
    matched = await first("events")
    if matched is not None:
        index, row = matched
        if "emit" in row:
            where = f"events/{index}/map"
            try:
                mapped = await expressions.evaluate(row["map"], document, millis=millis)
            except ExpressionError as exc:
                if exc.transient:
                    raise
                failures.append(f"{where}: the expression failed")
            else:
                problem = _fits(mapped, returns.get(row["emit"]) or [])
                if problem is None:
                    event = (row["emit"], mapped)
                else:
                    failures.append(
                        f"{where}: the {row['emit']} event does not fit its returns"
                    )
        if "write" in row:
            try:
                writes = await expressions.evaluate(
                    row["write"], document, millis=millis
                )
            except ExpressionError as exc:
                if exc.transient:
                    raise
                failures.append(f"events/{index}/write: the expression failed")
    status: Optional[tuple[str, str]] = None
    matched = await first("status")
    if matched is not None:
        status = (matched[1]["connection"], matched[1]["state"])
    return Delivered(
        event=event, writes=writes, status=status, failures=tuple(failures)
    )


# --- a schedule's run ----------------------------------------------------------


async def run_schedule(
    session: AsyncSession,
    *,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    guild_id: int,
    schedule: Mapping[str, Any],
    since: Optional[str],
) -> Any:
    """One run of an install's declarative schedule, as the SDK's
    ``runSchedule`` makes it: its read is made as the installation, with the
    params its ``params`` answers, and its ``write`` answers, from the read's
    answer, the changes the install makes to its values
    (``metadata.apply_changes``). Answers what ``write`` answered,
    :data:`UNDEFINED` for nothing.

    ``params`` reads ``since`` (when the schedule last succeeded in the
    community, ISO 8601, or null), ``now``, ``connection``, the non-secret
    fields of the connection the read's first request names, and the install's
    ``settings`` and ``aliases``, and answers an object or nothing. ``write``
    reads the read's mapped answer as ``result``, ``since``, ``now``,
    ``settings`` and ``aliases``. The read is held to the envelope's time, as
    :func:`call_endpoint`'s is.

    The read's expressions read each community connection its ``requires``
    names as ``connections.<id>``, as a call the installation makes does.

    Raises :class:`PluginDataError`: with ``CONNECTION_NO_TOKEN``, before
    anything is asked of the vendor, while a community connection the read
    names is not stored, or those its ``requires`` names hold no value; with
    the code the read answered unavailable with;
    with ``mapping-failed`` when ``params`` or ``write`` fails or ``params``
    answers something other than an object; and otherwise as
    :func:`call_endpoint` refuses a call or finds the plug-in unavailable.
    """
    endpoint = endpoint_by_id(plugin.definition, schedule["endpoint"])
    if endpoint is None:
        raise PluginDataError(PluginDataMessages.ENDPOINT_NOT_FOUND, 404)
    try:
        refs, required = await _resolve_connections(
            session,
            plugin=plugin,
            endpoint=endpoint,
            user_id=None,
            actor="installation",
        )
    except PluginDataError as exc:
        # A community connection the read names is not made: the run is
        # skipped rather than failed, until it is.
        raise PluginDataError(PluginChannelMessages.CONNECTION_NO_TOKEN, 409) from exc
    now = datetime.now(timezone.utc)
    run = _Run(plugin.definition, None, credentials={}, now=now)
    steps = endpoint.get("steps") or [{"request": endpoint["request"]}]
    connection = without_tokens(
        (plugin.config or {}).get(
            _request_connection(steps[0]["request"], "installation") or ""
        )
    )
    installed = install_settings(plugin)
    try:
        params = (
            await run.value(
                schedule["params"],
                {
                    "since": since,
                    "now": run.now,
                    "connection": connection,
                    **installed,
                },
                "params",
            )
            if "params" in schedule
            else UNDEFINED
        )
        if params is not UNDEFINED and not isinstance(params, dict):
            raise PluginDataError(MAPPING_FAILED, _STATE_REFUSED)
        result, _ = await _answered(
            registration=registration,
            plugin=plugin,
            guild_id=guild_id,
            endpoint=endpoint,
            params={} if params is UNDEFINED else params,
            refs=refs,
            fields=required,
            actor="installation",
            now=now,
        )
        if set(result) == {"unavailable"}:
            raise PluginDataError(result["unavailable"], _STATE_REFUSED)
        return await run.value(
            schedule["write"],
            {"result": result, "since": since, "now": run.now, **installed},
            "write",
        )
    except _Outcome as exc:
        raise PluginDataError(MAPPING_FAILED, _STATE_REFUSED) from exc


# --- the call behind ``_call_plugin`` -------------------------------------------


def typed_params(
    endpoint: Mapping[str, Any], params: Mapping[str, Any]
) -> dict[str, Any]:
    """The parameters as the caller sent them: the checked values, which
    travel as text to a container, back in their declared types."""
    declared = {
        entry["key"]: entry.get("type")
        for entry in endpoint.get("params") or []
        if isinstance(entry, dict)
    }

    def one(kind: Any, value: Any) -> Any:
        if kind == "int":
            return int(value)
        if kind == "bool":
            return value == "true"
        return value

    return {
        key: [one(declared.get(key), item) for item in value]
        if isinstance(value, list)
        else one(declared.get(key), value)
        for key, value in params.items()
    }


def _refusal(connection: Optional[Mapping[str, Any]]) -> PluginDataError:
    """A call refused for want of ``connection``: a member's own is theirs to
    connect, and the community's is its admins' to configure."""
    return PluginDataError(
        PluginDataMessages.CONNECTION_REQUIRED
        if (connection or {}).get("scope") == "interactive"
        else PluginDataMessages.NEEDS_CONFIGURATION,
        409,
    )


def request_refusal(
    definition: Any,
    endpoint: Mapping[str, Any],
    refs: Mapping[str, str],
    actor: Optional[str],
) -> Optional[PluginDataError]:
    """Why the endpoint's requests cannot be made as ``actor`` with the
    handles ``refs``, before any token is asked for: one naming no connection
    for ``actor`` (one per actor, on a call made as another or as none), a
    connection one names that ``definition`` does not declare, a member's own
    whose handle ``refs`` lacks, or, on a member's behalf, the community's
    when the endpoint's ``requires`` does not name it. ``None`` when they
    can."""
    required, _ = _required_connection_ids(endpoint)
    for request in _requests(endpoint):
        connection_id = _request_connection(request, actor)
        connection = (
            connection_by_id(definition, connection_id) if connection_id else None
        )
        interactive = (connection or {}).get("scope") == "interactive"
        if (
            connection is None
            or (interactive and connection_id not in refs)
            or (not interactive and actor == "member" and connection_id not in required)
        ):
            return _refusal(connection)
    return None


async def _credentials(
    *,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    guild_id: int,
    endpoint: Mapping[str, Any],
    refs: Mapping[str, str],
    actor: Optional[str],
) -> tuple[dict[str, str], dict[str, dict[str, Any]], bool]:
    """Each connection the endpoint's requests carry on a call made as
    ``actor``: its token and non-secret fields, and whether any is a
    member's own.

    A static connection's is the community's, which a call on a member's
    behalf carries only when the endpoint's ``requires`` names it; an
    interactive one's is the acting member's, by the handle resolved for
    them (:func:`request_refusal`). Tokens are refreshed or minted as the
    plug-in channel hands them out.
    """
    tokens: dict[str, str] = {}
    fields: dict[str, dict[str, Any]] = {}
    member = False
    async with cohorts.system_session(guild_id) as session:
        try:
            install = await load_install(
                session,
                registration,
                guild_id,
                plugin_install_id=plugin.id,
                for_write=True,
            )
        except PluginChannelError as exc:
            raise PluginDataError(exc.code, exc.status_code) from exc
        refused = request_refusal(install.definition, endpoint, refs, actor)
        if refused is not None:
            raise refused
        for connection_id in _connection_ids(endpoint, actor):
            connection = connection_by_id(install.definition, connection_id)
            interactive = (connection or {}).get("scope") == "interactive"
            refusal = _refusal(connection)
            ref = refs.get(connection_id)
            try:
                if interactive:
                    held = await flows.member_token(
                        session,
                        plugin=install,
                        public_id=registration.public_id,
                        connection_ref=str(ref),
                        guild_id=guild_id,
                    )
                    row = (
                        await session.exec(
                            select(GuildPluginUserConnection).where(
                                GuildPluginUserConnection.plugin_id == install.id,
                                GuildPluginUserConnection.connection_ref == ref,
                            )
                        )
                    ).first()
                    values = row.config if row is not None else None
                    member = True
                else:
                    held = await flows.community_token(
                        session,
                        plugin=install,
                        public_id=registration.public_id,
                        connection_id=connection_id,
                        guild_id=guild_id,
                    )
                    values = (install.config or {}).get(connection_id)
            except flows.ConnectionFlowError as exc:
                raise refusal from exc
            if held is None:
                raise refusal
            tokens[connection_id] = held.access_token
            fields[connection_id] = without_tokens(values)
    return tokens, fields, member


async def _answered(
    *,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    guild_id: int,
    endpoint: Mapping[str, Any],
    params: Mapping[str, Any],
    refs: Mapping[str, str],
    fields: Mapping[str, Mapping[str, Any]],
    actor: Optional[str],
    item: Optional[Mapping[str, Any]] = None,
    element: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[dict[str, Any], bool]:
    """One endpoint's answer for a call made as ``actor``, and whether a
    member's own connection was used. The credentials come first, outside
    the call's budget: a refresh the budget cut short would lose what the
    vendor had just issued. The pages are held to it."""
    tokens, used, member = await _credentials(
        registration=registration,
        plugin=plugin,
        guild_id=guild_id,
        endpoint=endpoint,
        refs=refs,
        actor=actor,
    )
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
            result = await run_endpoint(
                plugin.definition,
                endpoint,
                params=params,
                connections={**used, **fields},
                credentials=tokens,
                now=now or datetime.now(timezone.utc),
                installed=install_settings(plugin),
                item=item,
                element=element,
                actor=actor,
            )
    except TimeoutError as exc:
        raise PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE, 502, "the call ran out of time"
        ) from exc
    return result, member


async def call_endpoint(
    *,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    guild_id: int,
    endpoint_id: str,
    params: Mapping[str, Any],
    refs: Mapping[str, str],
    fields: Mapping[str, Mapping[str, Any]],
    actor: Optional[str],
    item: Optional[Mapping[str, Any]] = None,
    element: Optional[str] = None,
) -> dict[str, Any]:
    """One declarative endpoint of an install, answered as a container
    answers: ``{endpoint, actor, result}``.

    ``fields`` is each satisfied connection's non-secret fields as the
    caller's resolution read them, which the response cache key holds, so
    the expressions read those. ``item`` is the item an action's call is made
    on and ``element`` the list element it was run from, which they read too.

    Held to the envelope's time and size, as a container's answer is; each
    vendor answer to the connection egress limits.
    """
    endpoint = endpoint_by_id(
        plugin.definition, endpoint_id, directions=("read", "write")
    )
    if endpoint is None:
        raise PluginDataError(PluginDataMessages.ENDPOINT_NOT_FOUND, 404)
    result, member = await _answered(
        registration=registration,
        plugin=plugin,
        guild_id=guild_id,
        endpoint=endpoint,
        params=typed_params(endpoint, params),
        refs=refs,
        fields=fields,
        actor=actor,
        item=item,
        element=element,
    )
    if endpoint["direction"] == "write" and set(result) == {"unavailable"}:
        code = result["unavailable"]
        raise PluginDataError(code, _WRITE_STATUS.get(code, _STATE_REFUSED))
    body = {
        "endpoint": endpoint_id,
        "actor": actor or ("member" if member else "installation"),
        "result": result,
    }
    if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PluginDataError(
            PluginDataMessages.RESPONSE_TOO_LARGE,
            502,
            "the answer exceeded the ceiling",
        )
    return body
