"""The served wiring: what reaches which stream, at what level, and how."""

from __future__ import annotations

import json
import logging
import smtplib
from types import SimpleNamespace

import asyncpg
import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

from app.core import audit_context
from app.core.config import settings
from app.core.logging_config import (
    ACCESS_LOGGER_NAME,
    AUDIT_LOGGER_NAME,
    SERVER_LOGGER_NAME,
    configure_logging,
    logging_config,
)

LOGGER = "app.core.logging_config_test"


def _lines(capfd) -> list[dict]:
    """The JSON lines written to stderr since the last read."""
    return [json.loads(line) for line in capfd.readouterr().err.splitlines()]


@pytest.fixture(autouse=True)
def _served_wiring():
    """Apply the wiring before, and again after, so a test that pokes at a
    level leaves the process as it found it."""
    configure_logging()
    yield
    configure_logging()


def test_an_audit_line_reaches_stdout_with_nothing_forcing_the_level(capfd):
    """No ``caplog.at_level`` here: the level is the wiring's own."""
    logging.getLogger(AUDIT_LOGGER_NAME).info('{"event_type":"x"}')

    out, err = capfd.readouterr()
    assert out == '{"event_type":"x"}\n'
    assert '{"event_type":"x"}' not in err


def test_an_audit_line_is_the_bare_envelope_and_nothing_else(capfd):
    """No timestamp prefix, no level, no logger name: the line is the JSON
    object, so a pipeline parses it as a record."""
    logging.getLogger(AUDIT_LOGGER_NAME).info('{"a":1}')
    assert capfd.readouterr().out.splitlines() == ['{"a":1}']


def test_the_audit_stream_does_not_reach_the_root_handlers():
    """One envelope, one line, one place: the audit logger stops at its own
    handler rather than propagating up. (pytest's own capture attaches to the
    audit logger directly, so it would see the line either way.)"""
    configure_logging()
    assert logging.getLogger(AUDIT_LOGGER_NAME).propagate is False


def test_application_lines_go_to_stderr_as_json_naming_their_job(capfd):
    with audit_context.job("sweep", guild_id=7) as job:
        logging.getLogger(LOGGER).info("visited %s", 3)

    out, err = capfd.readouterr()
    assert "visited 3" not in out
    (line,) = [json.loads(text) for text in err.splitlines()]
    assert line["msg"] == "visited 3"
    assert line["level"] == "INFO"
    assert line["stream"] == "app"
    assert line["request_id"] == job.request_id
    assert line["guild_id"] == 7


def test_the_root_level_is_the_setting():
    assert logging_config()["root"]["level"] == settings.LOG_LEVEL
    assert (
        logging.getLogger().level == logging.getLevelNamesMapping()[settings.LOG_LEVEL]
    )


def test_loggers_configured_before_this_are_kept():
    """Uvicorn configures its own loggers before it imports the app; the
    wiring adds to the process rather than silencing them."""
    assert logging_config()["disable_existing_loggers"] is False


def test_applying_the_wiring_twice_installs_one_handler():
    configure_logging()
    configure_logging()
    assert len(logging.getLogger(AUDIT_LOGGER_NAME).handlers) == 1
    assert len(logging.getLogger().handlers) == 1


def test_uvicorns_loggers_write_through_the_one_sink():
    """Uvicorn gives its loggers handlers of its own before it imports the app;
    the wiring takes them away, so their records reach root's."""
    access = logging.getLogger(ACCESS_LOGGER_NAME)
    access.addHandler(logging.StreamHandler())
    access.propagate = False

    configure_logging()

    for name in (SERVER_LOGGER_NAME, ACCESS_LOGGER_NAME):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True


def test_the_request_line_names_the_route_and_not_the_address(capfd):
    scope = {
        "route": SimpleNamespace(path="/api/v1/communities/invite/{code}"),
        "path_params": {"code": "K7Q2ZX"},
    }
    _, token = audit_context.begin(request_id="req-1", scope=scope)
    try:
        logging.getLogger(ACCESS_LOGGER_NAME).info(
            '%s - "%s %s HTTP/%s" %d',
            "1.2.3.4",
            "GET",
            "/api/v1/communities/invite/K7Q2ZX?next=/c/1",
            "1.1",
            200,
        )
    finally:
        audit_context.end(token)

    (line,) = _lines(capfd)
    assert line["msg"] == "GET /api/v1/communities/invite/{code} 200"
    assert line["request_id"] == "req-1"
    assert (line["client"], line["method"], line["status"]) == ("1.2.3.4", "GET", 200)
    assert "K7Q2ZX" not in json.dumps(line)


def test_an_exception_keeps_its_message_unless_its_type_builds_it_from_values(
    capfd,
):
    """A message is written as raised; a database, mail or validation error
    is written as its codes, wherever it sits in the chain."""
    log = logging.getLogger(LOGGER)
    # Held in a name, so the traceback's source lines do not show it.
    address = "a@example.com"
    try:
        raise ValueError("task 3 has no status")
    except ValueError:
        log.exception("plain")
    try:
        try:
            raise asyncpg.exceptions.UniqueViolationError(
                f"duplicate key\nDETAIL:  Key (email)=({address}) already exists."
            )
        except asyncpg.PostgresError as inner:
            raise IntegrityError(
                "INSERT INTO users", {"email": address}, inner
            ) from inner
    except IntegrityError:
        log.exception("database")
    try:
        raise smtplib.SMTPRecipientsRefused({address: (550, b"no such user")})
    except smtplib.SMTPException:
        log.exception("mail")
    try:
        TypeAdapter(int).validate_python(address)
    except ValidationError:
        log.exception("validation")

    plain, database, mail, validation = [line["exc"] for line in _lines(capfd)]
    assert plain["message"] == "task 3 has no status"
    assert database["message"] == "sqlstate=23505"
    assert "The above exception was the direct cause" in database["traceback"]
    assert validation["message"] == "1 errors: int_parsing"
    assert address not in json.dumps([database, mail, validation])
