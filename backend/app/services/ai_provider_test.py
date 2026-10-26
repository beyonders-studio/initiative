"""The provider layer: each request shape through its SDK, the pinned egress,
the reading of a reply, and the mapping of what went wrong.

Requests go through the real SDK clients and, for the OpenAI client, the real
pinning transport; only the transport that would open a socket is replaced,
and DNS answers with a public address.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict

from app.core.messages import AIMessages
from app.schemas.ai_settings import AIProvider
from app.services import ai_provider, safe_http
from app.services.ai_provider import AIRequestError, Job, Target

JOB = Job(purpose="test", max_tokens=1000, timeout=5.0)
PROMPT = ("Be brief.", "<task>Ship it</task>")
PUBLIC_IP = "93.184.216.34"


class _Steps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str]


def _resolves_to(ip: str):
    return patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=[(2, 0, 0, "", (ip, 0))],
    )


def _usage(input_tokens: int = 10, output_tokens: int = 5) -> dict:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _anthropic_reply(text: str) -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "m",
        # A model that thinks first answers with a thinking block before the text.
        "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": text},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {**_usage(), "cache_read_input_tokens": 2},
    }


def _responses_reply(text: str) -> dict:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "m",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            **_usage(),
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 2},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _chat_reply(text: str) -> dict:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _sse(*events: dict, done: bool = False) -> str:
    """A streamed answer, as server-sent events."""
    lines = [
        (f"event: {event['type']}\n" if "type" in event else "")
        + f"data: {json.dumps(event)}\n\n"
        for event in events
    ]
    return "".join(lines) + ("data: [DONE]\n\n" if done else "")


def _anthropic_stream(*pieces: str) -> str:
    message = {**_anthropic_reply(""), "content": [], "stop_reason": None}
    message["usage"] = {**_usage(output_tokens=1), "cache_read_input_tokens": 2}
    return _sse(
        {"type": "message_start", "message": message},
        # A model that thinks first streams its thinking apart from the text.
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "text", "text": ""},
        },
        *(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": piece},
            }
            for piece in pieces
        ),
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    )


def _responses_stream(*pieces: str) -> str:
    return _sse(
        *(
            {
                "type": "response.output_text.delta",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": piece,
                "logprobs": [],
                "sequence_number": number,
            }
            for number, piece in enumerate(pieces)
        ),
        {
            "type": "response.completed",
            "sequence_number": len(pieces),
            "response": _responses_reply("".join(pieces)),
        },
    )


def _chat_stream(*pieces: str) -> str:
    chunk = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "m"}
    return _sse(
        *(
            {
                **chunk,
                "choices": [
                    {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                ],
            }
            for piece in pieces
        ),
        # The counts come on a last chunk of their own.
        {**chunk, "choices": [], "usage": _chat_reply("")["usage"]},
        done=True,
    )


class _Provider:
    """Answers every request with ``reply(body)``, or with ``status`` and
    ``error``, and keeps what was sent."""

    def __init__(self, monkeypatch, reply, status: int = 200, error=None):
        self.sent: list = []
        self.reply = reply
        self.status = status
        self.error = error or {}
        _openai_answers(monkeypatch, self._answer(httpx))
        real = anthropic.AsyncAnthropic

        def _anthropic(**kwargs):
            transport = httpx2.MockTransport(self._answer(httpx2))
            return real(**kwargs, http_client=httpx2.AsyncClient(transport=transport))

        monkeypatch.setattr(ai_provider.anthropic, "AsyncAnthropic", _anthropic)

    def _answer(self, lib):
        def handler(request):
            body = json.loads(request.content) if request.content else {}
            self.sent.append((request, body))
            if self.status != 200:
                # A refusal is answered once: the SDK would otherwise wait out
                # its backoff before retrying it.
                return lib.Response(
                    self.status, json=self.error, headers={"x-should-retry": "false"}
                )
            reply = self.reply(body)
            if isinstance(reply, str):
                return lib.Response(
                    200, text=reply, headers={"content-type": "text/event-stream"}
                )
            return lib.Response(200, json=reply)

        return handler


def _openai_answers(monkeypatch, handler) -> None:
    """The OpenAI client's pinned transport, with ``handler`` where the
    socket would be."""
    monkeypatch.setattr(
        ai_provider,
        "PinnedTransport",
        lambda *, allow_private, max_bytes: safe_http.PinnedTransport(
            allow_private=allow_private,
            max_bytes=max_bytes,
            inner=httpx.MockTransport(handler),
        ),
    )


def _target(provider: AIProvider, **overrides) -> Target:
    return Target(
        **{
            "provider": provider,
            "model": "m",
            "api_key": "test-key",
            "base_url": None,
            "allow_private": False,
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("provider", "base_url", "sent_to", "auth", "reply"),
    [
        (
            AIProvider.anthropic,
            None,
            "https://api.anthropic.com/v1/messages",
            ("x-api-key", "test-key"),
            _anthropic_reply,
        ),
        (
            AIProvider.openai,
            None,
            "https://api.openai.com/v1/responses",
            ("authorization", "Bearer test-key"),
            _responses_reply,
        ),
        (
            AIProvider.groq,
            None,
            "https://api.groq.com/openai/v1/chat/completions",
            ("authorization", "Bearer test-key"),
            _chat_reply,
        ),
        (
            AIProvider.ollama,
            "https://ollama.example.com:11434/",
            "https://ollama.example.com:11434/v1/chat/completions",
            ("authorization", "Bearer test-key"),
            _chat_reply,
        ),
    ],
)
async def test_each_shape_through_its_sdk(
    monkeypatch, caplog, provider, base_url, sent_to, auth, reply
):
    """A request goes where its preset (or the connection) says, with the key,
    the model and no sampling settings; the text is read from where that shape
    puts it, past any thinking; the usage is logged once; and a refused key
    reads as a bad key."""
    fake = _Provider(monkeypatch, reply=lambda body: reply(" generated text "))
    target = _target(provider, base_url=base_url)

    with (
        _resolves_to(PUBLIC_IP),
        caplog.at_level(logging.INFO, logger="app.services.ai_provider"),
    ):
        text = await ai_provider.complete_text(target, JOB, PROMPT, guild_id=7)

    assert text == "generated text"
    request, body = fake.sent[0]
    host = request.headers["host"]
    assert f"{request.url.scheme}://{host}{request.url.path}" == sent_to
    assert request.headers[auth[0]] == auth[1]
    assert body["model"] == "m"
    assert "temperature" not in body
    [line] = [r.getMessage() for r in caplog.records if "AI usage" in r.getMessage()]
    assert "community=7" in line and "purpose=test" in line
    assert "input=10 output=5" in line

    fake.status = 401
    with _resolves_to(PUBLIC_IP), pytest.raises(AIRequestError) as refused:
        await ai_provider.complete_text(target, JOB, PROMPT, guild_id=7)
    assert refused.value.code == AIMessages.INVALID_API_KEY


@pytest.mark.parametrize(
    ("provider", "stream"),
    [
        (AIProvider.anthropic, _anthropic_stream),
        (AIProvider.openai, _responses_stream),
        (AIProvider.groq, _chat_stream),
    ],
)
async def test_each_shape_streams_its_answer(monkeypatch, caplog, provider, stream):
    """The text comes as it is written, past any thinking; the usage is logged
    once it ends; and the community's request is let go."""
    fake = _Provider(monkeypatch, reply=lambda body: stream("Hello", " there"))

    with (
        _resolves_to(PUBLIC_IP),
        caplog.at_level(logging.INFO, logger="app.services.ai_provider"),
    ):
        pieces = [
            piece
            async for piece in ai_provider.stream_text(
                _target(provider), JOB, PROMPT, guild_id=7
            )
        ]

    assert pieces == ["Hello", " there"]
    assert fake.sent[0][1]["stream"] is True
    [line] = [r.getMessage() for r in caplog.records if "AI usage" in r.getMessage()]
    assert "input=10 output=5" in line
    assert ai_provider._in_flight == {}


