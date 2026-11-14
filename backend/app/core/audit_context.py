"""What the log knows about the request a line came from.

Every audit line carries a ``context`` block: the id this request is known by,
and — when the caller reached a community through a privileged-access grant
rather than membership — which grant let them in. The id is the thread back to
the deployment's own logs, which record the same request under the same name.

Where the request came from — the address, the agent — goes only on the lines
that are about a person getting in or reaching past their own communities.
Everywhere else a line says what was done and by which account, and leaves
where they were sitting out of it. ``services.audit`` decides which is which.

The value is a **mutable holder** in a ``contextvars.ContextVar``. The
middleware that opens a request puts one there; the guild-access gate fills in
the grant half when it establishes one, and a request that used a grant keeps
saying so; ``services.audit.record`` copies it into the envelope. A holder
rather than a value per write, so what the gate adds reaches the middleware
that opened the request whichever task each of them runs in.

Background work names itself the same way: :func:`job` opens a holder for one
pass of a worker or one data job, with an id of its own, and :func:`visiting`
names the community a sweep is in. Outside both — a startup seed, a script —
there is no holder, and a line written there carries ``"context": null``.

The application log reads the same holder (``app.core.logging_config``), so a
request's audit lines and its log lines carry one id.

The address and agent are read here once per request, and everything else
that wants them — a session's bookkeeping, a rate limit's key, a captcha
check — asks :func:`client_ip` and :func:`client_user_agent` for the same
values.
"""

from __future__ import annotations

import contextvars
import ipaddress
from collections.abc import Generator, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

#: The longest client-supplied value that reaches a line. A user agent is
#: whatever the caller typed into it, and a log line is not the place to keep
#: all of it.
MAX_USER_AGENT = 256

#: What a request id may be made of, for one arriving from a proxy. Letters,
#: digits and the three separators the common formats use.
_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)
MAX_REQUEST_ID = 128


@dataclass
class RequestContext:
    """One request's own details, filled in as they become known."""

    request_id: str
    source_ip: str | None = None
    user_agent: str | None = None
    #: The country the trusted proxy says the request came from, for the
    #: decisions that depend on where somebody is. Never written to a line.
    country: str | None = None
    #: The account the request is being served as, once it has authenticated.
    actor_user_id: int | None = None
    #: The community a grant or an install reaches, or the one a background
    #: job is working in; and the grant that reaches it.
    guild_id: int | None = None
    grant_id: int | None = None
    access_level: str | None = None
    settings_grant_id: int | None = None
    settings_level: str | None = None
    #: Whether the grant was issued and approved by the same account, which is
    #: what breaking glass does.
    break_glass: bool | None = None
    #: The installed plug-in the request is being served as: its registration's
    #: ``public_id`` and the install in the community.
    plugin: str | None = None
    install_id: int | None = None
    #: The ASGI scope the request is served under. Routing fills in the route
    #: it matched and the path's parameters, which :func:`route_of` and
    #: :meth:`community_id` read.
    scope: MutableMapping[str, Any] | None = field(
        default=None, repr=False, compare=False
    )

    def community_id(self) -> int | None:
        """The community the request's path names, else the one a grant, an
        install or a job named."""
        if self.scope is not None:
            named = (self.scope.get("path_params") or {}).get("community_id")
            if isinstance(named, int):
                return named
            if isinstance(named, str) and named.isascii() and named.isdigit():
                return int(named)
        return self.guild_id

    @property
    def is_privileged(self) -> bool:
        """Whether this request is being served by a grant rather than by
        membership."""
        return self.grant_id is not None or self.settings_grant_id is not None

    def as_envelope(self, *, caller: bool) -> dict[str, Any]:
        """The ``context`` block.

        ``caller`` asks for the address and agent the request arrived from —
        which say something about the person, not only about the request, so
        they go on the lines that need them and not on the rest. The request
        id is on every line either way: it names the request without naming
        where anybody was sitting.
        """
        block: dict[str, Any] = {"request_id": self.request_id}
        if caller:
            block["source_ip"] = self.source_ip
            block["user_agent"] = self.user_agent
        if self.plugin is not None:
            block["plugin"] = self.plugin
            block["install_id"] = self.install_id
        if self.is_privileged:
            block.update(
                {
                    "grant_id": self.grant_id,
                    "access_level": self.access_level,
                    "settings_grant_id": self.settings_grant_id,
                    "settings_level": self.settings_level,
                    "break_glass": self.break_glass,
                }
            )
        return block


_request: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "audit_request_context", default=None
)


def new_request_id() -> str:
    """A fresh id for a request that arrived without one."""
    return uuid4().hex


def clean_request_id(supplied: str | None) -> str | None:
    """``supplied`` if it is a plausible request id, else ``None``.

    An id arrives from a proxy and reaches a log line, so it is held to a
    length and a character set rather than passed through as typed.
    """
    if not supplied or len(supplied) > MAX_REQUEST_ID:
        return None
    return supplied if all(char in _ID_CHARS for char in supplied) else None


def _inet(address: str | None) -> str | None:
    """``address`` as a stored ``inet`` accepts it, or ``None`` when it is not
    an address (a test client's ``testclient``, a socket with no peer).

    Normalized, and without an IPv6 zone identifier: a zone names a local
    interface, which means nothing in stored data.
    """
    if not address:
        return None
    try:
        return str(ipaddress.ip_address(address.split("%", 1)[0]))
    except ValueError:
        return None


def begin(
    *,
    request_id: str,
    source_ip: str | None = None,
    user_agent: str | None = None,
    country: str | None = None,
    scope: MutableMapping[str, Any] | None = None,
) -> tuple[RequestContext, contextvars.Token]:
    """Open a request's context and return it with the token that closes it.

    ``source_ip`` is the peer the ASGI server resolved, which is already
    whatever the deployment's proxy configuration says it is (uvicorn's
    ``FORWARDED_ALLOW_IPS``).
    """
    context = RequestContext(
        request_id=request_id,
        source_ip=_inet(source_ip),
        user_agent=(user_agent or None) and user_agent[:MAX_USER_AGENT],
        country=country,
        scope=scope,
    )
    return context, _request.set(context)


def end(token: contextvars.Token) -> None:
    """Close the request opened with ``token``."""
    _request.reset(token)


def current() -> RequestContext | None:
    """This request's context, or ``None`` outside a request."""
    return _request.get()


@contextmanager
def job(name: str, *, guild_id: int | None = None) -> Generator[RequestContext]:
    """Name one unit of background work — a worker's pass, a data job — for
    the lines written while it runs, as a request is named for its own.

    The id starts ``job-<name>-``, so a job's lines are told from a request's
    by their id alone.
    """
    context, token = begin(request_id=f"job-{name}-{uuid4().hex[:12]}")
    context.guild_id = guild_id
    try:
        yield context
    finally:
        end(token)


@contextmanager
def visiting(guild_id: int) -> Generator[None]:
    """Name the community a sweep is visiting, for the lines written there.

    A copy of the pass's context rather than a change to it: a pass visits
    several communities at once, and each visit keeps its own.
    """
    within = _request.get()
    named = replace(
        within if within is not None else RequestContext(new_request_id()),
        guild_id=guild_id,
    )
    token = _request.set(named)
    try:
        yield
    finally:
        _request.reset(token)


def route_of(scope: MutableMapping[str, Any]) -> str | None:
    """The route as it is written, rather than as it was typed; ``None``
    when no route answered."""
    # A route in an included router knows its path only without the router's
    # prefix; FastAPI keeps the whole path on the context it ran it with.
    context = scope.get("fastapi", {}).get("effective_route_context")
    path = (
        getattr(getattr(context, "starlette_route", None), "path_format", None)
        or getattr(context, "path_format", None)
        or getattr(scope.get("route"), "path", None)
    )
    return path if isinstance(path, str) else None


def note_actor(user_id: int) -> None:
    """Record the account this request authenticated as."""
    context = _request.get()
    if context is not None:
        context.actor_user_id = user_id


def client_ip() -> str | None:
    """The address this request came from, normalized; ``None`` outside a
    request or when it arrived from no address."""
    context = _request.get()
    return context.source_ip if context is not None else None


def client_user_agent() -> str | None:
    """The user agent this request named, cut to :data:`MAX_USER_AGENT`;
    ``None`` outside a request or when it named none."""
    context = _request.get()
    return context.user_agent if context is not None else None


def note_grant(
    *,
    actor_user_id: int | None,
    guild_id: int,
    grant_id: int | None = None,
    access_level: str | None = None,
    settings_grant_id: int | None = None,
    settings_level: str | None = None,
    break_glass: bool | None = None,
) -> None:
    """Record that this request reaches ``guild_id`` through a grant.

    The first grant noted is the one kept. A request establishes its own
    context before anything else runs, so the first is what admitted it; what
    a later excursion into some other community routes as does not change
    what let this request in.
    """
    context = _request.get()
    if context is None or context.is_privileged:
        return
    context.actor_user_id = actor_user_id
    context.guild_id = guild_id
    context.grant_id = grant_id
    context.access_level = access_level
    context.settings_grant_id = settings_grant_id
    context.settings_level = settings_level
    context.break_glass = break_glass


def note_install(*, plugin: str, guild_id: int, install_id: int) -> None:
    """Record that this request is an installed plug-in's, acting as ``install_id``
    in ``guild_id``."""
    context = _request.get()
    if context is None:
        return
    context.plugin = plugin
    context.guild_id = guild_id
    context.install_id = install_id


def envelope_context(*, caller: bool) -> dict[str, Any] | None:
    """The ``context`` block for a line written now, or ``None``."""
    context = _request.get()
    return context.as_envelope(caller=caller) if context is not None else None


def client_country() -> str | None:
    """The country this request came from, as the trusted proxy says;
    ``None`` outside a request or when it is not known."""
    context = _request.get()
    return context.country if context is not None else None
