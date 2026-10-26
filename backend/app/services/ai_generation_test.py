"""AI work on a task or a file, on the connection the community resolves to.

The request path itself (each shape, the pinned egress, the errors) is
``ai_provider_test``; this covers what generation asks for and what it makes
of the answer.
"""

import json
from unittest.mock import patch

import httpx
import pytest

from app.core.messages import AIMessages
from app.schemas.ai_settings import AIProvider, ConnectionScope, ResolvedAISettings
from app.services import ai_generation, ai_provider, safe_http
from app.services.ai_context import TaskContext
from app.services.ai_provider import AIRequestError


class _Task:
    def __init__(self, title: str = "Ship it", description: str = "Do the thing"):
        self.title = title
        self.description = description


class _User:
    locale = "en"


def _resolving_to(monkeypatch, **overrides) -> list[tuple]:
    """Resolve to one connection, and keep what is written of its health."""
    resolved = ResolvedAISettings(
        **{
            "enabled": True,
            "provider": AIProvider.groq,
            "api_key": "test-key",
            "model": "m",
            "scope": ConnectionScope.community,
            "connection_id": 3,
            "source": "community",
            **overrides,
        }
    )
    health: list[tuple] = []

    async def resolve(*args, **kwargs):
        return resolved

    async def record_health(*args):
        health.append(args)

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", resolve)
    monkeypatch.setattr(ai_generation, "record_health", record_health)
    return health


async def test_a_checklist_is_asked_for_as_json_and_tidied(monkeypatch):
    sent: list[dict] = []
    answer = {"items": [" Book the hall ", "", "x" * 300]}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(answer)},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        ai_provider,
        "PinnedTransport",
        lambda *, allow_private, max_bytes: safe_http.PinnedTransport(
            allow_private=allow_private,
            max_bytes=max_bytes,
            inner=httpx.MockTransport(handler),
        ),
    )
    health = _resolving_to(monkeypatch)
    context = TaskContext('{"task":{"title":"Ship it"}}', 2, 5)

    async def read_task(*args, **kwargs):
        return context

    monkeypatch.setattr(ai_generation, "task_context", read_task)

    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=[(2, 0, 0, "", ("93.184.216.34", 0))],
    ):
        steps, told = await ai_generation.generate_checklist(None, _User(), 1, _Task())

    assert steps[0] == "Book the hall"
    assert len(steps) == 2 and steps[1].endswith("...")
    assert told is context
    system, data = (m["content"] for m in sent[0]["messages"])
    assert '{"items":' in system
    # The instructions come first and stay the same; the task follows them.
    assert data == f"<context>{context.data}</context>"
    # The connection answered, so it is well.
    assert health == [(ConnectionScope.community, 3, 1, None)]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"enabled": False, "provider": None}, AIMessages.NOT_ENABLED),
        ({"enabled": False, "api_key": None}, AIMessages.NOT_CONFIGURED),
    ],
)
async def test_a_connection_that_cannot_answer_says_why(monkeypatch, overrides, code):
    _resolving_to(monkeypatch, **overrides)
    with pytest.raises(AIRequestError) as refused:
        await ai_generation.generate_description(None, _User(), 1, _Task())
    assert refused.value.code == code


def _streaming(monkeypatch, *pieces: str, then: str | None = None) -> list[tuple]:
    """Answer with ``pieces`` as they are written, then fail with ``then``;
    keep the prompts asked."""
    asked: list[tuple] = []

    async def stream_text(target, job, prompt, *, guild_id):
        asked.append(prompt)
        for piece in pieces:
            yield piece
        if then:
            raise AIRequestError(then)

    monkeypatch.setattr(ai_provider, "stream_text", stream_text)
    return asked


async def _summary(monkeypatch, markdown: str) -> list[dict]:
    monkeypatch.setattr(ai_generation, "editor_markdown", lambda *a, **k: markdown)
    lines = await ai_generation.summarize(
        None, _User(), 1, title="Notes", content={"root": {}}
    )
    return [json.loads(line) async for line in lines]


async def test_a_summary_streams_as_it_is_written(monkeypatch):
    health = _resolving_to(monkeypatch)
    asked = _streaming(monkeypatch, "A ", "summary")

    assert await _summary(monkeypatch, "The rota") == [
        {"text": "A "},
        {"text": "summary"},
    ]
    assert "The rota" in asked[0][1]
    assert health == [(ConnectionScope.community, 3, 1, None)]


async def test_a_long_document_is_summarized_as_far_as_it_fits(monkeypatch):
    _resolving_to(monkeypatch)
    asked = _streaming(monkeypatch, "Short")
    monkeypatch.setattr(ai_generation, "_SUMMARY_BUDGET", 10)

    lines = await _summary(monkeypatch, "a" * 30 + "\n\n" + "b" * 50)

    # It ends where the first paragraph does, a third of the way in.
    assert lines == [{"cut": {"percent": 36}}, {"text": "Short"}]
    system, data = asked[0]
    assert "Only the beginning" in system
    assert "b" not in data.split("<content>")[1]


async def test_a_failure_says_why_before_or_part_way(monkeypatch):
    health = _resolving_to(monkeypatch)

    _streaming(monkeypatch, then=AIMessages.RATE_LIMITED)
    with pytest.raises(AIRequestError) as refused:
        await _summary(monkeypatch, "The rota")
    assert refused.value.code == AIMessages.RATE_LIMITED

    # Once text has gone out, the lines end with the code instead.
    _streaming(monkeypatch, "A ", then=AIMessages.RATE_LIMITED)
    assert await _summary(monkeypatch, "The rota") == [
        {"text": "A "},
        {"error": AIMessages.RATE_LIMITED},
    ]
    assert [code for *_, code in health] == [AIMessages.RATE_LIMITED] * 2


async def test_an_empty_document_is_not_sent(monkeypatch):
    _resolving_to(monkeypatch)
    with pytest.raises(AIRequestError) as refused:
        await _summary(monkeypatch, "  ")
    assert refused.value.code == AIMessages.DOCUMENT_EMPTY