async def test_the_openai_client_connects_to_the_validated_address(monkeypatch):
    fake = _Provider(monkeypatch, reply=lambda body: _chat_reply("ok"))
    with _resolves_to(PUBLIC_IP):
        await ai_provider.complete_text(
            _target(AIProvider.gemini), JOB, PROMPT, guild_id=None
        )
    request, _ = fake.sent[0]
    assert request.url.host == PUBLIC_IP
    assert request.headers["host"] == "generativelanguage.googleapis.com"
    assert request.extensions["sni_hostname"] == "generativelanguage.googleapis.com"


async def test_a_private_address_is_reached_only_when_allowed(monkeypatch):
    fake = _Provider(monkeypatch, reply=lambda body: _chat_reply("ok"))
    target = _target(AIProvider.custom, base_url="http://10.0.0.5/v1")

    with pytest.raises(AIRequestError) as refused:
        await ai_provider.complete_text(target, JOB, PROMPT, guild_id=None)
    assert refused.value.code == AIMessages.INVALID_BASE_URL
    assert fake.sent == []

    allowed = _target(
        AIProvider.custom, base_url="http://10.0.0.5/v1", allow_private=True
    )
    assert await ai_provider.complete_text(allowed, JOB, PROMPT, guild_id=None) == "ok"
    assert fake.sent[0][0].url.host == "10.0.0.5"

    # The operator's Ollama with no address is the one beside the server.
    local = _target(AIProvider.ollama, api_key=None, allow_private=True)
    with _resolves_to("127.0.0.1"):
        await ai_provider.complete_text(local, JOB, PROMPT, guild_id=None)
    request = fake.sent[1][0]
    assert request.headers["host"] == "localhost:11434"
    assert request.url.path == "/v1/chat/completions"


