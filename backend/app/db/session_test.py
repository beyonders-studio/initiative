"""Statement timing on the engines, and the tools a commit created."""

from __future__ import annotations

import logging

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import text

from app.core import audit_context, metrics
from app.db import session as db_session
from app.testing import create_guild, create_initiative, create_project, create_user


@pytest.fixture
def every_statement_is_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session, "SLOW_STATEMENT_SECONDS", 0.0)
    # The test engine is disposed at teardown; keep it out of the pool report.
    monkeypatch.setattr(metrics, "_watched_engines", {})


def _statements_timed(label: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "initiative_db_statement_duration_seconds_count", {"engine": label}
        )
        or 0.0
    )


async def test_a_slow_statement_is_logged_with_its_request_and_never_its_values(
    engine, every_statement_is_slow, caplog: pytest.LogCaptureFixture
):
    db_session.instrument_engine(engine, "timed")
    before = _statements_timed("timed")

    _, token = audit_context.begin(request_id="req-slow-1")
    try:
        with caplog.at_level(logging.WARNING, logger=db_session.logger.name):
            async with engine.connect() as connection:
                await connection.execute(
                    text("SELECT :word AS said"), {"word": "hunter2"}
                )
    finally:
        audit_context.end(token)

    assert _statements_timed("timed") == before + 1
    assert REGISTRY.get_sample_value(
        "initiative_db_slow_statements_total", {"engine": "timed"}
    )
    [record] = [r for r in caplog.records if "timed" in r.getMessage()]
    line = record.getMessage()
    assert record.log_context["request_id"] == "req-slow-1"
    assert "SELECT" in line
    assert "hunter2" not in line


async def test_a_statement_whose_text_is_a_readers_keeps_it_out_of_the_log(
    engine, every_statement_is_slow, caplog: pytest.LogCaptureFixture
):
    db_session.instrument_engine(engine, "reader", log_text=False)

    with caplog.at_level(logging.WARNING, logger=db_session.logger.name):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 'only mine' AS note"))

    [line] = [r.getMessage() for r in caplog.records if "reader" in r.getMessage()]
    assert "only mine" not in line
    assert "SELECT" not in line


async def test_ddl_is_timed_but_never_flagged(
    engine, every_statement_is_slow, caplog: pytest.LogCaptureFixture
):
    db_session.instrument_engine(engine, "ddl", flag_slow=False)
    before = _statements_timed("ddl")

    with caplog.at_level(logging.WARNING, logger=db_session.logger.name):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    assert _statements_timed("ddl") == before + 1
    assert not [r for r in caplog.records if "ddl" in r.getMessage()]


def _tools_created(tool: str) -> float:
    return (
        REGISTRY.get_sample_value("initiative_tools_created_total", {"tool": tool})
        or 0.0
    )


async def test_a_tool_is_counted_once_its_creation_commits(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    before = _tools_created("project")

    # Committed: counted.
    await create_project(session, initiative, user)
    # Flushed in a savepoint that rolls back, inside a transaction that
    # commits: not counted.
    savepoint = await session.begin_nested()
    await create_project(session, initiative, user, commit=False)
    await session.flush()
    await savepoint.rollback()
    await session.commit()
    # Flushed in a savepoint that is released, inside a transaction that rolls
    # back: not counted.
    async with session.begin_nested():
        await create_project(session, initiative, user, commit=False)
        await session.flush()
    await session.rollback()

    assert _tools_created("project") == before + 1
