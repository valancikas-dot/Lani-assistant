from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm_text_service import complete_text


class _FakeOpenAIClient:
    def __init__(self, response: object) -> None:
        self._response = response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_: object) -> object:
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: object) -> None:
        self.messages = SimpleNamespace(create=self._create)
        self._response = response

    async def _create(self, **_: object) -> object:
        return self._response


@pytest.mark.asyncio
async def test_complete_text_returns_openai_text(monkeypatch) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=" OpenAI text "))],
        usage=None,
    )

    import app.services.llm_text_service as svc

    fake_openai_module = SimpleNamespace(AsyncOpenAI=lambda api_key: _FakeOpenAIClient(response))
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_openai_module)

    result = await complete_text(
        openai_api_key="key",
        openai_model="gpt-test",
        openai_messages=[{"role": "user", "content": "hello"}],
    )

    assert result == "OpenAI text"


@pytest.mark.asyncio
async def test_complete_text_falls_back_to_anthropic(monkeypatch) -> None:
    import app.services.llm_text_service as svc

    async def _raise(**_: object) -> object:
        raise RuntimeError("openai down")

    failing_openai = SimpleNamespace(
        AsyncOpenAI=lambda api_key: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_raise))
        )
    )
    anthropic_response = SimpleNamespace(content=[SimpleNamespace(text=" Anthropic fallback ")], usage=None)
    fake_anthropic = SimpleNamespace(AsyncAnthropic=lambda api_key: _FakeAnthropicClient(anthropic_response))

    monkeypatch.setitem(__import__("sys").modules, "openai", failing_openai)
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    result = await complete_text(
        openai_api_key="key",
        anthropic_api_key="anthropic-key",
        openai_model="gpt-test",
        openai_messages=[{"role": "user", "content": "hello"}],
        anthropic_messages=[{"role": "user", "content": "hello"}],
    )

    assert result == "Anthropic fallback"


@pytest.mark.asyncio
async def test_complete_text_raises_without_configured_provider() -> None:
    with pytest.raises(RuntimeError, match="No LLM provider configured"):
        await complete_text(
            openai_api_key="",
            anthropic_api_key="",
            openai_model="gpt-test",
            openai_messages=[{"role": "user", "content": "hello"}],
        )