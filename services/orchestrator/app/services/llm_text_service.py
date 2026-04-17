from __future__ import annotations

import importlib
from typing import Any, Optional, cast

from app.services.llm_response_utils import extract_anthropic_text, extract_openai_message_text


def _openai_token_param(model: str, n: int) -> dict[str, int]:
    """Return the correct token-limit kwarg for the given OpenAI model.

    Reasoning models (o1, o3, o3-mini, o4-mini …) require
    ``max_completion_tokens``; all other models use ``max_tokens``.
    """
    reasoning_prefixes = ("o1", "o3", "o4")
    base = model.split("/")[-1].lower()  # handle org/model style
    if any(base.startswith(p) for p in reasoning_prefixes):
        return {"max_completion_tokens": n}
    return {"max_tokens": n}


async def complete_text(
    *,
    openai_api_key: str,
    anthropic_api_key: str = "",
    openai_model: str,
    anthropic_model: Optional[str] = None,
    openai_messages: list[dict[str, Any]],
    anthropic_messages: Optional[list[dict[str, Any]]] = None,
    system_prompt: str = "",
    max_tokens: int = 1024,
    temperature: Optional[float] = None,
    provider_preference: str = "openai_first",
    tracking_operation: Optional[str] = None,
) -> str:
    """Return a text completion using OpenAI and/or Anthropic with simple fallback."""

    if provider_preference == "anthropic_first":
        providers = ("anthropic", "openai")
    else:
        providers = ("openai", "anthropic")

    last_error: Exception | None = None

    for provider in providers:
        try:
            if provider == "openai" and openai_api_key:
                import openai

                client = openai.AsyncOpenAI(api_key=openai_api_key)
                kwargs: dict[str, Any] = {
                    "model": openai_model,
                    "messages": cast(Any, openai_messages),
                    **_openai_token_param(openai_model, max_tokens),
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature

                resp = await client.chat.completions.create(**kwargs)
                _record_openai_usage(resp=resp, model=openai_model, operation=tracking_operation)
                return extract_openai_message_text(resp)

            if provider == "anthropic" and anthropic_api_key:
                anthropic_mod = importlib.import_module("anthropic")
                client = anthropic_mod.AsyncAnthropic(api_key=anthropic_api_key)
                kwargs: dict[str, Any] = {
                    "model": anthropic_model or openai_model,
                    "max_tokens": max_tokens,
                    "messages": cast(Any, anthropic_messages or openai_messages),
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                resp = await client.messages.create(**kwargs)
                _record_anthropic_usage(resp=resp, model=openai_model, operation=tracking_operation)
                return extract_anthropic_text(resp)
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("No LLM provider configured.")


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


def _record_anthropic_usage(*, resp: Any, model: str, operation: Optional[str]) -> None:
    if not operation:
        return

    try:
        from app.services.token_tracker import record_usage

        usage = getattr(resp, "usage", None)
        if usage:
            record_usage(
                model,
                getattr(usage, "input_tokens", 0),
                getattr(usage, "output_tokens", 0),
                operation=operation,
            )
    except Exception:
        pass