def test_only_the_operators_own_servers_reach_private_addresses():
    for provider in (AIProvider.ollama, AIProvider.custom):
        assert ai_provider.allow_private(provider, "platform") is True
        assert ai_provider.allow_private(provider, "community") is False
    for provider in (AIProvider.openai, AIProvider.anthropic, AIProvider.openrouter):
        assert ai_provider.allow_private(provider, "platform") is False


async def test_a_connection_without_its_key_or_model_sends_nothing(monkeypatch):
    fake = _Provider(monkeypatch, reply=lambda body: _anthropic_reply("x"))
    for target, code in (
        (_target(AIProvider.anthropic, api_key=None), AIMessages.NOT_CONFIGURED),
        (_target(AIProvider.anthropic, model=None), AIMessages.MODEL_REQUIRED),
    ):
        with pytest.raises(AIRequestError) as refused:
            await ai_provider.complete_text(target, JOB, PROMPT, guild_id=None)
        assert refused.value.code == code
    assert fake.sent == []


async def test_a_json_answer_takes_the_schema_where_the_provider_does(monkeypatch):
    """The schema goes to a provider that takes one, and an answer is read
    past any words around it."""
    fake = _Provider(
        monkeypatch,
        reply=lambda body: _anthropic_reply('Here: {"items": ["a", "b"]} done'),
    )
    with _resolves_to(PUBLIC_IP):
        steps = await ai_provider.complete_json(
            _target(AIProvider.anthropic), JOB, PROMPT, _Steps, guild_id=None
        )
    assert steps.items == ["a", "b"]
    _, body = fake.sent[0]
    assert body["output_config"]["format"]["type"] == "json_schema"


async def test_a_model_that_refuses_the_schema_is_asked_without_it(monkeypatch):
    def reply(body):
        return _responses_reply('{"items": ["a"]}')

    fake = _Provider(monkeypatch, reply=reply)
    first = True

    def answer(request):
        nonlocal first
        body = json.loads(request.content)
        fake.sent.append((request, body))
        if first:
            first = False
            return httpx.Response(400, json={"error": {"type": "invalid_request"}})
        return httpx.Response(200, json=reply(body))

    _openai_answers(monkeypatch, answer)
    with _resolves_to(PUBLIC_IP):
        steps = await ai_provider.complete_json(
            _target(AIProvider.openai), JOB, PROMPT, _Steps, guild_id=None
        )
    assert steps.items == ["a"]
    assert "text" in fake.sent[0][1]
    assert "text" not in fake.sent[1][1]


async def test_an_answer_that_does_not_fit_is_asked_for_once_more(monkeypatch):
    fake = _Provider(monkeypatch, reply=lambda body: _chat_reply("not json"))
    with _resolves_to(PUBLIC_IP), pytest.raises(AIRequestError) as failed:
        await ai_provider.complete_json(
            _target(AIProvider.groq), JOB, PROMPT, _Steps, guild_id=None
        )
    assert failed.value.code == AIMessages.PROVIDER_ERROR
    assert len(fake.sent) == 2


async def test_models_are_listed_by_name(monkeypatch, caplog):
    catalog = ["zeta", "alpha"]
    fake = _Provider(
        monkeypatch,
        reply=lambda body: {
            "data": [{"id": name, "object": "model"} for name in catalog],
            "object": "list",
        },
    )
    with _resolves_to(PUBLIC_IP):
        assert await ai_provider.list_models(_target(AIProvider.groq)) == [
            "alpha",
            "zeta",
        ]

    # A catalog past the cap is read only as far as the cap.
    catalog = [f"m-{i}" for i in range(ai_provider.MODEL_LIST_CAP + 5)]
    with _resolves_to(PUBLIC_IP):
        listed = await ai_provider.list_models(_target(AIProvider.groq))
    assert len(listed) == ai_provider.MODEL_LIST_CAP

    fake.status = 404
    fake.error = {
        "error": {
            "type": "not_found_error",
            "message": "Incorrect API key provided: sk-12...abcd",
        }
    }
    with (
        _resolves_to(PUBLIC_IP),
        caplog.at_level(logging.WARNING, logger="app.services.ai_provider"),
        pytest.raises(AIRequestError) as refused,
    ):
        await ai_provider.list_models(_target(AIProvider.groq))
    assert refused.value.code == AIMessages.MODEL_NOT_FOUND
    # The kind of error the provider named is logged; what it said is not.
    assert "404 not_found_error" in caplog.text
    assert "sk-12" not in caplog.text


async def test_a_community_at_its_limit_waits_and_others_do_not(monkeypatch):
    fake = _Provider(monkeypatch, reply=lambda body: _chat_reply("ok"))
    monkeypatch.setattr(ai_provider, "_in_flight", {7: ai_provider.CALLS_PER_COMMUNITY})

    with pytest.raises(AIRequestError) as busy:
        await ai_provider.complete_text(
            _target(AIProvider.groq), JOB, PROMPT, guild_id=7
        )
    assert (busy.value.code, busy.value.status_code) == (AIMessages.BUSY, 429)
    assert fake.sent == []

    with _resolves_to(PUBLIC_IP):
        await ai_provider.complete_text(
            _target(AIProvider.groq), JOB, PROMPT, guild_id=8
        )
    # A finished request gives its place back.
    assert ai_provider._in_flight == {7: ai_provider.CALLS_PER_COMMUNITY}


async def test_a_server_somebody_runs_is_asked_once_and_read_within_a_bound(
    monkeypatch,
):
    """It is not retried, and a reply past the bound is a provider error."""
    target = _target(AIProvider.custom, base_url="https://llm.example.com/v1")
    fake = _Provider(monkeypatch, reply=lambda body: _chat_reply("ok"), status=500)
    with _resolves_to(PUBLIC_IP), pytest.raises(AIRequestError) as failed:
        await ai_provider.complete_text(target, JOB, PROMPT, guild_id=None)
    assert failed.value.code == AIMessages.PROVIDER_ERROR
    assert len(fake.sent) == 1

    fake.status = 200
    fake.reply = lambda body: _chat_reply("x" * 2_000)
    monkeypatch.setattr(ai_provider, "MAX_REPLY_BYTES", 1_000)
    with _resolves_to(PUBLIC_IP), pytest.raises(AIRequestError) as too_long:
        await ai_provider.complete_text(target, JOB, PROMPT, guild_id=None)
    assert too_long.value.code == AIMessages.PROVIDER_ERROR


@pytest.mark.parametrize(
    ("provider", "status", "error", "code"),
    [
        # Anthropic: billing, a limit the account set, the tier's monthly cap.
        (
            AIProvider.anthropic,
            402,
            {"type": "error", "error": {"type": "billing_error", "message": "x"}},
            AIMessages.OUT_OF_CREDIT,
        ),
        (
            AIProvider.anthropic,
            400,
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "You have reached your specified workspace API usage "
                    "limits. You will regain access on 2026-11-01 at 00:00 UTC.",
                },
            },
            AIMessages.SPEND_LIMIT_REACHED,
        ),
        (
            AIProvider.anthropic,
            429,
            {
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": "x",
                    "details": {"error_code": "enforced_spend_limit_reached"},
                },
            },
            AIMessages.SPEND_LIMIT_REACHED,
        ),
        (
            AIProvider.anthropic,
            429,
            {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}},
            AIMessages.RATE_LIMITED,
        ),
        # OpenAI names an exhausted balance.
        (
            AIProvider.openai,
            429,
            {
                "error": {
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                    "message": "x",
                }
            },
            AIMessages.OUT_OF_CREDIT,
        ),
        (
            AIProvider.groq,
            400,
            {"error": {"type": "invalid_request_error", "message": "x"}},
            AIMessages.PROVIDER_ERROR,
        ),
    ],
)
async def test_what_the_account_needs_is_named(
    monkeypatch, provider, status, error, code
):
    """A refusal the owner can act on at the provider says which; one that is
    not documented as such is a provider error."""
    _Provider(monkeypatch, reply=lambda body: {}, status=status, error=error)
    with _resolves_to(PUBLIC_IP), pytest.raises(AIRequestError) as refused:
        await ai_provider.complete_text(_target(provider), JOB, PROMPT, guild_id=None)
    assert refused.value.code == code
    assert code in ai_provider.PROVIDER_CODES
