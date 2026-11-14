"""How the served process writes its logs.

Two streams, by what reads them. Everything the process says — its own lines,
uvicorn's, the libraries' — goes to stderr, one JSON object per line, at
``LOG_LEVEL``. The ``audit`` logger goes to stdout as the bare JSON line
``services/audit.py`` hands it: one envelope per line and nothing else on the
stream, so a container-log pipeline ships it as records rather than as text
with a record somewhere inside. It does not propagate to the root logger,
which is what keeps each envelope to one line in one place.

**One sink.** Uvicorn's loggers keep no handler of their own here; they hand
their records to the root logger like every other, so one formatter writes all
of them. A record is stamped with the request or job it was written in when it
is made (:func:`_stamped`), so every line names its request, account,
community and route, whichever logger wrote it, and a test's ``caplog`` sees
the same fields.

**Uvicorn's request line** is written by uvicorn and shaped here: it names the
route template the request matched, never the address it was sent to, and no
query string (:func:`_access_fields`).

Applied when ``app.main`` is imported, which is how uvicorn loads the app, so
the wiring is the served one and not something a launcher has to remember.
Uvicorn applies its own configuration first and imports the app before it
writes its first served line. A level uvicorn's ``--log-config`` sets on a
logger not named below is kept.
"""

from __future__ import annotations

import json
import logging
import logging.config
import smtplib
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

import asyncpg
from fastapi.exceptions import ValidationException
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.exc import StatementError

from app.core import audit_context, metrics
from app.core.audit_events import SERVICE
from app.core.config import settings

#: The logger ``services/audit.py`` writes envelopes to.
AUDIT_LOGGER_NAME = "audit"
#: Uvicorn's request log, one line per request.
ACCESS_LOGGER_NAME = "uvicorn.access"
#: The logger uvicorn writes everything else to, a failed request among it.
SERVER_LOGGER_NAME = "uvicorn"

#: The attribute a record carries its request's fields in.
CONTEXT_ATTR = "log_context"

_DATABASE_ERRORS = (
    StatementError,
    AsyncAdapt_asyncpg_dbapi.Error,
    asyncpg.PostgresError,
)
_VALIDATION_ERRORS = (ValidationError, ValidationException)


class LiveStreamHandler(logging.StreamHandler):
    """A stream handler bound to ``sys.stdout`` or ``sys.stderr`` by name.

    ``logging.StreamHandler`` keeps the stream object it was given. This one
    looks the named stream up per record, so a process whose streams are
    replaced after configuration — a test harness capturing output, a
    launcher redirecting it — writes to the current one.
    """

    def __init__(self, stream_name: str) -> None:
        if stream_name not in ("stdout", "stderr"):
            raise ValueError(
                f"stream_name must be stdout or stderr, got {stream_name!r}"
            )
        self._stream_name = stream_name
        super().__init__()

    @property
    def stream(self) -> Any:  # type: ignore[override]
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, _value: Any) -> None:
        # Assigned by the base initialiser and by ``setStream``; the property
        # answers by name regardless.
        pass


def context_fields() -> dict[str, Any] | None:
    """The fields naming the request or job running now, or ``None``."""
    context = audit_context.current()
    if context is None:
        return None
    fields: dict[str, Any] = {"request_id": context.request_id}
    if context.actor_user_id is not None:
        fields["user_id"] = context.actor_user_id
    community = context.community_id()
    if community is not None:
        fields["guild_id"] = community
    if context.install_id is not None:
        fields["install_id"] = context.install_id
    if context.scope is not None:
        fields["route"] = (
            audit_context.route_of(context.scope) or metrics.UNMATCHED_ROUTE
        )
    return fields


_base_record_factory = logging.getLogRecordFactory()


