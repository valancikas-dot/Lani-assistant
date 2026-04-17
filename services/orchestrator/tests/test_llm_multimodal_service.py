from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm_multimodal_service import complete_multimodal_text


class _FakeOpenAIClient:
    def __init__(self, response: object) -> None:
        self._response = response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_: object) -> object:
        return self._response


@pytest.mark.asyncio
async def test_complete_multimodal_text_returns_text(monkeypatch) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=" Vision result "))],
        usage=None,
    )
    fake_openai = SimpleNamespace(AsyncOpenAI=lambda api_key: _FakeOpenAIClient(response))
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_openai)

    result = await complete_multimodal_text(
        openai_api_key="key",
        model="gpt-test",
        messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
    )

    assert result == "Vision result"


@pytest.mark.asyncio
async def test_complete_multimodal_text_raises_without_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        await complete_multimodal_text(
            openai_api_key="",
            model="gpt-test",
            messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        )