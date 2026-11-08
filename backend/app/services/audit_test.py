"""What ``record`` writes, and what it leaves out."""

import json

import pytest

from app.core import audit_context
from app.core.audit_events import (
    SCHEMA_VERSION,
    SERVICE,
    AuditCategory,
    AuditEventType,
)
from app.core.logging_config import configure_logging
from app.services import audit as audit_service
from app.testing import create_user


@pytest.fixture(autouse=True)
def _served_logging():
    """The wiring ``app.main`` applies. No test below forces a level: what
    reaches stdout here is what reaches it in the served process."""
    configure_logging()


def _audit_lines(out: str) -> list[dict]:
    """The envelopes on a captured stdout, parsed."""
    return [
        json.loads(line)
        for line in out.splitlines()
        if line.startswith("{") and '"stream":"audit"' in line
    ]


async def test_the_envelope_carries_ids_and_no_identity(session, capfd):
    """Names are resolved by whoever reads the stream, from ids. A name
    written into the record would outlive the erasure of the account."""
    actor = await create_user(session, username="ada-admin")
    subject = await create_user(session, username="sam-subject")
    actor_id, subject_id = actor.id, subject.id
    capfd.readouterr()

    envelope = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
        target_user_id=subject_id,
        target_type="user",
        target_id=subject_id,
    )
    await session.commit()

    (line,) = _audit_lines(capfd.readouterr().out)
    assert line == envelope
    serialized = json.dumps(line)
    assert "ada-admin" not in serialized and "sam-subject" not in serialized
    assert line["schema_version"] == SCHEMA_VERSION
    assert line["service"] == SERVICE
    assert line["event_type"] == "user.avatar_removed"
    assert line["actor_user_id"] == actor_id
    assert line["target_user_id"] == subject_id
    assert line["target"] == {"type": "user", "id": subject_id}
    assert line["tier"] == 2 and line["category"] == "moderation"


async def test_nothing_is_logged_until_the_write_lands(session, capfd):
    """The line is held until the transaction commits. Staged is not done."""
    actor = await create_user(session)
    capfd.readouterr()

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
    )
    assert _audit_lines(capfd.readouterr().out) == []

    await session.commit()
    assert len(_audit_lines(capfd.readouterr().out)) == 1


async def test_a_rolled_back_action_tells_nobody(session, capfd):
    """An action that did not happen leaves no line."""
    actor = await create_user(session)
    await session.commit()
    actor_id = actor.id
    capfd.readouterr()

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
    )
    await session.rollback()
    await session.commit()

    assert _audit_lines(capfd.readouterr().out) == []


async def test_a_record_in_a_rolled_back_savepoint_tells_nobody(session, capfd):
    """A record staged inside a savepoint goes with it when the savepoint is
    rolled back, while one staged before it still lands with the commit."""
    actor = await create_user(session)
    await session.commit()
    actor_id = actor.id
    capfd.readouterr()

    kept = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
    )
    savepoint = await session.begin_nested()
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_USERNAME_CHANGED,
        actor_user_id=actor_id,
    )
    await savepoint.rollback()
    await session.commit()

    assert _audit_lines(capfd.readouterr().out) == [kept]


async def test_a_record_before_the_first_statement_lands_with_the_commit(
    session, capfd
):
    """Staged before the session has begun a transaction, the record rides
    the one the commit closes."""
    capfd.readouterr()
    envelope = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=None,
    )
    await session.commit()
    assert _audit_lines(capfd.readouterr().out) == [envelope]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # A flag and a number are copied both ways.
        (
            {"enabled": False, "port": 25},
            {"enabled": True, "port": 587},
            {
                "changed": ["enabled", "port"],
                "values": {
                    "enabled": {"from": False, "to": True},
                    "port": {"from": 25, "to": 587},
                },
            },
        ),
        # A string field is named and never copied.
        (
            {"password": "old", "host": "a"},
            {"password": "new", "host": "a"},
            {"changed": ["password"], "values": {}},
        ),
        # An enumeration is copied by value; a list of them too.
        (
            {"policy": AuditCategory.MODERATION, "methods": ["a", "b"]},
            {"policy": AuditCategory.PLATFORM, "methods": ["a"]},
            {
                "changed": ["methods", "policy"],
                "values": {"policy": {"from": "moderation", "to": "platform"}},
            },
        ),
        # Nothing moved, nothing said.
        ({"a": 1}, {"a": 1}, {"changed": [], "values": {}}),
        # A field on one side only moves from or to None.
        ({}, {"a": 1}, {"changed": ["a"], "values": {"a": {"from": None, "to": 1}}}),
    ],
)
def test_changed_fields_names_every_move_and_copies_only_safe_values(
    before, after, expected
):
    assert audit_service.changed_fields(before, after) == expected


def test_snapshot_reads_the_named_attributes():
    class Row:
        a = 1
        b = "x"
        c = None

    assert audit_service.snapshot(Row(), ["a", "b"]) == {"a": 1, "b": "x"}


@pytest.mark.parametrize(
    "event_type",
    [
        AuditEventType.AUTH_SIGNED_IN,
        AuditEventType.AUTH_SIGN_IN_FAILED,
        AuditEventType.ACCESS_GRANT_SELF_ISSUED,
        AuditEventType.PAM_REQUEST,
    ],
)
def test_getting_in_and_reaching_in_say_where_from(event_type):
    """A sign-in and a privileged reach are the two the address is part of
    the answer to."""
    assert audit_service._identifies_the_caller(event_type)


@pytest.mark.parametrize(
    "event_type",
    [
        AuditEventType.SHARING_GRANT_CHANGED,
        AuditEventType.INITIATIVE_MEMBER_ADDED,
        AuditEventType.PLUGIN_INSTALLED,
        AuditEventType.AI_REQUEST_SENT,
        AuditEventType.USER_SUSPENDED,
        AuditEventType.PLATFORM_SETTINGS_CHANGED,
    ],
)
def test_everything_else_leaves_the_person_out_of_it(event_type):
    """Somebody working in their own community is recorded as who and what,
    not as where they were sitting."""
    assert not audit_service._identifies_the_caller(event_type)


async def test_a_members_own_work_carries_the_request_and_no_address(session, capfd):
    """The line says which request made the change; a filter can still put it
    beside the deployment's own logs, and it holds nothing about the person
    beyond the account that did it."""
    actor = await create_user(session)
    _, token = audit_context.begin(
        request_id="req-1", source_ip="203.0.113.7", user_agent="Firefox/1"
    )
    try:
        capfd.readouterr()
        await audit_service.record(
            session,
            event_type=AuditEventType.SHARING_GRANT_CHANGED,
            actor_user_id=actor.id,
            guild_id=1,
        )
        await session.commit()
    finally:
        audit_context.end(token)

    (line,) = _audit_lines(capfd.readouterr().out)
    assert line["context"] == {"request_id": "req-1"}
    assert line["actor_user_id"] == actor.id


async def test_a_sign_in_carries_where_it_came_from(session, capfd):
    actor = await create_user(session)
    _, token = audit_context.begin(
        request_id="req-2", source_ip="203.0.113.7", user_agent="Firefox/1"
    )
    try:
        capfd.readouterr()
        await audit_service.record(
            session,
            event_type=AuditEventType.AUTH_SIGNED_IN,
            actor_user_id=actor.id,
        )
        await session.commit()
    finally:
        audit_context.end(token)

    (line,) = _audit_lines(capfd.readouterr().out)
    assert line["context"] == {
        "request_id": "req-2",
        "source_ip": "203.0.113.7",
        "user_agent": "Firefox/1",
    }