def _stamped(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """A record carrying the fields of the request it was written in.

    Made only for a record that passed its logger's level, so a line nobody
    writes costs nothing here.
    """
    record = _base_record_factory(*args, **kwargs)
    setattr(record, CONTEXT_ATTR, context_fields())
    return record


def _access_fields(record: logging.LogRecord) -> dict[str, Any] | None:
    """Uvicorn's request line as fields: who asked, how, which route, and
    what it answered. The address the request was sent to is not one of them.
    """
    if record.name != ACCESS_LOGGER_NAME or not isinstance(record.args, tuple):
        return None
    if len(record.args) != 5:
        return None
    client, method, _address, http_version, status = record.args
    fields = getattr(record, CONTEXT_ATTR, None) or {}
    route = fields.get("route", metrics.UNMATCHED_ROUTE)
    return {
        "msg": f"{method} {route} {status}",
        "client": client,
        "method": method,
        "route": route,
        "status": status,
        "http": http_version,
    }


def _message(exc: BaseException) -> str:
    """What an exception says, as written to its line.

    An exception's message goes to the log as it was raised, so what a
    ``raise`` puts in its message is what the log keeps: name things by id.
    The types below build their message from the values they were handed —
    the statement's parameters, the recipients, the input — so only their codes
    are written.
    """
    from app.services.editor_engine import EditorError

    if isinstance(exc, _DATABASE_ERRORS):
        return _database_codes(exc)
    if isinstance(exc, smtplib.SMTPException):
        code = getattr(exc, "smtp_code", None)
        return f"smtp_code={code}" if code is not None else ""
    if isinstance(exc, _VALIDATION_ERRORS):
        errors = list(exc.errors())
        named = "; ".join(
            " ".join(
                part
                for part in (
                    ".".join(str(step) for step in error.get("loc", ())),
                    str(error.get("type")),
                )
                if part
            )
            for error in errors
        )
        return f"{len(errors)} errors: {named}"
    if isinstance(exc, EditorError):
        return ""
    return str(exc)


def _database_codes(exc: BaseException) -> str:
    """The codes a database error carries, from it or the errors it wraps."""
    found: dict[str, Any] = {}
    for link in _chain(exc):
        for attribute, key in (
            ("sqlstate", "sqlstate"),
            ("constraint_name", "constraint"),
            ("table_name", "table"),
        ):
            value = getattr(link, attribute, None)
            if value is not None:
                found.setdefault(key, value)
    return " ".join(f"{key}={value}" for key, value in found.items())


def _chain(exc: BaseException) -> list[BaseException]:
    """``exc`` and the exceptions it was raised from or during, outermost
    first, as Python's own traceback walks them."""
    seen: set[int] = set()
    links: list[BaseException] = []
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        seen.add(id(link))
        links.append(link)
        link = link.__cause__ or (
            None if link.__suppress_context__ else link.__context__
        )
    return links


def _type_name(exc: BaseException) -> str:
    kind = type(exc)
    if kind.__module__ == "builtins":
        return kind.__qualname__
    return f"{kind.__module__}.{kind.__qualname__}"


def render_exception(exc: BaseException) -> dict[str, Any]:
    """An exception as a line's ``exc`` field: its type, its message and the
    whole traceback, each link's message as :func:`_message` writes it."""
    links = _chain(exc)
    parts: list[str] = []
    for index, link in enumerate(reversed(links)):
        if index:
            parts.append(
                "\nThe above exception was the direct cause of the following "
                "exception:\n\n"
                if link.__cause__ is not None
                else "\nDuring handling of the above exception, another "
                "exception occurred:\n\n"
            )
        parts.append("Traceback (most recent call last):\n")
        parts.extend(traceback.format_tb(link.__traceback__))
        said = _message(link)
        parts.append(
            f"{_type_name(link)}: {said}\n" if said else f"{_type_name(link)}\n"
        )
    return {
        "type": _type_name(exc),
        "message": _message(exc),
        "traceback": "".join(parts),
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "stream": "app",
            "service": SERVICE,
        }
        line.update(getattr(record, CONTEXT_ATTR, None) or {})
        access = _access_fields(record)
        if access is not None:
            line.update(access)
        else:
            line["msg"] = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            line["exc"] = render_exception(record.exc_info[1])
        if record.stack_info:
            line["stack"] = record.stack_info
        return json.dumps(line, default=str)


def logging_config() -> dict[str, Any]:
    """The ``dictConfig`` the served process applies.

    Kept as data so a test can assert on the shape without applying it.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": "app.core.logging_config.JsonFormatter"},
            "line": {"format": "%(message)s"},
        },
        "handlers": {
            "app": {
                "()": "app.core.logging_config.LiveStreamHandler",
                "stream_name": "stderr",
                "formatter": "json",
            },
            "audit": {
                "()": "app.core.logging_config.LiveStreamHandler",
                "stream_name": "stdout",
                "formatter": "line",
            },
        },
        "root": {"level": settings.LOG_LEVEL, "handlers": ["app"]},
        "loggers": {
            AUDIT_LOGGER_NAME: {
                "level": "INFO",
                "handlers": ["audit"],
                "propagate": False,
            },
            # No handlers of their own and no level: what uvicorn set (or a
            # ``--log-config`` set) stays, and the records come to root.
            SERVER_LOGGER_NAME: {"handlers": [], "propagate": True},
            ACCESS_LOGGER_NAME: {"handlers": [], "propagate": True},
            # Every outgoing request is logged once, by ``services.safe_http``.
            "httpx2": {"level": "WARNING"},
            "httpcore2": {"level": "WARNING"},
            # fastmcp's client, which is still the original library.
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
        },
    }


def configure_logging() -> None:
    """Apply :func:`logging_config`.

    Idempotent: applying it again replaces the handlers it installed rather
    than adding to them.
    """
    logging.config.dictConfig(logging_config())
    if logging.getLogRecordFactory() is not _stamped:
        logging.setLogRecordFactory(_stamped)
