"""Feedback: what the sheet offers, what a filing becomes, and the app context
that travels with it."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from app.api.v1.platform_endpoints import tickets_test
from app.core.intake import IntakeStream
from app.core.messages import AppealMessages, FeedbackMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task

TICKETS = "/api/v1/me/tickets"

operations = tickets_test.operations


@pytest.fixture
async def feedback_desk(session, operations):
    """The operations community, with feedback bound too."""
    await set_rls_context(session, SystemGuild(operations["guild"].id))
    session.add(
        IntakeBinding(stream=IntakeStream.feedback, project_id=operations["project"].id)
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    return operations


async def _send(client, actor, **body):
    payload = {"stream": "feedback", "type": "idea", "body": "Dark mode for print."}
    payload.update(body)
    return await client.post(
        TICKETS, data={"payload": json.dumps(payload)}, headers=actor.headers
    )


async def test_the_form_is_offered_wherever_feedback_is_taken(
    client, acting_user, feedback_desk
):
    sender = await acting_user()
    offered = (await tickets_test._offered(client, sender))["feedback"]
    assert offered["mode"] == "form"
    assert offered["types"] == ["idea", "problem", "praise", "other"]


async def test_feedback_is_a_case_its_sender_follows(
    client, session, acting_user, feedback_desk
):
    """Their words open the case, said to them; the team's board names it by
    its kind and how it begins, and nothing the sender typed becomes a
    subject of theirs."""
    sender = await acting_user()
    response = await _send(
        client, sender, type="problem", body="Export drops the last row.\nEvery time."
    )
    assert response.status_code == 202, response.text

    await set_rls_context(session, SystemGuild(feedback_desk["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    assert case.stream == IntakeStream.feedback
    assert case.topic == "problem"
    assert case.filer_user_id == sender.user.id
    assert case.filer_subject is None
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert task.title == "Problem: Export drops the last row."
    opening = (
        await session.exec(select(Comment).where(Comment.task_id == task.id))
    ).one()
    assert opening.audience == CommentAudience.filer
    assert opening.content == "Export drops the last row.\nEvery time."
    await set_rls_context(session, Unattributed())


async def test_the_app_context_goes_to_the_team_where_it_was_sent(
    client, session, acting_user, feedback_desk
):
    sender = await acting_user()
    response = await _send(client, sender, context=tickets_test.DEVICE)
    assert response.status_code == 202, response.text

    await set_rls_context(session, SystemGuild(feedback_desk["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    for value in tickets_test.DEVICE.values():
        assert f"`{value}`" in task.description
    await set_rls_context(session, Unattributed())


async def test_removed_context_is_not_sent(client, session, acting_user, feedback_desk):
    sender = await acting_user()
    assert (await _send(client, sender)).status_code == 202

    await set_rls_context(session, SystemGuild(feedback_desk["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert "Where the app was" not in task.description
    await set_rls_context(session, Unattributed())


@pytest.mark.parametrize(
    "field,value",
    [
        ("route", "/c/12/i/[link](https://example.org)"),
        ("theme", "dark`"),
        ("locale", "en\n- injected"),
    ],
)
async def test_context_holds_only_names_and_route_templates(
    client, acting_user, feedback_desk, field, value
):
    sender = await acting_user()
    response = await _send(client, sender, context={field: value})
    assert response.status_code == 422, response.text


async def test_with_nothing_bound_sending_says_so(client, acting_user, operations):
    sender = await acting_user()
    response = await _send(client, sender)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == FeedbackMessages.NOWHERE_TO_SEND


async def test_it_takes_pictures_and_no_more_of_them_than_the_stream_allows(
    client, acting_user, feedback_desk
):
    sender = await acting_user()
    response = await client.post(
        TICKETS,
        data={
            "payload": json.dumps({"stream": "feedback", "type": "idea", "body": "x"})
        },
        files=[("files", (f"{n}.txt", b"words", "text/plain")) for n in range(4)],
        headers=sender.headers,
    )
    assert response.status_code == 400, response.text


@pytest.mark.always
@pytest.mark.parametrize("messages", [FeedbackMessages, AppealMessages])
async def test_every_error_code_is_localized(messages):
    from pathlib import Path

    codes = {
        value
        for name, value in vars(messages).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    locales = Path(__file__).resolve().parents[4].parent / "frontend/public/locales"
    for locale in ("de", "en", "es", "fr"):
        catalogue = json.loads((locales / locale / "errors.json").read_text())
        missing = sorted(codes - set(catalogue))
        assert not missing, f"{locale}/errors.json is missing {missing}"
