"""Content leaving for an AI provider reaching the audit log.

The disclosure is the request, not the reply, so the record is written and
committed before the call goes out. What it carries is which thing was sent,
what it was sent for, and which connection carried it — never a word of the
text itself.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import AIMessages
from app.models.platform.guild import CommunityRole
from app.schemas.ai_settings import AIProvider, ConnectionScope, ResolvedAISettings
from app.services import ai_generation
from app.services.ai_context import TaskContext
from app.testing import (
    create_file,
    create_task,
    create_wiki,
    create_wiki_page,
    emitted,
)


CONNECTION_ID = 41


def _wire_ai(monkeypatch) -> None:
    """A resolved connection for the endpoint's own look at the settings."""
    resolved = ResolvedAISettings(
        enabled=True,
        provider=AIProvider.openai,
        api_key="sk-not-a-real-key",
        model="gpt-4o-mini",
        scope=ConnectionScope.platform,
        connection_id=CONNECTION_ID,
        source="platform",
    )

    async def _resolve(session, guild_id=None):
        return resolved

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", _resolve)


async def test_a_checklist_request_records_what_carried_it(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, capfd
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project, title="Ship it")
    _wire_ai(monkeypatch)

    async def _generate(*args, **kwargs):
        return ["Step one"], TaskContext("{}", 0, 0)

    monkeypatch.setattr(ai_generation, "generate_checklist", _generate)
    capfd.readouterr()

    response = await client.post(
        a.g(f"/tasks/{task.id}/ai/checklist"), headers=a.headers
    )
    assert response.status_code == 200, response.text

    (row,) = emitted(capfd, AuditEventType.AI_REQUEST_SENT)
    assert row["actor_user_id"] == a.user.id
    assert row["guild_id"] == a.guild.id
    assert row["target"] == {"type": "task", "id": task.id}
    assert row["detail"] == {
        "purpose": "checklist",
        "initiative_id": a.initiative.id,
        "scope": "platform",
        "connection_id": CONNECTION_ID,
        "provider": "openai",
    }
    assert "Ship it" not in json.dumps(row)


async def test_a_description_request_records_its_own_purpose(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, capfd
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    _wire_ai(monkeypatch)

    async def _generate(*args, **kwargs):
        return "A description", TaskContext("{}", 0, 0)

    monkeypatch.setattr(ai_generation, "generate_description", _generate)
    capfd.readouterr()

    response = await client.post(
        a.g(f"/tasks/{task.id}/ai/description"), headers=a.headers
    )
    assert response.status_code == 200, response.text

    (row,) = emitted(capfd, AuditEventType.AI_REQUEST_SENT)
    assert row["detail"]["purpose"] == "description"
    assert row["target"] == {"type": "task", "id": task.id}


@pytest.mark.parametrize("kind", ["file", "wiki_page"])
async def test_a_summary_records_the_document_it_sent(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, capfd, kind
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    if kind == "file":
        document = await create_file(session, a.initiative, a.user)
        path = f"/files/{document.id}/ai/summary"
    else:
        wiki = await create_wiki(session, a.initiative, a.user)
        document = await create_wiki_page(session, wiki, a.user)
        path = f"/wiki-pages/{document.id}/ai/summary"
    _wire_ai(monkeypatch)

    async def _summarize(*args, **kwargs):
        async def lines():
            yield '{"text":"A summary"}\n'

        return lines()

    monkeypatch.setattr(ai_generation, "summarize", _summarize)
    capfd.readouterr()

    response = await client.post(a.g(path), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/jsonl")
    assert response.text == '{"text":"A summary"}\n'

    (row,) = emitted(capfd, AuditEventType.AI_REQUEST_SENT)
    assert row["actor_user_id"] == a.user.id
    assert row["target"] == {"type": kind, "id": document.id}
    assert row["detail"]["purpose"] == "summary"
    assert row["detail"]["initiative_id"] == a.initiative.id


async def test_a_deployment_with_no_ai_sends_nothing_and_records_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    """Nothing left the deployment, so there is no disclosure to write down."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    capfd.readouterr()

    response = await client.post(
        a.g(f"/tasks/{task.id}/ai/checklist"), headers=a.headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == AIMessages.NOT_ENABLED

    assert emitted(capfd, AuditEventType.AI_REQUEST_SENT) == []
