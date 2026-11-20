"""Unit tests for the AI settings service (mode-based connections).

Covers the security-critical pure logic that needs no DB:
- A stored connection's ``base_url`` is validated public-only, except the
  operator's connection to a server somebody runs.
- A hosted service keeps no address of its own.
- The probe reads the provider's catalog (``ai_provider.list_models``).

End-to-end resolution, connection CRUD, and the exfil-impossible property are
covered by the endpoint integration tests.
"""

import pytest
from fastapi import HTTPException

from app.core.messages import AIMessages
from app.schemas.ai_settings import AIProvider
from app.services import ai_provider, ai_settings
from app.services.ai_settings import (
    _connection_base_url,
    _validate_connection_base_url,
)


@pytest.mark.parametrize(
    ("provider", "scope"),
    [
        (AIProvider.ollama, "community"),
        (AIProvider.custom, "community"),
        (AIProvider.openai, "platform"),
        (AIProvider.anthropic, "platform"),
        (AIProvider.openrouter, "platform"),
    ],
)
async def test_a_private_base_url_is_refused(provider, scope):
    """A community can never persist a private/internal target, and nor can
    anyone for a hosted service."""
    with pytest.raises(HTTPException) as exc:
        await _validate_connection_base_url(provider, "http://169.254.169.254", scope)
    assert exc.value.status_code == 400
    assert exc.value.detail == AIMessages.INVALID_BASE_URL


@pytest.mark.parametrize("provider", [AIProvider.ollama, AIProvider.custom])
async def test_the_operators_own_server_may_be_private(provider):
    await _validate_connection_base_url(provider, "http://10.0.0.1:11434", "platform")


def test_a_hosted_service_keeps_no_address_of_its_own():
    assert _connection_base_url(AIProvider.groq, "https://elsewhere.example") is None
    assert (
        _connection_base_url(AIProvider.custom, " https://llm.example/v1 ")
        == "https://llm.example/v1"
    )


def _custom_conn(model: str | None) -> ai_settings._ConnRow:
    return ai_settings._ConnRow(
        scope="community",
        id=1,
        label="OpenRouter",
        provider=AIProvider.custom.value,
        base_url="https://openrouter.test/api/v1",
        model=model,
        api_key_encrypted=None,
        has_key=False,
        enabled=True,
        is_default=True,
    )


def _stub_catalog(monkeypatch, count: int) -> None:
    async def list_models(target):
        return [f"vendor/model-{i}" for i in range(count)]

    monkeypatch.setattr(ai_provider, "list_models", list_models)


async def test_the_probe_checks_the_model_against_the_whole_catalog(monkeypatch):
    # Gateways like OpenRouter list hundreds of models; a model past the first
    # page is still found.
    _stub_catalog(monkeypatch, 400)
    found = await ai_settings._probe(_custom_conn("vendor/model-314"), "key")
    assert found.success is True

    missing = await ai_settings._probe(_custom_conn("vendor/nope"), "key")
    assert (missing.success, missing.message) == (False, AIMessages.MODEL_NOT_FOUND)

    unnamed = await ai_settings._probe(_custom_conn(None), "key")
    assert (unnamed.success, unnamed.message) == (False, AIMessages.MODEL_REQUIRED)
    assert unnamed.available_models and len(unnamed.available_models) == 400


async def test_the_probe_does_not_reject_against_a_truncated_catalog(monkeypatch):
    # At the cap the listing is known-incomplete, so absence proves nothing.
    _stub_catalog(monkeypatch, ai_provider.MODEL_LIST_CAP + 10)
    result = await ai_settings._probe(_custom_conn("vendor/unlisted"), "key")
    assert result.success is True
