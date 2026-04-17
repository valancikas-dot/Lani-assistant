from __future__ import annotations

from typing import Any, Optional, cast

from app.services.llm_response_utils import extract_openai_message_text
from app.services.llm_text_service import _openai_token_param


async def complete_multimodal_text(
    *,
    openai_api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    temperature: Optional[float] = None,
    tracking_operation: Optional[str] = None,
) -> str:
    """Return plain text from an OpenAI multimodal chat completion."""
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    import openai

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": cast(Any, messages),
        **_openai_token_param(model, max_tokens),
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    response = await client.chat.completions.create(**kwargs)
    _record_openai_usage(resp=response, model=model, operation=tracking_operation)
    return extract_openai_message_text(response)


def _record_openai_usage(*, resp: Any, model: str, operation: Optional[str]) -> None:
    if not operation:
        return

    try:
        from app.services.token_tracker import record_usage

        usage = getattr(resp, "usage", None)
        if usage:
            record_usage(model, usage.prompt_tokens, usage.completion_tokens, operation=operation)
    except Exception:
        pass