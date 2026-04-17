from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm_tool_calling_service import create_tool_choice


class _FakeOpenAIClient:
    def __init__(self, response: object) -> None:
        self._response = response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_: object) -> object:
        return self._response


@pytest.mark.asyncio
async def test_create_tool_choice_returns_response(monkeypatch) -> None:
    response = SimpleNamespace(id="resp_123")
    fake_openai = SimpleNamespace(AsyncOpenAI=lambda api_key: _FakeOpenAIClient(response))
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_openai)

    result = await create_tool_choice(
        openai_api_key="key",
        model="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "test", "parameters": {"type": "object", "properties": {}}}}],
    )

    assert result is response


@pytest.mark.asyncio
async def test_create_tool_choice_raises_without_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        await create_tool_choice(
            openai_api_key="",
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )