"""Telling whoever runs this server about a security problem: the form, what
the filing surfaces offer, and ``/.well-known/security.txt``."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from app.api.v1.platform_endpoints import tickets_test
from app.core.intake import IntakeStream
from app.core.messages import SecurityMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.tenant.comment import Comment, CommentAudience, said_on
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task

TICKETS = "/api/v1/me/tickets"


@pytest.fixture
async def security_desk(session, operations):
    """The operations community, with security reports bound too."""
    await set_rls_context(session, SystemGuild(operations["guild"].id))
    session.add(
        IntakeBinding(stream=IntakeStream.security, project_id=operations["project"].id)
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    return operations


operations = tickets_test.operations


async def _report(client, actor, **body):
    payload = {
        "stream": "security",
        "type": "vulnerability",
        "subject": "Session cookie set without Secure",
        "body": "On the sign-in response, over https.",
    }
    payload.update(body)
    return await client.post(
        TICKETS, data={"payload": json.dumps(payload)}, headers=actor.headers
    )


async def test_anyone_signed_in_can_report_and_is_its_filer(
    client, session, acting_user, security_desk
):
    reporter = await acting_user()
    offered = await tickets_test._offered(client, reporter)
    assert offered["security"]["mode"] == "form"

    filed = await _report(client, reporter)
    assert filed.status_code == 202, filed.text

    await set_rls_context(session, SystemGuild(security_desk["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    assert case.stream == IntakeStream.security
    assert case.filer_user_id == reporter.user.id
    assert case.filer_subject == "Session cookie set without Secure"
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert task.title == "Session cookie set without Secure"
    opening = (
        await session.exec(select(Comment).where(said_on("task", task.id)))
    ).one()
    assert opening.audience == CommentAudience.filer
    assert opening.content == "On the sign-in response, over https."
    await set_rls_context(session, Unattributed())


async def test_with_nothing_bound_the_address_is_offered_and_filing_says_so(
    client, session, acting_user
):
    reporter = await acting_user()
    await tickets_test._set_contacts(session, security="security@example.org")
    offered = await tickets_test._offered(client, reporter)
    assert tickets_test._offer(offered["security"]) == {
        "mode": "email",
        "contact": "security@example.org",
    }
    filed = await _report(client, reporter)
    assert filed.status_code == 503
    assert filed.json()["detail"] == SecurityMessages.NOWHERE_TO_SEND


async def test_a_report_says_what_it_is_about(client, acting_user, security_desk):
    reporter = await acting_user()
    assert (await _report(client, reporter, type="gossip")).status_code == 422
    assert (await _report(client, reporter, subject="   ")).status_code == 422


async def test_security_txt_names_the_address_and_the_form(
    client, session, security_desk
):
    assert (await client.get("/.well-known/security.txt")).status_code == 404

    await tickets_test._set_contacts(session, security="security@example.org")
    served = await client.get("/.well-known/security.txt")
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("text/plain")
    lines = served.text.splitlines()
    assert lines[0] == "Contact: mailto:security@example.org"
    assert lines[1].startswith("Contact: http") and lines[1].endswith(
        "/my-tickets?report=security"
    )
    assert any(line.startswith("Expires: ") for line in lines)
    assert "Preferred-Languages: en" in lines


async def test_security_txt_falls_back_to_the_general_address(client, session):
    await tickets_test._set_contacts(session, general="ops@example.org")
    served = await client.get("/.well-known/security.txt")
    assert served.status_code == 200
    assert served.text.splitlines()[0] == "Contact: mailto:ops@example.org"
    # No form where nothing is bound to receive it.
    assert "my-tickets" not in served.text
